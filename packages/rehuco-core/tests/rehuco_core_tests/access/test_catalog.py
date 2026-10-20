"""Tests for the Root Catalog (#417): the Root Catalog read from a ``.rehudb``, and the upkeep that
keeps it current between scans.

The cache is a mock (#545): what it answers is set per test, and what is asserted is the catalog's part -- which roots
and rows its view lets through, what it asks the cache for, and how it reports a cache that fails. The cache itself is
tested on its own (`test_rehudb`), as is the verify updater (`test_rehudb_updates`), mocked here too.
"""

import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any, Final
from unittest.mock import MagicMock
from uuid import UUID

from pytest import LogCaptureFixture, fixture, raises
from pytest_mock import MockerFixture
from rehuco_core import (
    DEFAULT_RENAME_COORDINATOR,
    Catalog,
    CatalogCache,
    CatalogQuery,
    CatalogRecord,
    CatalogRoot,
    CatalogRow,
    CatalogUnreadable,
    KeyRelocation,
    RecordKind,
    RehucoRoot,
    ResourceKey,
)
from rehuco_core.rehudb import CatalogLocation

ANCHOR: Final = Path(Path.cwd().anchor) / "fake"
CACHE_PATH: Final = ANCHOR / "catalog.rehudb"
LIBRARY_ID: Final = UUID("00000000-0000-0000-0000-00000000000a")
PACKS_ID: Final = UUID("00000000-0000-0000-0000-00000000000b")
LIBRARY: Final = RehucoRoot(LIBRARY_ID, ANCHOR / "library", "library")
PACKS: Final = RehucoRoot(PACKS_ID, ANCHOR / "packs", "packs")


@fixture(name="cache")
def fixture_cache(mocker: MockerFixture) -> MagicMock:
    """Make every :meth:`CatalogCache.open <rehuco_core.CatalogCache.open>` hand back one mock cache.

    :param mocker: pytest-mock fixture.
    :returns: the mock, a context manager that hands back itself.
    """
    cache = mocker.MagicMock(spec=CatalogCache)
    cache.__enter__.return_value = cache
    mocker.patch.object(CatalogCache, "open", return_value=cache)
    return cache


def cached_root(root: RehucoRoot, position: int) -> CatalogRoot:
    """A root as the cache reads it back.

    :param root: the ``.rehuco``'s root.
    :param position: its row in the ``.rehuco``.
    :returns: the cache's root.
    """
    return CatalogRoot(root.root_id, root.label, root.path, position, False, None, None)


def cached_row(resource_id: int, root: RehucoRoot, path: str, **fields: Any) -> CatalogRow:
    """A row as the cache reads it back.

    :param resource_id: its id.
    :param root: the root it is under.
    :param path: root-relative.
    :param fields: any other field of its record.
    :returns: the row.
    """
    return CatalogRow(resource_id, root.root_id, root.label, CatalogRecord(path, RecordKind.REHU, **fields), 0.0)


def attached(*roots: RehucoRoot) -> Catalog:
    """A catalog attached to a session over the mock cache, viewing ``roots``.

    :param roots: the ``.rehuco``'s roots.
    :returns: the catalog.
    """
    catalog = Catalog()
    catalog.attach(Catalog.prepare(CACHE_PATH, roots))
    return catalog


def paths_of(catalog: Catalog) -> list[tuple[UUID, str]]:
    """Every row the catalog lists, as ``(root id, relative path)``."""
    return [(row.root_id, row.record.path) for row in catalog.query(CatalogQuery())]


# region Detached


def test_a_detached_catalog_answers_nothing_and_changes_nothing(cache: MagicMock) -> None:
    """With no cache attached every read is empty and every upkeep a no-op -- what the agent shows with no ``.rehuco``
    open -- and the cache is never opened.

    **Test steps:**

    * build a catalog and attach nothing
    * verify every read answers empty, every upkeep answers nothing and attaches nothing, and the cache was not opened
    """
    catalog = Catalog()
    key = ResourceKey(LIBRARY.path / "info.rehu")

    catalog.reconcile([LIBRARY, PACKS])
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
    assert not cache.mock_calls


