"""Legacy screenshot recognition for `.tc` conversion ([[acquisition-tooling#tc-to-rehu]]).

Scans a resource's directory for tc4-era screenshot naming schemes and renames each recognized file to
**the number it already carries**, zero-padded to two digits, under the ``<stem>NN`` convention the
reader `rehuco_core.rehu_screenshots.scan_rehu_screenshot_files` expects. Nothing is inferred and
nothing is dropped: a file whose slot is already taken keeps its own name and is reported as
un-converted, for the images dock to settle by hand ([[plugins#tutorial-plugin]], #270). Stays core-side
and GUI-free: callers resolve ``stem`` however they need to (e.g. from
``RehuDocumentModel.current_name``) and pass it in as a plain string.
"""

import os
import re
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Final

from PIL import Image, UnidentifiedImageError

from .constants import IMAGE_EXTENSIONS, LEGACY_SUFFIX
from .rehu_screenshots import scan_rehu_screenshot_files


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
agent's ``ScreenshotPatternsSettings`` is what makes the set the user's to change. **Order decides two
things**: which pattern claims a name more than one of them matches -- an ordinary list, evaluated top to
bottom, first match wins -- and, when two names want one slot, which of them takes it (#288). With this
set that second rule reads as *``cover`` first*, since ``^cover$`` leads the list."""


@dataclass(frozen=True, slots=True)
class ScreenshotSlotMatch:
    """Which slot a stem belongs to, and which pattern said so.

    :ivar slot: the slot number, read off the matching pattern's capture group (``0`` when it has none).
    :ivar pattern_index: the matching pattern's position in the set, counting only the patterns that
        compiled. What orders a collision: the earlier pattern's file takes the slot
        ([[acquisition-tooling#tc-to-rehu]]).
    """

    slot: int
    pattern_index: int


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

    def match(self, stem: str) -> ScreenshotSlotMatch | None:
        """The slot ``stem`` belongs to under the first pattern that matches it, and which one that was.

        :param stem: the filename without its extension.
        :returns: the match, or ``None`` when no pattern claims ``stem``. A pattern whose group
            captured nothing, or something other than a number, does not decide: the next one is tried.
        """
        for index, regex in enumerate(self.__patterns):
            found = regex.match(stem)
            if found is None:
                continue
            if regex.groups == 0:
                return ScreenshotSlotMatch(0, index)
            # a group that captured nothing, or something other than a number, names no slot: the
            # pattern compiled and matched, so it is not invalid, but it cannot decide this stem
            try:
                return ScreenshotSlotMatch(int(found.group(1)), index)
            except ValueError, TypeError:
                continue
        return None

    def slot(self, stem: str) -> int | None:
        """The slot ``stem`` belongs to, without which pattern decided it.

        :param stem: the filename without its extension.
        :returns: :attr:`ScreenshotSlotMatch.slot` of :meth:`match`, or ``None`` when nothing matched.
        """
        found = self.match(stem)
        return None if found is None else found.slot

    def recognizes(self, stem: str) -> bool:
        """Whether any pattern claims ``stem``.

        :param stem: the filename without its extension.
        :returns: whether :meth:`match` would return something other than ``None``.
        """
        return self.match(stem) is not None


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


MAX_SCREENSHOT_SLOT: Final = 100
"""The first slot number a conversion will not write ([[acquisition-tooling#tc-to-rehu]]).

No resource genuinely carries a hundred screenshots, so a triple-digit legacy number is someone else's
convention rather than this one's: the file keeps its name and the conversion says so, instead of
inventing a three-digit ``<stem>NNN`` the reader would not recognize."""


class ScreenshotSkipReason(StrEnum):
    """Why a pattern-matched image is left under its own name by a conversion (#288)."""

    COLLISION = "collision"
    """Its slot is already taken -- by an earlier legacy name, by another extension of the same name,
    or by a ``<stem>NN`` file already on disk. Nothing decides between two pictures claiming one
    number, so the later one is left for the images dock ([[plugins#tutorial-plugin]], #270)."""

    OUT_OF_RANGE = "out of range"
    """Its number is :data:`MAX_SCREENSHOT_SLOT` or above."""


@dataclass(frozen=True, slots=True)
class ScreenshotRename:
    """One pattern-matched image and the ``<stem>NN`` name it is renamed to.

    :ivar new_name: the fresh ``<stem>NN`` filename, keeping the file's own extension/case.
    :ivar source_filename: the legacy filename that becomes ``new_name`` -- a rename, so no second
        file is involved and nothing is copied.
    """

    new_name: str
    source_filename: str


@dataclass(frozen=True, slots=True)
class UnconvertedScreenshot:
    """One pattern-matched image a conversion leaves alone, and why (#288).

    :ivar filename: the legacy filename, untouched on disk.
    :ivar reason: why the conversion did not claim a slot for it.
    """

    filename: str
    reason: ScreenshotSkipReason


@dataclass(frozen=True, slots=True)
class TcScreenshotPlan:
    """What converting one directory's screenshots would do ([[acquisition-tooling#tc-to-rehu]]).

    Every pattern-matched image is in exactly one of the two tuples, which is the whole no-loss
    invariant: an image is renamed to the number it carries, or it is left exactly as it was found and
    named here.

    :ivar renames: the renames to perform, in slot order.
    :ivar unconverted: the images left under their own names, sorted by filename.
    """

    renames: tuple[ScreenshotRename, ...] = ()
    unconverted: tuple[UnconvertedScreenshot, ...] = ()

    @property
    def collision(self) -> bool:
        """Whether some image was left alone because its slot was taken -- the one outcome of a
        conversion worth a human's attention afterwards ([[acquisition-tooling#convert-mechanics]])."""
        return any(image.reason is ScreenshotSkipReason.COLLISION for image in self.unconverted)


def scan_tc_screenshots(
    directory: Path, stem: str, patterns: tuple[ScreenshotNamePattern, ...] = SCREENSHOT_NAME_PATTERNS
) -> TcScreenshotPlan:
    """Scan ``directory`` for tc4 legacy screenshot files and give each the number it already carries.

    :param directory: the resource's directory to scan.
    :param stem: the new filename base (e.g. ``"info"`` for a directory-scoped resource, or the file
        stem for a standalone one).
    :param patterns: the naming patterns to recognize, in the order they are tried, resolved by the
        caller -- core never reads a setting.
    :returns: the plan; see :class:`TcScreenshotPlan`.
    """
    return TcScreenshotScanner(directory, stem, patterns).scan()


def scan_tc_screenshot_files(
    directory: Path, stem: str, patterns: tuple[ScreenshotNamePattern, ...] = SCREENSHOT_NAME_PATTERNS
) -> list[Path]:
    """List the current (pre-conversion) path of every screenshot a conversion would number.

    The reader counterpart of :func:`scan_tc_screenshots`: where that returns the full plan (consumed by
    conversion), this returns just the files that will end up in a slot -- what the lightbox shows for a
    ``.tc`` resource before it is converted. Shares the ``(directory, stem)`` signature of
    `rehuco_core.rehu_screenshots.scan_rehu_screenshot_files` so either can serve as a screenshot lister,
    though ``stem`` only feeds the (here-discarded) rename plan and does not affect the returned paths.

    :param directory: the resource's directory to scan.
    :param stem: the new filename base, passed through to the underlying scan.
    :param patterns: the naming patterns to recognize; see :func:`scan_tc_screenshots`. Defaulted so
        this still matches the two-argument lister signature its counterpart is chosen against.
    :returns: each numbered screenshot's current absolute path, in slot order.
    """
    plan = scan_tc_screenshots(directory, stem, patterns)
    return [directory / rename.source_filename for rename in plan.renames]


def is_legacy_screenshot(filename: str, patterns: tuple[ScreenshotNamePattern, ...] = SCREENSHOT_NAME_PATTERNS) -> bool:
    """Whether ``filename`` is one of tc4's screenshot names.

    The classification alone, with none of the numbering: this reads a name and opens nothing, where
    :func:`scan_tc_screenshots` resolves whole directories into slots.

    Asked by the content walk (:mod:`rehuco_core.rehu_content_files`), which counts a pattern-matched
    image as a screenshot beside any record or none (#289). Answering here rather than restating the
    schemes there is what keeps that walk's answer identical to the conversion's -- so a directory's
    content is the same set before and after it is converted, including the images the conversion left
    under their own names.

    :param filename: a file's name, not its path.
    :param patterns: the naming patterns to recognize; see :func:`scan_tc_screenshots`.
    :returns: whether it is a recognized legacy screenshot.
    """
    stem, suffix = os.path.splitext(filename)
    return suffix.lower() in IMAGE_EXTENSIONS and compiled_screenshot_name_patterns(patterns).recognizes(stem)


def natural_sort_key(filename: str) -> tuple[tuple[int, int, str], ...]:
    """``filename`` as a natural-sort key, so ``file-2`` sorts before ``file-10``.

    Shared between :class:`TcScreenshotScanner`, which orders same-pattern candidates by it, and
    :func:`scan_unconverted_screenshots`, which orders the images dock's un-converted row by it (#265).

    :param filename: the candidate filename.
    :returns: one entry per digit/non-digit run, digits compared as numbers.
    """
    return tuple(
        (0, int(part), "") if part.isdigit() else (1, 0, part.lower()) for part in re.split(r"(\d+)", filename) if part
    )


def scan_unconverted_screenshots(
    directory: Path, stem: str, patterns: tuple[ScreenshotNamePattern, ...] = SCREENSHOT_NAME_PATTERNS
) -> list[Path]:
    """List ``directory``'s pattern-matched images that have not yet been given a ``<stem>NN`` slot.

    The images dock's second row kind ([[plugins#tutorial-plugin]], #265): a picture the screenshot name
    patterns recognize but that no conversion -- whole-directory or single-file (:func:`convert_screenshot`)
    -- has renamed into the numbered set yet. Unlike :func:`scan_tc_screenshots`, nothing here groups
    same-stem variants or picks a winner between them: every recognized image is listed, and it is the
    dock, not this scan, that a user settles one row at a time.

    :param directory: the resource's directory to scan.
    :param stem: the filename base already-numbered siblings carry (e.g. ``"info"``), so this can tell
        them apart from the still-unclaimed images being listed.
    :param patterns: the naming patterns to recognize; see :func:`scan_tc_screenshots`.
    :returns: the matching paths, in natural-sort order, or empty when ``directory`` is
        missing/unreadable (e.g. an offline mount, [[mounts-and-storage#offline-mounts]]).
    """
    numbered = re.compile(rf"^{re.escape(stem)}\d{{2}}$", re.IGNORECASE)
    recognized = compiled_screenshot_name_patterns(patterns)
    try:
        entries = list(directory.iterdir())
    except OSError:
        return []
    candidates = [
        entry.name
        for entry in entries
        if entry.suffix.lower() in IMAGE_EXTENSIONS
        and not numbered.match(entry.stem)
        and recognized.recognizes(entry.stem)
    ]
    return [directory / name for name in sorted(candidates, key=natural_sort_key)]


def convert_screenshot(
    path: Path, stem: str, patterns: tuple[ScreenshotNamePattern, ...] = SCREENSHOT_NAME_PATTERNS
) -> Path:
    """Convert one un-converted, pattern-matched screenshot into its own ``<stem>NN`` slot.

    ``path`` takes the legacy number its own name carries when that slot is free, and is appended past
    the current end of the numbered set otherwise -- the free-slot-or-append rule of #265, and the fix
    for the two-click case a whole-directory conversion (#288) cannot decide on its own: delete
    ``info00``, then convert ``sample-00`` and it lands on the slot that just opened rather than being
    refused as a collision. A legacy number at or above :data:`MAX_SCREENSHOT_SLOT` is not a free slot
    either -- the whole-directory conversion leaves such a file alone for exactly this hand correction
    ([[acquisition-tooling#tc-to-rehu]]) -- so it appends the same way rather than writing a
    ``<stem>NNN`` no reader recognizes.

    :param path: the image to convert, still under its legacy name.
    :param stem: the filename base the numbered set shares (e.g. ``"info"``).
    :param patterns: the naming patterns to recognize; see :func:`scan_tc_screenshots`.
    :returns: the file's new path.
    :raises PermissionError: ``path``'s resource is still a ``.tc``. Its images are numbered by the
        whole-directory conversion and nothing else: the dock is a read-only view over an open ``.tc``
        ([[plugins#tutorial-plugin]]), and the same lock applies here where that view cannot.
    :raises LookupError: ``path``'s name matches no pattern in ``patterns``.
    :raises ValueError: the numbered set is full -- appending would need a slot at or above
        :data:`MAX_SCREENSHOT_SLOT`.
    :raises FileExistsError: the chosen ``<stem>NN`` name is already on disk.
    """
    directory = path.parent
    if (directory / f"{stem}{LEGACY_SUFFIX}").exists():
        raise PermissionError(f"{path} belongs to a resource that is still a .tc")
    match = compiled_screenshot_name_patterns(patterns).match(path.stem)
    if match is None:
        raise LookupError(f"{path.name} matches no screenshot name pattern")
    taken = {int(existing.stem[len(stem) :]) for existing in scan_rehu_screenshot_files(directory, stem)}
    free = match.slot < MAX_SCREENSHOT_SLOT and match.slot not in taken
    slot = match.slot if free else max(taken, default=-1) + 1
    if slot >= MAX_SCREENSHOT_SLOT:
        raise ValueError(f"{path.name} cannot be numbered: the {stem}NN set is full")
    destination = directory / f"{stem}{slot:02d}{path.suffix}"
    if destination.exists():
        raise FileExistsError(destination)
    path.rename(destination)
    return destination


# one public entry point, because a scan is one operation: the classification half moved to
# ScreenshotNamePatterns when the patterns became the caller's (#53, #287), leaving this class the
# per-directory resolution, which nothing asks for separately
# pylint: disable-next=too-few-public-methods
class TcScreenshotScanner:
    """Numbers one directory's tc4 legacy screenshots ([[acquisition-tooling#tc-to-rehu]], #288).

    Each recognized file's slot comes from :meth:`ScreenshotNamePatterns.match`, a pure per-filename
    function ([[acquisition-tooling#screenshot-schemes]]) -- see :class:`ScreenshotNamePatterns`, where
    that classification lives. **The number a file carries is its slot**; nothing here infers one, and a
    slot two files want is given to neither of them twice:

    * a ``<stem>NN`` file already on disk owns that slot before the scan starts, and is not a candidate
      itself -- which is what makes a second conversion of the same directory rename nothing;
    * one stem under several extensions is one picture, so only the largest by pixel area (then the
      first in :data:`~rehuco_core.constants.IMAGE_EXTENSIONS`) takes the slot;
    * between different names, the earlier pattern's file takes the slot, then the earlier name by
      natural sort -- which for the shipped set means ``cover`` before a numbered series.

    Everything not renamed is reported, never dropped: see :class:`TcScreenshotPlan`.

    :param directory: the resource's directory to scan.
    :param stem: the new filename base (e.g. ``"info"`` or a file stem).
    :param patterns: the naming patterns to recognize, in the order they are tried, resolved by the
        caller -- core never reads a setting.
    """

    def __init__(
        self, directory: Path, stem: str, patterns: tuple[ScreenshotNamePattern, ...] = SCREENSHOT_NAME_PATTERNS
    ) -> None:
        self.__directory: Final = directory
        self.__stem: Final = stem
        self.__patterns: Final = compiled_screenshot_name_patterns(patterns)
        self.__numbered: Final = re.compile(rf"^{re.escape(stem)}\d{{2}}$", re.IGNORECASE)

    def scan(self) -> TcScreenshotPlan:
        """Scan :attr:`directory` and give each recognized legacy screenshot its own number.

        :returns: the plan; see :class:`TcScreenshotPlan`.
        """
        images = self.__images()
        taken = {int(Path(name).stem[len(self.__stem) :]) for name in images if self.__is_numbered(name)}
        renames: list[ScreenshotRename] = []
        unconverted: list[UnconvertedScreenshot] = []
        for match, winner, variants in self.__candidates(images):
            reason = self.__refusal(match.slot, taken)
            if reason is not None:
                unconverted.extend(UnconvertedScreenshot(name, reason) for name in (winner, *variants))
                continue
            taken.add(match.slot)
            renames.append(ScreenshotRename(f"{self.__stem}{match.slot:02d}{Path(winner).suffix}", winner))
            unconverted.extend(UnconvertedScreenshot(name, ScreenshotSkipReason.COLLISION) for name in variants)
        # slots are handed out in pattern order, which is not slot order -- a bare `05` under the third
        # pattern is decided before an `image-01` under the fifth -- so the plan is sorted afterwards
        return TcScreenshotPlan(
            tuple(sorted(renames, key=lambda rename: rename.new_name)),
            tuple(sorted(unconverted, key=lambda image: image.filename)),
        )

    @staticmethod
    def __refusal(slot: int, taken: set[int]) -> ScreenshotSkipReason | None:
        """Why ``slot`` cannot be written, or ``None`` when it can.

        :param slot: the slot a candidate's own name carries.
        :param taken: the slots already spoken for.
        :returns: the reason to leave the candidate alone, or ``None``.
        """
        if slot >= MAX_SCREENSHOT_SLOT:
            return ScreenshotSkipReason.OUT_OF_RANGE
        return ScreenshotSkipReason.COLLISION if slot in taken else None

    def __images(self) -> list[str]:
        """List :attr:`directory`'s entries with a recognized image extension.

        :returns: matching filenames, or empty when the directory is missing/unreadable (e.g. an
            offline mount, [[mounts-and-storage#offline-mounts]]).
        """
        try:
            entries = list(self.__directory.iterdir())
        except OSError:
            return []
        return [entry.name for entry in entries if entry.suffix.lower() in IMAGE_EXTENSIONS]

    def __is_numbered(self, filename: str) -> bool:
        """Whether ``filename`` already sits in a ``<stem>NN`` slot.

        Such a file is not a conversion candidate whatever the patterns say about its stem: it is
        already where the reader looks, and it owns its number against everything else in the
        directory.

        :param filename: a file name from :meth:`__images`.
        :returns: whether it matches ``<stem>NN`` with a two-digit index.
        """
        return self.__numbered.match(Path(filename).stem) is not None

    def __candidates(self, images: list[str]) -> list[tuple[ScreenshotSlotMatch, str, list[str]]]:
        """Group the pattern-matched images by name and put them in the order slots are handed out.

        :param images: :attr:`directory`'s image filenames.
        :returns: one ``(match, winner, variants)`` entry per recognized stem -- the winner being the
            file that would take the slot, the variants its same-stem losers -- ordered by the pattern
            that claimed the stem, then naturally, then by the name itself, so the directory's own
            listing order never decides anything.
        """
        groups: dict[str, list[str]] = {}
        matches: dict[str, ScreenshotSlotMatch] = {}
        for filename in images:
            if self.__is_numbered(filename):
                continue
            stem = Path(filename).stem
            match = self.__patterns.match(stem)
            if match is None:
                continue
            groups.setdefault(stem.lower(), []).append(filename)
            matches[stem.lower()] = match
        entries = [(matches[stem], *self.__narrowed(names)) for stem, names in groups.items()]
        return sorted(entries, key=lambda entry: (entry[0].pattern_index, natural_sort_key(entry[1]), entry[1]))

    def __narrowed(self, filenames: list[str]) -> tuple[str, list[str]]:
        """Pick which of one stem's files takes its slot: largest by pixel area, then the first
        extension in :data:`~rehuco_core.constants.IMAGE_EXTENSIONS`.

        One stem under several extensions is one picture stored twice, so the slot goes to the copy
        worth keeping rather than to whichever the directory listed first. The common case (a single
        file) returns outright without opening anything -- pixel-size ranking is only worth its I/O when
        there is actually more than one candidate to compare.

        :param filenames: one stem's files, in listing order.
        :returns: ``(winner, variants)``, the variants sorted by filename.
        """
        if len(filenames) == 1:
            return filenames[0], []
        ranked = sorted(filenames, key=self.__rank)
        return ranked[0], sorted(ranked[1:])

    def __rank(self, filename: str) -> tuple[int, int, str]:
        """How ``filename`` sorts among its same-stem siblings -- lowest wins.

        :param filename: the candidate filename.
        :returns: negated pixel area, the extension's index in
            :data:`~rehuco_core.constants.IMAGE_EXTENSIONS`, and the name itself as a last, always
            deterministic resort.
        """
        suffix = Path(filename).suffix.lower()
        return -self.__pixel_area(filename), IMAGE_EXTENSIONS.index(suffix), filename

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
