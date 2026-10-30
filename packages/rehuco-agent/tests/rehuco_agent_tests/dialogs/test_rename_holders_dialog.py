"""Tests for the dialog listing what holds a refused rename's files (#505).

Who holds them, whether one has a window, showing it and ending it are all the operating system's, measured in
``borco-core`` and ``test_rename_holders.py``; here they are stand-ins, and what is tested is the dialog: what it
lists, what each button does to its row, and that an answer overtaken by a newer ask is dropped.
"""

import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Final, cast
from unittest.mock import MagicMock

from borco_core import FileHolder
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication, QLabel, QPushButton
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.dialogs.holder_row import HolderRow
from rehuco_agent.dialogs.rename_holders_dialog import (
    COULD_NOT_ASK,
    COULD_NOT_SHOW,
    END_TIMEOUT,
    INTRO,
    NOT_ENDED,
    SEARCHING,
    STILL_RUNNING,
    RenameHoldersDialog,
)
from rehuco_agent.documents.rename_holders import FOLDER_HELD_BY_NOBODY, HELD_BY_REHUCO, HoldersFound
from shiboken6 import isValid

from rehuco_agent_tests.delete_at_teardown import DeleteAtTeardown

MODULE: Final = "rehuco_agent.dialogs.rename_holders_dialog"

RECORD: Final = Path("/fake/library/pack/info.rehu")
EXPLORER: Final = FileHolder(7, "Windows Explorer")
SCANNER: Final = FileHolder(9, "Scanner")

RELEASE_TIMEOUT: Final = 5.0
"""How long a held stand-in waits to be released, in seconds -- far past any test's need, so a test that fails
before releasing it still ends rather than hanging the pool."""


def holders_found(*others: FileHolder, rehuco: bool = False) -> HoldersFound:
    """Who holds the directory-scoped record's files.

    :param others: the other programs.
    :param rehuco: whether this process holds one too.
    :returns: the answer.
    """
    return HoldersFound(others, held_by_rehuco=rehuco, standing_inside=False, directory_scoped=True)


@fixture(name="find")
def fixture_find(mocker: MockerFixture) -> MagicMock:
    """Stand in for asking who holds the files: Explorer and a scanner, until a test says otherwise.

    :param mocker: pytest-mock fixture.
    :returns: the stand-in.
    """
    return mocker.patch(f"{MODULE}.RenameHolderReport.find", return_value=holders_found(EXPLORER, SCANNER))


@fixture(name="windows")
def fixture_windows(mocker: MockerFixture) -> dict[str, MagicMock]:
    """Stand in for the window and process calls: only Explorer has a window, showing works, ending works.

    :param mocker: pytest-mock fixture.
    :returns: the stand-ins, by name.
    """
    return {
        "has": mocker.patch(f"{MODULE}.has_window", side_effect=lambda pid: pid == EXPLORER.pid),
        "show": mocker.patch(f"{MODULE}.show_window", return_value=True),
        "end": mocker.patch(f"{MODULE}.end_process", return_value=True),
    }


@fixture(name="pool")
def fixture_pool(mocker: MockerFixture, delete_at_teardown: DeleteAtTeardown) -> QThreadPool:
    """A pool of two threads standing in for the dialog's global one: a test that holds one answer needs the next
    to run beside it, which the global pool cannot promise while other tests' jobs occupy it.

    :param mocker: pytest-mock fixture.
    :param delete_at_teardown: the conftest's teardown registry.
    :returns: the pool.
    """
    pool = delete_at_teardown(QThreadPool())
    pool.setMaxThreadCount(2)
    mocker.patch(f"{MODULE}.QThreadPool").globalInstance.return_value = pool
    return pool


@fixture(name="dialog")
def fixture_dialog(
    qtbot: QtBot, find: MagicMock, windows: dict[str, MagicMock], pool: QThreadPool
) -> Iterator[RenameHoldersDialog]:
    """The dialog for :data:`RECORD`, its first answer listed; the pool drained at teardown so no job outlives it.

    :param qtbot: pytest-qt fixture.
    :param find: the question's stand-in.
    :param windows: the window and process stand-ins.
    :param pool: the pool standing in for the global one.
    :yields: the dialog.
    """
    del find, windows
    dialog = RenameHoldersDialog(RECORD)
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog.status != SEARCHING)
    yield dialog
    pool.waitForDone()


def button(row: HolderRow, name: str) -> QPushButton:
    """One of a row's two buttons.

    :param row: the row.
    :param name: ``show_button`` or ``end_button``.
    :returns: the button.
    """
    found = row.findChild(QPushButton, name)
    assert found is not None
    return found


def scanner_row(dialog: RenameHoldersDialog) -> HolderRow:
    """The scanner's row, second in the list.

    :param dialog: the dialog.
    :returns: the row; cast because pylint reads an item of the rows as a signal, with PySide imported.
    """
    return cast(HolderRow, dialog.rows[1])


