"""Tests for the ``.rehudb`` catalog cache -- schema, versioning, roots, rows and queries (#372).

No file is ever created: :func:`sqlite3.connect` is patched to hand back shared-cache in-memory databases, one
per name, and a second *keeper* connection to the same name is what a test inspects the database through --
including after the cache under test has closed its own.
"""

# pylint: disable=too-many-lines  # one cohesive module per subject, see [[appendices.code-conventions]]

import logging
import re
import sqlite3
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any, Final
from uuid import uuid4

from pytest import LogCaptureFixture, fixture, mark, raises
from pytest_mock import MockerFixture
from rehuco_core import (
    BUILTIN_PLUGINS,
    REHUDB_SUFFIX,
    TYPE_FIELD_COLUMNS,
    CatalogCache,
    CatalogField,
    CatalogQuery,
    CatalogRecord,
    RecordKind,
    RecordSignature,
    RehucoFile,
    RehucoRoot,
    RootStorage,
    catalog_path_key,
    catalog_type_fields,
    rehudb_path,
)
from rehuco_core.migrations.rehudb import CHAIN, CURRENT_VERSION
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


@fixture(name="memory")
def fixture_memory() -> Generator[Callable[[], MemoryDatabase]]:
    """Make in-memory databases, and close every keeper when the test ends.

    A keeper left open is a connection the garbage collector closes later, under whichever test happens to
    be running -- a ``ResourceWarning`` blamed on a test that never touched SQLite.

    :yields: the factory.
    """
    made: list[MemoryDatabase] = []

    def make() -> MemoryDatabase:
        database = MemoryDatabase()
        made.append(database)
        return database

    yield make
    for database in made:
        database.keeper.close()


@fixture(name="database")
def fixture_database(mocker: MockerFixture, memory: Callable[[], MemoryDatabase]) -> MemoryDatabase:
    """Route every connection the cache opens to one fresh in-memory database, and fake the folder.

    :param mocker: pytest-mock fixture.
    :param memory: where the database comes from.
    :returns: the database.
    """
    database = memory()
    mocker.patch("rehuco_core.rehudb.sqlite3.connect", side_effect=database.connect)
    mocker.patch.object(Path, "mkdir", autospec=True)
    return database


@fixture(name="cache")
def fixture_cache(database: MemoryDatabase) -> Generator[CatalogCache]:
    """A freshly created cache over :func:`fixture_database`, closed when the test ends.

    :param database: the database it is created in.
    :yields: the open cache.
    """
    del database
    with CatalogCache.open(CACHE_PATH) as cache:
        yield cache


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


def ids(cache: CatalogCache) -> dict[str, int]:
    """Every row's id, by its root-relative path."""
    return {row.record.path: row.resource_id for row in cache.rows()}


# region Creating and versioning


def test_a_fresh_cache_is_incremental_and_stamped_with_the_current_version(
    database: MemoryDatabase, cache: CatalogCache
) -> None:
    """``auto_vacuum`` is chosen before the first table, and the stamp is the chain's head."""
    assert database.scalar("PRAGMA auto_vacuum") == INCREMENTAL
    assert database.scalar("PRAGMA user_version") == CURRENT_VERSION
    assert cache.schema_version == CURRENT_VERSION
    assert cache.path == CACHE_PATH
    assert {"roots", "resources", "authors", "tags", "publishers"} <= database.tables()


def test_every_connection_enforces_foreign_keys(cache: CatalogCache) -> None:
    """The cascade a root removal relies on is otherwise silently ignored."""
    assert cache.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_the_cache_folder_is_created(mocker: MockerFixture, memory: Callable[[], MemoryDatabase]) -> None:
    """A first run has no cache folder yet."""
    database = memory()
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


def test_a_newer_cache_is_discarded_and_rebuilt_never_written(
    mocker: MockerFixture, caplog: LogCaptureFixture, memory: Callable[[], MemoryDatabase]
) -> None:
    """There is no downgrade: a cache from a newer build is thrown away, the reason logged."""
    newer, rebuilt = memory(), memory()
    newer.keeper.execute("PRAGMA user_version = 99")
    newer.keeper.execute("CREATE TABLE future (x)")
    mocker.patch("rehuco_core.rehudb.sqlite3.connect", side_effect=[newer.connect(), rebuilt.connect()])
    mocker.patch.object(Path, "mkdir", autospec=True)
    unlink = mocker.patch.object(Path, "unlink", autospec=True)

    with caplog.at_level(logging.WARNING, logger="rehuco_core.rehudb"), CatalogCache.open(CACHE_PATH) as cache:
        assert cache.schema_version == CURRENT_VERSION

    assert "newer than this build" in caplog.text
    unlinked = {call.args[0] for call in unlink.call_args_list}
    assert unlinked == {CACHE_PATH, Path(f"{CACHE_PATH}-wal"), Path(f"{CACHE_PATH}-shm")}
    assert newer.scalar("PRAGMA user_version") == 99
    assert newer.tables() == {"future"}


