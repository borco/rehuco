"""Draws the Scrapers table's **Use browser** checkbox, centered in its cell (#278).

Installed with `QTableView.setItemDelegateForColumn`, not the view's general delegate
(`~borco_pyside.widgets.RowBandDelegate`), which this subclasses for the selection band behind the
indicator.

**Why not the base `QStyledItemDelegate.paint`?** It already draws a `CheckStateRole` cell's indicator
with no code of this module's own -- but `QCommonStyle`'s own `SE_ItemViewItemCheckIndicator` layout
does not honor `Qt.ItemDataRole.TextAlignmentRole` for the indicator glyph itself (only for adjacent
text), so it always sits left-anchored, however that role is set. Centering it needs an explicit,
manually-computed rect -- and :meth:`ScrapersCheckboxDelegate.editorEvent` hit-tests a click against
that same rect, rather than the base delegate's left-anchored one.
"""

from typing import override

from borco_pyside.widgets import RowBandDelegate
from PySide6.QtCore import QAbstractItemModel, QEvent, QModelIndex, QPersistentModelIndex, QRect, Qt
from PySide6.QtGui import QMouseEvent, QPainter
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionButton, QStyleOptionViewItem


class ScrapersCheckboxDelegate(RowBandDelegate):
    """Paints and hit-tests the **Use browser** column's checkbox, centered in its cell.

    :param parent: optional Qt parent.
    """

    @override
    def paint(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> None:
        state = index.data(Qt.ItemDataRole.CheckStateRole)
        painter.save()
        try:
            color = self.paint_band(painter, option, index)
            if state is None:
                return
            if QStyle.StateFlag.State_Selected in option.state:
                self.paint_selected_indicator(painter, self.__checkbox_rect(option), color, Qt.CheckState(state))
                return
            style = option.widget.style() if option.widget is not None else QApplication.style()
            check_option = QStyleOptionButton()
            check_option.rect = self.__checkbox_rect(option)
            check_option.state = QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_On
            if Qt.CheckState(state) != Qt.CheckState.Checked:
                check_option.state = QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_Off
            if not index.flags() & Qt.ItemFlag.ItemIsEnabled:
                check_option.state &= ~QStyle.StateFlag.State_Enabled
            style.drawPrimitive(QStyle.PrimitiveElement.PE_IndicatorCheckBox, check_option, painter)
        finally:
            painter.restore()

    @staticmethod
    def __checkbox_rect(option: QStyleOptionViewItem) -> QRect:
        """The checkbox indicator's rect, centered in ``option.rect`` -- what both :meth:`paint` and
        :meth:`editorEvent` use, so painting and hit-testing never disagree."""
        style = option.widget.style() if option.widget is not None else QApplication.style()
        width = style.pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth)
        height = style.pixelMetric(QStyle.PixelMetric.PM_IndicatorHeight)
        rect = option.rect
        return QRect(
            rect.x() + (rect.width() - width) // 2,
            rect.y() + (rect.height() - height) // 2,
            width,
            height,
        )

    @override
    def editorEvent(  # noqa: N802  (Qt API name)
        self,
        event: QEvent,
        model: QAbstractItemModel,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        if (
            event.type() != QEvent.Type.MouseButtonRelease
            or not isinstance(event, QMouseEvent)
            or not index.flags() & Qt.ItemFlag.ItemIsUserCheckable
            or not index.flags() & Qt.ItemFlag.ItemIsEnabled
        ):
            return super().editorEvent(event, model, option, index)
        if not self.__checkbox_rect(option).contains(event.position().toPoint()):
            return False
        current = Qt.CheckState(index.data(Qt.ItemDataRole.CheckStateRole))
        next_state = Qt.CheckState.Unchecked if current == Qt.CheckState.Checked else Qt.CheckState.Checked
        return model.setData(index, next_state, Qt.ItemDataRole.CheckStateRole)
