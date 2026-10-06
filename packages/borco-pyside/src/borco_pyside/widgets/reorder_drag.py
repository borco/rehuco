"""What a list reordered by dragging shows while an item is dragged: one shadow where it will land.

Shared by every list that reorders its items by a drag -- the card list moves real widgets around the shadow, an item
view paints its rows in the order they would take -- so the two behave alike: the dragged item leaves its place, which
becomes the shadow; the shadow follows the pointer to where the item would land, the other items closing up around it;
over its own place the shadow is simply where the item was; leaving the list puts it back there until the drag ends.
"""

from collections.abc import Iterable
from typing import Final

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QPainter, QPalette, QPen

GHOST_FILL_ALPHA: Final = 40
"""How opaque the shadow's fill is: faint, so it reads as a place and not as an item."""

GHOST_RADIUS: Final = 4
"""The shadow's corner radius, in pixels."""


def paint_drag_ghost(painter: QPainter, rect: QRectF, palette: QPalette) -> None:
    """Draw the shadow a dragged item leaves where it would land: a faint fill and a thin solid outline, both in the
    palette's highlight.

    :param painter: the painter; its state is left as it was.
    :param rect: the shadow's place.
    :param palette: the palette whose highlight it is drawn in.
    """
    color = palette.color(QPalette.ColorRole.Highlight)
    fill = QColor(color)
    fill.setAlpha(GHOST_FILL_ALPHA)
    painter.save()
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(color, 1))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), GHOST_RADIUS, GHOST_RADIUS)
    finally:
        painter.restore()


def drop_slot(y: float, other_centers: Iterable[float]) -> int:
    """The place the dragged item would end up at for a drop at ``y``: how many of the *other* items have their middle
    above it.

    :param y: the pointer's height.
    :param other_centers: the vertical middles of every item but the dragged one, as they are shown.
    :returns: the place, from ``0`` (above every other item) to the number of other items.
    """
    return sum(1 for center in other_centers if center < y)


class ReorderDrag:
    """One drag's bookkeeping: which item is dragged, and the single place its shadow stands.

    Idle until :meth:`begin`; both :attr:`dragged` and :attr:`slot` are ``-1`` then. A slot is a place among the
    *other* items, which is also the row the dragged one ends up at if dropped there.
    """

    def __init__(self) -> None:
        self.__dragged = -1
        self.__slot = -1

    @property
    def active(self) -> bool:
        """Whether an item is being dragged."""
        return self.__dragged >= 0

    @property
    def dragged(self) -> int:
        """The dragged item's row, or ``-1`` while none is."""
        return self.__dragged

    @property
    def slot(self) -> int:
        """Where the shadow stands -- the row the dragged item would end up at -- or ``-1`` while none is dragged."""
        return self.__slot

    def begin(self, row: int) -> bool:
        """Start dragging the item at ``row``: its own place becomes the shadow. A no-op once a drag has begun.

        :param row: the dragged item's row.
        :returns: whether a drag began.
        """
        if self.active:
            return False
        self.__dragged = row
        self.__slot = row
        return True

    def place(self, slot: int) -> bool:
        """Move the shadow to ``slot``.

        :param slot: where the dragged item would land, among the other items.
        :returns: whether the shadow moved; never while no drag is active.
        """
        if not self.active or slot == self.__slot:
            return False
        self.__slot = slot
        return True

    def leave(self) -> bool:
        """The pointer left the list: the shadow goes back to the dragged item's own place until the drag ends.

        :returns: whether the shadow moved.
        """
        return self.place(self.__dragged)

    def end(self) -> None:
        """Forget the drag: after a drop, a cancel, or a drag that ended elsewhere."""
        self.__dragged = -1
        self.__slot = -1

    def source_at(self, row: int) -> int | None:
        """What a list shows at ``row`` while the drag is on: the shadow, or one of the other items, closed up around
        it; the item that is there when no drag is.

        :param row: a place in the list as it is shown.
        :returns: the row of the item shown there, or ``None`` for the shadow.
        """
        if not self.active:
            return row
        if row == self.__slot:
            return None
        # the place among the other items, then that item's own row: the dragged one is not among them
        other = row if row < self.__slot else row - 1
        return other if other < self.__dragged else other + 1
