"""One program holding a refused rename's files, as `.RenameHoldersDialog` lists it (#505)."""

from typing import Final

from borco_core import FileHolder
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

from .holder_row_ui import Ui_HolderRow

ROW_TEXT: Final = "{name} — process {pid}"
"""How a holder is named: as the operating system names it, and by its process id, which tells apart two
copies of one program."""


class HolderRow(QWidget):
    """A holder's name, and the two things to do about it: *Show App* and *End Task*.

    What the buttons do is the dialog's: the row only asks.

    :param holder: the program.
    :param can_show: whether it has a window to show; *Show App* is disabled when it has none.
    :param parent: optional Qt parent.
    """

    show_requested = Signal(int)
    """*Show App* was clicked, with the holder's pid."""

    end_requested = Signal(int)
    """*End Task* was clicked, with the holder's pid."""

    def __init__(self, holder: FileHolder, can_show: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__holder: Final = holder
        self.__ui: Final = Ui_HolderRow()
        self.__ui.setupUi(self)
        self.__ui.name_label.setText(ROW_TEXT.format(name=holder.name, pid=holder.pid))
        self.__ui.show_button.setEnabled(can_show)
        self.__ui.show_button.clicked.connect(self.__on_show_clicked)
        self.__ui.end_button.clicked.connect(self.__on_end_clicked)

    @property
    def holder(self) -> FileHolder:
        """The program this row is about."""
        return self.__holder

    def set_ending(self, ending: bool) -> None:
        """Disable *End Task* while the program is being ended, and enable it again when that did not end it.

        :param ending: whether the program is being ended.
        """
        self.__ui.end_button.setEnabled(not ending)

    def __on_show_clicked(self) -> None:
        """Ask for the holder's window to be shown."""
        self.show_requested.emit(self.__holder.pid)

    def __on_end_clicked(self) -> None:
        """Ask for the holder to be ended."""
        self.end_requested.emit(self.__holder.pid)
