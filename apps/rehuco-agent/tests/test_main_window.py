"""Tests for MainWindow: the top-level dock-in-dock shell hosting DocumentsDock."""

# the shell has a broad surface (docks, session restore, geometry, docks menu, close handling);
# its test suite is correspondingly long -- one cohesive module reads better than an arbitrary
# split, so the module-length cap is lifted here rather than fragmenting it.
# pylint: disable=too-many-lines

from pathlib import Path
from typing import Any

from borco_pyside.dialogs import DockableDialogManager
from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QDialog, QLabel, QWidget
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.main_window import SETTINGS_DIALOG_OBJECT_NAME, MainWindow
from rehuco_agent.settings.document_session_settings import DocumentSessionSettings
from rehuco_agent.settings.main_window_settings import MainWindowSettings
from rehuco_agent.settings.ui.markdown_rendering_page import MarkdownRenderingPage


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


def test_installs_a_settings_dock_on_the_outer_manager(qtbot: QtBot) -> None:
    """The settings dock (#47) is registered on the *outer* manager -- not nested inside
    `DocumentsDock`'s own manager -- so it never gets tangled up with per-document docks.

    **Test steps:**

    * construct a real ``MainWindow``
    * find the outer dock manager's registered dock named :data:`SETTINGS_DIALOG_OBJECT_NAME`
    * verify it exists and is placed somewhere (has its own dock area)
    """
    window = MainWindow()
    qtbot.addWidget(window)

    dock_manager = window._MainWindow__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    settings_dock = dock_manager.findDockWidget(SETTINGS_DIALOG_OBJECT_NAME)

    assert settings_dock is not None
    assert settings_dock.dockAreaWidget() is not None


def test_settings_dock_is_placed_floating_by_default(qtbot: QtBot) -> None:
    """With nothing saved yet, the settings dock defaults to floating -- not docked/split into the
    documents area -- so a fresh install shows it as a normal, independent app window (#47).

    **Test steps:**

    * construct a real ``MainWindow`` and find the settings dock -- ``__init__``'s
      ``dialog_manager.restore_all()`` (#55) closes it by default since nothing is persisted, so
      reopen it to inspect its placement
    * verify it reports itself as floating
    """
    window = MainWindow()
    qtbot.addWidget(window)

    dock_manager = window._MainWindow__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    settings_dock = dock_manager.findDockWidget(SETTINGS_DIALOG_OBJECT_NAME)

    assert settings_dock is not None
    settings_dock.toggleView(True)
    assert settings_dock.isFloating()


def test_settings_dock_toggle_action_is_added_to_the_action_bar(qtbot: QtBot) -> None:
    """The settings dock's ``toggleViewAction`` is added to the new vertical action-bar toolbar.

    **Test steps:**

    * construct a real ``MainWindow``
    * find the settings dock and its own toggle action
    * verify that action is among the action bar's actions
    """
    window = MainWindow()
    qtbot.addWidget(window)

    dock_manager = window._MainWindow__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    settings_dock = dock_manager.findDockWidget(SETTINGS_DIALOG_OBJECT_NAME)
    assert settings_dock is not None

    ui = window._MainWindow__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert settings_dock.toggleViewAction() in ui.action_bar.actions()


@mark.windows
def test_registers_the_registry_page_on_windows(qtbot: QtBot) -> None:
    """On Windows, the Registry settings page (#47) is registered into the settings dialog.

    **Test steps:**

    * construct a real ``MainWindow``
    * verify the settings dialog's page stack holds a ``RegistryPage``
    """
    from rehuco_agent.settings.ui.registry_page import RegistryPage  # pylint: disable=import-outside-toplevel

    window = MainWindow()
    qtbot.addWidget(window)

    settings_dialog = window._MainWindow__settings_dialog  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    dialog_ui = settings_dialog._SettingsDialog__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    pages = [dialog_ui.page_stack.widget(index) for index in range(dialog_ui.page_stack.count())]
    assert any(isinstance(page, RegistryPage) for page in pages)


