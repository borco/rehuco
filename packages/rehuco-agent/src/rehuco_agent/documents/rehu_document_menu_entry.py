"""A two-line menu entry for a `.rehu` document: its title above its dimmed, right-elided path."""

from pathlib import Path
from typing import ClassVar, Final, override

from PySide6.QtCore import QEvent, QRect, QSize, Qt
from PySide6.QtGui import (
    QAction,
    QColor,
    QEnterEvent,
    QFont,
    QFontMetrics,
    QIcon,
    QImage,
    QPainter,
    QPaintEvent,
    QPalette,
    QPixmap,
)
from PySide6.QtWidgets import QMenu, QStyle, QStyleOptionMenuItem, QWidget, QWidgetAction

from .document_dock import DIRTY_DOCK_MARKER

MAX_WIDTH: Final = 600
"""Widest an entry will *ask* to be, so a long title or path elides instead of growing its menu
without bound.

A cap on :meth:`RehuDocumentMenuEntry.sizeHint` only -- deliberately **not** a
``setMaximumWidth``. A menu is as wide as its widest row, and rows narrower than that are stretched
to fill it; a hard cap would leave a document entry short of the menu's right edge, which is visible
the moment the row is highlighted (its background stops mid-row) and wastes the space its path could
have used."""

PATH_FONT_SCALE: Final = 0.80
"""The path line's font size relative to the title's, so the title reads as primary."""

DIMMED_ALPHA: Final = 0.7
"""Opacity of the path line while the row is highlighted -- the dimmed-vs-primary distinction the
``PlaceholderText`` role carries at rest, expressed against whatever color the style highlights text
in (that role is defined against the *menu's* background, not against a highlight)."""

PROBE_SIZE: Final = QSize(200, 26)
"""Scratch size for the one-off render :meth:`RehuDocumentMenuEntry.row_style` measures from. Wide
enough that a probe glyph lands clear of any check column, short enough to be free."""


