"""Tests for what the cache lets a search ask of an asset: its kind, licenses and formats, and a comparison of an
advertised range by its bounds (#678, [[assets#ranges]], [[assets#kind]]).

The cache is :mod:`test_rehudb`'s, over a shared-cache in-memory database; its fixtures are imported by name.
"""

from collections.abc import Callable

from pytest import mark
from pytest_mock import MockerFixture
from rehuco_core import (
    CatalogCache,
    CatalogComparison,
    CatalogField,
    CatalogOperator,
    CatalogQuery,
    CatalogRangeField,
)

from rehuco_core_tests.test_rehudb import (  # noqa: F401  # pylint: disable=unused-import
    MemoryDatabase,
    fixture_cache,
    fixture_database,
    fixture_memory,
    record,
    upgraded_one_record,
)
from rehuco_core_tests.test_rehudb_asset_fields import first_root


def found(cache: CatalogCache, query: CatalogQuery) -> list[str]:
    """The root-relative paths of the rows a query reads, in the cache's order.

    :param cache: the cache.
    :param query: what to read.
    :returns: the paths.
    """
    return [row.record.path for row in cache.rows(query)]


def compared(field: CatalogRangeField, operator: CatalogOperator, number: int) -> CatalogQuery:
    """A query of one comparison.

    :param field: the range field.
    :param operator: how to compare it.
    :param number: what to.
    :returns: the query.
    """
    return CatalogQuery(comparisons=(CatalogComparison(field, operator, number),))


def kind_query(value: str) -> CatalogQuery:
    """A query of one ``kind`` token.

    :param value: the token's value.
    :returns: the query.
    """
    return CatalogQuery(tokens=((CatalogField.KIND, value),))


def test_the_bounds_of_an_advertised_range_are_written_with_its_text(
    cache: CatalogCache, database: MemoryDatabase
) -> None:
    """Each advertised range keeps its text and, beside it, its smallest and largest value; text that is no range, or
    none, keeps ``NULL`` bounds, and a rescan that drops the text drops them.

    **Test steps:**

    * scan an asset with a list of bands and a plain value, one whose text is no range, and one with neither
    * verify the text and the bounds of each row
    * scan the first again without its triangles
    * verify its triangle bounds are ``NULL`` again
    """
    root = first_root(cache)
    cache.apply_root_scan(
        root.root_id,
        [
            record("a/info.rehu", type="asset", advertised_triangles="12,40-60", advertised_texture_size="2048"),
            record("b/info.rehu", type="asset", advertised_triangles="many", advertised_texture_size="4-2"),
            record("c/info.rehu", type="asset"),
        ],
    )

    columns = (
        "SELECT advertised_triangles, advertised_triangles_lower, advertised_triangles_upper, "
        "advertised_texture_size_lower, advertised_texture_size_upper FROM resources WHERE path = ?"
    )
    assert database.keeper.execute(columns, ("a/info.rehu",)).fetchone() == ("12,40-60", 12, 60, 2048, 2048)
    assert database.keeper.execute(columns, ("b/info.rehu",)).fetchone() == ("many", None, None, None, None)
    assert database.keeper.execute(columns, ("c/info.rehu",)).fetchone() == (None, None, None, None, None)

    cache.apply_root_scan(root.root_id, [record("a/info.rehu", type="asset", advertised_texture_size="2048")])

    assert database.keeper.execute(columns, ("a/info.rehu",)).fetchone() == (None, None, None, 2048, 2048)


def test_a_number_too_long_for_the_cache_is_no_range_and_stops_nothing(cache: CatalogCache) -> None:
    """A text of a number beyond what SQLite's integers hold has no bounds, so a scan that reads one still lands.

    **Test steps:**

    * scan an asset whose range text is a 40-digit number beside an ordinary one
    * verify both rows are written and a comparison finds only the ordinary one
    """
    root = first_root(cache)

    cache.apply_root_scan(
        root.root_id,
        [
            record("a/info.rehu", type="asset", advertised_triangles="9" * 40),
            record("b/info.rehu", type="asset", advertised_triangles="5"),
        ],
    )

    assert [row.record.path for row in cache.rows()] == ["a/info.rehu", "b/info.rehu"]
    assert found(cache, compared(CatalogRangeField.ADVERTISED_TRIANGLES, CatalogOperator.GREATER, 0)) == ["b/info.rehu"]


