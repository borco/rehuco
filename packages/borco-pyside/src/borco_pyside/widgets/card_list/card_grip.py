"""The handle a card is dragged by."""

from typing import Final, override

from PySide6.QtCore import QPoint, QPointF, QSize, Qt, Signal
from PySide6.QtGui import QMouseEvent, QPainter, QPaintEvent, QPalette
from PySide6.QtWidgets import QApplication, QWidget


class CardGrip(QWidget):
    """A column of dots on a card's left edge; pressing and moving it past the drag distance asks for a drag.

    Never takes focus: the keyboard reorders a card with its move keys, not through the grip.

    :param parent: optional Qt parent.
    """

    drag_requested = Signal()
    """Fires once per press, when the pointer has moved far enough to start a drag."""

    DOT_SIZE: Final = 3
    """The side of one dot, in pixels."""

    DOT_GAP: Final = 3
    """The space between dots, in pixels."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__press: QPoint | None = None
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("Drag to reorder")

    @override
    def sizeHint(self) -> QSize:  # noqa: N802  (Qt override)
        return QSize(2 * self.DOT_SIZE + 3 * self.DOT_GAP, 3 * self.DOT_SIZE + 2 * self.DOT_GAP)

    @override
    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802  (Qt override)
        if event.button() == Qt.MouseButton.LeftButton:
            self.__press = event.position().toPoint()
        super().mousePressEvent(event)

    @override
    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802  (Qt override)
        press = self.__press
        if press is not None and (event.position().toPoint() - press).manhattanLength() >= (
            QApplication.startDragDistance()
        ):
            self.__press = None
            self.drag_requested.emit()
        super().mouseMoveEvent(event)

    @override
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802  (Qt override)
        self.__press = None
        super().mouseReleaseEvent(event)

    @override
    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802  (Qt override)
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.palette().color(QPalette.ColorRole.Mid))
        step = self.DOT_SIZE + self.DOT_GAP
        left = (self.width() - (2 * self.DOT_SIZE + self.DOT_GAP)) / 2
        rows = max(1, (self.height() - self.DOT_GAP) // step)
        top = (self.height() - (rows * step - self.DOT_GAP)) / 2
        for row in range(rows):
            for column in range(2):
                painter.drawEllipse(QPointF(left + column * step, top + row * step) + QPointF(1.5, 1.5), 1.5, 1.5)
