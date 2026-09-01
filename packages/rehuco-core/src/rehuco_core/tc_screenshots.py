"""Legacy screenshot recognition for `.tc` conversion ([[acquisition-tooling#tc-to-rehu]]).

Scans a resource's directory for tc4-era screenshot naming schemes and assigns each recognized file a
fresh ``<stem>NN`` name, matching the reader convention `rehuco_core.rehu_screenshots.scan_rehu_screenshot_files`
already expects. Stays core-side and GUI-free: callers resolve ``stem`` however they need to (e.g. from
``RehuDocumentModel.current_name``) and pass it in as a plain string.
"""

import os
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final

from PIL import Image, UnidentifiedImageError

from .constants import IMAGE_EXTENSIONS

INDEX_PLACEHOLDER: Final = "#"
"""Marks where a number sits in a rule's ``rest`` template; a run of them is that number's minimum
zero-padded width, so ``##`` covers ``00``-``09``, ``10``-``99``, then ``100`` onwards
([[acquisition-tooling#screenshot-schemes]])."""


@dataclass(frozen=True, slots=True)
class LegacyScreenshotRule:
    """One legacy screenshot naming rule: a series' cover, and a template for everything after it.

    Two fields rather than one filename pattern, because a series is anchored by its **cover** and two
    rules can differ *only* there: an ``image-00``-first series and an ``image-01``-first one share the
    same ``image-##`` template, and no single filename tells them apart -- only which cover is present
    in the directory does ([[acquisition-tooling#screenshot-schemes]]).

    :ivar cover: the slot-0 filename stem, matched literally and case-insensitively.
    :ivar rest: the template the remaining files match, carrying exactly one run of
        :data:`INDEX_PLACEHOLDER` where their number sits.
    """

    cover: str
    rest: str


LEGACY_SCREENSHOT_RULES: Final = (
    LegacyScreenshotRule("00", "##"),
    LegacyScreenshotRule("sample-00", "sample-##"),
    LegacyScreenshotRule("image-00", "image-##"),
    LegacyScreenshotRule("image-01", "image-##"),
    LegacyScreenshotRule("file", "file(#)"),
    LegacyScreenshotRule("cover", "file-##"),
)
"""Default legacy screenshot naming rules, in the order they are tried
([[acquisition-tooling#screenshot-schemes]]) -- the tc4-era conventions this catalog actually holds.

What :func:`scan_tc_screenshots` and :func:`is_legacy_screenshot` fall back to when no set is given; the
agent's ``LegacyScreenshotsSettings`` is what makes the set the user's to change. **Order matters**: the
first rule whose cover is present in a directory assigns that directory's slots, which is the only thing
separating the two ``image-##`` rules from each other. The *tie-break* between files landing on one slot
-- largest pixel area, then ``.jpg``/``.jpeg``, then the alphabetically first name -- is not listed here
and is not the user's; it applies whatever this set says."""