def test_detaching_lets_the_cache_go(cache: MagicMock) -> None:
    """A detached catalog reads nothing more, and attaching again reads the same cache.

    **Test steps:**

    * attach a session whose cache holds one row, note its cache path, then detach
    * verify nothing is read, then attach a fresh session over the same path and verify the row is back
    """
    cache.rows.return_value = [cached_row(1, LIBRARY, "a/info.rehu")]
    catalog = attached(LIBRARY, PACKS)
    assert catalog.cache_path == CACHE_PATH

    catalog.detach()
    assert not paths_of(catalog)

    catalog.attach(Catalog.prepare(CACHE_PATH, (LIBRARY, PACKS)))
    assert paths_of(catalog) == [(LIBRARY_ID, "a/info.rehu")]


# endregion

# region Reads


def test_the_roots_and_rows_are_those_of_the_view(cache: MagicMock) -> None:
    """The roots and the rows are the cache's, in its order, kept to the roots the view lists.

    **Test steps:**

    * make the cache hold three roots, each with a row, and view two of them
    * verify the view's two roots in order, and their two rows
    """
    other = RehucoRoot(UUID(int=7), ANCHOR / "other", "other")
    cache.roots.return_value = (cached_root(LIBRARY, 0), cached_root(other, 1), cached_root(PACKS, 2))
    cache.rows.return_value = [
        cached_row(1, LIBRARY, "a/info.rehu"),
        cached_row(2, other, "o/info.rehu"),
        cached_row(3, PACKS, "p/info.rehu"),
    ]
    catalog = attached(LIBRARY, PACKS)

    assert [root.root_id for root in catalog.roots()] == [LIBRARY_ID, PACKS_ID]
    assert paths_of(catalog) == [(LIBRARY_ID, "a/info.rehu"), (PACKS_ID, "p/info.rehu")]


def test_a_query_and_an_update_in_place_are_passed_to_the_cache(cache: MagicMock) -> None:
    """The cache does the matching: the catalog hands it the query, and ``ids`` to narrow the read to those rows.

    **Test steps:**

    * make the cache answer a row, and query with a term and with ``ids``
    * verify each query and its ``ids`` reached the cache, and the row came back
    """
    cache.rows.return_value = [cached_row(2, LIBRARY, "b/info.rehu", title="Krita")]
    catalog = attached(LIBRARY, PACKS)
    query = CatalogQuery(terms=("krit",))

    assert [row.record.title for row in catalog.query(query)] == ["Krita"]
    cache.rows.assert_called_with(query, ids=None)
    assert [row.record.title for row in catalog.query(CatalogQuery(), ids={2})] == ["Krita"]
    cache.rows.assert_called_with(CatalogQuery(), ids={2})


def test_a_hidden_root_is_out_of_the_view_until_its_rows_are_removed(cache: MagicMock) -> None:
    """Remove Root drops a root from the view at once, while its rows wait for the removal job.

    **Test steps:**

    * make the cache hold a row under each root, and hide the first root
    * verify its root, its rows and its record's row are gone from the view, the other root's are not, and its count
      is still the cache's
    """
    cache.roots.return_value = (cached_root(LIBRARY, 0), cached_root(PACKS, 1))
    cache.rows.return_value = [cached_row(1, LIBRARY, "a/info.rehu"), cached_row(2, PACKS, "p/info.rehu")]
    cache.locate.return_value = CatalogLocation(cached_root(LIBRARY, 0), "a/info.rehu")
    cache.resource_count.return_value = 1
    catalog = attached(LIBRARY, PACKS)

    catalog.hide(LIBRARY_ID)

    assert [root.root_id for root in catalog.roots()] == [PACKS_ID]
    assert paths_of(catalog) == [(PACKS_ID, "p/info.rehu")]
    assert catalog.row(ResourceKey(LIBRARY.path / "a" / "info.rehu")) is None
    assert catalog.count(LIBRARY_ID) == 1


