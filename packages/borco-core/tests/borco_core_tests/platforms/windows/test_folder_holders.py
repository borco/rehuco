"""Tests for the handle walk behind :func:`borco_core.folder_holders` (#505).

Windows-only, like the module: ``ntdll`` and ``kernel32`` are bound at import, so the whole file skips off Windows
the way the Restart Manager tests beside it do. What the walk finds on a real machine is measured in
``tests/test_folder_holders.py``; this covers each step's refusals, and a name that never answers -- which a real
machine produces only when some program happens to have a synchronous request pending.
"""

import ctypes
import threading
from collections.abc import Callable
from ctypes import wintypes
from pathlib import Path
from typing import Any, Final
from unittest.mock import MagicMock

import pytest
from pytest import fixture, raises

pytest.importorskip("msvcrt")  # a Windows-only module stands in for "is this Windows" -- see the docstring

# these must follow the skip above, or collection fails off Windows -- hence the suppressions
from borco_core import FileHolder  # noqa: E402  # pylint: disable=wrong-import-position
from borco_core.platforms.windows import (  # noqa: E402  # pylint: disable=wrong-import-position
    folder_holders,
    shared_read,
)
from pytest_mock import MockerFixture  # noqa: E402  # pylint: disable=wrong-import-position

MODULE: Final = "borco_core.platforms.windows.folder_holders"

FOLDER: Final = Path("W:/library/pack")
TARGET: Final = r"\Device\Mup\host\share\library\pack"
PROBE: Final = 0x44
"""This process's own handle on the folder."""
FILE_TYPE: Final = 42
OTHER_TYPE: Final = 7
OWN_PID: Final = 100
SHELL_PID: Final = 7
EXPLORER_PID: Final = 9
LOCKED_PID: Final = 11
PROCESS: Final = 0x500
"""The handle a process is opened through."""

RELEASE_TIMEOUT: Final = 5.0


def entry(pid: int, handle: int, object_type: int = FILE_TYPE) -> folder_holders.HandleEntry:
    """One row of the handle list.

    :param pid: its process.
    :param handle: its handle value.
    :param object_type: its object type.
    :returns: the row.
    """
    row = folder_holders.HandleEntry()
    row.UniqueProcessId = pid
    row.HandleValue = handle
    row.ObjectTypeIndex = object_type
    return row


@fixture(name="walk")
def fixture_walk(mocker: MockerFixture) -> dict[str, MagicMock]:
    """Patch every step of :func:`folder_holders.folder_holders` around one folder: a shell with two handles in it,
    Explorer with one on it, a process that cannot be opened, a handle elsewhere, and this process's own probe.

    :param mocker: pytest-mock fixture.
    :returns: the stand-ins, by step.
    """
    names = {
        (SHELL_PID, 1): TARGET + "\\",
        (SHELL_PID, 2): TARGET + "\\info00.jpg",
        (EXPLORER_PID, 3): r"\Device\Mup\host\share\library\pack-old",
        (EXPLORER_PID, 4): TARGET,
    }
    entries = [
        entry(OWN_PID, PROBE),
        entry(OWN_PID, 5),
        entry(SHELL_PID, 0x90, OTHER_TYPE),
        entry(SHELL_PID, 1),
        entry(SHELL_PID, 2),
        entry(LOCKED_PID, 6),
        entry(EXPLORER_PID, 3),
        entry(EXPLORER_PID, 4),
    ]
    mocker.patch(f"{MODULE}.os.getpid", return_value=OWN_PID)
    return {
        "open_folder": mocker.patch(f"{MODULE}.open_folder", return_value=PROBE),
        "nt_path": mocker.patch(f"{MODULE}.nt_path", return_value=TARGET.upper()),
        "list": mocker.patch(f"{MODULE}.list_handles", return_value=entries),
        "open": mocker.patch(
            f"{MODULE}.OPEN_PROCESS", side_effect=lambda _access, _inherit, pid: None if pid == LOCKED_PID else pid
        ),
        "name": mocker.patch(f"{MODULE}.handle_name", side_effect=lambda process, handle: names.get((process, handle))),
        "process_name": mocker.patch(
            f"{MODULE}.process_name", side_effect=lambda process: {SHELL_PID: "bash.exe"}.get(process, "explorer.exe")
        ),
        "close": mocker.patch(f"{MODULE}.CLOSE_HANDLE", return_value=True),
    }


