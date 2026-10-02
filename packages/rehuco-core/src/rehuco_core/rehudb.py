"""The ``.rehudb`` catalog cache: one SQLite file per ``.rehuco``, holding what its roots' records say
([[data-model#cache-schema]], [[data-model#local-file-trio]], #372).

**Derived and disposable.** Everything here can be rebuilt from the records themselves, which is what lets
the cache be versioned forward only (:mod:`rehuco_core.migrations.rehudb`): a file stamped newer than this
build, or one that is not a database at all, is discarded and rebuilt rather than understood -- the reason
logged, the old content never written.

**Named by the rehuco id, in a local folder the caller names** (:func:`rehudb_path`). Not by the
``.rehuco``'s path, so moving or renaming one keeps its cache; never on a share, where SQLite's locking is
unsafe. Which folder is the app's to say -- core reads no settings and knows no platform's cache location.

**One connection per thread**, enforced rather than hoped for: :class:`CatalogCache` keeps
:mod:`sqlite3`'s same-thread check, so a scan job opens its own on the worker while a browser reads through
another on the GUI thread, and WAL lets the two proceed together. Foreign keys are switched on for every
connection, because the cascade a root removal relies on is otherwise silently ignored.

**Roots are keyed by their** ``.rehuco`` **id** (:attr:`~rehuco_core.RehucoRoot.root_id`), never by path:
relabelling, reordering or re-pointing a root updates its row in place (:meth:`CatalogCache.reconcile_roots`)
and keeps its resources. A **root is wholly online or wholly offline** ([[mounts-and-storage#offline-mounts]]):
one that would not list keeps its rows as they were (:meth:`CatalogCache.mark_root_unreachable`), while a full
scan of one that did replaces them (:meth:`CatalogCache.apply_root_scan`) -- a record no longer there is gone.

Every value a query matches against is a parameter; the SQL around it is assembled only from the fixed
fragments below, never from text a reader typed.
"""

import logging
import os
import sqlite3
import time
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import TracebackType
from typing import Final, Self
from uuid import UUID

from .constants import REHUDB_SUFFIX
from .migrations.rehudb import BASE_VERSION, CHAIN, SchemaChain
from .migrations.runner import chain_head
from .rehuco_file import RehucoRoot

LOG: Final = logging.getLogger(__name__)

BUSY_TIMEOUT_MS: Final = 5000
"""How long one connection waits for another's write to finish before giving up, in milliseconds.

A scan writes its whole root in one transaction at its end; a browser reading meanwhile waits out at most
that commit, which is short because everything slow -- listing and parsing -- happened before it began."""

SIDECAR_SUFFIXES: Final = ("-wal", "-shm")
"""The files SQLite keeps beside a database in WAL mode -- discarded with it, or a rebuilt cache would
replay an old log into a new file."""


class RecordKind(StrEnum):
    """Which format a cached record is ([[data-model#cache-schema]])."""

    REHU = "rehu"
    TC = "tc"


class CatalogField(StrEnum):
    """What a filter token can address ([[plugins#rehuco-dock]]); its value is the token's spelling."""

    FOLDER = "folder"
    AUTHORS = "authors"
    TAGS = "tags"
    PUBLISHERS = "publishers"
    TYPE = "type"


