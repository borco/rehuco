"""Tests for the images dock's *After conversion* column outcomes (#293).

``after_conversion`` is read entirely from a `TcScreenshotPlan` built by hand here -- what
`rehuco_core.scan_tc_screenshots` itself decided is covered by its own tests
(``test_tc_screenshots.py``); these check only that this module turns a given plan into the right
name-and-reason per image. ``scan_after_conversion`` is checked separately, for composing the scan
with that step.
"""

from pathlib import Path

from pytest_mock import MockerFixture
from rehuco_agent.documents.tc_conversion_outcomes import after_conversion, scan_after_conversion
from rehuco_agent.fields.image_scanner import AfterConversion
from rehuco_core import (
    SCREENSHOT_NAME_PATTERNS,
    ScreenshotRename,
    ScreenshotSkipReason,
    TcScreenshotPlan,
    UnconvertedScreenshot,
)

STEM = "info"


def test_a_renamed_image_becomes_its_new_name_with_no_reason() -> None:
    """A row the plan renames is the ``<stem>NN`` name, and is not a kept one.

    **Test steps:**

    * build a plan renaming ``cover.jpg`` to ``info00.jpg``
    * read the outcomes
    * verify ``cover.jpg`` becomes exactly the new name, with nothing to explain
    """
    plan = TcScreenshotPlan(renames=(ScreenshotRename("info00.jpg", "cover.jpg"),))

    outcome = after_conversion(plan, STEM, SCREENSHOT_NAME_PATTERNS)["cover.jpg"]

    assert outcome == AfterConversion("info00.jpg")
    assert outcome.kept is False


def test_a_kept_image_keeps_its_own_name() -> None:
    """A row the plan leaves alone is its own name again -- the column says what the file *becomes*,
    and a kept file becomes nothing new.

    **Test steps:**

    * build a plan leaving ``sample-00.jpg`` as a collision
    * read the outcomes
    * verify its name is unchanged and it reads as kept
    """
    plan = TcScreenshotPlan(
        renames=(ScreenshotRename("info00.jpg", "cover.jpg"),),
        unconverted=(UnconvertedScreenshot("sample-00.jpg", ScreenshotSkipReason.COLLISION),),
    )

    outcome = after_conversion(plan, STEM, SCREENSHOT_NAME_PATTERNS)["sample-00.jpg"]

    assert outcome.name == "sample-00.jpg"
    assert outcome.kept is True


def test_a_cross_name_collision_names_the_slot_and_its_winner() -> None:
    """A kept image whose slot a *different* name's file took says which slot, and who took it.

    **Test steps:**

    * build a plan where ``cover.jpg`` wins slot 0 and ``sample-00.jpg`` is left as a collision
    * read the outcomes
    * verify ``sample-00.jpg``'s reason names the slot and ``cover.jpg`` by name
    """
    plan = TcScreenshotPlan(
        renames=(ScreenshotRename("info00.jpg", "cover.jpg"),),
        unconverted=(UnconvertedScreenshot("sample-00.jpg", ScreenshotSkipReason.COLLISION),),
    )

    outcomes = after_conversion(plan, STEM, SCREENSHOT_NAME_PATTERNS)

    assert outcomes["sample-00.jpg"].reason == "slot 00 taken by cover.jpg"


def test_a_same_stem_variant_names_the_larger_sibling() -> None:
    """A kept image that lost to a **larger extension of its own stem** says so by name, not by slot.

    **Test steps:**

    * build a plan where ``sample-00.jpg`` wins slot 0 and ``sample-00.png`` -- the same stem, a
      smaller extension -- is left as a collision
    * read the outcomes
    * verify ``sample-00.png``'s reason names ``sample-00.jpg`` as larger, with no slot number
    """
    plan = TcScreenshotPlan(
        renames=(ScreenshotRename("info00.jpg", "sample-00.jpg"),),
        unconverted=(UnconvertedScreenshot("sample-00.png", ScreenshotSkipReason.COLLISION),),
    )

    outcomes = after_conversion(plan, STEM, SCREENSHOT_NAME_PATTERNS)

    assert outcomes["sample-00.png"].reason == "sample-00.jpg is larger"


def test_an_out_of_range_image_names_its_own_number() -> None:
    """A kept image whose own number is at or past the highest slot says so, by that number.

    **Test steps:**

    * build a plan leaving ``image-101.jpg`` as out of range
    * read the outcomes
    * verify the reason names ``101``
    """
    plan = TcScreenshotPlan(unconverted=(UnconvertedScreenshot("image-101.jpg", ScreenshotSkipReason.OUT_OF_RANGE),))

    outcomes = after_conversion(plan, STEM, SCREENSHOT_NAME_PATTERNS)

    assert outcomes["image-101.jpg"].reason == "number 101 is ≥ 100"


def test_a_collision_against_a_slot_no_rename_reports_names_the_slot_alone() -> None:
    """A slot already spoken for by something outside the plan's own renames (a `<stem>NN` file
    already on disk) still gets a reason -- naming the slot, since the plan has no filename to offer.

    **Test steps:**

    * build a plan leaving ``cover.jpg`` (slot 0) as a collision with no rename claiming slot 0
    * read the outcomes
    * verify the reason names the slot without a filename
    """
    plan = TcScreenshotPlan(unconverted=(UnconvertedScreenshot("cover.jpg", ScreenshotSkipReason.COLLISION),))

    outcomes = after_conversion(plan, STEM, SCREENSHOT_NAME_PATTERNS)

    assert outcomes["cover.jpg"].reason == "slot 00 already taken"


def test_scan_after_conversion_composes_the_scan_with_the_outcome_step(mocker: MockerFixture) -> None:
    """``scan_after_conversion`` is `rehuco_core.scan_tc_screenshots` piped straight into
    :func:`after_conversion` -- one source, so this column can never disagree with what a whole
    directory's conversion (`rehuco_core.convert_tc`) then does.

    **Test steps:**

    * mock ``scan_tc_screenshots`` to return a canned plan
    * call ``scan_after_conversion``
    * verify the scan was asked with the same ``(directory, stem, patterns)``, and its plan is what the
      outcomes came from
    """
    plan = TcScreenshotPlan(renames=(ScreenshotRename("info00.jpg", "cover.jpg"),))
    scan = mocker.patch("rehuco_agent.documents.tc_conversion_outcomes.scan_tc_screenshots", return_value=plan)
    directory = Path("/fake")

    outcomes = scan_after_conversion(directory, STEM, SCREENSHOT_NAME_PATTERNS)

    scan.assert_called_once_with(directory, STEM, SCREENSHOT_NAME_PATTERNS)
    assert outcomes == {"cover.jpg": AfterConversion("info00.jpg")}
