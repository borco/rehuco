"""Tests for `ScrapeActions` (#272): a dropped URL applied to the Main Editor as a reviewable edit."""

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, cast
from unittest.mock import call

from borco_pyside.widgets import MessageBannerRow, MessageBannerSeverity
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.image_downloads import ImageDownloads
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.documents.scrape_actions import ScrapeActions
from rehuco_agent.scraping.protocols import PageFetcher, RefetchRequestedError
from rehuco_agent.scraping.registry import ScraperRegistry
from rehuco_agent.scraping.results import Page, ScrapedImage, ScrapeResult
from rehuco_agent.scraping.scraper_executor import ScraperExecutor
from rehuco_agent.scraping.url_drop import UrlDrop
from rehuco_core import LockReason, LockReasonKind, RehuDocument
from rehuco_core.access import LoadedRecord, ResourceKey

PATH: Final = Path.cwd() / "fake" / "library" / "sculpting" / "info.rehu"
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

    def __init__(self, by_url: dict[str, object]) -> None:
        self.__by_url = by_url

    def find(self, url: str) -> object:
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


class SequenceFetcher:  # pylint: disable=missing-function-docstring,too-few-public-methods
    """A `PageFetcher` stand-in answering each fetch with the next of ``statuses``, repeating the last
    one once they run out -- a site that answers 503 a few times, then 200 (or never)."""

    def __init__(self, *statuses: int) -> None:
        self.__statuses = list(statuses)
        self.calls: list[str] = []

    def fetch(self, url: str) -> Page:
        self.calls.append(url)
        status = self.__statuses.pop(0) if len(self.__statuses) > 1 else self.__statuses[0]
        return Page(url=url, final_url=url, html="<html></html>", status=status)


class HoldingExecutor:
    """Accepts each job and holds it, for the test to run once it has changed something mid-flight."""

    def __init__(self) -> None:
        self.jobs: list[object] = []

    def submit(self, job: object) -> None:
        """Hold ``job`` unrun."""
        self.jobs.append(job)

    def run_next(self) -> None:
        """Run the oldest held job, inline."""
        self.jobs.pop(0).run()  # type: ignore[attr-defined]


class RefetchingScraper(FakeScraper):
    """Asks for the same URL again on every page answered with a 503, and scrapes every other page."""

    def scrape_page(self, page: Page) -> object:
        if page.status == 503:
            raise RefetchRequestedError("Example answered 503")
        return self.result


class FakeClock:  # pylint: disable=too-few-public-methods
    """A monotonic clock a test sets by hand."""

    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


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
    result.key = ResourceKey(PATH)
    result.path = PATH
    return result


def sourceless_model(resource_type: str = "Tutorial") -> RehuDocumentModel:
    """A view-model over a fresh document with no source at all, at :data:`PATH` -- the case a first
    scrape lands on."""
    result = RehuDocumentModel(RehuDocument({"type": resource_type}))
    result.key = ResourceKey(PATH)
    result.path = PATH
    return result


def drop(fragment: str | None = None) -> UrlDrop:
    """A parsed drop for :data:`URL`."""
    return UrlDrop(url=URL, fragment=fragment)


def build_actions(  # pylint: disable=too-many-arguments
    doc_model: RehuDocumentModel,
    registry: object,
    executor: object,
    fetcher: object,
    image_downloads: ImageDownloads,
    *,
    delay: float = 0.0,
    clock: FakeClock | None = None,
) -> ScrapeActions:
    """Construct `ScrapeActions` over test doubles, casting past their structural mismatch with the
    concrete `ScraperRegistry`/`ScraperExecutor` types (`PageFetcher` alone is a real Protocol). Every
    re-fetch waits ``delay`` seconds, whatever range it asked for; deleted when the test ends
    (:func:`delete_built_actions`)."""
    built = ScrapeActions(
        doc_model,
        image_downloads,
        registry=cast(ScraperRegistry, registry),
        executor=cast(ScraperExecutor, executor),
        fetcher=cast(PageFetcher, fetcher),
        choose_delay=lambda *_: delay,
        clock=clock,
    )
    BUILT_ACTIONS.append(built)
    return built


