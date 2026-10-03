"""The catalog cache kept current one record at a time, between scans ([[data-model#scan-and-staleness]], #373).

A save or a conversion re-reads its record (:meth:`CatalogRecordUpdater.upsert`); opening, browsing to or serving a
resource checks its row against the file and re-reads it when they disagree (:meth:`CatalogRecordUpdater.verify`).
A rename needs no read at all and is :meth:`~rehuco_core.CatalogCache.apply_relocation`'s; a deletion is
:meth:`~rehuco_core.CatalogCache.remove`'s.

**A root is wholly online or wholly offline** ([[mounts-and-storage#offline-mounts]]), here as in a scan: a record
that is missing under a root that is there is gone, and its row with it; under a root that is not, nothing changes.

**The cache belongs to the thread that opened it** (:class:`~rehuco_core.CatalogCache`), so an updater is used on
that thread; each read is one chunk under the rename coordinator's hold, as a scan's is.
"""

import logging
from dataclasses import replace
from pathlib import Path
from typing import Final

from .rehudb import CatalogCache, CatalogLocation
from .rehudb_scan import CatalogRecordReader
from .rename_coordination import DEFAULT_RENAME_COORDINATOR, RenameCoordinator
from .resource_scoping import is_record_name

LOG: Final = logging.getLogger(__name__)


class CatalogRecordUpdater:
    """Re-reads one record into the cache, or checks whether it needs to (#373).

    :param cache: the open cache, on this thread.
    :param coordinator: the rename barrier every read goes through.
    """

    def __init__(self, cache: CatalogCache, *, coordinator: RenameCoordinator = DEFAULT_RENAME_COORDINATOR) -> None:
        self.__cache: Final = cache
        self.__coordinator: Final = coordinator

    def upsert(self, path: Path) -> bool:
        """Read one record into its row -- after a save, or a conversion, which takes over the ``.tc``'s row.

        :param path: the record's absolute path.
        :returns: whether the cache changed: ``False`` for a path under no root, or not a record's name, or a
            missing record under a root that is offline.
        """
        location = self.__located(path)
        if location is None:
            return False
        with self.__coordinator.holding():
            return self.__reread(path, location)

    def verify(self, path: Path) -> bool:
        """Compare a record's row with the file, and re-read it when they differ (verify-on-access).

        The stat signature decides, as in an incremental scan: a modification time or size the row was not read
        at means the file changed out-of-band ([[mounts-and-storage#out-of-band]]).

        :param path: the record's absolute path.
        :returns: whether the record was reintegrated -- re-read, or its row removed because it is gone.
        """
        location = self.__located(path)
        if location is None:
            return False
        signature = self.__cache.signature(location.root.root_id, location.relative)
        with self.__coordinator.holding():
            try:
                stat = path.stat()
            except OSError:
                return self.__reread(path, location)
            if signature is not None and signature.matches(stat.st_mtime_ns, stat.st_size):
                return False
            LOG.info("%s changed since it was cached; reading it again.", path)
            return self.__reread(path, location)

    def __located(self, path: Path) -> CatalogLocation | None:
        """Where ``path`` is in the cache, when it is a record under a root at all."""
        if not is_record_name(path.name):
            return None
        return self.__cache.locate(path)

    def __reread(self, path: Path, location: CatalogLocation) -> bool:
        """Read ``path`` into its row, or remove the row of one that is gone; called under the hold.

        :returns: whether the cache changed.
        """
        if not path.is_file():
            if not location.root.path.is_dir():
                LOG.info("The root %s is offline; the row of %s is kept.", location.root.path, path)
                return False
            return self.__cache.remove(path)
        record = CatalogRecordReader.read(path)
        return self.__cache.upsert_record(location.root.root_id, replace(record, path=location.relative))
