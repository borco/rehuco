"""Tests for apply_item_action_icons: this app's glyphs on a list editor's actions (#231, #97)."""

from borco_pyside.widgets import StringListEditor
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QToolButton
from pytestqt.qtbot import QtBot
from rehuco_agent.item_action_icons import ICONS_BY_ACTION_TYPE, apply_item_action_icons


def test_every_action_the_editor_builds_is_mapped_and_carries_an_icon(qtbot: QtBot) -> None:
    """Every action a `StringListEditor` builds -- including the always-present Reset -- is in the map
    and gets dressed, whether or not its button is currently shown. The map being *complete* is the
    point: an action the toolkit grew that nobody mapped would otherwise ship as a blank button (#322).

    **Test steps:**

    * build an editor and dress it
    * verify every button's action is of a mapped type and ends up with a non-null icon
    """
    editor = StringListEditor()
    qtbot.addWidget(editor)

    apply_item_action_icons(editor)

    for column in (editor.item_actions, editor.ordering_actions):
        for button in column.findChildren(QToolButton):
            action = button.defaultAction()
            assert type(action) in ICONS_BY_ACTION_TYPE, f"{action.text()} is not mapped to an icon"
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
