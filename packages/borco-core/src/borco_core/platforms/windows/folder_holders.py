"""Walking every handle on the system for the ones at or under a folder -- what PowerToys File Locksmith does.

The Restart Manager (:mod:`~borco_core.platforms.windows.file_holders`) answers for files only, and the commonest
holder of a folder being renamed holds no file in it: a shell standing in it (its working directory is a handle on
the folder), an Explorer window showing it. Those are only found by asking the kernel for every handle of every
process (``NtQuerySystemInformation``), copying each file handle into this process, and asking its name.

**A name can hang.** Measured on Windows 11 (2026-10-26): of ~6,000 disk handles, one -- a folder watcher with a
synchronous ``ReadDirectoryChangesW`` pending -- never answered ``GetFinalPathNameByHandleW``. ``NtQueryObject``
answers the rest in ~1.8 s for ~169,000 handles, but a synchronous handle with a request in flight can block it
too, so each name is asked on a daemon thread with a deadline (:data:`NAME_DEADLINE`); one that misses it is
skipped and its thread left behind, holding its copy of the handle until the request ends.

**Names are compared in NT form** (``\\Device\\Mup\\host\\share\\...``, ``\\Device\\HarddiskVolume3\\...``), which
is what ``NtQueryObject`` answers with: the folder's own is read the same way, through a handle on it, so a mapped
drive letter and the UNC path it maps to match.

A process this one may not open (an elevated one from an ordinary app, a system service) is skipped: its handles
cannot be copied, which is the same limit File Locksmith has without elevation.

Windows-only, like every other module under ``platforms/windows/``: only ever imported inside
:func:`borco_core.folder_holders.folder_holders`'s ``if sys.platform == "win32":`` branch, with the same function
name, for the reason :mod:`borco_core.platforms.windows.shared_read` gives.
"""

import ctypes
import os
import threading
from ctypes import wintypes
from pathlib import Path
from typing import Final

from ...file_holder import FileHolder

# the folder is opened through the same bound ``CreateFileW`` the non-locking reader uses: one declaration of its
# signature, and the same sharing -- a probe that denied anyone anything would be a holder of its own
from .shared_read import CREATE_FILE, GENERIC_READ, INVALID_HANDLE_VALUE, OPEN_EXISTING, SHARE_EVERYTHING

NTDLL: Final = ctypes.WinDLL("ntdll")
KERNEL32: Final = ctypes.WinDLL("kernel32", use_last_error=True)

NAME_DEADLINE: Final = 0.2
"""How long one handle's name is waited for, in seconds. Every other name came back in well under a millisecond
(6,000 in under two seconds, thread start included); one that takes this long is stuck behind a pending request."""

SYSTEM_EXTENDED_HANDLE_INFORMATION: Final = 64
"""``NtQuerySystemInformation``'s class for every handle of every process, with 64-bit process ids and handles."""

OBJECT_NAME_INFORMATION: Final = 1
"""``NtQueryObject``'s class for an object's name."""

STATUS_SUCCESS: Final = 0
STATUS_INFO_LENGTH_MISMATCH: Final = 0xC0000004 - (1 << 32)
"""``NtQuerySystemInformation``'s answer when the buffer was too small -- as a signed ``NTSTATUS``."""

HANDLES_BUFFER: Final = 1 << 22
"""The first buffer the handle list is read into: 4 MiB, room for ~100,000 handles; doubled until it fits."""

NAME_BUFFER: Final = 4096
"""Bytes for one ``OBJECT_NAME_INFORMATION``: its ``UNICODE_STRING`` header and a name of up to ~2,000 characters."""

FILE_FLAG_BACKUP_SEMANTICS: Final = 0x0200_0000
"""``CreateFileW``: open a directory rather than a file -- how the folder itself is opened to read its NT name."""

VOLUME_NAME_NT: Final = 0x2
"""``GetFinalPathNameByHandleW``: the ``\\Device\\...`` form ``NtQueryObject`` uses."""

PATH_BUFFER: Final = 32_768
"""Characters for the folder's own NT name -- the longest path Windows has."""

PROCESS_DUP_HANDLE: Final = 0x0040
PROCESS_QUERY_LIMITED_INFORMATION: Final = 0x1000
"""``OpenProcess`` rights: copy its handles, and read its executable's name."""

DUPLICATE_SAME_ACCESS: Final = 0x2
FILE_TYPE_DISK: Final = 0x1
"""A copy keeps the original's rights; only a file on a disk or share is named -- a pipe's name can block forever."""


class HandleEntry(ctypes.Structure):  # pylint: disable=too-few-public-methods
    """``SYSTEM_HANDLE_TABLE_ENTRY_INFO_EX``: one handle of one process."""

    _fields_ = (
        ("Object", ctypes.c_void_p),
        ("UniqueProcessId", ctypes.c_size_t),
        ("HandleValue", ctypes.c_size_t),
        ("GrantedAccess", wintypes.ULONG),
        ("CreatorBackTraceIndex", wintypes.USHORT),
        ("ObjectTypeIndex", wintypes.USHORT),
        ("HandleAttributes", wintypes.ULONG),
        ("Reserved", wintypes.ULONG),
    )


