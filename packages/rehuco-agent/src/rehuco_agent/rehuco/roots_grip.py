"""The band a root is dragged by in the Roots view, and what it shows while one is dragged -- the cues of the grip a
card of a list is dragged by (#378, #461)."""

from typing import Final, cast, override
from uuid import UUID

from borco_pyside.widgets import ReorderDrag, drop_slot
from PySide6.QtCore import QEvent, QModelIndex, QObject, QPoint, QRect, Qt
from PySide6.QtGui import QColor, QDrag, QDragMoveEvent, QDropEvent, QHelpEvent, QMouseEvent, QPainter
from PySide6.QtWidgets import QAbstractItemView, QApplication, QToolTip, QWidget

from .roots_folder_model import ROOT_MIME_TYPE, RootsFolderModel

GRIP_WIDTH: Final = 16
"""The band at the left of a root row that drags it, in pixels."""

DOT_SIZE: Final = 3
"""The side of one dot of the grip, in pixels."""

DOT_GAP: Final = 3
"""The space between dots, in pixels."""

DOT_ALPHA: Final = 150
"""How opaque the dots are against the row, so the grip reads as a handle and not as text."""

GRIP_TOOLTIP: Final = "Drag to reorder"
"""What hovering a grip says, as the card list's grip says it."""


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


