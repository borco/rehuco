"""Legacy screenshot recognition for `.tc` conversion ([[acquisition-tooling#tc-to-rehu]]).

Scans a resource's directory for tc4-era screenshot naming schemes and assigns each recognized file a
fresh ``<stem>NN`` name, matching the reader convention
``rehuco_agent.documents.rehu_document_model.RehuDocumentModel.image_files()`` already expects. Stays
core-side and GUI-free: callers resolve ``stem`` however they need to (e.g. from
``RehuDocumentModel.current_name``) and pass it in as a plain string.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from PIL import Image, UnidentifiedImageError

from .constants import IMAGE_EXTENSIONS


@dataclass(frozen=True)
class ScreenshotRename:
    """One new-name slot's outcome from scanning a resource's directory for legacy screenshots.

    :ivar new_name: the fresh ``<stem>NN`` filename, keeping the winning file's own extension/case.
    :ivar source_filename: the winning old filename whose bytes become ``new_name``.
    :ivar recognized_filenames: every old filename that landed on this slot, winner and losers alike
        -- both the file actually renamed and any same-photo smaller/duplicate variant, since a
        description Markdown reference to either should end up pointing at ``new_name``.
    """

    new_name: str
    source_filename: str
    recognized_filenames: tuple[str, ...]


def scan_tc_screenshots(directory: Path, stem: str) -> list[ScreenshotRename]:
    """Scan ``directory`` for tc4 legacy screenshot files and assign each recognized one a new name.

    :param directory: the resource's directory to scan.
    :param stem: the new filename base (e.g. ``"info"`` for a directory-scoped resource, or the file
        stem for a standalone one).
    :returns: one :class:`ScreenshotRename` per recognized slot, sorted by slot index.
    """
    return TcScreenshotScanner(directory, stem).scan()


class TcScreenshotScanner:  # pylint: disable=too-few-public-methods
    """Recognizes tc4's legacy screenshot naming schemes in one directory ([[acquisition-tooling#tc-to-rehu]]).

    Five patterns, matched case-insensitively against a candidate image's filename stem, mutually
    exclusive by construction (distinct literal prefixes):

    - bare zero-padded index (``00``, ``01``, ...) -- its own independent series.
    - ``sample-NN`` -- a full-size series.
    - ``file`` / ``file(N)`` -- ``file`` alone is index 0, then Windows-duplicate-style ``(N)``
      suffixes for the rest; a genuine series, not duplicates of each other -- another full-size one.
    - ``cover`` -- always index 0, a smaller/thumbnail variant of whatever full-size series holds
      that same photo.
    - ``file-NN`` -- a smaller/thumbnail variant series; the numeric suffix *is* the index directly.

    When more than one recognized file lands on the same index (most commonly a thumbnail variant
    tying with a full-size one, but not limited to that pairing), the winner is narrowed by, in
    order: pixel dimensions (largest kept), then ``.jpg``/``.jpeg`` preferred over any other
    extension (only narrows further on an exact dimension tie), then the alphabetically first
    filename (a last-resort deterministic tiebreak, only reached if both of the above still tie).

    :param directory: the resource's directory to scan.
    :param stem: the new filename base (e.g. ``"info"`` or a file stem).
    """

    __BARE_NUMERIC_RE: Final = re.compile(r"^(\d+)$")
    __SAMPLE_RE: Final = re.compile(r"^sample-(\d+)$", re.IGNORECASE)
    __FILE_SERIES_RE: Final = re.compile(r"^file(?:\((\d+)\))?$", re.IGNORECASE)
    __COVER_RE: Final = re.compile(r"^cover$", re.IGNORECASE)
    __FILE_SMALL_RE: Final = re.compile(r"^file-(\d+)$", re.IGNORECASE)

    __PREFERRED_EXTENSIONS: Final = (".jpg", ".jpeg")

    def __init__(self, directory: Path, stem: str) -> None:
        self.__directory: Final = directory
        self.__stem: Final = stem

    def scan(self) -> list[ScreenshotRename]:
        """Scan :attr:`directory` and assign each recognized legacy screenshot a new name.

        :returns: one :class:`ScreenshotRename` per recognized slot, sorted by slot index.
        """
        slots = self.__group_by_slot()
        renames = []
        for index in sorted(slots):
            candidates = slots[index]
            winner = self.__winner(candidates)
            new_name = f"{self.__stem}{index:02d}{Path(winner).suffix}"
            renames.append(ScreenshotRename(new_name, winner, tuple(candidates)))
        return renames

    def __group_by_slot(self) -> dict[int, list[str]]:
        """Classify every recognized image into its slot index.

        :returns: ``{slot_index: [filenames]}``, filenames in directory-listing order.
        """
        slots: dict[int, list[str]] = {}
        for filename in self.__recognized_images():
            index = self.__slot_index(Path(filename).stem)
            if index is not None:
                slots.setdefault(index, []).append(filename)
        return slots

    def __recognized_images(self) -> list[str]:
        """List :attr:`directory`'s entries with a recognized image extension.

        :returns: matching filenames, or empty when the directory is missing/unreadable (e.g. an
            offline mount, [[mounts-and-storage#offline-mounts]]).
        """
        try:
            entries = list(self.__directory.iterdir())
        except OSError:
            return []
        return [entry.name for entry in entries if entry.suffix.lower() in IMAGE_EXTENSIONS]

    def __slot_index(self, file_stem: str) -> int | None:
        """Classify one filename's stem against the five patterns.

        :param file_stem: the filename without its extension.
        :returns: the slot index it belongs to, or ``None`` if it matches no recognized pattern.
        """
        if match := self.__BARE_NUMERIC_RE.match(file_stem):
            return int(match.group(1))
        if match := self.__SAMPLE_RE.match(file_stem):
            return int(match.group(1))
        if match := self.__FILE_SERIES_RE.match(file_stem):
            return int(match.group(1)) if match.group(1) else 0
        if self.__COVER_RE.match(file_stem):
            return 0
        if match := self.__FILE_SMALL_RE.match(file_stem):
            return int(match.group(1))
        return None

    def __winner(self, candidates: list[str]) -> str:
        """Narrow ``candidates`` down to the single winning filename (see class docstring for order).

        The common case (no tie to break) returns outright without opening any file -- pixel-size
        ranking is only worth its I/O when there's actually more than one candidate to compare.

        :param candidates: every recognized filename sharing one slot index.
        :returns: the winning filename.
        """
        if len(candidates) == 1:
            return candidates[0]
        narrowed = self.__narrowed_to_max(candidates, self.__pixel_area)
        narrowed = self.__narrowed_to_max(narrowed, self.__is_preferred_extension)
        return min(narrowed)

    def __narrowed_to_max(self, filenames: list[str], key: Callable[[str], int]) -> list[str]:
        """Keep only the filenames sharing the highest ``key`` value among ``filenames``.

        :param filenames: candidates to narrow.
        :param key: a scoring function evaluated once per filename.
        :returns: the subset of ``filenames`` whose score equals the highest one found.
        """
        scores = {filename: key(filename) for filename in filenames}
        best = max(scores.values())
        return [filename for filename in filenames if scores[filename] == best]

    def __is_preferred_extension(self, filename: str) -> int:
        """Whether ``filename``'s extension is ``.jpg``/``.jpeg``, as a 0/1 score for :meth:`__winner`."""
        return 1 if Path(filename).suffix.lower() in self.__PREFERRED_EXTENSIONS else 0

    def __pixel_area(self, filename: str) -> int:
        """Read ``filename``'s pixel dimensions (a lazy, header-only read for these formats).

        :param filename: the candidate filename, resolved against :attr:`directory`.
        :returns: ``width * height``, or ``0`` when the file can't be read as an image -- this runs during
            `.tc` conversion's plan phase, before any disk mutation, so a corrupt candidate should just lose
            the ranking contest rather than abort the conversion.
        """
        try:
            with Image.open(self.__directory / filename) as image:
                width, height = image.size
        except UnidentifiedImageError, OSError:
            return 0
        return width * height