def is_ending(row: HolderRow) -> bool:
    """Whether a row's *End Task* waits for its program to end -- its button disabled.

    :param row: the row.
    :returns: whether it does.
    """
    return not button(row, "end_button").isEnabled()


def held(result: object) -> tuple[Callable[..., object], threading.Event]:
    """A stand-in that waits to be released before answering ``result``, so a test sees the state while it waits.

    :param result: what to answer, or an exception to raise.
    :returns: the stand-in, and the event that releases it.
    """
    release = threading.Event()

    def wait_then_answer(*_args: object) -> object:
        release.wait(RELEASE_TIMEOUT)
        if isinstance(result, BaseException):
            raise result
        return result

    return wait_then_answer, release


def test_every_other_program_is_listed_with_its_buttons(dialog: RenameHoldersDialog) -> None:
    """Each program holding the files gets a row; *Show App* only where there is a window to show.

    **Test steps:**

    * open the dialog over two holders, only one with a window
    * verify both are listed in order, Show App is enabled for that one only, End Task for both, and nothing more
      is said
    """
    assert [row.holder for row in dialog.rows] == [EXPLORER, SCANNER]
    assert [button(row, "show_button").isEnabled() for row in dialog.rows] == [True, False]
    assert all(button(row, "end_button").isEnabled() for row in dialog.rows)
    assert not dialog.status


def test_the_record_is_named_and_this_process_said_apart(
    qtbot: QtBot, find: MagicMock, windows: object, pool: QThreadPool
) -> None:
    """The dialog names the resource it asks about, and a handle of Rehuco's own is said, never listed.

    **Test steps:**

    * make this process hold a file besides Explorer, and open the dialog
    * verify the folder is named, the question was about the record, only Explorer is listed, and this process
      is said below
    """
    del windows, pool
    find.return_value = holders_found(EXPLORER, rehuco=True)

    dialog = RenameHoldersDialog(RECORD)
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog.status != SEARCHING)

    intro = dialog.findChild(QLabel, "intro_label")
    assert intro is not None
    assert intro.text() == INTRO.format(name="pack")
    find.assert_called_once_with(RECORD)
    assert [row.holder for row in dialog.rows] == [EXPLORER]
    assert dialog.status == HELD_BY_REHUCO


def test_a_question_that_failed_says_why_and_can_be_asked_again(
    dialog: RenameHoldersDialog, find: MagicMock, pool: QThreadPool
) -> None:
    """A refused question lists nobody and says why; Refresh asks again.

    **Test steps:**

    * make the question fail, and refresh
    * verify nobody is listed and the reason is said
    * make it answer, and click Refresh
    * verify the holders are listed again
    """
    find.side_effect = OSError("offline")

    dialog.refresh()
    pool.waitForDone()
    QApplication.processEvents()

    assert not dialog.rows
    assert dialog.status == COULD_NOT_ASK.format(reason="offline")

    find.side_effect = None
    refresh = dialog.findChild(QPushButton, "refresh_button")
    assert refresh is not None
    refresh.click()
    pool.waitForDone()
    QApplication.processEvents()

    assert [row.holder for row in dialog.rows] == [EXPLORER, SCANNER]


def test_an_answer_overtaken_by_a_newer_ask_is_dropped(
    qtbot: QtBot, dialog: RenameHoldersDialog, find: MagicMock, pool: QThreadPool
) -> None:
    """Only the latest ask is listed, whichever answer lands last.

    **Test steps:**

    * hold the next answer (Explorer alone), and refresh
    * refresh again, answered at once (the scanner alone), and wait for it to be listed
    * release the held answer and let it land
    * verify the scanner alone is still listed
    """
    slow, release = held(holders_found(EXPLORER))
    answers = iter((slow, lambda _record: holders_found(SCANNER)))

    def answer_in_turn(record: Path) -> object:
        return next(answers)(record)

    find.side_effect = answer_in_turn

    dialog.refresh()
    dialog.refresh()
    qtbot.waitUntil(lambda: [row.holder for row in dialog.rows] == [SCANNER])

    release.set()
    pool.waitForDone()
    QApplication.processEvents()

    assert [row.holder for row in dialog.rows] == [SCANNER]


def test_show_app_brings_the_program_forward(dialog: RenameHoldersDialog, windows: dict[str, MagicMock]) -> None:
    """*Show App* asks for the program's window, and says so when it has none any more.

    **Test steps:**

    * click Show App on Explorer
    * verify its window was asked for and nothing was said
    * make showing fail, and click again
    * verify the dialog says it has no window any more
    """
    show = button(dialog.rows[0], "show_button")

    show.click()

    windows["show"].assert_called_once_with(EXPLORER.pid)
    assert not dialog.status

    windows["show"].return_value = False
    show.click()

    assert dialog.status == COULD_NOT_SHOW.format(name=EXPLORER.name)


