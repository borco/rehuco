"""Top-level `QtAds` dock-in-dock shell hosting the open-documents area ([[plugins#toolkit-surfaces]])."""

import sys
from pathlib import Path
from typing import Final, override

import PySide6QtAds as QtAds
from borco_pyside.dialogs import DockableDialog, DockableDialogManager
from borco_pyside.theming import ActionIconThemeHandler, ThemeManager
from PySide6.QtCore import QByteArray
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QDialog, QMainWindow

from rehuco_agent.dialogs.settings_dialog import SettingsDialog
from rehuco_agent.dialogs.unsaved_changes_dialog import UnsavedChangesDialog
from rehuco_agent.documents.document_widget import DocumentWidget
from rehuco_agent.documents.documents_dock import DocumentsDock
from rehuco_agent.main_window_ui import Ui_MainWindow
from rehuco_agent.settings.document_session_settings import DocumentSessionSettings
from rehuco_agent.settings.main_window_settings import TOOLBARS_STATE_VERSION, MainWindowSettings
from rehuco_agent.settings.persistent_settings import persistent_settings

SETTINGS_DIALOG_OBJECT_NAME: Final = "settings_dialog"
SETTINGS_ICON_RESOURCE: Final = ":/icons/app_settings.svg"

ARCHIVE_EXTENSIONS: Final = (".zip",)
"""Archive file extensions (each including the leading dot) that get a file-scoped ``.rehu``
companion ([[data-model#resource-scoping]]) via :meth:`MainWindow.open_archive`, instead of being
opened directly like a bare ``.rehu`` file."""


class MainWindow(QMainWindow):  # pylint: disable=too-many-instance-attributes
    """The single top-level window: a `CDockManager` whose central dock hosts :class:`DocumentsDock`,
    with a settings dock (#47) as a sibling -- beside the documents area, not merged into it.

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

        self.__window_settings: Final = MainWindowSettings()
        self.__window_settings.load(persistent_settings())
        if self.__window_settings.geometry:
            self.restoreGeometry(QByteArray(self.__window_settings.geometry))
        self.restoreState(QByteArray(self.__window_settings.toolbars_state), TOOLBARS_STATE_VERSION)
        self.__dock_manager.restoreState(QByteArray(self.__window_settings.outer_docks_state))
        self.__dialog_manager.restore_all(persistent_settings())

        self.__session: Final = DocumentSessionSettings()
        self.__session.load(persistent_settings())
        self.__restore_session()

        ThemeManager(
            self.__ui.theme_action,
            system_icon=":/icons/theme_auto.svg",
            light_icon=":/icons/theme_light.svg",
            dark_icon=":/icons/theme_dark.svg",
        )

    def __on_document_focus_changed(self, widget: DocumentWidget | None) -> None:
        """Reflect the newly-focused document's label in the window title, or the base title if none.

        :param widget: the newly-focused document's widget, or ``None`` when no document is focused.
        """
        label = widget.model.label if widget is not None else ""
        self.setWindowTitle(f"{label} - {self.__base_window_title}" if label else self.__base_window_title)

    def __register_settings_pages(self) -> None:
        """Register every settings category page this platform supports (#47).

        The Registry page is Windows-only (it wraps ``winreg``-backed HKCU registration) --
        imported lazily, only here, mirroring the same gate ``rehuco_agent.windows_registration``
        (and the ``borco_core.platforms.windows.*`` modules it wraps) already requires.
        """
        if sys.platform == "win32":
            # pylint: disable-next=import-outside-toplevel
            from rehuco_agent.dialogs.settings_pages.registry_page import RegistryPage

            self.__settings_dialog.add_page(RegistryPage(ARCHIVE_EXTENSIONS))

    def __setup_docking_system(self) -> None:
        central_dock = QtAds.CDockWidget(self.__dock_manager, "Central Widget")
        central_dock.setWidget(self.__documents_dock)
        central_dock.setFeature(QtAds.CDockWidget.NoTab, True)

        central_area = self.__dock_manager.setCentralWidget(central_dock)

        settings_dock = DockableDialog(
            self.__dock_manager, SETTINGS_DIALOG_OBJECT_NAME, "Settings", self.__settings_dialog
        )
        self.__dock_manager.addDockWidget(QtAds.RightDockWidgetArea, settings_dock.dock, central_area)
        self.__dialog_manager.register(settings_dock)
        ActionIconThemeHandler(settings_dock.toggle_action, SETTINGS_ICON_RESOURCE)
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

        self.__save_window_state()
        self.__dialog_manager.save_all(persistent_settings())
        self.__save_session()
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

        :param path: filesystem path to a ``.rehu`` file.
        """
        self.__documents_dock.open_document(Path(path).resolve())

    def open_folder(self, path: Path | str) -> None:
        """Open the directory-scoped resource at ``path`` ([[data-model#resource-scoping]]), focusing
        it if already open ([[nodes#single-instance]]).

        :param path: filesystem path to the directory.
        """
        self.__documents_dock.open_folder(Path(path).resolve())

    def open_archive(self, path: Path | str) -> None:
        """Open the file-scoped resource for the archive at ``path`` ([[data-model#resource-scoping]]),
        focusing it if already open ([[nodes#single-instance]]).

        :param path: filesystem path to the archive file (e.g. ``foo.zip``); its ``.rehu`` companion
            (e.g. ``foo.rehu``) is what actually gets opened or created.
        """
        self.__documents_dock.open_archive(Path(path).resolve())

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
