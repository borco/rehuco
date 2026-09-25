"""Tests for `ScrapeActions` (#272): a dropped URL applied to the Main Editor as a reviewable edit."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, cast
from unittest.mock import call

from borco_pyside.widgets import MessageBannerSeverity
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.image_downloads import ImageDownloads
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.documents.scrape_actions import ScrapeActions
from rehuco_agent.scraping.protocols import PageFetcher
from rehuco_agent.scraping.registry import ScraperRegistry
from rehuco_agent.scraping.results import Page, ScrapedImage, ScrapeResult
from rehuco_agent.scraping.scraper_executor import ScraperExecutor
from rehuco_agent.scraping.url_drop import UrlDrop
from rehuco_core import LockReason, LockReasonKind, RehuDocument

PATH: Final = Path("/fake/library/sculpting/info.rehu")
URL: Final = "https://example.com/page"

WAIT_TIMEOUT_MS: Final = 2000


@dataclass
# duplicate-code: deliberately the same shape `test_scrape_job.py`'s FakeScraper uses
class FakeScraper:  # pylint: disable=missing-function-docstring,duplicate-code
    """A minimal `SiteScraper`, the same shape `test_scrape_job.py`'s uses."""

    label: str = "Fake"
    publisher: str = "Example Publisher"
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

    def find(self, url: str) -> FakeScraper | None:
        return self.__by_url.get(url)


class SyncExecutor:  # pylint: disable=missing-function-docstring,too-few-public-methods
    """Runs a `ScrapeJob` immediately, inline, rather than on a real pool -- deterministic for these
    tests, at the cost of not exercising `ScraperExecutor` itself (`test_scraper_executor.py` does)."""

    def submit(self, job: object) -> None:
        job.run()  # type: ignore[attr-defined]


class FakeFetcher:  # pylint: disable=missing-function-docstring,too-few-public-methods
    """A `PageFetcher` stand-in that never touches the network -- every drop in this module carries no
    fragment, so `ScrapeJob` would otherwise fall back to a real `HttpPageFetcher`."""

    def fetch(self, url: str) -> Page:
        return Page(url=url, final_url=url, html="<html></html>")


def document(resource_type: str = "Tutorial") -> RehuDocument:
    """An in-memory, path-bearing document with a primary source."""
    doc = RehuDocument(
        {
            "type": resource_type,
            "sources": [{"title": "Original", "publisher": "Original Co", "url": "https://original.example"}],
        }
    )
    return doc


def model(resource_type: str = "Tutorial") -> RehuDocumentModel:
    """A view-model over a fresh document at :data:`PATH`."""
    result = RehuDocumentModel(document(resource_type))
    result.path = PATH
    return result


def drop(fragment: str | None = None) -> UrlDrop:
    """A parsed drop for :data:`URL`."""
    return UrlDrop(url=URL, fragment=fragment)


def build_actions(
    doc_model: RehuDocumentModel,
    registry: object,
    executor: object,
    fetcher: object,
    image_downloads: ImageDownloads,
) -> ScrapeActions:
    """Construct `ScrapeActions` over test doubles, casting past their structural mismatch with the
    concrete `ScraperRegistry`/`ScraperExecutor` types (`PageFetcher` alone is a real Protocol)."""
    return ScrapeActions(
        doc_model,
        image_downloads,
        registry=cast(ScraperRegistry, registry),
        executor=cast(ScraperExecutor, executor),
        fetcher=cast(PageFetcher, fetcher),
    )


def actions(
    doc_model: RehuDocumentModel, scraper: FakeScraper | None, image_downloads: ImageDownloads
) -> ScrapeActions:
    """`ScrapeActions` wired to a fake registry answering ``scraper`` for :data:`URL`, a synchronous
    executor, and a fetcher that never touches the network."""
    registry = FakeRegistry({URL: scraper})
    return build_actions(doc_model, registry, SyncExecutor(), FakeFetcher(), image_downloads)


@fixture
def image_downloads(mocker: MockerFixture) -> ImageDownloads:
    """A mock `ImageDownloads`, standing in for #73's image-acquisition seam this class hands its
    results' images off to."""
    return mocker.create_autospec(ImageDownloads, instance=True)


