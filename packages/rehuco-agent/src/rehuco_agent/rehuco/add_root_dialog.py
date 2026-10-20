"""The Add Root dialog: what the new root lives on, then where it is (#378)."""

from pathlib import Path
from typing import override

from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QPushButton, QWidget
from rehuco_core import RootStorage

from ..settings.persistent_settings import persistent_settings
from ..settings.root_catalog_settings import shared_root_catalog_settings
from .add_root_dialog_ui import Ui_AddRootDialog
from .root_storage import fill_root_storage_combo, selected_root_storage


class AddRootDialog(QDialog):
    """Asks for a new root: its **storage** first, then the folder.

    The storage is on top because it may decide what is asked below it: every storage is a folder on a disk this
    machine can see, so one folder picker serves all four.

    **Scan after adding** shows the Root Catalog setting of that name and writes it back, saved, however the dialog
    closes, like a dialog's geometry.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui = Ui_AddRootDialog()
        self.__ui.setupUi(self)
        fill_root_storage_combo(self.__ui.storage_combo)
        self.__ui.scan_after_adding_check_box.setChecked(shared_root_catalog_settings().scan_after_adding)
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
    def scan_after_adding(self) -> bool:
        """Whether the checkbox asks for the new root to be scanned."""
        return self.__ui.scan_after_adding_check_box.isChecked()

    @property
    def scan_after_adding_check_box(self) -> QCheckBox:
        """The *Scan after adding* checkbox, for tests."""
        return self.__ui.scan_after_adding_check_box

    @property
    def storage_combo(self) -> QComboBox:
        """The storage combo, for tests."""
        return self.__ui.storage_combo

    @property
    def ok_button(self) -> QPushButton:
        """The OK button, which needs a folder."""
        return self.__ui.button_box.button(QDialogButtonBox.StandardButton.Ok)

    @override
    def done(self, result: int) -> None:
        """Remember the *Scan after adding* choice, on every exit path, before closing.

        :param result: the dialog's result code, passed straight through to :meth:`QDialog.done`.
        """
        settings = shared_root_catalog_settings()
        if settings.scan_after_adding != self.scan_after_adding:
            settings.scan_after_adding = self.scan_after_adding
            settings.save(persistent_settings())
        super().done(result)

    def __browse(self) -> None:
        """Pick the folder with the system's folder dialog, starting where the typed one is."""
        chosen = QFileDialog.getExistingDirectory(self, "Add Root", self.folder)
        if chosen:
            self.folder = chosen

    def __update_ok(self) -> None:
        """Enable OK only while an absolute folder is named: a relative one would be read against whatever the app's
        working directory happens to be, which the folder picker beside the field can never hand back."""
        self.ok_button.setEnabled(Path(self.folder).is_absolute())
