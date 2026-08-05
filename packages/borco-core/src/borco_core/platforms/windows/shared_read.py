"""Opening a file for reading **without** claiming the right to stop anyone renaming or deleting it.

Windows decides sharing at open time, and Python's ``open`` picks the wrong answer for a background
reader. ``open(path, "rb")`` reaches the CRT's ``_wsopen_s`` with ``_SH_DENYNO``, which is
``FILE_SHARE_READ | FILE_SHARE_WRITE`` and, crucially, **not** ``FILE_SHARE_DELETE`` -- so while the
handle is open, renaming or deleting that file fails with ``WinError 32``. There is no flag on
``open`` that changes it: the share mode is not exposed, which is why this goes to ``CreateFileW``
directly and hands the resulting handle to the CRT afterwards.

Measured on Windows 11 / Python 3.14.6, holding one handle and renaming three ways:

===============================================  ===============  ================  ==============
handle held while renaming                       the file itself  its directory     the root above
===============================================  ===============  ================  ==============
none (baseline)                                  OK               OK                OK
``open(path, "rb")``                             WinError 32      WinError 5        WinError 5
``CreateFileW``, no ``FILE_SHARE_DELETE``        WinError 32      WinError 5        WinError 5
``CreateFileW`` + ``FILE_SHARE_DELETE``          **OK**           WinError 5        WinError 5
===============================================  ===============  ================  ==============

So this fixes the **file-scoped** case outright -- the file is renamed under the open handle and the
handle goes on reading the same bytes -- and fixes nothing about a **directory** rename. That is not a
share mode this is missing: NTFS refuses to rename a directory while any handle is open anywhere
beneath it, whatever flags that handle was opened with. Renaming a directory out from under a reader
needs the reader's cooperation, and that lives a layer up
(:mod:`rehuco_core.rename_coordination`); this is the half of the problem an opener can solve.

Windows-only, like every other module under ``platforms/windows/``: only ever imported inside
:func:`borco_core.shared_read_open`'s ``if sys.platform == "win32":`` branch. It carries the **same
function name** as the caller it stands behind, because it is the same operation -- the caller aliases
it on import, which is what says *whose* implementation this one is without inventing a second word
for one idea.
"""

import ctypes
import msvcrt
import os
from ctypes import wintypes
from io import BufferedReader
from pathlib import Path
from typing import Final

KERNEL32: Final = ctypes.WinDLL("kernel32", use_last_error=True)
"""``kernel32`` with thread-local error capture on, so :func:`ctypes.get_last_error` reports the
failure of *this* call rather than whatever last touched the process-wide ``GetLastError``."""

GENERIC_READ: Final = 0x8000_0000
"""``CreateFileW`` desired access: read the bytes, nothing more."""

FILE_SHARE_READ: Final = 0x0000_0001
FILE_SHARE_WRITE: Final = 0x0000_0002
FILE_SHARE_DELETE: Final = 0x0000_0004
"""The three sharing rights. ``DELETE`` is the one that matters and the one ``open`` does not ask for:
on Windows a rename **is** a delete right on the source, so withholding it is what turns a background
read into a lock."""

SHARE_EVERYTHING: Final = FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE
"""What this opener asks for: deny nobody anything. A reader has no business refusing another process
-- or another thread of this one -- the right to move the file it happens to be reading."""

OPEN_EXISTING: Final = 3
"""``CreateFileW`` creation disposition: fail if the file is not already there. Never create."""

FILE_ATTRIBUTE_NORMAL: Final = 0x0000_0080
"""``CreateFileW`` flags: no caching hints, so the read behaves like any other."""

INVALID_HANDLE_VALUE: Final = (1 << (ctypes.sizeof(ctypes.c_void_p) * 8)) - 1
"""What ``CreateFileW`` returns on failure: ``-1`` as an unsigned pointer.

Computed from the pointer width rather than written out, because the literal is ``0xFFFFFFFF`` on a
32-bit build and ``0xFFFFFFFFFFFFFFFF`` on a 64-bit one -- and ``ctypes`` hands the handle back as an
unsigned integer, so the sign that would have made one constant do for both is already gone."""

CREATE_FILE: Final = KERNEL32.CreateFileW
"""``CreateFileW``, with its signature declared once below.

Bound at module scope rather than fetched per call so the ``argtypes``/``restype`` declaration happens
once -- and, because :func:`shared_read_open` reads this name at call time, so a test can replace the
whole Win32 call with a stand-in."""

CREATE_FILE.argtypes = (
    wintypes.LPCWSTR,  # lpFileName
    wintypes.DWORD,  # dwDesiredAccess
    wintypes.DWORD,  # dwShareMode
    wintypes.LPVOID,  # lpSecurityAttributes
    wintypes.DWORD,  # dwCreationDisposition
    wintypes.DWORD,  # dwFlagsAndAttributes
    wintypes.HANDLE,  # hTemplateFile
)
CREATE_FILE.restype = wintypes.HANDLE


def shared_read_open(path: Path | str) -> BufferedReader:
    """Open ``path`` for binary reading, sharing it with everyone.

    The raw handle is adopted by the CRT (:func:`msvcrt.open_osfhandle`) and then by Python
    (:func:`os.fdopen`), so what comes back is an ordinary buffered file object: closing it closes the
    handle, and every caller downstream reads it without knowing how it was opened.

    :param path: the file to open.
    :returns: the open file, positioned at the start.
    :raises OSError: the file could not be opened -- the ``WinError`` for the real cause, so a missing
        file still arrives as :class:`FileNotFoundError` exactly as ``open`` would have raised it.
    """
    handle = CREATE_FILE(str(path), GENERIC_READ, SHARE_EVERYTHING, None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None)
    if handle is None or handle == INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    # from here the handle belongs to the descriptor, and the descriptor to the file object: neither
    # step is undone on the way out, because neither can fail once the handle is valid.
    descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    return os.fdopen(descriptor, "rb")
