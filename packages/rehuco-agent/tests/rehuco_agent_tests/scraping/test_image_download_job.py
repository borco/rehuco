"""Tests for `ImageDownloadJob` (#73): fetches one image URL and hands the result to the GUI thread."""

from PySide6.QtCore import QCoreApplication, QEvent
from pytest import LogCaptureFixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.scraping.image_download_job import ImageDownloadJob
from rehuco_agent.scraping.image_pipeline import AcquiredImage

from rehuco_agent_tests.delete_at_teardown import DeleteAtTeardown

URL = "https://example.com/photo.jpg"


def test_slot_reports_what_it_was_constructed_with(delete_at_teardown: DeleteAtTeardown) -> None:
    """The slot a caller assigned at construction is read back unchanged (#73).

    **Test steps:**

    * construct a job with an explicit slot
    * verify it comes back from the property
    """
    relay = delete_at_teardown(ImageDownloadJob.Relay())
    job = ImageDownloadJob(URL, None, slot=3, relay=relay)

    assert job.slot == 3


def test_a_plain_drops_slot_is_none(delete_at_teardown: DeleteAtTeardown) -> None:
    """A job built for a plain drop (no scrape-assigned slot) reports ``None`` (#73).

    **Test steps:**

    * construct a job with no slot given
    * verify the property answers ``None``
    """
    relay = delete_at_teardown(ImageDownloadJob.Relay())
    job = ImageDownloadJob(URL, None, relay=relay)

    assert job.slot is None


def test_run_emits_result_ready_on_the_gui_thread_on_success(
    qtbot: QtBot, mocker: MockerFixture, delete_at_teardown: DeleteAtTeardown
) -> None:
    """A successful fetch's `~.image_pipeline.AcquiredImage` reaches `result_ready`, marshalled across
    the queued connection (#73).

    **Test steps:**

    * stand in for `acquire` with a successful result
    * run the job
    * verify `result_ready` fired with that result
    """
    acquired = AcquiredImage(data=b"pixels", extension=".jpg")
    mocker.patch("rehuco_agent.scraping.image_download_job.acquire", return_value=acquired)
    relay = delete_at_teardown(ImageDownloadJob.Relay())
    job = ImageDownloadJob(URL, "https://example.com/page", relay=relay)

    with qtbot.waitSignal(relay.result_ready, timeout=1000) as blocker:
        job.run()

    assert blocker.args == [job, acquired]


def test_a_job_whose_relay_went_with_its_document_reports_into_nothing(qtbot: QtBot, mocker: MockerFixture) -> None:
    """A document closed while a download runs takes the relay with it; the job then finishes into nothing, raising
    nothing on the pool thread (#529).

    **Test steps:**

    * build a job over a relay, then delete the relay as a closing document would
    * run the job
    * verify nothing was raised
    """
    del qtbot  # an application, so the deferred delete below destroys the relay
    mocker.patch("rehuco_agent.scraping.image_download_job.acquire", return_value=AcquiredImage(b"x", ".jpg"))
    relay = ImageDownloadJob.Relay()
    job = ImageDownloadJob(URL, None, relay=relay)
    relay.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)

    job.run()


def test_run_emits_failed_and_logs_on_any_exception(
    qtbot: QtBot, mocker: MockerFixture, caplog: LogCaptureFixture, delete_at_teardown: DeleteAtTeardown
) -> None:
    """Any exception `acquire` raises is caught, logged under this module, and relayed through
    `failed` -- the blanket catch that keeps an escaping exception from being silently swallowed by the
    pool thread instead of reaching the document's log (#73).

    **Test steps:**

    * stand in for `acquire` raising
    * run the job
    * verify `failed` fired with that error and it was logged with the URL
    """
    error = ValueError("boom")
    mocker.patch("rehuco_agent.scraping.image_download_job.acquire", side_effect=error)
    relay = delete_at_teardown(ImageDownloadJob.Relay())
    job = ImageDownloadJob(URL, None, relay=relay)

    with qtbot.waitSignal(relay.failed, timeout=1000) as blocker:
        job.run()

    assert blocker.args == [job, error]
    assert URL in caplog.text
