"""Tests for a completed `.tc` conversion's retained backups: what they amount to, and discarding them
(#190, #290, [[acquisition-tooling#convert-mechanics]])."""

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

import pytest
from pytest_mock import MockerFixture
from rehuco_core import (
    NoTrashBinError,
    RehuDocument,
    RehuFormatError,
    conversion_backups,
    discard_conversion_backups,
    is_conversion_backup,
    original_path,
)

DIRECTORY: Final = Path("/fake/tutorial")
REHU_PATH: Final = DIRECTORY / "info.rehu"

# what a keep-backups conversion of `info.tc` (two recognized screenshot slots) leaves behind
CONVERTED: Final = (
    "info.rehu",
    "info00.jpg",
    "info01.jpg",
    "info.tc.orig",
    "cover.jpg.orig",
    "sample-00.png.orig",
    "sample-01.jpg.orig",
)

BACKUPS: Final = (
    DIRECTORY / "cover.jpg.orig",
    DIRECTORY / "info.tc.orig",
    DIRECTORY / "sample-00.png.orig",
    DIRECTORY / "sample-01.jpg.orig",
)

BACKUP_SIZE: Final = 1000
"""What every mocked backup reports, so a total is a multiple of it."""

SEEDED_STAMP: Final = "2023-11-14T22:13:20Z"
"""What the conversion wrote into ``created``."""


def mock_environment(
    mocker: MockerFixture,
    *,
    listing: Sequence[str] = CONVERTED,
    load_side_effect: Any = None,
    iterdir_side_effect: Any = None,
) -> dict[str, Any]:
    """Mock the directory an inventory reads and every filesystem call it makes.

    :param mocker: pytest-mock fixture.
    :param listing: the filenames the resource's directory holds.
    :param load_side_effect: optional ``side_effect`` for the document read (e.g. an unreadable file).
    :param iterdir_side_effect: optional ``side_effect`` for the directory listing (e.g. an away mount).
    :returns: the created mocks, keyed by what they stand in for.
    """
    paths = [DIRECTORY / name for name in listing]
    mocker.patch.object(Path, "iterdir", autospec=True, side_effect=iterdir_side_effect, return_value=paths)
    mocker.patch.object(Path, "exists", autospec=True, side_effect=lambda self: self in paths)
    mock_stat = mocker.patch.object(Path, "stat", return_value=mocker.MagicMock(st_size=BACKUP_SIZE))
    mock_load = mocker.patch.object(
        RehuDocument, "load", side_effect=load_side_effect, return_value=mocker.MagicMock(created=SEEDED_STAMP)
    )
    mock_unlink = mocker.patch.object(Path, "unlink", autospec=True)
    return {"load": mock_load, "stat": mock_stat, "unlink": mock_unlink}


# region Inventory tests


def test_inventory_reports_what_the_backups_amount_to(mocker: MockerFixture) -> None:
    """The inventory names every backup and what they occupy, without touching disk state.

    **Test steps:**

    * mock a directory holding a completed keep-backups conversion
    * read the inventory
    * verify the backups and the total bytes, and that nothing was unlinked
    """
    mocks = mock_environment(mocker)

    inventory = conversion_backups(REHU_PATH)

    assert inventory.backups == BACKUPS
    assert inventory.total_bytes == BACKUP_SIZE * len(BACKUPS)
    mocks["unlink"].assert_not_called()


def test_inventory_over_an_unreadable_directory_reports_no_backups(mocker: MockerFixture) -> None:
    """A directory that cannot be listed -- an away mount -- reports no backups
    ([[mounts-and-storage#offline-mounts]]).

    **Test steps:**

    * mock ``iterdir`` raising
    * read the inventory
    * verify it holds no backups
    """
    mock_environment(mocker, iterdir_side_effect=OSError("mount is away"))

    inventory = conversion_backups(REHU_PATH)

    assert not inventory.backups


