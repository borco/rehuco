"""FFmpeg's shared libraries, the external tool the in-app player can decode with (#580,
[[packaging-deployment#external-tools]])."""

import json
import os
import subprocess  # nosec B404  # only ever runs this program with a fixed flag, never a shell
import sys
import tempfile
from pathlib import Path
from typing import Final, override

from .ffmpeg_libraries import (
    LIBRARY_ORDER,
    LibrariesUnusableError,
    bundled_library_names,
    library_files,
    library_name_pattern,
)
from .tool_descriptor import (
    EXECUTABLE_SUFFIX,
    ToolCandidate,
    ToolDescriptor,
    ToolNotRunnableError,
    ToolStatus,
    Version,
)

PROBE_FLAG: Final = "--probe-ffmpeg-libraries"
"""The flag that makes the program try a build in a child process and write what happened (``--output``)."""


class FfmpegLibrariesTool(ToolDescriptor):
    """The libraries that replace the FFmpeg Qt Multimedia bundles: five files of the **same major version** as Qt's.

    A copy is judged by its file names against the ones the app's Qt carries, then tried in a child process, so nothing
    of it is loaded into the agent. The major comes from Qt's own folder, never from a number written here.
    """

    ID = "ffmpeg_libraries"
    LABEL = "FFmpeg libraries"
    PURPOSE = "Decodes video in the app's player with a shared FFmpeg build, so AV1 plays on any graphics card."
    FEATURES = "The Qt with external FFmpeg libraries choice on the Videos page."
    NOT_BUNDLED_BECAUSE = "Qt's own FFmpeg has no software AV1 decoder, and a build that has one is large."
    DOCS_ANCHOR = "ffmpeg-libraries"
    EXECUTABLES = ()
    MINIMUM = (0,)
    """Unused: a copy is judged by its libraries' major version, not by a version number."""

    NEWEST_TESTED = (0,)
    """Unused, as :attr:`MINIMUM`."""

    __TIMEOUT_SECONDS: Final = 30.0
    """How long the child may take to load the libraries before the copy is called not runnable."""

    def __init__(self) -> None:
        self.__qt_folder: Path | None = None
        self.__program: tuple[str, ...] = ()

    def configure(self, qt_folder: Path, program: tuple[str, ...]) -> None:
        """Say where Qt's libraries are and how to run the child, which only the host process knows.

        :param qt_folder: the PySide6 package folder.
        :param program: the command that runs this app, to which :data:`PROBE_FLAG` is appended.
        """
        self.__qt_folder = qt_folder
        self.__program = program

    @override
    def search_patterns(self) -> tuple[tuple[str, str], ...]:
        """The default install places of this OS: those of the FFmpeg program, and the shared packages.

        :returns: ``(source, pattern)`` pairs, the pattern's environment variables expanded.
        """
        if sys.platform != "win32":
            return ()
        patterns = (
            ("winget", r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\*FFmpeg*\*\bin"),
            ("scoop", r"%USERPROFILE%\scoop\apps\ffmpeg*\current\bin"),
            ("chocolatey", r"%ProgramData%\chocolatey\lib\ffmpeg*\tools\ffmpeg\bin"),
            ("Program Files", r"%ProgramFiles%\ffmpeg\bin"),
            ("Program Files", r"%ProgramFiles(x86)%\ffmpeg\bin"),
        )
        return tuple((source, os.path.expandvars(pattern)) for source, pattern in patterns)

    @override
    def search_folders(self) -> list[tuple[str, Path]]:
        """Every folder this OS may keep a build in, except Qt's own, whose libraries are what a build replaces.

        PySide6's folder is on ``PATH`` in a development environment and would otherwise be listed as a build.

        :returns: ``(source, folder)`` pairs in search order.
        """
        return [(source, folder) for source, folder in super().search_folders() if folder != self.__qt_folder]

    @override
    def executable_files(self, folder: Path) -> list[Path]:
        """What a folder holds of an FFmpeg build: any major's libraries, and ``ffmpeg``.

        Which are *there* is the answer, not which are wanted, so a static build and another major are listed and
        judged rather than missed.

        :param folder: the folder.
        :returns: the files that exist.
        """
        files = [file for stem in LIBRARY_ORDER for file in sorted(folder.glob(library_name_pattern(stem)))]
        program = folder / f"ffmpeg{EXECUTABLE_SUFFIX}"
        return [*files, program] if program.is_file() else files

    @override
    def resolve_folder(self, path: Path) -> Path | None:
        """Find the folder holding a build from what a user picked: a file in it, its folder, or an unpacked archive.

        :param path: what was picked.
        :returns: the folder holding any of a build's files, or ``None`` when it is not one.
        """
        if path.is_file():
            path = path.parent
        for folder in (path, path / "bin"):
            if self.executable_files(folder):
                return folder
        return None

    @override
    def verify_candidate(self, candidate: ToolCandidate) -> ToolCandidate | None:
        """Keep a build found earlier, re-judged by its file names: it is the app's Qt that changes major, not the
        build.

        A build judged usable under one PySide6 is of the wrong major under the next; one judged the wrong major may
        match now. The names cost no process, so they are read again; a build whose names match again is tried in the
        child again, since what the names let through was never judged.

        :param candidate: the build, as stored.
        :returns: the build with its status as of this Qt, or ``None`` when its folder holds no build any more.
        """
        folder = self.resolve_folder(candidate.folder)
        if folder is None or self.__qt_folder is None:
            return candidate if folder is not None else None
        try:
            library_files(folder, bundled_library_names(self.__qt_folder))
        except LibrariesUnusableError as error:
            if candidate.status is error.status:
                return candidate
            return ToolCandidate(candidate.folder, candidate.source, error.status, None, error.reason)
        if candidate.status in (ToolStatus.NO_LIBRARIES, ToolStatus.WRONG_MAJOR, ToolStatus.INCOMPLETE):
            status, version, reason = self.__ask_child(folder)
            return ToolCandidate(candidate.folder, candidate.source, status, version, reason)
        return candidate

    @override
    def assess(self, folder: Path) -> tuple[ToolStatus, Version | None, str]:
        """Judge a build: its file names against Qt's, then a child process that loads it.

        :param folder: the folder holding the build.
        :returns: the status, the version when the child read one, and the reason unless usable.
        """
        if self.__qt_folder is None:
            return ToolStatus.NOT_RUNNABLE, None, "Not available in this process."
        try:
            library_files(folder, bundled_library_names(self.__qt_folder))
        except LibrariesUnusableError as error:
            return error.status, None, error.reason
        return self.__ask_child(folder)

    @override
    def read_version(self, folder: Path) -> Version | None:
        """The build's version, as the child process read it.

        :param folder: the folder holding the build.
        :returns: the version, or ``None`` for a build that reports none.
        :raises ToolNotRunnableError: if the build cannot be used.
        """
        status, version, reason = self.assess(folder)
        if not status.is_usable:
            raise ToolNotRunnableError(reason)
        return version

    def __ask_child(self, folder: Path) -> tuple[ToolStatus, Version | None, str]:
        """Have a child process load the build and report.

        :param folder: the folder holding the build.
        :returns: what the child wrote, or *not runnable* when it wrote nothing.
        """
        with tempfile.TemporaryDirectory() as scratch:
            output = Path(scratch) / "answer.json"
            command = [*self.__program, PROBE_FLAG, str(folder), "--output", str(output)]
            try:
                subprocess.run(command, capture_output=True, timeout=self.__TIMEOUT_SECONDS, check=False)  # nosec B603
                answer = json.loads(output.read_text(encoding="utf-8"))
                status = ToolStatus(answer["status"])
                return status, tuple(answer["version"]) or None, answer["reason"]
            except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError) as error:
                return ToolStatus.NOT_RUNNABLE, None, f"Loading its libraries failed: {error}"
