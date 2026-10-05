"""The band a root is dragged by in the Roots view, like the grip a card of a list is dragged by (#378)."""

from typing import Final, override

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt
from PySide6.QtGui import QColor, QMouseEvent, QPainter
from PySide6.QtWidgets import QAbstractItemView

GRIP_WIDTH: Final = 16
"""The band at the left of a root row that drags it, in pixels."""

DOT_SIZE: Final = 3
"""The side of one dot of the grip, in pixels."""

DOT_GAP: Final = 3
"""The space between dots, in pixels."""

DOT_ALPHA: Final = 150
"""How opaque the dots are against the row, so the grip reads as a handle and not as text."""


def paint_grip(painter: QPainter, band: QRect, color: QColor) -> None:
    """Draw the grip: two columns of three dots, centred in ``band``.

    :param painter: the painter to draw with.
    :param band: the band at a row's left edge.
    :param color: the row's text colour, which the dots are drawn in, softened.
    """
    dot = QColor(color)
    dot.setAlpha(DOT_ALPHA)
    width = 2 * DOT_SIZE + DOT_GAP
    height = 3 * DOT_SIZE + 2 * DOT_GAP
    left = band.left() + (band.width() - width) // 2
    top = band.top() + (band.height() - height) // 2
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(dot)
    for column in range(2):
        for row in range(3):
            painter.drawRect(left + column * (DOT_SIZE + DOT_GAP), top + row * (DOT_SIZE + DOT_GAP), DOT_SIZE, DOT_SIZE)
    painter.restore()


# an event filter is one method; there is nothing else for it to be
# pylint: disable-next=too-few-public-methods
class RootsGripFilter(QObject):
    """Lets only the grip of a root row start a drag, by arming the column's drag on a press that lands on one and
    disarming it on any other, and shows the hand cursor over a grip.

    A list view starts a drag from anywhere on a draggable row, which would make every click-and-move on a root a
    reorder; whether an item may be dragged is the model's to say per row, and *where on it* is not something a
    view can be told, so the view's own switch is thrown at each press instead.

    Installed on the viewport of the column that lists the roots.

    :param column: the column whose viewport this watches.
    """

    def __init__(self, column: QAbstractItemView) -> None:
        super().__init__(column)
        self.__column: QAbstractItemView = column

    def on_grip(self, position: QPoint) -> bool:
        """Whether a point of the viewport is on the grip of a row that can be dragged.

        :param position: the point, in the viewport's coordinates.
        :returns: whether it is.
        """
        index = self.__column.indexAt(position)
        if not index.isValid() or not index.flags() & Qt.ItemFlag.ItemIsDragEnabled:
            return False
        return position.x() - self.__column.visualRect(index).left() < GRIP_WIDTH

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802  (Qt API name)
        del watched  # always the column's own viewport, which is where this is installed
        if isinstance(event, QMouseEvent):
            point = event.position().toPoint()
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self.__column.setDragEnabled(self.on_grip(point))
            elif event.type() == QEvent.Type.MouseMove and not event.buttons():
                viewport = self.__column.viewport()
                if self.on_grip(point):
                    viewport.setCursor(Qt.CursorShape.OpenHandCursor)
                else:
                    viewport.unsetCursor()
        return False
