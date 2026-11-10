"""Tests for moving a `.rehu` resource in place within its root (#579): another folder, its missing parents made, the
same collision check and rollback as a rename, and the emptied folders left behind removed on request; and a file
record's checksum entries renamed with its files (#339)."""

import errno
import logging
from pathlib import Path
from typing import Any, Final

from pytest import LogCaptureFixture, raises
from pytest_mock import MockerFixture
from rehuco_core import (
    CROSS_DEVICE_WINERROR,
    RehuRenamer,
    Relocation,
    RenameCoordinator,
    generate_checksums,
    is_cross_device,
    load_checksum_record,
    move_rehu_resource,
    rehu_move_conflict,
    remove_empty_parents,
    rename_rehu_resource,
    verify_checksums,
)
from rehuco_core.checksum_record import rename_checksum_entries

RECORD_TEXT: Final = "{}"
CONTENT_TEXT: Final = "content"
NEW_NAME: Final = "Intro [2024]"
DENIED: Final = 13
"""``EACCES``: a refusal no retry waits out, so a failing step fails at once."""


def make_folder_record(root: Path) -> Path:
    """A directory-scoped record at ``root/Old Author/Intro``, with one content file.

    :param root: the root's folder.
    :returns: its ``info.rehu``.
    """
    folder = root / "Old Author" / "Intro"
    folder.mkdir(parents=True)
    (folder / "content.zip").write_text(CONTENT_TEXT)
    record = folder / "info.rehu"
    record.write_text(RECORD_TEXT)
    return record


def make_file_record(root: Path) -> Path:
    """A file-scoped record ``root/foo.rehu`` with its archive, a screenshot, and someone else's ``foobar.zip``.

    :param root: the root's folder.
    :returns: its ``foo.rehu``.
    """
    root.mkdir(parents=True, exist_ok=True)
    for name in ("foo.zip", "foo00.jpg", "foobar.zip"):
        (root / name).write_text(CONTENT_TEXT)
    record = root / "foo.rehu"
    record.write_text(RECORD_TEXT)
    return record


