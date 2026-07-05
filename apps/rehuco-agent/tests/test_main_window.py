"""Tests for MainWindow: the top-level dock-in-dock shell hosting DocumentsDock."""

from pathlib import Path
from typing import Any

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QDialog, QWidget
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.document_session_settings import DocumentSessionSettings
from rehuco_agent.main_window import MainWindow


@fixture(autouse=True)
def mock_persistent_settings(mocker: MockerFixture) -> Any:
    """Stand in for ``persistent_settings()`` so session load/save never touch real QSettings storage.

    ``beginReadArray`` must return an int (``DocumentSessionSettings.load`` feeds it to ``range()``);
    everything else on the mock is a harmless no-op.
    """
    settings = mocker.MagicMock()
    settings.beginReadArray.return_value = 0
    return mocker.patch("rehuco_agent.main_window.persistent_settings", return_value=settings)


def test_installs_a_dock_manager_as_the_central_widget(qtbot: QtBot) -> None:
    """Setting up the docking system replaces the `.ui`'s plain central widget with a `CDockManager`.

    **Test steps:**

    * construct a real ``MainWindow`` (real `QtAds` objects, no mocking)
    * find the `.ui`'s original ``central_widget`` by object name
    * verify it's no longer the current central widget, and was hidden
    """
    window = MainWindow()
    qtbot.addWidget(window)

    original_central = window.findChild(QWidget, "central_widget")
    assert original_central is not None
    assert window.centralWidget() is not original_central
    assert original_central.isHidden()


def test_open_file_resolves_and_delegates_to_the_documents_dock(mocker: MockerFixture, qtbot: QtBot) -> None:
    """``open_file`` resolves its path and hands it to the documents dock.

    **Test steps:**

    * mock only ``DocumentsDock.open_document`` (the dock itself is real -- it's a real
      ``QWidget`` `CDockWidget.setWidget` requires, so mocking the whole class would break
      ``MainWindow``'s docking setup)
    * construct a ``MainWindow`` and call ``open_file`` with a relative path
    * verify ``open_document`` was called with the resolved absolute path
    """
    open_document = mocker.patch("rehuco_agent.main_window.DocumentsDock.open_document")
    window = MainWindow()
    qtbot.addWidget(window)

    window.open_file("a.rehu")

    open_document.assert_called_once_with(Path("a.rehu").resolve())


def test_close_event_accepts_immediately_with_no_dirty_documents(mocker: MockerFixture, qtbot: QtBot) -> None:
    """With no dirty documents, the close proceeds without showing the unsaved-changes dialog.

    **Test steps:**

    * mock ``open_document_models`` to return a clean model
    * mock the dialog class to detect an unwanted construction
    * dispatch a close event
    * verify the event was accepted and the dialog was never shown
    """
    window = MainWindow()
    qtbot.addWidget(window)
    clean_model = mocker.MagicMock(dirty=False)
    mocker.patch.object(window._MainWindow__documents_dock, "open_document_models", return_value=[clean_model])  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    dialog_class = mocker.patch("rehuco_agent.main_window.UnsavedChangesDialog")
    event = QCloseEvent()

    window.closeEvent(event)

    assert event.isAccepted()
    dialog_class.assert_not_called()


