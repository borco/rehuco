"""Tests for naming who holds a resource when its rename is refused (#355, #505).

The operating system's answer is mocked here -- what the Restart Manager reports is ``borco-core``'s to
measure -- and so is the filesystem the resource's files are listed from.
"""

import logging
import os
from pathlib import Path
from typing import Final
from unittest.mock import MagicMock

from borco_core import FileHolder
from pytest import LogCaptureFixture, fixture, mark, raises
from pytest_mock import MockerFixture
from rehuco_agent.documents.rename_holders import (
    FOLDER_HELD_BY_NOBODY,
    HELD_BY_NOBODY,
    HELD_BY_OWN_DIRECTORY,
    HELD_BY_REHUCO,
    HOLDER_FILE_LIMIT,
    HoldersFound,
    RenameHolderReport,
)
from rehuco_core import PartialRenameError

MODULE: Final = "rehuco_agent.documents.rename_holders"

FOLDER: Final = Path("/fake/library/pack")
INFO_PATH: Final = FOLDER / "info.rehu"
FILE_PATH: Final = Path("/fake/library/pack.rehu")
EXPLORER: Final = FileHolder(7, "Windows Explorer")


def locked(winerror: int = 32) -> PermissionError:
    """A refusal carrying a Windows error code, whatever platform the suite runs on.

    Set as an attribute rather than passed to the constructor: ``OSError``'s fourth argument only
    becomes ``winerror`` on Windows, and the suite also runs on Linux.

    :param winerror: the Windows error code.
    :returns: the error.
    """
    error = PermissionError(13, "The process cannot access the file because it is being used by another process")
    setattr(error, "winerror", winerror)
    return error


@fixture(name="cwd", autouse=True)
def fixture_cwd(mocker: MockerFixture) -> MagicMock:
    """Pin this process's working directory somewhere outside every resource here, so no test depends
    on where the suite was started from; a test standing inside a folder points it there.

    :param mocker: pytest-mock fixture.
    :returns: the ``Path.cwd`` stand-in.
    """
    return mocker.patch.object(Path, "cwd", return_value=Path("/fake/elsewhere"))


@fixture(name="listing")
def fixture_listing(mocker: MockerFixture) -> dict[str, MagicMock]:
    """Mock the listing the resource's files come from: a folder holding a zip, an image and a
    subfolder, beside a file-scoped record's siblings.

    :param mocker: pytest-mock fixture.
    :returns: the ``rglob`` and ``iterdir`` stand-ins, by name.
    """
    subfolder = FOLDER / "extras"
    mocker.patch.object(Path, "is_file", autospec=True, side_effect=lambda self: self != subfolder)
    return {
        "rglob": mocker.patch.object(
            Path, "rglob", autospec=True, return_value=iter([FOLDER / "pack.zip", subfolder, FOLDER / "info00.jpg"])
        ),
        "iterdir": mocker.patch.object(
            Path,
            "iterdir",
            autospec=True,
            return_value=iter([FILE_PATH, FILE_PATH.with_name("pack.zip"), FILE_PATH.with_name("other.zip")]),
        ),
    }


@fixture(name="holders")
def fixture_holders(mocker: MockerFixture) -> MagicMock:
    """Stand in for the operating system's answer: nobody, until a test says otherwise.

    :param mocker: pytest-mock fixture.
    :returns: the ``file_holders`` stand-in.
    """
    return mocker.patch(f"{MODULE}.file_holders", return_value=())


@fixture(name="folder_walk", autouse=True)
def fixture_folder_walk(mocker: MockerFixture) -> MagicMock:
    """Stand in for the walk over every handle on the system: nobody, until a test says otherwise. Autouse, so no
    test here walks the real machine's handles.

    :param mocker: pytest-mock fixture.
    :returns: the ``folder_holders`` stand-in.
    """
    return mocker.patch(f"{MODULE}.folder_holders", return_value=())


def test_a_folder_is_walked_and_merged_with_its_files_holders(
    listing: dict[str, MagicMock], holders: MagicMock, folder_walk: MagicMock
) -> None:
    """A directory-scoped resource also asks who holds the folder itself -- a shell standing in it holds no file --
    and a program both questions find is listed once, under the Restart Manager's name.

    **Test steps:**

    * make the Restart Manager name Explorer, and the walk name Explorer by its executable and a shell
    * find the holders of a directory-scoped resource
    * verify the folder was walked, and Explorer is listed once by its friendly name, then the shell
    """
    del listing
    shell = FileHolder(12, "bash.exe")
    holders.return_value = (EXPLORER,)
    folder_walk.return_value = (FileHolder(EXPLORER.pid, "explorer.exe"), shell)

    found = RenameHolderReport.find(INFO_PATH)

    folder_walk.assert_called_once_with(FOLDER)
    assert found.others == (EXPLORER, shell)


