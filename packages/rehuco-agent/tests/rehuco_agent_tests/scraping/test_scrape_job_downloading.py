"""Tests for `ScrapeJob` running a scraper that downloads for itself, a `FetchingScraper` (#701)."""

from pytest import mark, param, raises
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.scraping.protocols import (
    FetchError,
    FetchingScraper,
    LoginRequiredError,
    PageFetcher,
    PageGoneError,
    RefetchRequestedError,
)
from rehuco_agent.scraping.results import Page, ScrapeResult
from rehuco_agent.scraping.scrape_job import (
    DEFAULT_REFETCH_DELAY,
    LoginRequiredScrapeError,
    ScrapeError,
    ScrapeJob,
)
from rehuco_agent.settings.scrapers_settings import ScrapersSettings, scraper_key
from requests import RequestException

from rehuco_agent_tests.delete_at_teardown import DeleteAtTeardown

from .test_scrape_job import URL, FakeFetcher, FakeRegistry, FakeScraper


class DownloadingScraper(FakeScraper):
    """A `FetchingScraper`: given the job's fetcher, it fetches an address of its own and reads the item from it.

    :param error: raised from :meth:`scrape_url` instead of a result, when given.
    """

    def __init__(self, error: Exception | None = None) -> None:
        super().__init__(result=ScrapeResult(fields={"title": "Listing"}, description=None, images=()))
        self.error = error
        self.handed: list[tuple[str, PageFetcher]] = []

    def scrape_url(self, url: str, fetcher: PageFetcher) -> object:
        """Fetch an address of its own, or raise the error it was built with."""
        self.handed.append((url, fetcher))
        if self.error is not None:
            raise self.error
        fetcher.fetch(f"{url}/data")
        return self.result


def test_a_scraper_that_downloads_for_itself_is_handed_the_fetcher_and_no_page(
    qtbot: QtBot, delete_at_teardown: DeleteAtTeardown
) -> None:
    """Such a scraper is called with the URL dropped and the job's fetcher, instead of `scrape_page` and with no page
    fetched for it; the source of its record is the URL dropped (#701).

    **Test steps:**

    * build a job for a scraper with `scrape_url`, a fetcher and a registry
    * run the job
    * verify the scraper was handed the URL and that fetcher, and fetched only what it asked for
    * verify the result reached `result_ready`, and the publisher and the dropped URL are set
    """
    scraper = DownloadingScraper()
    assert isinstance(scraper, FetchingScraper)
    fetcher = FakeFetcher(page=Page(url=f"{URL}/data", final_url=f"{URL}/data", html="{}"))
    relay = delete_at_teardown(ScrapeJob.Relay())
    job = ScrapeJob(URL, FakeRegistry({URL: scraper}), fetcher=fetcher, relay=relay)  # type: ignore[arg-type]

    with qtbot.waitSignal(relay.result_ready, timeout=1000) as blocker:
        job.run()

    assert scraper.handed == [(URL, fetcher)]
    assert fetcher.calls == [f"{URL}/data"]
    assert blocker.args == [job, scraper.result]
    assert (job.publisher, job.page_url) == ("Fake Co", URL)


def test_a_scraper_that_downloads_for_itself_ignores_a_dropped_fragment(delete_at_teardown: DeleteAtTeardown) -> None:
    """A dropped fragment is not used by a scraper that fetches what it needs, and nothing is fetched for it first
    (#701).

    **Test steps:**

    * build a job with a dropped fragment for a scraper with `scrape_url`
    * scrape
    * verify the scraper's own fetch is the only one
    """
    scraper = DownloadingScraper()
    fetcher = FakeFetcher(page=Page(url=URL, final_url=URL, html=""))
    relay = delete_at_teardown(ScrapeJob.Relay())
    page = Page(url=URL, final_url=URL, html="<html>a fragment</html>")
    registry = FakeRegistry({URL: scraper})
    job = ScrapeJob(URL, registry, page=page, fetcher=fetcher, relay=relay)  # type: ignore[arg-type]

    result = job.scrape()

    assert result == scraper.result
    assert fetcher.calls == [f"{URL}/data"]


