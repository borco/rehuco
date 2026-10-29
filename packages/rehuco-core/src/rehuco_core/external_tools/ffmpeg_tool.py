"""FFmpeg, the external tool the duration probe uses ([[packaging-deployment#external-tools]], #521)."""

import os
import re
import sys
from pathlib import Path
from typing import Final, override

from .tool_descriptor import ToolDescriptor, Version


class FfmpegTool(ToolDescriptor):
    """The program: ``ffmpeg`` and ``ffprobe`` in one folder, any version from the minimum on.

    The *playback libraries* that replace Qt Multimedia's own FFmpeg are a different thing with a stricter rule
    ([[packaging-deployment#external-tools]]) and get their own descriptor when they are built.
    """

    ID = "ffmpeg"
    LABEL = "FFmpeg"
    PURPOSE = "Reads a video's length and frame size."
    FEATURES = "The duration probe on the Videos page."
    NOT_BUNDLED_BECAUSE = "A full build is large, and the builds that include every codec are GPL."
    DOCS_ANCHOR = "ffmpeg"
    EXECUTABLES = ("ffmpeg", "ffprobe")
    MINIMUM = (4, 0)
    NEWEST_TESTED = (9, 0)

    __VERSION_PATTERN: Final = re.compile(r"version n?(\d+)\.(\d+)(?:\.(\d+))?")
    """What ``ffprobe -version`` prints for a release build; a git build prints a date or a commit count instead."""

    __TIMEOUT_SECONDS: Final = 15.0
    """How long the version read may take before the copy is called not runnable."""

    @override
    def search_patterns(self) -> tuple[tuple[str, str], ...]:
        """The default install places of this OS.

        :returns: ``(source, pattern)`` pairs, the pattern's environment variables expanded.
        """
        if sys.platform == "win32":
            patterns = (
                ("winget", r"%LOCALAPPDATA%\Microsoft\WinGet\Links"),
                ("winget", r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\*FFmpeg*\*\bin"),
                ("scoop", r"%USERPROFILE%\scoop\apps\ffmpeg*\current\bin"),
                ("chocolatey", r"%ProgramData%\chocolatey\lib\ffmpeg*\tools\ffmpeg\bin"),
                ("Program Files", r"%ProgramFiles%\ffmpeg\bin"),
                ("Program Files", r"%ProgramFiles(x86)%\ffmpeg\bin"),
            )
        elif sys.platform == "darwin":
            patterns = (
                ("Homebrew", "/opt/homebrew/bin"),
                ("Homebrew", "/usr/local/bin"),
                ("MacPorts", "/opt/local/bin"),
            )
        else:
            patterns = (("system", "/usr/bin"), ("system", "/usr/local/bin"))
        return tuple((source, os.path.expandvars(pattern)) for source, pattern in patterns)

    @override
    def read_version(self, folder: Path) -> Version | None:
        """Run ``ffprobe -version`` and read the first line.

        :param folder: the folder holding ``ffprobe``.
        :returns: the version, or ``None`` for a build that prints none.
        :raises ToolNotRunnableError: if ``ffprobe`` does not start or exits with an error.
        """
        return self.read_printed_version(
            self.executable_files(folder)[-1], "-version", self.__TIMEOUT_SECONDS, self.__VERSION_PATTERN
        )
