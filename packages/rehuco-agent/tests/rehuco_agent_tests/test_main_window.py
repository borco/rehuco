"""Tests for MainWindow: the top-level dock-in-dock shell hosting DocumentsDock."""

# the shell has a broad surface (docks, session restore, geometry, docks menu, close handling);
# its test suite is correspondingly long -- one cohesive module reads better than an arbitrary
# split, so the module-length cap is lifted here rather than fragmenting it.
# pylint: disable=too-many-lines

import logging
from collections.abc import Callable, Generator, Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from threading import Event
from typing import Any, Final

import PySide6QtAds as QtAds
from borco_pyside.logging import LogWidget
from borco_pyside.logging.log_model import MESSAGE_COLUMN
from borco_pyside.qtads import tab_close_button
from borco_pyside.qtads.qtads_pin_side_handler import DEFAULT_PIN_SIDE, PIN_SIDE_KEY
from PySide6.QtCore import QByteArray, QEvent, QModelIndex, QObject, Qt
from PySide6.QtGui import QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QMessageBox,
    QScrollArea,
    QSystemTrayIcon,
    QWidget,
)
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent import main_window
from rehuco_agent.app_logging import shared_log_bridge
from rehuco_agent.documents.document_widget import LOG_DOCK_MIN_HEIGHT
from rehuco_agent.glyphs import TAB_CLOSE_GLYPH
from rehuco_agent.main_window import (
    DOCK_PIN_SIDES_GROUP,
    DOCUMENTS_DOCK_OBJECT_NAME,
    LOG_DOCK_OBJECT_NAME,
    LOG_DOCK_TITLE,
    SETTINGS_DIALOG_OBJECT_NAME,
    TASK_QUEUE_DOCK_OBJECT_NAME,
    MainWindow,
)
from rehuco_agent.recycle_bin_deleter import RecycleBinDeleter
from rehuco_agent.settings.checksum_settings import shared_checksum_settings
from rehuco_agent.settings.document_session_settings import DocumentSessionSettings
from rehuco_agent.settings.identity_settings import shared_identity_settings
from rehuco_agent.settings.image_viewer_settings import PREVIEWS_VISIBLE_KEY, shared_image_viewer_settings
from rehuco_agent.settings.logs_settings import shared_logs_settings
from rehuco_agent.settings.main_window_settings import MainWindowSettings
from rehuco_agent.settings.recent_files_settings import RecentFilesSettings
from rehuco_agent.settings.session_restore_settings import SessionRestoreSettings
from rehuco_agent.settings.tasks_settings import TasksSettings
from rehuco_agent.settings.tray_settings import shared_tray_settings
from rehuco_agent.settings.ui.checksums_page import ChecksumsPage
from rehuco_agent.settings.ui.descriptions_page import DescriptionsPage
from rehuco_agent.settings.ui.files_page import FilesPage
from rehuco_agent.settings.ui.identity_page import IdentityPage
from rehuco_agent.settings.ui.images_display_page import ImagesDisplayPage
from rehuco_agent.settings.ui.images_files_page import ImagesFilesPage
from rehuco_agent.settings.ui.location_templates_page import LocationTemplatesPage
from rehuco_agent.settings.ui.logs_page import LogsPage
from rehuco_agent.settings.ui.screenshot_patterns_page import ScreenshotPatternsPage
from rehuco_agent.settings.ui.settings_dialog import PAGE_ROLE, TITLE_ROLE, SettingsDialog
from rehuco_agent.settings.ui.tasks_page import TasksPage
from rehuco_agent.settings.ui.videos_page import VideosPage
from rehuco_agent.tasks import TaskQueueStatusIndicator, TaskQueueWidget
from rehuco_agent.tray_icon import TrayIcon
from rehuco_core import (
    DEFAULT_DELETER_PROVIDER,
    DEFAULT_PLUGIN_REGISTRY,
    INFO_REHU_FILENAME,
    JobControl,
    JobState,
    JobStatus,
    PluginRegistry,
    PluginSpec,
    SweepChecksumsJob,
    TaskJobBase,
    TaskQueue,
)

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


def test_settings_dock_starts_closed_beside_the_documents_dock(qtbot: QtBot) -> None:
    """With nothing saved yet, the Settings dock is a closed tab in the Documents area -- not a
    floating window of its own, and not a pane of the bottom strip (#307).

    Both halves matter. Closed, because settings are somewhere you go and a first run should open on
    the documents area; in *that* area, because :meth:`MainWindow.__seed_bottom_dock_heights` measures
    a fresh layout's split by toggling the bottom docks, and a tab adds no pane for it to count.

    **Test steps:**

    * construct a real ``MainWindow``
    * verify the Settings dock is closed, and shares the Documents dock's own dock area
    """
    window = MainWindow()
    qtbot.addWidget(window)

    dock_manager = window._MainWindow__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    settings_dock = dock_manager.findDockWidget(SETTINGS_DIALOG_OBJECT_NAME)

    assert settings_dock is not None
    assert settings_dock.isClosed()
    assert settings_dock.dockAreaWidget() is documents_dock_widget(window).dockAreaWidget()


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


def test_the_window_installs_the_configured_deleter_for_discard_jobs(qtbot: QtBot) -> None:
    """A discard job resolves its deleter when it runs, so the window points the process-wide provider
    at the Recycle Bin setting before the saved queue is restored -- a restored discard then honours
    the setting exactly as a freshly enqueued one does, rather than coming back as a plain unlink (#298).

    **Test steps:**

    * construct a real ``MainWindow`` with the Recycle Bin setting at its default (on)
    * verify the process-wide provider now resolves a `RecycleBinDeleter`, not core's plain unlink
    """
    window = MainWindow()
    qtbot.addWidget(window)

    assert isinstance(DEFAULT_DELETER_PROVIDER.resolve(), RecycleBinDeleter)


def test_registers_the_files_page(qtbot: QtBot) -> None:
    """The Files page (#226, #291, #298) is registered into the settings dialog.

    **Test steps:**

    * construct a real ``MainWindow``
    * verify the settings dialog's page stack holds a ``FilesPage``
    """
    window = MainWindow()
    qtbot.addWidget(window)

    settings_dialog = window._MainWindow__settings_dialog  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    dialog_ui = settings_dialog._SettingsDialog__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    # each page is shown through a scroll area of its own (#229), so read it back out of one
    stacked = [dialog_ui.page_stack.widget(index) for index in range(dialog_ui.page_stack.count())]
    pages = [area.widget() for area in stacked if isinstance(area, QScrollArea)]
    assert any(isinstance(page, FilesPage) for page in pages)


