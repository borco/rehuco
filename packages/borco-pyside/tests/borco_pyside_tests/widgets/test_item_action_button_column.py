"""Tests for ItemEditActionsColumn and ItemOrderingActionsColumn: each wired straight to a
`ItemEditor`/`ItemOrderingEditor` and a shared `ItemViewer`, with no bundle in between.

The editor/ordering/viewer objects here are plain `QObject`s satisfying the three protocols
structurally -- Qt signals need a real `QObject`, but nothing here inherits from the protocols
themselves, which is the point of a `Protocol`.
"""

from borco_pyside.widgets import ItemEditActionsColumn, ItemOrderingActionsColumn
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QToolButton
from pytestqt.qtbot import QtBot


# region helpers
class FakeEditor(QObject):
    """A bare `ItemEditor`: records every call, insert appends one past whatever it is given."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[object, ...]] = []

    def insert(self, at: int) -> int:
        """Record the call and report the row after ``at``."""
        self.calls.append(("insert", at))
        return at + 1

    def delete(self, at: int) -> None:
        """Record the call."""
        self.calls.append(("delete", at))

    def reset(self) -> None:
        """Record the call."""
        self.calls.append(("reset",))


class FakeOrderingEditor(QObject):
    """A bare `ItemOrderingEditor`: records every call, each move reports a fixed, distinguishable result."""

    count_changed = Signal()

    def __init__(self, count: int = 5) -> None:
        super().__init__()
        self.calls: list[tuple[object, ...]] = []
        self.count_value = count

    @property
    def count(self) -> int:
        """How many entries there are."""
        return self.count_value

    def move_to_top(self, at: int) -> int:
        """Record the call and report row 0."""
        self.calls.append(("move_to_top", at))
        return 0

    def move_up(self, at: int) -> int:
        """Record the call and report the row above ``at``."""
        self.calls.append(("move_up", at))
        return at - 1

    def move_down(self, at: int) -> int:
        """Record the call and report the row below ``at``."""
        self.calls.append(("move_down", at))
        return at + 1

    def move_to_bottom(self, at: int) -> int:
        """Record the call and report the last row."""
        self.calls.append(("move_to_bottom", at))
        return self.count_value - 1


class FakeViewer(QObject):
    """A bare `ItemViewer`: a settable current index, and a call log for `edit_current`."""

    current_index_changed = Signal()

    def __init__(self, current_index: int = -1) -> None:
        super().__init__()
        self.calls: list[tuple[object, ...]] = []
        self.__current_index = current_index

    @property
    def current_index(self) -> int:
        """The row currently selected."""
        return self.__current_index

    def set_current_index(self, row: int) -> None:
        """Record the call and select ``row``."""
        self.calls.append(("set_current_index", row))
        self.__current_index = row
        self.current_index_changed.emit()

    def edit_current(self) -> None:
        """Record the call."""
        self.calls.append(("edit_current",))


def button_for(column: ItemEditActionsColumn | ItemOrderingActionsColumn, action: object) -> QToolButton:
    """The button showing ``action`` inside ``column``.

    :param column: the column to search.
    :param action: the action whose button to find.
    :returns: the matching button.
    """
    return next(button for button in column.findChildren(QToolButton) if button.defaultAction() is action)


def build_edit_column(editor: FakeEditor, viewer: FakeViewer) -> ItemEditActionsColumn:
    """Build an `ItemEditActionsColumn` over the given fakes.

    :param editor: the fake `ItemEditor`.
    :param viewer: the fake `ItemViewer`.
    :returns: the built column.
    """
    # the ignore is the same one bind_value_widget's callers need, for the same reason: PySide types a
    # class-level ``Signal`` as ``Signal``, not as the ``SignalInstance`` an *instance* actually
    # exposes, so no fake declaring one ever satisfies the protocol statically
    return ItemEditActionsColumn(editor, viewer)  # type: ignore[arg-type]


def build_ordering_column(editor: FakeOrderingEditor, viewer: FakeViewer) -> ItemOrderingActionsColumn:
    """Build an `ItemOrderingActionsColumn` over the given fakes.

    :param editor: the fake `ItemOrderingEditor`.
    :param viewer: the fake `ItemViewer`.
    :returns: the built column.
    """
    return ItemOrderingActionsColumn(editor, viewer)  # type: ignore[arg-type]  # see build_edit_column


# endregion


# region ItemEditActionsColumn
def test_insert_asks_the_editor_then_selects_and_opens_the_result(qtbot: QtBot) -> None:
    """Insert is the one action reading and writing both objects: ask the editor to insert after the
    viewer's current row, make the result current, and open it for typing.

    **Test steps:**

    * build the column over a viewer at row 2
    * trigger Insert
    * verify the editor was asked to insert after row 2, the viewer's current row became 3, and
      ``edit_current`` was called
    """
    editor = FakeEditor()
    viewer = FakeViewer(current_index=2)
    column = build_edit_column(editor, viewer)
    qtbot.addWidget(column)

    column.insert_action.trigger()

    assert editor.calls == [("insert", 2)]
    assert viewer.current_index == 3
    assert ("edit_current",) in viewer.calls


def test_edit_calls_the_viewer_directly(qtbot: QtBot) -> None:
    """Edit does not touch the editor at all -- opening the current entry is the viewer's alone.

    **Test steps:**

    * build the column over a viewer at row 1 and trigger Edit
    * verify ``edit_current`` was called and the editor was never touched
    """
    editor = FakeEditor()
    viewer = FakeViewer(current_index=1)
    column = build_edit_column(editor, viewer)
    qtbot.addWidget(column)

    column.edit_action.trigger()

    assert viewer.calls == [("edit_current",)]
    assert not editor.calls


def test_delete_asks_the_editor_for_the_current_row(qtbot: QtBot) -> None:
    """Delete reads the row to drop from the viewer.

    **Test steps:**

    * build the column over a viewer at row 3 and trigger Delete
    * verify the editor was asked to delete row 3
    """
    editor = FakeEditor()
    viewer = FakeViewer(current_index=3)
    column = build_edit_column(editor, viewer)
    qtbot.addWidget(column)

    column.delete_action.trigger()

    assert editor.calls == [("delete", 3)]


def test_reset_calls_the_editor_with_no_row(qtbot: QtBot) -> None:
    """Reset is list-wide -- it neither reads nor needs a current row.

    **Test steps:**

    * build the column and trigger Reset
    * verify the editor's ``reset`` was called
    """
    editor = FakeEditor()
    viewer = FakeViewer()
    column = build_edit_column(editor, viewer)
    qtbot.addWidget(column)

    column.reset_action.trigger()

    assert editor.calls == [("reset",)]


def test_edit_and_delete_answer_to_whether_there_is_a_current_row(qtbot: QtBot) -> None:
    """Insert and Reset are list-wide; Edit and Delete need something to act on.

    **Test steps:**

    * build the column with no current row and verify Edit/Delete are off, Insert/Reset are on
    * move the viewer's current row and verify Edit/Delete come on
    """
    editor = FakeEditor()
    viewer = FakeViewer(current_index=-1)
    column = build_edit_column(editor, viewer)
    qtbot.addWidget(column)

    assert column.insert_action.isEnabled() is True
    assert column.reset_action.isEnabled() is True
    assert column.edit_action.isEnabled() is False
    assert column.delete_action.isEnabled() is False

    viewer.set_current_index(0)

    assert column.edit_action.isEnabled() is True
    assert column.delete_action.isEnabled() is True


def test_hiding_the_reset_action_hides_its_button(qtbot: QtBot) -> None:
    """An editor with no reset concept hides the button by hiding the action -- no bespoke API needed.

    **Test steps:**

    * build the column and hide the reset action
    * verify its button follows
    """
    column = build_edit_column(FakeEditor(), FakeViewer())
    qtbot.addWidget(column)
    column.show()
    button = button_for(column, column.reset_action)
    assert button.isVisible() is True

    column.reset_action.setVisible(False)

    assert button.isVisible() is False


# endregion


# region ItemOrderingActionsColumn
def test_each_move_asks_the_editor_and_selects_its_result(qtbot: QtBot) -> None:
    """Every move reads the row from the viewer, hands it to the matching editor method, and makes the
    result current.

    **Test steps:**

    * build the column over a viewer at row 2 and trigger each of the four moves in turn
    * verify each called the matching editor method with the viewer's row at the time, and the
      viewer's current row followed the editor's answer
    """
    editor = FakeOrderingEditor(count=5)
    viewer = FakeViewer(current_index=2)
    column = build_ordering_column(editor, viewer)
    qtbot.addWidget(column)

    column.move_up_action.trigger()
    assert editor.calls[-1] == ("move_up", 2)
    assert viewer.current_index == 1

    column.move_down_action.trigger()
    assert editor.calls[-1] == ("move_down", 1)
    assert viewer.current_index == 2

    column.move_to_top_action.trigger()
    assert editor.calls[-1] == ("move_to_top", 2)
    assert viewer.current_index == 0

    column.move_to_bottom_action.trigger()
    assert editor.calls[-1] == ("move_to_bottom", 0)
    assert viewer.current_index == 4


def test_every_move_needs_a_current_row(qtbot: QtBot) -> None:
    """With nothing selected, none of the four moves have anything to act on.

    **Test steps:**

    * build the column with no current row
    * verify all four actions are off
    """
    column = build_ordering_column(FakeOrderingEditor(), FakeViewer(current_index=-1))
    qtbot.addWidget(column)

    assert column.move_to_top_action.isEnabled() is False
    assert column.move_up_action.isEnabled() is False
    assert column.move_down_action.isEnabled() is False
    assert column.move_to_bottom_action.isEnabled() is False


def test_the_upward_pair_is_off_at_the_first_row_the_downward_pair_at_the_last(qtbot: QtBot) -> None:
    """A move that cannot go anywhere is off, so the buttons say where the entry already is.

    **Test steps:**

    * build the column with three entries, select the first row
    * verify up/top are off, down/bottom are on
    * select the last row and verify the reverse
    """
    editor = FakeOrderingEditor(count=3)
    viewer = FakeViewer(current_index=0)
    column = build_ordering_column(editor, viewer)
    qtbot.addWidget(column)

    assert (column.move_to_top_action.isEnabled(), column.move_up_action.isEnabled()) == (False, False)
    assert (column.move_down_action.isEnabled(), column.move_to_bottom_action.isEnabled()) == (True, True)

    viewer.set_current_index(2)

    assert (column.move_to_top_action.isEnabled(), column.move_up_action.isEnabled()) == (True, True)
    assert (column.move_down_action.isEnabled(), column.move_to_bottom_action.isEnabled()) == (False, False)


def test_a_count_change_re_evaluates_the_downward_pair(qtbot: QtBot) -> None:
    """The list can shrink out from under the current row without its index moving at all.

    **Test steps:**

    * build the column with the current row already at the (three-entry) end
    * shrink the editor's count to match a row that is now itself the new last one
    * verify `count_changed` alone is enough to re-evaluate the downward pair
    """
    editor = FakeOrderingEditor(count=3)
    viewer = FakeViewer(current_index=2)
    column = build_ordering_column(editor, viewer)
    qtbot.addWidget(column)
    assert column.move_down_action.isEnabled() is False

    editor.count_value = 5
    editor.count_changed.emit()

    assert column.move_down_action.isEnabled() is True


# endregion
