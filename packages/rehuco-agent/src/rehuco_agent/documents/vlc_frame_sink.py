"""Where libvlc decodes into: a buffer of this process's, each finished frame handed on as a ``QImage``
([[appendices.vlc#memory-rendering]], #319)."""

import ctypes
from typing import Final

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

CHROMA: Final = b"RV32"
"""What libvlc is asked to decode into: 32-bit BGRx, which is ``QImage.Format_RGB32`` byte for byte."""

BYTES_PER_PIXEL: Final = 4


class VlcFrameSink(QObject):
    """The three moments of libvlc's memory rendering, as plain methods the ctypes callbacks forward to.

    libvlc calls them on threads of its own: :meth:`setup` once per video with the decoder's picture size, then
    :meth:`lock` before each frame is written and :meth:`display` when it is due on screen. The frame is **copied**
    inside :meth:`display`, on libvlc's thread, into an image of its own, and that image crosses to the GUI thread
    through :attr:`frame_ready`; with one picture in libvlc's pool, the buffer is not written again until the copy
    is made. Nothing here touches a widget.

    The size libvlc gives :meth:`setup` is the decoder's, padded to its alignment (a 640x360 clip comes as 640x384);
    the visible size is read by the player once the video plays and the image is cropped to it there.

    :param parent: optional Qt parent.
    """

    frame_ready = Signal(QImage, int)
    """A frame is due on screen, with the :attr:`epoch` it was displayed under; emitted on libvlc's thread, delivered
    on the receiver's."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__width = 0
        self.__height = 0
        self.__buffer: ctypes.Array[ctypes.c_char] | None = None
        self.epoch = 0
        """What the owner counts its sources by; read on libvlc's thread as a frame is displayed, so a frame queued
        behind a change of source can be told from the new source's."""

    @property
    def size(self) -> tuple[int, int]:
        """The buffer's picture size, ``(width, height)``; zeros before :meth:`setup`."""
        return self.__width, self.__height

    def setup(self, width: int, height: int) -> tuple[int, int]:
        """Allocate for a video of the given picture size.

        :param width: the decoder's picture width.
        :param height: the decoder's picture height.
        :returns: the pitch in bytes and the number of lines, which libvlc is told.
        """
        self.__width, self.__height = width, height
        self.__buffer = ctypes.create_string_buffer(width * BYTES_PER_PIXEL * height)
        return width * BYTES_PER_PIXEL, height

    def cleanup(self) -> None:
        """Let the buffer go: the video is over."""
        self.__buffer = None
        self.__width = self.__height = 0

    def lock(self) -> int:
        """The address libvlc writes the next frame to.

        :returns: the buffer's address, or 0 before :meth:`setup`.
        """
        return ctypes.cast(self.__buffer, ctypes.c_void_p).value or 0 if self.__buffer is not None else 0

    def display(self) -> None:
        """A frame has been written and is due: copy it out and say so."""
        buffer = self.__buffer
        if buffer is None:
            return
        pitch = self.__width * BYTES_PER_PIXEL
        view = memoryview(buffer).cast("B")
        image = QImage(view, self.__width, self.__height, pitch, QImage.Format.Format_RGB32).copy()
        try:
            self.frame_ready.emit(image, self.epoch)
        except RuntimeError:  # deleted while libvlc still had a thread going
            pass
