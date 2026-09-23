"""Tests for `ScrapeJob` (#269)."""

from dataclasses import dataclass, field

from pytest import LogCaptureFixture, raises
from pytestqt.qtbot import QtBot
from rehuco_agent.scraping.results import Page, ScrapeResult
from rehuco_agent.scraping.scrape_job import NoScraperError, ScrapeError, ScrapeJob
from requests import RequestException

URL = "https://example.com/page"
REDIRECTED_URL = "https://redirected.example.com/page"


@dataclass
class FakeScraper:  # pylint: disable=missing-function-docstring
    """A minimal `SiteScraper`, built directly rather than from a registered class."""

    label: str = "Fake"
    publisher: str = "Fake Co"
    needs_browser: bool = False
    result: object = field(default_factory=lambda: ScrapeResult(fields={}, description=None, images=()))

    def matches(self, url: str) -> bool:
        del url
        return True

    def scrape_page(self, page: Page) -> object:
        del page
        return self.result


class FakeRegistry:  # pylint: disable=missing-function-docstring,too-few-public-methods
    """A minimal registry: `find` answers from a fixed mapping, by URL."""

    def __init__(self, by_url: dict[str, FakeScraper | None]) -> None:
        self.__by_url = by_url
        self.calls: list[str] = []

    def find(self, url: str) -> FakeScraper | None:
        self.calls.append(url)
        return self.__by_url.get(url)


class FakeFetcher:  # pylint: disable=missing-function-docstring,too-few-public-methods
    """A `PageFetcher` stand-in: returns a fixed page, or raises a fixed error."""

    def __init__(self, page: Page | None = None, error: Exception | None = None) -> None:
        self.__page = page
        self.__error = error
        self.calls: list[str] = []

    def fetch(self, url: str) -> Page:
        self.calls.append(url)
        if self.__error is not None:
            raise self.__error
        assert self.__page is not None
        return self.__page


def test_fragment_page_never_calls_the_fetcher(qtbot: QtBot) -> None:
    """A dropped fragment supplies its own `Page`; the fetcher is never asked (#269).

    **Test steps:**

    * build a job with a pre-supplied page and a scraper that matches
    * run the job
    * verify the fetcher was never called, and the result reached `result_ready`
    """
    scraper = FakeScraper(result=ScrapeResult(fields={"title": "T"}, description=None, images=()))
    registry = FakeRegistry({URL: scraper})
    fetcher = FakeFetcher()
    page = Page(url=URL, final_url=URL, html="<html></html>")
    job = ScrapeJob(URL, registry, page=page, fetcher=fetcher)  # type: ignore[arg-type]

    with qtbot.waitSignal(job.result_ready, timeout=1000) as blocker:
        job.run()

    assert not fetcher.calls
    assert blocker.args == [scraper.result]


def test_result_ready_fires_once_on_success(qtbot: QtBot) -> None:
    """A successful scrape emits `result_ready` exactly once, with the scraper's own result (#269).

    **Test steps:**

    * build a job whose fetcher and scraper both succeed
    * run the job
    * verify the emitted result is the scraper's
    """
    result = ScrapeResult(fields={"title": "T"}, description="d", images=())
    scraper = FakeScraper(result=result)
    registry = FakeRegistry({URL: scraper})
    page = Page(url=URL, final_url=URL, html="<html></html>")
    fetcher = FakeFetcher(page=page)
    job = ScrapeJob(URL, registry, fetcher=fetcher)  # type: ignore[arg-type]

    with qtbot.waitSignal(job.result_ready, timeout=1000) as blocker:
        job.run()

    assert blocker.args == [result]


def test_no_matching_scraper_logs_and_emits_nothing(qtbot: QtBot, caplog: LogCaptureFixture) -> None:
    """No scraper for the host is a warning, never a crash and never a fetch (#269).

    **Test steps:**

    * build a job whose registry matches nothing
    * run the job
    * verify the fetcher was never called and `result_ready` never fired
    """
    registry = FakeRegistry({})
    fetcher = FakeFetcher()
    job = ScrapeJob(URL, registry, fetcher=fetcher)  # type: ignore[arg-type]
    received: list[object] = []
    job.result_ready.connect(received.append)

    with caplog.at_level("WARNING"):
        job.run()
    qtbot.wait(50)

    assert not fetcher.calls
    assert not received
    assert f"No scraper matches example.com ({URL})." in caplog.text


