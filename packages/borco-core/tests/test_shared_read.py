"""Tests for the non-locking reader (#241).

Two kinds, deliberately. The **dispatch** is mocked like everything else in this suite: which opener
runs on which platform is this module's own logic and a fake proves it. The **share mode** is not --
it is a fact about the running operating system, and a mocked ``CreateFileW`` would only prove that
the mock was called. Those tests carry ``disk`` (real I/O, no mocks) and, where the behaviour is
Windows', ``windows`` as well.
"""

from pathlib import Path
from typing import Final

from borco_core import shared_read_open
from pytest import mark, raises
from pytest_mock import MockerFixture

WINDOWS_OPENER: Final = "borco_core.platforms.windows.shared_read.shared_read_open"
"""Where the Windows branch lands. Patched at its source module rather than at an import in
:mod:`borco_core.shared_read`, which has none -- the import happens inside the call."""

PAYLOAD: Final = b"rehuco content bytes"
"""What the real-disk tests write and read back, short enough to arrive in one read."""

SHARING_VIOLATION: Final = 32
"""``ERROR_SHARING_VIOLATION`` -- what Windows raises when a handle's share mode forbids the rename."""

ACCESS_DENIED: Final = 5
"""``ERROR_ACCESS_DENIED`` -- what Windows raises for a *directory* rename with a handle open beneath
it, whatever share mode that handle asked for."""


# region dispatch
def test_a_plain_open_is_used_off_windows(mocker: MockerFixture) -> None:
    """Everywhere but Windows the file is opened the ordinary way.

    POSIX has nothing to withhold: a rename there operates on a directory entry and an open descriptor
    never notices, so there is nothing for a special opener to buy.

    **Test steps:**

    * force ``sys.platform`` to Linux and patch ``Path.open``;
    * call :func:`~borco_core.shared_read_open`;
    * check the file was opened in binary read mode, and that handle returned.
    """
    mocker.patch("borco_core.shared_read.sys.platform", "linux")
    opened = mocker.patch.object(Path, "open")
    assert shared_read_open(Path("/fake/content.zip")) is opened.return_value
    opened.assert_called_once_with("rb")


@mark.windows
def test_windows_goes_through_the_share_delete_opener(mocker: MockerFixture) -> None:
    """On Windows the call is handed to the ``CreateFileW`` opener instead.

    **Test steps:**

    * patch the Windows opener;
    * call :func:`~borco_core.shared_read_open`;
    * check it was asked for the path, and its handle returned.
    """
    opener = mocker.patch(WINDOWS_OPENER)
    path = Path("C:/fake/content.zip")
    assert shared_read_open(path) is opener.return_value
    opener.assert_called_once_with(path)


# endregion


# region the share mode itself
@mark.disk
def test_a_file_can_be_renamed_while_it_is_being_read(tmp_path: Path) -> None:
    """A file opened this way is not locked: it can be renamed with the read half-finished, and the
    handle goes on reading the same bytes (#241).

    The property the whole design rests on for a **file-scoped** resource
    ([[data-model#resource-scoping]]). Real disk, because the share mode is the operating system's
    answer and not this module's.

    **Test steps:**

    * write a file and open it through :func:`~borco_core.shared_read_open`;
    * read one byte, rename the file, then read the rest;
    * check the rename succeeded and the bytes are the ones written.
    """
    source = tmp_path / "content.zip"
    source.write_bytes(PAYLOAD)
    with shared_read_open(source) as handle:
        first = handle.read(1)
        source.rename(tmp_path / "renamed.zip")
        rest = handle.read()
    assert first + rest == PAYLOAD
    assert (tmp_path / "renamed.zip").exists()


@mark.disk
@mark.windows
def test_a_plain_open_blocks_the_same_rename(tmp_path: Path) -> None:
    """``open(path, "rb")`` *is* the lock this module exists to avoid (#241).

    The contrast that makes the test above mean something: the CRT opens with ``_SH_DENYNO``, which
    withholds ``FILE_SHARE_DELETE``, and on Windows a rename needs it.

    **Test steps:**

    * write a file and open it with the built-in ``open``;
    * try to rename it;
    * check Windows refuses with ``ERROR_SHARING_VIOLATION``.
    """
    source = tmp_path / "content.zip"
    source.write_bytes(PAYLOAD)
    with source.open("rb"):
        with raises(OSError) as refusal:
            source.rename(tmp_path / "renamed.zip")
    assert refusal.value.winerror == SHARING_VIOLATION  # pyright: ignore[reportAttributeAccessIssue]


@mark.disk
@mark.windows
def test_no_share_mode_lets_the_directory_above_be_renamed(tmp_path: Path) -> None:
    """Sharing everything still does not let a **directory** be renamed while a file under it is open.

    This is why #241 is a cooperative protocol and not a better opener: NTFS refuses on the strength of
    the subtree, not of the child handle's flags, and a directory-scoped ``info.rehu``
    ([[data-model#resource-scoping]]) is the common case. Recorded as a test rather than as a note, so
    the day the rule changes is the day the suite says so.

    **Test steps:**

    * write a file inside a directory and open it through :func:`~borco_core.shared_read_open`;
    * try to rename the directory;
    * check Windows refuses with ``ERROR_ACCESS_DENIED``.
    """
    directory = tmp_path / "resource"
    directory.mkdir()
    (directory / "content.zip").write_bytes(PAYLOAD)
    with shared_read_open(directory / "content.zip"):
        with raises(OSError) as refusal:
            directory.rename(tmp_path / "renamed")
    assert refusal.value.winerror == ACCESS_DENIED  # pyright: ignore[reportAttributeAccessIssue]


# endregion
