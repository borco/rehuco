"""Tests for the ``.rehudb`` catalog cache -- schema, versioning, roots, rows and queries (#372).

No file is ever created: :func:`sqlite3.connect` is patched to hand back shared-cache in-memory databases, one
per name, and a second *keeper* connection to the same name is what a test inspects the database through --
including after the cache under test has closed its own.
"""

import logging
import sqlite3
from pathlib import Path
from typing import Any, Final
from uuid import uuid4

from pytest import LogCaptureFixture, fixture, raises
from pytest_mock import MockerFixture
from rehuco_core import (
    REHUDB_SUFFIX,
    CatalogCache,
    CatalogField,
    CatalogQuery,
    CatalogRecord,
    RecordKind,
    RehucoFile,
    RehucoRoot,
    rehudb_path,
)
from rehuco_core.migrations.rehudb import CURRENT_VERSION
from rehuco_core.rehudb import BUSY_TIMEOUT_MS

CACHE_PATH: Final = Path("/fake/cache/rehuco.rehudb")

real_connect: Final = sqlite3.connect
"""The real :func:`sqlite3.connect`, bound before any test patches the module's -- the module is shared, so
patching it for the cache patches it here too."""

INCREMENTAL: Final = 2
"""``PRAGMA auto_vacuum``'s answer for ``INCREMENTAL``."""


