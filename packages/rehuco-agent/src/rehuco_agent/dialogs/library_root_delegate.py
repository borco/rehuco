"""Draws a root in the library wizard's Root list on two lines: its label, and its location grayed beneath (#685)."""

from typing import Final, override

from borco_pyside.widgets.row_band_delegate import ModelIndex
from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPalette
from PySide6.QtWidgets import QApplication, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from ..rehuco.root_row_delegate import PATH_ALPHA, ROW_PADDING, RootRowDelegate

LOCATION_ROLE: Final = Qt.ItemDataRole.UserRole + 1
"""The item role that holds a root's location, drawn under its label."""


class LibraryRootDelegate(QStyledItemDelegate):
    """Draws an item as two lines::

        label
        D:\\\\folder\\\\that\\\\is\\\\the\\\\root

    The label is the item's display text, in the item's font; the location is its :data:`LOCATION_ROLE`,
    middle-elided to the width the row has, in the smaller font and the fainter color the Roots view gives a root's
    folder (`~rehuco_agent.rehuco.root_row_delegate.RootRowDelegate`). The style paints the band under both, and grays
    an item that is disabled.
    """

    @override
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: ModelIndex) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        label, opt.text = opt.text, ""
        style = opt.widget.style() if opt.widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        group = (
            QPalette.ColorGroup.Normal if QStyle.StateFlag.State_Enabled in opt.state else QPalette.ColorGroup.Disabled
        )
        role = (
            QPalette.ColorRole.HighlightedText
            if QStyle.StateFlag.State_Selected in opt.state
            else QPalette.ColorRole.Text
        )
        color = opt.palette.color(group, role)
        name_height = QFontMetrics(opt.font).height()
        location_font = RootRowDelegate.folder_font(opt.font)
        location_height = QFontMetrics(location_font).height()
        area = opt.rect.adjusted(ROW_PADDING, ROW_PADDING, -ROW_PADDING, -ROW_PADDING)
        painter.save()
        painter.setPen(color)
        RootRowDelegate.draw_line(
            painter,
            opt.font,
            label,
            Qt.TextElideMode.ElideRight,
            QRect(area.left(), area.top(), area.width(), name_height),
        )
        faint = QColor(color)
        faint.setAlpha(PATH_ALPHA)
        painter.setPen(faint)
        RootRowDelegate.draw_line(
            painter,
            location_font,
            str(index.data(LOCATION_ROLE) or ""),
            Qt.TextElideMode.ElideMiddle,
            QRect(area.left(), area.top() + name_height, area.width(), location_height),
        )
        painter.restore()

    @override
    def sizeHint(self, option: QStyleOptionViewItem, index: ModelIndex) -> QSize:  # noqa: N802  (Qt API name)
        hint = super().sizeHint(option, index)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        lines = QFontMetrics(opt.font).height() + QFontMetrics(RootRowDelegate.folder_font(opt.font)).height()
        return QSize(hint.width(), lines + 2 * ROW_PADDING)