@mark.parametrize(
    ("operator", "number", "expected"),
    [
        (CatalogOperator.LESS, 15, ["12", "1-14", "12-13", "14", "10-20", "12,40-60"]),
        (CatalogOperator.LESS, 12, ["1-14", "10-20"]),
        (CatalogOperator.LESS_OR_EQUAL, 12, ["12", "1-14", "12-13", "10-20", "12,40-60"]),
        (CatalogOperator.GREATER, 15, ["10-20", "12,40-60", "40-50"]),
        (CatalogOperator.GREATER, 60, []),
        (CatalogOperator.GREATER_OR_EQUAL, 60, ["12,40-60"]),
        (CatalogOperator.GREATER_OR_EQUAL, 14, ["1-14", "14", "10-20", "12,40-60", "40-50"]),
    ],
)
def test_a_comparison_matches_when_any_value_of_the_range_does(
    cache: CatalogCache, operator: CatalogOperator, number: int, expected: list[str]
) -> None:
    """``<`` and ``<=`` read a range's smallest value and ``>`` and ``>=`` its largest, so ``<15`` finds ``14``,
    ``12-13``, ``1-14`` and ``10-20``; a text that is no range is never found, nor a record of another type.

    **Test steps:**

    * scan assets whose ranges are values, bands and lists, one whose text is no range, and a tutorial
    * compare the advertised triangles to a number
    * verify the rows found are those whose range holds a value that does
    """
    root = first_root(cache)
    ranges = ["12", "1-14", "12-13", "14", "10-20", "12,40-60", "40-50", "many", ""]
    cache.apply_root_scan(
        root.root_id,
        [
            *(
                record(f"{index:02}/info.rehu", type="asset", advertised_triangles=text)
                for index, text in enumerate(ranges)
            ),
            record("tutorial/info.rehu", type="tutorial"),
        ],
    )
    texts = dict(enumerate(ranges))

    paths = found(cache, compared(CatalogRangeField.ADVERTISED_TRIANGLES, operator, number))

    assert [texts[int(path[:2])] for path in paths] == [text for text in ranges if text in expected]


def test_the_texture_size_is_compared_apart_from_the_triangles(cache: CatalogCache) -> None:
    """Each range field is compared by its own bounds.

    **Test steps:**

    * scan an asset with a small triangle count and a large texture, and one the other way round
    * compare each field to one number
    * verify each comparison finds the asset that holds a value that does
    """
    root = first_root(cache)
    cache.apply_root_scan(
        root.root_id,
        [
            record("a/info.rehu", type="asset", advertised_triangles="100", advertised_texture_size="4096"),
            record("b/info.rehu", type="asset", advertised_triangles="900000", advertised_texture_size="512"),
        ],
    )

    assert found(
        cache, compared(CatalogRangeField.ADVERTISED_TEXTURE_SIZE, CatalogOperator.GREATER_OR_EQUAL, 2048)
    ) == ["a/info.rehu"]
    assert found(cache, compared(CatalogRangeField.ADVERTISED_TRIANGLES, CatalogOperator.GREATER, 1000)) == [
        "b/info.rehu"
    ]


def test_every_comparison_must_hold(cache: CatalogCache) -> None:
    """Two comparisons of one field are both required, so a band is asked for with a pair.

    **Test steps:**

    * scan assets of 5, 50 and 500 triangles
    * ask for more than 10 and less than 100
    * verify only the middle one is found
    """
    root = first_root(cache)
    cache.apply_root_scan(
        root.root_id,
        [record(f"{count}/info.rehu", type="asset", advertised_triangles=count) for count in ("5", "50", "500")],
    )
    field = CatalogRangeField.ADVERTISED_TRIANGLES

    query = CatalogQuery(
        comparisons=(
            CatalogComparison(field, CatalogOperator.GREATER, 10),
            CatalogComparison(field, CatalogOperator.LESS, 100),
        )
    )

    assert found(cache, query) == ["50/info.rehu"]


def test_unknown_finds_an_asset_with_no_kind_and_never_another_type(cache: CatalogCache) -> None:
    """``kind:unknown`` finds an asset the scan called unknown and one with no kind at all, in any ASCII case, and
    nothing of a record that is not an asset, whose kind is missing for good.

    **Test steps:**

    * scan assets of kind ``unknown``, ``model`` and none, and a tutorial
    * search ``unknown`` and ``UNKNOWN``
    * verify both find the first and the third, and not the tutorial
    """
    root = first_root(cache)
    cache.apply_root_scan(
        root.root_id,
        [
            record("a/info.rehu", type="asset", asset_kind="unknown"),
            record("b/info.rehu", type="Asset", asset_kind="model"),
            record("c/info.rehu", type="asset"),
            record("d/info.rehu", type="tutorial"),
        ],
    )

    assert found(cache, kind_query("unknown")) == ["a/info.rehu", "c/info.rehu"]
    assert found(cache, kind_query("UNKNOWN")) == ["a/info.rehu", "c/info.rehu"]


def test_an_empty_kind_finds_only_an_asset_with_none(cache: CatalogCache) -> None:
    """``kind:""`` finds the assets whose block names no kind, not one that says ``unknown``, and no other type.

    **Test steps:**

    * scan assets of kind ``unknown`` and none, and a tutorial
    * search an empty kind
    * verify only the asset with none is found
    """
    root = first_root(cache)
    cache.apply_root_scan(
        root.root_id,
        [
            record("a/info.rehu", type="asset", asset_kind="unknown"),
            record("b/info.rehu", type="asset"),
            record("c/info.rehu", type="tutorial"),
        ],
    )

    assert found(cache, kind_query("")) == ["b/info.rehu"]


