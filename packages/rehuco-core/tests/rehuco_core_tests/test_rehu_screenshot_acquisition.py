"""Tests for writing a newly-acquired image into a resource's ``<stem>NN`` set (#73)."""

from pathlib import Path
from typing import Final

import pytest
from pytest_mock import MockerFixture
from rehuco_core.rehu_screenshot_acquisition import (
    MAX_BACKUP_ATTEMPTS,
    save_screenshot,
    screenshot_backup_path,
)
from rehuco_core.tc_screenshots import MAX_SCREENSHOT_SLOT

DIRECTORY: Final = Path("/fake/tutorial")
STEM: Final = "info"


# region save_screenshot


def test_a_plain_drop_takes_the_slot_one_past_the_highest(mocker: MockerFixture) -> None:
    """``slot=None`` numbers the next new screenshot one past the current highest (#73).

    **Test steps:**

    * scan reports ``info00``/``info01`` already present
    * save a new screenshot with no slot given
    * verify it landed at ``info02``
    """
    mocker.patch(
        "rehuco_core.rehu_screenshot_acquisition.scan_rehu_screenshot_files",
        return_value=[DIRECTORY / "info00.jpg", DIRECTORY / "info01.png"],
    )
    mocker.patch.object(Path, "exists", return_value=False)
    write = mocker.patch.object(Path, "open", mocker.mock_open())

    result = save_screenshot(DIRECTORY, STEM, b"data", ".jpg")

    assert result == DIRECTORY / "info02.jpg"
    write.assert_called_once_with("xb")


def test_an_empty_set_starts_at_00(mocker: MockerFixture) -> None:
    """A resource with no screenshots yet starts numbering from ``00`` (#73).

    **Test steps:**

    * scan reports no existing screenshots
    * save a new screenshot with no slot given
    * verify it landed at ``info00``
    """
    mocker.patch("rehuco_core.rehu_screenshot_acquisition.scan_rehu_screenshot_files", return_value=[])
    mocker.patch.object(Path, "exists", return_value=False)
    mocker.patch.object(Path, "open", mocker.mock_open())

    result = save_screenshot(DIRECTORY, STEM, b"data", ".jpg")

    assert result == DIRECTORY / "info00.jpg"


def test_a_full_set_refuses_a_plain_drop(mocker: MockerFixture) -> None:
    """A numbered set already at its ceiling has no next slot to hand a plain drop (#73).

    **Test steps:**

    * scan reports the set already at its highest slot
    * save a new screenshot with no slot given
    * verify a ``ValueError`` was raised, and nothing was opened for writing
    """
    mocker.patch(
        "rehuco_core.rehu_screenshot_acquisition.scan_rehu_screenshot_files",
        return_value=[DIRECTORY / f"info{MAX_SCREENSHOT_SLOT - 1:02d}.jpg"],
    )
    mocker.patch.object(Path, "exists", return_value=False)
    write = mocker.patch.object(Path, "open", mocker.mock_open())

    with pytest.raises(ValueError, match="full"):
        save_screenshot(DIRECTORY, STEM, b"data", ".jpg")

    write.assert_not_called()


def test_a_legacy_tc_sibling_refuses_the_whole_write(mocker: MockerFixture) -> None:
    """A directory that still holds ``info.tc`` is refused outright, before any slot is even computed (#73).

    **Test steps:**

    * report the legacy ``.tc`` file present
    * save a new screenshot
    * verify a ``PermissionError`` was raised and nothing was scanned or opened
    """
    mocker.patch.object(Path, "exists", return_value=True)
    scan = mocker.patch("rehuco_core.rehu_screenshot_acquisition.scan_rehu_screenshot_files")
    write = mocker.patch.object(Path, "open", mocker.mock_open())

    with pytest.raises(PermissionError):
        save_screenshot(DIRECTORY, STEM, b"data", ".jpg")

    scan.assert_not_called()
    write.assert_not_called()


def test_an_explicit_free_slot_writes_straight_through(mocker: MockerFixture) -> None:
    """An explicit slot with nothing occupying it writes with no rename involved (#73).

    **Test steps:**

    * scan reports only ``info00`` present
    * save a new screenshot at explicit slot ``1``
    * verify it landed at ``info01`` with no rename
    """
    mocker.patch(
        "rehuco_core.rehu_screenshot_acquisition.scan_rehu_screenshot_files",
        return_value=[DIRECTORY / "info00.jpg"],
    )
    mocker.patch.object(Path, "exists", return_value=False)
    rename = mocker.patch.object(Path, "rename")
    mocker.patch.object(Path, "open", mocker.mock_open())

    result = save_screenshot(DIRECTORY, STEM, b"data", ".jpg", slot=1)

    assert result == DIRECTORY / "info01.jpg"
    rename.assert_not_called()


def test_an_explicit_occupied_slot_backs_the_occupant_up_first(mocker: MockerFixture) -> None:
    """Writing into an occupied slot renames the file already there to its backup name first, never
    overwriting it outright (#73).

    **Test steps:**

    * scan reports ``info01.jpg`` occupying the target slot
    * save a new screenshot at that slot
    * verify the occupant was renamed to its ``.orig`` backup before the new bytes were written
    """
    mocker.patch(
        "rehuco_core.rehu_screenshot_acquisition.scan_rehu_screenshot_files",
        return_value=[DIRECTORY / "info01.jpg"],
    )
    mocker.patch.object(Path, "exists", return_value=False)
    rename = mocker.patch.object(Path, "rename")
    mocker.patch.object(Path, "open", mocker.mock_open())

    result = save_screenshot(DIRECTORY, STEM, b"data", ".png", slot=1)

    assert result == DIRECTORY / "info01.png"
    rename.assert_called_once_with(DIRECTORY / "info01.jpg.orig")


