"""Tests for ActionButtonColumn: a strip of icon-only tool buttons, each a view of one action."""

from borco_pyside.widgets import ActionButtonColumn
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QSizePolicy, QToolButton
from pytestqt.qtbot import QtBot


def buttons(column: ActionButtonColumn) -> list[QToolButton]:
    """The column's buttons, in the order they were added.

    :param column: the column to read.
    :returns: every tool button it holds.
    """
    return column.findChildren(QToolButton)


def test_add_action_appends_a_button_showing_it(qtbot: QtBot) -> None:
    """Each added action gets a button whose *default* action it is, in the order added.

    **Test steps:**

    * build a column and add two actions
    * verify two buttons appeared, each showing the matching action as its default action
    """
    column = ActionButtonColumn()
    qtbot.addWidget(column)

    first = column.add_action("First", "Do the first thing")
    second = column.add_action("Second", "Do the second thing")

    assert [button.defaultAction() for button in buttons(column)] == [first, second]


def test_a_shortcut_is_set_on_the_action_and_named_in_its_tooltip(qtbot: QtBot) -> None:
    """An icon-only button is nowhere to read a key off, so the tooltip names it.

    **Test steps:**

    * add an action with a shortcut
    * verify the action carries it, and that the tooltip is the given text plus the key
    """
    column = ActionButtonColumn()
    qtbot.addWidget(column)

    action = column.add_action("Insert", "Insert a new entry", QKeySequence(Qt.Key.Key_Insert))

    assert action.shortcut() == QKeySequence(Qt.Key.Key_Insert)
    assert action.toolTip() == "Insert a new entry (Ins)"


def test_a_shortcut_is_armed_by_the_widget_it_is_added_to_not_by_the_column(qtbot: QtBot) -> None:
    """The context is `WidgetShortcut`, so whoever calls ``addAction`` decides whose focus arms it.

    That indirection is what lets a list editor arm these on its list alone, leaving an open in-place
    editor's own key handling untouched.

    **Test steps:**

    * add an action with a shortcut
    * verify its shortcut context is the widget-only one
    """
    column = ActionButtonColumn()
    qtbot.addWidget(column)

    action = column.add_action("Delete", "Drop it", QKeySequence(QKeySequence.StandardKey.Delete))

    assert action.shortcutContext() == Qt.ShortcutContext.WidgetShortcut


def test_an_action_without_a_shortcut_keeps_its_tooltip_verbatim(qtbot: QtBot) -> None:
    """Nothing is appended when there is no key to name.

    **Test steps:**

    * add an action with no shortcut
    * verify its tooltip is exactly what was given, and it carries no shortcut
    """
    column = ActionButtonColumn()
    qtbot.addWidget(column)

    action = column.add_action("Reset", "Put the defaults back")

    assert action.toolTip() == "Put the defaults back"
    assert action.shortcut().isEmpty()


def test_the_button_mirrors_its_actions_enabled_state(qtbot: QtBot) -> None:
    """Enabling lives on the action -- a button showing a default action follows it (#104).

    **Test steps:**

    * add an action and disable it
    * verify the button went with it, and comes back when the action does
    """
    column = ActionButtonColumn()
    qtbot.addWidget(column)
    action = column.add_action("Edit", "Retype it")

    action.setEnabled(False)
    assert buttons(column)[0].isEnabled() is False

    action.setEnabled(True)
    assert buttons(column)[0].isEnabled() is True


def test_add_action_button_takes_an_action_built_elsewhere(qtbot: QtBot) -> None:
    """A caller with an action already in hand appends a button for it directly.

    **Test steps:**

    * build an action outside the column and hand it to ``add_action_button``
    * verify the returned button shows it
    """
    column = ActionButtonColumn()
    qtbot.addWidget(column)
    action = QAction("Elsewhere", column)

    button = column.add_action_button(action)

    assert button.defaultAction() is action
    assert buttons(column) == [button]


def test_the_column_never_stretches_past_its_buttons(qtbot: QtBot) -> None:
    """It sits beside a list, so extra height would push its first button off the list's first row.

    **Test steps:**

    * build a column
    * verify both size policies are fixed
    """
    column = ActionButtonColumn()
    qtbot.addWidget(column)

    assert column.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Fixed
    assert column.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Fixed
