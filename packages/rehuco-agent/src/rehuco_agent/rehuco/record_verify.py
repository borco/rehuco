"""Verify-on-access for the open catalog: a record's row checked against its file off the GUI thread, and the cache
brought in line (#487, #511, [[data-model#scan-and-staleness]])."""

import itertools
import logging
import threading
from collections.abc import Hashable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from PySide6.QtCore import QObject, QThreadPool, SignalInstance
from rehuco_core import CatalogScanner, RecordCheck, RecordsChecked, RenameCoordinator, check_records
from rehuco_core.access import Catalog, Changed, ResourceKey

from ..pool_relay import PoolRelay
from ..resource_events import ResourceEvents
from .roots_listing import ListedFolder

LOG: Final = logging.getLogger(__name__)


# what RootCatalog held for this, moved whole: the cache, the feed, the owner's signal, and the lock, serials and
# relay that keep a superseded answer out
class RecordVerify(QObject):
    """Checks records' rows against their files for the open :class:`~.root_catalog.RootCatalog`, which owns this.

    What the cache holds is read on the GUI thread, the ``stat`` and any read run on the pool, and the answer is
    written back on the GUI thread -- a share can block a ``stat`` for its whole timeout, and the cache is that
    thread's. **A newer call with the same key supersedes an older one** still out: its answer is dropped, and one not
    yet started does nothing.

    :param catalog: the cache the rows are read from and written to.
    :param coordinator: what a check holds each read under, so it never blocks a rename.
    :param events: the app's change feed, which hears of a change a check found that no event reported; ``None``
        tells nobody.
    :param rows_changed: the owner's signal, emitted with the cache row ids a write-back changed.
    :param parent: the owner.
    """

    @dataclass(frozen=True, slots=True)
    class FromFeed:
        """What a verify of files the change feed said changed is about -- the files themselves.

        Its answer is not published back on the feed, as a verify for an access or a listing is: the feed has said it.

        :param keys: the files.
        """

        keys: tuple[ResourceKey, ...]

    def __init__(
        self,
        catalog: Catalog,
        coordinator: RenameCoordinator,
        events: ResourceEvents | None,
        rows_changed: SignalInstance,
        parent: QObject,
    ) -> None:
        super().__init__(parent)
        self.__catalog: Final = catalog
        self.__rename_coordinator: Final = coordinator
        self.__events: Final = events
        self.__rows_changed: Final = rows_changed
        self.__lock: Final = threading.Lock()
        self.__verify_serials: Final = itertools.count(1)
        self.__latest_verify: Final[dict[Hashable, int]] = {}
        """The newest verify asked for per key, under :attr:`__lock`: an older one still queued does nothing, and an
        older answer is dropped."""

    def verify_records(self, paths: Iterable[Path], *, key: Hashable) -> None:
        """Check each record's row against its file and bring the cache in line, off the GUI thread (#487,
        [[data-model#scan-and-staleness]]).

        :param paths: records' absolute paths; those that are no record, or under no root, are passed over.
        :param key: what the call is about -- a listed folder, an opened record -- for superseding.
        """
        cache_path = self.__catalog.cache_path
        if cache_path is None:
            return
        keys: list[ResourceKey] = []
        for path in paths:
            try:
                keys.append(ResourceKey(path))
            except ValueError:  # a relative path is no record of any root
                continue
        checks = self.__catalog.plan_verify(keys)
        if not checks:
            return
        serial = self.__supersede(key)
        relay = PoolRelay.instance()
        QThreadPool.globalInstance().start(lambda: self.__run_verify(relay, serial, key, cache_path, checks))

    def on_listed(self, listed: ListedFolder) -> None:
        """Bring the cache in line with a folder's listing (#487, #645): verify the records it bears on, and every
        record the cache holds beneath it that the listing no longer shows a way to -- deleted or moved away, whether
        the app was running or not; walk each folder that appeared in it for records, on the pool, and verify those
        too. A newer listing of the folder supersedes all of it.

        :param listed: the listing.
        """
        if self.__catalog.cache_path is None:
            return
        paths = dict.fromkeys(listed.records)
        paths.update(dict.fromkeys(listed.unlisted(self.__catalog.records_beneath(ResourceKey(listed.folder)))))
        if not listed.appeared:
            self.verify_records(paths, key=listed.folder)
            return
        serial = self.__supersede(listed.folder)
        relay = PoolRelay.instance()
        QThreadPool.globalInstance().start(
            lambda: self.__run_walk(relay, serial, listed.folder, tuple(paths), listed.appeared)
        )

    def on_accessed(self, keys: tuple[ResourceKey, ...]) -> None:
        """Verify the records the app is opening (#487).

        :param keys: the records.
        """
        paths = tuple(key.path for key in keys)
        self.verify_records(paths, key=paths)

    def on_files_changed(self, keys: tuple[ResourceKey, ...]) -> None:
        """Check each changed file against its row on the pool, and bring the rows in line (#376, #379, #511).

        A folder deleted or replaced stands for every record the cache holds beneath it. A path that is not a record,
        or not under a root, is passed over by the planner itself.

        :param keys: the files or folders that changed.
        """
        paths = dict.fromkeys(key.path for key in keys)
        paths.update(dict.fromkeys(self.__catalog.record_paths(keys)))
        self.verify_records(paths, key=RecordVerify.FromFeed(keys))

    def __supersede(self, key: Hashable) -> int:
        """Make a new call the newest for ``key``, so an older one still out does nothing.

        :param key: what the call is about.
        :returns: the call's serial.
        """
        serial = next(self.__verify_serials)
        with self.__lock:
            self.__latest_verify[key] = serial  # pylint: disable=unsupported-assignment-operation
        return serial

    def __is_latest(self, key: Hashable, serial: int, *, release: bool = False) -> bool:
        """Whether a call is still the newest for its key.

        :param key: what the call is about.
        :param serial: the call's serial.
        :param release: whether to forget the key when it is -- the call's last step.
        :returns: whether it is.
        """
        with self.__lock:
            if self.__latest_verify.get(key) != serial:
                return False
            if release:
                del self.__latest_verify[key]  # pylint: disable=unsupported-delete-operation
        return True

    def __run_walk(
        self, relay: PoolRelay, serial: int, key: Hashable, paths: tuple[Path, ...], folders: tuple[Path, ...]
    ) -> None:
        """Walk the folders that appeared in a listing for their records, on a pool thread, and answer through
        ``relay`` with them added to ``paths``; never touches the cache.

        :param relay: the application's relay, so a catalog destroyed while the walk was out hears nothing.
        :param serial: the call's serial.
        :param key: the listed folder.
        :param paths: the records to verify already.
        :param folders: the folders to walk.
        """
        if not self.__is_latest(key, serial):
            return
        found: list[Path] = []
        for folder in folders:
            try:
                scanner = CatalogScanner(folder, coordinator=self.__rename_coordinator, include_legacy=True)
                found.extend(record for directory in scanner.walk() for record in directory.records)
            # the pool swallows what escapes: no answer would come, and the rest is still to verify
            except Exception:  # pylint: disable=broad-exception-caught
                LOG.exception("Could not walk %s for records.", folder)
        relay.post(self, self.__on_walked, serial, key, (*paths, *found))

    def __on_walked(self, serial: int, key: Hashable, paths: tuple[Path, ...]) -> None:
        """Verify what a listing and its walk found, unless a newer listing of the folder came meanwhile (GUI thread).

        :param serial: the call's serial.
        :param key: the listed folder.
        :param paths: the records.
        """
        if self.__is_latest(key, serial, release=True):
            self.verify_records(paths, key=key)

    def __run_verify(
        self, relay: PoolRelay, serial: int, key: Hashable, cache_path: Path, checks: list[RecordCheck]
    ) -> None:
        """Compare the records with the disk, on a pool thread, and answer through ``relay``; never touches the cache.

        :param relay: the application's relay, so a catalog destroyed while the check was out hears nothing.
        :param serial: the call's serial.
        :param key: what the call is about.
        :param cache_path: only handed back, to tell the answer which cache it was planned against.
        :param checks: what to compare.
        """
        if not self.__is_latest(key, serial):
            return
        try:
            checked = check_records(checks, self.__rename_coordinator)
        except Exception:  # pylint: disable=broad-exception-caught  # the pool swallows what escapes: no answer would come
            LOG.exception("Could not verify %d records against the disk.", len(checks))
            checked = RecordsChecked([], {})
        relay.post(self, self.__on_verified, serial, key, cache_path, checked)

    def __on_verified(self, serial: int, key: Hashable, cache_path: Path, checked: RecordsChecked) -> None:
        """Say what the disk showed, and write what the cache did not know into it -- unless the check was superseded,
        or the cache is not this one any more (GUI thread). The same ``.rehuco`` closed and opened again is the same
        cache, so an answer planned before the close is still written: the updater drops any finding its row moved
        past meanwhile.

        :param serial: the call's serial.
        :param key: what the call is about.
        :param cache_path: the cache the check was planned against.
        :param checked: what the disk said.
        """
        if not self.__is_latest(key, serial, release=True):
            return
        findings = checked.findings
        if cache_path != self.__catalog.cache_path or not findings:
            return
        affected, changed = self.__catalog.apply_verify(findings)
        if not changed:
            return
        self.__rows_changed.emit(affected)
        if self.__events is not None and not isinstance(key, RecordVerify.FromFeed):
            # a change no event reported, found by the catch-all: every other view hears of it the same way
            self.__events.changes.publish(Changed(tuple(ResourceKey(path) for path in changed)))
