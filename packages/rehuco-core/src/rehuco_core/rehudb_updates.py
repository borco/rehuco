"""The catalog cache kept current one record at a time, between scans ([[data-model#scan-and-staleness]], #373).

A save or a conversion re-reads its record (:meth:`CatalogRecordUpdater.upsert`); opening, browsing to or serving a
resource checks its row against the file and re-reads it when they disagree (:meth:`CatalogRecordUpdater.verify`).
A rename needs no read at all and is :meth:`~rehuco_core.CatalogCache.apply_relocation`'s; a deletion is
:meth:`~rehuco_core.CatalogCache.remove`'s.

**A root is wholly online or wholly offline** ([[mounts-and-storage#offline-mounts]]), here as in a scan: a record
that is missing under a root that is there is gone, and its row with it; under a root that is not, nothing changes.

**The cache belongs to the thread that opened it** (:class:`~rehuco_core.CatalogCache`), so an updater is used on
that thread; each read is one chunk under the rename coordinator's hold, as a scan's is.

**Verifying is three steps, for a caller whose cache thread must not touch the disk** (#487): the GUI thread, where a
share can block a ``stat`` for its whole timeout ([[mounts-and-storage#offline-mounts]]).
:meth:`~CatalogRecordUpdater.plan` asks the cache what it holds, :func:`check_records` compares that with the disk on
any thread and never sees the cache, and :meth:`~CatalogRecordUpdater.apply` writes what it found back on the cache's
thread -- dropping a finding the cache moved past meanwhile: a row a save or a scan rewrote, or a record a rename
moved.
"""

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final

from .rehudb import CatalogCache, CatalogLocation, CatalogRecord, CatalogRoot, RecordSignature
from .rehudb_scan import CatalogRecordReader
from .rename_coordination import DEFAULT_RENAME_COORDINATOR, RenameCoordinator, ResourceLocation
from .resource_scoping import is_record_name

LOG: Final = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RecordCheck:
    """One record to compare with its row, as the cache saw it when the check was planned (#487).

    :param path: the record's absolute path, as planned.
    :param location: where it is in the cache.
    :param signature: its row's signature then; ``None`` for no row.
    :param tracked: the path, followed across a rename while the check is out.
    """

    path: Path
    location: CatalogLocation
    signature: RecordSignature | None
    tracked: ResourceLocation


@dataclass(frozen=True, slots=True)
class RecordFinding:
    """What a check found on disk that the cache does not say (#487).

    :param check: the check it answers.
    :param record: the record as read now; ``None`` when it is gone from a root that is there.
    """

    check: RecordCheck
    record: CatalogRecord | None


@dataclass(frozen=True, slots=True)
class RecordsChecked:
    """What :func:`check_records` found (#487).

    :param findings: what the cache does not say, for :meth:`CatalogRecordUpdater.apply`.
    :param seen: every record that could be read, by its planned path, with the ``(modification time in ns, size)``
        it has on disk now -- changed or not, for whatever shows a record to compare with what it showed.
    """

    findings: list[RecordFinding]
    seen: dict[Path, tuple[int, int]]


def check_records(checks: Iterable[RecordCheck], coordinator: RenameCoordinator) -> RecordsChecked:
    """Compare each record with its row's signature, reading it when they differ -- on any thread, the cache unseen.

    Each record is one chunk under the rename coordinator's hold, as in a scan. A record whose row still matches
    costs one ``stat`` and finds nothing; one missing under a root that is offline finds nothing either.

    :param checks: what :meth:`CatalogRecordUpdater.plan` planned.
    :param coordinator: the rename barrier every read goes through.
    :returns: the findings, and what every record looks like on disk.
    """
    checked = RecordsChecked([], {})
    for check in checks:
        with coordinator.holding():
            _check(check, checked)
    return checked


def _check(check: RecordCheck, checked: RecordsChecked) -> None:
    """One record's comparison, added to ``checked``; called under the hold.

    :param check: the record.
    :param checked: what has been found so far.
    """
    path = check.tracked.path
    try:
        stat = path.stat()
    except OSError:
        stat = None
    if stat is not None:
        checked.seen[check.path] = (stat.st_mtime_ns, stat.st_size)
    if stat is not None and check.signature is not None and check.signature.matches(stat.st_mtime_ns, stat.st_size):
        return
    if not path.is_file():
        if not check.location.root.path.is_dir():
            LOG.info("The root %s is offline; the row of %s is kept.", check.location.root.path, path)
            return
        checked.findings.append(RecordFinding(check, None))
        return
    if check.signature is not None:
        LOG.info("%s changed since it was cached; reading it again.", path)
    checked.findings.append(RecordFinding(check, CatalogRecordReader.read(path)))


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
        """Compare a record's row with the file, and re-read it when they differ (verify-on-access), all on this
        thread: :meth:`plan`, :func:`check_records` and :meth:`apply` in one.

        The stat signature decides, as in an incremental scan: a modification time or size the row was not read
        at means the file changed out-of-band ([[mounts-and-storage#out-of-band]]).

        :param path: the record's absolute path.
        :returns: whether the record was reintegrated -- re-read, or its row removed because it is gone.
        """
        return bool(self.apply(check_records(self.plan([path]), self.__coordinator).findings))

    def plan(self, paths: Iterable[Path]) -> list[RecordCheck]:
        """What :func:`check_records` is to compare, read from the cache alone -- no disk (#487).

        :param paths: absolute paths; those that are no record's name, or under no root, are passed over, and a
            path named twice is checked once.
        :returns: one check per record.
        """
        checks: list[RecordCheck] = []
        seen: set[Path] = set()
        roots = self.__cache.roots()  # once for all the paths: a listing of a big folder plans hundreds
        for path in paths:
            if path in seen:
                continue
            seen.add(path)
            location = self.__located(path, roots)
            if location is None:
                continue
            signature = self.__cache.signature(location.root.root_id, location.relative)
            checks.append(RecordCheck(path, location, signature, self.__coordinator.track(path)))
        return checks

    def apply(self, findings: Sequence[RecordFinding]) -> set[Path]:
        """Write what :func:`check_records` found into the cache, on its thread (#487).

        **A finding the cache has moved past is dropped**: its record was renamed while the check was out (the
        rename rebased the row, and the listing that follows it verifies again), or its row is no longer the one
        planned against -- a save or a scan wrote it meanwhile, from a newer read than this one.

        :param findings: the findings.
        :returns: the paths whose rows changed.
        """
        changed: set[Path] = set()
        for finding in findings:
            check = finding.check
            root_id, relative = check.location.root.root_id, check.location.relative
            if check.tracked.path != check.path or self.__cache.signature(root_id, relative) != check.signature:
                LOG.debug("%s changed in the cache while it was checked; its finding is dropped.", check.path)
                continue
            if finding.record is None:
                written = self.__cache.remove(check.path)
            else:
                written = self.__cache.upsert_record(root_id, replace(finding.record, path=relative))
            if written:
                changed.add(check.path)
        return changed

    def __located(self, path: Path, roots: Sequence[CatalogRoot] | None = None) -> CatalogLocation | None:
        """Where ``path`` is in the cache, when it is a record under a root at all."""
        if not is_record_name(path.name):
            return None
        return self.__cache.locate(path, roots)

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
