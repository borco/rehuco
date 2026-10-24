"""One root of the mapping wizard: where it is shared, and where this machine finds it (#514)."""

from pathlib import Path
from typing import Final

from PySide6.QtWidgets import QFileDialog, QWidget
from rehuco_core import RehucoRoot

from .map_root_row_ui import Ui_MapRootRow
from .roots_node import root_title


class MapRootRow(QWidget):
    """A root's label and location, a folder to map it to and a *Skip* box that sets the folder aside.

    :param root: the root to ask about.
    :param parent: optional Qt parent.
    """

    def __init__(self, root: RehucoRoot, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.root: Final = root
        self.__ui: Final = Ui_MapRootRow()
        self.__ui.setupUi(self)
        self.__ui.label_label.setText(root_title(root))
        self.__ui.location_edit.setText(root.location)
        self.__ui.location_edit.setToolTip(root.location)
        self.__ui.browse_button.clicked.connect(self.browse)
        self.__ui.skip_check_box.toggled.connect(self.__on_skip_toggled)

    @property
    def skipped(self) -> bool:
        """Whether the user chose not to map this root on this machine."""
        return self.__ui.skip_check_box.isChecked()

    @property
    def folder(self) -> Path | None:
        """The folder typed or browsed to; ``None`` when the row is skipped, blank or not an absolute path."""
        text = self.__ui.path_edit.text().strip()
        if self.skipped or not text:
            return None
        path = Path(text)
        return path if path.is_absolute() else None

    def browse(self) -> None:
        """Let the user pick the folder, and put it in the path line when one is picked."""
        chosen = self.choose_folder()
        if chosen:
            self.__ui.path_edit.setText(chosen)

    def choose_folder(self) -> str:
        """Ask for a folder, starting from the one already typed.

        A public method rather than an inline dialog, so a test replaces the question on the instance.

        :returns: the folder picked, or an empty string when the dialog was cancelled.
        """
        return QFileDialog.getExistingDirectory(self, f"Folder of {root_title(self.root)}", self.__ui.path_edit.text())

    def __on_skip_toggled(self, skipped: bool) -> None:
        """A skipped row's folder cannot be changed.

        :param skipped: whether *Skip* is now checked.
        """
        self.__ui.path_edit.setEnabled(not skipped)
        self.__ui.browse_button.setEnabled(not skipped)
