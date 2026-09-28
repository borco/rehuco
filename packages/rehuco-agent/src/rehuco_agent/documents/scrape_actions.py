"""A URL dropped on the Main Editor dock, queued and applied as a reviewable field edit
([[acquisition-tooling#drag-drop-aids]], #272).

**Not the app-wide task queue.** A scrape runs on `~rehuco_agent.scraping.scraper_executor.ScraperExecutor`'s
own pool, submitted under this document's log scope so its fetch and parse are readable alongside the
app-wide log ([[acquisition-tooling#scrape-job]]).

**A result is applied only on the GUI thread, and only if the document is still open at the same path**
([[acquisition-tooling#scrape-job]]): a document closed or renamed while its page was being fetched simply
discards the result, logged under the scope it was submitted in.

**Every attempt is a scheduled attempt** (#368): a drop schedules its first attempt with no delay, and a
scraper asking for the page again (`~rehuco_agent.scraping.protocols.RefetchRequestedError`) schedules the
next one after a pause, on a single-shot `QTimer` here -- never a sleep on a pool worker, which would hold
one of its few slots for nothing.
"""

import logging
import math
import random
import time
from collections.abc import Callable
from pathlib import Path
from typing import Final, cast
from urllib.parse import urlsplit

from borco_core.logging import LogScope
from borco_pyside.widgets import MessageBannerRow, MessageBannerSeverity
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction

from ..scraping.markdown_images import substitute_image_stem
from ..scraping.protocols import PageFetcher, RefetchRequestedError
from ..scraping.registry import ScraperRegistry, shared_scraper_registry
from ..scraping.results import Page, ScrapeResult
from ..scraping.scrape_job import (
    MAX_REFETCHES,
    REFETCH_COUNTDOWN_MESSAGE,
    REFETCH_GAVE_UP_MESSAGE,
    ScrapeJob,
    refetch_delay,
)
from ..scraping.scraper_executor import ScraperExecutor, shared_scraper_executor
from ..scraping.url_drop import UrlDrop
from .document_fields import declared_field_names
from .image_downloads import ImageDownloads
from .rehu_document_model import RehuDocumentModel

LOG: Final = logging.getLogger(__name__)

BUSY_MESSAGE: Final = "Scraping {host}…"
"""What the banner says while a drop's scrape is in flight."""

CANCEL_TEXT: Final = "Cancel"
"""The label of a waiting re-fetch's banner action."""

COUNTDOWN_TICK_MS: Final = 1000
"""How often a waiting re-fetch's banner row is re-said, so its countdown reads down a second at a time."""


