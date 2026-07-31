"""The two action columns a list editor is built from: what a row *is*, and where it sits."""

from typing import Final

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QWidget

from .action_button_column import ActionButtonColumn


class ItemActionsColumn(ActionButtonColumn):
    """Insert / Edit / Delete / Reset -- the four actions that change *what* a list holds.

    Two of them act on the current row and two on the list as a whole, which is the whole enabled-state
    rule: an owner disables :attr:`edit_action` and :attr:`delete_action` while nothing is current, and
    leaves :attr:`insert_action` alone, since insert is how an empty list gets its first row.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__insert_action: Final = self.add_action(
            "Insert", "Insert a new entry below the current one", QKeySequence(Qt.Key.Key_Insert)
        )
        self.__edit_action: Final = self.add_action("Edit", "Edit the current entry", QKeySequence(Qt.Key.Key_F2))
        self.__delete_action: Final = self.add_action(
            "Delete", "Delete the current entry", QKeySequence(QKeySequence.StandardKey.Delete)
        )
        self.__reset_action: Final = self.add_action("Reset", "Replace the list with the default entries")

    @property
    def insert_action(self) -> QAction:
        """Add a new entry below the current one -- and the only way into an emptied list."""
        return self.__insert_action

    @property
    def edit_action(self) -> QAction:
        """Reopen the current entry for typing."""
        return self.__edit_action

    @property
    def delete_action(self) -> QAction:
        """Drop the current entry."""
        return self.__delete_action

    @property
    def reset_action(self) -> QAction:
        """Replace the whole list with its defaults."""
        return self.__reset_action


class ItemOrderingColumn(ActionButtonColumn):
    """Top / Up / Down / Bottom -- the four actions that change *where* the current row sits.

    All four act on the current row, so an owner disables the lot while nothing is current, the two
    upward ones on the first row, and the two downward ones on the last.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__move_to_top_action: Final = self.add_action(
            "Move to Top",
            "Move the current entry to the top",
            QKeySequence(Qt.KeyboardModifier.ControlModifier | Qt.Key.Key_Home),
        )
        self.__move_up_action: Final = self.add_action(
            "Move Up",
            "Move the current entry up one place",
            QKeySequence(Qt.KeyboardModifier.ControlModifier | Qt.Key.Key_Up),
        )
        self.__move_down_action: Final = self.add_action(
            "Move Down",
            "Move the current entry down one place",
            QKeySequence(Qt.KeyboardModifier.ControlModifier | Qt.Key.Key_Down),
        )
        self.__move_to_bottom_action: Final = self.add_action(
            "Move to Bottom",
            "Move the current entry to the bottom",
            QKeySequence(Qt.KeyboardModifier.ControlModifier | Qt.Key.Key_End),
        )

    @property
    def move_to_top_action(self) -> QAction:
        """Move the current entry to the first row."""
        return self.__move_to_top_action

    @property
    def move_up_action(self) -> QAction:
        """Move the current entry one row up."""
        return self.__move_up_action

    @property
    def move_down_action(self) -> QAction:
        """Move the current entry one row down."""
        return self.__move_down_action

    @property
    def move_to_bottom_action(self) -> QAction:
        """Move the current entry to the last row."""
        return self.__move_to_bottom_action
