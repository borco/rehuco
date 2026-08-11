"""System Integration settings page for platforms with nothing to register: the tray block (#205)."""

from typing import Final

from PySide6.QtWidgets import QWidget

from .system_integration_page_ui import Ui_SystemIntegrationPage
from .tray_block import TrayBlock


class SystemIntegrationPage(QWidget):
    """The System Integration page on a platform that registers nothing -- macOS, where the ``.rehu``
    association comes from the app bundle itself ([[packaging-deployment#app-identity]]) -- so the
    tray block (#205) is all there is to show.

    Its Windows and Linux counterparts are `RegistryPage` and `DesktopIntegrationPage`: same title,
    same tray block, with their own registration controls above it. Constructed under the matching
    ``sys.platform == "darwin"`` branch in `main_window.py`, so every platform has this page and the
    tray setting can be reached from all three.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_SystemIntegrationPage()
        self.__ui.setupUi(self)
        self.__tray: Final = TrayBlock(self.__ui.enabled_check_box, self.__ui.unavailable_label)

    @property
    def title(self) -> str:
        """This page's category-tree label."""
        return "System Integration"

    def is_dirty(self) -> bool:
        """Whether the staged tray checkbox differs from what's saved."""
        return self.__tray.is_dirty()

    def save_changes(self) -> None:
        """Persist the staged tray choice."""
        self.__tray.save_changes()

    def drop_changes(self) -> None:
        """Discard the staged tray edit."""
        self.__tray.drop_changes()