def test_a_row_is_found_by_its_key(cache: MagicMock) -> None:
    """``row`` locates the key, reads the rows at it by id, and answers the located root's; nothing for a key under no
    root, or one the cache has no row for.

    **Test steps:**

    * make the cache locate a key under the library, and hold its row
    * verify the key answers its row, read by the ids at its path
    * make the cache locate nothing, then find no ids, and verify each answers nothing
    """
    key = ResourceKey(LIBRARY.path / "a" / "info.rehu")
    cache.locate.return_value = CatalogLocation(cached_root(LIBRARY, 0), "a/info.rehu")
    cache.resource_ids.return_value = {1}
    cache.rows.return_value = [cached_row(1, LIBRARY, "a/info.rehu", type="tutorial", uuid="id-a")]
    catalog = attached(LIBRARY, PACKS)

    row = catalog.row(key)

    assert row is not None
    assert (row.root_id, row.record.type, row.record.uuid) == (LIBRARY_ID, "tutorial", "id-a")
    cache.locate.assert_called_with(key.path)
    cache.resource_ids.assert_called_with([key.path])
    cache.rows.assert_called_with(ids={1})

    cache.locate.return_value = None
    assert catalog.row(ResourceKey(ANCHOR / "elsewhere" / "info.rehu")) is None
    cache.locate.return_value = CatalogLocation(cached_root(LIBRARY, 0), "b/info.rehu")
    cache.resource_ids.return_value = set()
    assert catalog.row(ResourceKey(LIBRARY.path / "b" / "info.rehu")) is None


def test_where_roots_nest_a_record_is_the_innermost_roots(cache: MagicMock) -> None:
    """A record under two nested roots has a row under each; its row is the one of the root the cache locates it under
    -- the innermost -- never the outer root's, which the rows' order puts first.

    **Test steps:**

    * make the cache locate the record under the inner root, and hold a row for it under each root, outer first
    * verify the record's row is the inner root's; hiding the outer root changes nothing, hiding the inner one leaves
      no row
    """
    outer = RehucoRoot(LIBRARY_ID, ANCHOR / "library", "library")
    inner = RehucoRoot(PACKS_ID, ANCHOR / "library" / "sub", "sub")
    key = ResourceKey(inner.path / "x.rehu")
    cache.locate.return_value = CatalogLocation(cached_root(inner, 1), "x.rehu")
    cache.resource_ids.return_value = {1, 2}
    cache.rows.return_value = [cached_row(1, outer, "sub/x.rehu", title="outer"), cached_row(2, inner, "x.rehu")]
    catalog = attached(outer, inner)

    row = catalog.row(key)
    assert row is not None
    assert (row.root_id, row.resource_id) == (PACKS_ID, 2)

    catalog.hide(LIBRARY_ID)
    row = catalog.row(key)
    assert row is not None
    assert row.root_id == PACKS_ID

    catalog.hide(PACKS_ID)
    assert catalog.row(key) is None


def test_a_root_counts_its_rows(cache: MagicMock) -> None:
    """``count`` is the cache's count of the root's rows -- what removing it would drop.

    **Test steps:**

    * make the cache count two rows, and count a root
    * verify the count, asked for that root
    """
    cache.resource_count.return_value = 2
    catalog = attached(LIBRARY, PACKS)

    assert catalog.count(LIBRARY_ID) == 2
    cache.resource_count.assert_called_once_with(LIBRARY_ID)