def test_an_occupant_with_a_different_extension_is_still_backed_up(mocker: MockerFixture) -> None:
    """The occupant's own extension, not the incoming one, is what gets backed up (#73).

    **Test steps:**

    * scan reports ``info02.png`` occupying the slot a ``.jpg`` is about to claim
    * save the new ``.jpg`` at that slot
    * verify the ``.png`` occupant, not a ``.jpg``, was renamed to its backup
    """
    mocker.patch(
        "rehuco_core.rehu_screenshot_acquisition.scan_rehu_screenshot_files",
        return_value=[DIRECTORY / "info02.png"],
    )
    mocker.patch.object(Path, "exists", return_value=False)
    rename = mocker.patch.object(Path, "rename")
    mocker.patch.object(Path, "open", mocker.mock_open())

    save_screenshot(DIRECTORY, STEM, b"data", ".jpg", slot=2)

    rename.assert_called_once_with(DIRECTORY / "info02.png.orig")


def test_the_occupant_match_is_case_insensitive(mocker: MockerFixture) -> None:
    """A scan that lists an occupant under a different case still gets recognized and backed up (#73):
    the same case-insensitive matching :func:`~rehuco_core.scan_rehu_screenshot_files` itself uses.

    **Test steps:**

    * scan reports ``INFO01.JPG`` (upper-cased) occupying the slot
    * save a new screenshot at that slot
    * verify the differently-cased occupant was recognized and backed up
    """
    mocker.patch(
        "rehuco_core.rehu_screenshot_acquisition.scan_rehu_screenshot_files",
        return_value=[DIRECTORY / "INFO01.JPG"],
    )
    mocker.patch.object(Path, "exists", return_value=False)
    rename = mocker.patch.object(Path, "rename")
    mocker.patch.object(Path, "open", mocker.mock_open())

    save_screenshot(DIRECTORY, STEM, b"data", ".jpg", slot=1)

    rename.assert_called_once_with(DIRECTORY / "INFO01.JPG.orig")


def test_an_explicit_slot_at_or_past_the_ceiling_is_refused(mocker: MockerFixture) -> None:
    """An explicit slot is range-checked the same way the auto-picked one is (#73): a scrape result's
    own numbering could otherwise land outside the two-digit ``<stem>NN`` scheme entirely.

    **Test steps:**

    * save a new screenshot at an explicit slot equal to the ceiling
    * verify a ``ValueError`` was raised and nothing was opened for writing
    """
    mocker.patch("rehuco_core.rehu_screenshot_acquisition.scan_rehu_screenshot_files", return_value=[])
    mocker.patch.object(Path, "exists", return_value=False)
    write = mocker.patch.object(Path, "open", mocker.mock_open())

    with pytest.raises(ValueError, match="out of range"):
        save_screenshot(DIRECTORY, STEM, b"data", ".jpg", slot=MAX_SCREENSHOT_SLOT)

    write.assert_not_called()


# endregion

# region screenshot_backup_path


def test_the_plain_orig_name_is_used_when_free(mocker: MockerFixture) -> None:
    """The plain ``.orig`` name is tried first, and used when nothing already holds it.

    **Test steps:**

    * report no existing file at the plain ``.orig`` name
    * ask for a backup path
    * verify the plain name came back
    """
    mocker.patch.object(Path, "exists", return_value=False)

    assert screenshot_backup_path(DIRECTORY / "info00.jpg") == DIRECTORY / "info00.jpg.orig"


def test_a_taken_plain_name_falls_back_to_a_counter(mocker: MockerFixture) -> None:
    """A collision on the plain name inserts a counter between the stem and the extension.

    **Test steps:**

    * report the plain ``.orig`` name taken, the ``.2.`` counter free
    * ask for a backup path
    * verify the ``.2.`` counter name came back
    """
    mocker.patch.object(Path, "exists", side_effect=[True, False])

    assert screenshot_backup_path(DIRECTORY / "info00.jpg") == DIRECTORY / "info00.2.jpg.orig"


def test_the_next_counter_is_tried_after_that(mocker: MockerFixture) -> None:
    """A second collision moves on to the next counter.

    **Test steps:**

    * report the plain name and the ``.2.`` counter both taken, ``.3.`` free
    * ask for a backup path
    * verify the ``.3.`` counter name came back
    """
    mocker.patch.object(Path, "exists", side_effect=[True, True, False])

    assert screenshot_backup_path(DIRECTORY / "info00.jpg") == DIRECTORY / "info00.3.jpg.orig"


def test_exhausting_every_counter_raises(mocker: MockerFixture) -> None:
    """A directory stuck with every counter already taken raises rather than looping forever.

    **Test steps:**

    * report every candidate name taken
    * ask for a backup path
    * verify ``FileExistsError`` was raised
    """
    mocker.patch.object(Path, "exists", return_value=True)

    with pytest.raises(FileExistsError, match=str(MAX_BACKUP_ATTEMPTS)):
        screenshot_backup_path(DIRECTORY / "info00.jpg")


# endregion
