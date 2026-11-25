"""A store's library, scanned into a root on the app-wide task queue ([[acquisition-tooling#library-scan-job]],
[[acquisition-tooling#library-scan-stops]], #682).

**The records are the cursor.** Every run asks the cache how far the site's records in the root reach -- the newest
``acquired`` and the ids filed in its millisecond (`~rehuco_core.CatalogCache.library_cursor`) -- and reads the library
from there, oldest first. Nothing is written per item for the scan to know where it stands, so a crash, a kill and a
power cut cost what a pause costs: the item in hand. Run again and again, a scan adds what was acquired since. A
full rescan's own position is saved as the queue is, on a pause or a close, so a crash mid-rescan starts it over.

**An item already in the root is skipped**, never read again nor written over: the user's record is the user's. A
*full rescan* walks the whole library again and does one thing more, marking the records no longer in the account
``online: false`` ([[assets#online-only]]); it never deletes.

**A root removed from the catalog pauses the scan** before its next item (#685): the root's file and this machine's
mapping of it outlive the removal, so the records would otherwise go on being written where no catalog lists them.

**Three ways to stop, one way back.** A pause or an app close is seen inside the paced wait between two pages; a store
that challenges the persona or forgets its login ends the run paused with the reason, the persona browser opened at
the page; a store, a root or a disk that does not answer waits, or pauses for what only the user can fix. Resume runs
it again, and its first question is whether what stopped it is gone (`~.library_site.LibrarySession.check`).

**Every scan takes turns on one chain** (`~rehuco_core.LIBRARY_CHAIN`, #681), which the rebalance of a root's buckets
runs on too, so the two never move files at the same time; neither waits behind this machine's disks (#563).
"""

import logging
import random
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, override
from uuid import UUID

from rehuco_core import (
    DEFAULT_RECORD_MOVE_HOST,
    LIBRARY_CHAIN,
    PROGRESS_UNIT_RESOURCES,
    CatalogCache,
    CatalogRecordUpdater,
    JobControl,
    JobOutcome,
    JobPaused,
    JobWaiting,
    LibraryCursor,
    LicenseTerms,
    RecordConflict,
    RecordLockedError,
    Records,
    ResourceKey,
    TaskJobBase,
)

from ..settings.identity_settings import shared_identity_settings
from ..settings.scrapers_settings import shared_scrapers_settings
from .browser_fetcher import PersonaLease, shared_persona_browser
from .library_record_writer import LOCKED_RETRY_SECONDS, LibraryRecordWriter
from .library_rescan import LibraryRescan
from .library_site import LibraryEntry, LibrarySession, LibrarySite, StoreOfflineError, StorePausedError
from .protocols import FetchError

LOG: Final = logging.getLogger(__name__)

LIBRARY_SCAN_KIND: Final = "library-scan"
"""The name a library scan is saved under in the queue file ([[appendices.task-queue#lifetime]])."""

PAGE_PAUSE: Final = (3.0, 8.0)
"""The ``(min, max)`` seconds a scan waits between two pages, drawn at random: a library is read once, and a store that
starts challenging the persona costs more than the time saved."""

WAIT_SLICE_SECONDS: Final = 0.1
"""How long the wait between pages sleeps between two looks at its stop request, so a pause or an app close unwinds at
once ([[appendices.task-queue#teardown]])."""

STORE_OFFLINE_RETRY_SECONDS: Final = 60.0
"""How long a scan waits for a store that does not answer before trying again."""

ADDED_LINE: Final = "%s — %s: added"
"""The log line of an item written to the root: its title and its page."""

PRESENT_LINE: Final = "%s — %s: already there"
"""The log line of an item the root already holds a record of."""

GONE_LINE: Final = "%s is no longer in the account: marked offline."
"""The log line of a record a full rescan did not find in the library."""

REMOVED_REASON: Final = "The root %s was removed from the catalog: add it again, then resume."
"""Why a scan pauses once the catalog no longer lists its root: its records would be written where no catalog shows
them, and the cursor, read from the root's rows, would be gone (#685)."""