def test_a_kind_matches_whole_and_ignores_ascii_case(cache: CatalogCache) -> None:
    """Any other kind matches the stored kind whole, as ``type`` does, and ``NOCASE`` folds ASCII only.

    **Test steps:**

    * scan assets of kind ``model``, ``Model``, ``modelling`` and ``bóok``
    * search ``MODEL`` and ``BÓOK``
    * verify the first finds the first two, and the second finds nothing
    """
    root = first_root(cache)
    cache.apply_root_scan(
        root.root_id,
        [
            record("a/info.rehu", type="asset", asset_kind="model"),
            record("b/info.rehu", type="asset", asset_kind="Model"),
            record("c/info.rehu", type="asset", asset_kind="modelling"),
            record("d/info.rehu", type="asset", asset_kind="bóok"),
        ],
    )

    assert found(cache, kind_query("MODEL")) == ["a/info.rehu", "b/info.rehu"]
    assert not found(cache, kind_query("BÓOK"))


def test_a_license_matches_any_entry_whole_by_its_folded_id(cache: CatalogCache) -> None:
    """``licenses:`` finds the records holding one license id among theirs, case and accents ignored, as ``formats:``
    finds a format (#705).

    **Test steps:**

    * scan assets under ``fab-standard`` (two spellings, one beside another license), ``cc-by-4.0`` and none
    * search ``FAB-STANDARD``
    * verify the first two are found
    """
    root = first_root(cache)
    cache.apply_root_scan(
        root.root_id,
        [
            record("a/info.rehu", type="asset", licenses=("fab-standard",)),
            record("b/info.rehu", type="asset", licenses=("fab-uefn-reference-only", "Fab-Standard")),
            record("c/info.rehu", type="asset", licenses=("cc-by-4.0",)),
            record("d/info.rehu", type="asset"),
        ],
    )

    query = CatalogQuery(tokens=((CatalogField.LICENSES, "FAB-STANDARD"),))

    assert found(cache, query) == ["a/info.rehu", "b/info.rehu"]


def test_a_format_matches_whole_by_its_folded_name_and_free_text_never_finds_it(cache: CatalogCache) -> None:
    """``formats:`` finds the assets delivering a format, case and accents ignored, as ``tags:`` does; a word in the
    line does not look in formats.

    **Test steps:**

    * scan assets delivering ``FBX``, ``glb`` and ``Blénd``
    * search ``formats:fbx``, ``formats:blend`` and the word ``fbx``
    * verify the tokens find their asset, and the word finds nothing
    """
    root = first_root(cache)
    cache.apply_root_scan(
        root.root_id,
        [
            record("a/info.rehu", type="asset", formats=("FBX", "glb")),
            record("b/info.rehu", type="asset", formats=("Blénd",)),
        ],
    )

    assert found(cache, CatalogQuery(tokens=((CatalogField.FORMATS, "fbx"),))) == ["a/info.rehu"]
    assert found(cache, CatalogQuery(tokens=((CatalogField.FORMATS, "blend"),))) == ["b/info.rehu"]
    assert not found(cache, CatalogQuery(terms=("fbx",)))


def test_a_version_10_cache_upgrades_with_no_ranges_and_stale(
    memory: Callable[[], MemoryDatabase], mocker: MockerFixture
) -> None:
    """The version-11 step adds the advertised ranges and their bounds: a row from before it reads them empty, and
    carries no signature a real file could match, so the next scan reads them in.

    **Test steps:**

    * build a version-10 cache holding one scanned record and reopen it with the full chain
    * verify the row is kept, its ranges are empty, and its signature is cleared
    """
    row = upgraded_one_record(memory, mocker, 10)

    assert row.record.title == "T"
    assert (row.record.advertised_triangles, row.record.advertised_texture_size) == (None, None)
    assert (row.record.mtime_ns, row.record.content_hash) == (0, "")


def test_a_version_11_cache_upgrades_with_no_licenses_and_stale(
    memory: Callable[[], MemoryDatabase], mocker: MockerFixture
) -> None:
    """The version-12 step keeps licenses in a value table and drops the one ``license`` column (#705): a row from
    before it reads no licenses, and carries no signature a real file could match, so the next scan reads them in.

    **Test steps:**

    * build a version-11 cache holding one scanned record and reopen it with the full chain
    * verify the row is kept, it has no licenses, and its signature is cleared
    """
    row = upgraded_one_record(memory, mocker, 11)

    assert row.record.title == "T"
    assert row.record.licenses == ()
    assert (row.record.mtime_ns, row.record.content_hash) == (0, "")


def test_the_cache_has_no_license_column_any_more(cache: CatalogCache) -> None:
    """A record's licenses are a value table's, so ``resources`` keeps no column of one license (#705).

    **Test steps:**

    * read the columns of ``resources`` in a current cache
    * verify none is ``license``, and the licenses tables exist
    """
    columns = {name for _, name, *_ in cache.connection.execute("PRAGMA table_info(resources)")}
    tables = {name for (name,) in cache.connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

    assert "license" not in columns
    assert {"licenses", "resource_licenses"} <= tables
