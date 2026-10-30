"""The libvlc this run's player dock can decode with, loaded when first asked for (#319, [[plugins#in-app-player]]).

Unlike the FFmpeg libraries (#580), which Qt binds at import, libvlc is loaded lazily: at the first player built with
*VLC* chosen on the Videos page, from the install the Tools page resolves, through :class:`~rehuco_core.VlcLibrary`,
which never raises. A load that failed is not kept, so a VLC set up on the Tools page afterwards is tried at the next
player. A load that succeeded is kept for the run: python-vlc binds its library once per process, so a *different* VLC
chosen afterwards is taken at the next start, which the Videos page says (:func:`vlc_restart_needed`).
"""

from functools import lru_cache
from pathlib import Path

from rehuco_core import NO_LIBRARY_REASON, NOT_SET_UP, VLC_TOOL, VlcLibrary

from .own_program import own_program
from .settings.tools_settings import shared_tools_settings


def configure_vlc_probe() -> None:
    """Tell the VLC tool how to run the child that proves a libvlc loads: this program, with the probe flag (#319).

    Called once at start, before the tools are searched for, so a Detect judges the library in a process of its own.
    """
    VLC_TOOL.configure(tuple(own_program()))


class VlcPlayback:
    """What this run did about libvlc: the proxy loaded, kept once it is available."""

    def __init__(self) -> None:
        self.__loaded: VlcLibrary | None = None

    @property
    def library(self) -> VlcLibrary:
        """The proxy over the Tools page's VLC: loaded now when none is, or when the last load failed.

        :returns: the proxy, available or not; unavailable with a reason when no VLC with its library is set up.
        """
        if self.__loaded is None or not self.__loaded.available:
            self.__loaded = self.__load()
        return self.__loaded

    @property
    def restart_needed(self) -> bool:
        """Whether the Tools page's VLC is no longer the one this run loaded: python-vlc binds once per process.

        :returns: ``True`` when a library is loaded and the Tools page now resolves another, or none.
        """
        if self.__loaded is None or not self.__loaded.available:
            return False
        return self.__wanted() != self.__loaded.library

    @staticmethod
    def __wanted() -> Path | None:
        """The library the Tools page resolves to now.

        :returns: its path, or ``None`` when no VLC with its library is set up.
        """
        folder = shared_tools_settings().tool_folder(VLC_TOOL)
        return VLC_TOOL.library_path(folder) if folder is not None else None

    @staticmethod
    def __load() -> VlcLibrary:
        """Load the proxy over what the Tools page resolves, with the Tools settings' own reason when it resolves
        nothing.

        :returns: the proxy.
        """
        tools = shared_tools_settings()
        folder = tools.tool_folder(VLC_TOOL)
        if folder is None:
            return VlcLibrary.unavailable(tools.missing_reason(VLC_TOOL) or NOT_SET_UP)
        library = VLC_TOOL.library_path(folder)
        if library is None:
            return VlcLibrary.unavailable(NO_LIBRARY_REASON)
        return VlcLibrary.load(library)


@lru_cache(maxsize=1)
def shared_vlc_playback() -> VlcPlayback:
    """The process-wide libvlc state.

    :returns: the one instance.
    """
    return VlcPlayback()


def shared_vlc_library() -> VlcLibrary:
    """The process-wide python-vlc, loaded from the Tools page's VLC on first use.

    :returns: the proxy, available or not.
    """
    return shared_vlc_playback().library


def vlc_restart_needed() -> bool:
    """Whether the VLC chosen on the Tools page waits for the next start, because another is loaded in this run.

    :returns: ``True`` when it does.
    """
    return shared_vlc_playback().restart_needed
