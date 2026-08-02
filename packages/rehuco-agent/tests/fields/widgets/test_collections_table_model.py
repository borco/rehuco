"""Tests for CollectionsTableModel: the merge contract, the two cells, and what an insert makes."""

from typing import Any

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QColor
from pytest import fixture, mark, param, raises
from rehuco_agent.fields.colors import WARNING_COLOR
from rehuco_agent.fields.widgets.collections_table_model import CollectionsTableModel
from rehuco_agent.fields.widgets.membership_table_model import (
    INDEX_COLUMN,
    MISSING_TITLE_REASON,
    TITLE_COLUMN,
    MembershipTableModel,
)

STORED: list[dict[str, Any]] = [
    {"title": "Sculpting Series", "index": 2, "url": "https://example.com/series"},
    {"title": "Anatomy Series", "index": 1},
]
"""Two memberships, the first carrying the cached ``url`` the collection owns and no editor shows."""


@fixture
def model() -> CollectionsTableModel:
    """A model over :data:`STORED`.

    :returns: the seeded model.
    """
    model = CollectionsTableModel()
    model.set_entries(STORED)
    return model


def cell(model: CollectionsTableModel, row: int, column: int, role: Qt.ItemDataRole) -> Any:
    """Read one cell.

    :param model: the model to read.
    :param row: the row to read.
    :param column: the column to read.
    :param role: the role to read it under.
    :returns: whatever the model answers.
    """
    return model.data(model.index(row, column), role)


# region shape


def test_the_table_has_a_title_and_an_index_column(model: CollectionsTableModel) -> None:
    """One row per membership, two cells each -- the ``url`` is carried, not shown ([[field-schema#sources]]).

    **Test steps:**

    * verify the row and column counts
    * verify the headers
    """
    assert model.rowCount() == 2
    assert model.columnCount() == 2
    assert model.headerData(TITLE_COLUMN, Qt.Orientation.Horizontal) == "Title"
    assert model.headerData(INDEX_COLUMN, Qt.Orientation.Horizontal) == "Index"


def test_the_rows_are_in_stored_order(model: CollectionsTableModel) -> None:
    """Stored order is kept where the viewer sorts: a table that re-sorted itself as the index cell was
    typed into would move the row out from under the cursor.

    **Test steps:**

    * read both titles in row order
    * verify they are as stored, not index-ordered
    """
    assert [cell(model, row, TITLE_COLUMN, Qt.ItemDataRole.DisplayRole) for row in range(2)] == [
        "Sculpting Series",
        "Anatomy Series",
    ]


def test_seeding_does_not_adopt_the_caller_s_records(model: CollectionsTableModel) -> None:
    """The records are copied in, so the model cannot write into a list the document still holds.

    **Test steps:**

    * verify the model's records equal the stored ones but are not the same objects
    """
    assert model.entries == STORED
    assert model.entries[0] is not STORED[0]


def test_reseeding_the_same_records_is_not_a_change(model: CollectionsTableModel, qtbot: Any) -> None:
    """The echo guard: a caller handing back what it just read must not rebuild the rows under an open
    cell editor.

    **Test steps:**

    * hand the model its own entries back
    * verify no model reset was reported
    """
    del qtbot
    resets: list[None] = []
    model.modelReset.connect(lambda: resets.append(None))

    model.set_entries(model.entries)

    assert not resets


# endregion

# region the two cells


def test_an_unplaced_index_shows_as_nothing(model: CollectionsTableModel) -> None:
    """``0`` means *no position chosen*, so the cell shows nothing -- printing ``0`` would show a
    placement nobody made ([[field-schema#sources]]).

    **Test steps:**

    * set a membership to the unplaced index
    * verify the display is empty while the edit value is still the number
    """
    model.setData(model.index(0, INDEX_COLUMN), 0)

    assert cell(model, 0, INDEX_COLUMN, Qt.ItemDataRole.DisplayRole) == ""
    assert cell(model, 0, INDEX_COLUMN, Qt.ItemDataRole.EditRole) == 0


def test_an_emptied_title_is_flagged_and_not_refused(model: CollectionsTableModel) -> None:
    """Validation is flagged, never enforced: nothing refuses the keystroke, and the cell says why it is
    not something this editor would write.

    **Test steps:**

    * empty a title
    * verify the edit landed, and the cell carries the reason and the warning color
    """
    assert model.setData(model.index(0, TITLE_COLUMN), "   ") is True

    assert cell(model, 0, TITLE_COLUMN, Qt.ItemDataRole.DisplayRole) == ""
    assert cell(model, 0, TITLE_COLUMN, Qt.ItemDataRole.ToolTipRole) == MISSING_TITLE_REASON
    assert cell(model, 0, TITLE_COLUMN, Qt.ItemDataRole.ForegroundRole).color() == QColor(WARNING_COLOR)


