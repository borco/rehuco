"""Tests for an asset's own fields in the catalog cache: a column per scalar, ``compatibility`` as JSON, and the
formats value table (#676, [[assets#block]]).

The cache is :mod:`test_rehudb`'s, over a shared-cache in-memory database; its fixtures are imported by name.
"""

from collections.abc import Callable

from pytest_mock import MockerFixture
from rehuco_core import MAX_STORED_INTEGER, TYPE_FIELD_COLUMNS, CatalogCache, MappedRoot

from rehuco_core_tests.mapped_roots import mapped
from rehuco_core_tests.test_rehudb import (  # noqa: F401  # pylint: disable=unused-import
    MemoryDatabase,
    fixture_cache,
    fixture_database,
    fixture_memory,
    record,
    two_roots,
    upgraded_one_record,
)


def first_root(cache: CatalogCache) -> MappedRoot:
    """Reconcile the two test roots into ``cache`` and hand back the first.

    :param cache: the cache to reconcile.
    :returns: the first root.
    """
    rehuco, first, _ = two_roots()
    cache.reconcile_roots(mapped(rehuco))
    return first


def test_every_asset_field_round_trips(cache: CatalogCache) -> None:
    """What a scan read of an asset is what the browser reads back, its formats and compatibility in their order.

    **Test steps:**

    * scan an asset record carrying every asset field the cache stores
    * read its row back
    * verify the record is the one written
    """
    root = first_root(cache)
    written = record(
        "a/info.rehu",
        type="asset",
        asset_kind="model",
        compatibility=(("unreal", "5.1-5.6"), ("blender", ">=4,<5")),
        source_updated="2025-02",
        advertised_version="1.2",
        current_version="1.1",
        advertised_size=12096296,
        triangles=5000,
        texture_size=4096,
        acquired="2024-05-03T12:34:56.789123Z",
        formats=("glb", "fbx"),
        licenses=("fab-standard", "fab-uefn-reference-only"),
    )

    cache.apply_root_scan(root.root_id, [written])

    (row,) = cache.rows()
    assert row.record == written


def test_compatibility_is_kept_as_a_json_object_and_none_as_null(cache: CatalogCache, database: MemoryDatabase) -> None:
    """``compatibility`` is stored as its JSON object, its non-ASCII text as it is; an asset with none stores ``NULL``.

    **Test steps:**

    * scan an asset with a compatibility entry holding a non-ASCII value, and one with none
    * verify the first's column is the JSON object and the second's is ``NULL``
    """
    root = first_root(cache)

    cache.apply_root_scan(
        root.root_id,
        [
            record("a/info.rehu", type="asset", compatibility=(("unreal", "5.1–5.6"),)),
            record("b/info.rehu", type="asset"),
        ],
    )

    assert database.scalar("SELECT compatibility FROM resources WHERE path = 'a/info.rehu'") == '{"unreal": "5.1–5.6"}'
    assert database.scalar("SELECT compatibility FROM resources WHERE path = 'b/info.rehu'") is None


def test_two_assets_keep_their_own_spelling_of_one_format(cache: CatalogCache, database: MemoryDatabase) -> None:
    """A format is one value row matched ignoring case, each asset reading it as it spells it, as tags do.

    **Test steps:**

    * scan two assets naming one format in two cases
    * verify one value row is kept and each row reads its own spelling
    """
    root = first_root(cache)

    cache.apply_root_scan(
        root.root_id,
        [record("a/info.rehu", type="asset", formats=("FBX",)), record("b/info.rehu", type="asset", formats=("fbx",))],
    )

    assert database.scalar("SELECT COUNT(*) FROM formats") == 1
    assert [row.record.formats for row in cache.rows()] == [("FBX",), ("fbx",)]


def test_a_format_no_record_names_any_more_is_dropped(cache: CatalogCache, database: MemoryDatabase) -> None:
    """A rescan that leaves a format unnamed removes its value row, as it does an author's or a tag's.

    **Test steps:**

    * scan an asset with two formats, then scan it again with one
    * verify only the format still named is left
    """
    root = first_root(cache)
    cache.apply_root_scan(root.root_id, [record("a/info.rehu", type="asset", formats=("fbx", "glb"))])

    cache.apply_root_scan(root.root_id, [record("a/info.rehu", type="asset", formats=("glb",))])

    assert database.scalar("SELECT group_concat(name) FROM formats") == "glb"


def test_a_version_9_cache_upgrades_with_no_asset_fields_and_stale(
    memory: Callable[[], MemoryDatabase], mocker: MockerFixture
) -> None:
    """The version-10 step adds an asset's fields: a row from before it reads them empty, and carries no signature a
    real file could match, so the next scan reads them in.

    **Test steps:**

    * build a version-9 cache holding one scanned record and reopen it with the full chain
    * verify the stamp is current and the row is kept with every type field and its formats empty and its signature
      cleared
    """
    row = upgraded_one_record(memory, mocker, 9)

    assert row.record.title == "T"
    assert all(getattr(row.record, name) in {None, ()} for name in TYPE_FIELD_COLUMNS)
    assert row.record.formats == ()
    assert (row.record.mtime_ns, row.record.content_hash) == (0, "")


def test_a_size_beyond_what_the_cache_holds_is_kept_unknown_and_stops_nothing(cache: CatalogCache) -> None:
    """A whole number a ``.rehu`` names that SQLite's signed 64-bit integers cannot hold is stored as ``NULL``, so the
    scan that reads it lands every record of its root; the largest number they hold is kept (#678).

    **Test steps:**

    * scan assets whose size, triangles and texture side are a number beyond the limit, its negative, and the limit
    * verify every row is written, the first two read unknown and the last reads the limit
    """
    root = first_root(cache)

    cache.apply_root_scan(
        root.root_id,
        [
            record("a/info.rehu", type="asset", advertised_size=10**20, triangles=2**63, texture_size=-(10**20)),
            record("b/info.rehu", type="asset", advertised_size=MAX_STORED_INTEGER, triangles=-MAX_STORED_INTEGER),
        ],
    )

    first, second = (row.record for row in cache.rows())
    assert (first.advertised_size, first.triangles, first.texture_size) == (None, None, None)
    assert (second.advertised_size, second.triangles) == (MAX_STORED_INTEGER, -MAX_STORED_INTEGER)
