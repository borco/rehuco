"""What an optional external program is, and how a copy of it is judged ([[packaging-deployment#external-tools]], #521).

Some programs the app uses cannot ship with it. Each is described once, here, by a :class:`ToolDescriptor`, so the
detection, the version gate and the words a user reads are one shape rather than one per program. Qt-free: the agent's
Tools page shows what these say, and a node, being another machine, asks the same descriptors about its own box.
"""

import glob
import os
import re
import sys
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar, Final

Version = tuple[int, ...]
"""A version as its numeric parts, most significant first; compared as a tuple."""

EXECUTABLE_SUFFIX: Final = ".exe" if sys.platform == "win32" else ""
"""What an executable's file name ends with on this OS."""

SHIM_PATH_PATTERN: Final = re.compile(r'^\s*path\s*=\s*"?([^"]+?)"?\s*$', re.MULTILINE)
"""The line of a scoop ``.shim`` file naming the executable its launcher runs."""


def version_text(version: Version | None) -> str:
    """Spell a version the way a user reads it.

    :param version: the version, or ``None`` when it could not be read.
    :returns: dotted numbers, or ``unknown version``.
    """
    return ".".join(str(part) for part in version) if version else "unknown version"


class ToolNotRunnableError(Exception):
    """A tool's executable that could not be started, or that failed when asked for its version.

    :param reason: a sentence saying what happened, shown as the candidate's status.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason: Final = reason


class ToolStatus(StrEnum):
    """Whether a copy of a tool can be used, as the Tools page says it."""

    USABLE = "usable"
    """A version the tool's descriptor knows to work."""

    UNTESTED = "untested"
    """Newer than any tested, or a version that could not be read: allowed, never refused."""

    MISSING = "missing"
    """Nothing at the path, or a folder that does not hold the tool."""

    NOT_RUNNABLE = "not runnable"
    """The executable does not start."""

    TOO_OLD = "too old"
    """Older than the descriptor's minimum."""

    BLOCKLISTED = "blocklisted"
    """A version known not to work, with the reason."""

    @property
    def is_usable(self) -> bool:
        """Whether a feature may use a copy in this status."""
        return self in (ToolStatus.USABLE, ToolStatus.UNTESTED)


@dataclass(frozen=True)
class BlockedVersion:
    """One version known not to work."""

    version: Version
    """The version, compared whole against a copy's."""

    reason: str
    """Why it does not work, in words a user can act on."""


@dataclass(frozen=True)
class ToolCandidate:
    """One copy of a tool, found or chosen, with what is known about it."""

    folder: Path
    """The folder holding the tool's executables."""

    source: str
    """Where it was found: ``PATH``, ``winget``, ``Custom``..."""

    status: ToolStatus
    """Whether it can be used."""

    version: Version | None = None
    """Its version, or ``None`` when it could not be read."""

    reason: str = ""
    """Why it cannot be used, or is untested; empty when usable."""

    @property
    def is_usable(self) -> bool:
        """Whether a feature may use this copy."""
        return self.status.is_usable

    def executable(self, name: str) -> Path:
        """The path of one of the tool's executables.

        :param name: the executable's name without a suffix.
        :returns: its path in this copy's folder.
        """
        return self.folder / f"{name}{EXECUTABLE_SUFFIX}"

    def to_stored(self) -> dict[str, Any]:
        """Shape this candidate for storage in a settings file.

        :returns: a JSON-ready entry.
        """
        return {
            "folder": str(self.folder),
            "source": self.source,
            "status": self.status.value,
            "version": list(self.version) if self.version else [],
            "reason": self.reason,
        }

    @classmethod
    def from_stored(cls, raw: Any) -> ToolCandidate | None:
        """Read one stored entry, which another build or a hand edit may have written.

        :param raw: the stored entry, of any shape.
        :returns: the candidate, or ``None`` when the entry is not a well-formed one.
        """
        if not isinstance(raw, dict):
            return None
        folder, source, reason = raw.get("folder"), raw.get("source"), raw.get("reason")
        version = raw.get("version")
        try:
            status = ToolStatus(raw.get("status"))
        except ValueError:
            return None
        if not (isinstance(folder, str) and folder and isinstance(source, str) and isinstance(reason, str)):
            return None
        if not (isinstance(version, list) and all(isinstance(part, int) for part in version)):
            return None
        return cls(Path(folder), source, status, tuple(version) or None, reason)


def best_candidate(candidates: Iterable[ToolCandidate]) -> ToolCandidate | None:
    """The copy a feature should use: the newest usable one, the earliest listed among equals.

    :param candidates: the copies found.
    :returns: the best, or ``None`` when none is usable.
    """
    usable = [candidate for candidate in candidates if candidate.is_usable]
    return max(usable, key=lambda candidate: candidate.version or (), default=None)


