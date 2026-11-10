"""Tests for RehuDocumentModel's moves (#579, #339): the path row's root place, clicked -- the same orchestration as a
rename, into another folder, and the left-behind folders removed when the setting says so -- and the hooks a move a task
runs reports through."""

from pathlib import Path
from typing import Final
from unittest.mock import MagicMock

from pytest import mark
from pytest_mock import MockerFixture
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.settings.move_settings import shared_move_settings
from rehuco_core import RehuDocument, RenameCoordinator

ROOT: Final = Path(Path.cwd().anchor) / "tutorials"
RECORD: Final = ROOT / "Old" / "Foo" / "info.rehu"
INTO: Final = ROOT / "Jane"
MOVED: Final = INTO / "Foo [2024]" / "info.rehu"
MOVE: Final = "rehuco_agent.documents.rehu_document_model.move_rehu_resource"


def make_record(root: Path) -> RehuDocumentModel:
    """A clean directory-scoped record on disk at ``root/Old/Foo``, the only thing in ``Old``.

    :param root: the root's folder.
    :returns: its model.
    """
    record = root / "Old" / "Foo" / "info.rehu"
    record.parent.mkdir(parents=True)
    document = RehuDocument({"type": "Tutorial"}, record)
    document.save()
    return RehuDocumentModel(document)


def test_a_move_lands_through_core_and_is_adopted(mocker: MockerFixture) -> None:
    """With no coordinator the move goes straight to core, and the model follows it to the new path.

    **Test steps:**

    * mock the core move to succeed, and listen to ``renamed``
    * move the record into ``Jane`` as ``Foo [2024]``
    * verify core got the record, the folder and the name, the model is at the new path, and ``renamed`` fired once
    """
    move = mocker.patch(MOVE, return_value=MOVED)
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, RECORD))
    heard: list[Path | None] = []
    model.renamed.connect(lambda: heard.append(model.path))

    assert model.move_in_root(INTO, "Foo [2024]", ROOT) is True

    move.assert_called_once_with(RECORD, INTO, "Foo [2024]")
    assert model.path == MOVED
    assert model.current_name == "Foo [2024]"
    assert heard == [MOVED]
    assert model.rename_error == ""


def test_a_move_goes_through_the_coordinator_when_there_is_one(mocker: MockerFixture) -> None:
    """With a coordinator the move stands the readers aside, as a rename does.

    **Test steps:**

    * build a model over a coordinator whose rename is mocked to succeed
    * move the record
    * verify the coordinator got the folder, and core was not called directly
    """
    coordinator = RenameCoordinator()
    through = mocker.patch.object(coordinator, "rename", return_value=MOVED)
    direct = mocker.patch(MOVE)
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, RECORD), rename_coordinator=coordinator)

    assert model.move_in_root(INTO, "Foo [2024]", ROOT) is True

    through.assert_called_once_with(RECORD, "Foo [2024]", into=INTO)
    direct.assert_not_called()


def test_a_failed_move_reports_in_the_banner_naming_the_place(mocker: MockerFixture) -> None:
    """A refused move leaves the record where it was and says where it was going, under its root.

    **Test steps:**

    * make the core move fail
    * move the record
    * verify it failed, the banner names the place, and the model did not move
    """
    mocker.patch(MOVE, side_effect=FileExistsError(17, "Cannot create a file when that file already exists"))
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, RECORD))

    assert model.move_in_root(INTO, "Foo [2024]", ROOT) is False

    assert model.rename_error == (
        'Could not move "Foo" to "Jane/Foo [2024]": Cannot create a file when that file already exists.'
    )
    assert model.path == RECORD


def test_a_dirty_record_is_saved_before_it_moves(mocker: MockerFixture) -> None:
    """Edits are saved first, so the files moved are never stale; a save that fails stops the move.

    **Test steps:**

    * edit the record and make its save fail
    * move it
    * verify the banner says the save before moving failed, and nothing was moved
    """
    move = mocker.patch(MOVE)
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, RECORD))
    model.title = "New Title"
    mocker.patch.object(model, "save", side_effect=OSError(5, "offline mount"))

    assert model.move_in_root(INTO, "Foo [2024]", ROOT) is False

    assert model.rename_error == 'Could not save "Foo" before moving it: offline mount.'
    move.assert_not_called()


def test_a_record_with_a_save_not_landed_is_not_moved(mocker: MockerFixture) -> None:
    """A save not landed is the record until it lands; a move now would run ahead of it.

    **Test steps:**

    * give the record a save not landed
    * move it
    * verify the banner says to wait, and nothing was moved
    """
    move = mocker.patch(MOVE)
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, RECORD))
    mocker.patch.object(model, "_RehuDocumentModel__pending_save_for", return_value=MagicMock())

    assert model.move_in_root(INTO, "Foo [2024]", ROOT) is False

    assert model.rename_error.startswith('Cannot move to "Jane/Foo [2024]": a save of this record has not landed yet.')
    move.assert_not_called()


