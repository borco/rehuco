"""Tests for the columns an asset adds to a table browser (#678): what each shows, how each sorts, and which of them a
preset leaves to the header menu."""

from PySide6.QtCore import Qt
from rehuco_agent.rehuco.catalog_delegates import COLUMN_DELEGATES, LocalTimeDelegate, SizeDelegate
from rehuco_agent.rehuco.catalog_table_model import COLUMNS, TYPE_COLUMNS, CatalogColumn, CatalogTableModel
from rehuco_core import TYPE_FIELD_NAMES, CatalogRecord

from rehuco_agent_tests.rehuco.test_catalog_table_model import cell, column_of, model_of, rehu, row

ASSET_COLUMNS = list(CatalogColumn)[-13:]


def asset(path: str, **fields: object) -> CatalogRecord:
    """An asset record at ``path``.

    :param path: its root-relative path.
    :param fields: its fields.
    :returns: the record.
    """
    return rehu(path, type="asset", **fields)


def test_an_asset_row_shows_each_of_its_fields() -> None:
    """Each of the thirteen columns reads its field: the lists joined in the record's order, the compatibility as
    ``name: versions``, the numbers as numbers and the advertised ranges as the text they are.

    **Test steps:**

    * build a model of one asset carrying every field
    * verify each of the asset's thirteen cells
    """
    model = model_of(
        row(
            asset(
                "a/info.rehu",
                asset_kind="model",
                licenses=("fab-standard", "fab-uefn-reference-only"),
                formats=("fbx", "glb"),
                compatibility=(("unreal", "5.1-5.6"), ("blender", ">=4")),
                source_updated="2025-02",
                advertised_version="1.2",
                current_version="1.1",
                advertised_size=12096296,
                advertised_triangles="12,40-60",
                advertised_texture_size="1024",
                triangles=5000,
                texture_size=4096,
                acquired="2024-05-03T12:34:56.789123Z",
            )
        )
    )

    assert [cell(model, 0, column) for column in ASSET_COLUMNS] == [
        "model",
        "fab-standard, fab-uefn-reference-only",
        "fbx, glb",
        "unreal: 5.1-5.6, blender: >=4",
        "2025-02",
        "1.2",
        "1.1",
        12096296,
        "12,40-60",
        "1024",
        5000,
        4096,
        "2024-05-03T12:34:56.789123Z",
    ]


def test_a_record_with_none_of_them_has_empty_cells_and_a_size_tooltip_only_where_there_is_a_size() -> None:
    """A record that is no asset reads empty in every one of them; the advertised size's tooltip is its exact bytes.

    **Test steps:**

    * build a model of a tutorial and of an asset with an advertised size
    * verify the tutorial's cells are empty, and the sizes' tooltips
    """
    model = model_of(row(rehu("t/info.rehu", type="tutorial")), row(asset("a/info.rehu", advertised_size=1536)))

    assert [cell(model, 0, column) for column in ASSET_COLUMNS] == [None] * 13
    assert cell(model, 1, CatalogColumn.ADVERTISED_SIZE, Qt.ItemDataRole.ToolTipRole) == "1,536 bytes"
    assert cell(model, 0, CatalogColumn.ADVERTISED_SIZE, Qt.ItemDataRole.ToolTipRole) is None


def test_the_numbers_align_right_and_the_texts_do_not() -> None:
    """The size and the counts are numbers, the advertised ranges too, though they are text; kind and license are not.

    **Test steps:**

    * ask which of the thirteen columns are numeric
    * verify the sizes, counts and ranges
    """
    assert {column for column in ASSET_COLUMNS if COLUMNS[column].numeric} == {
        CatalogColumn.ADVERTISED_SIZE,
        CatalogColumn.ADVERTISED_TRIANGLES,
        CatalogColumn.ADVERTISED_TEXTURE_SIZE,
        CatalogColumn.TRIANGLES,
        CatalogColumn.TEXTURE_SIZE,
    }


def sorted_by(model: CatalogTableModel, column: CatalogColumn, order: Qt.SortOrder) -> list[str]:
    """The titles of a model's rows after sorting by a column.

    :param model: the model.
    :param column: the column.
    :param order: which way.
    :returns: the titles, top to bottom.
    """
    model.sort(column, order)
    return column_of(model, CatalogColumn.TITLE)


def test_the_advertised_ranges_and_the_versions_sort_by_their_numbers() -> None:
    """``9`` sorts before ``12,40-60`` and ``1.9`` before ``1.10``, as a person reads them, and a record with none
    sorts first ascending.

    **Test steps:**

    * build assets with advertised triangles of ``12,40-60``, ``9`` and none, and versions ``1.10`` and ``1.9``
    * sort by the triangles and by the version
    * verify the numeric order, the missing first
    """
    model = model_of(
        row(asset("a/info.rehu", title="a", advertised_triangles="12,40-60", advertised_version="1.10")),
        row(asset("b/info.rehu", title="b", advertised_triangles="9", advertised_version="1.9")),
        row(asset("c/info.rehu", title="c")),
    )

    assert sorted_by(model, CatalogColumn.ADVERTISED_TRIANGLES, Qt.SortOrder.AscendingOrder) == ["c", "b", "a"]
    assert sorted_by(model, CatalogColumn.ADVERTISED_VERSION, Qt.SortOrder.AscendingOrder) == ["c", "b", "a"]


def test_kinds_sort_ignoring_case_with_a_missing_one_first() -> None:
    """A kind sorts as text, case ignored, and a record with none is the smallest.

    **Test steps:**

    * build assets of kind ``Pack``, ``model`` and none
    * sort by kind ascending
    * verify none first, then ``model`` before ``Pack``
    """
    model = model_of(
        row(asset("x/info.rehu", title="x", asset_kind="Pack")),
        row(asset("y/info.rehu", title="y", asset_kind="model")),
        row(asset("z/info.rehu", title="z")),
    )

    assert sorted_by(model, CatalogColumn.KIND, Qt.SortOrder.AscendingOrder) == ["z", "y", "x"]


def test_only_acquired_is_shown_by_a_preset_and_every_column_is_a_type_field() -> None:
    """A preset leaves twelve of the thirteen to the header menu; each is some type field's column.

    **Test steps:**

    * ask which asset columns a preset shows
    * verify only Acquired, and that the type fields map onto every one of them
    """
    assert [column for column in ASSET_COLUMNS if COLUMNS[column].preset_visible] == [CatalogColumn.ACQUIRED]
    assert set(TYPE_COLUMNS) == set(TYPE_FIELD_NAMES)
    assert set(ASSET_COLUMNS) <= set(TYPE_COLUMNS.values())


def test_sizes_and_times_are_worded_by_their_delegates() -> None:
    """The advertised size reads as a size, the two times in local time.

    **Test steps:**

    * look up the delegates of the asset's columns
    * verify the size and the two times, and no delegate for a text
    """
    assert COLUMN_DELEGATES[CatalogColumn.ADVERTISED_SIZE] is SizeDelegate
    assert COLUMN_DELEGATES[CatalogColumn.SOURCE_UPDATED] is LocalTimeDelegate
    assert COLUMN_DELEGATES[CatalogColumn.ACQUIRED] is LocalTimeDelegate
    assert CatalogColumn.KIND not in COLUMN_DELEGATES
