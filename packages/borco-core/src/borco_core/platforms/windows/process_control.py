"""A process's top-level windows, bringing one to the front, and ending the process -- what File Locksmith
offers beside each holder it names.

**Which windows count** is what the taskbar shows: visible, unowned and titled. A process holding a file is
often a background one with only hidden or message-only windows (a scanner, a sync client); those have no
window worth raising, and saying so is better than raising something invisible.

**Bringing one to the front** runs into the foreground lock: Windows lets a process take the foreground only
when it already has it, or was the last to get input. A click in this process's own dialog is that input, so
a plain ``SetForegroundWindow`` usually succeeds; when it is refused anyway, attaching this thread's input to
the foreground window's thread for the call is the documented way through.

**Ending** is ``TerminateProcess``, the same as File Locksmith's *End task* and Task Manager's on a process:
nothing is asked of the program, so whatever it had unsaved is gone. A process this one may not open --
another user's, or an elevated one from an ordinary app -- is a refusal the caller reports.

Windows-only, like every other module under ``platforms/windows/``: only ever imported inside
:mod:`borco_core.process_control`'s ``if sys.platform == "win32":`` branches, with the same function names, for
the reason :mod:`borco_core.platforms.windows.shared_read` gives.
"""

import ctypes
from ctypes import wintypes
from typing import Final

USER32: Final = ctypes.WinDLL("user32", use_last_error=True)
KERNEL32: Final = ctypes.WinDLL("kernel32", use_last_error=True)

GW_OWNER: Final = 4
"""``GetWindow``: the window's owner -- a dialog or tool window has one, a taskbar window does not."""

SW_RESTORE: Final = 9
"""``ShowWindow``: un-minimize, back to the size and place the window had."""

PROCESS_TERMINATE: Final = 0x0001
SYNCHRONIZE: Final = 0x0010_0000
"""``OpenProcess`` rights: end the process, and wait on its handle until it has gone."""

TERMINATED_EXIT_CODE: Final = 1
"""The exit code an ended process is given -- what Task Manager gives it too."""

WAIT_OBJECT_0: Final = 0
"""``WaitForSingleObject``: the process has exited."""

ERROR_INVALID_PARAMETER: Final = 87
"""``OpenProcess`` with an id no running process has -- one that already exited."""

WNDENUMPROC: Final = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
"""The callback ``EnumWindows`` calls once per top-level window."""

ENUM_WINDOWS: Final = USER32.EnumWindows
ENUM_WINDOWS.argtypes = (WNDENUMPROC, wintypes.LPARAM)
ENUM_WINDOWS.restype = wintypes.BOOL

GET_WINDOW_THREAD_PROCESS_ID: Final = USER32.GetWindowThreadProcessId
GET_WINDOW_THREAD_PROCESS_ID.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
GET_WINDOW_THREAD_PROCESS_ID.restype = wintypes.DWORD

IS_WINDOW_VISIBLE: Final = USER32.IsWindowVisible
IS_WINDOW_VISIBLE.argtypes = (wintypes.HWND,)
IS_WINDOW_VISIBLE.restype = wintypes.BOOL

GET_WINDOW: Final = USER32.GetWindow
GET_WINDOW.argtypes = (wintypes.HWND, wintypes.UINT)
GET_WINDOW.restype = wintypes.HWND

GET_WINDOW_TEXT_LENGTH: Final = USER32.GetWindowTextLengthW
GET_WINDOW_TEXT_LENGTH.argtypes = (wintypes.HWND,)
GET_WINDOW_TEXT_LENGTH.restype = ctypes.c_int

IS_ICONIC: Final = USER32.IsIconic
IS_ICONIC.argtypes = (wintypes.HWND,)
IS_ICONIC.restype = wintypes.BOOL

SHOW_WINDOW: Final = USER32.ShowWindow
SHOW_WINDOW.argtypes = (wintypes.HWND, ctypes.c_int)
SHOW_WINDOW.restype = wintypes.BOOL

SET_FOREGROUND_WINDOW: Final = USER32.SetForegroundWindow
SET_FOREGROUND_WINDOW.argtypes = (wintypes.HWND,)
SET_FOREGROUND_WINDOW.restype = wintypes.BOOL

GET_FOREGROUND_WINDOW: Final = USER32.GetForegroundWindow
GET_FOREGROUND_WINDOW.argtypes = ()
GET_FOREGROUND_WINDOW.restype = wintypes.HWND

ATTACH_THREAD_INPUT: Final = USER32.AttachThreadInput
ATTACH_THREAD_INPUT.argtypes = (wintypes.DWORD, wintypes.DWORD, wintypes.BOOL)
ATTACH_THREAD_INPUT.restype = wintypes.BOOL

