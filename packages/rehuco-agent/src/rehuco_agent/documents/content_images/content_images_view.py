"""The Content Images dock's surface: paints the packed rows from the layout table (#221).

A `QAbstractScrollArea` rather than a `QListView` in icon mode: the list view's native flow leaves the
right edge ragged and calls ``sizeHint()`` per item across the Python/C++ boundary, while the whole
point here is geometry computed once, in one pass (`pack_rows`), and painted from a table. The view
paints only the rows in the viewport, asks the `ThumbnailLoader` for exactly those thumbnails, and asks
the model for the headers of the rows one screen ahead so the pack settles before they scroll in.

Read-only, visibly so: no selection, no context menu, no drag. A click opens the image maximized --
that is the one thing it answers.
"""

from typing import Final, override

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QMouseEvent, QPainter, QPaintEvent, QPalette, QResizeEvent
from PySide6.QtWidgets import QAbstractScrollArea, QFrame, QWidget

from ...fields.widgets.thumbnail_loader import ThumbnailLoader, thumbnail_cache_key
from .banners import ContentDisplayFlags, banner_rows
from .content_images_model import ArchiveImageSource, ContentImagesModel
from .justified_layout import LayoutItem, PackedLayout, pack_rows

ITEM_SPACING: Final = 4
"""The gap between images in a row and between rows, in pixels."""

BANNER_HEIGHT: Final = 24
"""A banner row's height, in pixels -- one line of text with room around it."""

BANNER_INSET: Final = 6
"""How far in from the left edge a banner's text starts, in pixels."""

PLACEHOLDER_ALPHA: Final = 28
BROKEN_ALPHA: Final = 70
"""How faint the placeholders are: a pending thumbnail is a hint of the text colour, a member that
could not be decoded a stronger one, so a broken pack reads as broken rather than as still loading."""


class ContentImagesView(QAbstractScrollArea):  # pylint: disable=too-many-instance-attributes
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
    """Fires with the position of the image the user clicked."""

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
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
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
        """The image source over the current entries -- what a click opens the lightbox against."""
        return self.__source

    @property
    def flags(self) -> ContentDisplayFlags:
        """Which boundaries are bannered."""
        return self.__flags

    @property
    def clamp(self) -> tuple[int, int]:
        """The ``(min, max)`` flush row height."""
        return self.__min_height, self.__max_height

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

        :param flags: which boundaries are bannered.
        """
        if flags == self.__flags:
            return
        self.__flags = flags
        self.schedule_repack()

    def schedule_repack(self) -> None:
        """Run the packing pass on the next event-loop turn, once for however many asks arrive."""
        self.__repack_timer.start()

    def index_at(self, point: QPoint) -> int | None:
        """The image under ``point`` (viewport coordinates), if any.

        :param point: the viewport position.
        :returns: the position in the source, or ``None`` over a gap, a banner or nothing.
        """
        if self.__layout is None:
            return None
        y = point.y() + self.verticalScrollBar().value()
        for row in self.__layout.rows_between(y, y + 1):
            if row.banner is not None:
                continue
            for index in range(row.first, row.last + 1):
                if QRect(*self.__layout.rects[index]).contains(point.x(), y):
                    return index
        return None

    @override
    def resizeEvent(self, event: QResizeEvent) -> None:
        """Re-pack to the new width.

        :param event: the Qt resize event, forwarded to the base class.
        """
        super().resizeEvent(event)
        self.schedule_repack()

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
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Open the image under a left click.

        Release, not press, and only when the release lands where the press did -- the standard "this
        was a click, not a drag away" test.

        :param event: the Qt mouse event, forwarded to the base class.
        """
        super().mouseReleaseEvent(event)
        if event.button() != Qt.MouseButton.LeftButton:
            return
        index = self.index_at(event.position().toPoint())
        if index is not None:
            self.image_activated.emit(index)

    def __paint_banner(self, painter: QPainter, y: int, height: int, text: str) -> None:
        """Paint one banner row: its text, in the palette's placeholder colour, bold.

        :param painter: the painter.
        :param y: the row's top in viewport coordinates.
        :param height: the row's height.
        :param text: the banner.
        """
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(self.palette().color(QPalette.ColorRole.PlaceholderText))
        rect = QRect(BANNER_INSET, y, self.viewport().width() - BANNER_INSET, height)
        painter.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        font.setBold(False)
        painter.setFont(font)

    def __paint_image(self, painter: QPainter, rect: QRect, index: int, height: int) -> None:
        """Paint one image cell: its thumbnail, or a placeholder while it decodes or once it failed.

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
            return
        colour = self.palette().color(QPalette.ColorRole.Text)
        failed = self.__loader.failed(self.__source.key(index), height, ratio)
        colour.setAlpha(BROKEN_ALPHA if failed else PLACEHOLDER_ALPHA)
        painter.fillRect(rect, colour)

    def __repack(self) -> None:
        """The packing pass: banners from the flags, aspects from the model, geometry from `pack_rows`."""
        entries = self.__model.entries
        rehu_directory = self.__model.rehu_directory
        banners = dict(banner_rows(entries, rehu_directory, self.__flags)) if rehu_directory is not None else {}
        items = [LayoutItem(self.__model.aspect(index), banners.get(index)) for index in range(len(entries))]
        width = max(1, self.viewport().width())
        self.__layout = pack_rows(items, width, self.__min_height, self.__max_height, ITEM_SPACING, BANNER_HEIGHT)
        scrollbar = self.verticalScrollBar()
        scrollbar.setRange(0, max(0, self.__layout.height - self.viewport().height()))
        scrollbar.setPageStep(self.viewport().height())
        scrollbar.setSingleStep(max(1, self.__min_height // 2))
        self.viewport().update()

    def __on_model_reset(self) -> None:
        """Adopt the new entries' source and re-pack from the top.

        The old table is dropped **now**, not when the pack runs: its rects index the old sequence, and
        a paint or a click arriving before the next event-loop turn would read them against a source
        that may be shorter.
        """
        self.__layout = None
        self.__source = self.__model.source
        self.verticalScrollBar().setValue(0)
        self.schedule_repack()

    def __on_thumbnail_ready(self, cache_key: str) -> None:
        """Repaint as a thumbnail lands -- coarse, like the row's: the loader announces every decode.

        :param cache_key: the thumbnail's cache key; unused.
        """
        del cache_key
        self.viewport().update()

    def __on_scrolled(self, value: int) -> None:
        """Repaint on scroll; the whole viewport, since every row moved.

        :param value: the new scroll position; unused.
        """
        del value
        self.viewport().update()
