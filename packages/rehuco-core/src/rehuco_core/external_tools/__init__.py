"""The optional external tools the app can use, and how they are found ([[packaging-deployment#external-tools]])."""

import sys
from typing import Final

from .ffmpeg_libraries import (
    LibrariesUnusableError,
    bundled_library_names,
    free_libraries,
    library_files,
    load_libraries,
    probe,
)
from .ffmpeg_libraries_tool import PROBE_FLAG, FfmpegLibrariesTool
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
from .vlc_library import LIBRARY_PATH_VARIABLE, NOT_SET_UP, VlcLibrary, probe_libvlc
from .vlc_tool import LIBVLC_PROBE_FLAG, NO_LIBRARY_REASON, VlcTool

FFMPEG_TOOL: Final = FfmpegTool()
VLC_TOOL: Final = VlcTool()
FFMPEG_LIBRARIES_TOOL: Final = FfmpegLibrariesTool()

EXTERNAL_TOOLS: Final[dict[str, ToolDescriptor]] = {
    tool.ID: tool for tool in (FFMPEG_TOOL, VLC_TOOL, *((FFMPEG_LIBRARIES_TOOL,) if sys.platform == "win32" else ()))
}
"""The tools this build knows, by :attr:`~ToolDescriptor.ID` -- one frame each on the Tools page. The FFmpeg libraries
are Windows-only: that is the one platform they were measured on (#580)."""

__all__ = [
    "EXTERNAL_TOOLS",
    "FFMPEG_LIBRARIES_TOOL",
    "FFMPEG_TOOL",
    "LIBRARY_PATH_VARIABLE",
    "LIBVLC_PROBE_FLAG",
    "NO_LIBRARY_REASON",
    "NOT_SET_UP",
    "PROBE_FLAG",
    "VLC_TOOL",
    "BlockedVersion",
    "FfmpegLibrariesTool",
    "FfmpegTool",
    "LibrariesUnusableError",
    "ToolCandidate",
    "ToolDescriptor",
    "ToolLocator",
    "ToolNotRunnableError",
    "ToolStatus",
    "Version",
    "VlcLibrary",
    "VlcTool",
    "best_candidate",
    "bundled_library_names",
    "free_libraries",
    "library_files",
    "load_libraries",
    "probe",
    "probe_libvlc",
    "shared_tool_locator",
    "version_text",
]