@dataclass(frozen=True, slots=True)
class CatalogRecord:  # pylint: disable=too-many-instance-attributes
    """What a scan read from one record: the common core a browser shows, and how to tell it changed.

    :param path: root-relative, ``/``-separated, as spelled on disk.
    :param kind: the record's format.
    :param uuid: the resource's id; empty for a legacy record, which has none until converted.
    :param type: the resource type.
    :param title: the primary source's title.
    :param publisher: the primary source's publisher.
    :param url: the primary source's URL.
    :param released: the partial-precision release date, or ``None``.
    :param current_size: the measured size in bytes, or ``None``.
    :param updated: when the record was last edited, as stored.
    :param authors: author names, in order.
    :param tags: advertised then extra tags, in order.
    :param publishers: every source's publisher, primary first.
    :param mtime_ns: the record file's modification time ([[data-model#scan-and-staleness]]).
    :param size: the record file's size in bytes.
    :param content_hash: the record file's bytes, hashed at this read.
    :param error: why the record could not be read, or ``None`` -- an unreadable record keeps a row, so
        the browser shows it exists rather than silently not listing it.
    """

    path: str
    kind: RecordKind
    uuid: str = ""
    type: str = ""
    title: str = ""
    publisher: str = ""
    url: str = ""
    released: str | None = None
    current_size: int | None = None
    updated: str = ""
    authors: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    publishers: tuple[str, ...] = ()
    mtime_ns: int = 0
    size: int = 0
    content_hash: str = ""
    error: str | None = None


@dataclass(frozen=True, slots=True)
class CatalogRoot:
    """One root's row: what the ``.rehuco`` says about it, and what the last scan found.

    :param root_id: the ``.rehuco`` root's stable id.
    :param label: the name the browser shows and a folder filter addresses.
    :param path: the root's folder.
    :param position: its row in the ``.rehuco``.
    :param removable: whether its folder lives on a removable device; stored, not yet read.
    :param reachable: whether the last scan could list it, or ``None`` before any scan.
    :param scanned_at: when its rows were last replaced by a scan, or ``None``.
    """

    root_id: UUID
    label: str
    path: Path
    position: int
    removable: bool
    reachable: bool | None
    scanned_at: float | None


@dataclass(frozen=True, slots=True)
class CatalogRow:
    """One resource as the browser reads it.

    :param resource_id: the row's id, stable across scans that keep finding the record.
    :param root_id: the root it was found under.
    :param root_label: that root's label.
    :param record: what the record says.
    :param scanned_at: when it was last read.
    """

    resource_id: int
    root_id: UUID
    root_label: str
    record: CatalogRecord
    scanned_at: float


@dataclass(frozen=True, slots=True)
class CatalogQuery:
    """Which rows to read: free text over title and path, and field tokens, all of which must match.

    The structure a filter line parses into (#379); parsing ``field="value"`` is the line's business, so
    this takes the tokens already split.

    :param text: matched case-insensitively anywhere in a title or a root-relative path; empty matches all.
    :param tokens: ``(field, value)`` pairs. ``folder`` is a ``<label>/<relative path>`` prefix; ``authors``,
        ``tags`` and ``publishers`` match one value whole, case-insensitively; ``type`` matches the type.
    """

    text: str = ""
    tokens: tuple[tuple[CatalogField, str], ...] = ()


JOINS: Final = (
    ("authors", "resource_authors"),
    ("tags", "resource_tags"),
    ("publishers", "resource_publishers"),
)
"""Each value table and its join table -- the only names ever formatted into a statement."""

TOKEN_CLAUSES: Final = {
    CatalogField.FOLDER: "(roots.label || '/' || r.path) LIKE ? ESCAPE '\\'",
    CatalogField.TYPE: "r.type = ? COLLATE NOCASE",
    **{
        CatalogField(table): (
            f"EXISTS (SELECT 1 FROM {join} j JOIN {table} v ON v.id = j.value_id "  # nosec B608  # fixed names
            "WHERE j.resource_id = r.id AND v.name = ?)"
        )
        for table, join in JOINS
    },
}
"""The clause each token field adds, each with exactly one parameter."""

RESOURCE_COLUMNS: Final = (
    "path",
    "kind",
    "uuid",
    "type",
    "title",
    "publisher",
    "url",
    "released",
    "current_size",
    "updated",
    "mtime_ns",
    "size",
    "content_hash",
    "error",
)
"""The ``resources`` columns a :class:`CatalogRecord` fills -- each one of its fields, under the same name."""


