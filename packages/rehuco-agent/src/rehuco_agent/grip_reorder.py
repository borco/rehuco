"""The grip a row of an item view is dragged by to another place, and what the view shows while one is dragged -- the
cues of the grip a card of a list is dragged by (#378, #461), shared by the Roots view and the License dock's list
(#705)."""

from typing import Final, cast, override

from borco_pyside.widgets import ReorderDrag, drop_slot
from PySide6.QtCore import QAbstractItemModel, QEvent, QMimeData, QModelIndex, QObject, QPoint, QRect, Qt
from PySide6.QtGui import QColor, QDrag, QDragMoveEvent, QDropEvent, QHelpEvent, QMouseEvent, QPainter
from PySide6.QtWidgets import QAbstractItemView, QApplication, QToolTip, QWidget

GRIP_WIDTH: Final = 16
"""The band at the left of a row that drags it, in pixels."""

DOT_SIZE: Final = 3
"""The side of one dot of the grip, in pixels."""

DOT_GAP: Final = 3
"""The space between dots, in pixels."""

DOT_ALPHA: Final = 150
"""How opaque the dots are against the row, so the grip reads as a handle and not as text."""

GRIP_TOOLTIP: Final = "Drag to reorder"
"""What hovering a grip says, as the card list's grip says it."""


