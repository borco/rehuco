"""Tests for `ScraperExecutor` (#269)."""

import threading
from dataclasses import dataclass, field
from logging import INFO, Handler, LogRecord, getLogger

from borco_core.logging import LogScope
from pytestqt.qtbot import QtBot
from rehuco_agent.scraping.results import Page, ScrapeResult
from rehuco_agent.scraping.scrape_job import ScrapeJob
from rehuco_agent.scraping.scraper_executor import ScraperExecutor, shared_scraper_executor

URL_A = "https://a.example.com/page"
URL_B = "https://b.example.com/page"


@dataclass
class BlockingScraper:  # pylint: disable=missing-function-docstring,too-many-instance-attributes
    """A `SiteScraper` whose `scrape_page` waits until every submitted job has arrived, then
    releases -- proof that two jobs run concurrently rather than serialize behind each other.
    """

    url: str
    arrived: threading.Barrier
    result: ScrapeResult = field(default_factory=lambda: ScrapeResult(fields={}, description=None, images=()))
    label: str = "Blocking"
    publisher: str = "Blocking Co"
    site_name: str = "Blocking"
    site_url: str = "https://blocking.example.com"
    needs_browser: bool = False

    def matches(self, url: str) -> bool:
        return url == self.url

    def scrape_page(self, page: object) -> ScrapeResult:
        del page
        self.arrived.wait(timeout=2)
        return self.result


class TwoUrlRegistry:  # pylint: disable=missing-function-docstring,too-few-public-methods
    """A registry over exactly the two scrapers a concurrency test needs."""

    def __init__(self, scrapers: dict[str, BlockingScraper]) -> None:
        self.__scrapers = scrapers

    def find(self, url: str) -> BlockingScraper | None:
        return self.__scrapers.get(url)


class FakeFetcher:  # pylint: disable=missing-function-docstring,too-few-public-methods
    """Answers a fixed page for whichever URL it is asked to fetch."""

    def fetch(self, url: str) -> Page:
        return Page(url=url, final_url=url, html="<html></html>")


def test_two_jobs_submitted_together_both_complete(qtbot: QtBot) -> None:
    """Nothing about one scrape blocks another: two jobs submitted together both run and finish
    (#269) -- the concurrency this executor exists for.

    **Test steps:**

    * build two jobs whose scrapers both wait on a shared barrier before returning
    * submit both to a fresh executor
    * verify both results arrive -- which is only possible if both scrapers reached the barrier,
      i.e. ran at the same time rather than one after the other
    * verify each result was delivered on the main thread, though the scrape ran on a pool thread,
      to a plain callable receiver -- the marshalled hand-off, not `AutoConnection`
    """
    barrier = threading.Barrier(2)
    result_a = ScrapeResult(fields={"title": "A"}, description=None, images=())
    result_b = ScrapeResult(fields={"title": "B"}, description=None, images=())
    scraper_a = BlockingScraper(url=URL_A, arrived=barrier, result=result_a)
    scraper_b = BlockingScraper(url=URL_B, arrived=barrier, result=result_b)
    registry = TwoUrlRegistry({URL_A: scraper_a, URL_B: scraper_b})
    fetcher = FakeFetcher()
    job_a = ScrapeJob(URL_A, registry, fetcher=fetcher)  # type: ignore[arg-type]
    job_b = ScrapeJob(URL_B, registry, fetcher=fetcher)  # type: ignore[arg-type]
    received: list[object] = []
    delivering_threads: list[threading.Thread] = []

    def receive(result: object) -> None:
        received.append(result)
        delivering_threads.append(threading.current_thread())

    job_a.result_ready.connect(receive)
    job_b.result_ready.connect(receive)
    executor = ScraperExecutor()

    with qtbot.waitSignal(job_a.result_ready, timeout=2000), qtbot.waitSignal(job_b.result_ready, timeout=2000):
        executor.submit(job_a)
        executor.submit(job_b)

    ordered = sorted(received, key=lambda result: result.fields["title"])  # type: ignore[union-attr]
    assert ordered == [result_a, result_b]
    assert delivering_threads == [threading.main_thread(), threading.main_thread()]


def test_a_job_submitted_inside_a_log_scope_logs_under_it(qtbot: QtBot) -> None:
    """The log scope open at submission time is carried onto the worker thread -- without this, a
    scrape's own log records would land in the app-wide dock only, never the document's (#269).

    **Test steps:**

    * open a `LogScope` and submit a job that logs one record while it runs
    * verify the record carries that scope, though it was made on a different thread
    """
    scope = "fake/document/path"
    seen_scopes: list[tuple[object, ...]] = []

    class RecordingHandler(Handler):  # pylint: disable=missing-class-docstring
        def emit(self, record: LogRecord) -> None:
            # resolved here, synchronously, on the thread that logged -- LogScope.of's own contract;
            # reading it later, off the record, would read the test thread's context instead
            seen_scopes.append(LogScope.of(record))

    class FakeScraperLoggingOnRun:  # pylint: disable=missing-class-docstring,missing-function-docstring
        label = "Logs"
        publisher = "Logs Co"
        site_name = "Logs"
        site_url = "https://logs.example.com"
        needs_browser = False

        def matches(self, url: str) -> bool:
            del url
            return True

        def scrape_page(self, page: object) -> ScrapeResult:
            del page
            getLogger("rehuco_agent.scraping.scrape_job").info("scraping under a scope")
            return ScrapeResult(fields={}, description=None, images=())

    class OneScraperRegistry:  # pylint: disable=missing-class-docstring,missing-function-docstring,R0903
        def find(self, url: str) -> FakeScraperLoggingOnRun | None:
            del url
            return FakeScraperLoggingOnRun()

    logger = getLogger("rehuco_agent.scraping.scrape_job")
    handler = RecordingHandler()
    logger.addHandler(handler)
    previous_level = logger.level
    logger.setLevel(INFO)
    try:
        job = ScrapeJob(URL_A, OneScraperRegistry(), fetcher=FakeFetcher())  # type: ignore[arg-type]
        executor = ScraperExecutor()
        with qtbot.waitSignal(job.result_ready, timeout=2000):
            with LogScope.open(scope):
                executor.submit(job)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)

    assert seen_scopes
    assert scope in seen_scopes[0]


def test_shared_scraper_executor_is_a_singleton() -> None:
    """The shared accessor returns the same instance every call (#269).

    **Test steps:**

    * call `shared_scraper_executor` twice
    * verify both calls return the same object
    """
    assert shared_scraper_executor() is shared_scraper_executor()