BUILT_ACTIONS: Final[list[ScrapeActions]] = []
"""Every `ScrapeActions` :func:`build_actions` built in the running test, for :func:`delete_built_actions`."""


@fixture(autouse=True)
def delete_built_actions() -> Iterator[None]:
    """Delete every `ScrapeActions` the test built, as the window's sub-docks would (#529).

    Left to Python, the last references to one are the closures its own chains' timers and actions carry: deleting
    an ended chain's timer releases them inside the timer's destruction, and the actions' wrapper then deletes the
    actions -- and that timer a second time -- from inside it. In the app the actions are their sub-docks' child,
    so their wrapper never deletes them.
    """
    yield
    while BUILT_ACTIONS:
        BUILT_ACTIONS.pop().deleteLater()


def refetching_actions(  # pylint: disable=too-many-arguments
    doc_model: RehuDocumentModel,
    fetcher: SequenceFetcher,
    image_downloads: ImageDownloads,
    *,
    delay: float = 0.0,
    clock: FakeClock | None = None,
    executor: object | None = None,
) -> ScrapeActions:
    """`ScrapeActions` whose scraper asks for a re-fetch of every 503 ``fetcher`` answers, run inline
    unless an ``executor`` is given."""
    result = ScrapeResult(fields={"title": "New Title"}, description=None, images=())
    registry = FakeRegistry({URL: RefetchingScraper(result=result)})
    executor = executor if executor is not None else SyncExecutor()
    return build_actions(doc_model, registry, executor, fetcher, image_downloads, delay=delay, clock=clock)


def countdown_row(doc_actions: ScrapeActions) -> MessageBannerRow | None:
    """The banner's waiting re-fetch row, if one shows."""
    return next((row for row in doc_actions.notice if row.action is not None), None)


def actions(
    doc_model: RehuDocumentModel, scraper: FakeScraper | None, image_downloads: ImageDownloads
) -> ScrapeActions:
    """`ScrapeActions` wired to a fake registry answering ``scraper`` for :data:`URL`, a synchronous
    executor, and a fetcher that never touches the network."""
    registry = FakeRegistry({URL: scraper})
    return build_actions(doc_model, registry, SyncExecutor(), FakeFetcher(), image_downloads)


def resolve(qtbot: QtBot, doc_actions: ScrapeActions, url_drop: UrlDrop) -> None:
    """Submit a drop and wait until it has resolved -- no busy row left -- rather than for a fixed time: its
    outcome lands two event-loop turns after ``changed`` first fires, the attempt's timer and then the relay's
    queued answer.

    :param qtbot: pytest-qt fixture.
    :param doc_actions: the actions to submit to.
    :param url_drop: the drop.
    """
    doc_actions.submit(url_drop)
    qtbot.waitUntil(
        lambda: all(row.severity is not MessageBannerSeverity.INFO for row in doc_actions.notice),
        timeout=WAIT_TIMEOUT_MS,
    )


@fixture(name="image_downloads")
def fixture_image_downloads(mocker: MockerFixture) -> ImageDownloads:
    """A mock `ImageDownloads`, standing in for #73's image-acquisition seam this class hands its
    results' images off to."""
    return mocker.create_autospec(ImageDownloads, instance=True)


# region applying a result


