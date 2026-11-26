"""Tests for the reader of a preset license's text (#705, [[assets#licenses]]): read off the GUI thread, handed back
with the license it was asked for, and a failure logged, never shown.

Fab's readers are tested with them (:mod:`~rehuco_agent_tests.scraping.sites.test_fab_license_texts`); here the read
is patched.
"""

import datetime
import logging
import threading
from typing import Final

from pytest import LogCaptureFixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.license_text_reader import LicenseTextReader
from rehuco_agent.scraping.library_site import StoreOfflineError
from rehuco_agent.scraping.protocols import FetchError
from rehuco_core import LicenseTerms

URL: Final = "https://www.fab.com/eula"
TERMS: Final = LicenseTerms("Standard License", URL, datetime.date(2026, 11, 26), "Terms.")
READ_URL: Final = "rehuco_agent.documents.license_text_reader.FabLicenseTexts.read_url"


def test_a_text_read_is_handed_back_with_its_license_off_the_gui_thread(qtbot: QtBot, mocker: MockerFixture) -> None:
    """**Test steps:**

    * have the read answer a text, and record the thread it ran on
    * read a license's text
    * verify the text arrived with the license and the address, and the read ran on another thread
    """
    threads: list[threading.Thread] = []

    def read(_self: object, url: str) -> LicenseTerms:
        threads.append(threading.current_thread())
        assert url == URL
        return TERMS

    mocker.patch(READ_URL, read)
    reader = LicenseTextReader()

    with qtbot.waitSignal(reader.text_read) as arrived:
        reader.read("fab-standard", URL)

    assert arrived.args == ["fab-standard", URL, TERMS]
    assert threads and threads[0] is not threading.main_thread()


@mark.parametrize("error", [StoreOfflineError("offline"), FetchError("not JSON")])
def test_a_text_that_cannot_be_read_is_logged_and_nothing_arrives(
    qtbot: QtBot, mocker: MockerFixture, caplog: LogCaptureFixture, error: Exception
) -> None:
    """**Test steps:**

    * have the read fail as the store being offline, and as an answer that is no text
    * verify a warning names the license and the address, and no text arrived
    """
    mocker.patch(READ_URL, side_effect=error)
    reader = LicenseTextReader()

    with caplog.at_level(logging.WARNING), qtbot.assertNotEmitted(reader.text_read, wait=50):
        reader.read("fab-standard", URL)
        qtbot.waitUntil(lambda: any("fab-standard" in record.getMessage() for record in caplog.records))

    assert URL in caplog.records[-1].getMessage()


def test_a_text_read_after_the_reader_is_gone_is_dropped(qtbot: QtBot, mocker: MockerFixture) -> None:
    """A document closed while its license's text is read must not be handed the text: the read's thread ends quietly.

    **Test steps:**

    * hold a read until the reader is destroyed, then let it answer a text
    * verify the read's thread ended with no exception left to it
    * destroy a reader between the check and the emit -- its signal raising as a dead object's does -- and verify that
      read ends quietly too
    """
    release = threading.Event()
    ended: list[BaseException | None] = []
    mocker.patch("threading.excepthook", lambda args: ended.append(args.exc_value))

    def read(_self: object, _url: str) -> LicenseTerms:
        release.wait(5)
        return TERMS

    mocker.patch(READ_URL, read)
    reader = LicenseTextReader()
    reader.read("fab-standard", URL)
    with qtbot.waitSignal(reader.destroyed):
        reader.deleteLater()
    release.set()
    reading = next(thread for thread in threading.enumerate() if thread.name == "license-text-reader")
    reading.join(5)

    # the signal is bound when a reader is made, so it is replaced first
    emit = mocker.Mock(side_effect=RuntimeError)
    mocker.patch.object(LicenseTextReader, "text_read", mocker.Mock(emit=emit))
    late = LicenseTextReader()
    late.read("fab-standard", URL)
    for thread in threading.enumerate():
        if thread.name == "license-text-reader":
            thread.join(5)

    emit.assert_called_once_with("fab-standard", URL, TERMS)
    assert not ended


def test_an_address_no_reader_knows_brings_no_text(
    qtbot: QtBot, mocker: MockerFixture, caplog: LogCaptureFixture
) -> None:
    """**Test steps:**

    * have the read know no text for the address
    * verify it is logged and no text arrived
    """
    mocker.patch(READ_URL, return_value=None)
    reader = LicenseTextReader()

    with caplog.at_level(logging.INFO), qtbot.assertNotEmitted(reader.text_read, wait=50):
        reader.read("mine", "https://example.com/mine")
        qtbot.waitUntil(lambda: any("mine" in record.getMessage() for record in caplog.records))
