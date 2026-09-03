"""Tests for the ``CreateFileW`` opener (#241).

Windows-only, like the module: ``msvcrt`` does not exist elsewhere, so the whole file skips off
Windows the same way the registry tests beside it do. What the operating system *does* with the share
mode is measured in ``tests/test_shared_read.py``'s ``disk`` tests; this covers the call itself --
what is asked of ``CreateFileW``, and what happens when it refuses.
"""

import os
from pathlib import Path
from typing import Final

import pytest
from pytest import raises

pytest.importorskip("msvcrt")  # module doesn't exist off Windows -- skip the whole file there

# these must follow the skip above, or collection fails off Windows -- hence the suppressions
from borco_core.platforms.windows import shared_read  # noqa: E402  # pylint: disable=wrong-import-position
from pytest_mock import MockerFixture  # noqa: E402  # pylint: disable=wrong-import-position

MODULE: Final = "borco_core.platforms.windows.shared_read"
"""Where the Win32 calls are patched -- every one of them funnels through this module."""

HANDLE: Final = 1234
"""A stand-in for the raw ``HANDLE`` ``CreateFileW`` hands back."""

DESCRIPTOR: Final = 7
"""A stand-in for the CRT file descriptor the handle is adopted into."""

PATH: Final = Path("C:/fake/content.zip")


def test_the_file_is_opened_sharing_everything(mocker: MockerFixture) -> None:
    """``CreateFileW`` is asked to read, to share read/write/delete, and never to create (#241).

    The three sharing rights together are the whole point: withholding ``FILE_SHARE_DELETE`` is
    exactly what a plain ``open`` does, and exactly what stops the file being renamed.

    **Test steps:**

    * patch the Win32 call and the two adoption steps;
    * call :func:`~borco_core.platforms.windows.shared_read.shared_read_open`;
    * check the arguments handed to ``CreateFileW``, and that the file object comes back.
    """
    create_file = mocker.patch(f"{MODULE}.CREATE_FILE", return_value=HANDLE)
    mocker.patch(f"{MODULE}.msvcrt.open_osfhandle", return_value=DESCRIPTOR)
    fdopen = mocker.patch(f"{MODULE}.os.fdopen")
    assert shared_read.shared_read_open(PATH) is fdopen.return_value
    create_file.assert_called_once_with(
        str(PATH),
        shared_read.GENERIC_READ,
        shared_read.FILE_SHARE_READ | shared_read.FILE_SHARE_WRITE | shared_read.FILE_SHARE_DELETE,
        None,
        shared_read.OPEN_EXISTING,
        shared_read.FILE_ATTRIBUTE_NORMAL,
        None,
    )


def test_the_handle_is_adopted_by_the_crt_and_then_by_python(mocker: MockerFixture) -> None:
    """The raw handle becomes a descriptor, and the descriptor an ordinary buffered reader.

    What makes the result interchangeable with ``path.open("rb")`` for every caller downstream --
    closing it closes the handle, and nothing has to know how it was opened.

    **Test steps:**

    * patch the Win32 call and the two adoption steps;
    * call the opener;
    * check the handle reached ``open_osfhandle`` read-only and binary, and the descriptor
      ``os.fdopen``.
    """
    mocker.patch(f"{MODULE}.CREATE_FILE", return_value=HANDLE)
    open_osfhandle = mocker.patch(f"{MODULE}.msvcrt.open_osfhandle", return_value=DESCRIPTOR)
    fdopen = mocker.patch(f"{MODULE}.os.fdopen")
    shared_read.shared_read_open(PATH)
    open_osfhandle.assert_called_once_with(HANDLE, os.O_RDONLY | os.O_BINARY)
    fdopen.assert_called_once_with(DESCRIPTOR, "rb")


@pytest.mark.parametrize(
    "returned",
    [pytest.param(shared_read.INVALID_HANDLE_VALUE, id="invalid-handle"), pytest.param(None, id="null-handle")],
)
def test_a_refused_open_raises_the_real_reason(mocker: MockerFixture, returned: int | None) -> None:
    """A failed ``CreateFileW`` is reported as the ``OSError`` ``open`` would have raised (#241).

    Both shapes of failure are checked because ``ctypes`` reports a null pointer as ``None`` rather
    than as zero, so a handle test written for one misses the other -- and either would otherwise be
    handed to ``open_osfhandle`` as though it were a file.

    **Test steps:**

    * patch ``CreateFileW`` to fail and ``GetLastError`` to report *file not found*;
    * call the opener;
    * check a ``FileNotFoundError`` comes out, and nothing was adopted.
    """
    mocker.patch(f"{MODULE}.CREATE_FILE", return_value=returned)
    mocker.patch(f"{MODULE}.ctypes.get_last_error", return_value=2)  # ERROR_FILE_NOT_FOUND
    adopt = mocker.patch(f"{MODULE}.msvcrt.open_osfhandle")
    with raises(FileNotFoundError):
        shared_read.shared_read_open(PATH)
    adopt.assert_not_called()
