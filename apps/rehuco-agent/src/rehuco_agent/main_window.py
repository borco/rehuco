"""Top-level `QtAds` dock-in-dock shell hosting the open-documents area ([[plugins#toolkit-surfaces]])."""

import sys
from pathlib import Path
from typing import Final, override

import PySide6QtAds as QtAds
from borco_pyside.dialogs import DockableDialog, DockableDialogManager
from borco_pyside.theming import ActionIconThemeHandler, ThemeManager
from PySide6.QtCore import QByteArray
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QDialog, QFileDialog, QMainWindow, QSizePolicy, QWidget, QWidgetAction

from rehuco_agent.dialogs.unsaved_changes_dialog import UnsavedChangesDialog
from rehuco_agent.docks_menu_entry import DocksMenuEntry
from rehuco_agent.documents.document_widget import DocumentWidget
from rehuco_agent.documents.documents_dock import DocumentsDock
from rehuco_agent.main_window_ui import Ui_MainWindow
from rehuco_agent.settings.document_session_settings import DocumentSessionSettings
from rehuco_agent.settings.main_window_settings import TOOLBARS_STATE_VERSION, MainWindowSettings
from rehuco_agent.settings.persistent_settings import persistent_settings
from rehuco_agent.settings.recent_files_settings import RecentFilesSettings
from rehuco_agent.settings.ui.markdown_rendering_page import MarkdownRenderingPage
from rehuco_agent.settings.ui.settings_dialog import SettingsDialog

SETTINGS_DIALOG_OBJECT_NAME: Final = "settings_dialog"
SETTINGS_ICON_RESOURCE: Final = ":/icons/app_settings.svg"

