"""Tests for StringItemListModel: a flat list of strings, and the `ItemEditor`/`ItemOrderingEditor`
surface built on top of it.
"""

from borco_pyside.widgets import StringItemListModel
from PySide6.QtCore import QModelIndex, Qt
from pytest import fixture


# region helpers
@fixture
def model() -> StringItemListModel:
    """A model over three entries, with two defaults.

    :returns: the seeded model.
    """
    subject = StringItemListModel(defaults=("*.tmp", "Thumbs.db"))
    subject.set_entries(["one", "two", "three"])
    return subject


# endregion


# region Qt model interface
def test_the_rows_are_the_entries(model: StringItemListModel) -> None:
    """One row per entry, in order.

    **Test steps:**

    * read the model's row count and each cell
    * verify they match the seeded entries
    """
    assert model.rowCount() == 3
    for row, value in enumerate(("one", "two", "three")):
        assert model.data(model.index(row, 0)) == value


def test_a_child_index_holds_nothing(model: StringItemListModel) -> None:
    """The list is flat, so anything under a row is outside the model.

    **Test steps:**

    * ask for the row count under a valid index
    * verify it is zero, and an invalid index carries no data and no flags
    """
    parent = model.index(0, 0)

    assert model.rowCount(parent) == 0
    assert model.data(QModelIndex()) is None
    assert model.flags(QModelIndex()) == Qt.ItemFlag.NoItemFlags


def test_every_cell_is_editable(model: StringItemListModel) -> None:
    """A row is typed in place.

    **Test steps:**

    * read the flags of the first cell
    * verify it is enabled, selectable and editable
    """
    flags = model.flags(model.index(0, 0))

    assert flags & Qt.ItemFlag.ItemIsEditable
    assert flags & Qt.ItemFlag.ItemIsEnabled
    assert flags & Qt.ItemFlag.ItemIsSelectable


def test_setting_the_same_text_is_refused(model: StringItemListModel) -> None:
    """An edit that changes nothing is not an edit.

    **Test steps:**

    * record every ``dataChanged`` and commit the text a cell already holds
    * verify the model refused it and said nothing
    """
    changes: list[QModelIndex] = []
    model.dataChanged.connect(lambda *args: changes.append(args[0]))

    assert model.setData(model.index(0, 0), "one") is False
    assert not changes


def test_setting_new_text_commits_it(model: StringItemListModel) -> None:
    """A real edit lands verbatim -- unnormalized, since normalizing is the owner's.

    **Test steps:**

    * commit padded, mixed-case text
    * verify it is stored exactly as given
    """
    assert model.setData(model.index(0, 0), "  MiXeD  ") is True

    assert model.entries[0] == "  MiXeD  "


def test_an_edit_outside_the_model_is_refused(model: StringItemListModel) -> None:
    """An invalid index, or a role that is not the edit role, writes nothing.

    **Test steps:**

    * commit into an invalid index, and into a valid one under the display role
    * verify both were refused
    """
    assert model.setData(QModelIndex(), "x", Qt.ItemDataRole.EditRole) is False
    assert model.setData(model.index(0, 0), "x", Qt.ItemDataRole.DisplayRole) is False


def test_a_row_operation_under_a_parent_is_refused(model: StringItemListModel) -> None:
    """There is nothing under a row, so nothing can be inserted, removed or moved there.

    **Test steps:**

    * insert, remove and move under a valid index
    * verify all three were refused and the list is untouched
    """
    parent = model.index(0, 0)

    assert model.insertRow(0, parent) is False
    assert model.removeRow(0, parent) is False
    assert model.moveRow(parent, 0, QModelIndex(), 1) is False
    assert model.moveRow(QModelIndex(), 0, parent, 1) is False
    assert model.rowCount() == 3


def test_a_row_operation_outside_the_list_is_refused(model: StringItemListModel) -> None:
    """A row past the end, or none at all, names nothing to act on.

    **Test steps:**

    * insert past the end, insert nothing, and remove past the end
    * verify all three were refused
    """
    assert model.insertRow(4) is False
    assert model.insertRows(0, 0) is False
    assert model.removeRow(3) is False
    assert model.removeRows(0, 0) is False


def test_a_move_that_would_leave_the_list_as_it_was_is_refused(model: StringItemListModel) -> None:
    """A no-op move is not an edit, and reporting one would be a lie.

    **Test steps:**

    * move a row to where it already is
    * verify the model refused it
    """
    assert model.moveRow(QModelIndex(), 0, QModelIndex(), 0) is False


# endregion


