"""The Content Images dock's surface: paints the packed rows from the layout table (#221).

A `QAbstractScrollArea` rather than a `QListView` in icon mode: the list view's native flow leaves the
right edge ragged and calls ``sizeHint()`` per item across the Python/C++ boundary, while the whole
point here is geometry computed once, in one pass (`pack_rows`), and painted from a table. The view
paints only the rows in the viewport, asks the `ThumbnailLoader` for exactly those thumbnails, and asks
the model for the headers of the rows one screen ahead so the pack settles before they scroll in.

Read-only, visibly so: no context menu, no drag. A single click **selects** one image (and a click on
the selected one clears it); a double-click selects it and opens it maximized; a click on a banner
collapses or expands the group under it. The path of the selected image -- or, with none selected, of the hovered
one -- is reported through :attr:`ContentImagesView.status_changed` for the dock's status line.
"""

from collections import Counter
from typing import Final, override

from borco_pyside.widgets.elided_label import ElidedLabel
from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QKeyEvent, QMouseEvent, QPainter, QPainterPath, QPaintEvent, QPalette, QResizeEvent
from PySide6.QtWidgets import QAbstractScrollArea, QFrame, QVBoxLayout, QWidget

from ...fields.widgets.image_strip import THUMBNAIL_BORDER
from ...fields.widgets.thumbnail_loader import ThumbnailLoader, thumbnail_cache_key
from .banners import ContentDisplayFlags, banner_rows, group_of
from .content_images_model import ArchiveImageSource, ContentImagesModel
from .justified_layout import LayoutItem, PackedLayout, Row, pack_rows

ITEM_SPACING: Final = 4
"""The gap between images in a row and between rows, in pixels."""

BANNER_HEIGHT: Final = 24
"""A banner row's height, in pixels -- one line of text with room around it."""

BANNER_INSET: Final = 6
"""How far in from the left edge a banner's text starts, in pixels."""

EXPANDED_MARK: Final = "-"
COLLAPSED_MARK: Final = "+"
"""What a banner is prefixed with: the mark says what a click on it does next."""

BANNER_MARK_WIDTH: Final = 14
"""The column the mark is centred in, in pixels. Fixed, and wider than either glyph: ``-`` is narrower
than ``+``, and a label that started right after the mark would shift sideways on every toggle."""

STATUS_LABEL_NAME: Final = "content_images_status"
"""The status line's object name."""

PLACEHOLDER_ALPHA: Final = 28
BROKEN_ALPHA: Final = 70
"""How faint the placeholders are: a pending thumbnail is a hint of the text colour, a member that
could not be decoded a stronger one, so a broken pack reads as broken rather than as still loading."""


def banner_label(key: str, count: int, *, collapsed: bool) -> str:
    """The text a banner row shows for group ``key``: its mark, the key, and how many images it holds.

    :param key: the group's key (`banner_text`).
    :param count: how many images the group holds.
    :param collapsed: whether the group is collapsed.
    :returns: e.g. ``- foo.zip [32]``.
    """
    return " ".join(banner_parts(key, count, collapsed=collapsed))


def banner_parts(key: str, count: int, *, collapsed: bool) -> tuple[str, str]:
    """`banner_label` in its two painted parts: the mark, and the key with its count.

    :param key: the group's key (`banner_text`).
    :param count: how many images the group holds.
    :param collapsed: whether the group is collapsed.
    :returns: e.g. ``("-", "foo.zip [32]")``.
    """
    return COLLAPSED_MARK if collapsed else EXPANDED_MARK, f"{key} [{count}]"


