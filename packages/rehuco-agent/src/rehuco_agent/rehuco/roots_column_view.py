"""The Roots view's column view (#378)."""

from collections.abc import Collection
from typing import cast, override
from uuid import UUID

from borco_pyside.widgets import ReorderDrag
from PySide6.QtCore import QAbstractItemModel, QEvent, QModelIndex, QPersistentModelIndex, QPoint, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QAbstractItemView, QColumnView, QListView, QWidget
from rehuco_core import FileType

from ..fields.widgets.image_export import PressDragFilter
from .root_row_delegate import RootRowDelegate
from .roots_folder_model import RootsFolderModel
from .roots_grip import RootsGripFilter
from .roots_item_delegate import RootsItemDelegate


class RootsColumnView(QColumnView):
    """A ``QColumnView`` whose every column is drawn by a :class:`RootsItemDelegate`.

    ``QColumnView`` puts a delegate of its own on each column it creates, and ignores one set on the view, so the
    columns are made here.

    **A row with nothing under it opens no empty column.** ``QColumnView`` ends the columns with a preview column for
    a file, whether it has a preview widget or not, and this view has a details pane of its own beside it that shows
    every row, a folder's and a root's too -- so that column is collapsed to nothing.

    **With no roots the first column still has the model** (#570), so it is drawn like any column and its background
    answers :meth:`column_root_at_global`, which the menu of an empty catalog needs.

    **An image row can be dragged out** (#395): a press on one that moves the drag distance reports it through
    :attr:`image_drag_requested`, for the owner -- which knows what record manages the row -- to export.

    **A root that duplicates an earlier one is drawn in red** (#498, :meth:`set_duplicate_roots`).

    :param parent: optional Qt parent.
    """

    image_drag_requested = Signal(QModelIndex, QWidget, QPixmap)
    """``(row, widget, picture)``: an image row has been dragged away from; the widget is the one the drag starts
    from and the picture is the row as drawn."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__duplicate_roots: frozenset[UUID] = frozenset()
        self.__collapse_preview_column()
        # the preview column exists by the time a row with nothing under it is current, whenever it was made
        self.updatePreviewWidget.connect(self.__collapse_preview_column)

    @override
    def setModel(self, model: QAbstractItemModel | None) -> None:  # noqa: N802
        super().setModel(model)
        if model is not None:
            model.modelReset.connect(self.__sync_empty_roots_column)
            model.rowsInserted.connect(self.__sync_empty_roots_column)
        self.__sync_empty_roots_column()

    def __sync_empty_roots_column(self) -> None:
        """Give the column of roots the model while there are no roots, and take it back with the first one (#570).

        With no rows ``QColumnView`` has nothing to open a column on, so it shows its bare preview column, which has
        no model: it is drawn grey, and :meth:`column_root_at_global` skips it, so the background of an empty catalog
        has no menu. That column is kept, and becomes the preview column once there are rows, which is the one item
        view here without a model (:meth:`__collapse_preview_column`).
        """
        model = self.model()
        bare = self.__bare_column()
        if model is None or bare is None:
            return
        if model.rowCount() == 0:
            bare.setModel(model)
            # a column made for rows fills its viewport with the base colour; the preview column does not
            bare.viewport().setAutoFillBackground(True)
        elif bare.model() is not None:
            bare.setModel(None)
            # the column of roots was created, and collapsed nothing, while this one still had the model
            self.__collapse_preview_column()

    def __bare_column(self) -> QAbstractItemView | None:
        """The preview column, whether or not it stands in for the column of roots: the one item view here that
        :meth:`createColumn` did not make. Looked up each time, never kept: it is Qt's, and Qt replaces it.

        :returns: the column; ``None`` before ``QColumnView`` has made it.
        """
        return next(
            (c for c in self.findChildren(QAbstractItemView) if c is not self and not isinstance(c, QListView)), None
        )

    @override
    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        super().changeEvent(event)
        # a style change -- a stylesheet set on an ancestor, which the dock manager does on a palette change --
        # unpolishes every column, and the Windows style's unpolish leaves a scroll area's viewport unfilled; the
        # children are restyled before the view hears of it, so the fill is put back here
        if event.type() == QEvent.Type.StyleChange:
            bare = self.__bare_column()
            if bare is not None and bare.model() is not None:
                bare.viewport().setAutoFillBackground(True)

    @override
    def createColumn(self, index: QModelIndex | QPersistentModelIndex) -> QAbstractItemView:  # noqa: N802
        column = super().createColumn(index)
        if index.isValid():
            column.setItemDelegate(RootsItemDelegate(column))
            self.__make_image_rows_draggable(column)
        else:
            # the first column lists the roots, which have a folder to show under their names, and are reordered by
            # a drag whose shadow the delegate paints and the grip filter moves
            drag = ReorderDrag()
            column.setItemDelegate(RootRowDelegate(column, drag, lambda: self.__duplicate_roots))
            RootsColumnView.__make_reorderable(column, drag)
        self.__collapse_preview_column()
        return column

    def set_duplicate_roots(self, root_ids: Collection[UUID]) -> None:
        """Say which roots duplicate an earlier one, to be drawn in red, and redraw the columns.

        :param root_ids: their ids.
        """
        self.__duplicate_roots = frozenset(root_ids)
        for column in self.findChildren(QAbstractItemView):
            column.viewport().update()

    def __make_image_rows_draggable(self, column: QAbstractItemView) -> None:
        """Let a row of an image file in a column be dragged out to other apps (#395).

        :param column: a column listing a folder's children.
        """
        viewport = column.viewport()

        def image_row_at(point: QPoint) -> object | None:
            index = column.indexAt(point)
            model = column.model()
            is_image = (
                index.isValid() and isinstance(model, RootsFolderModel) and model.file_type_of(index) is FileType.IMAGE
            )
            return QPersistentModelIndex(index) if is_image else None

        def start(token: object) -> None:
            # a row removed since the press comes back invalid, and the owner turns an invalid row away
            held = cast(QPersistentModelIndex, token)
            row = column.model().index(held.row(), held.column(), held.parent())
            self.image_drag_requested.emit(row, viewport, viewport.grab(column.visualRect(row)))

        PressDragFilter(viewport, image_row_at, start)

    @staticmethod
    def __make_reorderable(column: QAbstractItemView, drag: ReorderDrag) -> None:
        """Let the column that lists the roots take a root dragged by its grip to another place.

        The drag is :class:`~rehuco_agent.rehuco.roots_grip.RootsGripFilter`'s, the card list's behaviour: the view's
        own drag and its drop line stay off, and the column only takes drops, every one of which the filter answers.

        :param column: the first column.
        :param drag: the drag's bookkeeping, shared with the column's delegate.
        """
        column.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        column.setDefaultDropAction(Qt.DropAction.MoveAction)
        column.setDropIndicatorShown(False)
        column.setDragEnabled(False)
        column.setMouseTracking(True)
        column.viewport().setMouseTracking(True)
        grip_filter = RootsGripFilter(column, drag)
        column.viewport().installEventFilter(grip_filter)
        # the roots changing under a drag -- a scan's end, a relist -- abandons it, as a card list's rows do
        model = column.model()
        for signal in (model.rowsInserted, model.rowsRemoved, model.rowsMoved):
            signal.connect(grip_filter.abandon)
        model.modelReset.connect(lambda: grip_filter.abandon(None))

    def __collapse_preview_column(self, *_args: object) -> None:
        """Give the preview column no width. The view only ever moves it, so a maximum would not shrink it.

        The preview column is the one item view here that is given no model.
        """
        for column in self.findChildren(QAbstractItemView):
            if column is not self and column.model() is None:
                column.setFixedWidth(0)

    def index_at_global(self, position: QPoint) -> QModelIndex:
        """The row under a point on screen, in whichever column it falls.

        :param position: the point, in global coordinates.
        :returns: the row's index; invalid when the point is on no row.
        """
        for column in self.findChildren(QAbstractItemView):
            if not column.isVisible() or column is self:
                continue
            local = column.viewport().mapFromGlobal(position)
            index = column.indexAt(local) if column.viewport().rect().contains(local) else QModelIndex()
            if index.isValid():
                return index
        return QModelIndex()

    def column_root_at_global(self, position: QPoint) -> QModelIndex | None:
        """The folder whose column holds a point on screen: the row that column lists the children of.

        :param position: the point, in global coordinates.
        :returns: the folder's or root's index; invalid for the column of roots; None off every column.
        """
        for column in self.findChildren(QAbstractItemView):
            if not column.isVisible() or column is self or column.model() is None:
                continue
            if column.viewport().rect().contains(column.viewport().mapFromGlobal(position)):
                return QModelIndex(column.rootIndex())
        return None