# region entries / defaults
def test_setting_the_entries_it_already_holds_changes_nothing(model: StringItemListModel) -> None:
    """A caller handing back what it just read must not rebuild the rows under an open editor.

    **Test steps:**

    * record every reset and set the entries the model already reports
    * verify nothing was reported
    """
    resets: list[int] = []
    model.modelReset.connect(lambda: resets.append(1))

    model.set_entries(list(model.entries))

    assert not resets


def test_defaults_round_trips_and_is_settable(model: StringItemListModel) -> None:
    """What `reset` restores, readable and replaceable.

    **Test steps:**

    * read the seeded defaults, then replace them
    * verify both are what was given
    """
    assert model.defaults == ("*.tmp", "Thumbs.db")

    model.defaults = ("*.bak",)

    assert model.defaults == ("*.bak",)


# endregion


# region ItemEditor / ItemOrderingEditor
def test_insert_lands_after_the_given_row_and_returns_it(model: StringItemListModel) -> None:
    """A blank entry, not a normalized one -- normalizing what was typed is the owner's.

    **Test steps:**

    * insert after row 0
    * verify the new row is 1, holds a blank entry, and the count grew
    """
    new_row = model.insert(0)

    assert new_row == 1
    assert model.entries[1] == ""
    assert model.count == 4


def test_insert_appends_with_no_current_row(model: StringItemListModel) -> None:
    """A negative row names nothing to insert after, so the new entry goes last.

    **Test steps:**

    * insert with a negative row
    * verify the new entry landed at the end
    """
    new_row = model.insert(-1)

    assert new_row == 3
    assert model.entries[3] == ""


def test_delete_drops_the_given_row(model: StringItemListModel) -> None:
    """Delete acts on the row it is given.

    **Test steps:**

    * delete row 1
    * verify only that entry is gone
    """
    model.delete(1)

    assert model.entries == ("one", "three")


def test_delete_with_a_negative_row_does_nothing(model: StringItemListModel) -> None:
    """No row named is a no-op, not an error.

    **Test steps:**

    * delete with a negative row
    * verify nothing changed
    """
    model.delete(-1)

    assert model.count == 3


def test_reset_replaces_the_list_with_the_defaults(model: StringItemListModel) -> None:
    """A user who emptied the list has no other way back.

    **Test steps:**

    * empty the list, then reset
    * verify the defaults are back
    """
    model.set_entries(())

    model.reset()

    assert model.entries == ("*.tmp", "Thumbs.db")


def test_move_to_top_up_down_and_to_bottom_return_the_new_row(model: StringItemListModel) -> None:
    """Every move takes the row to act on and hands back where it ended up.

    **Test steps:**

    * move row 0 down, then to the bottom, then up, then to the top
    * verify each call's return value and the resulting order
    """
    assert model.move_down(0) == 1
    assert model.entries == ("two", "one", "three")

    assert model.move_to_bottom(1) == 2
    assert model.entries == ("two", "three", "one")

    assert model.move_up(2) == 1
    assert model.entries == ("two", "one", "three")

    assert model.move_to_top(1) == 0
    assert model.entries == ("one", "two", "three")


def test_a_move_out_of_range_or_unchanged_is_a_no_op_returning_the_original_row(model: StringItemListModel) -> None:
    """A move that cannot go anywhere, or names no row, leaves the list untouched.

    **Test steps:**

    * move a negative row, move row 0 to itself, and move row 0 above the top
    * verify each returns the row unchanged and nothing moved
    """
    assert model.move_up(-1) == -1
    assert model.move_to_top(0) == 0
    assert model.move_up(0) == 0
    assert model.entries == ("one", "two", "three")


def test_count_tracks_inserts_and_removes(model: StringItemListModel) -> None:
    """The `ItemOrderingEditor` contract: how many entries there are, and a signal when that changes.

    **Test steps:**

    * record every `count_changed` and insert, then delete
    * verify `count` follows and the signal fired for each
    """
    counts: list[int] = []
    model.count_changed.connect(lambda: counts.append(model.count))

    model.insert(-1)
    assert model.count == 4
    model.delete(0)
    assert model.count == 3

    assert counts == [4, 3]


def test_count_does_not_change_on_a_move(model: StringItemListModel) -> None:
    """Reordering never changes how many entries there are.

    **Test steps:**

    * record every `count_changed` and move an entry
    * verify it never fired
    """
    counts: list[int] = []
    model.count_changed.connect(lambda: counts.append(1))

    model.move_down(0)

    assert not counts


# endregion
