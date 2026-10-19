"""The System Integration settings page: the platform's frames, then the tray block (#205) and the local node
block (#506)."""

from collections.abc import Sequence
from typing import Final

from PySide6.QtWidgets import QFrame, QWidget

from ...node_host import NodeHost
from .node_block import NodeBlock
from .system_integration_page_ui import Ui_SystemIntegrationPage
from .tray_block import TrayBlock


class SystemIntegrationPage(QWidget):
    """The one System Integration page, on every platform (#508).

    It declares the blocks every platform shares -- the tray block (#205), which decides what the window's
    close button does, and the local node block (#506) -- and takes the platform's own blocks as frames to
    insert ahead of them: `RegistrationFrameWindows` and `CrashDumpsFrameWindows` on Windows,
    `RegistrationFrameLinux` on Linux, none on macOS, where the ``.rehu`` association comes from the app bundle
    itself ([[packaging-deployment#app-identity]]). A platform block is one more frame, not a section squeezed
    into another.

    The frames must be in the page by the time the settings dialog registers it, because
    `SettingsFrameFilter` takes its blocks from the page's direct ``QFrame`` children then; inserting them here
    makes them the page's own children, so the filter, the dirty highlight and the per-frame Apply, Reset and
    Defaults treat them like the page's own blocks.

    The platform frames' controls act immediately when clicked, so nothing of theirs is ever staged: the tray
    and node blocks hold this page's staged controls, and are what :meth:`is_dirty`, :meth:`save_changes`,
    :meth:`drop_changes` and :meth:`seed_defaults` answer for.

    :param node_host: the main window's node host, for the node block's status line; ``None`` leaves it static.
    :param platform_frames: the platform's blocks, inserted first in this order.
    :param parent: optional Qt parent.
    """

    def __init__(
        self,
        node_host: NodeHost | None = None,
        platform_frames: Sequence[QFrame] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        # children first: `SettingsFrameFilter.blocks()` lists the page's frames in child order, which is
        # the order the group column shows them in, so a frame adopted after `setupUi` would be listed
        # after the page's own although the layout puts it above them
        for frame in platform_frames:
            frame.setParent(self)
        self.__ui: Final = Ui_SystemIntegrationPage()
        self.__ui.setupUi(self)
        for index, frame in enumerate(platform_frames):
            self.__ui.main_layout.insertWidget(index, frame)
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