@mark.parametrize(
    ("ticked", "needs_browser", "browser"),
    [
        param(False, False, False, id="plain-http"),
        param(True, False, True, id="use-browser-ticked"),
        param(False, True, True, id="needs-browser"),
    ],
)
def test_the_fetcher_handed_over_follows_the_browser_choice(
    mocker: MockerFixture, delete_at_teardown: DeleteAtTeardown, ticked: bool, needs_browser: bool, browser: bool
) -> None:
    """The fetcher a scraper downloads with is the one its page would have been fetched with: HTTP, or the persona
    browser when the scraper needs it or the user ticked **Use browser** (#701).

    **Test steps:**

    * build a job with no injected fetcher, for a scraper ticked, needing the browser, or neither
    * scrape
    * verify the scraper was handed the browser fetcher or the HTTP one, as the choice says
    """
    scraper = DownloadingScraper()
    scraper.needs_browser = needs_browser
    settings = ScrapersSettings(browser_scrapers=frozenset({scraper_key(scraper)}) if ticked else frozenset())
    page = Page(url=f"{URL}/data", final_url=f"{URL}/data", html="{}")
    http_fetcher = mocker.Mock(fetch=mocker.Mock(return_value=page))
    browser_fetcher = mocker.Mock(fetch=mocker.Mock(return_value=page))
    mocker.patch("rehuco_agent.scraping.scrape_job.HttpPageFetcher", return_value=http_fetcher)
    mocker.patch("rehuco_agent.scraping.scrape_job.BrowserPageFetcher", return_value=browser_fetcher)
    relay = delete_at_teardown(ScrapeJob.Relay())

    ScrapeJob(URL, FakeRegistry({URL: scraper}), settings=settings, relay=relay).scrape()  # type: ignore[arg-type]

    assert scraper.handed == [(URL, browser_fetcher if browser else http_fetcher)]


@mark.parametrize(
    "error", [param(None, id="scraped"), param(FetchError("boom"), id="failed"), param(ValueError("bug"), id="raised")]
)
def test_a_scrape_closes_its_browser_however_it_ends(
    mocker: MockerFixture, delete_at_teardown: DeleteAtTeardown, error: Exception | None
) -> None:
    """The browser a scrape fetched with is quit when the scrape ends, so its window and the profile are never left
    held (#701).

    **Test steps:**

    * build a job for a scraper that needs the browser and succeeds, fails a fetch, or raises
    * scrape
    * verify one browser fetcher was built, and closed once
    """
    scraper = DownloadingScraper(error)
    scraper.needs_browser = True
    page = Page(url=f"{URL}/data", final_url=f"{URL}/data", html="{}")
    browser_fetcher = mocker.Mock(fetch=mocker.Mock(return_value=page))
    browser_cls = mocker.patch("rehuco_agent.scraping.scrape_job.BrowserPageFetcher", return_value=browser_fetcher)
    relay = delete_at_teardown(ScrapeJob.Relay())
    registry = FakeRegistry({URL: scraper})
    job = ScrapeJob(URL, registry, settings=ScrapersSettings(), relay=relay)  # type: ignore[arg-type]

    if error is None:
        job.scrape()
    else:
        with raises(ScrapeError if isinstance(error, FetchError) else ValueError):
            job.scrape()

    browser_cls.assert_called_once()
    browser_fetcher.close.assert_called_once_with()