class ScrapeActions(QObject):  # pylint: disable=too-many-instance-attributes
    """One document's scrape-on-drop: submits a `ScrapeJob` for a dropped `UrlDrop`, and applies its
    result as an ordinary dirty edit once it lands ([[acquisition-tooling#drag-drop-aids]]).

    **Applying a result never re-checks a value.** `ScrapeJob.scrape` already validated the whole result
    against the scrape-result schema before `result_ready` fired ([[acquisition-tooling#scraper-protocols]]),
    so this class only decides *which* fields this document's active type declares -- a field the result
    carries that the type does not is skipped, logged, never written.

    **Images go through `.ImageDownloads`** (#73), the same seam a URL dropped directly on the images
    sub-dock uses: this class only hands over each `~rehuco_agent.scraping.results.ScrapedImage`'s URL,
    referrer and slot, and never touches a file itself.

    **A re-fetch waits here, visibly** (#368): while one is pending, its banner row counts down to the
    next attempt and carries a **Cancel** action. At most `~.scrape_job.MAX_REFETCHES` are made per drop;
    after that, the last request's reason becomes the drop's failure row. A waiting re-fetch is also
    dropped when the document closes (:meth:`detach`) or its path changes.

    :param model: the document these actions are about.
    :param image_downloads: where a result's images are handed off.
    :param registry: where to look up a matching scraper; `None` uses the shared, process-wide instance.
    :param executor: what runs the scrape; `None` uses the shared, process-wide instance.
    :param fetcher: what fetches a URL drop's page when it carries no fragment; `None` uses
        `~.scrape_job.ScrapeJob`'s own default (`~.http_fetcher.HttpPageFetcher`) -- a real network
        fetch. Overridable for tests, the same reason `ScrapeJob` itself takes one.
    :param choose_delay: draws from a re-fetch's ``(min, max)`` range, which `~.scrape_job.refetch_delay`
        scales by how many re-fetches came before; `None` uses `random.uniform`. Overridable so a test
        never really waits.
    :param clock: a monotonic clock in seconds, what a countdown is measured against; `None` uses
        `time.monotonic`. Overridable so a test can read the countdown at a moment of its choosing.
    :param parent: optional Qt parent.
    """

    changed = Signal()
    """Fires when :attr:`notice` may have changed -- what the document's banner rebuilds on."""

    class Chain:  # pylint: disable=too-many-instance-attributes,too-few-public-methods
        """One drop's attempts, from its first fetch to its outcome.

        Nested for the same reason `~.scrape_job.ScrapeJob.Marshaller` is: nothing outside
        `ScrapeActions` has a reason to build one.

        :param owner: the Qt parent of the chain's timer and action.
        :param path: the document's path when the drop was submitted.
        :param url: the URL the first attempt scrapes.
        :param page: the dropped fragment, handed to the first attempt only -- a re-fetch always fetches.
        """

        def __init__(self, owner: QObject, path: Path, url: str, page: Page | None) -> None:
            self.path: Final = path
            self.url = url
            self.page = page
            self.attempt = 1
            self.message = ""
            self.job: ScrapeJob | None = None
            """The attempt in flight -- kept alive because `ScraperExecutor.submit` requires it (the
            runnable is auto-deleted before the queued signal is delivered). `None` while the next attempt
            is only scheduled."""
            self.deadline: float | None = None
            """When a waiting re-fetch launches, on the owner's clock; `None` while nothing is waiting."""
            self.timer: Final = QTimer(owner)
            self.timer.setSingleShot(True)
            self.cancel_action: Final = QAction(CANCEL_TEXT, owner)

        def dispose(self) -> None:
            """Stop the timer and release the chain's Qt objects."""
            self.timer.stop()
            self.timer.deleteLater()
            self.cancel_action.deleteLater()

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        model: RehuDocumentModel,
        image_downloads: ImageDownloads,
        registry: ScraperRegistry | None = None,
        executor: ScraperExecutor | None = None,
        fetcher: PageFetcher | None = None,
        choose_delay: Callable[[float, float], float] | None = None,
        clock: Callable[[], float] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.__model: Final = model
        self.__image_downloads: Final = image_downloads
        self.__registry: Final = registry if registry is not None else shared_scraper_registry()
        self.__executor: Final = executor if executor is not None else shared_scraper_executor()
        self.__fetcher: Final = fetcher
        self.__choose_delay: Final = choose_delay if choose_delay is not None else random.uniform
        self.__clock: Final = clock if clock is not None else time.monotonic
        self.__chains: Final[list[ScrapeActions.Chain]] = []
        """Drops not yet resolved. Membership is what every arriving signal is checked against, rather
        than relying on dropping this object's own reference to a job: a job is kept alive by the very
        signal connection its outcome would arrive through (a closure over ``job`` connected to ``job``'s
        own signal), a reference cycle Python's cyclic collector does not promise to break before that
        queued signal is delivered."""

        self.__last_failure = ""
        self.__tick: Final = QTimer(self)
        self.__tick.setInterval(COUNTDOWN_TICK_MS)
        self.__tick.timeout.connect(self.changed)
        model.path_changed.connect(self.__on_path_changed)  # type: ignore[attr-defined]

    # region What the document shows

    @property
    def notice(self) -> list[MessageBannerRow]:
        """The document's inline strip rows: one per drop not yet resolved -- the busy row while an
        attempt is in flight, or a countdown with a **Cancel** action while a re-fetch waits -- followed by
        the last failure as a warning, if one stands and nothing is running, replaced by the next drop's
        own outcome. A page no scraper matches is a failure like any other: the drop did not do what it
        was dropped for."""
        rows: list[MessageBannerRow] = []
        for chain in self.__chains:
            if chain.deadline is None:
                host = urlsplit(chain.url).hostname or chain.url
                rows.append(MessageBannerRow(MessageBannerSeverity.INFO, BUSY_MESSAGE.format(host=host)))
                continue
            text = REFETCH_COUNTDOWN_MESSAGE.format(
                message=chain.message,
                url=chain.url,
                seconds=max(0, math.ceil(chain.deadline - self.__clock())),
                attempt=chain.attempt,
                attempts=MAX_REFETCHES + 1,
            )
            rows.append(MessageBannerRow(MessageBannerSeverity.WARNING, text, chain.cancel_action))
        if not self.__chains and self.__last_failure:
            rows.append(MessageBannerRow(MessageBannerSeverity.WARNING, self.__last_failure))
        return rows

    def detach(self) -> None:
        """Stop reacting to this document's own scrapes, for a document that is being closed.

        An attempt in flight keeps running -- there is nothing to cancel a fetch-and-parse for -- but its
        outcome is no longer applied once it lands, the same discard a path change already gets; a
        re-fetch still waiting is dropped outright.
        """
        for chain in self.__chains:
            chain.dispose()
        self.__chains.clear()
        self.__tick.stop()

    # endregion

    # region Submitting

    def submit(self, drop: UrlDrop) -> None:
        """Queue a scrape for a dropped URL, under this document's log scope.

        :param drop: the parsed drop (`UrlDrop.parse`).
        """
        path = self.__model.path
        if path is None:
            return
        page = Page(url=drop.url, final_url=drop.url, html=drop.fragment) if drop.fragment is not None else None
        chain = ScrapeActions.Chain(self, path, drop.url, page)
        chain.timer.timeout.connect(lambda: self.__launch(chain))
        # queued, so the banner button that triggered it is not rebuilt away inside its own click
        chain.cancel_action.triggered.connect(lambda: self.__cancel(chain), Qt.ConnectionType.QueuedConnection)
        self.__chains.append(chain)
        self.__last_failure = ""
        self.changed.emit()
        chain.timer.start(0)

    def __launch(self, chain: ScrapeActions.Chain) -> None:
        """Run a chain's next attempt: one `ScrapeJob`, submitted under the document's log scope.

        :param chain: the chain whose timer just fired -- always still pending, since ending a chain stops
            its timer first (`Chain.dispose`).
        """
        job = ScrapeJob(chain.url, self.__registry, page=chain.page, fetcher=self.__fetcher)
        chain.page = None
        chain.job = job
        chain.deadline = None
        job.result_ready.connect(lambda result: self.__on_result(chain, job, result))
        job.failed.connect(lambda error: self.__on_failed(chain, job, error))
        job.refetch_requested.connect(lambda request: self.__on_refetch(chain, job, request))
        self.__update_tick()
        self.changed.emit()
        with LogScope.open(chain.path):
            if chain.attempt == 1:
                LOG.info("Scraping %s…", chain.url)
            else:
                LOG.info("Scraping %s (attempt %d of %d)…", chain.url, chain.attempt, MAX_REFETCHES + 1)
            self.__executor.submit(job)

    # endregion

    # region Outcomes

    def __is_current(self, chain: ScrapeActions.Chain, job: ScrapeJob) -> bool:
        """Whether ``job`` is still the attempt ``chain`` is waiting on -- `False` once the chain was
        cancelled, detached or ended.

        :param chain: the chain the outcome belongs to.
        :param job: the job the outcome came from.
        :returns: whether the outcome should be acted on.
        """
        return chain in self.__chains and chain.job is job

    def __on_result(self, chain: ScrapeActions.Chain, job: ScrapeJob, result: object) -> None:
        """Apply a finished scrape's result, or discard it, on the GUI thread.

        :param chain: the chain the result ends.
        :param job: the job that just resolved.
        :param result: the `ScrapeResult`.
        """
        if not self.__is_current(chain, job):
            return
        self.__end(chain)
        self.changed.emit()
        # the scope the scrape was submitted under, re-opened by hand: this runs on the GUI thread off a
        # queued signal, which inherits nothing from the worker the job's own records were made on, so
        # what is said about applying (or discarding) the result would otherwise reach the app-wide log
        # alone and never the document's ([[appendices.logging#scopes]])
        with LogScope.open(chain.path):
            if self.__model.path != chain.path:
                LOG.info("Discarding a scrape result: the document is no longer at %s.", chain.path)
                return
            if self.__model.locked:
                LOG.info("Discarding a scrape result: the document is locked.")
                return
            # not a runtime check: result_ready's payload is always a ScrapeResult, by ScrapeJob's own
            # contract -- Signal(object) is what PySide6 requires for a payload's exact type to survive
            # the C++ boundary at all (Qt's meta-object system has no template signals), so this cast is
            # purely for pyright, the same reason ScrapeJob.result_ready's own docstring states it.
            self.__apply(job, cast(ScrapeResult, result))

    def __on_failed(self, chain: ScrapeActions.Chain, job: ScrapeJob, error: object) -> None:
        """Record a scrape's refusal for the banner, on the GUI thread.

        :param chain: the chain the failure ends.
        :param job: the job that just failed.
        :param error: the `ScrapeError`.
        """
        if not self.__is_current(chain, job):
            return
        self.__end(chain)
        self.__last_failure = str(error)
        self.changed.emit()

    def __on_refetch(self, chain: ScrapeActions.Chain, job: ScrapeJob, request: object) -> None:
        """Schedule a chain's next attempt, or end it once its re-fetches are spent, on the GUI thread.

        :param chain: the chain that asked.
        :param job: the job that asked.
        :param request: the normalized `~.protocols.RefetchRequestedError`.
        """
        if not self.__is_current(chain, job):
            return
        # not a runtime check: refetch_requested's payload is always a normalized RefetchRequestedError,
        # by ScrapeJob's own contract -- the same Signal(object) reason as __on_result's cast
        refetch = cast(RefetchRequestedError, request)
        with LogScope.open(chain.path):
            if self.__model.path != chain.path:
                LOG.info("Discarding a re-fetch request: the document is no longer at %s.", chain.path)
                self.__end(chain)
                self.changed.emit()
                return
            if chain.attempt > MAX_REFETCHES:
                self.__end(chain)
                self.__last_failure = REFETCH_GAVE_UP_MESSAGE.format(message=refetch.message, count=MAX_REFETCHES + 1)
                LOG.warning(self.__last_failure)
                self.changed.emit()
                return
            # the attempt that just asked is the re-fetch count so far plus one, so it names this re-fetch
            delay = refetch_delay(cast(tuple[float, float], refetch.delay), chain.attempt, self.__choose_delay)
            chain.attempt += 1
            chain.url = cast(str, refetch.url)
            chain.message = refetch.message
            chain.job = None
            chain.deadline = self.__clock() + delay
            LOG.info(
                "%s; trying %s in %.1f s (attempt %d of %d).",
                refetch.message,
                chain.url,
                delay,
                chain.attempt,
                MAX_REFETCHES + 1,
            )
        chain.timer.start(round(delay * 1000))
        self.__update_tick()
        self.changed.emit()

    def __cancel(self, chain: ScrapeActions.Chain) -> None:
        """Drop a waiting re-fetch, from its banner row's **Cancel** action.

        :param chain: the chain to drop.
        """
        if chain not in self.__chains:
            return
        with LogScope.open(chain.path):
            LOG.info("Cancelled the re-fetch of %s.", chain.url)
        self.__end(chain)
        self.changed.emit()

    def __on_path_changed(self, _path: Path | None) -> None:
        """Drop every re-fetch still waiting: the document it would land on is no longer the one that
        asked. An attempt already in flight is left to land, and be discarded by :meth:`__on_result`'s own
        path check."""
        waiting = [chain for chain in self.__chains if chain.job is None]
        for chain in waiting:
            with LogScope.open(chain.path):
                LOG.info("Dropping the scrape of %s: the document is no longer at %s.", chain.url, chain.path)
            self.__end(chain)
        if waiting:
            self.changed.emit()

    def __end(self, chain: ScrapeActions.Chain) -> None:
        """Forget a chain and release its Qt objects.

        :param chain: the chain that just resolved or was dropped.
        """
        self.__chains.remove(chain)
        chain.dispose()
        self.__update_tick()

    def __update_tick(self) -> None:
        """Run the countdown tick exactly while some re-fetch is waiting."""
        if any(chain.deadline is not None for chain in self.__chains):
            if not self.__tick.isActive():
                self.__tick.start()
        else:
            self.__tick.stop()

    # endregion

    def __apply(self, job: ScrapeJob, result: ScrapeResult) -> None:
        """Write a validated result's fields, description and source onto the model, as an ordinary
        dirty edit.

        :param job: the job the result came from -- its :attr:`~.scrape_job.ScrapeJob.publisher` and
            :attr:`~.scrape_job.ScrapeJob.page_url` become the added source.
        :param result: the result to apply.
        """
        declared = declared_field_names(self.__model)
        for name, value in result.fields.items():
            if name in {"description", "url"}:
                continue
            if name not in declared:
                LOG.info("%s is not a field of this document's type; left unset.", name)
                continue
            setattr(self.__model, name, value)
        # a scraped `url` is a source, not a field write: a scraper that recognizes a canonical URL for
        # the page it read (ArtStation's store host, #366) hands it over here, and it goes through the
        # same add-or-fill path as the page itself, ahead of it -- so it fills an empty primary, or is
        # kept beside whatever sources the document already has, never overwriting one
        # ([[field-schema#sources]])
        canonical_url = result.fields.get("url")
        if isinstance(canonical_url, str) and canonical_url:
            self.__model.add_source(cast(str, job.publisher), canonical_url)
        description = result.description
        if description is None:
            raw = result.fields.get("description")
            description = raw if isinstance(raw, str) else None
        else:
            description = substitute_image_stem(description, self.__model.current_name)
        if description is not None and "description" in declared:
            self.__model.description = description
        # not a runtime check: both are set together, unconditionally, by the time scrape() returns the
        # result __apply is only ever called with -- see ScrapeJob.publisher/page_url's own docstrings
        self.__model.add_source(cast(str, job.publisher), cast(str, job.page_url))
        for image in result.images:
            self.__image_downloads.submit(image.url, image.referrer, image.slot)