def test_the_conversion_date_is_the_rehus_created_stamp(mocker: MockerFixture) -> None:
    """A conversion mints ``created``, so it dates the conversion rather than the resource -- which is
    what a backups manager lists in its *converted* column (#193).

    **Test steps:**

    * mock a directory holding a completed keep-backups conversion
    * read the inventory
    * verify it reports the seeded stamp
    """
    mock_environment(mocker)

    assert conversion_backups(REHU_PATH).converted == SEEDED_STAMP


def test_an_absent_rehu_names_no_conversion_date(mocker: MockerFixture) -> None:
    """No ``.rehu`` means there is nothing to read the stamp off, so the date is empty rather than made
    up.

    **Test steps:**

    * mock a directory holding only the backups
    * read the inventory
    * verify the conversion date is empty
    """
    mock_environment(mocker, listing=("info.tc.orig", "cover.jpg.orig"), load_side_effect=FileNotFoundError)

    assert conversion_backups(REHU_PATH).converted == ""


@pytest.mark.parametrize("load_side_effect", [RehuFormatError("not JSON"), OSError("mount away")])
def test_an_unreadable_rehu_names_no_conversion_date(mocker: MockerFixture, load_side_effect: Exception) -> None:
    """A ``.rehu`` that will not read cannot vouch for a conversion date either, so it shows none rather
    than one it made up (#193).

    **Test steps:**

    * mock the document read failing
    * read the inventory
    * verify the conversion date is empty
    """
    mock_environment(mocker, load_side_effect=load_side_effect)

    assert conversion_backups(REHU_PATH).converted == ""


def test_a_tie_breaks_losers_count_as_dropped_screenshots(mocker: MockerFixture) -> None:
    """Every recognized legacy screenshot is backed up and only a slot's winner is installed, so the
    difference between the two counts *is* what the tie-break dropped -- the rows #193 exists to review.

    **Test steps:**

    * mock a conversion whose three recognized screenshots landed on two slots
    * read the inventory
    * verify it reports the one loser, without re-scanning for legacy names
    """
    mock_environment(mocker)

    assert conversion_backups(REHU_PATH).dropped_screenshots == 1


def test_a_conversion_that_installed_every_screenshot_dropped_none(mocker: MockerFixture) -> None:
    """No tie-break means every recognized screenshot was installed, so there is nothing to review -- and
    the non-image backups (the ``.tc`` itself) must not be miscounted as dropped screenshots.

    **Test steps:**

    * mock a conversion whose two recognized screenshots landed on two slots
    * read the inventory
    * verify nothing is reported as dropped
    """
    mock_environment(
        mocker, listing=("info.rehu", "info00.jpg", "info01.jpg", "info.tc.orig", "cover.jpg.orig", "file-1.png.orig")
    )

    assert conversion_backups(REHU_PATH).dropped_screenshots == 0


def test_a_conversion_with_no_image_backups_dropped_none(mocker: MockerFixture) -> None:
    """A conversion that backed up no image renamed its screenshots into their slots instead of copying
    them (#288), so no image backups here means nothing was dropped -- and there is nothing to scan for.

    **Test steps:**

    * mock a resource whose only backup is ``info.tc.orig``, beside two numbered screenshots
    * read the inventory
    * verify nothing is reported as dropped
    """
    mock_environment(mocker, listing=("info.rehu", "info00.jpg", "info01.jpg", "info.tc.orig"))

    assert conversion_backups(REHU_PATH).dropped_screenshots == 0


def test_a_backup_that_vanishes_mid_inventory_counts_as_no_bytes(mocker: MockerFixture) -> None:
    """A backup deleted between the listing and the measurement contributes nothing rather than failing
    the inventory -- the total is what a caller offers to reclaim, not an answer worth refusing over.

    **Test steps:**

    * mock the size of the second backup as unreadable
    * read the inventory
    * verify the total counts the remaining three and the backup is still listed
    """
    mocks = mock_environment(mocker)
    mocks["stat"].side_effect = [
        mocker.MagicMock(st_size=BACKUP_SIZE),
        OSError("vanished"),
        mocker.MagicMock(st_size=BACKUP_SIZE),
        mocker.MagicMock(st_size=BACKUP_SIZE),
    ]

    inventory = conversion_backups(REHU_PATH)

    assert inventory.total_bytes == BACKUP_SIZE * (len(BACKUPS) - 1)
    assert inventory.backups == BACKUPS


