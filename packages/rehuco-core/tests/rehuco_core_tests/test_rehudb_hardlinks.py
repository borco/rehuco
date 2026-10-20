"""Tests for the cache's half of "a record has one row" (#498): the file identity a scan hands it, kept on the rows, and
the rule that settles one file named under two roots.

The cache is :mod:`test_rehudb`'s, over a shared-cache in-memory database read raw through its keeper; its fixtures are
imported by name. The identities are made up: what a real hardlink reports is `test_rehudb_scan_roots`'s to prove.
"""

from collections.abc import Callable
from pathlib import Path

from pytest_mock import MockerFixture
from rehuco_core import CatalogCache, HardlinkedRecord, RehucoRoot, RootScanEffects
from rehuco_core.migrations.rehudb import CHAIN, CURRENT_VERSION

from rehuco_core_tests.test_rehudb import (  # noqa: F401  # pylint: disable=unused-import
    MemoryDatabase,
    fixture_cache,
    fixture_database,
    fixture_filled,
    fixture_memory,
    ids,
    record,
    two_roots,
)


def file_ids(database: MemoryDatabase) -> dict[str, str | None]:
    """Every row's ``file_id``, by its root-relative path, read raw.

    :param database: the cache's database.
    :returns: the identities.
    """
    return dict(database.keeper.execute("SELECT path, file_id FROM resources").fetchall())


# region Identities


def test_a_scan_writes_the_identities_it_was_handed_and_clears_the_rest(
    database: MemoryDatabase, filled: tuple[CatalogCache, RehucoRoot, RehucoRoot]
) -> None:
    """A record read or found unchanged keeps the identity the scan gives it; one given none -- its file down to one
    name -- loses the one it had, and another root's rows are left alone.

    **Test steps:**

    * scan two hardlinked records under the first root, one read and one unchanged, and one under the second root
    * verify each carries its identity
    * rescan the first root with only the read record's identity; verify the unchanged one's is cleared, the other
      root's kept
    """
    cache, first, second = filled
    cache.apply_root_scan(first.root_id, [record("kept.rehu")])
    cache.apply_root_scan(second.root_id, [record("p.rehu")], identities={"p.rehu": "9:9"})

    cache.apply_root_scan(
        first.root_id,
        [record("read.rehu")],
        unchanged=("kept.rehu",),
        identities={"read.rehu": "1:1", "kept.rehu": "1:2"},
    )

    assert file_ids(database) == {"read.rehu": "1:1", "kept.rehu": "1:2", "p.rehu": "9:9"}
    cache.apply_root_scan(
        first.root_id, [record("read.rehu")], unchanged=("kept.rehu",), identities={"read.rehu": "1:1"}
    )
    assert file_ids(database) == {"read.rehu": "1:1", "kept.rehu": None, "p.rehu": "9:9"}


# endregion

# region One file under two roots


def test_the_later_roots_row_goes_when_the_earlier_root_finds_the_file(
    database: MemoryDatabase, filled: tuple[CatalogCache, RehucoRoot, RehucoRoot]
) -> None:
    """The earlier root in the ``.rehuco`` keeps the row, so its scan deletes the later root's -- and says so, the
    deleted row among the touched ones.

    **Test steps:**

    * scan the file under the second root, then under the first
    * verify the second root's row is gone and touched, the pair reported, and one row stays, under the first root
    """
    cache, first, second = filled
    cache.apply_root_scan(second.root_id, [record("b.rehu"), record("other.rehu")], identities={"b.rehu": "1:1"})
    lost = ids(cache)["b.rehu"]
    effects = RootScanEffects()

    assert cache.apply_root_scan(first.root_id, [record("a.rehu")], identities={"a.rehu": "1:1"}, effects=effects)

    assert lost in effects.touched
    assert effects.hardlinked == [HardlinkedRecord(first.root_id, "a.rehu", second.root_id, "b.rehu")]
    assert file_ids(database) == {"a.rehu": "1:1", "other.rehu": None}


