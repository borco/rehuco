"""The FFmpeg libraries this run decodes with, loaded before Qt Multimedia is imported (#580,
[[plugins#in-app-player]]).

Qt's FFmpeg plugin binds its libraries by name when Qt Multimedia is first imported, and the agent imports it as soon
as the main window's module is. So the choice made on the Videos page can only be applied at the next start, from
``__main__`` ahead of that import, and a build that cannot be loaded falls back to Qt's own with the reason kept for
the page and the log.
"""

import logging
from functools import lru_cache
from pathlib import Path
from typing import Final

import PySide6
from rehuco_core import (
    EXTERNAL_TOOLS,
    FFMPEG_LIBRARIES_TOOL,
    LibrariesUnusableError,
    bundled_library_names,
    library_files,
    load_libraries,
    shared_tool_locator,
)

from .own_program import own_program
from .settings.tools_settings import shared_tools_settings
from .settings.videos_settings import FFMPEG_LIBRARIES_PLAYER, shared_videos_settings

LOG: Final = logging.getLogger(__name__)


class PlaybackLibraries:
    """What this run did about the external FFmpeg libraries: whether they were asked for, and whether they loaded."""

    def __init__(self) -> None:
        self.__requested = False
        self.__loaded_from: Path | None = None
        self.__fallback_reason: str | None = None

    @property
    def requested(self) -> bool:
        """Whether the Videos page chose the libraries when this run started."""
        return self.__requested

    @property
    def loaded_from(self) -> Path | None:
        """The folder the libraries were loaded from, or ``None`` when Qt's own are in use."""
        return self.__loaded_from

    @property
    def fallback_reason(self) -> str | None:
        """Why Qt's own libraries are in use although the others were asked for, or ``None``."""
        return self.__fallback_reason

    def load_at_start(self) -> None:
        """Load the chosen libraries by full path, before Qt Multimedia is imported.

        Does nothing when they were not chosen. The build is the one the Tools page resolves to, with the judgment it
        was given there: an install the discovery found carries the child's verdict, and a path the user typed is
        tried in the child now, since that verdict lives nowhere else -- the agent itself never loads a build that was
        not seen to load. Any failure leaves Qt's own libraries in use and records why; this runs before the log and
        before ``main``'s own handler, so nothing may escape it.
        """
        if FFMPEG_LIBRARIES_TOOL.ID not in EXTERNAL_TOOLS:
            return
        qt_folder = Path(PySide6.__file__).parent
        FFMPEG_LIBRARIES_TOOL.configure(qt_folder, tuple(own_program()))
        if shared_videos_settings().player != FFMPEG_LIBRARIES_PLAYER:
            return
        self.__requested = True
        try:
            self.__load(qt_folder)
        except Exception as error:  # pylint: disable=broad-exception-caught  # a crash here leaves no log at all
            self.__fallback_reason = f"Loading the libraries failed: {error}"

    def __load(self, qt_folder: Path) -> None:
        """Resolve the chosen build and load it, or record why not.

        :param qt_folder: the PySide6 package folder, naming the libraries to match.
        """
        tools = shared_tools_settings()
        candidate = shared_tool_locator().resolve(
            FFMPEG_LIBRARIES_TOOL,
            tools.path(FFMPEG_LIBRARIES_TOOL.ID),
            tools.detection(FFMPEG_LIBRARIES_TOOL.ID).installs,
        )
        if candidate is None:
            self.__fallback_reason = "No FFmpeg libraries are set up on the Tools page."
            return
        if not candidate.is_usable:
            self.__fallback_reason = f"{candidate.folder}: {candidate.reason}"
            return
        try:
            load_libraries(library_files(candidate.folder, bundled_library_names(qt_folder)))
        except LibrariesUnusableError as error:
            self.__fallback_reason = f"{candidate.folder}: {error.reason}"
            return
        self.__loaded_from = candidate.folder

    def log_outcome(self) -> None:
        """Write what :meth:`load_at_start` did to the log, which is not running yet when it does."""
        if self.__loaded_from is not None:
            LOG.info("Playing with the external FFmpeg libraries in %s", self.__loaded_from)
        elif self.__fallback_reason is not None:
            LOG.warning("Playing with Qt's bundled FFmpeg, not the external libraries. %s", self.__fallback_reason)


@lru_cache(maxsize=1)
def shared_playback_libraries() -> PlaybackLibraries:
    """The process-wide record of this run's libraries.

    :returns: the shared instance.
    """
    return PlaybackLibraries()
