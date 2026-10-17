"""The Root Catalog on this machine, over a ``.rehudb`` (#417): its roots, a query over its rows, one row, a root's
size, and the upkeep that keeps it current between scans."""

import logging
import sqlite3
from collections.abc import Collection, Iterable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Final
from uuid import UUID

from ..rehuco_file import RehucoRoot
from ..rehudb import CatalogCache, CatalogQuery, CatalogRoot, CatalogRow
from ..rehudb_updates import CatalogRecordUpdater, RecordCheck, RecordFinding
from ..rename_coordination import DEFAULT_RENAME_COORDINATOR, RenameCoordinator
from .catalog_ops import CatalogSession, CatalogUnreadable
from .key_relocation import KeyRelocation
from .keys import ResourceKey

LOG: Final = logging.getLogger(__name__)


class Catalog:
    """The catalog read from a cache file on this machine.

    **Every call opens the cache for its own duration, on the calling thread**: a connection is one thread's
    ([[data-model#cache-schema]]), so any thread may call, and nothing is held between calls. Opening is a connect and
    a version check. What it reads -- :class:`CatalogSession` -- is swapped whole, so a call racing a swap sees the
    old session or the new one, never half of each. **The session has one writer**: :meth:`attach`, :meth:`detach`,
    :meth:`reconcile` and :meth:`hide` are read-modify-writes made from one thread -- the agent's GUI thread -- while
    the reads run anywhere.

    While nothing is attached, reads answer empty. Reads that cannot open the cache raise
    :class:`~rehuco_core.access.CatalogUnreadable`; the upkeep below logs and answers nothing, since the next scan
    rebuilds what it missed.

    :param coordinator: what a record read for the cache is held under, so it never blocks a rename
        ([[mounts-and-storage#out-of-band]]).
    """

    def __init__(self, coordinator: RenameCoordinator = DEFAULT_RENAME_COORDINATOR) -> None:
        self.__coordinator: Final = coordinator
        self.__session: CatalogSession | None = None

    # region reading the catalog

    def roots(self) -> tuple[CatalogRoot, ...]:
        """The view's roots, in the ``.rehuco``'s order.

        :returns: the roots; none while nothing is attached.
        :raises CatalogUnreadable: when the cache cannot be read.
        """
        session = self.__session
        if session is None:
            return ()
        try:
            with CatalogCache.open(session.cache_path) as cache:
                return tuple(root for root in cache.roots() if root.root_id in session.root_ids)
        except (OSError, sqlite3.Error) as error:
            raise CatalogUnreadable(f"Could not read the roots of {session.cache_path}: {error}") from error

    def query(self, query: CatalogQuery, *, ids: Collection[int] | None = None) -> list[CatalogRow]:
        """The rows ``query`` matches under the view's roots.

        :param query: a browser's query.
        :param ids: only these rows, for an update in place; every matching row when ``None``.
        :returns: the rows, in the cache's order; none while nothing is attached. A root the view dropped keeps its
            rows in the cache until its removal job has run, and they are not returned.
        :raises CatalogUnreadable: when the cache cannot be read.
        """
        session = self.__session
        if session is None:
            return []
        try:
            with CatalogCache.open(session.cache_path) as cache:
                return [row for row in cache.rows(query, ids=ids) if row.root_id in session.root_ids]
        except (OSError, sqlite3.Error) as error:
            raise CatalogUnreadable(f"Could not read the catalog {session.cache_path}: {error}") from error

    def row(self, key: ResourceKey) -> CatalogRow | None:
        """One resource's row, as an indexed lookup -- nothing is read from disk (#456, #395).

        :param key: the record, a ``.rehu`` or a legacy ``.tc``.
        :returns: its row; ``None`` for a key outside every root of the view, a record the cache has no row for yet
            (the next scan reads it), or a cache that cannot be read -- the last logged.
        """
        session = self.__session
        if session is None:
            return None
        try:
            with CatalogCache.open(session.cache_path) as cache:
                location = cache.locate(key.path)
                if location is None or location.root.root_id not in session.root_ids:
                    return None
                # the ids are the rows at or beneath the path under every root holding it: where roots nest, the
                # record has a row under each, and the one asked for is the innermost root's, which locate chose
                ids = cache.resource_ids([key.path])
                rows = cache.rows(ids=ids) if ids else []
        except (OSError, sqlite3.Error) as error:
            LOG.error("Could not read the row of %s from the cache: %s", key, error)
            return None
        return next((row for row in rows if row.root_id == location.root.root_id), None)

    def count(self, root_id: UUID) -> int:
        """How many resources the cache lists under a root -- what removing it would drop.

        :param root_id: the root.
        :returns: the count, ``.rehu`` and legacy ``.tc`` alike; ``0`` while nothing is attached or when the cache
            cannot be read -- the latter logged.
        """
        session = self.__session
        if session is None:
            return 0
        try:
            with CatalogCache.open(session.cache_path) as cache:
                return cache.resource_count(root_id)
        except (OSError, sqlite3.Error) as error:
            LOG.error("Could not count the cached entries of the root %s: %s", root_id, error)
            return 0

    # endregion

    # region the session

    @property
    def cache_path(self) -> Path | None:
        """The cache file read now, which the jobs scanning into it open themselves (#427); ``None`` while nothing is
        attached."""
        session = self.__session
        return None if session is None else session.cache_path

    @staticmethod
    def prepare(cache_path: Path, roots: Sequence[RehucoRoot]) -> CatalogSession:
        """Open a cache, bring its roots in line with a ``.rehuco``'s, and describe the session over it -- without
        attaching it, so a file that then fails to open leaves the attached one as it was.

        :param cache_path: the cache file; created when missing.
        :param roots: the ``.rehuco``'s roots, in its order.
        :returns: the session.
        :raises CatalogUnreadable: when the cache could not be opened or reconciled.
        """
        try:
            cache = CatalogCache.open(cache_path)
        except (OSError, sqlite3.Error) as error:
            raise CatalogUnreadable(f"Could not open the cache of {cache_path}: {error}") from error
        try:
            with cache:
                cache.reconcile_roots(roots)
        except sqlite3.Error as error:
            raise CatalogUnreadable(f"Could not read the cache of {cache_path}: {error}") from error
        return CatalogSession(cache_path, frozenset(root.root_id for root in roots))

    def attach(self, session: CatalogSession) -> None:
        """Read through ``session`` from now on, replacing the one attached.

        :param session: what :meth:`prepare` returned.
        """
        self.__session = session

    def detach(self) -> None:
        """Read nothing from now on. A no-op when nothing is attached."""
        self.__session = None

    def reconcile(self, roots: Sequence[RehucoRoot]) -> None:
        """Bring the cache's roots in line with the ``.rehuco``'s after an edit, and show those roots. A failure is
        logged: the next scan rebuilds the cache anyway.

        :param roots: the ``.rehuco``'s roots, in its order. A no-op while nothing is attached.
        """
        session = self.__session
        if session is None:
            return
        try:
            self.__session = self.prepare(session.cache_path, roots)
        except CatalogUnreadable as error:
            LOG.error("Could not update the cache %s: %s", session.cache_path, error.__cause__ or error)
            self.__session = replace(session, root_ids=frozenset(root.root_id for root in roots))

    def hide(self, root_id: UUID) -> None:
        """Stop listing a root at once, while the job removing its rows is still to run.

        :param root_id: the root.
        """
        session = self.__session
        if session is not None:
            self.__session = replace(session, root_ids=session.root_ids - {root_id})

    # endregion

    # region keeping the cache current between scans

    def follow(self, relocation: KeyRelocation) -> set[int]:
        """Rebase the rows a rename moved, reading no record (#376, #379).

        :param relocation: the rename's executed plan.
        :returns: the ids of the rows it may have touched -- those moving, and any stale one at a destination the
            rebase drops; empty when nothing moved.
        """
        pairs = relocation.to_local().pairs
        session = self.__session
        if session is None or not pairs:
            return set()
        try:
            with CatalogCache.open(session.cache_path) as cache:
                affected = cache.resource_ids([path for pair in pairs for path in pair])
                moved = cache.apply_relocation(pairs)
        except (OSError, sqlite3.Error) as error:
            LOG.error("Could not follow a rename in the cache %s: %s", session.cache_path, error)
            return set()
        return affected if moved else set()

    def refresh(self, keys: Iterable[ResourceKey]) -> set[int]:
        """Read each record the app wrote back into its row (#376, #379).

        A key that is no record, or is under no root, is passed over by the updater itself.

        :param keys: the files written or replaced.
        :returns: the ids of the rows it may have touched; empty when nothing changed.
        """
        paths = tuple(key.path for key in keys)
        session = self.__session
        if session is None or not paths:
            return set()
        changed = False
        affected: set[int] = set()
        try:
            with CatalogCache.open(session.cache_path) as cache:
                updater = CatalogRecordUpdater(cache, coordinator=self.__coordinator)
                # asked before, for a row the write removes; and after, for a row it adds or a converted .tc's it took
                # over
                affected = cache.resource_ids(paths)
                for path in paths:
                    changed = updater.upsert(path) or changed
                affected |= cache.resource_ids(paths)
        except (OSError, sqlite3.Error) as error:
            LOG.error("Could not update the cache %s: %s", session.cache_path, error)
        return affected if changed else set()

    def plan_verify(self, keys: Iterable[ResourceKey]) -> list[RecordCheck]:
        """What verify-on-access is to compare with the disk, read from the cache alone (#487).

        :param keys: the records; any that is no record or is under no root is passed over.
        :returns: one check per record; none when the cache cannot be read -- logged.
        """
        paths = [key.path for key in keys]
        session = self.__session
        if session is None or not paths:
            return []
        try:
            with CatalogCache.open(session.cache_path) as cache:
                return CatalogRecordUpdater(cache, coordinator=self.__coordinator).plan(paths)
        except (OSError, sqlite3.Error) as error:
            LOG.error("Could not read the cache %s to verify records: %s", session.cache_path, error)
            return []

    def apply_verify(self, findings: Sequence[RecordFinding]) -> tuple[set[int], set[Path]]:
        """Write what the disk showed into the cache.

        :param findings: what :func:`~rehuco_core.check_records` found for the checks :meth:`plan_verify` planned.
        :returns: the ids of the rows it may have touched and the paths whose rows changed; empty when the cache
            cannot be written -- logged.
        """
        session = self.__session
        if session is None or not findings:
            return set(), set()
        paths = [finding.check.path for finding in findings]
        try:
            with CatalogCache.open(session.cache_path) as cache:
                affected = cache.resource_ids(paths)
                changed = CatalogRecordUpdater(cache, coordinator=self.__coordinator).apply(findings)
                affected |= cache.resource_ids(paths)
        except (OSError, sqlite3.Error) as error:
            LOG.error("Could not update the cache %s: %s", session.cache_path, error)
            return set(), set()
        return affected, changed

    # endregion
