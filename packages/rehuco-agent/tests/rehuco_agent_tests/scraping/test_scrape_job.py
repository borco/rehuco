"""Tests for `ScrapeJob` (#269, #278)."""

from dataclasses import dataclass, field

from pytest import LogCaptureFixture, raises
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.scraping.protocols import FetchError, LoginRequiredError
from rehuco_agent.scraping.results import Page, ScrapeResult
from rehuco_agent.scraping.scrape_job import LoginRequiredScrapeError, NoScraperError, ScrapeError, ScrapeJob
from rehuco_agent.settings.scrapers_settings import ScrapersSettings, scraper_key
from requests import RequestException

URL = "https://example.com/page"
REDIRECTED_URL = "https://redirected.example.com/page"


@dataclass
# duplicate-code: deliberately the same shape `test_scrape_actions.py`'s FakeScraper uses
class FakeScraper:  # pylint: disable=missing-function-docstring,duplicate-code
    """A minimal `SiteScraper`, built directly rather than from a registered class."""

    label: str = "Fake"
    publisher: str = "Fake Co"
    site_name: str = "Fake"
    site_url: str = "https://fake.example.com"
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


def test_an_unticked_scraper_is_fetched_over_http(qtbot: QtBot, mocker: MockerFixture) -> None:
    """With no `fetcher` override, a scraper the user never ticked **Use browser** for is fetched over
    plain HTTP (#278).

    **Test steps:**

    * build a job with no injected fetcher, against settings ticking nothing
    * run the job
    * verify the HTTP fetcher, not the browser one, was built and called
    """
    scraper = FakeScraper()
    registry = FakeRegistry({URL: scraper})
    page = Page(url=URL, final_url=URL, html="<html></html>")
    http_fetcher = mocker.Mock(fetch=mocker.Mock(return_value=page))
    http_cls = mocker.patch("rehuco_agent.scraping.scrape_job.HttpPageFetcher", return_value=http_fetcher)
    browser_cls = mocker.patch("rehuco_agent.scraping.scrape_job.BrowserPageFetcher")
    job = ScrapeJob(URL, registry, settings=ScrapersSettings())  # type: ignore[arg-type]

    with qtbot.waitSignal(job.result_ready, timeout=1000):
        job.run()

    http_cls.assert_called_once_with()
    http_fetcher.fetch.assert_called_once_with(URL)
    browser_cls.assert_not_called()


def test_a_ticked_scraper_is_fetched_through_the_browser(qtbot: QtBot, mocker: MockerFixture) -> None:
    """A scraper the user ticked **Use browser** for is fetched through the persona browser, not HTTP
    (#278).

    **Test steps:**

    * build a job against settings ticking this scraper's key
    * run the job
    * verify the browser fetcher, not the HTTP one, was built and called
    """
    scraper = FakeScraper()
    settings = ScrapersSettings(browser_scrapers=frozenset({scraper_key(scraper)}))
    registry = FakeRegistry({URL: scraper})
    page = Page(url=URL, final_url=URL, html="<html></html>")
    browser_fetcher = mocker.Mock(fetch=mocker.Mock(return_value=page))
    browser_cls = mocker.patch("rehuco_agent.scraping.scrape_job.BrowserPageFetcher", return_value=browser_fetcher)
    http_cls = mocker.patch("rehuco_agent.scraping.scrape_job.HttpPageFetcher")
    job = ScrapeJob(URL, registry, settings=settings)  # type: ignore[arg-type]

    with qtbot.waitSignal(job.result_ready, timeout=1000):
        job.run()

    browser_cls.assert_called_once_with(settings)
    browser_fetcher.fetch.assert_called_once_with(URL)
    http_cls.assert_not_called()


def test_a_needs_browser_scraper_is_always_fetched_through_the_browser(qtbot: QtBot, mocker: MockerFixture) -> None:
    """A scraper declaring `needs_browser` goes through the persona browser even with nothing ticked
    (#269, #278).

    **Test steps:**

    * build a job for a `needs_browser` scraper, against settings ticking nothing
    * run the job
    * verify the browser fetcher was built and called
    """
    scraper = FakeScraper(needs_browser=True)
    registry = FakeRegistry({URL: scraper})
    page = Page(url=URL, final_url=URL, html="<html></html>")
    browser_fetcher = mocker.Mock(fetch=mocker.Mock(return_value=page))
    mocker.patch("rehuco_agent.scraping.scrape_job.BrowserPageFetcher", return_value=browser_fetcher)
    job = ScrapeJob(URL, registry, settings=ScrapersSettings())  # type: ignore[arg-type]

    with qtbot.waitSignal(job.result_ready, timeout=1000):
        job.run()

    browser_fetcher.fetch.assert_called_once_with(URL)