class LegacyScreenshotRuleMatcher:
    """One :class:`LegacyScreenshotRule` with its ``rest`` template compiled once.

    :param rule: the rule to compile.
    :raises ValueError: ``cover`` is blank or itself holds :data:`INDEX_PLACEHOLDER`, or ``rest`` does
        not carry exactly one run of it. :class:`LegacyScreenshotRules` skips a rule that raises rather
        than letting one malformed setting abort a scan.
    """

    __RUN_RE: Final = re.compile(f"{re.escape(INDEX_PLACEHOLDER)}+")

    def __init__(self, rule: LegacyScreenshotRule) -> None:
        if not rule.cover or INDEX_PLACEHOLDER in rule.cover:
            raise ValueError(f"cover must be a non-empty literal stem: {rule.cover!r}")
        run = self.__RUN_RE.search(rule.rest)
        if run is None or len(run.group()) != rule.rest.count(INDEX_PLACEHOLDER):
            raise ValueError(f"rest must carry exactly one {INDEX_PLACEHOLDER!r} run: {rule.rest!r}")
        self.rule: Final = rule
        self.__cover: Final = rule.cover.lower()
        self.__width: Final = len(run.group())
        # the literal halves are escaped, so a template never authors a regex: `file(#)`'s parens are
        # parentheses, not a group, and a settings string can carry no backtracking cost
        self.__pattern: Final = re.compile(
            f"^{re.escape(rule.rest[: run.start()])}(\\d+){re.escape(rule.rest[run.end() :])}$",
            re.IGNORECASE,
        )

    def matches_cover(self, file_stem: str) -> bool:
        """Whether ``file_stem`` is this rule's cover -- its slot 0.

        :param file_stem: the filename without its extension.
        :returns: whether it matches, case-insensitively.
        """
        return file_stem.lower() == self.__cover

    def number(self, file_stem: str) -> int | None:
        """The number ``file_stem`` carries under this rule's ``rest`` template.

        The padding is enforced by re-rendering: a digit run counts only when zero-padding its value to
        the template's width reproduces it exactly, so ``##`` accepts ``09`` and ``100`` but rejects
        ``0100``, and ``#`` rejects ``01``.

        :param file_stem: the filename without its extension.
        :returns: the number, or ``None`` when the template does not match it.
        """
        match = self.__pattern.match(file_stem)
        if match is None:
            return None
        digits = match.group(1)
        value = int(digits)
        return value if digits == str(value).zfill(self.__width) else None

    def recognizes(self, file_stem: str) -> bool:
        """Whether this rule claims ``file_stem`` at all, as its cover or one of the rest.

        :param file_stem: the filename without its extension.
        :returns: whether the rule recognizes it.
        """
        return self.matches_cover(file_stem) or self.number(file_stem) is not None

    def assign(self, stems: dict[str, str], claimed: set[str]) -> dict[str, int]:
        """Assign slots to every unclaimed file this rule recognizes.

        The cover takes slot 0; the rest are ordered by **ascending number** and take slots 1, 2, 3, …
        in that order. The numbers are an ordering, not the slot index -- which is what lets an
        ``image-01`` cover be followed by ``image-02`` at slot 1, and ``file`` by ``file(2)`` likewise.
        Files sharing one number (the same name under two extensions) share one slot.

        :param stems: ``{filename: stem}`` for the directory's recognized images.
        :param claimed: filenames an earlier rule already took, left alone here.
        :returns: ``{filename: slot}`` for the files this rule takes.
        """
        covers: list[str] = []
        by_number: dict[int, list[str]] = {}
        for filename, stem in stems.items():
            if filename in claimed:
                continue
            if self.matches_cover(stem):
                covers.append(filename)
                continue
            number = self.number(stem)
            if number is not None:
                by_number.setdefault(number, []).append(filename)
        slots = dict.fromkeys(covers, 0)
        for slot, number in enumerate(sorted(by_number), start=1):
            for filename in by_number[number]:
                slots[filename] = slot
        return slots


class LegacyScreenshotRules:
    """An ordered legacy screenshot rule set, compiled once ([[acquisition-tooling#screenshot-schemes]]).

    **Selection is a question about a directory, not a name.** The winning rule is the first one whose
    cover file is present; it assigns the slots. A file the winner does not recognize falls to the first
    *other* rule that does, folding into that rule's slot as a losing variant -- which is what keeps a
    thumbnail ``cover.jpg`` paired with the full-size ``sample-00.jpg`` it duplicates, so the tie-break
    still picks between them and a description reference to either still lands on the new name. When no
    rule's cover is present at all -- a series whose cover was deleted -- every rule simply participates
    in list order.

    :param rules: the rules, in the order they are tried; malformed ones are skipped.
    """

    def __init__(self, rules: Sequence[LegacyScreenshotRule] = LEGACY_SCREENSHOT_RULES) -> None:
        matchers: list[LegacyScreenshotRuleMatcher] = []
        for rule in rules:
            try:
                matchers.append(LegacyScreenshotRuleMatcher(rule))
            except ValueError:
                continue
        self.__matchers: Final = tuple(matchers)

    def recognizes(self, file_stem: str) -> bool:
        """Whether any rule claims ``file_stem``.

        Answerable from a name alone, unlike a slot: this is the classification the content walk asks
        for, which has no directory to rank (#250).

        :param file_stem: the filename without its extension.
        :returns: whether some rule recognizes it.
        """
        return any(matcher.recognizes(file_stem) for matcher in self.__matchers)

    def group_by_slot(self, filenames: Sequence[str]) -> dict[int, list[str]]:
        """Classify one directory's recognized images into their slots.

        :param filenames: the directory's image filenames, in listing order.
        :returns: ``{slot: [filenames]}``, each slot's candidates back in listing order.
        """
        stems = {filename: Path(filename).stem for filename in filenames}
        listing_order = {filename: index for index, filename in enumerate(filenames)}
        slots: dict[int, list[str]] = {}
        claimed: set[str] = set()
        for matcher in self.__winner_first(stems):
            for filename, slot in matcher.assign(stems, claimed).items():
                slots.setdefault(slot, []).append(filename)
                claimed.add(filename)
        for candidates in slots.values():
            candidates.sort(key=lambda filename: listing_order[filename])
        return slots

    def __winner_first(self, stems: dict[str, str]) -> tuple[LegacyScreenshotRuleMatcher, ...]:
        """Order the rules for assignment: the winning one, then the rest in list order.

        :param stems: ``{filename: stem}`` for the directory's recognized images.
        :returns: the matchers to assign with, winner first; the declared order when no cover is present.
        """
        for index, matcher in enumerate(self.__matchers):
            if any(matcher.matches_cover(stem) for stem in stems.values()):
                return (matcher, *self.__matchers[:index], *self.__matchers[index + 1 :])
        return self.__matchers


