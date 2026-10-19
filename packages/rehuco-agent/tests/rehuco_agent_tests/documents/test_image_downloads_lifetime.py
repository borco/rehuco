"""Tests for what `ImageDownloads` keeps alive: nothing per download (#529)."""

from PySide6.QtCore import QObject
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.image_organizer import ImageOrganizer

from rehuco_agent_tests.documents.test_image_downloads import URL, WAIT_TIMEOUT_MS, downloads, model, warning


def test_finished_downloads_leave_no_qt_object_behind(qtbot: QtBot, mocker: MockerFixture) -> None:
    """However many downloads finish, `ImageDownloads` keeps the same Qt children: every job reports through the one
    relay built with it, so nothing accumulates on a document left open for days (#529).

    **Test steps:**

    * finish one download and count the Qt children
    * finish five more
    * verify the count is the same
    """
    mocker.patch("rehuco_agent.scraping.image_download_job.acquire", side_effect=OSError("network down"))
    image_downloads = downloads(model(), mocker.create_autospec(ImageOrganizer, instance=True))

    def finish_one() -> None:
        image_downloads.submit(URL, None)
        qtbot.waitUntil(lambda: image_downloads.notice == [warning("network down")], timeout=WAIT_TIMEOUT_MS)

    finish_one()
    baseline = len(image_downloads.findChildren(QObject))
    for _ in range(5):
        finish_one()

    assert len(image_downloads.findChildren(QObject)) == baseline
