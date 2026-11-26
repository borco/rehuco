"""Tests for what the window does with a link clicked in a log surface (#700): the wiring from the shared relay to
the browser, the browsers dock and the status bar. What a link opens is tested in ``test_log_link_opener.py``."""

from typing import Final
from unittest.mock import Mock
from uuid import UUID

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.app_logging import shared_log_link_relay
from rehuco_agent.main_window import MainWindow
from rehuco_agent.rehuco import BrowsersDock
from rehuco_agent.rehuco.log_link_opener import RECORD_NOT_FOUND
from rehuco_agent.scraping.library_record_link import LibraryRecordLink
from rehuco_core import CatalogRecord, CatalogRow, RecordKind
from rehuco_core.access import Catalog

from .test_main_window import mock_persistent_settings  # noqa: F401  # pylint: disable=unused-import

pytestmark = mark.usefixtures("stub_settings_pages", "stub_sub_docks")

ROOT_ID: Final = UUID(int=7)
LINK: Final = LibraryRecordLink(ROOT_ID, "Fab", "abc")
WAIT_MS: Final = 2000


@fixture(name="open_row")
def fixture_open_row(mocker: MockerFixture) -> Mock:
    """The browsers dock's open of a row, replaced before the window takes it.

    :param mocker: pytest-mock fixture.
    :returns: the mock.
    """
    return mocker.patch.object(BrowsersDock, "open_row")


@fixture(name="window")
def fixture_window(qtbot: QtBot, open_row: Mock) -> MainWindow:
    """A window with no catalog open.

    :param qtbot: pytest-qt fixture.
    :param open_row: the replaced open, in place before the window is built.
    :returns: the window.
    """
    del open_row
    window = MainWindow()
    qtbot.addWidget(window)
    return window


def test_a_web_link_clicked_in_the_windows_log_opens_in_the_browser(mocker: MockerFixture, window: MainWindow) -> None:
    """The window's own log surface reports through the relay, and the window opens the page.

    **Test steps:**

    * replace the system's browser, and have the window's log widget report a clicked address
    * verify the browser was asked for it
    """
    browser = mocker.patch.object(QDesktopServices, "openUrl", return_value=True)

    window.log_widget.link_activated.emit("https://store.example/pack")

    browser.assert_called_once_with(QUrl("https://store.example/pack"))


def test_a_records_link_is_opened_by_the_browsers_dock(
    mocker: MockerFixture, qtbot: QtBot, window: MainWindow, open_row: Mock
) -> None:
    """A title link from any surface is looked up in the window's catalog and opened as a browser's row is.

    **Test steps:**

    * make the catalog find a row for the item, and report its link through the relay
    * verify the browsers dock was asked to open that row
    """
    del window
    row = CatalogRow(1, ROOT_ID, "Assets", CatalogRecord("fab/pack/info.rehu", RecordKind.REHU), 0.0)
    mocker.patch.object(Catalog, "find_by_site_id", return_value=row)

    shared_log_link_relay().activated.emit(LINK)

    qtbot.waitUntil(lambda: open_row.called, timeout=WAIT_MS)
    open_row.assert_called_once_with((ROOT_ID, "fab/pack/info.rehu"))


def test_a_record_that_is_gone_is_said_on_the_status_bar(qtbot: QtBot, window: MainWindow, open_row: Mock) -> None:
    """With no catalog open nothing is found, and the click is answered on the status bar.

    **Test steps:**

    * report a title link through the relay, no catalog being open
    * verify the status bar says no record is in the open catalog, and nothing was opened
    """
    shared_log_link_relay().activated.emit(LINK)

    qtbot.waitUntil(lambda: window.statusBar().currentMessage() == RECORD_NOT_FOUND, timeout=WAIT_MS)
    open_row.assert_not_called()