def test_a_valid_cell_carries_no_tooltip(model: CollectionsTableModel) -> None:
    """Only a cell with something to say says it.

    **Test steps:**

    * read the tooltip and foreground of a well-formed title
    * verify both are absent
    """
    assert cell(model, 0, TITLE_COLUMN, Qt.ItemDataRole.ToolTipRole) is None
    assert cell(model, 0, TITLE_COLUMN, Qt.ItemDataRole.ForegroundRole) is None


def test_a_titleless_record_still_shows_its_position(model: CollectionsTableModel) -> None:
    """A record with no usable title has no ``(index, title)`` pair to read, and its position is still a
    cell the user can type in -- so it is coerced the one way core would have.

    **Test steps:**

    * seed a record carrying a position and no title
    * verify the position reads back
    """
    model.set_entries([{"index": 5}])

    assert cell(model, 0, INDEX_COLUMN, Qt.ItemDataRole.EditRole) == 5


@mark.parametrize(
    ("stored", "expected"),
    [
        param({"title": "T"}, 0, id="no-index-at-all"),
        param({"title": "T", "index": "2"}, 0, id="a-string-is-not-an-index"),
        param({"title": "T", "index": True}, 0, id="a-bool-is-not-an-index"),
    ],
)
def test_a_malformed_index_reads_as_unplaced(stored: dict[str, Any], expected: int) -> None:
    """Malformed payload is coerced, not refused ([[data-model#write-integrity]]).

    **Test steps:**

    * seed each malformed record
    * verify its position reads as unplaced
    """
    model = CollectionsTableModel()
    model.set_entries([stored])

    assert model.index_of(0) == expected


def test_both_cells_are_editable(model: CollectionsTableModel) -> None:
    """A collection belongs to nobody, so there is no one whose permission a cell needs.

    **Test steps:**

    * read the flags of both cells
    * verify each is editable
    """
    for column in (TITLE_COLUMN, INDEX_COLUMN):
        assert model.flags(model.index(0, column)) & Qt.ItemFlag.ItemIsEditable


def test_an_invalid_index_carries_no_flags_and_no_data(model: CollectionsTableModel) -> None:
    """Qt asks about invalid indexes; the answer is nothing, never a crash.

    **Test steps:**

    * read the flags and data of an invalid index
    * verify both are empty, and that writing to one is refused
    """
    assert model.flags(QModelIndex()) == Qt.ItemFlag.NoItemFlags
    assert model.data(QModelIndex()) is None
    assert model.setData(QModelIndex(), "x") is False


def test_a_header_is_only_answered_for_the_columns(model: CollectionsTableModel) -> None:
    """The row numbers say nothing here -- the position is a column of its own.

    **Test steps:**

    * ask for a vertical header and for a non-display role
    * verify neither is answered
    """
    assert model.headerData(0, Qt.Orientation.Vertical) is None
    assert model.headerData(0, Qt.Orientation.Horizontal, Qt.ItemDataRole.ToolTipRole) is None


def test_a_child_index_holds_no_rows_or_columns(model: CollectionsTableModel) -> None:
    """The model is flat, so anything under a row is empty.

    **Test steps:**

    * ask for the row and column counts under a valid parent
    * verify both are zero
    """
    parent = model.index(0, TITLE_COLUMN)

    assert model.rowCount(parent) == 0
    assert model.columnCount(parent) == 0


# endregion

# region merge, don't rebuild


def test_retyping_a_title_keeps_the_cached_url(model: CollectionsTableModel) -> None:
    """The merge contract: a cell writes back into the record its row was built from, changing only the
    key it owns -- the ``url`` the collection owns is not this editor's to drop (#235).

    **Test steps:**

    * retype the title of the membership carrying a ``url``
    * verify the record keeps the ``url`` and its position
    """
    model.setData(model.index(0, TITLE_COLUMN), "Renamed Series")

    assert model.entries[0] == {"title": "Renamed Series", "index": 2, "url": "https://example.com/series"}


def test_editing_a_row_never_mutates_the_record_it_was_given() -> None:
    """A document hands its lists out by reference, so an edit builds a new record and leaves the old
    object alone ([[data-model#write-integrity]]).

    **Test steps:**

    * seed a record and edit it
    * verify the object handed in is unchanged
    """
    stored = {"title": "Old", "index": 1}
    model = CollectionsTableModel()
    model.set_entries([stored])

    model.setData(model.index(0, TITLE_COLUMN), "New")

    assert stored == {"title": "Old", "index": 1}


def test_writing_the_same_value_reports_no_change(model: CollectionsTableModel) -> None:
    """An edit that changes nothing is not an edit -- otherwise clicking through a row would dirty a
    document nobody typed into.

    **Test steps:**

    * write each cell's own current value back
    * verify both are refused
    """
    assert model.setData(model.index(0, TITLE_COLUMN), "Sculpting Series") is False
    assert model.setData(model.index(0, INDEX_COLUMN), 2) is False


