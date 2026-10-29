"""VLC, the external player a video can be opened in ([[packaging-deployment#external-tools]], #318)."""

import os
import re
import sys
from pathlib import Path
from typing import Final, override

from .tool_descriptor import ToolDescriptor, Version


class VlcTool(ToolDescriptor):
    """The program: the ``vlc`` executable, any version from the minimum on.

    It is launched as a process of its own, so the agent loads none of its libraries
    ([[plugins#in-app-player]]); the libvlc a future in-app surface would use is a different thing and gets its own
    descriptor if it is ever built.
    """

    ID = "vlc"
    LABEL = "VLC"
    PURPOSE = "Plays a video in its own window."
    FEATURES = "The external player choice on the Videos page."
    NOT_BUNDLED_BECAUSE = "It is GPL, and the app ships no GPL code."
    DOCS_ANCHOR = "vlc"
    EXECUTABLES = ("vlc",)
    MINIMUM = (3, 0)
    NEWEST_TESTED = (3, 0)

    __VERSION_PATTERN: Final = re.compile(r"VLC version (\d+)\.(\d+)(?:\.(\d+))?")
    """What ``vlc --version`` prints first; a nightly build prints a date or a revision there instead."""

    __TIMEOUT_SECONDS: Final = 30.0
    """How long the version read may take before the copy is called not runnable. Generous: a first run rebuilds
    VLC's plugin cache, which on a slow disk takes a while."""

    @override
    def search_patterns(self) -> tuple[tuple[str, str], ...]:
        """The default install places of this OS.

        :returns: ``(source, pattern)`` pairs, the pattern's environment variables expanded.
        """
        if sys.platform == "win32":
            patterns = (
                ("Program Files", r"%ProgramFiles%\VideoLAN\VLC"),
                ("Program Files", r"%ProgramFiles(x86)%\VideoLAN\VLC"),
                ("scoop", r"%USERPROFILE%\scoop\apps\vlc\current"),
            )
        elif sys.platform == "darwin":
            patterns = (
                ("Applications", "/Applications/VLC.app/Contents/MacOS"),
                ("Applications", os.path.expanduser("~/Applications/VLC.app/Contents/MacOS")),
                ("Homebrew", "/opt/homebrew/bin"),
                ("Homebrew", "/usr/local/bin"),
            )
        else:
            patterns = (("system", "/usr/bin"), ("system", "/usr/local/bin"))
        return tuple((source, os.path.expandvars(pattern)) for source, pattern in patterns)

    @override
    def read_version(self, folder: Path) -> Version | None:
        """Run ``vlc --version`` and read the first line it prints.

        VLC on Windows writes its plugin-cache complaints to the error stream and the version to the output stream,
        so only the output is read.

        :param folder: the folder holding ``vlc``.
        :returns: the version, or ``None`` for a build that prints none.
        :raises ToolNotRunnableError: if ``vlc`` does not start or exits with an error.
        """
        return self.read_printed_version(
            self.executable_files(folder)[0], "--version", self.__TIMEOUT_SECONDS, self.__VERSION_PATTERN
        )