def rehudb_path(cache_dir: Path, rehuco_id: UUID) -> Path:
    """Where a ``.rehuco``'s cache lives -- named by its rehuco id, so it follows the file wherever it moves.

    :param cache_dir: the local cache folder the app chose; never a share.
    :param rehuco_id: the ``.rehuco``'s :attr:`~rehuco_core.RehucoFile.rehuco_id`.
    :returns: the cache file's path.
    """
    return cache_dir / f"{rehuco_id}{REHUDB_SUFFIX}"


class CatalogCache:
    """An open ``.rehudb``, current-version, on the thread that opened it.

    Built by :meth:`open`; closed by :meth:`close` or by leaving a ``with`` block.

    :param connection: an open, configured, migrated connection.
    :param path: the file it is connected to.
    """

    def __init__(self, connection: sqlite3.Connection, path: Path) -> None:
        self.__connection: Final = connection
        self.__path: Final = path

    @classmethod
    def open(cls, path: Path, *, chain: SchemaChain = CHAIN) -> CatalogCache:
        """Open the cache at ``path``, creating it, upgrading it, or discarding and rebuilding it.

        A file this build cannot use -- stamped newer than ``chain`` reaches, or not a database -- is
        deleted with its WAL sidecars and created again, the reason logged.

        :param path: the cache file; its folder is created when missing.
        :param chain: the schema chain to bring the file up to -- this build's, unless a test needs another.
        :returns: the open cache.
        :raises OSError: the folder could not be created, or a discarded file could not be deleted.
        :raises sqlite3.Error: SQLite refused something even on a fresh file.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        head = chain_head(chain, BASE_VERSION)
        connection = cls.__connect(path)
        try:
            version = cls.__user_version(connection)
            reason = None if version <= head else f"its schema version {version} is newer than this build's {head}"
        except sqlite3.OperationalError:
            # a lock, a WAL recovery in progress, an unreadable path -- the file may be perfectly good,
            # and the one thing not to do about it is delete it
            connection.close()
            raise
        except sqlite3.DatabaseError as error:
            version, reason = BASE_VERSION, f"it is not a database ({error})"
        if reason is not None:
            LOG.warning("Discarding the catalog cache %s and rebuilding it: %s.", path, reason)
            connection.close()
            cls.__discard(path)
            connection = cls.__connect(path)
            version = BASE_VERSION
        try:
            cls.__configure(connection, fresh=version == BASE_VERSION)
            cls.__migrate(connection, version, chain)
        except BaseException:
            connection.close()
            raise
        return cls(connection, path)

    # region Lifetime

    @property
    def path(self) -> Path:
        """The file this cache is connected to."""
        return self.__path

    @property
    def schema_version(self) -> int:
        """The schema version the file is stamped with."""
        return self.__user_version(self.__connection)

    @property
    def connection(self) -> sqlite3.Connection:
        """The connection itself, for a caller that needs a pragma or a statement this class has no word for."""
        return self.__connection

    def close(self) -> None:
        """Close the connection; the cache is unusable afterwards."""
        self.__connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self, kind: type[BaseException] | None, error: BaseException | None, traceback: TracebackType | None
    ) -> None:
        self.close()

    # endregion

    # region Roots

    def roots(self) -> tuple[CatalogRoot, ...]:
        """Every root, in the ``.rehuco``'s order.

        :returns: the root rows.
        """
        cursor = self.__connection.execute(
            "SELECT id, label, path, position, removable, reachable, scanned_at FROM roots ORDER BY position"
        )
        return tuple(
            CatalogRoot(
                root_id=UUID(root_id),
                label=label,
                path=Path(path),
                position=position,
                removable=bool(removable),
                reachable=None if reachable is None else bool(reachable),
                scanned_at=scanned_at,
            )
            for root_id, label, path, position, removable, reachable, scanned_at in cursor
        )

    def reconcile_roots(self, roots: Sequence[RehucoRoot]) -> None:
        """Bring the ``roots`` table in line with a ``.rehuco``'s roots, matched by id.

        A root already here keeps its resources whatever changed about it -- label, path, order, the
        removable flag. A new id gets a row with nothing scanned under it; an id the ``.rehuco`` no longer
        has loses its row, and its resources with it.

        :param roots: the ``.rehuco``'s roots, in its order.
        """
        wanted = {str(root.root_id) for root in roots}
        with self.__transaction() as connection:
            for position, root in enumerate(roots):
                connection.execute(
                    "INSERT INTO roots (id, label, path, position, removable) VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT (id) DO UPDATE SET label = excluded.label, path = excluded.path, "
                    "position = excluded.position, removable = excluded.removable",
                    (str(root.root_id), root.label, str(root.path), position, int(root.removable)),
                )
            stale = [(root_id,) for (root_id,) in connection.execute("SELECT id FROM roots") if root_id not in wanted]
            connection.executemany("DELETE FROM roots WHERE id = ?", stale)
            if stale:
                self.__prune_values(connection)

    def mark_root_unreachable(self, root_id: UUID) -> None:
        """Record that a root would not list -- and nothing else: its rows stay exactly as they were.

        :param root_id: the root.
        """
        with self.__transaction() as connection:
            connection.execute("UPDATE roots SET reachable = 0 WHERE id = ?", (str(root_id),))

    def remove_root(self, root_id: UUID) -> None:
        """Delete a root and, by cascade, everything found under it; then hand the space back.

        ``PRAGMA incremental_vacuum`` rather than ``VACUUM``: the file was created to allow it, and it frees
        the pages the cascade emptied without rewriting the rest.

        :param root_id: the root.
        """
        with self.__transaction() as connection:
            connection.execute("DELETE FROM roots WHERE id = ?", (str(root_id),))
            self.__prune_values(connection)
        # a pragma that steps: it frees pages only as its rows are read
        self.__connection.execute("PRAGMA incremental_vacuum").fetchall()

    # endregion

    # region Resources

    def apply_root_scan(
        self, root_id: UUID, records: Sequence[CatalogRecord], *, scanned_at: float | None = None
    ) -> bool:
        """Replace a root's resources with what a full scan of it found, in one transaction.

        A record found again keeps its row id, so a view holding it keeps its place; a record not found is
        removed -- the root listed, so its absence is real.

        :param root_id: the root scanned.
        :param records: everything the scan found under it.
        :param scanned_at: when the scan ran; now, when omitted.
        :returns: whether it was applied -- ``False`` when the root was removed while the scan ran, which
            leaves nothing to apply to.
        """
        stamp = time.time() if scanned_at is None else scanned_at
        key = str(root_id)
        with self.__transaction() as connection:
            if connection.execute("SELECT 1 FROM roots WHERE id = ?", (key,)).fetchone() is None:
                LOG.info("The root %s was removed while it was scanned; the scan is dropped.", root_id)
                return False
            kept = {self.__upsert(connection, key, record, stamp) for record in records}
            existing = {
                resource_id
                for (resource_id,) in connection.execute("SELECT id FROM resources WHERE root_id = ?", (key,))
            }
            connection.executemany("DELETE FROM resources WHERE id = ?", [(gone,) for gone in existing - kept])
            connection.execute("UPDATE roots SET reachable = 1, scanned_at = ? WHERE id = ?", (stamp, key))
            self.__prune_values(connection)
        return True

    def rows(self, query: CatalogQuery | None = None) -> list[CatalogRow]:
        """The resources matching ``query``, in root order and then by path.

        :param query: what to match; ``None`` reads every row.
        :returns: the rows.
        """
        where, parameters = self.__where(query if query is not None else CatalogQuery())
        values = {table: self.__values(table, join, where, parameters) for table, join in JOINS}
        columns = ", ".join(f"r.{column}" for column in RESOURCE_COLUMNS)
        cursor = self.__connection.execute(
            f"SELECT r.id, r.root_id, roots.label, r.scanned_at, {columns} "  # nosec B608  # fixed names
            f"FROM resources r JOIN roots ON roots.id = r.root_id WHERE {where} ORDER BY roots.position, r.path_key",
            parameters,
        )
        rows: list[CatalogRow] = []
        for resource_id, root_id, root_label, scanned_at, *fields in cursor:
            columns_read = dict(zip(RESOURCE_COLUMNS, fields, strict=True))
            columns_read["kind"] = RecordKind(columns_read["kind"])
            record = CatalogRecord(
                **columns_read,
                authors=values["authors"].get(resource_id, ()),
                tags=values["tags"].get(resource_id, ()),
                publishers=values["publishers"].get(resource_id, ()),
            )
            rows.append(CatalogRow(resource_id, UUID(root_id), root_label, record, scanned_at))
        return rows

    # endregion

    # region Internals

    @contextmanager
    def __transaction(self) -> Generator[sqlite3.Connection]:
        """One write transaction: committed on a clean exit, rolled back on any other."""
        with self.__write(self.__connection):
            yield self.__connection

    @staticmethod
    @contextmanager
    def __write(connection: sqlite3.Connection) -> Generator[None]:
        """``BEGIN IMMEDIATE`` -- the write lock taken up front, so a second writer waits at the start
        rather than failing at the first statement -- then ``COMMIT``, or ``ROLLBACK`` on the way out of an
        exception."""
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        connection.execute("COMMIT")

    @staticmethod
    def __connect(path: Path) -> sqlite3.Connection:
        """A connection with transactions in this module's hands: autocommit, so every one is explicit -- and
        the busy wait set from the first statement, so the version read on open waits out another
        connection's write rather than failing on it."""
        return sqlite3.connect(path, autocommit=True, timeout=BUSY_TIMEOUT_MS / 1000)

    @staticmethod
    def __user_version(connection: sqlite3.Connection) -> int:
        """The file's schema stamp.

        :raises sqlite3.DatabaseError: the file is not a database.
        """
        return connection.execute("PRAGMA user_version").fetchone()[0]

    @staticmethod
    def __discard(path: Path) -> None:
        """Delete a cache file and its WAL sidecars, whichever of them exist."""
        path.unlink(missing_ok=True)
        for suffix in SIDECAR_SUFFIXES:
            path.with_name(path.name + suffix).unlink(missing_ok=True)

    @staticmethod
    def __configure(connection: sqlite3.Connection, *, fresh: bool) -> None:
        """Set the per-connection pragmas, and the one that must precede every table.

        :param connection: the connection.
        :param fresh: whether the file has no schema yet -- the only time ``auto_vacuum`` can be chosen
            without a full ``VACUUM``.
        """
        if fresh:
            connection.execute("PRAGMA auto_vacuum = INCREMENTAL")
        connection.execute("PRAGMA journal_mode = WAL").fetchall()
        connection.execute("PRAGMA foreign_keys = ON")

    @classmethod
    def __migrate(cls, connection: sqlite3.Connection, version: int, chain: SchemaChain) -> None:
        """Run every step ``version`` is below, each in its own transaction with its stamp.

        :param connection: the cache.
        :param version: the file's current stamp.
        :param chain: the steps.
        """
        for target, step in sorted(chain, key=lambda pair: pair[0]):
            if version >= target:
                continue
            with cls.__write(connection):
                step(connection)
                connection.execute(f"PRAGMA user_version = {int(target)}")
            LOG.info("Upgraded the catalog cache schema to version %d.", target)
            version = target

    @staticmethod
    def __upsert(connection: sqlite3.Connection, root_id: str, record: CatalogRecord, stamp: float) -> int:
        """Write one record's row and its values, keeping the row's id when it was already there.

        :returns: the row's id.
        """
        names = ", ".join(RESOURCE_COLUMNS)
        updates = ", ".join(f"{column} = excluded.{column}" for column in RESOURCE_COLUMNS)
        fields = tuple(getattr(record, column) for column in RESOURCE_COLUMNS)
        (resource_id,) = connection.execute(
            f"INSERT INTO resources (root_id, path_key, scanned_at, {names}) "  # nosec B608  # fixed names
            f"VALUES (?, ?, ?, {', '.join('?' * len(RESOURCE_COLUMNS))}) "
            f"ON CONFLICT (root_id, path_key) DO UPDATE SET scanned_at = excluded.scanned_at, {updates} RETURNING id",
            (root_id, os.path.normcase(record.path), stamp, *fields),
        ).fetchone()
        for (table, join), names_of in zip(JOINS, (record.authors, record.tags, record.publishers), strict=True):
            CatalogCache.__write_values(connection, table, join, resource_id, names_of)
        return resource_id

    @staticmethod
    def __write_values(
        connection: sqlite3.Connection, table: str, join: str, resource_id: int, names: tuple[str, ...]
    ) -> None:
        """Replace one resource's names in one value table, adding any name not there yet.

        :param table: the value table.
        :param join: its join table.
        :param resource_id: the resource.
        :param names: its names, in order; an empty one is skipped, a repeat (case-insensitively) kept once.
        """
        insert_value = f"INSERT INTO {table} (name) VALUES (?) ON CONFLICT DO NOTHING"  # nosec B608  # fixed names
        select_value = f"SELECT id FROM {table} WHERE name = ?"  # nosec B608  # fixed names
        connection.execute(f"DELETE FROM {join} WHERE resource_id = ?", (resource_id,))  # nosec B608  # fixed names
        for position, name in enumerate(name for name in names if name):
            connection.execute(insert_value, (name,))
            (value_id,) = connection.execute(select_value, (name,)).fetchone()
            connection.execute(
                f"INSERT OR IGNORE INTO {join} (resource_id, value_id, position) VALUES (?, ?, ?)",
                (resource_id, value_id, position),
            )

    @staticmethod
    def __prune_values(connection: sqlite3.Connection) -> None:
        """Drop every author, tag and publisher no resource names any more."""
        for table, join in JOINS:
            orphans = f"DELETE FROM {table} WHERE id NOT IN (SELECT value_id FROM {join})"  # nosec B608  # fixed names
            connection.execute(orphans)

    @staticmethod
    def __where(query: CatalogQuery) -> tuple[str, tuple[str, ...]]:
        """The ``WHERE`` condition a query reads as, over ``resources r`` joined to ``roots``.

        :returns: the condition and its parameters, one per placeholder.
        """
        clauses = ["1"]
        parameters: list[str] = []
        if query.text:
            clauses.append("(r.title LIKE ? ESCAPE '\\' OR r.path LIKE ? ESCAPE '\\')")
            pattern = f"%{CatalogCache.__escaped(query.text)}%"
            parameters += [pattern, pattern]
        for field, value in query.tokens:
            clauses.append(TOKEN_CLAUSES[field])
            if field is CatalogField.FOLDER:
                parameters.append(f"{CatalogCache.__escaped(value.strip('/'))}/%")
            else:
                parameters.append(value)
        return " AND ".join(clauses), tuple(parameters)

    @staticmethod
    def __escaped(text: str) -> str:
        """``text`` with ``LIKE``'s wildcards and its escape character taken literally."""
        return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def __values(self, table: str, join: str, where: str, parameters: tuple[str, ...]) -> dict[int, tuple[str, ...]]:
        """One value table's names for every matching resource, in each resource's own order.

        :returns: the names, keyed by resource id.
        """
        cursor = self.__connection.execute(
            f"SELECT j.resource_id, v.name FROM {join} j JOIN {table} v ON v.id = j.value_id "  # nosec B608  # fixed
            f"WHERE j.resource_id IN (SELECT r.id FROM resources r JOIN roots ON roots.id = r.root_id WHERE {where}) "
            "ORDER BY j.resource_id, j.position",
            parameters,
        )
        names: dict[int, list[str]] = {}
        for resource_id, name in cursor:
            names.setdefault(resource_id, []).append(name)
        return {resource_id: tuple(found) for resource_id, found in names.items()}

    # endregion
