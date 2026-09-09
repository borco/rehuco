"""Legacy screenshot recognition for `.tc` conversion ([[acquisition-tooling#tc-to-rehu]]).

Scans a resource's directory for tc4-era screenshot naming schemes and assigns each recognized file a
fresh ``<stem>NN`` name, matching the reader convention `rehuco_core.rehu_screenshots.scan_rehu_screenshot_files`
already expects. Stays core-side and GUI-free: callers resolve ``stem`` however they need to (e.g. from
``RehuDocumentModel.current_name``) and pass it in as a plain string.
"""

import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final

from PIL import Image, UnidentifiedImageError

from .constants import IMAGE_EXTENSIONS


@dataclass(frozen=True, slots=True)
class ScreenshotNamePattern:
    """A screenshot recognition pattern: a plain regex with a slot convention
    ([[acquisition-tooling#screenshot-schemes]]).

    :ivar pattern: the regular expression, matched case-insensitively against a filename's stem. At
        most one capture group; its match becomes the slot as ``int`` (padding ignored). No capture
        group means slot ``0``.
    """

    pattern: str


SCREENSHOT_NAME_PATTERNS: Final = (
    ScreenshotNamePattern(r"^cover$"),
    ScreenshotNamePattern(r"^file$"),
    ScreenshotNamePattern(r"^(\d+)$"),
    ScreenshotNamePattern(r"^sample-(\d+)$"),
    ScreenshotNamePattern(r"^image-(\d+)$"),
    ScreenshotNamePattern(r"^file-(\d+)$"),
    ScreenshotNamePattern(r"^file\((\d+)\)$"),
)
"""Default screenshot name patterns, in the order they are tried ([[acquisition-tooling#screenshot-schemes]])
-- the tc4-era conventions this catalog actually holds.

What :func:`scan_tc_screenshots` and :func:`is_legacy_screenshot` fall back to when no set is given; the
agent's ``ScreenshotPatternsSettings`` is what makes the set the user's to change. **Order matters only
for which pattern matches first when more than one could** -- an ordinary list, evaluated top to bottom,
first match wins. The *tie-break* between files landing on one slot -- largest pixel area, then
``.jpg``/``.jpeg``, then the alphabetically first name -- is not listed here and is not the user's; it
applies whatever this set says."""


class ScreenshotNamePatterns:
    """An ordered, compiled screenshot name pattern set ([[acquisition-tooling#screenshot-schemes]]).

    Each pattern is compiled once, case-insensitively; a pattern that fails to compile or carries more
    than one capture group is skipped and its raw pattern string collected into :attr:`invalid`, rather
    than letting one malformed entry crash a scan or a conversion.

    :param patterns: the patterns, in the order they are tried.
    """

    def __init__(self, patterns: tuple[ScreenshotNamePattern, ...] = SCREENSHOT_NAME_PATTERNS) -> None:
        compiled: list[re.Pattern[str]] = []
        invalid: list[str] = []
        for pattern in patterns:
            try:
                regex = re.compile(pattern.pattern, re.IGNORECASE)
            except re.error:
                invalid.append(pattern.pattern)
                continue
            if regex.groups > 1:
                invalid.append(pattern.pattern)
                continue
            compiled.append(regex)
        self.__patterns: Final = tuple(compiled)
        self.invalid: Final = tuple(invalid)
        """The raw pattern strings that failed to compile or carried more than one capture group, in
        the order they were given."""

    def slot(self, stem: str) -> int | None:
        """The slot ``stem`` belongs to under the first pattern that matches it.

        :param stem: the filename without its extension.
        :returns: the matched capture group as ``int`` (padding ignored), ``0`` when the matching
            pattern has no capture group, or ``None`` when no pattern matches. A pattern whose group
            captured nothing, or something other than a number, does not decide: the next one is tried.
        """
        for regex in self.__patterns:
            match = regex.match(stem)
            if match is None:
                continue
            if regex.groups == 0:
                return 0
            # a group that captured nothing, or something other than a number, names no slot: the
            # pattern compiled and matched, so it is not invalid, but it cannot decide this stem
            try:
                return int(match.group(1))
            except ValueError, TypeError:
                continue
        return None

    def recognizes(self, stem: str) -> bool:
        """Whether any pattern claims ``stem``.

        :param stem: the filename without its extension.
        :returns: whether :meth:`slot` would return something other than ``None``.
        """
        return self.slot(stem) is not None


@lru_cache(maxsize=8)
def compiled_screenshot_name_patterns(
    patterns: tuple[ScreenshotNamePattern, ...] = SCREENSHOT_NAME_PATTERNS,
) -> ScreenshotNamePatterns:
    """Compile ``patterns`` once and reuse the result.

    Recognition is asked per *file* by walks that visit thousands of them
    (:mod:`rehuco_core.rehu_content_files`), so compiling a pattern set on every question would pay for
    the same regexes over and over. Cached on the pattern tuple itself, which is frozen and hashable.

    :param patterns: the pattern set, as a tuple.
    :returns: the compiled set.
    """
    return ScreenshotNamePatterns(patterns)


def screenshot_name_patterns_state(patterns: tuple[ScreenshotNamePattern, ...]) -> list[str]:
    """Write a pattern set down as plain data a saved job can carry
    ([[appendices.task-queue#lifetime]]).

    :param patterns: the pattern set to serialize.
    :returns: one raw pattern string per entry, in order.
    """
    return [pattern.pattern for pattern in patterns]


