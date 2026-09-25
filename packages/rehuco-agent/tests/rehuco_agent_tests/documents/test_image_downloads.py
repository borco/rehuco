"""Tests for `ImageDownloads` (#73): a document's acquired screenshots, however they arrived."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, cast

from borco_pyside.widgets import MessageBannerRow, MessageBannerSeverity
from pytest import LogCaptureFixture, fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.image_downloads import (
    DOWNLOAD_WRITE_FAILURE,
    LOCAL_WRITE_FAILURE,
    READ_FAILURE,
    ImageDownloads,
)
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.image_organizer import ImageOrganizer
from rehuco_agent.scraping.image_pipeline import AcquiredImage, NotAnImageError
from rehuco_agent.scraping.protocols import PageFetcher
from rehuco_agent.scraping.registry import ScraperRegistry
from rehuco_agent.scraping.results import Page, ScrapedImage, ScrapeResult
from rehuco_agent.scraping.scraper_executor import ScraperExecutor
from rehuco_agent.scraping.url_drop import UrlDrop
from rehuco_core import LockReason, LockReasonKind, RehuDocument

PATH: Final = Path("/fake/library/sculpting/info.rehu")
URL: Final = "https://example.com/photo.jpg"
PAGE_URL: Final = "https://example.com/page"
PAGE_DROP: Final = UrlDrop(url=PAGE_URL, fragment=None)
"""A bare page link dropped on the images sub-dock -- no selection, so the page is fetched."""

SELECTION_HTML: Final = '<p>Some <b>selected</b> text <img src="https://example.com/inline.jpg"></p>'
"""A selection's own markup, which is scraped as the page instead of fetching it again."""

WAIT_TIMEOUT_MS: Final = 2000


class SyncExecutor:  # pylint: disable=missing-function-docstring,too-few-public-methods
    """Runs a job immediately, inline, rather than on a real pool -- deterministic for these tests."""

    def submit(self, job: object) -> None:
        job.run()  # type: ignore[attr-defined]


class FakeFetcher:  # pylint: disable=missing-function-docstring,too-few-public-methods
    """A `PageFetcher` stand-in that never touches the network."""

    def fetch(self, url: str) -> Page:
        return Page(url=url, final_url=url, html="<html></html>")


class RefusingFetcher:  # pylint: disable=missing-function-docstring,too-few-public-methods
    """A `PageFetcher` that fails the test outright if a page is fetched at all."""

    def fetch(self, url: str) -> Page:
        raise AssertionError(f"{url} was fetched, but the drop carried the page itself")


@dataclass
class FakeScraper:  # pylint: disable=missing-function-docstring,duplicate-code
    """A minimal `SiteScraper`, the same shape `test_scrape_actions.py`'s uses; records every page it
    was handed."""

    label: str = "Fake"
    publisher: str = "Example Publisher"
    site_name: str = "Fake"
    site_url: str = "https://fake.example.com"
    needs_browser: bool = False
    result: object = field(default_factory=lambda: ScrapeResult(fields={}, description=None, images=()))
    pages: list[Page] = field(default_factory=list)

    def matches(self, url: str) -> bool:
        del url
        return True

    def scrape_page(self, page: Page) -> object:
        self.pages.append(page)
        return self.result


class FakeRegistry:  # pylint: disable=missing-function-docstring,too-few-public-methods
    """A minimal registry: `find` answers from a fixed mapping, by URL."""

    def __init__(self, by_url: dict[str, FakeScraper | None]) -> None:
        self.__by_url = by_url

    def find(self, url: str) -> FakeScraper | None:
        return self.__by_url.get(url)


def document() -> RehuDocument:
    """A minimal Tutorial document."""
    return RehuDocument({"type": "Tutorial"})


def model(path: Path | None = PATH) -> RehuDocumentModel:
    """A view-model over a fresh document, bound to ``path`` (``None`` for a not-yet-saved one)."""
    result = RehuDocumentModel(document())
    result.path = path
    return result


def warning(text: str) -> MessageBannerRow:
    """The warning row a failure is expected to put on the banner.

    :param text: the failure's message.
    :returns: the row.
    """
    return MessageBannerRow(MessageBannerSeverity.WARNING, text)


@fixture
def organizer(mocker: MockerFixture) -> ImageOrganizer:
    """A mock `ImageOrganizer`, standing in for the resource's directory writer."""
    return mocker.create_autospec(ImageOrganizer, instance=True)


def downloads(
    doc_model: RehuDocumentModel,
    organizer_double: ImageOrganizer | None,
    registry: object = None,
    executor: object = None,
    fetcher: object = None,
) -> ImageDownloads:
    """`ImageDownloads` wired over test doubles, casting past their structural mismatch with the
    concrete `ScraperRegistry`/`ScraperExecutor` types."""
    return ImageDownloads(
        doc_model,
        organizer_double,
        registry=cast(ScraperRegistry, registry) if registry is not None else None,
        executor=cast(ScraperExecutor, executor) if executor is not None else SyncExecutor(),  # type: ignore[arg-type]
        fetcher=cast(PageFetcher, fetcher) if fetcher is not None else FakeFetcher(),
    )


