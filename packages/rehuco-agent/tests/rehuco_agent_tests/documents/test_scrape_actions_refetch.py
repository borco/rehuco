"""Tests for `ScrapeActions` re-fetching a refused page (#272, #368, #369): the retry chain, its countdown row, and
ArtStation's refused store page.

Kept apart from `test_scrape_actions.py`, whose fakes and fixtures it imports, so that module stays under its size
cap; its autouse fixture is imported by name so it runs here too.
"""

from pathlib import Path
from typing import Final, cast

from borco_pyside.widgets import MessageBannerRow, MessageBannerSeverity
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents import scrape_actions
from rehuco_agent.documents.image_downloads import ImageDownloads
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.documents.scrape_actions import ScrapeActions
from rehuco_agent.scraping.results import Page
from rehuco_agent.scraping.scrape_job import MAX_REFETCHES
from rehuco_agent.scraping.sites.artstation import ArtStation
from rehuco_agent.scraping.url_drop import UrlDrop

from .test_scrape_actions import (  # noqa: F401  # pylint: disable=unused-import
    URL,
    WAIT_TIMEOUT_MS,
    FakeClock,
    FakeRegistry,
    HoldingExecutor,
    SequenceFetcher,
    SyncExecutor,
    actions,
    build_actions,
    countdown_row,
    delete_built_actions,
    document,
    drop,
    fixture_image_downloads,
    model,
    refetching_actions,
)

# region re-fetching


