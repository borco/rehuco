"""Top-level `QtAds` dock-in-dock shell hosting the open-documents area ([[plugins#toolkit-surfaces]])."""

# the window wires together every top-level surface the app has -- docks, actions, dialogs, the task
# queue -- and that is one cohesive job; splitting it to dodge a line-count cap would scatter the wiring
# rather than clarify it (same precedent as test_rehu_document_model.py, [[appendices.code-conventions]])
# pylint: disable=too-many-lines

import logging
import sys
from pathlib import Path
from typing import Final, override

import PySide6QtAds as QtAds
from borco_pyside.dialogs import DockableDialog, DockableDialogManager
from borco_pyside.logging import LogScope, LogWidget
from borco_pyside.theming import ActionIconThemeHandler, ThemeManager, ThemeMenu, ThemeModel
from PySide6.QtCore import QByteArray
from PySide6.QtGui import QAction, QCloseEvent, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QSystemTrayIcon,
    QWidget,
    QWidgetAction,
)
from rehuco_core import (
    DEFAULT_RENAME_COORDINATOR,
    FINISHED_JOB_STATES,
    JobState,
    SweepChecksumsJob,
    TaskQueue,
)

from .app_logging import LOG_VIEW_ICON_RESOURCE, build_log_widget, shared_log_bridge
from .archives import ARCHIVE_EXTENSIONS
from .dialogs.conversion_backups_dialog import ConversionBackupsDialog
from .dialogs.import_legacy_catalog_wizard import ImportLegacyCatalogWizard
from .documents.confirm_and_save_dirty import confirm_and_save_dirty
from .documents.document_widget import DocumentWidget
from .documents.documents_dock import DocumentsDock
from .documents.rehu_document_menu_entry import RehuDocumentMenuEntry
from .documents.rehu_document_model import path_label
from .documents.save_or_prompt_retry import save_or_prompt_retry
from .main_window_ui import Ui_MainWindow
from .settings.checksum_settings import shared_checksum_settings
from .settings.document_session_settings import DocumentSessionSettings
from .settings.excluded_files_settings import shared_excluded_files_settings
from .settings.identity_settings import shared_identity_settings
from .settings.image_viewer_settings import shared_image_viewer_settings
from .settings.logs_settings import shared_logs_settings
from .settings.main_window_settings import TOOLBARS_STATE_VERSION, MainWindowSettings
from .settings.persistent_settings import persistent_settings
from .settings.recent_files_settings import RecentFilesSettings
from .settings.tasks_settings import TasksSettings
from .settings.theme_settings import ThemeSettings
from .settings.tray_settings import shared_tray_settings
from .settings.ui.checksums_page import ChecksumsPage
from .settings.ui.descriptions_page import DescriptionsPage
from .settings.ui.excluded_files_page import ExcludedFilesPage
from .settings.ui.identity_page import IdentityPage
from .settings.ui.images_page import ImagesPage
from .settings.ui.logs_page import LogsPage
from .settings.ui.settings_dialog import SettingsDialog
from .settings.ui.tasks_page import TasksPage
from .settings.ui.videos_page import VideosPage
from .tasks import TaskQueueStatusIndicator, TaskQueueStore, TaskQueueWidget, job_already_queued
from .tray_icon import TrayIcon

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

IMAGE_PREVIEWS_ICON_RESOURCE: Final = ":/icons/image_previews.svg"