class RehuDocumentMenuEntry(QWidget):
    """A menu entry for a `.rehu` document: its title in normal text, its full path beneath it in
    smaller, dimmed text -- both right-elided to fit :data:`MAX_WIDTH`. Shared by the `View` menu's
    open-documents list (#61) and the `File` menu's `Open recents` list (#64).

    **Aligned and highlighted by the style, not by hand** (#79). A `QWidgetAction`'s custom default
    widget is painted by *us*, not by the `QMenu` around it, so anything invented here becomes a
    second, divergent implementation of a menu row -- which is how this entry first ended up with a
    square `Highlight`-blue block and a text checkmark while the native rows above it drew the
    `windows11` style's soft, rounded, inset pill and its own check glyph. So the row's background and
    checkmark are drawn by ``QStyle.CE_MenuItem`` from a real :class:`QStyleOptionMenuItem`, seeded
    from the owning menu through ``QMenu.initStyleOption``: the highlight, the checkmark and the check
    column's width then come from the same style code every native row uses. Seeding from the menu is
    also what carries ``maxIconWidth`` across -- the `View` menu's own ``Log``/``Tasks``/``Image
    Previews`` rows have icons, which widens the check column for *every* row, so an entry reserving
    only its own check width would sit left of everything above it.

    The two text lines are then drawn directly, at an x **measured from the style** rather than
    assumed (:meth:`row_style`). Letting ``CE_MenuItem`` draw them too would be neater but is not
    portable: only some styles leave the background alone when the option is unselected. `windows11`
    and `Fusion` do, so text passes compose over the row; `windowsvista` and the plain `Windows` style
    repaint the whole rect, which would erase the highlight underneath. Measuring the offset and
    drawing the text keeps every style -- including whatever macOS and the Linux desktops resolve to
    -- on the one path that was actually verified.

    :param title: the document's display title (`RehuDocumentModel.label`, or the same
        `info.rehu`-aware derivation for a not-currently-open path).
    :param path: the document's full path, or ``None`` for a not-yet-saved document.
    :param parent: optional Qt parent.
    :param checked: draw the style's own checkmark -- the `View` menu's open-documents list (#79)
        sets this for the currently focused document. The `File` menu's `Open recents` list has no
        notion of "current" and leaves it ``False``.
    :param dirty: draw :data:`~rehuco_agent.documents.document_dock.DIRTY_DOCK_MARKER` -- the same
        marker the document's own tab title carries -- in the menu's icon column (#79, see
        :meth:`__dirty_icon`).
    """

    row_styles: ClassVar[dict[tuple[str, int, str, int], tuple[int, QPalette.ColorRole]]] = {}
    """Memoized :meth:`row_style` results, keyed by everything they depend on."""

    def __init__(
        self,
        title: str,
        path: Path | None,
        parent: QWidget | None = None,
        *,
        checked: bool = False,
        dirty: bool = False,
    ) -> None:
        super().__init__(parent)
        self.__action: QAction | None = None
        self.__checked: Final = checked
        self.__dirty: Final = dirty
        self.__title: Final = title
        self.__path: Final = str(path) if path is not None else ""
        self.__hovered = False

    def __path_font(self) -> QFont:
        """This entry's font, scaled down for the path line."""
        font = self.font()
        font.setPointSizeF(font.pointSizeF() * PATH_FONT_SCALE)
        return font

    def __dirty_icon(self, color: QColor) -> QIcon:
        """The unsaved-changes marker as an icon, for the style to place in the menu's icon column.

        An icon rather than a prefix on the title (#79): the icon column is a column, and the `View`
        menu already has one -- its ``Log``/``Tasks``/``Image Previews`` rows put icons there -- so a
        marker written into the text instead lands wherever that document's title happens to start,
        ragged against the icons above it. The check column is separate again, so a focused *and*
        unsaved document shows both without them colliding.

        Drawn from :data:`~rehuco_agent.documents.document_dock.DIRTY_DOCK_MARKER` itself rather than
        as a hand-drawn circle, so the menu and the document's own tab cannot drift into two
        different marks.

        :param color: the color to draw it in -- the text color of the line it belongs to, so it
            follows the row into and out of its highlighted state.
        :returns: the marker icon, rendered for this screen's pixel ratio.
        """
        extent = self.style().pixelMetric(QStyle.PixelMetric.PM_SmallIconSize, None, self)
        ratio = self.devicePixelRatio()
        pixmap = QPixmap(QSize(int(extent * ratio), int(extent * ratio)))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setPen(color)
        painter.drawText(QRect(0, 0, extent, extent), Qt.AlignmentFlag.AlignCenter, DIRTY_DOCK_MARKER.strip())
        painter.end()
        return QIcon(pixmap)

    def __own_action(self) -> tuple[QMenu, QAction] | None:
        """The owning menu and this entry's own action in it, or ``None`` outside a menu.

        Looked up rather than taken as a constructor argument: a `QWidgetAction` and its default
        widget already point at each other, so asking a caller to pass the action back would be one
        more thing to get wrong. Cached on first hit -- a menu does not hand its widget to a
        different action later.
        """
        menu = self.parentWidget()
        if not isinstance(menu, QMenu):
            return None
        if self.__action is None:
            self.__action = next(
                (
                    action
                    for action in menu.actions()
                    if isinstance(action, QWidgetAction) and action.defaultWidget() is self
                ),
                None,
            )
        return (menu, self.__action) if self.__action is not None else None

    def __option(self, rect: QRect) -> QStyleOptionMenuItem:
        """A menu-item style option for ``rect``, seeded from the owning menu when possible.

        :param rect: the sub-rectangle this pass draws into.
        :returns: the option, with ``rect`` and this entry's own hovered state applied.
        """
        option = QStyleOptionMenuItem()
        owner = self.__own_action()
        if owner is not None:
            owner[0].initStyleOption(option, owner[1])
        else:
            option.initFrom(self)
        option.rect = rect
        option.menuItemType = QStyleOptionMenuItem.MenuItemType.Normal
        option.text = ""
        option.icon = QIcon()
        # NotCheckable, not an unchecked NonExclusive: styles drawing a real indicator rather than a
        # bare glyph (Fusion draws a checkbox) would otherwise put an empty box on every row --
        # including all of `Open recents`, which has nothing to check. It costs no alignment: the
        # check column's width comes from maxIconWidth, which every row reserves regardless.
        option.checkType = QStyleOptionMenuItem.CheckType.NotCheckable
        option.checked = False
        # the state initStyleOption reports tracks the menu's *current action*, which never follows a
        # widget-action's pointer -- this entry tracks its own hover instead (enterEvent/leaveEvent)
        option.state = QStyle.StateFlag.State_Enabled
        if self.__hovered:
            option.state |= QStyle.StateFlag.State_Selected
        return option

    def __render_probe(self, text: str, *, selected: bool) -> QImage:
        """Draw one scratch menu row, for :meth:`row_style` to measure.

        :param text: the row's text.
        :param selected: whether to draw it highlighted.
        :returns: the rendered image, on a transparent ground.
        """
        option = self.__option(QRect(0, 0, PROBE_SIZE.width(), PROBE_SIZE.height()))
        option.text = text
        option.state = QStyle.StateFlag.State_Enabled
        if selected:
            option.state |= QStyle.StateFlag.State_Selected
        image = QImage(PROBE_SIZE, QImage.Format.Format_ARGB32)
        image.fill(self.palette().color(QPalette.ColorRole.Window))
        painter = QPainter(image)
        self.style().drawControl(QStyle.ControlElement.CE_MenuItem, option, painter, self)
        painter.end()
        return image

    def row_style(self) -> tuple[int, QPalette.ColorRole]:
        """Where this style starts a menu row's text, and which role it draws highlighted text in.

        Both are **measured** from the style rather than derived from pixel metrics or picked by
        convention, because neither is knowable otherwise:

        * the text offset is the check column plus whatever margins the style spends, and styles
          disagree (27px on `windowsvista`, 17px on the plain `Windows` style at the same DPI). It is
          found by rendering the same row twice, once empty and once with a probe glyph, and taking
          the first column where the two differ -- which is exactly where text begins, whatever the
          style painted behind it.
        * the highlighted text color has no single right answer: `windows11` tints the row a very
          light gray and keeps the ordinary dark ``Text``, while `Fusion` and the plain `Windows`
          style fill it with a saturated blue and switch to ``HighlightedText``. Forcing either one
          renders the focused row unreadable wherever the other was meant -- pale-on-pale, which is
          what forcing ``HighlightedText`` first produced here. So the style is asked what it fills
          with, and the role is chosen for contrast against that.

        The answers depend only on the style, the palette, the font and the menu's check column, so
        they are memoized against all four: a handful of tiny renders per theme, not per paint.

        :returns: the text's left offset in this widget's coordinates, and the palette role to draw
            highlighted text in.
        """
        option = self.__option(self.rect())
        # objectName(), not the class name: PySide reports several distinct Qt styles as the same
        # wrapper class (`QCommonStyle`), so keying on the class silently serves one style's
        # measurements to another. QStyleFactory stamps the object name with the real style key.
        style_name = self.style().objectName() or type(self.style()).__name__
        key = (style_name, self.palette().cacheKey(), self.font().key(), option.maxIconWidth)
        cached = RehuDocumentMenuEntry.row_styles.get(key)
        if cached is not None:
            return cached

        empty = self.__render_probe("", selected=False)
        texted = self.__render_probe("Hg", selected=False)
        text_left = next(
            (
                x
                for x in range(PROBE_SIZE.width())
                if any(empty.pixel(x, y) != texted.pixel(x, y) for y in range(PROBE_SIZE.height()))
            ),
            0,
        )

        # sampled at the row's center: several styles fill the highlight with a vertical gradient, so
        # a pixel near an edge reports an extreme rather than what the text will actually sit on
        highlight = QColor(
            self.__render_probe("", selected=True).pixel(PROBE_SIZE.width() // 2, PROBE_SIZE.height() // 2)
        )
        # perceived brightness, not lightness(): a saturated mid blue reads far darker than its
        # max/min average suggests, and it is legibility against it being decided here
        brightness = (0.299 * highlight.red() + 0.587 * highlight.green() + 0.114 * highlight.blue()) / 255
        role = QPalette.ColorRole.Text if brightness > 0.5 else QPalette.ColorRole.HighlightedText

        RehuDocumentMenuEntry.row_styles[key] = (text_left, role)  # pylint: disable=unsupported-assignment-operation
        return text_left, role

    def __available_text_width(self) -> int:
        """Width left for text once the style's chrome is paid for, to elide against.

        Taken as the wider of this widget and :data:`MAX_WIDTH`, which is safe in both directions. A
        menu entry is asked for its text before it is ever laid out -- the menu sizes itself *from*
        that text -- and an unlaid-out child widget still reports Qt's default 100px, which would
        elide every title to two characters; the cap stands in until there is a real width. Once
        there is one it can only be *wider* than the cap for text that needed eliding, since such a
        row asks for the full cap and the menu is at least as wide as its widest row -- so taking the
        wider of the two never over-runs the row, and lets a stretched row use the space it was given
        rather than eliding at a boundary the reader cannot see.
        """
        text_left, _ = self.row_style()
        metrics = QFontMetrics(self.font())
        text_width = metrics.horizontalAdvance(self.__title)
        chrome = self.__row_size(self.__title, QSize(text_width, metrics.height())).width() - text_width
        trailing = max(0, chrome - text_left)
        return max(0, max(self.width(), MAX_WIDTH) - text_left - trailing)

    def __row_size(self, text: str, text_size: QSize) -> QSize:
        """What the style makes a one-line menu row sized around ``text_size`` holding ``text``.

        :param text: the row's text, which some styles measure rather than trust the size for.
        :param text_size: the text's own size.
        :returns: the full row size, text plus the style's chrome.
        """
        option = self.__option(self.rect())
        option.text = text
        return self.style().sizeFromContents(QStyle.ContentsType.CT_MenuItem, option, text_size, self)

    @property
    def checked(self) -> bool:
        """Whether this row draws the style's checkmark (the currently focused document, #79)."""
        return self.__checked

    @property
    def dirty(self) -> bool:
        """Whether this row draws the unsaved-changes marker in the icon column (#79)."""
        return self.__dirty

    def displayed_title(self) -> str:
        """The title exactly as drawn: the dirty marker, if any, then the title, right-elided to fit.

        The same call :meth:`paintEvent` draws with, so what this reports and what a reader sees
        cannot drift apart.
        """
        return QFontMetrics(self.font()).elidedText(
            self.__title, Qt.TextElideMode.ElideRight, self.__available_text_width()
        )

    def displayed_path(self) -> str:
        """The path exactly as drawn, right-elided to fit -- empty for a not-yet-saved document."""
        return QFontMetrics(self.__path_font()).elidedText(
            self.__path, Qt.TextElideMode.ElideRight, self.__available_text_width()
        )

    @override
    def sizeHint(self) -> QSize:
        """Two stacked text lines, plus whatever chrome the style puts around a menu row."""
        title_metrics = QFontMetrics(self.font())
        path_metrics = QFontMetrics(self.__path_font())
        text_width = max(title_metrics.horizontalAdvance(self.__title), path_metrics.horizontalAdvance(self.__path))
        row = self.__row_size(self.__title, QSize(text_width, title_metrics.height()))
        return QSize(min(row.width(), MAX_WIDTH), row.height() + path_metrics.height())

    @override
    def enterEvent(self, event: QEnterEvent) -> None:
        """Start drawing this row as the highlighted one (#79)."""
        self.__hovered = True
        self.update()
        super().enterEvent(event)

    @override
    def leaveEvent(self, event: QEvent) -> None:
        """Stop drawing this row as the highlighted one (#79)."""
        self.__hovered = False
        self.update()
        super().leaveEvent(event)

    def __text_color(self, highlighted_role: QPalette.ColorRole, *, dimmed: bool) -> QColor:
        """The pen for one text line, given the role this style highlights text in.

        :param highlighted_role: the role from :meth:`row_style`.
        :param dimmed: whether this is the secondary (path) line.
        :returns: the color to draw it in.
        """
        palette = self.palette()
        if not self.__hovered:
            return palette.color(QPalette.ColorRole.PlaceholderText if dimmed else QPalette.ColorRole.Text)
        color = QColor(palette.color(highlighted_role))
        if dimmed:
            color.setAlphaF(DIMMED_ALPHA)
        return color

    def __draw_text(self, painter: QPainter) -> None:
        """Draw the title over the path, both at the style's own text offset.

        :param painter: the painter :meth:`paintEvent` already opened on this widget.
        """
        text_left, highlighted_role = self.row_style()
        title_font = self.font()
        path_font = self.__path_font()
        title_height = QFontMetrics(title_font).height()
        path_height = QFontMetrics(path_font).height()
        # the two lines are centered as a block, so the pair sits where a single native row's text
        # would rather than riding the widget's top edge
        top = (self.height() - title_height - path_height) // 2
        width = max(0, self.width() - text_left)

        for offset, height, text, font, dimmed in (
            (top, title_height, self.displayed_title(), title_font, False),
            (top + title_height, path_height, self.displayed_path(), path_font, True),
        ):
            painter.setFont(font)
            painter.setPen(self.__text_color(highlighted_role, dimmed=dimmed))
            painter.drawText(
                QRect(text_left, offset, width, height),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                text,
            )

    @override
    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw the row's background and checkmark through the style, then the two text lines."""
        painter = QPainter(self)
        background = self.__option(self.rect())
        if self.__checked:
            background.checkType = QStyleOptionMenuItem.CheckType.NonExclusive
            background.checked = True
        if self.__dirty:
            _, highlighted_role = self.row_style()
            background.icon = self.__dirty_icon(self.__text_color(highlighted_role, dimmed=False))
        self.style().drawControl(QStyle.ControlElement.CE_MenuItem, background, painter, self)
        self.__draw_text(painter)
        super().paintEvent(event)
