"""Tests for MainWindow: the top-level dock-in-dock shell hosting DocumentsDock."""

# the shell has a broad surface (docks, session restore, geometry, docks menu, close handling);
# its test suite is correspondingly long -- one cohesive module reads better than an arbitrary
# split, so the module-length cap is lifted here rather than fragmenting it.
# pylint: disable=too-many-lines

import logging
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from threading import Event
from typing import Any, Final

from borco_pyside.dialogs import DockableDialogManager
from borco_pyside.logging import LogWidget
from borco_pyside.logging.log_model import MESSAGE_COLUMN
from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QLabel,
    QMessageBox,
    QScrollArea,
    QSystemTrayIcon,
    QWidget,
)
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.app_logging import shared_log_bridge
from rehuco_agent.main_window import (
    LOG_DOCK_OBJECT_NAME,
    SETTINGS_DIALOG_OBJECT_NAME,
    TASK_QUEUE_DOCK_OBJECT_NAME,
    MainWindow,
)
from rehuco_agent.settings.checksum_settings import shared_checksum_settings
from rehuco_agent.settings.document_session_settings import DocumentSessionSettings
from rehuco_agent.settings.identity_settings import shared_identity_settings
from rehuco_agent.settings.image_viewer_settings import PREVIEWS_VISIBLE_KEY, shared_image_viewer_settings
from rehuco_agent.settings.logs_settings import shared_logs_settings
from rehuco_agent.settings.main_window_settings import MainWindowSettings
from rehuco_agent.settings.recent_files_settings import RecentFilesSettings
from rehuco_agent.settings.tasks_settings import TasksSettings
from rehuco_agent.settings.tray_settings import shared_tray_settings
from rehuco_agent.settings.ui.checksums_page import ChecksumsPage
from rehuco_agent.settings.ui.descriptions_page import DescriptionsPage
from rehuco_agent.settings.ui.excluded_files_page import ExcludedFilesPage
from rehuco_agent.settings.ui.identity_page import IdentityPage
from rehuco_agent.settings.ui.logs_page import LogsPage
from rehuco_agent.settings.ui.settings_dialog import SettingsDialog
from rehuco_agent.settings.ui.tasks_page import TasksPage
from rehuco_agent.settings.ui.videos_page import VideosPage
from rehuco_agent.tasks import TaskQueueStatusIndicator, TaskQueueWidget
from rehuco_agent.tray_icon import TrayIcon
from rehuco_core import JobControl, JobState, JobStatus, SweepChecksumsJob, TaskJobBase, TaskQueue

SWEEP_ROOT: Final = Path("/fake/library")
"""The folder a sweep test points the chooser at -- never read, since no sweep here does real work."""

SWEEP_TIMEOUT: Final = 5.0
"""How long a held sweep waits to be released, in seconds -- generous, since it only ever expires when
something is genuinely wrong."""

GATE_TIMEOUT: Final = 120.0
"""How long a gated job blocks before giving up on ever being released, in seconds -- a deadlock guard,
never a wait anything is meant to reach.

**Deliberately far longer than any assertion window**, unlike :data:`SWEEP_TIMEOUT`, which a job may
legitimately sit inside. A gated job exists to hold the queue in a *running* state while the test looks
at it, so the moment its own gate can expire first, the thing under test has already changed underneath
the assertion. That is not hypothetical: the first event-loop spin in a test can take seconds (draining
the deferred deletions every widget-heavy test above it left behind), so a five-second gate expired
before the very first sample -- the job read ``done``, the status indicator was correctly hidden, and
the failure looked like a lost signal rather than a job nobody was holding any more."""

WAIT_TIMEOUT_MS: Final = 10_000
"""How long a ``waitUntil`` gives the GUI thread to show an effect, in milliseconds.

Generous for the same reason :data:`GATE_TIMEOUT` is: the wait itself may be the spin that drains a
long-accumulated deferred-deletion backlog, so the budget has to cover that before it can honestly
call an effect missing."""

UNSAVED_CHANGES_DIALOG: Final = "rehuco_agent.documents.confirm_and_save_dirty.UnsavedChangesDialog"
"""Where the close guard's batch dialog is looked up -- the shared seam ``closeEvent`` reaches it
through (#176), not this module, so that is where these tests patch it."""


@fixture(autouse=True)
def mock_persistent_settings(mocker: MockerFixture) -> Any:
    """Stand in for ``persistent_settings()`` so session load/save never touch real QSettings storage.

    ``value`` must return whatever default it was called with -- a bare ``MagicMock`` would
    otherwise return a truthy, garbage ``MagicMock`` for calls like ``value(KEY, QByteArray(),
    type=QByteArray)``, since ``bytes(MagicMock())`` doesn't raise -- which would make every
    ``MainWindow()`` in these tests spuriously call ``restoreGeometry`` with junk bytes.
    ``beginReadArray`` must return an int (``DocumentSessionSettings.load`` feeds it to ``range()``).

    Patched at **two** import sites: this module's own, and
    ``rehuco_agent.tasks.task_queue_store``'s -- ``TaskQueueStore`` resolves ``task_queue_path()``
    off its own imported name, not this module's, so a window's task queue would otherwise compute a
    path from the real per-user settings file (#202).
    """
    settings = mocker.MagicMock()
    settings.value.side_effect = lambda key, default=None, type=None: default  # noqa: A002
    settings.beginReadArray.return_value = 0
    settings.fileName.return_value = "/dev/null/settings.ini"
    mocker.patch("rehuco_agent.tasks.task_queue_store.persistent_settings", return_value=settings)
    return mocker.patch("rehuco_agent.main_window.persistent_settings", return_value=settings)


def discard_unsaved_changes_on_close(mocker: MockerFixture) -> Any:
    """Stand in an unsaved-changes dialog that answers Accepted-with-nothing-selected (discard).

    Call this in a test that dispatches ``closeEvent`` over a mocked ``dirty`` model but isn't itself
    exercising the close guard. ``closeEvent`` pops a **real modal** ``UnsavedChangesDialog`` for any
    dirty open model (:meth:`MainWindow.closeEvent`), and its ``exec()`` would block forever with no one
    to click it; this lets such a test close over the dirty model freely. Tests that *do* exercise the
    guard (accept-and-select, reject, assert-not-constructed) must **not** call this -- they patch
    ``UnsavedChangesDialog`` themselves so the real wiring stays under test.
    """
    dialog = mocker.MagicMock()
    dialog.exec.return_value = QDialog.DialogCode.Accepted
    dialog.selected_models.return_value = []
    return mocker.patch(UNSAVED_CHANGES_DIALOG, return_value=dialog)


@fixture
def dock_entries() -> Callable[[MainWindow], list[Any]]:
    """Factory returning ``window``'s current per-document ``View`` menu entries (#57) -- the
    whole dynamic tail ``__add_open_documents`` rebuilds, excluding the static theme entries and
    their trailing separator above it -- so docks-menu tests can assert on the per-document list
    alone. ``Close All``/``Close Missing Files`` used to lead this same tail (#96); they moved to
    ``File`` (#247), so the tail is nothing but the per-document list (or its placeholder) now.
    """

    def factory(window: MainWindow) -> list[Any]:
        return list(window._MainWindow__dynamic_view_menu_actions)  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    return factory


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


def test_the_outer_manager_alone_carries_the_dock_stylesheet(qtbot: QtBot) -> None:
    """The window's outer manager styles the whole dock nest; the documents dock's carries nothing (#234).

    Pins the shape, not a wall-clock number: QtAds sets its ~10 KB default sheet on every
    ``CDockManager``, and this window nests one inside another (inside one more per open document).
    Since QSS cascades, every copy below the outermost is re-evaluated for nothing -- which is roughly
    half of what activating a document tab used to cost.

    **Test steps:**

    * construct a real ``MainWindow`` and reach both its own manager and the documents dock's
    * verify the outer one carries QtAds' default sheet *and* the tracked-focus rules, and the nested
      one carries nothing at all
    """
    window = MainWindow()
    qtbot.addWidget(window)
    outer = window._MainWindow__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    documents_dock = window._MainWindow__documents_dock  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    nested = documents_dock._DocumentsDock__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    assert "ads--CDockWidgetTab" in outer.styleSheet()
    assert '[tracked_focus="true"]' in outer.styleSheet()
    assert nested.styleSheet() == ""


def test_a_documents_dock_status_message_shows_on_the_status_bar(qtbot: QtBot) -> None:
    """A field's status message, relayed up by ``DocumentsDock``, lands on this window's real status
    bar; an empty message clears it. This is the genuine top-level window -- the one place safely wired
    to a status bar -- so routing lands here rather than at any embedded ``QMainWindow`` in between (the
    ``.window()`` trap).

    **Test steps:**

    * construct a real ``MainWindow`` and reach its documents dock
    * emit the dock's ``status_message`` with an href and verify the status bar shows it
    * emit an empty message and verify the status bar clears
    """
    window = MainWindow()
    qtbot.addWidget(window)
    documents_dock = window._MainWindow__documents_dock  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    documents_dock.status_message.emit("https://example.com/alice")
    assert window.statusBar().currentMessage() == "https://example.com/alice"

    documents_dock.status_message.emit("")
    assert window.statusBar().currentMessage() == ""


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
    # each page is shown through a scroll area of its own (#229), so read it back out of one
    stacked = [dialog_ui.page_stack.widget(index) for index in range(dialog_ui.page_stack.count())]
    pages = [area.widget() for area in stacked if isinstance(area, QScrollArea)]
    assert any(isinstance(page, RegistryPage) for page in pages)


def test_registers_the_desktop_integration_page_on_linux(qtbot: QtBot, mocker: MockerFixture) -> None:
    """On Linux, the Desktop Integration settings page (#209) fills the same System Integration slot.

    Faked rather than skipped off Linux: the page and the `linux_registration` module behind it are
    plain ``pathlib`` code, so they construct anywhere -- unlike the Windows page, which needs
    ``winreg``.

    **Test steps:**

    * force ``sys.platform`` to Linux, then construct a real ``MainWindow``
    * verify the settings dialog's page stack holds a ``DesktopIntegrationPage``
    """
    from rehuco_agent.settings.ui.desktop_integration_page import (  # pylint: disable=import-outside-toplevel
        DesktopIntegrationPage,
    )

    mocker.patch("rehuco_agent.main_window.sys.platform", "linux")
    window = MainWindow()
    qtbot.addWidget(window)

    settings_dialog = window._MainWindow__settings_dialog  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    dialog_ui = settings_dialog._SettingsDialog__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    # each page is shown through a scroll area of its own (#229), so read it back out of one
    stacked = [dialog_ui.page_stack.widget(index) for index in range(dialog_ui.page_stack.count())]
    pages = [area.widget() for area in stacked if isinstance(area, QScrollArea)]
    assert any(isinstance(page, DesktopIntegrationPage) for page in pages)


def test_registers_no_system_integration_page_on_other_platforms(qtbot: QtBot, mocker: MockerFixture) -> None:
    """Everywhere else the slot stays empty: neither page is registered rather than one standing in for
    the other, since each is about a desktop the platform does not have.

    Faked rather than skipped, like its Linux sibling above, so the assertion runs the same on every CI
    leg -- and it is the only test that builds the window on a platform that is neither, which is what
    exercises both guards' *other* branch.

    **Test steps:**

    * force ``sys.platform`` to macOS, then construct a real ``MainWindow``
    * verify the settings dialog's page stack holds neither platform's page
    """
    from rehuco_agent.settings.ui.desktop_integration_page import (  # pylint: disable=import-outside-toplevel
        DesktopIntegrationPage,
    )

    mocker.patch("rehuco_agent.main_window.sys.platform", "darwin")
    window = MainWindow()
    qtbot.addWidget(window)

    settings_dialog = window._MainWindow__settings_dialog  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    dialog_ui = settings_dialog._SettingsDialog__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    # each page is shown through a scroll area of its own (#229), so read it back out of one
    stacked = [dialog_ui.page_stack.widget(index) for index in range(dialog_ui.page_stack.count())]
    pages = [area.widget() for area in stacked if isinstance(area, QScrollArea)]
    assert not any(isinstance(page, DesktopIntegrationPage) for page in pages)
    # by name rather than by class: importing the Windows page pulls in `winreg`, which is the very
    # thing this platform does not have
    assert not any(type(page).__name__ == "RegistryPage" for page in pages)


def test_registers_the_identity_page(qtbot: QtBot) -> None:
    """The Identity settings page (#99) is registered into the settings dialog, on every platform.

    **Test steps:**

    * construct a real ``MainWindow``
    * verify the settings dialog's page stack holds an ``IdentityPage``
    """
    window = MainWindow()
    qtbot.addWidget(window)

    settings_dialog = window._MainWindow__settings_dialog  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    dialog_ui = settings_dialog._SettingsDialog__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    # each page is shown through a scroll area of its own (#229), so read it back out of one
    stacked = [dialog_ui.page_stack.widget(index) for index in range(dialog_ui.page_stack.count())]
    pages = [area.widget() for area in stacked if isinstance(area, QScrollArea)]
    assert any(isinstance(page, IdentityPage) for page in pages)


def test_registers_the_excluded_files_page_under_the_plugins_group(qtbot: QtBot) -> None:
    """The Excluded Files page (#226) is registered into the settings dialog, under "Plugins".

    **Test steps:**

    * construct a real ``MainWindow``
    * verify the settings dialog's page stack holds an ``ExcludedFilesPage``
    """
    window = MainWindow()
    qtbot.addWidget(window)

    settings_dialog = window._MainWindow__settings_dialog  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    dialog_ui = settings_dialog._SettingsDialog__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    # each page is shown through a scroll area of its own (#229), so read it back out of one
    stacked = [dialog_ui.page_stack.widget(index) for index in range(dialog_ui.page_stack.count())]
    pages = [area.widget() for area in stacked if isinstance(area, QScrollArea)]
    assert any(isinstance(page, ExcludedFilesPage) for page in pages)


