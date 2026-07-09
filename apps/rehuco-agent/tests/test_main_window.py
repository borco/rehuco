"""Tests for MainWindow: the top-level dock-in-dock shell hosting DocumentsDock."""

from pathlib import Path
from typing import Any

from PySide6.QtCore import QByteArray
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QDialog, QWidget
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.main_window import MainWindow
from rehuco_agent.settings.document_session_settings import DocumentSessionSettings
from rehuco_agent.settings.window_settings import WindowSettings


@fixture(autouse=True)
def mock_persistent_settings(mocker: MockerFixture) -> Any:
    """Stand in for ``persistent_settings()`` so session load/save never touch real QSettings storage.

    ``value`` must return whatever default it was called with -- a bare ``MagicMock`` would
    otherwise return a truthy, garbage ``MagicMock`` for calls like ``value(KEY, QByteArray(),
    type=QByteArray)``, since ``bytes(MagicMock())`` doesn't raise -- which would make every
    ``MainWindow()`` in these tests spuriously call ``restoreGeometry`` with junk bytes.
    ``beginReadArray`` must return an int (``DocumentSessionSettings.load`` feeds it to ``range()``).
    """
    settings = mocker.MagicMock()
    settings.value.side_effect = lambda key, default=None, type=None: default  # noqa: A002
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


def test_on_document_focus_changed_shows_the_label_alongside_the_base_title(
    mocker: MockerFixture, qtbot: QtBot
) -> None:
    """Reporting a focused document's widget sets the window title to "<label> - <base title>".

    **Test steps:**

    * construct ``MainWindow`` and note its base (``.ui``-set) title
    * call the private focus-changed handler with a stand-in widget reporting a label
    * verify the window title includes it
    """
    window = MainWindow()
    qtbot.addWidget(window)
    base_title = window.windowTitle()
    widget = mocker.MagicMock(model=mocker.MagicMock(label="foo"))

    window._MainWindow__on_document_focus_changed(widget)  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    assert window.windowTitle() == f"foo - {base_title}"


def test_on_document_focus_changed_reverts_to_the_base_title_for_none(qtbot: QtBot) -> None:
    """Reporting no focused document (``None``) reverts the window title to the base title.

    **Test steps:**

    * construct ``MainWindow``, change its title, then call the handler with ``None``
    * verify the window title reverted to the base title
    """
    window = MainWindow()
    qtbot.addWidget(window)
    base_title = window.windowTitle()
    window.setWindowTitle("something else")

    window._MainWindow__on_document_focus_changed(None)  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    assert window.windowTitle() == base_title


def test_document_focus_changed_is_wired_to_the_window_title(mocker: MockerFixture, qtbot: QtBot) -> None:
    """``DocumentsDock.document_focus_changed`` really is connected to the window-title handler.

    **Test steps:**

    * construct ``MainWindow``
    * emit ``document_focus_changed`` directly on its documents dock, with a stand-in widget
    * verify the window title picked up its label
    """
    window = MainWindow()
    qtbot.addWidget(window)
    base_title = window.windowTitle()
    docs_dock = window._MainWindow__documents_dock  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    widget = mocker.MagicMock(model=mocker.MagicMock(label="bar"))

    docs_dock.document_focus_changed.emit(widget)

    assert window.windowTitle() == f"bar - {base_title}"


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


def test_open_folder_resolves_and_delegates_to_the_documents_dock(mocker: MockerFixture, qtbot: QtBot) -> None:
    """``open_folder`` resolves its path and hands it to the documents dock (#43).

    **Test steps:**

    * mock only ``DocumentsDock.open_folder`` (same reasoning as ``open_file``'s test above)
    * construct a ``MainWindow`` and call ``open_folder`` with a relative path
    * verify ``open_folder`` was called with the resolved absolute path
    """
    open_folder = mocker.patch("rehuco_agent.main_window.DocumentsDock.open_folder")
    window = MainWindow()
    qtbot.addWidget(window)

    window.open_folder("a_folder")

    open_folder.assert_called_once_with(Path("a_folder").resolve())


def test_open_path_dispatches_a_file_path_to_open_file(mocker: MockerFixture, qtbot: QtBot) -> None:
    """``open_path`` hands a non-directory path to ``open_file`` (#43).

    **Test steps:**

    * mock ``Path.is_dir`` to report the path is not a directory
    * call ``open_path``
    * verify ``open_file`` (not ``open_folder``) was called with the path
    """
    mocker.patch("rehuco_agent.main_window.Path.is_dir", return_value=False)
    window = MainWindow()
    qtbot.addWidget(window)
    open_file = mocker.patch.object(window, "open_file")
    open_folder = mocker.patch.object(window, "open_folder")

    window.open_path("a.rehu")

    open_file.assert_called_once_with("a.rehu")
    open_folder.assert_not_called()


def test_open_path_dispatches_a_directory_path_to_open_folder(mocker: MockerFixture, qtbot: QtBot) -> None:
    """``open_path`` hands a directory path to ``open_folder`` instead (#43).

    **Test steps:**

    * mock ``Path.is_dir`` to report the path is a directory
    * call ``open_path``
    * verify ``open_folder`` (not ``open_file``) was called with the path
    """
    mocker.patch("rehuco_agent.main_window.Path.is_dir", return_value=True)
    window = MainWindow()
    qtbot.addWidget(window)
    open_file = mocker.patch.object(window, "open_file")
    open_folder = mocker.patch.object(window, "open_folder")

    window.open_path("a_folder")

    open_folder.assert_called_once_with("a_folder")
    open_file.assert_not_called()


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