def test_registers_the_videos_page(qtbot: QtBot) -> None:
    """The Videos page (#225) is registered into the settings dialog.

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


def test_the_category_tree_is_one_flat_alphabetical_list(qtbot: QtBot) -> None:
    """Every page is a top-level row, except the ones grouped under "Images" (#277, #294, #298) and
    "Locations" (#322), and the rows are in alphabetical order.

    The pages that used to nest under "Plugins" are among the top-level ones, so a reader looking for
    "Videos" no longer has to know it is a plugin's setting to find it. Order is registration order
    (nothing sorts the tree), which is what the sorted assertion actually guards. This platform's own
    page is left out of the expected set -- that it lands in the right place is covered by that same
    assertion, on whichever platform is running.

    **Test steps:**

    * construct a real ``MainWindow``
    * verify only "Images" and "Locations" have children, the cross-platform pages are all top-level
      rows, and the whole top-level list is sorted case-insensitively
    * verify "Images" nests exactly Display, Sidecar Extensions and Sidecar Names, in that order
    * verify "Locations" nests one page per installed plugin main key, alphabetically by title
    """
    window = MainWindow()
    qtbot.addWidget(window)

    settings_dialog = window._MainWindow__settings_dialog  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    model = settings_dialog._SettingsDialog__model  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    items = [model.item(row) for row in range(model.rowCount())]
    titles = [item.text() for item in items]
    grouped_row_counts = {"Images": 3, "Locations": len(DEFAULT_PLUGIN_REGISTRY.main_keys)}
    assert [item.rowCount() for item in items] == [grouped_row_counts.get(title, 0) for title in titles]
    assert set(titles) >= {
        "Checksums",
        "Descriptions",
        "Files",
        "Identity",
        "Images",
        "Locations",
        "Logs",
        "Session",
        "Tasks",
        "Videos",
    }
    assert "Excluded Files" not in titles
    assert "Screenshot Patterns" not in titles
    assert titles == sorted(titles, key=str.casefold)

    images_item = items[titles.index("Images")]
    child_titles = [images_item.child(row).text() for row in range(images_item.rowCount())]
    assert child_titles == ["Display", "Sidecar Extensions", "Sidecar Names"]

    locations_item = items[titles.index("Locations")]
    location_child_titles = [locations_item.child(row).text() for row in range(locations_item.rowCount())]
    assert location_child_titles == ["Collections", "Reference Images", "Tutorials"]


def test_a_plugin_this_build_does_not_ship_still_gets_its_own_locations_page(
    mocker: MockerFixture, qtbot: QtBot
) -> None:
    """Locations pages come from the installed plugin registry, not a fixed enumeration of today's
    three types (#322): a fourth, made-up plugin gets its own page with no code change beyond
    registering it.

    **Test steps:**

    * swap ``DEFAULT_PLUGIN_REGISTRY`` for one carrying today's three plugins plus a made-up fourth
    * construct a real ``MainWindow``
    * verify the Locations group now nests a fourth page, alphabetically placed by its display title
    """
    extra_registry = PluginRegistry((*DEFAULT_PLUGIN_REGISTRY, PluginSpec(("daz3d",), color="#5D4037")))
    mocker.patch.object(main_window, "DEFAULT_PLUGIN_REGISTRY", extra_registry)

    window = MainWindow()
    qtbot.addWidget(window)

    settings_dialog = window._MainWindow__settings_dialog  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    model = settings_dialog._SettingsDialog__model  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    items = [model.item(row) for row in range(model.rowCount())]
    titles = [item.text() for item in items]
    locations_item = items[titles.index("Locations")]
    location_child_titles = [locations_item.child(row).text() for row in range(locations_item.rowCount())]

    assert location_child_titles == ["Collections", "Daz3Ds", "Reference Images", "Tutorials"]

    dialog_ui = settings_dialog._SettingsDialog__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    stacked = [dialog_ui.page_stack.widget(index) for index in range(dialog_ui.page_stack.count())]
    pages = [area.widget() for area in stacked if isinstance(area, QScrollArea)]
    assert any(isinstance(page, LocationTemplatesPage) for page in pages)


def test_registers_the_checksums_page(qtbot: QtBot) -> None:
    """The Checksums page (#242) is registered into the settings dialog, once.

    **Test steps:**

    * construct a real ``MainWindow``
    * verify the page stack holds a `ChecksumsPage` and the category tree lists it exactly once
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


def test_registers_the_screenshot_patterns_page(qtbot: QtBot) -> None:
    """The Screenshot Patterns page (#53, #287) is registered into the settings dialog once, nested
    under the "Images" group as "Sidecar Names" (#294, #298).

    **Test steps:**

    * construct a real ``MainWindow``
    * verify the page stack holds a `ScreenshotPatternsPage` and the "Images" group lists it once
    """
    window = MainWindow()
    qtbot.addWidget(window)

    settings_dialog = window._MainWindow__settings_dialog  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    dialog_ui = settings_dialog._SettingsDialog__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    stacked = [dialog_ui.page_stack.widget(index) for index in range(dialog_ui.page_stack.count())]
    pages = [area.widget() for area in stacked if isinstance(area, QScrollArea)]
    assert any(isinstance(page, ScreenshotPatternsPage) for page in pages)

    model = settings_dialog._SettingsDialog__model  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    images_item = next(model.item(row) for row in range(model.rowCount()) if model.item(row).text() == "Images")
    child_titles = [images_item.child(row).text() for row in range(images_item.rowCount())]
    assert child_titles.count("Sidecar Names") == 1


def test_selecting_the_images_group_stacks_every_block_of_its_three_pages(qtbot: QtBot) -> None:
    """The "Images" group row shows Display, Sidecar Extensions and Sidecar Names together in one column
    (#230, #294, #298) -- so the group behaves exactly as the one flat Images page did before the
    split.

    **Test steps:**

    * construct a real ``MainWindow`` and select the "Images" group row in the settings tree
    * verify the shown column holds every block each of the three pages declared
    """
    window = MainWindow()
    qtbot.addWidget(window)

    settings_dialog = window._MainWindow__settings_dialog  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    dialog_ui = settings_dialog._SettingsDialog__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    model = settings_dialog._SettingsDialog__model  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    images_item = next(model.item(row) for row in range(model.rowCount()) if model.item(row).text() == "Images")
    dialog_ui.category_tree.setCurrentIndex(dialog_ui.category_tree.model().mapFromSource(images_item.index()))

    column_layout = dialog_ui.page_stack.currentWidget().widget().layout()
    stacked = {column_layout.itemAt(index).widget() for index in range(column_layout.count())}
    page_blocks = settings_dialog._SettingsDialog__page_blocks  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    for page_type in (ImagesDisplayPage, ImagesFilesPage, ScreenshotPatternsPage):
        page = next(page for page in page_blocks if isinstance(page, page_type))
        declared = {block for block, _, _ in page_blocks[page]}
        assert declared, page_type.__name__
        assert declared <= stacked, page_type.__name__


def test_the_filter_finds_each_images_page_under_its_group(qtbot: QtBot) -> None:
    """A term carried only by a grouped page's block finds that page, shown under the "Images" row
    and beside no sibling (#76, #294, #298).

    **Test steps:**

    * construct a real ``MainWindow``
    * filter by a Sidecar Names (screenshot patterns) term, then by a Sidecar Extensions term
    * verify each time the visible tree is the "Images" row with exactly that one child
    """
    window = MainWindow()
    qtbot.addWidget(window)

    settings_dialog = window._MainWindow__settings_dialog  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    dialog_ui = settings_dialog._SettingsDialog__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    proxy = dialog_ui.category_tree.model()

    def visible_titles(parent: QModelIndex) -> list[str]:
        titles: list[str] = []
        for row in range(proxy.rowCount(parent)):
            index = proxy.index(row, 0, parent)
            titles.append(proxy.data(index))
            titles.extend(visible_titles(index))
        return titles

    dialog_ui.filter_edit.setText("sidecar image name patterns")
    assert visible_titles(QModelIndex()) == ["Images", "Sidecar Names"]

    dialog_ui.filter_edit.setText("sidecar image extensions")
    assert visible_titles(QModelIndex()) == ["Images", "Sidecar Extensions"]


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
    """The reference-images extension list is a block on Images/Files, not a page (#222, #294).

    **Test steps:**

    * construct a real ``MainWindow``
    * verify no row in the category tree is titled "Reference Images"
    """
    window = MainWindow()
    qtbot.addWidget(window)

    settings_dialog = window._MainWindow__settings_dialog  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    model = settings_dialog._SettingsDialog__model  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert "Reference Images" not in [model.item(row).text() for row in range(model.rowCount())]


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


def test_an_open_request_from_a_documents_files_dock_takes_the_ordinary_open_route(
    mocker: MockerFixture, qtbot: QtBot
) -> None:
    """Another resource double-clicked in a document's Files sub-dock arrives here rather than being
    opened where it was clicked (#266), so it gets the same resolve, the same reveal of the documents
    area and the same ``Open recents`` entry as an open from the menu.

    **Test steps:**

    * construct a ``MainWindow`` with the dock's own open mocked
    * emit the documents dock's ``open_requested``
    * verify it went through ``open_path`` and reached the dock's open
    """
    open_document = mocker.patch("rehuco_agent.main_window.DocumentsDock.open_document")
    window = MainWindow()
    qtbot.addWidget(window)
    documents_dock = window._MainWindow__documents_dock  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    neighbour = Path("a.rehu").resolve()

    documents_dock.open_requested.emit(neighbour)

    open_document.assert_called_once_with(neighbour)


def test_an_open_request_carrying_anything_else_opens_nothing(mocker: MockerFixture, qtbot: QtBot) -> None:
    """The relay is typed ``object`` so a Python ``Path`` survives the hop from a sub-dock three
    managers down, which leaves the type to be established here -- and opening whatever arrived would
    hand a non-path to a resolve that raises on one.

    **Test steps:**

    * emit the documents dock's ``open_requested`` with something that is not a path
    * verify nothing was opened
    """
    open_document = mocker.patch("rehuco_agent.main_window.DocumentsDock.open_document")
    window = MainWindow()
    qtbot.addWidget(window)
    documents_dock = window._MainWindow__documents_dock  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    documents_dock.open_requested.emit("a.rehu")

    open_document.assert_not_called()


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
    """``File > Conversion Backups...`` opens the backups manager over the app-wide queue (#193, #290).

    Takes no identity, unlike the import wizard: discarding deletes files and files them under nobody,
    so there are no per-user flags for an identity to belong to.

    **Test steps:**

    * mock the dialog class
    * trigger ``conversion_backups_action``
    * verify the dialog was built over the app-wide queue and shown modally
    """
    dialog = mocker.MagicMock()
    built = mocker.patch("rehuco_agent.main_window.ConversionBackupsDialog", return_value=dialog)
    window = MainWindow()
    qtbot.addWidget(window)

    window._MainWindow__ui.conversion_backups_action.trigger()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    built.assert_called_once_with(
        window._MainWindow__task_queue,  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
        parent=window,
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
    gap plain ``toggled``-based mirroring can't catch on its own (#64). A dock closed from its tab's
    ``[x]``, and a layout restore that places it closed, both change visibility this same silent way.

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


def test_a_document_path_change_replaces_its_recents_entry_in_place(qtbot: QtBot) -> None:
    """When an open document's path moves (a ``.tc`` -> ``.rehu`` conversion, a completed rename),
    ``Open recents`` (#64) is corrected to the new path in place, not bumped to newest (#295).

    **Test steps:**

    * record an older and a newer path
    * raise ``document_path_changed`` for the older one moving to a third path
    * verify the third path sits where the older one did, and the newer one is still newest
    """
    window = MainWindow()
    qtbot.addWidget(window)
    older = Path("older.tc").resolve()
    newer = Path("newer.rehu").resolve()
    moved_to = Path("older.rehu").resolve()
    recent_files = window._MainWindow__recent_files  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    recent_files.record(older)
    recent_files.record(newer)

    window._MainWindow__documents_dock.document_path_changed.emit(  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
        older, moved_to
    )

    assert recent_files.newest_first() == [newer, moved_to]


def test_a_directory_scoped_rename_replaces_the_folder_recorded_in_recents(qtbot: QtBot) -> None:
    """Renaming a directory-scoped resource that was opened by its folder (#64's ``open_folder``
    route) corrects that folder's recents entry, not just the ``info.rehu`` path it never held (#296).

    **Test steps:**

    * record the resource's folder, as ``open_folder`` would have
    * raise ``document_path_changed`` with the ``info.rehu`` paths a rename moves between
    * verify the recorded folder became the renamed one, in place
    """
    window = MainWindow()
    qtbot.addWidget(window)
    old_folder = Path("foo").resolve()
    new_folder = Path("bar").resolve()
    recent_files = window._MainWindow__recent_files  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    recent_files.record(old_folder)

    window._MainWindow__documents_dock.document_path_changed.emit(  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
        old_folder / INFO_REHU_FILENAME, new_folder / INFO_REHU_FILENAME
    )

    assert recent_files.newest_first() == [new_folder]


def test_a_file_scoped_rename_replaces_the_archive_recorded_in_recents(qtbot: QtBot) -> None:
    """Renaming a file-scoped resource that was opened by its archive (#64's ``open_archive`` route)
    corrects that archive's recents entry, which shares the ``.rehu``'s stem but never its extension
    (#296).

    **Test steps:**

    * record the resource's archive, as ``open_archive`` would have
    * raise ``document_path_changed`` with the ``.rehu`` paths a rename moves between
    * verify the recorded archive became the renamed stem under its own extension, in place
    """
    window = MainWindow()
    qtbot.addWidget(window)
    old_archive = Path("foo.zip").resolve()
    recent_files = window._MainWindow__recent_files  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    recent_files.record(old_archive)

    window._MainWindow__documents_dock.document_path_changed.emit(  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
        Path("foo.rehu").resolve(), Path("bar.rehu").resolve()
    )

    assert recent_files.newest_first() == [Path("bar.zip").resolve()]


def test_a_rename_corrects_every_recents_entry_the_same_resource_holds(qtbot: QtBot) -> None:
    """A resource opened once by its ``.rehu`` and once by its archive holds two recents entries --
    each route records its own path even when it lands on the already-open dock -- and a rename
    corrects both, each in its own place (#296).

    **Test steps:**

    * record the resource's ``.rehu``, an unrelated path, then the resource's archive
    * raise ``document_path_changed`` with the ``.rehu`` paths a rename moves between
    * verify both entries moved to the new stem and neither changed position
    """
    window = MainWindow()
    qtbot.addWidget(window)
    unrelated = Path("other.rehu").resolve()
    recent_files = window._MainWindow__recent_files  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    recent_files.record(Path("foo.rehu").resolve())
    recent_files.record(unrelated)
    recent_files.record(Path("foo.zip").resolve())

    window._MainWindow__documents_dock.document_path_changed.emit(  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
        Path("foo.rehu").resolve(), Path("bar.rehu").resolve()
    )

    assert recent_files.newest_first() == [Path("bar.zip").resolve(), unrelated, Path("bar.rehu").resolve()]


def test_a_document_gaining_its_first_path_leaves_recents_alone(qtbot: QtBot) -> None:
    """A path change with no path on one side -- a path-less document gaining its first path, or a
    document losing its path -- touches nothing in ``Open recents``: nothing was recorded under
    ``None`` to swap, and a first path is not an open (#295).

    **Test steps:**

    * record one path
    * raise ``document_path_changed`` from ``None`` to a path, then from a path to ``None``
    * verify the recorded path is still the only entry
    """
    window = MainWindow()
    qtbot.addWidget(window)
    recorded = Path("recorded.rehu").resolve()
    recent_files = window._MainWindow__recent_files  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    recent_files.record(recorded)
    documents_dock = window._MainWindow__documents_dock  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    documents_dock.document_path_changed.emit(None, Path("first.rehu").resolve())
    documents_dock.document_path_changed.emit(recorded, None)

    assert recent_files.newest_first() == [recorded]


def test_a_focused_documents_path_change_updates_the_window_title(mocker: MockerFixture, qtbot: QtBot) -> None:
    """When the *focused* document moves (a completed rename), the window title picks up its new
    label instead of keeping the one it had before the move (#356).

    **Test steps:**

    * stand in the focused document with a label reflecting its new path
    * raise ``document_path_changed`` for that document's old path moving to its new one
    * verify the window title picked up the new label
    """
    window = MainWindow()
    qtbot.addWidget(window)
    base_title = window.windowTitle()
    documents_dock = window._MainWindow__documents_dock  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    old_path = Path("old_name/info.rehu").resolve()
    new_path = Path("new_name/info.rehu").resolve()
    focused_widget = mocker.MagicMock(model=mocker.MagicMock(label="new_name/", path=new_path))
    mocker.patch.object(documents_dock, "focused_document_widget", return_value=focused_widget)

    documents_dock.document_path_changed.emit(old_path, new_path)

    assert window.windowTitle() == f"new_name/ - {base_title}"


def test_an_unfocused_documents_path_change_leaves_the_window_title_alone(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A path change on a document that is not the focused one does not touch the window title --
    it only reflects the *focused* document's label (#356).

    **Test steps:**

    * stand in the focused document, unrelated to the path change
    * raise ``document_path_changed`` for a different, unrelated document's move
    * verify the window title kept the focused document's own label
    """
    window = MainWindow()
    qtbot.addWidget(window)
    base_title = window.windowTitle()
    documents_dock = window._MainWindow__documents_dock  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    focused_path = Path("focused/info.rehu").resolve()
    focused_widget = mocker.MagicMock(model=mocker.MagicMock(label="focused/", path=focused_path))
    mocker.patch.object(documents_dock, "focused_document_widget", return_value=focused_widget)
    window._MainWindow__on_document_focus_changed(focused_widget)  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    documents_dock.document_path_changed.emit(Path("old.rehu").resolve(), Path("new.rehu").resolve())

    assert window.windowTitle() == f"focused/ - {base_title}"


def test_recents_menu_lists_remembered_paths_newest_first(qtbot: QtBot) -> None:
    """``Open recents`` lists every remembered path, most-recently-opened first (#64).

    **Test steps:**

    * construct ``MainWindow`` and record two paths, oldest first
    * populate the recents menu
    * verify its entries read back newest first, none of them marked
    """
    window = MainWindow()
    qtbot.addWidget(window)
    recent_files = window._MainWindow__recent_files  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    older, newer = Path("older.rehu").resolve(), Path("newer.rehu").resolve()
    recent_files.record(older)
    recent_files.record(newer)

    window._MainWindow__populate_recents_menu()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    menu = window._MainWindow__ui.open_recents_menu  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    paths_shown = [action.defaultWidget().displayed_path() for action in menu.actions()]
    assert paths_shown == [str(newer), str(older)]
    # recents lists paths, not open documents -- no notion of "current" or "dirty", so no entry
    # is ever checked or marked (#79)
    assert not any(action.defaultWidget().checked or action.defaultWidget().dirty for action in menu.actions())


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
    titles_shown = [action.defaultWidget().displayed_title() for action in menu.actions()]
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

    paths_shown = [action.defaultWidget().displayed_path() for action in menu.actions()]
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


def float_open_settings_dock(window: MainWindow) -> Any:
    """Tear the Settings dock out into a floating window of its own, open, and return that container.

    Stands in for the user dragging it out, which is the only way any of these docks floats since #307
    -- none of them is placed that way. The behaviour under test is about a floating dock window rather
    than about Settings; this is simply the dock whose content is cheapest to build.
    ``addDockWidgetFloating`` reopens the closed dock it moves
    ([[appendices.qt-ads#auto-hide-abandoned-float]]), so no toggle is needed; the container is read
    back through the dock rather than assumed, so a caller fails loudly rather than asserting on ``None``.

    :param window: the window whose Settings dock to float.
    :returns: the floating container now holding it.
    """
    dock_manager = window._MainWindow__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    dock = main_dock(window, SETTINGS_DIALOG_OBJECT_NAME)
    dock_manager.addDockWidgetFloating(dock)
    container = dock.floatingDockContainer()
    assert container is not None, "the Settings dock was expected to float out (#307)"
    return container


def test_hide_to_tray_hides_a_floating_dock_with_the_window(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Hiding to tray takes every floating dock window with it: a floating dock is its own
    top-level window, so it does not follow a plain ``hide()`` and would otherwise sit on screen
    with nothing behind it (#205).

    **Test steps:**

    * mock tray availability as ``True`` and enable tray mode before constructing the window
    * float the Settings dock out into a window of its own
    * call ``hide_to_tray``
    * verify the window and the floating dock are both hidden
    """
    mocker.patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=True)
    shared_tray_settings().enabled = True
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    container = float_open_settings_dock(window)
    assert container.isVisible()

    window.hide_to_tray()

    assert window.isHidden()
    assert container.isVisible() is False


def test_hide_to_tray_leaves_the_dock_logically_open(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A dock hidden with the window stays *open* as far as it is concerned -- hidden, not
    closed -- so what gets persisted on a quit from the tray is the user's own choice rather than
    the tray's bookkeeping (#205).

    **Test steps:**

    * mock tray availability as ``True`` and enable tray mode before constructing the window
    * float the Settings dock out, then hide to tray
    * verify it still reports itself open
    """
    mocker.patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=True)
    shared_tray_settings().enabled = True
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    float_open_settings_dock(window)
    dock_manager = window._MainWindow__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    window.hide_to_tray()

    dock = dock_manager.findDockWidget(SETTINGS_DIALOG_OBJECT_NAME)
    assert dock is not None
    assert dock.isClosed() is False


def test_showing_from_the_tray_brings_back_the_dock_hidden_with_the_window(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A floating dock that was on screen when the window went to the tray comes back with it (#205).

    **Test steps:**

    * mock tray availability as ``True`` and enable tray mode before constructing the window
    * float the Settings dock out, hide to tray, then show again
    * verify the window and the floating dock are both back on screen
    """
    mocker.patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=True)
    shared_tray_settings().enabled = True
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    container = float_open_settings_dock(window)
    window.hide_to_tray()

    window.raise_and_activate()

    assert window.isVisible()
    assert container.isVisible()


def test_showing_from_the_tray_leaves_a_closed_dock_closed(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Only what was actually on screen comes back: a dock the user had closed before hiding is
    not opened by returning from the tray (#205).

    **Test steps:**

    * mock tray availability as ``True`` and enable tray mode before constructing the window
    * leave the Settings dock closed, hide to tray, then show again
    * verify it is still closed
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


def test_close_to_tray_hides_a_floating_dock_too(mocker: MockerFixture, qtbot: QtBot) -> None:
    """The window's own close button routes through the same hide, so closing to tray takes the
    floating docks with it -- not only the tray menu's Hide (#205).

    **Test steps:**

    * mock tray availability as ``True`` and enable tray mode before constructing the window
    * float the Settings dock out into a window of its own
    * dispatch a close event (the titlebar close, not an explicit quit)
    * verify the close was ignored and the floating dock went away with the window
    """
    mocker.patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=True)
    shared_tray_settings().enabled = True
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    container = float_open_settings_dock(window)
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
    and what matters here is that whichever one this platform built carries the tray block. The title
    is read off the tree row, since a page no longer carries one of its own (#277).

    **Test steps:**

    * construct a real ``MainWindow``
    * find the page registered under the title "System Integration"
    * verify it holds the tray checkbox
    """
    window = MainWindow()
    qtbot.addWidget(window)

    settings_dialog = window._MainWindow__settings_dialog  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    model = settings_dialog._SettingsDialog__model  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    rows = [model.item(row) for row in range(model.rowCount())]
    system_integration = [item.data(PAGE_ROLE) for item in rows if item.data(TITLE_ROLE) == "System Integration"]

    assert len(system_integration) == 1, "every platform registers exactly one System Integration page"
    assert system_integration[0].findChild(QCheckBox, "enabled_check_box") is not None


# endregion


def test_restore_session_on_startup_delegates_to_the_documents_dock(mocker: MockerFixture, qtbot: QtBot) -> None:
    """The loaded session is handed to ``DocumentsDock.restore_session`` as-is (#21, #66) --
    ``DocumentsDock`` alone decides how to recreate each dock/tab and when each document's file is
    actually read; see its own test suite for that behavior.

    **Test steps:**

    * mock ``DocumentsDock.restore_session``
    * construct ``MainWindow``
    * verify it was called once, with the window's own loaded session
    """
    restore_session = mocker.patch("rehuco_agent.main_window.DocumentsDock.restore_session")

    window = MainWindow()
    qtbot.addWidget(window)

    session = window._MainWindow__session  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    restore_session.assert_called_once_with(session)


def test_restore_on_startup_off_skips_reopening_the_saved_session(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Turning off the Session page's toggle (#65) starts with no documents open, even though the
    previous session still has an open item saved underneath.

    **Test steps:**

    * seed ``DocumentSessionSettings.load`` to report one open item
    * seed ``SessionRestoreSettings.load`` to report the toggle off
    * mock ``DocumentsDock.restore_session``
    * construct ``MainWindow``
    * verify ``restore_session`` was never called
    """
    open_path = Path("open.rehu").resolve()

    def fake_session_load(self: DocumentSessionSettings, settings: object) -> None:
        del settings
        self.items[open_path] = DocumentSessionSettings.Item(open=True, state=b"state-bytes")  # pylint: disable=unsupported-assignment-operation

    def fake_restore_settings_load(self: SessionRestoreSettings, settings: object) -> None:
        del settings
        self.restore_on_startup = False

    mocker.patch.object(DocumentSessionSettings, "load", fake_session_load)
    mocker.patch.object(SessionRestoreSettings, "load", fake_restore_settings_load)
    restore_session = mocker.patch("rehuco_agent.main_window.DocumentsDock.restore_session")

    window = MainWindow()
    qtbot.addWidget(window)

    restore_session.assert_not_called()


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


def test_close_event_saves_an_open_settings_dock_as_open(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A Settings dock left open at close reopens open on the next launch (#307).

    The deliberate behaviour change: "Restore on start" used to let the user leave it open now and
    still have it stay shut next time, and a plain dock does not draw that distinction -- open at
    close is open at start, the same deal Documents, Log and Tasks already offer. Pinned here because
    it is the capability that release spent, and a silent regression back to closed would look like a
    bug rather than the trade.

    **Test steps:**

    * construct a window, open its Settings dock, and dispatch a close event
    * construct a second window seeded (via a mocked ``load``) with the saved outer dock state
    * verify the second window's Settings dock came back open
    """
    first = MainWindow()
    qtbot.addWidget(first)
    dock_manager = first._MainWindow__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    settings_dock = dock_manager.findDockWidget(SETTINGS_DIALOG_OBJECT_NAME)
    assert settings_dock is not None
    settings_dock.toggleView(True)

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
    assert second_settings_dock.isClosed() is False


def test_a_floating_closed_settings_dock_restores_floating_and_closed(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A Settings dock the user floated out and then closed comes back exactly so: closed, in a
    floating container that is rebuilt but not shown, and it opens floating when asked (#307).

    Floated by hand because since #307 nothing else floats it -- the previous build's own floating
    default is what the version bump discards. A docked-and-closed round trip would prove nothing here:
    the dock is *built* closed, so that assertion passes on a window whose restore never ran.

    **Test steps:**

    * float one window's Settings dock out, close it, and capture the layout it saves
    * seed ``MainWindowSettings.load`` with that blob and construct a second window
    * verify the dock is closed, its container exists and is hidden, and opening it floats
    """
    first = MainWindow()
    qtbot.addWidget(first)
    float_open_settings_dock(first)
    main_dock(first, SETTINGS_DIALOG_OBJECT_NAME).toggleView(False)

    first._MainWindow__save_window_state()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    window_settings = first._MainWindow__window_settings  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    saved_state = window_settings.outer_docks_state

    def fake_load(self: MainWindowSettings, settings: object) -> None:
        del settings
        self.outer_docks_state = saved_state

    mocker.patch.object(MainWindowSettings, "load", fake_load)

    second = MainWindow()
    qtbot.addWidget(second)
    restored = main_dock(second, SETTINGS_DIALOG_OBJECT_NAME)

    assert restored.isClosed()
    container = restored.floatingDockContainer()
    assert container is not None
    assert container.isVisible() is False
    restored.toggleView(True)
    assert restored.isFloating()


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
    * force ``sys.platform`` to ``"win32"`` and mock the Windows-only helpers (the show-at-once pair
      too, #308, so the faked platform never reaches ``ctypes.windll`` off Windows)
    * call ``raise_and_activate``
    * verify the foreground helper was called with this window
    """
    window = MainWindow()
    qtbot.addWidget(window)
    mocker.patch.object(window, "show")
    mocker.patch.object(window, "raise_")
    mocker.patch.object(window, "activateWindow")

    mocker.patch("rehuco_agent.main_window.sys.platform", "win32")
    mocker.patch("borco_pyside.platforms.windows.window_transitions.open_transition_disabled")
    mocker.patch("borco_pyside.platforms.windows.window_painting.paint_now")
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
    titles = [action.defaultWidget().displayed_title() for action in dynamic_actions]
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


def test_docks_menu_marks_the_focused_documents_entry_with_a_checkmark(
    dock_entries: Callable[[MainWindow], list[Any]], mocker: MockerFixture, qtbot: QtBot
) -> None:
    """Only the currently focused document's entry draws the style's checkmark (#79); it is drawn in
    the menu's own check column rather than written into the title, so the title is unaffected.

    **Test steps:**

    * construct ``MainWindow`` and stand in two open documents
    * stand in one of them as the focused widget
    * populate the docks menu
    * verify only the focused document's entry is checked, and no title gained a marker
    """
    window = MainWindow()
    qtbot.addWidget(window)
    documents_dock = window._MainWindow__documents_dock  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    focused_widget = mocker.MagicMock(
        model=mocker.MagicMock(label="Focused", path=Path("/focused/info.rehu"), dirty=False)
    )
    other_widget = mocker.MagicMock(model=mocker.MagicMock(label="Other", path=Path("/other/info.rehu"), dirty=False))
    for widget in (focused_widget, other_widget):
        widget.save_state.return_value = b"snapshot"  # keeps teardown's implicit close() from choking on a MagicMock
    mocker.patch.object(documents_dock, "open_document_widgets", return_value=[focused_widget, other_widget])
    mocker.patch.object(documents_dock, "focused_document_widget", return_value=focused_widget)

    window._MainWindow__add_open_documents(window._MainWindow__ui.view_menu)  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    entries = [action.defaultWidget() for action in dock_entries(window)]
    assert {entry.displayed_title(): entry.checked for entry in entries} == {"Focused": True, "Other": False}


def test_docks_menu_marks_a_dirty_documents_entry_with_the_dirty_marker(
    dock_entries: Callable[[MainWindow], list[Any]], mocker: MockerFixture, qtbot: QtBot
) -> None:
    """Only a dirty open document's entry draws the unsaved-changes marker -- the same one its own
    tab title carries, placed in the menu's icon column rather than in the title text (#79).

    **Test steps:**

    * construct ``MainWindow`` and stand in a dirty and a clean open document
    * populate the docks menu
    * verify only the dirty document's entry is marked, and no title text was altered
    """
    # the dirty stand-in below would otherwise pop a real modal close guard at teardown
    discard_unsaved_changes_on_close(mocker)
    window = MainWindow()
    qtbot.addWidget(window)
    dirty_widget = mocker.MagicMock(model=mocker.MagicMock(label="Dirty", path=Path("/dirty/info.rehu"), dirty=True))
    clean_widget = mocker.MagicMock(model=mocker.MagicMock(label="Clean", path=Path("/clean/info.rehu"), dirty=False))
    for widget in (dirty_widget, clean_widget):
        widget.save_state.return_value = b"snapshot"  # keeps teardown's implicit close() from choking on a MagicMock
    documents_dock = window._MainWindow__documents_dock  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    mocker.patch.object(documents_dock, "open_document_widgets", return_value=[dirty_widget, clean_widget])

    window._MainWindow__add_open_documents(window._MainWindow__ui.view_menu)  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    entries = [action.defaultWidget() for action in dock_entries(window)]
    assert {entry.displayed_title(): entry.dirty for entry in entries} == {"Dirty": True, "Clean": False}


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


# region the documents dock (#268)


def documents_dock_widget(window: MainWindow) -> Any:
    """Find the documents area's own dock on the outer manager (#268).

    :param window: the window to read.
    :returns: the dock.
    """
    dock_manager = window._MainWindow__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    return dock_manager.findDockWidget(DOCUMENTS_DOCK_OBJECT_NAME)


def test_installs_a_documents_dock_and_no_central_widget(qtbot: QtBot) -> None:
    """The documents area is an ordinary dock on the outer manager, and the manager has no central
    widget at all (#268).

    The area used to be ``CDockManager.setCentralWidget``'s permanent, tabless dock -- the one surface
    the user could not put away. Both halves are asserted here, because the point is not that a
    Documents dock exists but that it is a *peer* of Log and Tasks rather than the fixture they split
    off from.

    **Test steps:**

    * construct a real ``MainWindow``
    * find the outer dock manager's registered dock named :data:`DOCUMENTS_DOCK_OBJECT_NAME`
    * verify it exists, is placed, and hosts the window's ``DocumentsDock``
    * verify no central-widget dock is registered alongside it
    """
    window = MainWindow()
    qtbot.addWidget(window)
    dock_manager = window._MainWindow__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    documents_dock = window._MainWindow__documents_dock  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    dock = documents_dock_widget(window)

    assert dock is not None
    assert dock.dockAreaWidget() is not None
    assert dock.widget() is documents_dock
    assert set(dock_manager.dockWidgetsMap()) == {
        DOCUMENTS_DOCK_OBJECT_NAME,
        LOG_DOCK_OBJECT_NAME,
        TASK_QUEUE_DOCK_OBJECT_NAME,
        SETTINGS_DIALOG_OBJECT_NAME,
    }


def test_the_documents_dock_starts_open_and_closable(qtbot: QtBot) -> None:
    """Unlike the Log and Tasks pair, the Documents dock starts **open** -- the documents area is what
    the window is for -- and it is closable, which is what made #268 worth doing (#268).

    **Test steps:**

    * construct a real ``MainWindow`` with nothing persisted
    * verify the dock is open and its toggle checked
    * verify it carries the closable feature
    """
    window = MainWindow()
    qtbot.addWidget(window)

    dock = documents_dock_widget(window)

    assert not dock.isClosed()
    assert dock.toggleViewAction().isChecked()
    dock.toggleView(False)
    assert dock.isClosed()


def test_the_documents_dock_toggle_leads_the_app_dock_toggles_on_the_action_bar(qtbot: QtBot) -> None:
    """The three app-dock toggles lead the action bar, ahead of the theme action, in the order
    Documents, Log, Tasks (#268 added the first one ahead of #200's and #202's; #311 moved the group
    to the top).

    **Test steps:**

    * construct a real ``MainWindow``
    * read the action bar's actions in order
    * verify all three precede theme, documents before log before tasks, and settings stays last
    """
    window = MainWindow()
    qtbot.addWidget(window)
    ui = window._MainWindow__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    dock_manager = window._MainWindow__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    settings_dock = dock_manager.findDockWidget(SETTINGS_DIALOG_OBJECT_NAME)

    actions = ui.action_bar.actions()
    documents_toggle = documents_dock_widget(window).toggleViewAction()
    log_toggle = log_dock(window).toggleViewAction()

    assert actions.index(documents_toggle) < actions.index(log_toggle)
    assert actions.index(log_toggle) < actions.index(ui.theme_action)
    assert actions.index(ui.theme_action) < actions.index(settings_dock.toggleViewAction())


def test_the_documents_dock_toggle_carries_a_themed_icon(qtbot: QtBot) -> None:
    """The toggle is themed from the documents icon, so it follows a theme switch like the Log and
    Tasks buttons beside it (#268).

    **Test steps:**

    * construct a real ``MainWindow``
    * verify the documents dock's toggle action carries an icon
    """
    window = MainWindow()
    qtbot.addWidget(window)

    assert not documents_dock_widget(window).toggleViewAction().icon().isNull()


def test_the_documents_dock_toggle_leads_the_app_docks_in_the_view_menu(qtbot: QtBot) -> None:
    """``View`` lists ``documents_action`` after the theme entries and before ``log_action`` (#268).

    A companion, not the dock's own ``toggleViewAction()``, for the same reason the other two are --
    see ``__setup_docking_system``'s companion-wiring comment.

    **Test steps:**

    * construct a real ``MainWindow`` and rebuild the dynamic tail as ``aboutToShow`` would
    * verify ``documents_action`` is in the menu, after the theme entries and before ``log_action``
    """
    window = MainWindow()
    qtbot.addWidget(window)
    ui = window._MainWindow__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    window._MainWindow__add_open_documents(ui.view_menu)  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    actions = ui.view_menu.actions()
    theme_titles = {"&Default", "&Light", "Dar&k"}

    assert ui.documents_action in actions
    last_theme = max(actions.index(action) for action in actions if action.text() in theme_titles)
    assert last_theme < actions.index(ui.documents_action) < actions.index(ui.log_action)


def test_the_view_menu_toggle_shows_and_hides_the_documents_dock(qtbot: QtBot) -> None:
    """Triggering the View menu's documents entry closes the (open-by-default) dock; triggering it
    again reopens it (#268).

    The entry is ``documents_action``, the companion -- its ``triggered`` is wired straight to the
    dock's real toggle action by ``ActionIconThemeHandler``, so this pins that the companion actually
    drives visibility, not merely that it sits in the right place.

    **Test steps:**

    * construct a real ``MainWindow`` and find ``documents_action`` in the View menu
    * trigger it and verify the dock closed
    * trigger it again and verify the dock reopened
    """
    window = MainWindow()
    qtbot.addWidget(window)
    ui = window._MainWindow__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    toggle = ui.documents_action
    assert toggle in ui.view_menu.actions()

    toggle.trigger()
    assert documents_dock_widget(window).isClosed()

    toggle.trigger()
    assert not documents_dock_widget(window).isClosed()


@mark.parametrize(
    ("method", "dock_method", "argument"),
    [
        ("open_file", "open_document", "a.rehu"),
        ("open_folder", "open_folder", "a_folder"),
        ("open_archive", "open_archive", "a.zip"),
    ],
)
def test_every_open_funnel_reopens_a_closed_documents_dock(
    method: str, dock_method: str, argument: str, mocker: MockerFixture, qtbot: QtBot
) -> None:
    """Opening anything shows the Documents dock the user had closed (#268).

    The three funnels are covered together because every outside route -- the ``File`` dialogs,
    ``Open recents``, argv, the shell verbs, a ``QFileOpenEvent`` and the single-instance forward --
    reaches the documents area through one of them.

    **Test steps:**

    * mock the ``DocumentsDock`` method this funnel delegates to (the dock itself stays real)
    * construct a ``MainWindow`` and close its Documents dock
    * call the funnel
    * verify the dock is open again
    """
    mocker.patch(f"rehuco_agent.main_window.DocumentsDock.{dock_method}")
    window = MainWindow()
    qtbot.addWidget(window)
    documents_dock_widget(window).toggleView(False)

    getattr(window, method)(argument)

    assert not documents_dock_widget(window).isClosed()


def test_picking_a_document_from_the_view_menu_reopens_a_closed_documents_dock(
    dock_entries: Callable[[MainWindow], list[Any]], mocker: MockerFixture, qtbot: QtBot
) -> None:
    """The ``View`` menu's open-documents list reveals the Documents dock before focusing the picked
    document (#268) -- otherwise the row the user just clicked would appear to do nothing.

    **Test steps:**

    * construct ``MainWindow``, stand in one open document, and close the Documents dock
    * populate the docks menu and trigger its single entry
    * verify the dock is open again and ``DocumentsDock.focus_document`` was called with the widget
    """
    window = MainWindow()
    qtbot.addWidget(window)
    widget = mocker.MagicMock(model=mocker.MagicMock(label="Solo", path=Path("/solo/info.rehu"), dirty=False))
    widget.save_state.return_value = b"snapshot"  # keeps teardown's implicit close() from choking on a MagicMock
    documents_dock = window._MainWindow__documents_dock  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    mocker.patch.object(documents_dock, "open_document_widgets", return_value=[widget])
    focus_document = mocker.patch.object(documents_dock, "focus_document")
    documents_dock_widget(window).toggleView(False)

    window._MainWindow__add_open_documents(window._MainWindow__ui.view_menu)  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    dock_entries(window)[0].trigger()

    assert not documents_dock_widget(window).isClosed()
    focus_document.assert_called_once_with(widget)


def test_opening_a_file_raises_a_floating_documents_dock(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A Documents dock torn out into its own window is raised and activated by an open, not merely
    fronted as a tab (#268) -- a floating window behind this one is as invisible as a closed dock.

    The binding exposes only ``QWidget.raise_`` on a dock, not ADS's ``CDockWidget::raise()``, so the
    reveal raises the floating container itself; this pins that it does.

    **Test steps:**

    * construct ``MainWindow``, float its Documents dock, and spy on the container's raise/activate
    * ``open_file`` with a mocked ``DocumentsDock.open_document``
    * verify the container was raised and activated, and the dock is open
    """
    mocker.patch("rehuco_agent.main_window.DocumentsDock.open_document")
    window = MainWindow()
    qtbot.addWidget(window)
    dock_manager = window._MainWindow__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    container = dock_manager.addDockWidgetFloating(documents_dock_widget(window))
    raise_ = mocker.patch.object(container, "raise_")
    activate_window = mocker.patch.object(container, "activateWindow")

    window.open_file("a.rehu")

    raise_.assert_called_once_with()
    activate_window.assert_called_once_with()
    assert not documents_dock_widget(window).isClosed()


def test_opening_a_file_makes_its_document_current_in_the_reopened_dock(qtbot: QtBot) -> None:
    """The reveal is not the whole story: the document opened into the reopened dock is the current
    one, so what was just opened is what is on screen (#268).

    Opens a path that does not exist, which yields a real (locked) document dock
    ([[data-model#write-integrity]]) -- the point here is which dock is current, not what was read.

    **Test steps:**

    * construct a ``MainWindow``, close its Documents dock, and open two missing paths
    * verify the dock is open and the *second* path is the focused document
    """
    window = MainWindow()
    qtbot.addWidget(window)
    documents_dock = window._MainWindow__documents_dock  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    documents_dock_widget(window).toggleView(False)

    window.open_file("first_missing.rehu")
    window.open_file("second_missing.rehu")

    assert not documents_dock_widget(window).isClosed()
    assert documents_dock.focused_document_path() == Path("second_missing.rehu").resolve()


def test_restoring_the_session_reveals_the_documents_dock(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Session restore reveals the dock before handing the session to ``DocumentsDock`` (#268, #66).

    Asserted by call order rather than by the end state: ``__init__`` restores the outer layout
    *afterwards*, which is what actually decides the dock's visibility on a launch (see the test
    below), so "is it open now" cannot tell the reveal from the restore.

    **Test steps:**

    * record the order in which the reveal and ``DocumentsDock.restore_session`` are called
    * construct a ``MainWindow``
    * verify the session was restored, and the reveal came first
    """
    calls: list[str] = []
    mocker.patch.object(
        MainWindow,
        "_MainWindow__reveal_documents_dock",
        side_effect=lambda: calls.append("reveal"),
    )
    mocker.patch(
        "rehuco_agent.main_window.DocumentsDock.restore_session",
        side_effect=lambda _session: calls.append("restore_session"),
    )

    window = MainWindow()
    qtbot.addWidget(window)

    assert calls == ["reveal", "restore_session"]


def test_the_saved_theme_is_applied_before_the_session_is_restored(mocker: MockerFixture, qtbot: QtBot) -> None:
    """The saved theme is applied before any restored document is built (#304).

    The other order built every restored document's chrome against a palette that was about to be
    replaced, leaving each one to catch up through a ``palette_changed`` round-trip afterwards -- the
    fragility that #304's stale toolbar glyphs grew out of. Constructing ``ThemeModel`` is what applies
    the theme, so its ``setColorScheme`` call has to land before ``DocumentsDock.restore_session``.

    **Test steps:**

    * record the order in which ``QStyleHints.setColorScheme`` and ``DocumentsDock.restore_session``
      are called
    * construct a ``MainWindow``
    * verify the session was restored, and the theme was applied first
    """
    calls: list[str] = []
    mocker.patch.object(
        QApplication.styleHints(),
        "setColorScheme",
        side_effect=lambda _scheme: calls.append("theme"),
    )
    mocker.patch(
        "rehuco_agent.main_window.DocumentsDock.restore_session",
        side_effect=lambda _session: calls.append("restore_session"),
    )

    window = MainWindow()
    qtbot.addWidget(window)

    assert "restore_session" in calls
    assert calls.index("theme") < calls.index("restore_session")


def test_a_documents_dock_left_closed_stays_closed_after_a_restart(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A Documents dock closed when the window closed is closed again on the next launch -- it rides
    the outer dock layout like every other dock, and the layout restore has the last word over the
    session's own reveal (#268).

    **Test steps:**

    * construct a window, close its Documents dock, and capture the real window state it saves
    * construct a second window seeded (via a mocked ``load``) with that saved state
    * verify the second window's Documents dock starts closed, unlike the open default
    """
    first = MainWindow()
    qtbot.addWidget(first)
    documents_dock_widget(first).toggleView(False)
    first._MainWindow__save_window_state()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    saved = first._MainWindow__window_settings  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    def fake_load(self: MainWindowSettings, settings: object) -> None:
        del settings
        self.outer_docks_state = saved.outer_docks_state

    mocker.patch.object(MainWindowSettings, "load", fake_load)

    second = MainWindow()
    qtbot.addWidget(second)

    assert documents_dock_widget(second).isClosed()


def test_an_unusable_saved_layout_leaves_the_documents_dock_open(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A saved layout that cannot be applied leaves the window's own default standing, Documents dock
    open and placed (#268).

    This is what the :data:`~rehuco_agent.settings.main_window_settings.OUTER_DOCKS_STATE_VERSION`
    bump buys: a v3 blob describes this area as a *central widget*, a structure the manager no longer
    has, so it is discarded at load rather than restored into a shell with no central area. Here the
    blob is refused one step later, by ``CDockManager.restoreState`` itself, which pins the same
    guarantee without having to forge a layout the current shell can no longer produce.

    **Test steps:**

    * seed ``MainWindowSettings.load`` with a blob that is not a dock layout at all
    * construct a ``MainWindow``
    * verify the Documents dock is open and placed in an area
    """

    def fake_load(self: MainWindowSettings, settings: object) -> None:
        del settings
        self.outer_docks_state = b"not a dock layout"

    mocker.patch.object(MainWindowSettings, "load", fake_load)

    window = MainWindow()
    qtbot.addWidget(window)

    dock = documents_dock_widget(window)
    assert not dock.isClosed()
    assert dock.dockAreaWidget() is not None


def test_an_unusable_saved_layout_leaves_the_settings_dock_as_built(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A saved layout that cannot be applied leaves the Settings dock exactly where the window put it
    -- a closed tab in the Documents area, in no window of its own (#307).

    The startup path that used to float it as a fallback, and the reason that fallback could go: the
    dock is placed once and never re-placed, so a refused blob costs nothing to recover from and
    builds no `CFloatingDockContainer` for QtAds to leave behind
    ([[appendices.qt-ads#auto-hide-abandoned-float]]).

    **Test steps:**

    * seed ``MainWindowSettings.load`` with a blob that is not a dock layout at all
    * construct a ``MainWindow``
    * verify the Settings dock is closed, still tabbed beside Documents, and nothing floats
    """

    def fake_load(self: MainWindowSettings, settings: object) -> None:
        del settings
        self.outer_docks_state = b"not a dock layout"

    mocker.patch.object(MainWindowSettings, "load", fake_load)

    window = MainWindow()
    qtbot.addWidget(window)

    dock_manager = window._MainWindow__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    settings_dock = dock_manager.findDockWidget(SETTINGS_DIALOG_OBJECT_NAME)
    assert settings_dock is not None
    assert settings_dock.isClosed()
    assert settings_dock.dockAreaWidget() is documents_dock_widget(window).dockAreaWidget()
    assert window.findChildren(QtAds.CFloatingDockContainer) == []


def splitter_sizes(window: MainWindow) -> list[int]:
    """The heights of the Documents dock's own splitter panes -- Documents first, then each bottom
    dock (#268).

    :param window: the window to read.
    :returns: the pane sizes, in splitter order.
    """
    dock_manager = window._MainWindow__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    return list(dock_manager.splitterSizes(documents_dock_widget(window).dockAreaWidget()))


def shown_with_every_app_dock_open(window: MainWindow) -> None:
    """Show ``window`` and open its Log and Tasks docks, so the three-pane split is real and measurable.

    These tests are the deliberate exception to this module's "never ``.show()`` a ``MainWindow``" rule
    (which is about ``isVisible()`` lying under an unshown ancestor): the seeding under test *only*
    happens on a real show, because a splitter that has never been laid out refuses to be sized. The
    suite runs offscreen, so nothing appears.

    :param window: the window to show.
    """
    window.show()
    log_dock(window).toggleView(True)
    task_queue_dock(window).toggleView(True)


def test_the_first_show_gives_the_documents_dock_the_bulk_of_a_fresh_layout(qtbot: QtBot) -> None:
    """With every app dock open on a fresh layout, the Documents dock keeps most of the height and the
    Log and Tasks docks get a strip each (#268).

    Without this, dropping the central widget made the documents area just another splitter pane sized
    from its content's hint -- and an empty one hints small where a ``LogWidget``'s table hints large,
    so the log ended up with the window and the thing it is a log *of* with a sliver.

    **Test steps:**

    * construct a real ``MainWindow`` with nothing persisted, show it, and open both bottom docks
    * verify the Documents pane is larger than both bottom panes put together
    """
    window = MainWindow()
    qtbot.addWidget(window)

    shown_with_every_app_dock_open(window)

    documents, *bottom = splitter_sizes(window)
    assert len(bottom) == 2
    assert documents > sum(bottom)


def test_a_restored_layout_is_not_reseeded_on_show(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A layout that actually restored keeps its own splitter sizes -- the seed is a default for a
    fresh window, not a policy imposed on a remembered one (#268).

    **Test steps:**

    * show a window with every app dock open, drag the split log-heavy, and capture the state it saves
    * construct a second window seeded (via a mocked ``load``) with that saved state, and show it
    * verify the Documents pane is still the smaller one, not re-seeded to the fresh-layout default
    """
    first = MainWindow()
    qtbot.addWidget(first)
    shown_with_every_app_dock_open(first)
    dock_manager = first._MainWindow__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    total = sum(splitter_sizes(first))
    log_heavy = [total // 8, total // 2, total - total // 8 - total // 2]
    dock_manager.setSplitterSizes(documents_dock_widget(first).dockAreaWidget(), log_heavy)
    first._MainWindow__save_window_state()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    saved = first._MainWindow__window_settings  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    def fake_load(self: MainWindowSettings, settings: object) -> None:
        del settings
        self.outer_docks_state = saved.outer_docks_state

    mocker.patch.object(MainWindowSettings, "load", fake_load)

    second = MainWindow()
    qtbot.addWidget(second)
    second.show()

    documents, *bottom = splitter_sizes(second)
    assert documents < sum(bottom)


def test_a_later_show_does_not_reseed_a_split_the_user_has_dragged(qtbot: QtBot) -> None:
    """The seed runs once. A window hidden to tray and shown again (:meth:`MainWindow.show`, via
    ``raise_and_activate`` or the tray's own un-hide) keeps the split the user dragged (#268).

    **Test steps:**

    * show a window with every app dock open, then drag the split log-heavy
    * hide and show it again
    * verify the dragged sizes are still in place
    """
    window = MainWindow()
    qtbot.addWidget(window)
    shown_with_every_app_dock_open(window)
    dock_manager = window._MainWindow__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    total = sum(splitter_sizes(window))
    log_heavy = [total // 8, total // 2, total - total // 8 - total // 2]
    dock_manager.setSplitterSizes(documents_dock_widget(window).dockAreaWidget(), log_heavy)

    window.hide()
    window.show()

    documents, *bottom = splitter_sizes(window)
    assert documents < sum(bottom)


# endregion

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


def test_the_log_dock_hosts_its_widget_directly_not_in_a_scroll_area(qtbot: QtBot) -> None:
    """The log dock's own table already manages its header and rows -- an outer scroll area would drag
    that header along with the rows instead (#305).

    **Test steps:**

    * construct a real ``MainWindow``
    * verify the dock's content is parented directly on the dock, with no scroll area between them
    """
    window = MainWindow()
    qtbot.addWidget(window)

    dock = log_dock(window)

    assert dock.widget().parentWidget() is dock


def test_the_log_dock_has_a_minimum_height_a_splitter_drag_cant_cross(qtbot: QtBot) -> None:
    """A squeezed log dock still reads, rather than shrinking to a sliver.

    **Test steps:**

    * construct a real ``MainWindow``
    * verify the dock's own minimum size hint reports the configured floor
    """
    window = MainWindow()
    qtbot.addWidget(window)

    dock = log_dock(window)

    assert dock.minimumSizeHint().height() == LOG_DOCK_MIN_HEIGHT


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


def test_the_log_dock_toggle_sits_ahead_of_theme_and_settings_on_the_action_bar(qtbot: QtBot) -> None:
    """The log and task queue toggles are on the action bar ahead of the theme action, and the
    settings dock's toggle closes the bar -- log before tasks (#202 added the second one alongside the
    log's; #311 moved both above theme).

    **Test steps:**

    * construct a real ``MainWindow``
    * read the action bar's actions in order
    * verify both app-dock toggles precede theme, log before tasks, and settings stays last
    """
    window = MainWindow()
    qtbot.addWidget(window)
    ui = window._MainWindow__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    dock_manager = window._MainWindow__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    settings_dock = dock_manager.findDockWidget(SETTINGS_DIALOG_OBJECT_NAME)

    actions = ui.action_bar.actions()
    log_toggle = log_dock(window).toggleViewAction()
    tasks_toggle = task_queue_dock(window).toggleViewAction()

    assert actions.index(log_toggle) < actions.index(tasks_toggle)
    assert actions.index(tasks_toggle) < actions.index(ui.theme_action)
    assert actions.index(ui.theme_action) < actions.index(settings_dock.toggleViewAction())


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
    in the bottom group below the log toggle (#71; #311 moved the dock toggles above both).

    **Test steps:**

    * construct a real ``MainWindow``
    * read the action bar's actions in order
    * verify the toggle sits after theme, and the log dock's own toggle precedes both
    """
    window = MainWindow()
    qtbot.addWidget(window)
    ui = window._MainWindow__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    actions = ui.action_bar.actions()

    assert actions.index(log_dock(window).toggleViewAction()) < actions.index(ui.theme_action)
    assert actions.index(ui.theme_action) < actions.index(ui.image_previews_toggle_action)


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


def test_close_event_saves_the_tasks_dock_s_nested_layout(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Closing the app saves the Tasks dock's own sub-dock layout, not just the outer one (#276).

    The outer manager's ``saveState()`` records where the Tasks dock sits; what its *nested* shell looks
    like inside is a blob of the shell's own.

    **Test steps:**

    * construct ``MainWindow``
    * mock ``MainWindowSettings.save`` and dispatch a close event
    * verify a non-empty task queue state was recorded
    """
    window = MainWindow()
    qtbot.addWidget(window)
    save = mocker.patch.object(MainWindowSettings, "save")
    event = QCloseEvent()

    window.closeEvent(event)

    window_settings = window._MainWindow__window_settings  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert window_settings.task_queue_state != b""
    save.assert_called_once()


def test_the_tasks_dock_s_nested_layout_is_restored_on_start(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A restart brings the Tasks dock's Log sub-dock back open if that is how it was left (#276).

    **Test steps:**

    * open the Log sub-dock on one window's Tasks shell and save that shell's state
    * seed ``MainWindowSettings.load`` with it and construct a second window
    * verify the sub-dock came back open
    """
    source = MainWindow()
    qtbot.addWidget(source)
    source_widget = task_queue_dock(source).widget()
    source_log_dock = source_widget._TaskQueueWidget__log_dock  # type: ignore[attr-defined]  # pylint: disable=protected-access
    source_log_dock.toggleView(True)
    saved = source_widget.save_state()

    def fake_load(self: MainWindowSettings, settings: object) -> None:
        del settings
        self.task_queue_state = saved

    mocker.patch.object(MainWindowSettings, "load", fake_load)

    window = MainWindow()
    qtbot.addWidget(window)

    widget = task_queue_dock(window).widget()
    log_dock = widget._TaskQueueWidget__log_dock  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert log_dock.isClosed() is False


# endregion


# region pinned docks (#279)

MAIN_DOCK_NAMES: Final = (
    DOCUMENTS_DOCK_OBJECT_NAME,
    LOG_DOCK_OBJECT_NAME,
    TASK_QUEUE_DOCK_OBJECT_NAME,
    SETTINGS_DIALOG_OBJECT_NAME,
)
"""The window's four own docks -- the set pinning is an affordance of."""

PIN_BUTTON_WAIT: Final = 10_000
"""How long a wait for the pin-button suppressor is given. Generous on purpose: the suppressor's hide
is deferred by one turn of the event loop, and the first wait in a Qt test can spend seconds draining
a backlog of ``deleteLater`` calls left by earlier tests, so the gate has to outlast that rather than
the work it is actually waiting for."""


@fixture(autouse=True)
def auto_hide_flags() -> Iterator[None]:
    """Turn QtAds' pinning on for the duration of one test, and put the flags back afterwards.

    The flags are a `CDockManager` **static**, normally set in ``Application.show_main_window`` --
    which these tests never run -- and leaving them on would decide the behaviour of every later test
    in the session. New areas honour a flag set after the first manager was built (verified), so this
    needs no session-wide ordering.
    """
    previous = QtAds.CDockManager.autoHideConfigFlags()
    flags = QtAds.CDockManager.eAutoHideFlag
    QtAds.CDockManager.setAutoHideConfigFlags(flags.DefaultAutoHideConfig | flags.AutoHideShowOnMouseOver)
    yield
    QtAds.CDockManager.setAutoHideConfigFlags(previous)


def main_dock(window: MainWindow, name: str) -> Any:
    """Find one of the window's own docks on the outer manager by object name.

    :param window: the window to read.
    :param name: the dock's object name.
    :returns: the dock.
    """
    dock_manager = window._MainWindow__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    return dock_manager.findDockWidget(name)


def test_every_main_dock_is_pinnable(qtbot: QtBot) -> None:
    """All four of the window's own docks can be collapsed into a sidebar (#279).

    One flag, set the same way in all four builders since #307 made the Settings dock a plain
    ``CDockWidget`` like its three siblings -- it used to be the exception, turning pinning on by hand
    after a framework that knew nothing of sidebars had built it.

    **Test steps:**

    * construct a real ``MainWindow``
    * verify each of the four docks carries ``DockWidgetPinnable``
    """
    window = MainWindow()
    qtbot.addWidget(window)

    pinnable = QtAds.CDockWidget.DockWidgetFeature.DockWidgetPinnable

    assert [bool(main_dock(window, name).features() & pinnable) for name in MAIN_DOCK_NAMES] == [True] * 4


def dict_backed_settings(settings: Any) -> dict[str, Any]:
    """Give the mocked ``persistent_settings()`` real, group-aware storage for one test.

    :func:`mock_persistent_settings` hands back a ``MagicMock`` whose ``value`` returns the default it
    was asked for -- right for the windows that must not read anything, and useless for a test about
    something *surviving* a save and a load. This wires the four calls that matter onto one dict,
    honouring ``beginGroup`` so each dock's key stays its own (without it every handler would write the
    same bare ``pin_side`` and the test would pass for the wrong reason).

    :param settings: the ``QSettings`` stand-in to wire up -- ``mock_persistent_settings.return_value``.
    :returns: the backing dict, for asserting on what was written.
    """
    store: dict[str, Any] = {}
    state = {"group": ""}
    settings.beginGroup.side_effect = lambda name: state.__setitem__("group", f"{name}/")
    settings.endGroup.side_effect = lambda: state.__setitem__("group", "")
    settings.setValue.side_effect = lambda key, value: store.__setitem__(state["group"] + key, value)
    settings.remove.side_effect = lambda key: store.pop(state["group"] + key, None)
    settings.value.side_effect = lambda key, default=None, type=None: store.get(  # noqa: A002
        state["group"] + key, default
    )
    return store


def test_every_main_dock_starts_on_the_default_sidebar(qtbot: QtBot) -> None:
    """A dock nobody has pinned yet sends its first pin to :data:`DEFAULT_PIN_SIDE` (#279).

    **Test steps:**

    * construct a real ``MainWindow`` with nothing remembered
    * verify every main dock's preferred sidebar is the default one
    """
    window = MainWindow()
    qtbot.addWidget(window)

    sides = [main_dock(window, name).preferredAutoHideSideBarLocation() for name in MAIN_DOCK_NAMES]

    assert sides == [DEFAULT_PIN_SIDE] * 4


def test_a_dock_dropped_on_a_sidebar_pins_back_there(qtbot: QtBot) -> None:
    """Unpinning and re-pinning returns a dock to where the user last put it, not to the default (#279).

    The bug this memory exists for. Exercised through
    ``CDockManager.addAutoHideDockWidget(location, dock)`` -- the entry point a drop overlay calls with
    the border it was dropped on -- rather than a synthesized mouse drag, which offscreen cannot
    deliver. QtAds writes back none of this itself: the preferred side it would otherwise keep is the
    default, and the button reads only that.

    **Test steps:**

    * construct a real ``MainWindow`` and drop the Log dock on the right-hand sidebar
    * unpin it, then pin it again the way its title-bar button does
    * verify it landed on the right both times
    """
    window = MainWindow()
    qtbot.addWidget(window)
    log = log_dock(window)
    log.toggleView(True)
    dock_manager = window._MainWindow__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    dock_manager.addAutoHideDockWidget(QtAds.SideBarRight, log)
    assert log.autoHideLocation() == QtAds.SideBarRight

    log.setAutoHide(False)
    log.setAutoHide(True)

    assert log.autoHideLocation() == QtAds.SideBarRight


def test_the_remembered_side_survives_a_restart(qtbot: QtBot, mock_persistent_settings: Any) -> None:
    """Where a dock was last pinned is written on close and picked up by the next window (#279).

    Asserted with the dock left **unpinned** at close, which is the case the saved layout cannot cover
    on its own: a blob that records no pin says nothing about where the next one should go.

    **Test steps:**

    * back the settings stand-in with real storage
    * pin one window's Log dock to the right, unpin it, and close the window
    * construct a second window against the same storage
    * verify its Log dock pins to the right without being told
    """
    store = dict_backed_settings(mock_persistent_settings.return_value)
    source = MainWindow()
    qtbot.addWidget(source)
    source_log = log_dock(source)
    source_log.toggleView(True)
    source_manager = source._MainWindow__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    source_manager.addAutoHideDockWidget(QtAds.SideBarRight, source_log)
    source_log.setAutoHide(False)
    source.closeEvent(QCloseEvent())
    assert store[f"{DOCK_PIN_SIDES_GROUP}/{LOG_DOCK_OBJECT_NAME}/{PIN_SIDE_KEY}"] == "right"

    window = MainWindow()
    qtbot.addWidget(window)

    assert log_dock(window).preferredAutoHideSideBarLocation() == QtAds.SideBarRight


def test_a_dock_nobody_pinned_stores_no_side(qtbot: QtBot, mock_persistent_settings: Any) -> None:
    """A dock nobody has pinned writes no key at all, rather than today's default (#279).

    What keeps :data:`DEFAULT_PIN_SIDE` the authority for such a dock: a stored ``left`` would read as
    a choice the user made, and a later change to that constant would reach fresh installs only.

    **Test steps:**

    * construct a real ``MainWindow``, pin only the Log dock, and close it
    * verify the Log dock's side was written and the Tasks dock's key was removed
    """
    window = MainWindow()
    qtbot.addWidget(window)
    log = log_dock(window)
    log.toggleView(True)
    log.setAutoHide(True)

    window.closeEvent(QCloseEvent())

    settings = mock_persistent_settings.return_value
    written = {call.args[0] for call in settings.setValue.call_args_list}
    removed = {call.args[0] for call in settings.remove.call_args_list}
    assert PIN_SIDE_KEY in written
    assert PIN_SIDE_KEY in removed


def test_pinning_the_log_dock_puts_it_in_the_sidebar(qtbot: QtBot) -> None:
    """Pinning collapses a dock into a sidebar tab naming it (#279).

    **Test steps:**

    * construct a real ``MainWindow`` and reveal the Log dock
    * pin it
    * verify the configured sidebar holds one tab, titled after the dock
    """
    window = MainWindow()
    qtbot.addWidget(window)
    log = log_dock(window)
    log.toggleView(True)

    log.setAutoHide(True)

    dock_manager = window._MainWindow__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    side_bar = dock_manager.autoHideSideBar(QtAds.SideBarLeft)
    assert log.isAutoHide()
    assert side_bar.count() == 1
    assert side_bar.tab(0).text() == LOG_DOCK_TITLE


def test_a_pinned_dock_still_reads_as_open(qtbot: QtBot) -> None:
    """A pinned dock is put away, not closed -- so the ``View`` menu must still tick it (#279, #79).

    Both readings are asserted, because both are consulted: the dock's own ``isClosed()`` and the
    toggle action's checked state, which is what the menu companion mirrors.

    **Test steps:**

    * construct a real ``MainWindow``, reveal the Log dock and pin it
    * verify it reads as not closed, and its toggle action stays checked
    """
    window = MainWindow()
    qtbot.addWidget(window)
    log = log_dock(window)
    log.toggleView(True)

    log.setAutoHide(True)

    assert log.isClosed() is False
    assert log.toggleViewAction().isChecked() is True


def test_toggling_a_pinned_dock_off_and_on_leaves_it_pinned(qtbot: QtBot) -> None:
    """The toolbar toggle puts a pinned dock away and brings it back **still pinned** (#279).

    Which is what the toggle should do: it answers "is this dock in play", and pinning is where a
    dock in play sits -- so hiding one is not a decision to un-pin it. Asserted rather than assumed,
    because the toggle action is QtAds' own and its reading of a pinned dock is the thing #279 had to
    check ([[appendices.qt-ads#auto-hide-toggle-view]]).

    **Test steps:**

    * construct a real ``MainWindow``, reveal the Log dock and pin it
    * trigger its toggle action twice, letting the queued work between them run
    * verify it is back, still pinned to the same sidebar, and its tab is there again
    """
    window = MainWindow()
    qtbot.addWidget(window)
    log = log_dock(window)
    log.toggleView(True)
    log.setAutoHide(True)
    action = log.toggleViewAction()

    action.trigger()
    QApplication.processEvents()
    action.trigger()
    QApplication.processEvents()

    dock_manager = window._MainWindow__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert log.isClosed() is False
    assert log.isAutoHide() is True
    assert log.autoHideLocation() == QtAds.SideBarLeft
    assert dock_manager.autoHideSideBar(QtAds.SideBarLeft).count() == 1


def test_opening_a_file_slides_a_collapsed_pinned_documents_dock_out(mocker: MockerFixture, qtbot: QtBot) -> None:
    """An open reaches a document even when the Documents dock is pinned and collapsed (#279, #268).

    #268's guarantee is that any open *shows* the dock. A pinned dock collapsed into its sidebar tab
    is as invisible as a closed one, and the reveal's ``toggleView(True)`` is QtAds' own -- so whether
    it expands an auto-hide container, rather than treating a not-closed dock as already shown, is
    exactly what this pins.

    **Test steps:**

    * construct ``MainWindow``, pin its Documents dock and collapse the sidebar container
    * ``open_file`` with a mocked ``DocumentsDock.open_document``
    * verify the dock is still pinned, and its auto-hide container is expanded (no longer hidden)

    ``isHidden()``, not ``isVisible()``: the window is never shown here, like every ``MainWindow``
    test, and under an unshown ancestor ``isVisible()`` is false whatever the container is doing.
    """
    mocker.patch("rehuco_agent.main_window.DocumentsDock.open_document")
    window = MainWindow()
    qtbot.addWidget(window)
    docs = documents_dock_widget(window)
    docs.setAutoHide(True)
    QApplication.processEvents()
    docs.autoHideDockContainer().collapseView(True)
    QApplication.processEvents()
    assert docs.autoHideDockContainer().isHidden() is True

    window.open_file("a.rehu")
    QApplication.processEvents()

    assert docs.isAutoHide() is True
    assert docs.autoHideDockContainer().isHidden() is False


def test_a_pinned_layout_survives_a_restart(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Which docks are pinned, and where, is part of the saved outer layout (#279).

    **Test steps:**

    * pin one window's Log dock and capture its outer layout through ``closeEvent``
    * seed ``MainWindowSettings.load`` with that blob and construct a second window
    * verify the Log dock comes back pinned to the same sidebar
    """
    source = MainWindow()
    qtbot.addWidget(source)
    source_log = log_dock(source)
    source_log.toggleView(True)
    source_log.setAutoHide(True)
    source.closeEvent(QCloseEvent())
    source_settings = source._MainWindow__window_settings  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    saved = source_settings.outer_docks_state

    def fake_load(self: MainWindowSettings, settings: object) -> None:
        del settings
        self.outer_docks_state = saved

    mocker.patch.object(MainWindowSettings, "load", fake_load)

    window = MainWindow()
    qtbot.addWidget(window)

    restored = log_dock(window)
    assert restored.isAutoHide() is True
    assert restored.autoHideLocation() == QtAds.SideBarLeft


def test_the_tasks_shells_sub_docks_are_not_pinnable(qtbot: QtBot) -> None:
    """Pinning stays a main-window affordance: a nested shell's sub-docks carry no pin button (#279).

    The nested manager's button comes from the same process-wide flag as the window's own, so this is
    what `QtAdsAutoHideButtonSuppressor` is installed for -- and the main Tasks dock's own button
    staying put is asserted beside it, since a suppressor that reached too far would look identical
    otherwise.

    **Test steps:**

    * construct a real ``MainWindow`` and reveal the Tasks dock and its Log sub-dock
    * verify both sub-dock areas' pin buttons end up hidden
    * verify the Tasks dock's own area still has one
    """
    window = MainWindow()
    qtbot.addWidget(window)
    tasks = task_queue_dock(window)
    tasks.toggleView(True)
    widget = tasks.widget()
    inner = widget._TaskQueueWidget__dock_manager  # type: ignore[attr-defined]  # pylint: disable=protected-access
    widget._TaskQueueWidget__log_dock.toggleView(True)  # type: ignore[attr-defined]  # pylint: disable=protected-access

    qtbot.waitUntil(
        lambda: (
            len(inner.openedDockAreas()) == 2
            and all(area.titleBarButton(QtAds.TitleBarButtonAutoHide).isHidden() for area in inner.openedDockAreas())
        ),
        timeout=PIN_BUTTON_WAIT,
    )

    assert not tasks.dockAreaWidget().titleBarButton(QtAds.TitleBarButtonAutoHide).isHidden()


def pinned_settings_layout(window: MainWindow, open_dock: bool) -> bytes:
    """Pin ``window``'s Settings dock into the main container's left sidebar and return the layout
    that saves (#306).

    ``addAutoHideDockWidget``, not ``dock.setAutoHide(True)``: the latter pins into the dock's own
    ``dockContainer()``, which for a floating dock is that floating window's sidebar rather than the
    main window's -- the wrong container entirely, and not the one the bug needs.

    ``__save_window_state()`` rather than ``closeEvent``, which would take the whole window down --
    the task queue included -- for a blob this only needs one method to produce.

    :param window: the window to pin and read.
    :param open_dock: whether the dock is left open (pinned and in play) or closed afterwards.
    :returns: the saved outer dock layout.
    """
    dock_manager = window._MainWindow__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    dock = main_dock(window, SETTINGS_DIALOG_OBJECT_NAME)
    dock.toggleView(True)
    dock_manager.addAutoHideDockWidget(QtAds.SideBarLeft, dock)
    QApplication.processEvents()
    dock.toggleView(open_dock)
    window._MainWindow__save_window_state()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    return window._MainWindow__window_settings.outer_docks_state  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def test_restoring_a_sidebar_pinned_settings_dock_creates_no_floating_window(
    mocker: MockerFixture, qtbot: QtBot
) -> None:
    """A launch whose saved layout pins the Settings dock to a sidebar builds no floating container
    at all -- the empty window that used to flash ahead of the main window (#306).

    The dock is placed **docked** and never floated by the window at all (#307), precisely so that
    nothing exists for QtAds' sidebar restore path to abandon: it is the one path
    that does not retire the container it took the dock out of, and the leftover then passes
    ``CDockManager::showEvent``'s own guard because it still holds one stale open area
    ([[appendices.qt-ads#auto-hide-abandoned-float]]).

    Asserted as *never created* rather than *not visible*, which is both stronger and what lets this
    keep the module's never-``show()`` rule. Through ``findChildren`` rather than
    ``dockManager().floatingWidgets()``: the manager has already dropped the container Qt still
    parents, so the manager's own list can be blind to the thing under test.

    **Test steps:**

    * pin one window's Settings dock into the left sidebar and capture the layout it saves
    * seed ``MainWindowSettings.load`` with that blob and construct a second window
    * verify the second window holds no floating container, and its Settings dock is pinned
    """
    first = MainWindow()
    qtbot.addWidget(first)
    saved = pinned_settings_layout(first, open_dock=True)

    def fake_load(self: MainWindowSettings, settings: object) -> None:
        del settings
        self.outer_docks_state = saved

    mocker.patch.object(MainWindowSettings, "load", fake_load)

    second = MainWindow()
    qtbot.addWidget(second)

    assert second.findChildren(QtAds.CFloatingDockContainer) == []
    assert main_dock(second, SETTINGS_DIALOG_OBJECT_NAME).isAutoHide() is True


def test_a_closed_pinned_settings_dock_restores_closed_and_pinned(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A Settings dock saved pinned *and* put away comes back both -- with still no floating
    container built along the way (#306, #55).

    The intersection of the two: #55's guarantee is that the layout restore has the last word on
    visibility, and #306's is that a sidebar placement leaves no window behind. A fix for one that
    floated the dock whenever it read as closed would satisfy neither.

    **Test steps:**

    * pin one window's Settings dock into the left sidebar, toggle it off, and capture the layout
    * seed ``MainWindowSettings.load`` with that blob and construct a second window
    * verify the second window's dock is closed, still pinned, and built no floating container
    """
    first = MainWindow()
    qtbot.addWidget(first)
    saved = pinned_settings_layout(first, open_dock=False)

    def fake_load(self: MainWindowSettings, settings: object) -> None:
        del settings
        self.outer_docks_state = saved

    mocker.patch.object(MainWindowSettings, "load", fake_load)

    second = MainWindow()
    qtbot.addWidget(second)

    restored = main_dock(second, SETTINGS_DIALOG_OBJECT_NAME)
    assert restored.isClosed() is True
    assert restored.isAutoHide() is True
    assert second.findChildren(QtAds.CFloatingDockContainer) == []


def test_a_floating_settings_dock_waits_for_the_main_window(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A Settings dock saved *floating and open* does not reach the screen before the window that
    owns it -- it comes up with :meth:`MainWindow.raise_and_activate`, above it (#306).

    The sibling of the sidebar case, and the one no amount of placement fixes: here the layout is
    right and the dock genuinely belongs in a window of its own, but
    ``CDockManager.restoreState`` shows that window the instant it applies the blob, and the restore
    has to run during ``__init__`` for the layout to land at all (#55). So the container is held back
    instead -- by `QtAdsFloatingShowGuard` while it is being created, which is what stops the native
    window ever being mapped, then on the same list ``hide_to_tray`` uses.

    Asserted through ``raise_and_activate`` rather than ``show()`` because that is how the app itself
    comes up (`Application.show_main_window`, `TrayIcon`), and it is what puts the docks back.

    The dock is floated **by hand** here, standing in for the user dragging it out: since #307 the
    window places it docked and never floats it itself, so a floating one in a saved layout is
    always a choice the user made. That it is Settings is incidental -- any dock the user tears out
    can be saved this way.

    **Test steps:**

    * float one window's Settings dock out, open, and capture the layout it saves
    * seed ``MainWindowSettings.load`` with that blob and construct a second window
    * verify its container exists but is not visible, and is queued for the window's own show
    * ``raise_and_activate`` and verify the floating dock is now up
    """
    first = MainWindow()
    qtbot.addWidget(first)
    float_open_settings_dock(first)
    first._MainWindow__save_window_state()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    saved = first._MainWindow__window_settings.outer_docks_state  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    def fake_load(self: MainWindowSettings, settings: object) -> None:
        del settings
        self.outer_docks_state = saved

    mocker.patch.object(MainWindowSettings, "load", fake_load)

    second = MainWindow()
    qtbot.addWidget(second)

    container = main_dock(second, SETTINGS_DIALOG_OBJECT_NAME).floatingDockContainer()
    deferred = second._MainWindow__floating_docks_hidden_with_window  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert container is not None
    assert container.isVisible() is False
    assert deferred == [container]

    second.raise_and_activate()

    assert container.isVisible() is True
    assert deferred == []


def test_a_restored_floating_dock_shows_after_the_main_window(mocker: MockerFixture, qtbot: QtBot) -> None:
    """The ordering guarantee, asserted on the events themselves rather than on visibility: the
    container's first *real* show comes after the main window's (#306).

    The sibling assertion to the test above, and the reason the guard is armed around
    ``raise_and_activate``'s show as well as around construction. QtAds can show a floating container
    from ``CDockManager::showEvent``, which fires while the owning window is still showing its
    children -- ahead of its own native window, measured on a real plugin.

    Telling a guarded show (attribute set, nothing mapped) from a real one is what makes this
    assertable at all: offscreen never paints, so the event order is what there is to read.

    **Test steps:**

    * float one window's Settings dock out, open, and capture the layout it saves
    * seed that blob and construct a second ``MainWindow`` under a spy recording every top-level
      ``Show`` and whether it was guarded
    * ``raise_and_activate`` and verify the container's first real show follows the window's
    """
    first = MainWindow()
    qtbot.addWidget(first)
    float_open_settings_dock(first)
    first._MainWindow__save_window_state()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    saved = first._MainWindow__window_settings.outer_docks_state  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    def fake_load(self: MainWindowSettings, settings: object) -> None:
        del settings
        self.outer_docks_state = saved

    mocker.patch.object(MainWindowSettings, "load", fake_load)
    shows: list[tuple[str, bool]] = []

    class ShowSpy(QObject):
        """Records each top-level ``Show`` with whether the guard had already marked it off-screen."""

        def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
            if event.type() == QEvent.Type.Show and isinstance(watched, QWidget) and watched.isWindow():
                shows.append((type(watched).__name__, watched.testAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)))
            return False

    spy = ShowSpy()
    app = QApplication.instance()
    assert app is not None
    app.installEventFilter(spy)
    try:
        window = MainWindow()
        qtbot.addWidget(window)
        window.raise_and_activate()
    finally:
        app.removeEventFilter(spy)

    container = main_dock(window, SETTINGS_DIALOG_OBJECT_NAME).floatingDockContainer()
    assert container is not None
    assert container.isVisible() is True
    real_shows = [name for name, guarded in shows if not guarded]
    assert real_shows.index("MainWindow") < real_shows.index("CFloatingDockContainer")


def test_a_restored_floating_dock_is_shown_at_once_with_the_window_on_windows(
    mocker: MockerFixture, qtbot: QtBot
) -> None:
    """On Windows, the window and each floating container put back by ``raise_and_activate`` are each
    shown with the desktop's open animation off and painted right after -- all before the window is
    raised -- so the dock neither sits empty over the window until the event loop drains nor fades in
    a beat behind it (#308).

    Only the *calls* are assertable here: the deferred paint is a ``WM_PAINT`` scheduling fact of the
    real ``windows`` plugin and the fade is the desktop's, neither of which offscreen reproduces, so
    the frame-by-frame check on a real launch is what confirms the effect and this pins the wiring
    that produces it.

    Same platform trap as ``test_raise_and_activate_forces_foreground_on_windows``: the window is built
    with the real platform still in effect, and ``sys.platform`` is faked only afterwards.

    **Test steps:**

    * float one window's Settings dock out, open, and capture the layout it saves
    * seed that blob and construct a second window with the real platform in effect
    * fake ``sys.platform`` to ``"win32"``, mock the three Windows-only helpers plus both ``show``\\ s
      and the window's ``raise_``, all on one recorder
    * ``raise_and_activate`` and verify the order: each show bracketed by the transition context and
      followed by its paint, then raise, then force foreground
    """
    first = MainWindow()
    qtbot.addWidget(first)
    float_open_settings_dock(first)
    first._MainWindow__save_window_state()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    saved = first._MainWindow__window_settings.outer_docks_state  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    def fake_load(self: MainWindowSettings, settings: object) -> None:
        del settings
        self.outer_docks_state = saved

    mocker.patch.object(MainWindowSettings, "load", fake_load)
    second = MainWindow()
    qtbot.addWidget(second)
    container = main_dock(second, SETTINGS_DIALOG_OBJECT_NAME).floatingDockContainer()
    assert container is not None

    mocker.patch("rehuco_agent.main_window.sys.platform", "win32")
    recorder = mocker.MagicMock()
    recorder.attach_mock(mocker.patch.object(second, "show"), "show")
    recorder.attach_mock(mocker.patch.object(container, "show"), "container_show")
    recorder.attach_mock(mocker.patch.object(second, "raise_"), "raise_")
    recorder.attach_mock(mocker.patch("borco_pyside.platforms.windows.window_painting.paint_now"), "paint_now")
    recorder.attach_mock(
        mocker.patch("borco_pyside.platforms.windows.window_activation.force_foreground"), "force_foreground"
    )

    @contextmanager
    def fake_no_fade(window: QWidget) -> Generator[None]:
        recorder.no_fade_enter(window)
        yield
        recorder.no_fade_exit(window)

    mocker.patch("borco_pyside.platforms.windows.window_transitions.open_transition_disabled", fake_no_fade)

    second.raise_and_activate()

    assert recorder.mock_calls == [
        mocker.call.no_fade_enter(second),
        mocker.call.show(),
        mocker.call.paint_now(second),
        mocker.call.no_fade_exit(second),
        mocker.call.no_fade_enter(container),
        mocker.call.container_show(),
        mocker.call.paint_now(container),
        mocker.call.no_fade_exit(container),
        mocker.call.raise_(),
        mocker.call.force_foreground(second),
    ]


def test_a_restored_floating_dock_is_shown_plainly_elsewhere(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Off Windows, neither Windows-only helper is reached for the window or a restored floating dock:
    the deferred first paint and the per-window fade are the Windows desktop's, and both helpers are
    Windows-only calls (#308).

    **Test steps:**

    * float one window's Settings dock out, open, and capture the layout it saves
    * seed that blob, fake ``sys.platform`` to ``"linux"``, construct a second window
    * ``raise_and_activate`` and verify the container came up and neither helper was called
    """
    first = MainWindow()
    qtbot.addWidget(first)
    float_open_settings_dock(first)
    first._MainWindow__save_window_state()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    saved = first._MainWindow__window_settings.outer_docks_state  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    def fake_load(self: MainWindowSettings, settings: object) -> None:
        del settings
        self.outer_docks_state = saved

    mocker.patch.object(MainWindowSettings, "load", fake_load)
    mocker.patch("rehuco_agent.main_window.sys.platform", "linux")
    paint_now = mocker.patch("borco_pyside.platforms.windows.window_painting.paint_now")
    no_fade = mocker.patch("borco_pyside.platforms.windows.window_transitions.open_transition_disabled")
    second = MainWindow()
    qtbot.addWidget(second)
    container = main_dock(second, SETTINGS_DIALOG_OBJECT_NAME).floatingDockContainer()
    assert container is not None

    second.raise_and_activate()

    assert container.isVisible() is True
    paint_now.assert_not_called()
    no_fade.assert_not_called()


# endregion


# region maximizing an outer dock over the window (#341)


def test_the_outer_tabs_draw_their_close_glyph(qtbot: QtBot) -> None:
    """The outer manager's own tabs get the close glyph a tracker draws (#341).

    That manager hosts every nested tracker's stylesheet, whose close-button rule zeroes the icon on
    every tab under it -- its own included -- so without a tracker of its own the outer [x] was an
    empty hit area (measured on screen).

    **Test steps:**

    * build the window, reveal the Log dock
    * verify its tab's close button carries the app's close glyph, squared, with no icon
    """
    window = MainWindow()
    qtbot.addWidget(window)
    log_dock(window).toggleView(True)
    close_button = tab_close_button(log_dock(window))
    assert close_button is not None

    qtbot.waitUntil(lambda: close_button.text() == TAB_CLOSE_GLYPH.codepoint, timeout=10_000)

    assert close_button.iconSize().width() == 0
    assert close_button.width() == close_button.height()


def test_an_outer_dock_maximizes_and_the_close_time_capture_reads_it_undone(
    mocker: MockerFixture, qtbot: QtBot
) -> None:
    """Each outer dock's tab carries the maximize toggle -- the Documents, Log, Tasks and Settings
    docks fill the window -- and the close-time outer-docks capture reads the layout with it undone
    (#341).

    The outermost of the three nested managers.

    **Test steps:**

    * show the window with the Log dock revealed beside the Documents dock, capture the outer layout
    * maximize the Log dock through its tab's button
    * dispatch a close event and verify the recorded outer state equals the un-maximized capture
    """
    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1000, 700)
    window.show()
    manager = window._MainWindow__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    handler = window._MainWindow__maximize_handler  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    log_dock(window).toggleView(True)
    log_area = log_dock(window).dockAreaWidget()
    assert log_area is not None
    # the baseline must be a settled layout: the window's first show and the reveal both re-divide
    # the strip on a later turn of the event loop, and a capture before that differs from every
    # later one whether or not anything is maximized in between
    qtbot.wait(100)
    unmaximized = bytes(manager.saveState().data())
    qtbot.waitUntil(lambda: handler.button(log_dock(window)) is not None, timeout=10_000)
    button = handler.button(log_dock(window))
    assert button is not None
    mocker.patch.object(MainWindowSettings, "save")
    button.click()
    assert manager.openedDockAreas() == [log_area]

    window.closeEvent(QCloseEvent())

    window_settings = window._MainWindow__window_settings  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert window_settings.outer_docks_state == unmaximized


# endregion
