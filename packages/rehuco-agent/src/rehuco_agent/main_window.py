"""Top-level `QtAds` dock-in-dock shell hosting the open-documents area ([[plugins#toolkit-surfaces]])."""

import logging
import sys
from pathlib import Path
from typing import Final, override

import PySide6QtAds as QtAds
from borco_pyside.dialogs import DockableDialog, DockableDialogManager
from borco_pyside.logging import LogWidget
from borco_pyside.theming import ActionIconThemeHandler, ThemeManager, ThemeMenu, ThemeModel
from PySide6.QtCore import QByteArray
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QWidget,
    QWidgetAction,
)
from rehuco_core import FINISHED_JOB_STATES, JobState, TaskQueue

from .app_logging import LOG_VIEW_ICON_RESOURCE, build_log_widget, shared_log_bridge
from .archives import ARCHIVE_EXTENSIONS
from .documents.confirm_and_save_dirty import confirm_and_save_dirty
from .documents.document_widget import DocumentWidget
from .documents.documents_dock import DocumentsDock
from .documents.rehu_document_menu_entry import RehuDocumentMenuEntry
from .documents.rehu_document_model import path_label
from .documents.save_or_prompt_retry import save_or_prompt_retry
from .main_window_ui import Ui_MainWindow
from .settings.document_session_settings import DocumentSessionSettings
from .settings.logs_settings import shared_logs_settings
from .settings.main_window_settings import TOOLBARS_STATE_VERSION, MainWindowSettings
from .settings.persistent_settings import persistent_settings
from .settings.recent_files_settings import RecentFilesSettings
from .settings.tasks_settings import TasksSettings
from .settings.theme_settings import ThemeSettings
from .settings.ui.descriptions_page import DescriptionsPage
from .settings.ui.excluded_files_page import ExcludedFilesPage
from .settings.ui.identity_page import IdentityPage
from .settings.ui.images_page import ImagesPage
from .settings.ui.logs_page import LogsPage
from .settings.ui.settings_dialog import SettingsDialog
from .settings.ui.tasks_page import TasksPage
from .settings.ui.videos_page import VideosPage
from .tasks import TaskQueueStore, TaskQueueWidget

LOG: Final = logging.getLogger(__name__)

SETTINGS_DIALOG_OBJECT_NAME: Final = "settings_dialog"
SETTINGS_ICON_RESOURCE: Final = ":/icons/app_settings.svg"

LOG_DOCK_OBJECT_NAME: Final = "log_dock"
"""The app-wide log dock's ``objectName`` -- its identity in the outer `CDockManager`'s saved layout.

A fixed literal, like the settings dock's: this is the one dock on that manager that is not about a
document, so nothing here derives from a path and nothing resyncs on a rename (#52's dock-identity
resync is document-scoped)."""

LOG_DOCK_TITLE: Final = "Log"

TASK_QUEUE_DOCK_OBJECT_NAME: Final = "task_queue_dock"
"""The app-wide task queue dock's ``objectName`` -- a fixed literal, the same reason the log dock's is
(#202): this is not a document either, so nothing here resyncs on a rename."""

TASK_QUEUE_DOCK_TITLE: Final = "Tasks"

TASK_VIEW_ICON_RESOURCE: Final = ":/icons/task_view.svg"

TASK_QUEUE_LOSS_TITLE: Final = "Unfinished tasks"
TASK_QUEUE_LOSS_MESSAGE: Final = "{count} unfinished task(s) will not survive quitting:"
"""Opens the only prompt quitting can raise about the queue (#202).

Counts rather than names the jobs: the reason a prompt is owed is the *kind* of loss, which the lines
below it spell out, and a label list would grow unbounded on the bulk enqueue this is most likely to
follow."""

THEME_DEFAULT_ICON: Final = ":/icons/theme_auto.svg"
"""Shown for the follow-system theme mode (``Qt.ColorScheme.Unknown``) -- on the toolbar's
3-state cycling action (:class:`~borco_pyside.theming.ThemeManager`) and the ``View`` menu's
``Default`` entry (:class:`~borco_pyside.theming.ThemeMenu`) alike, #57."""

THEME_LIGHT_ICON: Final = ":/icons/theme_light.svg"
"""Shown for the light theme mode (``Qt.ColorScheme.Light``), same two consumers as
:data:`THEME_DEFAULT_ICON`."""

THEME_DARK_ICON: Final = ":/icons/theme_dark.svg"
"""Shown for the dark theme mode (``Qt.ColorScheme.Dark``), same two consumers as
:data:`THEME_DEFAULT_ICON`."""