def test_a_scraper_needing_the_browser_is_refused_without_fetching(qtbot: QtBot, caplog: LogCaptureFixture) -> None:
    """A scraper declaring `needs_browser` is refused before any fetch is attempted (#269).

    **Test steps:**

    * build a job whose only matching scraper needs the browser fetcher
    * run the job
    * verify the fetcher was never called and `result_ready` never fired
    """
    scraper = FakeScraper(needs_browser=True)
    registry = FakeRegistry({URL: scraper})
    fetcher = FakeFetcher()
    job = ScrapeJob(URL, registry, fetcher=fetcher)  # type: ignore[arg-type]
    received: list[object] = []
    job.result_ready.connect(received.append)

    with caplog.at_level("WARNING"):
        job.run()
    qtbot.wait(50)

    assert not fetcher.calls
    assert not received
    assert "needs the browser fetcher" in caplog.text


def test_a_failed_fetch_is_caught_and_logged(qtbot: QtBot, caplog: LogCaptureFixture) -> None:
    """A fetch that raises is logged, not left to crash the pool thread it would run on (#269).

    **Test steps:**

    * build a job whose fetcher raises
    * run the job
    * verify `result_ready` never fired
    """
    scraper = FakeScraper()
    registry = FakeRegistry({URL: scraper})
    fetcher = FakeFetcher(error=RequestException("boom"))
    job = ScrapeJob(URL, registry, fetcher=fetcher)  # type: ignore[arg-type]
    received: list[object] = []
    job.result_ready.connect(received.append)

    with caplog.at_level("WARNING"):
        job.run()
    qtbot.wait(50)

    assert not received
    assert "Could not fetch" in caplog.text


def test_a_raising_scraper_is_caught_and_logged(qtbot: QtBot, caplog: LogCaptureFixture) -> None:
    """A user-written scraper that raises is logged with its traceback, never left to escape the pool
    thread -- where it would be printed and reach no log dock (#269).

    **Test steps:**

    * build a job whose scraper raises from `scrape_page`
    * run the job
    * verify `result_ready` never fired and the failure was logged with the URL
    """

    class RaisingScraper(FakeScraper):  # pylint: disable=missing-class-docstring
        def scrape_page(self, page: Page) -> ScrapeResult:
            del page
            raise RuntimeError("boom in user code")

    registry = FakeRegistry({URL: RaisingScraper()})
    page = Page(url=URL, final_url=URL, html="<html></html>")
    job = ScrapeJob(URL, registry, fetcher=FakeFetcher(page=page))  # type: ignore[arg-type]
    received: list[object] = []
    job.result_ready.connect(received.append)

    with caplog.at_level("ERROR"):
        job.run()
    qtbot.wait(50)

    assert not received
    assert f"Scraping {URL} failed." in caplog.text
    assert "boom in user code" in caplog.text


def test_a_redirect_is_re_resolved_on_the_final_url(qtbot: QtBot) -> None:
    """A fetch that redirects to another host is dispatched to *that* host's scraper (#269).

    **Test steps:**

    * build a job whose fetch redirects to a different URL, matched by a different scraper
    * run the job
    * verify the redirected scraper's result was emitted, and both lookups happened
    """
    original_scraper = FakeScraper(label="Original")
    redirected_result = ScrapeResult(fields={"title": "Redirected"}, description=None, images=())
    redirected_scraper = FakeScraper(label="Redirected", result=redirected_result)
    registry = FakeRegistry({URL: original_scraper, REDIRECTED_URL: redirected_scraper})
    page = Page(url=URL, final_url=REDIRECTED_URL, html="<html></html>")
    fetcher = FakeFetcher(page=page)
    job = ScrapeJob(URL, registry, fetcher=fetcher)  # type: ignore[arg-type]

    with qtbot.waitSignal(job.result_ready, timeout=1000) as blocker:
        job.run()

    assert registry.calls == [URL, REDIRECTED_URL]
    assert blocker.args == [redirected_result]