def test_an_item_no_longer_public_fails_with_the_scraper_s_sentence(delete_at_teardown: DeleteAtTeardown) -> None:
    """A scraper that raises `PageGoneError`, from either method, fails the scrape with the sentence it gave (#701).

    **Test steps:**

    * scrape with a scraper whose `scrape_url` raises it, and with one whose `scrape_page` raises it
    * verify each raises `ScrapeError` with that sentence
    """

    class GonePageScraper(FakeScraper):  # pylint: disable=missing-class-docstring
        def scrape_page(self, page: Page) -> ScrapeResult:
            del page
            raise PageGoneError("This listing is no longer public.")

    relay = delete_at_teardown(ScrapeJob.Relay())
    page = Page(url=URL, final_url=URL, html="")

    for scraper in (DownloadingScraper(PageGoneError("This listing is no longer public.")), GonePageScraper()):
        registry = FakeRegistry({URL: scraper})
        job = ScrapeJob(URL, registry, page=page, fetcher=FakeFetcher(page=page), relay=relay)  # type: ignore[arg-type]

        with raises(ScrapeError, match="^This listing is no longer public.$"):
            job.scrape()


@mark.parametrize(
    "error",
    [
        param(RequestException("boom"), id="requests"),
        param(FetchError("could not start the browser"), id="browser"),
    ],
)
def test_a_fetch_the_scraper_made_that_fails_is_reported_as_a_failed_fetch(
    delete_at_teardown: DeleteAtTeardown, error: Exception
) -> None:
    """A fetch that fails inside `scrape_url` is reported as the page's own fetch is (#701).

    **Test steps:**

    * scrape with a scraper whose own fetch raises each kind of fetch failure
    * verify `ScrapeError` says the fetch of the URL failed, with the cause
    """
    relay = delete_at_teardown(ScrapeJob.Relay())
    registry = FakeRegistry({URL: DownloadingScraper(error)})
    job = ScrapeJob(URL, registry, fetcher=FakeFetcher(), relay=relay)  # type: ignore[arg-type]

    with raises(ScrapeError, match=f"Could not fetch {URL}: .*{error}"):
        job.scrape()


def test_a_login_wall_or_a_retry_the_scraper_met_is_reported_as_for_a_page(
    delete_at_teardown: DeleteAtTeardown,
) -> None:
    """A scraper that downloads for itself gets the same login message and the same normalized re-fetch request a
    page's scraper does (#701).

    **Test steps:**

    * scrape with a scraper whose `scrape_url` raises `LoginRequiredError`
    * verify `LoginRequiredScrapeError` names the scraper and the host
    * scrape with one asking for a re-fetch with no URL and no pause
    * verify the request carries this job's URL and the default pause
    """
    relay = delete_at_teardown(ScrapeJob.Relay())
    gated = DownloadingScraper(LoginRequiredError("login form"))
    gated.label = "Gated"
    job = ScrapeJob(URL, FakeRegistry({URL: gated}), fetcher=FakeFetcher(), relay=relay)  # type: ignore[arg-type]
    with raises(LoginRequiredScrapeError, match="Gated needs a login.*example.com"):
        job.scrape()

    busy = DownloadingScraper(RefetchRequestedError("busy"))
    job = ScrapeJob(URL, FakeRegistry({URL: busy}), fetcher=FakeFetcher(), relay=relay)  # type: ignore[arg-type]
    with raises(RefetchRequestedError) as caught:
        job.scrape()

    assert (caught.value.url, caught.value.delay, caught.value.message) == (URL, DEFAULT_REFETCH_DELAY, "busy")


def test_an_invalid_result_from_a_scraper_that_downloads_for_itself_fails_that_scrape(
    delete_at_teardown: DeleteAtTeardown,
) -> None:
    """Its result is validated against the schema as a page scraper's is (#701).

    **Test steps:**

    * scrape with a scraper returning a field of the wrong type
    * verify `ScrapeError` names the scraper and the URL
    """
    scraper = DownloadingScraper()
    scraper.result = {"fields": {"title": 1}}
    relay = delete_at_teardown(ScrapeJob.Relay())
    page = Page(url=f"{URL}/data", final_url=f"{URL}/data", html="")
    registry = FakeRegistry({URL: scraper})
    job = ScrapeJob(URL, registry, fetcher=FakeFetcher(page=page), relay=relay)  # type: ignore[arg-type]

    with raises(ScrapeError, match=f"Fake returned an invalid result for {URL}"):
        job.scrape()
