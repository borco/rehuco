"""Tests for moving a `.rehu` resource in place within its root (#579): another folder, its missing parents made, the
same collision check and rollback as a rename, and the emptied folders left behind removed on request."""

import logging
from pathlib import Path
from typing import Any, Final

from pytest import LogCaptureFixture, raises
from pytest_mock import MockerFixture
from rehuco_core import (
    RehuRenamer,
    Relocation,
    RenameCoordinator,
    move_rehu_resource,
    rehu_move_conflict,
    remove_empty_parents,
)

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