def test_every_process_at_or_under_the_folder_is_named_once(walk: dict[str, MagicMock]) -> None:
    """Each process with a file handle at or under the folder is named once, case aside; a handle elsewhere, another
    object type, this process's own and a process that cannot be opened are not.

    **Test steps:**

    * walk the stand-in table, the folder's name in another case than the handles'
    * verify the shell and Explorer are named once each, in table order
    * verify the shell's second handle was never asked about, nor this process's own or another type's
    * verify the probe and every opened process were closed, and the unopenable one never was
    """
    assert folder_holders.folder_holders(FOLDER) == (
        FileHolder(SHELL_PID, "bash.exe"),
        FileHolder(EXPLORER_PID, "explorer.exe"),
    )

    asked = [call.args for call in walk["name"].call_args_list]
    assert asked == [(SHELL_PID, 1), (0, 6), (EXPLORER_PID, 3), (EXPLORER_PID, 4)]
    closed = [call.args[0] for call in walk["close"].call_args_list]
    assert closed == [PROBE, SHELL_PID, EXPLORER_PID]


def test_a_table_without_the_probe_is_a_refusal(walk: dict[str, MagicMock]) -> None:
    """Without this process's own handle in the list there is no telling which type is a file: a refusal, never a
    guess -- and the probe is still closed.

    **Test steps:**

    * take the probe out of the table, and walk it, expecting an ``OSError``
    * verify the probe was closed and no process was opened
    """
    walk["list"].return_value = walk["list"].return_value[1:]

    with raises(OSError, match="not in the handle list"):
        folder_holders.folder_holders(FOLDER)

    walk["close"].assert_called_once_with(PROBE)
    walk["open"].assert_not_called()


def test_a_folder_whose_name_cannot_be_read_still_closes_its_probe(walk: dict[str, MagicMock]) -> None:
    """A refused name ends the walk before it starts, with the probe closed.

    **Test steps:**

    * make reading the folder's name fail, and walk, expecting the ``OSError``
    * verify the probe was closed and the table never read
    """
    walk["nt_path"].side_effect = OSError("refused")

    with raises(OSError, match="refused"):
        folder_holders.folder_holders(FOLDER)

    walk["close"].assert_called_once_with(PROBE)
    walk["list"].assert_not_called()


def test_a_folder_that_cannot_be_opened_is_a_refusal(mocker: MockerFixture) -> None:
    """A missing or unreachable folder is the ``OSError`` for its code.

    **Test steps:**

    * make opening the folder return the invalid handle, with the last error saying not found
    * open it, expecting that error
    """
    mocker.patch(f"{MODULE}.CREATE_FILE", return_value=shared_read.INVALID_HANDLE_VALUE)
    mocker.patch(f"{MODULE}.ctypes.get_last_error", return_value=3)

    with raises(FileNotFoundError):
        folder_holders.open_folder(FOLDER)


def test_a_folder_opens_shared_as_a_directory(mocker: MockerFixture) -> None:
    """The probe is opened shared with everyone and as a directory, so it is no holder in anyone's way.

    **Test steps:**

    * open the folder through a stand-in
    * verify the handle came back and the sharing and directory flags were asked for
    """
    create = mocker.patch(f"{MODULE}.CREATE_FILE", return_value=PROBE)

    assert folder_holders.open_folder(FOLDER) == PROBE

    arguments = create.call_args.args
    assert arguments[2] == shared_read.SHARE_EVERYTHING
    assert arguments[5] == folder_holders.FILE_FLAG_BACKUP_SEMANTICS


def test_a_name_that_cannot_be_read_is_a_refusal(mocker: MockerFixture) -> None:
    """A handle whose NT name does not come back is the ``OSError`` for the last error.

    **Test steps:**

    * make the name call answer nothing, and read it, expecting the error
    """
    mocker.patch(f"{MODULE}.GET_FINAL_PATH_NAME_BY_HANDLE", return_value=0)
    mocker.patch(f"{MODULE}.ctypes.get_last_error", return_value=5)

    with raises(PermissionError):
        folder_holders.nt_path(PROBE)


