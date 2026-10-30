"""One external tool's block on the Tools page (#521)."""

from typing import Final

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QFrame
from rehuco_core import (
    ToolCandidate,
    ToolDescriptor,
    ToolLocator,
    shared_tool_locator,
)

from ...documents.latest_runner import LatestRunner
from ..tool_discovery import ToolDiscovery, shared_tool_discovery
from ..tools_settings import ToolsSettings, shared_tools_settings
from .tool_frame_ui import Ui_ToolFrame
from .tool_path_control import LOOKING_TEXT, ToolPathControl

DOCS_URL: Final = "https://borco.github.io/rehuco/external-tools/"
"""The docs page saying where each tool comes from, one section per tool under a fixed anchor."""

INSPECT_TAG: Final = "inspect"
NOT_FOUND_STATUS: Final = (
    "Nothing was found. Install it from the instructions above and press Detect, or choose Custom."
)
UNREADABLE_STATUS: Final = "Looking for it failed: {error}"


class ToolFrame(QObject):  # pylint: disable=too-many-instance-attributes
    """The block for one tool: what it is for, where to get it, where it is, and whether that works.

    **Not a widget**, for the reason `TrayBlock` gives: `SettingsFrameFilter` counts only an exact ``QFrame`` that is
    a direct child of the page as a block, so the frame is a plain ``QFrame`` built from this ``.ui`` and handed to
    `ToolsPage` through :attr:`frame`. This object is parented to it, so it lives as long as the page does.

    **It searches for nothing.** The installs listed are what `ToolDiscovery` found and `ToolsSettings` holds; the block
    follows the discovery, and **Detect** asks it to search again. Only a custom path is looked at here, since the user
    typed it: that reads a version, so it runs on the thread pool ([[appendices.code-conventions#worker-threads]]) and
    answers only the last asked.

    :param tool: the tool this block sets up.
    :param settings: where the tool's detection is read; the shared one when omitted.
    :param discovery: what searches; the shared one when omitted.
    :param locator: judges a custom path; the process-wide one when omitted.
    """

    answered = Signal()
    """The block shows a new answer: a search was recorded, or a typed path was inspected."""

    def __init__(
        self,
        tool: ToolDescriptor,
        settings: ToolsSettings | None = None,
        discovery: ToolDiscovery | None = None,
        locator: ToolLocator | None = None,
    ) -> None:
        frame = QFrame()
        super().__init__(frame)
        self.__frame: Final = frame
        self.__tool: Final = tool
        self.__settings: Final = settings if settings is not None else shared_tools_settings()
        self.__discovery: Final = discovery if discovery is not None else shared_tool_discovery()
        self.__locator: Final = locator if locator is not None else shared_tool_locator()
        self.__ui: Final = Ui_ToolFrame()
        self.__ui.setupUi(frame)
        self.__looking = not self.__settings.detection(tool.ID).searched
        # names after the tool, so a page with several tools has distinct frames and each header label is found
        frame.setObjectName(f"{tool.ID}_frame")
        self.__ui.tool_frame_label.setObjectName(f"{tool.ID}_frame_label")
        self.__ui.tool_frame_label.setText(tool.LABEL)
        self.__ui.description_label.setText(tool.PURPOSE)
        self.__ui.description_label.setToolTip(f"Needed by: {tool.FEATURES}\nNot bundled: {tool.NOT_BUNDLED_BECAUSE}")
        self.__ui.install_label.setText(f'<a href="{DOCS_URL}#{tool.DOCS_ANCHOR}">How to install {tool.LABEL}</a>')
        self.__ui.path_control.browse_title = f"Locate {tool.LABEL}"

        self.__inspector: Final = LatestRunner(self)
        self.__inspector.read.connect(self.__on_inspected)
        self.__discovery.tool_done.connect(self.__on_tool_done)
        self.__ui.path_control.choice_changed.connect(self.__update_status)
        self.__ui.detect_button.clicked.connect(self.__on_detect_clicked)
        self.__show_detection()

    @property
    def frame(self) -> QFrame:
        """The block, for the page to adopt."""
        return self.__frame

    @property
    def control(self) -> ToolPathControl:
        """The choice of install, which is this block's one setting."""
        return self.__ui.path_control

    @property
    def tool(self) -> ToolDescriptor:
        """The tool this block sets up."""
        return self.__tool

    def __show_detection(self) -> None:
        """List the installs found, or say a search is going."""
        if self.__looking:
            self.__ui.path_control.set_looking()
            self.__update_status()
        else:
            self.__ui.path_control.set_candidates(self.__settings.detection(self.__tool.ID).installs)

    def __on_detect_clicked(self) -> None:
        """Ask the discovery to search for this tool again."""
        self.__looking = True
        self.__show_detection()
        self.__discovery.start(force=[self.__tool.ID])

    def __on_tool_done(self, tool_id: str) -> None:
        """Show a search or verification that was recorded, if it is this tool's.

        :param tool_id: the tool the discovery reported.
        """
        if tool_id != self.__tool.ID:
            return
        self.__looking = False
        self.__show_detection()
        self.answered.emit()

    def __show_status(self, text: str) -> None:
        """Show the line under the control, or hide it: a candidate's verdict is its row's parenthesis, so the line
        says only what no row can -- a search is going, nothing was found, or a typed path could not be looked at.

        :param text: the line; empty hides the label.
        """
        self.__ui.status_label.setText(text)
        self.__ui.status_label.setVisible(bool(text))

    def __update_status(self) -> None:
        """Judge the staged choice: a listed install as it was found, a custom path by inspecting it."""
        control = self.__ui.path_control
        if control.chosen_candidate() is not None:
            self.__inspector.discard()
            control.set_custom_status(None)
            self.__show_status("")
            return
        path = str(control.settings_value())
        if not path:
            self.__inspector.discard()
            control.set_custom_status(None)
            self.__show_status(LOOKING_TEXT if self.__looking else NOT_FOUND_STATUS)
            return
        tool, locator = self.__tool, self.__locator
        self.__inspector.start(INSPECT_TAG, lambda: locator.inspect(tool, path))

    def __on_inspected(self, tag: str, result: object) -> None:
        """Show what inspecting the typed path found.

        :param tag: unused; this runner does one kind of work.
        :param result: the candidate, or the error inspecting raised.
        """
        del tag
        if isinstance(result, ToolCandidate):
            self.__ui.path_control.set_custom_status(result)
            self.__show_status("")
        else:
            self.__ui.path_control.set_custom_status(None)
            self.__show_status(UNREADABLE_STATUS.format(error=result))
        self.answered.emit()