@lru_cache(maxsize=8)
def compiled_legacy_screenshot_rules(rules: tuple[LegacyScreenshotRule, ...]) -> LegacyScreenshotRules:
    """Compile ``rules`` once and reuse the result.

    Recognition is asked per *file* by walks that visit thousands of them
    (:mod:`rehuco_core.rehu_content_files`), so compiling a rule set on every question would pay for the
    same regexes over and over. Cached on the rule tuple itself, which is frozen and hashable.

    :param rules: the rule set, as a tuple.
    :returns: the compiled set.
    """
    return LegacyScreenshotRules(rules)


def legacy_screenshot_rules_state(rules: tuple[LegacyScreenshotRule, ...]) -> list[list[str]]:
    """Write a rule set down as plain data a saved job can carry
    ([[appendices.task-queue#lifetime]]).

    :param rules: the rule set to serialize.
    :returns: one ``[cover, rest]`` pair per rule, in order.
    """
    return [[rule.cover, rule.rest] for rule in rules]


def legacy_screenshot_rules_from_state(state: object) -> tuple[LegacyScreenshotRule, ...] | None:
    """Read a rule set back out of a saved job's state, defensively.

    :param state: whatever :func:`legacy_screenshot_rules_state` wrote, as read back.
    :returns: the rules, or ``None`` when the state is missing or malformed -- which leaves the caller
        on its default rather than on a half-read set.
    """
    if not isinstance(state, list):
        return None
    rules: list[LegacyScreenshotRule] = []
    for pair in state:
        if not isinstance(pair, list) or len(pair) != 2 or not all(isinstance(field, str) for field in pair):
            return None
        rules.append(LegacyScreenshotRule(pair[0], pair[1]))
    return tuple(rules)


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
    directory: Path, stem: str, rules: tuple[LegacyScreenshotRule, ...] = LEGACY_SCREENSHOT_RULES
) -> list[ScreenshotRename]:
    """Scan ``directory`` for tc4 legacy screenshot files and assign each recognized one a new name.

    :param directory: the resource's directory to scan.
    :param stem: the new filename base (e.g. ``"info"`` for a directory-scoped resource, or the file
        stem for a standalone one).
    :param rules: the naming rules to recognize, in the order they are tried, resolved by the caller --
        core never reads a setting.
    :returns: one :class:`ScreenshotRename` per recognized slot, sorted by slot index.
    """
    return TcScreenshotScanner(directory, stem, rules).scan()


