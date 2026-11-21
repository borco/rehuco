"""A turning arc: something is being waited for, and how long it will take is not known."""

from typing import Final, override

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

SPINNER_SIZE: Final = 48
"""The side of the square the arc turns in, in pixels."""

SPINNER_THICKNESS: Final = 4
"""The arc's line width, in pixels."""

SPINNER_STEP_DEGREES: Final = 30
"""How far the arc turns at each tick."""

SPINNER_INTERVAL_MS: Final = 80
"""The time between two ticks, in milliseconds."""

SPINNER_SPAN_DEGREES: Final = 270
"""How much of the circle the arc covers."""


class BusySpinner(QWidget):
    """An arc turning in a square, in the palette's text color, while :attr:`running`.

    Stopped, it paints nothing and keeps its place, so what sits beside it does not move as it starts and stops.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.__angle = 0
        """Where the arc starts, in degrees, clockwise from the top."""
        self.__timer: Final = QTimer(self)
        self.__timer.setInterval(SPINNER_INTERVAL_MS)
        self.__timer.timeout.connect(self.__turn)

    @property
    def running(self) -> bool:
        """Whether the arc is turning."""
        return self.__timer.isActive()

    @property
    def angle(self) -> int:
        """Where the arc starts, in degrees clockwise from the top."""
        return self.__angle

    def start(self) -> None:
        """Start turning. A no-op while turning."""
        if not self.__timer.isActive():
            self.__timer.start()
            self.update()

    def stop(self) -> None:
        """Stop turning and paint nothing. A no-op while stopped."""
        if self.__timer.isActive():
            self.__timer.stop()
            self.update()

    @override
    def sizeHint(self) -> QSize:  # noqa: N802 (Qt override)
        """See :meth:`QWidget.sizeHint`.

        :returns: the square the arc turns in.
        """
        return QSize(SPINNER_SIZE, SPINNER_SIZE)

    @override
    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 (Qt override)
        """Paint the arc where it is now, or nothing while stopped.

        :param event: the Qt paint event.
        """
        del event
        if not self.__timer.isActive():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(self.palette().windowText().color(), SPINNER_THICKNESS)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        side = min(self.width(), self.height()) - SPINNER_THICKNESS
        box = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        # Qt counts angles counter-clockwise from three o'clock, in sixteenths of a degree
        painter.drawArc(box, (90 - self.__angle) * 16, -SPINNER_SPAN_DEGREES * 16)
        painter.end()

    def __turn(self) -> None:
        """Move the arc on by one step."""
        self.__angle = (self.__angle + SPINNER_STEP_DEGREES) % 360
        self.update()
