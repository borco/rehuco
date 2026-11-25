"""A library scan's new record, placed under its root and written whole ([[acquisition-tooling#library-scan-job]],
[[acquisition-tooling#library-scan-stops]], #682).

**Never half a record.** The screenshots, the license text and, last, the ``.rehu`` are written into a staging folder
beside the place, its name starting with a dot so a bucket listing does not count it, and renamed into place in one step
once all of it is there. Until that last write the folder holds no record a catalog scan could read. A pause, a cancel
or a failure removes it; one a crash left is the scan's own, removed when the same item is written again.

**The root's layout and the split limit are read again for every record**, since either may change while a scan runs
for hours; neither is ever kept in the scan's state.
"""

import errno
import logging
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from uuid import UUID

from borco_core import Presence, device_of, presence_of
from rehuco_core import (
    ASSET_PLUGIN,
    DEFAULT_RECORD_MOVE_HOST,
    DEFAULT_RENAME_COORDINATOR,
    INFO_REHU_FILENAME,
    SITE_ID_KEY,
    BucketChain,
    BucketedPlace,
    BucketSplitter,
    JobPaused,
    JobWaiting,
    LicenseTerms,
    RecordBucketMover,
    RecordLockedError,
    RecordNaming,
    Records,
    Refusal,
    RehuDocument,
    RehurootFile,
    RehurootFileError,
    RenameYieldTimeout,
    ResourceKey,
    destinations,
    locked_record,
    resolve_buckets,
    save_screenshot,
    ungoverned_reason,
    write_license_terms,
)
from requests import RequestException

from ..settings.location_replacements_settings import shared_location_replacements_settings
from .document_scrape_target import DocumentScrapeTarget
from .image_pipeline import NotAnImageError, acquire
from .library_site import LibraryEntry, ScannedItem
from .results import ScrapedImage

LOG: Final = logging.getLogger(__name__)

STAGING_PREFIX: Final = ".rehuscan-"
"""What a record being written is staged under, beside its place: ``.rehuscan-<its folder's name>``."""

OFFLINE_RETRY_SECONDS: Final = 30.0
"""How long a scan waits for a root that does not answer before trying again, as a save waits for its share."""

LOCKED_RETRY_SECONDS: Final = 10.0
"""How long a scan waits when settling the buckets meets a record another write holds."""

READERS_BUSY_RETRY_SECONDS: Final = 10.0
"""How long a scan waits when settling the buckets meets a reader that did not let go in time."""


@dataclass(frozen=True)
class WrittenRecord:
    """A record a scan put under its root.

    :param path: its ``.rehu`` file, where it landed.
    :param chains: the bucketed levels it went into, the innermost first, to settle once it is in the cache.
    """

    path: Path
    chains: tuple[BucketChain, ...] = ()