class ContentImagesView(QAbstractScrollArea):  # pylint: disable=too-many-instance-attributes,too-many-public-methods
    """A justified-row grid over a `ContentImagesModel`, painted from a precomputed table (#221).

    :param model: the entries and their dimensions.
    :param loader: the shared thumbnail decode pool.
    :param parent: optional Qt parent.
    :param min_height: the shortest flush row.
    :param max_height: the tallest flush row.
    :param flags: which boundaries are bannered; the defaults (zip names on, folder names off) when
        ``None``.
    """

    image_activated = Signal(int)
    """Fires with the position of the image the user double-clicked."""

    selection_changed = Signal(object)
    """Fires with the position of the newly selected image, or ``None`` once the selection is cleared."""

    status_changed = Signal(str)
    """Fires with what the dock's status line should say: the selected image's path, else the
    hovered one's, else nothing."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        model: ContentImagesModel,
        loader: ThumbnailLoader,
        parent: QWidget | None = None,
        *,
        min_height: int = 140,
        max_height: int = 260,
        flags: ContentDisplayFlags | None = None,
    ) -> None:
        super().__init__(parent)
        self.__model: Final = model
        self.__loader: Final = loader
        self.__min_height = min_height
        self.__max_height = max_height
        self.__flags = flags if flags is not None else ContentDisplayFlags()
        self.__layout: PackedLayout | None = None
        self.__source: ArchiveImageSource = model.source
        self.__groups: list[str | None] = []
        self.__counts: Counter[str] = Counter()
        self.__collapsed: set[str] = set()
        self.__reveal_banner: str | None = None
        self.__reveal_index: int | None = None
        self.__selected: int | None = None
        self.__hovered: int | None = None
        self.__swallow_release = False
        self.__previews_visible = True
        self.setFrameShape(QFrame.Shape.NoFrame)
        # focus on a click, for the keyboard navigation: the arrows move the selection, +/- fold the
        # current group, ESC clears the selection
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # the window's own background, not a text field's: this is a surface of images and labels,
        # and its status line below matches it
        self.viewport().setBackgroundRole(QPalette.ColorRole.Window)
        self.viewport().setAutoFillBackground(True)
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        self.viewport().setMouseTracking(True)
        # one pass per burst: a resize, a reset and a run of header reads each ask for a repack, and
        # a zero-delay single shot folds whatever arrives in one event-loop turn into one
        self.__repack_timer: Final = QTimer(self)
        self.__repack_timer.setSingleShot(True)
        self.__repack_timer.setInterval(0)
        self.__repack_timer.timeout.connect(self.__repack)
        model.modelReset.connect(self.__on_model_reset)
        model.dimensions_changed.connect(self.schedule_repack)
        loader.ready.connect(self.__on_thumbnail_ready)
        self.verticalScrollBar().valueChanged.connect(self.__on_scrolled)

    @property
    def layout_table(self) -> PackedLayout | None:
        """The current packing, or ``None`` before the first pass."""
        return self.__layout

    @property
    def source(self) -> ArchiveImageSource:
        """The image source over the current entries -- what a double-click opens the lightbox against."""
        return self.__source

    @property
    def flags(self) -> ContentDisplayFlags:
        """Which boundaries are bannered."""
        return self.__flags

    @property
    def clamp(self) -> tuple[int, int]:
        """The ``(min, max)`` flush row height."""
        return self.__min_height, self.__max_height

    @property
    def selected(self) -> int | None:
        """The selected image's position, or ``None``."""
        return self.__selected

    @property
    def collapsed(self) -> frozenset[str]:
        """The groups currently collapsed, by banner key."""
        return frozenset(self.__collapsed)

    def set_clamp(self, min_height: int, max_height: int) -> None:
        """Re-pack under a new row-height clamp -- the settings page's Apply.

        :param min_height: the shortest flush row.
        :param max_height: the tallest flush row.
        """
        if (min_height, max_height) == (self.__min_height, self.__max_height):
            return
        self.__min_height, self.__max_height = min_height, max_height
        self.schedule_repack()

    def set_flags(self, flags: ContentDisplayFlags) -> None:
        """Re-pack under new banner choices -- the settings page's Apply.

        The groups change with the boxes, so what was collapsed under the old ones no longer names
        anything; every group opens.

        :param flags: which boundaries are bannered.
        """
        if flags == self.__flags:
            return
        self.__flags = flags
        self.__collapsed.clear()
        self.__reveal_banner = None
        self.__reveal_index = None
        self.schedule_repack()

    def set_collapsed(self, key: str, collapsed: bool) -> None:
        """Collapse or expand the group under banner ``key`` -- what a click on the banner does.

        A selected image inside a group being collapsed is deselected: it is no longer on screen to
        be the selection. A group collapsed from inside it (its banner pinned, its own row scrolled
        off) is scrolled back to its banner once re-packed: the rows that vanished were the ones on
        screen, and without that the viewport would land somewhere in the middle of the next group.

        :param key: the group's banner key.
        :param collapsed: whether to collapse it.
        """
        if collapsed == (key in self.__collapsed):
            return
        if collapsed:
            self.__collapsed.add(key)
            self.__reveal_banner = key
            if self.__selected is not None and self.__groups[self.__selected] == key:
                self.set_selected(None)
        else:
            self.__collapsed.discard(key)
        self.schedule_repack()

    @property
    def previews_visible(self) -> bool:
        """Whether the images are shown at all -- the app-wide previews toggle's state (#71)."""
        return self.__previews_visible

    def set_previews_visible(self, visible: bool) -> None:
        """Show the images, or only the banners -- the app-wide previews toggle (``Ctrl+Shift+``,
        backtick, #71), which clears every image off screen and reaches this grid like every
        document's strip, whose thumbnails go the same way. The banners stay, so the resource's
        archives and folders are still legible; every image row is packed away as a collapsed
        group's are.

        :param visible: whether the images are shown.
        """
        if visible == self.__previews_visible:
            return
        self.__previews_visible = visible
        self.schedule_repack()

    def reveal(self, index: int) -> None:
        """Select the image at ``index`` and bring it into view, expanding its group if that is
        collapsed -- what the viewer's close does with the image it was on (#221).

        The scroll lands once the next pack has run, since an expansion moves every row below it; an
        index outside the source is ignored.

        :param index: the position to reveal.
        """
        if not 0 <= index < len(self.__source):
            return
        group = self.__groups[index] if index < len(self.__groups) else None
        if group is not None and group in self.__collapsed:
            self.__collapsed.discard(group)
        self.set_selected(index)
        self.__reveal_index = index
        self.schedule_repack()

    def set_selected(self, index: int | None) -> None:
        """Select the image at ``index``, or clear the selection with ``None``.

        :param index: the position, or ``None``.
        """
        if index == self.__selected:
            return
        self.__selected = index
        self.selection_changed.emit(index)
        self.__report_status()
        self.viewport().update()

    def schedule_repack(self) -> None:
        """Run the packing pass on the next event-loop turn, once for however many asks arrive."""
        self.__repack_timer.start()

    def index_at(self, point: QPoint) -> int | None:
        """The image under ``point`` (viewport coordinates), if any.

        :param point: the viewport position.
        :returns: the position in the source, or ``None`` over a gap, a banner (the pinned one
            included: it covers whatever row scrolled under it) or nothing.
        """
        if self.__layout is None:
            return None
        if 0 <= point.y() < BANNER_HEIGHT and self.pinned_banner() is not None:
            return None
        y = point.y() + self.verticalScrollBar().value()
        for row in self.__layout.rows_between(y, y + 1):
            if row.banner is not None:
                continue
            for index in range(row.first, row.last + 1):
                if QRect(*self.__layout.rects[index]).contains(point.x(), y):
                    return index
        return None

    def banner_at(self, point: QPoint) -> str | None:
        """The banner under ``point`` (viewport coordinates), if any -- the pinned one first.

        :param point: the viewport position.
        :returns: the group's key, or ``None`` when the point is not on a banner row.
        """
        if self.__layout is None:
            return None
        pinned = self.pinned_banner()
        if pinned is not None and 0 <= point.y() < BANNER_HEIGHT:
            return pinned
        y = point.y() + self.verticalScrollBar().value()
        for row in self.__layout.rows_between(y, y + 1):
            if row.banner is not None and row.y <= y < row.y + row.height:
                return row.banner
        return None

    def pinned_banner(self) -> str | None:
        """The group whose banner is pinned to the top of the viewport: the group of the first image
        row on screen, once its own banner row has scrolled above the top.

        What lets a group be collapsed from anywhere inside it -- a folder of hundreds of images would
        otherwise need scrolling back to its banner.

        :returns: the group's key, or ``None`` while the top of the viewport shows a banner row of its
            own or nothing is scrolled off.
        """
        layout = self.__layout
        if layout is None:
            return None
        offset = self.verticalScrollBar().value()
        group: str | None = None
        for row in layout.rows_between(offset, offset + 1):
            if row.banner is not None:
                # the top of the viewport is a banner row itself: nothing to pin over it
                return None
            group = self.__groups[row.first]
        return group if group is not None and offset > 0 else None

    def banner_label(self, key: str) -> str:
        """What the banner of group ``key`` reads right now.

        :param key: the group's key.
        :returns: the label, mark and count included.
        """
        return banner_label(key, self.__counts.get(key, 0), collapsed=key in self.__collapsed)

    def status_text(self) -> str:
        """What the dock's status line says: the selected image's path, else the hovered one's, else
        nothing."""
        index = self.__selected if self.__selected is not None else self.__hovered
        if index is None or index >= len(self.__source):
            return ""
        return self.__source.describe(index).path_text

    @override
    def resizeEvent(self, event: QResizeEvent) -> None:
        """Re-pack to the new size -- keeping the selected image on screen if it was, which the pack
        itself does, except that it must be judged against the viewport **as it was**: a dock made
        shorter has just pushed a cell at its old bottom edge out of the new viewport, and that cell
        is exactly the one to keep. A selection the user has scrolled away from stays away.

        :param event: the Qt resize event, forwarded to the base class.
        """
        super().resizeEvent(event)
        shrink = event.oldSize().height() - event.size().height() if event.oldSize().isValid() else 0
        # a selection is only ever made into the current table (a reset clears it as it drops the
        # table), so it always has a rect to judge
        if (
            self.__selected is not None
            and self.__layout is not None
            and self.__is_in_view(self.__layout, self.__selected, self.viewport().height() + shrink)
        ):
            self.__reveal_index = self.__selected
        self.schedule_repack()

    def __is_in_view(self, layout: PackedLayout, index: int, viewport_height: int) -> bool:
        """Whether ``index``'s cell intersects a viewport ``viewport_height`` tall at the current
        scroll offset, under ``layout``.

        :param layout: the table to read the cell from.
        :param index: the position.
        :param viewport_height: the viewport's height to judge against.
        :returns: ``False`` for a hidden cell.
        """
        _, top, _, height = layout.rects[index]
        offset = self.verticalScrollBar().value()
        return height > 0 and top < offset + viewport_height and top + height > offset

    @override
    def paintEvent(self, event: QPaintEvent) -> None:
        """Paint the rows in the viewport from the table, requesting what they need.

        :param event: the Qt paint event; the whole viewport is painted either way.
        """
        del event
        layout = self.__layout
        if layout is None:
            return
        painter = QPainter(self.viewport())
        # a thumbnail is decoded for this screen's ratio and painted one device pixel per pixel; the
        # hint covers the rare cell it does not match exactly, so that resample is not nearest-neighbour
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        offset = self.verticalScrollBar().value()
        viewport_height = self.viewport().height()
        wanted: list[str] = []
        visible: list[int] = []
        for row in layout.rows_between(offset, offset + viewport_height):
            if row.banner is not None:
                self.__paint_banner(painter, row.y - offset, row.height, row.banner)
                continue
            for index in range(row.first, row.last + 1):
                x, y, w, h = layout.rects[index]
                self.__paint_image(painter, QRect(x, y - offset, w, h), index, row.height)
                wanted.append(thumbnail_cache_key(self.__source.key(index), row.height, self.devicePixelRatio()))
                visible.append(index)
        self.__paint_pinned_banner(painter)
        painter.end()
        self.__loader.retain(self, wanted)
        # headers for what is in view and one screen ahead, so the pack settles before it scrolls in
        ahead = [
            index
            for row in layout.rows_between(offset + viewport_height, offset + 2 * viewport_height)
            if row.banner is None
            for index in range(row.first, row.last + 1)
        ]
        self.__model.request_dimensions([*visible, *ahead])

    @override
    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Keyboard navigation (#221): LEFT/RIGHT select the previous/next image, UP/DOWN the nearest
        image in the row above/below, ``+``/``-`` (keypad included) expand/collapse the current group
        -- the selected image's, else the pinned one's, else the first on screen -- and ESC clears
        the selection. Anything else passes on.

        :param event: the Qt key event.
        """
        match event.key():
            case Qt.Key.Key_Escape:
                self.set_selected(None)
            case Qt.Key.Key_Left:
                self.__step_selection(-1)
            case Qt.Key.Key_Right:
                self.__step_selection(1)
            case Qt.Key.Key_Up:
                self.__step_rows(-1)
            case Qt.Key.Key_Down:
                self.__step_rows(1)
            case Qt.Key.Key_Plus | Qt.Key.Key_Minus:
                group = self.current_group()
                if group is not None:
                    self.set_collapsed(group, event.key() == Qt.Key.Key_Minus)
            case _:
                super().keyPressEvent(event)
                return
        event.accept()

    def current_group(self) -> str | None:
        """The group the keyboard's ``+``/``-`` act on: the selected image's, else the pinned banner's,
        else that of the first banner or image row on screen.

        :returns: the group's key, or ``None`` with no banners at all or nothing packed.
        """
        if self.__selected is not None and self.__selected < len(self.__groups):
            return self.__groups[self.__selected]
        pinned = self.pinned_banner()
        if pinned is not None or self.__layout is None:
            return pinned
        offset = self.verticalScrollBar().value()
        on_screen = self.__layout.rows_between(offset, offset + self.viewport().height())
        first = next(iter(on_screen), None)
        if first is None:
            return None
        return first.banner if first.banner is not None else self.__groups[first.first]

    def __visible_rows(self) -> list[Row]:
        """The image rows of the current table -- no banners, no collapsed groups -- top to bottom."""
        if self.__layout is None:
            return []
        return [row for row in self.__layout.rows if row.banner is None]

    def __step_selection(self, delta: int) -> None:
        """Select the image ``delta`` places along the shown sequence, or the first shown one with
        nothing selected; stops at the ends.

        :param delta: ``-1`` for the previous image, ``1`` for the next.
        """
        rows = self.__visible_rows()
        shown = [index for row in rows for index in range(row.first, row.last + 1)]
        if not shown:
            return
        if self.__selected not in shown:
            self.reveal(shown[0])
            return
        position = shown.index(self.__selected) + delta
        if 0 <= position < len(shown):
            self.reveal(shown[position])

    def __step_rows(self, delta: int) -> None:
        """Select the image in the row ``delta`` rows away whose centre is nearest the selected one's,
        or the first shown image with nothing selected; stops at the ends.

        :param delta: ``-1`` for the row above, ``1`` for the row below.
        """
        rows = self.__visible_rows()
        if not rows or self.__layout is None:
            return
        selected = self.__selected
        current = (
            next((at for at, row in enumerate(rows) if row.first <= selected <= row.last), None)
            if selected is not None
            else None
        )
        if selected is None or current is None:
            self.reveal(rows[0].first)
            return
        target = current + delta
        if not 0 <= target < len(rows):
            return
        rects = self.__layout.rects
        x, _, w, _ = rects[selected]
        centre = x + w / 2
        row = rows[target]
        nearest = min(
            range(row.first, row.last + 1),
            key=lambda index: abs(rects[index][0] + rects[index][2] / 2 - centre),
        )
        self.reveal(nearest)

    @override
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Track the hovered image for the status line.

        :param event: the Qt mouse event, forwarded to the base class.
        """
        super().mouseMoveEvent(event)
        self.__set_hovered(self.index_at(event.position().toPoint()))

    @override
    def leaveEvent(self, event: QEvent) -> None:
        """Nothing is hovered once the pointer leaves.

        :param event: the Qt leave event, forwarded to the base class.
        """
        super().leaveEvent(event)
        self.__set_hovered(None)

    @override
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """A left click selects the image under it (or deselects it when it is the selected one), or
        collapses/expands the group under a banner.

        Release, not press, and only when the release lands where the press did -- the standard "this
        was a click, not a drag away" test. The release that ends a double-click is swallowed, or the
        open would be followed by a stray toggle of the selection.

        :param event: the Qt mouse event, forwarded to the base class.
        """
        super().mouseReleaseEvent(event)
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self.__swallow_release:
            self.__swallow_release = False
            return
        point = event.position().toPoint()
        banner = self.banner_at(point)
        if banner is not None:
            self.set_collapsed(banner, banner not in self.__collapsed)
            return
        index = self.index_at(point)
        if index is not None:
            self.set_selected(None if index == self.__selected else index)

    @override
    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """Open the image under a left double-click, selected -- whatever the selection was before,
        and whether or not the click that started the double-click toggled it off.

        :param event: the Qt mouse event, forwarded to the base class.
        """
        super().mouseDoubleClickEvent(event)
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = event.position().toPoint()
        if self.banner_at(point) is not None:
            # the first click already toggled the group; the release that ends this double-click
            # must not toggle it back
            self.__swallow_release = True
            return
        index = self.index_at(point)
        if index is not None:
            self.__swallow_release = True
            self.set_selected(index)
            self.image_activated.emit(index)

    def __set_hovered(self, index: int | None) -> None:
        """Remember the hovered image and re-report the status line if that changes what it says.

        :param index: the hovered position, or ``None``.
        """
        if index == self.__hovered:
            return
        self.__hovered = index
        if self.__selected is None:
            self.__report_status()

    def __report_status(self) -> None:
        """Announce what the status line should say now."""
        self.status_changed.emit(self.status_text())

    def __paint_banner(self, painter: QPainter, y: int, height: int, key: str) -> None:
        """Paint one banner row: its mark centred in a fixed column, then its label, elided to what
        is left of the width -- in the palette's placeholder colour, bold. Two columns, so the label
        stands still when the mark changes width on a toggle.

        :param painter: the painter.
        :param y: the row's top in viewport coordinates.
        :param height: the row's height.
        :param key: the group's key.
        """
        mark, text = banner_parts(key, self.__counts.get(key, 0), collapsed=key in self.__collapsed)
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(self.palette().color(QPalette.ColorRole.PlaceholderText))
        mark_rect = QRect(BANNER_INSET, y, BANNER_MARK_WIDTH, height)
        painter.drawText(mark_rect, Qt.AlignmentFlag.AlignCenter, mark)
        left = BANNER_INSET + BANNER_MARK_WIDTH
        rect = QRect(left, y, self.viewport().width() - left - BANNER_INSET, height)
        # elided in the middle: the path's start and the count at its end are the parts that tell
        # one group from the next, and the folder names between are what a narrow dock can spare
        elided = painter.fontMetrics().elidedText(text, Qt.TextElideMode.ElideMiddle, rect.width())
        painter.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided)
        font.setBold(False)
        painter.setFont(font)

    def __paint_pinned_banner(self, painter: QPainter) -> None:
        """Paint the current group's banner pinned over the top of the viewport, if one is
        (:meth:`pinned_banner`), on the widget's own background so the rows scroll under it.

        :param painter: the painter.
        """
        pinned = self.pinned_banner()
        if pinned is None:
            return
        painter.fillRect(0, 0, self.viewport().width(), BANNER_HEIGHT, self.palette().color(QPalette.ColorRole.Window))
        self.__paint_banner(painter, 0, BANNER_HEIGHT, pinned)

    def __paint_image(self, painter: QPainter, rect: QRect, index: int, height: int) -> None:
        """Paint one image cell: its thumbnail, or a placeholder while it decodes or once it failed,
        and the selection ring when it is the selected one.

        :param painter: the painter.
        :param rect: the cell in viewport coordinates.
        :param index: the image's position.
        :param height: the row height the thumbnail is decoded at.
        """
        ratio = self.devicePixelRatio()
        pixmap = self.__loader.request(self, self.__source, index, height, ratio)
        if pixmap is not None:
            # fitted and centred, never stretched: the cell was packed from the header's aspect, and
            # a thumbnail that disagrees with it (a header still unread, or a format whose stored size
            # differs from its shown one) must show its own proportions inside the cell. Sized in
            # logical pixels, which is what the pixmap's own ratio makes its device pixels into
            fitted = pixmap.deviceIndependentSize().toSize().scaled(rect.size(), Qt.AspectRatioMode.KeepAspectRatio)
            target = QRect(QPoint(0, 0), fitted)
            target.moveCenter(rect.center())
            painter.drawPixmap(target, pixmap)
        else:
            colour = self.palette().color(QPalette.ColorRole.Text)
            failed = self.__loader.failed(self.__source.key(index), height, ratio)
            colour.setAlpha(BROKEN_ALPHA if failed else PLACEHOLDER_ALPHA)
            painter.fillRect(rect, colour)
        if index == self.__selected:
            # the same odd-even-filled ring the thumbnail row marks its current item with
            border = THUMBNAIL_BORDER
            ring = QPainterPath()
            ring.addRect(QRectF(rect))
            ring.addRect(QRectF(rect.adjusted(border, border, -border, -border)))
            painter.fillPath(ring, self.palette().color(QPalette.ColorRole.Highlight))

    def __repack(self) -> None:
        """The packing pass: banners and groups from the flags, aspects from the model, geometry from
        `pack_rows` -- with a collapsed group's images left out.

        A selected image on screen under the outgoing table is kept on screen under the new one:
        every pass can move it (a header landing changes a row's height, a width changes every row),
        and the scroll offset alone would land on other images."""
        if (
            self.__reveal_index is None
            and self.__selected is not None
            and self.__layout is not None
            and self.__is_in_view(self.__layout, self.__selected, self.viewport().height())
        ):
            self.__reveal_index = self.__selected
        entries = self.__model.entries
        rehu_directory = self.__model.rehu_directory
        if rehu_directory is not None:
            banners = dict(banner_rows(entries, rehu_directory, self.__flags))
            self.__groups = group_of(entries, rehu_directory, self.__flags)
        else:
            banners = {}
            self.__groups = [None] * len(entries)
        self.__counts = Counter(group for group in self.__groups if group is not None)
        hide_all = not self.__previews_visible
        items = [
            LayoutItem(
                self.__model.aspect(index),
                banners.get(index),
                hidden=hide_all or self.__groups[index] in self.__collapsed,
            )
            for index in range(len(entries))
        ]
        width = max(1, self.viewport().width())
        self.__layout = pack_rows(items, width, self.__min_height, self.__max_height, ITEM_SPACING, BANNER_HEIGHT)
        scrollbar = self.verticalScrollBar()
        scrollbar.setRange(0, max(0, self.__layout.height - self.viewport().height()))
        scrollbar.setPageStep(self.viewport().height())
        scrollbar.setSingleStep(max(1, self.__min_height // 2))
        if self.__reveal_banner is not None:
            # the collapsed banner's row lands at the top of the viewport; a banner already on screen
            # (its row below the scroll offset) stays where it is, so a click there shifts nothing.
            # The banner is always in this table: the key came off the previous one, and the two
            # things that change the set of banners (a reset, new flags) drop the ask
            banner_tops = {row.banner: row.y for row in self.__layout.rows if row.banner is not None}
            scrollbar.setValue(min(scrollbar.value(), banner_tops[self.__reveal_banner]))
            self.__reveal_banner = None
        if self.__reveal_index is not None:
            # the least scroll that brings the whole cell into the viewport -- nothing when it is
            # already there, so a viewer closed on the image it opened from leaves the grid still
            _, top, _, height = self.__layout.rects[self.__reveal_index]
            bottom = top + height
            viewport_height = self.viewport().height()
            # a cell packed away (previews hidden app-wide) has no place to scroll to
            if height <= 0:
                pass
            elif top < scrollbar.value():
                scrollbar.setValue(top - ITEM_SPACING)
            elif bottom > scrollbar.value() + viewport_height:
                scrollbar.setValue(bottom + ITEM_SPACING - viewport_height)
            self.__reveal_index = None
        self.viewport().update()

    def __on_model_reset(self) -> None:
        """Adopt the new entries' source and re-pack from the top, with nothing selected or collapsed.

        The old table is dropped **now**, not when the pack runs: its rects index the old sequence, and
        a paint or a click arriving before the next event-loop turn would read them against a source
        that may be shorter.
        """
        self.__layout = None
        self.__source = self.__model.source
        self.__collapsed.clear()
        self.__reveal_banner = None
        self.__reveal_index = None
        self.__hovered = None
        self.set_selected(None)
        self.verticalScrollBar().setValue(0)
        self.schedule_repack()

    def __on_thumbnail_ready(self, cache_key: str) -> None:
        """Repaint as a thumbnail lands -- coarse, like the row's: the loader announces every decode.

        :param cache_key: the thumbnail's cache key; unused.
        """
        del cache_key
        self.viewport().update()

    def __on_scrolled(self, value: int) -> None:
        """Repaint on scroll; the whole viewport, since every row moved -- and re-read what is under
        the pointer, which a scroll changes without the pointer moving.

        :param value: the new scroll position; unused.
        """
        del value
        self.viewport().update()
        if self.viewport().underMouse():
            self.__set_hovered(self.index_at(self.viewport().mapFromGlobal(QCursor.pos())))


class ContentImagesPanel(QWidget):
    """The dock's content: the grid over a one-line status bar that names the selected image, or the
    hovered one while nothing is selected (#221).

    :param view: the grid.
    :param parent: optional Qt parent.
    """

    def __init__(self, view: ContentImagesView, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__view: Final = view
        # elided to the dock's width -- a member path inside a deep archive can be far longer than
        # the dock is wide; the inset is the strip's, not the label's, so it elides to its real width
        self.__status: Final = ElidedLabel(self)
        self.__status.setObjectName(STATUS_LABEL_NAME)
        self.__status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        strip = QWidget(self)
        strip.setBackgroundRole(QPalette.ColorRole.Window)
        strip.setAutoFillBackground(True)
        strip_layout = QVBoxLayout(strip)
        strip_layout.setContentsMargins(BANNER_INSET, 2, BANNER_INSET, 2)
        strip_layout.addWidget(self.__status)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(view, 1)
        layout.addWidget(strip)
        view.status_changed.connect(self.__status.set_text)

    @property
    def view(self) -> ContentImagesView:
        """The grid."""
        return self.__view

    @property
    def status(self) -> ElidedLabel:
        """The status line."""
        return self.__status