# region submit / submit_page / acquire_local are no-ops without a path


def test_submit_is_a_no_op_for_a_document_with_no_path(organizer: ImageOrganizer) -> None:
    """A path-less document has nowhere to log the download under, so nothing is queued (#73).

    **Test steps:**

    * submit a URL against a document with no path
    * verify no notice appeared
    """
    image_downloads = downloads(model(None), organizer)

    image_downloads.submit(URL, None)

    assert not image_downloads.notice


def test_submit_page_is_a_no_op_for_a_document_with_no_path(organizer: ImageOrganizer) -> None:
    """Same refusal for a page scrape (#73).

    **Test steps:**

    * submit a page drop against a document with no path
    * verify no notice appeared
    """
    image_downloads = downloads(model(None), organizer)

    image_downloads.submit_page(PAGE_DROP)

    assert not image_downloads.notice


def test_acquire_local_is_a_no_op_for_a_document_with_no_path(organizer: ImageOrganizer) -> None:
    """A local acquisition needs the same path to write beside (#73).

    **Test steps:**

    * acquire a local file against a document with no path
    * verify the organizer was never asked to write
    """
    image_downloads = downloads(model(None), organizer)

    image_downloads.acquire_local([Path("/fake/photo.jpg")])

    cast(object, organizer.acquire).assert_not_called()  # type: ignore[attr-defined]


# endregion

# region acquire_local


def test_acquire_local_refuses_when_locked(organizer: ImageOrganizer) -> None:
    """A locked document refuses a local acquisition outright (#73).

    **Test steps:**

    * lock the document, then acquire a local file
    * verify the organizer was never asked to write
    """
    doc_model = model()
    doc_model.lock_reasons = [LockReason(LockReasonKind.NEWER_FORMAT, "locked")]
    image_downloads = downloads(doc_model, organizer)

    image_downloads.acquire_local([Path("/fake/photo.jpg")])

    cast(object, organizer.acquire).assert_not_called()  # type: ignore[attr-defined]


def test_acquire_local_refuses_with_no_organizer() -> None:
    """A document with nowhere to write (``None`` organizer) refuses too (#73).

    **Test steps:**

    * acquire a local file with no organizer configured
    * verify nothing raised and nothing was reported
    """
    image_downloads = downloads(model(), None)

    image_downloads.acquire_local([Path("/fake/photo.jpg")])

    assert not image_downloads.notice


def test_an_unreadable_dropped_file_is_logged_and_shown_on_the_banner(
    mocker: MockerFixture, organizer: ImageOrganizer, caplog: LogCaptureFixture
) -> None:
    """A path that cannot be read never reaches the organizer, and says why in the log and on the
    banner alike (#73).

    **Test steps:**

    * stand in for `acquire` raising `OSError`
    * acquire a local file
    * verify the organizer was never asked to write, and one warning row carries the logged sentence
    """
    mocker.patch("rehuco_agent.documents.image_downloads.acquire", side_effect=OSError("unreadable"))
    image_downloads = downloads(model(), organizer)

    image_downloads.acquire_local([Path("/fake/photo.jpg")])

    cast(object, organizer.acquire).assert_not_called()  # type: ignore[attr-defined]
    message = READ_FAILURE.format(error="unreadable")
    assert message in caplog.text
    assert image_downloads.notice == [warning(message)]


def test_a_dropped_non_image_is_logged_and_shown_on_the_banner(
    mocker: MockerFixture, organizer: ImageOrganizer, caplog: LogCaptureFixture
) -> None:
    """A source recognized as not an image is reported the same way (#73).

    **Test steps:**

    * stand in for `acquire` raising `NotAnImageError`
    * acquire a local file
    * verify the organizer was never asked to write, and one warning row carries the logged sentence
    """
    mocker.patch("rehuco_agent.documents.image_downloads.acquire", side_effect=NotAnImageError("not an image"))
    image_downloads = downloads(model(), organizer)

    image_downloads.acquire_local([Path("/fake/photo.jpg")])

    cast(object, organizer.acquire).assert_not_called()  # type: ignore[attr-defined]
    message = READ_FAILURE.format(error="not an image")
    assert message in caplog.text
    assert image_downloads.notice == [warning(message)]


