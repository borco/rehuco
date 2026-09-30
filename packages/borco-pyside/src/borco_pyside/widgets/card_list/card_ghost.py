"""The placeholder a dragged card leaves where it would land."""

from typing import override

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPalette, QPen
from PySide6.QtWidgets import QWidget


class CardGhost(QWidget):
    """A quiet gap as tall as the dragged card: a faint fill and a thin solid outline.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    @override
    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802  (Qt override)
        super().paintEvent(event)
        color = self.palette().color(QPalette.ColorRole.Highlight)
        fill = QColor(color)
        fill.setAlpha(40)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(color, 1))
        painter.setBrush(fill)
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
