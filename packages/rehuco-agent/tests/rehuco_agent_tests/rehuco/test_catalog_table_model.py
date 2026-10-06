"""Tests for a table browser's model (#377, #379)."""

from collections.abc import Iterator
from itertools import count
from pathlib import Path
from typing import Any, Final
from uuid import UUID, uuid4

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, Qt
from pytest import fixture, mark
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco.catalog_table_model import (
    COLUMNS,
    DEFAULT_HIDDEN,
    LEGACY_FORMAT,
    PATH_ROLE,
    UNKNOWN_FORMAT,
    CatalogColumn,
    CatalogTableModel,
    CatalogTotals,
)
from rehuco_core import CatalogRecord, CatalogRow, RecordKind

ROOT_ID: Final = uuid4()
ROOT: Final = Path("/fake/tutorials")

ids: Iterator[int] = count(10_000)
"""Every row a test builds has an id of its own, as the cache's rows do."""


def row(record: CatalogRecord, root_id: UUID = ROOT_ID, resource_id: int | None = None) -> CatalogRow:
    """A cache row for ``record`` under the root ``root_id``, labeled ``tutorials``, with a fresh id unless given."""
    return CatalogRow(
        resource_id=next(ids) if resource_id is None else resource_id,
        root_id=root_id,
        root_label="tutorials",
        record=record,
        scanned_at=0.0,
    )


def rehu(path: str, **fields: Any) -> CatalogRecord:
    """A ``.rehu`` record at ``path`` of the current format, with ``fields`` besides."""
    return CatalogRecord(path, RecordKind.REHU, **{"format_version": 1, **fields})


def model_of(*rows: CatalogRow) -> CatalogTableModel:
    """A model holding ``rows``, in the order given -- the cache's order."""
    model = CatalogTableModel()
    model.set_rows(list(rows), {ROOT_ID: ROOT})
    return model


