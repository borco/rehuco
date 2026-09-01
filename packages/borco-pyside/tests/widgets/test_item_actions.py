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
# doesn't exist yet at module import time (pytest-qt builds one per session, inside a fixture). The
# native spelling of a key is platform-specific -- macOS renders Ctrl+Up as the glyphs "⌘↑" -- so the
# expected tooltip suffix is asked of Qt at assert time rather than written out here.
ACTIONS_WITH_SHORTCUTS = [
    (InsertItemAction, Qt.Key.Key_Insert),
    (EditItemAction, Qt.Key.Key_F2),
    (DeleteItemAction, QKeySequence.StandardKey.Delete),
    (MoveToTopItemAction, Qt.KeyboardModifier.ControlModifier | Qt.Key.Key_Home),
    (MoveUpItemAction, Qt.KeyboardModifier.ControlModifier | Qt.Key.Key_Up),
    (MoveDownItemAction, Qt.KeyboardModifier.ControlModifier | Qt.Key.Key_Down),
    (MoveToBottomItemAction, Qt.KeyboardModifier.ControlModifier | Qt.Key.Key_End),
]


@mark.parametrize("action_class,key", ACTIONS_WITH_SHORTCUTS)
def test_the_action_carries_its_own_shortcut(action_class: type[QAction], key: Any, qapp: Any) -> None:
    """Each action is self-contained: its shortcut is set the moment it is built, not by a column.

    **Test steps:**

    * build the action
    * verify it carries the shortcut and names it, in native form, in its own tooltip

    :param action_class: the action type under test.
    :param key: the key data its shortcut is built from.
    :param qapp: pytest-qt's application fixture -- a ``QAction`` needs one, and asking for it here is
        what stops this test passing only when something else built one first on the same worker.
    """
    del qapp
    action = action_class()
    sequence = QKeySequence(key)

    assert action.shortcut() == sequence
    assert action.toolTip().endswith(f" ({sequence.toString(QKeySequence.SequenceFormat.NativeText)})")


@mark.parametrize("action_class", [action_class for action_class, *_ in ACTIONS_WITH_SHORTCUTS])
def test_the_shortcut_is_armed_by_the_widget_it_is_added_to_not_by_the_action(
    action_class: type[QAction],
    qapp: Any,
) -> None:
    """The context is `WidgetShortcut`, so whoever calls ``addAction`` decides whose focus arms it.

    **Test steps:**

    * build the action
    * verify its shortcut context is the widget-only one

    :param action_class: the action type under test.
    :param qapp: pytest-qt's application fixture; see :func:`test_the_action_carries_its_own_shortcut`.
    """
    del qapp
    action = action_class()

    assert action.shortcutContext() == Qt.ShortcutContext.WidgetShortcut


def test_reset_carries_no_shortcut(qapp: Any) -> None:
    """Reset is list-wide, not tied to a current row, so nothing on the view should fire it by key.

    **Test steps:**

    * build the action
    * verify it carries no shortcut and its tooltip names none

    :param qapp: pytest-qt's application fixture; see :func:`test_the_action_carries_its_own_shortcut`.
    """
    del qapp
    action = ResetItemAction()

    assert action.shortcut().isEmpty()
    assert action.toolTip() == "Replace the list with the default entries"
