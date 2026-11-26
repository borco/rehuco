"""Tests for what a clicked log link opens (#700): a store's page in the browser, a scanned item's record in the
documents dock.

The catalog is a `Mock` of its class, which is tested in ``test_catalog.py``; the system's browser is replaced.
"""

import logging
import threading
from typing import Final
from unittest.mock import Mock
from uuid import UUID

from PySide6.QtCore import QCoreApplication, QThreadPool, QUrl
from PySide6.QtGui import QDesktopServices
from pytest import LogCaptureFixture, fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco.log_link_opener import RECORD_NOT_FOUND, LogLinkOpener
from rehuco_agent.scraping.library_record_link import LibraryRecordLink
from rehuco_core import Catalog, CatalogRecord, CatalogRow, RecordKind

from rehuco_agent_tests.delete_at_teardown import DeleteAtTeardown

ROOT_ID: Final = UUID(int=7)
LINK: Final = LibraryRecordLink(ROOT_ID, "Fab", "abc")
"""The title link of one scanned item."""

ROW: Final = CatalogRow(1, ROOT_ID, "Assets", CatalogRecord("fab/pack/info.rehu", RecordKind.REHU), 0.0)
"""Where the cache has that item's record now."""

WAIT_MS: Final = 2000


@fixture(name="catalog")
def fixture_catalog(mocker: MockerFixture) -> Mock:
    """A catalog that finds :data:`ROW` for :data:`LINK`.

    :param mocker: pytest-mock fixture.
    :returns: the mock.
    """
    catalog = mocker.Mock(spec=Catalog)
    catalog.find_by_site_id.return_value = ROW
    return catalog


@fixture(name="open_row")
def fixture_open_row(mocker: MockerFixture) -> Mock:
    """What opens a catalog row.

    :param mocker: pytest-mock fixture.
    :returns: the mock.
    """
    return mocker.Mock()


@fixture(name="opener")
def fixture_opener(qtbot: QtBot, delete_at_teardown: DeleteAtTeardown, catalog: Mock, open_row: Mock) -> LogLinkOpener:
    """The opener over the mock catalog.

    :param qtbot: pytest-qt fixture, so a `QApplication` exists.
    :param delete_at_teardown: deletes the opener when the test ends.
    :param catalog: the catalog.
    :param open_row: what opens a row.
    :returns: the opener.
    """
    del qtbot
    return delete_at_teardown(LogLinkOpener(catalog, open_row))


@fixture(name="browser")
def fixture_browser(mocker: MockerFixture) -> Mock:
    """The system's browser, which no test may start.

    :param mocker: pytest-mock fixture.
    :returns: the mock of ``QDesktopServices.openUrl``.
    """
    return mocker.patch.object(QDesktopServices, "openUrl", return_value=True)


def test_a_web_address_opens_in_the_browser(opener: LogLinkOpener, browser: Mock, open_row: Mock) -> None:
    """The address a scan logged goes to the system's browser, and touches nothing else.

    **Test steps:**

    * open an ``https`` address
    * verify the browser was asked for it, and no record was opened
    """
    opener.open("https://store.example/pack")

    browser.assert_called_once_with(QUrl("https://store.example/pack"))
    open_row.assert_not_called()


def test_a_target_that_is_no_web_page_is_logged_and_left_alone(
    opener: LogLinkOpener, browser: Mock, open_row: Mock, caplog: LogCaptureFixture
) -> None:
    """A record's text is outside input: only ``http`` and ``https`` are handed to the system.

    **Test steps:**

    * open a ``file`` address, a bare word and an object that is no link's target
    * verify nothing was opened, and each was logged as a warning
    """
    with caplog.at_level(logging.WARNING):
        for target in ("file:///etc/passwd", "word", object()):
            opener.open(target)

    browser.assert_not_called()
    open_row.assert_not_called()
    assert caplog.text.count("is not one this app opens") == 3


def test_a_records_link_opens_the_row_the_catalog_finds(
    qtbot: QtBot, opener: LogLinkOpener, catalog: Mock, open_row: Mock
) -> None:
    """The item's record is found again by its store id, in the root the scan filed it into, and opened by row.

    **Test steps:**

    * open the title link
    * verify the lookup was made by store, id and root, and the row found was opened by its root and path
    """
    opener.open(LINK)

    qtbot.waitUntil(lambda: open_row.called, timeout=WAIT_MS)
    catalog.find_by_site_id.assert_called_once_with("Fab", "abc", ROOT_ID)
    open_row.assert_called_once_with((ROOT_ID, "fab/pack/info.rehu"))


def test_a_record_the_catalog_no_longer_has_is_refused(
    qtbot: QtBot, opener: LogLinkOpener, catalog: Mock, open_row: Mock
) -> None:
    """A deleted record, or one whose root left the catalog, says so instead of opening nothing in silence.

    **Test steps:**

    * make the lookup find nothing, and open the title link
    * verify the refusal's reason, and that nothing was opened
    """
    catalog.find_by_site_id.return_value = None

    with qtbot.waitSignal(opener.refused, timeout=WAIT_MS) as refused:
        opener.open(LINK)

    assert refused.args == [RECORD_NOT_FOUND]
    open_row.assert_not_called()


def test_a_lookup_that_fails_is_refused_and_logged(
    qtbot: QtBot, opener: LogLinkOpener, catalog: Mock, open_row: Mock, caplog: LogCaptureFixture
) -> None:
    """A cache that cannot be read is no reason to leave the click unanswered, nor to lose the cause.

    **Test steps:**

    * make the lookup raise, and open the title link
    * verify the refusal carries the cause, the warning was logged and nothing was opened
    """
    catalog.find_by_site_id.side_effect = OSError("disk gone")

    with caplog.at_level(logging.WARNING), qtbot.waitSignal(opener.refused, timeout=WAIT_MS) as refused:
        opener.open(LINK)

    assert refused.args == ["The record could not be looked up: disk gone"]
    assert "could not be looked up: disk gone" in caplog.text
    open_row.assert_not_called()


def test_a_later_click_outdates_the_answer_of_an_earlier_one(
    opener: LogLinkOpener, catalog: Mock, open_row: Mock
) -> None:
    """Only the last link clicked opens its record: a slow lookup that a click on another title has outdated is dropped.

    **Test steps:**

    * hold the first lookup on a share that does not answer, and click a second title
    * let the first lookup finish, and wait for the pool to be done and its answers delivered
    * verify only the second record was opened, whichever of the two lookups ended first
    """
    release = threading.Event()
    first = CatalogRow(2, ROOT_ID, "Assets", CatalogRecord("fab/first/info.rehu", RecordKind.REHU), 0.0)

    def find(_site: str, site_id: str, _root: UUID) -> CatalogRow:
        if site_id == "first":
            assert release.wait(WAIT_MS / 1000)
            return first
        return ROW

    catalog.find_by_site_id.side_effect = find
    opener.open(LibraryRecordLink(ROOT_ID, "Fab", "first"))
    opener.open(LINK)

    release.set()
    assert QThreadPool.globalInstance().waitForDone(WAIT_MS)
    QCoreApplication.sendPostedEvents()

    open_row.assert_called_once_with((ROOT_ID, "fab/pack/info.rehu"))