class ToolDescriptor(ABC):
    """What the app knows about one external tool: what it is for, where each OS keeps it, how its version is read
    and which versions are no good.

    There are no checksums: a descriptor has a minimum and a blocklist, and a version newer than any tested is
    :attr:`~ToolStatus.UNTESTED` and allowed, since an allowlist would lock out everyone who updated.
    """

    ID: ClassVar[str]
    """The tool's stable identifier -- the key its path is stored under, never the display text."""

    LABEL: ClassVar[str]
    """How the tool is named to a user."""

    PURPOSE: ClassVar[str]
    """What the tool is for, in a sentence."""

    FEATURES: ClassVar[str]
    """Which features need it."""

    NOT_BUNDLED_BECAUSE: ClassVar[str]
    """Why it does not ship with the app."""

    DOCS_ANCHOR: ClassVar[str]
    """The section of the docs site's External Tools page that says where to get it."""

    EXECUTABLES: ClassVar[tuple[str, ...]]
    """The executables a folder must hold, without a suffix."""

    MINIMUM: ClassVar[Version]
    """The oldest version that works."""

    NEWEST_TESTED: ClassVar[Version]
    """The newest version known to work, to the parts given: a later patch of a tested ``major.minor`` is tested too,
    and anything beyond is untested."""

    BLOCKLIST: ClassVar[tuple[BlockedVersion, ...]] = ()
    """The versions known not to work."""

    @abstractmethod
    def search_patterns(self) -> tuple[tuple[str, str], ...]:
        """Where this OS usually keeps the tool, beyond ``PATH``.

        :returns: ``(source, glob pattern of a folder)`` pairs, each pattern with its environment variables expanded.
        """

    @abstractmethod
    def read_version(self, folder: Path) -> Version | None:
        """Ask the copy in ``folder`` for its version, loading nothing into this process.

        :param folder: the folder holding the executables.
        :returns: the version, or ``None`` when it prints one in no form that can be compared (a git build).
        :raises ToolNotRunnableError: if the executable does not start.
        """

    def executable_files(self, folder: Path) -> list[Path]:
        """The tool's executables in a folder, whether or not they exist.

        :param folder: the folder.
        :returns: one path per name in :attr:`EXECUTABLES`.
        """
        return [folder / f"{name}{EXECUTABLE_SUFFIX}" for name in self.EXECUTABLES]

    def resolve_folder(self, path: Path) -> Path | None:
        """Find the folder holding the tool from what a user picked: an executable, its folder, or an unpacked
        archive's root holding a ``bin``.

        A folder of links to the executables (winget's ``Links``), or of scoop's shims -- a launcher beside a ``.shim``
        file naming the real executable -- resolves to the folder they point at, so one install found two ways is
        listed once.

        :param path: what was picked.
        :returns: the folder holding every executable, or ``None`` when it is not one.
        """
        if path.is_file():
            path = path.parent
        for folder in (path, path / "bin"):
            if all(file.is_file() for file in self.executable_files(folder)):
                target = self.__pointed_folder(self.executable_files(folder)[0]) or folder
                if all(file.is_file() for file in self.executable_files(target)):
                    return target
                return folder
        return None

    @staticmethod
    def __pointed_folder(executable: Path) -> Path | None:
        """The folder a stand-in for an executable points at: a linked file's target, or a scoop shim's.

        Only a linked *file*, never a linked folder: scoop's ``current`` is a junction whose path should stay, so a
        chosen install survives an update.

        :param executable: the executable, as found.
        :returns: the folder holding what it stands in for, or ``None`` when it is the executable itself.
        """
        if executable.is_symlink():
            return executable.resolve().parent
        shim = executable.with_suffix(".shim")
        try:
            match = SHIM_PATH_PATTERN.search(shim.read_text(encoding="utf-8"))
        except OSError, UnicodeDecodeError:
            return None
        return Path(match.group(1)).parent if match is not None else None

    def search_folders(self) -> list[tuple[str, Path]]:
        """Every folder this OS may keep the tool in: those on ``PATH``, then the descriptor's patterns.

        :returns: ``(source, folder)`` pairs in search order, not yet checked to hold the tool.
        """
        found = [("PATH", Path(entry)) for entry in os.environ.get("PATH", "").split(os.pathsep) if entry]
        for source, pattern in self.search_patterns():
            found.extend((source, Path(match)) for match in sorted(glob.glob(pattern)))
        return found

    def judge(self, version: Version | None) -> tuple[ToolStatus, str]:
        """Judge a runnable copy by its version alone.

        :param version: the copy's version, or ``None`` when unreadable.
        :returns: its status and, unless usable, the reason.
        """
        if version is None:
            return ToolStatus.UNTESTED, "The version could not be read, so it is untested."
        if version < self.MINIMUM:
            return ToolStatus.TOO_OLD, f"Version {version_text(self.MINIMUM)} or newer is needed."
        for blocked in self.BLOCKLIST:
            if blocked.version == version:
                return ToolStatus.BLOCKLISTED, blocked.reason
        if version[: len(self.NEWEST_TESTED)] > self.NEWEST_TESTED:
            return ToolStatus.UNTESTED, "Newer than any version tested."
        return ToolStatus.USABLE, ""