def paint_grip(painter: QPainter, band: QRect, color: QColor) -> None:
    """Draw the grip: two columns of three dots, centered in ``band``.

    :param painter: the painter to draw with.
    :param band: the band at a row's left edge.
    :param color: the row's text color, which the dots are drawn in, softened.
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


class GripReorderFilter(QObject):
    """Drags a row by its grip, and only by it, exactly as a card of a card list is dragged
    (:class:`~borco_pyside.widgets.CardListEditor`): the row leaves its place, which becomes the shadow; the shadow
    follows the pointer to where the row would land, the other rows closing up around it; over its own place the
    shadow is simply where the row was; leaving the view puts it back there until the drag ends; the drop moves the
    row to the shadow's place. The shadow's bookkeeping, look and landing rule are the card list's own
    (:class:`~borco_pyside.widgets.ReorderDrag`, :func:`~borco_pyside.widgets.paint_drag_ghost`,
    :func:`~borco_pyside.widgets.drop_slot`).

    **The drag is this filter's, not the view's.** A view starts a drag from anywhere on a draggable row, and drops
    between rows with a line; so the view's own drag stays off, a press on a grip followed by a move past the drag
    distance starts one here, and every drag event of the view is answered here. A view cannot open a gap between its
    rows, so while a row is dragged the view's delegate paints the rows in the order they would take, from the same
    :class:`~borco_pyside.widgets.ReorderDrag`.

    **A grip** is the :data:`GRIP_WIDTH` band at the left of a row's first cell, on a row whose model flags it
    draggable. Shows the hand cursor and the card list's tooltip over one. Installed on the view's viewport.

    Designed for inheritance: what a view's drag carries and how its row is moved are the model's, so a subclass says
    whether a drag is of the dragged row (:meth:`_carries`) and moves it (:meth:`_move`).

    :param view: the view whose viewport this watches.
    :param drag: the drag's bookkeeping, which the view's delegate paints the rows from.
    """

    def __init__(self, view: QAbstractItemView, drag: ReorderDrag) -> None:
        super().__init__(view)
        self.__drag: Final = drag
        self.__press: tuple[int, QPoint] | None = None
        """The row whose grip the left button went down on, and where; ``None`` otherwise."""

    def abandon(self, parent: QModelIndex | None, *_args: object) -> None:
        """Give up the drag when the rows changed under it, so the shadow never names a row that is no longer there;
        the drop that follows is refused, as a card list refuses one after its rows changed. Connected to the model's
        row signals; a change under another row (``parent`` valid) is not one.

        :param parent: the parent of the rows that changed, for the row signals; ``None`` for a reset.
        """
        if (parent is not None and parent.isValid()) or not self.__drag.active:
            return
        self.__drag.end()
        # one expression: a view Qt made can be a temporary wrapper (#459), and its viewport is used before it goes
        cast(QAbstractItemView, self.parent()).viewport().update()

    def _carries(self, model: QAbstractItemModel, mime: QMimeData, row: int) -> bool:
        """Whether a drag carries the row being dragged, as the model's own mime data says it: a row of another view
        over the same kind of model is not.

        :param model: the view's model.
        :param mime: the drag's data.
        :param row: the dragged row.
        :returns: ``False`` here; a subclass reads the model's own format.
        """
        del model, mime, row
        return False

    def _move(self, model: QAbstractItemModel, row: int, slot: int) -> None:
        """Move the dragged row to where its shadow stands.

        :param model: the view's model.
        :param row: the dragged row.
        :param slot: where it lands, among the other rows -- also the row it ends up at.
        """

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802  (Qt API name)
        # **No wrapper of an object Qt made is kept, and none is fetched through a temporary.** A view Qt makes -- a
        # column of a column view -- and its viewport can have their wrappers invalidated while they live (#459,
        # #461); a wrapper kept here then raised "already deleted" on every hover. Fetched afresh instead, the view
        # can come back as a new, unregistered wrapper -- and anything asked of a temporary one goes with it, so its
        # viewport, fetched through it, died the moment the expression ended. Hence: the viewport is ``watched``,
        # which Qt hands over for this event, and the view is fetched once here and held for the whole event.
        viewport = cast(QWidget, watched)
        view = cast(QAbstractItemView, self.parent())
        kind = event.type()
        if isinstance(event, QMouseEvent):
            return self.__on_mouse(view, viewport, kind, event)
        if kind == QEvent.Type.ToolTip and isinstance(event, QHelpEvent):
            return GripReorderFilter.__show_grip_tooltip(view, viewport, event)
        if kind in (QEvent.Type.DragEnter, QEvent.Type.DragMove) and isinstance(event, QDragMoveEvent):
            return self.__on_drag_over(view, viewport, event)
        if kind == QEvent.Type.Drop and isinstance(event, QDropEvent):
            return self.__on_drop(view, viewport, event)
        if kind == QEvent.Type.DragLeave:
            # the pointer is elsewhere: the shadow goes back to where the row came from, until the drag ends
            if self.__drag.leave():
                viewport.update()
            return True
        return False

    @staticmethod
    def __on_grip(view: QAbstractItemView, position: QPoint) -> bool:
        """Whether a point of the viewport is on the grip of a row that can be dragged.

        :param view: the view.
        :param position: the point, in the viewport's coordinates.
        :returns: whether it is.
        """
        index = view.indexAt(position)
        if not index.isValid() or not index.flags() & Qt.ItemFlag.ItemIsDragEnabled:
            return False
        first = index.siblingAtColumn(0)
        return 0 <= position.x() - view.visualRect(first).left() < GRIP_WIDTH

    def __on_mouse(self, view: QAbstractItemView, viewport: QWidget, kind: QEvent.Type, event: QMouseEvent) -> bool:
        """Remember a press on a grip and start the drag once the pointer has moved far enough; show the hand cursor
        over a grip.

        :param view: the view.
        :param viewport: its viewport.
        :param kind: the event's type.
        :param event: the mouse event.
        :returns: whether the event was taken -- only the move that starts a drag is.
        """
        point = event.position().toPoint()
        if kind == QEvent.Type.MouseButtonPress:
            on_grip = event.button() == Qt.MouseButton.LeftButton and GripReorderFilter.__on_grip(view, point)
            self.__press = (view.indexAt(point).row(), point) if on_grip else None
        elif kind == QEvent.Type.MouseButtonRelease:
            self.__press = None
        elif kind == QEvent.Type.MouseMove and not event.buttons():
            if GripReorderFilter.__on_grip(view, point):
                viewport.setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                viewport.unsetCursor()
        elif kind == QEvent.Type.MouseMove and self.__press is not None:
            row, pressed = self.__press
            if (point - pressed).manhattanLength() >= QApplication.startDragDistance():
                self.__press = None
                self.__start_drag(view, viewport, row)
                return True
        return False

    def __start_drag(self, view: QAbstractItemView, viewport: QWidget, row: int) -> None:
        """Drag the row at ``row``, as a card list drags a card: its place is the shadow for the length of the drag.

        :param view: the view.
        :param viewport: its viewport.
        :param row: the dragged row.
        """
        model = view.model()
        index = model.index(row, 0)
        rect = GripReorderFilter.__row_rect(view, index)
        drag = QDrag(viewport)
        drag.setMimeData(model.mimeData([index]))
        # before the drag begins: from then on the row paints as the shadow
        drag.setPixmap(viewport.grab(rect))
        drag.setHotSpot(QPoint(GRIP_WIDTH // 2, rect.height() // 2))
        self.__drag.begin(row)
        viewport.update()
        drag.exec(Qt.DropAction.MoveAction)
        self.__drag.end()
        viewport.update()

    @staticmethod
    def __row_rect(view: QAbstractItemView, index: QModelIndex) -> QRect:
        """Where a whole row is shown, every column of it.

        :param view: the view.
        :param index: the row's first cell.
        :returns: the row's rectangle, in the viewport's coordinates.
        """
        rect = view.visualRect(index)
        for column in range(1, view.model().columnCount(index.parent())):
            rect = rect.united(view.visualRect(index.siblingAtColumn(column)))
        return rect

    def __dragged_row(self, view: QAbstractItemView, event: QDropEvent) -> int | None:
        """The row a drag this filter started carries.

        :param view: the view.
        :param event: the drag event.
        :returns: the dragged row, or ``None`` for any other drag.
        """
        if not self.__drag.active:
            return None
        row = self.__drag.dragged
        return row if self._carries(view.model(), event.mimeData(), row) else None

    def __slot_at(self, view: QAbstractItemView, y: float) -> int:
        """The place the dragged row would end up at for a drop at ``y``, by the card list's rule.

        :param view: the view.
        :param y: the pointer's height, in the viewport's coordinates.
        :returns: the place, among the other rows.
        """
        model = view.model()
        centers = (
            view.visualRect(model.index(row, 0)).center().y()
            for row in range(model.rowCount())
            if row != self.__drag.slot
        )
        return drop_slot(y, centers)

    def __on_drag_over(self, view: QAbstractItemView, viewport: QWidget, event: QDragMoveEvent) -> bool:
        """Follow a drag of ours with the shadow; refuse any other.

        :param view: the view.
        :param viewport: its viewport.
        :param event: the enter or move event.
        :returns: ``True``: no drag over this view is the view's own.
        """
        if self.__dragged_row(view, event) is None:
            event.ignore()
            return True
        event.acceptProposedAction()
        if self.__drag.place(self.__slot_at(view, event.position().y())):
            viewport.update()
        return True

    def __on_drop(self, view: QAbstractItemView, viewport: QWidget, event: QDropEvent) -> bool:
        """Move the dragged row to where its shadow stands.

        :param view: the view.
        :param viewport: its viewport.
        :param event: the drop.
        :returns: ``True``: no drop on this view is the view's own.
        """
        row = self.__dragged_row(view, event)
        if row is None:
            event.ignore()
            return True
        slot = self.__slot_at(view, event.position().y())
        event.acceptProposedAction()
        self.__drag.end()
        viewport.update()
        self._move(view.model(), row, slot)
        return True

    @staticmethod
    def __show_grip_tooltip(view: QAbstractItemView, viewport: QWidget, event: QHelpEvent) -> bool:
        """Say what the grip is for while the pointer rests on one, in the card list's words.

        :param view: the view.
        :param viewport: its viewport.
        :param event: the tooltip request.
        :returns: whether it was answered; a point off every grip is left to the view's own tooltip.
        """
        point = event.pos()
        if not GripReorderFilter.__on_grip(view, point):
            return False
        row = view.visualRect(view.indexAt(point).siblingAtColumn(0))
        # the tooltip goes away when the pointer leaves the grip, not when it leaves the row
        QToolTip.showText(
            event.globalPos(), GRIP_TOOLTIP, viewport, QRect(row.left(), row.top(), GRIP_WIDTH, row.height())
        )
        return True