def test_any_thread_may_read(mocker: MockerFixture, cache: MagicMock) -> None:
    """Each call opens the cache on the calling thread, so a worker reads as the attaching thread does.

    **Test steps:**

    * attach on this thread, and query from another, noting the thread each open ran on
    * verify the other thread read the row, and opened the cache itself
    """
    cache.rows.return_value = [cached_row(1, LIBRARY, "a/info.rehu")]
    catalog = attached(LIBRARY, PACKS)
    opened_on: list[threading.Thread] = []

    def open_here(_path: Path) -> MagicMock:
        opened_on.append(threading.current_thread())
        return cache

    mocker.patch.object(CatalogCache, "open", side_effect=open_here)
    answers: list[object] = []
    worker = threading.Thread(target=lambda: answers.append(paths_of(catalog)))

    worker.start()
    worker.join()

    assert answers == [[(LIBRARY_ID, "a/info.rehu")]]
    assert opened_on == [worker]


def test_a_cache_that_cannot_be_read_refuses_the_listings_and_answers_nothing_else(
    cache: MagicMock, caplog: LogCaptureFixture
) -> None:
    """The roots and a query raise :class:`~rehuco_core.CatalogUnreadable`, never ``sqlite3.Error``; a row and a count
    answer nothing, logged.

    **Test steps:**

    * attach, then make every read raise a database error
    * verify the two listings raise, and the row and the count answer nothing with the failures logged
    """
    catalog = attached(LIBRARY, PACKS)
    locked = sqlite3.OperationalError("locked")
    cache.roots.side_effect = locked
    cache.rows.side_effect = locked
    cache.locate.side_effect = locked
    cache.resource_count.side_effect = locked

    with raises(CatalogUnreadable, match="Could not read the roots of .*locked"):
        catalog.roots()
    with raises(CatalogUnreadable, match="Could not read the catalog .*locked"):
        catalog.query(CatalogQuery())
    with caplog.at_level(logging.ERROR):
        assert catalog.row(ResourceKey(LIBRARY.path / "a" / "info.rehu")) is None
        assert catalog.count(LIBRARY_ID) == 0

    assert "Could not read the row of" in caplog.text
    assert f"Could not count the cached entries of the root {LIBRARY_ID}" in caplog.text


# endregion

# region The session


def test_preparing_reconciles_the_roots_and_describes_the_session(cache: MagicMock) -> None:
    """``prepare`` brings the cache's roots in line with the ``.rehuco``'s, closes it, and attaches nothing.

    **Test steps:**

    * prepare a session over two roots
    * verify the cache was opened at its path, reconciled to the roots and closed, and the session names both
    """
    session = Catalog.prepare(CACHE_PATH, (LIBRARY, PACKS))

    CatalogCache.open.assert_called_once_with(CACHE_PATH)  # type: ignore[attr-defined]  # patched by the fixture
    cache.reconcile_roots.assert_called_once_with((LIBRARY, PACKS))
    cache.__exit__.assert_called_once()
    assert (session.cache_path, session.root_ids) == (CACHE_PATH, frozenset({LIBRARY_ID, PACKS_ID}))


def test_preparing_a_cache_that_cannot_be_opened_or_reconciled_says_which(
    mocker: MockerFixture, cache: MagicMock
) -> None:
    """``prepare`` refuses with what failed, so the agent's message can say it; a cache that fails is left closed.

    **Test steps:**

    * make the open fail, and prepare; then make the reconcile fail, and prepare again
    * verify each refusal names its step and the reason, and the second closed the cache
    """
    opening = mocker.patch.object(CatalogCache, "open", side_effect=sqlite3.OperationalError("locked"))
    with raises(CatalogUnreadable, match="Could not open the cache of .*locked"):
        Catalog.prepare(CACHE_PATH, (LIBRARY, PACKS))
    mocker.stop(opening)

    cache.reconcile_roots.side_effect = sqlite3.OperationalError("busy")
    with raises(CatalogUnreadable, match="Could not read the cache of .*busy"):
        Catalog.prepare(CACHE_PATH, (LIBRARY, PACKS))
    cache.__exit__.assert_called_once()


