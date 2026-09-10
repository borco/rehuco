"""What the images dock's *After conversion* column says about each pattern-matched image (#293).

The whole-directory ``.tc`` conversion (`rehuco_core.convert_tc`) either renames a pattern-matched image
to the number its own name already carries, or leaves it exactly as it was found -- for one of the
reasons `rehuco_core.tc_screenshots.TcScreenshotScanner` decides between (#288). This module turns that
same dry-run plan (`rehuco_core.scan_tc_screenshots`) into one
`~rehuco_agent.fields.image_scanner.AfterConversion` per image -- the name the file will have, and why
it keeps its own when it does -- so the column can never disagree with what Convert then does: it reads
the plan, it never re-decides anything the plan already decided.
"""

from pathlib import Path
from typing import Final

from rehuco_core import (
    MAX_SCREENSHOT_SLOT,
    ScreenshotNamePattern,
    ScreenshotSkipReason,
    TcScreenshotPlan,
    UnconvertedScreenshot,
    compiled_screenshot_name_patterns,
    scan_tc_screenshots,
)

from ..fields.image_scanner import AfterConversion


def scan_after_conversion(
    directory: Path, stem: str, patterns: tuple[ScreenshotNamePattern, ...]
) -> dict[str, AfterConversion]:
    """Scan ``directory`` and say what converting it would do to each pattern-matched image (#293).

    Composes `rehuco_core.scan_tc_screenshots` with :func:`after_conversion` into the one
    ``(directory, stem) -> {filename: outcome}`` shape
    `~rehuco_agent.documents.rehu_document_image_scanner.RehuDocumentImageScanner`'s other two listers
    already have, so the same pattern-binding seam
    (`~rehuco_agent.documents.rehu_document_model.RehuDocumentModel.__make_image_scanner`) installs all
    three the same way.

    :param directory: the resource's directory to scan.
    :param stem: the filename base the numbered set would share.
    :param patterns: the naming patterns to recognize, resolved by the caller -- this module never
        reads a setting.
    :returns: the mapping; see :func:`after_conversion`.
    """
    return after_conversion(scan_tc_screenshots(directory, stem, patterns), stem, patterns)


def after_conversion(
    plan: TcScreenshotPlan, stem: str, patterns: tuple[ScreenshotNamePattern, ...]
) -> dict[str, AfterConversion]:
    """What each image ``plan`` accounts for is once the conversion has run (#293).

    A renamed image becomes its ``<stem>NN`` name. A kept image keeps its own, and carries why, in the
    plan's own vocabulary and nothing else: its slot is taken -- by an earlier name (#288's pattern-order
    rule), or by an earlier extension of its own name (the larger one wins) -- or its own number is
    :data:`~rehuco_core.MAX_SCREENSHOT_SLOT` or above. No image is ever backed up to an ``.orig``
    ([[acquisition-tooling#tc-to-rehu]]), so no fourth outcome exists here.

    :param plan: the resource's dry-run screenshot plan (`rehuco_core.scan_tc_screenshots`) -- the same
        scan `rehuco_core.convert_tc` runs, so this is read from it rather than re-decided.
    :param stem: the filename base the numbered set would share (e.g. ``"info"``) -- what a renamed
        image's slot number is read against.
    :param patterns: the naming patterns ``plan`` was built from, matched again here only to recover the
        slot number a *kept* image's own name carries, which the plan does not restate.
    :returns: ``{filename: outcome}``, one entry per image ``plan`` mentions, renamed or kept.
    """
    return AfterConversionOutcomes(plan, stem, patterns).build()


# a real class rather than a module-private helper function beside the one above, for the reason the
# rest of the codebase keeps its own scan/plan logic in classes (`TcScreenshotScanner`,
# `TcConversionPlanner`) -- there is a second, genuinely private step (:meth:`__kept_reason`) here too
# pylint: disable-next=too-few-public-methods
class AfterConversionOutcomes:
    """Builds :func:`after_conversion`'s ``{filename: outcome}`` mapping for one plan.

    :param plan: the plan to describe; see :func:`after_conversion`.
    :param stem: the numbered set's filename base; see :func:`after_conversion`.
    :param patterns: the naming patterns the plan was built from; see :func:`after_conversion`.
    """

    def __init__(self, plan: TcScreenshotPlan, stem: str, patterns: tuple[ScreenshotNamePattern, ...]) -> None:
        self.__plan: Final = plan
        self.__winners_by_slot: Final = {
            int(Path(rename.new_name).stem[len(stem) :]): rename.source_filename for rename in plan.renames
        }
        self.__recognized: Final = compiled_screenshot_name_patterns(patterns)

    def build(self) -> dict[str, AfterConversion]:
        """Every image ``plan`` mentions, mapped to its outcome.

        :returns: ``{filename: outcome}``; see :func:`after_conversion`.
        """
        outcomes = {rename.source_filename: AfterConversion(rename.new_name) for rename in self.__plan.renames}
        outcomes.update(
            (image.filename, AfterConversion(image.filename, self.__kept_reason(image)))
            for image in self.__plan.unconverted
        )
        return outcomes

    def __kept_reason(self, image: UnconvertedScreenshot) -> str:
        """Why one kept image is left under its own name, in the plan's own vocabulary (#288).

        :param image: the kept image and its reason.
        :returns: the reason, never empty -- a kept image always has one.
        """
        match = self.__recognized.match(Path(image.filename).stem)
        if match is None:  # pragma: no cover -- defensive: the plan's own scan already matched this name
            return "kept"
        if image.reason is ScreenshotSkipReason.OUT_OF_RANGE:
            return f"number {match.slot} is ≥ {MAX_SCREENSHOT_SLOT}"
        winner = self.__winners_by_slot.get(match.slot)
        if winner is None:
            # the slot belongs to a `<stem>NN` file already on disk beside this `.tc` (a stalled prior
            # conversion, or one hand-created) rather than to anything `plan.renames` reports -- rare,
            # but real, so this names the slot rather than a filename the plan never told it
            return f"slot {match.slot:02d} already taken"
        if Path(winner).stem.lower() == Path(image.filename).stem.lower():
            return f"{winner} is larger"
        return f"slot {match.slot:02d} taken by {winner}"