def test_the_later_roots_name_is_not_written_when_the_earlier_root_holds_the_file(
    database: MemoryDatabase, filled: tuple[CatalogCache, RehucoRoot, RehucoRoot]
) -> None:
    """Scanned the other way round, the later root's name loses: neither read nor kept unchanged, and a row it had
    from before is swept.

    **Test steps:**

    * scan the file under the first root; give the second root a row for its name from before
    * rescan the second root with the name read once and unchanged once
    * verify the name has no row, its old one was swept and touched, the pair reported, the first root's row kept
    """
    cache, first, second = filled
    cache.apply_root_scan(first.root_id, [record("a.rehu")], identities={"a.rehu": "1:1"})
    cache.apply_root_scan(second.root_id, [record("b.rehu")])
    old = ids(cache)["b.rehu"]

    for read, unchanged in (([record("b.rehu")], ()), ([], ("b.rehu",))):
        effects = RootScanEffects()
        cache.apply_root_scan(second.root_id, read, unchanged=unchanged, identities={"b.rehu": "1:1"}, effects=effects)

        assert effects.hardlinked == [HardlinkedRecord(first.root_id, "a.rehu", second.root_id, "b.rehu")]
        assert file_ids(database) == {"a.rehu": "1:1"}
    assert old not in ids(cache).values()


def test_a_scan_with_no_identities_settles_nothing(
    filled: tuple[CatalogCache, RehucoRoot, RehucoRoot],
) -> None:
    """A file with one name has no identity, so another root's row for a hardlinked record is no business of it.

    **Test steps:**

    * scan a hardlinked record under the second root
    * scan the first root with no identities
    * verify nothing was reported and the second root's row stays
    """
    cache, first, second = filled
    cache.apply_root_scan(second.root_id, [record("b.rehu")], identities={"b.rehu": "1:1"})
    effects = RootScanEffects()

    cache.apply_root_scan(first.root_id, [record("a.rehu")], effects=effects)

    assert not effects.hardlinked
    assert sorted(ids(cache)) == ["a.rehu", "b.rehu"]


# endregion

# region The schema step


def test_a_version_6_cache_upgrades_with_a_file_identity_column_and_its_index(
    memory: Callable[[], MemoryDatabase], mocker: MockerFixture, tmp_path: Path
) -> None:
    """The version-7 step adds ``file_id`` and its index: a row from before it keeps its place and reads no identity
    until the next scan sets one.

    **Test steps:**

    * build a version-6 cache holding one record
    * reopen it with the full chain
    * verify the stamp is current, the column and the index exist, and the row is kept with no identity
    """
    database = memory()
    mocker.patch("rehuco_core.rehudb.sqlite3.connect", side_effect=database.connect)
    cache_path = tmp_path / "catalog.rehudb"
    rehuco, first, _ = two_roots()
    with CatalogCache.open(cache_path, chain=CHAIN[:6]) as old:
        old.reconcile_roots(rehuco.roots)
        database.keeper.execute(
            "INSERT INTO resources (root_id, path, path_key, kind, title, mtime_ns, size, content_hash, scanned_at) "
            "VALUES (?, 'a/info.rehu', 'a/info.rehu', 'rehu', 'T', 42, 7, 'abc', 0)",
            (str(first.root_id),),
        )
    assert "file_id" not in {name for (_, name, *_) in database.keeper.execute("PRAGMA table_info(resources)")}

    with CatalogCache.open(cache_path) as upgraded:
        assert upgraded.schema_version == CURRENT_VERSION == 7
        assert [row.record.title for row in upgraded.rows()] == ["T"]

    assert file_ids(database) == {"a/info.rehu": None}
    assert database.scalar("SELECT name FROM sqlite_master WHERE type = 'index' AND name = 'resources_file_id'")


# endregion