def test_acquire_local_rescans_and_emits_acquired_on_success(
    mocker: MockerFixture, qtbot: QtBot, organizer: ImageOrganizer
) -> None:
    """A successful write rescans the resource's images and fires `acquired`, and reports nothing (#73).

    **Test steps:**

    * stand in for `acquire` with a successful result
    * acquire a local file
    * verify the organizer wrote it, the model rescanned, `acquired` fired, and the banner is clear
    """
    acquired_image = AcquiredImage(data=b"pixels", extension=".jpg")
    mocker.patch("rehuco_agent.documents.image_downloads.acquire", return_value=acquired_image)
    doc_model = model()
    rescan = mocker.patch.object(doc_model, "rescan_images")
    image_downloads = downloads(doc_model, organizer)

    with qtbot.waitSignal(image_downloads.acquired, timeout=WAIT_TIMEOUT_MS):
        image_downloads.acquire_local([Path("/fake/photo.jpg")])

    cast(object, organizer.acquire).assert_called_once_with(b"pixels", ".jpg")  # type: ignore[attr-defined]
    rescan.assert_called_once_with()
    assert not image_downloads.notice


def test_a_failed_local_write_is_logged_with_its_traceback_and_shown_on_the_banner(
    mocker: MockerFixture, organizer: ImageOrganizer, caplog: LogCaptureFixture
) -> None:
    """A write that fails on disk is an unexpected error: logged with its traceback, and on the banner
    too, rather than vanishing once the log is closed (#73).

    **Test steps:**

    * stand in for `acquire` succeeding, but the organizer's write raising `OSError`
    * acquire a local file
    * verify the log record carries the exception, and one warning row carries its sentence
    """
    acquired_image = AcquiredImage(data=b"pixels", extension=".jpg")
    mocker.patch("rehuco_agent.documents.image_downloads.acquire", return_value=acquired_image)
    cast(object, organizer.acquire).side_effect = OSError("disk full")  # type: ignore[attr-defined]
    image_downloads = downloads(model(), organizer)

    image_downloads.acquire_local([Path("/fake/photo.jpg")])

    message = LOCAL_WRITE_FAILURE.format(error="disk full")
    (record,) = [record for record in caplog.records if record.getMessage() == message]
    assert record.exc_info is not None
    assert image_downloads.notice == [warning(message)]


def test_acquire_local_gives_a_warning_banner_row_when_the_set_is_full(
    mocker: MockerFixture, organizer: ImageOrganizer
) -> None:
    """A full ``<stem>NN`` set is not just logged -- it also lands on the banner (#73), so a silent
    numbering ceiling never looks like a successful acquisition.

    **Test steps:**

    * stand in for `acquire` succeeding, but the organizer's write raising `ValueError` (a full set)
    * acquire a local file
    * verify the notice carries a warning row naming the failure
    """
    acquired_image = AcquiredImage(data=b"pixels", extension=".jpg")
    mocker.patch("rehuco_agent.documents.image_downloads.acquire", return_value=acquired_image)
    cast(object, organizer.acquire).side_effect = ValueError("the set is full")  # type: ignore[attr-defined]
    image_downloads = downloads(model(), organizer)

    image_downloads.acquire_local([Path("/fake/photo.jpg")])

    assert image_downloads.notice == [warning(LOCAL_WRITE_FAILURE.format(error="the set is full"))]


def test_a_multi_file_drop_is_one_batch_rescanned_once_with_a_row_per_failure(
    mocker: MockerFixture, qtbot: QtBot, organizer: ImageOrganizer
) -> None:
    """Every file of a multi-file drop gets its turn, however the others fared; the drop rescans once,
    and each file that failed keeps its own row rather than the next file clearing it (#73).

    **Test steps:**

    * drop three files: the first writes, the second will not read, the third meets a full set
    * verify the model rescanned once and `acquired` fired, and the banner has both failures, in order
    """
    mocker.patch(
        "rehuco_agent.documents.image_downloads.acquire",
        side_effect=[
            AcquiredImage(data=b"one", extension=".jpg"),
            OSError("two unreadable"),
            AcquiredImage(data=b"three", extension=".png"),
        ],
    )
    written_then_full = [Path("/fake/info00.jpg"), ValueError("the set is full")]
    cast(object, organizer.acquire).side_effect = written_then_full  # type: ignore[attr-defined]
    doc_model = model()
    rescan = mocker.patch.object(doc_model, "rescan_images")
    image_downloads = downloads(doc_model, organizer)

    with qtbot.waitSignal(image_downloads.acquired, timeout=WAIT_TIMEOUT_MS):
        image_downloads.acquire_local([Path("/fake/one.jpg"), Path("/fake/two.jpg"), Path("/fake/three.png")])

    rescan.assert_called_once_with()
    assert image_downloads.notice == [
        warning(READ_FAILURE.format(error="two unreadable")),
        warning(LOCAL_WRITE_FAILURE.format(error="the set is full")),
    ]