def test_a_redirect_onto_a_browser_only_scraper_is_refused(qtbot: QtBot, caplog: LogCaptureFixture) -> None:
    """A redirect landing on a host whose scraper needs the browser fetcher is refused after the fetch,
    the same way a direct hit is refused before it (#269).

    **Test steps:**

    * build a job whose fetch redirects to a host matched by a browser-only scraper
    * run the job
    * verify `result_ready` never fired and the refusal names that scraper
    """
    registry = FakeRegistry(
        {URL: FakeScraper(label="Original"), REDIRECTED_URL: FakeScraper(label="Gated", needs_browser=True)}
    )
    page = Page(url=URL, final_url=REDIRECTED_URL, html="<html></html>")
    job = ScrapeJob(URL, registry, fetcher=FakeFetcher(page=page))  # type: ignore[arg-type]
    received: list[object] = []
    job.result_ready.connect(received.append)

    with caplog.at_level("WARNING"):
        job.run()
    qtbot.wait(50)

    assert not received
    assert "Gated needs the browser fetcher" in caplog.text


def test_a_scraper_returning_a_mapping_yields_the_same_result_as_the_dataclass(qtbot: QtBot) -> None:
    """A script returning a JSON-shaped mapping directly is normalized the same as one returning the
    dataclass (#340)."""
    dataclass_result = ScrapeResult(fields={"title": "T"}, description="d", images=())
    mapping_result = {"fields": {"title": "T"}, "description": "d", "images": []}
    scraper = FakeScraper(result=mapping_result)
    registry = FakeRegistry({URL: scraper})
    page = Page(url=URL, final_url=URL, html="<html></html>")
    job = ScrapeJob(URL, registry, page=page, fetcher=FakeFetcher())  # type: ignore[arg-type]

    with qtbot.waitSignal(job.result_ready, timeout=1000) as blocker:
        job.run()

    assert blocker.args == [dataclass_result]


def test_an_invalid_result_fails_only_that_scrape(qtbot: QtBot, caplog: LogCaptureFixture) -> None:
    """A scraper's result failing the scrape-result schema is logged with the scraper's label and the
    URL, and never reaches `result_ready` (#340) -- non-fatal, per-script, the same as an import error."""
    bad_result = ScrapeResult(fields={"current_size": 5}, description=None, images=())
    scraper = FakeScraper(label="Bad", result=bad_result)
    registry = FakeRegistry({URL: scraper})
    page = Page(url=URL, final_url=URL, html="<html></html>")
    job = ScrapeJob(URL, registry, page=page, fetcher=FakeFetcher())  # type: ignore[arg-type]
    received: list[object] = []
    job.result_ready.connect(received.append)

    with caplog.at_level("WARNING"):
        job.run()
    qtbot.wait(50)

    assert not received
    assert "Bad returned an invalid result" in caplog.text
    assert URL in caplog.text


def test_scrape_raises_for_no_matching_scraper() -> None:
    """`scrape()` raises `ScrapeError` (the synchronous half `run()`/the CLI use) rather than returning
    `None`."""
    job = ScrapeJob(URL, FakeRegistry({}), fetcher=FakeFetcher())  # type: ignore[arg-type]

    with raises(ScrapeError, match="No scraper matches example.com"):
        job.scrape()


def test_scrape_raises_when_the_matching_scraper_needs_the_browser() -> None:
    """`scrape()` raises `ScrapeError` for a browser-only scraper rather than returning `None`."""
    registry = FakeRegistry({URL: FakeScraper(needs_browser=True)})
    job = ScrapeJob(URL, registry, fetcher=FakeFetcher())  # type: ignore[arg-type]

    with raises(ScrapeError, match="needs the browser fetcher"):
        job.scrape()


def test_scrape_raises_when_the_fetch_fails() -> None:
    """`scrape()` raises `ScrapeError` when the fetcher raises, rather than returning `None`."""
    registry = FakeRegistry({URL: FakeScraper()})
    job = ScrapeJob(URL, registry, fetcher=FakeFetcher(error=RequestException("boom")))  # type: ignore[arg-type]

    with raises(ScrapeError, match="Could not fetch"):
        job.scrape()


def test_no_matching_scraper_emits_failed_with_the_host(qtbot: QtBot) -> None:
    """`failed` fires on the GUI thread with a `NoScraperError` naming the host (#272)."""
    registry = FakeRegistry({})
    job = ScrapeJob(URL, registry, fetcher=FakeFetcher())  # type: ignore[arg-type]

    with qtbot.waitSignal(job.failed, timeout=1000) as blocker:
        job.run()

    assert blocker.args is not None
    assert len(blocker.args) == 1
    error = blocker.args[0]
    assert isinstance(error, NoScraperError)
    assert error.host == "example.com"


