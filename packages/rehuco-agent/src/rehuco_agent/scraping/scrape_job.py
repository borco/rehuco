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
from .results import Page

LOG: Final = logging.getLogger(__name__)


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

        Never fires when no scraper matched, when a matching scraper needs the browser fetcher, or when
        the fetch failed -- each of those is logged instead. Applying the result to an editor, and
        discarding it if the document has since closed or been renamed, is the caller's job.
        """
        return self.__marshaller.result_ready

    def run(self) -> None:
        """Do the work: resolve, fetch, parse, emit.

        Runs on whatever thread `ScraperExecutor` hands it to. Touches no widget directly -- the result
        crosses back to the GUI thread through :attr:`result_ready`'s queued connection.

        The blanket catch is the point rather than a shortcut, the same one `BackgroundMeasurement`
        makes: `matches` and `scrape_page` are user-written code, an exception escaping a pool thread
        is printed by the pool and reaches no log dock, and the document's log is the one place a
        broken script can be diagnosed from.
        """
        try:
            self.__scrape()
        except Exception:  # pylint: disable=broad-exception-caught
            LOG.exception("Scraping %s failed.", self.__url)

    def __scrape(self) -> None:
        """The steps of :meth:`run`, in order: resolve, refuse or fetch, re-resolve a redirect, parse,
        emit.
        """
        scraper = self.__registry.find(self.__url)
        if scraper is None:
            LOG.warning("No scraper matches %s.", self.__url)
            return
        if scraper.needs_browser:
            LOG.warning(
                "%s needs the browser fetcher, which this build does not have; %s was not scraped.",
                scraper.label,
                self.__url,
            )
            return
        page = self.__page if self.__page is not None else self.__fetch(self.__url)
        if page is None:
            return
        if page.final_url != self.__url:
            redirected = self.__registry.find(page.final_url)
            if redirected is not None and redirected.needs_browser:
                LOG.warning(
                    "%s needs the browser fetcher, which this build does not have; %s was not scraped.",
                    redirected.label,
                    self.__url,
                )
                return
            if redirected is not None:
                scraper = redirected
        result = scraper.scrape_page(page)
        self.__marshaller.scraped.emit(result)

    def __fetch(self, url: str) -> Page | None:
        """Fetch ``url``, logging and swallowing a failure rather than letting it crash the pool thread.

        :param url: the address to fetch.
        :returns: the fetched page, or `None` when the fetch failed.
        """
        try:
            return self.__fetcher.fetch(url)
        except RequestException as error:
            LOG.warning("Could not fetch %s: %s", url, error)
            return None
