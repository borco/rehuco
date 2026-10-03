"""A scan of one ``.rehuco`` root: every record under it, read for the catalog cache
([[data-model#scan-and-staleness]], [[data-model#cache-schema]], #372).

**Incremental by default** (#373): given the root's cached rows, a record whose stat signature (modification
time and size) still matches is not opened, and only what changed is read. Without them, which is a first scan,
every record is. Either way the result is the root's whole content, so what was not found is swept.

**Parse on find.** Each directory's records are read as soon as its listing closes, so progress is a running
count rather than a percentage over a total nobody has yet -- a first scan cannot know one, and a walk that
collected before it read would only exist to invent it. A later scan reports against the previous one's total
instead (:class:`~rehuco_core.ScanCatalogRootJob`), an estimate that is right when little changed.

**A root is wholly online or wholly offline** ([[mounts-and-storage#offline-mounts]], #245). One that does not
list is *offline* and the scan says so without reading anything, so its cached rows survive rather than being
read as an empty folder. One that lists is *online*, and then what the scan did not find is gone -- including
the contents of a branch that would not list, which is named in the result but not kept. The root is probed
once more when the walk ends; if it went away meanwhile, the whole result is marked as such and is not
applied, since a scan cannot tell a mount dropping mid-walk from folders that really are gone.

**It never blocks a rename** ([[data-model#cache-schema]]). Each listing, and each record read, is one chunk
inside the rename coordinator's hold, closed before the next; the directories still to visit and the records
already read are tracked locations, so a folder renamed mid-scan lands in the result under its new name.

**An unreadable record is reported, not fatal**: it gets a row carrying the reason, and the scan goes on.
"""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

import xxhash

from .rehu_catalog import CatalogCheckpoint, CatalogScanner
from .rehu_document import RehuDocument, author_name
from .rehu_locks import coerced_str_list
from .rehu_parse_limits import oversized_file_reason
from .rehudb import CatalogRecord, RecordKind, RecordSignature, catalog_path_key, catalog_type_fields
from .rename_coordination import DEFAULT_RENAME_COORDINATOR, RenameCoordinator, ResourceLocation
from .resource_scoping import is_legacy_record_name
from .tc_document import load_tc

LOG: Final = logging.getLogger(__name__)

ScanProgress = Callable[[int], None]
"""What a scan calls after each record it reads, with how many it has read so far."""


class RootScanOutcome(StrEnum):
    """How a root scan ended."""

    SCANNED = "scanned"
    """The root listed, and was still there at the end: the result replaces the root's rows."""

    OFFLINE = "offline"
    """The root did not list: nothing was read, and its rows stay as they were."""

    WENT_OFFLINE = "went offline"
    """The root listed but was gone by the end: the result is discarded, and the rows stay as they were."""


@dataclass(frozen=True, slots=True)
class RootScanResult:
    """What one root scan found.

    :param root: the root's folder, as it was at the end of the scan.
    :param outcome: how the scan ended.
    :param records: every record read, paths relative to :attr:`root`; empty unless :attr:`outcome` is
        :attr:`RootScanOutcome.SCANNED`.
    :param unreadable_branches: directories under the root that would not list.
    :param unchanged: the root-relative paths, as spelled now, of the records found unchanged and not read (#373);
        empty, like :attr:`records`, unless the scan applies.
    """

    root: Path
    outcome: RootScanOutcome
    records: tuple[CatalogRecord, ...] = ()
    unreadable_branches: tuple[Path, ...] = ()
    unchanged: tuple[str, ...] = ()

    @property
    def applicable(self) -> bool:
        """Whether :attr:`records` and :attr:`unchanged` are the root's whole content, fit to replace its rows."""
        return self.outcome is RootScanOutcome.SCANNED

    @property
    def unreadable_records(self) -> int:
        """How many records were found but could not be read."""
        return sum(1 for record in self.records if record.error is not None)

    @property
    def legacy_records(self) -> int:
        """How many records are legacy ``.tc`` files no ``.rehu`` covers."""
        return sum(1 for record in self.records if record.kind is RecordKind.TC)


