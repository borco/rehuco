"""Tests for ItemActionsColumn and ItemOrderingColumn: the two standard list-editor action columns."""

from borco_pyside.widgets import ItemActionsColumn, ItemOrderingColumn
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QToolButton
from pytestqt.qtbot import QtBot

# region helpers


def shown_actions(column: ItemActionsColumn | ItemOrderingColumn) -> list[QAction]:
    """Every action the column shows a button for, in column order.

    :param column: the column to read.
    :returns: the buttons' default actions.
    """
    return [button.defaultAction() for button in column.findChildren(QToolButton)]


def shortcuts(column: ItemActionsColumn | ItemOrderingColumn) -> list[str]:
    """Each shown action's shortcut, in column order.

    :param column: the column to read.
    :returns: the portable spelling of every action's key, blank for one with none.
    """
    return [action.shortcut().toString() for action in shown_actions(column)]


# endregion

# region ItemActionsColumn tests


def test_the_item_column_shows_insert_edit_delete_reset_in_that_order(qtbot: QtBot) -> None:
    """The four actions that change what a list holds, in the order they are read in.

    **Test steps:**

    * build the column
    * verify its buttons show exactly the four named actions, in order
    """
    column = ItemActionsColumn()
    qtbot.addWidget(column)

    assert shown_actions(column) == [
        column.insert_action,
        column.edit_action,
        column.delete_action,
        column.reset_action,
    ]


def test_the_item_columns_shortcuts_are_the_conventional_ones(qtbot: QtBot) -> None:
    """Ins/F2/Del are what a list is already expected to answer to; Reset is list-wide and has none.

    **Test steps:**

    * build the column
    * verify each action's shortcut
    """
    column = ItemActionsColumn()
    qtbot.addWidget(column)

    assert shortcuts(column) == ["Ins", "F2", "Del", ""]


# endregion

# region ItemOrderingColumn tests


def test_the_ordering_column_shows_top_up_down_bottom_in_that_order(qtbot: QtBot) -> None:
    """The four actions that change where a row sits, laid out the way they move it.

    **Test steps:**

    * build the column
    * verify its buttons show exactly the four named actions, in order
    """
    column = ItemOrderingColumn()
    qtbot.addWidget(column)

    assert shown_actions(column) == [
        column.move_to_top_action,
        column.move_up_action,
        column.move_down_action,
        column.move_to_bottom_action,
    ]


def test_the_ordering_columns_shortcuts_are_the_arrow_and_jump_keys_with_control(qtbot: QtBot) -> None:
    """Ctrl + the key that would *navigate* there moves the row there instead.

    **Test steps:**

    * build the column
    * verify each action's shortcut
    """
    column = ItemOrderingColumn()
    qtbot.addWidget(column)

    assert shortcuts(column) == ["Ctrl+Home", "Ctrl+Up", "Ctrl+Down", "Ctrl+End"]


# endregion

# region both columns


def test_neither_column_ships_an_icon(qtbot: QtBot) -> None:
    """A generic library guessing at a glyph is worse than the app supplying one, so it supplies none.

    **Test steps:**

    * build both columns
    * verify every action's icon is null, ready for the consuming app to set
    """
    items = ItemActionsColumn()
    ordering = ItemOrderingColumn()
    qtbot.addWidget(items)
    qtbot.addWidget(ordering)

    assert all(action.icon().isNull() for action in shown_actions(items) + shown_actions(ordering))


# endregion
