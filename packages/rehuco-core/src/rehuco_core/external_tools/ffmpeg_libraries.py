"""The FFmpeg libraries that can stand in for the ones Qt Multimedia bundles ([[packaging-deployment#external-tools]],
#580).

Qt's FFmpeg plugin binds five libraries by name. Loaded by full path from another folder, before Qt Multimedia is
imported, a user's shared build of the **same major version** is what the plugin then uses
([[plugins#in-app-player]]). The rules for that are here, shared by the Tools page's descriptor, the child process that
tries a build without loading it into the agent, and the load at start: which five files, which major, in which order.
"""

import ctypes
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from .tool_descriptor import ToolStatus

LIBRARY_ORDER: Final = ("avutil", "swresample", "swscale", "avcodec", "avformat")
"""The libraries, in the order they are loaded: each one after those it depends on."""

LIBRARY_SUFFIX: Final = ".dll"
"""What a library's file name ends with; the playback libraries are only offered on Windows."""

VERSION_PATTERN: Final = re.compile(rb"n?(\d+)\.(\d+)(?:\.(\d+))?")
"""What ``av_version_info()`` returns for a release build; a git build returns a commit description instead."""

WINDOWS_BAD_IMAGE_FORMAT: Final = 193
"""The Windows error for a library built for another processor than the process runs on."""


class LibrariesUnusableError(Exception):
    """A folder whose libraries cannot replace Qt's.

    :param status: which way they cannot.
    :param reason: a sentence saying what is wrong, shown beside the candidate.
    """

    def __init__(self, status: ToolStatus, reason: str) -> None:
        super().__init__(reason)
        self.status: Final = status
        self.reason: Final = reason


def library_name_pattern(stem: str) -> str:
    """The glob that finds a library of any major version.

    :param stem: the library's name without its major version, for example ``avcodec``.
    :returns: the pattern, relative to the folder holding it.
    """
    return f"{stem}-*{LIBRARY_SUFFIX}"


def bundled_library_names(qt_folder: Path) -> dict[str, str]:
    """Read which libraries Qt bundles from its own folder, so no version is written into the code.

    :param qt_folder: the PySide6 package folder.
    :returns: the file name of each library in :data:`LIBRARY_ORDER` that is there, by stem; a stem is missing from a
        PySide6 that bundles no FFmpeg.
    """
    names: dict[str, str] = {}
    for stem in LIBRARY_ORDER:
        found = sorted(file.name for file in qt_folder.glob(library_name_pattern(stem)))
        if found:
            names[stem] = found[0]
    return names


def library_files(folder: Path, names: dict[str, str]) -> list[Path]:
    """The files of a build that replace Qt's, in the order to load them.

    :param folder: the folder holding the build's libraries.
    :param names: the file names Qt bundles, from :func:`bundled_library_names`.
    :returns: one path per library, in :data:`LIBRARY_ORDER`.
    :raises LibrariesUnusableError: if the folder holds none (a static build), another major version, or too few.
    """
    if not names:
        raise LibrariesUnusableError(ToolStatus.NOT_RUNNABLE, "This Qt bundles no FFmpeg libraries to replace.")
    present = {stem: sorted(file.name for file in folder.glob(library_name_pattern(stem))) for stem in LIBRARY_ORDER}
    if not any(present.values()):
        raise LibrariesUnusableError(
            ToolStatus.NO_LIBRARIES, "A static build: it has programs but no libraries to load. Use a shared build."
        )
    missing = [names[stem] for stem in LIBRARY_ORDER if stem in names and names[stem] not in present[stem]]
    others = [name for stem in LIBRARY_ORDER for name in present[stem] if name not in names.values()]
    if missing and others:
        raise LibrariesUnusableError(
            ToolStatus.WRONG_MAJOR,
            f"It holds {', '.join(others)}; this app's Qt needs {', '.join(missing)}, so a build of the same major "
            "version.",
        )
    if missing:
        raise LibrariesUnusableError(ToolStatus.INCOMPLETE, f"Missing {', '.join(missing)}.")
    return [folder / names[stem] for stem in LIBRARY_ORDER if stem in names]


def load_libraries(files: Sequence[Path]) -> list[ctypes.CDLL]:
    """Load libraries by full path, in the order given; none stays loaded if one fails.

    :param files: the libraries, each after those it depends on.
    :returns: the loaded libraries; a loaded library stays loaded for the life of the process whether or not these
        are kept.
    :raises LibrariesUnusableError: if one cannot be loaded; those loaded before it are freed again.
    """
    loaded: list[ctypes.CDLL] = []
    for file in files:
        try:
            loaded.append(ctypes.CDLL(str(file)))
        except OSError as error:
            free_libraries(loaded)
            if getattr(error, "winerror", None) == WINDOWS_BAD_IMAGE_FORMAT:
                raise LibrariesUnusableError(
                    ToolStatus.WRONG_ARCHITECTURE, f"{file.name} is built for another processor than this app's."
                ) from error
            raise LibrariesUnusableError(ToolStatus.NOT_RUNNABLE, f"{file.name} did not load: {error}") from error
    return loaded


def free_libraries(libraries: Sequence[ctypes.CDLL]) -> None:
    """Unload libraries, the last loaded first.

    :param libraries: what :func:`load_libraries` loaded.
    """
    if sys.platform != "win32":
        return
    # pylint: disable-next=import-outside-toplevel
    import _ctypes

    for library in reversed(libraries):
        _ctypes.FreeLibrary(library._handle)  # pylint: disable=protected-access


def read_loaded_version(libraries: Sequence[ctypes.CDLL]) -> tuple[int, ...] | None:
    """Ask the loaded ``avutil`` for the build's version.

    :param libraries: what :func:`load_libraries` loaded, ``avutil`` first.
    :returns: the version, or ``None`` for a build that reports a commit instead (a git build).
    """
    avutil = libraries[0]
    avutil.av_version_info.restype = ctypes.c_char_p
    match = VERSION_PATTERN.match(avutil.av_version_info() or b"")
    if match is None:
        return None
    return tuple(int(part) for part in match.groups() if part is not None)


def probe(folder: Path, qt_folder: Path, output: Path) -> int:
    """Try a build the way the agent will use it, in this child process, and write what happened.

    The agent never loads an unchosen build, and a build that crashes the process it loads into takes only this one.

    :param folder: the folder holding the build's libraries.
    :param qt_folder: the PySide6 package folder, naming the libraries to match.
    :param output: where to write the answer, a JSON object with ``status``, ``version`` and ``reason``.
    :returns: the exit code: 0 once an answer was written.
    """
    version: tuple[int, ...] | None = None
    try:
        libraries = load_libraries(library_files(folder, bundled_library_names(qt_folder)))
        version = read_loaded_version(libraries)
        status, reason = ToolStatus.UNTESTED if version is None else ToolStatus.USABLE, ""
        if version is None:
            reason = "The version could not be read, so it is untested."
    except LibrariesUnusableError as error:
        status, reason = error.status, error.reason
    output.write_text(
        json.dumps({"status": status.value, "version": list(version or ()), "reason": reason}), encoding="utf-8"
    )
    return 0