def screenshot_name_patterns_from_state(state: object) -> tuple[ScreenshotNamePattern, ...] | None:
    """Read a pattern set back out of a saved job's state, defensively.

    :param state: whatever :func:`screenshot_name_patterns_state` wrote, as read back.
    :returns: the patterns, or ``None`` when the state is missing or malformed -- which leaves the
        caller on its default rather than on a half-read set.
    """
    if not isinstance(state, list) or not all(isinstance(entry, str) for entry in state):
        return None
    return tuple(ScreenshotNamePattern(entry) for entry in state)


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


def scan_tc_screenshots(
    directory: Path, stem: str, patterns: tuple[ScreenshotNamePattern, ...] = SCREENSHOT_NAME_PATTERNS
) -> list[ScreenshotRename]:
    """Scan ``directory`` for tc4 legacy screenshot files and assign each recognized one a new name.

    :param directory: the resource's directory to scan.
    :param stem: the new filename base (e.g. ``"info"`` for a directory-scoped resource, or the file
        stem for a standalone one).
    :param patterns: the naming patterns to recognize, in the order they are tried, resolved by the
        caller -- core never reads a setting.
    :returns: one :class:`ScreenshotRename` per recognized slot, sorted by slot index.
    """
    return TcScreenshotScanner(directory, stem, patterns).scan()


def scan_tc_screenshot_files(
    directory: Path, stem: str, patterns: tuple[ScreenshotNamePattern, ...] = SCREENSHOT_NAME_PATTERNS
) -> list[Path]:
    """List each recognized legacy slot's current (pre-conversion) winner file.

    The reader counterpart of :func:`scan_tc_screenshots`: where that returns the full rename *plan*
    (consumed by conversion), this returns just each slot winner's current path -- what the lightbox
    shows for a ``.tc`` resource before it is converted. Shares the ``(directory, stem)`` signature of
    `rehuco_core.rehu_screenshots.scan_rehu_screenshot_files` so either can serve as a screenshot lister,
    though ``stem`` only feeds the (here-discarded) rename plan and does not affect the returned paths.

    :param directory: the resource's directory to scan.
    :param stem: the new filename base, passed through to the underlying scan.
    :param patterns: the naming patterns to recognize; see :func:`scan_tc_screenshots`. Defaulted so
        this still matches the two-argument lister signature its counterpart is chosen against.
    :returns: each slot winner's absolute path, sorted by slot index.
    """
    return [directory / rename.source_filename for rename in scan_tc_screenshots(directory, stem, patterns)]


def is_legacy_screenshot(filename: str, patterns: tuple[ScreenshotNamePattern, ...] = SCREENSHOT_NAME_PATTERNS) -> bool:
    """Whether ``filename`` is one of tc4's screenshot names -- a slot winner or a losing variant.

    The classification alone, with none of the ranking: this reads a name and opens nothing, where
    :func:`scan_tc_screenshots` compares pixel dimensions to decide which of several files claims a slot.

    Asked by the content walk (:mod:`rehuco_core.rehu_content_files`), which excludes a legacy record's
    screenshots the way it excludes an ``infoNN.jpg`` beside an ``info.rehu`` (#250). Answering here
    rather than restating the schemes there is what keeps the set that walk skips identical to the set
    :func:`~rehuco_core.originals_to_back_up` renames aside -- *every* recognized image, winners and
    losers alike -- so a directory's content is the same set before and after it is converted.

    :param filename: a file's name, not its path.
    :param patterns: the naming patterns to recognize; see :func:`scan_tc_screenshots`.
    :returns: whether it is a recognized legacy screenshot.
    """
    stem, suffix = os.path.splitext(filename)
    return suffix.lower() in IMAGE_EXTENSIONS and compiled_screenshot_name_patterns(patterns).recognizes(stem)


# one public entry point, because a scan is one operation: the classification half moved to
# ScreenshotNamePatterns when the patterns became the caller's (#53, #287), leaving this class the
# ranking and the naming, which nothing asks for separately
# pylint: disable-next=too-few-public-methods
class TcScreenshotScanner:
    """Recognizes tc4's legacy screenshot naming schemes in one directory ([[acquisition-tooling#tc-to-rehu]]).

    Each recognized file's slot comes from :meth:`ScreenshotNamePatterns.slot`, a pure per-filename
    function ([[acquisition-tooling#screenshot-schemes]]) -- see :class:`ScreenshotNamePatterns`, where
    that classification lives.

    When more than one recognized file lands on the same slot (most commonly a thumbnail variant
    tying with a full-size one, but not limited to that pairing), the winner is narrowed by, in
    order: pixel dimensions (largest kept), then ``.jpg``/``.jpeg`` preferred over any other
    extension (only narrows further on an exact dimension tie), then the alphabetically first
    filename (a last-resort deterministic tiebreak, only reached if both of the above still tie).

    :param directory: the resource's directory to scan.
    :param stem: the new filename base (e.g. ``"info"`` or a file stem).
    :param patterns: the naming patterns to recognize, in the order they are tried, resolved by the
        caller -- core never reads a setting.
    """

    __PREFERRED_EXTENSIONS: Final = (".jpg", ".jpeg")

    def __init__(
        self, directory: Path, stem: str, patterns: tuple[ScreenshotNamePattern, ...] = SCREENSHOT_NAME_PATTERNS
    ) -> None:
        self.__directory: Final = directory
        self.__stem: Final = stem
        self.__patterns: Final = compiled_screenshot_name_patterns(patterns)

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

        Each recognized filename's slot comes from :meth:`ScreenshotNamePatterns.slot` on its own stem
        -- there is no directory-level selection any more, only a per-file question repeated once per
        recognized image.

        :returns: ``{slot_index: [filenames]}``, filenames in directory-listing order.
        """
        slots: dict[int, list[str]] = {}
        for filename in self.__recognized_images():
            slot = self.__patterns.slot(Path(filename).stem)
            if slot is None:
                continue
            slots.setdefault(slot, []).append(filename)
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