GET_CURRENT_THREAD_ID: Final = KERNEL32.GetCurrentThreadId
GET_CURRENT_THREAD_ID.argtypes = ()
GET_CURRENT_THREAD_ID.restype = wintypes.DWORD

OPEN_PROCESS: Final = KERNEL32.OpenProcess
OPEN_PROCESS.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
OPEN_PROCESS.restype = wintypes.HANDLE

TERMINATE_PROCESS: Final = KERNEL32.TerminateProcess
TERMINATE_PROCESS.argtypes = (wintypes.HANDLE, wintypes.UINT)
TERMINATE_PROCESS.restype = wintypes.BOOL

WAIT_FOR_SINGLE_OBJECT: Final = KERNEL32.WaitForSingleObject
WAIT_FOR_SINGLE_OBJECT.argtypes = (wintypes.HANDLE, wintypes.DWORD)
WAIT_FOR_SINGLE_OBJECT.restype = wintypes.DWORD

CLOSE_HANDLE: Final = KERNEL32.CloseHandle
CLOSE_HANDLE.argtypes = (wintypes.HANDLE,)
CLOSE_HANDLE.restype = wintypes.BOOL
"""Every call bound once with its signature declared, and read by name at call time so a test can replace
each with a stand-in -- the same shape :mod:`~borco_core.platforms.windows.file_holders` has."""


def top_windows(pid: int) -> tuple[int, ...]:
    """The process's taskbar windows: visible, unowned and titled.

    :param pid: the process.
    :returns: their handles, in ``EnumWindows``' order -- topmost in the z-order first.
    """
    found: list[int] = []

    def visit(window: int, _parameter: int) -> bool:
        owner = wintypes.DWORD(0)
        GET_WINDOW_THREAD_PROCESS_ID(window, ctypes.byref(owner))
        if (
            owner.value == pid
            and IS_WINDOW_VISIBLE(window)
            and not GET_WINDOW(window, GW_OWNER)
            and GET_WINDOW_TEXT_LENGTH(window) > 0
        ):
            found.append(window)
        return True

    ENUM_WINDOWS(WNDENUMPROC(visit), 0)
    return tuple(found)


def has_window(pid: int) -> bool:
    """Whether the process has a window :func:`show_window` can bring to the front.

    :param pid: the process.
    :returns: whether it has a taskbar window.
    """
    return bool(top_windows(pid))


def show_window(pid: int) -> bool:
    """Bring the process's topmost taskbar window to the front, restoring it if it is minimized.

    :param pid: the process.
    :returns: whether it had a window to show and Windows let it take the foreground.
    """
    windows = top_windows(pid)
    if not windows:
        return False
    window = windows[0]
    if IS_ICONIC(window):
        SHOW_WINDOW(window, SW_RESTORE)
    if SET_FOREGROUND_WINDOW(window):
        return True
    return bring_forward_attached(window)


def bring_forward_attached(window: int) -> bool:
    """Retry taking the foreground for ``window`` with this thread's input attached to the foreground one's.

    :param window: the window to bring forward.
    :returns: whether it took the foreground.
    """
    foreground = GET_WINDOW_THREAD_PROCESS_ID(GET_FOREGROUND_WINDOW(), None)
    current = GET_CURRENT_THREAD_ID()
    attached = foreground != current and bool(ATTACH_THREAD_INPUT(current, foreground, True))
    try:
        return bool(SET_FOREGROUND_WINDOW(window))
    finally:
        if attached:
            ATTACH_THREAD_INPUT(current, foreground, False)


def end_process(pid: int, timeout: float) -> bool:
    """End the process, the way Task Manager's *End task* does, and wait for it to go.

    :param pid: the process.
    :param timeout: how long to wait for it to exit, in seconds.
    :returns: whether it has gone -- also when it had already exited before it was asked.
    :raises OSError: Windows refused to open or end it, with its ``WinError`` -- access denied for an elevated
        process or another user's.
    """
    handle = OPEN_PROCESS(PROCESS_TERMINATE | SYNCHRONIZE, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error == ERROR_INVALID_PARAMETER:
            return True
        raise ctypes.WinError(error)
    try:
        if not TERMINATE_PROCESS(handle, TERMINATED_EXIT_CODE):
            raise ctypes.WinError(ctypes.get_last_error())
        return WAIT_FOR_SINGLE_OBJECT(handle, round(timeout * 1000)) == WAIT_OBJECT_0
    finally:
        CLOSE_HANDLE(handle)