UNLISTED_LINE: Final = "%s was written, but the catalog places it under no root: it is listed at the next scan."
"""The log line of a record the cache would not enter, which the next run then finds at its place and enters."""


@dataclass(frozen=True)
class LibraryScanTarget:
    """What one scan is of: which store, into which root, and whether the whole library is read again.

    :param site_key: the site's :attr:`~.library_site.LibrarySite.key`.
    :param root_id: the root the records go to.
    :param root_label: the root's name, for the row.
    :param root_file: the root's ``.rehuroot``, whose layouts place each record.
    :param cache_path: the catalog's ``.rehudb``.
    :param full_rescan: whether the library is walked from its oldest item again, marking what left the account.
    """

    site_key: str
    root_id: UUID
    root_label: str
    root_file: Path
    cache_path: Path
    full_rescan: bool = False

    def to_state(self) -> dict[str, Any]:
        """This target as JSON primitives.

        :returns: the state.
        """
        return {
            "site": self.site_key,
            "root": str(self.root_id),
            "root_label": self.root_label,
            "root_file": str(self.root_file),
            "cache": str(self.cache_path),
            "full_rescan": self.full_rescan,
        }

    @staticmethod
    def from_state(state: dict[str, Any]) -> LibraryScanTarget:
        """The target :meth:`to_state` wrote.

        :param state: the state, as read back.
        :returns: the target.
        :raises ValueError: the state is not one this class wrote.
        """
        try:
            site, root, label, root_file, cache = (
                state["site"],
                state["root"],
                state["root_label"],
                state["root_file"],
                state["cache"],
            )
            full_rescan = state.get("full_rescan", False)
        except (KeyError, TypeError) as error:
            raise ValueError(f"Not a library scan's state: {error}") from error
        if not all(isinstance(value, str) for value in (site, root, label, root_file, cache)):
            raise ValueError("A library scan's state names its site, root and files as text")
        if not isinstance(full_rescan, bool):
            raise ValueError("A library scan's full_rescan is a boolean")
        return LibraryScanTarget(site, UUID(root), label, Path(root_file), Path(cache), full_rescan)


@dataclass
class LibraryScanCounts:
    """What a scan's runs counted: the items added, those already there, and the records a rescan found gone.

    Kept in the scan's state, so the row's bar and its outcome read the same after a restart.

    :param added: the items written.
    :param present: the items the root already held a record of.
    :param gone: the records a full rescan marked offline.
    """

    added: int = 0
    present: int = 0
    gone: int = 0

    @property
    def walked(self) -> int:
        """How many listed items the runs filed or found filed -- the scan's progress.

        :returns: the count.
        """
        return self.added + self.present

    def summary(self, full_rescan: bool) -> str | None:
        """The outcome's line.

        :param full_rescan: whether the scan is a full rescan, which also says what it found gone.
        :returns: the line; ``None`` before anything was counted.
        """
        if not (self.added or self.present or self.gone):
            return None
        summary = f"{self.added} added, {self.present} already there"
        return f"{summary}, {self.gone} no longer in the account" if full_rescan else summary

    def to_state(self) -> dict[str, int]:
        """These counts as JSON primitives.

        :returns: the state.
        """
        return {"added": self.added, "present": self.present, "gone": self.gone}

    @staticmethod
    def from_state(state: object) -> LibraryScanCounts:
        """The counts :meth:`to_state` wrote; none counted when the state names none.

        :param state: the state, as read back.
        :returns: the counts.
        :raises ValueError: the state is not whole numbers under those names.
        """
        if state is None:
            return LibraryScanCounts()
        if not isinstance(state, dict):
            raise ValueError("A library scan's counts are a mapping")
        values = [state.get(name, 0) for name in ("added", "present", "gone")]
        if not all(isinstance(value, int) and not isinstance(value, bool) for value in values):
            raise ValueError("A library scan's counts are whole numbers")
        return LibraryScanCounts(*values)