def test_restores_window_geometry_when_previously_saved(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Previously-saved window geometry is restored on construction.

    **Test steps:**

    * seed ``WindowSettings.load`` to report saved geometry bytes
    * mock ``restoreGeometry`` to detect the call
    * construct ``MainWindow``
    * verify ``restoreGeometry`` was called with those bytes
    """

    def fake_load(self: WindowSettings, settings: object) -> None:
        del settings
        self.geometry = b"geometry-bytes"

    mocker.patch.object(WindowSettings, "load", fake_load)
    restore_geometry = mocker.patch.object(MainWindow, "restoreGeometry")

    window = MainWindow()
    qtbot.addWidget(window)

    restore_geometry.assert_called_once_with(QByteArray(b"geometry-bytes"))


def test_skips_restoring_geometry_when_nothing_was_saved(mocker: MockerFixture, qtbot: QtBot) -> None:
    """With no previously-saved geometry, construction doesn't call ``restoreGeometry`` at all.

    **Test steps:**

    * mock ``restoreGeometry`` to detect an unwanted call
    * construct ``MainWindow`` (the default mocked settings report no saved geometry)
    * verify ``restoreGeometry`` was never called
    """
    restore_geometry = mocker.patch.object(MainWindow, "restoreGeometry")

    window = MainWindow()
    qtbot.addWidget(window)

    restore_geometry.assert_not_called()


def test_close_event_saves_the_window_geometry(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Closing the app saves the window's current geometry.

    **Test steps:**

    * mock ``saveGeometry`` to return known bytes
    * dispatch a close event
    * verify ``WindowSettings.save`` was called with those bytes recorded on the instance
    """
    window = MainWindow()
    qtbot.addWidget(window)
    mocker.patch.object(window, "saveGeometry", return_value=QByteArray(b"new-geometry"))
    save = mocker.patch.object(WindowSettings, "save")
    event = QCloseEvent()

    window.closeEvent(event)

    window_settings = window._MainWindow__window_settings  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert window_settings.geometry == b"new-geometry"
    save.assert_called_once()


def test_restore_session_refocuses_the_previously_focused_document(mocker: MockerFixture, qtbot: QtBot) -> None:
    """The document focused when the session was last saved is re-focused on restore.

    **Test steps:**

    * seed the session with two open items and a matching focused-document path
    * mock ``open_document`` to return a stand-in widget for each path
    * construct ``MainWindow``
    * verify ``open_document`` was called an extra, final time for the focused path (to re-focus
      its already-open dock)
    """
    first_path = Path("first.rehu").resolve()
    second_path = Path("second.rehu").resolve()

    def fake_load(self: DocumentSessionSettings, settings: object) -> None:
        del settings
        # pylint: disable=unsupported-assignment-operation
        self.items[first_path] = DocumentSessionSettings.Item(open=True, state=b"first")
        self.items[second_path] = DocumentSessionSettings.Item(open=True, state=b"second")
        self.focused_path = second_path

    mocker.patch.object(DocumentSessionSettings, "load", fake_load)
    open_document = mocker.patch(
        "rehuco_agent.main_window.DocumentsDock.open_document", return_value=mocker.MagicMock()
    )

    window = MainWindow()
    qtbot.addWidget(window)

    assert open_document.call_args_list[-1].args == (second_path,)  # pylint: disable=no-member
    assert open_document.call_count == 3  # first_path, second_path, then second_path again to focus it


def test_restore_session_does_not_refocus_a_document_that_failed_to_reopen(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A remembered focused document that fails to reopen isn't re-focused (nothing to focus).

    **Test steps:**

    * seed the session with a focused-document path that isn't among the successfully-opened ones
    * construct ``MainWindow``
    * verify ``open_document`` was called exactly once for that path (the initial attempt), not twice
    """
    path = Path("missing.rehu").resolve()

    def fake_load(self: DocumentSessionSettings, settings: object) -> None:
        del settings
        self.items[path] = DocumentSessionSettings.Item(open=True, state=b"state")  # pylint: disable=unsupported-assignment-operation
        self.focused_path = path

    mocker.patch.object(DocumentSessionSettings, "load", fake_load)
    open_document = mocker.patch("rehuco_agent.main_window.DocumentsDock.open_document", return_value=None)

    window = MainWindow()
    qtbot.addWidget(window)

    open_document.assert_called_once_with(path)


def test_close_event_records_the_focused_document(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Closing the app records the currently-focused document's path into the session.

    **Test steps:**

    * mock ``focused_document_path`` to report a path
    * dispatch a close event
    * verify the session's ``focused_document`` was set to it
    """
    window = MainWindow()
    qtbot.addWidget(window)
    path = Path("focused.rehu").resolve()
    docs_dock = window._MainWindow__documents_dock  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    mocker.patch.object(docs_dock, "focused_document_path", return_value=path)
    mocker.patch.object(DocumentSessionSettings, "save")
    event = QCloseEvent()

    window.closeEvent(event)

    session = window._MainWindow__session  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert session.focused_path == path


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
