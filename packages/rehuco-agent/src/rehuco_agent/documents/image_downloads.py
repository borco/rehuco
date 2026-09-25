"""One document's image downloads, submitted and applied the way a scrape is ([[acquisition-tooling#drag-drop-aids]],
#73).

**Not the app-wide task queue.** A download runs on `~rehuco_agent.scraping.scraper_executor.ScraperExecutor`'s
own pool, submitted under this document's log scope, exactly the way `.ScrapeActions` submits a scrape --
local to the dock that triggered it, with no row in the Tasks dock.

**A result is written to disk only on the GUI thread, and only if the document is still open at the same
path and unlocked** ([[acquisition-tooling#scrape-job]]): a document closed, renamed or locked while a
download was in flight simply discards the result, logged under the scope it was submitted in.
"""

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Final, cast

from borco_core.logging import LogScope
from borco_pyside.widgets import MessageBannerRow, MessageBannerSeverity
from PySide6.QtCore import QObject, Signal

from ..fields.image_organizer import ImageOrganizer
from ..scraping.image_download_job import ImageDownloadJob
from ..scraping.image_pipeline import AcquiredImage, ImageBytes, NotAnImageError, acquire
from ..scraping.protocols import PageFetcher
from ..scraping.registry import ScraperRegistry, shared_scraper_registry
from ..scraping.results import Page, ScrapeResult
from ..scraping.scrape_job import ScrapeJob
from ..scraping.scraper_executor import ScraperExecutor, shared_scraper_executor
from ..scraping.url_drop import UrlDrop
from .rehu_document_model import RehuDocumentModel

LOG: Final = logging.getLogger(__name__)

BUSY_MESSAGE: Final = "Downloading an image…"
"""What the banner says while at least one download is in flight."""

BUSY_PAGE_MESSAGE: Final = "Reading a page for its images…"
"""What the banner says while a dropped page is being scraped for :meth:`ImageDownloads.submit_page`."""

READ_FAILURE: Final = "Could not acquire a dropped image: {error}"
LOCAL_WRITE_FAILURE: Final = "Could not write a dropped image to disk: {error}"
DOWNLOAD_WRITE_FAILURE: Final = "Could not write a downloaded image to disk: {error}"
"""What an acquisition that fails on this side of the network says -- a dropped file that would not
read, or bytes in hand that would not write. The same sentence goes to the document's log and to its
banner, so a row on the banner can be found again in the log, traceback and all."""