class LibraryScanJob(TaskJobBase):
    """Scans one store's library into one root ([[acquisition-tooling#library-scan-job]]).

    A `~rehuco_core.PersistableTaskJob` and a `~rehuco_core.ReportingTaskJob` by shape. Built bare by the registry's
    factory and then restored, or with its target by the dialog that starts it (#683).

    :param sites: finds a site by its key -- the scraper wizards' registry (#683), asked again on every run, so a site
        added after a restart is found.
    :param target: what to scan; ``None`` for a job about to be restored.
    """

    kind = LIBRARY_SCAN_KIND
    chain = LIBRARY_CHAIN
    resumes_where_it_stopped = True
    progress_unit = PROGRESS_UNIT_RESOURCES

    def __init__(self, sites: Callable[[str], LibrarySite | None], target: LibraryScanTarget | None = None) -> None:
        super().__init__()
        self.__sites: Final = sites
        self.__target = target
        self.__position = LibraryCursor()
        self.__licenses: dict[str, LicenseTerms | None] = {}
        self.__counts = LibraryScanCounts()
        self.__describe()

    @property
    def outcome(self) -> JobOutcome | None:
        """What the runs found: how many items were added, already there and, for a full rescan, gone.

        :returns: the outcome; ``None`` before any item was walked.
        """
        target = self.__target
        summary = None if target is None else self.__counts.summary(target.full_rescan)
        return None if summary is None else JobOutcome(summary)

    def validate(self) -> str | None:
        """Say whether this scan can start now: its site is installed, its root mapped, its catalog's cache there.

        :returns: ``None``, or why not.
        """
        target = self.__target
        if target is None:
            return "The scan names no library to read."
        if self.__sites(target.site_key) is None:
            return f"No library scanner named {target.site_key} is installed."
        if DEFAULT_RECORD_MOVE_HOST.root_folder(target.root_id) is None:
            return f"This machine maps no folder to the root {target.root_label}."
        if not target.cache_path.is_file():
            return f"The catalog's cache is gone: {target.cache_path}"
        return None

    def capture_state(self) -> dict[str, Any]:
        """What the records cannot say: the target, what the runs counted and, for a full rescan, how far it got.

        :returns: the state.
        :raises ValueError: the job has no target.
        """
        target = self.__require_target()
        state = target.to_state()
        state["counts"] = self.__counts.to_state()
        if target.full_rescan:
            state["position"] = {
                "acquired": self.__position.acquired,
                "site_ids": sorted(self.__position.site_ids),
            }
        return state

    def restore_state(self, state: dict[str, Any]) -> None:
        """Become the scan that captured ``state``.

        :param state: what :meth:`capture_state` wrote.
        :raises ValueError: the state is not one this class wrote.
        """
        target = LibraryScanTarget.from_state(state)
        position = state.get("position")
        if position is not None:
            acquired, site_ids = position.get("acquired"), position.get("site_ids", [])
            if (acquired is not None and not isinstance(acquired, str)) or not isinstance(site_ids, list):
                raise ValueError("A library scan's position is a time and a list of ids")
            self.__position = LibraryCursor(acquired, frozenset(str(site_id) for site_id in site_ids))
        self.__counts = LibraryScanCounts.from_state(state.get("counts"))
        self.__target = target
        self.__describe()

    @override
    def reset(self) -> None:
        """Start over: a full rescan from the oldest item, and no counts."""
        super().reset()
        self.__position = LibraryCursor()
        self.__counts = LibraryScanCounts()

    @override
    def run(self, control: JobControl) -> None:
        """Walk the library from where the records reach, filing each item the root has no record of.

        :param control: the engine's face to this job.
        :raises JobPaused: asked to, or stopped by what only the user can fix -- the reason as its message.
        :raises JobWaiting: the store or the root does not answer.
        """
        target = self.__require_target()
        site = self.__sites(target.site_key)
        if site is None:
            raise JobPaused(f"No library scanner named {target.site_key} is installed.")
        self.__licenses = {}
        try:
            with CatalogCache.open(target.cache_path) as cache:
                self.__walk(control, target, site, cache)
        except StorePausedError as stopped:
            self.__show_browser(stopped.url)
            raise JobPaused(stopped.reason) from stopped
        except StoreOfflineError as offline:
            raise JobWaiting(offline.reason, STORE_OFFLINE_RETRY_SECONDS) from offline
        except FetchError as error:
            raise JobPaused(str(error)) from error

    def __walk(self, control: JobControl, target: LibraryScanTarget, site: LibrarySite, cache: CatalogCache) -> None:
        """One run's walk of the library, the persona leased and the store's session open for its whole length.

        :param control: the engine's face to this job.
        :param target: what to scan.
        :param site: the store.
        :param cache: the catalog's cache, opened on this thread.
        """
        identity = shared_identity_settings()
        writer = LibraryRecordWriter(
            target.root_id, target.root_file, username=identity.current_username, checkpoint=self.checkpoint
        )
        writer.root_folder()
        self.__require_listed(cache, target)
        cursor = self.__position if target.full_rescan else cache.library_cursor(site.name, target.root_id)
        rescan = (
            LibraryRescan(self.__dated(cache, site, target.root_id), self.__position) if target.full_rescan else None
        )
        settings = shared_scrapers_settings()
        with (
            shared_persona_browser().lease(
                settings.browser, headless=not settings.show_browser, checkpoint=self.checkpoint
            ) as lease,
            site.session(lease) as session,
        ):
            session.check()
            for entry in session.listing(cursor, lambda: self.__wait(lease)):
                self.checkpoint()
                # an item may load pages of its own, so a drop waits for one item at most, never a whole page of them
                lease.yield_if_wanted()
                self.__require_listed(cache, target)
                if cursor.covers(entry.acquired, entry.site_id):
                    continue
                if rescan is not None:
                    self.__mark_gone(cache, site, target, writer, rescan.listed(entry.acquired, entry.site_id))
                self.__take(cache, session, site=site, target=target, writer=writer, entry=entry)
                if rescan is not None:
                    self.__position = rescan.position
                control.report(self.__counts.walked)
            if rescan is not None:
                self.__mark_gone(cache, site, target, writer, rescan.finished())

    def __take(  # pylint: disable=too-many-arguments  # one item, and everything a run holds open for it
        self,
        cache: CatalogCache,
        session: LibrarySession,
        *,
        site: LibrarySite,
        target: LibraryScanTarget,
        writer: LibraryRecordWriter,
        entry: LibraryEntry,
    ) -> None:
        """File one item: skipped when the root already holds a record of it, else read and written.

        :param cache: the catalog's cache.
        :param session: the store's library, open.
        :param site: the store.
        :param target: what is scanned.
        :param writer: what writes a new record.
        :param entry: the item.
        """
        if cache.find_by_site_id(site.name, entry.site_id, target.root_id):
            self.__counts.present += 1
            LOG.info(PRESENT_LINE, entry.title, entry.url)
            return
        item = session.read_item(entry)
        terms = None if item.license_path is None else self.__license(session, item.license_path)
        written = writer.write(entry, item, site.name, terms)
        if not CatalogRecordUpdater(cache).upsert(written.path):
            LOG.warning(UNLISTED_LINE, written.path)
        # counted before its buckets settle: a wait met there leaves the record written, and added by this run
        self.__counts.added += 1
        LOG.info(ADDED_LINE, entry.title, entry.url)
        writer.settle(written)

    def __mark_gone(
        self,
        cache: CatalogCache,
        site: LibrarySite,
        target: LibraryScanTarget,
        writer: LibraryRecordWriter,
        gone: list[str],
    ) -> None:
        """Mark the records a full rescan passed over ``online: false``, saved against the version just read and
        entered in the cache.

        :param cache: the catalog's cache.
        :param site: the store.
        :param target: what is scanned.
        :param writer: what knows the root's folder, and whether it answers.
        :param gone: the store ids no longer in the account.
        :raises JobWaiting: a record is locked by a write elsewhere, or the root stopped answering.
        """
        if not gone:
            return
        root = writer.root_folder()
        identity = shared_identity_settings()
        records = Records()
        for site_id in gone:
            for row in cache.find_by_site_id(site.name, site_id, target.root_id):
                key = ResourceKey(root / row.record.path)
                try:
                    loaded = records.load(
                        key, username=identity.current_username, unknown_username=identity.unknown_username
                    )
                    if loaded.version is None or loaded.document.active_field("online") is False:
                        continue
                    loaded.document.set_active_field("online", False)
                    records.save(
                        key, loaded.document, loaded.version, username=identity.current_username, overwrite=False
                    )
                except RecordConflict:
                    LOG.warning("%s changed while a rescan marked it offline; left as it is.", key.path)
                    continue
                except RecordLockedError as error:
                    raise JobWaiting(str(error), LOCKED_RETRY_SECONDS) from error
                except OSError:
                    writer.root_folder()
                    raise
                CatalogRecordUpdater(cache).upsert(key.path)
                self.__counts.gone += 1
                LOG.info(GONE_LINE, row.record.title or key.path)

    def __wait(self, lease: PersonaLease) -> None:
        """The paced pause between two pages: the persona given up to a drop waiting for it, then a random wait,
        stopped at once by a pause or a cancel.

        :param lease: the scan's hold on the persona.
        :raises JobPaused: a pause was asked for.
        :raises JobCanceled: a cancel was asked for.
        """
        lease.yield_if_wanted()
        deadline = time.monotonic() + random.uniform(*PAGE_PAUSE)  # nosec B311  # a pace, not a secret
        while time.monotonic() < deadline:
            self.checkpoint()
            time.sleep(WAIT_SLICE_SECONDS)
        self.checkpoint()

    def __license(self, session: LibrarySession, path: str) -> LicenseTerms | None:
        """A license's text, read from the store once per run.

        :param session: the store's library, open.
        :param path: the store's id for the license.
        :returns: the terms, or ``None`` for one with no text.
        """
        if path not in self.__licenses:
            self.__licenses[path] = session.read_license(path)
        return self.__licenses[path]

    @staticmethod
    def __require_listed(cache: CatalogCache, target: LibraryScanTarget) -> None:
        """Stop the scan once the catalog no longer lists its root, asked before every item: Remove Root leaves the
        root's file and this machine's mapping of it, so nothing else would notice.

        :param cache: the catalog's cache.
        :param target: what is scanned.
        :raises JobPaused: the root was removed from the catalog.
        """
        if all(root.root_id != target.root_id for root in cache.roots()):
            raise JobPaused(REMOVED_REASON % target.root_label)

    @staticmethod
    def __dated(cache: CatalogCache, site: LibrarySite, root_id: UUID) -> Iterator[tuple[str, str]]:
        """The store id and ``acquired`` of each of the site's records in the root that has one.

        :param cache: the catalog's cache.
        :param site: the store.
        :param root_id: the root.
        :returns: the pairs.
        """
        name = site.name.casefold()
        for row in cache.library_rows(site.name, root_id):
            acquired = row.record.acquired
            site_id = next((id_ for on, id_ in row.record.site_ids if on.casefold() == name), None)
            if acquired and site_id is not None:
                yield site_id, acquired

    @staticmethod
    def __show_browser(url: str) -> None:
        """Open the persona browser at the page that stopped the scan, for the user to answer it.

        :param url: the page.
        """
        settings = shared_scrapers_settings()
        try:
            shared_persona_browser().open_for_login(settings.browser, url)
        except FetchError as error:
            LOG.warning("The persona browser could not be opened at %s: %s", url, error)

    def __require_target(self) -> LibraryScanTarget:
        """This job's target.

        :returns: the target.
        :raises ValueError: the job has none -- built bare and never restored.
        """
        if self.__target is None:
            raise ValueError("A library scan with no target")
        return self.__target

    def __describe(self) -> None:
        """Set the label from the target."""
        target = self.__target
        if target is None:
            self.label = "Library scan"
            return
        site = self.__sites(target.site_key)
        name = target.site_key if site is None else site.name
        verb = "Full rescan of" if target.full_rescan else "Scan"
        self.label = f"{verb} the {name} library into {target.root_label}"
