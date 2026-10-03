"""Tests for the bare resource table's model (#377)."""

from pathlib import Path
from typing import Final
from uuid import UUID, uuid4

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, Qt
from pytest import fixture
from rehuco_agent.rehuco.catalog_table_model import (
    AUTHORS_COLUMN,
    PATH_ROLE,
    SIZE_ROLE,
    TITLE_COLUMN,
    CatalogTableModel,
)
from rehuco_core import CatalogRecord, CatalogRow, RecordKind

ROOT_ID: Final = uuid4()
ROOT: Final = Path("/fake/tutorials")


def row(record: CatalogRecord, root_id: UUID = ROOT_ID) -> CatalogRow:
    """A cache row for ``record`` under the root ``root_id``, labeled ``tutorials``."""
    return CatalogRow(resource_id=1, root_id=root_id, root_label="tutorials", record=record, scanned_at=0.0)


@fixture(name="model")
def fixture_model() -> CatalogTableModel:
    """A model holding one readable record and one that could not be read."""
    model = CatalogTableModel()
    model.set_rows(
        [
            row(
                CatalogRecord(
                    "python/info.rehu", RecordKind.REHU, title="Python", type="tutorial", authors=("Ada", "Grace")
                )
            ),
            row(CatalogRecord("broken/info.rehu", RecordKind.REHU, error="Not JSON")),
        ],
        {ROOT_ID: ROOT},
    )
    return model


def test_columns_are_authors_title_type_and_path(model: CatalogTableModel) -> None:
    """A row shows its authors first, then its title, its type and its root-qualified path.

    **Test steps:**

    * read the headers and the first row's cells
    * verify the authors lead, joined in the record's order
    """
    assert model.columnCount() == 4
    assert [model.headerData(column, Qt.Orientation.Horizontal) for column in range(4)] == [
        "Authors",
        "Title",
        "Type",
        "Path",
    ]
    assert [model.index(0, column).data() for column in range(4)] == [
        "Ada, Grace",
        "Python",
        "tutorial",
        "tutorials/python/info.rehu",
    ]


def test_a_record_with_no_authors_shows_an_empty_cell(model: CatalogTableModel) -> None:
    """A record naming no author leaves the cell blank rather than inventing one.

    **Test steps:**

    * read the authors cell of the record that could not be read
    * verify it is empty
    """
    assert model.index(1, AUTHORS_COLUMN).data() == ""


def test_a_record_with_no_title_is_named_by_its_file(model: CatalogTableModel) -> None:
    """A record that could not be read still says which file it is.

    **Test steps:**

    * read the title cell of the unreadable record
    * verify it is the file name
    """
    assert model.index(1, TITLE_COLUMN).data() == "info.rehu"


def test_an_unreadable_record_says_why_on_hover(model: CatalogTableModel) -> None:
    """The reason the record could not be read is its tooltip, and only its.

    **Test steps:**

    * read both rows' tooltips
    * verify the unreadable one carries its error and the readable one none
    """
    assert model.index(1, 0).data(Qt.ItemDataRole.ToolTipRole) == "Not JSON"
    assert model.index(0, 0).data(Qt.ItemDataRole.ToolTipRole) is None


def test_a_row_answers_its_absolute_path(model: CatalogTableModel) -> None:
    """The root's folder and the root-relative path make the file a double-click opens.

    **Test steps:**

    * read the path role and ``absolute_path``
    * verify both are the root joined to the record's path
    """
    assert model.index(0, 0).data(PATH_ROLE) == ROOT / "python/info.rehu"
    assert model.absolute_path(0) == ROOT / "python/info.rehu"


def test_a_row_answers_its_current_size_or_zero() -> None:
    """The size role is the record's ``current_size``; a record stating none counts as nothing.

    **Test steps:**

    * set one record with a size and one without
    * verify the size role answers the size, then ``0``
    """
    model = CatalogTableModel()
    model.set_rows(
        [
            row(CatalogRecord("a/info.rehu", RecordKind.REHU, current_size=4096)),
            row(CatalogRecord("b/info.tc", RecordKind.TC)),
        ],
        {ROOT_ID: ROOT},
    )

    assert [model.index(r, 0).data(SIZE_ROLE) for r in range(2)] == [4096, 0]


def test_a_row_whose_root_is_unknown_has_no_path() -> None:
    """Nothing is invented for a root the model was not told about.

    **Test steps:**

    * set a row under a root the model was not told about
    * verify its path, and an out-of-range row's, is ``None``
    """
    model = CatalogTableModel()
    model.set_rows([row(CatalogRecord("a/info.rehu", RecordKind.REHU), uuid4())], {ROOT_ID: ROOT})

    assert model.absolute_path(0) is None
    assert model.absolute_path(5) is None
    assert model.absolute_path(-1) is None


