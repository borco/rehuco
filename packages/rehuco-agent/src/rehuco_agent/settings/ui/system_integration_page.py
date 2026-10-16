"""System Integration settings page for platforms with nothing to register: the tray block (#205) and the
local node block (#506)."""

from typing import Final

from PySide6.QtWidgets import QWidget

from ...node_host import NodeHost
from .node_block import NodeBlock
from .system_integration_page_ui import Ui_SystemIntegrationPage
from .tray_block import TrayBlock


class SystemIntegrationPage(QWidget):
    """The System Integration page on a platform that registers nothing -- macOS, where the ``.rehu``
    association comes from the app bundle itself ([[packaging-deployment#app-identity]]) -- so the
    tray block (#205) and the local node block (#506) are all there is to show.

    Its Windows and Linux counterparts are `RegistryPage` and `DesktopIntegrationPage`: same title,
    same two blocks, with their own registration controls above them. Constructed under the matching
    ``sys.platform == "darwin"`` branch in `main_window.py`, so every platform has this page and both
    settings can be reached from all three.

    :param node_host: the main window's node host, for the node block's status line; ``None`` leaves it static.
    :param parent: optional Qt parent.
    """

    def __init__(self, node_host: NodeHost | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_SystemIntegrationPage()
        self.__ui.setupUi(self)
        self.__tray: Final = TrayBlock(self.__ui.enabled_check_box, self.__ui.unavailable_label)
        self.__node: Final = NodeBlock(self.__ui.node_enabled_check_box, self.__ui.node_status_label, node_host)

    def is_dirty(self) -> bool:
        """Whether either staged checkbox differs from what's saved."""
        return self.__tray.is_dirty() or self.__node.is_dirty()

    def save_changes(self) -> None:
        """Persist the staged tray and node choices."""
        self.__tray.save_changes()
        self.__node.save_changes()

    def drop_changes(self) -> None:
        """Discard the staged tray and node edits."""
        self.__tray.drop_changes()
        self.__node.drop_changes()

    def seed_defaults(self) -> None:
        """Stage both blocks' factory values (#342)."""
        self.__tray.seed_defaults()
        self.__node.seed_defaults()
