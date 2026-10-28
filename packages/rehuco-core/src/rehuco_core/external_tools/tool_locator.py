"""Finds copies of a tool and says whether each can be used ([[packaging-deployment#external-tools]], #521)."""

import threading
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

from .tool_descriptor import ToolCandidate, ToolDescriptor, ToolNotRunnableError, ToolStatus, best_candidate


class ToolLocator:
    """Turns a :class:`~rehuco_core.external_tools.tool_descriptor.ToolDescriptor` into candidates.

    Asked when a feature needs the tool, never once at start: a tool updates itself and a share unmounts. What costs
    is running the tool for its version, so that is cached by folder and the executables' modification times, which
    an update changes.
    """

    def __init__(self) -> None:
        self.__lock = threading.Lock()
        self.__readings: dict[tuple[str, Path, tuple[int, ...]], ToolCandidate] = {}

    def inspect(self, descriptor: ToolDescriptor, path: Path | str, source: str = "Custom") -> ToolCandidate:
        """Judge the copy a path names.

        :param descriptor: the tool.
        :param path: an executable, the folder holding it, or an unpacked archive's root.
        :param source: where the path came from, shown beside it.
        :returns: the candidate; :attr:`~ToolStatus.MISSING` when the path holds no copy.
        """
        path = Path(path)
        missing = ToolCandidate(path, source, ToolStatus.MISSING, reason=f"No {descriptor.LABEL} at {path}.")
        folder = descriptor.resolve_folder(path)
        if folder is None:
            return missing
        try:
            stamps = tuple(file.stat().st_mtime_ns for file in descriptor.executable_files(folder))
        except OSError:
            return missing
        key = (descriptor.ID, folder, stamps)
        with self.__lock:
            reading = self.__readings.get(key)
        if reading is None:
            reading = self.__read(descriptor, folder)
            with self.__lock:
                self.__readings[key] = reading
        return ToolCandidate(folder, source, reading.status, reading.version, reading.reason)

    def detect(self, descriptor: ToolDescriptor) -> list[ToolCandidate]:
        """List every copy this OS keeps in its usual places.

        :param descriptor: the tool.
        :returns: the candidates, one per folder: usable ones first, newest first, the unusable ones after, listed
            rather than skipped.
        """
        seen: set[Path] = set()
        found: list[ToolCandidate] = []
        for source, folder in descriptor.search_folders():
            candidate = self.inspect(descriptor, folder, source)
            if candidate.status is ToolStatus.MISSING or candidate.folder.resolve() in seen:
                continue
            seen.add(candidate.folder.resolve())
            found.append(candidate)
        return sorted(found, key=lambda candidate: (candidate.is_usable, candidate.version or ()), reverse=True)

    def verify(self, descriptor: ToolDescriptor, candidates: Iterable[ToolCandidate]) -> list[ToolCandidate]:
        """Keep the copies found earlier that are still there.

        Only that the executables exist is checked: nothing is searched for and no version is read again, which is
        what makes it cheap enough to do at every start. An update is noticed when a search is forced.

        :param descriptor: the tool.
        :param candidates: copies found earlier.
        :returns: those whose folder still holds the tool, in their order.
        """
        return [candidate for candidate in candidates if descriptor.resolve_folder(candidate.folder) is not None]

    def resolve(
        self, descriptor: ToolDescriptor, configured: str = "", detected: Iterable[ToolCandidate] = ()
    ) -> ToolCandidate | None:
        """Find the copy a feature should use, searching for nothing.

        :param descriptor: the tool.
        :param configured: the path the user chose, or empty for the best copy found.
        :param detected: the copies found earlier, as stored.
        :returns: the chosen path's candidate, usable or not, so its reason can be shown; for an empty path the
            newest usable copy among ``detected``, or ``None`` when there is none. A copy found earlier that is no
            longer there -- uninstalled, or on a share that is down -- comes back :attr:`~ToolStatus.MISSING` rather
            than usable, so a scan refuses instead of totalling ``0`` over files it never read.
        """
        if configured:
            return self.inspect(descriptor, configured)
        best = best_candidate(detected)
        if best is not None and descriptor.resolve_folder(best.folder) is None:
            reason = f"{descriptor.LABEL} at {best.folder} is no longer there; press Detect to look again."
            return ToolCandidate(best.folder, best.source, ToolStatus.MISSING, best.version, reason)
        return best

    @staticmethod
    def __read(descriptor: ToolDescriptor, folder: Path) -> ToolCandidate:
        """Run the copy for its version and judge it.

        :param descriptor: the tool.
        :param folder: the folder holding it.
        :returns: the candidate, its source left for the caller to set.
        """
        try:
            version = descriptor.read_version(folder)
        except ToolNotRunnableError as error:
            return ToolCandidate(folder, "", ToolStatus.NOT_RUNNABLE, reason=error.reason)
        status, reason = descriptor.judge(version)
        return ToolCandidate(folder, "", status, version, reason)


@lru_cache(maxsize=1)
def shared_tool_locator() -> ToolLocator:
    """The process-wide locator, so every feature shares one cache of versions already read.

    :returns: the shared instance.
    """
    return ToolLocator()
