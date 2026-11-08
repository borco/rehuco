"""The Add Roots dialog's *New layout…*: a named preset of layouts and fallbacks, added to the settings (#578)."""

from typing import Final

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QPushButton, QWidget
from rehuco_core import DEFAULT_LAYOUTS

from ..settings.root_catalog_settings import RootLayout
from .new_layout_dialog_ui import Ui_NewLayoutDialog
from .root_layouts_editor import RootLayoutsEditor


class NewLayoutDialog(QDialog):
    """Asks for a preset's name and its maps, starting from a root made from a folder's default; OK needs a name no
    other preset has.

    :param taken: the names the presets have, which a new one may not take.
    :param parent: optional Qt parent.
    """

    def __init__(self, taken: frozenset[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_NewLayoutDialog()
        self.__ui.setupUi(self)
        self.__taken: Final = frozenset(name.casefold() for name in taken)
        self.__ui.layouts_editor.set_values(DEFAULT_LAYOUTS, {})
        self.__ui.name_edit.textChanged.connect(self.__update_ok)
        self.__update_ok()

    @property
    def preset(self) -> RootLayout:
        """The preset as it stands."""
        editor = self.__ui.layouts_editor
        return RootLayout(self.__ui.name_edit.text().strip(), editor.layouts, editor.fallbacks)

    @property
    def layouts_editor(self) -> RootLayoutsEditor:
        """The maps' editor, for tests."""
        return self.__ui.layouts_editor

    @property
    def ok_button(self) -> QPushButton:
        """The OK button, for tests."""
        return self.__ui.button_box.button(QDialogButtonBox.StandardButton.Ok)

    def set_name(self, name: str) -> None:
        """Type a name, for tests.

        :param name: the name.
        """
        self.__ui.name_edit.setText(name)

    def __update_ok(self) -> None:
        """Let OK through only while the name is one no other preset has."""
        name = self.__ui.name_edit.text().strip()
        self.ok_button.setEnabled(bool(name) and name.casefold() not in self.__taken)
