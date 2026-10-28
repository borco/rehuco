"""The optional external tools the app can use, and how they are found ([[packaging-deployment#external-tools]])."""

from typing import Final

from .ffmpeg_tool import FfmpegTool
from .tool_descriptor import (
    BlockedVersion,
    ToolCandidate,
    ToolDescriptor,
    ToolNotRunnableError,
    ToolStatus,
    Version,
    best_candidate,
    version_text,
)
from .tool_locator import ToolLocator, shared_tool_locator

FFMPEG_TOOL: Final = FfmpegTool()

EXTERNAL_TOOLS: Final[dict[str, ToolDescriptor]] = {tool.ID: tool for tool in (FFMPEG_TOOL,)}
"""The tools this build knows, by :attr:`~ToolDescriptor.ID` -- one frame each on the Tools page."""

__all__ = [
    "EXTERNAL_TOOLS",
    "FFMPEG_TOOL",
    "BlockedVersion",
    "FfmpegTool",
    "ToolCandidate",
    "ToolDescriptor",
    "ToolLocator",
    "ToolNotRunnableError",
    "ToolStatus",
    "Version",
    "best_candidate",
    "shared_tool_locator",
    "version_text",
]