def test_registers_the_videos_page_under_the_plugins_group(qtbot: QtBot) -> None:
    """The Videos page (#225) is registered into the settings dialog, under "Plugins".

    **Test steps:**

    * construct a real ``MainWindow``
    * verify the settings dialog's page stack holds a ``VideosPage``
    """
    window = MainWindow()
    qtbot.addWidget(window)

    settings_dialog = window._MainWindow__settings_dialog  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    dialog_ui = settings_dialog._SettingsDialog__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    # each page is shown through a scroll area of its own (#229), so read it back out of one
    stacked = [dialog_ui.page_stack.widget(index) for index in range(dialog_ui.page_stack.count())]
    pages = [area.widget() for area in stacked if isinstance(area, QScrollArea)]
    assert any(isinstance(page, VideosPage) for page in pages)


def test_the_plugins_group_lists_every_page_alphabetically(qtbot: QtBot) -> None:
    """Descriptions, Images and Viewers folded into one "Plugins" group, sorted by title (#230).

    **Test steps:**

    * construct a real ``MainWindow``
    * verify the settings dialog's category tree holds a single "Plugins" row, its children in
      alphabetical order -- Reference Images among them no longer, its list being a block on Images
    """
    window = MainWindow()
    qtbot.addWidget(window)

    settings_dialog = window._MainWindow__settings_dialog  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    model = settings_dialog._SettingsDialog__model  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    groups = [model.item(row) for row in range(model.rowCount()) if model.item(row).text() == "Plugins"]
    assert len(groups) == 1
    assert [groups[0].child(row).text() for row in range(groups[0].rowCount())] == [
        "Descriptions",
        "Excluded Files",
        "Images",
        "Videos",
    ]


def test_registers_the_checksums_page_at_the_top_level(qtbot: QtBot) -> None:
    """Checksums govern every resource type rather than one plugin's, so the page is not in Plugins (#242).

    **Test steps:**

    * construct a real ``MainWindow``
    * verify the page stack holds a `ChecksumsPage` and the category tree lists it at the top level
    """
    window = MainWindow()
    qtbot.addWidget(window)

    settings_dialog = window._MainWindow__settings_dialog  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    dialog_ui = settings_dialog._SettingsDialog__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    stacked = [dialog_ui.page_stack.widget(index) for index in range(dialog_ui.page_stack.count())]
    pages = [area.widget() for area in stacked if isinstance(area, QScrollArea)]
    assert any(isinstance(page, ChecksumsPage) for page in pages)

    model = settings_dialog._SettingsDialog__model  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert [model.item(row).text() for row in range(model.rowCount())].count("Checksums") == 1


def test_registers_the_descriptions_page(qtbot: QtBot) -> None:
    """The Descriptions settings page (#26, #47) is registered into the settings dialog,
    on every platform (unlike the Windows-only System Integration page).

    **Test steps:**

    * construct a real ``MainWindow``
    * verify the settings dialog's page stack holds a ``DescriptionsPage``
    """
    window = MainWindow()
    qtbot.addWidget(window)

    settings_dialog = window._MainWindow__settings_dialog  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    dialog_ui = settings_dialog._SettingsDialog__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    # each page is shown through a scroll area of its own (#229), so read it back out of one
    stacked = [dialog_ui.page_stack.widget(index) for index in range(dialog_ui.page_stack.count())]
    pages = [area.widget() for area in stacked if isinstance(area, QScrollArea)]
    assert any(isinstance(page, DescriptionsPage) for page in pages)


def test_registers_no_reference_images_page_of_its_own(qtbot: QtBot) -> None:
    """The reference-images extension list is a block on Images, not a page (#222).

    **Test steps:**

    * construct a real ``MainWindow``
    * verify no registered page is titled "Reference Images"
    """
    window = MainWindow()
    qtbot.addWidget(window)

    settings_dialog = window._MainWindow__settings_dialog  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    dialog_ui = settings_dialog._SettingsDialog__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    # each page is shown through a scroll area of its own (#229), so read it back out of one
    stacked = [dialog_ui.page_stack.widget(index) for index in range(dialog_ui.page_stack.count())]
    pages = [area.widget() for area in stacked if isinstance(area, QScrollArea)]
    assert "Reference Images" not in [getattr(page, "title", None) for page in pages]


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