def test_a_failure_repeated_across_a_drop_shows_once(mocker: MockerFixture, organizer: ImageOrganizer) -> None:
    """Several files failing the same way -- every one of them past a full set -- say so in one row,
    not one per file (#73).

    **Test steps:**

    * drop two files, both meeting a full set
    * verify the banner has a single row
    """
    mocker.patch(
        "rehuco_agent.documents.image_downloads.acquire", return_value=AcquiredImage(data=b"x", extension=".jpg")
    )
    cast(object, organizer.acquire).side_effect = ValueError("the set is full")  # type: ignore[attr-defined]
    image_downloads = downloads(model(), organizer)

    image_downloads.acquire_local([Path("/fake/one.jpg"), Path("/fake/two.jpg")])

    assert image_downloads.notice == [warning(LOCAL_WRITE_FAILURE.format(error="the set is full"))]


def test_a_drop_that_writes_nothing_does_not_rescan(
    mocker: MockerFixture, qtbot: QtBot, organizer: ImageOrganizer
) -> None:
    """With nothing written there is nothing to read back, and nothing was acquired (#73).

    **Test steps:**

    * drop one file that will not read
    * verify the model was not rescanned and `acquired` never fired
    """
    mocker.patch("rehuco_agent.documents.image_downloads.acquire", side_effect=OSError("unreadable"))
    doc_model = model()
    rescan = mocker.patch.object(doc_model, "rescan_images")
    image_downloads = downloads(doc_model, organizer)

    with qtbot.assertNotEmitted(image_downloads.acquired):
        image_downloads.acquire_local([Path("/fake/photo.jpg")])

    rescan.assert_not_called()


def test_the_next_drop_replaces_the_last_drops_failures(mocker: MockerFixture, organizer: ImageOrganizer) -> None:
    """A drop's failure rows stand until the next drop, whose own outcome replaces them (#73).

    **Test steps:**

    * drop a file that will not read, then one that writes
    * verify the banner carried the failure after the first, and is clear after the second
    """
    mocker.patch(
        "rehuco_agent.documents.image_downloads.acquire",
        side_effect=[OSError("unreadable"), AcquiredImage(data=b"x", extension=".jpg")],
    )
    image_downloads = downloads(model(), organizer)

    image_downloads.acquire_local([Path("/fake/one.jpg")])
    assert len(image_downloads.notice) == 1

    image_downloads.acquire_local([Path("/fake/two.jpg")])

    assert not image_downloads.notice


# endregion

# region submit / __on_result


def test_submit_shows_a_busy_row_immediately(organizer: ImageOrganizer) -> None:
    """A submitted download shows an INFO row before the (synchronous, here) executor even runs it.

    **Test steps:**

    * submit with an executor that never runs the job
    * verify the notice carries a busy INFO row
    """

    class NeverRunningExecutor:  # pylint: disable=missing-class-docstring,missing-function-docstring,too-few-public-methods
        def submit(self, job: object) -> None:
            del job

    image_downloads = downloads(model(), organizer, executor=NeverRunningExecutor())

    image_downloads.submit(URL, None)

    assert len(image_downloads.notice) == 1
    assert image_downloads.notice[0].severity == MessageBannerSeverity.INFO


def test_on_result_writes_with_the_jobs_slot(mocker: MockerFixture, qtbot: QtBot, organizer: ImageOrganizer) -> None:
    """A finished download writes through the organizer with the job's own slot (#73).

    **Test steps:**

    * stand in for a successful download
    * submit a URL with an explicit slot
    * verify the organizer was asked to write with that slot, and the model rescanned
    """
    acquired_image = AcquiredImage(data=b"pixels", extension=".jpg")
    mocker.patch("rehuco_agent.scraping.image_download_job.acquire", return_value=acquired_image)
    doc_model = model()
    rescan = mocker.patch.object(doc_model, "rescan_images")
    image_downloads = downloads(doc_model, organizer)

    with qtbot.waitSignal(image_downloads.acquired, timeout=WAIT_TIMEOUT_MS):
        image_downloads.submit(URL, None, slot=4)

    cast(object, organizer.acquire).assert_called_once_with(b"pixels", ".jpg", 4)  # type: ignore[attr-defined]
    rescan.assert_called_once_with()


def test_on_result_discards_on_a_path_change(qtbot: QtBot, mocker: MockerFixture, organizer: ImageOrganizer) -> None:
    """A result for a document that has since moved is discarded, never written (#73).

    **Test steps:**

    * move the document out from under the download before running it
    * verify the organizer was never asked to write
    """
    acquired_image = AcquiredImage(data=b"pixels", extension=".jpg")
    mocker.patch("rehuco_agent.scraping.image_download_job.acquire", return_value=acquired_image)
    doc_model = model()

    class LateExecutor:  # pylint: disable=missing-class-docstring,missing-function-docstring,too-few-public-methods
        def submit(self, job: object) -> None:
            doc_model.path = Path("/fake/library/sculpting/moved.rehu")
            job.run()  # type: ignore[attr-defined]

    image_downloads = downloads(doc_model, organizer, executor=LateExecutor())

    with qtbot.waitSignal(image_downloads.changed, timeout=WAIT_TIMEOUT_MS):
        image_downloads.submit(URL, None)
    qtbot.wait(20)

    cast(object, organizer.acquire).assert_not_called()  # type: ignore[attr-defined]


