"""The Add Root dialog: where the new root is, and what it is called (#378, #514)."""

from pathlib import Path
from typing import Final, override

from borco_pyside.theming import ActionIconThemeHandler
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLineEdit,
    QPushButton,
    QWidget,
)
from rehuco_core import RehucoFile

from ..settings.persistent_settings import persistent_settings
from ..settings.root_catalog_settings import shared_root_catalog_settings
from .add_root_dialog_ui import Ui_AddRootDialog

DEFAULT_NAME_ICON: Final = ":/icons/settings_reset_to_defaults.svg"
"""The icon of the settings pages' *defaults* button, on the button that puts the folder's name back."""


class AddRootDialog(QDialog):
    """Asks for a new root: its folder and its name.

    What the folder lives on is not asked: it is detected when the root is mapped on this machine.

    **The name defaults to the folder's name**: it is shown as the field's placeholder, filled in once a folder is
    chosen (browsed to, or typed and left) while the field is empty -- a folder chosen later leaves a name already
    there alone -- and a button beside the field puts it back. Closing with the field empty uses it.

    **Scan after adding** shows the Root Catalog setting of that name and writes it back, saved, however the dialog
    closes, like a dialog's geometry.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui = Ui_AddRootDialog()
        self.__ui.setupUi(self)
        self.__ui.scan_after_adding_check_box.setChecked(shared_root_catalog_settings().scan_after_adding)
        self.__ui.browse_button.clicked.connect(self.__browse)
        self.__default_name_action = QAction("Use Folder Name", self)
        self.__default_name_action.setToolTip("Use the folder's name")
        ActionIconThemeHandler(self.__default_name_action, DEFAULT_NAME_ICON)
        self.__ui.default_name_button.setDefaultAction(self.__default_name_action)
        self.__default_name_action.triggered.connect(self.__use_default_name)
        self.__ui.folder_edit.textChanged.connect(self.__update_folder)
        self.__ui.folder_edit.editingFinished.connect(self.__fill_name)
        self.__ui.name_edit.textChanged.connect(self.__update_default_name)
        self.__update_folder()

    @property
    def folder(self) -> str:
        """The folder as typed, without surrounding blanks."""
        return self.__ui.folder_edit.text().strip()

    @folder.setter
    def folder(self, folder: str) -> None:
        self.__ui.folder_edit.setText(folder)

    @property
    def default_name(self) -> str:
        """The name a root gets when none is typed: the folder's name; empty while no folder is named."""
        return RehucoFile.default_label(self.folder) if self.folder else ""

    @property
    def name(self) -> str:
        """The name as typed, without surrounding blanks, or the default one when nothing is typed."""
        return self.__ui.name_edit.text().strip() or self.default_name

    @property
    def name_edit(self) -> QLineEdit:
        """The name field, for tests."""
        return self.__ui.name_edit

    @property
    def default_name_action(self) -> QAction:
        """Puts the folder's name in the name field; enabled while the field differs from it."""
        return self.__default_name_action

    @property
    def scan_after_adding(self) -> bool:
        """Whether the checkbox asks for the new root to be scanned."""
        return self.__ui.scan_after_adding_check_box.isChecked()

    @property
    def scan_after_adding_check_box(self) -> QCheckBox:
        """The *Scan after adding* checkbox, for tests."""
        return self.__ui.scan_after_adding_check_box

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
            self.__fill_name()

    def __update_folder(self) -> None:
        """Follow the folder as it changes: OK only while an absolute one is named -- a relative one would be read
        against whatever the app's working directory happens to be, which the folder picker beside the field can never
        hand back -- and its name as the name field's placeholder."""
        self.ok_button.setEnabled(Path(self.folder).is_absolute())
        self.__ui.name_edit.setPlaceholderText(self.default_name)
        self.__update_default_name()

    def __update_default_name(self) -> None:
        """Enable the default-name button while there is a name to put and the field is not it already."""
        default = self.default_name
        self.__default_name_action.setEnabled(bool(default) and self.__ui.name_edit.text().strip() != default)

    def __fill_name(self) -> None:
        """Put the folder's name in the name field -- only while the field is empty."""
        if not self.__ui.name_edit.text().strip():
            self.__ui.name_edit.setText(self.default_name)

    def __use_default_name(self) -> None:
        """Put the folder's name in the name field, whatever is there."""
        self.__ui.name_edit.setText(self.default_name)