def test_a_file_that_is_not_a_database_is_rebuilt(
    mocker: MockerFixture, caplog: LogCaptureFixture, memory: Callable[[], MemoryDatabase]
) -> None:
    """A disposable cache that will not open is replaced rather than reported."""
    broken = mocker.Mock(spec=sqlite3.Connection)
    broken.execute.side_effect = sqlite3.DatabaseError("file is not a database")
    rebuilt = memory()
    mocker.patch("rehuco_core.rehudb.sqlite3.connect", side_effect=[broken, rebuilt.connect()])
    mocker.patch.object(Path, "mkdir", autospec=True)
    mocker.patch.object(Path, "unlink", autospec=True)

    with caplog.at_level(logging.WARNING, logger="rehuco_core.rehudb"), CatalogCache.open(CACHE_PATH) as cache:
        assert cache.schema_version == CURRENT_VERSION

    assert "not a database" in caplog.text
    broken.close.assert_called_once_with()


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


def test_a_connection_waits_for_a_busy_cache_from_its_first_statement(
    mocker: MockerFixture, memory: Callable[[], MemoryDatabase]
) -> None:
    """The busy wait is set on the connection, not by a later pragma, so the version read on open has it."""
    database = memory()
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
    moved = RehucoRoot(relabeled.root_id, Path("F:/elsewhere"), relabeled.label, RootStorage.REMOVABLE)
    cache.reconcile_roots([other, moved])

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


def test_an_unchanged_record_keeps_its_row_as_it_was_read(cache: CatalogCache) -> None:
    """An incremental scan's unchanged record is kept whole -- id, fields and read time -- while what it did not
    find is swept; an unchanged path with no row (gone from the cache meanwhile) adds none."""
    rehuco, first, _ = two_roots()
    cache.reconcile_roots(rehuco.roots)
    cache.apply_root_scan(first.root_id, [record("a/info.rehu", title="A"), record("b/info.rehu")], scanned_at=1.0)
    before = ids(cache)

    assert cache.apply_root_scan(first.root_id, [], unchanged=("a/info.rehu", "never/cached.rehu"), scanned_at=2.0)

    (row,) = cache.rows()
    assert (row.resource_id, row.record.title, row.scanned_at) == (before["a/info.rehu"], "A", 1.0)


def test_an_unchanged_record_takes_its_new_spelling(cache: CatalogCache, mocker: MockerFixture) -> None:
    """A case-only rename on a case-insensitive filesystem changes no stat signature, only how the path is spelled."""
    mocker.patch("rehuco_core.rehudb.catalog_path_key", side_effect=str.casefold)
    rehuco, first, _ = two_roots()
    cache.reconcile_roots(rehuco.roots)
    cache.apply_root_scan(first.root_id, [record("course/info.rehu")])
    before = ids(cache)

    cache.apply_root_scan(first.root_id, [], unchanged=("Course/info.rehu",))

    assert ids(cache) == {"Course/info.rehu": before["course/info.rehu"]}


def test_a_converted_record_takes_over_its_legacy_row(cache: CatalogCache) -> None:
    """A ``.rehu`` arriving where a same-stem ``.tc`` had a row -- compared case-folded, in the same directory --
    keeps that row's id; a ``.tc`` in a subdirectory, or of another stem, is a resource of its own.

    **Test steps:**

    * apply a scan holding ``course/Info.TC`` and three ``.tc`` rows it does not cover
    * rescan with ``course/info.rehu`` in the first one's place
    * verify the ``.rehu`` has the first ``.tc``'s id and the other three are untouched
    """
    rehuco, first, _ = two_roots()
    cache.reconcile_roots(rehuco.roots)
    names = ("course/Info.TC", "course/alpha.tc", "course/other.tc", "course/sub/info.tc")
    legacy = [CatalogRecord(path, RecordKind.TC) for path in names]
    cache.apply_root_scan(first.root_id, legacy)
    before = ids(cache)

    cache.apply_root_scan(first.root_id, [record("course/info.rehu"), *legacy[1:]])

    assert ids(cache) == {
        "course/info.rehu": before["course/Info.TC"],
        "course/alpha.tc": before["course/alpha.tc"],
        "course/other.tc": before["course/other.tc"],
        "course/sub/info.tc": before["course/sub/info.tc"],
    }
    assert {row.record.path: row.record.kind for row in cache.rows()}["course/info.rehu"] is RecordKind.REHU


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
        advertised_duration=3600,
        original_duration=3500,
        current_duration=1200,
        level=("intermediate", "beginner"),
        advertised_count="500+",
        current_count=480,
        format_version=1,
        mtime_ns=42,
        size=7,
        content_hash="abc",
        error="broken",
    )

    cache.apply_root_scan(first.root_id, [written], scanned_at=5.0)

    (row,) = cache.rows()
    assert row.record == written
    assert (row.root_id, row.root_label, row.scanned_at) == (first.root_id, "tutorials", 5.0)


