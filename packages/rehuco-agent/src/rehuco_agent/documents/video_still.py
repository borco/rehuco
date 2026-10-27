"""The picture a player shows while no video is open in it ([[plugins#in-app-player]], #317)."""

from typing import override

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPaintEvent
from PySide6.QtWidgets import QSizePolicy, QWidget


class VideoStill(QWidget):
    """Draws one frame of a video, as large as fits and centred, on black -- what the player shows for a video that is
    loaded but not playing, so that it holds no file ([[plugins#in-app-player]]).

    Takes the room it is given and asks for none: its size follows nothing, so a large frame cannot widen the dock.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__image: QImage | None = None
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

    @property
    def image(self) -> QImage | None:
        """The frame shown, or ``None``."""
        return self.__image

    def set_image(self, image: QImage | None) -> None:
        """Show a frame, or nothing.

        :param image: the frame; ``None`` or a null image shows black.
        """
        self.__image = None if image is None or image.isNull() else image
        self.update()

    @override
    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802  (Qt API name)
        """Paint the frame, scaled to fit with its proportions, over black.

        :param event: the paint event.
        """
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("black"))
        if self.__image is not None:
            size = self.__image.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
            target = QRect(0, 0, size.width(), size.height())
            target.moveCenter(self.rect().center())
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawImage(target, self.__image)
        painter.end()