def test_scraped_fields_land_and_dirty_the_model(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """Declared fields from the result are written through, and the model ends up dirty (#272).

    **Test steps:**

    * drop a page whose result carries a title and an advertised duration
    * verify the model holds both values
    * verify the model is dirty
    """
    doc_model = model()
    result = ScrapeResult(fields={"title": "New Title", "advertised_duration": 3600}, description=None, images=())
    doc_actions = actions(doc_model, FakeScraper(result=result), image_downloads)

    resolve(qtbot, doc_actions, drop())

    assert doc_model.title == "New Title"
    assert doc_model.advertised_duration == 3600
    assert doc_model.dirty is True


def test_an_asset_s_scraped_fields_reach_the_record(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """A drop on an asset writes the asset block's fields onto the record; before the model had properties for
    them they stayed behind as stray attributes of the model and nothing was saved (#701).

    **Test steps:**

    * drop a page whose result carries a title and asset fields onto an asset document
    * verify the record holds each asset field, read as its own property reads it
    * verify the title landed and the model is dirty
    """
    doc_model = model("asset")
    fields = {
        "title": "New Title",
        "kind": "model",
        "license": "cc-by-4.0",
        "formats": ["fbx", "obj"],
        "compatibility": {"unreal": "5.0-5.5"},
        "source_updated": "2025-09-08",
        "advertised_size": 123,
        "advertised_triangles": "12",
    }
    result = ScrapeResult(fields=fields, description=None, images=())
    doc_actions = actions(doc_model, FakeScraper(result=result), image_downloads)

    resolve(qtbot, doc_actions, drop())

    record = doc_model.document
    assert (record.kind, record.license, record.formats) == ("model", "cc-by-4.0", ["fbx", "obj"])
    assert record.compatibility == {"unreal": "5.0-5.5"}
    assert (record.source_updated, record.advertised_size, record.advertised_triangles) == ("2025-09-08", 123, "12")
    assert doc_model.title == "New Title"
    assert doc_model.dirty is True


def test_a_field_the_result_does_not_carry_is_left_untouched(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """A field absent from the result's `fields` keeps its current value (#272).

    **Test steps:**

    * set ``released`` on the model, then drop a page whose result carries only a title
    * verify ``released`` still holds its earlier value
    """
    doc_model = model()
    doc_model.released = "2020"
    result = ScrapeResult(fields={"title": "New Title"}, description=None, images=())
    doc_actions = actions(doc_model, FakeScraper(result=result), image_downloads)

    resolve(qtbot, doc_actions, drop())

    assert doc_model.released == "2020"


def test_a_field_the_type_does_not_declare_is_skipped(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """`level` is Tutorial-only; a ReferenceImages document leaves it alone rather than raise (#272).

    **Test steps:**

    * drop a page whose result carries a title and a ``level`` onto a ReferenceImages document
    * verify the title landed
    * verify ``level`` is still empty
    """
    doc_model = model("ReferenceImages")
    result = ScrapeResult(fields={"title": "New Title", "level": ["beginner"]}, description=None, images=())
    doc_actions = actions(doc_model, FakeScraper(result=result), image_downloads)

    resolve(qtbot, doc_actions, drop())

    assert doc_model.title == "New Title"
    assert doc_model.level == []


def test_the_description_gets_the_stem_substituted(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """`ScrapeResult.description`'s stem-less placeholders become this document's real `<stem>NN` (#272), named
    as its screenshots are (#682).

    **Test steps:**

    * drop a page whose description names an image placeholder on a directory-scoped record
    * verify the placeholder became ``info00``, the name its screenshots are written under
    """
    doc_model = model()
    result = ScrapeResult(fields={}, description="See ![](#image-00) for reference.", images=())
    doc_actions = actions(doc_model, FakeScraper(result=result), image_downloads)

    resolve(qtbot, doc_actions, drop())

    # PATH is "info.rehu" -- directory-scoped -- whose screenshots are info00, info01, ... (#682); the folder's name
    # is its rename target (#250), never its screenshots' stem
    assert doc_model.description == "See ![](info00) for reference."


def test_the_fields_description_is_used_when_the_result_has_none(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """A scraper that only fills ``fields["description"]`` still lands, unsubstituted (#272).

    **Test steps:**

    * drop a page whose result has no description of its own but a ``description`` field
    * verify the model's description is that field's text, unchanged
    """
    doc_model = model()
    result = ScrapeResult(fields={"description": "Plain text, no images."}, description=None, images=())
    doc_actions = actions(doc_model, FakeScraper(result=result), image_downloads)

    resolve(qtbot, doc_actions, drop())

    assert doc_model.description == "Plain text, no images."


def test_a_source_is_added_from_the_scraper_and_page(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """The scraper's publisher and the scraped page's URL are added as a source (#272).

    **Test steps:**

    * drop a page on a document that already has a source, with a scraper naming a publisher
    * verify the last source holds the dropped URL
    * verify the last source holds the scraper's publisher
    """
    doc_model = model()
    doc_actions = actions(doc_model, FakeScraper(publisher="Example Publisher"), image_downloads)

    resolve(qtbot, doc_actions, drop())

    assert doc_model.sources[-1]["url"] == URL
    assert doc_model.sources[-1]["publisher"] == "Example Publisher"


def test_a_scraped_url_field_becomes_primary_and_the_dropped_url_is_added_second(
    qtbot: QtBot, image_downloads: ImageDownloads
) -> None:
    """A scraper that returns a canonical ``url`` field distinct from the page dropped (e.g. ArtStation
    reconstructing the `www.artstation.com` URL from a store host, #366) has it added as a source ahead of
    the page actually dropped -- not written as a field -- so on a fresh document it fills the empty
    primary, publisher included, and the dropped page is appended as a second, non-primary source
    ([[acquisition-tooling#scraper-protocols]]).

    **Test steps:**

    * drop a page into a source-less document, with a result carrying a canonical ``url`` field
    * verify the model's url is the canonical one
    * verify the first source is the canonical URL with the scraper's publisher
    * verify the last source is the dropped URL with the same publisher
    * verify there are two sources and the model's publisher is the scraper's
    """
    doc_model = sourceless_model()
    canonical_url = "https://www.artstation.com/marketplace/p/aBcDe/example-product-tutorial"
    result = ScrapeResult(fields={"url": canonical_url}, description=None, images=())
    doc_actions = actions(doc_model, FakeScraper(publisher="ArtStation", result=result), image_downloads)

    resolve(qtbot, doc_actions, drop())

    assert doc_model.url == canonical_url
    assert doc_model.sources[0]["url"] == canonical_url
    assert doc_model.sources[0]["publisher"] == "ArtStation"
    assert doc_model.sources[-1]["url"] == URL
    assert doc_model.sources[-1]["publisher"] == "ArtStation"
    assert len(doc_model.sources) == 2
    assert doc_model.publisher == "ArtStation"


def test_a_scraped_url_field_is_kept_beside_an_existing_primary_not_written_over_it(
    qtbot: QtBot, image_downloads: ImageDownloads
) -> None:
    """On a document that already has a primary source, a canonical ``url`` and the dropped page are
    both appended and the primary is left exactly as it was -- URL and publisher alike (#366).

    **Test steps:**

    * drop a page on a document with a primary source, with a result carrying a canonical ``url`` field
    * verify the sources' URLs are the original, the canonical one and the dropped one, in that order
    * verify the primary's publisher is unchanged
    * verify the two appended sources carry the scraper's publisher
    """
    doc_model = model()
    canonical_url = "https://www.artstation.com/marketplace/p/aBcDe/example-product-tutorial"
    result = ScrapeResult(fields={"url": canonical_url}, description=None, images=())
    doc_actions = actions(doc_model, FakeScraper(publisher="ArtStation", result=result), image_downloads)

    resolve(qtbot, doc_actions, drop())

    assert [source["url"] for source in doc_model.sources] == ["https://original.example", canonical_url, URL]
    assert doc_model.sources[0]["publisher"] == "Original Co"
    assert doc_model.sources[1]["publisher"] == "ArtStation"
    assert doc_model.sources[2]["publisher"] == "ArtStation"


def test_a_scraped_url_field_equal_to_the_dropped_url_adds_no_second_source(
    qtbot: QtBot, image_downloads: ImageDownloads
) -> None:
    """A scraper whose canonical ``url`` field is the same string as the page dropped fills the primary
    source once, publisher included, and the second add finds it already there -- no second source
    appears.

    **Test steps:**

    * drop a page into a source-less document, with a result whose ``url`` field is the dropped URL
    * verify the model's url is that URL and its publisher is the scraper's
    * verify there is exactly one source
    """
    doc_model = sourceless_model()
    result = ScrapeResult(fields={"url": URL}, description=None, images=())
    doc_actions = actions(doc_model, FakeScraper(publisher="ArtStation", result=result), image_downloads)

    resolve(qtbot, doc_actions, drop())

    assert doc_model.url == URL
    assert doc_model.publisher == "ArtStation"
    assert len(doc_model.sources) == 1


def test_a_scraped_site_id_lands_on_the_canonical_source(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """A store id the scraper reports goes onto the source of the canonical ``url`` it came with, not onto the page
    dropped, and is no field write (#675, [[assets#site-id]]).

    **Test steps:**

    * scrape a page whose result carries a canonical ``url`` and a ``site_id``, into a source-less document
    * verify the canonical source holds the id and the dropped page's source does not
    """
    doc_model = sourceless_model()
    canonical_url = "https://www.artstation.com/marketplace/p/aBcDe/example-product-tutorial"
    result = ScrapeResult(fields={"url": canonical_url, "site_id": "aBcDe"}, description=None, images=())
    doc_actions = actions(doc_model, FakeScraper(publisher="ArtStation", result=result), image_downloads)

    resolve(qtbot, doc_actions, drop())

    assert [(source["url"], source.get("site_id")) for source in doc_model.sources] == [
        (canonical_url, "aBcDe"),
        (URL, None),
    ]


def test_a_scraped_site_id_without_a_canonical_url_lands_on_the_dropped_page(
    qtbot: QtBot, image_downloads: ImageDownloads
) -> None:
    """With no canonical ``url``, the reported id goes onto the source of the page dropped (#675).

    **Test steps:**

    * scrape a page whose result carries only a ``site_id``, into a source-less document
    * verify its one source is the dropped page, holding the id
    """
    doc_model = sourceless_model()
    result = ScrapeResult(fields={"site_id": "u-9"}, description=None, images=())
    doc_actions = actions(doc_model, FakeScraper(publisher="Udemy", result=result), image_downloads)

    resolve(qtbot, doc_actions, drop())

    assert [(source["url"], source.get("site_id")) for source in doc_model.sources] == [(URL, "u-9")]


def test_a_drop_carrying_a_fragment_is_scraped_without_a_fetch(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """A selection drop's `text/html` is handed to the scraper as the page itself; nothing is fetched
    ([[acquisition-tooling#drag-drop-aids]], #272).

    **Test steps:**

    * build the actions with a scraper that returns the page's html as the title, and a fetcher that fails the test
    * drop the URL with an html fragment
    * verify the title is the fragment, so it reached the scraper as the page and nothing was fetched
    """
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

    resolve(qtbot, doc_actions, drop(fragment="<h1>From the fragment</h1>"))

    assert doc_model.title == "<h1>From the fragment</h1>"


def test_each_scraped_image_is_handed_to_image_downloads(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """Every `ScrapedImage` a result carries is handed to `.ImageDownloads.submit`, url/referrer/slot
    intact -- this class never touches a file itself (#73) (#272).

    **Test steps:**

    * drop a page whose result carries a title and two images, one with a referrer and one without
    * verify the title landed
    * verify the mock ``ImageDownloads`` was submitted both images, in order, with their url, referrer and slot
    """
    doc_model = model()
    images = (
        ScrapedImage(0, "https://x/one.jpg", "https://x/"),
        ScrapedImage(1, "https://x/two.jpg", None),
    )
    result = ScrapeResult(fields={"title": "New Title"}, description=None, images=images)
    doc_actions = actions(doc_model, FakeScraper(result=result), image_downloads)

    resolve(qtbot, doc_actions, drop())

    assert doc_model.title == "New Title"
    assert image_downloads.submit.call_args_list == [  # type: ignore[attr-defined]
        call("https://x/one.jpg", "https://x/", 0),
        call("https://x/two.jpg", None, 1),
    ]


# endregion
# region discarding a result


def test_submit_is_a_no_op_for_a_document_with_no_path(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """A drop on a not-yet-saved document (no path) is refused: there is nowhere to log it under, and
    no way to tell later whether it is still the same document (#272).

    **Test steps:**

    * build the actions over a document that has no path, and verify it has none
    * submit a drop and wait briefly
    * verify there is no banner row
    * verify the title is unchanged
    """
    doc_model = RehuDocumentModel(document())
    assert doc_model.path is None
    doc_actions = actions(doc_model, FakeScraper(), image_downloads)

    doc_actions.submit(drop())
    qtbot.wait(20)

    assert not doc_actions.notice
    assert doc_model.title == "Original"


def test_a_locked_document_discards_an_arriving_result(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """A result for a document that has become locked while its page was being fetched is discarded,
    never applied (#272).

    **Test steps:**

    * use an executor that locks the document, then runs the job, when it is handed one
    * submit a drop and wait for the outcome to land
    * verify the title is unchanged
    """
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
    """A result for a document that has since moved is discarded, never applied (#272).

    **Test steps:**

    * use an executor that moves the document to another path, then runs the job, when it is handed one
    * submit a drop and wait for the outcome to land
    * verify the title is unchanged
    """
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
    """A detached document's in-flight scrape is never applied once it lands (#272).

    **Test steps:**

    * submit a drop to an executor that holds the job, and wait until it holds one
    * detach the actions, then run the held job
    * verify the title is unchanged
    """
    doc_model = model()
    registry = FakeRegistry(
        {URL: FakeScraper(result=ScrapeResult(fields={"title": "New"}, description=None, images=()))}
    )
    executor = HoldingExecutor()
    doc_actions = build_actions(doc_model, registry, executor, FakeFetcher(), image_downloads)
    doc_actions.submit(drop())
    qtbot.waitUntil(lambda: bool(executor.jobs), timeout=WAIT_TIMEOUT_MS)

    doc_actions.detach()
    executor.run_next()
    qtbot.wait(50)

    assert doc_model.title == "Original"


def test_detach_discards_a_failure_that_arrives_afterward(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """A detached document's in-flight scrape never records its failure once it lands, either (#272).

    **Test steps:**

    * submit a drop for a URL no scraper matches, to an executor that holds the job, and wait until it holds one
    * detach the actions, then run the held job
    * verify there is no banner row
    """
    doc_model = model()
    executor = HoldingExecutor()
    doc_actions = build_actions(doc_model, FakeRegistry({}), executor, FakeFetcher(), image_downloads)
    doc_actions.submit(drop())
    qtbot.waitUntil(lambda: bool(executor.jobs), timeout=WAIT_TIMEOUT_MS)

    doc_actions.detach()
    executor.run_next()
    qtbot.wait(50)

    assert not doc_actions.notice


def test_another_record_loaded_in_place_says_nothing_of_the_last_one_s_scrapes(
    mocker: MockerFixture, qtbot: QtBot, image_downloads: ImageDownloads
) -> None:
    """Another record loaded into the model (a preview moving on, #381) drops the failure the last one's drop left,
    and a drop still in flight for it fails without a row on the record shown now.

    **Test steps:**

    * fail a drop and verify its row; load another record and verify there is none
    * drop again, load a third record while it is in flight, then let it fail
    * verify there is still no row
    """
    doc_model = model()
    executor = HoldingExecutor()
    doc_actions = build_actions(doc_model, FakeRegistry({}), executor, FakeFetcher(), image_downloads)

    def load(name: str) -> None:
        other = RehuDocument({"type": "Tutorial", "title": name}, PATH.with_name(f"{name}.rehu"))
        mocker.patch(
            "rehuco_agent.documents.record_reader.RecordReader.read_record",
            return_value=LoadedRecord(other, None, tuple(other.lock_reasons), None),
        )
        doc_model.load(PATH.with_name(f"{name}.rehu"))

    doc_actions.submit(drop())
    qtbot.waitUntil(lambda: bool(executor.jobs), timeout=WAIT_TIMEOUT_MS)
    with qtbot.waitSignal(doc_actions.changed, timeout=WAIT_TIMEOUT_MS):
        executor.run_next()
    assert doc_actions.notice
    load("second")
    assert not doc_actions.notice

    doc_actions.submit(drop())
    qtbot.waitUntil(lambda: bool(executor.jobs), timeout=WAIT_TIMEOUT_MS)
    load("third")
    with qtbot.waitSignal(doc_actions.changed, timeout=WAIT_TIMEOUT_MS):
        executor.run_next()

    assert not doc_actions.notice


# endregion
# region the banner


def test_a_no_match_gives_a_warning_row_naming_the_host(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """No scraper for the host is a WARNING row, like every other failure: the drop did not do what it
    was dropped for (#272, #73).

    **Test steps:**

    * drop a URL no scraper matches
    * verify there is exactly one banner row
    * verify it is a WARNING
    * verify its text names the host
    """
    doc_model = model()
    doc_actions = actions(doc_model, None, image_downloads)

    resolve(qtbot, doc_actions, drop())

    assert len(doc_actions.notice) == 1
    assert doc_actions.notice[0].severity == MessageBannerSeverity.WARNING
    assert "example.com" in doc_actions.notice[0].text


def test_resolved_drops_leave_no_qt_object_behind(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """However many drops resolve, the actions keep the same Qt children: every job reports through the one relay
    built with them, and each chain's timer and action go when it ends -- nothing accumulates on a document left
    open for days (#529).

    **Test steps:**

    * resolve one drop and count the actions' Qt children
    * resolve five more
    * verify the count is the same
    """
    doc_actions = actions(model(), None, image_downloads)

    def resolve_one() -> None:
        with qtbot.waitSignal(doc_actions.changed, timeout=WAIT_TIMEOUT_MS):
            doc_actions.submit(drop())
        # the failure's warning, not the busy row: the chain has ended, so its timer and action are on their way
        qtbot.waitUntil(
            lambda: [row.severity for row in doc_actions.notice] == [MessageBannerSeverity.WARNING],
            timeout=WAIT_TIMEOUT_MS,
        )
        qtbot.wait(10)  # an event loop turning runs the deferred deletes

    resolve_one()
    baseline = len(doc_actions.children())
    for _ in range(5):
        resolve_one()

    assert len(doc_actions.children()) == baseline


def test_a_fetch_failure_gives_a_warning_row(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """Any other scrape failure is a WARNING row (#272).

    **Test steps:**

    * drop a page whose scraper raises ``RuntimeError``
    * verify there is exactly one banner row
    * verify it is a WARNING
    """
    doc_model = model()

    class RaisingScraper(FakeScraper):  # pylint: disable=missing-class-docstring
        def scrape_page(self, page: Page) -> object:
            del page
            raise RuntimeError("boom")

    doc_actions = actions(doc_model, RaisingScraper(), image_downloads)

    resolve(qtbot, doc_actions, drop())

    assert len(doc_actions.notice) == 1
    assert doc_actions.notice[0].severity == MessageBannerSeverity.WARNING


def test_the_next_drop_replaces_the_previous_failures_row(qtbot: QtBot, image_downloads: ImageDownloads) -> None:
    """A new drop's outcome replaces the last one's row, not accumulates beside it (#272).

    **Test steps:**

    * drop a URL no scraper matches and verify one banner row
    * drop it again
    * verify there is still exactly one banner row
    """
    doc_model = model()
    doc_actions = actions(doc_model, None, image_downloads)
    resolve(qtbot, doc_actions, drop())
    assert len(doc_actions.notice) == 1

    resolve(qtbot, doc_actions, drop())

    assert len(doc_actions.notice) == 1


def test_the_busy_row_appears_while_a_scrape_is_in_flight(image_downloads: ImageDownloads) -> None:
    """A submitted scrape shows an INFO row immediately, before the (synchronous, here) executor runs it.

    **Test steps:**

    * build the actions over an executor that accepts a job and never runs it
    * submit a drop
    * verify there is exactly one banner row
    * verify it is an INFO row
    * verify its text names the host
    """
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