def test_close_action_is_disabled_with_no_document_focused(qtbot: QtBot) -> None:
    """``File`` > ``Close`` (``Ctrl+W``, #247) starts disabled -- nothing is focused on construction.

    **Test steps:**

    * construct ``MainWindow``
    * verify ``close_action`` is disabled
    """
    window = MainWindow()
    qtbot.addWidget(window)

    assert not window._MainWindow__ui.close_action.isEnabled()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def test_document_focus_changed_toggles_the_close_action(mocker: MockerFixture, qtbot: QtBot) -> None:
    """``close_action`` is enabled iff a document is focused, read off the same
    ``document_focus_changed`` signal that drives the window title (#247).

    **Test steps:**

    * construct ``MainWindow``
    * emit ``document_focus_changed`` with a stand-in widget
    * verify ``close_action`` is enabled
    * emit it again with ``None``
    * verify ``close_action`` is disabled again
    """
    window = MainWindow()
    qtbot.addWidget(window)
    docs_dock = window._MainWindow__documents_dock  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    widget = mocker.MagicMock(model=mocker.MagicMock(label="bar"))

    docs_dock.document_focus_changed.emit(widget)

    assert window._MainWindow__ui.close_action.isEnabled()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    docs_dock.document_focus_changed.emit(None)

    assert not window._MainWindow__ui.close_action.isEnabled()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def test_close_action_triggering_delegates_to_the_documents_dock(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Triggering ``close_action`` delegates straight to ``DocumentsDock.close_focused_document`` (#247).

    **Test steps:**

    * construct ``MainWindow``
    * mock ``DocumentsDock.close_focused_document``
    * trigger ``close_action``
    * verify it was called
    """
    window = MainWindow()
    qtbot.addWidget(window)
    documents_dock = window._MainWindow__documents_dock  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    close_focused_document = mocker.patch.object(documents_dock, "close_focused_document")
    close_action = window._MainWindow__ui.close_action  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    close_action.setEnabled(True)  # a disabled action's trigger() is a no-op; a document is focused in practice

    close_action.trigger()

    close_focused_document.assert_called_once_with()


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


def test_open_file_records_a_successful_open_into_recents(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A successful ``open_file`` records the resolved path into ``Open recents`` (#64).

    **Test steps:**

    * mock ``DocumentsDock.open_document`` to return a genuinely-loaded widget (``load_failed`` False)
    * call ``open_file``
    * verify the resolved path is now the newest recent entry
    """
    widget = mocker.MagicMock()
    widget.model.document.load_failed = False
    mocker.patch("rehuco_agent.main_window.DocumentsDock.open_document", return_value=widget)
    window = MainWindow()
    qtbot.addWidget(window)

    window.open_file("a.rehu")

    recent_files = window._MainWindow__recent_files  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert recent_files.newest_first() == [Path("a.rehu").resolve()]


def test_open_file_does_not_record_a_failed_open(mocker: MockerFixture, qtbot: QtBot) -> None:
    """An ``open_file`` whose file could not be read (a load-failure stub) is not recorded into
    ``Open recents`` (#64) -- the dock still opens (locked), but a missing/unparseable file is not a file
    you opened ([[data-model#write-integrity]]).

    **Test steps:**

    * mock ``DocumentsDock.open_document`` to return a load-failure stub widget (``load_failed`` True)
    * call ``open_file``
    * verify ``Open recents`` stays empty
    """
    widget = mocker.MagicMock()
    widget.model.document.load_failed = True
    mocker.patch("rehuco_agent.main_window.DocumentsDock.open_document", return_value=widget)
    window = MainWindow()
    qtbot.addWidget(window)

    window.open_file("missing.rehu")

    recent_files = window._MainWindow__recent_files  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert recent_files.newest_first() == []


def test_open_folder_records_a_successful_open_into_recents(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A successful ``open_folder`` records the resolved path into ``Open recents`` (#64).

    **Test steps:**

    * mock ``DocumentsDock.open_folder`` to return a genuinely-loaded widget (``load_failed`` False)
    * call ``open_folder``
    * verify the resolved path is now the newest recent entry
    """
    widget = mocker.MagicMock()
    widget.model.document.load_failed = False
    mocker.patch("rehuco_agent.main_window.DocumentsDock.open_folder", return_value=widget)
    window = MainWindow()
    qtbot.addWidget(window)

    window.open_folder("a_folder")

    recent_files = window._MainWindow__recent_files  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert recent_files.newest_first() == [Path("a_folder").resolve()]


def test_open_folder_does_not_record_a_failed_open(mocker: MockerFixture, qtbot: QtBot) -> None:
    """An ``open_folder`` whose resource could not be read (a load-failure stub) is not recorded into
    ``Open recents`` (#64, [[data-model#write-integrity]]).

    **Test steps:**

    * mock ``DocumentsDock.open_folder`` to return a load-failure stub widget (``load_failed`` True, e.g.
      an unreadable ``info.rehu``)
    * call ``open_folder``
    * verify ``Open recents`` stays empty
    """
    widget = mocker.MagicMock()
    widget.model.document.load_failed = True
    mocker.patch("rehuco_agent.main_window.DocumentsDock.open_folder", return_value=widget)
    window = MainWindow()
    qtbot.addWidget(window)

    window.open_folder("missing_folder")

    recent_files = window._MainWindow__recent_files  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert recent_files.newest_first() == []


def test_open_archive_records_a_successful_open_into_recents(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A successful ``open_archive`` records the resolved path into ``Open recents`` (#64).

    **Test steps:**

    * mock ``DocumentsDock.open_archive`` to return a genuinely-loaded widget (``load_failed`` False)
    * call ``open_archive``
    * verify the resolved path is now the newest recent entry
    """
    widget = mocker.MagicMock()
    widget.model.document.load_failed = False
    mocker.patch("rehuco_agent.main_window.DocumentsDock.open_archive", return_value=widget)
    window = MainWindow()
    qtbot.addWidget(window)

    window.open_archive("a.zip")

    recent_files = window._MainWindow__recent_files  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert recent_files.newest_first() == [Path("a.zip").resolve()]


def test_open_archive_does_not_record_a_failed_open(mocker: MockerFixture, qtbot: QtBot) -> None:
    """An ``open_archive`` whose companion could not be read (a load-failure stub) is not recorded into
    ``Open recents`` (#64, [[data-model#write-integrity]]).

    **Test steps:**

    * mock ``DocumentsDock.open_archive`` to return a load-failure stub widget (``load_failed`` True, e.g.
      an unreadable companion)
    * call ``open_archive``
    * verify ``Open recents`` stays empty
    """
    widget = mocker.MagicMock()
    widget.model.document.load_failed = True
    mocker.patch("rehuco_agent.main_window.DocumentsDock.open_archive", return_value=widget)
    window = MainWindow()
    qtbot.addWidget(window)

    window.open_archive("missing.zip")

    recent_files = window._MainWindow__recent_files  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert recent_files.newest_first() == []


def test_open_rehu_action_opens_the_chosen_file(mocker: MockerFixture, qtbot: QtBot) -> None:
    """``File > Open rehu...`` opens whatever file the user picks (#64).

    **Test steps:**

    * mock the file-open dialog to report a chosen path
    * trigger ``open_rehu_action``
    * verify ``open_file`` was called with that path
    """
    mocker.patch("rehuco_agent.main_window.QFileDialog.getOpenFileName", return_value=("picked.rehu", ""))
    window = MainWindow()
    qtbot.addWidget(window)
    open_file = mocker.patch.object(window, "open_file")

    window._MainWindow__ui.open_rehu_action.trigger()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    open_file.assert_called_once_with("picked.rehu")


def test_open_rehu_action_does_nothing_when_dialog_is_cancelled(mocker: MockerFixture, qtbot: QtBot) -> None:
    """``File > Open rehu...`` does nothing when the dialog is cancelled (#64).

    **Test steps:**

    * mock the file-open dialog to report no chosen path (cancelled)
    * trigger ``open_rehu_action``
    * verify ``open_file`` was never called
    """
    mocker.patch("rehuco_agent.main_window.QFileDialog.getOpenFileName", return_value=("", ""))
    window = MainWindow()
    qtbot.addWidget(window)
    open_file = mocker.patch.object(window, "open_file")

    window._MainWindow__ui.open_rehu_action.trigger()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    open_file.assert_not_called()


def test_open_folder_action_opens_the_chosen_folder(mocker: MockerFixture, qtbot: QtBot) -> None:
    """``File > Open folder...`` opens whatever folder the user picks (#64).

    **Test steps:**

    * mock the folder-picker dialog to report a chosen path
    * trigger ``open_folder_action``
    * verify ``open_folder`` was called with that path
    """
    mocker.patch("rehuco_agent.main_window.QFileDialog.getExistingDirectory", return_value="picked_folder")
    window = MainWindow()
    qtbot.addWidget(window)
    open_folder = mocker.patch.object(window, "open_folder")

    window._MainWindow__ui.open_folder_action.trigger()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    open_folder.assert_called_once_with("picked_folder")


def test_open_folder_action_does_nothing_when_dialog_is_cancelled(mocker: MockerFixture, qtbot: QtBot) -> None:
    """``File > Open folder...`` does nothing when the dialog is cancelled (#64).

    **Test steps:**

    * mock the folder-picker dialog to report no chosen path (cancelled)
    * trigger ``open_folder_action``
    * verify ``open_folder`` was never called
    """
    mocker.patch("rehuco_agent.main_window.QFileDialog.getExistingDirectory", return_value="")
    window = MainWindow()
    qtbot.addWidget(window)
    open_folder = mocker.patch.object(window, "open_folder")

    window._MainWindow__ui.open_folder_action.trigger()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    open_folder.assert_not_called()


def test_open_companion_action_opens_the_chosen_archive(mocker: MockerFixture, qtbot: QtBot) -> None:
    """``File > Open companion...`` opens whatever archive the user picks (#64).

    **Test steps:**

    * mock the file-open dialog to report a chosen path
    * trigger ``open_companion_action``
    * verify ``open_archive`` was called with that path
    """
    mocker.patch("rehuco_agent.main_window.QFileDialog.getOpenFileName", return_value=("picked.zip", ""))
    window = MainWindow()
    qtbot.addWidget(window)
    open_archive = mocker.patch.object(window, "open_archive")

    window._MainWindow__ui.open_companion_action.trigger()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    open_archive.assert_called_once_with("picked.zip")


def test_open_companion_action_does_nothing_when_dialog_is_cancelled(mocker: MockerFixture, qtbot: QtBot) -> None:
    """``File > Open companion...`` does nothing when the dialog is cancelled (#64).

    **Test steps:**

    * mock the file-open dialog to report no chosen path (cancelled)
    * trigger ``open_companion_action``
    * verify ``open_archive`` was never called
    """
    mocker.patch("rehuco_agent.main_window.QFileDialog.getOpenFileName", return_value=("", ""))
    window = MainWindow()
    qtbot.addWidget(window)
    open_archive = mocker.patch.object(window, "open_archive")

    window._MainWindow__ui.open_companion_action.trigger()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    open_archive.assert_not_called()


def test_save_all_action_saves_only_dirty_open_documents(mocker: MockerFixture, qtbot: QtBot) -> None:
    """``File > Save all`` saves every dirty document, reusing #41's per-document save, and leaves
    clean ones alone (#64).

    **Test steps:**

    * stand in one dirty and one clean open document model
    * mock the unsaved-changes dialog so qtbot's teardown-close doesn't block on a real modal for
      the still-dirty stand-in
    * trigger ``save_all_action``
    * verify only the dirty model was saved
    """
    window = MainWindow()
    qtbot.addWidget(window)
    dirty, clean = mocker.MagicMock(dirty=True), mocker.MagicMock(dirty=False)
    mocker.patch.object(window._MainWindow__documents_dock, "open_document_models", return_value=[dirty, clean])  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    mocker.patch(UNSAVED_CHANGES_DIALOG)

    window._MainWindow__ui.save_all_action.trigger()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    dirty.save.assert_called_once_with()
    clean.save.assert_not_called()


def test_save_all_shows_a_critical_dialog_when_a_save_fails(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A ``Save all`` whose per-document save raises ``OSError`` (an offline mount, #146) surfaces a
    critical dialog rather than aborting the sweep with a traceback.

    **Test steps:**

    * stand in one dirty open document whose ``save`` raises ``OSError``
    * mock the critical dialog to answer Cancel, and the unsaved-changes dialog for teardown
    * trigger ``save_all_action``
    * verify the critical dialog was shown
    """
    window = MainWindow()
    qtbot.addWidget(window)
    dirty = mocker.MagicMock(dirty=True, label="doc.rehu")
    dirty.save.side_effect = OSError("offline mount")
    mocker.patch.object(window._MainWindow__documents_dock, "open_document_models", return_value=[dirty])  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    mocker.patch(UNSAVED_CHANGES_DIALOG)
    critical = mocker.patch.object(QMessageBox, "critical", return_value=QMessageBox.StandardButton.Cancel)

    window._MainWindow__ui.save_all_action.trigger()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    critical.assert_called_once()


def test_sweep_checksums_action_queues_a_sweep_over_the_chosen_folder(mocker: MockerFixture, qtbot: QtBot) -> None:
    """``File > Sweep checksums...`` queues one sweep carrying the settings it resolved (#242).

    **Test steps:**

    * configure the checksum settings and mock the folder picker to report a chosen folder
    * trigger ``sweep_checksums_action``
    * verify one `SweepChecksumsJob` was enqueued carrying every resolved choice
    """
    settings = shared_checksum_settings()
    settings.algorithm = "crc32"
    settings.migrate_on_verify = True
    settings.create_missing_on_verify = True
    settings.stale_days = 30
    mocker.patch("rehuco_agent.main_window.QFileDialog.getExistingDirectory", return_value=str(SWEEP_ROOT))
    built = mocker.patch("rehuco_agent.main_window.SweepChecksumsJob", wraps=SweepChecksumsJob)
    window = MainWindow()
    qtbot.addWidget(window)

    window._MainWindow__ui.sweep_checksums_action.trigger()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    queue = window._MainWindow__task_queue  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert [status.source for status in queue.jobs()] == [SWEEP_ROOT]
    assert built.call_args.args == (SWEEP_ROOT,)
    assert built.call_args.kwargs["algorithm"] == "crc32"
    assert built.call_args.kwargs["migrate_to"] == "crc32"
    assert built.call_args.kwargs["create_if_missing"] is True
    assert built.call_args.kwargs["stale_after"] == timedelta(days=30)


def test_sweep_checksums_action_remembers_the_folder_it_was_pointed_at(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A catalog is swept repeatedly, so re-navigating to it every time is the whole friction (#242).

    **Test steps:**

    * record a previously swept folder, then mock the picker and trigger the action
    * verify the dialog was seeded with the remembered folder and the new one replaced it
    """
    shared_checksum_settings().last_sweep_root = "/fake/elsewhere"
    dialog = mocker.patch("rehuco_agent.main_window.QFileDialog.getExistingDirectory", return_value=str(SWEEP_ROOT))
    window = MainWindow()
    qtbot.addWidget(window)

    window._MainWindow__ui.sweep_checksums_action.trigger()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    assert dialog.call_args.args[2] == "/fake/elsewhere"
    assert shared_checksum_settings().last_sweep_root == str(SWEEP_ROOT)
    window._MainWindow__task_queue.pause()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def test_sweep_checksums_action_does_nothing_when_dialog_is_cancelled(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A cancelled chooser must neither queue work nor overwrite the remembered folder (#242).

    **Test steps:**

    * mock the folder picker to report no chosen path
    * trigger ``sweep_checksums_action``
    * verify nothing was queued and the remembered folder is unchanged
    """
    shared_checksum_settings().last_sweep_root = "/fake/elsewhere"
    mocker.patch("rehuco_agent.main_window.QFileDialog.getExistingDirectory", return_value="")
    window = MainWindow()
    qtbot.addWidget(window)

    window._MainWindow__ui.sweep_checksums_action.trigger()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    assert window._MainWindow__task_queue.jobs() == ()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert shared_checksum_settings().last_sweep_root == "/fake/elsewhere"


def test_sweeping_the_same_folder_twice_does_not_queue_it_twice(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Asking twice is not asking again -- the same rule the document actions follow (#204).

    **Test steps:**

    * hold the first sweep inside its run, then trigger the action twice over the same folder
    * verify only one row was added
    """
    mocker.patch("rehuco_agent.main_window.QFileDialog.getExistingDirectory", return_value=str(SWEEP_ROOT))
    mocker.patch.object(SweepChecksumsJob, "validate", return_value=None)
    release = Event()
    mocker.patch.object(SweepChecksumsJob, "run", side_effect=lambda _control: release.wait(SWEEP_TIMEOUT))
    window = MainWindow()
    qtbot.addWidget(window)

    try:
        window._MainWindow__ui.sweep_checksums_action.trigger()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
        window._MainWindow__ui.sweep_checksums_action.trigger()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    finally:
        release.set()

    queue = window._MainWindow__task_queue  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert len(queue.jobs()) == 1


def test_import_legacy_catalog_action_opens_the_wizard_over_the_unknown_identity(
    mocker: MockerFixture, qtbot: QtBot
) -> None:
    """``File > Import Legacy Catalog...`` opens the wizard filed under the unknown identity (#109,
    #192), the same rule an in-app `.tc` open already follows.

    **Test steps:**

    * mock the wizard class and the identity settings
    * trigger ``import_legacy_catalog_action``
    * verify the wizard was built over the app-wide queue and the unknown username, and shown modally
    """
    shared_identity_settings().unknown_username = "legacy"
    wizard = mocker.MagicMock()
    built = mocker.patch("rehuco_agent.main_window.ImportLegacyCatalogWizard", return_value=wizard)
    window = MainWindow()
    qtbot.addWidget(window)

    window._MainWindow__ui.import_legacy_catalog_action.trigger()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    built.assert_called_once_with(
        window._MainWindow__task_queue,  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
        username="legacy",
        parent=window,
    )
    wizard.exec.assert_called_once()


def test_conversion_backups_action_opens_the_manager(mocker: MockerFixture, qtbot: QtBot) -> None:
    """``File > Conversion Backups...`` opens the backups manager over the app-wide queue, wired to the
    documents dock's open-paths seam (#193, #246).

    Takes no identity, unlike the import wizard: reverting and discarding move and delete files and file
    them under nobody, so there are no per-user flags for an identity to belong to.

    **Test steps:**

    * mock the dialog class
    * trigger ``conversion_backups_action``
    * verify the dialog was built over the app-wide queue, the documents dock's ``open_paths`` and
      ``adopt_reverted_conversion``, and shown modally
    """
    dialog = mocker.MagicMock()
    built = mocker.patch("rehuco_agent.main_window.ConversionBackupsDialog", return_value=dialog)
    window = MainWindow()
    qtbot.addWidget(window)
    documents_dock = window._MainWindow__documents_dock  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    window._MainWindow__ui.conversion_backups_action.trigger()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    built.assert_called_once_with(
        window._MainWindow__task_queue,  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
        parent=window,
        open_paths=documents_dock.open_paths,
        on_reverted=documents_dock.adopt_reverted_conversion,
    )
    dialog.exec.assert_called_once()


def test_quit_action_closes_the_window(mocker: MockerFixture, qtbot: QtBot) -> None:
    """``File > Quit`` closes the window, letting the existing close guard take over (#64).

    **Test steps:**

    * mock ``close`` on the class, before construction -- the ``triggered`` signal is connected to
      ``self.close`` in ``__init__``, so patching only the already-constructed instance would leave
      that connection pointing at the original, real ``close``
    * trigger ``quit_action``
    * verify ``close`` was called
    """
    close = mocker.patch.object(MainWindow, "close")
    window = MainWindow()
    qtbot.addWidget(window)

    window._MainWindow__ui.quit_action.trigger()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    close.assert_called_once()


def test_settings_action_is_added_to_the_file_menu(qtbot: QtBot) -> None:
    """``File > Settings`` is its own action, distinct from the toolbar's settings-dock toggle (#64):
    sharing that one directly would carry its checked-state icon recoloring (built for a toolbar
    button's highlighted background) into a plain menu row, rendering it unreadable there.

    **Test steps:**

    * construct ``MainWindow``
    * verify ``settings_action`` is among ``file_menu``'s actions
    """
    window = MainWindow()
    qtbot.addWidget(window)

    ui = window._MainWindow__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert ui.settings_action in ui.file_menu.actions()


def test_settings_action_triggering_toggles_the_settings_dock(qtbot: QtBot) -> None:
    """Triggering ``File > Settings`` forwards to the real settings-dock toggle (#64).

    **Test steps:**

    * construct ``MainWindow`` and note the settings dock's initial visibility
    * trigger ``settings_action``
    * verify the dock's real toggle action's checked state flipped, and ``settings_action`` mirrors it
    """
    window = MainWindow()
    qtbot.addWidget(window)
    dock_manager = window._MainWindow__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    settings_dock = dock_manager.findDockWidget(SETTINGS_DIALOG_OBJECT_NAME)
    assert settings_dock is not None
    ui = window._MainWindow__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    before = settings_dock.toggleViewAction().isChecked()

    ui.settings_action.trigger()

    assert settings_dock.toggleViewAction().isChecked() != before
    assert ui.settings_action.isChecked() == settings_dock.toggleViewAction().isChecked()


def test_settings_action_reflects_the_dock_being_toggled_elsewhere(qtbot: QtBot) -> None:
    """``settings_action``'s checkmark stays in sync even when the dock's real toggle action fires
    some other way (e.g. the toolbar button) -- not just via this menu's own clicks (#64).

    **Test steps:**

    * construct ``MainWindow`` and trigger the settings dock's *real* toggle action directly
    * verify ``settings_action`` picked up the new checked state
    """
    window = MainWindow()
    qtbot.addWidget(window)
    dock_manager = window._MainWindow__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    settings_dock = dock_manager.findDockWidget(SETTINGS_DIALOG_OBJECT_NAME)
    assert settings_dock is not None
    ui = window._MainWindow__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    settings_dock.toggleViewAction().trigger()

    assert ui.settings_action.isChecked() == settings_dock.toggleViewAction().isChecked()


def test_file_menu_about_to_show_resyncs_settings_action_after_a_silent_dock_change(qtbot: QtBot) -> None:
    """``File``'s own ``aboutToShow`` force-corrects ``settings_action``'s checkmark even when the
    settings dock's visibility changed through ``toggleView()`` -- which updates the real toggle
    action's checked state *without* emitting ``toggled`` at all (confirmed empirically), the exact
    gap plain ``toggled``-based mirroring can't catch on its own (#64). ``DockableDialog``'s own
    ``restore_all``/``enforce_restore_on_start`` both change visibility this same silent way.

    **Test steps:**

    * construct ``MainWindow`` and find the settings dock
    * flip its visibility directly via ``toggleView()``, not through any action
    * emit ``file_menu.aboutToShow``
    * verify ``settings_action`` now matches the dock's real toggle state
    """
    window = MainWindow()
    qtbot.addWidget(window)
    dock_manager = window._MainWindow__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    settings_dock = dock_manager.findDockWidget(SETTINGS_DIALOG_OBJECT_NAME)
    assert settings_dock is not None
    ui = window._MainWindow__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    before = settings_dock.toggleViewAction().isChecked()

    settings_dock.toggleView(not before)
    ui.file_menu.aboutToShow.emit()

    assert ui.settings_action.isChecked() != before
    assert ui.settings_action.isChecked() == settings_dock.toggleViewAction().isChecked()


def test_quit_action_is_the_last_entry_in_the_file_menu(qtbot: QtBot) -> None:
    """``Quit`` is appended last to ``File``, after ``Settings`` (#64).

    **Test steps:**

    * construct ``MainWindow``
    * verify ``quit_action`` is the final action in ``file_menu``
    """
    window = MainWindow()
    qtbot.addWidget(window)

    ui = window._MainWindow__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert ui.file_menu.actions()[-1] is ui.quit_action


def test_recents_menu_lists_remembered_paths_newest_first(qtbot: QtBot) -> None:
    """``Open recents`` lists every remembered path, most-recently-opened first (#64).

    **Test steps:**

    * construct ``MainWindow`` and record two paths, oldest first
    * populate the recents menu
    * verify its entries read back newest first
    """
    window = MainWindow()
    qtbot.addWidget(window)
    recent_files = window._MainWindow__recent_files  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    older, newer = Path("older.rehu").resolve(), Path("newer.rehu").resolve()
    recent_files.record(older)
    recent_files.record(newer)

    window._MainWindow__populate_recents_menu()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    menu = window._MainWindow__ui.open_recents_menu  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    paths_shown = [action.defaultWidget().findChildren(QLabel)[1].text() for action in menu.actions()]
    assert paths_shown == [str(newer), str(older)]


def test_recents_menu_derives_the_title_the_same_way_as_a_document_label(qtbot: QtBot) -> None:
    """A recent ``info.rehu`` path shows its parent folder's name (trailing-slashed) as its title,
    the same ``info.rehu``-aware rule as :attr:`RehuDocumentModel.label` -- not the bare
    ``"info.rehu"`` filename (#64).

    **Test steps:**

    * record a directory-scoped ``info.rehu`` path and a plain ``.rehu`` path
    * populate the recents menu
    * verify each entry's title label reads the folder name / bare filename respectively
    """
    window = MainWindow()
    qtbot.addWidget(window)
    recent_files = window._MainWindow__recent_files  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    folder_path = (Path("some_folder") / "info.rehu").resolve()
    plain_path = Path("plain.rehu").resolve()
    recent_files.record(folder_path)
    recent_files.record(plain_path)

    window._MainWindow__populate_recents_menu()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    menu = window._MainWindow__ui.open_recents_menu  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    titles_shown = [action.defaultWidget().findChildren(QLabel)[0].text() for action in menu.actions()]
    assert titles_shown == ["plain.rehu", "some_folder/"]


def test_recents_menu_shows_a_disabled_placeholder_when_empty(qtbot: QtBot) -> None:
    """With nothing remembered, ``Open recents`` shows a single disabled placeholder entry (#64).

    **Test steps:**

    * construct ``MainWindow`` with nothing recorded
    * populate the recents menu
    * verify exactly one, disabled action is present
    """
    window = MainWindow()
    qtbot.addWidget(window)

    window._MainWindow__populate_recents_menu()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    menu = window._MainWindow__ui.open_recents_menu  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    actions = menu.actions()
    assert len(actions) == 1
    assert not actions[0].isEnabled()


def test_recents_menu_entry_triggering_opens_that_path(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Selecting a remembered path in ``Open recents`` reopens it via ``open_path`` (#64).

    **Test steps:**

    * construct ``MainWindow`` and record one path
    * populate the recents menu and trigger its single entry
    * verify ``open_path`` was called with that path
    """
    window = MainWindow()
    qtbot.addWidget(window)
    path = Path("remembered.rehu").resolve()
    window._MainWindow__recent_files.record(path)  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    open_path = mocker.patch.object(window, "open_path")

    window._MainWindow__populate_recents_menu()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    menu = window._MainWindow__ui.open_recents_menu  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    menu.actions()[0].trigger()

    open_path.assert_called_once_with(path)


def test_recents_menu_repopulates_on_every_show(qtbot: QtBot) -> None:
    """The recents menu is rebuilt fresh every time it's about to show, not just once (#64).

    **Test steps:**

    * construct ``MainWindow`` and emit the menu's ``aboutToShow`` with nothing recorded yet
    * record a path, then emit ``aboutToShow`` again
    * verify the menu now reflects the newly-recorded path
    """
    window = MainWindow()
    qtbot.addWidget(window)
    menu = window._MainWindow__ui.open_recents_menu  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    menu.aboutToShow.emit()
    assert len(menu.actions()) == 1
    assert not menu.actions()[0].isEnabled()

    path = Path("fresh.rehu").resolve()
    window._MainWindow__recent_files.record(path)  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    menu.aboutToShow.emit()

    paths_shown = [action.defaultWidget().findChildren(QLabel)[1].text() for action in menu.actions()]
    assert paths_shown == [str(path)]


def test_close_event_saves_recent_files(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Closing the app persists the recent-files list (#64).

    **Test steps:**

    * construct ``MainWindow``
    * mock ``RecentFilesSettings.save`` to detect the call
    * dispatch a close event
    * verify ``save`` was called once
    """
    window = MainWindow()
    qtbot.addWidget(window)
    save = mocker.patch.object(RecentFilesSettings, "save")
    event = QCloseEvent()

    window.closeEvent(event)

    save.assert_called_once()


def test_close_event_saves_the_settings_dialogs_filter_state(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Closing the app persists the settings dialog's filter text and toggles (#76).

    The dialog lives in a dock and never closes on its own, so this is the only moment its filter
    state is written.

    **Test steps:**

    * construct ``MainWindow``
    * mock ``SettingsDialog.save_filter_state`` to detect the call
    * dispatch a close event
    * verify ``save_filter_state`` was called once
    """
    window = MainWindow()
    qtbot.addWidget(window)
    save_filter_state = mocker.patch.object(SettingsDialog, "save_filter_state")
    event = QCloseEvent()

    window.closeEvent(event)

    save_filter_state.assert_called_once()


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
    dialog_class = mocker.patch(UNSAVED_CHANGES_DIALOG)
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
    mocker.patch(UNSAVED_CHANGES_DIALOG, return_value=dialog)
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
    mocker.patch(UNSAVED_CHANGES_DIALOG, return_value=dialog)
    event = QCloseEvent()

    window.closeEvent(event)

    assert not event.isAccepted()
    dirty_model.save.assert_not_called()


def test_close_event_still_persists_when_a_failing_save_is_retried(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A selected save that fails once then succeeds on Retry (a transient offline mount, #146) does
    **not** skip the window-state/session persistence -- the worst-case bug this fix closes.

    **Test steps:**

    * stand in one selected dirty model whose ``save`` raises ``OSError`` once then succeeds
    * mock the unsaved-changes dialog to accept and select it, and the critical dialog to answer Retry
    * mock ``MainWindowSettings.save`` to detect that persistence still ran
    * dispatch a close event
    * verify the save was retried, the close was accepted, and persistence ran
    """
    window = MainWindow()
    qtbot.addWidget(window)
    model = mocker.MagicMock(dirty=True, label="doc.rehu")

    # raise only on the first attempt, then succeed -- and tolerate any further calls (qtbot's
    # teardown-close re-runs the same guard), unlike a fixed-length list that would exhaust
    attempts = {"count": 0}

    def flaky_save() -> None:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise OSError("offline mount")

    model.save.side_effect = flaky_save
    mocker.patch.object(window._MainWindow__documents_dock, "open_document_models", return_value=[model])  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    dialog = mocker.MagicMock()
    dialog.exec.return_value = QDialog.DialogCode.Accepted
    dialog.selected_models.return_value = [model]
    mocker.patch(UNSAVED_CHANGES_DIALOG, return_value=dialog)
    mocker.patch.object(QMessageBox, "critical", return_value=QMessageBox.StandardButton.Retry)
    save = mocker.patch.object(MainWindowSettings, "save")
    event = QCloseEvent()

    window.closeEvent(event)

    assert model.save.call_count == 2
    assert event.isAccepted()
    save.assert_called_once()


def test_close_event_is_aborted_when_a_failing_save_is_cancelled(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Cancelling the retry/cancel dialog a failing save raises aborts the close: the window stays
    open, its edits and session intact, and persistence does not run (#146).

    **Test steps:**

    * stand in one selected dirty model whose ``save`` raises ``OSError``
    * mock the unsaved-changes dialog to accept and select it, and the critical dialog to answer Cancel
    * mock ``MainWindowSettings.save`` to detect whether persistence ran
    * dispatch a close event
    * verify the close was ignored and persistence never ran
    """
    window = MainWindow()
    qtbot.addWidget(window)
    model = mocker.MagicMock(dirty=True, label="doc.rehu")
    model.save.side_effect = OSError("offline mount")
    mocker.patch.object(window._MainWindow__documents_dock, "open_document_models", return_value=[model])  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    dialog = mocker.MagicMock()
    dialog.exec.return_value = QDialog.DialogCode.Accepted
    dialog.selected_models.return_value = [model]
    mocker.patch(UNSAVED_CHANGES_DIALOG, return_value=dialog)
    mocker.patch.object(QMessageBox, "critical", return_value=QMessageBox.StandardButton.Cancel)
    save = mocker.patch.object(MainWindowSettings, "save")
    event = QCloseEvent()

    window.closeEvent(event)

    assert not event.isAccepted()
    save.assert_not_called()


# region tray tests (#205)


def test_no_tray_icon_by_default(qtbot: QtBot) -> None:
    """With tray mode off (the default), a fresh window builds no `TrayIcon`.

    **Test steps:**

    * construct a real ``MainWindow``
    * verify no tray icon was built
    """
    window = MainWindow()
    qtbot.addWidget(window)

    assert window._MainWindow__tray_icon is None  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def test_tray_icon_built_at_startup_when_already_enabled(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A window built while tray mode is already on (and a tray is available) starts with its icon
    already in place, without waiting for the setting to change.

    **Test steps:**

    * mock tray availability as ``True`` and enable tray mode before constructing the window
    * verify a `TrayIcon` was built
    """
    mocker.patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=True)
    shared_tray_settings().enabled = True

    window = MainWindow()
    qtbot.addWidget(window)

    assert isinstance(window._MainWindow__tray_icon, TrayIcon)  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def test_a_redundant_enabled_notification_does_not_rebuild_an_existing_tray_icon(
    mocker: MockerFixture, qtbot: QtBot
) -> None:
    """The build guard is idempotent: an already-enabled icon is left exactly as it is, not replaced.

    ``SimpleProperty`` only notifies on an actual value change, so this shouldn't fire from a real
    setting toggle -- but the handler itself makes no such assumption, and this pins that it doesn't
    need to.

    **Test steps:**

    * build a window with tray mode already on (an icon exists)
    * call the handler again with ``enabled=True``
    * verify the same `TrayIcon` instance is still there, untouched
    """
    mocker.patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=True)
    shared_tray_settings().enabled = True
    window = MainWindow()
    qtbot.addWidget(window)
    icon = window._MainWindow__tray_icon  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    window._MainWindow__on_tray_enabled_changed(True)  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    assert window._MainWindow__tray_icon is icon  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def test_tray_icon_not_built_when_enabled_but_no_tray_is_available(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Tray mode turned on with no system tray available (bare Linux sessions, chiefly) refuses to
    engage: no `TrayIcon` is built at all.

    **Test steps:**

    * mock tray availability as ``False`` and enable tray mode before constructing the window
    * verify no `TrayIcon` was built
    """
    mocker.patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=False)
    shared_tray_settings().enabled = True

    window = MainWindow()
    qtbot.addWidget(window)

    assert window._MainWindow__tray_icon is None  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def test_tray_icon_created_live_when_the_setting_turns_on(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Turning tray mode on after the window already exists builds the icon immediately -- not just
    on the next launch, the same immediacy `MarkdownRenderingSettings` gives an open viewer.

    **Test steps:**

    * mock tray availability as ``True``
    * construct the window with tray mode off
    * turn tray mode on via the shared settings
    * verify a `TrayIcon` now exists
    """
    mocker.patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=True)
    window = MainWindow()
    qtbot.addWidget(window)
    assert window._MainWindow__tray_icon is None  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    shared_tray_settings().enabled = True

    assert isinstance(window._MainWindow__tray_icon, TrayIcon)  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def test_tray_icon_torn_down_live_when_the_setting_turns_off(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Turning tray mode back off tears the icon down immediately.

    **Test steps:**

    * mock tray availability as ``True`` and enable tray mode before constructing the window
    * turn tray mode off via the shared settings
    * verify no `TrayIcon` remains
    """
    mocker.patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=True)
    shared_tray_settings().enabled = True
    window = MainWindow()
    qtbot.addWidget(window)
    assert window._MainWindow__tray_icon is not None  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    shared_tray_settings().enabled = False

    assert window._MainWindow__tray_icon is None  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def test_close_event_hides_to_tray_instead_of_closing(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A plain window close (titlebar/Alt+F4 -- not ``File`` > ``Quit`` or the tray menu's own
    ``Quit``) hides the window to tray instead of running the guarded close, while tray mode is on.

    **Test steps:**

    * mock tray availability as ``True`` and enable tray mode before constructing the window
    * dispatch a close event directly (not through :meth:`MainWindow.request_quit`)
    * verify the event was ignored, the window was hidden, and nothing was persisted
    """
    mocker.patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=True)
    shared_tray_settings().enabled = True
    window = MainWindow()
    qtbot.addWidget(window)
    hide = mocker.patch.object(window, "hide")
    save = mocker.patch.object(MainWindowSettings, "save")
    event = QCloseEvent()

    window.closeEvent(event)

    assert not event.isAccepted()
    hide.assert_called_once_with()
    save.assert_not_called()


def test_close_event_quits_normally_when_no_tray_is_available(mocker: MockerFixture, qtbot: QtBot) -> None:
    """With tray mode on but no system tray available, closing still quits -- tray mode refuses to
    engage rather than leaving an unquittable app.

    **Test steps:**

    * mock tray availability as ``False`` and enable tray mode before constructing the window
    * mock ``open_document_models`` to return no dirty documents
    * dispatch a close event
    * verify the event was accepted (not hidden-to-tray)
    """
    mocker.patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=False)
    shared_tray_settings().enabled = True
    window = MainWindow()
    qtbot.addWidget(window)
    mocker.patch.object(window._MainWindow__documents_dock, "open_document_models", return_value=[])  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    event = QCloseEvent()

    window.closeEvent(event)

    assert event.isAccepted()


def test_request_quit_bypasses_tray_and_runs_the_guarded_close(mocker: MockerFixture, qtbot: QtBot) -> None:
    """``request_quit`` (``File`` > ``Quit``, or the tray menu's own ``Quit``) overrides tray mode's
    close-to-tray routing: the same guarded close a plain window close runs still runs, so
    persistence still happens.

    **Test steps:**

    * mock tray availability as ``True`` and enable tray mode before constructing the window
    * mock ``open_document_models`` to return no dirty documents, and ``QApplication.quit`` so the
      accepted close's explicit quit never reaches the test session's real application
    * call ``request_quit``
    * verify persistence ran (standing in for "the guarded close ran, not the tray hide")
    """
    mocker.patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=True)
    shared_tray_settings().enabled = True
    window = MainWindow()
    qtbot.addWidget(window)
    mocker.patch.object(window._MainWindow__documents_dock, "open_document_models", return_value=[])  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    mocker.patch.object(QApplication, "quit")
    save = mocker.patch.object(MainWindowSettings, "save")

    window.request_quit()

    save.assert_called_once()


def test_an_accepted_quit_tears_down_the_tray_and_quits_the_application(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A quit accepted while the tray icon exists ends with the icon torn down and an **explicit**
    ``QApplication.quit()`` -- a window hidden to tray is no longer a visible primary window, so
    closing it never fires Qt's own last-window-closed quit, and Quit from the tray menu would
    otherwise leave ``exec()`` running forever (#205).

    **Test steps:**

    * mock tray availability as ``True`` and enable tray mode before constructing the window
    * mock ``open_document_models`` to return no dirty documents, and spy on ``QApplication.quit``
    * call ``request_quit``
    * verify the tray icon is gone and the application was told to quit
    """
    mocker.patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=True)
    shared_tray_settings().enabled = True
    window = MainWindow()
    qtbot.addWidget(window)
    mocker.patch.object(window._MainWindow__documents_dock, "open_document_models", return_value=[])  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    quit_call = mocker.patch.object(QApplication, "quit")

    window.request_quit()

    assert window._MainWindow__tray_icon is None  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    quit_call.assert_called_once()


def test_quitting_from_the_tray_with_a_dirty_document_runs_the_save_prompt(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Quitting via ``request_quit`` (the tray menu's Quit) with a dirty document runs the same
    batch save prompt a window close does -- hiding to tray postpones the close guard, it never
    passes it (#205). A refusal leaves the window, its edits, and the tray icon exactly as they
    were, with nothing persisted.

    **Test steps:**

    * mock tray availability as ``True`` and enable tray mode before constructing the window
    * mock ``open_document_models`` to return a dirty model, and the dialog to be rejected (Cancel)
    * call ``request_quit``
    * verify the dialog was shown, nothing was persisted, and the tray icon survived
    """
    mocker.patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=True)
    shared_tray_settings().enabled = True
    window = MainWindow()
    qtbot.addWidget(window)
    dirty_model = mocker.MagicMock(dirty=True)
    mocker.patch.object(window._MainWindow__documents_dock, "open_document_models", return_value=[dirty_model])  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    dialog = mocker.MagicMock()
    dialog.exec.return_value = QDialog.DialogCode.Rejected
    dialog_class = mocker.patch(UNSAVED_CHANGES_DIALOG, return_value=dialog)
    save = mocker.patch.object(MainWindowSettings, "save")

    window.request_quit()

    dialog_class.assert_called_once()
    save.assert_not_called()
    assert window._MainWindow__tray_icon is not None  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def float_open_settings_dialog(window: MainWindow) -> Any:
    """Open the settings dialog as its own floating window, and return that container.

    The dialog is placed floating by default (#47), so opening it is all it takes -- but the
    container is read back through the dock rather than assumed, so these tests fail loudly if that
    default ever changes rather than silently asserting about ``None``.
    """
    dock_manager = window._MainWindow__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    dock = dock_manager.findDockWidget(SETTINGS_DIALOG_OBJECT_NAME)
    assert dock is not None
    dock.toggleView(True)
    container = dock.floatingDockContainer()
    assert container is not None, "the settings dialog is expected to open floating (#47)"
    return container


def test_hide_to_tray_hides_a_floating_dialog_with_the_window(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Hiding to tray takes every floating dock window with it: a floating dialog is its own
    top-level window, so it does not follow a plain ``hide()`` and would otherwise sit on screen
    with nothing behind it (#205).

    **Test steps:**

    * mock tray availability as ``True`` and enable tray mode before constructing the window
    * open the settings dialog as its own floating window
    * call ``hide_to_tray``
    * verify the window and the floating dialog are both hidden
    """
    mocker.patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=True)
    shared_tray_settings().enabled = True
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    container = float_open_settings_dialog(window)
    assert container.isVisible()

    window.hide_to_tray()

    assert window.isHidden()
    assert container.isVisible() is False


def test_hide_to_tray_leaves_the_dialog_logically_open(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A dialog hidden with the window stays *open* as far as its dock is concerned -- hidden, not
    closed -- so what gets persisted on a quit from the tray is the user's own choice rather than
    the tray's bookkeeping (#205).

    **Test steps:**

    * mock tray availability as ``True`` and enable tray mode before constructing the window
    * open the settings dialog floating, then hide to tray
    * verify its dock still reports itself open
    """
    mocker.patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=True)
    shared_tray_settings().enabled = True
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    float_open_settings_dialog(window)
    dock_manager = window._MainWindow__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    window.hide_to_tray()

    dock = dock_manager.findDockWidget(SETTINGS_DIALOG_OBJECT_NAME)
    assert dock is not None
    assert dock.isClosed() is False


def test_showing_from_the_tray_brings_back_the_dialog_hidden_with_the_window(
    mocker: MockerFixture, qtbot: QtBot
) -> None:
    """A dialog that was on screen when the window went to the tray comes back with it (#205).

    **Test steps:**

    * mock tray availability as ``True`` and enable tray mode before constructing the window
    * open the settings dialog floating, hide to tray, then show again
    * verify the window and the dialog are both back on screen
    """
    mocker.patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=True)
    shared_tray_settings().enabled = True
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    container = float_open_settings_dialog(window)
    window.hide_to_tray()

    window.raise_and_activate()

    assert window.isVisible()
    assert container.isVisible()


def test_showing_from_the_tray_leaves_a_closed_dialog_closed(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Only what was actually on screen comes back: a dialog the user had closed before hiding is
    not opened by returning from the tray (#205).

    **Test steps:**

    * mock tray availability as ``True`` and enable tray mode before constructing the window
    * leave the settings dialog closed, hide to tray, then show again
    * verify the dialog is still closed
    """
    mocker.patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=True)
    shared_tray_settings().enabled = True
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    dock_manager = window._MainWindow__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    dock = dock_manager.findDockWidget(SETTINGS_DIALOG_OBJECT_NAME)
    assert dock is not None
    dock.toggleView(False)

    window.hide_to_tray()
    window.raise_and_activate()

    assert dock.isClosed() is True


def test_close_to_tray_hides_a_floating_dialog_too(mocker: MockerFixture, qtbot: QtBot) -> None:
    """The window's own close button routes through the same hide, so closing to tray takes the
    floating dialogs with it -- not only the tray menu's Hide (#205).

    **Test steps:**

    * mock tray availability as ``True`` and enable tray mode before constructing the window
    * open the settings dialog floating
    * dispatch a close event (the titlebar close, not an explicit quit)
    * verify the close was ignored and the dialog went away with the window
    """
    mocker.patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=True)
    shared_tray_settings().enabled = True
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    container = float_open_settings_dialog(window)
    event = QCloseEvent()

    window.closeEvent(event)

    assert not event.isAccepted()
    assert window.isHidden()
    assert container.isVisible() is False


def test_the_tray_setting_lives_on_the_system_integration_page(qtbot: QtBot) -> None:
    """The tray checkbox is a block on the System Integration page rather than a category of its
    own (#205) -- what the window's close button does is system integration, and the page exists on
    every platform, so the setting is reachable from all of them.

    Asserted by title and by the checkbox's object name rather than by page class: which class fills
    that slot is per-platform (`RegistryPage`, `DesktopIntegrationPage`, `SystemIntegrationPage`),
    and what matters here is that whichever one this platform built carries the tray block.

    **Test steps:**

    * construct a real ``MainWindow``
    * find the registered page titled "System Integration"
    * verify it holds the tray checkbox
    """
    window = MainWindow()
    qtbot.addWidget(window)

    settings_dialog = window._MainWindow__settings_dialog  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    dialog_ui = settings_dialog._SettingsDialog__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    stacked = [dialog_ui.page_stack.widget(index) for index in range(dialog_ui.page_stack.count())]
    pages = [area.widget() for area in stacked if isinstance(area, QScrollArea)]
    system_integration = [
        page for page in pages if page is not None and getattr(page, "title", None) == "System Integration"
    ]

    assert len(system_integration) == 1, "every platform registers exactly one System Integration page"
    assert system_integration[0].findChild(QCheckBox, "enabled_check_box") is not None


# endregion


def test_restore_session_reopens_open_documents_and_restores_their_state(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A document the saved session marks open is reopened and has its dock layout restored.

    **Test steps:**

    * seed ``DocumentSessionSettings.load`` to report one open item (with known state bytes) and
      one closed item
    * mock ``DocumentsDock.open_document`` to return a stand-in widget
    * construct ``MainWindow``
    * verify ``open_document`` was called only for the open item's path, carrying that item's state
      (#62: the layout rides the open itself, so the dock applies exactly one layout per document)
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

    open_document.assert_called_once_with(open_path, state=b"state-bytes")


def test_restore_session_materializes_a_locked_dock_for_a_vanished_file(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A previously-open document whose file has since vanished still reopens on restore -- as a locked
    dock materialized in its place, its saved state applied ([[data-model#write-integrity]]) -- rather
    than being skipped or crashing the restore.

    **Test steps:**

    * seed one open item
    * mock ``open_document`` to return the (locked) dock it now yields for a file that can't be read
    * construct ``MainWindow`` and verify the open still carried the saved state to restore
    """
    path = Path("missing.rehu").resolve()

    def fake_load(self: DocumentSessionSettings, settings: object) -> None:
        del settings
        self.items[path] = DocumentSessionSettings.Item(open=True, state=b"state")  # pylint: disable=unsupported-assignment-operation

    mocker.patch.object(DocumentSessionSettings, "load", fake_load)
    widget = mocker.MagicMock()
    open_document = mocker.patch("rehuco_agent.main_window.DocumentsDock.open_document", return_value=widget)

    window = MainWindow()
    qtbot.addWidget(window)

    open_document.assert_called_once_with(path, state=b"state")


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


def test_close_event_skips_a_never_saved_document_when_snapshotting(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A brand-new document bound to a path but never written to disk is not snapshotted (#175).

    Restoring it would reopen via the load path and materialize a locked ``MISSING`` stub for a file
    that never existed, resurrecting edits the user discarded at the close guard (#147 semantics).

    **Test steps:**

    * dispatch a close event with one open widget reporting a path but ``model.saved_on_disk is False``
      (dirty, as a never-saved draft always is -- ``discard_unsaved_changes_on_close`` dismisses the
      close guard so the dispatch doesn't block on its modal)
    * verify the session gains no entry for it, and save still happens
    """
    discard_unsaved_changes_on_close(mocker)
    window = MainWindow()
    qtbot.addWidget(window)
    path = Path("never-saved.rehu").resolve()
    widget = mocker.MagicMock()
    widget.model = mocker.MagicMock(path=path, dirty=True, saved_on_disk=False)
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


def test_restore_session_refocuses_a_vanished_focused_documents_locked_dock(
    mocker: MockerFixture, qtbot: QtBot
) -> None:
    """A remembered focused document whose file has vanished is still re-focused -- its materialized
    locked dock is a real, focusable dock now ([[data-model#write-integrity]]), not a skipped nothing.

    **Test steps:**

    * seed the session with a focused-document path whose file can't be read
    * construct ``MainWindow``
    * verify ``open_document`` was called twice for that path: the initial open, then again to re-focus
      its locked dock
    """
    path = Path("missing.rehu").resolve()

    def fake_load(self: DocumentSessionSettings, settings: object) -> None:
        del settings
        self.items[path] = DocumentSessionSettings.Item(open=True, state=b"state")  # pylint: disable=unsupported-assignment-operation
        self.focused_path = path

    mocker.patch.object(DocumentSessionSettings, "load", fake_load)
    open_document = mocker.patch(
        "rehuco_agent.main_window.DocumentsDock.open_document", return_value=mocker.MagicMock()
    )

    window = MainWindow()
    qtbot.addWidget(window)

    assert open_document.call_args_list == [mocker.call(path, state=b"state"), mocker.call(path)]


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


def test_docks_menu_lists_open_documents_alphabetically_by_title(
    dock_entries: Callable[[MainWindow], list[Any]], mocker: MockerFixture, qtbot: QtBot
) -> None:
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

    window._MainWindow__add_open_documents(window._MainWindow__ui.view_menu)  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    dynamic_actions = dock_entries(window)
    titles = [action.defaultWidget().findChildren(QLabel)[0].text() for action in dynamic_actions]
    assert titles == ["alpha", "Bravo", "Charlie"]


def test_docks_menu_shows_a_disabled_placeholder_when_nothing_is_open(
    dock_entries: Callable[[MainWindow], list[Any]], qtbot: QtBot
) -> None:
    """With no documents open, the ``View`` menu shows a single disabled placeholder entry.

    **Test steps:**
    * construct ``MainWindow`` with nothing open
    * populate the docks menu
    * verify exactly one, disabled action is present
    """
    window = MainWindow()
    qtbot.addWidget(window)

    window._MainWindow__add_open_documents(window._MainWindow__ui.view_menu)  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    dynamic_actions = dock_entries(window)
    assert len(dynamic_actions) == 1
    assert not dynamic_actions[0].isEnabled()


def test_docks_menu_repopulates_on_every_show(
    dock_entries: Callable[[MainWindow], list[Any]], mocker: MockerFixture, qtbot: QtBot
) -> None:
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
    assert len(dock_entries(window)) == 1

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

    assert len(dock_entries(window)) == 2


def test_docks_menu_entry_triggering_focuses_that_document(
    dock_entries: Callable[[MainWindow], list[Any]], mocker: MockerFixture, qtbot: QtBot
) -> None:
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

    window._MainWindow__add_open_documents(window._MainWindow__ui.view_menu)  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    dock_entries(window)[0].trigger()

    focus_document.assert_called_once_with(widget)


def test_close_actions_are_grouped_below_close_in_the_file_menu(qtbot: QtBot) -> None:
    """``Close Missing Files`` and ``Close All`` sit right below ``Close`` in ``File``, in that
    order, and precede ``Save all`` (#96, moved from ``View`` by #247).

    **Test steps:**

    * construct ``MainWindow``
    * read ``File``'s actions in order
    * verify Close, Close Missing Files and Close All are adjacent, in that order, before Save all
    """
    window = MainWindow()
    qtbot.addWidget(window)
    ui = window._MainWindow__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    actions = ui.file_menu.actions()

    assert actions.index(ui.close_action) + 1 == actions.index(ui.close_missing_action)
    assert actions.index(ui.close_missing_action) + 1 == actions.index(ui.close_all_action)
    assert actions.index(ui.close_all_action) < actions.index(ui.save_all_action)


def test_close_all_action_shortcut_is_ctrl_shift_w(qtbot: QtBot) -> None:
    """``Close All`` (``File``, #247) carries ``Ctrl+Shift+W``.

    **Test steps:**

    * construct ``MainWindow``
    * verify ``close_all_action``'s shortcut
    """
    window = MainWindow()
    qtbot.addWidget(window)
    ui = window._MainWindow__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    assert ui.close_all_action.shortcut() == QKeySequence("Ctrl+Shift+W")


def test_close_all_action_is_enabled_iff_a_document_is_open(mocker: MockerFixture, qtbot: QtBot) -> None:
    """``Close All`` (``File``, moved from ``View`` by #247) is enabled iff any document is open
    (#96), resynced fresh right before ``File`` shows -- the same laziness its old home in ``View``
    already relied on.

    **Test steps:**

    * construct ``MainWindow`` with nothing open and show ``File``
    * verify Close All is disabled
    * stand in one open document and show ``File`` again
    * verify Close All is now enabled
    """
    window = MainWindow()
    qtbot.addWidget(window)
    ui = window._MainWindow__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    documents_dock = window._MainWindow__documents_dock  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    mocker.patch.object(documents_dock, "open_document_widgets", return_value=[])

    ui.file_menu.aboutToShow.emit()
    assert not ui.close_all_action.isEnabled()

    widget = mocker.MagicMock(model=mocker.MagicMock(label="Solo", path=Path("/solo/info.rehu"), dirty=False))
    widget.save_state.return_value = b"snapshot"  # keeps teardown's implicit close() from choking on a MagicMock
    mocker.patch.object(documents_dock, "open_document_widgets", return_value=[widget])

    ui.file_menu.aboutToShow.emit()
    assert ui.close_all_action.isEnabled()


def test_close_missing_files_action_is_enabled_iff_a_document_is_missing(mocker: MockerFixture, qtbot: QtBot) -> None:
    """``Close Missing Files`` (``File``, moved from ``View`` by #247) is enabled iff
    ``DocumentsDock.has_missing_documents`` reports a missing document (#93, #96).

    **Test steps:**

    * construct ``MainWindow``, stand in no missing documents, and show ``File``
    * verify Close Missing Files is disabled
    * stand in a missing document and show ``File`` again
    * verify Close Missing Files is now enabled
    """
    window = MainWindow()
    qtbot.addWidget(window)
    ui = window._MainWindow__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    documents_dock = window._MainWindow__documents_dock  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    mocker.patch.object(documents_dock, "has_missing_documents", return_value=False)

    ui.file_menu.aboutToShow.emit()
    assert not ui.close_missing_action.isEnabled()

    mocker.patch.object(documents_dock, "has_missing_documents", return_value=True)

    ui.file_menu.aboutToShow.emit()
    assert ui.close_missing_action.isEnabled()


def test_close_all_action_triggering_delegates_to_the_documents_dock(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Triggering ``Close All`` delegates straight to ``DocumentsDock.close_all`` (#96).

    **Test steps:**

    * construct ``MainWindow``
    * mock ``DocumentsDock.close_all``
    * trigger ``close_all_action``
    * verify it was called
    """
    window = MainWindow()
    qtbot.addWidget(window)
    ui = window._MainWindow__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    documents_dock = window._MainWindow__documents_dock  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    close_all = mocker.patch.object(documents_dock, "close_all")
    ui.close_all_action.setEnabled(True)  # a disabled action's trigger() is a no-op; a document is open in practice

    ui.close_all_action.trigger()

    close_all.assert_called_once_with()


def test_close_missing_files_action_triggering_delegates_to_the_documents_dock(
    mocker: MockerFixture, qtbot: QtBot
) -> None:
    """Triggering ``Close Missing Files`` delegates straight to ``DocumentsDock.close_missing`` (#96).

    **Test steps:**

    * construct ``MainWindow``
    * mock ``DocumentsDock.close_missing``
    * trigger ``close_missing_action``
    * verify it was called
    """
    window = MainWindow()
    qtbot.addWidget(window)
    ui = window._MainWindow__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    documents_dock = window._MainWindow__documents_dock  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    close_missing = mocker.patch.object(documents_dock, "close_missing")
    ui.close_missing_action.setEnabled(True)  # a disabled action's trigger() is a no-op; a document would be missing

    ui.close_missing_action.trigger()

    close_missing.assert_called_once_with()


# region the app-wide log dock (#200)


def log_dock(window: MainWindow) -> Any:
    """Find the app-wide log dock on the outer manager.

    :param window: the window to read.
    :returns: the dock.
    """
    dock_manager = window._MainWindow__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    return dock_manager.findDockWidget(LOG_DOCK_OBJECT_NAME)


def task_queue_dock(window: MainWindow) -> Any:
    """Find the app-wide task queue dock on the outer manager (#202).

    :param window: the window to read.
    :returns: the dock.
    """
    dock_manager = window._MainWindow__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    return dock_manager.findDockWidget(TASK_QUEUE_DOCK_OBJECT_NAME)


def task_queue_status_indicator(window: MainWindow) -> TaskQueueStatusIndicator:
    """The status bar's own view of the task queue (#239).

    :param window: the window to read.
    :returns: the indicator.
    """
    return window._MainWindow__task_queue_status_indicator  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def log_messages(window: MainWindow) -> list[str]:
    """Read every message the app-wide log surface holds.

    :param window: the window to read.
    :returns: the messages, oldest first.
    """
    model = window.log_widget.model
    return [model.data(model.index(row, MESSAGE_COLUMN)) for row in range(model.rowCount())]


def test_installs_a_log_dock_on_the_outer_manager(qtbot: QtBot) -> None:
    """The log dock (#200) is registered on the *outer* manager, and hosts the app-wide log surface.

    Not on ``DocumentsDock``'s nested manager: it is a log of the app, not of any one document.

    **Test steps:**

    * construct a real ``MainWindow``
    * find the outer dock manager's registered dock named :data:`LOG_DOCK_OBJECT_NAME`
    * verify it exists, is placed, and hosts the window's ``log_widget``
    """
    window = MainWindow()
    qtbot.addWidget(window)

    dock = log_dock(window)

    assert dock is not None
    assert dock.dockAreaWidget() is not None
    assert isinstance(dock.widget(), LogWidget)
    assert window.log_widget is dock.widget()


def test_the_log_dock_starts_hidden(qtbot: QtBot) -> None:
    """A first run shows the resource being edited, not a log of having opened it (#200).

    **Test steps:**

    * construct a real ``MainWindow`` with nothing persisted
    * verify the log dock is closed and its toggle unchecked
    """
    window = MainWindow()
    qtbot.addWidget(window)

    dock = log_dock(window)

    assert dock.isClosed()
    assert not dock.toggleViewAction().isChecked()


def test_the_log_dock_toggle_sits_between_theme_and_settings_on_the_action_bar(qtbot: QtBot) -> None:
    """The log and task queue toggles are on the action bar, between the theme action and the settings
    dock's toggle -- in that order (#202 added the second one alongside the log's).

    **Test steps:**

    * construct a real ``MainWindow``
    * read the action bar's actions in order
    * verify both app-dock toggles sit between theme and settings, log before tasks
    """
    window = MainWindow()
    qtbot.addWidget(window)
    ui = window._MainWindow__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    dock_manager = window._MainWindow__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    settings_dock = dock_manager.findDockWidget(SETTINGS_DIALOG_OBJECT_NAME)

    actions = ui.action_bar.actions()
    log_toggle = log_dock(window).toggleViewAction()
    tasks_toggle = task_queue_dock(window).toggleViewAction()

    assert actions.index(ui.theme_action) < actions.index(log_toggle)
    assert actions.index(log_toggle) < actions.index(tasks_toggle)
    assert actions.index(tasks_toggle) < actions.index(settings_dock.toggleViewAction())


def test_the_log_dock_toggle_carries_a_themed_icon(qtbot: QtBot) -> None:
    """The toggle is themed from the log icon, so it follows a theme switch like every other dock's.

    **Test steps:**

    * construct a real ``MainWindow``
    * verify the log dock's toggle action carries an icon
    """
    window = MainWindow()
    qtbot.addWidget(window)

    assert not log_dock(window).toggleViewAction().icon().isNull()


def test_the_log_dock_toggle_is_in_the_view_menu_between_theme_and_the_documents(qtbot: QtBot) -> None:
    """The View menu lists ``log_action``/``tasks_action``, in that order, after the theme entries and
    before the open resources (#200, #202).

    Companions, not the docks' own ``toggleViewAction()``s: those carry the toolbar's checked-state
    color, unreadable against a menu row with no highlighted backdrop behind it -- see
    ``__add_log_dock``'s and ``__add_task_queue_dock``'s companion-wiring comments.

    **Test steps:**

    * construct a real ``MainWindow`` and rebuild the dynamic tail as ``aboutToShow`` would
    * verify both companions are in the menu, after the theme entries and before the first dynamic
      entry, log before tasks
    """
    window = MainWindow()
    qtbot.addWidget(window)
    ui = window._MainWindow__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    window._MainWindow__add_open_documents(ui.view_menu)  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    actions = ui.view_menu.actions()
    dynamic = window._MainWindow__dynamic_view_menu_actions  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    theme_titles = {"&Default", "&Light", "Dar&k"}

    assert ui.log_action in actions
    assert ui.tasks_action in actions
    last_theme = max(actions.index(action) for action in actions if action.text() in theme_titles)
    assert last_theme < actions.index(ui.log_action) < actions.index(ui.tasks_action)
    assert actions.index(ui.tasks_action) < min(actions.index(action) for action in dynamic)


def test_the_view_menu_toggle_shows_and_hides_the_log_dock(qtbot: QtBot) -> None:
    """Triggering the View menu's log entry opens the dock; triggering it again closes it (#200).

    The entry in the menu is ``log_action``, the companion -- its own ``triggered`` is wired straight
    to the dock's real toggle action's ``trigger()`` by ``ActionIconThemeHandler``, so this pins that
    the companion actually drives visibility, not merely that it sits in the right place.

    **Test steps:**

    * construct a real ``MainWindow`` and find ``log_action`` in the View menu
    * trigger it and verify the dock opened
    * trigger it again and verify the dock closed
    """
    window = MainWindow()
    qtbot.addWidget(window)
    ui = window._MainWindow__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    toggle = ui.log_action
    assert toggle in ui.view_menu.actions()

    toggle.trigger()
    assert not log_dock(window).isClosed()

    toggle.trigger()
    assert log_dock(window).isClosed()


def test_opening_the_log_dock_from_the_action_bar_checks_the_menu_companion_too(qtbot: QtBot) -> None:
    """``log_action`` (the View menu row) follows the real toggle action (the action bar button), not
    just the other way around -- the direction ``ActionIconThemeHandler`` wires via ``toggled``.

    **Test steps:**

    * construct a real ``MainWindow`` and trigger the action bar's own log toggle
    * verify the View menu's ``log_action`` reads checked too
    """
    window = MainWindow()
    qtbot.addWidget(window)
    ui = window._MainWindow__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    log_dock(window).toggleViewAction().trigger()

    assert not log_dock(window).isClosed()
    assert ui.log_action.isChecked()


def test_the_log_docks_visibility_survives_a_restart(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A log dock left open is open again on the next launch -- it rides the outer dock layout (#200).

    The other half of "state survives a restart": the filters have their own test above; this pins
    the visibility, which is the outer ``CDockManager``'s ``saveState()``'s to carry.

    **Test steps:**

    * construct a window, open its log dock, and capture the real window state it saves
    * construct a second window seeded (via a mocked ``load``) with that saved state
    * verify the second window's log dock starts open, unlike the hidden default
    """
    first = MainWindow()
    qtbot.addWidget(first)
    log_dock(first).toggleView(True)
    first._MainWindow__save_window_state()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    saved = first._MainWindow__window_settings  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    def fake_load(self: MainWindowSettings, settings: object) -> None:
        del settings
        self.outer_docks_state = saved.outer_docks_state

    mocker.patch.object(MainWindowSettings, "load", fake_load)

    second = MainWindow()
    qtbot.addWidget(second)

    assert not log_dock(second).isClosed()


def test_the_log_dock_replays_records_logged_before_it_was_ever_shown(qtbot: QtBot) -> None:
    """A record logged before there was a GUI is in the dock the first time it is opened.

    The whole point of the bridge caching: startup, the settings read and an early failure all happen
    before there is anything to show them.

    **Test steps:**

    * log a record through the shared bridge before building the window
    * construct a real ``MainWindow`` and reveal its log dock
    * verify the record is in the surface
    """
    bridge = shared_log_bridge()
    logger = logging.getLogger("rehuco_agent.tests.main_window_log_dock")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.addHandler(bridge)
    try:
        logger.warning("logged before the window existed")

        window = MainWindow()
        qtbot.addWidget(window)
        log_dock(window).toggleView(True)

        assert "logged before the window existed" in log_messages(window)
    finally:
        logger.removeHandler(bridge)


def test_the_log_surface_takes_its_limit_from_the_settings(qtbot: QtBot) -> None:
    """The app-wide surface is capped at the configured app limit, not the library's default.

    **Test steps:**

    * set the app limit before the window is built
    * construct a real ``MainWindow``
    * verify the surface took it
    """
    shared_logs_settings().app_limit = 42

    window = MainWindow()
    qtbot.addWidget(window)

    assert window.log_widget.limit == 42


def test_changing_the_app_limit_re_caps_the_open_log_surface(qtbot: QtBot) -> None:
    """A limit lowered in the settings dialog reaches a dock already open and scrolled back.

    **Test steps:**

    * construct a real ``MainWindow``
    * change the shared app limit
    * verify the surface and the bridge both re-capped
    """
    window = MainWindow()
    qtbot.addWidget(window)

    shared_logs_settings().app_limit = 17

    assert window.log_widget.limit == 17
    assert shared_log_bridge().limit == 17


def test_close_event_saves_the_log_surfaces_filters(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Closing the app saves which bands the log dock was showing, and what it was searching for.

    **Test steps:**

    * construct ``MainWindow``
    * mock ``MainWindowSettings.save`` and dispatch a close event
    * verify a non-empty log widget state was recorded
    """
    window = MainWindow()
    qtbot.addWidget(window)
    save = mocker.patch.object(MainWindowSettings, "save")
    event = QCloseEvent()

    window.closeEvent(event)

    window_settings = window._MainWindow__window_settings  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert window_settings.log_widget_state != b""
    save.assert_called_once()


def test_the_log_surfaces_filters_are_restored_on_start(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A restart brings the log dock back under the filters it was left with.

    **Test steps:**

    * save a state with the debug band hidden and a search typed
    * seed ``MainWindowSettings.load`` with it and construct a window
    * verify both came back
    """
    source = MainWindow()
    qtbot.addWidget(source)
    source_ui = source.log_widget._LogWidget__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access
    source_ui.show_debugs_action.setChecked(False)
    source_ui.search_edit.setText("a search")
    saved = source.log_widget.save_state()

    def fake_load(self: MainWindowSettings, settings: object) -> None:
        del settings
        self.log_widget_state = saved

    mocker.patch.object(MainWindowSettings, "load", fake_load)

    window = MainWindow()
    qtbot.addWidget(window)

    restored_ui = window.log_widget._LogWidget__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert not restored_ui.show_debugs_action.isChecked()
    assert restored_ui.search_edit.text() == "a search"


def test_registers_the_logs_page(qtbot: QtBot) -> None:
    """The Logs settings page (#200) is registered top-level, not under "Plugins".

    How much log to keep is about the app itself, and a reader looking for it has no plugin name to
    guess.

    **Test steps:**

    * construct a real ``MainWindow``
    * verify the settings dialog's page stack holds a ``LogsPage``
    """
    window = MainWindow()
    qtbot.addWidget(window)

    settings_dialog = window._MainWindow__settings_dialog  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    dialog_ui = settings_dialog._SettingsDialog__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    stacked = [dialog_ui.page_stack.widget(index) for index in range(dialog_ui.page_stack.count())]
    pages = [area.widget() for area in stacked if isinstance(area, QScrollArea)]
    assert any(isinstance(page, LogsPage) for page in pages)


# endregion


# region the app-wide task queue dock (#202)


def test_installs_a_task_queue_dock_on_the_outer_manager(qtbot: QtBot) -> None:
    """The task queue dock is registered on the *outer* manager, hosting the window's task queue widget.

    **Test steps:**

    * construct a real ``MainWindow``
    * find the outer dock manager's registered dock named :data:`TASK_QUEUE_DOCK_OBJECT_NAME`
    * verify it exists, is placed, and hosts a ``TaskQueueWidget``
    """
    window = MainWindow()
    qtbot.addWidget(window)

    dock = task_queue_dock(window)

    assert dock is not None
    assert dock.dockAreaWidget() is not None
    assert isinstance(dock.widget(), TaskQueueWidget)


def test_the_task_queue_dock_starts_hidden(qtbot: QtBot) -> None:
    """A first run does not show an empty queue (#202, mirroring the log dock's #200 default).

    **Test steps:**

    * construct a real ``MainWindow`` with nothing persisted
    * verify the task queue dock is closed and its toggle unchecked
    """
    window = MainWindow()
    qtbot.addWidget(window)

    dock = task_queue_dock(window)

    assert dock.isClosed()
    assert not dock.toggleViewAction().isChecked()


def test_the_task_queue_dock_toggle_carries_a_themed_icon(qtbot: QtBot) -> None:
    """The toggle is themed from the task-view icon, so it follows a theme switch like every dock's.

    **Test steps:**

    * construct a real ``MainWindow``
    * verify the task queue dock's toggle action carries an icon
    """
    window = MainWindow()
    qtbot.addWidget(window)

    assert not task_queue_dock(window).toggleViewAction().icon().isNull()


def test_the_view_menu_toggle_shows_and_hides_the_task_queue_dock(qtbot: QtBot) -> None:
    """Triggering the View menu's task queue entry (``tasks_action``, the companion) opens the dock;
    triggering it again closes it.

    **Test steps:**

    * construct a real ``MainWindow`` and find ``tasks_action`` in the View menu
    * trigger it and verify the dock opened
    * trigger it again and verify the dock closed
    """
    window = MainWindow()
    qtbot.addWidget(window)
    ui = window._MainWindow__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    toggle = ui.tasks_action
    assert toggle in ui.view_menu.actions()

    toggle.trigger()
    assert not task_queue_dock(window).isClosed()

    toggle.trigger()
    assert task_queue_dock(window).isClosed()


def test_opening_the_task_queue_dock_from_the_action_bar_checks_the_menu_companion_too(qtbot: QtBot) -> None:
    """``tasks_action`` follows the real toggle action, the same direction pinned for the log dock.

    **Test steps:**

    * construct a real ``MainWindow`` and trigger the action bar's own task queue toggle
    * verify the View menu's ``tasks_action`` reads checked too
    """
    window = MainWindow()
    qtbot.addWidget(window)
    ui = window._MainWindow__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    task_queue_dock(window).toggleViewAction().trigger()

    assert not task_queue_dock(window).isClosed()
    assert ui.tasks_action.isChecked()


class GatedJob(TaskJobBase):
    """A job that reports once, then blocks until released -- the window's own queue is real here,
    the same discipline ``tests/tasks/test_task_queue_widget.py`` uses (#239).

    :param label: the job's label.
    """

    def __init__(self, label: str) -> None:
        super().__init__()
        self.label = label
        self.entered: Final = Event()
        self.__proceed: Final = Event()

    def run(self, control: JobControl) -> None:
        control.report(1, 1)
        self.entered.set()
        self.__proceed.wait(GATE_TIMEOUT)

    def let_finish(self) -> None:
        """Release the block, letting ``run`` return."""
        self.__proceed.set()


def test_the_task_queue_status_indicator_sits_on_the_status_bar_hidden_by_default(qtbot: QtBot) -> None:
    """The queue's status bar surface (#239) exists from construction and starts hidden, mirroring the
    dock's own default: an empty queue is nothing to interrupt a reader for.

    **Test steps:**

    * construct a real ``MainWindow`` with nothing enqueued
    * verify the indicator is a permanent widget on the status bar, and hidden

    Read off :meth:`~PySide6.QtWidgets.QWidget.isHidden`, not ``isVisible()``: none of these tests
    ``show()`` the window, and ``isVisible()`` answers for the whole ancestor chain -- it would read
    ``False`` here regardless of what the indicator itself was told, which is exactly the bit under
    test. ``isHidden()`` is this widget's own explicit shown/hidden state alone.
    """
    window = MainWindow()
    qtbot.addWidget(window)

    indicator = task_queue_status_indicator(window)

    assert indicator in window.statusBar().findChildren(TaskQueueStatusIndicator)
    assert indicator.isHidden()


def test_the_task_queue_status_indicator_follows_the_queue_while_its_dock_stays_closed(
    qtbot: QtBot,
) -> None:
    """A queue running with its dock closed is not mistaken for an idle app (#239) -- the whole point
    of the indicator.

    **Test steps:**

    * construct a real ``MainWindow`` and enqueue a job without opening the task queue dock
    * verify the indicator shows once the job starts running, and names it
    * finish the job and verify the indicator hides again

    The job is run to completion before the test returns -- an unfinished, non-persistable job still
    in the queue when the window closes at teardown pops the real quit-time
    :meth:`~MainWindow._MainWindow__confirm_task_queue_loss` warning dialog, which nothing here would
    ever answer.
    """
    window = MainWindow()
    qtbot.addWidget(window)
    queue = window._MainWindow__task_queue  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    indicator = task_queue_status_indicator(window)
    assert task_queue_dock(window).isClosed()

    job = GatedJob("importing")
    queue.enqueue(job)
    assert job.entered.wait(SWEEP_TIMEOUT)
    # entered.wait only confirms the worker thread reached the job -- the state change still has to
    # cross to the GUI thread through the queue's own marshalling before the indicator reacts, so a
    # fixed sleep races that hop under load; wait for the actual effect instead
    qtbot.waitUntil(lambda: not indicator.isHidden(), timeout=WAIT_TIMEOUT_MS)

    assert task_queue_dock(window).isClosed()
    assert "importing" in indicator.text()

    job.let_finish()
    qtbot.waitUntil(indicator.isHidden, timeout=WAIT_TIMEOUT_MS)


def test_clicking_the_task_queue_status_indicator_opens_the_dock(qtbot: QtBot) -> None:
    """Clicking the indicator reveals the dock it stands in for.

    **Test steps:**

    * construct a real ``MainWindow`` and enqueue a job, so the indicator is visible and clickable
    * click it
    * verify the task queue dock opened

    Finishes the job and pumps once more before returning, the same reason
    :func:`test_the_task_queue_status_indicator_follows_the_queue_while_its_dock_stays_closed` does --
    an unfinished job left behind at teardown pops a real, unanswered warning dialog.
    """
    window = MainWindow()
    qtbot.addWidget(window)
    queue = window._MainWindow__task_queue  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    indicator = task_queue_status_indicator(window)

    job = GatedJob("importing")
    queue.enqueue(job)
    assert job.entered.wait(SWEEP_TIMEOUT)
    # same cross-thread wait as test_the_task_queue_status_indicator_follows_the_queue_while_its_dock_stays_closed --
    # wait for the indicator to actually react rather than a fixed sleep
    qtbot.waitUntil(lambda: not indicator.isHidden(), timeout=WAIT_TIMEOUT_MS)
    assert task_queue_dock(window).isClosed()

    qtbot.mouseClick(indicator, Qt.MouseButton.LeftButton)

    assert not task_queue_dock(window).isClosed()

    job.let_finish()
    qtbot.waitUntil(indicator.isHidden, timeout=WAIT_TIMEOUT_MS)


def test_the_image_previews_toggle_is_in_the_view_menu_checked_by_default(qtbot: QtBot) -> None:
    """``image_previews_action`` sits in the View menu, checked from the start, on ``Ctrl+Shift+``
    (grave accent, #71).

    **Test steps:**

    * construct a real ``MainWindow``
    * verify the action is in the View menu, checked, and bound to ``Ctrl+Shift+`` (grave accent)
    """
    window = MainWindow()
    qtbot.addWidget(window)
    ui = window._MainWindow__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    assert ui.image_previews_action in ui.view_menu.actions()
    assert ui.image_previews_action.isChecked()
    assert ui.image_previews_action.shortcut() == QKeySequence("Ctrl+Shift+`")


def test_the_image_previews_shortcut_is_application_wide(qtbot: QtBot) -> None:
    """The toggle's shortcut fires from anywhere in the app, not only while the main window itself is
    the active window (#71).

    A torn-out QtAds dock is a genuine top-level window of its own, so the default ``WindowShortcut``
    context (scoped to whichever window the action's own widget belongs to) would go deaf to the
    ``Ctrl+Shift+`` grave-accent shortcut the moment a floated dock had the keyboard instead of the
    main window.

    **Test steps:**

    * construct a real ``MainWindow``
    * verify the action's shortcut context is ``ApplicationShortcut``
    """
    window = MainWindow()
    qtbot.addWidget(window)
    ui = window._MainWindow__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    assert ui.image_previews_action.shortcutContext() == Qt.ShortcutContext.ApplicationShortcut


def test_toggling_image_previews_off_hides_every_open_documents_strip(qtbot: QtBot) -> None:
    """Unchecking ``image_previews_action`` hides every open document's preview strip at once (#71).

    Goes through the shared, reactive ``ImageViewerSettings`` singleton rather than a dock of its own,
    so this pins the toggle's real effect rather than merely its own checked state.

    **Test steps:**

    * construct a real ``MainWindow`` and untoggle ``image_previews_action``
    * verify the shared settings' ``previews_visible`` followed
    * toggle it back on and verify it followed again
    """
    window = MainWindow()
    qtbot.addWidget(window)
    ui = window._MainWindow__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    ui.image_previews_action.trigger()
    assert shared_image_viewer_settings().previews_visible is False

    ui.image_previews_action.trigger()
    assert shared_image_viewer_settings().previews_visible is True


def test_the_image_previews_toggle_button_sits_right_below_theme_on_the_action_bar(qtbot: QtBot) -> None:
    """``image_previews_toggle_action`` -- the toolbar primary -- sits directly after ``theme_action``,
    ahead of the log toggle (#71).

    **Test steps:**

    * construct a real ``MainWindow``
    * read the action bar's actions in order
    * verify the toggle sits between theme and the log dock's own toggle
    """
    window = MainWindow()
    qtbot.addWidget(window)
    ui = window._MainWindow__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    actions = ui.action_bar.actions()

    assert actions.index(ui.theme_action) < actions.index(ui.image_previews_toggle_action)
    assert actions.index(ui.image_previews_toggle_action) < actions.index(log_dock(window).toggleViewAction())


def test_the_image_previews_toggle_button_carries_a_themed_icon(qtbot: QtBot) -> None:
    """The toolbar toggle is themed from the image-previews icon, so it follows a theme switch like
    every other action bar button (#71).

    **Test steps:**

    * construct a real ``MainWindow``
    * verify the toolbar toggle carries an icon
    """
    window = MainWindow()
    qtbot.addWidget(window)
    ui = window._MainWindow__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    assert not ui.image_previews_toggle_action.icon().isNull()


def test_toggling_the_action_bar_button_drives_the_shared_setting_and_the_menu_companion(qtbot: QtBot) -> None:
    """Clicking the toolbar toggle -- not just the View menu row -- hides every open document's
    preview strip, and the menu row's checked state follows along (#71).

    ``image_previews_toggle_action`` is the primary the setting is actually wired to;
    ``image_previews_action`` is its View-menu companion, kept in sync via
    ``ActionIconThemeHandler``'s own ``toggled`` mirroring.

    **Test steps:**

    * construct a real ``MainWindow`` and untoggle the toolbar button
    * verify the shared settings' ``previews_visible`` followed, and so did the menu companion
    * toggle it back on and verify both followed again
    """
    window = MainWindow()
    qtbot.addWidget(window)
    ui = window._MainWindow__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    ui.image_previews_toggle_action.trigger()
    assert shared_image_viewer_settings().previews_visible is False
    assert not ui.image_previews_action.isChecked()

    ui.image_previews_toggle_action.trigger()
    assert shared_image_viewer_settings().previews_visible is True
    assert ui.image_previews_action.isChecked()


def test_toggling_image_previews_persists_the_choice(mock_persistent_settings: Any, qtbot: QtBot) -> None:
    """The toggle writes itself to storage as it is clicked, so it survives a restart (#71).

    It has no Apply button behind it and no settings page to be saved from, so the click is the only
    moment there is to record it.

    **Test steps:**

    * construct a real ``MainWindow`` and hide previews from the toolbar
    * verify the hidden choice was written out under its own key
    """
    window = MainWindow()
    qtbot.addWidget(window)
    ui = window._MainWindow__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    stored = mock_persistent_settings.return_value

    ui.image_previews_toggle_action.trigger()

    stored.setValue.assert_any_call(PREVIEWS_VISIBLE_KEY, False)


def test_a_launch_with_previews_hidden_opens_with_the_toggle_off(qtbot: QtBot) -> None:
    """A window built while previews are hidden opens with both surfaces already reading off (#71).

    The restore half of persistence: the ``.ui``'s own ``checked`` default says on, so a window that
    merely trusted it would show every strip again on the launch after the user hid them.

    **Test steps:**

    * hide previews before the window exists, then construct a real ``MainWindow``
    * verify the toolbar toggle and its View menu companion both open unchecked
    """
    shared_image_viewer_settings().previews_visible = False

    window = MainWindow()
    qtbot.addWidget(window)
    ui = window._MainWindow__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    assert not ui.image_previews_toggle_action.isChecked()
    assert not ui.image_previews_action.isChecked()


def test_the_task_queue_docks_visibility_survives_a_restart(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A task queue dock left open is open again on the next launch -- it rides the outer dock layout.

    **Test steps:**

    * construct a window, open its task queue dock, and capture the real window state it saves
    * construct a second window seeded (via a mocked ``load``) with that saved state
    * verify the second window's task queue dock starts open, unlike the hidden default
    """
    first = MainWindow()
    qtbot.addWidget(first)
    task_queue_dock(first).toggleView(True)
    first._MainWindow__save_window_state()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    saved = first._MainWindow__window_settings  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    def fake_load(self: MainWindowSettings, settings: object) -> None:
        del settings
        self.outer_docks_state = saved.outer_docks_state

    mocker.patch.object(MainWindowSettings, "load", fake_load)

    second = MainWindow()
    qtbot.addWidget(second)

    assert not task_queue_dock(second).isClosed()


def test_a_rename_makes_the_queue_re_read_its_job_sources(mocker: MockerFixture, qtbot: QtBot) -> None:
    """The window wires the coordinator's notification to the queue's re-read, so a job's row follows
    the resource it was working on (#241).

    The two halves are built and tested apart -- core never learns what a coordinator is -- so this is
    the one place the connection between them is a fact rather than an intention.

    **Test steps:**

    * mock the queue's re-read, then construct a real ``MainWindow``
    * rename through the window's coordinator, with the renamer itself mocked out
    * verify the queue was asked to re-read exactly once

    Patched on the **class, before the window exists**: the window hands the coordinator a *bound*
    method, so an instance patched afterwards would never be the object the coordinator holds -- and
    the test would fail while the wiring was perfectly correct.

    The **renamer** is mocked rather than ``Path``: patching the filesystem wholesale reaches the
    window's own teardown, where the task queue is written to disk, and a rename test has no business
    breaking a save.
    """
    resync = mocker.patch.object(TaskQueue, "resync_sources", autospec=True)
    renamer = mocker.patch("rehuco_core.rename_coordination.RehuRenamer")
    renamer.return_value.rename.return_value = Path("C:/tutorials/new_name/info.rehu")
    window = MainWindow()
    qtbot.addWidget(window)
    coordinator = window._MainWindow__rename_coordinator  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    coordinator.rename(Path("C:/tutorials/old_folder/info.rehu"), "new_name")

    assert resync.call_count == 1


def test_registers_the_tasks_page(qtbot: QtBot) -> None:
    """The Tasks settings page (#202) is registered top-level, not under "Plugins" -- the same
    reasoning as the Logs page: a restart-time choice about the app's own queue, not a plugin's.

    **Test steps:**

    * construct a real ``MainWindow``
    * verify the settings dialog's page stack holds a ``TasksPage``
    """
    window = MainWindow()
    qtbot.addWidget(window)

    settings_dialog = window._MainWindow__settings_dialog  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    dialog_ui = settings_dialog._SettingsDialog__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    stacked = [dialog_ui.page_stack.widget(index) for index in range(dialog_ui.page_stack.count())]
    pages = [area.widget() for area in stacked if isinstance(area, QScrollArea)]
    assert any(isinstance(page, TasksPage) for page in pages)


def test_restore_tasks_on_restart_brings_unfinished_work_back_queued(mocker: MockerFixture, qtbot: QtBot) -> None:
    """*Resume tasks on restart* on means unfinished work comes back ``queued``, not ``paused``.

    **Test steps:**

    * turn the setting on, leaving both clears off
    * construct a ``MainWindow``
    * verify ``store.restore`` was asked for ``queued``
    """
    restore_spy = mocker.patch("rehuco_agent.tasks.task_queue_store.TaskQueueStore.restore")

    def fake_load(self: TasksSettings, settings: object) -> None:
        del settings
        self.resume_on_restart = True

    mocker.patch.object(TasksSettings, "load", fake_load)

    window = MainWindow()
    qtbot.addWidget(window)

    restore_spy.assert_called_once()
    assert restore_spy.call_args.kwargs["unfinished_state"].value == "queued"  # pylint: disable=no-member


def test_closing_the_window_pauses_waits_saves_and_shuts_down_the_task_queue(
    mocker: MockerFixture, qtbot: QtBot
) -> None:
    """The exit sequence runs, in order, before the window actually closes ([[appendices.task-queue#teardown]]).

    **Test steps:**

    * construct a real ``MainWindow`` with nothing dirty to prompt about
    * patch the queue's pause/wait_until_idle/shutdown and the store's save
    * close the window
    * verify all four ran, in order
    """
    window = MainWindow()
    qtbot.addWidget(window)
    queue = window._MainWindow__task_queue  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    store = window._MainWindow__task_queue_store  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    calls: list[str] = []
    mocker.patch.object(queue, "pause", side_effect=lambda: calls.append("pause"))
    mocker.patch.object(queue, "wait_until_idle", side_effect=lambda: calls.append("wait") or True)
    mocker.patch.object(store, "save", side_effect=lambda: calls.append("save"))
    mocker.patch.object(queue, "shutdown", side_effect=lambda: calls.append("shutdown"))

    window.close()

    assert calls == ["pause", "wait", "save", "shutdown"]


def at_risk_status(*, safely_interruptible: bool = True, persistable: bool = True) -> JobStatus:
    """An unfinished job status with the two declarations a quit prompt reads.

    :param safely_interruptible: whether stopping it part-way leaves nothing behind.
    :param persistable: whether it survives a restart.
    :returns: the status.
    """
    return JobStatus(
        serial=1,
        label="job",
        state=JobState.RUNNING,
        safely_interruptible=safely_interruptible,
        persistable=persistable,
    )


def stub_queue_jobs(window: MainWindow, mocker: MockerFixture, *statuses: JobStatus) -> None:
    """Make the window's task queue report exactly ``statuses``.

    Crafted statuses rather than real jobs: what the prompt reads is two booleans a job *declares*,
    and driving a real job into each combination would test the fake rather than the decision.

    :param window: the window whose queue to stub.
    :param mocker: the patcher.
    :param statuses: what the queue should report.
    """
    queue = window._MainWindow__task_queue  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    mocker.patch.object(queue, "jobs", return_value=statuses)


def test_quitting_is_silent_when_every_unfinished_job_is_safe_and_saved(mocker: MockerFixture, qtbot: QtBot) -> None:
    """The common case raises no prompt at all -- being asked every time is the friction persistence
    exists to remove ([[appendices.task-queue#lifetime]]).

    **Test steps:**

    * stub the queue with an unfinished job that is both interruptible and persistable
    * close the window
    * verify no dialog appeared and the window closed
    """
    window = MainWindow()
    qtbot.addWidget(window)
    stub_queue_jobs(window, mocker, at_risk_status())
    warning = mocker.patch("rehuco_agent.main_window.QMessageBox.warning")

    assert window.close()

    warning.assert_not_called()


def test_quitting_is_silent_when_the_only_at_risk_jobs_have_already_finished(
    mocker: MockerFixture, qtbot: QtBot
) -> None:
    """A finished job is not about to lose anything, whatever it declared while it ran.

    **Test steps:**

    * stub the queue with a done job that is neither interruptible nor persistable
    * close the window
    * verify no dialog appeared
    """
    window = MainWindow()
    qtbot.addWidget(window)
    finished = JobStatus(serial=1, label="job", state=JobState.DONE, safely_interruptible=False, persistable=False)
    stub_queue_jobs(window, mocker, finished)
    warning = mocker.patch("rehuco_agent.main_window.QMessageBox.warning")

    assert window.close()

    warning.assert_not_called()


@mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"safely_interruptible": False}, "cannot be stopped part-way"),
        ({"persistable": False}, "will not be saved"),
    ],
)
def test_quitting_names_why_work_would_be_lost(
    mocker: MockerFixture, qtbot: QtBot, kwargs: dict[str, bool], expected: str
) -> None:
    """Each of the two ways work is lost gets its own line, so the prompt says which one applies.

    **Test steps:**

    * stub the queue with one unfinished job carrying the declaration under test
    * accept the prompt and close
    * verify the message named that reason
    """
    window = MainWindow()
    qtbot.addWidget(window)
    stub_queue_jobs(window, mocker, at_risk_status(**kwargs))
    warning = mocker.patch("rehuco_agent.main_window.QMessageBox.warning", return_value=QMessageBox.StandardButton.Yes)

    window.close()

    warning.assert_called_once()
    assert expected in warning.call_args.args[2]


def test_refusing_the_quit_prompt_keeps_the_window_open_and_the_queue_running(
    mocker: MockerFixture, qtbot: QtBot
) -> None:
    """Answering No aborts the close, leaving the queue untouched -- "wait for them to finish" is never
    offered, so going back is how someone deals with the work on their own terms.

    **Test steps:**

    * stub the queue with an unsaveable unfinished job and answer No
    * close the window
    * verify the close was refused and the queue was never shut down
    """
    window = MainWindow()
    qtbot.addWidget(window)
    stub_queue_jobs(window, mocker, at_risk_status(persistable=False))
    mocker.patch("rehuco_agent.main_window.QMessageBox.warning", return_value=QMessageBox.StandardButton.No)
    queue = window._MainWindow__task_queue  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    shutdown = mocker.patch.object(queue, "shutdown")

    assert not window.close()

    shutdown.assert_not_called()


def test_accepting_the_quit_prompt_shuts_the_queue_down_anyway(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Answering Yes goes ahead, losing what was named -- the choice was made knowingly.

    **Test steps:**

    * stub the queue with an uninterruptible unfinished job and answer Yes
    * close the window
    * verify the queue was shut down
    """
    window = MainWindow()
    qtbot.addWidget(window)
    stub_queue_jobs(window, mocker, at_risk_status(safely_interruptible=False))
    mocker.patch("rehuco_agent.main_window.QMessageBox.warning", return_value=QMessageBox.StandardButton.Yes)
    queue = window._MainWindow__task_queue  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    shutdown = mocker.patch.object(queue, "shutdown")

    assert window.close()

    shutdown.assert_called_once()


def test_a_queue_that_will_not_settle_is_logged_rather_than_waited_on(
    mocker: MockerFixture, qtbot: QtBot, caplog: Any
) -> None:
    """A job ignoring its checkpoints must never turn quitting into a window that will not close.

    **Test steps:**

    * make ``wait_until_idle`` report that the queue never settled
    * close the window
    * verify a warning was logged and the window still closed
    """
    window = MainWindow()
    qtbot.addWidget(window)
    queue = window._MainWindow__task_queue  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    mocker.patch.object(queue, "wait_until_idle", return_value=False)

    with caplog.at_level(logging.WARNING, logger="rehuco_agent.main_window"):
        assert window.close()

    assert "did not settle" in caplog.text


@mark.parametrize(
    ("clear_done", "clear_failed", "kept"),
    [
        (False, False, ["done", "failed", "cancelled", "queued"]),
        (True, False, ["failed", "cancelled", "queued"]),
        (False, True, ["done", "cancelled", "queued"]),
        (True, True, ["cancelled", "queued"]),
    ],
)
def test_each_clear_on_restart_setting_drops_only_its_own_kind(
    mocker: MockerFixture, qtbot: QtBot, clear_done: bool, clear_failed: bool, kept: list[str]
) -> None:
    """The two clears are independent, and **a cancelled job survives every combination** -- it was
    stopped on purpose and is the likeliest of the three to be retried.

    **Test steps:**

    * stand in a saved queue holding one job of each finished state, plus one queued
    * set each combination of the two clear settings
    * verify exactly the expected jobs reached ``restore``
    """
    saved = [
        {"kind": "x", "label": "done", "job_state": "done", "state": {}},
        {"kind": "x", "label": "failed", "job_state": "failed", "state": {}},
        {"kind": "x", "label": "cancelled", "job_state": "cancelled", "state": {}},
        {"kind": "x", "label": "queued", "job_state": "queued", "state": {}},
    ]
    mocker.patch("rehuco_agent.tasks.task_queue_store.TaskQueueStore.read_items", return_value=saved)
    restore = mocker.patch("rehuco_agent.tasks.task_queue_store.TaskQueueStore.restore")

    def fake_load(self: TasksSettings, settings: object) -> None:
        del settings
        self.clear_done_on_restart = clear_done
        self.clear_failed_on_restart = clear_failed

    mocker.patch.object(TasksSettings, "load", fake_load)

    window = MainWindow()
    qtbot.addWidget(window)

    restore.assert_called_once()
    assert [item["label"] for item in restore.call_args.args[0]] == kept


def test_restored_unfinished_work_comes_back_held_unless_resuming_is_asked_for(
    mocker: MockerFixture, qtbot: QtBot
) -> None:
    """Held is the default, so a restarted app comes up with nothing running.

    **Test steps:**

    * construct a window with the resume setting left off
    * verify ``restore`` was asked for the paused state
    """
    restore = mocker.patch("rehuco_agent.tasks.task_queue_store.TaskQueueStore.restore")

    window = MainWindow()
    qtbot.addWidget(window)

    restore.assert_called_once()
    assert restore.call_args.kwargs["unfinished_state"] is JobState.PAUSED


# endregion