class RootsGripFilter(QObject):
    """Drags a root by its grip, and only by it, exactly as a card of a card list is dragged
    (:class:`~borco_pyside.widgets.CardListEditor`): the root leaves its place, which becomes the shadow; the shadow
    follows the pointer to where the root would land, the other roots closing up around it; over its own place the
    shadow is simply where the root was; leaving the list puts it back there until the drag ends; the drop moves the
    root to the shadow's place. The shadow's bookkeeping, look and landing rule are the card list's own
    (:class:`~borco_pyside.widgets.ReorderDrag`, :func:`~borco_pyside.widgets.paint_drag_ghost`,
    :func:`~borco_pyside.widgets.drop_slot`).

    **The drag is this filter's, not the view's.** A list view starts a drag from anywhere on a draggable row, and drops
    between rows with a line; so the view's own drag stays off, a press on a grip followed by a move past the drag
    distance starts one here, and every drag event of the column is answered here. A list view cannot open a gap
    between its rows, so while a root is dragged the column's delegate paints the rows in the order they would take,
    from the same :class:`~borco_pyside.widgets.ReorderDrag`.

    Shows the hand cursor and the card list's tooltip over a grip. Installed on the viewport of the column that lists
    the roots.

    :param column: the column whose viewport this watches.
    :param drag: the drag's bookkeeping, which the column's delegate paints the rows from.
    """

    def __init__(self, column: QAbstractItemView, drag: ReorderDrag) -> None:
        super().__init__(column)
        self.__drag: Final = drag
        self.__press: tuple[int, QPoint] | None = None
        """The row whose grip the left button went down on, and where; ``None`` otherwise."""

    def abandon(self, parent: QModelIndex | None, *_args: object) -> None:
        """Give up the drag when the roots changed under it -- a scan ended, a relist -- so the shadow never names a
        row that is no longer there; the drop that follows is refused, as a card list refuses one after its rows
        changed. Connected to the model's row signals; a change under a folder (``parent`` valid) is not one.

        :param parent: the parent of the rows that changed, for the row signals; ``None`` for a reset.
        """
        if (parent is not None and parent.isValid()) or not self.__drag.active:
            return
        self.__drag.end()
        # one expression: the column wrapper is a temporary (#459), and its viewport is used before it goes
        cast(QAbstractItemView, self.parent()).viewport().update()

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802  (Qt API name)
        # **No wrapper of an object Qt made is kept, and none is fetched through a temporary.** The column and its
        # viewport are both made by Qt, and shiboken can invalidate such a wrapper while the object lives (#459,
        # #461); a wrapper kept here then raised "already deleted" on every hover. Fetched afresh instead, the column
        # can come back as a new, unregistered wrapper -- and anything asked of a temporary one goes with it, so its
        # viewport, fetched through it, died the moment the expression ended. Hence: the viewport is ``watched``,
        # which Qt hands over for this event, and the column is fetched once here and held for the whole event.
        viewport = cast(QWidget, watched)
        column = cast(QAbstractItemView, self.parent())
        kind = event.type()
        if isinstance(event, QMouseEvent):
            return self.__on_mouse(column, viewport, kind, event)
        if kind == QEvent.Type.ToolTip and isinstance(event, QHelpEvent):
            return RootsGripFilter.__show_grip_tooltip(column, viewport, event)
        if kind in (QEvent.Type.DragEnter, QEvent.Type.DragMove) and isinstance(event, QDragMoveEvent):
            return self.__on_drag_over(column, viewport, event)
        if kind == QEvent.Type.Drop and isinstance(event, QDropEvent):
            return self.__on_drop(column, viewport, event)
        if kind == QEvent.Type.DragLeave:
            # the pointer is elsewhere: the shadow goes back to where the root came from, until the drag ends
            if self.__drag.leave():
                viewport.update()
            return True
        return False

    @staticmethod
    def __on_grip(column: QAbstractItemView, position: QPoint) -> bool:
        """Whether a point of the viewport is on the grip of a row that can be dragged.

        :param column: the column.
        :param position: the point, in the viewport's coordinates.
        :returns: whether it is.
        """
        index = column.indexAt(position)
        if not index.isValid() or not index.flags() & Qt.ItemFlag.ItemIsDragEnabled:
            return False
        return position.x() - column.visualRect(index).left() < GRIP_WIDTH

    def __on_mouse(self, column: QAbstractItemView, viewport: QWidget, kind: QEvent.Type, event: QMouseEvent) -> bool:
        """Remember a press on a grip and start the drag once the pointer has moved far enough; show the hand cursor
        over a grip.

        :param column: the column.
        :param viewport: its viewport.
        :param kind: the event's type.
        :param event: the mouse event.
        :returns: whether the event was taken -- only the move that starts a drag is.
        """
        point = event.position().toPoint()
        if kind == QEvent.Type.MouseButtonPress:
            on_grip = event.button() == Qt.MouseButton.LeftButton and RootsGripFilter.__on_grip(column, point)
            self.__press = (column.indexAt(point).row(), point) if on_grip else None
        elif kind == QEvent.Type.MouseButtonRelease:
            self.__press = None
        elif kind == QEvent.Type.MouseMove and not event.buttons():
            if RootsGripFilter.__on_grip(column, point):
                viewport.setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                viewport.unsetCursor()
        elif kind == QEvent.Type.MouseMove and self.__press is not None:
            row, pressed = self.__press
            if (point - pressed).manhattanLength() >= QApplication.startDragDistance():
                self.__press = None
                self.__start_drag(column, viewport, row)
                return True
        return False

    def __start_drag(self, column: QAbstractItemView, viewport: QWidget, row: int) -> None:
        """Drag the root at ``row``, as a card list drags a card: its place is the shadow for the length of the drag.

        :param column: the column.
        :param viewport: its viewport.
        :param row: the dragged root's row.
        """
        model = column.model()
        index = model.index(row, 0)
        rect = column.visualRect(index)
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

    def __dragged_row(self, column: QAbstractItemView, event: QDropEvent) -> int | None:
        """The row a drag this filter started carries.

        :param column: the column.
        :param event: the drag event.
        :returns: the dragged row, or ``None`` for any other drag -- a root of another catalog's view included.
        """
        model = column.model()
        mime = event.mimeData()
        if not self.__drag.active or not isinstance(model, RootsFolderModel) or not mime.hasFormat(ROOT_MIME_TYPE):
            return None
        try:
            root_id = UUID(bytes(mime.data(ROOT_MIME_TYPE).data()).decode("ascii"))
        except ValueError:
            return None
        root = model.root_at(model.index(self.__drag.dragged, 0))
        return self.__drag.dragged if root is not None and root.root_id == root_id else None

    def __slot_at(self, column: QAbstractItemView, y: float) -> int:
        """The place the dragged root would end up at for a drop at ``y``, by the card list's rule.

        :param column: the column.
        :param y: the pointer's height, in the viewport's coordinates.
        :returns: the place, among the other roots.
        """
        model = column.model()
        centers = (
            column.visualRect(model.index(row, 0)).center().y()
            for row in range(model.rowCount())
            if row != self.__drag.slot
        )
        return drop_slot(y, centers)

    def __on_drag_over(self, column: QAbstractItemView, viewport: QWidget, event: QDragMoveEvent) -> bool:
        """Follow a drag of ours with the shadow; refuse any other.

        :param column: the column.
        :param viewport: its viewport.
        :param event: the enter or move event.
        :returns: ``True``: no drag over this column is the view's.
        """
        if self.__dragged_row(column, event) is None:
            event.ignore()
            return True
        event.acceptProposedAction()
        if self.__drag.place(self.__slot_at(column, event.position().y())):
            viewport.update()
        return True

    def __on_drop(self, column: QAbstractItemView, viewport: QWidget, event: QDropEvent) -> bool:
        """Move the dragged root to where its shadow stands.

        :param column: the column.
        :param viewport: its viewport.
        :param event: the drop.
        :returns: ``True``: no drop on this column is the view's.
        """
        row = self.__dragged_row(column, event)
        if row is None:
            event.ignore()
            return True
        slot = self.__slot_at(column, event.position().y())
        event.acceptProposedAction()
        self.__drag.end()
        viewport.update()
        # a drag of ours is a root of this column's model, which __dragged_row has checked
        cast(RootsFolderModel, column.model()).request_root_move(row, slot)
        return True

    @staticmethod
    def __show_grip_tooltip(column: QAbstractItemView, viewport: QWidget, event: QHelpEvent) -> bool:
        """Say what the grip is for while the pointer rests on one, in the card list's words.

        :param column: the column.
        :param viewport: its viewport.
        :param event: the tooltip request.
        :returns: whether it was answered; a point off every grip is left to the view's own tooltip.
        """
        point = event.pos()
        if not RootsGripFilter.__on_grip(column, point):
            return False
        row = column.visualRect(column.indexAt(point))
        # the tooltip goes away when the pointer leaves the grip, not when it leaves the row
        QToolTip.showText(
            event.globalPos(), GRIP_TOOLTIP, viewport, QRect(row.left(), row.top(), GRIP_WIDTH, row.height())
        )
        return True
