"""One file notifier per root of the open ``.rehuco``, kept in step with its roots (#511)."""

import logging
import sqlite3
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Final
from uuid import UUID

from ..access import ChangeFeed, FileSignature
from ..rehudb import CatalogCache
from ..rename_coordination import DEFAULT_RENAME_COORDINATOR, RenameCoordinator
from .file_notifier import FileNotifier
from .watched_folder import WatchedFolder

LOG: Final = logging.getLogger(__name__)


class RootNotifiers:
    """Starts a :class:`~rehuco_core.notify.FileNotifier` for each root it is told to follow, and stops it when the root
    goes; a polled root sweeps the records its cache rows name.

    :param feed: where every notifier publishes.
    :param coordinator: the rename coordinator the sweeps answer to.
    """

    def __init__(self, feed: ChangeFeed, coordinator: RenameCoordinator = DEFAULT_RENAME_COORDINATOR) -> None:
        self.__feed: Final = feed
        self.__coordinator: Final = coordinator
        self.__notifiers: dict[UUID, FileNotifier] = {}
        self.__cache_path: Path | None = None

    @property
    def root_ids(self) -> frozenset[UUID]:
        """The roots being watched."""
        return frozenset(self.__notifiers)

    def follow(self, roots: Mapping[UUID, Path], cache_path: Path) -> None:
        """Watch exactly these roots: start what is new, stop what is gone, restart a root whose folder changed.

        :param roots: each root's folder, by its id.
        :param cache_path: the catalog cache the roots' rows are in; another one restarts every root.
        """
        if cache_path != self.__cache_path:
            self.stop()
            self.__cache_path = cache_path
        for root_id in tuple(self.__notifiers):
            if roots.get(root_id) != self.__notifiers[root_id].folder.path:
                self.__notifiers.pop(root_id).stop()
        for root_id, path in roots.items():
            if root_id not in self.__notifiers:
                notifier = FileNotifier(
                    WatchedFolder(path, root_id),
                    self.__feed,
                    RootNotifiers.known_records(cache_path, root_id, path),
                    self.__coordinator,
                )
                self.__notifiers[root_id] = notifier
                notifier.start()

    def stop(self) -> None:
        """Stop every notifier; nothing more is published."""
        for notifier in self.__notifiers.values():
            notifier.stop()
        self.__notifiers.clear()
        self.__cache_path = None

    @staticmethod
    def known_records(cache_path: Path, root_id: UUID, root: Path) -> Callable[[], dict[Path, FileSignature | None]]:
        """What a sweep of a polled root compares with the disk: every record its cache rows name, each with the
        signature it was read with -- none for a row that could not be read or whose signature a schema step cleared.

        :param cache_path: the catalog cache.
        :param root_id: the root.
        :param root: its folder.
        :returns: the reader, for a sweep's thread; it answers nothing when the cache cannot be read -- logged.
        """

        def read() -> dict[Path, FileSignature | None]:
            try:
                with CatalogCache.open(cache_path) as cache:
                    rows = cache.signatures(root_id)
            except (OSError, sqlite3.Error) as error:
                LOG.error("Could not read the cache %s to poll a root: %s", cache_path, error)
                return {}
            return {
                root.joinpath(*row.path.split("/")): (
                    (row.mtime_ns, row.size) if row.error is None and row.mtime_ns else None
                )
                for row in rows.values()
            }

        return read