def test_setting_rows_resets_the_model(model: CatalogTableModel) -> None:
    """Replacing the rows is a reset, and an empty set leaves an empty table.

    **Test steps:**

    * replace the rows with none
    * verify the table is empty
    """
    model.set_rows([], {})

    assert model.rowCount() == 0
    assert model.index(0, 0).data() is None


def test_an_invalid_index_answers_nothing(model: CatalogTableModel) -> None:
    """A view asking about no cell gets ``None`` for every role.

    **Test steps:**

    * read the display and path roles of an invalid index
    * verify both are ``None``
    """
    assert model.data(QModelIndex()) is None
    assert model.data(QModelIndex(), PATH_ROLE) is None


def test_a_child_index_has_no_rows(model: CatalogTableModel) -> None:
    """A table has no children under a cell.

    **Test steps:**

    * ask for the counts under a cell
    * verify both are zero
    """
    assert model.rowCount(model.index(0, 0)) == 0
    assert model.columnCount(model.index(0, 0)) == 0


def test_other_roles_and_headers_answer_nothing(model: CatalogTableModel) -> None:
    """Only the display, tooltip and path roles say anything.

    **Test steps:**

    * read a decoration, a vertical header and a header tooltip
    * verify each is ``None``
    """
    assert model.index(0, 0).data(Qt.ItemDataRole.DecorationRole) is None
    assert model.headerData(0, Qt.Orientation.Vertical) is None
    assert model.headerData(0, Qt.Orientation.Horizontal, Qt.ItemDataRole.ToolTipRole) is None


# region Sorting


def titled(*titles: str) -> CatalogTableModel:
    """A model of one record per title, in the order given -- the cache's order."""
    model = CatalogTableModel()
    model.set_rows(
        [row(CatalogRecord(f"{title}/info.rehu", RecordKind.REHU, title=title)) for title in titles],
        {ROOT_ID: ROOT},
    )
    return model


def shown_titles(model: CatalogTableModel) -> list[str]:
    """The titles in row order."""
    return [model.index(row_, TITLE_COLUMN).data() for row_ in range(model.rowCount())]


def test_sorting_ignores_case_and_can_be_reversed() -> None:
    """A header click orders the rows by that column without regard to case, either way round.

    **Test steps:**

    * sort mixed-case titles ascending, then descending
    * verify both orders
    """
    model = titled("beta", "Alpha", "gamma")

    model.sort(TITLE_COLUMN, Qt.SortOrder.AscendingOrder)
    assert shown_titles(model) == ["Alpha", "beta", "gamma"]

    model.sort(TITLE_COLUMN, Qt.SortOrder.DescendingOrder)
    assert shown_titles(model) == ["gamma", "beta", "Alpha"]


def test_column_minus_one_is_the_caches_own_order() -> None:
    """Clearing the sort shows the rows as the cache handed them over.

    **Test steps:**

    * sort, then sort on column ``-1``
    * verify the original order is back
    """
    model = titled("beta", "Alpha", "gamma")
    model.sort(TITLE_COLUMN)

    model.sort(-1)

    assert shown_titles(model) == ["beta", "Alpha", "gamma"]


def test_new_rows_arrive_in_the_sort_already_chosen() -> None:
    """A rescan's rows are shown in the order the view asked for, not the cache's.

    **Test steps:**

    * sort descending, then replace the rows
    * verify the new rows are in descending order
    """
    model = titled("a")
    model.sort(TITLE_COLUMN, Qt.SortOrder.DescendingOrder)

    model.set_rows(
        [row(CatalogRecord(f"{title}/info.rehu", RecordKind.REHU, title=title)) for title in ("b", "c", "a")],
        {ROOT_ID: ROOT},
    )

    assert shown_titles(model) == ["c", "b", "a"]


def test_a_persistent_index_follows_its_row_through_a_sort() -> None:
    """The selection a view holds stays on the same resource when the rows move.

    **Test steps:**

    * hold a persistent index on ``gamma``, which is the last row
    * sort descending
    * verify the index now points at row 0, still ``gamma``
    """
    model = titled("alpha", "beta", "gamma")
    held = QPersistentModelIndex(model.index(2, TITLE_COLUMN))

    model.sort(TITLE_COLUMN, Qt.SortOrder.DescendingOrder)

    assert held.row() == 0
    assert held.data() == "gamma"


def test_sorting_by_authors_puts_resources_without_authors_first() -> None:
    """An empty authors cell sorts before any name.

    **Test steps:**

    * sort a model holding one record with authors and one without by the authors column
    * verify the one without comes first
    """
    model = CatalogTableModel()
    model.set_rows(
        [
            row(CatalogRecord("a/info.rehu", RecordKind.REHU, title="With", authors=("ann",))),
            row(CatalogRecord("b/info.rehu", RecordKind.REHU, title="Without")),
        ],
        {ROOT_ID: ROOT},
    )

    model.sort(AUTHORS_COLUMN)

    assert shown_titles(model) == ["Without", "With"]


# endregion