def test_a_record_without_type_fields_reads_them_empty(cache: CatalogCache, database: MemoryDatabase) -> None:
    """A record whose type has none of the type-specific fields stores nothing for them, ``level`` included.

    **Test steps:**

    * scan a record carrying no type-specific field
    * verify its ``level`` column holds ``NULL``, not an empty array, and the row reads every field empty
    """
    rehuco, first, _ = two_roots()
    cache.reconcile_roots(rehuco.roots)

    cache.apply_root_scan(first.root_id, [record("a/info.rehu", type="collection")])

    assert database.scalar("SELECT level FROM resources") is None
    (row,) = cache.rows()
    assert row.record == record("a/info.rehu", type="collection")
    assert all(getattr(row.record, name) in {None, ()} for name in TYPE_FIELD_COLUMNS)


def test_a_rescan_shows_a_value_whose_case_changed(cache: CatalogCache) -> None:
    """A file that fixed an author's, tag's or publisher's case shows the new spelling after a rescan (#377).

    The shared value rows are unique case-insensitively, so they keep the first spelling ever stored; what a
    resource shows is its own.

    **Test steps:**

    * scan a record naming ``foo bar`` as author, tag and publisher
    * rescan it naming ``Foo Bar``
    * verify the row reads ``Foo Bar`` in all three
    """
    rehuco, first, _ = two_roots()
    cache.reconcile_roots(rehuco.roots)
    cache.apply_root_scan(
        first.root_id, [record("a/info.rehu", authors=("foo bar",), tags=("foo bar",), publishers=("foo bar",))]
    )

    cache.apply_root_scan(
        first.root_id, [record("a/info.rehu", authors=("Foo Bar",), tags=("Foo Bar",), publishers=("Foo Bar",))]
    )

    (row,) = cache.rows()
    assert (row.record.authors, row.record.tags, row.record.publishers) == (("Foo Bar",), ("Foo Bar",), ("Foo Bar",))


def test_two_resources_keep_their_own_spelling_of_one_name(cache: CatalogCache) -> None:
    """Each resource shows its file's spelling, while a filter still finds both as one name.

    **Test steps:**

    * scan two records spelling one author differently
    * verify each row reads its own spelling, and an ``authors`` token in either case matches both
    """
    rehuco, first, _ = two_roots()
    cache.reconcile_roots(rehuco.roots)

    cache.apply_root_scan(
        first.root_id, [record("a/info.rehu", authors=("foo bar",)), record("b/info.rehu", authors=("Foo Bar",))]
    )

    assert {row.record.path: row.record.authors for row in cache.rows()} == {
        "a/info.rehu": ("foo bar",),
        "b/info.rehu": ("Foo Bar",),
    }
    matched = cache.rows(CatalogQuery(tokens=((CatalogField.AUTHORS, "FOO BAR"),)))
    assert {row.record.path for row in matched} == {"a/info.rehu", "b/info.rehu"}


def test_a_row_written_before_spellings_were_kept_reads_the_shared_one(
    cache: CatalogCache, database: MemoryDatabase
) -> None:
    """A join row from a version-1 cache has no spelling of its own until its resource is scanned again.

    **Test steps:**

    * scan a record, then clear its join row's spelling as version 1 left it
    * verify the shared spelling is read instead
    """
    rehuco, first, _ = two_roots()
    cache.reconcile_roots(rehuco.roots)
    cache.apply_root_scan(first.root_id, [record("a/info.rehu", authors=("Ann",))])

    database.keeper.execute("UPDATE resource_authors SET name = NULL")

    (row,) = cache.rows()
    assert row.record.authors == ("Ann",)


