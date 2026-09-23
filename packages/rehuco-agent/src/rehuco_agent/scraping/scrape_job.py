"""The scrape itself: fetch, dispatch, parse, hand the result to the GUI thread
([[acquisition-tooling#scrape-job]]).
"""

import logging
from typing import Final
from urllib.parse import urlsplit

from PySide6.QtCore import QObject, Qt, Signal, SignalInstance
from requests import RequestException

from ..settings.scrapers_settings import ScrapersSettings, shared_scrapers_settings
from .browser_fetcher import BrowserPageFetcher
from .http_fetcher import HttpPageFetcher
from .protocols import FetchError, LoginRequiredError, PageFetcher
from .registry import ScraperRegistry
from .results import InvalidScrapeResultError, Page, ScrapeResult

LOG: Final = logging.getLogger(__name__)


class ScrapeError(Exception):
    """A scrape could not produce a result -- no scraper matched, the fetch failed, or the scraper's
    own result failed `~.results.SCRAPE_RESULT_SCHEMA`.

    Raised by `ScrapeJob.scrape`, the synchronous half both `ScrapeJob.run` (which logs it instead of
    letting it escape a pool thread) and the ``--scrape`` CLI (which prints it and exits 1) consume."""


class NoScraperError(ScrapeError):
    """No scraper matches the URL's host -- the one refusal that means a script is missing rather than
    broken, so a drop reports it by host ([[acquisition-tooling#drag-drop-aids]]) in the same words the
    ``--scrape`` CLI prints.

    :param url: the URL nothing matched.
    """

    def __init__(self, url: str) -> None:
        self.host: Final = urlsplit(url).hostname or url
        super().__init__(f"No scraper matches {self.host} ({url}).")


class LoginRequiredScrapeError(ScrapeError):
    """The fetched page was a login wall ([[acquisition-tooling#browser-persona]]) -- raised as
    `~.protocols.LoginRequiredError` by a scraper's own parsing, or by `~.http_fetcher.HttpPageFetcher`
    on a ``401``/``403``.

    :param label: the scraper that hit the login wall.
    :param host: the host that needs a login.
    """

    def __init__(self, label: str, host: str) -> None:
        super().__init__(f"{label} needs a login: open the browser from Settings ▸ Scrapers and log in to {host}.")


