"""Whether a drive has a queryable Recycle Bin, checked *before* ever calling ``send2trash`` (#300).

No ``SHFileOperationW`` return code documents "this drive has no Recycle Bin": Microsoft's own docs,
``send2trash``'s source and issue tracker, and live testing on a real machine all point the other way --
a bin-less destination is historically *silently permanent-deleted* by the legacy Windows backend, not
reported as a distinguishable error. Parsing the delete's own failure after the fact therefore can't tell
a locked file from a missing bin; asking up front can.

``SHQueryRecycleBinW`` answers that question directly: it returns ``S_OK`` for a drive that has a bin and
an ``HRESULT`` failure for one that doesn't. Measured on Windows 11 / Python 3.14.6 / send2trash 2.1.0,
and checked against what ``send2trash`` then actually did to a throwaway file on each:

=====================================================  ==============  ==================================
drive                                                  ``HRESULT``     ``send2trash`` on a file there
=====================================================  ==============  ==================================
local NTFS (``C:\\``, ``D:\\``)                        ``S_OK``        recycled
Samba share (Ubuntu host), mapped to a letter          ``S_OK``        recycled -- Windows keeps its own
                                                                       ``$I``/``$R`` pair in a
                                                                       ``$RECYCLE.BIN`` it creates on
                                                                       the share
WSL distro mount (``\\\\wsl.localhost\\...``, Plan 9)  ``0x80070003``  **silently permanently deleted**,
                                                                       no exception
drive letter with no media                             ``0x80004005``  --
=====================================================  ==============  ==================================

The third row is the whole reason this exists: on a bin-less drive the library raises nothing, so an
``except`` around it can never refuse -- only asking first can. The second row is the client's own
mechanism, not the server's, so a Samba share needs no ``recycle`` VFS module for it -- the TS-230
([[packaging-deployment#ts230-as-nas]]) is expected to match that row, though it has not itself been
measured. One call costs roughly 100-470 microseconds -- cheap in
isolation, but a bulk delete (discarding hundreds of conversion backups, normally all on one drive) would
otherwise pay that win32 round trip once per file for a fact that essentially never changes mid-run. Hence
the per-drive cache below, refreshed lazily the next time that drive is asked about rather than on a
timer: there is no background thread here, only a short TTL so an unmounted/remounted share or a changed
policy is eventually noticed.
"""

import ctypes
import time
from ctypes import wintypes
from functools import lru_cache
from pathlib import Path
from typing import Final

SHELL32: Final = ctypes.WinDLL("shell32", use_last_error=True)

CACHE_TTL_SECONDS: Final = 120.0
"""How long a drive's answer is trusted before it is asked again -- long enough that a bulk delete over
hundreds of files on one drive pays the real Win32 call once, short enough that an unmounted/remounted
share is noticed within about two minutes rather than for the rest of the process's life."""


class SHQUERYRBINFO(ctypes.Structure):  # pylint: disable=too-few-public-methods
    """``SHQUERYRBINFO``: what ``SHQueryRecycleBinW`` fills in. Only ``cb_size`` is read by this module;
    the size/count fields exist because the struct's layout requires them. Field names are ``snake_case``
    rather than the C struct's own ``cbSize``/``i64Size``/``i64NumItems`` -- a ``ctypes`` field's Python
    name is arbitrary bookkeeping, not part of the binary layout, which ``_fields_``'s declared order and
    types alone determine."""

    _fields_ = (
        ("cb_size", wintypes.DWORD),
        ("i64_size", ctypes.c_int64),
        ("i64_num_items", ctypes.c_int64),
    )


SH_QUERY_RECYCLE_BIN: Final = SHELL32.SHQueryRecycleBinW
"""``SHQueryRecycleBinW``, with its signature declared once so ``ctypes`` marshals the arguments
correctly and so a test can replace the whole Win32 call with a stand-in (bound at module scope for the
same reason ``CREATE_FILE`` is in ``borco_core.platforms.windows.shared_read``)."""

SH_QUERY_RECYCLE_BIN.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(SHQUERYRBINFO))
SH_QUERY_RECYCLE_BIN.restype = ctypes.c_long  # HRESULT


class RecycleBinCapability:  # pylint: disable=too-few-public-methods
    """Answers, and caches, whether a drive has a queryable Recycle Bin."""

    def __init__(self) -> None:
        self.__cache: dict[str, tuple[bool, float]] = {}
        """``{drive root: (has a bin, when that was last checked)}``, ``time.monotonic()`` timestamps."""

    def has_recycle_bin(self, path: Path) -> bool:
        """Whether ``path``'s drive root has a Recycle Bin, per a cached ``SHQueryRecycleBinW`` call.

        :param path: the file about to be deleted; only its drive matters.
        :returns: ``True`` if that drive has a queryable Recycle Bin.
        """
        drive = self.__drive_root(path)
        now = time.monotonic()
        cached = self.__cache.get(drive)
        if cached is not None and now - cached[1] < CACHE_TTL_SECONDS:
            return cached[0]
        result = self.__query(drive)
        self.__cache[drive] = (result, now)
        return result

    @staticmethod
    def __drive_root(path: Path) -> str:
        """``path``'s drive, as the root ``SHQueryRecycleBinW`` expects -- ``"C:\\\\"`` for a local
        drive, ``"\\\\\\\\server\\\\share\\\\"`` for a UNC path."""
        drive = Path(path).drive
        return f"{drive}\\" if drive else "\\"

    @staticmethod
    def __query(drive: str) -> bool:
        """One real ``SHQueryRecycleBinW`` call, uncached."""
        info = SHQUERYRBINFO()
        # ctypes.Structure has no __init__ of its own; every field is set right after construction
        # pylint: disable-next=attribute-defined-outside-init
        info.cb_size = ctypes.sizeof(SHQUERYRBINFO)
        hresult = SH_QUERY_RECYCLE_BIN(drive, ctypes.byref(info))
        return hresult == 0


@lru_cache(maxsize=1)
def recycle_bin_capability() -> RecycleBinCapability:
    """The single, process-wide `RecycleBinCapability`.

    :returns: the shared instance.
    """
    return RecycleBinCapability()


def has_recycle_bin(path: Path) -> bool:
    """Whether ``path``'s drive root has a Recycle Bin -- see `RecycleBinCapability.has_recycle_bin`.

    :param path: the file about to be deleted; only its drive matters.
    :returns: ``True`` if that drive has a queryable Recycle Bin.
    """
    return recycle_bin_capability().has_recycle_bin(path)
