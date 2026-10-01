"""Tests for `ShortcutsTableView`: the shortcuts table as a settings value control (#344)."""

from typing import Any

from borco_pyside.shortcuts import Command, CommandRegistry, CommandScope, Keymap
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


def test_a_value_that_is_not_a_keymap_is_ignored(view: ShortcutsTableView) -> None:
    """Only a keymap `settings_value` returned is written back.

    **Test steps:**

    * write a string into the view
    * verify the draft is unchanged
    """
    before = view.settings_value()

    view.set_settings_value("not a keymap")

    assert view.settings_value() == before


def test_a_view_without_a_shortcuts_model_has_no_value(qtbot: QtBot) -> None:
    """With no model there is nothing to read or write.

    **Test steps:**

    * build a view with no model
    * verify its value is ``None`` and writing to it does nothing
    """
    bare = ShortcutsTableView()
    qtbot.addWidget(bare)

    bare.set_settings_value(Keymap())

    assert bare.settings_value() is None