class ImageDownloads(QObject):  # pylint: disable=too-many-instance-attributes
    """One document's acquired screenshots, however they arrived (#73).

    :meth:`submit` queues an `~rehuco_agent.scraping.image_download_job.ImageDownloadJob` per URL and
    writes the result to disk once it lands -- the single entry point for every URL this document ever
    downloads a screenshot from, whether it is a URL dropped directly on the images sub-dock or one of
    the ``ScrapedImage`` entries a scrape result carries (`.ScrapeActions`). :meth:`acquire_local` writes
    a drop's local files or its own image data the same way, synchronously, since there is no network
    wait to keep off the GUI thread for either. Both write through the same
    `~rehuco_agent.fields.image_organizer.ImageOrganizer` and the same discard rules.

    :meth:`submit_page` is the third entry point: a page URL (rather than an image URL), or a selection,
    dropped directly on the images sub-dock, scraped the same way `.ScrapeActions` scrapes one -- a
    selection's own HTML as the page, a bare URL fetched -- but with its ``fields`` and ``description``
    thrown away: only its ``images`` are handed to :meth:`submit`, one per image. What lets a user
    re-fetch a resource's screenshots from their source page -- a redesign, a broken link fixed, a
    higher-resolution asset -- without touching anything else the ``.rehu`` carries.

    **Every failure is a warning row on the banner**, not only a line in the log: a download that failed,
    a page no scraper reads, a dropped file that would not read, a write that was refused or failed.
    Failures are kept per **batch** -- everything one gesture set off: a drop's files, a page's images, a
    scrape's images -- so a batch that fails several ways shows each way once, and the next batch
    replaces them (:meth:`__begin_batch`).

    :param model: the document these downloads are about.
    :param image_organizer: what writes an acquired image's bytes to disk; ``None`` (a document with no
        path yet) refuses every submission outright.
    :param registry: where :meth:`submit_page` looks up a matching scraper; ``None`` uses the shared,
        process-wide instance.
    :param executor: what runs the downloads and the page scrapes; ``None`` uses the shared,
        process-wide instance.
    :param fetcher: what :meth:`submit_page` fetches a page with; ``None`` uses `ScrapeJob`'s own
        default (a real network fetch). Overridable for tests, the same reason `.ScrapeActions` takes
        one.
    :param parent: optional Qt parent.
    """

    changed = Signal()
    """Fires when :attr:`notice` may have changed -- what the document's banner rebuilds on."""

    acquired = Signal()
    """Fires once an image has actually been written to disk -- what
    `~rehuco_agent.documents.RehuDocumentModel.rescan_images` already reads the directory back
    through, and what a listener that tracks retained ``.orig`` backups
    (`.ConversionBackupActions`) rescans on: writing into an occupied slot backs the file already
    there up first, which is not a seam any of that class's own re-read triggers (a path change, a
    save, a lock-reason change) fires for on its own."""

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        model: RehuDocumentModel,
        image_organizer: ImageOrganizer | None,
        registry: ScraperRegistry | None = None,
        executor: ScraperExecutor | None = None,
        fetcher: PageFetcher | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.__model: Final = model
        self.__image_organizer: Final = image_organizer
        self.__registry: Final = registry if registry is not None else shared_scraper_registry()
        self.__executor: Final = executor if executor is not None else shared_scraper_executor()
        self.__fetcher: Final = fetcher
        self.__pending: Final[dict[ImageDownloadJob, Path]] = {}
        """Jobs submitted but not yet resolved, keyed to the path captured at submission -- kept alive
        for the same reason `.ScrapeActions.__pending` is, and read back to decide whether the document
        is still the one that asked."""

        self.__pending_pages: Final[dict[ScrapeJob, Path]] = {}
        """The page scrapes :meth:`submit_page` is waiting to hear back from, the same shape as
        :attr:`__pending` but for the job kind that only reads a page for its images."""

        self.__failures: Final[list[str]] = []
        """What the current batch has failed with so far, in the order it happened -- see
        :meth:`__begin_batch` for where a batch starts."""

        self.__detached = False
        """Set by :meth:`detach`. Checked explicitly for the same reason `.ScrapeActions.__detached`
        is: a job is kept alive by the very signal connection its result would arrive through."""

    # region What the document shows

    @property
    def notice(self) -> list[MessageBannerRow]:
        """The document's inline strip rows for a download or a page scrape in flight, then -- once
        nothing is running -- one warning row per distinct failure of the last batch."""
        rows: list[MessageBannerRow] = []
        if self.__pending_pages:
            rows.append(MessageBannerRow(MessageBannerSeverity.INFO, BUSY_PAGE_MESSAGE))
        if self.__pending:
            rows.append(MessageBannerRow(MessageBannerSeverity.INFO, BUSY_MESSAGE))
        if not self.__pending and not self.__pending_pages:
            # distinct, in the order they happened: a page whose every image hit the same full set
            # says so once, not once per image
            rows.extend(
                MessageBannerRow(MessageBannerSeverity.WARNING, failure) for failure in dict.fromkeys(self.__failures)
            )
        return rows

    def detach(self) -> None:
        """Stop reacting to this document's own downloads, for a document that is being closed.

        The jobs themselves keep running -- there is nothing to cancel a fetch for -- but their
        results are no longer applied once they land.
        """
        self.__detached = True
        self.__pending.clear()
        self.__pending_pages.clear()

    # endregion

    # region Submitting

    def submit(self, url: str, referrer: str | None, slot: int | None = None) -> None:
        """Queue a download for one image URL, under this document's log scope.

        :param url: the image's URL.
        :param referrer: the page to send as the download's ``Referer``, or ``None``.
        :param slot: the ``<stem>NN`` slot this image is destined for -- a scrape result's own
            numbering, or ``None`` for a plain drop, which takes the next free slot at write time.
        """
        path = self.__model.path
        if path is None:
            return
        self.__begin_batch()
        job = ImageDownloadJob(url, referrer, slot)
        self.__pending[job] = path  # pylint: disable=unsupported-assignment-operation
        job.result_ready.connect(lambda result: self.__on_result(job, path, result))
        job.failed.connect(lambda error: self.__on_failed(job, error))
        self.changed.emit()
        with LogScope.open(path):
            LOG.info("Downloading %s…", url)
            self.__executor.submit(job)

    def submit_page(self, drop: UrlDrop) -> None:
        """Scrape one page for its images, under this document's log scope.

        Re-fetches a resource's screenshots from the page they came from, without touching anything
        else the ``.rehu`` carries: the scraped ``fields`` and ``description`` are thrown away, and only
        ``images`` is read, each handed to :meth:`submit` in turn -- so a slot the page's own scraper
        still assigns the same way overwrites (backing the old file up first, never losing it outright)
        while every other field stays exactly as it was.

        :param drop: the parsed drop (`UrlDrop.parse`): a page's URL, not an image's, or a selection,
            whose own ``fragment`` is scraped as the page rather than fetched again -- exactly what
            `.ScrapeActions.submit` does with the same drop on the Main Editor.
        """
        path = self.__model.path
        if path is None:
            return
        self.__begin_batch()
        page = Page(url=drop.url, final_url=drop.url, html=drop.fragment) if drop.fragment is not None else None
        job = ScrapeJob(drop.url, self.__registry, page=page, fetcher=self.__fetcher)
        self.__pending_pages[job] = path  # pylint: disable=unsupported-assignment-operation
        job.result_ready.connect(lambda result: self.__on_page_result(job, path, result))
        job.failed.connect(lambda error: self.__on_page_failed(job, error))
        self.changed.emit()
        with LogScope.open(path):
            LOG.info("Reading %s for its images…", drop.url)
            self.__executor.submit(job)

    def acquire_local(self, sources: Sequence[Path | ImageBytes]) -> None:
        """Write a drop's local files, or its own image data, straight to disk -- no download involved.

        Synchronous, unlike :meth:`submit`: there is no network wait to keep off the GUI thread, only a
        read and a write per source. Takes the whole drop at once rather than one source per call, so a
        multi-file drop is one batch -- each file that fails keeps its own banner row -- and the resource
        is rescanned once, after the last write, rather than once per file. Refuses the same way
        :meth:`__on_result` discards a download's result -- no path, no organizer, or locked -- and
        reports the same way it does, under the same log scope.

        :param sources: the drop's local files, or its own image bytes, in the order to acquire them.
        """
        path = self.__model.path
        organizer = self.__image_organizer
        if path is None or self.__model.locked or organizer is None:
            return
        self.__begin_batch()
        written = False
        with LogScope.open(path):
            for source in sources:
                written = self.__acquire_one(organizer, source) or written
        if written:
            self.__model.rescan_images()
            self.acquired.emit()
        self.changed.emit()

    # endregion

    def __begin_batch(self) -> None:
        """Forget the last batch's failures, when nothing is still running.

        A submission made while anything is still in flight joins the batch already running instead:
        a page's images are submitted one after another, and the second must not erase what the first
        has already failed with.
        """
        if not self.__pending and not self.__pending_pages:
            self.__failures.clear()

    def __fail(self, message: str, *, with_traceback: bool = False) -> None:
        """Log ``message`` and keep it for the banner (:attr:`notice`).

        :param message: what failed -- the same sentence in the log and on the banner.
        :param with_traceback: log the exception being handled along with it: an unexpected ``OSError``
            from a write, rather than a refusal the message already explains in full.
        """
        if with_traceback:
            LOG.exception("%s", message)
        else:
            LOG.warning("%s", message)
        self.__failures.append(message)

    def __acquire_one(self, organizer: ImageOrganizer, source: Path | ImageBytes) -> bool:
        """Read one of :meth:`acquire_local`'s sources and write it, recording a failure rather than
        raising, so the rest of the drop still gets its turn.

        :param organizer: what writes the bytes.
        :param source: the local file or the drop's own image bytes.
        :returns: whether it was written.
        """
        try:
            acquired = acquire(source)
        except (OSError, NotAnImageError) as error:
            self.__fail(READ_FAILURE.format(error=error))
            return False
        try:
            organizer.acquire(acquired.data, acquired.extension)
        except OSError as error:
            self.__fail(LOCAL_WRITE_FAILURE.format(error=error), with_traceback=True)
            return False
        except ValueError as error:
            self.__fail(LOCAL_WRITE_FAILURE.format(error=error))
            return False
        return True

    def __on_result(self, job: ImageDownloadJob, submitted_path: Path, result: object) -> None:
        """Write a finished download's bytes to disk, or discard them, on the GUI thread.

        :param job: the job that just resolved, dropped from :attr:`__pending` either way.
        :param submitted_path: the document's path when ``job`` was submitted.
        :param result: the `~rehuco_agent.scraping.image_pipeline.AcquiredImage`.
        """
        self.__pending.pop(job, None)
        if self.__detached:
            return
        self.changed.emit()
        with LogScope.open(submitted_path):
            if self.__model.path != submitted_path:
                LOG.info("Discarding a downloaded image: the document is no longer at %s.", submitted_path)
                return
            if self.__model.locked:
                LOG.info("Discarding a downloaded image: the document is locked.")
                return
            if self.__image_organizer is None:
                LOG.info("Discarding a downloaded image: this resource has nowhere to write it.")
                return
            # not a runtime check: result_ready's payload is always an AcquiredImage, by
            # ImageDownloadJob's own contract -- see ScrapeActions.__on_result's matching cast
            acquired = cast(AcquiredImage, result)
            try:
                self.__image_organizer.acquire(acquired.data, acquired.extension, job.slot)
            except OSError as error:
                self.__fail(DOWNLOAD_WRITE_FAILURE.format(error=error), with_traceback=True)
                self.changed.emit()
                return
            except ValueError as error:
                self.__fail(DOWNLOAD_WRITE_FAILURE.format(error=error))
                self.changed.emit()
                return
            self.__model.rescan_images()
        self.acquired.emit()

    def __on_failed(self, job: ImageDownloadJob, error: object) -> None:
        """Record a download's failure for the banner, on the GUI thread.

        Not logged here: `~rehuco_agent.scraping.image_download_job.ImageDownloadJob.run` already logged
        it, on the worker, under the scope the download was submitted in.

        :param job: the job that just failed, dropped from :attr:`__pending` either way.
        :param error: the exception `~rehuco_agent.scraping.image_download_job.ImageDownloadJob.run`
            caught.
        """
        self.__pending.pop(job, None)
        if self.__detached:
            return
        self.__failures.append(str(error))
        self.changed.emit()

    def __on_page_result(self, job: ScrapeJob, submitted_path: Path, result: object) -> None:
        """Submit one download per scraped image, discarding the page's fields and description, on the
        GUI thread.

        The same discard rules :meth:`__on_result` applies to a finished download apply here first --
        there would be nothing to hand the images on to otherwise.

        :param job: the job that just resolved, dropped from :attr:`__pending_pages` either way.
        :param submitted_path: the document's path when ``job`` was submitted.
        :param result: the `~rehuco_agent.scraping.results.ScrapeResult`.
        """
        self.__pending_pages.pop(job, None)
        if self.__detached:
            return
        self.changed.emit()
        with LogScope.open(submitted_path):
            if self.__model.path != submitted_path:
                LOG.info("Discarding a page's images: the document is no longer at %s.", submitted_path)
                return
            if self.__model.locked:
                LOG.info("Discarding a page's images: the document is locked.")
                return
            # not a runtime check: result_ready's payload is always a ScrapeResult, by ScrapeJob's own
            # contract -- see ScrapeActions.__on_result's matching cast
            images = cast(ScrapeResult, result).images
            for image in images:
                self.submit(image.url, image.referrer, image.slot)

    def __on_page_failed(self, job: ScrapeJob, error: object) -> None:
        """Record a page scrape's failure for the banner, on the GUI thread.

        :param job: the job that just failed, dropped from :attr:`__pending_pages` either way.
        :param error: the `~rehuco_agent.scraping.scrape_job.ScrapeError` `ScrapeJob.run` caught.
        """
        self.__pending_pages.pop(job, None)
        if self.__detached:
            return
        self.__failures.append(str(error))
        self.changed.emit()