class MainWindow(QMainWindow):  # pylint: disable=too-many-instance-attributes
    """The single top-level window: a `CDockManager` whose central dock hosts :class:`DocumentsDock`,
    with a settings dock (#47) registered on the same outer manager -- not merged into
    `DocumentsDock`'s own nested one. Floating-first by default (see
    `DockableDialog.place_floating`), so it starts as its own independent window rather than
    pre-split into the documents area; a saved layout freely re-docks or repositions it.

    Dock-in-dock (a `CDockManager` inside the central dock's `DocumentsDock`, itself inside this
    window's own `CDockManager`) leaves room for a future resource browser to dock alongside the
    open documents ([[packaging-deployment#qml-regression]]) without restructuring this shell -- the
    settings dock is the first thing to actually use that room.
    """

    def __init__(self) -> None:
        super().__init__()

        self.__ui: Final = Ui_MainWindow()
        self.__ui.setupUi(self)
        self.centralWidget().hide()
        self.__base_window_title: Final = self.windowTitle()
        # every action __add_open_documents itself added on the last rebuild -- removed and
        # rebuilt from scratch each time, so the rebuild never has to know or guess what's
        # "static" above it (the theme entries, their separator, or anything added there later)
        self.__dynamic_view_menu_actions: Final[list[QAction]] = []

        self.__dialog_manager: Final = DockableDialogManager()
        self.__dock_manager: Final = QtAds.CDockManager(self)
        self.__settings_dialog: Final = SettingsDialog()
        self.__register_settings_pages()
        # after registration, not folded into SettingsDialog.__init__: add_page's own "first page
        # added becomes current" side effect needs every page registered first, or there'd be nothing
        # yet to correct (#228)
        self.__settings_dialog.restore_selected_page()

        # the window's outermost manager styles the whole dock nest: every manager below it -- this
        # dock's own, and one per open document -- would otherwise carry its own copy of QtAds'
        # ~10 KB default stylesheet, re-evaluated per level on every tab switch
        # ([[appendices.qt-ads#per-manager-stylesheet]], #234)
        # the app-wide log surface, built before the docking system that hosts it: the dock is placed in
        # __setup_docking_system, but the widget is this window's for its whole life (#200)
        self.__log_widget: Final = build_log_widget(limit=shared_logs_settings().app_limit)

        # same shape, for the task queue (#202): the engine and its store exist for the window's whole
        # life, restored here -- before the dock that shows them is built -- so the widget's own model
        # seeds itself from an already-restored queue rather than an empty one it would have to be told
        # to re-seed from a moment later
        self.__task_queue: Final = TaskQueue()
        self.__task_queue_store: Final = TaskQueueStore(self.__task_queue)
        self.__restore_task_queue()
        self.__task_queue_widget: Final = TaskQueueWidget(self.__task_queue)
        self.__task_queue_widget.attach()

        self.__documents_dock: Final = DocumentsDock(self, stylesheet_host=self.__dock_manager)
        self.__documents_dock.document_focus_changed.connect(self.__on_document_focus_changed)
        self.__documents_dock.status_message.connect(self.__on_status_message)
        self.__setup_docking_system()
        self.__ui.view_menu.aboutToShow.connect(lambda: self.__add_open_documents(self.__ui.view_menu))
        self.__setup_file_menu()

        self.__window_settings: Final = MainWindowSettings()
        self.__window_settings.load(persistent_settings())
        if self.__window_settings.geometry:
            self.restoreGeometry(QByteArray(self.__window_settings.geometry))
        self.restoreState(QByteArray(self.__window_settings.toolbars_state), TOOLBARS_STATE_VERSION)
        self.__log_widget.restore_state(self.__window_settings.log_widget_state)

        self.__recent_files: Final = RecentFilesSettings()
        self.__recent_files.load(persistent_settings())

        self.__session: Final = DocumentSessionSettings()
        self.__session.load(persistent_settings())
        self.__restore_session()

        self.__dialog_manager.restore_all(persistent_settings())

        self.__theme_settings: Final = ThemeSettings()
        self.__theme_settings.load(persistent_settings())

        # the shared source of truth for both views below (#57) -- neither ever reads
        # QApplication.styleHints().colorScheme() itself, which reports the *resolved* appearance
        # and can't distinguish "explicitly Light" from "Default, currently resolving to Light"
        self.__theme_model: Final = ThemeModel(self.__theme_settings.mode)
        ThemeManager(
            self.__theme_model,
            self.__ui.theme_action,
            default_icon=THEME_DEFAULT_ICON,
            light_icon=THEME_LIGHT_ICON,
            dark_icon=THEME_DARK_ICON,
        )

        theme_menu = ThemeMenu(
            self.__theme_model,
            default_icon=THEME_DEFAULT_ICON,
            light_icon=THEME_LIGHT_ICON,
            dark_icon=THEME_DARK_ICON,
        )

        self.__ui.view_menu.addAction(theme_menu.default_action)
        self.__ui.view_menu.addAction(theme_menu.light_action)
        self.__ui.view_menu.addAction(theme_menu.dark_action)
        self.__ui.view_menu.addSeparator()  # between the static theme entries above and the app docks below
        # log_action/tasks_action stand in for the docks' own toggleViewAction()s here (see
        # __setup_docking_system's companion-wiring comment) -- a plain menu row, unlike the toolbar
        # buttons those were built for. Sit between the theme entries and the open-resource list: both
        # are views of the app rather than of a resource, and __add_open_documents only ever appends,
        # so the static section keeps this order however often the dynamic tail is rebuilt (#200, #202)
        self.__ui.view_menu.addAction(self.__ui.log_action)
        self.__ui.view_menu.addAction(self.__ui.tasks_action)
        self.__ui.view_menu.addSeparator()  # between the app docks above and the dynamic docks list below

        # must be called after restoring the geometry and the session (open documents) so
        # the outer dock layout can be restored to the right place, and any floating
        # dialog's own window is already created and ready to be restored to its prior
        # visibility (#47, #55). Skipped when empty (no session saved yet): CDockManager.restoreState()
        # would return False anyway, but only after Qt's qUncompress() logs a spurious "Input data is
        # corrupted" warning to stderr for the invalid-as-qCompress empty buffer.
        if self.__window_settings.outer_docks_state:
            self.__dock_manager.restoreState(QByteArray(self.__window_settings.outer_docks_state))

    def __on_document_focus_changed(self, widget: DocumentWidget | None) -> None:
        """Reflect the newly-focused document's label in the window title, or the base title if none.

        :param widget: the newly-focused document's widget, or ``None`` when no document is focused.
        """
        label = widget.model.label if widget is not None else ""
        self.setWindowTitle(f"{label} - {self.__base_window_title}" if label else self.__base_window_title)

    def __on_status_message(self, text: str) -> None:
        """Show a document field's transient status message on this window's status bar, or clear it for
        an empty ``text`` -- the landing point of the ``authors`` viewer's hovered-link URL, bubbled up
        through ``DocumentWidget`` -> ``DocumentsDock`` (`StatusReporter`, [[plugins#field-toolkit]]).

        This is the one place the message is actually shown, because this is the **genuine top-level
        window** -- the only one safely wired to a real status bar. Neither the field nor the
        ``DocumentWidget``/``DocumentsDock`` between it and here may drive a status bar of its own, and
        the trap is subtle: ``QMainWindow`` keeps the ``Qt.WindowType.Window`` flag even when constructed
        with a parent, so each embedded ``QMainWindow`` reads as its *own* top-level window to
        ``QWidget.window()``. Walking up from the field with ``.window()`` therefore stops at the nearest
        embedded ``DocumentWidget``, not here; and ``QMainWindow.statusBar()`` lazily creates a bar on
        first call, so a stray ``statusBar()`` there would silently grow a status bar nobody can see and
        swallow every future status tip meant for this real one. Routing the message up as a signal --
        each owner re-emitting to the next -- sidesteps that walk entirely and lands it here, at the
        window whose ``status_bar`` was wired up at construction (``main_window_ui.py``).

        :param text: the message to show; an empty string clears it.
        """
        self.statusBar().showMessage(text)

    def __add_open_documents(self, menu: QMenu) -> None:
        """Rebuild ``menu`` with Close All / Close Missing Files and every currently open document,
        alphabetically by title (#61, #96).

        Listed directly under ``View``, below the three static theme entries and their trailing
        separator (#57) -- not mixed into them. Rebuilt fresh on every ``aboutToShow`` rather than
        kept in sync incrementally -- the open set, titles, paths, and lock reasons all change
        independently (open/close/rename/save-as/revert), and a menu only actually needs to be
        correct while it's showing. Only :attr:`__dynamic_view_menu_actions` -- this method's own
        additions from the last rebuild -- is removed first, unlike a plain ``menu.clear()``, which
        would wipe whatever's above them too.

        :param menu: the menu to (re)populate (``View``).
        """
        for action in self.__dynamic_view_menu_actions:
            menu.removeAction(action)
            action.deleteLater()
        self.__dynamic_view_menu_actions.clear()

        widgets = sorted(
            self.__documents_dock.open_document_widgets(), key=lambda widget: widget.model.label.casefold()
        )

        close_all_action = menu.addAction("Close All")
        close_all_action.setEnabled(bool(widgets))
        close_all_action.triggered.connect(self.__documents_dock.close_all)
        self.__dynamic_view_menu_actions.append(close_all_action)

        close_missing_action = menu.addAction("Close Missing Files")
        close_missing_action.setEnabled(self.__documents_dock.has_missing_documents())
        close_missing_action.triggered.connect(self.__documents_dock.close_missing)
        self.__dynamic_view_menu_actions.append(close_missing_action)

        self.__dynamic_view_menu_actions.append(menu.addSeparator())

        if not widgets:
            placeholder = menu.addAction("No Open Docks")
            placeholder.setEnabled(False)
            self.__dynamic_view_menu_actions.append(placeholder)
            return
        for widget in widgets:
            action = QWidgetAction(menu)
            action.setDefaultWidget(RehuDocumentMenuEntry(widget.model.label, widget.model.path, menu))
            action.triggered.connect(lambda _checked=False, widget=widget: self.__documents_dock.focus_document(widget))
            menu.addAction(action)
            self.__dynamic_view_menu_actions.append(action)

    def __setup_file_menu(self) -> None:
        """Wire ``File``'s static actions -- open dialogs, save all, quit -- and the ``Open recents``
        submenu's on-demand population (#64). ``Settings`` and the trailing ``Quit`` separator are
        appended later, in :meth:`__setup_docking_system`, once the settings dock's own toggle
        action exists to reuse.
        """
        self.__ui.open_rehu_action.triggered.connect(self.__on_open_rehu)
        self.__ui.open_folder_action.triggered.connect(self.__on_open_folder)
        self.__ui.open_companion_action.triggered.connect(self.__on_open_companion)
        self.__ui.save_all_action.triggered.connect(self.__on_save_all)
        self.__ui.quit_action.triggered.connect(self.close)
        self.__ui.open_recents_menu.aboutToShow.connect(self.__populate_recents_menu)
        # settings_action's checked state can go stale without emitting toggled (see
        # ActionIconThemeHandler's companion parameter docstring) -- force it correct right before
        # it's seen, same as __populate_docks_menu/__populate_recents_menu rebuild fresh on every
        # aboutToShow (#64)
        self.__ui.file_menu.aboutToShow.connect(self.__settings_action_icon_handler.resync_companion_checked_state)

    def __on_open_rehu(self) -> None:
        """Prompt for a ``.rehu`` file and open it (``File`` > ``Open rehu...``, #64)."""
        path, _ = QFileDialog.getOpenFileName(self, "Open rehu", "", "Rehu Files (*.rehu);;All Files (*)")
        if path:
            self.open_file(path)

    def __on_open_folder(self) -> None:
        """Prompt for a directory-scoped resource's folder and open it (``File`` > ``Open folder...``,
        [[data-model#resource-scoping]], #64)."""
        path = QFileDialog.getExistingDirectory(self, "Open Folder")
        if path:
            self.open_folder(path)

    def __on_open_companion(self) -> None:
        """Prompt for an archive file and open its ``.rehu`` companion (``File`` > ``Open companion...``,
        [[data-model#resource-scoping]], #64)."""
        filters = " ".join(f"*{extension}" for extension in ARCHIVE_EXTENSIONS)
        path, _ = QFileDialog.getOpenFileName(self, "Open Companion", "", f"Archives ({filters});;All Files (*)")
        if path:
            self.open_archive(path)

    def __on_save_all(self) -> None:
        """Save every currently dirty open document (``File`` > ``Save all``, reusing #41's
        per-document ``RehuDocumentModel.save``, #64).

        Each save is guarded (:func:`~rehuco_agent.documents.save_or_prompt_retry.save_or_prompt_retry`,
        #146): an I/O failure raises a retry/cancel dialog rather than aborting the whole sweep with a
        traceback. Cancelling one stops the sweep -- the user chose not to keep saving -- leaving the
        remaining dirty documents untouched.
        """
        for model in self.__documents_dock.open_document_models():
            if model.dirty and not save_or_prompt_retry(self, model):
                return

    def __populate_recents_menu(self) -> None:
        """Rebuild ``Open recents`` with the most-recently-opened paths, newest first (#64).

        Rebuilt fresh on every ``aboutToShow`` rather than kept in sync incrementally, mirroring
        :meth:`__populate_docks_menu` -- including reusing the same :class:`RehuDocumentMenuEntry`
        title/path row, title derived via
        :func:`~rehuco_agent.documents.rehu_document_model.path_label` (#117), the same rule
        :attr:`~rehuco_agent.documents.rehu_document_model.RehuDocumentModel.label` uses.
        """
        menu = self.__ui.open_recents_menu
        menu.clear()
        paths = self.__recent_files.newest_first()
        if not paths:
            placeholder = menu.addAction("No Recent Files")
            placeholder.setEnabled(False)
            return
        for path in paths:
            title = path_label(path)
            action = QWidgetAction(menu)
            action.setDefaultWidget(RehuDocumentMenuEntry(title, path, menu))
            action.triggered.connect(lambda _checked=False, path=path: self.open_path(path))
            menu.addAction(action)

    def __register_settings_pages(self) -> None:
        """Register every settings category page this platform supports (#47).

        Identity (#99) is cross-platform and top-level -- registered first, so it is the page the
        dialog initially shows. Every other cross-platform page nests under one "Plugins" group (#76,
        #230), registered alphabetically by title: Descriptions, Excluded Files (#226), Images. The
        reference-images extension list is a block on Images rather than a page of its own (#222): a
        page holding one list, whose subject was images, is what a reader looking for images had to
        know a plugin name to find.

        The top-level "System Integration" page is per-platform: Windows gets the `RegistryPage`
        wrapping ``winreg``-backed HKCU registration (#47), Linux the `DesktopIntegrationPage`
        wrapping the XDG desktop entry / MIME type / icon (#209), and macOS neither -- there the
        association comes from the app bundle itself ([[packaging-deployment#app-identity]]). Both
        are imported lazily, only here: the Windows one *must* be, mirroring the gate
        ``rehuco_agent.windows_registration`` (and the ``borco_core.platforms.windows.*`` modules
        it wraps) already requires, and the Linux one follows for symmetry. Two separate ``if``s
        rather than an ``if``/``elif`` chain: coverage excludes the whole construct when its first
        guard line is excluded off Windows, which would silently drop the Linux branch from the
        report there.
        """
        self.__settings_dialog.add_page(IdentityPage())
        # top-level, not under "Plugins": how much log to keep is about the app itself, and a reader
        # looking for it has no plugin name to guess (#200)
        self.__settings_dialog.add_page(LogsPage())
        # same reasoning, for the task queue's restart choices (#202)
        self.__settings_dialog.add_page(TasksPage())
        self.__settings_dialog.add_page(DescriptionsPage(), group="Plugins")
        self.__settings_dialog.add_page(ExcludedFilesPage(), group="Plugins")
        self.__settings_dialog.add_page(ImagesPage(), group="Plugins")
        self.__settings_dialog.add_page(VideosPage(), group="Plugins")
        if sys.platform == "win32":
            # pylint: disable-next=import-outside-toplevel
            from .settings.ui.registry_page import RegistryPage

            self.__settings_dialog.add_page(RegistryPage(ARCHIVE_EXTENSIONS))

        if sys.platform == "linux":
            # pylint: disable-next=import-outside-toplevel
            from .settings.ui.desktop_integration_page import DesktopIntegrationPage

            self.__settings_dialog.add_page(DesktopIntegrationPage())

    def __setup_docking_system(self) -> None:
        central_dock = QtAds.CDockWidget(self.__dock_manager, "Central Widget")
        central_dock.setWidget(self.__documents_dock)
        central_dock.setFeature(QtAds.CDockWidget.NoTab, True)

        self.__dock_manager.setCentralWidget(central_dock)

        # not Final: this runs from __setup_docking_system rather than __init__, matching
        # __settings_action_icon_handler below
        self.__log_dock = self.__add_log_dock()
        self.__task_queue_dock = self.__add_task_queue_dock()
        # log_action/tasks_action stand in for the docks' own toggleViewAction()s in the View menu,
        # the same reason settings_action stands in for toggle_action in File below: the toolbar
        # button sits on a highlighted checked-button background, where ActionIconThemeHandler's
        # checked-state color reads well, but a menu row has no such background behind its icon --
        # only the native checkmark -- so that same color would be unreadable there whenever a dock
        # is open. Kept (unlike every other ActionIconThemeHandler call site here) since view_menu's
        # own aboutToShow needs them to resync log_action/tasks_action right before View shows --
        # connected here rather than where the actions are actually added to view_menu (__init__,
        # once the theme entries ahead of them exist) because both handlers already exist by this
        # point and view_menu itself does too, declared in the .ui.
        self.__log_view_icon_handler = ActionIconThemeHandler(
            self.__log_dock.toggleViewAction(), LOG_VIEW_ICON_RESOURCE, companion=self.__ui.log_action
        )
        self.__task_view_icon_handler = ActionIconThemeHandler(
            self.__task_queue_dock.toggleViewAction(), TASK_VIEW_ICON_RESOURCE, companion=self.__ui.tasks_action
        )
        self.__ui.view_menu.aboutToShow.connect(self.__log_view_icon_handler.resync_companion_checked_state)
        self.__ui.view_menu.aboutToShow.connect(self.__task_view_icon_handler.resync_companion_checked_state)

        settings_dock = DockableDialog(
            self.__dock_manager, SETTINGS_DIALOG_OBJECT_NAME, "Settings", self.__settings_dialog
        )
        # floating-first, not docking-first: the fallback placement for "nothing saved yet" --
        # __init__'s later CDockManager.restoreState() call freely re-docks or repositions it if
        # there's anything actually saved
        settings_dock.place_floating()
        self.__dialog_manager.register(settings_dock)
        # settings_action stands in for toggle_action in File (a plain menu row, unlike the
        # toolbar button toggle_action was built for) -- see the companion parameter's docstring
        # for why that needs a second, differently-themed action rather than reusing toggle_action
        # outright (#64). Kept (unlike every other ActionIconThemeHandler call site here) since
        # __setup_file_menu needs it to resync settings_action right before File shows.
        self.__settings_action_icon_handler = ActionIconThemeHandler(
            settings_dock.toggle_action, SETTINGS_ICON_RESOURCE, companion=self.__ui.settings_action
        )

        # settings_dock only exists from here on, so its menu action is appended to file_menu here
        # rather than declared in the .ui alongside the rest of the menu (#64)
        self.__ui.file_menu.addAction(self.__ui.settings_action)
        self.__ui.file_menu.addSeparator()
        self.__ui.file_menu.addAction(self.__ui.quit_action)

        # QToolBar has no dedicated stretch item -- an expanding QWidget is the standard stand-in,
        # pushing theme/settings to the bottom of the vertical action_bar (#59)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.__ui.action_bar.addWidget(spacer)
        self.__ui.action_bar.addAction(self.__ui.theme_action)
        self.__ui.action_bar.addAction(self.__log_dock.toggleViewAction())
        self.__ui.action_bar.addAction(self.__task_queue_dock.toggleViewAction())
        self.__ui.action_bar.addAction(settings_dock.toggle_action)

    def __add_log_dock(self) -> QtAds.CDockWidget:
        """Build the app-wide log dock on the outer manager, hidden by default (#200).

        A plain ``CDockWidget``, not a `DockableDialog`: that framework's whole addition over a dock is
        the "Restore on start" checkbox, which belongs to a modeless dialog and not to a log -- whether
        this reopens with the window is simply whether it was open when the window closed, which the
        outer manager's own ``saveState()`` already records.

        **Hidden by default**, and the dock area is the bottom one: a log is read across the width of the
        window, under the thing it is about, and a first run should show the resource being edited rather
        than a log of having opened it. An older saved layout knows nothing of this dock, which is what
        :data:`~rehuco_agent.settings.main_window_settings.OUTER_DOCKS_STATE_VERSION`'s bump is for.

        The widget is attached to the bridge here, at construction, rather than on first reveal: the
        replay is what makes a dock opened later worth opening, and it costs one batch of rows in a model
        that is not on screen.

        :returns: the dock, hidden.
        """
        self.__log_widget.attach_to(shared_log_bridge())
        shared_logs_settings().app_limit_changed.connect(self.__on_app_log_limit_changed)  # type: ignore[attr-defined]

        dock = QtAds.CDockWidget(self.__dock_manager, LOG_DOCK_TITLE)
        dock.setObjectName(LOG_DOCK_OBJECT_NAME)
        features = QtAds.CDockWidget.DockWidgetFeature
        dock.setFeatures(
            features.DockWidgetClosable
            | features.DockWidgetMovable
            | features.DockWidgetFloatable
            | features.DockWidgetFocusable
        )
        dock.setWidget(self.__log_widget)
        self.__dock_manager.addDockWidget(QtAds.BottomDockWidgetArea, dock)
        dock.toggleView(False)
        return dock

    def __restore_task_queue(self) -> None:
        """Read the saved queue, drop what the two "clear on restart" settings say to, and restore
        the rest -- before anything else touches :attr:`__task_queue` (#202,
        [[appendices.task-queue#lifetime]]).

        **Applied at load, before ``restore()``.** A clear-on-restart setting turned on after the app
        was last closed is then honoured on the very next start rather than the one after, and the
        dropped jobs never enter the queue at all -- no ``jobs_removed`` churn, no flash of rows
        vanishing as the window opens. Which of the two held-back states unfinished work restarts in is
        *resume tasks on restart*'s to decide, not this method's: eligibility is per-job, so a newly
        enqueued job runs immediately regardless.
        """
        settings = TasksSettings()
        settings.load(persistent_settings())
        items = self.__task_queue_store.read_items()
        dropped_states = set()
        if settings.clear_done_on_restart:
            dropped_states.add(JobState.DONE)
        if settings.clear_failed_on_restart:
            dropped_states.add(JobState.FAILED)
        if dropped_states:
            items = [item for item in items if item.get("job_state") not in dropped_states]
        unfinished_state = JobState.QUEUED if settings.resume_on_restart else JobState.PAUSED
        self.__task_queue_store.restore(items, unfinished_state=unfinished_state)

    def __add_task_queue_dock(self) -> QtAds.CDockWidget:
        """Build the app-wide task queue dock on the outer manager, hidden by default (#202).

        The same shape as :meth:`__add_log_dock`, and for the same reasons: a plain ``CDockWidget``
        rather than a `DockableDialog` (whose only addition, the "Restore on start" checkbox, belongs
        to a modeless dialog and not to a queue whose visibility the outer manager's own
        ``saveState()`` already records), placed beside it in the bottom area, hidden until asked for.

        :returns: the dock, hidden.
        """
        dock = QtAds.CDockWidget(self.__dock_manager, TASK_QUEUE_DOCK_TITLE)
        dock.setObjectName(TASK_QUEUE_DOCK_OBJECT_NAME)
        features = QtAds.CDockWidget.DockWidgetFeature
        dock.setFeatures(
            features.DockWidgetClosable
            | features.DockWidgetMovable
            | features.DockWidgetFloatable
            | features.DockWidgetFocusable
        )
        dock.setWidget(self.__task_queue_widget)
        self.__dock_manager.addDockWidget(QtAds.BottomDockWidgetArea, dock)
        dock.toggleView(False)
        return dock

    def __confirm_task_queue_loss(self) -> bool:
        """Ask before quitting only when quitting would actually cost something (#202).

        **Silent in the common case**, which is the whole point of persistence: if every unfinished job
        can be stopped part-way leaving nothing behind *and* will be written to the queue file, the app
        quits with no prompt at all -- being asked every time is exactly the friction
        [[appendices.task-queue#lifetime]] exists to remove.

        A prompt appears for the two cases where something is genuinely lost, each read off the
        job's own declaration on its status: a job that is **not**
        :attr:`~rehuco_core.JobStatus.safely_interruptible` leaves something behind when stopped
        part-way, and one that is not :attr:`~rehuco_core.JobStatus.persistable` is dropped rather
        than restored -- the opt-out §6.1 puts on every row precisely so a surface can say so instead
        of letting it vanish.

        **"Wait for them to finish" is deliberately not offered.** A modal blocking on an unbounded
        disk walk is a window that will not close, so the only choices are to quit anyway or to go
        back -- which is what leaves someone able to pause or finish the work on their own terms.

        :returns: whether the close may proceed.
        """
        at_risk = [
            status
            for status in self.__task_queue.jobs()
            if status.state not in FINISHED_JOB_STATES and not (status.safely_interruptible and status.persistable)
        ]
        if not at_risk:
            return True

        unsafe = sum(1 for status in at_risk if not status.safely_interruptible)
        unsaved = sum(1 for status in at_risk if not status.persistable)
        reasons = []
        if unsafe:
            reasons.append(f"{unsafe} cannot be stopped part-way without leaving something behind.")
        if unsaved:
            reasons.append(f"{unsaved} will not be saved, and will be lost.")
        question = "\n".join([TASK_QUEUE_LOSS_MESSAGE.format(count=len(at_risk)), *reasons, "", "Quit anyway?"])
        answer = QMessageBox.warning(
            self,
            TASK_QUEUE_LOSS_TITLE,
            question,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def __shutdown_task_queue(self) -> None:
        """Pause, wait, save, then shut the task queue down ([[appendices.task-queue#teardown]]).

        Silent in the common case: pausing and waiting settle every unfinished job that is
        interruptible without losing anything, so the queue is written and torn down with no prompt.
        ``wait_until_idle`` **reports** rather than hangs -- a job ignoring its checkpoints must never
        turn "quit" into a window that will not close -- so a job left running is logged, not blocked
        on.

        The task queue dock's widget is detached **before** ``shutdown()``: shutdown synchronously emits
        ``job_updated`` for each job it cancels, and each would otherwise schedule a wake-up whose
        dispatch runs against a widget already being torn down.
        """
        self.__task_queue.pause()
        if not self.__task_queue.wait_until_idle():
            LOG.warning("The task queue did not settle before quitting; the unfinished job may be lost.")
        self.__task_queue_store.save()
        self.__task_queue_widget.detach()
        self.__task_queue.shutdown()

    def __on_app_log_limit_changed(self, limit: int) -> None:
        """Re-cap the app-wide log surface as the setting changes.

        The bridge re-caps itself (:func:`~rehuco_agent.app_logging.shared_log_bridge`); this is the
        surface's half, so a limit lowered in the settings dialog reaches a dock that is open and
        scrolled back rather than waiting for a restart ([[appendices.logging#buffers]]).

        :param limit: the newly-configured limit.
        """
        self.__log_widget.limit = limit

    @property
    def log_widget(self) -> LogWidget:
        """The app-wide log surface hosted by the log dock (#200)."""
        return self.__log_widget

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        """Guard the app close: prompt for dirty documents, saving the checked ones.

        The prompt itself, and the guarded save of each checked document, are the shared batch guard
        (:func:`~rehuco_agent.documents.confirm_and_save_dirty.confirm_and_save_dirty`, #176) --
        the same one :meth:`~rehuco_agent.documents.documents_dock.DocumentsDock.close_all` uses. What
        is specific here is the follow-on: a refusal (the prompt cancelled, or a failed save's
        retry/cancel dialog cancelled, #146) aborts the app close, so the window stays open with its
        edits and the session intact. Crucially, that keeps a failure from skipping the persistence
        steps below (window state, session, recents, theme) while the window closes anyway -- once the
        guard has passed, they always run.

        :param event: the close event to accept or ignore.
        """
        dirty_models = [model for model in self.__documents_dock.open_document_models() if model.dirty]
        if not confirm_and_save_dirty(self, dirty_models):
            event.ignore()
            return

        if not self.__confirm_task_queue_loss():
            event.ignore()
            return

        # pause, wait, save, shut down (#202, [[appendices.task-queue#teardown]]) -- before the outer
        # dock layout is captured below, the same ordering constraint __dialog_manager's call is under
        self.__shutdown_task_queue()

        # must run before __save_window_state captures the outer CDockManager's saveState(), or a
        # floating-and-visible-but-unchecked dialog gets saved that way anyway and flashes open on
        # the next launch before __init__'s dialog_manager.restore_all() notices the checkbox (#47)
        self.__dialog_manager.enforce_restore_on_start()
        self.__save_window_state()
        self.__dialog_manager.save_all(persistent_settings())
        self.__save_session()
        self.__settings_dialog.save_filter_state()
        self.__recent_files.save(persistent_settings())
        self.__theme_settings.mode = self.__theme_model.mode
        self.__theme_settings.save(persistent_settings())
        super().closeEvent(event)

    def __restore_session(self) -> None:
        """Reopen every document the last session left open, restoring its dock layout and focus.

        A path that has since gone missing or become unparseable still reopens -- as an empty, **locked**
        dock materialized in its place ([[data-model#write-integrity]]), not skipped and not a dialog per
        file -- so the user can fix it and revert in place rather than lose the session slot. The outer
        layout (splits/tabs between documents) is restored only once every document it references has
        already been reopened above -- ``DocumentsDock.restore_state`` matches saved entries up to
        currently-registered docks by name, it does not create any itself.
        """
        opened: dict[Path, DocumentWidget] = {}
        for path, item in self.__session.items.items():
            if not item.open:
                continue
            widget = self.__documents_dock.open_document(path)
            widget.restore_state(item.state)
            opened[path] = widget

        self.__documents_dock.restore_state(self.__session.docks_state)

        focused_path = self.__session.focused_path
        if focused_path is not None and focused_path in opened:
            self.__documents_dock.open_document(focused_path)  # re-focuses an already-open dock

    def __save_window_state(self) -> None:
        """Persist this window's current size/position, toolbar layout, outer dock layout, and the
        app-wide log surface's own filters (#200)."""
        self.__window_settings.geometry = bytes(self.saveGeometry().data())
        self.__window_settings.toolbars_state = bytes(self.saveState(TOOLBARS_STATE_VERSION).data())
        self.__window_settings.outer_docks_state = bytes(self.__dock_manager.saveState().data())
        self.__window_settings.log_widget_state = self.__log_widget.save_state()
        self.__window_settings.save(persistent_settings())

    def __save_session(self) -> None:
        """Snapshot every open document's dock layout and focus, and persist the open-file set.

        Currently open documents always count as the most-recently-used ones (moved to the end of
        the LRU order); everything else keeps its prior state but is marked closed. A brand-new
        document not yet written to its path (``saved_on_disk`` false) is skipped -- there is nothing
        on disk to restore, and reopening it via the load path would materialize a locked ``MISSING``
        stub for a file that never existed, resurrecting edits the user discarded (#175, #147).
        """
        open_widgets = {
            widget.model.path: widget
            for widget in self.__documents_dock.open_document_widgets()
            if widget.model.path is not None and widget.model.saved_on_disk
        }

        for path in open_widgets:
            self.__session.items.pop(path, None)
        for item in self.__session.items.values():
            item.open = False
        for path, widget in open_widgets.items():
            self.__session.items[path] = DocumentSessionSettings.Item(  # pylint: disable=unsupported-assignment-operation
                open=True, state=widget.save_state()
            )
        self.__session.focused_path = self.__documents_dock.focused_document_path()
        self.__session.docks_state = self.__documents_dock.save_state()

        self.__session.save(persistent_settings())

    def open_path(self, path: Path | str) -> None:
        """Open ``path``, dispatching to :meth:`open_file`, :meth:`open_folder`, or
        :meth:`open_archive` by its kind.

        The single entry point for anything an outside caller (argv, Windows ProgID/shell-verb
        forwarding, a ``QFileOpenEvent``, #43) hands in without already knowing which kind it is.

        :param path: filesystem path to a ``.rehu`` file, to a directory-scoped resource's
            directory, or to an archive file ([[data-model#resource-scoping]]).
        """
        resolved = Path(path)
        if resolved.is_dir():
            self.open_folder(path)
        elif resolved.suffix.lower() in ARCHIVE_EXTENSIONS:
            self.open_archive(path)
        else:
            self.open_file(path)

    def open_file(self, path: Path | str) -> None:
        """Open ``path`` in its document dock, focusing it if already open ([[nodes#single-instance]]).

        Recorded into ``Open recents`` (#64) once opened, alongside :meth:`open_folder`/:meth:`open_archive`
        -- **unless** the file could not be read at all and opened as a load-failure stub
        (:attr:`~RehuDocument.load_failed`): a missing or unparseable file is not a file you opened, so it
        stays out of recents even though it still yields a (locked) dock ([[data-model#write-integrity]]).

        :param path: filesystem path to a ``.rehu`` file.
        """
        resolved = Path(path).resolve()
        widget = self.__documents_dock.open_document(resolved)
        if not widget.model.document.load_failed:
            self.__recent_files.record(resolved)

    def open_folder(self, path: Path | str) -> None:
        """Open the directory-scoped resource at ``path`` ([[data-model#resource-scoping]]), focusing
        it if already open ([[nodes#single-instance]]).

        Recorded into ``Open recents`` (#64) once opened, alongside :meth:`open_file`/:meth:`open_archive`
        -- unless the resource could not be read and opened as a load-failure stub
        (:attr:`~RehuDocument.load_failed`, [[data-model#write-integrity]]).

        :param path: filesystem path to the directory.
        """
        resolved = Path(path).resolve()
        widget = self.__documents_dock.open_folder(resolved)
        if not widget.model.document.load_failed:
            self.__recent_files.record(resolved)

    def open_archive(self, path: Path | str) -> None:
        """Open the file-scoped resource for the archive at ``path`` ([[data-model#resource-scoping]]),
        focusing it if already open ([[nodes#single-instance]]).

        Recorded into ``Open recents`` (#64) once opened, alongside :meth:`open_file`/:meth:`open_folder`
        -- unless the companion could not be read and opened as a load-failure stub
        (:attr:`~RehuDocument.load_failed`, [[data-model#write-integrity]]).

        :param path: filesystem path to the archive file (e.g. ``foo.zip``); its ``.rehu`` companion
            (e.g. ``foo.rehu``) is what actually gets opened or created.
        """
        resolved = Path(path).resolve()
        widget = self.__documents_dock.open_archive(resolved)
        if not widget.model.document.load_failed:
            self.__recent_files.record(resolved)

    def raise_and_activate(self) -> None:
        """Bring this window to the foreground, restoring it first if minimized ([[nodes#single-instance]]).

        Called whenever a path is opened -- including a forwarded open from a second process via
        the single-instance guard -- so the running app visibly comes forward rather than silently
        gaining a new dock behind other windows.
        """
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

        if sys.platform == "win32":
            from borco_pyside.platforms.windows import window_activation  # pylint: disable=import-outside-toplevel

            window_activation.force_foreground(self)
