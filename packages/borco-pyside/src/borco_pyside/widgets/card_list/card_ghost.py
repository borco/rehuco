"""The placeholder a dragged card leaves where it would land."""

from typing import override

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPaintEvent
from PySide6.QtWidgets import QWidget

from ..reorder_drag import paint_drag_ghost


class CardGhost(QWidget):
    """A quiet gap as tall as the dragged card: a faint fill and a thin solid outline, drawn as every reorderable list
    draws its shadow (:func:`~borco_pyside.widgets.reorder_drag.paint_drag_ghost`).

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    @override
    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802  (Qt override)
        super().paintEvent(event)
        painter = QPainter(self)
        paint_drag_ghost(painter, QRectF(self.rect()), self.palette())