def test_registers_the_markdown_rendering_page(qtbot: QtBot) -> None:
    """The Markdown Rendering settings page (#26, #47) is registered into the settings dialog,
    on every platform (unlike the Windows-only Registry page).

    **Test steps:**

    * construct a real ``MainWindow``
    * verify the settings dialog's page stack holds a ``MarkdownRenderingPage``
    """
    window = MainWindow()
    qtbot.addWidget(window)

    settings_dialog = window._MainWindow__settings_dialog  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    dialog_ui = settings_dialog._SettingsDialog__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    pages = [dialog_ui.page_stack.widget(index) for index in range(dialog_ui.page_stack.count())]
    assert any(isinstance(page, MarkdownRenderingPage) for page in pages)


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


def test_open_archive_resolves_and_delegates_to_the_documents_dock(mocker: MockerFixture, qtbot: QtBot) -> None:
    """``open_archive`` resolves its path and hands it to the documents dock (#43).

    **Test steps:**

    * mock only ``DocumentsDock.open_archive`` (same reasoning as ``open_file``'s test above)
    * construct a ``MainWindow`` and call ``open_archive`` with a relative path
    * verify ``open_archive`` was called with the resolved absolute path
    """
    open_archive = mocker.patch("rehuco_agent.main_window.DocumentsDock.open_archive")
    window = MainWindow()
    qtbot.addWidget(window)

    window.open_archive("a.zip")

    open_archive.assert_called_once_with(Path("a.zip").resolve())


def test_open_path_dispatches_a_file_path_to_open_file(mocker: MockerFixture, qtbot: QtBot) -> None:
    """``open_path`` hands a non-directory, non-archive path to ``open_file`` (#43).

    **Test steps:**

    * mock ``Path.is_dir`` to report the path is not a directory
    * call ``open_path``
    * verify ``open_file`` (not ``open_folder``/``open_archive``) was called with the path
    """
    mocker.patch("rehuco_agent.main_window.Path.is_dir", return_value=False)
    window = MainWindow()
    qtbot.addWidget(window)
    open_file = mocker.patch.object(window, "open_file")
    open_folder = mocker.patch.object(window, "open_folder")
    open_archive = mocker.patch.object(window, "open_archive")

    window.open_path("a.rehu")

    open_file.assert_called_once_with("a.rehu")
    open_folder.assert_not_called()
    open_archive.assert_not_called()


def test_open_path_dispatches_a_directory_path_to_open_folder(mocker: MockerFixture, qtbot: QtBot) -> None:
    """``open_path`` hands a directory path to ``open_folder`` instead (#43).

    **Test steps:**

    * mock ``Path.is_dir`` to report the path is a directory
    * call ``open_path``
    * verify ``open_folder`` (not ``open_file``/``open_archive``) was called with the path
    """
    mocker.patch("rehuco_agent.main_window.Path.is_dir", return_value=True)
    window = MainWindow()
    qtbot.addWidget(window)
    open_file = mocker.patch.object(window, "open_file")
    open_folder = mocker.patch.object(window, "open_folder")
    open_archive = mocker.patch.object(window, "open_archive")

    window.open_path("a_folder")

    open_folder.assert_called_once_with("a_folder")
    open_file.assert_not_called()
    open_archive.assert_not_called()