class MemoryDatabase:
    """One named in-memory database, alive for as long as its keeper connection is open."""

    def __init__(self) -> None:
        self.__uri: Final = f"file:rehudb-{uuid4()}?mode=memory&cache=shared"
        self.keeper: Final = self.connect()

    def connect(self, *_args: object, **_kwargs: object) -> sqlite3.Connection:
        """A new connection to this database, as the patched :func:`sqlite3.connect` hands it out."""
        return real_connect(self.__uri, uri=True, autocommit=True, check_same_thread=False)

    def scalar(self, statement: str) -> object:
        """The first column of the first row ``statement`` reads, through the keeper."""
        return self.keeper.execute(statement).fetchone()[0]

    def tables(self) -> set[str]:
        """Every table the database holds."""
        return {name for (name,) in self.keeper.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


@fixture(name="database")
def fixture_database(mocker: MockerFixture) -> MemoryDatabase:
    """Route every connection the cache opens to one fresh in-memory database, and fake the folder.

    :param mocker: pytest-mock fixture.
    :returns: the database.
    """
    database = MemoryDatabase()
    mocker.patch("rehuco_core.rehudb.sqlite3.connect", side_effect=database.connect)
    mocker.patch.object(Path, "mkdir", autospec=True)
    return database


@fixture(name="cache")
def fixture_cache(database: MemoryDatabase) -> CatalogCache:
    """A freshly created cache over :func:`fixture_database`.

    :param database: the database it is created in.
    :returns: the open cache.
    """
    del database
    return CatalogCache.open(CACHE_PATH)


def two_roots() -> tuple[RehucoFile, RehucoRoot, RehucoRoot]:
    """A ``.rehuco`` with two roots, ``tutorials`` and ``packs``."""
    rehuco = RehucoFile.new()
    rehuco.add_root("D:/tutorials")
    rehuco.add_root("E:/packs")
    first, second = rehuco.roots
    return rehuco, first, second


def record(path: str, **fields: Any) -> CatalogRecord:
    """A ``.rehu`` record at ``path`` with the given fields and a content hash."""
    return CatalogRecord(path, RecordKind.REHU, content_hash="0", **fields)


# region Creating and versioning


def test_a_fresh_cache_is_incremental_and_stamped_with_the_current_version(
    database: MemoryDatabase, cache: CatalogCache
) -> None:
    """``auto_vacuum`` is chosen before the first table, and the stamp is the chain's head."""
    assert database.scalar("PRAGMA auto_vacuum") == INCREMENTAL
    assert database.scalar("PRAGMA user_version") == CURRENT_VERSION
    assert cache.schema_version == CURRENT_VERSION
    assert {"roots", "resources", "authors", "tags", "publishers"} <= database.tables()


def test_every_connection_enforces_foreign_keys(cache: CatalogCache) -> None:
    """The cascade a root removal relies on is otherwise silently ignored."""
    assert cache.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_the_cache_folder_is_created(mocker: MockerFixture) -> None:
    """A first run has no cache folder yet."""
    database = MemoryDatabase()
    mocker.patch("rehuco_core.rehudb.sqlite3.connect", side_effect=database.connect)
    mkdir = mocker.patch.object(Path, "mkdir", autospec=True)

    CatalogCache.open(CACHE_PATH).close()

    mkdir.assert_called_once_with(CACHE_PATH.parent, parents=True, exist_ok=True)


def test_the_cache_is_named_by_the_rehuco_id() -> None:
    """Moving or renaming the ``.rehuco`` keeps its cache, because its path names nothing."""
    rehuco = RehucoFile.new()

    assert rehudb_path(Path("/cache"), rehuco.rehuco_id) == Path("/cache") / f"{rehuco.rehuco_id}{REHUDB_SUFFIX}"


def test_each_step_runs_once_in_order(database: MemoryDatabase) -> None:
    """A version-1 file meets a two-step chain: only the second step runs, and the stamp follows it."""
    database.keeper.execute("PRAGMA user_version = 1")
    ran: list[int] = []
    chain = (
        (1, lambda connection: ran.append(1)),
        (2, lambda connection: (ran.append(2), connection.execute("CREATE TABLE two (x)"))),
    )

    CatalogCache.open(CACHE_PATH, chain=chain).close()  # type: ignore[arg-type]

    assert ran == [2]
    assert database.scalar("PRAGMA user_version") == 2
    assert "two" in database.tables()


def test_a_failing_step_leaves_the_version_it_started_from(database: MemoryDatabase) -> None:
    """Each step is its own transaction, its stamp inside it."""

    def failing(connection: sqlite3.Connection) -> None:
        connection.execute("CREATE TABLE half (x)")
        raise sqlite3.OperationalError("step two broke")

    chain = ((1, lambda connection: connection.execute("CREATE TABLE one (x)")), (2, failing))

    with raises(sqlite3.OperationalError, match="step two broke"):
        CatalogCache.open(CACHE_PATH, chain=chain)  # type: ignore[arg-type]

    assert database.scalar("PRAGMA user_version") == 1
    assert "one" in database.tables()
    assert "half" not in database.tables()


def test_a_newer_cache_is_discarded_and_rebuilt_never_written(mocker: MockerFixture, caplog: LogCaptureFixture) -> None:
    """There is no downgrade: a cache from a newer build is thrown away, the reason logged."""
    newer, rebuilt = MemoryDatabase(), MemoryDatabase()
    newer.keeper.execute("PRAGMA user_version = 99")
    newer.keeper.execute("CREATE TABLE future (x)")
    mocker.patch("rehuco_core.rehudb.sqlite3.connect", side_effect=[newer.connect(), rebuilt.connect()])
    mocker.patch.object(Path, "mkdir", autospec=True)
    unlink = mocker.patch.object(Path, "unlink", autospec=True)

    with caplog.at_level(logging.WARNING, logger="rehuco_core.rehudb"):
        cache = CatalogCache.open(CACHE_PATH)

    assert "newer than this build" in caplog.text
    unlinked = {call.args[0] for call in unlink.call_args_list}
    assert unlinked == {CACHE_PATH, Path(f"{CACHE_PATH}-wal"), Path(f"{CACHE_PATH}-shm")}
    assert cache.schema_version == CURRENT_VERSION
    assert newer.scalar("PRAGMA user_version") == 99
    assert newer.tables() == {"future"}


def test_a_file_that_is_not_a_database_is_rebuilt(mocker: MockerFixture, caplog: LogCaptureFixture) -> None:
    """A disposable cache that will not open is replaced rather than reported."""
    broken = mocker.Mock(spec=sqlite3.Connection)
    broken.execute.side_effect = sqlite3.DatabaseError("file is not a database")
    rebuilt = MemoryDatabase()
    mocker.patch("rehuco_core.rehudb.sqlite3.connect", side_effect=[broken, rebuilt.connect()])
    mocker.patch.object(Path, "mkdir", autospec=True)
    mocker.patch.object(Path, "unlink", autospec=True)

    with caplog.at_level(logging.WARNING, logger="rehuco_core.rehudb"):
        cache = CatalogCache.open(CACHE_PATH)

    assert "not a database" in caplog.text
    broken.close.assert_called_once_with()
    assert cache.schema_version == CURRENT_VERSION


def test_a_locked_cache_is_refused_not_deleted(mocker: MockerFixture) -> None:
    """A lock is not corruption: the file may be perfectly good, and deleting it would destroy a valid cache."""
    locked = mocker.Mock(spec=sqlite3.Connection)
    locked.execute.side_effect = sqlite3.OperationalError("database is locked")
    mocker.patch("rehuco_core.rehudb.sqlite3.connect", return_value=locked)
    mocker.patch.object(Path, "mkdir", autospec=True)
    unlink = mocker.patch.object(Path, "unlink", autospec=True)

    with raises(sqlite3.OperationalError, match="locked"):
        CatalogCache.open(CACHE_PATH)

    unlink.assert_not_called()
    locked.close.assert_called_once_with()


def test_a_connection_waits_for_a_busy_cache_from_its_first_statement(mocker: MockerFixture) -> None:
    """The busy wait is set on the connection, not by a later pragma, so the version read on open has it."""
    database = MemoryDatabase()
    connect = mocker.patch("rehuco_core.rehudb.sqlite3.connect", side_effect=database.connect)
    mocker.patch.object(Path, "mkdir", autospec=True)

    CatalogCache.open(CACHE_PATH).close()

    assert connect.call_args.kwargs["timeout"] == BUSY_TIMEOUT_MS / 1000


def test_the_cache_closes_on_leaving_a_with_block(cache: CatalogCache) -> None:
    """The connection is unusable once the block ends."""
    with cache:
        pass

    with raises(sqlite3.ProgrammingError):
        cache.connection.execute("SELECT 1")


# endregion

# region Roots


def test_reconciling_inserts_roots_in_the_rehuco_order(cache: CatalogCache) -> None:
    """A new id gets a row with nothing scanned under it."""
    rehuco, first, second = two_roots()

    cache.reconcile_roots(rehuco.roots)

    roots = cache.roots()
    assert [root.root_id for root in roots] == [first.root_id, second.root_id]
    assert [root.label for root in roots] == ["tutorials", "packs"]
    assert roots[0].reachable is None
    assert roots[0].scanned_at is None


def test_a_relabeled_repointed_and_reordered_root_keeps_its_rows(cache: CatalogCache) -> None:
    """Rows are keyed by root id, never by path or label."""
    rehuco, first, _ = two_roots()
    cache.reconcile_roots(rehuco.roots)
    cache.apply_root_scan(first.root_id, [record("a/info.rehu")])

    rehuco.relabel_root(0, "courses")
    rehuco.move_to_bottom(0)
    other, relabeled = rehuco.roots
    cache.reconcile_roots([other, RehucoRoot(relabeled.root_id, Path("F:/elsewhere"), relabeled.label, True)])

    rows = cache.rows()
    assert [row.root_label for row in rows] == ["courses"]
    root = next(root for root in cache.roots() if root.root_id == first.root_id)
    assert (root.label, root.path, root.position, root.removable) == ("courses", Path("F:/elsewhere"), 1, True)


def test_a_root_the_rehuco_no_longer_has_cascades_away(database: MemoryDatabase, cache: CatalogCache) -> None:
    """A missing id loses its row, its resources and their join rows; values nobody names go too."""
    rehuco, first, second = two_roots()
    cache.reconcile_roots(rehuco.roots)
    cache.apply_root_scan(first.root_id, [record("a/info.rehu", authors=("Ann",), tags=("x",))])

    cache.reconcile_roots([second])

    assert not cache.rows()
    assert [root.root_id for root in cache.roots()] == [second.root_id]
    assert database.scalar("SELECT count(*) FROM resource_authors") == 0
    assert database.scalar("SELECT count(*) FROM authors") == 0


def test_removing_a_root_cascades_and_returns_its_space(database: MemoryDatabase, cache: CatalogCache) -> None:
    """The pages the cascade empties are handed back by ``incremental_vacuum``, not left on the freelist."""
    rehuco, first, second = two_roots()
    cache.reconcile_roots(rehuco.roots)
    cache.apply_root_scan(first.root_id, [record(f"r{index}/info.rehu", title="x" * 500) for index in range(400)])
    cache.apply_root_scan(second.root_id, [record("kept/info.rehu", publishers=("Pub",))])

    cache.remove_root(first.root_id)

    assert [row.record.path for row in cache.rows()] == ["kept/info.rehu"]
    assert database.scalar("PRAGMA freelist_count") == 0
    assert database.scalar("SELECT count(*) FROM publishers") == 1


def test_an_unreachable_root_keeps_its_rows(cache: CatalogCache) -> None:
    """Offline is recorded on the root, and nothing under it changes."""
    rehuco, first, _ = two_roots()
    cache.reconcile_roots(rehuco.roots)
    cache.apply_root_scan(first.root_id, [record("a/info.rehu")], scanned_at=1000.0)

    cache.mark_root_unreachable(first.root_id)

    root = cache.roots()[0]
    assert root.reachable is False
    assert root.scanned_at == 1000.0
    assert [row.record.path for row in cache.rows()] == ["a/info.rehu"]


# endregion

# region Applying a scan


def test_a_scan_replaces_the_roots_rows_and_keeps_the_ids_of_records_found_again(cache: CatalogCache) -> None:
    """A record found again keeps its row; one not found is gone; a new one is added."""
    rehuco, first, _ = two_roots()
    cache.reconcile_roots(rehuco.roots)
    cache.apply_root_scan(first.root_id, [record("a/info.rehu", title="Old"), record("b/info.rehu")])
    kept = {row.record.path: row.resource_id for row in cache.rows()}["a/info.rehu"]

    applied = cache.apply_root_scan(first.root_id, [record("a/info.rehu", title="New"), record("c/info.rehu")])

    assert applied
    rows = {row.record.path: row for row in cache.rows()}
    assert set(rows) == {"a/info.rehu", "c/info.rehu"}
    assert rows["a/info.rehu"].resource_id == kept
    assert rows["a/info.rehu"].record.title == "New"
    assert cache.roots()[0].reachable is True


def test_a_scan_leaves_the_other_roots_rows_alone(cache: CatalogCache) -> None:
    """A root's scan says nothing about any other root."""
    rehuco, first, second = two_roots()
    cache.reconcile_roots(rehuco.roots)
    cache.apply_root_scan(second.root_id, [record("p/info.rehu")])

    cache.apply_root_scan(first.root_id, [])

    assert [(row.root_id, row.record.path) for row in cache.rows()] == [(second.root_id, "p/info.rehu")]


def test_a_scan_of_a_root_removed_meanwhile_is_dropped(cache: CatalogCache) -> None:
    """Nothing to apply to, so nothing is applied."""
    assert not cache.apply_root_scan(uuid4(), [record("a/info.rehu")])
    assert not cache.rows()


def test_every_field_of_a_record_round_trips(cache: CatalogCache) -> None:
    """What a scan read is what the browser reads back, values in their own order."""
    rehuco, first, _ = two_roots()
    cache.reconcile_roots(rehuco.roots)
    written = CatalogRecord(
        "Sub/Foo.tc",
        RecordKind.TC,
        uuid="u",
        type="tutorial",
        title="T",
        publisher="P",
        url="https://example.com",
        released="2024-03",
        current_size=123,
        updated="2026-01-01",
        authors=("Zed", "Ann"),
        tags=("b", "a"),
        publishers=("P", "Q"),
        mtime_ns=42,
        size=7,
        content_hash="abc",
        error="broken",
    )

    cache.apply_root_scan(first.root_id, [written], scanned_at=5.0)

    (row,) = cache.rows()
    assert row.record == written
    assert (row.root_id, row.root_label, row.scanned_at) == (first.root_id, "tutorials", 5.0)


# endregion

# region Querying


@fixture(name="library")
def fixture_library(cache: CatalogCache) -> CatalogCache:
    """A cache holding a few resources across two roots.

    :param cache: the cache to fill.
    :returns: it, filled.
    """
    rehuco, first, second = two_roots()
    cache.reconcile_roots(rehuco.roots)
    cache.apply_root_scan(
        first.root_id,
        [
            record("blender/donut/info.rehu", title="Donut 100%", type="tutorial", authors=("Ann",), tags=("3d",)),
            record("blender/rig/info.rehu", title="Rigging", type="tutorial", authors=("Bob",), tags=("3d", "rig")),
            record("zbrush/info.rehu", title="Sculpt_1", type="tutorial", authors=("Ann",), publishers=("Pub",)),
        ],
    )
    cache.apply_root_scan(second.root_id, [record("faces.rehu", title="Faces", type="reference_images")])
    return cache


def titles(cache: CatalogCache, query: CatalogQuery) -> list[str]:
    """The titles of the rows ``query`` reads, in their order."""
    return [row.record.title for row in cache.rows(query)]


def test_every_row_comes_back_in_root_order(library: CatalogCache) -> None:
    """No query reads everything, the ``.rehuco``'s first root first."""
    assert titles(library, CatalogQuery()) == ["Donut 100%", "Rigging", "Sculpt_1", "Faces"]


def test_free_text_matches_title_or_path_case_insensitively(library: CatalogCache) -> None:
    """Free text is a substring of either."""
    assert titles(library, CatalogQuery("RIG")) == ["Rigging"]
    assert titles(library, CatalogQuery("zbrush")) == ["Sculpt_1"]


def test_free_text_takes_like_wildcards_literally(library: CatalogCache) -> None:
    """``%`` and ``_`` are characters a title can hold, not patterns a reader meant."""
    assert titles(library, CatalogQuery("0%")) == ["Donut 100%"]
    assert titles(library, CatalogQuery("t_1")) == ["Sculpt_1"]
    assert not titles(library, CatalogQuery("_ig"))


def test_a_value_token_matches_one_value_whole_and_case_insensitively(library: CatalogCache) -> None:
    """``authors``, ``tags`` and ``publishers`` each look through their join."""
    assert titles(library, CatalogQuery(tokens=((CatalogField.AUTHORS, "ann"),))) == ["Donut 100%", "Sculpt_1"]
    assert titles(library, CatalogQuery(tokens=((CatalogField.TAGS, "rig"),))) == ["Rigging"]
    assert titles(library, CatalogQuery(tokens=((CatalogField.PUBLISHERS, "PUB"),))) == ["Sculpt_1"]
    assert not titles(library, CatalogQuery(tokens=((CatalogField.AUTHORS, "An"),)))


def test_a_type_token_matches_the_type(library: CatalogCache) -> None:
    """The type is a column of its own."""
    assert titles(library, CatalogQuery(tokens=((CatalogField.TYPE, "reference_images"),))) == ["Faces"]


def test_a_folder_token_is_a_label_and_path_prefix(library: CatalogCache) -> None:
    """``folder`` addresses ``<label>/<relative path>``, a whole folder at a time."""
    blender = CatalogQuery(tokens=((CatalogField.FOLDER, "tutorials/blender/"),))
    assert titles(library, blender) == ["Donut 100%", "Rigging"]
    assert titles(library, CatalogQuery(tokens=((CatalogField.FOLDER, "packs"),))) == ["Faces"]
    assert not titles(library, CatalogQuery(tokens=((CatalogField.FOLDER, "tutorials/blend"),)))


def test_tokens_and_text_must_all_match(library: CatalogCache) -> None:
    """Every condition narrows."""
    query = CatalogQuery("o", ((CatalogField.AUTHORS, "Ann"), (CatalogField.TAGS, "3d")))

    assert titles(library, query) == ["Donut 100%"]


def test_a_matching_row_still_carries_all_its_values(library: CatalogCache) -> None:
    """Narrowing by one tag does not narrow the tags a row reads back."""
    (row,) = library.rows(CatalogQuery(tokens=((CatalogField.TAGS, "rig"),)))

    assert row.record.tags == ("3d", "rig")


# endregion
