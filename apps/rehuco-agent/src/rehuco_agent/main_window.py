"""Top-level `QtAds` dock-in-dock shell hosting the open-documents area ([[plugins#toolkit-surfaces]])."""

import sys
from pathlib import Path
from typing import Final, override

import PySide6QtAds as QtAds
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QDialog, QMainWindow

from rehuco_agent.documents_dock import DocumentsDock
from rehuco_agent.main_window_ui import Ui_MainWindow
from rehuco_agent.unsaved_changes_dialog import UnsavedChangesDialog


class MainWindow(QMainWindow):
    """The single top-level window: a `CDockManager` whose central dock hosts :class:`DocumentsDock`.

    Dock-in-dock (a `CDockManager` inside the central dock's `DocumentsDock`, itself inside this
    window's own `CDockManager`) leaves room for a future resource browser to dock alongside the
    open documents ([[packaging-deployment#qml-regression]]) without restructuring this shell.
    """

    def __init__(self) -> None:
        super().__init__()

        self.__ui: Final = Ui_MainWindow()
        self.__ui.setupUi(self)
        self.centralWidget().hide()

        self.__documents_dock: Final = DocumentsDock(self)
        self.__setup_docking_system()

    def __setup_docking_system(self) -> None:
        dock_manager = QtAds.CDockManager(self)

        central_dock = QtAds.CDockWidget(dock_manager, "Central Widget")
        central_dock.setWidget(self.__documents_dock)
        central_dock.setFeature(QtAds.CDockWidget.NoTab, True)

        dock_manager.setCentralWidget(central_dock)

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

        super().closeEvent(event)

    def open_file(self, path: Path | str) -> None:
        """Open ``path`` in its document dock, focusing it if already open ([[nodes#single-instance]]).

        :param path: filesystem path to a ``.rehu`` file.
        """
        self.__documents_dock.open_document(Path(path).resolve())

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