def test_a_forced_fetcher_overrides_dispatch(qtbot: QtBot, mocker: MockerFixture) -> None:
    """An explicitly injected `fetcher` is used regardless of settings -- the shape every test but
    these three dispatch tests wants (#278).

    **Test steps:**

    * build a job for a `needs_browser` scraper with an injected fetcher
    * run the job
    * verify neither the HTTP nor the browser fetcher classes were touched
    """
    scraper = FakeScraper(needs_browser=True)
    registry = FakeRegistry({URL: scraper})
    page = Page(url=URL, final_url=URL, html="<html></html>")
    fetcher = FakeFetcher(page=page)
    http_cls = mocker.patch("rehuco_agent.scraping.scrape_job.HttpPageFetcher")
    browser_cls = mocker.patch("rehuco_agent.scraping.scrape_job.BrowserPageFetcher")
    job = ScrapeJob(URL, registry, fetcher=fetcher)  # type: ignore[arg-type]

    with qtbot.waitSignal(job.result_ready, timeout=1000):
        job.run()

    assert fetcher.calls == [URL]
    http_cls.assert_not_called()
    browser_cls.assert_not_called()


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


def test_a_redirect_onto_a_browser_scraper_re_fetches_through_it(qtbot: QtBot, mocker: MockerFixture) -> None:
    """A redirect landing on a host whose scraper needs the browser is re-fetched through it, rather
    than handing over the page the HTTP fetch already brought back (#269, #278).

    **Test steps:**

    * build a job with no injected fetcher, whose HTTP fetch redirects to a `needs_browser` scraper
    * run the job
    * verify both fetchers were called, the HTTP one on the original URL and the browser one on the
      redirected URL, and the redirected scraper's own result was emitted
    """
    original = FakeScraper(label="Original")
    redirected_result = ScrapeResult(fields={"title": "Redirected"}, description=None, images=())
    redirected = FakeScraper(label="Redirected", needs_browser=True, result=redirected_result)
    registry = FakeRegistry({URL: original, REDIRECTED_URL: redirected})
    http_page = Page(url=URL, final_url=REDIRECTED_URL, html="<html>http</html>")
    browser_page = Page(url=REDIRECTED_URL, final_url=REDIRECTED_URL, html="<html>browser</html>")
    http_fetcher = mocker.Mock(fetch=mocker.Mock(return_value=http_page))
    browser_fetcher = mocker.Mock(fetch=mocker.Mock(return_value=browser_page))
    mocker.patch("rehuco_agent.scraping.scrape_job.HttpPageFetcher", return_value=http_fetcher)
    mocker.patch("rehuco_agent.scraping.scrape_job.BrowserPageFetcher", return_value=browser_fetcher)
    job = ScrapeJob(URL, registry, settings=ScrapersSettings())  # type: ignore[arg-type]

    with qtbot.waitSignal(job.result_ready, timeout=1000) as blocker:
        job.run()

    http_fetcher.fetch.assert_called_once_with(URL)
    browser_fetcher.fetch.assert_called_once_with(REDIRECTED_URL)
    assert blocker.args == [redirected_result]


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


def test_a_login_required_error_from_scrape_page_becomes_a_login_message() -> None:
    """A scraper's own parsing detecting a login wall becomes `LoginRequiredScrapeError`, naming the
    scraper and the host (#278).

    **Test steps:**

    * build a scraper whose `scrape_page` raises `LoginRequiredError`
    * scrape a dropped fragment (so no fetcher is involved)
    * verify `scrape()` raises `LoginRequiredScrapeError` naming the scraper and the host
    """

    class LoginGatedScraper(FakeScraper):  # pylint: disable=missing-class-docstring
        def scrape_page(self, page: Page) -> ScrapeResult:
            del page
            raise LoginRequiredError("a login form was found instead of the product page")

    registry = FakeRegistry({URL: LoginGatedScraper(label="Gated")})
    page = Page(url=URL, final_url=URL, html="<html></html>")
    job = ScrapeJob(URL, registry, page=page)  # type: ignore[arg-type]

    with raises(LoginRequiredScrapeError, match="Gated needs a login.*example.com"):
        job.scrape()


def test_a_login_required_error_from_the_fetcher_becomes_a_login_message() -> None:
    """A fetcher detecting a login wall (`HttpPageFetcher`'s 401/403 case) becomes the same
    `LoginRequiredScrapeError` a scraper's own parsing would raise (#278).

    **Test steps:**

    * build a job whose fetcher raises `LoginRequiredError`
    * verify `scrape()` raises `LoginRequiredScrapeError` naming the scraper and the host
    """
    registry = FakeRegistry({URL: FakeScraper(label="Gated")})
    fetcher = FakeFetcher(error=LoginRequiredError("401"))
    job = ScrapeJob(URL, registry, fetcher=fetcher)  # type: ignore[arg-type]

    with raises(LoginRequiredScrapeError, match="Gated needs a login.*example.com"):
        job.scrape()


def test_scrape_raises_when_the_fetcher_raises_fetcherror() -> None:
    """`scrape()` wraps a `FetchError` (the browser fetcher's own failure mode) as a `ScrapeError`, the
    same as a `requests.RequestException` (#278)."""
    registry = FakeRegistry({URL: FakeScraper()})
    fetcher = FakeFetcher(error=FetchError("could not start the browser"))
    job = ScrapeJob(URL, registry, fetcher=fetcher)  # type: ignore[arg-type]

    with raises(ScrapeError, match="Could not fetch"):
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