def test_a_failed_fetch_emits_failed(qtbot: QtBot) -> None:
    """`failed` fires on the GUI thread with the `ScrapeError` a failed fetch raised (#272)."""
    scraper = FakeScraper()
    registry = FakeRegistry({URL: scraper})
    fetcher = FakeFetcher(error=RequestException("boom"))
    job = ScrapeJob(URL, registry, fetcher=fetcher)  # type: ignore[arg-type]

    with qtbot.waitSignal(job.failed, timeout=1000) as blocker:
        job.run()

    assert blocker.args is not None
    assert "Could not fetch" in str(blocker.args[0])


def test_an_invalid_result_emits_failed(qtbot: QtBot) -> None:
    """`failed` fires on the GUI thread when the scraper's result fails the schema (#272)."""
    bad_result = ScrapeResult(fields={"current_size": 5}, description=None, images=())
    scraper = FakeScraper(label="Bad", result=bad_result)
    registry = FakeRegistry({URL: scraper})
    page = Page(url=URL, final_url=URL, html="<html></html>")
    job = ScrapeJob(URL, registry, page=page, fetcher=FakeFetcher())  # type: ignore[arg-type]

    with qtbot.waitSignal(job.failed, timeout=1000) as blocker:
        job.run()

    assert blocker.args is not None
    assert "Bad returned an invalid result" in str(blocker.args[0])


def test_a_raising_scraper_emits_failed(qtbot: QtBot) -> None:
    """`failed` fires on the GUI thread when the scraper itself raises (#272)."""

    class RaisingScraper(FakeScraper):  # pylint: disable=missing-class-docstring
        def scrape_page(self, page: Page) -> ScrapeResult:
            del page
            raise RuntimeError("boom in user code")

    registry = FakeRegistry({URL: RaisingScraper()})
    page = Page(url=URL, final_url=URL, html="<html></html>")
    job = ScrapeJob(URL, registry, fetcher=FakeFetcher(page=page))  # type: ignore[arg-type]

    with qtbot.waitSignal(job.failed, timeout=1000) as blocker:
        job.run()

    assert blocker.args is not None
    assert f"Scraping {URL} failed" in str(blocker.args[0])


def test_publisher_and_page_url_are_set_after_a_successful_scrape(qtbot: QtBot) -> None:
    """`publisher`/`page_url` name the scraper and page that actually ran, after any redirect (#272)."""
    original_scraper = FakeScraper(label="Original", publisher="Original Co")
    redirected_result = ScrapeResult(fields={"title": "Redirected"}, description=None, images=())
    redirected_scraper = FakeScraper(label="Redirected", publisher="Redirected Co", result=redirected_result)
    registry = FakeRegistry({URL: original_scraper, REDIRECTED_URL: redirected_scraper})
    page = Page(url=URL, final_url=REDIRECTED_URL, html="<html></html>")
    job = ScrapeJob(URL, registry, fetcher=FakeFetcher(page=page))  # type: ignore[arg-type]

    with qtbot.waitSignal(job.result_ready, timeout=1000):
        job.run()

    assert job.publisher == "Redirected Co"
    assert job.page_url == REDIRECTED_URL


def test_a_redirect_onto_an_unclaimed_host_keeps_the_original_scraper(qtbot: QtBot) -> None:
    """When nothing claims the URL a fetch landed on, the scraper that claimed the requested one still
    parses the page (#269).

    **Test steps:**

    * build a job whose fetch redirects to a host no scraper matches
    * run the job
    * verify the original scraper's result was emitted after both lookups
    """
    original_result = ScrapeResult(fields={"title": "Original"}, description=None, images=())
    registry = FakeRegistry({URL: FakeScraper(label="Original", result=original_result)})
    page = Page(url=URL, final_url=REDIRECTED_URL, html="<html></html>")
    job = ScrapeJob(URL, registry, fetcher=FakeFetcher(page=page))  # type: ignore[arg-type]

    with qtbot.waitSignal(job.result_ready, timeout=1000) as blocker:
        job.run()

    assert registry.calls == [URL, REDIRECTED_URL]
    assert blocker.args == [original_result]