ARCHIVE_EXTENSIONS: Final = (".zip",)
"""Archive file extensions (each including the leading dot) that get a file-scoped ``.rehu``
companion ([[data-model#resource-scoping]]) via :meth:`MainWindow.open_archive`, instead of being
opened directly like a bare ``.rehu`` file."""


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

        self.__dialog_manager: Final = DockableDialogManager()
        self.__dock_manager: Final = QtAds.CDockManager(self)
        self.__settings_dialog: Final = SettingsDialog()
        self.__register_settings_pages()

        self.__documents_dock: Final = DocumentsDock(self)
        self.__documents_dock.document_focus_changed.connect(self.__on_document_focus_changed)
        self.__setup_docking_system()
        self.__ui.view_menu.aboutToShow.connect(self.__populate_docks_menu)
        self.__setup_file_menu()

        self.__window_settings: Final = MainWindowSettings()
        self.__window_settings.load(persistent_settings())
        if self.__window_settings.geometry:
            self.restoreGeometry(QByteArray(self.__window_settings.geometry))
        self.restoreState(QByteArray(self.__window_settings.toolbars_state), TOOLBARS_STATE_VERSION)

        self.__recent_files: Final = RecentFilesSettings()
        self.__recent_files.load(persistent_settings())

        self.__session: Final = DocumentSessionSettings()
        self.__session.load(persistent_settings())
        self.__restore_session()

        self.__dialog_manager.restore_all(persistent_settings())

        ThemeManager(
            self.__ui.theme_action,
            system_icon=":/icons/theme_auto.svg",
            light_icon=":/icons/theme_light.svg",
            dark_icon=":/icons/theme_dark.svg",
        )

        # must be called after restoring the geometry and the session (open documents) so
        # the outer dock layout can be restored to the right place, and any floating
        # dialog's own window is already created and ready to be restored to its prior
        # visibility (#47, #55)
        self.__dock_manager.restoreState(QByteArray(self.__window_settings.outer_docks_state))

    def __on_document_focus_changed(self, widget: DocumentWidget | None) -> None:
        """Reflect the newly-focused document's label in the window title, or the base title if none.

        :param widget: the newly-focused document's widget, or ``None`` when no document is focused.
        """
        label = widget.model.label if widget is not None else ""
        self.setWindowTitle(f"{label} - {self.__base_window_title}" if label else self.__base_window_title)

    def __populate_docks_menu(self) -> None:
        """Rebuild ``View`` with every currently open document, alphabetically by title (#61).

        Listed directly under ``View`` rather than a ``Docks`` submenu, for now. Rebuilt fresh on
        every ``aboutToShow`` rather than kept in sync incrementally -- the open set, titles, and
        paths all change independently (open/close/rename/save-as), and a menu only actually needs
        to be correct while it's showing.
        """
        menu = self.__ui.view_menu
        menu.clear()
        widgets = sorted(
            self.__documents_dock.open_document_widgets(), key=lambda widget: widget.model.label.casefold()
        )
        if not widgets:
            placeholder = menu.addAction("No Open Docks")
            placeholder.setEnabled(False)
            return
        for widget in widgets:
            action = QWidgetAction(menu)
            action.setDefaultWidget(DocksMenuEntry(widget.model.label, widget.model.path, menu))
            action.triggered.connect(lambda _checked=False, widget=widget: self.__documents_dock.focus_document(widget))
            menu.addAction(action)

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
        per-document ``RehuDocumentModel.save``, #64)."""
        for model in self.__documents_dock.open_document_models():
            if model.dirty:
                model.save()

    def __populate_recents_menu(self) -> None:
        """Rebuild ``Open recents`` with the most-recently-opened paths, newest first (#64).

        Rebuilt fresh on every ``aboutToShow`` rather than kept in sync incrementally, mirroring
        :meth:`__populate_docks_menu`.
        """
        menu = self.__ui.open_recents_menu
        menu.clear()
        paths = self.__recent_files.newest_first()
        if not paths:
            placeholder = menu.addAction("No Recent Files")
            placeholder.setEnabled(False)
            return
        for path in paths:
            action = menu.addAction(str(path))
            action.triggered.connect(lambda _checked=False, path=path: self.open_path(path))

    def __register_settings_pages(self) -> None:
        """Register every settings category page this platform supports (#47).

        Markdown Rendering is cross-platform. The Registry page is Windows-only (it wraps
        ``winreg``-backed HKCU registration) -- imported lazily, only here, mirroring the same gate
        ``rehuco_agent.windows_registration`` (and the ``borco_core.platforms.windows.*`` modules
        it wraps) already requires.
        """
        self.__settings_dialog.add_page(MarkdownRenderingPage())
        if sys.platform == "win32":
            # pylint: disable-next=import-outside-toplevel
            from rehuco_agent.settings.ui.registry_page import RegistryPage

            self.__settings_dialog.add_page(RegistryPage(ARCHIVE_EXTENSIONS))

    def __setup_docking_system(self) -> None:
        central_dock = QtAds.CDockWidget(self.__dock_manager, "Central Widget")
        central_dock.setWidget(self.__documents_dock)
        central_dock.setFeature(QtAds.CDockWidget.NoTab, True)

        self.__dock_manager.setCentralWidget(central_dock)

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
        self.__ui.action_bar.addAction(settings_dock.toggle_action)

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        """Guard the app close: prompt for dirty documents, saving the checked ones.

        Cancelling the prompt aborts the app close; nothing closes. Unchecked dirty documents are
        left unsaved -- their edits are discarded along with the close.

        :param event: the close event to accept or ignore.
        """
        dirty_models = [model for model in self.__documents_dock.open_document_models() if model.dirty]
        if dirty_models:
            dialog = UnsavedChangesDialog(dirty_models, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                event.ignore()
                return
            for model in dialog.selected_models():
                model.save()

        # must run before __save_window_state captures the outer CDockManager's saveState(), or a
        # floating-and-visible-but-unchecked dialog gets saved that way anyway and flashes open on
        # the next launch before __init__'s dialog_manager.restore_all() notices the checkbox (#47)
        self.__dialog_manager.enforce_restore_on_start()
        self.__save_window_state()
        self.__dialog_manager.save_all(persistent_settings())
        self.__save_session()
        self.__recent_files.save(persistent_settings())
        super().closeEvent(event)

    def __restore_session(self) -> None:
        """Reopen every document the last session left open, restoring its dock layout and focus.

        A path that no longer exists or fails to load is skipped silently (``open_document``
        already showed an error dialog for it, #35) -- the rest of the session still restores.
        The outer layout (splits/tabs between documents) is restored only once every document
        it references has already been reopened above -- ``DocumentsDock.restore_state`` matches
        saved entries up to currently-registered docks by name, it does not create any itself.
        """
        opened: dict[Path, DocumentWidget] = {}
        for path, item in self.__session.items.items():
            if not item.open:
                continue
            widget = self.__documents_dock.open_document(path)
            if widget is not None:
                widget.restore_state(item.state)
                opened[path] = widget

        self.__documents_dock.restore_state(self.__session.docks_state)

        focused_path = self.__session.focused_path
        if focused_path is not None and focused_path in opened:
            self.__documents_dock.open_document(focused_path)  # re-focuses an already-open dock

    def __save_window_state(self) -> None:
        """Persist this window's current size/position, toolbar layout, and outer dock layout."""
        self.__window_settings.geometry = bytes(self.saveGeometry().data())
        self.__window_settings.toolbars_state = bytes(self.saveState(TOOLBARS_STATE_VERSION).data())
        self.__window_settings.outer_docks_state = bytes(self.__dock_manager.saveState().data())
        self.__window_settings.save(persistent_settings())

    def __save_session(self) -> None:
        """Snapshot every open document's dock layout and focus, and persist the open-file set.

        Currently open documents always count as the most-recently-used ones (moved to the end of
        the LRU order); everything else keeps its prior state but is marked closed.
        """
        open_widgets = {
            widget.model.path: widget
            for widget in self.__documents_dock.open_document_widgets()
            if widget.model.path is not None
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

        Recorded into ``Open recents`` (#64) on success, alongside :meth:`open_folder`/:meth:`open_archive`.

        :param path: filesystem path to a ``.rehu`` file.
        """
        resolved = Path(path).resolve()
        if self.__documents_dock.open_document(resolved) is not None:
            self.__recent_files.record(resolved)

    def open_folder(self, path: Path | str) -> None:
        """Open the directory-scoped resource at ``path`` ([[data-model#resource-scoping]]), focusing
        it if already open ([[nodes#single-instance]]).

        Recorded into ``Open recents`` (#64) on success, alongside :meth:`open_file`/:meth:`open_archive`.

        :param path: filesystem path to the directory.
        """
        resolved = Path(path).resolve()
        if self.__documents_dock.open_folder(resolved) is not None:
            self.__recent_files.record(resolved)

    def open_archive(self, path: Path | str) -> None:
        """Open the file-scoped resource for the archive at ``path`` ([[data-model#resource-scoping]]),
        focusing it if already open ([[nodes#single-instance]]).

        Recorded into ``Open recents`` (#64) on success, alongside :meth:`open_file`/:meth:`open_folder`.

        :param path: filesystem path to the archive file (e.g. ``foo.zip``); its ``.rehu`` companion
            (e.g. ``foo.rehu``) is what actually gets opened or created.
        """
        resolved = Path(path).resolve()
        if self.__documents_dock.open_archive(resolved) is not None:
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