def test_a_retry_chain_that_succeeds_applies_the_result(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """Two 503s the scraper asks to re-fetch, then a 200: the third attempt's result is applied, and
    the banner is left clear (#368).

    **Test steps:**

    * answer the fetches 503, 503, then 200, for a scraper that asks to re-fetch every 503
    * submit a drop and wait until the new title has landed
    * verify the URL was fetched three times
    * verify the banner is empty
    """
    doc_model = model()
    fetcher = SequenceFetcher(503, 503, 200)
    doc_actions = refetching_actions(doc_model, fetcher, image_downloads)

    doc_actions.submit(drop())
    qtbot.waitUntil(lambda: doc_model.title == "New Title", timeout=WAIT_TIMEOUT_MS)

    assert fetcher.calls == [URL, URL, URL]
    assert not doc_actions.notice


def test_a_chain_out_of_refetches_ends_as_a_failure_row(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """A scraper still asking after `MAX_REFETCHES` re-fetches ends the drop with its last reason as the
    failure row, having fetched ``MAX_REFETCHES + 1`` times (#368).

    **Test steps:**

    * answer every fetch with a 503, for a scraper that asks to re-fetch every 503
    * submit a drop and wait until a banner row says it gave up
    * verify the fetcher was called ``MAX_REFETCHES + 1`` times
    * verify the first row is a WARNING with the reason followed by the number of failed fetches
    * verify the title is unchanged
    """
    doc_model = model()
    fetcher = SequenceFetcher(503)
    doc_actions = refetching_actions(doc_model, fetcher, image_downloads)

    doc_actions.submit(drop())
    qtbot.waitUntil(lambda: any("gave up" in row.text for row in doc_actions.notice), timeout=WAIT_TIMEOUT_MS)

    assert len(fetcher.calls) == MAX_REFETCHES + 1
    assert doc_actions.notice[0].severity == MessageBannerSeverity.WARNING
    assert doc_actions.notice[0].text == f"Example answered 503 — gave up after {MAX_REFETCHES + 1} failed fetches"
    assert doc_model.title == "Original"


def test_cancel_stops_a_waiting_chain(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """Triggering a waiting re-fetch's banner action drops it: the row clears and nothing more is
    fetched (#368).

    **Test steps:**

    * answer 503 then 200, with a 0.2 s wait before the re-fetch
    * submit a drop and wait until the countdown row shows
    * trigger the countdown row's action, wait until the banner is empty, then wait 400 ms
    * verify the URL was fetched only once
    * verify the title is unchanged
    """
    doc_model = model()
    fetcher = SequenceFetcher(503, 200)
    doc_actions = refetching_actions(doc_model, fetcher, image_downloads, delay=0.2)
    doc_actions.submit(drop())
    qtbot.waitUntil(lambda: countdown_row(doc_actions) is not None, timeout=WAIT_TIMEOUT_MS)

    action = cast(MessageBannerRow, countdown_row(doc_actions)).action
    assert action is not None
    action.trigger()
    qtbot.waitUntil(lambda: not doc_actions.notice, timeout=WAIT_TIMEOUT_MS)
    qtbot.wait(400)

    assert fetcher.calls == [URL]
    assert doc_model.title == "Original"


def test_detach_mid_countdown_drops_the_retry(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """A document closed while a re-fetch waits never fetches again (#368).

    **Test steps:**

    * answer 503 then 200, with a 0.2 s wait before the re-fetch
    * submit a drop and wait until the countdown row shows
    * detach the actions and wait 400 ms
    * verify the URL was fetched only once
    * verify the banner is empty
    * verify the title is unchanged
    """
    doc_model = model()
    fetcher = SequenceFetcher(503, 200)
    doc_actions = refetching_actions(doc_model, fetcher, image_downloads, delay=0.2)
    doc_actions.submit(drop())
    qtbot.waitUntil(lambda: countdown_row(doc_actions) is not None, timeout=WAIT_TIMEOUT_MS)

    doc_actions.detach()
    qtbot.wait(400)

    assert fetcher.calls == [URL]
    assert not doc_actions.notice
    assert doc_model.title == "Original"


def test_a_path_change_mid_countdown_drops_the_retry(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """A document moved while a re-fetch waits drops it -- the next attempt would land on a document
    that is no longer the one that asked (#368).

    **Test steps:**

    * answer 503 then 200, with a 0.2 s wait before the re-fetch
    * submit a drop and wait until the countdown row shows
    * move the document to another path, waiting for the actions to report a change, then wait 400 ms
    * verify the URL was fetched only once
    * verify the banner is empty
    * verify the title is unchanged
    """
    doc_model = model()
    fetcher = SequenceFetcher(503, 200)
    doc_actions = refetching_actions(doc_model, fetcher, image_downloads, delay=0.2)
    doc_actions.submit(drop())
    qtbot.waitUntil(lambda: countdown_row(doc_actions) is not None, timeout=WAIT_TIMEOUT_MS)

    with qtbot.waitSignal(doc_actions.changed, timeout=WAIT_TIMEOUT_MS):
        doc_model.path = Path("/fake/library/sculpting/moved.rehu")
    qtbot.wait(400)

    assert fetcher.calls == [URL]
    assert not doc_actions.notice
    assert doc_model.title == "Original"


def test_each_refetch_is_scheduled_by_its_own_number(
    mocker: MockerFixture, qtbot: QtBot, image_downloads: ImageDownloads
) -> None:
    """The pause grows with each re-fetch (`refetch_delay`): the chain hands it 1 for the first, 2 for the
    second, so the waits lengthen rather than repeat (#369).

    **Test steps:**

    * spy on ``refetch_delay`` and answer the fetches 503, 503, then 200
    * submit a drop and wait until the new title has landed
    * verify the spy was called with the re-fetch numbers 1 and 2, in that order
    """
    spy = mocker.spy(scrape_actions, "refetch_delay")
    doc_model = model()
    doc_actions = refetching_actions(doc_model, SequenceFetcher(503, 503, 200), image_downloads)

    doc_actions.submit(drop())
    qtbot.waitUntil(lambda: doc_model.title == "New Title", timeout=WAIT_TIMEOUT_MS)

    assert [entry.args[1] for entry in spy.call_args_list] == [1, 2]


def test_the_countdown_row_ticks(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """A waiting re-fetch's row is a WARNING naming the reason, the URL, the seconds left and the
    attempt, re-said each second as the clock runs down (#368).

    **Test steps:**

    * answer 503 then 200, with a 60 s wait on a hand-set clock
    * submit a drop and wait until the countdown row shows
    * verify the row is a WARNING whose text names the reason, the URL, 60 s and attempt 2
    * advance the clock by 2.5 s and wait for the actions to report a change
    * verify the row's text now says 58 s, still attempt 2
    * detach the actions
    """
    doc_model = model()
    clock = FakeClock()
    doc_actions = refetching_actions(doc_model, SequenceFetcher(503, 200), image_downloads, delay=60.0, clock=clock)
    doc_actions.submit(drop())
    qtbot.waitUntil(lambda: countdown_row(doc_actions) is not None, timeout=WAIT_TIMEOUT_MS)
    row = cast(MessageBannerRow, countdown_row(doc_actions))
    assert row.severity == MessageBannerSeverity.WARNING
    assert row.text == f"Example answered 503 — trying {URL} in 60 s (attempt 2 of {MAX_REFETCHES + 1})"

    clock.now += 2.5
    with qtbot.waitSignal(doc_actions.changed, timeout=WAIT_TIMEOUT_MS):
        pass

    assert f"in 58 s (attempt 2 of {MAX_REFETCHES + 1})" in cast(MessageBannerRow, countdown_row(doc_actions)).text
    doc_actions.detach()


def test_two_waiting_drops_each_show_a_countdown(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """Two drops waiting to re-fetch at once each keep their own countdown row, on one shared tick (#368).

    **Test steps:**

    * answer every fetch with a 503, with a 60 s wait before the re-fetch
    * submit two drops and wait until two rows carry an action
    * verify the banner holds exactly two rows
    * detach the actions
    """
    doc_model = model()
    doc_actions = refetching_actions(doc_model, SequenceFetcher(503), image_downloads, delay=60.0)

    doc_actions.submit(drop())
    doc_actions.submit(drop())
    qtbot.waitUntil(lambda: sum(row.action is not None for row in doc_actions.notice) == 2, timeout=WAIT_TIMEOUT_MS)

    assert len(doc_actions.notice) == 2
    doc_actions.detach()


def test_a_path_change_mid_attempt_drops_its_refetch_request(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """A document moved while an attempt is in flight discards that attempt's re-fetch request: the
    drop ends, with no further fetch and no row left behind (#368).

    **Test steps:**

    * answer 503 then 200, through an executor that holds the job; submit a drop and wait until it holds one
    * move the document to another path, then run the held job and wait until the banner is empty
    * verify the URL was fetched only once
    * verify the executor holds no further job
    """
    doc_model = model()
    fetcher = SequenceFetcher(503, 200)
    executor = HoldingExecutor()
    doc_actions = refetching_actions(doc_model, fetcher, image_downloads, executor=executor)
    doc_actions.submit(drop())
    qtbot.waitUntil(lambda: bool(executor.jobs), timeout=WAIT_TIMEOUT_MS)

    doc_model.path = Path("/fake/library/sculpting/moved.rehu")
    executor.run_next()
    qtbot.waitUntil(lambda: not doc_actions.notice, timeout=WAIT_TIMEOUT_MS)
    qtbot.wait(50)

    assert fetcher.calls == [URL]
    assert not executor.jobs


def test_detach_mid_attempt_ignores_its_refetch_request(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """A document closed while an attempt is in flight never schedules the re-fetch that attempt asks
    for (#368).

    **Test steps:**

    * answer 503 then 200, through an executor that holds the job; submit a drop and wait until it holds one
    * detach the actions, then run the held job
    * verify the URL was fetched only once
    * verify the banner is empty
    """
    doc_model = model()
    fetcher = SequenceFetcher(503, 200)
    executor = HoldingExecutor()
    doc_actions = refetching_actions(doc_model, fetcher, image_downloads, executor=executor)
    doc_actions.submit(drop())
    qtbot.waitUntil(lambda: bool(executor.jobs), timeout=WAIT_TIMEOUT_MS)

    doc_actions.detach()
    executor.run_next()
    qtbot.wait(50)

    assert fetcher.calls == [URL]
    assert not doc_actions.notice


def test_a_cancel_arriving_after_its_drop_ended_is_ignored(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """Cancel is delivered queued, so the drop can end first -- here, by the document closing between the
    click and its delivery; the late cancel then finds nothing to drop (#368).

    **Test steps:**

    * answer 503 then 200, with a 60 s wait; submit a drop and wait until the countdown row shows
    * trigger the row's action, then detach the actions at once and wait briefly
    * verify the banner is empty
    """
    doc_model = model()
    doc_actions = refetching_actions(doc_model, SequenceFetcher(503, 200), image_downloads, delay=60.0)
    doc_actions.submit(drop())
    qtbot.waitUntil(lambda: countdown_row(doc_actions) is not None, timeout=WAIT_TIMEOUT_MS)
    action = cast(MessageBannerRow, countdown_row(doc_actions)).action
    assert action is not None

    action.trigger()
    doc_actions.detach()
    qtbot.wait(50)

    assert not doc_actions.notice


# endregion

# region ArtStation's refused store page (#369)

ARTSTATION_STORE_URL: Final = "https://anartist.artstation.com/store/12345/example"
ARTSTATION_MARKETPLACE_URL: Final = "https://www.artstation.com/marketplace/p/12345/example"


def artstation_actions(
    doc_model: RehuDocumentModel, fetcher: SequenceFetcher, image_downloads: ImageDownloads
) -> ScrapeActions:
    """`ScrapeActions` over the real `ArtStation` scraper, found for either of its URL shapes."""
    registry = FakeRegistry({ARTSTATION_STORE_URL: ArtStation(), ARTSTATION_MARKETPLACE_URL: ArtStation()})
    return build_actions(doc_model, registry, SyncExecutor(), fetcher, image_downloads)


def test_a_refused_store_page_is_retried_on_the_marketplace_url(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """The real scraper through the whole chain: a 503 from the store host, and the next attempt fetches
    the marketplace URL, whose 200 lands as the result.

    **Test steps:**

    * answer 503 then 200 for the real ArtStation scraper
    * drop the store URL and wait until the banner is empty
    * verify the fetches were the store URL, then the marketplace URL
    * verify the last source is the marketplace URL
    """
    doc_model = model()
    fetcher = SequenceFetcher(503, 200)
    doc_actions = artstation_actions(doc_model, fetcher, image_downloads)

    doc_actions.submit(UrlDrop(url=ARTSTATION_STORE_URL, fragment=None))
    qtbot.waitUntil(lambda: not doc_actions.notice, timeout=WAIT_TIMEOUT_MS)

    assert fetcher.calls == [ARTSTATION_STORE_URL, ARTSTATION_MARKETPLACE_URL]
    assert doc_model.sources[-1]["url"] == ARTSTATION_MARKETPLACE_URL


def test_a_refused_marketplace_page_is_retried_on_itself(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """A marketplace 503 has no store URL to fall back on, so the same URL is fetched again.

    **Test steps:**

    * answer 503 then 200 for the real ArtStation scraper
    * drop the marketplace URL and wait until the banner is empty
    * verify the marketplace URL was fetched twice
    * verify the last source is the marketplace URL
    """
    doc_model = model()
    fetcher = SequenceFetcher(503, 200)
    doc_actions = artstation_actions(doc_model, fetcher, image_downloads)

    doc_actions.submit(UrlDrop(url=ARTSTATION_MARKETPLACE_URL, fragment=None))
    qtbot.waitUntil(lambda: not doc_actions.notice, timeout=WAIT_TIMEOUT_MS)

    assert fetcher.calls == [ARTSTATION_MARKETPLACE_URL, ARTSTATION_MARKETPLACE_URL]
    assert doc_model.sources[-1]["url"] == ARTSTATION_MARKETPLACE_URL


class StockErrorPageFetcher:  # pylint: disable=missing-function-docstring,too-few-public-methods
    """Answers the first fetch with ArtStation's stock 503 page and no status -- how a browser that cannot
    report one leaves it -- and every later fetch with an ordinary page."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch(self, url: str) -> Page:
        self.calls.append(url)
        if len(self.calls) == 1:
            html = "<html><head><title>503 Service Temporarily Unavailable</title></head><body></body></html>"
            return Page(url=url, final_url=url, html=html)
        return Page(url=url, final_url=url, html="<html></html>", status=200)


def test_a_stock_error_page_with_no_status_is_retried(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """The page itself is enough: a stock 503 page carrying no status still sends the retry to the
    marketplace URL (#369).

    **Test steps:**

    * fetch ArtStation's stock 503 page with no status first, an ordinary page after it
    * drop the store URL and wait until the banner is empty
    * verify the fetches were the store URL, then the marketplace URL
    """
    doc_model = model()
    fetcher = StockErrorPageFetcher()
    registry = FakeRegistry({ARTSTATION_STORE_URL: ArtStation(), ARTSTATION_MARKETPLACE_URL: ArtStation()})
    doc_actions = build_actions(doc_model, registry, SyncExecutor(), fetcher, image_downloads)

    doc_actions.submit(UrlDrop(url=ARTSTATION_STORE_URL, fragment=None))
    qtbot.waitUntil(lambda: not doc_actions.notice, timeout=WAIT_TIMEOUT_MS)

    assert fetcher.calls == [ARTSTATION_STORE_URL, ARTSTATION_MARKETPLACE_URL]


# endregion
