"""Tests for `ShortcutsTableView`: the shortcuts table as a settings value control (#344)."""

from typing import Any

from borco_pyside.shortcuts import Command, CommandRegistry, CommandScope
from PySide6.QtGui import QKeySequence
from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.settings.ui.settings_frame_filter import ValueControl
from rehuco_agent.settings.ui.shortcuts_table_model import ShortcutsFilterProxyModel, ShortcutsTableModel
from rehuco_agent.settings.ui.shortcuts_table_view import ShortcutsTableView

SAVE = Command("test.save", "Save", "Save the focused document", ("Ctrl+S",), (CommandScope.WINDOW,))


@fixture
def view(qtbot: QtBot, qapp: Any) -> ShortcutsTableView:
    """A view over a one-command model, reached through a filter proxy as on the page.

    :param qtbot: the widget-owning fixture.
    :param qapp: the application the key classes need.
    :returns: the view.
    """
    del qapp
    registry = CommandRegistry()
    registry.register(SAVE)
    model = ShortcutsTableModel(registry)
    model.set_draft(registry.keymap)
    proxy = ShortcutsFilterProxyModel()
    proxy.setSourceModel(model)
    widget = ShortcutsTableView()
    qtbot.addWidget(widget)
    widget.setModel(proxy)
    return widget


def test_the_view_is_a_value_control(view: ShortcutsTableView) -> None:
    """The settings frame filter recognises it by shape.

    **Test steps:**

    * check the view against the `ValueControl` protocol
    """
    assert isinstance(view, ValueControl)


def test_the_value_round_trips_through_the_draft(view: ShortcutsTableView) -> None:
    """What `settings_value` returned writes back, and a changed draft compares unequal.

    **Test steps:**

    * capture the value, edit the draft through the model, capture again
    * verify the two differ, then write the first back and verify the draft matches it
    """
    proxy = view.model()
    model = proxy.sourceModel()  # type: ignore[attr-defined]
    before = view.settings_value()

    model.set_entry(SAVE.id, [QKeySequence("Ctrl+Shift+S")], SAVE.default_scope)
    assert view.settings_value() != before

    view.set_settings_value(before)
    assert view.settings_value() == before
    assert model.keys_of(SAVE.id) == (QKeySequence("Ctrl+S"),)