def test_close_event_saves_selected_documents_when_accepted(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Accepting the unsaved-changes dialog saves the models it reports as selected.

    **Test steps:**

    * mock ``open_document_models`` to return two dirty models
    * mock the dialog to accept and select only one of them
    * dispatch a close event
    * verify the event was accepted and only the selected model was saved
    """
    window = MainWindow()
    qtbot.addWidget(window)
    kept, discarded = mocker.MagicMock(dirty=True), mocker.MagicMock(dirty=True)
    mocker.patch.object(window._MainWindow__documents_dock, "open_document_models", return_value=[kept, discarded])  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    dialog = mocker.MagicMock()
    dialog.exec.return_value = QDialog.DialogCode.Accepted
    dialog.selected_models.return_value = [kept]
    mocker.patch("rehuco_agent.main_window.UnsavedChangesDialog", return_value=dialog)
    event = QCloseEvent()

    window.closeEvent(event)

    assert event.isAccepted()
    kept.save.assert_called_once_with()
    discarded.save.assert_not_called()


def test_close_event_ignores_the_close_when_dialog_is_cancelled(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Cancelling the unsaved-changes dialog aborts the app close; nothing is saved.

    **Test steps:**

    * mock ``open_document_models`` to return a dirty model
    * mock the dialog to be rejected (Cancel)
    * dispatch a close event
    * verify the event was ignored and the model was not saved
    """
    window = MainWindow()
    qtbot.addWidget(window)
    dirty_model = mocker.MagicMock(dirty=True)
    mocker.patch.object(window._MainWindow__documents_dock, "open_document_models", return_value=[dirty_model])  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    dialog = mocker.MagicMock()
    dialog.exec.return_value = QDialog.DialogCode.Rejected
    mocker.patch("rehuco_agent.main_window.UnsavedChangesDialog", return_value=dialog)
    event = QCloseEvent()

    window.closeEvent(event)

    assert not event.isAccepted()
    dirty_model.save.assert_not_called()


def test_restore_session_reopens_open_documents_and_restores_their_state(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A document the saved session marks open is reopened and has its dock layout restored.

    **Test steps:**

    * seed ``DocumentSessionSettings.load`` to report one open item (with known state bytes) and
      one closed item
    * mock ``DocumentsDock.open_document`` to return a stand-in widget
    * construct ``MainWindow``
    * verify ``open_document`` was called only for the open item's path, and its widget's
      ``restore_state`` was called with that item's state
    """
    open_path = Path("open.rehu").resolve()
    closed_path = Path("closed.rehu").resolve()

    def fake_load(self: DocumentSessionSettings, settings: object) -> None:
        del settings
        # pylint: disable=unsupported-assignment-operation
        self.items[open_path] = DocumentSessionSettings.Item(open=True, state=b"state-bytes")
        self.items[closed_path] = DocumentSessionSettings.Item(open=False, state=b"old-state")

    mocker.patch.object(DocumentSessionSettings, "load", fake_load)
    widget = mocker.MagicMock()
    open_document = mocker.patch("rehuco_agent.main_window.DocumentsDock.open_document", return_value=widget)

    window = MainWindow()
    qtbot.addWidget(window)

    open_document.assert_called_once_with(open_path)
    widget.restore_state.assert_called_once_with(b"state-bytes")


def test_restore_session_skips_a_document_that_fails_to_reopen(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A previously-open document that fails to reopen (missing/invalid file, #35) is skipped, not crashed on.

    **Test steps:**

    * seed one open item
    * mock ``open_document`` to return ``None``, as it does when the file can't be loaded
    * construct ``MainWindow`` and verify it doesn't raise
    """
    path = Path("missing.rehu").resolve()

    def fake_load(self: DocumentSessionSettings, settings: object) -> None:
        del settings
        self.items[path] = DocumentSessionSettings.Item(open=True, state=b"state")  # pylint: disable=unsupported-assignment-operation

    mocker.patch.object(DocumentSessionSettings, "load", fake_load)
    mocker.patch("rehuco_agent.main_window.DocumentsDock.open_document", return_value=None)

    window = MainWindow()
    qtbot.addWidget(window)


def test_close_event_snapshots_open_documents_into_the_session(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Closing the app snapshots every open document's dock layout into the session and saves it.

    **Test steps:**

    * construct ``MainWindow`` with one (clean) open document widget
    * dispatch a close event
    * verify the session gained an entry for that document's path, marked open with its saved
      state, and ``DocumentSessionSettings.save`` was called
    """
    window = MainWindow()
    qtbot.addWidget(window)
    path = Path("a.rehu").resolve()
    widget = mocker.MagicMock()
    widget.model = mocker.MagicMock(path=path, dirty=False)
    widget.save_state.return_value = b"snapshot"
    mocker.patch.object(
        window._MainWindow__documents_dock,  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
        "open_document_widgets",
        return_value=[widget],
    )
    mocker.patch.object(
        window._MainWindow__documents_dock,  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
        "open_document_models",
        return_value=[widget.model],
    )
    save = mocker.patch.object(DocumentSessionSettings, "save")
    event = QCloseEvent()

    window.closeEvent(event)

    session = window._MainWindow__session  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert session.items[path] == DocumentSessionSettings.Item(open=True, state=b"snapshot")
    save.assert_called_once()


def test_close_event_marks_a_no_longer_open_document_as_closed(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A document the session remembers as open, but that isn't open anymore, is marked closed.

    **Test steps:**

    * seed the session with an item marked open, matching no currently-open document
    * dispatch a close event with no documents open
    * verify the item is now marked closed, its prior state preserved
    """
    window = MainWindow()
    qtbot.addWidget(window)
    stale_path = Path("stale.rehu").resolve()
    session = window._MainWindow__session  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    session.items[stale_path] = DocumentSessionSettings.Item(  # pylint: disable=unsupported-assignment-operation
        open=True, state=b"old"
    )
    docs_dock = window._MainWindow__documents_dock  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    mocker.patch.object(docs_dock, "open_document_widgets", return_value=[])
    mocker.patch.object(docs_dock, "open_document_models", return_value=[])
    mocker.patch.object(DocumentSessionSettings, "save")
    event = QCloseEvent()

    window.closeEvent(event)

    item = session.items[stale_path]
    assert item.open is False  # pylint: disable=no-member
    assert item.state == b"old"  # pylint: disable=no-member


def test_close_event_skips_a_document_with_no_path_when_snapshotting(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A document widget with no path yet is skipped when snapshotting, not crashed on.

    **Test steps:**

    * dispatch a close event with one open widget reporting ``model.path is None``
    * verify the session gains no entry for it, and save still happens
    """
    window = MainWindow()
    qtbot.addWidget(window)
    widget = mocker.MagicMock()
    widget.model = mocker.MagicMock(path=None, dirty=False)
    docs_dock = window._MainWindow__documents_dock  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    mocker.patch.object(docs_dock, "open_document_widgets", return_value=[widget])
    mocker.patch.object(docs_dock, "open_document_models", return_value=[widget.model])
    save = mocker.patch.object(DocumentSessionSettings, "save")
    event = QCloseEvent()

    window.closeEvent(event)

    session = window._MainWindow__session  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert not session.items
    save.assert_called_once()


def test_raise_and_activate_shows_a_normal_window(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A visible, non-minimized window is shown (not restored), raised, and activated.

    Forces ``sys.platform`` to a non-Windows value so this runs identically on every CI leg,
    without touching the real Windows-only foreground helper.

    **Test steps:**

    * force ``sys.platform`` to ``"linux"`` and mock show/showNormal/raise_/activateWindow
    * call ``raise_and_activate``
    * verify ``show`` (not ``showNormal``) was called, plus ``raise_``/``activateWindow``
    """
    mocker.patch("rehuco_agent.main_window.sys.platform", "linux")
    window = MainWindow()
    qtbot.addWidget(window)
    show = mocker.patch.object(window, "show")
    show_normal = mocker.patch.object(window, "showNormal")
    raise_ = mocker.patch.object(window, "raise_")
    activate = mocker.patch.object(window, "activateWindow")

    window.raise_and_activate()

    show.assert_called_once_with()
    show_normal.assert_not_called()
    raise_.assert_called_once_with()
    activate.assert_called_once_with()


def test_raise_and_activate_restores_a_minimized_window(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A minimized window is restored via ``showNormal()`` instead of ``show()``.

    **Test steps:**

    * force ``sys.platform`` to ``"linux"``, mark the window minimized
    * call ``raise_and_activate``
    * verify ``showNormal`` (not ``show``) was called
    """
    mocker.patch("rehuco_agent.main_window.sys.platform", "linux")
    window = MainWindow()
    qtbot.addWidget(window)
    mocker.patch.object(window, "isMinimized", return_value=True)
    show_normal = mocker.patch.object(window, "showNormal")
    show = mocker.patch.object(window, "show")

    window.raise_and_activate()

    show_normal.assert_called_once_with()
    show.assert_not_called()


def test_raise_and_activate_forces_foreground_on_windows(mocker: MockerFixture, qtbot: QtBot) -> None:
    """On Windows, the process-input-attach foreground helper is invoked with this window.

    **Test steps:**

    * force ``sys.platform`` to ``"win32"`` and mock the Windows-only helper
    * call ``raise_and_activate``
    * verify the helper was called with this window
    """
    mocker.patch("rehuco_agent.main_window.sys.platform", "win32")
    force_foreground = mocker.patch("borco_pyside.platforms.windows.window_activation.force_foreground")
    window = MainWindow()
    qtbot.addWidget(window)
    mocker.patch.object(window, "show")
    mocker.patch.object(window, "raise_")
    mocker.patch.object(window, "activateWindow")

    window.raise_and_activate()

    force_foreground.assert_called_once_with(window)


def test_raise_and_activate_skips_the_windows_helper_elsewhere(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Off Windows, the platform-specific foreground helper is never invoked.

    **Test steps:**

    * force ``sys.platform`` to ``"linux"`` and mock the Windows-only helper
    * call ``raise_and_activate``
    * verify the helper was never called
    """
    mocker.patch("rehuco_agent.main_window.sys.platform", "linux")
    force_foreground = mocker.patch("borco_pyside.platforms.windows.window_activation.force_foreground")
    window = MainWindow()
    qtbot.addWidget(window)
    mocker.patch.object(window, "show")
    mocker.patch.object(window, "raise_")
    mocker.patch.object(window, "activateWindow")

    window.raise_and_activate()

    force_foreground.assert_not_called()
