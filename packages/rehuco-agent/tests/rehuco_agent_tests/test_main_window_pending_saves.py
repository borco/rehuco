"""Tests for MainWindow's part in saves as jobs (#497): unsaved edits kept across a quit or asked about, reopened at
start, and the Tasks dock's *Inspect*, *Discard* and pending-saves indicator wired to the window's save owner.

:class:`~rehuco_agent.documents.pending_saves.PendingSaves` and
:class:`~rehuco_agent.documents.unsaved_changes.UnsavedChanges` have their own tests; here their methods are patched,
and what is checked is that the window calls them.
"""

from pathlib import Path
from typing import Any, Final

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QDialog
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.pending_saves import PendingSaves
from rehuco_agent.documents.unsaved_changes import UnsavedChanges
from rehuco_agent.main_window import MainWindow
from rehuco_agent.settings.session_restore_settings import SessionRestoreSettings
from rehuco_agent.tasks import TaskQueueWidget
from rehuco_core.access import ResourceKey

from rehuco_agent_tests.test_main_window import (  # noqa: F401  # pylint: disable=unused-import
    UNSAVED_CHANGES_DIALOG,
    mock_persistent_settings,
    task_queue_dock,
)

pytestmark = mark.usefixtures("stub_settings_pages", "stub_sub_docks")
"""Every window here is built over stub settings pages, and every document it opens over stub sub-docks (#545)."""

SERIAL: Final = 1234
"""The save row the Tasks dock asks about."""

KEY: Final = ResourceKey(Path(Path.cwd().anchor) / "media" / "res" / "res.rehu")
"""The record of that row -- never read: the window's own opening of it is patched."""


def keep_unsaved_changes(mocker: MockerFixture, keep: bool) -> None:
    """Have the session settings say whether a quit keeps unsaved edits.

    :param mocker: pytest-mock fixture.
    :param keep: the choice.
    """

    def load(self: SessionRestoreSettings, settings: object) -> None:
        """Load the defaults, with the choice.

        :param settings: unused.
        """
        del settings
        self.keep_unsaved_changes = keep

    mocker.patch.object(SessionRestoreSettings, "load", load)


def private(window: MainWindow, name: str) -> Any:
    """One of the window's private members.

    :param window: the window.
    :param name: the member's name, unmangled.
    :returns: the member.
    """
    return getattr(window, f"_MainWindow__{name}")


@fixture(name="store")
def fixture_store(mocker: MockerFixture) -> Any:
    """The kept-edits store's methods, patched before any window is built.

    :param mocker: pytest-mock fixture.
    :returns: a namespace of the patched ``keep``, ``forget`` and ``reopen``.
    """
    holder = mocker.Mock()
    holder.keep = mocker.patch.object(UnsavedChanges, "keep")
    holder.forget = mocker.patch.object(UnsavedChanges, "forget")
    holder.reopen = mocker.patch.object(UnsavedChanges, "reopen")
    return holder


# region quitting and starting


def test_a_quit_keeping_unsaved_changes_asks_nothing_and_keeps_the_edits(
    mocker: MockerFixture, qtbot: QtBot, store: Any
) -> None:
    """With the setting on, quitting with a dirty document shows no prompt and keeps the open documents' edits.

    **Test steps:**

    * turn keeping unsaved changes on, build the window, and stand in one dirty open document
    * deliver a close
    * verify the close was accepted, no unsaved-changes dialog was built, nothing was saved, and the open documents
      were handed to the store to keep
    """
    keep_unsaved_changes(mocker, True)
    window = MainWindow()
    qtbot.addWidget(window)
    widget = mocker.MagicMock()
    widget.model = mocker.MagicMock(path=None, dirty=True)
    widget.save_state.return_value = b""
    dock = private(window, "documents_dock")
    mocker.patch.object(dock, "open_document_models", return_value=[widget.model])
    mocker.patch.object(dock, "open_document_widgets", return_value=[widget])
    dialog_class = mocker.patch(UNSAVED_CHANGES_DIALOG)
    save_and_wait = mocker.patch.object(PendingSaves, "save_and_wait")
    mocker.patch.object(QApplication, "quit")
    event = QCloseEvent()

    window.closeEvent(event)

    assert event.isAccepted()
    dialog_class.assert_not_called()
    save_and_wait.assert_not_called()
    store.keep.assert_called_once_with([widget])
    store.forget.assert_not_called()


def test_a_quit_not_keeping_unsaved_changes_asks_and_empties_the_store(
    mocker: MockerFixture, qtbot: QtBot, store: Any
) -> None:
    """With the setting off, quitting with a dirty document asks about it, and keeps no edits for the next start.

    **Test steps:**

    * leave keeping unsaved changes off, build the window, and stand in one dirty open document
    * deliver a close, accepting the unsaved-changes dialog with nothing selected
    * verify the close was accepted, the dialog was built, and the store was emptied rather than kept
    """
    keep_unsaved_changes(mocker, False)
    window = MainWindow()
    qtbot.addWidget(window)
    dock = private(window, "documents_dock")
    mocker.patch.object(dock, "open_document_models", return_value=[mocker.MagicMock(dirty=True)])
    dialog = mocker.MagicMock()
    dialog.exec.return_value = QDialog.DialogCode.Accepted
    dialog.selected_models.return_value = []
    dialog_class = mocker.patch(UNSAVED_CHANGES_DIALOG, return_value=dialog)
    mocker.patch.object(QApplication, "quit")
    event = QCloseEvent()

    window.closeEvent(event)

    assert event.isAccepted()
    dialog_class.assert_called_once()
    store.forget.assert_called_once_with()
    store.keep.assert_not_called()