def scan_tc_screenshot_files(
    directory: Path, stem: str, rules: tuple[LegacyScreenshotRule, ...] = LEGACY_SCREENSHOT_RULES
) -> list[Path]:
    """List each recognized legacy slot's current (pre-conversion) winner file.

    The reader counterpart of :func:`scan_tc_screenshots`: where that returns the full rename *plan*
    (consumed by conversion), this returns just each slot winner's current path -- what the lightbox
    shows for a ``.tc`` resource before it is converted. Shares the ``(directory, stem)`` signature of
    `rehuco_core.rehu_screenshots.scan_rehu_screenshot_files` so either can serve as a screenshot lister,
    though ``stem`` only feeds the (here-discarded) rename plan and does not affect the returned paths.

    :param directory: the resource's directory to scan.
    :param stem: the new filename base, passed through to the underlying scan.
    :param rules: the naming rules to recognize; see :func:`scan_tc_screenshots`. Defaulted so this
        still matches the two-argument lister signature its counterpart is chosen against.
    :returns: each slot winner's absolute path, sorted by slot index.
    """
    return [directory / rename.source_filename for rename in scan_tc_screenshots(directory, stem, rules)]


def is_legacy_screenshot(filename: str, rules: tuple[LegacyScreenshotRule, ...] = LEGACY_SCREENSHOT_RULES) -> bool:
    """Whether ``filename`` is one of tc4's screenshot names -- a slot winner or a losing variant.

    The classification alone, with none of the ranking: this reads a name and opens nothing, where
    :func:`scan_tc_screenshots` compares pixel dimensions to decide which of several files claims a slot.

    Asked by the content walk (:mod:`rehuco_core.rehu_content_files`), which excludes a legacy record's
    screenshots the way it excludes an ``infoNN.jpg`` beside an ``info.rehu`` (#250). Answering here
    rather than restating the schemes there is what keeps the set that walk skips identical to the set
    :func:`~rehuco_core.originals_to_back_up` renames aside -- *every* recognized image, winners and
    losers alike -- so a directory's content is the same set before and after it is converted.

    :param filename: a file's name, not its path.
    :param rules: the naming rules to recognize; see :func:`scan_tc_screenshots`.
    :returns: whether it is a recognized legacy screenshot.
    """
    stem, suffix = os.path.splitext(filename)
    return suffix.lower() in IMAGE_EXTENSIONS and compiled_legacy_screenshot_rules(rules).recognizes(stem)


# one public entry point, because a scan is one operation: the classification half moved to
# LegacyScreenshotRules when the rules became the caller's (#53), leaving this class the ranking and
# the naming, which nothing asks for separately
# pylint: disable-next=too-few-public-methods
class TcScreenshotScanner:
    """Recognizes tc4's legacy screenshot naming schemes in one directory ([[acquisition-tooling#tc-to-rehu]]).

    Each rule is a series: a cover and a template for the files after it
    (:class:`LegacyScreenshotRule`). The first rule whose cover is present in the directory assigns the
    slots, and files it does not recognize fall to the other rules as losing variants -- see
    :class:`LegacyScreenshotRules`, which is where that selection lives.

    When more than one recognized file lands on the same index (most commonly a thumbnail variant
    tying with a full-size one, but not limited to that pairing), the winner is narrowed by, in
    order: pixel dimensions (largest kept), then ``.jpg``/``.jpeg`` preferred over any other
    extension (only narrows further on an exact dimension tie), then the alphabetically first
    filename (a last-resort deterministic tiebreak, only reached if both of the above still tie).

    :param directory: the resource's directory to scan.
    :param stem: the new filename base (e.g. ``"info"`` or a file stem).
    :param rules: the naming rules to recognize, in the order they are tried, resolved by the caller --
        core never reads a setting.
    """

    __PREFERRED_EXTENSIONS: Final = (".jpg", ".jpeg")

    def __init__(
        self, directory: Path, stem: str, rules: tuple[LegacyScreenshotRule, ...] = LEGACY_SCREENSHOT_RULES
    ) -> None:
        self.__directory: Final = directory
        self.__stem: Final = stem
        self.__rules: Final = compiled_legacy_screenshot_rules(rules)

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

        Deferred whole -- not per file -- to :meth:`LegacyScreenshotRules.group_by_slot`, because which
        rule applies is decided by the directory's *set* of names rather than by any one of them.

        :returns: ``{slot_index: [filenames]}``, filenames in directory-listing order.
        """
        return self.__rules.group_by_slot(self.__recognized_images())

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
