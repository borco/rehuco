"""Windows-only: force an already-shown window to the real foreground.

Plain `raise_()` / `activateWindow()` -- and even the classic `HWND_TOPMOST`/`HWND_NOTOPMOST`
toggle some apps use -- are not always enough on Windows: `SetForegroundWindow` refuses to hand
focus to a background process, and the window only flashes in the taskbar instead (verified
empirically). The reliable workaround is to temporarily attach this process's input queue to the
current foreground window's thread -- `AttachThreadInput` lets a thread borrow another thread's
input state, and Windows only enforces the foreground-lock between *different* input queues, so
once attached, `SetForegroundWindow` succeeds as if called by the already-foreground thread itself.
"""

import ctypes
from typing import Final

from PySide6.QtWidgets import QWidget

SW_RESTORE: Final = 9
"""``ShowWindow`` command: restore a minimized/maximized window to its normal size and position."""


def force_foreground(window: QWidget) -> None:
    """Bring ``window`` to the real foreground, restoring it first if minimized.

    :param window: the already-shown top-level window to bring to the foreground.
    """
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    hwnd = int(window.winId())
    foreground_hwnd = user32.GetForegroundWindow()
    foreground_thread = user32.GetWindowThreadProcessId(foreground_hwnd, None)
    current_thread = kernel32.GetCurrentThreadId()

    user32.AttachThreadInput(current_thread, foreground_thread, True)
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    user32.AttachThreadInput(current_thread, foreground_thread, False)
