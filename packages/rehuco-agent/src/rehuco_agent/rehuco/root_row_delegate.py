"""Paints a root's row in the Roots view's first column: its glyph and name, and under the name its folder (#378)."""

from typing import Final, override

from borco_pyside.widgets.row_band_delegate import ModelIndex
from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem

from .roots_folder_model import RootsFolderModel
from .roots_item_delegate import ICON_SIZE, ICON_TEXT_GAP, RootsItemDelegate, arrow_height

PATH_FONT_SCALE: Final = 0.85
"""How large the folder line is against the name's font."""

PATH_ALPHA: Final = 150
"""How opaque the folder line is against the row, so it reads as secondary to the name."""

ROW_PADDING: Final = 4
"""The space above the name and below the folder, in pixels."""


class RootRowDelegate(RootsItemDelegate):
    """Draws a root as two lines, with the glyph centred on the row beside both::

               name
        [icon]
               D:\\\\folder\\\\that\\\\is\\\\the\\\\root

    The folder is middle-elided to the width the row has, in a smaller font and a fainter colour than the name. The
    name keeps the model's font -- struck through for a local folder that is gone -- and the row's colour, greyed for a
    root that is away; the grip, the selection band and the arrow are the base delegate's.

    The folder is the model's :attr:`~RootsFolderModel.PATH_ROLE`.

    **The glyph grows as the arrow does.** The style draws the column view's arrow bigger in a taller row, so a two-line
    root row has a bigger one than a folder row in the next column; the glyph is scaled by the same ratio -- the
    arrow this row gets over the one a one-line row gets, as :func:`~.roots_item_delegate.arrow_height` measures them
    -- so a root's glyph and arrow match each other, as a folder's do.

    :param parent: optional Qt parent.
    """

    @override
    def paint_content(
        self, painter: QPainter, opt: QStyleOptionViewItem, index: ModelIndex, rect: QRect, color: QColor
    ) -> None:
        folder_font = RootRowDelegate.__folder_font(opt.font)
        name_height = QFontMetrics(opt.font).height()
        folder_height = QFontMetrics(folder_font).height()
        top = rect.top() + (rect.height() - name_height - folder_height) // 2
        left = rect.left()
        icon = index.data(RootsFolderModel.ICON_PATH_ROLE)
        if isinstance(icon, str):
            size = self.glyph_size(opt, index, rect.height())
            self.draw_icon(painter, icon, color, QRect(left, rect.top() + (rect.height() - size) // 2, size, size))
            left += size + ICON_TEXT_GAP
        width = rect.right() - left + 1
        RootRowDelegate.__draw_line(
            painter, opt.font, opt.text, opt.textElideMode, QRect(left, top, width, name_height)
        )
        faint = QColor(color)
        faint.setAlpha(PATH_ALPHA)
        painter.setPen(faint)
        RootRowDelegate.__draw_line(
            painter,
            folder_font,
            str(index.data(RootsFolderModel.PATH_ROLE) or ""),
            Qt.TextElideMode.ElideMiddle,
            QRect(left, top + name_height, width, folder_height),
        )

    @staticmethod
    def __draw_line(painter: QPainter, font: QFont, text: str, elide: Qt.TextElideMode, line: QRect) -> None:
        """Draw one line of text, elided to fit, vertically centred in its rect.

        :param painter: the painter, its pen already set.
        :param font: the font.
        :param text: the text.
        :param elide: where to elide it.
        :param line: the line's rect.
        """
        painter.setFont(font)
        painter.drawText(
            line,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            painter.fontMetrics().elidedText(text, elide, line.width()),
        )

    def glyph_size(self, option: QStyleOptionViewItem, index: ModelIndex, row_height: int) -> int:
        """How big a root's glyph is drawn in a row ``row_height`` tall: :data:`ICON_SIZE` scaled by how much bigger
        the style draws this row's arrow than a one-line row's, never smaller than a folder's nor taller than the lines.

        :param option: the row's option.
        :param index: the root.
        :param row_height: the row's height.
        :returns: the glyph's side, in pixels.
        """
        style = option.widget.style() if option.widget is not None else QApplication.style()
        folder_arrow = arrow_height(style, super().sizeHint(option, index).height())
        root_arrow = arrow_height(style, row_height)
        scaled = round(ICON_SIZE * root_arrow / folder_arrow) if folder_arrow > 0 else ICON_SIZE
        return max(ICON_SIZE, min(scaled, row_height - 2 * ROW_PADDING))

    @override
    def sizeHint(self, option: QStyleOptionViewItem, index: ModelIndex) -> QSize:  # noqa: N802  (Qt API name)
        hint = super().sizeHint(option, index)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        lines = QFontMetrics(opt.font).height() + QFontMetrics(RootRowDelegate.__folder_font(opt.font)).height()
        height = max(hint.height(), lines + 2 * ROW_PADDING)
        if not isinstance(index.data(RootsFolderModel.ICON_PATH_ROLE), str):
            return QSize(hint.width(), height)
        # the one-line hint already made room for a glyph of the folders' size; a root's is bigger by this much
        return QSize(hint.width() + self.glyph_size(option, index, height) - ICON_SIZE, height)

    @staticmethod
    def __folder_font(name_font: QFont) -> QFont:
        """The font of the folder line: the name's, smaller.

        :param name_font: the name's font.
        :returns: the font.
        """
        font = QFont(name_font)
        font.setStrikeOut(False)
        if font.pointSizeF() > 0:
            font.setPointSizeF(font.pointSizeF() * PATH_FONT_SCALE)
        else:  # a font is sized in points or in pixels, and ``pixelSize()`` is ``-1`` for one in points
            font.setPixelSize(max(1, round(font.pixelSize() * PATH_FONT_SCALE)))
        return font
