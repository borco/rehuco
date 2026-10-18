"""Tests for the Root Catalog (#417): the Root Catalog read from a ``.rehudb``, and the upkeep that
keeps it current between scans.

Every cache is a real file under ``tmp_path``; the rows a scan would find are written straight into it.
"""

import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from pytest import LogCaptureFixture, raises
from pytest_mock import MockerFixture
from rehuco_core import (
    DEFAULT_RENAME_COORDINATOR,
    Catalog,
    CatalogCache,
    CatalogQuery,
    CatalogRecord,
    CatalogUnreadable,
    KeyRelocation,
    RecordKind,
    RehucoRoot,
    RehuDocument,
    ResourceKey,
    check_records,
)

LIBRARY_ID: Final = UUID("00000000-0000-0000-0000-00000000000a")
PACKS_ID: Final = UUID("00000000-0000-0000-0000-00000000000b")


def record(path: str, **fields: Any) -> CatalogRecord:
    """A record as a scan reads it.

    :param path: root-relative.
    :param fields: any other field.
    :returns: the record.
    """
    return CatalogRecord(path, RecordKind.REHU, content_hash="0", **fields)


def roots_under(tmp_path: Path) -> tuple[RehucoRoot, RehucoRoot]:
    """Two roots, ``library`` and ``packs``, as a ``.rehuco`` lists them.

    :param tmp_path: pytest's temporary folder.
    :returns: the roots, in order.
    """
    return RehucoRoot(LIBRARY_ID, tmp_path / "library", "library"), RehucoRoot(PACKS_ID, tmp_path / "packs", "packs")


def attached(
    tmp_path: Path, roots: tuple[RehucoRoot, ...], scans: dict[UUID, list[CatalogRecord]] | None = None
) -> Catalog:
    """A catalog attached to a new cache holding ``roots``, with what a scan of each found.

    :param tmp_path: pytest's temporary folder.
    :param roots: the ``.rehuco``'s roots.
    :param scans: each root's records.
    :returns: the catalog.
    """
    cache_path = tmp_path / "catalog.rehudb"
    session = Catalog.prepare(cache_path, roots)
    with CatalogCache.open(cache_path) as cache:
        for root_id, records in (scans or {}).items():
            cache.apply_root_scan(root_id, records)
    catalog = Catalog()
    catalog.attach(session)
    return catalog


def paths_of(catalog: Catalog) -> list[tuple[UUID, str]]:
    """Every row the catalog lists, as ``(root id, relative path)``."""
    return [(row.root_id, row.record.path) for row in catalog.query(CatalogQuery())]