def test_on_result_discards_when_locked(qtbot: QtBot, mocker: MockerFixture, organizer: ImageOrganizer) -> None:
    """A result for a document locked mid-flight is discarded too (#73).

    **Test steps:**

    * lock the document out from under the download before running it
    * verify the organizer was never asked to write
    """
    acquired_image = AcquiredImage(data=b"pixels", extension=".jpg")
    mocker.patch("rehuco_agent.scraping.image_download_job.acquire", return_value=acquired_image)
    doc_model = model()

    class LockingExecutor:  # pylint: disable=missing-class-docstring,missing-function-docstring,too-few-public-methods
        def submit(self, job: object) -> None:
            doc_model.lock_reasons = [LockReason(LockReasonKind.NEWER_FORMAT, "locked mid-download")]
            job.run()  # type: ignore[attr-defined]

    image_downloads = downloads(doc_model, organizer, executor=LockingExecutor())

    with qtbot.waitSignal(image_downloads.changed, timeout=WAIT_TIMEOUT_MS):
        image_downloads.submit(URL, None)
    qtbot.wait(20)

    cast(object, organizer.acquire).assert_not_called()  # type: ignore[attr-defined]


def test_on_result_discards_with_no_organizer(qtbot: QtBot, mocker: MockerFixture) -> None:
    """A result for a document with nowhere to write (``None`` organizer) is discarded (#73).

    **Test steps:**

    * submit against a document built with no organizer
    * verify nothing raised
    """
    acquired_image = AcquiredImage(data=b"pixels", extension=".jpg")
    mocker.patch("rehuco_agent.scraping.image_download_job.acquire", return_value=acquired_image)
    image_downloads = downloads(model(), None)

    with qtbot.waitSignal(image_downloads.changed, timeout=WAIT_TIMEOUT_MS):
        image_downloads.submit(URL, None)
    qtbot.wait(20)  # must not raise


def test_detach_discards_a_result_that_arrives_afterward(
    qtbot: QtBot, mocker: MockerFixture, organizer: ImageOrganizer
) -> None:
    """A detached document's in-flight download is never written once it lands (#73).

    **Test steps:**

    * submit, then detach before the (synchronous) executor runs the job
    * verify the organizer was never asked to write
    """
    acquired_image = AcquiredImage(data=b"pixels", extension=".jpg")
    mocker.patch("rehuco_agent.scraping.image_download_job.acquire", return_value=acquired_image)

    class DeferredExecutor:  # pylint: disable=missing-class-docstring,missing-function-docstring,too-few-public-methods
        def __init__(self) -> None:
            self.job: object = None

        def submit(self, job: object) -> None:
            self.job = job

    executor = DeferredExecutor()
    image_downloads = downloads(model(), organizer, executor=executor)

    image_downloads.submit(URL, None)
    image_downloads.detach()
    cast(object, executor.job).run()  # type: ignore[attr-defined]
    qtbot.wait(20)

    cast(object, organizer.acquire).assert_not_called()  # type: ignore[attr-defined]


def test_a_failed_download_write_is_logged_with_its_traceback_and_shown_on_the_banner(
    qtbot: QtBot, mocker: MockerFixture, organizer: ImageOrganizer, caplog: LogCaptureFixture
) -> None:
    """A downloaded image whose write fails on disk is logged with its traceback, and lands on the
    banner once the busy row clears -- a download that succeeded and one that was lost must not look
    alike (#73).

    **Test steps:**

    * stand in for a successful download whose write raises `OSError`
    * submit a URL
    * verify the log record carries the exception, and one warning row carries its sentence
    """
    acquired_image = AcquiredImage(data=b"pixels", extension=".jpg")
    mocker.patch("rehuco_agent.scraping.image_download_job.acquire", return_value=acquired_image)
    cast(object, organizer.acquire).side_effect = OSError("disk full")  # type: ignore[attr-defined]
    image_downloads = downloads(model(), organizer)

    with qtbot.waitSignal(image_downloads.changed, timeout=WAIT_TIMEOUT_MS):
        image_downloads.submit(URL, None)
    qtbot.wait(20)

    message = DOWNLOAD_WRITE_FAILURE.format(error="disk full")
    (record,) = [record for record in caplog.records if record.getMessage() == message]
    assert record.exc_info is not None
    assert image_downloads.notice == [warning(message)]


