"""Where this machine has verified a ``.checksum`` record: trust is per location, and per machine (#357,
[[data-model#checksums]]).

A record's ``verified`` dates describe bytes that were hashed **where the record was at the time**. A
folder copied or moved elsewhere carries its record along, and before this the copy inherited every date
-- reading as verified for up to the whole staleness window although nothing had ever hashed its bytes.
Now a record is trusted only at a location this machine has verified it at, and only for stamps written
from the moment that trust began (:func:`~rehuco_core.is_checksum_fresh`).

**Kept beside the app, not in the record.** Machines see one share under different mount points
([[mounts-and-storage#rehuco-scope]]); an anchor written *into* the record would have each machine
find the other's, distrust it, re-hash, and rewrite it back. Kept per machine, neither the ``.checksum``
nor the ``.rehu`` format changes, and losing the file costs one re-verification -- never a false *current*.

**Unverified until verified here.** A location this machine has never registered is not trusted, which
includes every location on a fresh machine and the whole catalog the first time this build runs: the
first sweep after it re-hashes everything once.

**Core never reads a setting**, so the file's *path* is the agent's to give (:meth:`ChecksumTrust.attach`).
Until one is attached nothing is tracked, and freshness is the staleness window's alone -- which is what
the node, a script, and a test that never asks all keep.
"""

import json
import logging
import os
import time
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any, Final

from borco_core import atomic_write_text

from .checksum_record import TRUST_NOT_TRACKED, checksum_record_path, parse_verified, verified_stamp
from .constants import REHU_SUFFIX
from .rehu_document import RehuDocument, RehuFormatError

LOG: Final = logging.getLogger(__name__)

TRUST_VERSION: Final = 1
"""The trust file's own format version -- a local cache, so a version it does not understand is read as
empty rather than migrated: re-verifying is what losing it costs."""

TRUST_VERSION_KEY: Final = "version"
TRUST_LOCATIONS_KEY: Final = "locations"
TRUST_ID_KEY: Final = "id"
TRUST_SINCE_KEY: Final = "trusted_since"
"""The keys the trust file is written under: ``{"version": 1, "locations": {<key>: {"id": ...,
"trusted_since": ...}}}``, one location per record this machine has verified."""

DEFERRED_SAVE_INTERVAL: Final = 60.0
"""How often, in seconds, a deferred store still writes itself down (:meth:`ChecksumTrust.deferred_saves`)
-- so a sweep over thousands of resources costs a write a minute rather than one per resource, and a crash
part-way through loses at most a minute of registrations, which only ever costs a re-verification."""


