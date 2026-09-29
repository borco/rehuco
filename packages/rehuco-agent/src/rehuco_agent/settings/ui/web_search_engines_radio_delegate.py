"""Draws the web search engines table's **Use** column as a radio button, centered in its cell (#388).

`QStyledItemDelegate` draws a `CheckStateRole` cell as a *check box*, left-anchored; this draws the
style's radio indicator instead, at a rect that both :meth:`WebSearchEnginesRadioDelegate.paint` and
:meth:`~WebSearchEnginesRadioDelegate.editorEvent` compute, so painting and hit-testing never disagree
(the same reasoning `~.scrapers_checkbox_delegate.ScrapersCheckboxDelegate` gives for its own).
"""

# the centered-indicator geometry and the click hit-test read the same as `ScrapersCheckboxDelegate`'s,
# because they are the same job; only the indicator drawn and the state a click asks for differ
# pylint: disable=duplicate-code

from typing import override

from PySide6.QtCore import QAbstractItemModel, QEvent, QModelIndex, QPersistentModelIndex, QRect, Qt
from PySide6.QtGui import QMouseEvent, QPainter
from PySide6.QtWidgets import QApplication, QStyle, QStyledItemDelegate, QStyleOptionButton, QStyleOptionViewItem


class WebSearchEnginesRadioDelegate(QStyledItemDelegate):
    """Paints and hit-tests the **Use** column's radio button. A click asks the model to check the row;
    the model is what makes the choice exclusive, and what refuses to clear it.

    :param parent: optional Qt parent.
    """

    @override
    def paint(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> None:
        state = index.data(Qt.ItemDataRole.CheckStateRole)
        painter.save()
        try:
            style = option.widget.style() if option.widget is not None else QApplication.style()
            radio = QStyleOptionButton()
            radio.rect = self.__radio_rect(option)
            checked = Qt.CheckState(state) == Qt.CheckState.Checked
            radio.state = QStyle.StateFlag.State_Enabled | (
                QStyle.StateFlag.State_On if checked else QStyle.StateFlag.State_Off
            )
            style.drawPrimitive(QStyle.PrimitiveElement.PE_IndicatorRadioButton, radio, painter)
        finally:
            painter.restore()

    @staticmethod
    def __radio_rect(option: QStyleOptionViewItem) -> QRect:
        """The radio indicator's rect, centered in ``option.rect``."""
        style = option.widget.style() if option.widget is not None else QApplication.style()
        width = style.pixelMetric(QStyle.PixelMetric.PM_ExclusiveIndicatorWidth)
        height = style.pixelMetric(QStyle.PixelMetric.PM_ExclusiveIndicatorHeight)
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
        ):
            return super().editorEvent(event, model, option, index)
        if not self.__radio_rect(option).contains(event.position().toPoint()):
            return False
        return model.setData(index, Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