def test_on_result_gives_a_warning_banner_row_when_the_set_is_full(
    qtbot: QtBot, mocker: MockerFixture, organizer: ImageOrganizer
) -> None:
    """A full ``<stem>NN`` set from a download also lands on the banner, the same as a local
    acquisition's (#73).

    **Test steps:**

    * stand in for a successful download whose write raises `ValueError` (a full set)
    * submit a URL
    * verify the notice carries a warning row naming the failure
    """
    acquired_image = AcquiredImage(data=b"pixels", extension=".jpg")
    mocker.patch("rehuco_agent.scraping.image_download_job.acquire", return_value=acquired_image)
    cast(object, organizer.acquire).side_effect = ValueError("the set is full")  # type: ignore[attr-defined]
    image_downloads = downloads(model(), organizer)

    with qtbot.waitSignal(image_downloads.changed, timeout=WAIT_TIMEOUT_MS):
        image_downloads.submit(URL, None)
    qtbot.wait(20)

    assert image_downloads.notice == [warning(DOWNLOAD_WRITE_FAILURE.format(error="the set is full"))]


def test_on_failed_sets_the_warning_row(qtbot: QtBot, mocker: MockerFixture, organizer: ImageOrganizer) -> None:
    """A download's own failure (a network error) is a warning row on the banner (#73).

    **Test steps:**

    * stand in for a failed download
    * submit a URL
    * verify the notice carries a single warning row
    """
    mocker.patch("rehuco_agent.scraping.image_download_job.acquire", side_effect=OSError("network down"))
    image_downloads = downloads(model(), organizer)

    with qtbot.waitSignal(image_downloads.changed, timeout=WAIT_TIMEOUT_MS):
        image_downloads.submit(URL, None)
    qtbot.wait(20)

    assert image_downloads.notice == [warning("network down")]


def test_detach_discards_a_failure_that_arrives_afterward(organizer: ImageOrganizer) -> None:
    """A detached document's in-flight download never records its failure once it lands, either (#73).

    **Test steps:**

    * submit a download that will fail, then detach before it runs
    * verify no notice landed
    """

    class DeferredExecutor:  # pylint: disable=missing-class-docstring,missing-function-docstring,too-few-public-methods
        def __init__(self) -> None:
            self.job: object = None

        def submit(self, job: object) -> None:
            self.job = job

    executor = DeferredExecutor()
    image_downloads = downloads(model(), organizer, executor=executor)

    image_downloads.submit(URL, None)
    image_downloads.detach()
    cast(object, executor.job).run()  # type: ignore[attr-defined]

    assert not image_downloads.notice


# endregion

# region submit_page / __on_page_result


def test_submit_page_shows_a_busy_row_immediately(organizer: ImageOrganizer) -> None:
    """A submitted page scrape shows an INFO row before the (synchronous, here) executor runs it (#73).

    **Test steps:**

    * submit a page drop with an executor that never runs the job
    * verify the notice carries a busy INFO row
    """

    class NeverRunningExecutor:  # pylint: disable=missing-class-docstring,missing-function-docstring,too-few-public-methods
        def submit(self, job: object) -> None:
            del job

    image_downloads = downloads(
        model(), organizer, registry=FakeRegistry({PAGE_URL: FakeScraper()}), executor=NeverRunningExecutor()
    )

    image_downloads.submit_page(PAGE_DROP)

    assert len(image_downloads.notice) == 1
    assert image_downloads.notice[0].severity == MessageBannerSeverity.INFO


def test_page_result_submits_one_download_per_image(
    qtbot: QtBot, mocker: MockerFixture, organizer: ImageOrganizer
) -> None:
    """Each `ScrapedImage` the scraped page reports is handed to `submit`, one download per image
    (#73).

    **Test steps:**

    * scrape a page reporting two images
    * verify each image was downloaded through the pipeline, and the model rescanned twice
    """
    images = (
        ScrapedImage(0, "https://x/one.jpg", "https://x/"),
        ScrapedImage(1, "https://x/two.jpg", None),
    )
    result = ScrapeResult(fields={}, description=None, images=images)
    acquired_image = AcquiredImage(data=b"pixels", extension=".jpg")
    acquire = mocker.patch("rehuco_agent.scraping.image_download_job.acquire", return_value=acquired_image)
    doc_model = model()
    rescan = mocker.patch.object(doc_model, "rescan_images")
    registry = FakeRegistry({PAGE_URL: FakeScraper(result=result)})
    image_downloads = downloads(doc_model, organizer, registry=registry)

    with qtbot.waitSignal(image_downloads.changed, timeout=WAIT_TIMEOUT_MS):
        image_downloads.submit_page(PAGE_DROP)
    qtbot.wait(20)

    assert acquire.call_args_list == [
        mocker.call("https://x/one.jpg", "https://x/"),
        mocker.call("https://x/two.jpg", None),
    ]
    assert rescan.call_count == 2