class UnicodeString(ctypes.Structure):  # pylint: disable=too-few-public-methods
    """``UNICODE_STRING``, the head of ``OBJECT_NAME_INFORMATION``: a length in bytes and a pointer to the text."""

    _fields_ = (("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT), ("Buffer", ctypes.c_void_p))


NT_QUERY_SYSTEM_INFORMATION: Final = NTDLL.NtQuerySystemInformation
NT_QUERY_SYSTEM_INFORMATION.argtypes = (wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG))
NT_QUERY_SYSTEM_INFORMATION.restype = ctypes.c_long

NT_QUERY_OBJECT: Final = NTDLL.NtQueryObject
NT_QUERY_OBJECT.argtypes = (
    wintypes.HANDLE,
    wintypes.ULONG,
    ctypes.c_void_p,
    wintypes.ULONG,
    ctypes.POINTER(wintypes.ULONG),
)
NT_QUERY_OBJECT.restype = ctypes.c_long

GET_FINAL_PATH_NAME_BY_HANDLE: Final = KERNEL32.GetFinalPathNameByHandleW
GET_FINAL_PATH_NAME_BY_HANDLE.argtypes = (wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD)
GET_FINAL_PATH_NAME_BY_HANDLE.restype = wintypes.DWORD

OPEN_PROCESS: Final = KERNEL32.OpenProcess
OPEN_PROCESS.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
OPEN_PROCESS.restype = wintypes.HANDLE

GET_CURRENT_PROCESS: Final = KERNEL32.GetCurrentProcess
GET_CURRENT_PROCESS.argtypes = ()
GET_CURRENT_PROCESS.restype = wintypes.HANDLE

DUPLICATE_HANDLE: Final = KERNEL32.DuplicateHandle
DUPLICATE_HANDLE.argtypes = (
    wintypes.HANDLE,
    wintypes.HANDLE,
    wintypes.HANDLE,
    ctypes.POINTER(wintypes.HANDLE),
    wintypes.DWORD,
    wintypes.BOOL,
    wintypes.DWORD,
)
DUPLICATE_HANDLE.restype = wintypes.BOOL

GET_FILE_TYPE: Final = KERNEL32.GetFileType
GET_FILE_TYPE.argtypes = (wintypes.HANDLE,)
GET_FILE_TYPE.restype = wintypes.DWORD

QUERY_FULL_PROCESS_IMAGE_NAME: Final = KERNEL32.QueryFullProcessImageNameW
QUERY_FULL_PROCESS_IMAGE_NAME.argtypes = (
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
)
QUERY_FULL_PROCESS_IMAGE_NAME.restype = wintypes.BOOL

CLOSE_HANDLE: Final = KERNEL32.CloseHandle
CLOSE_HANDLE.argtypes = (wintypes.HANDLE,)
CLOSE_HANDLE.restype = wintypes.BOOL
"""Every call bound once with its signature declared, and read by name at call time so a test can replace each with
a stand-in -- the same shape :mod:`~borco_core.platforms.windows.file_holders` has."""


def folder_holders(folder: Path) -> tuple[FileHolder, ...]:
    """The processes other than this one with a handle on ``folder`` or anything under it; see
    :func:`borco_core.folder_holders.folder_holders`.

    :param folder: the folder.
    :returns: the holders, each once, named by their executable, in the order their handles were listed.
    :raises OSError: the folder could not be opened, or the handle list could not be read.
    """
    own = os.getpid()
    probe = open_folder(folder)
    try:
        target = nt_path(probe).casefold()
        entries = list_handles()
        # a handle's type is a number that differs between Windows builds: this process's own handle on the folder
        # is a file handle, and says which number that is on this one
        file_type = next(
            (entry.ObjectTypeIndex for entry in entries if entry.UniqueProcessId == own and entry.HandleValue == probe),
            None,
        )
        if file_type is None:
            raise OSError("This process's own handle on the folder is not in the handle list.")
    finally:
        CLOSE_HANDLE(probe)
    processes: dict[int, int] = {}
    try:
        holders: dict[int, FileHolder] = {}
        for entry in entries:
            pid = entry.UniqueProcessId
            if entry.ObjectTypeIndex != file_type or pid == own or pid in holders:
                continue
            if pid not in processes:
                processes[pid] = OPEN_PROCESS(PROCESS_DUP_HANDLE | PROCESS_QUERY_LIMITED_INFORMATION, False, pid) or 0
            name = handle_name(processes[pid], entry.HandleValue)
            if name is not None and is_at_or_under(name.casefold(), target):
                holders[pid] = FileHolder(pid, process_name(processes[pid]))
        return tuple(holders.values())
    finally:
        for process in processes.values():
            if process:
                CLOSE_HANDLE(process)


def open_folder(folder: Path) -> int:
    """Open a handle on the folder itself, to read its name and find this build's file handle type by.

    :param folder: the folder.
    :returns: the handle; the caller closes it.
    :raises OSError: it could not be opened.
    """
    handle = CREATE_FILE(
        str(folder), GENERIC_READ, SHARE_EVERYTHING, None, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS, None
    )
    if handle is None or handle == INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    return handle


def nt_path(handle: int) -> str:
    """The NT name of the file or folder ``handle`` is open on.

    :param handle: a handle of this process.
    :returns: the ``\\Device\\...`` name.
    :raises OSError: it could not be read.
    """
    buffer = ctypes.create_unicode_buffer(PATH_BUFFER)
    length = GET_FINAL_PATH_NAME_BY_HANDLE(handle, buffer, PATH_BUFFER, VOLUME_NAME_NT)
    if not 0 < length < PATH_BUFFER:
        raise ctypes.WinError(ctypes.get_last_error())
    return buffer.value


def list_handles() -> list[HandleEntry]:
    """Every handle of every process, growing the buffer until the list fits.

    :returns: the handles.
    :raises OSError: the list could not be read.
    """
    size = HANDLES_BUFFER
    while True:
        buffer = ctypes.create_string_buffer(size)
        needed = wintypes.ULONG(0)
        status = NT_QUERY_SYSTEM_INFORMATION(SYSTEM_EXTENDED_HANDLE_INFORMATION, buffer, size, ctypes.byref(needed))
        if status == STATUS_INFO_LENGTH_MISMATCH:
            size = max(size * 2, needed.value)
            continue
        if status != STATUS_SUCCESS:
            raise OSError(f"NtQuerySystemInformation failed: 0x{status & 0xFFFF_FFFF:08X}")
        count = ctypes.c_size_t.from_buffer(buffer).value
        return list((HandleEntry * count).from_buffer(buffer, 2 * ctypes.sizeof(ctypes.c_size_t)))


def handle_name(process: int, handle: int) -> str | None:
    """The NT name of another process's handle, when it is a file on a disk or share and answers in time.

    :param process: the process, opened to copy its handles -- ``0`` when it could not be.
    :param handle: its handle.
    :returns: the name, or ``None`` for a handle that could not be copied, is no disk file, or did not answer.
    """
    if not process:
        return None
    copy = wintypes.HANDLE()
    if not DUPLICATE_HANDLE(
        process, handle, GET_CURRENT_PROCESS(), ctypes.byref(copy), 0, False, DUPLICATE_SAME_ACCESS
    ):
        return None
    if GET_FILE_TYPE(copy) != FILE_TYPE_DISK:
        CLOSE_HANDLE(copy)
        return None
    answered, name = name_within_deadline(copy)
    if answered:
        # a copy whose name did not come back is left open: the thread still asking is using it
        CLOSE_HANDLE(copy)
    return name


def name_within_deadline(handle: wintypes.HANDLE) -> tuple[bool, str | None]:
    """Ask a handle's name on a daemon thread, waiting at most :data:`NAME_DEADLINE`.

    :param handle: a handle of this process.
    :returns: whether it answered, and the name it answered with (``None`` when it had none).
    """
    answer: list[str | None] = []
    worker = threading.Thread(target=lambda: answer.append(object_name(handle)), daemon=True)
    worker.start()
    worker.join(NAME_DEADLINE)
    return (False, None) if worker.is_alive() else (True, answer[0])


def object_name(handle: wintypes.HANDLE) -> str | None:
    """``NtQueryObject``'s name for a handle. Can block -- see the module docstring.

    :param handle: a handle of this process.
    :returns: the name, or ``None`` when it has none or could not be read.
    """
    buffer = ctypes.create_string_buffer(NAME_BUFFER)
    needed = wintypes.ULONG(0)
    if NT_QUERY_OBJECT(handle, OBJECT_NAME_INFORMATION, buffer, NAME_BUFFER, ctypes.byref(needed)) != STATUS_SUCCESS:
        return None
    name = UnicodeString.from_buffer(buffer)
    return ctypes.wstring_at(name.Buffer, name.Length // 2) if name.Buffer else None


def is_at_or_under(name: str, target: str) -> bool:
    """Whether a handle's name is the folder's, or names something beneath it. Both already case-folded.

    :param name: the handle's NT name.
    :param target: the folder's NT name.
    :returns: whether it is the folder or under it -- a working directory's name, which ends with a separator,
        among the latter.
    """
    return name == target or name.startswith(target + "\\")


def process_name(process: int) -> str:
    """A process's executable name, as File Locksmith shows it (``bash.exe``).

    :param process: the process, opened to read its name.
    :returns: the name, or ``"?"`` when it could not be read.
    """
    size = wintypes.DWORD(PATH_BUFFER)
    buffer = ctypes.create_unicode_buffer(PATH_BUFFER)
    if not QUERY_FULL_PROCESS_IMAGE_NAME(process, 0, buffer, ctypes.byref(size)):
        return "?"
    return Path(buffer.value).name