def table_answers(*rows: folder_holders.HandleEntry, room: int) -> Callable[..., int]:
    """An ``NtQuerySystemInformation`` stand-in that wants ``room`` bytes, then writes ``rows`` into a buffer that big.

    :param rows: the handles to list.
    :param room: the size it asks for.
    :returns: the side effect.
    """
    header = 2 * ctypes.sizeof(ctypes.c_size_t)

    def query(_class: int, buffer: Any, size: int, needed: Any) -> int:
        if size < room:
            needed._obj.value = room  # pylint: disable=protected-access
            return folder_holders.STATUS_INFO_LENGTH_MISMATCH
        ctypes.c_size_t.from_buffer(buffer).value = len(rows)
        for index, row in enumerate(rows):
            ctypes.memmove(
                ctypes.addressof(buffer) + header + index * ctypes.sizeof(row),
                ctypes.addressof(row),
                ctypes.sizeof(row),
            )
        return folder_holders.STATUS_SUCCESS

    return query


def test_the_table_grows_until_it_fits(mocker: MockerFixture) -> None:
    """A table larger than the first buffer is read again into one as large as it said.

    **Test steps:**

    * make the table ask for more than the first buffer
    * list it, and verify the rows came back and the table was asked twice
    """
    rows = (entry(SHELL_PID, 1), entry(EXPLORER_PID, 4))
    query = mocker.patch(
        f"{MODULE}.NT_QUERY_SYSTEM_INFORMATION",
        side_effect=table_answers(*rows, room=folder_holders.HANDLES_BUFFER * 3),
    )

    listed = folder_holders.list_handles()

    assert [(row.UniqueProcessId, row.HandleValue) for row in listed] == [(SHELL_PID, 1), (EXPLORER_PID, 4)]
    assert query.call_count == 2


def test_a_refused_table_is_a_refusal(mocker: MockerFixture) -> None:
    """Any other status is an ``OSError`` naming it.

    **Test steps:**

    * make the table answer access denied, and list it, expecting the error with the status
    """
    mocker.patch(f"{MODULE}.NT_QUERY_SYSTEM_INFORMATION", return_value=0xC0000022 - (1 << 32))

    with raises(OSError, match="0xC0000022"):
        folder_holders.list_handles()


@fixture(name="copying")
def fixture_copying(mocker: MockerFixture) -> dict[str, MagicMock]:
    """Patch copying a handle: it copies as handle ``0x700``, is a disk file, and is named at once.

    :param mocker: pytest-mock fixture.
    :returns: the stand-ins, by step.
    """

    def duplicate(_source: Any, _handle: Any, _target: Any, copy: Any, *_rest: Any) -> bool:
        copy._obj.value = 0x700  # pylint: disable=protected-access
        return True

    return {
        "duplicate": mocker.patch(f"{MODULE}.DUPLICATE_HANDLE", side_effect=duplicate),
        "current": mocker.patch(f"{MODULE}.GET_CURRENT_PROCESS", return_value=0x1),
        "type": mocker.patch(f"{MODULE}.GET_FILE_TYPE", return_value=folder_holders.FILE_TYPE_DISK),
        "name": mocker.patch(f"{MODULE}.object_name", return_value=TARGET),
        "close": mocker.patch(f"{MODULE}.CLOSE_HANDLE", return_value=True),
    }


def test_a_copied_disk_handle_is_named_and_closed(copying: dict[str, MagicMock]) -> None:
    """A handle copied in, found to be a disk file, is named and its copy closed.

    **Test steps:**

    * name another process's handle
    * verify the name came back and the copy was closed
    """
    assert folder_holders.handle_name(PROCESS, 6) == TARGET

    assert copying["name"].call_args.args[0].value == 0x700
    copying["close"].assert_called_once()


def test_a_process_not_opened_has_nothing_named(copying: dict[str, MagicMock]) -> None:
    """A process that could not be opened has no handle to copy.

    **Test steps:**

    * name a handle of a process given as ``0``, and verify nothing was copied
    """
    assert folder_holders.handle_name(0, 6) is None

    copying["duplicate"].assert_not_called()


def test_a_handle_that_will_not_copy_has_no_name(copying: dict[str, MagicMock]) -> None:
    """A handle the process will not share has no name and nothing to close.

    **Test steps:**

    * refuse the copy, and verify no name and nothing closed
    """
    copying["duplicate"].side_effect = None
    copying["duplicate"].return_value = False

    assert folder_holders.handle_name(PROCESS, 6) is None

    copying["close"].assert_not_called()


