"""Tests for naming who holds a resource when its rename is refused (#355).

The operating system's answer is mocked here -- what the Restart Manager reports is ``borco-core``'s to
measure -- and so is the filesystem the resource's files are listed from.
"""

import os
from pathlib import Path
from typing import Final
from unittest.mock import MagicMock

from borco_core import FileHolder
from pytest import fixture, mark
from pytest_mock import MockerFixture
from rehuco_agent.documents.rename_holders import (
    FOLDER_HELD_BY_NOBODY,
    HELD_BY_NOBODY,
    HELD_BY_OTHERS,
    HELD_BY_OWN_DIRECTORY,
    HELD_BY_REHUCO,
    HOLDER_FILE_LIMIT,
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


@mark.parametrize("error", [PermissionError(13, "Permission denied"), ValueError("not a plain name")])
def test_a_failure_that_is_not_a_lock_names_nobody(error: Exception, holders: MagicMock) -> None:
    """Only a refusal over an open handle is worth asking about; anything else says nothing more.

    **Test steps:**

    * describe a failure carrying no Windows lock code
    * verify nothing was added and nobody was asked
    """
    assert not RenameHolderReport.describe(INFO_PATH, error)
    holders.assert_not_called()


def test_the_folders_files_are_asked_about(listing: dict[str, MagicMock], holders: MagicMock) -> None:
    """A directory-scoped rename moves everything under the folder, so every file there is asked about
    -- subfolders themselves are not files and are skipped.

    **Test steps:**

    * describe a lock refusal of a directory-scoped resource
    * verify the files under the folder were asked about, and nothing else
    """
    del listing

    RenameHolderReport.describe(INFO_PATH, locked())

    holders.assert_called_once_with([FOLDER / "pack.zip", FOLDER / "info00.jpg"])


def test_a_file_scoped_records_own_files_are_asked_about(listing: dict[str, MagicMock], holders: MagicMock) -> None:
    """A file-scoped rename respells the files named after the record, so only those are asked about.

    **Test steps:**

    * describe a lock refusal of a file-scoped resource
    * verify the record and its namesake were asked about, and the unrelated sibling was not
    """
    del listing

    RenameHolderReport.describe(FILE_PATH, locked())

    holders.assert_called_once_with([FILE_PATH, FILE_PATH.with_name("pack.zip")])


def test_the_question_is_bounded(listing: dict[str, MagicMock], holders: MagicMock) -> None:
    """A folder of thousands of loose images asks about the first few hundred, not all of them.

    **Test steps:**

    * list more files than the limit under the folder
    * describe a lock refusal, and verify exactly the limit was asked about
    """
    listing["rglob"].return_value = iter(FOLDER / f"img{index:05}.jpg" for index in range(HOLDER_FILE_LIMIT + 10))

    RenameHolderReport.describe(INFO_PATH, locked())

    assert len(holders.call_args.args[0]) == HOLDER_FILE_LIMIT


def test_other_programs_are_named(listing: dict[str, MagicMock], holders: MagicMock) -> None:
    """Whoever holds a file is named, each program once, whether the refusal was access denied or a
    sharing violation.

    **Test steps:**

    * make two processes of one program and one of another hold files
    * describe both kinds of lock refusal
    * verify each names both programs, once each
    """
    del listing
    holders.return_value = (EXPLORER, FileHolder(8, "Windows Explorer"), FileHolder(9, "Photos"))
    expected = HELD_BY_OTHERS.format(names="Windows Explorer, Photos")

    assert RenameHolderReport.describe(INFO_PATH, locked(32)) == expected
    assert RenameHolderReport.describe(INFO_PATH, locked(5)) == expected


def test_this_app_holding_a_file_is_said_plainly(listing: dict[str, MagicMock], holders: MagicMock) -> None:
    """A handle of Rehuco's own is reported as such, never blamed on someone else.

    **Test steps:**

    * make this process and another program hold files
    * describe a lock refusal
    * verify both are said, the other program first
    """
    del listing
    holders.return_value = (FileHolder(os.getpid(), "Rehuco"), EXPLORER)

    description = RenameHolderReport.describe(INFO_PATH, locked())

    assert description == f"{HELD_BY_OTHERS.format(names='Windows Explorer')} {HELD_BY_REHUCO}"


def test_standing_in_the_folder_is_said_plainly(
    listing: dict[str, MagicMock], holders: MagicMock, cwd: MagicMock
) -> None:
    """A rename that could not step the process out of the folder says so, instead of hinting at
    Explorer -- the working directory is a handle no other program can be blamed for.

    **Test steps:**

    * put the working directory in a subfolder of the resource, with nobody holding a file
    * describe a lock refusal of the directory-scoped resource
    * verify the working directory is named and the Explorer hint is not
    """
    del listing, holders
    cwd.return_value = FOLDER / "images"

    assert RenameHolderReport.describe(INFO_PATH, locked()) == HELD_BY_OWN_DIRECTORY


def test_the_working_directory_is_named_after_the_files_holders(
    listing: dict[str, MagicMock], holders: MagicMock, cwd: MagicMock
) -> None:
    """Whoever holds a file comes first; the working directory is the last thing said.

    **Test steps:**

    * make another program hold a file, with the working directory in the folder
    * describe a lock refusal, and verify the order
    """
    del listing
    holders.return_value = (EXPLORER,)
    cwd.return_value = FOLDER

    description = RenameHolderReport.describe(INFO_PATH, locked())

    assert description == f"{HELD_BY_OTHERS.format(names='Windows Explorer')} {HELD_BY_OWN_DIRECTORY}"


def test_a_file_scoped_rename_never_blames_the_working_directory(
    listing: dict[str, MagicMock], holders: MagicMock, cwd: MagicMock
) -> None:
    """A working directory beside files being respelled does not block them, so it is not named --
    nor is one that cannot be read at all.

    **Test steps:**

    * put the working directory in the file-scoped resource's folder; describe a lock refusal
    * make reading the working directory fail; describe a directory-scoped refusal
    * verify neither names the working directory
    """
    del listing, holders
    cwd.return_value = FILE_PATH.parent
    assert RenameHolderReport.describe(FILE_PATH, locked()) == HELD_BY_NOBODY

    cwd.side_effect = FileNotFoundError("gone")
    assert RenameHolderReport.describe(INFO_PATH, locked()) == FOLDER_HELD_BY_NOBODY


def test_nobody_found_for_a_folder_points_at_explorer(listing: dict[str, MagicMock], holders: MagicMock) -> None:
    """A handle on the folder itself cannot be asked about, and an Explorer window showing it is the
    holder most often behind that -- so the banner says what to do about one.

    **Test steps:**

    * make nobody hold any file
    * describe a lock refusal of a directory-scoped and of a file-scoped resource
    * verify the folder gets the Explorer hint, and the files only the plain answer
    """
    del listing, holders

    assert RenameHolderReport.describe(INFO_PATH, locked()) == FOLDER_HELD_BY_NOBODY
    assert RenameHolderReport.describe(FILE_PATH, locked()) == HELD_BY_NOBODY


def test_a_partial_rename_is_looked_through_to_its_refusal(listing: dict[str, MagicMock], holders: MagicMock) -> None:
    """A rename that could not be rolled back still started with a refusal worth explaining.

    **Test steps:**

    * build a ``PartialRenameError`` caused by a lock refusal, as ``raise ... from`` would
    * describe it, and verify the holder was named
    """
    del listing
    holders.return_value = (EXPLORER,)
    partial = PartialRenameError("split")
    partial.__cause__ = locked()

    assert RenameHolderReport.describe(FILE_PATH, partial) == HELD_BY_OTHERS.format(names="Windows Explorer")


def test_a_question_that_cannot_be_asked_adds_nothing(listing: dict[str, MagicMock], holders: MagicMock) -> None:
    """Neither an unlistable folder nor a refused question turns into a guess.

    **Test steps:**

    * make the listing fail, then make the question itself fail
    * verify neither added anything
    """
    listing["rglob"].side_effect = OSError("offline")
    assert not RenameHolderReport.describe(INFO_PATH, locked())

    listing["rglob"].side_effect = None
    holders.side_effect = OSError("refused")
    assert not RenameHolderReport.describe(INFO_PATH, locked())