def test_a_version_1_cache_upgrades_and_keeps_its_rows(
    memory: Callable[[], MemoryDatabase], mocker: MockerFixture
) -> None:
    """The version-2 step adds the spelling column without losing what version 1 held.

    **Test steps:**

    * build a version-1 cache holding one record with an author
    * reopen it with the full chain
    * verify the stamp is current and the record still reads its author
    """
    database = memory()
    mocker.patch("rehuco_core.rehudb.sqlite3.connect", side_effect=database.connect)
    mocker.patch.object(Path, "mkdir", autospec=True)
    rehuco, first, _ = two_roots()
    with CatalogCache.open(CACHE_PATH, chain=CHAIN[:1]) as old:
        old.reconcile_roots(rehuco.roots)
        database.keeper.execute("BEGIN")
        old_id = database.keeper.execute(
            "INSERT INTO resources (root_id, path, path_key, kind, mtime_ns, size, content_hash, scanned_at) "
            "VALUES (?, 'a/info.rehu', 'a/info.rehu', 'rehu', 0, 0, '0', 0) RETURNING id",
            (str(first.root_id),),
        ).fetchone()[0]
        database.keeper.execute("INSERT INTO authors (name) VALUES ('Ann')")
        database.keeper.execute("INSERT INTO resource_authors VALUES (?, 1, 0)", (old_id,))
        database.keeper.execute("COMMIT")

    with CatalogCache.open(CACHE_PATH) as upgraded:
        assert upgraded.schema_version == CURRENT_VERSION
        assert [row.record.authors for row in upgraded.rows()] == [("Ann",)]


def test_a_version_2_cache_upgrades_keeping_its_rows_empty_and_stale(
    memory: Callable[[], MemoryDatabase], mocker: MockerFixture
) -> None:
    """The version-3 step adds the type-specific columns: a row from before it keeps its place, shows them empty
    rather than wrong, and carries no signature a real file could match, so the next scan reads it again (#399).

    **Test steps:**

    * build a version-2 cache holding one scanned tutorial
    * reopen it with the full chain
    * verify the stamp is current, the row is still there with its title, its type fields are empty, and its
      stat signature and content hash are cleared
    """
    database = memory()
    mocker.patch("rehuco_core.rehudb.sqlite3.connect", side_effect=database.connect)
    mocker.patch.object(Path, "mkdir", autospec=True)
    rehuco, first, _ = two_roots()
    with CatalogCache.open(CACHE_PATH, chain=CHAIN[:2]) as old:
        old.reconcile_roots(rehuco.roots)
        database.keeper.execute(
            "INSERT INTO resources (root_id, path, path_key, kind, type, title, mtime_ns, size, content_hash, "
            "scanned_at) VALUES (?, 'a/info.rehu', 'a/info.rehu', 'rehu', 'tutorial', 'T', 42, 7, 'abc', 0)",
            (str(first.root_id),),
        )

    with CatalogCache.open(CACHE_PATH) as upgraded:
        assert upgraded.schema_version == CURRENT_VERSION
        rows = upgraded.rows()
    assert len(rows) == 1
    row = rows[0]
    assert (row.record.title, row.record.type, row.record.size) == ("T", "tutorial", 7)
    assert all(getattr(row.record, name) in {None, ()} for name in TYPE_FIELD_COLUMNS)
    assert (row.record.mtime_ns, row.record.content_hash) == (0, "")


def test_a_version_3_cache_upgrades_with_no_format_version_and_stale(
    memory: Callable[[], MemoryDatabase], mocker: MockerFixture
) -> None:
    """The version-4 step adds the format version: a row from before it keeps its place, reads no version until it
    is read again, and carries no signature a real file could match (#379).

    **Test steps:**

    * build a version-3 cache holding one scanned ``.rehu``
    * reopen it with the full chain
    * verify the stamp is current, the row is still there with no format version, and its signature is cleared
    """
    database = memory()
    mocker.patch("rehuco_core.rehudb.sqlite3.connect", side_effect=database.connect)
    mocker.patch.object(Path, "mkdir", autospec=True)
    rehuco, first, _ = two_roots()
    with CatalogCache.open(CACHE_PATH, chain=CHAIN[:3]) as old:
        old.reconcile_roots(rehuco.roots)
        database.keeper.execute(
            "INSERT INTO resources (root_id, path, path_key, kind, title, mtime_ns, size, content_hash, scanned_at) "
            "VALUES (?, 'a/info.rehu', 'a/info.rehu', 'rehu', 'T', 42, 7, 'abc', 0)",
            (str(first.root_id),),
        )

    with CatalogCache.open(CACHE_PATH) as upgraded:
        assert upgraded.schema_version == CURRENT_VERSION
        rows = upgraded.rows()
    assert len(rows) == 1
    row = rows[0]
    assert (row.record.title, row.record.format_version) == ("T", None)
    assert (row.record.mtime_ns, row.record.content_hash) == (0, "")


