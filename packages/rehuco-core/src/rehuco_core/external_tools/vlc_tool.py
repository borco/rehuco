"""VLC, whose libvlc the in-app player can decode with ([[packaging-deployment#external-tools]], #318, #319)."""

import ctypes.util
import json
import os
import re
import subprocess  # nosec B404  # only ever runs this program with a fixed flag, never a shell
import sys
import tempfile
from pathlib import Path
from typing import Final, override

from .tool_descriptor import ToolDescriptor, ToolNotRunnableError, ToolStatus, Version

LIBVLC_PROBE_FLAG: Final = "--probe-libvlc"
"""The flag that makes the program load a libvlc in a child process and write what happened (``--output``)."""

NO_LIBRARY_REASON: Final = (
    "VLC is installed, but not its shared library (a static or sandboxed build); playing in the app needs libvlc."
)


class VlcTool(ToolDescriptor):
    """The program and, what the app uses of it, its **shared library**: ``libvlc``, loaded into the player through
    python-vlc ([[appendices.vlc#python-vlc]]).

    A copy is judged three ways, each cheaper than the next: the library's files must be there (a static or sandboxed
    VLC has none to load), ``vlc --version`` must print a version from the minimum on, and a child process must load
    the library and get an instance of it, so nothing is loaded into the agent that was not proved to load.
    """

    ID = "vlc"
    LABEL = "VLC"
    PURPOSE = "Decodes video in the app's player with the user's own VLC: deinterlaced, and AV1 on any graphics card."
    FEATURES = "The In-app player with VLC's libraries choice on the Videos page."
    NOT_BUNDLED_BECAUSE = "It is GPL, and the app ships no GPL code."
    DOCS_ANCHOR = "vlc"
    EXECUTABLES = ("vlc",)
    MINIMUM = (3, 0)
    NEWEST_TESTED = (3, 0)

    __VERSION_PATTERN: Final = re.compile(r"VLC version (\d+)\.(\d+)(?:\.(\d+))?")
    """What ``vlc --version`` prints first; a nightly build prints a date or a revision there instead."""

    __TIMEOUT_SECONDS: Final = 30.0
    """How long the version read, and the child, may take before the copy is called not runnable. Generous: a first
    run rebuilds VLC's plugin cache, which on a slow disk takes a while ([[appendices.vlc#launch]])."""

    def __init__(self) -> None:
        self.__program: tuple[str, ...] = ()

    def configure(self, program: tuple[str, ...]) -> None:
        """Say how to run the child that loads the library, which only the host process knows.

        Unconfigured, a copy is judged by its files and its version alone.

        :param program: the command that runs this app, to which :data:`LIBVLC_PROBE_FLAG` is appended.
        """
        self.__program = program

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

    def library_files(self, folder: Path) -> list[Path]:
        """What loading libvlc from an install needs, whether or not it is there.

        :param folder: the folder holding ``vlc``.
        :returns: the library, the core library it loads, and the plugins folder, as this OS lays them out. On Linux
            the libraries are the system's, wherever the loader finds them, so the paths may be empty names.
        """
        if sys.platform == "win32":
            return [folder / "libvlc.dll", folder / "libvlccore.dll", folder / "plugins"]
        if sys.platform == "darwin":
            return [folder / "lib" / "libvlc.dylib", folder / "lib" / "libvlccore.dylib", folder / "plugins"]
        return [Path(ctypes.util.find_library(name) or "") for name in ("vlc", "vlccore")]

    def library_path(self, folder: Path) -> Path | None:
        """The ``libvlc`` shared library of an install, when the whole of what it needs is there.

        :param folder: the folder holding ``vlc``.
        :returns: the library's path, or ``None`` when the install cannot be loaded from.
        """
        files = self.library_files(folder)
        return files[0] if all(self.__is_there(file) for file in files) else None

    @staticmethod
    def __is_there(file: Path) -> bool:
        """Whether one of the library's files is there: an empty name (a library the loader did not find) never is; a
        bare name with no folder is one the loader did find by its own search path (``libvlc.so.5`` on Linux), which
        python-vlc loads by that name.

        :param file: the file, an empty path, or a bare name.
        :returns: whether it is there.
        """
        if not file.name:
            return False
        return True if file.parent == Path() else file.exists()

    @override
    def assess(self, folder: Path) -> tuple[ToolStatus, Version | None, str]:
        """Judge an install: its library's files, then ``vlc --version``, then a child process that loads the library.

        :param folder: the folder holding ``vlc``.
        :returns: the status, the version when read, and the reason unless usable.
        """
        files = self.library_files(folder)
        present = [file for file in files if self.__is_there(file)]
        if not present:
            return ToolStatus.NO_LIBRARIES, None, NO_LIBRARY_REASON
        if len(present) < len(files):
            missing = ", ".join(file.name for file in files if file not in present)
            return ToolStatus.INCOMPLETE, None, f"The install lacks {missing}, which libvlc needs."
        try:
            version = self.read_version(folder)
        except ToolNotRunnableError as error:
            return ToolStatus.NOT_RUNNABLE, None, error.reason
        status, reason = self.judge(version)
        if not status.is_usable or not self.__program:
            return status, version, reason
        child_status, child_reason = self.__ask_child(files[0])
        return (status, version, reason) if child_status.is_usable else (child_status, version, child_reason)

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

    def __ask_child(self, library: Path) -> tuple[ToolStatus, str]:
        """Have a child process load the library and report.

        :param library: the ``libvlc`` shared library.
        :returns: the status and, unless usable, the reason; *not runnable* when the child wrote nothing, or bound a
            library other than the one asked for.
        """
        with tempfile.TemporaryDirectory() as scratch:
            output = Path(scratch) / "answer.json"
            command = [*self.__program, LIBVLC_PROBE_FLAG, str(library), "--output", str(output)]
            try:
                subprocess.run(command, capture_output=True, timeout=self.__TIMEOUT_SECONDS, check=False)  # nosec B603
                answer = json.loads(output.read_text(encoding="utf-8"))
                status, reason, bound = ToolStatus(answer["status"]), str(answer["reason"]), str(answer["library"])
            except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError) as error:
                return ToolStatus.NOT_RUNNABLE, f"Loading libvlc failed: {error}"
        if status.is_usable and os.path.normcase(bound) != os.path.normcase(str(library)):
            return ToolStatus.NOT_RUNNABLE, f"python-vlc bound {bound} instead of {library}."
        return status, reason