def test_a_file_scoped_resource_walks_no_folder(
    listing: dict[str, MagicMock], holders: MagicMock, folder_walk: MagicMock
) -> None:
    """A file-scoped rename respells files beside others in a folder it does not move: whoever stands in that folder
    is not in its way, so the folder is not walked.

    **Test steps:**

    * find the holders of a file-scoped resource
    * verify the folder was not walked
    """
    del listing, holders

    RenameHolderReport.find(FILE_PATH)

    folder_walk.assert_not_called()


@mark.parametrize("error", [PermissionError(13, "Permission denied"), ValueError("not a plain name")])
def test_a_failure_that_is_not_a_lock_is_not_a_refusal(error: Exception) -> None:
    """Only a refusal over an open handle is worth asking about.

    **Test steps:**

    * ask about a failure carrying no Windows lock code
    * verify it is not a lock refusal
    """
    assert not RenameHolderReport.is_lock_refusal(error)


@mark.parametrize("winerror", [32, 5])
def test_a_sharing_violation_and_access_denied_are_refusals(winerror: int) -> None:
    """Either Windows answer to a rename over an open handle is a lock refusal.

    **Test steps:**

    * ask about a sharing violation and about access denied
    * verify each is a lock refusal
    """
    assert RenameHolderReport.is_lock_refusal(locked(winerror))


def test_a_partial_rename_is_looked_through_to_its_refusal() -> None:
    """A rename that could not be rolled back still started with a refusal worth explaining.

    **Test steps:**

    * build a ``PartialRenameError`` caused by a lock refusal, as ``raise ... from`` would
    * verify it is a lock refusal
    """
    partial = PartialRenameError("split")
    partial.__cause__ = locked()

    assert RenameHolderReport.is_lock_refusal(partial)


def test_the_folders_files_are_asked_about(listing: dict[str, MagicMock], holders: MagicMock) -> None:
    """A directory-scoped rename moves everything under the folder, so every file there is asked about
    -- subfolders themselves are not files and are skipped.

    **Test steps:**

    * find the holders of a directory-scoped resource
    * verify the files under the folder were asked about, and nothing else
    """
    del listing

    RenameHolderReport.find(INFO_PATH)

    holders.assert_called_once_with([FOLDER / "pack.zip", FOLDER / "info00.jpg"])


def test_a_file_scoped_records_own_files_are_asked_about(listing: dict[str, MagicMock], holders: MagicMock) -> None:
    """A file-scoped rename respells the files named after the record, so only those are asked about.

    **Test steps:**

    * find the holders of a file-scoped resource
    * verify the record and its namesake were asked about, and the unrelated sibling was not
    """
    del listing

    RenameHolderReport.find(FILE_PATH)

    holders.assert_called_once_with([FILE_PATH, FILE_PATH.with_name("pack.zip")])


def test_the_question_is_bounded(listing: dict[str, MagicMock], holders: MagicMock) -> None:
    """A folder of thousands of loose images asks about the first few hundred, not all of them.

    **Test steps:**

    * list more files than the limit under the folder
    * find the holders, and verify exactly the limit was asked about
    """
    listing["rglob"].return_value = iter(FOLDER / f"img{index:05}.jpg" for index in range(HOLDER_FILE_LIMIT + 10))

    RenameHolderReport.find(INFO_PATH)

    assert len(holders.call_args.args[0]) == HOLDER_FILE_LIMIT


def test_other_programs_and_this_one_are_told_apart(listing: dict[str, MagicMock], holders: MagicMock) -> None:
    """Every other process is listed, in the operating system's order; this one is said apart, never listed.

    **Test steps:**

    * make two processes of one program, one of another, and this process hold files
    * find the holders
    * verify the three other processes are listed in order, and this one is noted as a holder
    """
    del listing
    others = (EXPLORER, FileHolder(8, "Windows Explorer"), FileHolder(9, "Photos"))
    holders.return_value = (others[0], FileHolder(os.getpid(), "Rehuco"), *others[1:])

    found = RenameHolderReport.find(INFO_PATH)

    assert found == HoldersFound(others, held_by_rehuco=True, standing_inside=False, directory_scoped=True)


