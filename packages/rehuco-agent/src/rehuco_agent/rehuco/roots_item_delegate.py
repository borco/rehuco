"""Paints a Roots view row: its glyph, its name, and the arrow that says it opens another column (#378)."""

from typing import Final, override

from borco_pyside.widgets import RowBandDelegate
from borco_pyside.widgets.row_band_delegate import TEXT_PADDING, ModelIndex
from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFontMetricsF, QPainter, QPalette
from PySide6.QtWidgets import QAbstractItemView, QApplication, QStyle, QStyleOptionViewItem

from ..svg_icon_cache import SvgIconCache
from .roots_folder_model import RootsFolderModel
from .roots_grip import GRIP_WIDTH, paint_grip

ICON_SIZE: Final = 16
"""A row's glyph is this many pixels square, as in the files sub-dock."""

ICON_TEXT_GAP: Final = 6

ARROW_WIDTH: Final = 12
"""Room kept at a row's right edge for the arrow of one that opens another column."""


class RootsItemDelegate(RowBandDelegate):
    """Draws what :class:`~borco_pyside.widgets.RowBandDelegate` draws, plus the row's glyph and the column view's
    arrow.

    The glyph path is the model's :attr:`~RootsFolderModel.ICON_PATH_ROLE`, recoloured to the text colour so it
    reads on the selection band as the text does. A row the model says is greyed
    (:attr:`~RootsFolderModel.GREYED_ROLE`) is drawn in the palette's disabled colours while staying selectable --
    which an unreachable root has to be, so its card can still be edited.

    A ``QColumnView`` gives its columns a delegate of its own, which draws that arrow and nothing else this view
    needs, so :class:`~rehuco_agent.rehuco.roots_column_view.RootsColumnView` puts this one on each column.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QAbstractItemView | None = None) -> None:
        super().__init__(parent)
        self.__icons: Final = SvgIconCache()

    @override
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: ModelIndex) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        painter.save()
        try:
            color = self.paint_band(painter, opt, index)
            selected = QStyle.StateFlag.State_Selected in opt.state
            if index.data(RootsFolderModel.GREYED_ROLE) and not selected:
                color = opt.palette.color(  # pylint: disable=no-member
                    QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text
                )
                painter.setPen(color)
            rect = opt.rect.adjusted(TEXT_PADDING, 0, -TEXT_PADDING, 0)
            if index.flags() & Qt.ItemFlag.ItemIsDragEnabled:
                paint_grip(painter, QRect(opt.rect.left(), opt.rect.top(), GRIP_WIDTH, opt.rect.height()), color)
                rect.setLeft(opt.rect.left() + GRIP_WIDTH)
            if index.model().hasChildren(index):
                self.__paint_arrow(painter, opt, rect)
                rect.setRight(rect.right() - ARROW_WIDTH)
            self.paint_content(painter, opt, index, rect, color)
        finally:
            painter.restore()

    def paint_content(
        self, painter: QPainter, opt: QStyleOptionViewItem, index: ModelIndex, rect: QRect, color: QColor
    ) -> None:
        """Draw what is in a row between its grip and its arrow: the glyph, then the name. What a subclass changes to
        draw a different row.

        :param painter: the painter, its pen already the row's colour.
        :param opt: the initialised option.
        :param index: the row.
        :param rect: what the row has left, padded.
        :param color: the row's text colour.
        """
        path = index.data(RootsFolderModel.ICON_PATH_ROLE)
        if isinstance(path, str):
            glyph = QRect(rect.left(), rect.top() + (rect.height() - ICON_SIZE) // 2, ICON_SIZE, ICON_SIZE)
            self.draw_icon(painter, path, color, glyph)
            rect.setLeft(rect.left() + ICON_SIZE + ICON_TEXT_GAP)
        painter.setFont(opt.font)
        elided = painter.fontMetrics().elidedText(opt.text, opt.textElideMode, rect.width())
        painter.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided)

    def draw_icon(self, painter: QPainter, path: str, color: QColor, rect: QRect) -> None:
        """Draw a glyph recoloured to ``color``.

        :param painter: the painter.
        :param path: the glyph's resource path.
        :param color: what to draw it in.
        :param rect: where.
        """
        self.__icons.icon(path, color).paint(painter, rect)

    @staticmethod
    def __paint_arrow(painter: QPainter, opt: QStyleOptionViewItem, rect: QRect) -> None:
        """Draw the style's column-view arrow at the right of a row.

        :param painter: the painter to draw with.
        :param opt: the initialised option.
        :param rect: the row's rect, padded.
        """
        arrow = QStyleOptionViewItem(opt)
        arrow.rect = QRect(rect.right() - ARROW_WIDTH + 1, rect.top(), ARROW_WIDTH, rect.height())
        style = opt.widget.style() if opt.widget is not None else QApplication.style()
        style.drawPrimitive(QStyle.PrimitiveElement.PE_IndicatorColumnViewArrow, arrow, painter, opt.widget)

    @override
    def sizeHint(self, option: QStyleOptionViewItem, index: ModelIndex) -> QSize:  # noqa: N802  (Qt API name)
        hint = super().sizeHint(option, index)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        extra = ARROW_WIDTH if index.model().hasChildren(index) else 0
        if index.flags() & Qt.ItemFlag.ItemIsDragEnabled:
            extra += GRIP_WIDTH
        if isinstance(index.data(RootsFolderModel.ICON_PATH_ROLE), str):
            extra += ICON_SIZE + ICON_TEXT_GAP
        return QSize(hint.width() + extra, max(hint.height(), ICON_SIZE + 2, round(QFontMetricsF(opt.font).height())))
