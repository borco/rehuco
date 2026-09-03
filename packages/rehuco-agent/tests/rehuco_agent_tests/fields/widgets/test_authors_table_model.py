"""Tests for AuthorsTableModel: the ``authors`` list as name/URL rows, merged rather than rebuilt."""

from typing import Any

from PySide6.QtCore import QModelIndex, Qt
from pytest import fixture
from rehuco_agent.fields.widgets.authors_table_model import (
    INVALID_URL_REASON,
    MISSING_NAME_REASON,
    NAME_COLUMN,
    URL_COLUMN,
    AuthorsTableModel,
    canonical_author_entry,
)


# region helpers
@fixture
def model() -> AuthorsTableModel:
    """A model over two entries: one plain name, one record carrying a URL.

    :returns: the seeded model.
    """
    subject = AuthorsTableModel()
    subject.set_entries(["Alice", {"name": "Bob", "url": "https://example.com/bob"}])
    return subject


def cell(model: AuthorsTableModel, row: int, column: int, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
    """One cell's value under ``role``.

    :param model: the model to read.
    :param row: the row to read.
    :param column: the column to read.
    :param role: the item role; the display text by default.
    :returns: whatever the model answers with.
    """
    return model.data(model.index(row, column), role)


def edit(model: AuthorsTableModel, row: int, column: int, value: str) -> bool:
    """Type ``value`` into one cell, as the delegate's editor would.

    :param model: the model to edit.
    :param row: the row to edit.
    :param column: the column to edit.
    :param value: the text committed.
    :returns: whether the model took it.
    """
    return model.setData(model.index(row, column), value, Qt.ItemDataRole.EditRole)


# endregion


# region canonical form
def test_a_record_holding_nothing_but_a_name_reduces_to_that_name() -> None:
    """The canonical minimal form, so "are all entries simple?" stays a trivial test.

    **Test steps:**

    * canonicalize a ``{"name"}``-only record
    * verify it came back as the plain name
    """
    assert canonical_author_entry({"name": "Alice"}) == "Alice"


def test_a_record_carrying_anything_else_is_left_exactly_as_it_is() -> None:
    """A URL, or a key no editor here can show, is what makes an entry a record.

    **Test steps:**

    * canonicalize a record with a URL, and one with a key this build does not know
    * verify both came back untouched
    """
    with_url = {"name": "Alice", "url": "https://example.com"}
    with_unknown = {"name": "Alice", "pronouns": "they/them"}

    assert canonical_author_entry(with_url) == with_url
    assert canonical_author_entry(with_unknown) == with_unknown


def test_a_plain_name_is_already_canonical() -> None:
    """Nothing to reduce.

    **Test steps:**

    * canonicalize a plain string
    * verify it came back unchanged
    """
    assert canonical_author_entry("Alice") == "Alice"


# endregion


# region reading
def test_the_rows_are_the_entries_and_the_columns_are_name_and_url(model: AuthorsTableModel) -> None:
    """Two columns, titled, one row per author.

    **Test steps:**

    * read the seeded model's shape and header titles
    * verify both cells of both rows
    """
    assert model.rowCount() == 2
    assert model.columnCount() == 2
    titles = [
        model.headerData(column, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
        for column in (NAME_COLUMN, URL_COLUMN)
    ]
    assert titles == ["Name", "URL"]
    assert cell(model, 0, NAME_COLUMN) == "Alice"
    assert cell(model, 0, URL_COLUMN) == ""
    assert cell(model, 1, NAME_COLUMN) == "Bob"
    assert cell(model, 1, URL_COLUMN) == "https://example.com/bob"


def test_a_child_index_holds_nothing_at_all(model: AuthorsTableModel) -> None:
    """The list is flat, so anything under a row is outside the model.

    **Test steps:**

    * ask for the row and column counts under a valid index
    * verify both are zero, and that an invalid index carries no data and no flags
    """
    parent = model.index(0, NAME_COLUMN)

    assert model.rowCount(parent) == 0
    assert model.columnCount(parent) == 0
    assert model.data(QModelIndex()) is None
    assert model.flags(QModelIndex()) == Qt.ItemFlag.NoItemFlags


def test_every_cell_is_editable(model: AuthorsTableModel) -> None:
    """Both halves of an entry are typed in place.

    **Test steps:**

    * read the flags of both columns
    * verify each is enabled, selectable and editable
    """
    for column in (NAME_COLUMN, URL_COLUMN):
        flags = model.flags(model.index(0, column))
        assert flags & Qt.ItemFlag.ItemIsEditable
        assert flags & Qt.ItemFlag.ItemIsEnabled
        assert flags & Qt.ItemFlag.ItemIsSelectable


def test_only_the_horizontal_header_is_titled(model: AuthorsTableModel) -> None:
    """Row numbers say nothing about an author, and no other role has an answer here.

    **Test steps:**

    * ask for a vertical header title and for a non-display role
    * verify both are unanswered
    """
    assert model.headerData(0, Qt.Orientation.Vertical, Qt.ItemDataRole.DisplayRole) is None
    assert model.headerData(0, Qt.Orientation.Horizontal, Qt.ItemDataRole.ToolTipRole) is None


def test_a_role_the_model_has_no_answer_for_is_unanswered(model: AuthorsTableModel) -> None:
    """Anything past display, edit, tooltip and foreground is not this model's to fill in.

    **Test steps:**

    * ask a valid cell for its decoration
    * verify nothing came back
    """
    assert cell(model, 0, NAME_COLUMN, Qt.ItemDataRole.DecorationRole) is None


# endregion


# region validation
def test_an_emptied_name_is_flagged_where_it_was_typed(model: AuthorsTableModel) -> None:
    """The editor enforces a non-empty name by *saying so*, not by refusing the keystroke.

    **Test steps:**

    * empty a row's name
    * verify that cell reports the reason as a tooltip and colors itself
    """
    edit(model, 0, NAME_COLUMN, "")

    assert model.invalid_reason(0, NAME_COLUMN) == MISSING_NAME_REASON
    assert cell(model, 0, NAME_COLUMN, Qt.ItemDataRole.ToolTipRole) == MISSING_NAME_REASON
    assert cell(model, 0, NAME_COLUMN, Qt.ItemDataRole.ForegroundRole) is not None


def test_a_url_that_is_not_an_http_address_is_flagged(model: AuthorsTableModel) -> None:
    """A value the viewer would render as no link at all is said so where it was typed.

    **Test steps:**

    * type a non-http URL into a row
    * verify the URL cell reports the reason and colors itself, and the name cell does not
    """
    edit(model, 0, URL_COLUMN, "ftp://example.com/alice")

    assert model.invalid_reason(0, URL_COLUMN) == INVALID_URL_REASON
    assert cell(model, 0, URL_COLUMN, Qt.ItemDataRole.ToolTipRole) == INVALID_URL_REASON
    assert cell(model, 0, NAME_COLUMN, Qt.ItemDataRole.ForegroundRole) is None


def test_a_valid_row_is_flagged_nowhere(model: AuthorsTableModel) -> None:
    """A name with a proper link is exactly what this editor writes.

    **Test steps:**

    * read both cells of the seeded record row
    * verify neither carries a reason, a tooltip or a color
    """
    for column in (NAME_COLUMN, URL_COLUMN):
        assert model.invalid_reason(1, column) == ""
        assert cell(model, 1, column, Qt.ItemDataRole.ToolTipRole) is None
        assert cell(model, 1, column, Qt.ItemDataRole.ForegroundRole) is None


def test_an_empty_url_is_not_a_bad_one(model: AuthorsTableModel) -> None:
    """Most authors have no page to link to; that is the common case, not a fault.

    **Test steps:**

    * read the plain-name row's URL cell
    * verify it carries no reason
    """
    assert model.invalid_reason(0, URL_COLUMN) == ""


# endregion


# region editing
def test_renaming_a_record_keeps_its_url(model: AuthorsTableModel) -> None:
    """A row writes back into the entry it was built from, changing only the cell it owns.

    **Test steps:**

    * retype the record row's name
    * verify the entry kept its URL
    """
    assert edit(model, 1, NAME_COLUMN, "Bobby") is True

    assert model.entries[1] == {"name": "Bobby", "url": "https://example.com/bob"}


def test_editing_a_row_keeps_a_key_no_editor_here_can_show(model: AuthorsTableModel) -> None:
    """Dropping a key from a newer schema version on an entry nobody meant to touch is an invisible
    loss -- the worst kind (#97).

    **Test steps:**

    * seed an entry carrying a key beyond name and url, and retype its name
    * verify the unknown key survived
    """
    model.set_entries([{"name": "Alice", "url": "https://example.com", "pronouns": "they/them"}])

    edit(model, 0, NAME_COLUMN, "Alicia")

    assert model.entries[0] == {
        "name": "Alicia",
        "url": "https://example.com",
        "pronouns": "they/them",
    }


def test_the_entry_the_row_came_from_is_never_mutated(model: AuthorsTableModel) -> None:
    """The document hands its lists out by reference, so an edit builds a new record instead.

    **Test steps:**

    * seed the model from a record held onto outside it, then retype that row's name
    * verify the original record still reads as it did
    """
    original = {"name": "Bob", "url": "https://example.com/bob"}
    model.set_entries([original])

    edit(model, 0, NAME_COLUMN, "Bobby")

    assert original == {"name": "Bob", "url": "https://example.com/bob"}


def test_giving_a_plain_name_a_url_turns_it_into_a_record(model: AuthorsTableModel) -> None:
    """The record form is what carries a URL ([[field-schema#authors]]).

    **Test steps:**

    * type a URL onto the plain-name row
    * verify the entry became a ``{name, url}`` record
    """
    edit(model, 0, URL_COLUMN, "https://example.com/alice")

    assert model.entries[0] == {"name": "Alice", "url": "https://example.com/alice"}


def test_clearing_a_url_leaves_the_entry_a_plain_name_again(model: AuthorsTableModel) -> None:
    """Canonical minimal form: absent is not empty, and a record with only a name is a name.

    **Test steps:**

    * empty the record row's URL
    * verify the entry came back as a plain string
    """
    edit(model, 1, URL_COLUMN, "")

    assert model.entries[1] == "Bob"


def test_clearing_a_url_on_a_record_with_other_keys_keeps_it_a_record(model: AuthorsTableModel) -> None:
    """It is not a plain name: it carries something a name cannot.

    **Test steps:**

    * seed an entry with a URL and an unknown key, then empty its URL
    * verify the URL key is gone and the other one is not
    """
    model.set_entries([{"name": "Alice", "url": "https://example.com", "pronouns": "they/them"}])

    edit(model, 0, URL_COLUMN, "")

    assert model.entries[0] == {"name": "Alice", "pronouns": "they/them"}


def test_a_committed_value_is_stripped(model: AuthorsTableModel) -> None:
    """Surrounding whitespace is not part of a name or a link.

    **Test steps:**

    * commit a padded name
    * verify the stored entry has none of the padding
    """
    edit(model, 0, NAME_COLUMN, "  Alicia  ")

    assert model.entries[0] == "Alicia"


def test_committing_what_is_already_there_reports_nothing(model: AuthorsTableModel) -> None:
    """An edit that changes nothing is not an edit.

    **Test steps:**

    * record every ``dataChanged`` and commit the name a row already holds
    * verify the model refused it and said nothing
    """
    changes: list[QModelIndex] = []
    model.dataChanged.connect(lambda top_left, *_: changes.append(top_left))

    assert edit(model, 0, NAME_COLUMN, "Alice") is False
    assert not changes


def test_a_cell_edit_reports_the_whole_row(model: AuthorsTableModel) -> None:
    """A name can change what the URL cell's validity means, and an emptied URL rewrites the entry.

    **Test steps:**

    * record every ``dataChanged`` range and retype a name
    * verify the reported range spans both columns of that row
    """
    ranges: list[tuple[int, int]] = []
    model.dataChanged.connect(
        lambda top_left, bottom_right, *_: ranges.append((top_left.column(), bottom_right.column()))
    )

    edit(model, 0, NAME_COLUMN, "Alicia")

    assert ranges == [(NAME_COLUMN, URL_COLUMN)]


def test_an_edit_outside_the_model_is_refused(model: AuthorsTableModel) -> None:
    """An invalid index, or a role that is not the edit role, writes nothing.

    **Test steps:**

    * commit into an invalid index, and into a valid one under the display role
    * verify both were refused
    """
    assert model.setData(QModelIndex(), "Alice", Qt.ItemDataRole.EditRole) is False
    assert model.setData(model.index(0, NAME_COLUMN), "Alicia", Qt.ItemDataRole.DisplayRole) is False


# endregion


# region rows
def test_an_inserted_row_is_a_blank_name(model: AuthorsTableModel) -> None:
    """An entry with no name is not a record of anything yet.

    **Test steps:**

    * insert a row between the two entries
    * verify it is an empty plain string, and the others kept their places
    """
    assert model.insertRow(1) is True

    assert model.rowCount() == 3
    assert model.entries[1] == ""
    assert model.entries[0] == "Alice"


def test_a_removed_row_takes_its_entry_with_it(model: AuthorsTableModel) -> None:
    """Delete drops the author it points at.

    **Test steps:**

    * remove the first row
    * verify only the second entry is left
    """
    assert model.removeRow(0) is True

    assert model.entries == ({"name": "Bob", "url": "https://example.com/bob"},)


def test_a_row_moves_as_one_model_move(model: AuthorsTableModel) -> None:
    """Credit order is the data, so reordering is a first-class edit.

    **Test steps:**

    * record every ``rowsMoved`` and move the first entry past the second
    * verify the order changed and it was reported as a move
    """
    moves: list[int] = []
    model.rowsMoved.connect(lambda *_: moves.append(1))

    assert model.moveRow(QModelIndex(), 0, QModelIndex(), 2) is True

    assert [entry if isinstance(entry, str) else entry["name"] for entry in model.entries] == ["Bob", "Alice"]
    assert moves == [1]


def test_a_row_moves_back_up_as_well(model: AuthorsTableModel) -> None:
    """The destination is read in the pre-move row space, which differs by direction.

    **Test steps:**

    * move the second entry to the top
    * verify the order changed
    """
    assert model.moveRow(QModelIndex(), 1, QModelIndex(), 0) is True

    assert [entry if isinstance(entry, str) else entry["name"] for entry in model.entries] == ["Bob", "Alice"]


def test_a_row_operation_under_a_parent_is_refused(model: AuthorsTableModel) -> None:
    """There is nothing under a row, so nothing can be inserted, removed or moved there.

    **Test steps:**

    * insert, remove and move under a valid index
    * verify all three were refused and the list is untouched
    """
    parent = model.index(0, NAME_COLUMN)

    assert model.insertRow(0, parent) is False
    assert model.removeRow(0, parent) is False
    assert model.moveRow(parent, 0, QModelIndex(), 1) is False
    assert model.moveRow(QModelIndex(), 0, parent, 1) is False
    assert model.rowCount() == 2


def test_a_row_operation_outside_the_list_is_refused(model: AuthorsTableModel) -> None:
    """A row past the end, or none at all, names nothing to act on.

    **Test steps:**

    * insert past the end, insert nothing, and remove past the end
    * verify all three were refused
    """
    assert model.insertRow(3) is False
    assert model.insertRows(0, 0) is False
    assert model.removeRow(2) is False
    assert model.removeRows(0, 0) is False


def test_a_move_that_would_leave_the_list_as_it_was_is_refused(model: AuthorsTableModel) -> None:
    """A no-op move is not an edit, and reporting one would be a lie.

    **Test steps:**

    * move a row to where it already is
    * verify the model refused it
    """
    assert model.moveRow(QModelIndex(), 0, QModelIndex(), 0) is False


# endregion


# region replacing the whole list
def test_setting_the_entries_replaces_every_row(model: AuthorsTableModel) -> None:
    """The whole list arrives at once from the document.

    **Test steps:**

    * record every reset and set three entries
    * verify the rows are the new ones and it was one reset
    """
    resets: list[int] = []
    model.modelReset.connect(lambda: resets.append(1))

    model.set_entries(["Carol", "Dave", "Erin"])

    assert model.entries == ("Carol", "Dave", "Erin")
    assert resets == [1]


def test_setting_the_entries_it_already_holds_changes_nothing(model: AuthorsTableModel) -> None:
    """A caller handing back what it just read must not rebuild the rows under an open editor.

    **Test steps:**

    * record every reset and set the entries the model already reports
    * verify nothing was reported
    """
    resets: list[int] = []
    model.modelReset.connect(lambda: resets.append(1))

    model.set_entries(list(model.entries))

    assert not resets


def test_the_entries_are_canonical_however_they_arrived(model: AuthorsTableModel) -> None:
    """A hand-written file can hold a record with nothing but a name; it reads as that name.

    **Test steps:**

    * set a ``{"name"}``-only record
    * verify it reads back as the plain name, and setting *that* changes nothing further
    """
    resets: list[int] = []

    model.set_entries([{"name": "Carol"}])
    model.modelReset.connect(lambda: resets.append(1))

    assert model.entries == ("Carol",)

    model.set_entries(["Carol"])

    assert not resets


# endregion


# region ItemEditor / ItemOrderingEditor
def test_insert_lands_after_the_given_row_and_returns_it(model: AuthorsTableModel) -> None:
    """A blank entry, not a blank record -- an entry with no name is not a record of anything yet.

    **Test steps:**

    * insert after row 0
    * verify the new row is 1, holds a blank name, and the count grew
    """
    new_row = model.insert(0)

    assert new_row == 1
    assert model.entries[1] == ""
    assert model.count == 3


def test_insert_appends_with_no_current_row(model: AuthorsTableModel) -> None:
    """A negative row names nothing to insert after, so the new entry goes last.

    **Test steps:**

    * insert with a negative row
    * verify the new entry landed at the end
    """
    new_row = model.insert(-1)

    assert new_row == 2
    assert model.entries[2] == ""


def test_delete_drops_the_given_row(model: AuthorsTableModel) -> None:
    """Delete acts on the row it is given, not a row the model remembers.

    **Test steps:**

    * delete row 0
    * verify only the second entry is left
    """
    model.delete(0)

    assert model.entries == ({"name": "Bob", "url": "https://example.com/bob"},)


def test_delete_with_a_negative_row_does_nothing(model: AuthorsTableModel) -> None:
    """No row named is a no-op, not an error.

    **Test steps:**

    * delete with a negative row
    * verify nothing changed
    """
    model.delete(-1)

    assert model.count == 2


def test_reset_is_a_no_op(model: AuthorsTableModel) -> None:
    """Authors have no defaults concept at all.

    **Test steps:**

    * record every reset and call reset()
    * verify nothing changed and no model reset fired
    """
    resets: list[int] = []
    model.modelReset.connect(lambda: resets.append(1))

    model.reset()

    assert model.entries == ("Alice", {"name": "Bob", "url": "https://example.com/bob"})
    assert not resets


def test_move_to_top_up_down_and_to_bottom_return_the_new_row(model: AuthorsTableModel) -> None:
    """Every move takes the row to act on and hands back where it ended up.

    **Test steps:**

    * move row 1 to the top, then down, then to the bottom, then up
    * verify each call's return value and the resulting order
    """
    assert model.move_to_top(1) == 0
    assert [entry if isinstance(entry, str) else entry["name"] for entry in model.entries] == ["Bob", "Alice"]

    assert model.move_down(0) == 1
    assert [entry if isinstance(entry, str) else entry["name"] for entry in model.entries] == ["Alice", "Bob"]

    assert model.move_to_bottom(0) == 1
    assert [entry if isinstance(entry, str) else entry["name"] for entry in model.entries] == ["Bob", "Alice"]

    assert model.move_up(1) == 0
    assert [entry if isinstance(entry, str) else entry["name"] for entry in model.entries] == ["Alice", "Bob"]


def test_a_move_out_of_range_or_unchanged_is_a_no_op_returning_the_original_row(model: AuthorsTableModel) -> None:
    """A move that cannot go anywhere, or names no row, leaves the list untouched.

    **Test steps:**

    * move a negative row, move row 0 to itself, and move row 0 above the top
    * verify each returns the row unchanged and nothing moved
    """
    assert model.move_up(-1) == -1
    assert model.move_to_top(0) == 0
    assert model.move_up(0) == 0
    assert model.entries == ("Alice", {"name": "Bob", "url": "https://example.com/bob"})


def test_count_tracks_inserts_and_removes(model: AuthorsTableModel) -> None:
    """The `ItemOrderingEditor` contract: how many entries there are, and a signal when that changes.

    **Test steps:**

    * record every `count_changed` and insert, then delete
    * verify `count` follows and the signal fired for each
    """
    counts: list[int] = []
    model.count_changed.connect(lambda: counts.append(model.count))

    model.insert(-1)
    assert model.count == 3
    model.delete(0)
    assert model.count == 2

    assert counts == [3, 2]


def test_count_does_not_change_on_a_move(model: AuthorsTableModel) -> None:
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
