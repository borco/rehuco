"""Windows-only: force an already-shown window to the real foreground.

Plain `raise_()` / `activateWindow()` -- and even the classic `HWND_TOPMOST`/`HWND_NOTOPMOST`
toggle some apps use -- are not always enough on Windows: `SetForegroundWindow` refuses to hand
focus to a background process, and the window only flashes in the taskbar instead (verified
empirically). The reliable workaround is to temporarily attach this process's input queue to the
current foreground window's thread -- `AttachThreadInput` lets a thread borrow another thread's
input state, and Windows only enforces the foreground-lock between *different* input queues, so
once attached, `SetForegroundWindow` succeeds as if called by the already-foreground thread itself.

Only a minimized window is restored on the way: ``SW_RESTORE`` on one that is on screen takes a maximized or
snapped (arranged) window back to its normal rectangle, so an open forwarded to a window snapped to half the
screen would un-snap it.
"""

import ctypes
import logging
from typing import Final

from PySide6.QtWidgets import QWidget

LOG: Final = logging.getLogger(__name__)

SW_RESTORE: Final = 9
"""``ShowWindow`` command: restore a window -- a minimized one to the placement it was minimized from, snap
or maximize included; a maximized or snapped one to its normal size and position, which is why it is only sent
to a minimized window."""


def force_foreground(window: QWidget) -> None:
    """Bring ``window`` to the real foreground, restoring it first only if minimized -- a maximized or snapped
    window keeps its placement.

    :param window: the already-shown top-level window to bring to the foreground.
    """
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    hwnd = int(window.winId())
    foreground_hwnd = user32.GetForegroundWindow()
    foreground_thread = user32.GetWindowThreadProcessId(foreground_hwnd, None)
    current_thread = kernel32.GetCurrentThreadId()

    # AttachThreadInput fails when the two thread ids are equal (this process is already
    # foreground) -- the paired detach below would then "succeed" against nothing, so skip the
    # whole borrow-input dance rather than attach to ourselves.
    attached = False
    if foreground_thread != current_thread:
        if user32.AttachThreadInput(current_thread, foreground_thread, True):
            attached = True
        else:
            LOG.warning("AttachThreadInput(attach) failed for thread %d -> %d", current_thread, foreground_thread)

    try:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        if not user32.BringWindowToTop(hwnd):
            LOG.warning("BringWindowToTop failed for hwnd %d", hwnd)
        if not user32.SetForegroundWindow(hwnd):
            LOG.warning("SetForegroundWindow failed for hwnd %d", hwnd)
    finally:
        if attached and not user32.AttachThreadInput(current_thread, foreground_thread, False):
            LOG.warning("AttachThreadInput(detach) failed for thread %d -> %d", current_thread, foreground_thread)