def test_a_handle_that_is_no_disk_file_is_never_named(copying: dict[str, MagicMock]) -> None:
    """A pipe's or a console's name can block forever, so only a disk file is asked; the others' copies are closed.

    **Test steps:**

    * make the copy a pipe, and verify no name was asked and the copy was closed
    """
    copying["type"].return_value = 3  # FILE_TYPE_PIPE

    assert folder_holders.handle_name(PROCESS, 6) is None

    copying["name"].assert_not_called()
    copying["close"].assert_called_once()


def test_a_name_that_never_answers_is_skipped_and_its_copy_kept(
    copying: dict[str, MagicMock], mocker: MockerFixture
) -> None:
    """A name stuck behind a pending request is given up on at the deadline, and its copy left open for the thread
    still using it.

    **Test steps:**

    * make the name block until released, with a short deadline
    * name the handle, and verify it gave up with no name and closed nothing
    * release the stuck name
    """
    release = threading.Event()
    copying["name"].side_effect = lambda _handle: release.wait(RELEASE_TIMEOUT) and TARGET
    mocker.patch(f"{MODULE}.NAME_DEADLINE", 0.05)

    try:
        assert folder_holders.handle_name(PROCESS, 6) is None
        copying["close"].assert_not_called()
    finally:
        release.set()


def names_answer(name: str | None, status: int = folder_holders.STATUS_SUCCESS) -> Callable[..., int]:
    """An ``NtQueryObject`` stand-in writing ``name`` as the buffer's ``UNICODE_STRING``, its text after the header.

    :param name: the name, or ``None`` for a null text pointer.
    :param status: what the call returns.
    :returns: the side effect.
    """

    def query(_handle: int, _class: int, buffer: Any, _size: int, _needed: Any) -> int:
        header = folder_holders.UnicodeString.from_buffer(buffer)
        if name is not None:
            text = ctypes.create_unicode_buffer(name)
            offset = ctypes.sizeof(folder_holders.UnicodeString)
            ctypes.memmove(ctypes.addressof(buffer) + offset, text, ctypes.sizeof(text))
            header.Length = len(name) * ctypes.sizeof(ctypes.c_wchar)
            header.Buffer = ctypes.addressof(buffer) + offset
        return status

    return query


def test_an_object_name_is_read_from_its_unicode_string(mocker: MockerFixture) -> None:
    """The name is the text the ``UNICODE_STRING`` points at, as long as it says.

    **Test steps:**

    * make the query write a name, and verify it is read back whole
    """
    mocker.patch(f"{MODULE}.NT_QUERY_OBJECT", side_effect=names_answer(TARGET))

    assert folder_holders.object_name(wintypes.HANDLE(0x700)) == TARGET


def test_an_object_without_a_name_or_a_refused_query_has_none(mocker: MockerFixture) -> None:
    """A handle with no name, and a refused query, both answer ``None``.

    **Test steps:**

    * make the query answer a null text pointer, then a failure status
    * verify both read as no name
    """
    query = mocker.patch(f"{MODULE}.NT_QUERY_OBJECT", side_effect=names_answer(None))
    assert folder_holders.object_name(wintypes.HANDLE(0x700)) is None

    query.side_effect = names_answer(TARGET, status=0xC0000008 - (1 << 32))
    assert folder_holders.object_name(wintypes.HANDLE(0x700)) is None


def test_a_process_is_named_by_its_executable(mocker: MockerFixture) -> None:
    """A process is named by its executable's file name; one whose name cannot be read is ``?``.

    **Test steps:**

    * make the image name a full path, and verify only its file name comes back
    * make it fail, and verify ``?``
    """

    def image(_process: int, _flags: int, buffer: Any, _size: Any) -> bool:
        buffer.value = r"C:\Program Files\Git\usr\bin\bash.exe"
        return True

    query = mocker.patch(f"{MODULE}.QUERY_FULL_PROCESS_IMAGE_NAME", side_effect=image)
    assert folder_holders.process_name(PROCESS) == "bash.exe"

    query.side_effect = None
    query.return_value = False
    assert folder_holders.process_name(PROCESS) == "?"