def test_a_selection_is_scraped_from_its_own_html_not_fetched(qtbot: QtBot, organizer: ImageOrganizer) -> None:
    """A selection hands its own markup to the scraper as the page, and nothing is fetched -- the same
    rule the Main Editor's scrape follows for the same drop (#73, [[acquisition-tooling#drag-drop-aids]]).

    **Test steps:**

    * submit a selection drop, with a fetcher that fails the test if called at all
    * verify the scraper was handed one page, carrying the selection's own markup
    """
    scraper = FakeScraper()
    image_downloads = downloads(
        model(), organizer, registry=FakeRegistry({PAGE_URL: scraper}), fetcher=RefusingFetcher()
    )

    with qtbot.waitSignal(image_downloads.changed, timeout=WAIT_TIMEOUT_MS):
        image_downloads.submit_page(UrlDrop(url=PAGE_URL, fragment=SELECTION_HTML))
    qtbot.wait(20)

    assert [page.html for page in scraper.pages] == [SELECTION_HTML]
    assert not image_downloads.notice


def test_each_failed_image_of_a_page_keeps_its_own_row(
    qtbot: QtBot, mocker: MockerFixture, organizer: ImageOrganizer
) -> None:
    """A page's images are one batch: the second image's submission does not wipe the first's
    failure, so both stand on the banner once the page is done (#73).

    **Test steps:**

    * scrape a page reporting two images, whose downloads fail two different ways
    * verify the banner has both failures, in order
    """
    images = (ScrapedImage(0, "https://x/one.jpg", None), ScrapedImage(1, "https://x/two.jpg", None))
    result = ScrapeResult(fields={}, description=None, images=images)
    mocker.patch(
        "rehuco_agent.scraping.image_download_job.acquire",
        side_effect=[OSError("one unreachable"), OSError("two unreachable")],
    )
    registry = FakeRegistry({PAGE_URL: FakeScraper(result=result)})
    image_downloads = downloads(model(), organizer, registry=registry)

    image_downloads.submit_page(PAGE_DROP)
    qtbot.waitUntil(lambda: len(image_downloads.notice) == 2, timeout=WAIT_TIMEOUT_MS)

    assert image_downloads.notice == [warning("one unreachable"), warning("two unreachable")]


def test_page_result_discards_on_a_path_change(qtbot: QtBot, mocker: MockerFixture, organizer: ImageOrganizer) -> None:
    """A page result for a document that has since moved never submits any of its images (#73).

    **Test steps:**

    * move the document out from under the page scrape before running it
    * verify no download was ever queued
    """
    result = ScrapeResult(fields={}, description=None, images=(ScrapedImage(0, "https://x/one.jpg", None),))
    doc_model = model()
    registry = FakeRegistry({PAGE_URL: FakeScraper(result=result)})
    acquire = mocker.patch("rehuco_agent.scraping.image_download_job.acquire")

    class LateExecutor:  # pylint: disable=missing-class-docstring,missing-function-docstring,too-few-public-methods
        def submit(self, job: object) -> None:
            doc_model.path = Path("/fake/library/sculpting/moved.rehu")
            job.run()  # type: ignore[attr-defined]

    image_downloads = downloads(doc_model, organizer, registry=registry, executor=LateExecutor())

    with qtbot.waitSignal(image_downloads.changed, timeout=WAIT_TIMEOUT_MS):
        image_downloads.submit_page(PAGE_DROP)
    qtbot.wait(20)

    acquire.assert_not_called()


def test_page_result_discards_when_locked(qtbot: QtBot, mocker: MockerFixture, organizer: ImageOrganizer) -> None:
    """A page result for a document locked mid-flight is discarded too (#73).

    **Test steps:**

    * lock the document out from under the page scrape before running it
    * verify no download was ever queued
    """
    result = ScrapeResult(fields={}, description=None, images=(ScrapedImage(0, "https://x/one.jpg", None),))
    doc_model = model()
    registry = FakeRegistry({PAGE_URL: FakeScraper(result=result)})
    acquire = mocker.patch("rehuco_agent.scraping.image_download_job.acquire")

    class LockingExecutor:  # pylint: disable=missing-class-docstring,missing-function-docstring,too-few-public-methods
        def submit(self, job: object) -> None:
            doc_model.lock_reasons = [LockReason(LockReasonKind.NEWER_FORMAT, "locked mid-scrape")]
            job.run()  # type: ignore[attr-defined]

    image_downloads = downloads(doc_model, organizer, registry=registry, executor=LockingExecutor())

    with qtbot.waitSignal(image_downloads.changed, timeout=WAIT_TIMEOUT_MS):
        image_downloads.submit_page(PAGE_DROP)
    qtbot.wait(20)

    acquire.assert_not_called()


