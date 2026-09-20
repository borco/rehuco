"""Windows-only: show a top-level window without the desktop's open animation.

The Desktop Window Manager fades every top-level in from the moment its ``ShowWindow`` lands, each
on its own clock. Two windows shown one after the other -- an owner and the dock window it owns,
say -- therefore fade in staggered by however long the first show took, and for those frames the
second is a translucent ghost over an already-opaque first: it reads as arriving late, behind, and
empty, even when its content was painted before the animation began (measured frame by frame on a
real desktop). ``DWMWA_TRANSITIONS_FORCEDISABLED`` turns the animation off for one window; set on
each around its show, the windows appear together in the first frame either reaches, and cleared
again right after, every later transition (minimize, close) stays the desktop's own.
"""

import ctypes
from collections.abc import Generator
from contextlib import contextmanager
from typing import Final

from PySide6.QtWidgets import QWidget

DWMWA_TRANSITIONS_FORCEDISABLED: Final = 3
"""``DwmSetWindowAttribute`` attribute: a non-zero ``BOOL`` suppresses the window's DWM transitions."""


@contextmanager
def open_transition_disabled(window: QWidget) -> Generator[None]:
    """Suppress the desktop's transition animations on ``window`` for the duration of the block.

    :param window: the top-level widget about to be shown; its native window is created here if it
        does not exist yet, which is what ``show()`` would do next anyway.
    """
    hwnd = ctypes.c_void_p(int(window.winId()))
    disabled = ctypes.c_int(1)
    enabled = ctypes.c_int(0)
    dwmapi = ctypes.windll.dwmapi
    dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_TRANSITIONS_FORCEDISABLED, ctypes.byref(disabled), ctypes.sizeof(disabled))
    try:
        yield
    finally:
        dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_TRANSITIONS_FORCEDISABLED, ctypes.byref(enabled), ctypes.sizeof(enabled)
        )