def cell(model: CatalogTableModel, row_: int, column: CatalogColumn, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
    """One cell's data."""
    return model.index(row_, column).data(role)


def column_of(model: CatalogTableModel, column: CatalogColumn) -> list[Any]:
    """A column's values, in row order."""
    return [cell(model, row_, column) for row_ in range(model.rowCount())]


@fixture(name="model")
def fixture_model() -> CatalogTableModel:
    """A model holding one readable record and one that could not be read."""
    return model_of(
        row(rehu("python/info.rehu", title="Python", type="tutorial", authors=("Ada", "Grace"))),
        row(CatalogRecord("broken/info.rehu", RecordKind.REHU, error="Not JSON")),
    )


# region Columns


def test_every_column_has_a_header_and_the_first_four_keep_their_places(model: CatalogTableModel) -> None:
    """The columns are every field the cache holds; #377's four lead, in their old order, so a header state saved
    before the others existed still fits them.

    **Test steps:**

    * read the column count and the headers
    * verify every column is there, the first four authors, title, type and path
    """
    headers = [model.headerData(column, Qt.Orientation.Horizontal) for column in range(model.columnCount())]

    assert model.columnCount() == len(CatalogColumn) == len(COLUMNS)
    assert headers[:4] == ["Authors", "Title", "Type", "Path"]
    assert "Format" in headers and "Kind" not in headers


def test_a_plain_browser_hides_the_url_and_the_type_specific_columns() -> None:
    """The common columns start shown; the URL and the fields a preset shows start hidden.

    **Test steps:**

    * read which columns start hidden
    * verify the URL and the six type-specific ones
    """
    assert DEFAULT_HIDDEN == {
        CatalogColumn.URL,
        CatalogColumn.ADVERTISED_DURATION,
        CatalogColumn.ORIGINAL_DURATION,
        CatalogColumn.CURRENT_DURATION,
        CatalogColumn.LEVEL,
        CatalogColumn.ADVERTISED_COUNT,
        CatalogColumn.CURRENT_COUNT,
    }


def test_a_row_shows_its_fields(model: CatalogTableModel) -> None:
    """Authors joined in the record's order, then title, type and the root-qualified path.

    **Test steps:**

    * read the first row's first four cells
    * verify each
    """
    assert [model.index(0, column).data() for column in range(4)] == [
        "Ada, Grace",
        "Python",
        "tutorial",
        "tutorials/python/info.rehu",
    ]


def test_a_cell_holds_the_value_not_its_text() -> None:
    """A size is its bytes and a duration its seconds -- a delegate words them -- and a count is a number.

    **Test steps:**

    * hold a tutorial with a size and durations, and a pack with counts
    * verify each cell's data is the value itself, and a numeric column aligns right
    """
    model = model_of(
        row(rehu("a.rehu", current_size=1024, advertised_duration=3600, level=("beginner", "advanced"))),
        row(rehu("b.rehu", advertised_count="500+", current_count=480)),
    )

    assert cell(model, 0, CatalogColumn.SIZE) == 1024
    assert cell(model, 0, CatalogColumn.ADVERTISED_DURATION) == 3600
    assert cell(model, 0, CatalogColumn.LEVEL) == "beginner, advanced"
    assert (cell(model, 1, CatalogColumn.ADVERTISED_COUNT), cell(model, 1, CatalogColumn.CURRENT_COUNT)) == (
        "500+",
        480,
    )
    assert cell(model, 0, CatalogColumn.SIZE, Qt.ItemDataRole.TextAlignmentRole) == (
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    )
    assert cell(model, 0, CatalogColumn.TITLE, Qt.ItemDataRole.TextAlignmentRole) is None


def test_the_exact_size_is_the_size_cells_tooltip() -> None:
    """What the short human size hides is said on hover.

    **Test steps:**

    * hold a record of 1,024 bytes and read its size cell's tooltip
    * verify the exact bytes
    """
    model = model_of(row(rehu("a.rehu", current_size=1024)))

    assert cell(model, 0, CatalogColumn.SIZE, Qt.ItemDataRole.ToolTipRole) == "1,024 bytes"


def test_the_format_column_tells_a_version_a_legacy_tc_and_an_unknown_one_apart() -> None:
    """A ``.rehu`` shows its version -- ``0`` for an unstamped one -- a ``.tc`` shows ``tc``, and a ``.rehu`` whose
    version is not known, unreadable or not read since, shows ``?``, never ``tc``.

    **Test steps:**

    * hold a v1, a v0, a ``.tc``, an unreadable ``.rehu`` and one with no version stored
    * verify the cells, and that the unknown ones say why on hover
    """
    model = model_of(
        row(rehu("v1.rehu")),
        row(rehu("v0.rehu", format_version=0)),
        row(CatalogRecord("old.tc", RecordKind.TC)),
        row(CatalogRecord("bad.rehu", RecordKind.REHU, error="Not JSON")),
        row(CatalogRecord("stale.rehu", RecordKind.REHU)),
    )

    assert column_of(model, CatalogColumn.FORMAT) == [1, 0, LEGACY_FORMAT, UNKNOWN_FORMAT, UNKNOWN_FORMAT]
    assert cell(model, 3, CatalogColumn.FORMAT, Qt.ItemDataRole.ToolTipRole) == "Not JSON"
    assert "scan" in cell(model, 4, CatalogColumn.FORMAT, Qt.ItemDataRole.ToolTipRole)


def test_a_record_with_no_authors_shows_an_empty_cell(model: CatalogTableModel) -> None:
    """A record naming no author leaves the cell blank rather than inventing one.

    **Test steps:**

    * read the authors cell of the record that could not be read
    * verify it holds nothing
    """
    assert cell(model, 1, CatalogColumn.AUTHORS) is None


def test_a_record_with_no_title_is_named_by_its_file(model: CatalogTableModel) -> None:
    """A record that could not be read still says which file it is.

    **Test steps:**

    * read the title cell of the unreadable record
    * verify it is the file name
    """
    assert cell(model, 1, CatalogColumn.TITLE) == "info.rehu"


def test_an_unreadable_record_says_why_on_hover(model: CatalogTableModel) -> None:
    """The reason the record could not be read is its tooltip, and only its.

    **Test steps:**

    * read both rows' tooltips
    * verify the unreadable one carries its error and the readable one none
    """
    assert model.index(1, 0).data(Qt.ItemDataRole.ToolTipRole) == "Not JSON"
    assert model.index(0, 0).data(Qt.ItemDataRole.ToolTipRole) is None


def test_a_row_answers_its_absolute_path_and_its_key(model: CatalogTableModel) -> None:
    """The root's folder and the root-relative path make the file a double-click opens; the root's id and the
    relative path are how the row is named to others.

    **Test steps:**

    * read the path role, ``absolute_path`` and ``row_key``
    * verify each
    """
    assert model.index(0, 0).data(PATH_ROLE) == ROOT / "python/info.rehu"
    assert model.absolute_path(0) == ROOT / "python/info.rehu"
    assert model.row_key(0) == (ROOT_ID, "python/info.rehu")
    assert model.row_key(2) is None


def test_a_row_whose_root_is_unknown_has_no_path() -> None:
    """Nothing is invented for a root the model was not told about.

    **Test steps:**

    * set a row under a root the model was not told about
    * verify its path, and an out-of-range row's, is ``None``
    """
    model = CatalogTableModel()
    model.set_rows([row(rehu("a/info.rehu"), uuid4())], {ROOT_ID: ROOT})

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
    """Only the display, tooltip, alignment and path roles say anything.

    **Test steps:**

    * read a decoration, a vertical header, a header tooltip and a header past the last column
    * verify each is ``None``
    """
    assert model.index(0, 0).data(Qt.ItemDataRole.DecorationRole) is None
    assert model.headerData(0, Qt.Orientation.Vertical) is None
    assert model.headerData(0, Qt.Orientation.Horizontal, Qt.ItemDataRole.ToolTipRole) is None
    assert model.headerData(len(CatalogColumn), Qt.Orientation.Horizontal) is None


# endregion

# region Totals


def test_the_totals_tell_none_from_zero_and_count_legacy_tc_apart() -> None:
    """A measured ``0`` adds to a total, a record stating none is unmeasured, and a legacy ``.tc`` -- whose ``0`` is an
    old claim -- is counted on its own and left out of both totals.

    **Test steps:**

    * set a sized record, a record of ``0`` bytes, a measured pack, an empty pack, an unmeasured pack and two ``.tc``
      files, one claiming ``0`` and one a size
    * verify the count, the legacy count, the sum of the sizes with the rows missing one, and the images with the packs
      missing a count
    """
    pack = "reference_images"
    model = model_of(
        row(rehu("a/info.rehu", type="tutorial", current_size=4096)),
        row(rehu("b/info.rehu", type="tutorial", current_size=0)),
        row(CatalogRecord("c/info.tc", RecordKind.TC, type=pack, current_size=0)),
        row(CatalogRecord("g/info.tc", RecordKind.TC, type=pack, current_size=999)),
        row(rehu("d.rehu", type=pack, current_size=100, current_count=7)),
        row(rehu("e.rehu", type=pack, current_size=0, current_count=0)),
        row(rehu("f.rehu", type=pack)),
    )

    assert model.totals == CatalogTotals(
        count=7, legacy=2, size=4196, unmeasured_size=1, images=7, unmeasured_images=1, has_images=True
    )


def test_a_table_with_no_reference_image_rows_has_no_image_total() -> None:
    """Rows of a type that declares no image count are not "unmeasured" images, and with only empty packs the total
    still means something.

    **Test steps:**

    * set a tutorial and a legacy ``.tc`` of a pack type, and read the totals
    * set only an empty pack, and read them again
    * verify no image total, then ``0`` images with nothing missing
    """
    model = model_of(
        row(rehu("a/info.rehu", type="tutorial")),
        row(CatalogRecord("b/info.tc", RecordKind.TC, type="reference_images")),
    )
    assert (model.totals.has_images, model.totals.unmeasured_images) == (False, 0)

    model.set_rows([row(rehu("e.rehu", type="reference_images", current_count=0))], {})
    assert (model.totals.has_images, model.totals.images, model.totals.unmeasured_images) == (True, 0, 0)


def test_some_rows_add_up_by_the_rule_the_totals_do() -> None:
    """A selection's totals are the totals of those rows alone, ``.tc`` and unmeasured rows included.

    **Test steps:**

    * set a sized record, a legacy ``.tc``, a measured pack and an unmeasured one
    * verify the totals of no row, of one, of two with the ``.tc`` and of every row (a repeated and an out-of-range
      number ignored)
    """
    pack = "reference_images"
    model = model_of(
        row(rehu("a/info.rehu", type="tutorial", current_size=4096)),
        row(CatalogRecord("c/info.tc", RecordKind.TC, type=pack, current_size=0)),
        row(rehu("d.rehu", type=pack, current_size=100, current_count=7)),
        row(rehu("f.rehu", type=pack)),
    )

    assert model.totals_of([]) == CatalogTotals()
    assert model.totals_of([0]) == CatalogTotals(count=1, size=4096)
    assert model.totals_of([1, 2]) == CatalogTotals(count=2, legacy=1, size=100, images=7, has_images=True)
    assert model.totals_of([0, 1, 2, 3, 3, 9, -1]) == model.totals


# endregion

# region Sorting


def titled(*titles: str) -> CatalogTableModel:
    """A model of one record per title, in the order given -- the cache's order."""
    return model_of(*(row(rehu(f"{title}/info.rehu", title=title)) for title in titles))


def shown_titles(model: CatalogTableModel) -> list[str]:
    """The titles in row order."""
    return column_of(model, CatalogColumn.TITLE)


def test_sorting_ignores_case_and_can_be_reversed() -> None:
    """A header click orders the rows by that column without regard to case, either way round.

    **Test steps:**

    * sort mixed-case titles ascending, then descending
    * verify both orders
    """
    model = titled("beta", "Alpha", "gamma")

    model.sort(CatalogColumn.TITLE, Qt.SortOrder.AscendingOrder)
    assert shown_titles(model) == ["Alpha", "beta", "gamma"]

    model.sort(CatalogColumn.TITLE, Qt.SortOrder.DescendingOrder)
    assert shown_titles(model) == ["gamma", "beta", "Alpha"]


def test_column_minus_one_is_the_caches_own_order() -> None:
    """Clearing the sort shows the rows as the cache handed them over.

    **Test steps:**

    * sort, then sort on column ``-1``
    * verify the original order is back
    """
    model = titled("beta", "Alpha", "gamma")
    model.sort(CatalogColumn.TITLE)

    model.sort(-1)

    assert shown_titles(model) == ["beta", "Alpha", "gamma"]


def test_new_rows_arrive_in_the_sort_already_chosen() -> None:
    """A rescan's rows are shown in the order the view asked for, not the cache's.

    **Test steps:**

    * sort descending, then replace the rows
    * verify the new rows are in descending order
    """
    model = titled("a")
    model.sort(CatalogColumn.TITLE, Qt.SortOrder.DescendingOrder)

    model.set_rows([row(rehu(f"{title}/info.rehu", title=title)) for title in ("b", "c", "a")], {ROOT_ID: ROOT})

    assert shown_titles(model) == ["c", "b", "a"]


def test_a_persistent_index_follows_its_row_through_a_sort() -> None:
    """The selection a view holds stays on the same resource when the rows move.

    **Test steps:**

    * hold a persistent index on ``gamma``, which is the last row
    * sort descending
    * verify the index now points at row 0, still ``gamma``
    """
    model = titled("alpha", "beta", "gamma")
    held = QPersistentModelIndex(model.index(2, CatalogColumn.TITLE))

    model.sort(CatalogColumn.TITLE, Qt.SortOrder.DescendingOrder)

    assert held.row() == 0
    assert held.data() == "gamma"


@mark.parametrize("order", [Qt.SortOrder.AscendingOrder, Qt.SortOrder.DescendingOrder])
def test_a_missing_value_sorts_after_every_value_either_way_round(order: Qt.SortOrder) -> None:
    """A record with no authors is not "less" than one with: it comes last in both orders.

    **Test steps:**

    * sort a record without authors and two with by the authors column, each way round
    * verify the one without is last
    """
    model = model_of(
        row(rehu("a/info.rehu", title="Without")),
        row(rehu("b/info.rehu", title="Ann", authors=("ann",))),
        row(rehu("c/info.rehu", title="Bob", authors=("bob",))),
    )

    model.sort(CatalogColumn.AUTHORS, order)

    assert shown_titles(model)[-1] == "Without"


def test_a_size_sorts_by_its_bytes_not_its_text() -> None:
    """Two sizes that read alike in short form still sort apart, and a number is not compared as text.

    **Test steps:**

    * sort 1,024 B, 1,000 B, 9 B and an unmeasured record by size
    * verify the order is by bytes, the unmeasured one last
    """
    model = model_of(
        row(rehu("a.rehu", title="1024", current_size=1024)),
        row(rehu("b.rehu", title="none")),
        row(rehu("c.rehu", title="1000", current_size=1000)),
        row(rehu("d.rehu", title="9", current_size=9)),
    )

    model.sort(CatalogColumn.SIZE)

    assert shown_titles(model) == ["9", "1000", "1024", "none"]


def test_a_duration_and_a_claimed_count_sort_as_numbers() -> None:
    """Seconds compare as numbers, and a claim like ``500+`` by the number in it.

    **Test steps:**

    * sort by a duration, then by the advertised count
    * verify both orders are numeric
    """
    model = model_of(
        row(rehu("a.rehu", title="a", current_duration=600, advertised_count="1000")),
        row(rehu("b.rehu", title="b", current_duration=90, advertised_count="500+")),
        row(rehu("c.rehu", title="c", current_duration=3600, advertised_count="80")),
    )

    model.sort(CatalogColumn.CURRENT_DURATION)
    assert shown_titles(model) == ["b", "a", "c"]

    model.sort(CatalogColumn.ADVERTISED_COUNT)
    assert shown_titles(model) == ["c", "b", "a"]


@mark.parametrize(
    ("order", "expected"),
    [
        (Qt.SortOrder.AscendingOrder, ["v0", "v1", "v2", "tc", "unknown"]),
        (Qt.SortOrder.DescendingOrder, ["v2", "v1", "v0", "tc", "unknown"]),
    ],
)
def test_the_format_column_sorts_by_version_then_tc_then_unknown(order: Qt.SortOrder, expected: list[str]) -> None:
    """Versions compare as numbers; every ``.tc``, then every unknown version, follows them in either order.

    **Test steps:**

    * sort an unknown, a ``.tc`` and three versions by format
    * verify the versions in the order asked, then ``tc``, then ``?``
    """
    model = model_of(
        row(CatalogRecord("unknown.rehu", RecordKind.REHU, title="unknown")),
        row(CatalogRecord("tc.tc", RecordKind.TC, title="tc")),
        row(rehu("v2.rehu", title="v2", format_version=2)),
        row(rehu("v0.rehu", title="v0", format_version=0)),
        row(rehu("v1.rehu", title="v1")),
    )

    model.sort(CatalogColumn.FORMAT, order)

    assert shown_titles(model) == expected


# endregion

# region Updating in place


@fixture(name="three")
def fixture_three(qtbot: QtBot) -> CatalogTableModel:
    """A model sorted by title over ``alpha``, ``beta`` and ``gamma`` (ids 1, 2, 3), with reset reported as a failure.

    :param qtbot: pytest-qt fixture.
    :returns: the model.
    """
    del qtbot
    model = model_of(
        *(
            row(rehu(f"{title}/info.rehu", title=title, current_size=10), resource_id=resource_id)
            for resource_id, title in enumerate(("alpha", "beta", "gamma"), start=1)
        )
    )
    model.sort(CatalogColumn.TITLE)
    return model


def test_a_changed_row_is_updated_where_it_stands(qtbot: QtBot, three: CatalogTableModel) -> None:
    """A write that leaves a row where the sort has it changes its cells, and nothing else.

    **Test steps:**

    * hold a persistent index on ``beta`` and update it to ``bravo``
    * verify no reset, the cells changed in place, the index kept
    """
    held = QPersistentModelIndex(three.index(1, CatalogColumn.TITLE))

    with qtbot.assertNotEmitted(three.modelReset), qtbot.waitSignal(three.dataChanged):
        three.update_rows({2}, [row(rehu("beta/info.rehu", title="bravo", current_size=10), resource_id=2)])

    assert shown_titles(three) == ["alpha", "bravo", "gamma"]
    assert (held.row(), held.data()) == (1, "bravo")


def test_a_row_whose_sort_key_changed_moves_and_keeps_its_selection(qtbot: QtBot, three: CatalogTableModel) -> None:
    """A retitled row moves to where the sort now puts it, its persistent index with it.

    **Test steps:**

    * hold a persistent index on ``alpha`` and retitle it ``zulu``, then retitle ``gamma`` ``aaa``
    * verify each moved without a reset, the index following ``zulu``
    """
    held = QPersistentModelIndex(three.index(0, CatalogColumn.TITLE))

    with qtbot.assertNotEmitted(three.modelReset), qtbot.waitSignal(three.rowsMoved):
        three.update_rows({1}, [row(rehu("alpha/info.rehu", title="zulu", current_size=10), resource_id=1)])
    assert shown_titles(three) == ["beta", "gamma", "zulu"]
    assert (held.row(), held.data()) == (2, "zulu")

    with qtbot.assertNotEmitted(three.modelReset), qtbot.waitSignal(three.rowsMoved):
        three.update_rows({3}, [row(rehu("gamma/info.rehu", title="aaa", current_size=10), resource_id=3)])
    assert shown_titles(three) == ["aaa", "beta", "zulu"]
    assert (held.row(), held.data()) == (2, "zulu")


def test_a_new_matching_row_is_inserted_where_the_sort_puts_it(qtbot: QtBot, three: CatalogTableModel) -> None:
    """A record the model did not show arrives in its sorted place.

    **Test steps:**

    * update with a new row ``delta``
    * verify it is inserted between ``beta`` and ``gamma``, without a reset
    """
    with qtbot.assertNotEmitted(three.modelReset), qtbot.waitSignal(three.rowsInserted):
        three.update_rows({4}, [row(rehu("delta/info.rehu", title="delta", current_size=10), resource_id=4)])

    assert shown_titles(three) == ["alpha", "beta", "delta", "gamma"]


def test_a_gone_or_no_longer_matching_row_is_removed(qtbot: QtBot, three: CatalogTableModel) -> None:
    """An affected row the cache no longer returns for this query leaves the table; one the model never had is
    ignored.

    **Test steps:**

    * update ``beta`` and an id the model does not show, with nothing fresh
    * verify only ``beta`` is removed, without a reset
    """
    with qtbot.assertNotEmitted(three.modelReset), qtbot.waitSignal(three.rowsRemoved):
        three.update_rows({2, 99}, [])

    assert shown_titles(three) == ["alpha", "gamma"]


def test_an_unsorted_insert_lands_in_the_caches_order(qtbot: QtBot) -> None:
    """With no column sorted, a new row goes where the cache would put it: by path.

    **Test steps:**

    * hold ``a`` and ``c`` unsorted, then insert ``b``
    * verify ``b`` lands between them
    """
    del qtbot
    model = model_of(row(rehu("a/info.rehu", title="a")), row(rehu("c/info.rehu", title="c")))

    model.update_rows({500}, [row(rehu("b/info.rehu", title="b"), resource_id=500)])
    assert shown_titles(model) == ["a", "b", "c"]

    model.sort(-1)
    assert shown_titles(model) == ["a", "b", "c"]


def test_the_totals_follow_each_change_as_a_fresh_count_of_the_same_rows_would(three: CatalogTableModel) -> None:
    """Adjusted by the rows changed, never recomputed -- and equal to what a reset over the same rows adds up to,
    the image total going away with its last pack.

    **Test steps:**

    * insert a pack with images, resize a row and remove another, then remove the pack
    * verify after each the totals equal a fresh model's over the same rows
    """
    pack = row(rehu("pack.rehu", title="pack", type="reference_images", current_count=40), resource_id=4)
    resized = row(rehu("alpha/info.rehu", title="alpha", current_size=5000), resource_id=1)

    three.update_rows({4, 1, 2}, [pack, resized])
    expected = model_of(
        resized, row(rehu("gamma/info.rehu", title="gamma", current_size=10), resource_id=3), pack
    ).totals
    assert three.totals == expected
    assert three.totals.has_images

    three.update_rows({4}, [])
    assert three.totals == CatalogTotals(count=2, size=5010)


def test_a_rename_respells_the_row_and_its_key(three: CatalogTableModel) -> None:
    """A rebased path is what the row's key and path show afterwards.

    **Test steps:**

    * update ``beta`` with its path renamed
    * verify the key and the path cell
    """
    three.update_rows({2}, [row(rehu("b2/info.rehu", title="beta", current_size=10), resource_id=2)])

    assert three.row_key(1) == (ROOT_ID, "b2/info.rehu")
    assert cell(three, 1, CatalogColumn.PATH) == "tutorials/b2/info.rehu"


# endregion