def test_reconciling_follows_an_edit_of_the_roots(cache: MagicMock) -> None:
    """After an edit of the ``.rehuco``'s roots the cache is reconciled to them and the view follows: a dropped root's
    rows are no longer listed, a new root is.

    **Test steps:**

    * attach over both roots, then reconcile to the second root and a new one
    * verify the cache was reconciled to those two, and only their roots and rows are listed
    """
    added = RehucoRoot(UUID(int=7), ANCHOR / "added", "added")
    cache.roots.return_value = (cached_root(LIBRARY, 0), cached_root(PACKS, 1), cached_root(added, 2))
    cache.rows.return_value = [cached_row(1, LIBRARY, "a/info.rehu"), cached_row(2, PACKS, "p/info.rehu")]
    catalog = attached(LIBRARY, PACKS)

    catalog.reconcile([PACKS, added])

    cache.reconcile_roots.assert_called_with([PACKS, added])
    assert [root.root_id for root in catalog.roots()] == [PACKS_ID, added.root_id]
    assert paths_of(catalog) == [(PACKS_ID, "p/info.rehu")]


def test_a_reconcile_that_fails_is_logged_and_the_view_still_follows_the_file(
    cache: MagicMock, caplog: LogCaptureFixture
) -> None:
    """The next scan rebuilds the cache, so a failed reconcile is logged rather than raised; what the view lists still
    follows the ``.rehuco``.

    **Test steps:**

    * attach over both roots, each with a row, then make the reconcile fail and reconcile to the second root alone
    * verify the failure is logged with its cause, and only the second root's row is listed
    """
    cache.rows.return_value = [cached_row(1, LIBRARY, "a/info.rehu"), cached_row(2, PACKS, "p/info.rehu")]
    catalog = attached(LIBRARY, PACKS)
    cache.reconcile_roots.side_effect = sqlite3.OperationalError("locked")

    with caplog.at_level(logging.ERROR):
        catalog.reconcile([PACKS])

    assert "Could not update the cache" in caplog.text and "locked" in caplog.text
    assert paths_of(catalog) == [(PACKS_ID, "p/info.rehu")]


# endregion

# region Keeping the cache current


def test_a_rename_rebases_its_rows_and_says_which(cache: MagicMock) -> None:
    """``follow`` asks the ids at both ends of the rename, has the cache rebase them, and answers those ids -- none when
    the cache moved nothing.

    **Test steps:**

    * make the cache find a row at the rename and move it, and follow a folder's rename
    * verify the ids were asked for both ends, the pairs rebased, and the row's id answered
    * make the cache move nothing, and verify the rename answers nothing
    """
    source, destination = LIBRARY.path / "a", LIBRARY.path / "b"
    cache.resource_ids.return_value = {1}
    cache.apply_relocation.return_value = 1
    catalog = attached(LIBRARY, PACKS)
    rename = KeyRelocation(((ResourceKey(source), ResourceKey(destination)),))

    assert catalog.follow(rename) == {1}
    cache.resource_ids.assert_called_once_with([source, destination])
    cache.apply_relocation.assert_called_once_with(rename.to_local().pairs)

    cache.apply_relocation.return_value = 0
    assert catalog.follow(rename) == set()


def test_the_records_at_or_beneath_a_key_are_read_from_the_cache(cache: MagicMock) -> None:
    """``record_paths`` answers what the cache holds at or beneath the keys' paths (#511); no keys asks nothing.

    **Test steps:**

    * make the cache answer two records, and ask for a folder's and a record's
    * verify the cache was asked for both paths and its answer came back; no keys at all answer nothing
    """
    folder, single = ResourceKey(LIBRARY.path / "a"), ResourceKey(PACKS.path / "p.rehu")
    found = [LIBRARY.path / "a" / "one.rehu", single.path]
    cache.record_paths.return_value = found
    catalog = attached(LIBRARY, PACKS)

    assert catalog.record_paths([folder, single]) == found
    cache.record_paths.assert_called_once_with([folder.path, single.path])
    assert not catalog.record_paths([])
    cache.record_paths.assert_called_once()


