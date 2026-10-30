"""Windows-only: the picture a native window shows, taken in memory.

``QWidget.grab()`` renders Qt's own painting and knows nothing of what another library draws into a native child
window (libvlc's Direct3D output, say); a screen grab wants the window on a monitor and unoccluded. ``PrintWindow``
with ``PW_RENDERFULLCONTENT`` asks the compositor for the window's content as it is, whether or not it is visible, and
answers in a few milliseconds (5--11 ms for 640x400, measured). The bits go into a device-independent bitmap and from
there into a :class:`~PySide6.QtGui.QImage`; nothing touches the disk.
"""

import ctypes
from ctypes import wintypes
from typing import Final

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QWidget

PW_RENDERFULLCONTENT: Final = 0x00000002
"""Ask for the window as the compositor has it, DirectX output included."""

DIB_RGB_COLORS: Final = 0


class BitmapInfoHeader(ctypes.Structure):  # pylint: disable=too-few-public-methods
    """``BITMAPINFOHEADER``: how ``GetDIBits`` is asked for the pixels."""

    _fields_ = (  # noqa: RUF012
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    )


def picture_of(window: QWidget) -> QImage | None:
    """The content of a native window, as the compositor shows it.

    :param window: a widget with a native window of its own (``WA_NativeWindow``).
    :returns: a 32-bit image of its client area, or ``None`` when the system refuses or the window has no size.
    """
    width, height = window.width(), window.height()
    if width <= 0 or height <= 0:
        return None
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    screen_dc = user32.GetDC(0)
    memory_dc = gdi32.CreateCompatibleDC(screen_dc)
    bitmap = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
    previous = gdi32.SelectObject(memory_dc, bitmap)
    try:
        if not user32.PrintWindow(int(window.winId()), memory_dc, PW_RENDERFULLCONTENT):
            return None
        # a negative height asks for a top-down bitmap, the row order a QImage expects
        header = BitmapInfoHeader(ctypes.sizeof(BitmapInfoHeader), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
        pixels = ctypes.create_string_buffer(width * height * 4)
        if gdi32.GetDIBits(memory_dc, bitmap, 0, height, pixels, ctypes.byref(header), DIB_RGB_COLORS) != height:
            return None
        # copied: the image must outlive the buffer it was read from
        return QImage(pixels.raw, width, height, width * 4, QImage.Format.Format_RGB32).copy()
    finally:
        gdi32.SelectObject(memory_dc, previous)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(0, screen_dc)