def write_record(path: Path, title: str) -> ResourceKey:
    """Write a ``.rehu`` with a title.

    :param path: where it goes; its folders are created.
    :param title: its title.
    :returns: its key.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    document = RehuDocument.new(path)
    document.title = title
    document.save()
    return ResourceKey(path)


# region Detached


def test_a_detached_catalog_answers_nothing_and_changes_nothing(tmp_path: Path) -> None:
    """With no cache attached every read is empty and every upkeep a no-op -- what the agent shows with no ``.rehuco``
    open.

    **Test steps:**

    * build a catalog and attach nothing
    * verify every read answers empty, and every upkeep answers nothing and attaches nothing
    """
    catalog = Catalog()
    key = ResourceKey(tmp_path / "library" / "info.rehu")
    library, packs = roots_under(tmp_path)

    catalog.reconcile([library, packs])
    catalog.hide(LIBRARY_ID)

    assert catalog.cache_path is None
    assert not catalog.roots()
    assert not catalog.query(CatalogQuery())
    assert catalog.row(key) is None
    assert catalog.count(LIBRARY_ID) == 0
    assert catalog.follow(KeyRelocation(((key, key.with_name("moved.rehu")),))) == set()
    assert not catalog.record_paths([key])
    catalog.mark_reachable(LIBRARY_ID, False)
    assert not catalog.plan_verify([key])
    assert catalog.apply_verify([]) == (set(), set())


def test_detaching_lets_the_cache_go(tmp_path: Path) -> None:
    """A detached catalog reads nothing more, and attaching again reads the same cache.

    **Test steps:**

    * attach a cache holding one row, note its session path, then detach
    * verify nothing is read, then attach a fresh session over the same file and verify the row is back
    """
    roots = roots_under(tmp_path)
    catalog = attached(tmp_path, roots, {LIBRARY_ID: [record("a/info.rehu")]})
    cache_path = catalog.cache_path
    assert cache_path is not None

    catalog.detach()
    assert not paths_of(catalog)

    catalog.attach(Catalog.prepare(cache_path, roots))
    assert paths_of(catalog) == [(LIBRARY_ID, "a/info.rehu")]


# endregion

# region Reads


def test_the_roots_and_rows_are_those_of_the_view(tmp_path: Path) -> None:
    """The roots come in the ``.rehuco``'s order, and the rows of every root it lists.

    **Test steps:**

    * attach a cache with two roots, each holding a row
    * verify both roots in order, and both rows
    """
    catalog = attached(
        tmp_path, roots_under(tmp_path), {LIBRARY_ID: [record("a/info.rehu")], PACKS_ID: [record("p/info.rehu")]}
    )

    assert [root.root_id for root in catalog.roots()] == [LIBRARY_ID, PACKS_ID]
    assert paths_of(catalog) == [(LIBRARY_ID, "a/info.rehu"), (PACKS_ID, "p/info.rehu")]


def test_a_query_matches_and_an_update_in_place_reads_only_its_rows(tmp_path: Path) -> None:
    """The query filters, and ``ids`` narrows the read to the rows asked for.

    **Test steps:**

    * attach a cache with two rows of different titles
    * verify a text query returns the matching one, and ``ids`` the one asked for
    """
    catalog = attached(
        tmp_path,
        roots_under(tmp_path),
        {LIBRARY_ID: [record("a/info.rehu", title="Blender"), record("b/info.rehu", title="Krita")]},
    )
    krita = next(row for row in catalog.query(CatalogQuery()) if row.record.title == "Krita")

    assert [row.record.title for row in catalog.query(CatalogQuery(terms=("blend",)))] == ["Blender"]
    assert [row.record.title for row in catalog.query(CatalogQuery(), ids={krita.resource_id})] == ["Krita"]


def test_a_hidden_root_is_out_of_the_view_until_its_rows_are_removed(tmp_path: Path) -> None:
    """Remove Root drops a root from the view at once, while its rows wait for the removal job.

    **Test steps:**

    * attach a cache with a row under each root, and hide the first root
    * verify its root, its rows and its record's row are gone from the view, the other root's are not, and the cache
      still counts them
    """
    library, _ = roots = roots_under(tmp_path)
    catalog = attached(tmp_path, roots, {LIBRARY_ID: [record("a/info.rehu")], PACKS_ID: [record("p/info.rehu")]})

    catalog.hide(LIBRARY_ID)

    assert [root.root_id for root in catalog.roots()] == [PACKS_ID]
    assert paths_of(catalog) == [(PACKS_ID, "p/info.rehu")]
    assert catalog.row(ResourceKey(library.path / "a" / "info.rehu")) is None
    assert catalog.count(LIBRARY_ID) == 1


def test_a_row_is_found_by_its_key(tmp_path: Path) -> None:
    """``row`` is an indexed lookup by key: the record's row, and nothing for a key it has no row for.

    **Test steps:**

    * attach a cache with one row
    * verify its key answers its row, and an unscanned record and a path under no root answer nothing
    """
    library, _ = roots = roots_under(tmp_path)
    catalog = attached(tmp_path, roots, {LIBRARY_ID: [record("a/info.rehu", type="tutorial", uuid="id-a")]})

    row = catalog.row(ResourceKey(library.path / "a" / "info.rehu"))

    assert row is not None
    assert (row.root_id, row.record.type, row.record.uuid) == (LIBRARY_ID, "tutorial", "id-a")
    assert catalog.row(ResourceKey(library.path / "b" / "info.rehu")) is None
    assert catalog.row(ResourceKey(tmp_path / "elsewhere" / "info.rehu")) is None


def test_where_roots_nest_a_record_is_the_innermost_roots(tmp_path: Path) -> None:
    """A record under two nested roots has a row under each; its row is the innermost root's, as
    :meth:`~rehuco_core.CatalogCache.locate` decides -- never the outer root's, which the rows' order puts first.

    **Test steps:**

    * attach a cache whose second root is inside the first, each holding a row for the same record
    * verify the record's row is the inner root's; hiding the outer root changes nothing, hiding the inner one leaves
      no row
    """
    outer = RehucoRoot(LIBRARY_ID, tmp_path / "library", "library")
    inner = RehucoRoot(PACKS_ID, tmp_path / "library" / "sub", "sub")
    catalog = attached(
        tmp_path,
        (outer, inner),
        {LIBRARY_ID: [record("sub/x.rehu", title="outer")], PACKS_ID: [record("x.rehu", title="inner")]},
    )
    key = ResourceKey(inner.path / "x.rehu")

    row = catalog.row(key)
    assert row is not None
    assert (row.root_id, row.record.title) == (PACKS_ID, "inner")

    catalog.hide(LIBRARY_ID)
    row = catalog.row(key)
    assert row is not None
    assert row.root_id == PACKS_ID

    catalog.hide(PACKS_ID)
    assert catalog.row(key) is None


def test_a_root_counts_its_rows(tmp_path: Path) -> None:
    """``count`` is what removing a root would drop.

    **Test steps:**

    * attach a cache with two rows under one root and none under the other
    * verify the counts, and none for a root the cache does not have
    """
    catalog = attached(tmp_path, roots_under(tmp_path), {LIBRARY_ID: [record("a/info.rehu"), record("b/info.tc")]})

    assert catalog.count(LIBRARY_ID) == 2
    assert catalog.count(PACKS_ID) == 0
    assert catalog.count(UUID(int=0)) == 0


def test_any_thread_may_read(tmp_path: Path) -> None:
    """Each call opens the cache on the calling thread, so a worker reads as the attaching thread does.

    **Test steps:**

    * attach a cache on this thread, and query it from another
    * verify the other thread read the row and raised nothing
    """
    catalog = attached(tmp_path, roots_under(tmp_path), {LIBRARY_ID: [record("a/info.rehu")]})
    answers: list[object] = []
    worker = threading.Thread(target=lambda: answers.append(paths_of(catalog)))

    worker.start()
    worker.join()

    assert answers == [[(LIBRARY_ID, "a/info.rehu")]]


def test_a_cache_that_cannot_be_read_refuses_the_listings_and_answers_nothing_else(
    tmp_path: Path, mocker: MockerFixture, caplog: LogCaptureFixture
) -> None:
    """The roots and a query raise :class:`~rehuco_core.CatalogUnreadable`, never ``sqlite3.Error``; a row and a count
    answer nothing, logged.

    **Test steps:**

    * attach a cache, then make every read raise a database error
    * verify the two listings raise, and the row and the count answer nothing with the failures logged
    """
    library, _ = roots = roots_under(tmp_path)
    catalog = attached(tmp_path, roots, {LIBRARY_ID: [record("a/info.rehu")]})
    locked = sqlite3.OperationalError("locked")
    mocker.patch.object(CatalogCache, "roots", side_effect=locked)
    mocker.patch.object(CatalogCache, "rows", side_effect=locked)
    mocker.patch.object(CatalogCache, "resource_count", side_effect=locked)

    with raises(CatalogUnreadable, match="Could not read the roots of .*locked"):
        catalog.roots()
    with raises(CatalogUnreadable, match="Could not read the catalog .*locked"):
        catalog.query(CatalogQuery())
    with caplog.at_level(logging.ERROR):
        assert catalog.row(ResourceKey(library.path / "a" / "info.rehu")) is None
        assert catalog.count(LIBRARY_ID) == 0

    assert "Could not read the row of" in caplog.text
    assert f"Could not count the cached entries of the root {LIBRARY_ID}" in caplog.text


# endregion

# region The session


def test_preparing_a_cache_that_cannot_be_opened_or_reconciled_says_which(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    """``prepare`` refuses with what failed, so the agent's message can say it; a cache that fails is left closed.

    **Test steps:**

    * make the open fail, and prepare; then make the reconcile fail, spy on ``close``, and prepare again
    * verify each refusal names its step and the reason, and the second closed its connection
    """
    cache_path = tmp_path / "catalog.rehudb"
    opening = mocker.patch.object(CatalogCache, "open", side_effect=sqlite3.OperationalError("locked"))
    with raises(CatalogUnreadable, match="Could not open the cache of .*locked"):
        Catalog.prepare(cache_path, roots_under(tmp_path))
    mocker.stop(opening)

    mocker.patch.object(CatalogCache, "reconcile_roots", side_effect=sqlite3.OperationalError("busy"))
    close = mocker.spy(CatalogCache, "close")
    with raises(CatalogUnreadable, match="Could not read the cache of .*busy"):
        Catalog.prepare(cache_path, roots_under(tmp_path))
    close.assert_called_once()


def test_reconciling_follows_an_edit_of_the_roots(tmp_path: Path) -> None:
    """After an edit of the ``.rehuco``'s roots the cache and the view follow it: a dropped root loses its rows, a new
    one is listed with none.

    **Test steps:**

    * attach a cache with a row under each root
    * reconcile to the second root and a new one
    * verify the first root's row is gone from the cache, and the roots are the second and the new one
    """
    library, packs = roots_under(tmp_path)
    catalog = attached(
        tmp_path, (library, packs), {LIBRARY_ID: [record("a/info.rehu")], PACKS_ID: [record("p/info.rehu")]}
    )
    added = RehucoRoot(UUID(int=7), tmp_path / "added", "added")

    catalog.reconcile([packs, added])

    assert [root.root_id for root in catalog.roots()] == [PACKS_ID, added.root_id]
    assert paths_of(catalog) == [(PACKS_ID, "p/info.rehu")]
    assert catalog.count(LIBRARY_ID) == 0


def test_a_reconcile_that_fails_is_logged_and_the_view_still_follows_the_file(
    tmp_path: Path, mocker: MockerFixture, caplog: LogCaptureFixture
) -> None:
    """The next scan rebuilds the cache, so a failed reconcile is logged rather than raised; what the view lists still
    follows the ``.rehuco``.

    **Test steps:**

    * attach a cache with a row under each root, then make the reconcile fail and reconcile to the second root alone
    * verify the failure is logged with its cause, and only the second root's row is listed
    """
    library, packs = roots_under(tmp_path)
    catalog = attached(
        tmp_path, (library, packs), {LIBRARY_ID: [record("a/info.rehu")], PACKS_ID: [record("p/info.rehu")]}
    )
    mocker.patch.object(CatalogCache, "reconcile_roots", side_effect=sqlite3.OperationalError("locked"))

    with caplog.at_level(logging.ERROR):
        catalog.reconcile([packs])

    assert "Could not update the cache" in caplog.text and "locked" in caplog.text
    assert paths_of(catalog) == [(PACKS_ID, "p/info.rehu")]


# endregion

# region Keeping the cache current


def test_a_rename_rebases_its_rows_and_says_which(tmp_path: Path) -> None:
    """``follow`` moves the rows a rename moved, reading nothing, and answers their ids.

    **Test steps:**

    * attach a cache with a row under a folder, and follow that folder's rename
    * verify the row moved with its id kept and was answered; a rename of nothing answers nothing
    """
    library, _ = roots = roots_under(tmp_path)
    catalog = attached(tmp_path, roots, {LIBRARY_ID: [record("a/info.rehu")]})
    (before,) = catalog.query(CatalogQuery())

    affected = catalog.follow(KeyRelocation(((ResourceKey(library.path / "a"), ResourceKey(library.path / "b")),)))

    assert affected == {before.resource_id}
    assert [(row.resource_id, row.record.path) for row in catalog.query(CatalogQuery())] == [
        (before.resource_id, "b/info.rehu")
    ]
    assert catalog.follow(KeyRelocation(((ResourceKey(library.path / "x"), ResourceKey(library.path / "y")),))) == set()


def test_the_records_at_or_beneath_a_key_are_read_from_the_cache(tmp_path: Path) -> None:
    """``record_paths`` answers the records the cache holds at or beneath each key -- a record itself, everything under
    a folder -- each once, as absolute paths; a key under no root adds nothing, and so does an empty request (#511).

    **Test steps:**

    * attach a cache with rows in two folders of one root and one in the other root
    * verify a folder key answers the records beneath it, a record key answers itself, and a key given twice, a key
      under no root and no keys at all add nothing more
    """
    library, packs = roots = roots_under(tmp_path)
    catalog = attached(
        tmp_path,
        roots,
        {
            LIBRARY_ID: [record("a/one.rehu"), record("a/deep/two.rehu"), record("b/three.rehu")],
            PACKS_ID: [record("p.rehu")],
        },
    )
    folder = ResourceKey(library.path / "a")
    single = ResourceKey(packs.path / "p.rehu")

    found = catalog.record_paths([folder, single, folder, ResourceKey(tmp_path / "elsewhere")])

    assert sorted(found) == sorted(
        [library.path / "a" / "one.rehu", library.path / "a" / "deep" / "two.rehu", single.path]
    )
    assert len(found) == 3
    assert not catalog.record_paths([])


def test_a_roots_reachability_is_recorded_for_a_root_of_the_view_only(tmp_path: Path) -> None:
    """``mark_reachable`` writes what the root's file notifier saw into its cache row, its rows untouched; a root the
    view dropped is left alone (#511).

    **Test steps:**

    * attach a cache whose library has a row, and mark it unreachable, then reachable again
    * verify the root's reachability follows each mark and its row is still listed
    * hide the packs root, mark it unreachable, and verify its cache row is unchanged
    """
    roots = roots_under(tmp_path)
    catalog = attached(tmp_path, roots, {LIBRARY_ID: [record("a/info.rehu")], PACKS_ID: []})

    def reachable(root_id: UUID) -> bool | None:
        """What the cache says of a root's reachability."""
        with CatalogCache.open(tmp_path / "catalog.rehudb") as cache:
            return next(root.reachable for root in cache.roots() if root.root_id == root_id)

    catalog.mark_reachable(LIBRARY_ID, False)
    assert reachable(LIBRARY_ID) is False
    assert paths_of(catalog) == [(LIBRARY_ID, "a/info.rehu")]
    catalog.mark_reachable(LIBRARY_ID, True)
    assert reachable(LIBRARY_ID) is True

    catalog.hide(PACKS_ID)
    catalog.mark_reachable(PACKS_ID, False)
    assert reachable(PACKS_ID) is True


def test_verify_on_access_plans_from_the_cache_and_applies_what_the_disk_showed(tmp_path: Path) -> None:
    """The cache halves of verify-on-access: a plan read from the cache alone, and the disk's findings written back.

    **Test steps:**

    * attach an empty cache, and write a record it has no row for
    * plan a verify of it, check the plan against the disk, and apply the findings
    * verify one check was planned, and its row is now listed and answered as changed
    """
    library, _ = roots = roots_under(tmp_path)
    catalog = attached(tmp_path, roots)
    key = write_record(library.path / "a" / "info.rehu", "Checked")

    checks = catalog.plan_verify([key])
    affected, changed = catalog.apply_verify(check_records(checks, DEFAULT_RENAME_COORDINATOR).findings)

    (row,) = catalog.query(CatalogQuery())
    assert [check.path for check in checks] == [key.path]
    assert affected == {row.resource_id}
    assert changed == {key.path}
    assert row.record.title == "Checked"


def test_upkeep_that_cannot_reach_the_cache_is_logged_and_answers_nothing(
    tmp_path: Path, mocker: MockerFixture, caplog: LogCaptureFixture
) -> None:
    """The next scan rebuilds what upkeep missed, so each failure is logged and answers as if nothing changed.

    **Test steps:**

    * attach a cache with a row, and write a record it has none for; plan a verify of it while the cache works
    * make the cache's reads and the updater's plan and apply raise a database error
    * make the cache's record paths and reachability writes raise too
    * verify a rename, a record lookup, a reachability mark, a plan and an apply each answer nothing, and each
      failure is logged
    """
    library, _ = roots = roots_under(tmp_path)
    catalog = attached(tmp_path, roots, {LIBRARY_ID: [record("a/info.rehu")]})
    key = write_record(library.path / "b" / "info.rehu", "Late")
    findings = check_records(catalog.plan_verify([key]), DEFAULT_RENAME_COORDINATOR).findings
    locked = sqlite3.OperationalError("locked")
    mocker.patch.object(CatalogCache, "resource_ids", side_effect=locked)
    mocker.patch("rehuco_core.access.catalog.CatalogRecordUpdater.plan", side_effect=locked)
    mocker.patch.object(CatalogCache, "record_paths", side_effect=locked)
    mocker.patch.object(CatalogCache, "mark_root_reachable", side_effect=locked)

    with caplog.at_level(logging.ERROR):
        assert (
            catalog.follow(KeyRelocation(((ResourceKey(library.path / "a"), ResourceKey(library.path / "c")),)))
            == set()
        )
        assert not catalog.record_paths([key])
        catalog.mark_reachable(LIBRARY_ID, False)
        assert not catalog.plan_verify([key])
        assert catalog.apply_verify(findings) == (set(), set())

    assert "Could not follow a rename in the cache" in caplog.text
    assert "Could not update the cache" in caplog.text
    assert f"Could not read the cache {catalog.cache_path}: locked" in caplog.text
    assert "Could not read the cache" in caplog.text and "to verify records" in caplog.text


# endregion
