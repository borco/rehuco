"""Tests for LocationReplacementsEditor's table painting and its check cell (#383)."""

from borco_pyside.widgets import RowBandDelegate
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QStyle, QStyleOptionViewItem
from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.settings.location_replacements_settings import ReplacementRule
from rehuco_agent.settings.ui.location_replacements_editor import LocationReplacementsEditor
from rehuco_agent.settings.ui.location_replacements_model import REGEX_COLUMN


@fixture(name="editor")
def fixture_editor(qtbot: QtBot) -> LocationReplacementsEditor:
    """An editor over one plain rule, shown.

    :param qtbot: the widget-owning fixture.
    :returns: the editor.
    """
    widget = LocationReplacementsEditor()
    qtbot.addWidget(widget)
    widget.values = [ReplacementRule("a", "b", False)]
    with qtbot.waitExposed(widget):
        widget.show()
    return widget


def test_the_regexp_cell_still_toggles_through_the_shared_delegate(editor: LocationReplacementsEditor) -> None:
    """The check indicator is drawn where the base `editorEvent` hit-tests it, so a click on it toggles.

    **Test steps:**

    * release the mouse over the Regexp cell's check indicator
    * verify the rule's flag flipped
    """
    view = editor.view
    index = editor.model.index(0, REGEX_COLUMN)
    delegate = view.itemDelegateForIndex(index)
    assert isinstance(delegate, RowBandDelegate)
    option = QStyleOptionViewItem()
    option.rect = view.visualRect(index)
    option.state |= QStyle.StateFlag.State_Enabled
    option.widget = view
    delegate.initStyleOption(option, index)
    indicator = view.style().subElementRect(QStyle.SubElement.SE_ItemViewItemCheckIndicator, option, view)
    point = QPointF(indicator.center())
    event = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        point,
        point,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )

    assert delegate.editorEvent(event, editor.model, option, index) is True
    assert editor.model.data(index, Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
