"""The Add Root dialog: what the new root lives on, then where it is (#378)."""

from pathlib import Path

from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFileDialog, QPushButton, QWidget
from rehuco_core import RootStorage

from .add_root_dialog_ui import Ui_AddRootDialog
from .root_storage import fill_root_storage_combo, selected_root_storage


class AddRootDialog(QDialog):
    """Asks for a new root: its **storage** first, then the folder.

    The storage is on top because it will decide what is asked below it: today every storage is a folder on a disk
    this machine can see, so one folder picker serves all four, but a root served by another node will want a picker
    over the swarm's roots instead (Release 0.4.0, [[nodes#access-seam]]).

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui = Ui_AddRootDialog()
        self.__ui.setupUi(self)
        fill_root_storage_combo(self.__ui.storage_combo)
        self.__ui.browse_button.clicked.connect(self.__browse)
        self.__ui.folder_edit.textChanged.connect(self.__update_ok)
        self.__update_ok()

    @property
    def storage(self) -> RootStorage:
        """The storage the combo shows."""
        return selected_root_storage(self.__ui.storage_combo)

    @property
    def folder(self) -> str:
        """The folder as typed, without surrounding blanks."""
        return self.__ui.folder_edit.text().strip()

    @folder.setter
    def folder(self, folder: str) -> None:
        self.__ui.folder_edit.setText(folder)

    @property
    def storage_combo(self) -> QComboBox:
        """The storage combo, for tests."""
        return self.__ui.storage_combo

    @property
    def ok_button(self) -> QPushButton:
        """The OK button, which needs a folder."""
        return self.__ui.button_box.button(QDialogButtonBox.StandardButton.Ok)

    def __browse(self) -> None:
        """Pick the folder with the system's folder dialog, starting where the typed one is."""
        start = self.folder if Path(self.folder).is_dir() else ""
        chosen = QFileDialog.getExistingDirectory(self, "Add Root", start)
        if chosen:
            self.folder = chosen

    def __update_ok(self) -> None:
        """Enable OK only while an absolute folder is named: a relative one would be read against whatever the app's
        working directory happens to be, which the folder picker beside the field can never hand back."""
        self.ok_button.setEnabled(Path(self.folder).is_absolute())
