"""The Tools settings page: where each optional external program is (#521)."""

from typing import Final

from PySide6.QtWidgets import QWidget
from rehuco_core import EXTERNAL_TOOLS

from ..persistent_settings import persistent_settings
from ..tools_settings import ToolsSettings, shared_tools_settings
from .tool_frame import ToolFrame
from .tools_page_ui import Ui_ToolsPage


class ToolsPage(QWidget):
    """Set up the programs the app can use but does not ship ([[packaging-deployment#external-tools]]).

    One `ToolFrame` per tool in `rehuco_core`'s registry, built here rather than listed in the ``.ui`` so the page
    follows the registry: a tool added there has its block with no change to this page. Each is adopted before
    ``setupUi`` because `SettingsFrameFilter` lists a page's blocks in child order.

    Edits are staged in each block's path control until :meth:`save_changes` pushes them into the shared
    `ToolsSettings` and persists them; the next feature that needs a tool resolves it from that. The page searches for
    nothing itself: each block shows what `ToolDiscovery` found, and its Detect asks for another search.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__frames: Final = [ToolFrame(tool) for tool in EXTERNAL_TOOLS.values()]
        for tool_frame in self.__frames:
            tool_frame.frame.setParent(self)
        self.__ui: Final = Ui_ToolsPage()
        self.__ui.setupUi(self)
        for index, tool_frame in enumerate(self.__frames):
            self.__ui.main_layout.insertWidget(index, tool_frame.frame)
        self.drop_changes()

    @property
    def frames(self) -> list[ToolFrame]:
        """The blocks, one per tool, in registry order."""
        return list(self.__frames)

    def is_dirty(self) -> bool:
        """Whether any staged choice differs from what the shared settings currently hold."""
        settings = shared_tools_settings()
        return any(
            tool_frame.control.settings_value() != settings.path(tool_frame.tool.ID) for tool_frame in self.__frames
        )

    def save_changes(self) -> None:
        """Push the staged paths into the shared settings object and persist them."""
        settings = shared_tools_settings()
        for tool_frame in self.__frames:
            settings.set_path(tool_frame.tool.ID, str(tool_frame.control.settings_value()))
        settings.save(persistent_settings())  # the detections go with the paths, as they are in memory

    def drop_changes(self) -> None:
        """Discard the staged edits, re-seeding every block from the shared settings."""
        self.__show(shared_tools_settings())

    def seed_defaults(self) -> None:
        """Stage the factory values: every tool on the best install found (#342)."""
        for tool_frame in self.__frames:
            tool_frame.control.set_settings_value("")

    def __show(self, settings: ToolsSettings) -> None:
        """Fill every block from ``settings``.

        :param settings: the values to show -- the shared object's saved ones.
        """
        for tool_frame in self.__frames:
            tool_frame.control.set_settings_value(settings.path(tool_frame.tool.ID))
