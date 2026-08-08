"""Tests for undoing a completed `.tc` conversion from its retained backups (#190,
[[acquisition-tooling#convert-mechanics]])."""

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

import pytest
from pytest_mock import MockerFixture
from rehuco_core import (
    RehuDocument,
    RehuFormatError,
    conversion_backups,
    discard_conversion_backups,
    is_conversion_backup,
    original_path,
    revert_conversion,
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

RESTORES: Final = (
    DIRECTORY / "cover.jpg",
    DIRECTORY / "info.tc",
    DIRECTORY / "sample-00.png",
    DIRECTORY / "sample-01.jpg",
)

WRITTEN: Final = (REHU_PATH, DIRECTORY / "info00.jpg", DIRECTORY / "info01.jpg")

BACKUP_SIZE: Final = 1000
"""What every mocked backup reports, so a total is a multiple of it."""

SEEDED_STAMP: Final = "2023-11-14T22:13:20Z"
"""What the conversion wrote into both ``created`` and ``updated``."""


def staged_path(written: Path) -> Path:
    """Where a revert moves ``written`` aside while it runs."""
    return written.with_name(written.name + ".reverting")


def mock_environment(
    mocker: MockerFixture,
    *,
    listing: Sequence[str] = CONVERTED,
    updated: str = SEEDED_STAMP,
    load_side_effect: Any = None,
    iterdir_side_effect: Any = None,
) -> dict[str, Any]:
    """Mock the directory a revert reads and every filesystem call it makes.

    :param mocker: pytest-mock fixture.
    :param listing: the filenames the resource's directory holds.
    :param updated: the ``.rehu``'s ``updated`` stamp; drifting from the seeded ``created`` one is what
        *edited since* means.
    :param load_side_effect: optional ``side_effect`` for the document read (e.g. an unreadable file).
    :param iterdir_side_effect: optional ``side_effect`` for the directory listing (e.g. an away mount).
    :returns: the created mocks, keyed by what they stand in for.
    """
    paths = [DIRECTORY / name for name in listing]
    mocker.patch.object(Path, "iterdir", autospec=True, side_effect=iterdir_side_effect, return_value=paths)
    mocker.patch.object(Path, "exists", autospec=True, side_effect=lambda self: self in paths)
    mock_stat = mocker.patch.object(Path, "stat", return_value=mocker.MagicMock(st_size=BACKUP_SIZE))
    mock_load = mocker.patch.object(
        RehuDocument,
        "load",
        side_effect=load_side_effect,
        return_value=mocker.MagicMock(created=SEEDED_STAMP, updated=updated),
    )
    mock_rename = mocker.patch.object(Path, "rename", autospec=True)
    mock_unlink = mocker.patch.object(Path, "unlink", autospec=True)
    return {"load": mock_load, "rename": mock_rename, "stat": mock_stat, "unlink": mock_unlink}


# region Inventory tests


def test_inventory_reports_what_a_revert_would_restore(mocker: MockerFixture) -> None:
    """The inventory names every backup, where each would land, what they occupy, and what the revert
    would delete -- all without touching disk state.

    **Test steps:**

    * mock a directory holding a completed keep-backups conversion
    * read the inventory
    * verify the backups, their restore targets, the total bytes and the written files, and that
      nothing was renamed or unlinked
    """
    mocks = mock_environment(mocker)

    inventory = conversion_backups(REHU_PATH)

    assert inventory.backups == BACKUPS
    assert inventory.restores == RESTORES
    assert inventory.total_bytes == BACKUP_SIZE * len(BACKUPS)
    assert inventory.written == WRITTEN
    assert inventory.legacy_restored == DIRECTORY / "info.tc"
    assert not inventory.obstructions
    assert inventory.revertible is True
    mocks["rename"].assert_not_called()
    mocks["unlink"].assert_not_called()


def test_inventory_without_a_backed_up_tc_is_not_revertible(mocker: MockerFixture) -> None:
    """A directory whose ``.orig`` files hold no ``.tc`` is not a conversion this can undo -- whatever
    else it holds. A discard-originals run leaves exactly this, and so does an unrelated directory
    somebody happened to leave a backup in.

    **Test steps:**

    * mock a directory holding image backups but no ``info.tc.orig``
    * read the inventory
    * verify it is not revertible, and says so by naming no restored legacy source
    """
    mock_environment(mocker, listing=("info.rehu", "info00.jpg", "cover.jpg.orig"))

    inventory = conversion_backups(REHU_PATH)

    assert inventory.legacy_restored is None
    assert inventory.revertible is False


def test_inventory_reports_an_occupied_restore_target(mocker: MockerFixture) -> None:
    """A legacy name the user has since put back by hand occupies a restore target, which refuses the
    whole revert rather than letting it overwrite the file -- the same never-overwrite discipline the
    forward conversion follows.

    **Test steps:**

    * mock a ``cover.jpg`` sitting where ``cover.jpg.orig`` would be restored
    * read the inventory
    * verify that path is reported as an obstruction and the conversion reads as not revertible
    """
    mock_environment(mocker, listing=(*CONVERTED, "cover.jpg"))

    inventory = conversion_backups(REHU_PATH)

    assert inventory.obstructions == (DIRECTORY / "cover.jpg",)
    assert inventory.revertible is False


def test_inventory_does_not_count_the_written_files_as_obstructions(mocker: MockerFixture) -> None:
    """A conversion that overwrote an existing ``.rehu`` backed it up, so its restore target is the
    written ``.rehu`` itself -- which the revert deletes, so it obstructs nothing.

    **Test steps:**

    * mock a directory whose backups include ``info.rehu.orig``
    * read the inventory
    * verify no obstruction is reported and the conversion stays revertible
    """
    mock_environment(mocker, listing=(*CONVERTED, "info.rehu.orig"))

    inventory = conversion_backups(REHU_PATH)

    assert not inventory.obstructions
    assert inventory.revertible is True


def test_inventory_over_an_unreadable_directory_reverts_nothing(mocker: MockerFixture) -> None:
    """A directory that cannot be listed -- an away mount -- reports no backups and refuses, rather than
    reading as a conversion whose originals were discarded ([[mounts-and-storage#offline-mounts]]).

    **Test steps:**

    * mock ``iterdir`` raising
    * read the inventory
    * verify it holds no backups and is not revertible
    """
    mock_environment(mocker, iterdir_side_effect=OSError("mount is away"))

    inventory = conversion_backups(REHU_PATH)

    assert not inventory.backups
    assert inventory.revertible is False


def test_a_rehu_saved_again_since_the_conversion_reads_as_edited(mocker: MockerFixture) -> None:
    """``created`` and ``updated`` drifting apart is the edit: a conversion seeds both with the same
    stamp, and only a changed save refreshes ``updated``. This is the warning a caller owes the user
    before a revert deletes the file.

    **Test steps:**

    * mock a ``.rehu`` whose ``updated`` is later than its ``created``
    * read the inventory
    * verify it reports the file as edited since the conversion
    """
    mock_environment(mocker, updated="2026-08-06T09:00:00Z")

    assert conversion_backups(REHU_PATH).edited_since is True


def test_an_unreadable_rehu_reads_as_edited(mocker: MockerFixture) -> None:
    """A ``.rehu`` that cannot be parsed cannot be shown to be untouched, and *unreadable* is not
    *unedited* -- so it warns, which is the cheaper of the two mistakes.

    **Test steps:**

    * mock the document read raising a format error
    * read the inventory
    * verify it reports the file as edited since the conversion
    """
    mock_environment(mocker, load_side_effect=RehuFormatError("not JSON"))

    assert conversion_backups(REHU_PATH).edited_since is True


def test_an_absent_rehu_reads_as_unedited(mocker: MockerFixture) -> None:
    """No ``.rehu`` means the revert deletes nothing, so there is no edit to lose and nothing to warn
    about -- the backups are still restorable.

    **Test steps:**

    * mock a directory holding only the backups
    * read the inventory
    * verify nothing is reported as written, it is not flagged as edited, and it stays revertible
    """
    mock_environment(mocker, listing=("info.tc.orig", "cover.jpg.orig"), load_side_effect=FileNotFoundError)

    inventory = conversion_backups(REHU_PATH)

    assert not inventory.written
    assert inventory.edited_since is False
    assert inventory.revertible is True


def test_the_conversion_date_is_the_rehus_created_stamp(mocker: MockerFixture) -> None:
    """A conversion mints ``created``, so it dates the conversion rather than the resource -- which is
    what a backups manager lists in its *converted* column (#193).

    **Test steps:**

    * mock a directory holding a completed keep-backups conversion
    * read the inventory
    * verify it reports the seeded stamp, and reports no edit
    """
    mock_environment(mocker)

    inventory = conversion_backups(REHU_PATH)

    assert inventory.converted == SEEDED_STAMP
    assert inventory.edited_since is False


@pytest.mark.parametrize("load_side_effect", [RehuFormatError("not JSON"), OSError("mount away")])
def test_an_unreadable_rehu_names_no_conversion_date(mocker: MockerFixture, load_side_effect: Exception) -> None:
    """A ``.rehu`` that will not read still warns before a revert, but it cannot vouch for a conversion
    date -- so it shows none rather than one it made up (#193).

    **Test steps:**

    * mock the document read failing
    * read the inventory
    * verify the conversion date is empty while the edit warning still stands
    """
    mock_environment(mocker, load_side_effect=load_side_effect)

    inventory = conversion_backups(REHU_PATH)

    assert inventory.converted == ""
    assert inventory.edited_since is True


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
    walk skips precisely the set a revert would restore rather than a wider one.

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

# region Revert tests


def test_revert_stages_what_was_written_restores_every_backup_then_deletes(mocker: MockerFixture) -> None:
    """A full revert puts the directory back as the conversion found it: every backup is renamed to its
    original name, and the files the conversion wrote are deleted -- but only after the last rename
    succeeded, which is why they are moved aside rather than unlinked up front.

    **Test steps:**

    * revert a completed keep-backups conversion
    * verify the written files were staged first, then every backup restored, then the staged files
      unlinked -- and nothing else was
    """
    mocks = mock_environment(mocker)

    inventory = revert_conversion(REHU_PATH)

    staging = [mocker.call(written, staged_path(written)) for written in WRITTEN]
    restoring = [mocker.call(backup, restore) for backup, restore in zip(BACKUPS, RESTORES, strict=True)]
    assert mocks["rename"].call_args_list == staging + restoring
    assert [call.args[0] for call in mocks["unlink"].call_args_list] == [staged_path(w) for w in WRITTEN]
    assert inventory.restores == RESTORES


def test_revert_without_a_backed_up_tc_refuses_and_touches_nothing(mocker: MockerFixture) -> None:
    """Nothing to restore the legacy source from is a refusal, not a partial revert that deletes the
    ``.rehu`` and leaves the directory holding neither format.

    **Test steps:**

    * mock a directory whose backups hold no ``info.tc.orig``
    * revert
    * verify ``FileNotFoundError`` and that nothing was renamed or unlinked
    """
    mocks = mock_environment(mocker, listing=("info.rehu", "info00.jpg", "cover.jpg.orig"))

    with pytest.raises(FileNotFoundError):
        revert_conversion(REHU_PATH)

    mocks["rename"].assert_not_called()
    mocks["unlink"].assert_not_called()


def test_revert_onto_an_occupied_restore_target_refuses_and_touches_nothing(mocker: MockerFixture) -> None:
    """One occupied restore target refuses the whole revert -- half a restored resource is worse than a
    converted one, and the file in the way is the user's.

    **Test steps:**

    * mock a ``cover.jpg`` sitting where ``cover.jpg.orig`` would be restored
    * revert
    * verify ``FileExistsError`` and that nothing was renamed or unlinked
    """
    mocks = mock_environment(mocker, listing=(*CONVERTED, "cover.jpg"))

    with pytest.raises(FileExistsError):
        revert_conversion(REHU_PATH)

    mocks["rename"].assert_not_called()
    mocks["unlink"].assert_not_called()


def test_a_leftover_staging_file_refuses_before_anything_moves(mocker: MockerFixture) -> None:
    """A ``.reverting`` sibling left by an interrupted revert aborts the next one instead of being
    clobbered -- the stale-backup guard's counterpart, and checked before the first rename so a refusal
    never leaves the written files half-staged.

    **Test steps:**

    * mock a leftover ``info01.jpg.reverting`` -- the *last* file the staging loop would move
    * revert
    * verify ``FileExistsError`` and that nothing was renamed
    """
    mocks = mock_environment(mocker, listing=(*CONVERTED, "info01.jpg.reverting"))

    with pytest.raises(FileExistsError):
        revert_conversion(REHU_PATH)

    mocks["rename"].assert_not_called()


def test_a_failed_restore_puts_the_converted_state_back(mocker: MockerFixture) -> None:
    """A rename failing part-way through the restore loop rolls the revert back: what was already
    restored is renamed to its backup again and every staged file returns to the name the conversion
    gave it, so the directory is left converted rather than split between the two states.

    **Test steps:**

    * mock the rename to fail on the second restore (after three stagings and one restore)
    * revert
    * verify the exception propagates, the one restore and all three stagings were undone, and nothing
      was unlinked
    """
    mocks = mock_environment(mocker)
    calls: list[object] = []

    def rename_side_effect(_self: Path, _target: Path) -> None:
        calls.append(None)
        if len(calls) == len(WRITTEN) + 2:
            raise OSError("permission denied")

    mocks["rename"].side_effect = rename_side_effect

    with pytest.raises(OSError, match="permission denied"):
        revert_conversion(REHU_PATH)

    undo = [mocker.call(RESTORES[0], BACKUPS[0])] + [mocker.call(staged_path(written), written) for written in WRITTEN]
    assert mocks["rename"].call_args_list[-len(undo) :] == undo
    mocks["unlink"].assert_not_called()


def test_a_failed_staging_puts_back_what_already_moved(mocker: MockerFixture) -> None:
    """A failure inside the staging loop itself -- before any backup has been touched -- returns the
    already-staged files to their written names.

    **Test steps:**

    * mock the rename to fail on the second staging
    * revert
    * verify the exception propagates and the one staged file was moved back
    """
    mocks = mock_environment(mocker)
    calls: list[object] = []

    def rename_side_effect(_self: Path, _target: Path) -> None:
        calls.append(None)
        if len(calls) == 2:
            raise OSError("permission denied")

    mocks["rename"].side_effect = rename_side_effect

    with pytest.raises(OSError, match="permission denied"):
        revert_conversion(REHU_PATH)

    assert mocks["rename"].call_args_list == [
        mocker.call(WRITTEN[0], staged_path(WRITTEN[0])),
        mocker.call(WRITTEN[1], staged_path(WRITTEN[1])),
        mocker.call(staged_path(WRITTEN[0]), WRITTEN[0]),
    ]


# endregion

# region Discard tests


def test_discard_deletes_exactly_the_backups(mocker: MockerFixture) -> None:
    """Discarding makes the conversion permanent by deleting the ``.orig`` siblings and nothing else --
    the written ``.rehu`` and its screenshots stay.

    **Test steps:**

    * discard a completed keep-backups conversion's backups
    * verify exactly the backups were unlinked, and nothing was renamed
    """
    mocks = mock_environment(mocker)

    discarded = discard_conversion_backups(REHU_PATH)

    assert discarded == BACKUPS
    assert [call.args[0] for call in mocks["unlink"].call_args_list] == list(BACKUPS)
    mocks["rename"].assert_not_called()


# endregion
