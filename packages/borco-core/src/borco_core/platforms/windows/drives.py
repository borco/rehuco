"""What kind of drive a Windows drive letter is, and which share a mapped one points at -- without touching the
network.

Windows-only, like every other module under ``platforms/windows/``: only ever imported inside
:func:`borco_core.path_presence.device_of`'s ``if sys.platform == "win32":`` branch.

**Both calls answer from local state and return at once, for a drive letter.** Measured on Windows 11 / Python 3.14.6
with a mapped drive (``W:`` -> ``\\\\esprimo\\tutorials``, the server up), a letter nothing is mapped to, and the fixed
system drive: ``GetDriveTypeW`` takes under a millisecond on all three, and ``WNetGetConnectionW`` answers from the
connection table. A drive letter whose server is *off* still says "remote" immediately.

**Never call :func:`drive_type` with a UNC root** (``\\\\host\\share\\``). The same call on
``\\\\192.168.1.249\\tutorials\\``, a host that was switched off, blocked for **21 s** before answering "no root
directory" -- it resolves the host to find out what the share is. A UNC path is remote by its form, and
:func:`~borco_core.path_presence.device_of` never asks.
"""

import ctypes
from ctypes import wintypes
from typing import Final

KERNEL32: Final = ctypes.WinDLL("kernel32", use_last_error=True)
MPR: Final = ctypes.WinDLL("mpr", use_last_error=True)

DRIVE_NO_ROOT_DIR: Final = 1
"""``GetDriveTypeW``: nothing is there -- a letter nothing is mapped to or an empty reader."""
DRIVE_REMOVABLE: Final = 2
DRIVE_FIXED: Final = 3
DRIVE_REMOTE: Final = 4
DRIVE_CDROM: Final = 5
DRIVE_RAMDISK: Final = 6

GET_DRIVE_TYPE: Final = KERNEL32.GetDriveTypeW
GET_DRIVE_TYPE.argtypes = (wintypes.LPCWSTR,)
GET_DRIVE_TYPE.restype = wintypes.UINT

WNET_GET_CONNECTION: Final = MPR.WNetGetConnectionW
WNET_GET_CONNECTION.argtypes = (wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
WNET_GET_CONNECTION.restype = wintypes.DWORD

GET_LOGICAL_DRIVES: Final = KERNEL32.GetLogicalDrives
GET_LOGICAL_DRIVES.argtypes = ()
GET_LOGICAL_DRIVES.restype = wintypes.DWORD

LETTER_COUNT: Final = 26

NO_ERROR: Final = 0
MAXIMUM_SHARE_NAME_LENGTH: Final = 1024
"""Characters reserved for the share a drive maps to -- ``MAX_PATH`` plus room for a long host name."""


def drive_type(root: str) -> int:
    """The ``DRIVE_*`` value Windows gives the drive letter ``root`` (``"C:\\\\"``).

    :param root: a drive-letter root, never a UNC one (see the module docstring).
    :returns: one of the ``DRIVE_*`` constants, or ``0`` when it cannot be determined.
    """
    return int(GET_DRIVE_TYPE(root))


def mapped_share(drive: str) -> str | None:
    """The ``\\\\host\\share`` a mapped drive letter points at.

    :param drive: the letter with its colon (``"W:"``).
    :returns: the share, or ``None`` when the letter is not a mapped network drive.
    """
    buffer = ctypes.create_unicode_buffer(MAXIMUM_SHARE_NAME_LENGTH)
    length = wintypes.DWORD(MAXIMUM_SHARE_NAME_LENGTH)
    if WNET_GET_CONNECTION(drive, buffer, ctypes.byref(length)) != NO_ERROR:
        return None
    return buffer.value or None


def mapped_drives() -> dict[str, str]:
    """Every drive letter mapped to a network share, from local state only.

    :returns: the share (``\\\\host\\share``) of each mapped letter (``"W:"``), in letter order.
    """
    present = int(GET_LOGICAL_DRIVES())
    drives: dict[str, str] = {}
    for index in range(LETTER_COUNT):
        if not present >> index & 1:
            continue
        letter = f"{chr(ord('A') + index)}:"
        if drive_type(f"{letter}\\") != DRIVE_REMOTE:
            continue
        share = mapped_share(letter)
        if share is not None:
            drives[letter] = share
    return drives