# endregion

# region Targeted updates

TUTORIALS: Final = Path("D:/tutorials")
""":func:`two_roots`'s first root's folder."""


@fixture(name="filled")
def fixture_filled(cache: CatalogCache) -> tuple[CatalogCache, RehucoRoot, RehucoRoot]:
    """A cache whose two roots are reconciled and empty.

    :param cache: the cache.
    :returns: it, and the two roots.
    """
    rehuco, first, second = two_roots()
    cache.reconcile_roots(rehuco.roots)
    return cache, first, second


def test_a_path_is_located_under_its_innermost_root(cache: CatalogCache) -> None:
    """Component by component, so a sibling folder that merely starts alike is not inside; a root's own folder is
    no record."""
    rehuco, first, _ = two_roots()
    row = rehuco.add_root(TUTORIALS / "blender")
    inner = rehuco.roots[row]
    cache.reconcile_roots(rehuco.roots)

    located = cache.locate(TUTORIALS / "blender/donut/info.rehu")
    outer = cache.locate(TUTORIALS / "zbrush/info.rehu")

    assert located is not None and outer is not None
    assert (located.root.root_id, located.relative) == (inner.root_id, "donut/info.rehu")
    assert (outer.root.root_id, outer.relative) == (first.root_id, "zbrush/info.rehu")
    assert cache.locate(Path("D:/tutorials2/info.rehu")) is None
    assert cache.locate(TUTORIALS) is None


def test_one_record_is_written_and_removed_on_its_own(filled: tuple[CatalogCache, RehucoRoot, RehucoRoot]) -> None:
    """A save writes its row, a deletion drops it and the values only it named; neither touches another row."""
    cache, first, _ = filled
    cache.apply_root_scan(first.root_id, [record("kept.rehu")])

    assert cache.upsert_record(first.root_id, record("new.rehu", title="New", authors=("Ann",)), scanned_at=5.0)
    rows = {row.record.path: row for row in cache.rows()}
    assert (rows["new.rehu"].record.title, rows["new.rehu"].scanned_at) == ("New", 5.0)

    assert cache.remove(TUTORIALS / "new.rehu")
    assert list(ids(cache)) == ["kept.rehu"]
    assert not cache.rows(CatalogQuery(tokens=((CatalogField.AUTHORS, "Ann"),)))
    assert not cache.remove(TUTORIALS / "new.rehu")
    assert not cache.remove(Path("Z:/elsewhere/new.rehu"))


def test_the_rows_at_or_beneath_a_path_are_found_by_id(filled: tuple[CatalogCache, RehucoRoot, RehucoRoot]) -> None:
    """A record, a folder's subtree, and nothing for a path under no root or a sibling that merely starts alike
    (#379).

    **Test steps:**

    * scan three records under the first root
    * verify a record, a folder and an outside path each name the rows they hold
    """
    cache, first, _ = filled
    cache.apply_root_scan(first.root_id, [record("a/info.rehu"), record("a/b/info.rehu"), record("ab/info.rehu")])
    by_path = ids(cache)

    assert cache.resource_ids([TUTORIALS / "a" / "info.rehu"]) == {by_path["a/info.rehu"]}
    assert cache.resource_ids([TUTORIALS / "a", Path("Z:/elsewhere/a")]) == {
        by_path["a/info.rehu"],
        by_path["a/b/info.rehu"],
    }
    assert not cache.resource_ids([TUTORIALS, Path("Z:/elsewhere")])


def test_rows_read_by_id_are_only_those_that_also_match(filled: tuple[CatalogCache, RehucoRoot, RehucoRoot]) -> None:
    """The few rows a change touched, still narrowed by the query, with their values (#379).

    **Test steps:**

    * scan three records, two of them by one author
    * verify reading two ids returns those two, and with an author token only the one that matches
    """
    cache, first, _ = filled
    cache.apply_root_scan(
        first.root_id,
        [record("a.rehu", authors=("Ann",)), record("b.rehu", authors=("Bob",)), record("c.rehu", authors=("Ann",))],
    )
    by_path = ids(cache)
    wanted = {by_path["a.rehu"], by_path["b.rehu"]}

    assert [row.record.path for row in cache.rows(ids=wanted)] == ["a.rehu", "b.rehu"]
    (row,) = cache.rows(CatalogQuery(tokens=((CatalogField.AUTHORS, "Ann"),)), ids=wanted)
    assert (row.record.path, row.record.authors) == ("a.rehu", ("Ann",))
    assert not cache.rows(ids=())


