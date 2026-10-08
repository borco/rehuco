"""Tests for the Windows drive-letter classifier (#464).

Windows-only, like the module: ``kernel32`` and ``mpr`` are loaded at import, so the file skips off Windows.
:func:`drive_type` is a fact about the running machine and is asked of it; :func:`mapped_share` is too for a letter
that is no network drive, and its success path -- which needs a mapped drive this machine may not have -- has the
``mpr`` call replaced.
"""

import os
import string
from typing import Any, Final

import pytest
from pytest import mark

pytest.importorskip("msvcrt")  # a Windows-only module stands in for "is this Windows" -- see the docstring

# these must follow the skip above, or collection fails off Windows -- hence the suppressions
from borco_core.platforms.windows import drives  # noqa: E402  # pylint: disable=wrong-import-position
from pytest_mock import MockerFixture  # noqa: E402  # pylint: disable=wrong-import-position

MODULE: Final = "borco_core.platforms.windows.drives"
"""Where the ``mpr`` call is patched."""

SHARE: Final = "\\\\nas\\share"


def unused_drive() -> str:
    """A drive letter with its colon that nothing on this machine is mounted at.

    :returns: for example ``"Z:"``.
    """
    free = next((letter for letter in reversed(string.ascii_uppercase) if not os.path.exists(f"{letter}:\\")), None)
    if free is None:
        pytest.skip("every drive letter is in use")
    return f"{free}:"


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
def test_a_connection_with_no_name_is_no_share(mocker: MockerFixture) -> None:
    """A success that wrote nothing is not a share.

    **Test steps:**

    * replace the ``mpr`` call with one that succeeds and writes nothing
    * verify the answer is ``None``
    """
    mocker.patch(f"{MODULE}.WNET_GET_CONNECTION", return_value=drives.NO_ERROR)

    assert drives.mapped_share("W:") is None