def test_open_path_dispatches_an_archive_path_to_open_archive(mocker: MockerFixture, qtbot: QtBot) -> None:
    """``open_path`` hands a path with an :data:`~rehuco_agent.main_window.ARCHIVE_EXTENSIONS` suffix
    to ``open_archive`` instead (#43).

    **Test steps:**

    * mock ``Path.is_dir`` to report the path is not a directory
    * call ``open_path`` with a ``.zip`` path
    * verify ``open_archive`` (not ``open_file``/``open_folder``) was called with the path
    """
    mocker.patch("rehuco_agent.main_window.Path.is_dir", return_value=False)
    window = MainWindow()
    qtbot.addWidget(window)
    open_file = mocker.patch.object(window, "open_file")
    open_folder = mocker.patch.object(window, "open_folder")
    open_archive = mocker.patch.object(window, "open_archive")

    window.open_path("a.zip")

    open_archive.assert_called_once_with("a.zip")
    open_file.assert_not_called()
    open_folder.assert_not_called()


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

    * seed ``MainWindowSettings.load`` to report saved geometry bytes
    * mock ``restoreGeometry`` to detect the call
    * construct ``MainWindow``
    * verify ``restoreGeometry`` was called with those bytes
    """

    def fake_load(self: MainWindowSettings, settings: object) -> None:
        del settings
        self.geometry = b"geometry-bytes"

    mocker.patch.object(MainWindowSettings, "load", fake_load)
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
    * verify ``MainWindowSettings.save`` was called with those bytes recorded on the instance
    """
    window = MainWindow()
    qtbot.addWidget(window)
    mocker.patch.object(window, "saveGeometry", return_value=QByteArray(b"new-geometry"))
    save = mocker.patch.object(MainWindowSettings, "save")
    event = QCloseEvent()

    window.closeEvent(event)

    window_settings = window._MainWindow__window_settings  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert window_settings.geometry == b"new-geometry"
    save.assert_called_once()