def test_a_record_of_a_root_not_in_the_cache_is_not_written(cache: CatalogCache) -> None:
    """Nothing to write it under."""
    assert not cache.upsert_record(uuid4(), record("a.rehu"))
    assert not cache.rows()


def test_a_roots_resources_are_counted(filled: tuple[CatalogCache, RehucoRoot, RehucoRoot]) -> None:
    """The count is what a root's removal would drop, and no other root's."""
    cache, first, second = filled
    assert cache.resource_count(first.root_id) == 0
    cache.apply_root_scan(first.root_id, [record("a.rehu"), record("b.rehu")])
    cache.apply_root_scan(second.root_id, [record("p.rehu")])

    assert cache.resource_count(first.root_id) == 2
    assert cache.resource_count(second.root_id) == 1
    assert cache.resource_count(uuid4()) == 0


def test_a_signature_is_what_its_row_was_read_at(filled: tuple[CatalogCache, RehucoRoot, RehucoRoot]) -> None:
    """One row's, or every row's under a root, keyed as a scan looks them up."""
    cache, first, second = filled
    cache.apply_root_scan(first.root_id, [record("a.rehu", mtime_ns=7, size=3)])
    cache.apply_root_scan(second.root_id, [record("p.rehu")])

    expected = RecordSignature("a.rehu", 7, 3)
    assert cache.signatures(first.root_id) == {catalog_path_key("a.rehu"): expected}
    assert cache.signature(first.root_id, "a.rehu") == expected
    assert cache.signature(first.root_id, "p.rehu") is None


def test_a_signature_matches_only_a_readable_uncleared_row_of_the_same_time_and_size() -> None:
    """An error row and a cleared one are always read again."""
    assert RecordSignature("a", 7, 3).matches(7, 3)
    assert not RecordSignature("a", 7, 3).matches(8, 3)
    assert not RecordSignature("a", 7, 3).matches(7, 4)
    assert not RecordSignature("a", 7, 3, "Not JSON").matches(7, 3)
    assert not RecordSignature("a", 0, 3).matches(0, 3)


def test_a_renamed_directory_rebases_every_record_beneath_it(
    filled: tuple[CatalogCache, RehucoRoot, RehucoRoot],
) -> None:
    """A directory-scoped collection's rename moves its own record and every nested ``.rehu`` and ``.tc``, ids and
    values kept, without reading one; a sibling whose name merely starts alike, and the other root, stay.

    **Test steps:**

    * fill ``series/`` with nested records, beside ``seriesX/``, and a row under the other root
    * apply the one pair ``series`` -> ``saga``
    * verify the rebased paths, the ids, the values, and the rows left alone
    """
    cache, first, second = filled
    nested = [record("series/info.rehu", authors=("Ann",)), record("series/a/info.rehu")]
    cache.apply_root_scan(
        first.root_id, [*nested, CatalogRecord("series/b/Info.tc", RecordKind.TC), record("seriesX/info.rehu")]
    )
    cache.apply_root_scan(second.root_id, [record("series/info.rehu")])
    before = {(row.root_id, row.record.path): row.resource_id for row in cache.rows()}

    moved = cache.apply_relocation([(TUTORIALS / "series", TUTORIALS / "saga")])

    assert moved == 3
    rows = {(row.root_id, row.record.path): row for row in cache.rows()}
    assert {(root_id, path): row.resource_id for (root_id, path), row in rows.items()} == {
        (first.root_id, "saga/info.rehu"): before[(first.root_id, "series/info.rehu")],
        (first.root_id, "saga/a/info.rehu"): before[(first.root_id, "series/a/info.rehu")],
        (first.root_id, "saga/b/Info.tc"): before[(first.root_id, "series/b/Info.tc")],
        (first.root_id, "seriesX/info.rehu"): before[(first.root_id, "seriesX/info.rehu")],
        (second.root_id, "series/info.rehu"): before[(second.root_id, "series/info.rehu")],
    }
    assert rows[(first.root_id, "saga/info.rehu")].record.authors == ("Ann",)
    assert cache.signature(first.root_id, "saga/a/info.rehu") is not None