class ScrapeJob:  # pylint: disable=too-many-instance-attributes
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
        [[acquisition-tooling#drag-drop-aids]]) -- when given, no fetcher is ever called.
    :param fetcher: what fetches ``url`` when no ``page`` is given, overriding the dispatch below --
        `None` (every caller but a test) resolves one from `settings` instead:
        `~.http_fetcher.HttpPageFetcher` unless the matching scraper needs the browser
        ([[acquisition-tooling#browser-persona]]), in which case `~.browser_fetcher.BrowserPageFetcher`.
    :param settings: where the browser choice and the per-scraper **Use browser** picks come from;
        `None` reads the shared, process-wide settings, the shape every caller but a test wants.
    """

    def __init__(
        self,
        url: str,
        registry: ScraperRegistry,
        *,
        page: Page | None = None,
        fetcher: PageFetcher | None = None,
        settings: ScrapersSettings | None = None,
    ) -> None:
        self.__url: Final = url
        self.__registry: Final = registry
        self.__page: Final = page
        self.__forced_fetcher: Final = fetcher
        self.__settings: Final = settings if settings is not None else shared_scrapers_settings()
        self.__marshaller: Final = ScrapeJob.Marshaller()
        self.__publisher: str | None = None
        self.__page_url: str | None = None

    class Marshaller(QObject):
        """Carries a finished scrape's result across the thread boundary, and nothing else.

        Nested and undocumented outside this class for the same reason
        `rehuco_agent.tasks.TaskQueueModel.Marshaller` is: a mangled class name is not one Qt or the
        linters will accept, and nothing outside `ScrapeJob` has a reason to build one.

        Two pairs of signals rather than two: :attr:`scraped`/:attr:`failure` fire on whichever thread
        the scrape ran on and are each connected, with an explicit `Qt.ConnectionType.QueuedConnection`,
        to a relay that re-emits :attr:`result_ready`/:attr:`failed` -- so those two always fire on the
        GUI thread, whatever kind of object connects to them (a plain callable included, which
        `AutoConnection` would run on the worker thread instead).
        """

        scraped = Signal(object)
        """Fires with the `ScrapeResult`, on the worker thread. Not for callers outside `ScrapeJob`."""

        failure = Signal(object)
        """Fires with the `ScrapeError`, on the worker thread. Not for callers outside `ScrapeJob`."""

        result_ready = Signal(object)
        """Fires with the `ScrapeResult`, always on the GUI thread. What `ScrapeJob.result_ready`
        exposes."""

        failed = Signal(object)
        """Fires with the `ScrapeError`, always on the GUI thread. What `ScrapeJob.failed` exposes."""

        def __init__(self) -> None:
            super().__init__()
            self.scraped.connect(self.__relay_result, Qt.ConnectionType.QueuedConnection)
            self.failure.connect(self.__relay_failure, Qt.ConnectionType.QueuedConnection)

        def __relay_result(self, result: object) -> None:
            """Re-emit :attr:`result_ready`, on the GUI thread by construction of the connection above.

            :param result: the `ScrapeResult` :attr:`scraped` carried.
            """
            self.result_ready.emit(result)

        def __relay_failure(self, error: object) -> None:
            """Re-emit :attr:`failed`, on the GUI thread by construction of the connection above.

            :param error: the `ScrapeError` :attr:`failure` carried.
            """
            self.failed.emit(error)

    @property
    def result_ready(self) -> SignalInstance:
        """Fires on the GUI thread with the scraped `ScrapeResult`, exactly once, only on success.

        Never fires when no scraper matched, when the fetch failed or landed on a login wall, or when
        the scraper's own result failed the scrape-result schema -- each of those is logged instead
        (:meth:`scrape` raises `ScrapeError` for all, :meth:`run` catches and logs it). Applying the
        result to an editor, and discarding it if the document has since closed or been renamed, is the
        caller's job.
        """
        return self.__marshaller.result_ready

    @property
    def failed(self) -> SignalInstance:
        """Fires on the GUI thread with the `ScrapeError`, exactly once, whenever :attr:`result_ready`
        does not -- no scraper matched, the fetch failed or landed on a login wall, or the result failed
        the scrape-result schema. Fires alongside the same `LOG.warning`/
        `LOG.exception` call :meth:`run` always made; this is what lets a caller show the refusal beside
        an open document (e.g. a `MessageBanner` row) rather than read it only from the log.
        """
        return self.__marshaller.failed

    @property
    def publisher(self) -> str | None:
        """The publisher of the scraper that produced the result, after any redirect -- `None` until
        :meth:`scrape` has resolved one. Read after :attr:`result_ready` fires; both are set before it
        is emitted."""
        return self.__publisher

    @property
    def page_url(self) -> str | None:
        """The URL of the page actually read -- the dropped fragment's URL, or the fetch's
        `~.results.Page.final_url` -- `None` until :meth:`scrape` has resolved one. Read after
        :attr:`result_ready` fires; both are set before it is emitted."""
        return self.__page_url

    def run(self) -> None:
        """Do the work: resolve, fetch, parse, validate, emit.

        Runs on whatever thread `ScraperExecutor` hands it to. Touches no widget directly -- the result
        crosses back to the GUI thread through :attr:`result_ready`'s queued connection, and a refusal
        through :attr:`failed`'s.

        The blanket catch is the point rather than a shortcut, the same one `BackgroundMeasurement`
        makes: `matches` and `scrape_page` are user-written code, an exception escaping a pool thread
        is printed by the pool and reaches no log dock, and the document's log is the one place a
        broken script can be diagnosed from. A `ScrapeError` -- an expected refusal or a bad result --
        is logged as a warning rather than with a traceback; anything else still gets `LOG.exception`
        and is wrapped as a `ScrapeError` before reaching :attr:`failed`.
        """
        try:
            self.__marshaller.scraped.emit(self.scrape())
        except ScrapeError as error:
            LOG.warning(str(error))
            self.__marshaller.failure.emit(error)
        except Exception as error:  # pylint: disable=broad-exception-caught
            LOG.exception("Scraping %s failed.", self.__url)
            self.__marshaller.failure.emit(ScrapeError(f"Scraping {self.__url} failed: {error}"))

    def scrape(self) -> ScrapeResult:
        """Resolve, refuse or fetch, re-resolve a redirect, parse, validate -- the synchronous half of
        :meth:`run`, and what the ``--scrape`` CLI calls directly.

        Also resolves :attr:`publisher` and :attr:`page_url`, set before returning.

        :returns: the scraper's result, validated against `~.results.SCRAPE_RESULT_SCHEMA`
            (`~.results.ScrapeResult.coerce`).
        :raises ScrapeError: no scraper matches, the fetch failed, the fetch landed on a login wall, or
            the result failed the schema.
        """
        scraper = self.__registry.find(self.__url)
        if scraper is None:
            raise NoScraperError(self.__url)
        page = self.__page if self.__page is not None else self.__fetch(self.__url, scraper)
        if page.final_url != self.__url:
            redirected = self.__registry.find(page.final_url)
            if redirected is not None:
                needs_refetch = (
                    self.__page is None
                    and self.__forced_fetcher is None
                    and self.__settings.uses_browser(redirected)
                    and not self.__settings.uses_browser(scraper)
                )
                if needs_refetch:
                    # the redirect landed on a scraper the original one wouldn't have needed the
                    # browser for -- re-fetch through it rather than handing over an HTTP-fetched page
                    page = self.__fetch(page.final_url, redirected)
                scraper = redirected
        try:
            raw_result = scraper.scrape_page(page)
        except LoginRequiredError as error:
            raise LoginRequiredScrapeError(
                scraper.label, urlsplit(page.final_url).hostname or page.final_url
            ) from error
        try:
            result = ScrapeResult.coerce(raw_result)
        except InvalidScrapeResultError as error:
            raise ScrapeError(f"{scraper.label} returned an invalid result for {self.__url}: {error}") from error
        self.__publisher = scraper.publisher
        self.__page_url = page.final_url
        return result

    def __fetch(self, url: str, scraper: object) -> Page:
        """Fetch ``url`` with the fetcher ``scraper`` dispatches to, wrapping a failure as a
        `ScrapeError` rather than letting it crash the pool thread.

        :param url: the address to fetch.
        :param scraper: the scraper this fetch is for -- decides HTTP vs. the persona browser.
        :returns: the fetched page.
        :raises ScrapeError: the fetch failed, or landed on a login wall.
        """
        fetcher = self.__fetcher_for(scraper)
        try:
            return fetcher.fetch(url)
        except LoginRequiredError as error:
            raise LoginRequiredScrapeError(
                getattr(scraper, "label", "The scraper"), urlsplit(url).hostname or url
            ) from error
        except (RequestException, FetchError) as error:
            raise ScrapeError(f"Could not fetch {url}: {error}") from error

    def __fetcher_for(self, scraper: object) -> PageFetcher:
        """The fetcher this scrape uses for ``scraper``: the injected override, or dispatch on
        `~rehuco_agent.settings.scrapers_settings.ScrapersSettings.uses_browser`.

        :param scraper: the scraper the fetch is for.
        :returns: the fetcher to use.
        """
        if self.__forced_fetcher is not None:
            return self.__forced_fetcher
        if self.__settings.uses_browser(scraper):
            return BrowserPageFetcher(self.__settings)
        return HttpPageFetcher()
