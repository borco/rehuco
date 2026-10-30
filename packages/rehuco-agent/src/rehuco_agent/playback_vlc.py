"""The libvlc this run's player dock can decode with, loaded once and only when asked for (#319,
[[plugins#in-app-player]]).

Unlike the FFmpeg libraries (#580), which Qt binds at import, libvlc is loaded lazily: at the first player built with
*VLC* chosen on the Videos page. It comes from the install the Tools page resolves, through
:class:`~rehuco_core.VlcLibrary`, which never raises; the reason it could not be loaded is kept for the player's notice.
python-vlc binds its library once per process, so a VLC chosen on the Tools page after the first load is taken at
the next start, and the proxy's reason says so.
"""

from functools import lru_cache
from typing import Final

from rehuco_core import NO_LIBRARY_REASON, VLC_TOOL, VlcLibrary

from .own_program import own_program
from .settings.tools_settings import shared_tools_settings

NOT_SET_UP: Final = "No VLC is set up on the Tools page."
"""The reason when the Tools settings give none of their own."""


def configure_vlc_probe() -> None:
    """Tell the VLC tool how to run the child that proves a libvlc loads: this program, with the probe flag (#319).

    Called once at start, before the tools are searched for, so a Detect judges the library in a process of its own.
    """
    VLC_TOOL.configure(tuple(own_program()))


@lru_cache(maxsize=1)
def shared_vlc_library() -> VlcLibrary:
    """The process-wide python-vlc, loaded from the Tools page's VLC on first use.

    :returns: the proxy, available or not; unavailable with a reason when no VLC with its library is set up.
    """
    tools = shared_tools_settings()
    folder = tools.tool_folder(VLC_TOOL)
    if folder is None:
        return VlcLibrary.unavailable(tools.missing_reason(VLC_TOOL) or NOT_SET_UP)
    library = VLC_TOOL.library_path(folder)
    if library is None:
        return VlcLibrary.unavailable(NO_LIBRARY_REASON)
    return VlcLibrary.load(library)