@mark.usefixtures("real_path_stat")
@mark.parametrize("remove", [False, True])
def test_the_folder_left_behind_goes_only_when_the_setting_says(tmp_path: Path, remove: bool) -> None:
    """The folder the record left empty stays, unless *Remove the left-behind folders* is set; the root always stays.

    **Test steps:**

    * set the choice, and move a record out of ``Old``, which holds nothing else
    * verify the record is at its new place, and ``Old`` is gone only when the choice is on
    """
    shared_move_settings().remove_empty_folders = remove
    model = make_record(tmp_path)

    assert model.move_in_root(tmp_path / "Jane", "Foo", tmp_path) is True

    assert (tmp_path / "Jane" / "Foo" / "info.rehu").is_file()
    assert (tmp_path / "Old").exists() is not remove
    assert tmp_path.is_dir()


@mark.usefixtures("real_path_stat")
def test_a_rename_never_removes_folders(tmp_path: Path) -> None:
    """Removing the left-behind folders is a move's: a rename leaves its folder where it was.

    **Test steps:**

    * set the choice on, and rename a record within ``Old``
    * verify ``Old`` is still there, holding it
    """
    shared_move_settings().remove_empty_folders = True
    model = make_record(tmp_path)

    assert model.rename_location("Bar") is True

    assert (tmp_path / "Old" / "Bar" / "info.rehu").is_file()


@mark.usefixtures("real_path_stat")
def test_the_conflict_check_answers_for_the_place(tmp_path: Path) -> None:
    """The advisory check says whether something occupies the place; a record with no path has none.

    **Test steps:**

    * put a folder at ``Jane/Foo``
    * verify a move there is reported occupied, one to ``Jane/Bar`` not, and a pathless record never is
    """
    model = make_record(tmp_path)
    (tmp_path / "Jane" / "Foo").mkdir(parents=True)

    assert model.move_conflicts(tmp_path / "Jane", "Foo") is True
    assert model.move_conflicts(tmp_path / "Jane", "Bar") is False
    assert RehuDocumentModel(RehuDocument({"type": "Tutorial"})).move_conflicts(tmp_path, "Foo") is False


@mark.usefixtures("real_path_stat")
def test_a_record_under_no_root_moves_and_leaves_its_folders(tmp_path: Path) -> None:
    """A record under no root is moved by a rename all the same; with no root to stop at, its folders stay, and the
    place is named by its full path (#339).

    **Test steps:**

    * set removing the left-behind folders on, and move a record under no root into a root's folder
    * verify it moved, ``Old`` is still there, and a refused second move names the full path
    """
    shared_move_settings().remove_empty_folders = True
    model = make_record(tmp_path / "stray")
    into = tmp_path / "root" / "Jane"

    assert model.move_in_root(into, "Foo", None) is True

    assert (into / "Foo" / "info.rehu").is_file()
    assert (tmp_path / "stray" / "Old").is_dir()
    (tmp_path / "elsewhere" / "Foo").mkdir(parents=True)
    assert model.move_in_root(tmp_path / "elsewhere", "Foo", None) is False
    assert str(tmp_path / "elsewhere" / "Foo") in model.rename_error


def test_a_move_a_task_runs_is_prepared_as_a_move_is(mocker: MockerFixture) -> None:
    """Before a move is queued the record is saved and checked as before a move in place; a refusal is on the banner.

    **Test steps:**

    * prepare a clean record's move: allowed
    * give it a save not landed and prepare again: refused, naming the place
    * prepare a record with no path: refused
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, RECORD))

    assert model.prepare_move("Archive: Foo") is True
    assert model.rename_error == ""

    mocker.patch.object(model, "_RehuDocumentModel__pending_save_for", return_value=MagicMock())
    assert model.prepare_move("Archive: Foo") is False
    assert model.rename_error.startswith('Cannot move to "Archive: Foo": a save of this record has not landed yet.')

    assert RehuDocumentModel(RehuDocument({"type": "Tutorial"})).prepare_move("Archive: Foo") is False


def test_a_move_a_task_ran_reports_its_end() -> None:
    """A failed move is told on the banner; a landed one as a rename's landing.

    **Test steps:**

    * report a failure, then a landing, listening to ``renamed``
    * verify the banner holds the failure, and ``renamed`` fired once
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, RECORD))
    heard: list[bool] = []
    model.renamed.connect(lambda: heard.append(True))

    model.move_failed("Could not move: the copy did not match.")
    model.move_landed()

    assert model.rename_error == "Could not move: the copy did not match."
    assert heard == [True]
