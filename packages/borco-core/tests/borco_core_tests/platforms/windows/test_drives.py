"""Tests for the Windows drive-letter classifier (#464).

Windows-only, like the module: ``kernel32`` and ``mpr`` are loaded at import, so the file skips off Windows.
:func:`drive_type` is a fact about the running machine and is asked of it; :func:`mapped_share` is too for a letter
that is no network drive, and its success path -- which needs a mapped drive this machine may not have -- has the
``mpr`` call replaced.
"""

import os
from typing import Any, Final

import pytest
from pytest import mark

pytest.importorskip("msvcrt")  # a Windows-only module stands in for "is this Windows" -- see the docstring

# these must follow the skip above, or collection fails off Windows -- hence the suppressions
from borco_core.platforms.windows import drives  # noqa: E402  # pylint: disable=wrong-import-position
from pytest_mock import MockerFixture  # noqa: E402  # pylint: disable=wrong-import-position

from borco_core_tests.drive_letters import unused_drive  # noqa: E402  # pylint: disable=wrong-import-position

MODULE: Final = "borco_core.platforms.windows.drives"
"""Where the ``mpr`` call is patched."""

SHARE: Final = "\\\\nas\\share"


@mark.windows
def test_the_system_drive_is_fixed() -> None:
    """The drive Windows is installed on is a fixed disk.

    **Test steps:**

    * ask for the type of the system drive's root
    * verify it is ``DRIVE_FIXED``
    """
    assert drives.drive_type(os.environ.get("SystemDrive", "C:") + "\\") == drives.DRIVE_FIXED


@mark.windows
def test_a_letter_nothing_is_mapped_to_has_no_root() -> None:
    """A letter with nothing behind it is what an unplugged drive looks like.

    **Test steps:**

    * ask for the type of an unused letter's root
    * verify it is ``DRIVE_NO_ROOT_DIR``
    """
    assert drives.drive_type(unused_drive() + "\\") == drives.DRIVE_NO_ROOT_DIR


@mark.windows
def test_a_local_drive_maps_to_no_share() -> None:
    """Only a mapped network drive has a share.

    **Test steps:**

    * ask which share the system drive maps to, and which an unused letter does
    * verify both answers are ``None``
    """
    assert drives.mapped_share(os.environ.get("SystemDrive", "C:")) is None
    assert drives.mapped_share(unused_drive()) is None


@mark.windows
def test_a_mapped_drive_gives_its_share(mocker: MockerFixture) -> None:
    """The share is what ``WNetGetConnectionW`` writes into the buffer.

    **Test steps:**

    * replace the ``mpr`` call with one that succeeds and writes a share
    * verify the share is returned and the call was made for the given letter
    """

    def connection(_drive: str, buffer: Any, _length: Any) -> int:
        buffer.value = SHARE
        return drives.NO_ERROR

    call = mocker.patch(f"{MODULE}.WNET_GET_CONNECTION", side_effect=connection)

    assert drives.mapped_share("W:") == SHARE
    assert call.call_args.args[0] == "W:"


@mark.windows
def test_the_mapped_drives_are_the_remote_letters_with_a_share(mocker: MockerFixture) -> None:
    """Only a present, remote letter that maps to a share is listed.

    **Test steps:**

    * make letters C, D, E and W present, with D remote and unreadable, E fixed and W remote
    * replace the types and shares accordingly
    * verify only ``W:`` is listed, with its share
    """
    present = sum(1 << (ord(letter) - ord("A")) for letter in "CDEW")
    mocker.patch(f"{MODULE}.GET_LOGICAL_DRIVES", return_value=present)
    types = {
        "C:\\": drives.DRIVE_FIXED,
        "D:\\": drives.DRIVE_REMOTE,
        "E:\\": drives.DRIVE_FIXED,
        "W:\\": drives.DRIVE_REMOTE,
    }
    mocker.patch(f"{MODULE}.drive_type", side_effect=types.__getitem__)
    mocker.patch(f"{MODULE}.mapped_share", side_effect=lambda letter: SHARE if letter == "W:" else None)

    assert drives.mapped_drives() == {"W:": SHARE}


@mark.windows
def test_the_system_drive_is_never_a_mapped_drive() -> None:
    """The real drive table lists no fixed disk.

    **Test steps:**

    * ask for the mapped drives of this machine
    * verify the system drive is not among them
    """
    assert os.environ.get("SystemDrive", "C:") not in drives.mapped_drives()


@mark.windows
def test_a_connection_with_no_name_is_no_share(mocker: MockerFixture) -> None:
    """A success that wrote nothing is not a share.

    **Test steps:**

    * replace the ``mpr`` call with one that succeeds and writes nothing
    * verify the answer is ``None``
    """
    mocker.patch(f"{MODULE}.WNET_GET_CONNECTION", return_value=drives.NO_ERROR)

    assert drives.mapped_share("W:") is None
