"""The widget libvlc's frames are painted on ([[plugins#in-app-player]], #319)."""

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QImage, QPainter, QPaintEvent
from PySide6.QtWidgets import QWidget


class VlcSurface(QWidget):
    """An ordinary widget showing the frame libvlc decoded last, scaled to fit and centred on black.

    Ordinary on purpose: libvlc renders into memory ([[appendices.vlc#memory-rendering]]) rather than into a native
    window of its own, so this is painted by Qt like any other widget and anything may be drawn over it -- the
    maximized player's overlays ([[plugins#player-maximized]]) among them. Painting a 1080p frame into a window the
    size of a monitor costs about 3 ms (measured).

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__frame: QImage | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    @property
    def frame(self) -> QImage | None:
        """The frame shown, or ``None`` while there is none."""
        return self.__frame

    def set_frame(self, frame: QImage | None) -> None:
        """Show a frame, or nothing.

        :param frame: the frame, or ``None`` to show black.
        """
        self.__frame = frame
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        """Paint the frame to fit, letterboxed on black.

        :param event: Qt's paint event.
        """
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.black)
        if self.__frame is not None and not self.__frame.isNull():
            scaled = self.__frame.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
            box = QRect(0, 0, scaled.width(), scaled.height())
            box.moveCenter(self.rect().center())
            painter.drawImage(box, self.__frame)
        painter.end()