class CatalogRootScan:  # pylint: disable=too-few-public-methods
    """Reads every changed record under one root ([[data-model#cache-schema]], #372, #373).

    **Incremental, given what the cache knows** ([[data-model#scan-and-staleness]]): a record whose stat
    signature still matches its row is not opened at all -- it is reported unchanged, and its row stays as it is.
    Without ``known`` every record is read, which is what a first scan is.

    **It descends everywhere**, whatever a record's type ([[data-model#scan-and-staleness]], #373): a record nested
    inside a tutorial is a resource of its own, as the content walk already treats it (#254), so a scan that stopped
    at the tutorial would lose it from the catalog while the tutorial no longer counted it either.

    :param root: the root's folder.
    :param coordinator: the rename barrier every read goes through.
    :param checkpoint: called once per directory and once per record, so a cancel bites within one read;
        whatever it raises leaves the scan.
    :param progress: called with the running count after each record, read or not.
    :param known: the root's cached rows (:meth:`~rehuco_core.CatalogCache.signatures`), or ``None`` to read every
        record.
    """

    def __init__(
        self,
        root: Path,
        *,
        coordinator: RenameCoordinator = DEFAULT_RENAME_COORDINATOR,
        checkpoint: CatalogCheckpoint | None = None,
        progress: ScanProgress | None = None,
        known: Mapping[str, RecordSignature] | None = None,
    ) -> None:
        self.__coordinator: Final = coordinator
        self.__root: Final = coordinator.track(root)
        self.__checkpoint: Final = checkpoint
        self.__progress: Final = progress
        self.__known: Final[Mapping[str, RecordSignature]] = known if known is not None else {}

    def scan(self) -> RootScanResult:
        """Walk the root and read each record found that changed.

        :returns: what was found, and how the scan ended.
        """
        scanner = CatalogScanner(
            self.__root.path, checkpoint=self.__checkpoint, coordinator=self.__coordinator, include_legacy=True
        )
        found: list[tuple[ResourceLocation, CatalogRecord | None]] = []
        unreadable: list[Path] = []
        for listed, directory in enumerate(scanner.walk()):
            if not directory.listed:
                if listed == 0:  # the walk lists the root first
                    LOG.info("The root %s did not list; its cached rows are kept.", directory.path)
                    return RootScanResult(directory.path, RootScanOutcome.OFFLINE)
                LOG.warning("%s did not list; whatever the cache held under it is dropped.", directory.path)
                unreadable.append(directory.path)
                continue
            for location in directory.record_locations:
                if self.__checkpoint is not None:
                    self.__checkpoint()
                with self.__coordinator.holding():
                    record = self.__visit(location.path)
                found.append((location, record))
                if self.__progress is not None:
                    self.__progress(len(found))
        # one hold around the probe and the relative paths: the root and the records are rewritten together
        # by a rename, and reading them in two steps could pair a root before it with records after it
        with self.__coordinator.holding():
            root = self.__root.path
            if not root.is_dir():
                LOG.warning("The root %s went away during its scan; the scan is discarded.", root)
                return RootScanResult(root, RootScanOutcome.WENT_OFFLINE, unreadable_branches=tuple(unreadable))
            records = tuple(
                replace(record, path=self.__relative(root, location.path))
                for location, record in found
                if record is not None
            )
            unchanged = tuple(self.__relative(root, location.path) for location, record in found if record is None)
        return RootScanResult(root, RootScanOutcome.SCANNED, records, tuple(unreadable), unchanged)

    def __visit(self, path: Path) -> CatalogRecord | None:
        """Read one record, unless its row says it has not changed.

        :param path: the record, as it is now; called under the hold, so it and the root agree.
        :returns: what it holds, or ``None`` when it is unchanged.
        """
        known = self.__known.get(catalog_path_key(self.__relative(self.__root.path, path)))
        if known is not None:
            try:
                stat = path.stat()
            except OSError:
                pass  # the read below stats it again, and records why it could not
            else:
                if known.matches(stat.st_mtime_ns, stat.st_size):
                    return None
        return CatalogRecordReader.read(path)

    @staticmethod
    def __relative(root: Path, path: Path) -> str:
        """``path``, read from where its location is **now**, relative to the root."""
        return path.relative_to(root).as_posix()


class CatalogRecordReader:  # pylint: disable=too-few-public-methods
    """Reads one record into what the cache stores of it -- for a scan, and for a targeted update (#373)."""

    @staticmethod
    def read(path: Path) -> CatalogRecord:
        """Read one record: its stat signature, a hash of its bytes, the common core it holds and its type's own
        fields.

        The path stored here is ``path`` itself; the caller makes it root-relative.

        :param path: the record, as it is now.
        :returns: what it holds, or a row naming why it could not be read.
        """
        kind = RecordKind.TC if is_legacy_record_name(path.name) else RecordKind.REHU
        try:
            stat = path.stat()
            oversized = oversized_file_reason(stat.st_size)
            content_hash = "" if oversized else xxhash.xxh3_64(path.read_bytes()).hexdigest()
        except OSError as error:
            LOG.warning("%s could not be read: %s", path, error)
            return CatalogRecord(path.as_posix(), kind, error=str(error))
        signature = CatalogRecord(path.as_posix(), kind, mtime_ns=stat.st_mtime_ns, size=stat.st_size)
        if oversized:
            return replace(signature, error=oversized)
        try:
            document = load_tc(path) if kind is RecordKind.TC else RehuDocument.load(path)
        except (OSError, ValueError) as error:
            LOG.warning("%s could not be read: %s", path, error)
            return replace(signature, content_hash=content_hash, error=str(error))
        return replace(
            signature,
            uuid=document.id,
            type=document.type,
            title=document.title,
            publisher=document.publisher,
            url=document.url,
            released=document.released,
            current_size=document.current_size,
            updated=document.updated,
            authors=tuple(name for name in (author_name(entry) for entry in document.authors) if name),
            tags=(*document.advertised_tags, *document.extra_tags),
            publishers=CatalogRecordReader.__publishers(document),
            content_hash=content_hash,
            **CatalogRecordReader.__type_fields(document),
        )

    @staticmethod
    def __type_fields(document: RehuDocument) -> dict[str, Any]:
        """The type-specific fields the cache stores (:data:`~rehuco_core.rehudb.TYPE_FIELD_COLUMNS`) that the
        record's type declares -- so a stray key in another type's block, or a type no plugin here claims, stays
        empty rather than showing in a column that is not its type's."""
        values = {
            "advertised_duration": document.advertised_duration,
            "original_duration": document.original_duration,
            "current_duration": document.current_duration,
            "level": tuple(coerced_str_list(document.active_field("level"))),
            "advertised_count": document.advertised_count,
            "current_count": document.current_count,
        }
        return {name: values[name] for name in catalog_type_fields(document.type, document.plugins)}

    @staticmethod
    def __publishers(document: RehuDocument) -> tuple[str, ...]:
        """Every source's publisher, the primary's first, each named once."""
        names = (source.get("publisher") for source in document.source_records if isinstance(source, dict))
        return tuple(dict.fromkeys(name for name in names if isinstance(name, str) and name))