def test_a_backup_is_any_orig_sibling_spelled_exactly(mocker: MockerFixture) -> None:
    """The definition the inventory here and the content walk (#253) both read, pinned on names alone.

    **Any** ``.orig``, whatever it is a backup of -- a stem carries nothing tying a legacy ``cover.jpg``
    to its resource, which is why backups are enumerated per directory -- and matched exactly, so the
    walk skips precisely this set.

    **Test steps:**

    * ask the predicate about the names a conversion writes, names it never would, and one differing
      only in case
    * verify only the true ``.orig`` siblings answered yes
    """
    del mocker
    candidates = ["info.tc.orig", "cover.jpg.orig", "render.blend.orig", "info.tc", "info.orig.tc", "info.tc.ORIG"]

    assert [name for name in candidates if is_conversion_backup(name)] == [
        "info.tc.orig",
        "cover.jpg.orig",
        "render.blend.orig",
    ]


def test_a_path_that_is_not_a_backup_has_no_original(mocker: MockerFixture) -> None:
    """:func:`~rehuco_core.original_path` answers where a ``.orig`` sibling came from, so a path that is
    not one has no answer to give -- and inventing one (the path itself) would name a restore target
    that would overwrite a file nothing ever backed up.

    **Test steps:**

    * ask for the original of a plain filename
    * verify ``ValueError``
    """
    del mocker

    with pytest.raises(ValueError, match="not a .orig backup"):
        original_path(DIRECTORY / "info.tc")


# endregion

# region Discard tests


def test_discard_deletes_exactly_the_backups(mocker: MockerFixture) -> None:
    """Discarding makes the conversion permanent by deleting the ``.orig`` siblings and nothing else --
    the written ``.rehu`` and its screenshots stay.

    **Test steps:**

    * discard a completed keep-backups conversion's backups
    * verify exactly the backups were unlinked
    """
    mocks = mock_environment(mocker)

    discarded = discard_conversion_backups(REHU_PATH)

    assert discarded == BACKUPS
    assert [call.args[0] for call in mocks["unlink"].call_args_list] == list(BACKUPS)


def test_discard_goes_through_the_given_deleter(mocker: MockerFixture) -> None:
    """Each backup is handed to ``deleter``, not unlinked directly, so a caller's Recycle Bin choice
    reaches it (#298).

    **Test steps:**

    * discard with a recording deleter
    * verify it -- not ``Path.unlink`` -- was asked to delete exactly the backups
    """
    mocks = mock_environment(mocker)

    class RecordingDeleter:  # pylint: disable=too-few-public-methods
        """A `~rehuco_core.Deleter` that records what it was asked to delete instead of touching disk."""

        def __init__(self) -> None:
            self.deleted: list[Path] = []

        def delete(self, path: Path) -> None:
            """Record ``path`` rather than removing it."""
            self.deleted.append(path)

    deleter = RecordingDeleter()

    discarded = discard_conversion_backups(REHU_PATH, deleter=deleter)

    assert discarded == BACKUPS
    assert deleter.deleted == list(BACKUPS)
    mocks["unlink"].assert_not_called()


def test_a_deleter_that_cannot_reach_a_bin_stops_the_discard(mocker: MockerFixture) -> None:
    """A `NoTrashBinError` is not swallowed here -- discard is the whole point of the call, unlike a
    conversion's own end-of-the-line cleanup (#298).

    **Test steps:**

    * discard with a deleter that always refuses
    * verify the error propagates
    """
    mock_environment(mocker)

    class RefusingDeleter:  # pylint: disable=too-few-public-methods
        """A `~rehuco_core.Deleter` with no bin to reach, whatever it is handed."""

        def delete(self, path: Path) -> None:
            """Refuse ``path`` the way a Recycle-Bin deleter refuses an unreachable location."""
            raise NoTrashBinError(f"No Recycle Bin is available for {path.parent}")

    with pytest.raises(NoTrashBinError):
        discard_conversion_backups(REHU_PATH, deleter=RefusingDeleter())


# endregion