def test_a_roots_reachability_is_recorded_for_a_root_of_the_view_only(cache: MagicMock) -> None:
    """``mark_reachable`` writes what the root's file notifier saw into the cache; a root the view dropped is left
    alone (#511).

    **Test steps:**

    * mark the library unreachable, then reachable again
    * verify each mark reached the cache
    * hide the packs root, mark it unreachable, and verify the cache was not asked
    """
    catalog = attached(LIBRARY, PACKS)

    catalog.mark_reachable(LIBRARY_ID, False)
    catalog.mark_reachable(LIBRARY_ID, True)
    catalog.hide(PACKS_ID)
    catalog.mark_reachable(PACKS_ID, False)

    assert cache.mark_root_reachable.call_args_list == [((LIBRARY_ID, False),), ((LIBRARY_ID, True),)]


def test_verify_on_access_plans_from_the_cache_and_applies_what_the_disk_showed(
    mocker: MockerFixture, cache: MagicMock
) -> None:
    """The cache halves of verify-on-access go through the updater over the cache: a plan of the keys' paths, and the
    findings applied, answered with the rows touched before and after and the paths that changed.

    **Test steps:**

    * mock the updater, the cache's ids before and after the apply different
    * plan a verify of a key and apply a finding
    * verify the updater was built over the cache with the coordinator, the plan and the apply were its, and the
      answer joins both reads of ids
    """
    updater_class = mocker.patch("rehuco_core.access.catalog.CatalogRecordUpdater")
    updater = updater_class.return_value
    updater.apply.return_value = {LIBRARY.path / "a" / "info.rehu"}
    cache.resource_ids.side_effect = [{1}, {1, 2}]
    key = ResourceKey(LIBRARY.path / "a" / "info.rehu")
    finding = MagicMock()
    finding.check.path = key.path
    catalog = attached(LIBRARY, PACKS)

    checks = catalog.plan_verify([key])
    affected, changed = catalog.apply_verify([finding])

    assert checks is updater.plan.return_value
    updater.plan.assert_called_once_with([key.path])
    updater_class.assert_called_with(cache, coordinator=DEFAULT_RENAME_COORDINATOR)
    updater.apply.assert_called_once_with([finding])
    assert affected == {1, 2}
    assert changed == {key.path}


def test_upkeep_that_cannot_reach_the_cache_is_logged_and_answers_nothing(
    mocker: MockerFixture, cache: MagicMock, caplog: LogCaptureFixture
) -> None:
    """The next scan rebuilds what upkeep missed, so each failure is logged and answers as if nothing changed.

    **Test steps:**

    * attach, then make the cache's ids, record paths and reachability writes and the updater's plan raise a database
      error
    * verify a rename, a record lookup, a reachability mark, a plan and an apply each answer nothing, and each
      failure is logged
    """
    catalog = attached(LIBRARY, PACKS)
    key = ResourceKey(LIBRARY.path / "b" / "info.rehu")
    finding = MagicMock()
    finding.check.path = key.path
    locked = sqlite3.OperationalError("locked")
    cache.resource_ids.side_effect = locked
    cache.record_paths.side_effect = locked
    cache.mark_root_reachable.side_effect = locked
    mocker.patch("rehuco_core.access.catalog.CatalogRecordUpdater.plan", side_effect=locked)

    with caplog.at_level(logging.ERROR):
        assert (
            catalog.follow(KeyRelocation(((ResourceKey(LIBRARY.path / "a"), ResourceKey(LIBRARY.path / "c")),)))
            == set()
        )
        assert not catalog.record_paths([key])
        catalog.mark_reachable(LIBRARY_ID, False)
        assert not catalog.plan_verify([key])
        assert catalog.apply_verify([finding]) == (set(), set())

    assert "Could not follow a rename in the cache" in caplog.text
    assert "Could not update the cache" in caplog.text
    assert f"Could not read the cache {catalog.cache_path}: locked" in caplog.text
    assert "Could not read the cache" in caplog.text and "to verify records" in caplog.text


# endregion