class ChecksumTrust:
    """This machine's register of where it has verified which record, and since when (#357).

    **Keyed by the record's canonical location.** The key is the record's path with the directory
    *holding the resource* resolved -- which turns a mapped drive into the share it maps, so a share
    remapped to another letter keeps its trust -- while the resource's own directory is taken by name.
    Resolving only as far as the container is what lets :meth:`moved` compute the old key after the
    rename, when the old directory no longer exists. The record rather than the ``.rehu`` is keyed
    because the record is what is trusted: ``info.rehu`` and a leftover ``info.tc`` share one
    ``info.checksum``, and so share its trust.

    **Guarded by the resource's id** ([[data-model#stable-identity]]): a different resource moved into a
    path this machine trusts does not inherit that trust. A record with no readable ``.rehu`` id (a
    ``.tc``, a ``.rehu`` that will not load) is guarded by nothing more than its location.

    Thread-safe: checksum jobs register from the queue's worker while a surface asks from the GUI thread.

    :param path: the trust file, or ``None`` for a store that tracks nothing until one is attached.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.__lock: Final = RLock()
        self.__path: Path | None = None
        self.__locations: dict[str, dict[str, Any]] = {}
        self.__dirty = False
        self.__deferred = 0
        self.__last_save = 0.0
        if path is not None:
            self.attach(path)

    # region Attaching

    def attach(self, path: Path | None) -> None:
        """Start tracking in the file at ``path`` -- or stop, with ``None``.

        The file is read now. **A file that cannot be read costs its trust and nothing else**: missing,
        unparseable, stamped by a newer build or shaped wrongly, it is logged and read as empty, which
        fails safe -- every location reads unverified until verified again.

        :param path: the trust file; its directory need not exist until the first save.
        """
        with self.__lock:
            self.__path = path
            self.__locations = {} if path is None else self.__read(path)
            self.__dirty = False

    @property
    def tracking(self) -> bool:
        """Whether a file is attached -- whether trust is being tracked at all."""
        with self.__lock:
            return self.__path is not None

    # endregion

    # region Asking and telling

    def trusted_since(self, rehu_path: Path) -> datetime | None:
        """When this machine began trusting ``rehu_path``'s record where it is now.

        :param rehu_path: the resource's ``.rehu`` (or ``.tc``) file.
        :returns: the instant, which :func:`~rehuco_core.is_checksum_fresh` compares each stamp against;
            ``None`` when the location is unknown here, or known for a different resource; or
            :data:`~rehuco_core.TRUST_NOT_TRACKED` when nothing is attached.
        """
        with self.__lock:
            if self.__path is None:
                return TRUST_NOT_TRACKED
            entry = self.__locations.get(self.location_key(rehu_path))
        if entry is None or entry.get(TRUST_ID_KEY) != self.resource_identity(rehu_path):
            return None
        return parse_verified(entry.get(TRUST_SINCE_KEY))

    def register(self, rehu_path: Path, at: datetime) -> None:
        """Trust ``rehu_path``'s record where it is now, from ``at`` on -- unless it already is.

        **Never moves an existing trust forward.** A run at a trusted location leaves ``trusted_since``
        alone: moving it would silently distrust every stamp written there before, which is exactly the
        verification this location has earned.

        :param rehu_path: the resource's ``.rehu`` (or ``.tc``) file.
        :param at: when the run that verified it here began -- the same instant its stamps carry.
        """
        identity = self.resource_identity(rehu_path)
        with self.__lock:
            if self.__path is None:
                return
            key = self.location_key(rehu_path)
            existing = self.__locations.get(key)
            if existing is not None and existing.get(TRUST_ID_KEY) == identity:
                return
            self.__locations[key] = {TRUST_ID_KEY: identity, TRUST_SINCE_KEY: verified_stamp(at)}
            self.__changed()

    def moved(self, old: Path, new: Path) -> None:
        """Carry a record's trust across a rename this process made.

        A rename rewrites no bytes, so what was verified before it still holds after -- unlike a copy or
        a move made outside the app, which this never hears of and which therefore re-verifies.

        :param old: the resource's ``.rehu`` file before the rename; it need not exist any more.
        :param new: the same file after it.
        """
        with self.__lock:
            if self.__path is None:
                return
            entry = self.__locations.pop(self.location_key(old), None)
            if entry is None:
                return
            self.__locations[self.location_key(new)] = entry
            self.__changed()

    # endregion

    # region Saving

    @contextmanager
    def deferred_saves(self) -> Generator[None]:
        """Hold writes back for the length of a block -- a sweep's, which registers resource after resource.

        Inside, a change is written at most once every :data:`DEFERRED_SAVE_INTERVAL`, and whatever is
        left is written on the way out. Re-entrant, and shared across threads: another job registering
        meanwhile is written with the rest, which only ever delays a write, never loses one that
        mattered -- a registration lost to a crash costs a re-verification.

        :yields: nothing; the block does the registering.
        """
        with self.__lock:
            if self.__deferred == 0:
                # the interval runs from the block's start, not from whenever this process last wrote
                self.__last_save = time.monotonic()
            self.__deferred += 1
        try:
            yield
        finally:
            with self.__lock:
                self.__deferred -= 1
                if self.__deferred == 0 and self.__dirty:
                    self.save()

    def save(self) -> None:
        """Write the store down now, if a file is attached.

        A failure is logged rather than raised: registration happens at the end of a run whose record is
        already written, and a run must not fail over a cache whose loss only costs re-verifying.
        """
        with self.__lock:
            if self.__path is None:
                return
            payload = {TRUST_VERSION_KEY: TRUST_VERSION, TRUST_LOCATIONS_KEY: self.__locations}
            self.__last_save = time.monotonic()
            try:
                self.__path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_text(self.__path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
            except OSError:
                LOG.exception("The checksum trust file could not be saved to %s.", self.__path)
                return
            self.__dirty = False

    # endregion

    # region Keys and identities

    @staticmethod
    def location_key(rehu_path: Path) -> str:
        """The canonical spelling of where ``rehu_path``'s record lives, as this store keys it.

        :param rehu_path: the resource's ``.rehu`` (or ``.tc``) file.
        :returns: the record's path, its container resolved and the whole case-folded where the
            filesystem folds case (:func:`os.path.normcase`).
        """
        record = checksum_record_path(rehu_path)
        directory = record.parent
        return os.path.normcase(str(directory.parent.resolve() / directory.name / record.name))

    @staticmethod
    def resource_identity(rehu_path: Path) -> str | None:
        """The resource UUID guarding a location's trust, or ``None`` when there is none to read.

        :param rehu_path: the resource's ``.rehu`` (or ``.tc``) file.
        :returns: the ``.rehu``'s ``id``; ``None`` for a ``.tc``, for a ``.rehu`` that will not load, and
            for one with no id.
        """
        if rehu_path.suffix != REHU_SUFFIX:
            return None
        try:
            identity = RehuDocument.load(rehu_path).id
        except OSError, RehuFormatError:
            return None
        return identity or None

    # endregion

    def __changed(self) -> None:
        """Note a change, and write it down now unless saves are being deferred and one was made recently."""
        self.__dirty = True
        if self.__deferred == 0 or time.monotonic() - self.__last_save >= DEFERRED_SAVE_INTERVAL:
            self.save()

    @staticmethod
    def __read(path: Path) -> dict[str, dict[str, Any]]:
        """Read the trust file's locations, or none at all when it cannot be read.

        :param path: the trust file.
        :returns: key to entry; entries that are not objects are dropped, and an entry whose fields do
            not read is simply never trusted (:meth:`trusted_since`).
        """
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        except OSError:
            LOG.exception("The checksum trust file could not be read; every location reads unverified.")
            return {}
        try:
            data = json.loads(text)
        except ValueError:
            LOG.exception("The checksum trust file is not readable JSON; every location reads unverified.")
            return {}
        if not isinstance(data, dict) or data.get(TRUST_VERSION_KEY) != TRUST_VERSION:
            LOG.warning("The checksum trust file is not one this build reads; every location reads unverified.")
            return {}
        locations = data.get(TRUST_LOCATIONS_KEY)
        if not isinstance(locations, dict):
            LOG.warning("The checksum trust file holds no locations; every location reads unverified.")
            return {}
        return {key: entry for key, entry in locations.items() if isinstance(entry, dict)}


DEFAULT_CHECKSUM_TRUST: Final = ChecksumTrust()
"""The one :class:`ChecksumTrust` every checksum job and every rename reads, the process-wide singleton
the same way :data:`~rehuco_core.DEFAULT_RENAME_COORDINATOR` is: a job the registry rebuilt from the saved
queue has no window to be handed anything. Tracks nothing until the agent attaches its file."""