def test_a_refused_quit_neither_keeps_nor_empties_the_store(mocker: MockerFixture, qtbot: QtBot, store: Any) -> None:
    """A quit cancelled at the unsaved-changes prompt leaves the kept edits as they are.

    **Test steps:**

    * leave keeping unsaved changes off, build the window, and make the dirty-document guard refuse
    * deliver a close
    * verify the close was ignored and the store was neither written nor emptied
    """
    keep_unsaved_changes(mocker, False)
    window = MainWindow()
    qtbot.addWidget(window)
    mocker.patch("rehuco_agent.main_window.confirm_and_save_dirty", return_value=False)
    event = QCloseEvent()

    window.closeEvent(event)

    assert not event.isAccepted()
    store.keep.assert_not_called()
    store.forget.assert_not_called()


def test_the_kept_edits_are_reopened_at_start(qtbot: QtBot, store: Any) -> None:
    """Building the window reopens the documents whose edits the last quit kept.

    **Test steps:**

    * build the window
    * verify the store was asked to reopen them, once
    """
    window = MainWindow()
    qtbot.addWidget(window)

    store.reopen.assert_called_once_with()


# endregion

# region the Tasks dock's save actions


def test_inspect_opens_the_saves_document_and_looks_at_it_there(mocker: MockerFixture, qtbot: QtBot) -> None:
    """*Inspect* on a save row opens its record and hands the opened document to the save owner.

    **Test steps:**

    * build the window; have the save owner name the row's record, and the registry find a document for it
    * ask the Tasks dock to inspect the row
    * verify the record was opened, and the owner was asked to inspect the row with that document
    """
    window = MainWindow()
    qtbot.addWidget(window)
    mocker.patch.object(PendingSaves, "key_of", return_value=KEY)
    model = mocker.Mock()
    mocker.patch.object(private(window, "document_registry"), "find", return_value=model)
    open_path = mocker.patch.object(window, "open_path")
    inspect = mocker.patch.object(PendingSaves, "inspect")

    private(window, "task_queue_widget").inspect_save_requested.emit(SERIAL)

    open_path.assert_called_once_with(KEY.path)
    inspect.assert_called_once_with(window, SERIAL, model)


def test_inspect_of_a_row_that_is_no_save_does_nothing(mocker: MockerFixture, qtbot: QtBot) -> None:
    """*Inspect* on a row the save owner knows no record for opens nothing.

    **Test steps:**

    * build the window; have the save owner name no record for the row
    * ask the Tasks dock to inspect the row
    * verify nothing was opened or inspected
    """
    window = MainWindow()
    qtbot.addWidget(window)
    mocker.patch.object(PendingSaves, "key_of", return_value=None)
    open_path = mocker.patch.object(window, "open_path")
    inspect = mocker.patch.object(PendingSaves, "inspect")

    private(window, "task_queue_widget").inspect_save_requested.emit(SERIAL)

    open_path.assert_not_called()
    inspect.assert_not_called()


def test_inspect_of_a_record_that_did_not_open_inspects_nothing(mocker: MockerFixture, qtbot: QtBot) -> None:
    """*Inspect* whose record could not be opened has no document to look at.

    **Test steps:**

    * build the window; have the save owner name the row's record, and the registry find no document for it
    * ask the Tasks dock to inspect the row
    * verify the record was asked open, and nothing was inspected
    """
    window = MainWindow()
    qtbot.addWidget(window)
    mocker.patch.object(PendingSaves, "key_of", return_value=KEY)
    mocker.patch.object(private(window, "document_registry"), "find", return_value=None)
    open_path = mocker.patch.object(window, "open_path")
    inspect = mocker.patch.object(PendingSaves, "inspect")

    private(window, "task_queue_widget").inspect_save_requested.emit(SERIAL)

    open_path.assert_called_once_with(KEY.path)
    inspect.assert_not_called()


def test_discard_hands_the_rows_to_the_save_owner(mocker: MockerFixture, qtbot: QtBot) -> None:
    """*Discard* on save rows asks the save owner to drop them, parented to the window.

    **Test steps:**

    * build the window, and patch the owner's discard
    * ask the Tasks dock to discard two rows
    * verify the owner was asked to discard both
    """
    window = MainWindow()
    qtbot.addWidget(window)
    discard = mocker.patch.object(PendingSaves, "discard")

    private(window, "task_queue_widget").discard_saves_requested.emit([SERIAL, SERIAL + 1])

    discard.assert_called_once_with(window, [SERIAL, SERIAL + 1])


def test_the_pending_saves_indicator_opens_the_tasks_dock_on_the_pending_saves(
    mocker: MockerFixture, qtbot: QtBot
) -> None:
    """Clicking the status bar's pending-saves count opens the Tasks dock, showing the saves that have not landed.

    **Test steps:**

    * build the window with the Tasks dock closed, and patch the dock widget's ``show_pending_saves``
    * click the pending-saves indicator
    * verify the Tasks dock is open and was asked to show the pending saves
    """
    window = MainWindow()
    qtbot.addWidget(window)
    dock = task_queue_dock(window)
    dock.toggleView(False)
    show_pending_saves = mocker.patch.object(TaskQueueWidget, "show_pending_saves")

    private(window, "pending_saves_indicator").click()

    assert not dock.isClosed()
    show_pending_saves.assert_called_once_with()


# endregion