def failing_on(call: int, real: Any) -> Any:
    """A ``Path`` method stand-in failing its ``call``-th call and running ``real`` for every other.

    :param call: which call fails, counted from 1.
    :param real: the method it stands in for.
    :returns: the side effect.
    """
    calls = 0

    def side_effect(self: Path, *args: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == call:
            raise PermissionError(DENIED, "Access is denied", str(self))
        return real(self, *args)

    return side_effect


# region moves
def test_a_folder_record_moves_into_a_folder_made_for_it(tmp_path: Path) -> None:
    """A directory-scoped record moves whole into another folder under the root, its missing parents made.

    **Test steps:**

    * move ``Old Author/Intro`` into ``Smith/2024``, neither of which exists, as ``Intro [2024]``
    * check the record and its content are there, the old folder gone, and the new record path returned
    """
    record = make_folder_record(tmp_path)

    moved = move_rehu_resource(record, tmp_path / "Smith" / "2024", NEW_NAME)

    destination = tmp_path / "Smith" / "2024" / NEW_NAME
    assert moved == destination / "info.rehu"
    assert (destination / "content.zip").read_text() == CONTENT_TEXT
    assert not record.parent.exists()


def test_a_file_record_moves_its_whole_set_and_leaves_others_alone(tmp_path: Path) -> None:
    """A file-scoped record's set -- every file named after it -- moves into the folder, renamed; a file merely
    starting alike stays.

    **Test steps:**

    * move ``foo.rehu`` into ``A/B`` as ``bar``
    * check ``bar.rehu``, ``bar.zip`` and ``bar00.jpg`` are there, and ``foobar.zip`` is where it was
    """
    record = make_file_record(tmp_path)

    moved = move_rehu_resource(record, tmp_path / "A" / "B", "bar")

    folder = tmp_path / "A" / "B"
    assert moved == folder / "bar.rehu"
    assert sorted(entry.name for entry in folder.iterdir()) == ["bar.rehu", "bar.zip", "bar00.jpg"]
    assert sorted(entry.name for entry in tmp_path.iterdir()) == ["A", "foobar.zip"]


def test_a_record_keeping_its_name_still_moves(tmp_path: Path) -> None:
    """The same name in another folder is a move, not the no-op a rename to its own name is.

    **Test steps:**

    * move ``Intro`` into ``Smith`` keeping its name
    * check it moved
    """
    record = make_folder_record(tmp_path)

    moved = move_rehu_resource(record, tmp_path / "Smith", "Intro")

    assert moved == tmp_path / "Smith" / "Intro" / "info.rehu"
    assert moved.is_file()


def test_a_move_to_where_the_record_is_does_nothing(tmp_path: Path) -> None:
    """Its own folder and its own name: nothing on disk is touched.

    **Test steps:**

    * move a record into the folder it is in, under its own name
    * check the path came back unchanged and the record is still there
    """
    record = make_folder_record(tmp_path)

    moved = move_rehu_resource(record, tmp_path / "Old Author", "Intro")

    assert moved == record
    assert record.is_file()


def test_a_folder_cannot_move_into_itself(tmp_path: Path) -> None:
    """A folder moved beneath itself is refused, nothing made and nothing moved.

    **Test steps:**

    * move ``Old Author/Intro`` into ``Old Author/Intro/sub``
    * check the refusal, the record in place, and no ``sub`` made
    """
    record = make_folder_record(tmp_path)

    with raises(ValueError, match="into itself"):
        move_rehu_resource(record, record.parent / "sub", NEW_NAME)

    assert record.is_file()
    assert not (record.parent / "sub").exists()


def test_a_file_record_may_move_into_a_folder_beneath_its_own(tmp_path: Path) -> None:
    """Only a folder can move into itself: a file set goes into a subfolder of the folder it is in.

    **Test steps:**

    * move ``foo.rehu`` into ``sub`` beside it
    * check it is there
    """
    record = make_file_record(tmp_path)

    moved = move_rehu_resource(record, tmp_path / "sub", "foo")

    assert moved == tmp_path / "sub" / "foo.rehu"
    assert moved.is_file()


# endregion


# region refusals
def test_an_occupied_destination_is_refused_before_any_folder_is_made(tmp_path: Path) -> None:
    """A folder already at the destination refuses the move: nothing moved, and the parents made for it are not.

    **Test steps:**

    * put a folder at ``Smith/Intro [2024]``, ``Smith`` existing
    * move a record there
    * check the refusal and the record in place
    """
    record = make_folder_record(tmp_path)
    (tmp_path / "Smith" / NEW_NAME).mkdir(parents=True)

    with raises(FileExistsError):
        move_rehu_resource(record, tmp_path / "Smith", NEW_NAME)

    assert record.is_file()


def test_a_failed_step_rolls_back_and_removes_the_folders_made(tmp_path: Path, mocker: MockerFixture) -> None:
    """A step that fails part-way puts the moved files back and removes the folders made for the move.

    **Test steps:**

    * fail the second rename of a file-scoped move into ``A/B``
    * check the error, every file back under its name, and no ``A``
    """
    record = make_file_record(tmp_path)
    mocker.patch.object(Path, "rename", autospec=True, side_effect=failing_on(2, Path.rename))

    with raises(PermissionError):
        move_rehu_resource(record, tmp_path / "A" / "B", "bar")

    assert sorted(entry.name for entry in tmp_path.iterdir()) == ["foo.rehu", "foo.zip", "foo00.jpg", "foobar.zip"]


def test_a_folder_that_cannot_be_made_removes_those_made_before_it(tmp_path: Path, mocker: MockerFixture) -> None:
    """Making the parents stops at the first one refused, removing those made, with nothing moved.

    **Test steps:**

    * refuse the second ``mkdir`` of a move into ``A/B``
    * check the error, the record in place, and no ``A``
    """
    record = make_folder_record(tmp_path)
    mocker.patch.object(Path, "mkdir", autospec=True, side_effect=failing_on(2, Path.mkdir))

    with raises(PermissionError):
        move_rehu_resource(record, tmp_path / "A" / "B", NEW_NAME)

    assert record.is_file()
    assert not (tmp_path / "A").exists()


def test_a_made_folder_that_will_not_go_is_logged(
    tmp_path: Path, mocker: MockerFixture, caplog: LogCaptureFixture
) -> None:
    """A folder made for a failed move that cannot be removed again is logged and left.

    **Test steps:**

    * fail a move's rename, and refuse every ``rmdir``
    * check the move's own error is raised, the record in place, and the folder left logged
    """
    record = make_folder_record(tmp_path)
    mocker.patch.object(Path, "rename", autospec=True, side_effect=PermissionError(DENIED, "Access is denied"))
    mocker.patch.object(Path, "rmdir", autospec=True, side_effect=PermissionError(DENIED, "Access is denied"))

    with caplog.at_level(logging.WARNING), raises(PermissionError):
        move_rehu_resource(record, tmp_path / "A", NEW_NAME)

    assert record.is_file()
    assert f"Could not remove {tmp_path / 'A'}" in caplog.text


# endregion


# region the advisory check
def test_the_conflict_check_names_what_is_in_the_way(tmp_path: Path) -> None:
    """The advisory check answers for the destination folder, not the record's own.

    **Test steps:**

    * put a folder at ``Smith/Intro [2024]``
    * check it is named for that move, and nothing for a move into ``Jones``
    """
    record = make_folder_record(tmp_path)
    occupied = tmp_path / "Smith" / NEW_NAME
    occupied.mkdir(parents=True)

    assert rehu_move_conflict(record, tmp_path / "Smith", NEW_NAME) == occupied
    assert rehu_move_conflict(record, tmp_path / "Jones", NEW_NAME) is None


# endregion


# region through the coordinator
def test_the_coordinator_moves_and_announces_the_move(tmp_path: Path) -> None:
    """A move through the coordinator lands, and its listeners hear the pair it ran.

    **Test steps:**

    * move a record into ``Smith`` through a coordinator with a listener
    * check the listener got the folder's pair
    """
    record = make_folder_record(tmp_path)
    coordinator = RenameCoordinator()
    heard: list[Relocation] = []
    coordinator.add_rename_listener(heard.append)

    moved = coordinator.rename(record, NEW_NAME, into=tmp_path / "Smith")

    assert moved == tmp_path / "Smith" / NEW_NAME / "info.rehu"
    assert heard == [Relocation(((record.parent, tmp_path / "Smith" / NEW_NAME),))]


def test_a_renamer_with_no_folder_renames_where_it_is(tmp_path: Path) -> None:
    """Without ``into`` a renamer is the rename it always was: the same folder, nothing made.

    **Test steps:**

    * rename a record through a renamer given no folder
    * check it stays in ``Old Author``
    """
    record = make_folder_record(tmp_path)

    renamed = RehuRenamer(record, NEW_NAME).rename()

    assert renamed == tmp_path / "Old Author" / NEW_NAME / "info.rehu"


# endregion


# region left-behind folders
def test_empty_folders_are_removed_up_to_the_root(tmp_path: Path) -> None:
    """Every empty folder from the start up is removed; the root is kept.

    **Test steps:**

    * make ``root/a/b/c``, all empty
    * remove from ``c`` up to ``root``
    * check ``c``, ``b`` and ``a`` went, deepest first, and ``root`` stays
    """
    root = tmp_path / "root"
    start = root / "a" / "b" / "c"
    start.mkdir(parents=True)

    removed = remove_empty_parents(start, root)

    assert removed == [start, start.parent, root / "a"]
    assert root.is_dir()
    assert not any(root.iterdir())


def test_removing_stops_at_a_folder_that_is_not_empty(tmp_path: Path) -> None:
    """A folder holding anything else stops the removal there.

    **Test steps:**

    * make ``root/a/b`` empty, with a file in ``a``
    * check only ``b`` went
    """
    root = tmp_path / "root"
    start = root / "a" / "b"
    start.mkdir(parents=True)
    (root / "a" / "other.txt").write_text(CONTENT_TEXT)

    assert remove_empty_parents(start, root) == [start]
    assert (root / "a").is_dir()


def test_nothing_outside_the_root_is_removed(tmp_path: Path) -> None:
    """A start that is the root, or outside it, removes nothing.

    **Test steps:**

    * make an empty root and an empty folder beside it
    * check neither is removed
    """
    root = tmp_path / "root"
    beside = tmp_path / "beside"
    root.mkdir()
    beside.mkdir()

    assert not remove_empty_parents(root, root)
    assert not remove_empty_parents(beside, root)
    assert root.is_dir() and beside.is_dir()


# endregion


# region a file record's checksum entries
def test_a_renamed_file_record_still_verifies(tmp_path: Path) -> None:
    """A file record's checksum entries are its files' names, so a rename renames them too (#339): the record verifies
    under its new name, with nothing missing and nothing added.

    **Test steps:**

    * make ``foo.rehu`` with its checksums, rename it to ``bar``
    * check the record names ``bar.zip`` alone -- the screenshot is no content -- and a verify matches it
    """
    record = make_file_record(tmp_path)
    generate_checksums(record)

    renamed = rename_rehu_resource(record, "bar")

    names = sorted(entry["name"] for entry in load_checksum_record(renamed.with_suffix(".checksum"))["files"])
    assert names == ["bar.zip"]
    assert set(verify_checksums(renamed).statuses.values()) == {"matched"}


def test_a_folder_record_keeps_its_checksum_record_as_it_was(tmp_path: Path) -> None:
    """A folder record's entries are relative to its folder, which moves whole: its record is not rewritten.

    **Test steps:**

    * make a folder record with its checksums, and read its checksum record's bytes
    * move it as ``Intro [2024]``
    * check the moved record holds the same bytes
    """
    record = make_folder_record(tmp_path)
    generate_checksums(record)
    before = record.with_suffix(".checksum").read_bytes()

    moved = move_rehu_resource(record, tmp_path / "Smith", NEW_NAME)

    assert moved.with_suffix(".checksum").read_bytes() == before


def test_a_record_that_cannot_be_rewritten_leaves_the_rename_standing(
    tmp_path: Path, mocker: MockerFixture, caplog: LogCaptureFixture
) -> None:
    """The files moved, so a checksum record that will not take its new names is logged, never a failed rename.

    **Test steps:**

    * make ``foo.rehu`` with its checksums, and make writing a checksum record refuse
    * rename it to ``bar``
    * check the rename landed and the stale record was logged
    """
    record = make_file_record(tmp_path)
    generate_checksums(record)
    mocker.patch("rehuco_core.rehu_rename.update_checksum_record", side_effect=PermissionError(DENIED, "denied"))

    with caplog.at_level(logging.WARNING):
        renamed = rename_rehu_resource(record, "bar")

    assert renamed.is_file()
    assert "still names its files' old names" in caplog.text


def test_entries_are_renamed_by_name_and_the_rest_carried() -> None:
    """Only a named entry changes; an entry that is no object is carried, and a record with nothing to rename, or none
    at all, writes nothing.

    **Test steps:**

    * rename ``a`` to ``b`` in a record holding ``a``, ``c`` and a stray string
    * rename ``x`` in the same record, then in no record
    * check the first renames ``a`` only, and the others answer ``None``
    """
    record = {"version": 1, "files": [{"name": "a", "xxh3": "0"}, {"name": "c"}, "stray"]}

    assert rename_checksum_entries(record, {"a": "b"}) == {
        "version": 1,
        "files": [{"name": "b", "xxh3": "0"}, {"name": "c"}, "stray"],
    }
    assert rename_checksum_entries(record, {"x": "y"}) is None
    assert rename_checksum_entries(None, {"a": "b"}) is None


# endregion


# region the plan and other devices
def test_the_plan_is_checked_but_not_for_collisions(tmp_path: Path) -> None:
    """The public plan refuses what a rename refuses before it looks -- a name that is not plain -- but leaves an
    occupied destination to its caller (#339).

    **Test steps:**

    * make a folder record and occupy its destination
    * check the plan still lists the folder's one pair, and a name with a separator is refused
    """
    record = make_folder_record(tmp_path)
    (tmp_path / "Smith" / NEW_NAME).mkdir(parents=True)

    assert RehuRenamer(record, NEW_NAME, into=tmp_path / "Smith").plan() == [
        (record.parent, tmp_path / "Smith" / NEW_NAME)
    ]
    with raises(ValueError, match="not a plain"):
        RehuRenamer(record, "a/b").plan()


def test_a_rename_across_devices_is_told_apart() -> None:
    """``EXDEV``, and Windows' *not the same device*, are what a rename to another volume answers; nothing else is.

    **Test steps:**

    * build the three errors
    * check the first two are cross-device and a denial is not
    """
    windows = OSError(errno.EIO, "not the same device")
    windows.winerror = CROSS_DEVICE_WINERROR  # type: ignore[attr-defined]  # set only on Windows' own errors

    assert is_cross_device(OSError(errno.EXDEV, "cross-device link"))
    assert is_cross_device(windows)
    assert not is_cross_device(PermissionError(DENIED, "denied"))


# endregion
