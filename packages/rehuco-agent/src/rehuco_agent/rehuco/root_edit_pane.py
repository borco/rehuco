"""The Roots view's edit mode for a root: its name, its layouts and its fallbacks, editable (#514, #578)."""

from typing import Final

from PySide6.QtWidgets import QApplication, QLineEdit, QToolButton, QWidget

from .root_edit_pane_ui import Ui_RootEditPane
from .root_layouts_editor import RootLayoutsEditor


class RootEditPane(QWidget):
    """The editors the details pane shows for a root while the Roots view's *Edit* is on: the name field with its
    default-name button, and the layouts and fallbacks tables. What they say is the owner's to fill and to write.

    :param parent: optional Qt parent; what a ``.ui`` promotes the widget with.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_RootEditPane()
        self.__ui.setupUi(self)

    @property
    def name_edit(self) -> QLineEdit:
        """The root's name."""
        return self.__ui.root_name_edit

    @property
    def default_name_button(self) -> QToolButton:
        """The button beside the name that gives the root its default name."""
        return self.__ui.default_root_name_button

    @property
    def layouts_editor(self) -> RootLayoutsEditor:
        """The root's layouts and fallbacks."""
        return self.__ui.layouts_editor

    def editing_here(self) -> bool:
        """Whether the keyboard is in one of the editors -- what a refill of the same root leaves alone.

        :returns: whether the focus is on the name field or anywhere else inside this pane.
        """
        if self.__ui.root_name_edit.hasFocus():
            return True
        focused = QApplication.focusWidget()
        return focused is not None and self.isAncestorOf(focused)