TRAY_ICON_RESOURCE: Final = ":/icons/rehuco-agent.svg"
"""qrc path to the tray icon (#205) -- the app's own icon, the same one `Application.__init__` sets
as the window icon; a tray icon distinguishing itself from every other running app is `QSystemTrayIcon`'s
whole point, and no dedicated asset says anything a second icon design would."""

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

        # not Final: request_quit sets this before close(), and closeEvent clears it right back --
        # the one thing that overrides tray mode's close-to-tray routing (#205)
        self.__quit_requested = False
        # not Final: __on_tray_enabled_changed creates/tears it down live as the setting changes
        self.__tray_icon: TrayIcon | None = None
        # the floating dock windows hidden alongside this one by hide_to_tray, waiting for
        # raise_and_activate to put them back; empty whenever the window is not hidden to tray
        self.__floating_docks_hidden_with_window: Final[list[QtAds.CFloatingDockContainer]] = []
        shared_tray_settings().enabled_changed.connect(self.__on_tray_enabled_changed)  # type: ignore[attr-defined]
        self.__on_tray_enabled_changed(shared_tray_settings().enabled)

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

        # the app's one rename coordinator: every document renames through it and every job that reads
        # files tracks its locations in it, so a rename asks the running work to stand aside for one
        # chunk instead of waiting for it to finish (#241). Its notification drives the queue's own
        # re-read, which is how a moved job's row stops naming a folder that no longer exists.
        # The process-wide one rather than this window's own (#204): a job the registry rebuilt from
        # the saved queue has no window to be handed anything, and a job reading through a coordinator
        # nobody renames through would hold a directory open against the rename it must stand aside for.
        self.__rename_coordinator: Final = DEFAULT_RENAME_COORDINATOR
        self.__rename_coordinator.add_rename_listener(self.__task_queue.resync_sources)

        self.__documents_dock: Final = DocumentsDock(
            self,
            stylesheet_host=self.__dock_manager,
            rename_coordinator=self.__rename_coordinator,
            task_queue=self.__task_queue,
        )
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
        self.__setup_view_menu()

        # must be called after restoring the geometry and the session (open documents) so
        # the outer dock layout can be restored to the right place, and any floating
        # dialog's own window is already created and ready to be restored to its prior
        # visibility (#47, #55). Skipped when empty (no session saved yet): CDockManager.restoreState()
        # would return False anyway, but only after Qt's qUncompress() logs a spurious "Input data is
        # corrupted" warning to stderr for the invalid-as-qCompress empty buffer.
        if self.__window_settings.outer_docks_state:
            self.__dock_manager.restoreState(QByteArray(self.__window_settings.outer_docks_state))

    def __on_document_focus_changed(self, widget: DocumentWidget | None) -> None:
        """Reflect the newly-focused document's label in the window title, or the base title if none,
        and enable ``File`` > ``Close`` (``Ctrl+W``, #247) only while a document is actually focused --
        the same condition, read off the same signal, so the two never disagree about whether one is.

        :param widget: the newly-focused document's widget, or ``None`` when no document is focused.
        """
        label = widget.model.label if widget is not None else ""
        self.setWindowTitle(f"{label} - {self.__base_window_title}" if label else self.__base_window_title)
        self.__ui.close_action.setEnabled(widget is not None)

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
        """Rebuild ``menu`` with every currently open document, alphabetically by title (#61).

        Listed directly under ``View``, below the three static theme entries and their trailing
        separator (#57) -- not mixed into them. ``Close All``/``Close Missing Files`` used to lead
        this same tail (#96); they moved to ``File``, grouped below ``Close`` (#247), once both
        needed a keyboard shortcut and a menu rebuilt from scratch on every show is not where a
        shortcut-bearing action wants to live. Rebuilt fresh on every ``aboutToShow`` rather than
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

    def __setup_view_menu(self) -> None:
        """Build the theme controls and fill ``View``'s static section -- the theme entries, then the
        app-wide docks (#57, #200, #202).

        The toolbar's 3-state cycling action and the menu's three explicit entries are two views of the
        one :class:`~borco_pyside.theming.ThemeModel` built in ``__init__``; neither reads
        ``QApplication.styleHints().colorScheme()``, which reports the *resolved* appearance and cannot
        tell "explicitly Light" from "Default, currently resolving to Light".

        ``log_action``/``tasks_action`` stand in for those docks' own ``toggleViewAction()``s here (see
        :meth:`__setup_docking_system`'s companion-wiring comment) -- a plain menu row, unlike the
        toolbar buttons those were built for. They sit between the theme entries and the open-resource
        list because both are views of the *app* rather than of a resource, and
        :meth:`__add_open_documents` only ever appends, so this static order survives however often the
        dynamic tail is rebuilt.

        ``image_previews_action`` (``Ctrl+Shift+``, grave accent, #71) joins them for the same reason:
        it too is a view of the app rather than of one resource. It is the *companion* to the toolbar's
        own ``image_previews_toggle_action`` -- see :meth:`__setup_docking_system`'s companion-wiring
        comment for both that pairing and the shortcut-context reasoning.
        """
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
        self.__ui.view_menu.addAction(self.__ui.log_action)
        self.__ui.view_menu.addAction(self.__ui.tasks_action)
        self.__ui.view_menu.addAction(self.__ui.image_previews_action)
        self.__ui.view_menu.addSeparator()  # between the app docks above and the dynamic docks list below

    def __setup_file_menu(self) -> None:
        """Wire ``File``'s static actions -- open dialogs, close, save all, quit -- and the ``Open
        recents`` submenu's on-demand population (#64). ``Settings`` and the trailing ``Quit``
        separator are appended later, in :meth:`__setup_docking_system`, once the settings dock's
        own toggle action exists to reuse.

        ``Sweep checksums...`` (#242) lives here rather than in a menu of its own: ``File`` is where
        every *point at something on disk and act on it* entry already is, and a sweep is a folder
        chooser plus an enqueue. A ``Tools`` menu becomes worth having when the second catalog-wide
        operation lands -- the cache scan the same walk was built for ([[data-model#scan-and-staleness]])
        -- and both should move there together rather than one arriving alone.
        """
        self.__ui.open_rehu_action.triggered.connect(self.__on_open_rehu)
        self.__ui.open_folder_action.triggered.connect(self.__on_open_folder)
        self.__ui.open_companion_action.triggered.connect(self.__on_open_companion)
        self.__ui.close_action.triggered.connect(self.__documents_dock.close_focused_document)
        self.__ui.close_missing_action.triggered.connect(self.__documents_dock.close_missing)
        self.__ui.close_all_action.triggered.connect(self.__documents_dock.close_all)
        self.__ui.save_all_action.triggered.connect(self.__on_save_all)
        self.__ui.sweep_checksums_action.triggered.connect(self.__on_sweep_checksums)
        self.__ui.import_legacy_catalog_action.triggered.connect(self.__on_import_legacy_catalog)
        self.__ui.conversion_backups_action.triggered.connect(self.__on_conversion_backups)
        self.__ui.quit_action.triggered.connect(self.request_quit)
        self.__ui.open_recents_menu.aboutToShow.connect(self.__populate_recents_menu)
        # settings_action's checked state can go stale without emitting toggled (see
        # ActionIconThemeHandler's companion parameter docstring) -- force it correct right before
        # it's seen, same as __populate_docks_menu/__populate_recents_menu rebuild fresh on every
        # aboutToShow (#64)
        self.__ui.file_menu.aboutToShow.connect(self.__settings_action_icon_handler.resync_companion_checked_state)
        # close_missing_action/close_all_action moved here from the View menu's own dynamic rebuild
        # (#96, #247) -- resynced the same lazy way that rebuild always read them: fresh right before
        # the menu holding them shows, since the open set and which of it is missing both change
        # independently of any signal narrower than that
        self.__ui.file_menu.aboutToShow.connect(self.__resync_close_actions_enabled)

    def __resync_close_actions_enabled(self) -> None:
        """Recompute ``Close Missing Files``/``Close All``'s enabled state (#96, #247).

        Read fresh off the documents dock every time, mirroring :meth:`__add_open_documents`'s own
        reasoning for its dynamic tail: the open set and which of it is missing both change
        independently (open/close/rename/revert), and a menu only actually needs to be correct while
        it's showing.
        """
        self.__ui.close_missing_action.setEnabled(self.__documents_dock.has_missing_documents())
        self.__ui.close_all_action.setEnabled(bool(self.__documents_dock.open_document_widgets()))

    def __on_image_previews_toggled(self, visible: bool) -> None:
        """Apply the previews toggle app-wide, and persist it as it is clicked (#71).

        Written through here rather than at shutdown, the same shape ``Sweep checksums...``'s
        remembered root uses: this toggle has no Apply button behind it and no settings page to be
        saved from, so the click is the only moment there is to record it. Assigning the property is
        what reaches the open documents; the save is only about the next launch.

        :param visible: whether previews are now shown.
        """
        settings = shared_image_viewer_settings()
        settings.previews_visible = visible
        settings.save(persistent_settings())

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

    def __on_sweep_checksums(self) -> None:
        """Prompt for a folder and queue a sweep over it (``File`` > ``Sweep checksums...``, #242).

        **A folder per run, not a configured library.** Where a machine's folder roots live is
        [[mounts-and-storage#rehuco-scope]]'s `.rehuco` question and nothing writes one yet, so a sweep
        is pointed at a folder the way ``Open folder...`` is -- with the last one remembered, since a
        catalog is swept repeatedly and re-navigating to it every time would be the whole friction.

        The settings are resolved here, at enqueue, and captured into the job: core never reads a
        setting, and a restored sweep is meant to be *the sweep that was queued*
        ([[appendices.task-queue#lifetime]]).

        Enqueued inside the folder's own log scope, so the sweep's records are attributable to what it
        was over ([[appendices.task-queue#scopes]]) -- no document is open on that scope, so the detail
        reads in the app-wide Log dock.
        """
        settings = shared_checksum_settings()
        chosen = QFileDialog.getExistingDirectory(self, "Sweep Checksums", settings.last_sweep_root)
        if not chosen:
            return
        root = Path(chosen)
        settings.last_sweep_root = str(root)
        settings.save(persistent_settings())
        job = SweepChecksumsJob(
            root,
            algorithm=settings.algorithm,
            stale_after=settings.stale_after,
            create_if_missing=settings.create_missing_on_verify,
            migrate_to=settings.migrate_target,
            excluded_patterns=shared_excluded_files_settings().excluded_file_patterns,
        )
        if job_already_queued(self.__task_queue, label=job.label, source=job.source):
            LOG.info("%s is already in the task queue; it was not queued again.", job.label)
            return
        with LogScope.open(root):
            self.__task_queue.enqueue(job)

    def __on_import_legacy_catalog(self) -> None:
        """Open the bulk `.tc` import wizard (``File`` > ``Import Legacy Catalog...``, #192).

        Filed under the **unknown** identity, the same rule an in-app `.tc` open already follows
        (``DocumentsDock``): the per-user flags a legacy file carries were not set by this install's
        own identity ([[field-schema#per-user-shared]], #109).
        """
        wizard = ImportLegacyCatalogWizard(
            self.__task_queue, username=shared_identity_settings().unknown_username, parent=self
        )
        wizard.exec()

    def __on_conversion_backups(self) -> None:
        """Open the conversion-backups manager (``File`` > ``Conversion Backups...``, #193).

        Takes no identity, unlike :meth:`__on_import_legacy_catalog`: reverting and discarding move and
        delete files, and file them under nobody -- there are no per-user flags being read or written
        here for an identity to belong to.

        Wired to the documents dock's open-paths seam (#246), which warns before a revert about an open
        tab and refreshes it once reverted.
        """
        dialog = ConversionBackupsDialog(
            self.__task_queue,
            parent=self,
            open_paths=self.__documents_dock.open_paths,
            on_reverted=self.__documents_dock.adopt_reverted_conversion,
        )
        dialog.exec()

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

        The top-level "System Integration" page is per-platform, and **every** platform has one:
        Windows gets the `RegistryPage` wrapping ``winreg``-backed HKCU registration (#47), Linux
        the `DesktopIntegrationPage` wrapping the XDG desktop entry / MIME type / icon (#209), and
        macOS the `SystemIntegrationPage` -- which registers nothing, since there the association
        comes from the app bundle itself ([[packaging-deployment#app-identity]]). macOS gets a page
        at all because the tray block (#205) lives on this one, and a setting that decides what the
        window's close button does must be reachable wherever there is a window.

        All three are imported lazily, only here: the Windows one *must* be, mirroring the gate
        ``rehuco_agent.windows_registration`` (and the ``borco_core.platforms.windows.*`` modules
        it wraps) already requires, and the other two follow for symmetry. Separate ``if``s rather
        than an ``if``/``elif`` chain: coverage excludes the whole construct when its first guard
        line is excluded off Windows, which would silently drop the other branches from the report
        there.
        """
        self.__settings_dialog.add_page(IdentityPage())
        # top-level, not under "Plugins": how much log to keep is about the app itself, and a reader
        # looking for it has no plugin name to guess (#200)
        self.__settings_dialog.add_page(LogsPage())
        # same reasoning, for the task queue's restart choices (#202)
        self.__settings_dialog.add_page(TasksPage())
        # and again for the checksum defaults (#242): they govern every resource type rather than one
        # plugin's, and the sweep that reads them is reached from File rather than from a document
        self.__settings_dialog.add_page(ChecksumsPage())
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

        if sys.platform == "darwin":
            # pylint: disable-next=import-outside-toplevel
            from .settings.ui.system_integration_page import SystemIntegrationPage

            self.__settings_dialog.add_page(SystemIntegrationPage())

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

        # the queue's own surface while its dock is closed (#239): this window's first
        # addPermanentWidget call, following the model the dock's widget already exposes rather than
        # becoming a second listener on the queue itself
        self.__task_queue_status_indicator = TaskQueueStatusIndicator(self.__task_queue_widget.model)
        self.__task_queue_status_indicator.clicked.connect(lambda: self.__task_queue_dock.toggleView(True))
        self.statusBar().addPermanentWidget(self.__task_queue_status_indicator)

        # image_previews_toggle_action/image_previews_action follow the same primary/companion split
        # as the two pairs above, but neither wraps a dock: both are declared in main_window.ui, and
        # the app-wide ImageViewerSettings singleton -- not a dock's own visibility -- is what the
        # *toggle* (the primary, on the toolbar) drives and is driven by (#71). The companion's
        # shortcutContext is ApplicationShortcut (set in main_window.ui), not the default
        # WindowShortcut: a torn-out QtAds dock is a genuine top-level window of its own (#41's
        # ambiguous-shortcut concern doesn't apply -- there is exactly one action carrying this
        # shortcut), so WindowShortcut would go deaf to Ctrl+Shift+` the moment a floated dock had
        # focus instead of this window.
        self.__image_previews_icon_handler = ActionIconThemeHandler(
            self.__ui.image_previews_toggle_action,
            IMAGE_PREVIEWS_ICON_RESOURCE,
            companion=self.__ui.image_previews_action,
        )
        self.__ui.view_menu.aboutToShow.connect(self.__image_previews_icon_handler.resync_companion_checked_state)
        # seeded from the stored setting rather than left on the .ui's own `checked` default, and
        # seeded *before* the connection below so restoring a hidden-previews launch is not itself
        # written back as a fresh toggle
        self.__ui.image_previews_toggle_action.setChecked(shared_image_viewer_settings().previews_visible)
        self.__ui.image_previews_toggle_action.toggled.connect(self.__on_image_previews_toggled)

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
        self.__ui.action_bar.addAction(self.__ui.image_previews_toggle_action)
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
        # the coordinator is process-wide and outlives this window (#204), so its listener has to be
        # taken back rather than left pointing at a queue that is about to be shut down
        self.__rename_coordinator.remove_rename_listener(self.__task_queue.resync_sources)
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
        """Route to tray (#205), or guard the app close: prompt for dirty documents, saving the
        checked ones.

        **Tray routing comes first.** While the tray icon exists and this close was not requested
        through :meth:`request_quit` (a window close via the titlebar/Alt+F4, not File > Quit or the
        tray menu's own Quit), the event is ignored and the window is hidden instead -- nothing below
        runs, so a document's edits and the task queue are left exactly as they were. The quit flag is
        read and cleared right away, before either branch: a refused guard below must not leave a
        stale "this was a real quit" reading that would skip tray routing on the *next*, unrelated
        close.

        Otherwise, the prompt itself, and the guarded save of each checked document, are the shared
        batch guard
        (:func:`~rehuco_agent.documents.confirm_and_save_dirty.confirm_and_save_dirty`, #176) --
        the same one :meth:`~rehuco_agent.documents.documents_dock.DocumentsDock.close_all` uses. What
        is specific here is the follow-on: a refusal (the prompt cancelled, or a failed save's
        retry/cancel dialog cancelled, #146) aborts the app close, so the window stays open with its
        edits and the session intact. Crucially, that keeps a failure from skipping the persistence
        steps below (window state, session, recents, theme) while the window closes anyway -- once the
        guard has passed, they always run.

        A close accepted while the tray icon exists ends with an **explicit** application quit --
        see the comment on that block for why Qt's own last-window-closed quit cannot be relied on
        for a window that is hidden to tray.

        :param event: the close event to accept or ignore.
        """
        quit_requested = self.__quit_requested
        self.__quit_requested = False
        if self.__tray_icon is not None and not quit_requested:
            event.ignore()
            self.hide_to_tray()
            return

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
        if self.__tray_icon is not None:
            # An explicit quit, not left to Qt's last-window-closed machinery: a window hidden to
            # tray is no longer a *visible* primary window, so closing it never fires that quit --
            # Quit from the tray menu while hidden would run this whole teardown and then leave
            # ``exec()`` running forever, the unquittable-app trap #205 names arriving through the
            # other door (confirmed empirically offscreen). The icon is taken down first so it
            # never outlives the window it controls.
            self.__tray_icon.hide()
            self.__tray_icon.deleteLater()
            self.__tray_icon = None
            if (app := QApplication.instance()) is not None:  # pragma: no branch  (always exists here)
                app.quit()
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
        gaining a new dock behind other windows. ``show()`` alone is what makes this also the tray
        icon's own "Show"/un-hide action (#205): a window hidden to tray is still not minimized, so
        the plain ``show()`` branch is what a forwarded open lands on, exactly like `TrayIcon` itself
        raising it from its menu.

        Every floating dock window :meth:`hide_to_tray` put away comes back with it, before this
        window takes the foreground -- so the main window ends up the active one, with the dialogs
        it owns restored above it rather than stealing the activation on the way up.
        """
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        for container in self.__floating_docks_hidden_with_window:
            container.show()
        self.__floating_docks_hidden_with_window.clear()
        self.raise_()
        self.activateWindow()

        if sys.platform == "win32":
            from borco_pyside.platforms.windows import window_activation  # pylint: disable=import-outside-toplevel

            window_activation.force_foreground(self)

    def hide_to_tray(self) -> None:
        """Hide this window to the tray, taking every floating dock window with it (#205).

        **A floating dock is its own top-level window**, parented to its `CDockManager` rather than
        to this one, so it does not follow a plain ``hide()`` -- a floating Settings dialog would sit
        on screen with nothing behind it, offering Apply on a window the user has just put away
        (confirmed empirically offscreen). Every floating container is found from this window, which
        covers the documents dock's own nested manager as well as the outer one, so a torn-out
        document window follows too.

        Each is hidden rather than closed (``toggleView(False)``), which is what keeps the round trip
        honest in both directions: the dock stays *open* as far as `CDockWidget.isClosed` is
        concerned, so :meth:`raise_and_activate` puts back exactly what was on screen, and a Quit
        from the tray while hidden still persists the dialog as open for the next launch
        (`DockableDialog.save_settings` reads that same flag) rather than recording the tray's own
        bookkeeping as the user's choice.
        """
        for container in self.findChildren(QtAds.CFloatingDockContainer):
            if container.isVisible():
                self.__floating_docks_hidden_with_window.append(container)
                container.hide()
        self.hide()

    def request_quit(self) -> None:
        """Ask this window to close as an explicit quit (#205) -- the one thing that overrides tray
        mode's close-to-tray routing, from either ``File`` > ``Quit`` or the tray menu's own
        ``Quit``.

        Sets the flag :meth:`closeEvent` reads (and clears) before calling :meth:`close`, so the
        guarded close path -- the same one a plain window close runs -- decides whether the app can
        actually quit; a cancelled dirty-document prompt or task-queue warning leaves the window
        (and, while tray mode is on, the tray icon) exactly as they were.
        """
        self.__quit_requested = True
        self.close()

    def __on_tray_enabled_changed(self, enabled: bool) -> None:
        """Create or tear down the tray icon as `TraySettings.enabled` changes (#205) -- live, not
        just on the next launch, the same immediacy `MarkdownRenderingSettings` gives an open
        description viewer.

        **Refuses to engage without a real tray to show in.** A tray-only app with no visible window
        and no icon would be unquittable, so this leaves :attr:`__tray_icon` ``None`` -- and
        :meth:`closeEvent` closing exactly as if the setting were off -- whenever
        ``QSystemTrayIcon.isSystemTrayAvailable()`` is false (bare Linux sessions, chiefly).

        :param enabled: the newly-set value of `TraySettings.enabled`.
        """
        if enabled and QSystemTrayIcon.isSystemTrayAvailable():
            if self.__tray_icon is None:
                self.__tray_icon = TrayIcon(self, QIcon(TRAY_ICON_RESOURCE))
                self.__tray_icon.show()
        elif self.__tray_icon is not None:
            self.__tray_icon.hide()
            self.__tray_icon.deleteLater()
            self.__tray_icon = None