def test_a_file_scoped_rename_moves_only_its_own_record(filled: tuple[CatalogCache, RehucoRoot, RehucoRoot]) -> None:
    """``foo.rehu``'s siblings and sidecars travel in the plan but have no rows; ``foobar.rehu`` is another
    resource."""
    cache, first, _ = filled
    cache.apply_root_scan(first.root_id, [record("dir/foo.rehu"), record("dir/foobar.rehu")])
    before = ids(cache)
    plan = [
        (TUTORIALS / f"dir/foo{tail}", TUTORIALS / f"dir/bar{tail}") for tail in (".rehu", ".zip", ".sfv", "00.jpg")
    ]

    assert cache.apply_relocation(plan) == 1
    assert ids(cache) == {"dir/bar.rehu": before["dir/foo.rehu"], "dir/foobar.rehu": before["dir/foobar.rehu"]}


def test_a_folder_rename_carries_its_file_scoped_record_and_that_records_rename_only_itself(
    filled: tuple[CatalogCache, RehucoRoot, RehucoRoot],
) -> None:
    """A folder holding ``info.rehu`` and ``bar.rehu``: renaming the folder rebases both; renaming ``bar`` touches
    only ``bar``'s row."""
    cache, first, _ = filled
    cache.apply_root_scan(first.root_id, [record("pack/info.rehu"), record("pack/bar.rehu")])
    before = ids(cache)

    assert cache.apply_relocation([(TUTORIALS / "pack", TUTORIALS / "kit")]) == 2
    assert cache.apply_relocation([(TUTORIALS / "kit/bar.rehu", TUTORIALS / "kit/baz.rehu")]) == 1

    assert ids(cache) == {"kit/info.rehu": before["pack/info.rehu"], "kit/baz.rehu": before["pack/bar.rehu"]}


def test_a_case_only_rename_on_a_case_insensitive_filesystem_respells_in_place(
    filled: tuple[CatalogCache, RehucoRoot, RehucoRoot], mocker: MockerFixture
) -> None:
    """Both ends share their keys, so the rows moving are not mistaken for stale ones already at the destination."""
    mocker.patch("rehuco_core.rehudb.catalog_path_key", side_effect=str.casefold)
    cache, first, _ = filled
    cache.apply_root_scan(first.root_id, [record("course/info.rehu"), record("course/lesson.rehu")])
    before = ids(cache)

    assert cache.apply_relocation([(TUTORIALS / "course", TUTORIALS / "Course")]) == 2

    assert ids(cache) == {
        "Course/info.rehu": before["course/info.rehu"],
        "Course/lesson.rehu": before["course/lesson.rehu"],
    }


def test_a_stale_row_at_the_destination_gives_way(filled: tuple[CatalogCache, RehucoRoot, RehucoRoot]) -> None:
    """The rename found nothing there, so a row there is out of date."""
    cache, first, _ = filled
    cache.apply_root_scan(first.root_id, [record("old/info.rehu", title="Moved"), record("new/info.rehu")])
    before = ids(cache)

    cache.apply_relocation([(TUTORIALS / "old", TUTORIALS / "new")])

    (row,) = cache.rows()
    assert (row.record.path, row.resource_id, row.record.title) == ("new/info.rehu", before["old/info.rehu"], "Moved")


def test_a_rename_of_the_root_itself_leaves_its_rows_alone(filled: tuple[CatalogCache, RehucoRoot, RehucoRoot]) -> None:
    """Relative to the root, nothing moved; where the root now is, is the ``.rehuco``'s to say."""
    cache, first, _ = filled
    cache.apply_root_scan(first.root_id, [record("info.rehu")])

    assert cache.apply_relocation([(TUTORIALS, Path("D:/tuts"))]) == 0
    assert list(ids(cache)) == ["info.rehu"]


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


def test_a_folder_token_folds_the_label_as_ascii_and_the_path_as_the_filesystem_does(library: CatalogCache) -> None:
    """The root's label is matched ignoring ASCII case; the path beneath it by its key (#454), which folds as this
    filesystem does -- so ``BLENDER`` finds ``blender`` where ``normcase`` says they are one folder, and only there."""
    assert titles(library, CatalogQuery(tokens=((CatalogField.FOLDER, "TUTORIALS"),))) == [
        "Donut 100%",
        "Rigging",
        "Sculpt_1",
    ]
    shouted = CatalogQuery(tokens=((CatalogField.FOLDER, "Tutorials/BLENDER"),))

    assert bool(titles(library, shouted)) == (catalog_path_key("BLENDER") == catalog_path_key("blender"))