def test_detach_discards_a_page_result_that_arrives_afterward(
    qtbot: QtBot, mocker: MockerFixture, organizer: ImageOrganizer
) -> None:
    """A detached document's in-flight page scrape never submits its images once it lands (#73).

    **Test steps:**

    * submit a page scrape, then detach before it runs
    * verify no download was ever queued
    """
    result = ScrapeResult(fields={}, description=None, images=(ScrapedImage(0, "https://x/one.jpg", None),))
    registry = FakeRegistry({PAGE_URL: FakeScraper(result=result)})
    acquire = mocker.patch("rehuco_agent.scraping.image_download_job.acquire")

    class DeferredExecutor:  # pylint: disable=missing-class-docstring,missing-function-docstring,too-few-public-methods
        def __init__(self) -> None:
            self.job: object = None

        def submit(self, job: object) -> None:
            self.job = job

    executor = DeferredExecutor()
    image_downloads = downloads(model(), organizer, registry=registry, executor=executor)

    image_downloads.submit_page(PAGE_DROP)
    image_downloads.detach()
    cast(object, executor.job).run()  # type: ignore[attr-defined]
    qtbot.wait(20)

    acquire.assert_not_called()


def test_detach_discards_a_page_failure_that_arrives_afterward(organizer: ImageOrganizer) -> None:
    """A detached document's in-flight page scrape never records its failure once it lands, either
    (#73).

    **Test steps:**

    * submit a page scrape that will fail (no matching scraper), then detach before it runs
    * verify no notice landed
    """

    class DeferredExecutor:  # pylint: disable=missing-class-docstring,missing-function-docstring,too-few-public-methods
        def __init__(self) -> None:
            self.job: object = None

        def submit(self, job: object) -> None:
            self.job = job

    executor = DeferredExecutor()
    image_downloads = downloads(model(), organizer, registry=FakeRegistry({}), executor=executor)

    image_downloads.submit_page(PAGE_DROP)
    image_downloads.detach()
    cast(object, executor.job).run()  # type: ignore[attr-defined]

    assert not image_downloads.notice


def test_page_failure_sets_the_warning_row(qtbot: QtBot, organizer: ImageOrganizer) -> None:
    """A page no scraper matches is a warning row naming the host -- a failure like any other, since
    the drop did not do what it was dropped for (#73).

    **Test steps:**

    * scrape a page with no matching scraper
    * verify the notice carries a single warning row naming the host
    """
    image_downloads = downloads(model(), organizer, registry=FakeRegistry({}))

    with qtbot.waitSignal(image_downloads.changed, timeout=WAIT_TIMEOUT_MS):
        image_downloads.submit_page(PAGE_DROP)
    qtbot.wait(20)

    assert len(image_downloads.notice) == 1
    assert image_downloads.notice[0].severity == MessageBannerSeverity.WARNING
    assert "example.com" in image_downloads.notice[0].text


# endregion

# region notice ordering


def test_notice_shows_the_page_row_before_the_download_row(organizer: ImageOrganizer) -> None:
    """Both a busy page scrape and a busy download can stand at once; the page row leads (#73).

    **Test steps:**

    * submit a page scrape and a plain download, both held by executors that never run
    * verify the notice carries both rows, page first
    """

    class NeverRunningExecutor:  # pylint: disable=missing-class-docstring,missing-function-docstring,too-few-public-methods
        def submit(self, job: object) -> None:
            del job

    image_downloads = downloads(
        model(), organizer, registry=FakeRegistry({PAGE_URL: FakeScraper()}), executor=NeverRunningExecutor()
    )

    image_downloads.submit_page(PAGE_DROP)
    image_downloads.submit(URL, None)

    assert len(image_downloads.notice) == 2
    assert "page" in image_downloads.notice[0].text.lower()


def test_the_last_failure_is_suppressed_while_a_second_download_is_in_flight(
    qtbot: QtBot, mocker: MockerFixture, organizer: ImageOrganizer
) -> None:
    """A last failure is suppressed while another download is still running -- the same *busy beats
    last-outcome* ordering `.ScrapeActions.notice` uses (#73).

    **Test steps:**

    * fail one download synchronously, then submit a second one held forever in flight
    * verify the notice shows only the busy row, not the earlier failure
    """

    class OnceThenNeverExecutor:  # pylint: disable=missing-function-docstring,too-few-public-methods
        """Runs the first job it is given (so it fails synchronously); holds every later one pending."""

        def __init__(self) -> None:
            self.__ran_once = False

        def submit(self, job: object) -> None:
            if not self.__ran_once:
                self.__ran_once = True
                job.run()  # type: ignore[attr-defined]

    mocker.patch("rehuco_agent.scraping.image_download_job.acquire", side_effect=OSError("network down"))
    executor = OnceThenNeverExecutor()
    image_downloads = downloads(model(), organizer, executor=executor)

    with qtbot.waitSignal(image_downloads.changed, timeout=WAIT_TIMEOUT_MS):
        image_downloads.submit("https://x/fails.jpg", None)
    qtbot.wait(20)
    assert image_downloads.notice == [warning("network down")]

    image_downloads.submit(URL, None)

    assert len(image_downloads.notice) == 1
    assert image_downloads.notice[0].severity == MessageBannerSeverity.INFO


# endregion