def test_end_task_waits_disabled_then_takes_the_program_off(
    qtbot: QtBot, dialog: RenameHoldersDialog, windows: dict[str, MagicMock]
) -> None:
    """*End Task* is disabled while the program is being ended, and its row goes once it has.

    **Test steps:**

    * hold the end, and click End Task on the scanner
    * verify its button is disabled and the row still listed
    * release the end, and wait for the scanner's row to be deleted
    * verify the scanner is off the list, ended with the dialog's wait, and Explorer is still listed
    """
    wait_then_end, release = held(True)
    windows["end"].side_effect = wait_then_end
    scanner = scanner_row(dialog)

    button(scanner, "end_button").click()

    assert is_ending(scanner)
    assert not button(scanner, "end_button").isEnabled()
    assert dialog.rows[1] is scanner

    release.set()
    qtbot.waitUntil(lambda: not isValid(scanner))

    windows["end"].assert_called_once_with(SCANNER.pid, END_TIMEOUT)
    assert [row.holder for row in dialog.rows] == [EXPLORER]


def test_ending_the_last_program_says_nobody_holds_the_files(
    qtbot: QtBot, find: MagicMock, windows: dict[str, MagicMock], pool: QThreadPool
) -> None:
    """Once every program is ended, the dialog says what it says when nobody was found.

    **Test steps:**

    * open the dialog over Explorer alone, and end it
    * verify the list is empty and the folder's nobody sentence is said
    """
    del windows, pool
    find.return_value = holders_found(EXPLORER)
    dialog = RenameHoldersDialog(RECORD)
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: len(dialog.rows) == 1)

    button(dialog.rows[0], "end_button").click()
    qtbot.waitUntil(lambda: not dialog.rows)

    assert dialog.status == FOLDER_HELD_BY_NOBODY


@mark.parametrize(
    ("refusal", "reason"),
    [(PermissionError(13, "Access is denied"), "Access is denied"), (RuntimeError("unexpected"), "unexpected")],
)
def test_a_program_that_could_not_be_ended_gets_its_button_back(
    qtbot: QtBot, dialog: RenameHoldersDialog, windows: dict[str, MagicMock], refusal: Exception, reason: str
) -> None:
    """A refused end -- an elevated program -- or a failed one leaves the row, its button enabled again, and says why.

    **Test steps:**

    * make ending the scanner raise, and click End Task
    * verify its button comes back enabled, the row stays, and the reason is said
    """
    windows["end"].side_effect = refusal
    scanner = scanner_row(dialog)

    button(scanner, "end_button").click()
    qtbot.waitUntil(lambda: not is_ending(scanner))

    assert dialog.rows[1] is scanner
    assert dialog.status == NOT_ENDED.format(name=SCANNER.name, reason=reason)


def test_a_program_that_outlived_the_wait_gets_its_button_back(
    qtbot: QtBot, dialog: RenameHoldersDialog, windows: dict[str, MagicMock]
) -> None:
    """A program told to end that is still running after the wait stays listed, and the dialog says so.

    **Test steps:**

    * make the end answer that the program is still there, and click End Task
    * verify its button comes back enabled, the row stays, and the wait is named
    """
    windows["end"].return_value = False
    scanner = scanner_row(dialog)

    button(scanner, "end_button").click()
    qtbot.waitUntil(lambda: not is_ending(scanner_row(dialog)))

    assert dialog.rows[1] is scanner
    assert dialog.status == STILL_RUNNING.format(name=SCANNER.name, seconds=END_TIMEOUT)


def test_an_end_answered_after_a_refresh_dropped_its_row_changes_nothing(
    qtbot: QtBot, dialog: RenameHoldersDialog, find: MagicMock, windows: dict[str, MagicMock], pool: QThreadPool
) -> None:
    """A program the latest ask no longer lists is not taken off a list it is not on.

    **Test steps:**

    * hold the end, and click End Task on the scanner
    * refresh to an answer naming Explorer alone
    * release the end, and let its answer land
    * verify Explorer is still listed and nothing was said
    """
    wait_then_end, release = held(True)
    windows["end"].side_effect = wait_then_end
    button(dialog.rows[1], "end_button").click()
    find.return_value = holders_found(EXPLORER)
    dialog.refresh()
    qtbot.waitUntil(lambda: len(dialog.rows) == 1)

    release.set()
    pool.waitForDone()
    QApplication.processEvents()

    assert [row.holder for row in dialog.rows] == [EXPLORER]
    assert not dialog.status


def test_close_closes(dialog: RenameHoldersDialog) -> None:
    """*Close* closes the dialog.

    **Test steps:**

    * show the dialog, and click Close
    * verify it is no longer visible
    """
    dialog.show()

    close = dialog.findChild(QPushButton, "close_button")
    assert close is not None
    close.click()

    assert not dialog.isVisible()
