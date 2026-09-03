"""Tests for renumbering a resource's screenshots on disk ([[data-model#image-meanings]], #72)."""

from pathlib import Path
from typing import Final

import pytest
from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_core import plan_screenshot_renumbering, renumber_screenshots
from rehuco_core.rehu_screenshot_ordering import TEMP_SUFFIX

DIRECTORY: Final = Path("/fake/tutorial")
STEM: Final = "info"


# region Renames recorder


class Renames:
    """Records every ``Path.replace`` the renumbering makes, without a filesystem behind it.

    The renumbering's whole contract is *which* renames it issues and *in what order* -- parking
    every mover before any of them claims a slot -- so recording the calls says more than inspecting
    a directory afterwards would, and says it without one.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail_on: str | None = None
        """The target name whose rename raises, standing in for a disk that refused it."""
        self.fail_unparking = False
        """Refuse every move *out* of a parked name -- so the parks land, the first claim fails, and
        the rollback that follows fails too."""

    def replace(self, source: Path, target: Path) -> Path:
        """Record one rename, or raise when the test asked this target to fail.

        :param source: the path being renamed, bound as ``self`` by the patched method.
        :param target: where it is going.
        :returns: the target, as :meth:`pathlib.Path.replace` does.
        :raises OSError: when ``target`` is the one the test declared unwritable.
        """
        if (self.fail_on is not None and target.name == self.fail_on) or (
            self.fail_unparking and source.name.endswith(TEMP_SUFFIX)
        ):
            raise OSError("refused")
        self.calls.append((source.name, target.name))
        return target

    @property
    def parked(self) -> list[tuple[str, str]]:
        """Only the calls that parked a file under the temporary suffix."""
        return [call for call in self.calls if call[1].endswith(TEMP_SUFFIX)]

    @property
    def claimed(self) -> list[tuple[str, str]]:
        """Only the calls that moved a parked file on to its slot."""
        return [call for call in self.calls if call[0].endswith(TEMP_SUFFIX)]


@fixture
def renames(mocker: MockerFixture) -> Renames:
    """Patch ``Path.replace`` to record instead of touching the disk.

    :param mocker: pytest-mock fixture.
    :returns: the recorder every rename lands in.
    """
    recorder = Renames()
    mocker.patch.object(Path, "replace", autospec=True, side_effect=recorder.replace)
    return recorder


# endregion

# region plan_screenshot_renumbering tests


def test_a_set_already_in_its_slots_needs_no_renames() -> None:
    """A canonical, gap-free set plans nothing -- the common case costs no disk writes.

    **Test steps:**

    * plan the order a zero-based set is already in
    * verify the plan is empty
    """
    ordered = [DIRECTORY / "info00.jpg", DIRECTORY / "info01.png"]

    assert not plan_screenshot_renumbering(STEM, ordered)


def test_swapping_two_screenshots_renames_both() -> None:
    """A move is a rename: the pair trade slot numbers, each keeping its own extension.

    **Test steps:**

    * plan the order with the second screenshot moved above the first
    * verify each took the other's number and kept its own extension
    """
    ordered = [DIRECTORY / "info01.png", DIRECTORY / "info00.jpg"]

    assert plan_screenshot_renumbering(STEM, ordered) == {"info01.png": "info00.png", "info00.jpg": "info01.jpg"}


def test_a_one_based_set_is_renumbered_from_zero() -> None:
    """The canonical set starts at 00, so a leading gap closes like any other (#72).

    **Test steps:**

    * plan the order a one-based set is already in
    * verify every file moves down one slot
    """
    ordered = [DIRECTORY / "info01.jpg", DIRECTORY / "info02.jpg", DIRECTORY / "info03.jpg"]

    assert plan_screenshot_renumbering(STEM, ordered) == {
        "info01.jpg": "info00.jpg",
        "info02.jpg": "info01.jpg",
        "info03.jpg": "info02.jpg",
    }


def test_a_dropped_screenshot_pulls_every_later_one_down() -> None:
    """Deleting one closes the gap it left: the survivors are passed, and renumber onto its slot.

    This is the worked case from #72 -- ``info00`` removed, so ``01/02/03`` become ``00/01/02``.

    **Test steps:**

    * plan the order of the survivors of a four-screenshot set whose first was removed
    * verify each moved down exactly one slot
    """
    survivors = [DIRECTORY / "info01.jpg", DIRECTORY / "info02.jpg", DIRECTORY / "info03.jpg"]

    assert plan_screenshot_renumbering(STEM, survivors) == {
        "info01.jpg": "info00.jpg",
        "info02.jpg": "info01.jpg",
        "info03.jpg": "info02.jpg",
    }


def test_only_the_screenshots_after_a_hole_move() -> None:
    """Files already in the right slot are left alone -- a delete rewrites the tail, not the set.

    **Test steps:**

    * plan the survivors of a set whose *second* screenshot was removed
    * verify the first is untouched and only the tail moves
    """
    survivors = [DIRECTORY / "info00.jpg", DIRECTORY / "info02.jpg", DIRECTORY / "info03.jpg"]

    assert plan_screenshot_renumbering(STEM, survivors) == {
        "info02.jpg": "info01.jpg",
        "info03.jpg": "info02.jpg",
    }


def test_an_empty_set_plans_nothing() -> None:
    """A resource whose last screenshot was just deleted has nothing left to renumber.

    **Test steps:**

    * plan an empty order
    * verify the plan is empty
    """
    assert not plan_screenshot_renumbering(STEM, [])


# endregion

# region renumber_screenshots tests


def test_every_mover_is_parked_before_any_claims_its_slot(renames: Renames) -> None:
    """Two passes, not one: nothing lands in a slot while another file still holds it (#72).

    A swap has each file's target occupied by the other and a rotation has every target occupied, so
    a single pass would need an ordering that does not exist. Parking first removes the question.

    **Test steps:**

    * renumber a swapped pair
    * verify both parks happen before either claim
    """
    ordered = [DIRECTORY / "info01.png", DIRECTORY / "info00.jpg"]

    renumber_screenshots(DIRECTORY, STEM, ordered)

    assert renames.parked == [
        ("info01.png", "info01.png" + TEMP_SUFFIX),
        ("info00.jpg", "info00.jpg" + TEMP_SUFFIX),
    ]
    assert renames.claimed == [
        ("info00.jpg" + TEMP_SUFFIX, "info01.jpg"),
        ("info01.png" + TEMP_SUFFIX, "info00.png"),
    ]


def test_renumbering_reports_what_it_renamed(renames: Renames) -> None:
    """The old-to-new mapping comes back, so a caller holding names can follow them (#72).

    A document's hidden-screenshot list is filenames, not paths, and would otherwise point at names
    that no longer exist the moment a screenshot moves.

    **Test steps:**

    * renumber a swapped pair
    * verify the reported mapping names both moves
    """
    del renames
    ordered = [DIRECTORY / "info01.png", DIRECTORY / "info00.jpg"]

    assert renumber_screenshots(DIRECTORY, STEM, ordered) == {
        "info01.png": "info00.png",
        "info00.jpg": "info01.jpg",
    }


def test_a_set_already_in_order_touches_the_disk_not_at_all(renames: Renames) -> None:
    """Nothing to renumber means no writes -- opening the editor must not rewrite the directory.

    **Test steps:**

    * renumber a set already in its slots
    * verify no rename was issued
    """
    renumber_screenshots(DIRECTORY, STEM, [DIRECTORY / "info00.jpg", DIRECTORY / "info01.png"])

    assert renames.calls == []


def test_a_rotation_renumbers_without_any_file_overwriting_another(renames: Renames) -> None:
    """Every file in a three-way rotation moves, and each lands only after all three are parked.

    **Test steps:**

    * renumber a set rotated by one
    * verify all three parks precede all three claims
    """
    ordered = [DIRECTORY / "info02.jpg", DIRECTORY / "info00.jpg", DIRECTORY / "info01.jpg"]

    renumber_screenshots(DIRECTORY, STEM, ordered)

    assert len(renames.parked) == 3
    assert len(renames.claimed) == 3
    assert renames.calls[:3] == renames.parked


def test_a_failed_rename_puts_every_parked_file_back(renames: Renames) -> None:
    """A refused rename rolls back rather than leaving a resource half renumbered (#72).

    Half a renumbering is worse than none: the numbering *is* the order, so a screenshot left in
    another's slot is a reordering nobody asked for and nothing records what it was.

    **Test steps:**

    * refuse the first claim of a swap, then renumber
    * verify the error surfaces and both parked files were put back where they came from
    """
    renames.fail_on = "info01.jpg"
    ordered = [DIRECTORY / "info01.png", DIRECTORY / "info00.jpg"]

    with pytest.raises(OSError, match="refused"):
        renumber_screenshots(DIRECTORY, STEM, ordered)

    assert renames.calls[-2:] == [
        ("info00.jpg" + TEMP_SUFFIX, "info00.jpg"),
        ("info01.png" + TEMP_SUFFIX, "info01.png"),
    ]


def test_a_rollback_that_also_fails_still_raises_the_original_error(renames: Renames) -> None:
    """The error the caller sees is the one that explains what happened, not the cleanup's.

    **Test steps:**

    * refuse every move out of a parked name, so the claim and each rollback both fail
    * verify the parks happened, and the original refusal is what propagates
    """
    renames.fail_unparking = True
    ordered = [DIRECTORY / "info01.png", DIRECTORY / "info00.jpg"]

    with pytest.raises(OSError, match="refused"):
        renumber_screenshots(DIRECTORY, STEM, ordered)

    assert len(renames.parked) == 2
    assert not renames.claimed


# endregion