def test_the_app_in_its_own_way_is_logged_as_an_error(
    listing: dict[str, MagicMock], holders: MagicMock, cwd: MagicMock, caplog: LogCaptureFixture
) -> None:
    """Rehuco holding one of its own files, or standing in its own folder, is a bug: each is logged as an error
    naming the resource, so the trace outlives the dialog -- and other programs holding files log nothing.

    **Test steps:**

    * make this process hold a file and stand in the folder; find the holders
    * verify two errors were logged, one naming the record and one the folder
    * make only another program hold a file; find the holders
    * verify nothing was logged
    """
    del listing
    holders.return_value = (FileHolder(os.getpid(), "Rehuco"),)
    cwd.return_value = FOLDER / "images"

    with caplog.at_level(logging.ERROR, logger=MODULE):
        RenameHolderReport.find(INFO_PATH)

    assert [record.levelno for record in caplog.records] == [logging.ERROR, logging.ERROR]
    assert str(INFO_PATH) in caplog.records[0].getMessage()
    assert str(FOLDER) in caplog.records[1].getMessage()

    caplog.clear()
    holders.return_value = (EXPLORER,)
    cwd.return_value = Path("/fake/elsewhere")
    with caplog.at_level(logging.ERROR, logger=MODULE):
        RenameHolderReport.find(INFO_PATH)

    assert not caplog.records


def test_standing_in_the_folder_is_found(listing: dict[str, MagicMock], holders: MagicMock, cwd: MagicMock) -> None:
    """A rename that could not step the process out of the folder is found -- the working directory is a handle
    no other program can be blamed for.

    **Test steps:**

    * put the working directory in a subfolder of the directory-scoped resource
    * find the holders, and verify the process is standing inside
    """
    del listing, holders
    cwd.return_value = FOLDER / "images"

    assert RenameHolderReport.find(INFO_PATH).standing_inside


def test_a_file_scoped_rename_never_blames_the_working_directory(
    listing: dict[str, MagicMock], holders: MagicMock, cwd: MagicMock
) -> None:
    """A working directory beside files being respelled does not block them -- nor does one that cannot be
    read at all.

    **Test steps:**

    * put the working directory in the file-scoped resource's folder, and find its holders
    * make reading the working directory fail, and find a directory-scoped resource's holders
    * verify neither is standing inside
    """
    del listing, holders
    cwd.return_value = FILE_PATH.parent
    assert not RenameHolderReport.find(FILE_PATH).standing_inside

    cwd.side_effect = FileNotFoundError("gone")
    assert not RenameHolderReport.find(INFO_PATH).standing_inside


def test_a_question_that_cannot_be_asked_is_a_refusal(listing: dict[str, MagicMock], holders: MagicMock) -> None:
    """Neither an unlistable folder nor a refused question turns into a guess: the caller hears why.

    **Test steps:**

    * make the listing fail, then make the question itself fail
    * verify each raises its ``OSError``
    """
    listing["rglob"].side_effect = OSError("offline")
    with raises(OSError, match="offline"):
        RenameHolderReport.find(INFO_PATH)

    listing["rglob"].side_effect = None
    holders.side_effect = OSError("refused")
    with raises(OSError, match="refused"):
        RenameHolderReport.find(INFO_PATH)


def answer(*, rehuco: bool = False, inside: bool = False, folder: bool = True) -> HoldersFound:
    """Who holds the files: one other program, and this process as asked.

    :param rehuco: whether this process holds one.
    :param inside: whether it is standing in the folder.
    :param folder: whether the rename was of a folder.
    :returns: the answer.
    """
    return HoldersFound((EXPLORER,), held_by_rehuco=rehuco, standing_inside=inside, directory_scoped=folder)


def test_notes_say_nothing_while_only_other_programs_are_listed() -> None:
    """The listed programs say everything there is to say.

    **Test steps:**

    * verify the notes are empty while one other program is listed
    """
    assert not answer().notes(1)


def test_notes_say_this_process_is_in_the_way() -> None:
    """A handle of Rehuco's own and its working directory are said plainly, in that order, listed or not.

    **Test steps:**

    * verify each is said alone, and both together in order, with a program listed and with none
    """
    assert answer(rehuco=True).notes(1) == HELD_BY_REHUCO
    assert answer(inside=True).notes(0) == HELD_BY_OWN_DIRECTORY
    assert answer(rehuco=True, inside=True).notes(1) == f"{HELD_BY_REHUCO} {HELD_BY_OWN_DIRECTORY}"


def test_notes_say_nobody_once_nobody_is_listed() -> None:
    """With no program listed -- none found, or every one ended -- the folder gets the Explorer hint and the
    files the plain answer.

    **Test steps:**

    * verify the notes for no program listed, for a folder and for a file-scoped resource
    """
    assert answer().notes(0) == FOLDER_HELD_BY_NOBODY
    assert answer(folder=False).notes(0) == HELD_BY_NOBODY
