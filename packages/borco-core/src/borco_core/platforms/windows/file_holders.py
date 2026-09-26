"""Asking the Restart Manager which processes have a set of files open.

The Restart Manager (``rstrtmgr.dll``) is the Windows API installers use to find what must close before
a file can be replaced, and the one Explorer's own "file in use" dialog reads. It answers for *any* open
handle, whatever share mode it asked for, and names the process as the user knows it (``Windows
Explorer``, not ``explorer.exe``). A session is needed per question: start it, register the files, list
the processes holding them, end it -- and the end must happen on every path, since a session left open
counts against a small per-user limit.

Files only: registering a directory is refused (``ERROR_ACCESS_DENIED`` from ``RmGetList``, measured), so
a directory's own handles -- an Explorer window showing it, a process's working directory -- are
invisible here.

Windows-only, like every other module under ``platforms/windows/``: only ever imported inside
:func:`borco_core.file_holders.file_holders`'s ``if sys.platform == "win32":`` branch, and it carries the
same function name as that caller for the reason :mod:`borco_core.platforms.windows.shared_read` gives.
"""

import ctypes
from collections.abc import Sequence
from ctypes import wintypes
from pathlib import Path
from typing import Final

from ...file_holder import FileHolder

RSTRTMGR: Final = ctypes.WinDLL("rstrtmgr", use_last_error=True)
"""The Restart Manager. Its functions return their error code rather than setting ``GetLastError``."""

CCH_RM_SESSION_KEY: Final = 32
"""The session key's length in characters, without its terminator (``sizeof(GUID) * 2``)."""

CCH_RM_MAX_APP_NAME: Final = 255
CCH_RM_MAX_SVC_NAME: Final = 63
"""The fixed buffer lengths in ``RM_PROCESS_INFO``, without their terminators."""

ERROR_SUCCESS: Final = 0
ERROR_MORE_DATA: Final = 234
"""What ``RmGetList`` returns when the buffer it was handed is too small -- including the first call,
made with none, to learn the size; and again if a process started holding a file in between."""

LIST_ATTEMPTS: Final = 3
"""How often to size the buffer and list again before giving up on a list that keeps growing."""


class RmUniqueProcess(ctypes.Structure):  # pylint: disable=too-few-public-methods
    """``RM_UNIQUE_PROCESS``: a process id, and its start time to tell a reused id apart."""

    _fields_ = (("dwProcessId", wintypes.DWORD), ("ProcessStartTime", wintypes.FILETIME))


class RmProcessInfo(ctypes.Structure):  # pylint: disable=too-few-public-methods
    """``RM_PROCESS_INFO``: one process holding a registered file."""

    _fields_ = (
        ("Process", RmUniqueProcess),
        ("strAppName", wintypes.WCHAR * (CCH_RM_MAX_APP_NAME + 1)),
        ("strServiceShortName", wintypes.WCHAR * (CCH_RM_MAX_SVC_NAME + 1)),
        ("ApplicationType", ctypes.c_int),
        ("AppStatus", wintypes.ULONG),
        ("TSSessionId", wintypes.DWORD),
        ("bRestartable", wintypes.BOOL),
    )


RM_START_SESSION: Final = RSTRTMGR.RmStartSession
RM_START_SESSION.argtypes = (ctypes.POINTER(wintypes.DWORD), wintypes.DWORD, wintypes.LPWSTR)
RM_START_SESSION.restype = wintypes.DWORD

RM_REGISTER_RESOURCES: Final = RSTRTMGR.RmRegisterResources
RM_REGISTER_RESOURCES.argtypes = (
    wintypes.DWORD,  # dwSessionHandle
    wintypes.UINT,  # nFiles
    ctypes.POINTER(wintypes.LPCWSTR),  # rgsFileNames
    wintypes.UINT,  # nApplications
    ctypes.POINTER(RmUniqueProcess),  # rgApplications
    wintypes.UINT,  # nServices
    ctypes.POINTER(wintypes.LPCWSTR),  # rgsServiceNames
)
RM_REGISTER_RESOURCES.restype = wintypes.DWORD

RM_GET_LIST: Final = RSTRTMGR.RmGetList
RM_GET_LIST.argtypes = (
    wintypes.DWORD,  # dwSessionHandle
    ctypes.POINTER(wintypes.UINT),  # pnProcInfoNeeded
    ctypes.POINTER(wintypes.UINT),  # pnProcInfo
    ctypes.POINTER(RmProcessInfo),  # rgAffectedApps
    ctypes.POINTER(wintypes.DWORD),  # lpdwRebootReasons
)
RM_GET_LIST.restype = wintypes.DWORD

RM_END_SESSION: Final = RSTRTMGR.RmEndSession
RM_END_SESSION.argtypes = (wintypes.DWORD,)
RM_END_SESSION.restype = wintypes.DWORD
"""The four calls, bound once with their signatures declared, and read by name at call time so a test
can replace each with a stand-in -- the same shape :mod:`~borco_core.platforms.windows.shared_read`
gives ``CreateFileW``."""


def file_holders(paths: Sequence[Path]) -> tuple[FileHolder, ...]:
    """The processes that have any of ``paths`` open, each once; see
    :func:`borco_core.file_holders.file_holders`.

    :param paths: the files to ask about.
    :returns: the holders, in the order the Restart Manager listed them.
    :raises OSError: a Restart Manager call failed, with its ``WinError``.
    """
    if not paths:
        return ()
    session = wintypes.DWORD(0)
    key = ctypes.create_unicode_buffer(CCH_RM_SESSION_KEY + 1)
    raise_for_result(RM_START_SESSION(ctypes.byref(session), 0, key))
    try:
        names = (wintypes.LPCWSTR * len(paths))(*(str(path) for path in paths))
        raise_for_result(RM_REGISTER_RESOURCES(session, len(paths), names, 0, None, 0, None))
        return list_session_holders(session)
    finally:
        RM_END_SESSION(session)


def list_session_holders(session: wintypes.DWORD) -> tuple[FileHolder, ...]:
    """List a session's holders, growing the buffer until they fit.

    :param session: a session with its files registered.
    :returns: the holders, each process once.
    :raises OSError: the list kept growing past :data:`LIST_ATTEMPTS`, or ``RmGetList`` failed.
    """
    capacity = 0
    for _ in range(LIST_ATTEMPTS):
        needed, count, reasons = wintypes.UINT(0), wintypes.UINT(capacity), wintypes.DWORD(0)
        infos = (RmProcessInfo * capacity)()
        result = RM_GET_LIST(session, ctypes.byref(needed), ctypes.byref(count), infos, ctypes.byref(reasons))
        if result == ERROR_MORE_DATA:
            capacity = needed.value
            continue
        raise_for_result(result)
        holders = (FileHolder(infos[i].Process.dwProcessId, infos[i].strAppName) for i in range(count.value))
        return tuple(dict.fromkeys(holders))
    raise ctypes.WinError(ERROR_MORE_DATA)


def raise_for_result(result: int) -> None:
    """Raise a Restart Manager call's failure as the ``OSError`` for its code.

    :param result: what the call returned.
    :raises OSError: ``result`` is not ``ERROR_SUCCESS``.
    """
    if result != ERROR_SUCCESS:
        raise ctypes.WinError(result)
