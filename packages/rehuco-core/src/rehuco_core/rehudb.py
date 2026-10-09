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
one that would not list keeps its rows as they were (:meth:`CatalogCache.mark_root_unreachable`), while a scan of
one that did replaces them (:meth:`CatalogCache.apply_root_scan`) -- a record no longer there is gone.

**Between scans, one record at a time** (#373): a record re-read after a save is written alone
(:meth:`CatalogCache.upsert_record`), a deleted one removed (:meth:`CatalogCache.remove`), and a rename applied
from its executed plan without reading anything (:meth:`CatalogCache.apply_relocation`).

Every value a query matches against is a parameter; the SQL around it is assembled only from the fixed
fragments below, never from text a reader typed.
"""

# one class over one file: every read and write here keeps the same invariants -- roots by id, a row per record, the
# value tables pruned -- and splitting it would separate rules that only make sense read against each other
# pylint: disable=too-many-lines

import json
import logging
import os
import sqlite3
import time
from collections.abc import Collection, Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import TracebackType
from typing import Final, Self
from uuid import UUID

from borco_core import fold

from .constants import REHUDB_SUFFIX
from .migrations.rehudb import BASE_VERSION, CHAIN, FOLD_STAMP_VERSION, SchemaChain
from .migrations.runner import chain_head
from .plugins import DEFAULT_PLUGIN_REGISTRY, PluginRegistry
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
    """What a scan read from one record: the common core a browser shows, its type's own fields, and how to tell
    it changed.

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
    :param advertised_duration: the claimed running time in seconds, or ``None``; type-specific, like the five below
        -- filled only where the record's type declares the field (:func:`catalog_type_fields`).
    :param original_duration: the complete download's measured running time in seconds, or ``None``.
    :param current_duration: the running time still on disk in seconds, or ``None``.
    :param level: the chosen levels, in order.
    :param advertised_count: the pack's own claim of how many images it holds, as text (``500+``), or ``None``.
    :param current_count: the measured content-image count, or ``None``.
    :param format_version: the file's own ``format_version`` as it is on disk (``0`` for an unstamped ``.rehu``), or
        ``None``: always for a legacy ``.tc``, which has no version of its own, and for a ``.rehu`` that could not be
        read (#379).
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
    advertised_duration: int | None = None
    original_duration: int | None = None
    current_duration: int | None = None
    level: tuple[str, ...] = ()
    advertised_count: str | None = None
    current_count: int | None = None
    format_version: int | None = None
    mtime_ns: int = 0
    size: int = 0
    content_hash: str = ""
    error: str | None = None


@dataclass(frozen=True, slots=True)
class RecordSignature:
    """What an incremental scan needs of a cached row to decide whether to read its record again
    ([[data-model#scan-and-staleness]], #373).

    :param path: root-relative, as last spelled.
    :param mtime_ns: the record file's modification time at last read; ``0`` once a schema step cleared it.
    :param size: the record file's size at last read.
    :param error: why it could not be read last time, or ``None``.
    """

    path: str
    mtime_ns: int
    size: int
    error: str | None = None

    def matches(self, mtime_ns: int, size: int) -> bool:
        """Whether the file as it is now still is what this row was read from.

        Never for a row that could not be read, which is asked again in case it now can be, nor for one whose
        signature a schema step cleared (``0``), which is the marker that its columns are stale.

        :param mtime_ns: the file's modification time now.
        :param size: the file's size now.
        :returns: whether the row can be trusted without a read.
        """
        return self.error is None and self.mtime_ns != 0 and (self.mtime_ns, self.size) == (mtime_ns, size)


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
class CatalogLocation:
    """Where a path sits in the cache: the root it is under and its root-relative spelling.

    :param root: the root -- the innermost one, where roots nest.
    :param relative: the path relative to it, ``/``-separated, spelled as the path spells it.
    """

    root: CatalogRoot
    relative: str


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
    """Which rows to read: free-text terms over title and path, and field tokens, all of which must match.

    The structure a filter line parses into (#398); parsing ``field:"value"`` and splitting the free text into terms
    is the line's business, so this takes them already split.

    :param terms: each matched anywhere in a title or a root-relative path, either one, ignoring case and diacritics
        (:func:`borco_core.fold`, #475); none matches all.
    :param tokens: ``(field, value)`` pairs. ``folder`` is a ``<label>/<relative path>`` prefix; ``authors``,
        ``tags`` and ``publishers`` match one value whole, ignoring case and diacritics; ``type`` matches the type.
    """

    terms: tuple[str, ...] = ()
    tokens: tuple[tuple[CatalogField, str], ...] = ()


JOINS: Final = (
    ("authors", "resource_authors"),
    ("tags", "resource_tags"),
    ("publishers", "resource_publishers"),
)
"""Each value table and its join table -- the only names ever formatted into a statement."""

TOKEN_CLAUSES: Final = {
    CatalogField.TYPE: "r.type = ? COLLATE NOCASE",
    **{
        # driven from the value's folded-name index and the join's value index, not probed once per resource (#454)
        CatalogField(table): (
            f"r.id IN (SELECT j.resource_id FROM {join} j JOIN {table} v ON v.id = j.value_id "  # nosec  # B608: fixed
            "WHERE v.folded = ?)"
        )
        for table, join in JOINS
    },
}
"""The clause each token field adds but ``folder``, each with exactly one parameter -- folded for a value table's."""

FOLD_PROBE: Final = "\u0130 \u00df \ufb01 \u210c e\u0301 \u00c5 \u01c4 \u03a3\u03c2 \u1e9e \uff05 \u00e9 \u0141"
"""Text that exercises every step of :func:`borco_core.fold`: letters casefolding turns into two (``İ``, ``ß``), a
ligature, a letter NFKD turns into a capital, a decomposed and a precomposed accent, a digraph, final sigma, a fullwidth
sign and a letter with a stroke that fold cannot decompose. What it folds to is the fingerprint of ``fold`` the cache
keeps (``cache_meta``): a rule that changes shows in at least one of them."""

FOLD_STAMP_KEY: Final = "fold"
"""The ``cache_meta`` key the fingerprint lives under."""

TERM_CLAUSE: Final = "(r.folded_title LIKE ? ESCAPE '\\' OR r.folded_path LIKE ? ESCAPE '\\')"
"""What one free-text term adds: found in the folded title or the folded path (schema v5, #475), both parameters the
same pattern -- a stored column each, since folding every row through a Python SQL function per read measured 10-30x
slower."""

FOLDER_ROOT_CLAUSE: Final = "r.root_id IN (SELECT id FROM roots WHERE label = ? COLLATE NOCASE)"
"""A root by its label, folded as ASCII only, as the label's uniqueness is.

Phrased on ``r.root_id`` rather than ``roots.label`` on purpose: a ``folder`` token ORs one of these per way of
splitting its value, and SQLite drives an OR through the ``(root_id, path_key)`` index only when every term is a
condition on ``r``'s own indexed columns -- a term on the joined ``roots`` row makes the whole query a scan."""

FOLDER_SUBTREE_CLAUSE: Final = f"({FOLDER_ROOT_CLAUSE} AND r.path_key >= ? AND r.path_key < ?)"
"""A folder beneath a root, by key range -- three parameters: the root's label, then the bounds of the keys under the
folder's ``/``-terminated prefix. The path part folds as the filesystem does (:func:`catalog_path_key`)."""

TYPE_FIELD_COLUMNS: Final = (
    "advertised_duration",
    "original_duration",
    "current_duration",
    "level",
    "advertised_count",
    "current_count",
)
"""The type-specific fields the cache stores, one column each (schema v3, #399): a tutorial's durations and level,
a reference pack's image counts. A scan fills one only where the record's type declares it."""

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
    *TYPE_FIELD_COLUMNS,
    "format_version",
    "mtime_ns",
    "size",
    "content_hash",
    "error",
)
"""The ``resources`` columns a :class:`CatalogRecord` fills -- each one of its fields, under the same name, and
stored as it is but for ``level``, which a column holds as a JSON array (:meth:`CatalogCache.rows`)."""

SELECTED_COLUMNS: Final = ", ".join(f"r.{column}" for column in RESOURCE_COLUMNS)
"""The ``resources r`` columns a row is read with, in :data:`RESOURCE_COLUMNS` order."""

KEY_RANGE_END: Final = "\U0010ffff"
"""Appended to a key prefix to bound the range of keys that start with it: the highest code point, whose UTF-8
sorts after every other character's, so ``prefix <= key < prefix + KEY_RANGE_END`` is an indexed prefix match --
where ``LIKE`` would need its wildcards escaped and ``substr`` would read every row of the root."""

SUBTREE_CLAUSE: Final = "(path_key = ? OR (path_key >= ? AND path_key < ?))"
"""A path and everything beneath it, by key -- three parameters: the path's own key, then the bounds of the keys
under its ``/``-terminated prefix."""


def catalog_type_fields(type_name: str, plugins: PluginRegistry = DEFAULT_PLUGIN_REGISTRY) -> tuple[str, ...]:
    """The type-specific columns a resource type contributes to a browser: those of :data:`TYPE_FIELD_COLUMNS`
    its plugin declares (:meth:`~rehuco_core.PluginRegistry.field_names`), in the cache's order.

    The cache says which fields it stores and the plugin which fields its type has; a column belongs to a type
    where the two meet. Their labels are the agent's to say, as every field's are.

    :param type_name: a type's main key or alias, as spelled on disk.
    :param plugins: the plugins installed here.
    :returns: the column names; ``()`` for a type that declares none, or whose plugin is not installed.
    """
    declared = plugins.field_names(type_name)
    return tuple(column for column in TYPE_FIELD_COLUMNS if column in declared)


def catalog_path_key(path: str) -> str:
    """The normalized spelling a root-relative path is matched by (``path_key``, [[data-model#cache-schema]]):
    case folded and separators unified exactly where this filesystem does, through :func:`os.path.normcase`.

    :param path: root-relative, ``/``-separated.
    :returns: its key.
    """
    return os.path.normcase(path)


def rehudb_path(cache_dir: Path, rehuco_id: UUID) -> Path:
    """Where a ``.rehuco``'s cache lives -- named by its rehuco id, so it follows the file wherever it moves.

    :param cache_dir: the local cache folder the app chose; never a share.
    :param rehuco_id: the ``.rehuco``'s :attr:`~rehuco_core.RehucoFile.rehuco_id`.
    :returns: the cache file's path.
    """
    return cache_dir / f"{rehuco_id}{REHUDB_SUFFIX}"


class CatalogCache:  # pylint: disable=too-many-public-methods
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
            if cls.__user_version(connection) >= FOLD_STAMP_VERSION:
                cls.__refold_if_stale(connection)
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
        self,
        root_id: UUID,
        records: Sequence[CatalogRecord],
        *,
        unchanged: Sequence[str] = (),
        scanned_at: float | None = None,
    ) -> bool:
        """Replace a root's resources with what a scan of it found, in one transaction -- mark and sweep.

        A record found again keeps its row id, so a view holding it keeps its place; a record not found is
        removed -- the root listed, so its absence is real.

        :param root_id: the root scanned.
        :param records: every record the scan read.
        :param unchanged: the root-relative paths, as spelled now, of the records an incremental scan found
            unchanged and did not read (#373): each keeps its row as it is -- its ``scanned_at`` included, which says
            when it was last *read* -- but for its spelling, which follows a case-only rename.
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
            for path in unchanged:
                row = connection.execute(
                    "UPDATE resources SET path = ?, folded_path = ? WHERE root_id = ? AND path_key = ? RETURNING id",
                    (path, fold(path), key, catalog_path_key(path)),
                ).fetchone()
                if row is not None:
                    kept.add(row[0])
            existing = {
                resource_id
                for (resource_id,) in connection.execute("SELECT id FROM resources WHERE root_id = ?", (key,))
            }
            connection.executemany("DELETE FROM resources WHERE id = ?", [(gone,) for gone in existing - kept])
            connection.execute("UPDATE roots SET reachable = 1, scanned_at = ? WHERE id = ?", (stamp, key))
            self.__prune_values(connection)
        return True

    def signatures(self, root_id: UUID) -> dict[str, RecordSignature]:
        """Every row under a root, as much of it as an incremental scan compares against (#373).

        :param root_id: the root.
        :returns: the signatures, keyed by path key (:func:`catalog_path_key`); as many as the last scan found,
            which is the total the next one reports progress against.
        """
        cursor = self.__connection.execute(
            "SELECT path_key, path, mtime_ns, size, error FROM resources WHERE root_id = ?", (str(root_id),)
        )
        return {key: RecordSignature(*fields) for key, *fields in cursor}

    def resource_count(self, root_id: UUID) -> int:
        """How many rows a root holds -- what removing it would drop (#378).

        :param root_id: the root.
        :returns: its cached resources, ``.rehu`` and legacy ``.tc`` alike.
        """
        sql = "SELECT COUNT(*) FROM resources WHERE root_id = ?"
        return self.__connection.execute(sql, (str(root_id),)).fetchone()[0]

    def resource_type(self, root_id: UUID, relative: str) -> str | None:
        """The type a cached record says its resource is, for the Roots view to tell a reference pack (#456).

        An indexed lookup on ``(root_id, path_key)`` -- no record is read from disk, so a record the cache has not
        scanned yet answers ``None`` until the next scan.

        :param root_id: the root.
        :param relative: the record's root-relative path.
        :returns: the type as the record spells it (an alias included, ``""`` for a typeless record), or ``None``
            when no row holds that path.
        """
        row = self.__connection.execute(
            "SELECT type FROM resources WHERE root_id = ? AND path_key = ?", (str(root_id), catalog_path_key(relative))
        ).fetchone()
        return None if row is None else row[0]

    def resource_uuid(self, root_id: UUID, relative: str) -> str | None:
        """The id a cached record carries, for the Roots view to name an image copied out of its resource (#395).

        An indexed lookup like :meth:`resource_type`: nothing is read from disk.

        :param root_id: the root.
        :param relative: the record's root-relative path.
        :returns: the id, ``""`` for a legacy record (which has none until converted), or ``None`` when no row holds
            that path.
        """
        row = self.__connection.execute(
            "SELECT uuid FROM resources WHERE root_id = ? AND path_key = ?", (str(root_id), catalog_path_key(relative))
        ).fetchone()
        return None if row is None else row[0]

    def signature(self, root_id: UUID, relative: str) -> RecordSignature | None:
        """One row's signature, for verify-on-access ([[data-model#scan-and-staleness]]).

        :param root_id: the root.
        :param relative: the record's root-relative path.
        :returns: the signature, or ``None`` when no row holds that path.
        """
        row = self.__connection.execute(
            "SELECT path, mtime_ns, size, error FROM resources WHERE root_id = ? AND path_key = ?",
            (str(root_id), catalog_path_key(relative)),
        ).fetchone()
        return RecordSignature(*row) if row is not None else None

    def locate(self, path: Path) -> CatalogLocation | None:
        """Which root ``path`` is under, and where beneath it.

        Compared component by component, each one normalized as the filesystem would
        (:func:`os.path.normcase`), so a root ``D:/lib`` holds ``d:/LIB/x.rehu`` on Windows and never
        ``D:/lib2/x.rehu`` anywhere. Where roots nest, the innermost one answers.

        :param path: an absolute path.
        :returns: the location, its relative part spelled as ``path`` spells it; ``None`` outside every root, and
            for a root's own folder, which is no record.
        """
        parts = self.__normalized_parts(path)
        holding = (
            root
            for root in self.roots()
            if len(parts) > len(root.path.parts) and parts[: len(root.path.parts)] == self.__normalized_parts(root.path)
        )
        best = max(holding, key=lambda root: len(root.path.parts), default=None)
        if best is None:
            return None
        return CatalogLocation(best, "/".join(path.parts[len(best.path.parts) :]))

    def upsert_record(self, root_id: UUID, record: CatalogRecord, *, scanned_at: float | None = None) -> bool:
        """Write one record read outside a scan -- after a save or a conversion (#373).

        A ``.rehu`` written where a same-stem ``.tc`` had a row takes that row over, keeping its id: converting a
        record replaces its row in place ([[data-model#cache-schema]]).

        :param root_id: the root it is under.
        :param record: what it holds, its path root-relative.
        :param scanned_at: when it was read; now, when omitted.
        :returns: whether it was written -- ``False`` when the root is not in the cache.
        """
        stamp = time.time() if scanned_at is None else scanned_at
        key = str(root_id)
        with self.__transaction() as connection:
            if connection.execute("SELECT 1 FROM roots WHERE id = ?", (key,)).fetchone() is None:
                return False
            self.__upsert(connection, key, record, stamp)
            self.__prune_values(connection)
        return True

    def remove(self, path: Path) -> bool:
        """Delete the row of a record that is gone (#373).

        :param path: the record's absolute path.
        :returns: whether a row was deleted.
        """
        location = self.locate(path)
        if location is None:
            return False
        with self.__transaction() as connection:
            removed = connection.execute(
                "DELETE FROM resources WHERE root_id = ? AND path_key = ?",
                (str(location.root.root_id), catalog_path_key(location.relative)),
            ).rowcount
            if removed:
                self.__prune_values(connection)
        return bool(removed)

    def apply_relocation(self, pairs: Sequence[tuple[Path, Path]]) -> int:
        """Apply a rename that ran, without reading a record (#373).

        ``pairs`` is the rename's executed plan (:attr:`~rehuco_core.RehuRenamer.executed`), and the one rule
        applied is the renamer's own (:meth:`~rehuco_core.RehuRenamer.relocate`): **a path at or beneath a renamed
        source lands at the same offset beneath its destination**. A directory-scoped rename's one pair is the
        directory, so every record beneath it is rebased; a file-scoped one's pairs are files, so only its own
        record's row matches and its siblings, which have no rows, change nothing. Each row keeps its own spelling
        of the part that did not move.

        A row already at a destination is stale -- the rename found nothing there -- and is dropped first. A
        source at or above a root's own folder moves the root rather than anything in it: its rows' relative
        paths stay right, and where the root now is is the ``.rehuco``'s to say.

        :param pairs: ``(source, destination)`` absolute paths, as the rename ran them.
        :returns: how many rows were rebased.
        """
        roots = self.roots()
        moved = 0
        with self.__transaction() as connection:
            for source, destination in pairs:
                for root in roots:
                    relative = self.__relative_pair(root, source, destination)
                    if relative is not None:
                        moved += self.__rebase(connection, str(root.root_id), *relative)
            if moved:
                self.__prune_values(connection)
        return moved

    def resource_ids(self, paths: Sequence[Path]) -> set[int]:
        """The rows at or beneath each of ``paths`` -- what a rename or a write may have changed, asked before and
        after it so a browser can update just those rows in place (#379).

        :param paths: absolute paths, of records or of folders; one under no root adds nothing.
        :returns: the rows' ids.
        """
        roots = self.roots()
        ids: set[int] = set()
        for path in paths:
            parts = self.__normalized_parts(path)
            for root in roots:
                depth = len(root.path.parts)
                if len(parts) <= depth or parts[:depth] != self.__normalized_parts(root.path):
                    continue
                relative = "/".join(path.parts[depth:])
                cursor = self.__connection.execute(
                    f"SELECT id FROM resources WHERE root_id = ? AND {SUBTREE_CLAUSE}",  # nosec  # B608: fixed
                    (str(root.root_id), *self.__subtree_keys(relative)),
                )
                ids.update(resource_id for (resource_id,) in cursor)
        return ids

    def rows(self, query: CatalogQuery | None = None, *, ids: Collection[int] | None = None) -> list[CatalogRow]:
        """The resources matching ``query``, in root order and then by path.

        :param query: what to match; ``None`` reads every row.
        :param ids: when given, only these rows are read -- the few a rename or a write touched (#379); each is one
            parameter, so the set is meant to be small.
        :returns: the rows.
        """
        where, parameters = self.__where(query if query is not None else CatalogQuery(), ids)
        values = {table: self.__values(table, join, where, parameters) for table, join in JOINS}
        cursor = self.__connection.execute(
            f"SELECT r.id, r.root_id, roots.label, r.scanned_at, {SELECTED_COLUMNS} "  # nosec  # B608: fixed names
            f"FROM resources r JOIN roots ON roots.id = r.root_id WHERE {where} ORDER BY roots.position, r.path_key",
            parameters,
        )
        rows: list[CatalogRow] = []
        for resource_id, root_id, root_label, scanned_at, *fields in cursor:
            columns_read = dict(zip(RESOURCE_COLUMNS, fields, strict=True))
            columns_read["kind"] = RecordKind(columns_read["kind"])
            columns_read["level"] = self.__level_read(columns_read["level"])
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

    @staticmethod
    def __fold_is_current(connection: sqlite3.Connection) -> bool:
        """Whether the fingerprint the file keeps is what :data:`FOLD_PROBE` folds to now."""
        stored = connection.execute("SELECT value FROM cache_meta WHERE key = ?", (FOLD_STAMP_KEY,)).fetchone()
        return stored is not None and stored[0] == fold(FOLD_PROBE)

    @classmethod
    def __refold_if_stale(cls, connection: sqlite3.Connection) -> None:
        """Write the folded columns again from the real ones when the ``fold`` that wrote them is not this one (#475).

        The file keeps what :data:`FOLD_PROBE` folded to when it last wrote them; a different answer now -- an edit to
        ``fold``, or a Python whose Unicode tables moved -- or none at all (a file just upgraded, whose columns are
        empty) means they cannot be trusted, and a search would silently miss rows. The check is a single read; the
        refill is one transaction of about a second per 100k resources, and no scan.

        :param connection: the cache, at a version with ``cache_meta``.
        """
        if cls.__fold_is_current(connection):
            return
        with cls.__write(connection):
            # another process may have refilled while this one waited for the write lock
            if cls.__fold_is_current(connection):
                return
            resources = connection.execute("SELECT id, title, path FROM resources").fetchall()
            connection.executemany(
                "UPDATE resources SET folded_title = ?, folded_path = ? WHERE id = ?",
                [(fold(title), fold(path), resource_id) for resource_id, title, path in resources],
            )
            for table, _ in JOINS:
                names = connection.execute(f"SELECT id, name FROM {table}").fetchall()  # nosec  # B608: fixed names
                connection.executemany(
                    f"UPDATE {table} SET folded = ? WHERE id = ?",  # nosec  # B608: fixed names
                    [(fold(name), value_id) for value_id, name in names],
                )
            connection.execute(
                "INSERT INTO cache_meta (key, value) VALUES (?, ?) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (FOLD_STAMP_KEY, fold(FOLD_PROBE)),
            )
        LOG.info("Wrote the catalog cache's folded search columns again: another fold wrote them.")

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
        fields = tuple(CatalogCache.__stored(record, column) for column in RESOURCE_COLUMNS)
        key = catalog_path_key(record.path)
        CatalogCache.__adopt_legacy_row(connection, root_id, record, key)
        (resource_id,) = connection.execute(
            "INSERT INTO resources (root_id, path_key, scanned_at, folded_title, folded_path, "
            f"{names}) "  # nosec  # B608: fixed names
            f"VALUES (?, ?, ?, ?, ?, {', '.join('?' * len(RESOURCE_COLUMNS))}) "
            "ON CONFLICT (root_id, path_key) DO UPDATE SET scanned_at = excluded.scanned_at, "
            f"folded_title = excluded.folded_title, folded_path = excluded.folded_path, {updates} RETURNING id",
            (root_id, key, stamp, fold(record.title), fold(record.path), *fields),
        ).fetchone()
        for (table, join), names_of in zip(JOINS, (record.authors, record.tags, record.publishers), strict=True):
            CatalogCache.__write_values(connection, table, join, resource_id, names_of)
        return resource_id

    @staticmethod
    def __adopt_legacy_row(connection: sqlite3.Connection, root_id: str, record: CatalogRecord, key: str) -> None:
        """Re-key the row of the ``.tc`` a new ``.rehu`` record converts, so the write that follows lands on it.

        Only for a ``.rehu`` with no row of its own yet, and only a ``.tc`` the scanner would count as covered by
        it: same directory, stem equal case-folded ([[data-model#cache-schema]]). Coverage stops at the directory,
        so a ``.tc`` deeper down is found by the range but never taken.

        :param connection: the cache, inside a write transaction.
        :param root_id: the root.
        :param record: the record about to be written.
        :param key: its path key.
        """
        if record.kind is not RecordKind.REHU:
            return
        if connection.execute("SELECT 1 FROM resources WHERE root_id = ? AND path_key = ?", (root_id, key)).fetchone():
            return
        parent, _, name = record.path.rpartition("/")
        prefix = catalog_path_key(f"{parent}/") if parent else ""
        stem = os.path.splitext(name)[0].casefold()
        candidates = connection.execute(
            "SELECT id, path FROM resources WHERE root_id = ? AND kind = ? AND path_key >= ? AND path_key < ?",
            (root_id, RecordKind.TC.value, prefix, prefix + KEY_RANGE_END),
        )
        for resource_id, path in candidates.fetchall():
            row_parent, _, row_name = path.rpartition("/")
            if catalog_path_key(row_parent) == catalog_path_key(parent) and (
                os.path.splitext(row_name)[0].casefold() == stem
            ):
                connection.execute(
                    "UPDATE resources SET path = ?, path_key = ?, folded_path = ? WHERE id = ?",
                    (record.path, key, fold(record.path), resource_id),
                )
                return

    @staticmethod
    def __normalized_parts(path: Path) -> tuple[str, ...]:
        """``path``'s components, each normalized as this filesystem normalizes a name -- so a prefix test cannot
        mistake ``lib2`` for something inside ``lib``."""
        return tuple(os.path.normcase(part) for part in path.parts)

    @staticmethod
    def __relative_pair(root: CatalogRoot, source: Path, destination: Path) -> tuple[str, str] | None:
        """One renamed pair, made relative to ``root`` -- or ``None`` when the rename did not move anything inside
        it.

        :returns: the source's and the destination's root-relative paths, each spelled as the pair spells it.
        """
        root_parts = CatalogCache.__normalized_parts(root.path)
        source_parts = CatalogCache.__normalized_parts(source)
        depth = len(root_parts)
        if source_parts[:depth] != root_parts or len(source_parts) == depth:
            if root_parts[: len(source_parts)] == source_parts:
                LOG.info("A rename moved the root %s itself; its rows are kept as they are.", root.path)
            return None
        # a rename's pairs stay inside one directory, so a source beneath the root has its destination there too
        return "/".join(source.parts[depth:]), "/".join(destination.parts[depth:])

    @staticmethod
    def __subtree_keys(path: str) -> tuple[str, str, str]:
        """The three parameters :data:`SUBTREE_CLAUSE` takes for ``path``: its own key and the range of the keys
        beneath it."""
        prefix = catalog_path_key(f"{path}/")
        return catalog_path_key(path), prefix, prefix + KEY_RANGE_END

    @staticmethod
    def __rebase(connection: sqlite3.Connection, root_id: str, source: str, destination: str) -> int:
        """Rewrite every row at or beneath ``source`` to the same offset beneath ``destination``.

        :param connection: the cache, inside a write transaction.
        :param root_id: the root.
        :param source: root-relative, as the rename spelled it.
        :param destination: root-relative, as the rename spelled it.
        :returns: how many rows moved.
        """
        subtree = f"SELECT id, path FROM resources WHERE root_id = ? AND {SUBTREE_CLAUSE}"  # nosec  # B608: fixed
        moving = connection.execute(subtree, (root_id, *CatalogCache.__subtree_keys(source))).fetchall()
        if not moving:
            return 0
        moving_ids = {resource_id for resource_id, _ in moving}
        # a case-only rename on a case-insensitive filesystem has the same keys at both ends: those rows are moving
        stale = connection.execute(subtree, (root_id, *CatalogCache.__subtree_keys(destination))).fetchall()
        connection.executemany(
            "DELETE FROM resources WHERE id = ?", [(gone,) for gone, _ in stale if gone not in moving_ids]
        )
        depth = len(source.split("/"))
        for resource_id, path in moving:
            rebased = "/".join((destination, *path.split("/")[depth:]))
            connection.execute(
                "UPDATE resources SET path = ?, path_key = ?, folded_path = ? WHERE id = ?",
                (rebased, catalog_path_key(rebased), fold(rebased), resource_id),
            )
        return len(moving)

    @staticmethod
    def __stored(record: CatalogRecord, column: str) -> object:
        """What one of a record's columns holds: its field as it is, but ``level`` as a JSON array, or ``NULL``
        when it names none -- the inverse of :meth:`__level_read`."""
        value = getattr(record, column)
        if column != "level":
            return value
        return json.dumps(list(value)) if value else None

    @staticmethod
    def __level_read(stored: str | None) -> tuple[str, ...]:
        """The levels a ``level`` column holds, in order -- the inverse of :meth:`__stored`."""
        return tuple(json.loads(stored)) if stored else ()

    @staticmethod
    def __write_values(
        connection: sqlite3.Connection, table: str, join: str, resource_id: int, names: tuple[str, ...]
    ) -> None:
        """Replace one resource's names in one value table, adding any name not there yet.

        :param table: the value table.
        :param join: its join table.
        :param resource_id: the resource.
        :param names: its names, in order; an empty one is skipped, a repeat (case-insensitively) kept once. Each is
            stored on the join exactly as spelled, since the value row it shares with other resources keeps only the
            first spelling ever written.
        """
        insert_value = f"INSERT INTO {table} (name, folded) VALUES (?, ?) ON CONFLICT DO NOTHING"  # nosec  # B608
        select_value = f"SELECT id FROM {table} WHERE name = ?"  # nosec  # B608: fixed names
        connection.execute(f"DELETE FROM {join} WHERE resource_id = ?", (resource_id,))  # nosec  # B608: fixed names
        for position, name in enumerate(name for name in names if name):
            connection.execute(insert_value, (name, fold(name)))
            (value_id,) = connection.execute(select_value, (name,)).fetchone()
            connection.execute(
                f"INSERT OR IGNORE INTO {join} (resource_id, value_id, position, name) VALUES (?, ?, ?, ?)",
                (resource_id, value_id, position, name),
            )

    @staticmethod
    def __prune_values(connection: sqlite3.Connection) -> None:
        """Drop every author, tag and publisher no resource names any more."""
        for table, join in JOINS:
            orphans = f"DELETE FROM {table} WHERE id NOT IN (SELECT value_id FROM {join})"  # nosec  # B608: fixed names
            connection.execute(orphans)

    @staticmethod
    def __where(query: CatalogQuery, ids: Collection[int] | None = None) -> tuple[str, tuple[object, ...]]:
        """The ``WHERE`` condition a query reads as, over ``resources r`` joined to ``roots``.

        :param query: what to match.
        :param ids: the only rows to read, when given.
        :returns: the condition and its parameters, one per placeholder.
        """
        clauses = ["1"]
        parameters: list[object] = []
        if ids is not None:
            clauses.append(f"r.id IN ({', '.join('?' * len(ids))})")
            parameters += ids
        for term in query.terms:
            # escaped after folding, since a compatibility form can fold into a wildcard (``％`` to ``%``)
            pattern = f"%{CatalogCache.__escaped(fold(term))}%"
            clauses.append(TERM_CLAUSE)
            parameters += [pattern, pattern]
        for field, value in query.tokens:
            if field is CatalogField.FOLDER:
                clause, folder_parameters = CatalogCache.__folder_clause(value)
                clauses.append(clause)
                parameters += folder_parameters
            else:
                clauses.append(TOKEN_CLAUSES[field])
                parameters.append(value if field is CatalogField.TYPE else fold(value))
        return " AND ".join(clauses), tuple(parameters)

    @staticmethod
    def __folder_clause(value: str) -> tuple[str, tuple[str, ...]]:
        """The condition a ``folder`` token reads as: every row beneath ``<root label>/<relative path>``.

        A label may hold a ``/``, so every split of ``value`` into a label and a path is tried, each an indexed range.
        The label matches as ASCII folds it; the path as the filesystem does, the way Roots navigates by it.

        :param value: the token's value, ``/``-separated.
        :returns: the condition and its parameters.
        """
        parts = value.strip("/").split("/")
        alternatives: list[str] = []
        parameters: list[str] = []
        for split in range(1, len(parts) + 1):
            label, relative = "/".join(parts[:split]), "/".join(parts[split:])
            if not relative:
                alternatives.append(FOLDER_ROOT_CLAUSE)
                parameters.append(label)
                continue
            prefix = catalog_path_key(f"{relative}/")
            alternatives.append(FOLDER_SUBTREE_CLAUSE)
            parameters += [label, prefix, prefix + KEY_RANGE_END]
        return f"({' OR '.join(alternatives)})", tuple(parameters)

    @staticmethod
    def __escaped(text: str) -> str:
        """``text`` with ``LIKE``'s wildcards and its escape character taken literally."""
        return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def __values(self, table: str, join: str, where: str, parameters: Sequence[object]) -> dict[int, tuple[str, ...]]:
        """One value table's names for every matching resource, in each resource's own order and spelling -- the
        join's own, falling back to the shared one for a row written before the join kept a spelling.

        :returns: the names, keyed by resource id.
        """
        cursor = self.__connection.execute(
            "SELECT j.resource_id, COALESCE(j.name, v.name) "
            f"FROM {join} j JOIN {table} v ON v.id = j.value_id "  # nosec  # B608: fixed names
            f"WHERE j.resource_id IN (SELECT r.id FROM resources r JOIN roots ON roots.id = r.root_id WHERE {where}) "
            "ORDER BY j.resource_id, j.position",
            parameters,
        )
        names: dict[int, list[str]] = {}
        for resource_id, name in cursor:
            names.setdefault(resource_id, []).append(name)
        return {resource_id: tuple(found) for resource_id, found in names.items()}

    # endregion
