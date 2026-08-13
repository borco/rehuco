"""Tests for apply_item_action_icons: this app's glyphs on a list editor's actions (#231, #97)."""

from borco_pyside.widgets import StringListEditor
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QToolButton
from pytestqt.qtbot import QtBot
from rehuco_agent.item_action_icons import ICONS_BY_ACTION_TYPE, apply_item_action_icons


def test_every_mapped_action_type_carries_an_icon(qtbot: QtBot) -> None:
    """Every action a `StringListEditor` builds -- including the always-present Reset -- gets dressed,
    whether or not its button is currently shown.

    **Test steps:**

    * build an editor and dress it
    * verify every button's action, of a mapped type, ends up with a non-null icon
    """
    editor = StringListEditor()
    qtbot.addWidget(editor)

    apply_item_action_icons(editor)

    for column in (editor.item_actions, editor.ordering_actions):
        for button in column.findChildren(QToolButton):
            action = button.defaultAction()
            if type(action) in ICONS_BY_ACTION_TYPE:
                assert not action.icon().isNull(), f"{action.text()} carries no icon"


def test_an_action_of_an_unmapped_type_is_left_alone(qtbot: QtBot) -> None:
    """A button showing an action this app has no icon for is skipped, not guessed at.

    **Test steps:**

    * build an editor, add a button showing a plain `QAction`, and dress the editor
    * verify that action still carries no icon
    """
    editor = StringListEditor()
    qtbot.addWidget(editor)
    stray = QAction("Unmapped", editor.item_actions)
    editor.item_actions.add_action_button(stray)

    apply_item_action_icons(editor)

    assert stray.icon().isNull()
