"""The scrape itself: fetch, dispatch, parse, hand the result to the GUI thread
([[acquisition-tooling#scrape-job]]).
"""

import logging
from typing import Final

from PySide6.QtCore import QObject, Qt, Signal, SignalInstance
from requests import RequestException

from .http_fetcher import HttpPageFetcher
from .protocols import PageFetcher
from .registry import ScraperRegistry
from .results import InvalidScrapeResultError, Page, ScrapeResult

LOG: Final = logging.getLogger(__name__)


class ScrapeError(Exception):
    """A scrape could not produce a result -- no scraper matched, a matching scraper needs the browser
    fetcher, the fetch failed, or the scraper's own result failed `~.results.SCRAPE_RESULT_SCHEMA`.

    Raised by `ScrapeJob.scrape`, the synchronous half both `ScrapeJob.run` (which logs it instead of
    letting it escape a pool thread) and the ``--scrape`` CLI (which prints it and exits 1) consume."""


class ScrapeJob:
    """Fetches one page (or takes an already-fetched one), dispatches it to a matching scraper, and
    hands the result to the GUI thread.

    **Not a `TaskJob`, and never enqueued on the app-wide `rehuco_core.TaskQueue`**
    ([[acquisition-tooling#scrape-job]]): that queue is a single worker running one job at a time,
    right for a checksum sweep or a catalog import measured in hours, wrong for an interactive fetch
    that must not wait behind one -- a `ScrapeJob` instead runs on `ScraperExecutor`'s dedicated pool,
    where several run concurrently. It carries none of `TaskJob`'s label/progress/pause/cancel/resume
    machinery, and is not something the Tasks dock ever lists -- its only visible trace is its log
    lines.

    Constructed for one specific `url`, not for a document: dispatch is purely host-based
    (`ScraperRegistry.find`) and picking out what a result's fields mean for a particular open
    document happens where the result is applied, not here -- so this class carries no resource-type
    argument and no document identity at all.

    :param url: the URL to scrape.
    :param registry: where to look up a matching scraper.
    :param page: an already-fetched page (the dropped-fragment path,
        [[acquisition-tooling#drag-drop-aids]]) -- when given, :attr:`fetcher` is never called.
    :param fetcher: what fetches ``url`` when no ``page`` is given.
    """

    def __init__(
        self,
        url: str,
        registry: ScraperRegistry,
        *,
        page: Page | None = None,
        fetcher: PageFetcher | None = None,
    ) -> None:
        self.__url: Final = url
        self.__registry: Final = registry
        self.__page: Final = page
        self.__fetcher: Final = fetcher if fetcher is not None else HttpPageFetcher()
        self.__marshaller: Final = ScrapeJob.Marshaller()

    class Marshaller(QObject):
        """Carries a finished scrape's result across the thread boundary, and nothing else.

        Nested and undocumented outside this class for the same reason
        `rehuco_agent.tasks.TaskQueueModel.Marshaller` is: a mangled class name is not one Qt or the
        linters will accept, and nothing outside `ScrapeJob` has a reason to build one.

        Two signals rather than one: :attr:`scraped` fires on whichever thread the scrape ran on and is
        connected, with an explicit `Qt.ConnectionType.QueuedConnection`, to :meth:`__relay`, which
        re-emits :attr:`result_ready` -- so that one always fires on the GUI thread, whatever kind of
        object connects to it (a plain callable included, which `AutoConnection` would run on the
        worker thread instead).
        """

        scraped = Signal(object)
        """Fires with the `ScrapeResult`, on the worker thread. Not for callers outside `ScrapeJob`."""

        result_ready = Signal(object)
        """Fires with the `ScrapeResult`, always on the GUI thread. What `ScrapeJob.result_ready`
        exposes."""

        def __init__(self) -> None:
            super().__init__()
            self.scraped.connect(self.__relay, Qt.ConnectionType.QueuedConnection)

        def __relay(self, result: object) -> None:
            """Re-emit :attr:`result_ready`, on the GUI thread by construction of the connection above.

            :param result: the `ScrapeResult` :attr:`scraped` carried.
            """
            self.result_ready.emit(result)

    @property
    def result_ready(self) -> SignalInstance:
        """Fires on the GUI thread with the scraped `ScrapeResult`, exactly once, only on success.

        Never fires when no scraper matched, when a matching scraper needs the browser fetcher, when the
        fetch failed, or when the scraper's own result failed the scrape-result schema -- each of those
        is logged instead (:meth:`scrape` raises `ScrapeError` for all four, :meth:`run` catches and
        logs it). Applying the result to an editor, and discarding it if the document has since closed
        or been renamed, is the caller's job.
        """
        return self.__marshaller.result_ready

    def run(self) -> None:
        """Do the work: resolve, fetch, parse, validate, emit.

        Runs on whatever thread `ScraperExecutor` hands it to. Touches no widget directly -- the result
        crosses back to the GUI thread through :attr:`result_ready`'s queued connection.

        The blanket catch is the point rather than a shortcut, the same one `BackgroundMeasurement`
        makes: `matches` and `scrape_page` are user-written code, an exception escaping a pool thread
        is printed by the pool and reaches no log dock, and the document's log is the one place a
        broken script can be diagnosed from. A `ScrapeError` -- an expected refusal or a bad result --
        is logged as a warning rather than with a traceback; anything else still gets `LOG.exception`.
        """
        try:
            self.__marshaller.scraped.emit(self.scrape())
        except ScrapeError as error:
            LOG.warning(str(error))
        except Exception:  # pylint: disable=broad-exception-caught
            LOG.exception("Scraping %s failed.", self.__url)

    def scrape(self) -> ScrapeResult:
        """Resolve, refuse or fetch, re-resolve a redirect, parse, validate -- the synchronous half of
        :meth:`run`, and what the ``--scrape`` CLI calls directly.

        :returns: the scraper's result, validated against `~.results.SCRAPE_RESULT_SCHEMA`
            (`~.results.ScrapeResult.coerce`).
        :raises ScrapeError: no scraper matches, the matching scraper (direct or after a redirect) needs
            the browser fetcher, the fetch failed, or the result failed the schema.
        """
        scraper = self.__registry.find(self.__url)
        if scraper is None:
            raise ScrapeError(f"No scraper matches {self.__url}.")
        if scraper.needs_browser:
            raise ScrapeError(
                f"{scraper.label} needs the browser fetcher, which this build does not have; "
                f"{self.__url} was not scraped."
            )
        page = self.__page if self.__page is not None else self.__fetch(self.__url)
        if page.final_url != self.__url:
            redirected = self.__registry.find(page.final_url)
            if redirected is not None and redirected.needs_browser:
                raise ScrapeError(
                    f"{redirected.label} needs the browser fetcher, which this build does not have; "
                    f"{self.__url} was not scraped."
                )
            if redirected is not None:
                scraper = redirected
        raw_result = scraper.scrape_page(page)
        try:
            return ScrapeResult.coerce(raw_result)
        except InvalidScrapeResultError as error:
            raise ScrapeError(f"{scraper.label} returned an invalid result for {self.__url}: {error}") from error

    def __fetch(self, url: str) -> Page:
        """Fetch ``url``, wrapping a failure as a `ScrapeError` rather than letting it crash the pool
        thread.

        :param url: the address to fetch.
        :returns: the fetched page.
        :raises ScrapeError: the fetch failed.
        """
        try:
            return self.__fetcher.fetch(url)
        except RequestException as error:
            raise ScrapeError(f"Could not fetch {url}: {error}") from error