def test_close_event_saves_the_outer_docks_state(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Closing the app saves the outer dock manager's own layout (central dock + settings dock, #47).

    **Test steps:**

    * construct ``MainWindow``
    * mock ``MainWindowSettings.save`` to detect the call
    * dispatch a close event
    * verify the recorded outer dock state is real, non-empty ``CDockManager`` state
    """
    window = MainWindow()
    qtbot.addWidget(window)
    save = mocker.patch.object(MainWindowSettings, "save")
    event = QCloseEvent()

    window.closeEvent(event)

    window_settings = window._MainWindow__window_settings  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert window_settings.outer_docks_state != b""
    save.assert_called_once()


def test_close_event_saves_an_unchecked_settings_dock_as_closed_even_while_open(
    mocker: MockerFixture, qtbot: QtBot
) -> None:
    """A settings dock left open (e.g. floated out) but with "Restore on start" unchecked is saved
    as closed -- not saved open-then-corrected on the next restore, which would flash the floating
    window open before hiding it again (#47).

    **Test steps:**

    * construct a window; reopen the settings dock (``__init__``'s ``dialog_manager.restore_all()``,
      #55, closes it by default since nothing is persisted yet) and leave "Restore on start" unchecked
    * dispatch a close event
    * construct a second window seeded (via a mocked ``load``) with the saved outer dock state
    * verify the second window's settings dock is closed, having never needed to be shown at all
    """
    first = MainWindow()
    qtbot.addWidget(first)
    dock_manager = first._MainWindow__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    settings_dock = dock_manager.findDockWidget(SETTINGS_DIALOG_OBJECT_NAME)
    assert settings_dock is not None
    settings_dock.toggleView(True)  # "Restore on start" defaults unchecked

    first.closeEvent(QCloseEvent())

    window_settings = first._MainWindow__window_settings  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    saved_state = window_settings.outer_docks_state

    def fake_load(self: MainWindowSettings, settings: object) -> None:
        del settings
        self.outer_docks_state = saved_state

    mocker.patch.object(MainWindowSettings, "load", fake_load)

    second = MainWindow()
    qtbot.addWidget(second)
    second_dock_manager = second._MainWindow__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    second_settings_dock = second_dock_manager.findDockWidget(SETTINGS_DIALOG_OBJECT_NAME)

    assert second_settings_dock is not None
    assert second_settings_dock.isClosed()


def test_outer_docks_state_round_trips_the_settings_dock_visibility(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A settings dock closed before saving stays closed once a fresh window restores that state.

    **Test steps:**

    * construct a window, close its settings dock, then capture the real outer dock state it saves
    * construct a second window seeded (via a mocked ``load``) with that saved state
    * verify the second window's settings dock is also closed
    """
    first = MainWindow()
    qtbot.addWidget(first)
    dock_manager = first._MainWindow__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    settings_dock = dock_manager.findDockWidget(SETTINGS_DIALOG_OBJECT_NAME)
    assert settings_dock is not None
    settings_dock.toggleView(False)

    first._MainWindow__save_window_state()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    window_settings = first._MainWindow__window_settings  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    saved_state = window_settings.outer_docks_state

    def fake_load(self: MainWindowSettings, settings: object) -> None:
        del settings
        self.outer_docks_state = saved_state

    mocker.patch.object(MainWindowSettings, "load", fake_load)

    second = MainWindow()
    qtbot.addWidget(second)
    second_dock_manager = second._MainWindow__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    second_settings_dock = second_dock_manager.findDockWidget(SETTINGS_DIALOG_OBJECT_NAME)

    assert second_settings_dock is not None
    assert second_settings_dock.isClosed()


def test_close_event_saves_every_registered_dockable_dialog(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Closing the app persists every registered dockable dialog's own settings (#47).

    **Test steps:**

    * construct ``MainWindow``
    * mock ``DockableDialogManager.save_all`` to detect the call
    * dispatch a close event
    * verify ``save_all`` was called once
    """
    window = MainWindow()
    qtbot.addWidget(window)
    save_all = mocker.patch.object(DockableDialogManager, "save_all")
    event = QCloseEvent()

    window.closeEvent(event)

    save_all.assert_called_once()


def test_close_event_saves_the_toolbars_state(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Closing the app saves the toolbar's own layout (the ``action_bar`` area).

    **Test steps:**

    * construct ``MainWindow``
    * mock ``MainWindowSettings.save`` to detect the call
    * dispatch a close event
    * verify the recorded toolbars state is real, non-empty ``QMainWindow`` state
    """
    window = MainWindow()
    qtbot.addWidget(window)
    save = mocker.patch.object(MainWindowSettings, "save")
    event = QCloseEvent()

    window.closeEvent(event)

    window_settings = window._MainWindow__window_settings  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert window_settings.toolbars_state != b""
    save.assert_called_once()


def test_toolbars_state_round_trips_the_action_bar_area(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Moving the action bar to a different toolbar area survives a save/restore round trip.

    **Test steps:**

    * construct a window, move its action bar to the bottom area, then capture the real toolbars
      state it saves
    * construct a second window seeded (via a mocked ``load``) with that saved state
    * verify the second window's action bar is also in the bottom area
    """
    first = MainWindow()
    qtbot.addWidget(first)
    first_ui = first._MainWindow__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    first.addToolBar(Qt.ToolBarArea.BottomToolBarArea, first_ui.action_bar)

    first._MainWindow__save_window_state()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    window_settings = first._MainWindow__window_settings  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    saved_state = window_settings.toolbars_state

    def fake_load(self: MainWindowSettings, settings: object) -> None:
        del settings
        self.toolbars_state = saved_state

    mocker.patch.object(MainWindowSettings, "load", fake_load)

    second = MainWindow()
    qtbot.addWidget(second)
    second_ui = second._MainWindow__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    assert second.toolBarArea(second_ui.action_bar) == Qt.ToolBarArea.BottomToolBarArea


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

    Builds the window *before* faking ``sys.platform`` -- ``MainWindow.__init__`` has its own,
    unrelated ``sys.platform == "win32"`` check (``__register_settings_pages``, #47) that would
    otherwise also see the faked value and genuinely try to import the Windows-only
    ``rehuco_agent.windows_registration`` (-> ``winreg``) on whatever OS actually runs this test,
    crashing on macOS/Linux CI instead of being about ``raise_and_activate`` at all.

    **Test steps:**

    * build the window with the real platform still in effect
    * force ``sys.platform`` to ``"win32"`` and mock the Windows-only helper
    * call ``raise_and_activate``
    * verify the helper was called with this window
    """
    window = MainWindow()
    qtbot.addWidget(window)
    mocker.patch.object(window, "show")
    mocker.patch.object(window, "raise_")
    mocker.patch.object(window, "activateWindow")

    mocker.patch("rehuco_agent.main_window.sys.platform", "win32")
    force_foreground = mocker.patch("borco_pyside.platforms.windows.window_activation.force_foreground")

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


def test_docks_menu_lists_open_documents_alphabetically_by_title(mocker: MockerFixture, qtbot: QtBot) -> None:
    """The ``View`` menu lists every open document, sorted alphabetically (case-insensitively) by title (#61).

    **Test steps:**
    * construct ``MainWindow`` and stand in three open documents with titles out of order/case
    * populate the docks menu
    * verify each entry's title label reads back in alphabetical order
    """
    window = MainWindow()
    qtbot.addWidget(window)
    widgets = [
        mocker.MagicMock(model=mocker.MagicMock(label=label, path=Path(f"/{label}/info.rehu"), dirty=False))
        for label in ("Charlie", "alpha", "Bravo")
    ]
    for widget in widgets:
        widget.save_state.return_value = b"snapshot"  # keeps teardown's implicit close() from choking on a MagicMock
    mocker.patch.object(window._MainWindow__documents_dock, "open_document_widgets", return_value=widgets)  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    window._MainWindow__populate_docks_menu()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    menu = window._MainWindow__ui.view_menu  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    titles = [action.defaultWidget().findChildren(QLabel)[0].text() for action in menu.actions()]
    assert titles == ["alpha", "Bravo", "Charlie"]


def test_docks_menu_shows_a_disabled_placeholder_when_nothing_is_open(qtbot: QtBot) -> None:
    """With no documents open, the ``View`` menu shows a single disabled placeholder entry.

    **Test steps:**
    * construct ``MainWindow`` with nothing open
    * populate the docks menu
    * verify exactly one, disabled action is present
    """
    window = MainWindow()
    qtbot.addWidget(window)

    window._MainWindow__populate_docks_menu()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    menu = window._MainWindow__ui.view_menu  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    actions = menu.actions()
    assert len(actions) == 1
    assert not actions[0].isEnabled()


def test_docks_menu_repopulates_on_every_show(mocker: MockerFixture, qtbot: QtBot) -> None:
    """The docks menu is rebuilt fresh every time it's about to show, not just once.

    **Test steps:**
    * construct ``MainWindow`` with one open document and populate the menu once
    * stand in a second open document and emit the menu's ``aboutToShow`` again
    * verify the menu now reflects both documents
    """
    window = MainWindow()
    qtbot.addWidget(window)
    menu = window._MainWindow__ui.view_menu  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    first_widget = mocker.MagicMock(model=mocker.MagicMock(label="First", path=Path("/first/info.rehu"), dirty=False))
    first_widget.save_state.return_value = b"snapshot"  # keeps teardown's implicit close() from choking on a MagicMock
    mocker.patch.object(
        window._MainWindow__documents_dock,  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
        "open_document_widgets",
        return_value=[first_widget],
    )
    menu.aboutToShow.emit()
    assert len(menu.actions()) == 1

    second_widget = mocker.MagicMock(
        model=mocker.MagicMock(label="Second", path=Path("/second/info.rehu"), dirty=False)
    )
    second_widget.save_state.return_value = b"snapshot"
    mocker.patch.object(
        window._MainWindow__documents_dock,  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
        "open_document_widgets",
        return_value=[first_widget, second_widget],
    )
    menu.aboutToShow.emit()

    assert len(menu.actions()) == 2


def test_docks_menu_entry_triggering_focuses_that_document(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Selecting a document's entry in the ``View`` menu focuses/raises its dock (#61).

    **Test steps:**
    * construct ``MainWindow`` and stand in one open document
    * populate the docks menu and trigger its single entry
    * verify ``DocumentsDock.focus_document`` was called with that document's widget
    """
    window = MainWindow()
    qtbot.addWidget(window)
    widget = mocker.MagicMock(model=mocker.MagicMock(label="Solo", path=Path("/solo/info.rehu"), dirty=False))
    widget.save_state.return_value = b"snapshot"  # keeps teardown's implicit close() from choking on a MagicMock
    documents_dock = window._MainWindow__documents_dock  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    mocker.patch.object(documents_dock, "open_document_widgets", return_value=[widget])
    focus_document = mocker.patch.object(documents_dock, "focus_document")

    window._MainWindow__populate_docks_menu()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    menu = window._MainWindow__ui.view_menu  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    menu.actions()[0].trigger()

    focus_document.assert_called_once_with(widget)