# region applying a result


def test_scraped_fields_land_and_dirty_the_model(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """Declared fields from the result are written through, and the model ends up dirty (#272)."""
    doc_model = model()
    result = ScrapeResult(fields={"title": "New Title", "advertised_duration": 3600}, description=None, images=())
    doc_actions = actions(doc_model, FakeScraper(result=result), image_downloads)

    with qtbot.waitSignal(doc_actions.changed, timeout=WAIT_TIMEOUT_MS):
        doc_actions.submit(drop())
    qtbot.wait(20)

    assert doc_model.title == "New Title"
    assert doc_model.advertised_duration == 3600
    assert doc_model.dirty is True


def test_a_field_the_result_does_not_carry_is_left_untouched(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """A field absent from the result's `fields` keeps its current value (#272)."""
    doc_model = model()
    doc_model.released = "2020"
    result = ScrapeResult(fields={"title": "New Title"}, description=None, images=())
    doc_actions = actions(doc_model, FakeScraper(result=result), image_downloads)

    with qtbot.waitSignal(doc_actions.changed, timeout=WAIT_TIMEOUT_MS):
        doc_actions.submit(drop())
    qtbot.wait(20)

    assert doc_model.released == "2020"


def test_a_field_the_type_does_not_declare_is_skipped(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """`level` is Tutorial-only; a ReferenceImages document leaves it alone rather than raise (#272)."""
    doc_model = model("ReferenceImages")
    result = ScrapeResult(fields={"title": "New Title", "level": ["beginner"]}, description=None, images=())
    doc_actions = actions(doc_model, FakeScraper(result=result), image_downloads)

    with qtbot.waitSignal(doc_actions.changed, timeout=WAIT_TIMEOUT_MS):
        doc_actions.submit(drop())
    qtbot.wait(20)

    assert doc_model.title == "New Title"
    assert doc_model.level == []


def test_the_description_gets_the_stem_substituted(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """`ScrapeResult.description`'s stem-less placeholders become this document's real `<stem>NN` (#272)."""
    doc_model = model()
    result = ScrapeResult(fields={}, description="See ![](#image-00) for reference.", images=())
    doc_actions = actions(doc_model, FakeScraper(result=result), image_downloads)

    with qtbot.waitSignal(doc_actions.changed, timeout=WAIT_TIMEOUT_MS):
        doc_actions.submit(drop())
    qtbot.wait(20)

    # PATH is "info.rehu" -- directory-scoped -- so the stem is the parent folder's name (#250)
    assert doc_model.description == "See ![](sculpting00) for reference."


def test_the_fields_description_is_used_when_the_result_has_none(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """A scraper that only fills ``fields["description"]`` still lands, unsubstituted (#272)."""
    doc_model = model()
    result = ScrapeResult(fields={"description": "Plain text, no images."}, description=None, images=())
    doc_actions = actions(doc_model, FakeScraper(result=result), image_downloads)

    with qtbot.waitSignal(doc_actions.changed, timeout=WAIT_TIMEOUT_MS):
        doc_actions.submit(drop())
    qtbot.wait(20)

    assert doc_model.description == "Plain text, no images."


def test_a_source_is_added_from_the_scraper_and_page(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """The scraper's publisher and the scraped page's URL are added as a source (#272)."""
    doc_model = model()
    doc_actions = actions(doc_model, FakeScraper(publisher="Example Publisher"), image_downloads)

    with qtbot.waitSignal(doc_actions.changed, timeout=WAIT_TIMEOUT_MS):
        doc_actions.submit(drop())
    qtbot.wait(20)

    assert doc_model.sources[-1]["url"] == URL
    assert doc_model.sources[-1]["publisher"] == "Example Publisher"


def test_a_drop_carrying_a_fragment_is_scraped_without_a_fetch(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """A selection drop's `text/html` is handed to the scraper as the page itself; nothing is fetched
    ([[acquisition-tooling#drag-drop-aids]], #272)."""
    doc_model = model()

    class FragmentScraper(FakeScraper):  # pylint: disable=missing-class-docstring
        def scrape_page(self, page: Page) -> object:
            return ScrapeResult(fields={"title": page.html}, description=None, images=())

    class RefusingFetcher:  # pylint: disable=missing-class-docstring,too-few-public-methods
        def fetch(self, url: str) -> Page:
            """Fail the test if anything fetches: a fragment drop must never reach the network."""
            raise AssertionError(f"unexpected fetch of {url}")

    registry = FakeRegistry({URL: FragmentScraper()})
    doc_actions = build_actions(doc_model, registry, SyncExecutor(), RefusingFetcher(), image_downloads)

    with qtbot.waitSignal(doc_actions.changed, timeout=WAIT_TIMEOUT_MS):
        doc_actions.submit(drop(fragment="<h1>From the fragment</h1>"))
    qtbot.wait(20)

    assert doc_model.title == "<h1>From the fragment</h1>"


def test_each_scraped_image_is_handed_to_image_downloads(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """Every `ScrapedImage` a result carries is handed to `.ImageDownloads.submit`, url/referrer/slot
    intact -- this class never touches a file itself (#73) (#272)."""
    doc_model = model()
    images = (
        ScrapedImage(0, "https://x/one.jpg", "https://x/"),
        ScrapedImage(1, "https://x/two.jpg", None),
    )
    result = ScrapeResult(fields={"title": "New Title"}, description=None, images=images)
    doc_actions = actions(doc_model, FakeScraper(result=result), image_downloads)

    with qtbot.waitSignal(doc_actions.changed, timeout=WAIT_TIMEOUT_MS):
        doc_actions.submit(drop())
    qtbot.wait(20)

    assert doc_model.title == "New Title"
    assert image_downloads.submit.call_args_list == [  # type: ignore[attr-defined]
        call("https://x/one.jpg", "https://x/", 0),
        call("https://x/two.jpg", None, 1),
    ]


# endregion
# region discarding a result


def test_submit_is_a_no_op_for_a_document_with_no_path(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """A drop on a not-yet-saved document (no path) is refused: there is nowhere to log it under, and
    no way to tell later whether it is still the same document (#272)."""
    doc_model = RehuDocumentModel(document())
    assert doc_model.path is None
    doc_actions = actions(doc_model, FakeScraper(), image_downloads)

    doc_actions.submit(drop())
    qtbot.wait(20)

    assert not doc_actions.notice
    assert doc_model.title == "Original"


def test_a_locked_document_discards_an_arriving_result(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """A result for a document that has become locked while its page was being fetched is discarded,
    never applied (#272)."""
    doc_model = model()
    registry = FakeRegistry(
        {URL: FakeScraper(result=ScrapeResult(fields={"title": "New"}, description=None, images=()))}
    )

    class LockingExecutor:  # pylint: disable=missing-class-docstring,too-few-public-methods
        def submit(self, job: object) -> None:
            """Lock the document out from under the scrape before running it."""
            doc_model.lock_reasons = [LockReason(LockReasonKind.NEWER_FORMAT, "locked mid-scrape")]
            job.run()  # type: ignore[attr-defined]

    doc_actions = build_actions(doc_model, registry, LockingExecutor(), FakeFetcher(), image_downloads)

    with qtbot.waitSignal(doc_actions.changed, timeout=WAIT_TIMEOUT_MS):
        doc_actions.submit(drop())
    qtbot.wait(20)

    assert doc_model.title == "Original"


def test_a_path_change_before_the_result_arrives_discards_it(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """A result for a document that has since moved is discarded, never applied (#272)."""
    doc_model = model()
    registry = FakeRegistry(
        {URL: FakeScraper(result=ScrapeResult(fields={"title": "New"}, description=None, images=()))}
    )

    class LateExecutor:  # pylint: disable=missing-class-docstring,too-few-public-methods
        def submit(self, job: object) -> None:
            """Move the document out from under the scrape before running it."""
            doc_model.path = Path("/fake/library/sculpting/moved.rehu")
            job.run()  # type: ignore[attr-defined]

    doc_actions = build_actions(doc_model, registry, LateExecutor(), FakeFetcher(), image_downloads)

    with qtbot.waitSignal(doc_actions.changed, timeout=WAIT_TIMEOUT_MS):
        doc_actions.submit(drop())
    qtbot.wait(20)

    assert doc_model.title == "Original"


def test_detach_discards_a_result_that_arrives_afterward(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """A detached document's in-flight scrape is never applied once it lands (#272)."""
    doc_model = model()
    doc_actions = actions(
        doc_model,
        FakeScraper(result=ScrapeResult(fields={"title": "New"}, description=None, images=())),
        image_downloads,
    )

    doc_actions.submit(drop())
    doc_actions.detach()
    qtbot.wait(50)

    assert doc_model.title == "Original"


def test_detach_discards_a_failure_that_arrives_afterward(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """A detached document's in-flight scrape never records its failure once it lands, either (#272)."""
    doc_model = model()
    doc_actions = actions(doc_model, None, image_downloads)

    doc_actions.submit(drop())
    doc_actions.detach()
    qtbot.wait(50)

    assert not doc_actions.notice


# endregion
# region the banner


def test_a_no_match_gives_a_warning_row_naming_the_host(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """No scraper for the host is a WARNING row, like every other failure: the drop did not do what it
    was dropped for (#272, #73)."""
    doc_model = model()
    doc_actions = actions(doc_model, None, image_downloads)

    with qtbot.waitSignal(doc_actions.changed, timeout=WAIT_TIMEOUT_MS):
        doc_actions.submit(drop())
    qtbot.wait(20)

    assert len(doc_actions.notice) == 1
    assert doc_actions.notice[0].severity == MessageBannerSeverity.WARNING
    assert "example.com" in doc_actions.notice[0].text


def test_a_fetch_failure_gives_a_warning_row(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """Any other scrape failure is a WARNING row (#272)."""
    doc_model = model()

    class RaisingScraper(FakeScraper):  # pylint: disable=missing-class-docstring
        def scrape_page(self, page: Page) -> object:
            del page
            raise RuntimeError("boom")

    doc_actions = actions(doc_model, RaisingScraper(), image_downloads)

    with qtbot.waitSignal(doc_actions.changed, timeout=WAIT_TIMEOUT_MS):
        doc_actions.submit(drop())
    qtbot.wait(20)

    assert len(doc_actions.notice) == 1
    assert doc_actions.notice[0].severity == MessageBannerSeverity.WARNING


def test_the_next_drop_replaces_the_previous_failures_row(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """A new drop's outcome replaces the last one's row, not accumulates beside it (#272)."""
    doc_model = model()
    doc_actions = actions(doc_model, None, image_downloads)
    with qtbot.waitSignal(doc_actions.changed, timeout=WAIT_TIMEOUT_MS):
        doc_actions.submit(drop())
    qtbot.wait(20)
    assert len(doc_actions.notice) == 1

    with qtbot.waitSignal(doc_actions.changed, timeout=WAIT_TIMEOUT_MS):
        doc_actions.submit(drop())
    qtbot.wait(20)

    assert len(doc_actions.notice) == 1


def test_the_busy_row_appears_while_a_scrape_is_in_flight(image_downloads: ImageDownloads) -> None:
    """A submitted scrape shows an INFO row immediately, before the (synchronous, here) executor runs it."""
    doc_model = model()

    class NeverRunningExecutor:  # pylint: disable=missing-class-docstring,too-few-public-methods
        def submit(self, job: object) -> None:
            """Accept the job and do nothing with it -- the point of this test."""
            del job

    registry = FakeRegistry({URL: FakeScraper()})
    doc_actions = build_actions(doc_model, registry, NeverRunningExecutor(), None, image_downloads)

    doc_actions.submit(drop())

    assert len(doc_actions.notice) == 1
    assert doc_actions.notice[0].severity == MessageBannerSeverity.INFO
    assert "example.com" in doc_actions.notice[0].text


# endregion
