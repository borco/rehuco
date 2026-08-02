"""Tests for the individual item actions: each a self-contained `QAction`."""

from typing import Any

from borco_pyside.widgets import (
    DeleteItemAction,
    EditItemAction,
    InsertItemAction,
    MoveDownItemAction,
    MoveToBottomItemAction,
    MoveToTopItemAction,
    MoveUpItemAction,
    ResetItemAction,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from pytest import mark

# Qt key data only, no `QKeySequence`/`QAction` instances -- those need a `QApplication`, which
# doesn't exist yet at module import time (pytest-qt builds one per session, inside a fixture).
ACTIONS_WITH_SHORTCUTS = [
    (InsertItemAction, Qt.Key.Key_Insert, "Ins"),
    (EditItemAction, Qt.Key.Key_F2, "F2"),
    (DeleteItemAction, QKeySequence.StandardKey.Delete, "Del"),
    (MoveToTopItemAction, Qt.KeyboardModifier.ControlModifier | Qt.Key.Key_Home, "Ctrl+Home"),
    (MoveUpItemAction, Qt.KeyboardModifier.ControlModifier | Qt.Key.Key_Up, "Ctrl+Up"),
    (MoveDownItemAction, Qt.KeyboardModifier.ControlModifier | Qt.Key.Key_Down, "Ctrl+Down"),
    (MoveToBottomItemAction, Qt.KeyboardModifier.ControlModifier | Qt.Key.Key_End, "Ctrl+End"),
]


@mark.parametrize("action_class,key,native", ACTIONS_WITH_SHORTCUTS)
def test_the_action_carries_its_own_shortcut(action_class: type[QAction], key: Any, native: str) -> None:
    """Each action is self-contained: its shortcut is set the moment it is built, not by a column.

    **Test steps:**

    * build the action
    * verify it carries the shortcut and names it, in native form, in its own tooltip
    """
    action = action_class()

    assert action.shortcut() == QKeySequence(key)
    assert native in action.toolTip()


@mark.parametrize("action_class", [action_class for action_class, *_ in ACTIONS_WITH_SHORTCUTS])
def test_the_shortcut_is_armed_by_the_widget_it_is_added_to_not_by_the_action(
    action_class: type[QAction],
) -> None:
    """The context is `WidgetShortcut`, so whoever calls ``addAction`` decides whose focus arms it.

    **Test steps:**

    * build the action
    * verify its shortcut context is the widget-only one
    """
    action = action_class()

    assert action.shortcutContext() == Qt.ShortcutContext.WidgetShortcut


def test_reset_carries_no_shortcut() -> None:
    """Reset is list-wide, not tied to a current row, so nothing on the view should fire it by key.

    **Test steps:**

    * build the action
    * verify it carries no shortcut and its tooltip names none
    """
    action = ResetItemAction()

    assert action.shortcut().isEmpty()
    assert action.toolTip() == "Replace the list with the default entries"