class LibraryRecordWriter:
    """Places a library item's new record under a root by the root's layout, and writes it whole.

    :param root_id: the root.
    :param root_file: the root's ``.rehuroot``, whose layouts place the record.
    :param username: who the record is written as.
    :param checkpoint: the scan's own, called where the work may stop.
    """

    def __init__(self, root_id: UUID, root_file: Path, *, username: str, checkpoint: Callable[[], None]) -> None:
        self.__root_id: Final = root_id
        self.__root_file: Final = root_file
        self.__username: Final = username
        self.__checkpoint: Final = checkpoint

    def write(
        self, entry: LibraryEntry, item: ScannedItem, publisher: str, terms: LicenseTerms | None
    ) -> WrittenRecord:
        """Write the record of a library item that has none in the root yet.

        :param entry: what the listing said of the item.
        :param item: the item, read in full.
        :param publisher: the site, as the record's source names it.
        :param terms: the text of the license the item is held under, saved beside it; ``None`` for none.
        :returns: where it landed; a record of the item already at its place (written before a crash, not yet in the
            cache) is returned as it is, never written over.
        :raises JobPaused: the layout refuses the record, its place is taken by something else, or the disk is full.
        :raises JobWaiting: the root does not answer.
        """
        root = self.root_folder()
        document = RehuDocument.new(Path(INFO_REHU_FILENAME), username=self.__username)
        document.set_active_type(ASSET_PLUGIN.key)
        images = DocumentScrapeTarget(document).apply(item.result, publisher=publisher, page_url=item.page_url)
        document.acquired = entry.acquired
        # the listing's id is the one the scan finds the record by, whatever the page said
        document.site_id = entry.site_id
        placed = self.__place(root, document, entry.site_id)
        final = root.joinpath(*placed.relative.parts)
        landed = final / INFO_REHU_FILENAME
        if final.exists():
            if self.__holds(landed, publisher, entry.site_id):
                LOG.info("%s was already written at %s.", entry.title, final)
                return WrittenRecord(landed)
            raise JobPaused(f"{final} is already there, so {entry.title} was not written over it.")
        staging = final.with_name(f"{STAGING_PREFIX}{final.name}")
        placed_whole = False
        try:
            self.__stage(staging, document, images, item, terms)
            staging.rename(final)
            placed_whole = True
        except OSError as error:
            if error.errno == errno.ENOSPC:
                raise JobPaused(f"The disk holding {root} is full.") from error
            self.__check_reachable(root, error)
            raise
        finally:
            # a pause, a cancel or a failure leaves nothing a catalog scan could take for a record
            if not placed_whole:
                shutil.rmtree(staging, ignore_errors=True)
        return WrittenRecord(landed, placed.chains)

    def settle(self, written: WrittenRecord) -> None:
        """Split the bucket folders the record went into that it took past the limit, with the limit as it is now.

        :param written: the record, in the cache already, so a scan stopped here finds it on its next run.
        :raises JobWaiting: a record to move is locked by a write elsewhere, or a reader did not let go in time.
        """
        if not written.chains:
            return
        root = self.root_folder()
        host = DEFAULT_RECORD_MOVE_HOST
        splitter = BucketSplitter(
            host.split_limit(),
            RecordBucketMover(DEFAULT_RENAME_COORDINATOR, host, self.__checkpoint),
            self.__checkpoint,
        )
        try:
            for chain in written.chains:
                splitter.settle(root.joinpath(*chain.folder.parts), chain.chain)
        except RecordLockedError as error:
            raise JobWaiting(str(error), LOCKED_RETRY_SECONDS) from error
        except RenameYieldTimeout as error:
            raise JobWaiting(str(error), READERS_BUSY_RETRY_SECONDS) from error

    def root_folder(self) -> Path:
        """Where this machine finds the root, answering.

        :returns: the folder.
        :raises JobPaused: this machine maps no folder to the root.
        :raises JobWaiting: the root does not answer.
        """
        root = DEFAULT_RECORD_MOVE_HOST.root_folder(self.__root_id)
        if root is None:
            raise JobPaused("This machine maps no folder to the root: add it in the Roots view, then resume.")
        if presence_of(root) is Presence.OFFLINE:
            raise JobWaiting(self.offline_reason(root), OFFLINE_RETRY_SECONDS)
        return root

    @staticmethod
    def offline_reason(root: Path) -> str:
        """The sentence a scan waiting for its root shows.

        :param root: the root's folder.
        :returns: the sentence.
        """
        device = device_of(root)
        return f"Waiting for the root: {device.host or device.root} does not answer."

    def __place(self, root: Path, document: RehuDocument, folder_name: str) -> BucketedPlace:
        """Where the root's layout puts the record now, its buckets resolved from the disk.

        :param root: the root's folder.
        :param document: the record, its fields written.
        :param folder_name: what a ``*`` template keeps: the store's id.
        :returns: the place.
        :raises JobPaused: the root's file cannot be read, its layout admits no such record, or the place leads into a
            folder split where the layout has no buckets (#681).
        :raises JobWaiting: the root's file does not answer.
        """
        try:
            laid_out = RehurootFile.load(self.__root_file)
        except RehurootFileError as error:
            raise JobPaused(f"The root's file cannot be read: {error}") from error
        except OSError as error:
            self.__check_reachable(self.__root_file.parent, error)
            raise JobPaused(f"The root's file cannot be read: {error}") from error
        offered = destinations(
            laid_out, RecordNaming.of(document, folder_name), shared_location_replacements_settings().rules
        )
        if isinstance(offered, Refusal):
            raise JobPaused(f"The root's layout does not admit the record: {offered.reason}")
        placement = offered[0]
        place = resolve_buckets(root, placement.relative, placement.bucketed)
        if place.ungoverned is not None:
            raise JobPaused(ungoverned_reason(place.ungoverned))
        return place

    def __stage(
        self,
        staging: Path,
        document: RehuDocument,
        images: tuple[ScrapedImage, ...],
        item: ScannedItem,
        terms: LicenseTerms | None,
    ) -> None:
        """Write the record's screenshots, its license text and, last, the record itself into the staging folder.

        The ``.rehu`` goes last, so until the very end the folder holds nothing a catalog scan reads as a record.

        :param staging: the folder, removed first if a crash left it.
        :param document: the record.
        :param images: its screenshots, to fetch.
        :param item: the item, whose page names a screenshot that could not be fetched.
        :param terms: its license's text, or ``None``.
        """
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        rehu = staging / INFO_REHU_FILENAME
        for image in images:
            self.__checkpoint()
            try:
                fetched = acquire(image.url, image.referrer)
                save_screenshot(staging, rehu.stem, fetched.data, fetched.extension, image.slot)
            except (RequestException, NotAnImageError, ValueError) as error:
                # a slot past the numbered set's end is a ValueError: one image lost, never the record
                LOG.warning("A screenshot of %s was left out: %s (%s)", item.page_url, image.url, error)
        if terms is not None:
            with locked_record(rehu, user=self.__username):
                write_license_terms(rehu, terms)
        Records().save(ResourceKey(rehu), document, None, username=self.__username, overwrite=False, new=True)

    @staticmethod
    def __holds(landed: Path, publisher: str, site_id: str) -> bool:
        """Whether the record at a place is this item's.

        :param landed: the ``.rehu`` the place would hold.
        :param publisher: the site.
        :param site_id: the item's store id.
        :returns: whether it is there and names the item.
        """
        if not landed.is_file():
            return False
        try:
            document = RehuDocument.load(landed)
        except OSError, ValueError:
            return False
        return any(
            str(source.get("publisher", "")).casefold() == publisher.casefold() and source.get(SITE_ID_KEY) == site_id
            for source in document.sources
            if isinstance(source, dict)
        )

    def __check_reachable(self, folder: Path, error: OSError) -> None:
        """Turn a failure on a folder that stopped answering into a wait.

        :param folder: where the failure happened.
        :param error: the failure.
        :raises JobWaiting: the folder does not answer.
        """
        if presence_of(folder) is Presence.OFFLINE:
            raise JobWaiting(self.offline_reason(folder), OFFLINE_RETRY_SECONDS) from error