def test_a_folder_token_takes_like_wildcards_literally(library: CatalogCache) -> None:
    """``%`` and ``_`` in a folder are characters, not patterns."""
    assert not titles(library, CatalogQuery(tokens=((CatalogField.FOLDER, "tutorials/_lender"),)))
    assert not titles(library, CatalogQuery(tokens=((CatalogField.FOLDER, "tutorials/%"),)))


def test_two_resources_sharing_a_value_under_different_spellings_each_keep_their_own(cache: CatalogCache) -> None:
    """The value row keeps the first spelling ever written; each resource's join keeps what its record said, and a
    token finds both whatever its case."""
    rehuco, first, _ = two_roots()
    cache.reconcile_roots(rehuco.roots)
    cache.apply_root_scan(
        first.root_id,
        [record("a/info.rehu", title="A", authors=("Ann",)), record("b/info.rehu", title="B", authors=("ann",))],
    )

    rows = cache.rows(CatalogQuery(tokens=((CatalogField.AUTHORS, "ANN"),)))

    assert [(row.record.title, row.record.authors) for row in rows] == [("A", ("Ann",)), ("B", ("ann",))]


def test_a_repeated_value_field_must_match_both_values(library: CatalogCache) -> None:
    """Two tokens of one field narrow, each an independent clause."""
    both = CatalogQuery(tokens=((CatalogField.TAGS, "3d"), (CatalogField.TAGS, "rig")))

    assert titles(library, both) == ["Rigging"]


@mark.parametrize(
    "token",
    [
        (CatalogField.FOLDER, "tutorials/blender"),
        (CatalogField.AUTHORS, "ann"),
        (CatalogField.TAGS, "rig"),
        (CatalogField.PUBLISHERS, "pub"),
    ],
    ids=lambda token: token[0].value,
)
def test_a_token_on_its_own_reads_resources_through_an_index_never_a_scan(
    library: CatalogCache, token: tuple[CatalogField, str]
) -> None:
    """Every statement one token runs reaches ``resources`` through an index (#454): a plan that scans the table and
    probes a join once per row is what made ``authors:`` cost 758 ms at 100k resources, and a folder token ORed over
    its label splits scans unless every term is on the table's own indexed columns. The planner's choice here does not
    depend on the row count, so the small library is enough -- but each token is asked alone, since beside another
    it may ride that one's index as a mere filter."""
    statements: list[str] = []
    connection = library.connection
    connection.set_trace_callback(statements.append)
    try:
        library.rows(CatalogQuery(tokens=(token,)))
    finally:
        connection.set_trace_callback(None)
    plans = {
        statement: [step for (*_, step) in connection.execute(f"EXPLAIN QUERY PLAN {statement}")]
        for statement in statements
        if "FROM resources r" in statement
    }

    assert len(plans) == 4  # the rows and the three value tables
    assert not [step for steps in plans.values() for step in steps if re.fullmatch(r"SCAN r( .*)?", step)]


def test_tokens_and_text_must_all_match(library: CatalogCache) -> None:
    """Every condition narrows."""
    query = CatalogQuery("o", ((CatalogField.AUTHORS, "Ann"), (CatalogField.TAGS, "3d")))

    assert titles(library, query) == ["Donut 100%"]


def test_a_matching_row_still_carries_all_its_values(library: CatalogCache) -> None:
    """Narrowing by one tag does not narrow the tags a row reads back."""
    (row,) = library.rows(CatalogQuery(tokens=((CatalogField.TAGS, "rig"),)))

    assert row.record.tags == ("3d", "rig")


# endregion

# region A type's columns


def test_a_type_contributes_the_stored_fields_its_plugin_declares() -> None:
    """A tutorial contributes its durations and level, a reference pack -- by any of its spellings -- its image
    counts, in the cache's order (#399)."""
    assert catalog_type_fields("tutorial") == ("advertised_duration", "original_duration", "current_duration", "level")
    assert catalog_type_fields("ReferenceImages") == ("advertised_count", "current_count")


def test_a_type_declaring_none_of_them_contributes_nothing() -> None:
    """A Collection declares no field of its own, a type no plugin claims declares nothing, and a record with no
    type has none."""
    assert not catalog_type_fields("collection")
    assert not catalog_type_fields("daz3d")
    assert not catalog_type_fields("")


def test_every_stored_type_field_is_some_plugins() -> None:
    """No type-specific column is one no built-in type would ever fill."""
    declared = {name for plugin in BUILTIN_PLUGINS for name in plugin.field_names}

    assert set(TYPE_FIELD_COLUMNS) <= declared


# endregion