def test_only_the_edit_role_writes(model: CollectionsTableModel) -> None:
    """Every other role is a read; a display-role write would be a value nothing asked for.

    **Test steps:**

    * write under the display role
    * verify it is refused and nothing changed
    """
    assert model.setData(model.index(0, TITLE_COLUMN), "New", Qt.ItemDataRole.DisplayRole) is False
    assert model.entries[0]["title"] == "Sculpting Series"


# endregion

# region what the list holds


def test_an_insert_makes_a_blank_membership(model: CollectionsTableModel) -> None:
    """A blank title and no position: a membership naming no series is not a membership in anything yet,
    which is also what makes the row abandonable while its editor is still open.

    **Test steps:**

    * insert after the first row
    * verify the new row landed there, blank
    """
    row = model.insert(0)

    assert row == 1
    assert model.entries[1] == {"title": "", "index": 0}


def test_an_insert_at_a_negative_row_appends(model: CollectionsTableModel) -> None:
    """With no current row there is nothing to insert *after*, so the entry goes at the end.

    **Test steps:**

    * insert with no current row
    * verify it landed last
    """
    assert model.insert(-1) == 2


def test_delete_drops_one_membership(model: CollectionsTableModel) -> None:
    """One row, one membership.

    **Test steps:**

    * delete the first row
    * verify only the second is left
    """
    model.delete(0)

    assert [record["title"] for record in model.entries] == ["Anatomy Series"]


def test_delete_at_a_negative_row_is_a_no_op(model: CollectionsTableModel) -> None:
    """With nothing current there is nothing to drop.

    **Test steps:**

    * delete with no current row
    * verify both memberships are still there
    """
    model.delete(-1)

    assert len(model.entries) == 2


def test_reset_is_a_no_op(model: CollectionsTableModel) -> None:
    """A default set of memberships would be somebody else's memberships -- there is no reset concept here.

    **Test steps:**

    * reset the model
    * verify nothing changed
    """
    model.reset()

    assert model.entries == STORED


@mark.parametrize(
    ("row", "count"),
    [param(3, 1, id="past-the-end"), param(-1, 1, id="before-the-start"), param(0, 0, id="no-rows-at-all")],
)
def test_an_out_of_range_insert_is_refused(model: CollectionsTableModel, row: int, count: int) -> None:
    """Qt's own primitives answer honestly rather than corrupting the list.

    **Test steps:**

    * call ``insertRows`` with each refused shape
    * verify it is refused and the list is untouched
    """
    assert model.insertRows(row, count) is False
    assert len(model.entries) == 2


@mark.parametrize(
    ("row", "count"),
    [param(2, 1, id="past-the-end"), param(-1, 1, id="before-the-start"), param(0, 3, id="more-than-there-are")],
)
def test_an_out_of_range_removal_is_refused(model: CollectionsTableModel, row: int, count: int) -> None:
    """The same for removal.

    **Test steps:**

    * call ``removeRows`` with each refused shape
    * verify it is refused and the list is untouched
    """
    assert model.removeRows(row, count) is False
    assert len(model.entries) == 2


def test_a_child_parent_is_refused_by_both_primitives(model: CollectionsTableModel) -> None:
    """The model is flat, so nothing can be inserted or removed *under* a row.

    **Test steps:**

    * call both primitives with a valid parent
    * verify both are refused
    """
    parent = model.index(0, TITLE_COLUMN)

    assert model.insertRows(0, 1, parent) is False
    assert model.removeRows(0, 1, parent) is False


def test_the_count_follows_the_rows(model: CollectionsTableModel) -> None:
    """The `ItemOrderingEditor` contract's count, reported whenever it moves.

    **Test steps:**

    * record the count changes while inserting and deleting
    * verify one is reported per change, and the count tracks the rows
    """
    changes: list[int] = []
    model.count_changed.connect(lambda: changes.append(model.count))

    model.insert(-1)
    model.delete(0)

    assert changes == [3, 2]
    assert model.count == 2


@mark.parametrize("move", ["move_to_top", "move_up", "move_down", "move_to_bottom"])
def test_the_ordering_moves_are_honest_no_ops(model: CollectionsTableModel, move: str) -> None:
    """``index`` is the position here, not the row -- so the protocol the shared machinery asks for is
    satisfied by moves that do nothing, and the editor hides the column rather than offering them.

    **Test steps:**

    * call each move on the first row
    * verify the row is unmoved and the list is untouched
    """
    assert getattr(model, move)(0) == 0
    assert model.entries == STORED


# endregion

# region the shared base


def test_the_base_says_nothing_about_what_a_row_is() -> None:
    """The base is the two cells and the merge rule; *what a row is* -- where the records live and how one
    is replaced -- is the subclass's, and there is no plausible default to guess.

    **Test steps:**

    * ask the base to read and to replace a record
    * verify both refuse
    """
    base = MembershipTableModel()

    with raises(NotImplementedError):
        base.record(0)
    with raises(NotImplementedError):
        base.replace_record(0, {})


# endregion
