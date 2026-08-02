"""The machinery a list editor is made of: a view over a model, and the two action columns."""

from typing import Final

from PySide6.QtCore import (
    QAbstractItemModel,
    QAbstractProxyModel,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
    Signal,
)
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QHBoxLayout,
    QSizePolicy,
    QWidget,
)

from .item_action_button_column import ItemEditActionsColumn, ItemOrderingActionsColumn
from .item_protocols import ItemEditor, ItemOrderingEditor


class ItemListEditor(QWidget):
    """Edit an ordered list in place, with buttons and keys for both halves of the job.

    The widget is a view over a model, and two `ActionButtonColumn`s built from it
    (`ItemEditActionsColumn`, `ItemOrderingActionsColumn`) -- reachable through :attr:`item_actions` and
    :attr:`ordering_actions`, which is where a consuming app hangs its icons; this widget ships none, so
    it never drags an icon set into a generic library.

    **This widget is the `ItemViewer`.** It is the one thing that holds the actual `QAbstractItemView`,
    so it is the one thing that can say which row is current and open one for typing -- everything about
    *what the list holds* (`ItemEditor`) and *where an entry sits* (`ItemOrderingEditor`) belongs to the
    model instead, and the model passed in here is expected to implement both. This widget never mutates
    the model on its own initiative: every insert/delete/move a user makes goes through the model's own
    methods, reached by the two columns, not by this class.

    The shortcuts (``Ins``, ``F2``, ``Del``, ``Ctrl+Home``/``Up``/``Down``/``End``) are armed on the
    view alone, so they fire only while the view itself has focus. That is what makes ``Del`` delete a
    *character* while an entry is open for editing: the delegate's editor is a `QLineEdit` child holding
    the focus in the view's stead, and a `Qt.ShortcutContext.WidgetShortcut` armed on the view does not
    reach it. ``Ctrl+Home``/``Ctrl+End`` take those keys away from the view's own jump-to-first/last-row
    navigation, which is the trade this widget makes deliberately.

    **The one thing no model or protocol can own: abandoning a blank insert.** A whitespace-only commit
    lands in the model, then the delegate's ``closeEditor`` undoes it an instant later -- a view-level
    signal nothing but this widget can see. It reacts to the model's own ``rowsInserted`` (not to
    however the insert was triggered) to remember which row is newly-inserted and so far untyped-into --
    a row from *any* insert, not just one made through :meth:`ItemEditActionsColumn`'s button, gets this
    treatment, which is the more honest generic behavior. `row_is_blank` decides what "still blank"
    means; abandoning it is the model's own `QAbstractItemModel.removeRow`, called directly rather than
    through `ItemEditor.delete` -- an abandoned insert was never a choice the way a real delete is.

    :param view: the view to show the rows in, built by the subclass and reparented here. A view sized
        to its rows (`ContentSizedListView`, `ContentSizedTableView`) keeps an enclosing page's scroll
        area doing the scrolling, instead of a second scrollbar appearing inside a widget the reader
        must first scroll *to*.
    :param model: the list itself, reparented here; must implement both `ItemEditor` and
        `ItemOrderingEditor` as well as the `QAbstractItemModel` surface a view needs.
    :param parent: optional Qt parent.
    :param with_ordering: whether the ordering column is shown. Off for a list whose order carries no
        meaning, where four move buttons would invite an edit that changes nothing. Settable later
        through :meth:`set_ordering_visible`, for a widget promoted into a ``.ui`` (constructed with a
        parent and nothing else).
    :param proxy: an optional proxy to put between the view and the model -- a filter, a sort, or both.
        The view is given the proxy and the *model* is still what everything else here talks to, so a
        filtered list is one model with a view onto part of it rather than a second code path: the two
        columns, the shortcuts, the abandoned-insert rule and the reported edits are all unchanged and
        unaware. Only :attr:`current_index` and :meth:`set_current_index` know the difference, because a
        row number is the one thing the two row spaces disagree about -- and those are stated in **source**
        rows, the space every model call is already in, so a caller never has to map either.
    """

    values_changed = Signal()
    """Emitted once per edit -- an entry added, retyped, deleted, moved, or the whole list replaced."""

    current_index_changed = Signal()
    """Fires whenever :attr:`current_index` changes -- the `ItemViewer` contract."""

    def __init__(
        self,
        view: QAbstractItemView,
        model: QAbstractItemModel,
        parent: QWidget | None = None,
        *,
        with_ordering: bool = True,
        proxy: QAbstractProxyModel | None = None,
    ) -> None:
        super().__init__(parent)
        # the row an insert just made, until its editor closes -- persistent, so it still names that
        # entry if anything shifts the rows underneath it (see __on_editor_closed)
        self.__pending_entry = QPersistentModelIndex()
        # set only around the abandon-undo removeRow call, the one edit that must report nothing
        # because it undoes an insert that itself was never reported either
        self.__quiet = False

        self.__model: Final = model
        model.setParent(self)
        self.__view: Final = view
        view.setParent(self)
        self.__proxy: Final = proxy
        if proxy is None:
            view.setModel(model)
        else:
            proxy.setParent(self)
            proxy.setSourceModel(model)
            view.setModel(proxy)
        # banded rows: the entries are short values with little other structure to read a row boundary
        # from, and these lists have no grid to supply one
        view.setAlternatingRowColors(True)

        # the concrete model is expected to satisfy both protocols; QAbstractItemModel's own typing has
        # no way to express that intersection, so the two lines below are where it's asserted
        editor: ItemEditor = model  # type: ignore[assignment]  # the model also implements ItemEditor
        ordering: ItemOrderingEditor = model  # type: ignore[assignment]  # ...and ItemOrderingEditor
        # the ignore is the same one bind_value_widget's callers need, for the same reason: PySide
        # types a class-level ``Signal`` as ``Signal``, not as the ``SignalInstance`` an *instance*
        # actually exposes, so ``self`` never satisfies ``ItemViewer`` statically despite implementing it
        self.__item_actions: Final = ItemEditActionsColumn(editor, self, self)  # type: ignore[arg-type]
        self.__ordering_actions: Final = ItemOrderingActionsColumn(ordering, self, self)  # type: ignore[arg-type]

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.__view, 1)
        # ordering first, so the column that moves the row the buttons point at sits against the list
        layout.addWidget(self.__ordering_actions)
        layout.addWidget(self.__item_actions)
        # the view is sized to its rows, so it is shorter than the button columns whenever it holds
        # few of them -- and a layout centres a short item in its cell, leaving a one-entry list
        # floating with white space above it and its first row level with nothing
        for widget in (self.__view, self.__ordering_actions, self.__item_actions):
            layout.setAlignment(widget, Qt.AlignmentFlag.AlignTop)
        # Maximum, not Preferred: everything inside is either row-sized or button-sized, so there is
        # nothing here that could use extra height -- height given to it would be blank space under
        # the last row, which reads as entries the user cannot see
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        self.__wire()
        self.set_ordering_visible(with_ordering)

    @property
    def view(self) -> QAbstractItemView:
        """The view the rows are shown and edited in -- also the widget the shortcuts are armed on."""
        return self.__view

    @property
    def model(self) -> QAbstractItemModel:
        """The list itself: every domain operation is a call on it, and its signals are what report an edit."""
        return self.__model

    @property
    def item_actions(self) -> ItemEditActionsColumn:
        """The insert/edit/delete/reset column -- where a consuming app sets those icons."""
        return self.__item_actions

    @property
    def ordering_actions(self) -> ItemOrderingActionsColumn:
        """The top/up/down/bottom column -- where a consuming app sets those four icons."""
        return self.__ordering_actions

    # region ItemViewer

    @property
    def current_index(self) -> int:
        """The row being acted on, as a **source** row; ``-1`` when there is none.

        Source rather than view rows because that is the space every model call is in: the two columns
        read this and hand it straight to `ItemEditor`/`ItemOrderingEditor`, which know only the model. A
        filtered-out or reordered row is therefore never acted on by its position on screen."""
        index = self.__view.currentIndex()
        if self.__proxy is not None:
            index = self.__proxy.mapToSource(index)
        return index.row()

    def set_current_index(self, row: int) -> None:
        """Make ``row`` the current one.

        :param row: the **source** row to select, or a negative row to select none. A row the proxy does
            not show maps to an invalid index, which selects nothing -- the honest answer for a row that
            is not on screen to be current *on*.
        """
        index = self.__model.index(row, 0) if row >= 0 else QModelIndex()
        if self.__proxy is not None:
            index = self.__proxy.mapFromSource(index)
        self.__view.setCurrentIndex(index)

    def edit_current(self) -> None:
        """Open the current entry for in-place editing; a no-op with no current entry."""
        index = self.__view.currentIndex()
        if index.isValid():
            self.__view.edit(index)

    # endregion

    def set_ordering_visible(self, visible: bool) -> None:
        """Show or hide the ordering column.

        :param visible: whether the top/up/down/bottom buttons are shown. Hiding them takes their
            shortcuts with them, so a hidden column is not reachable by key either.
        """
        self.__ordering_actions.setVisible(visible)
        for action in self.__ordering_action_list():
            self.__view.removeAction(action)
            if visible:
                self.__view.addAction(action)

    def row_is_blank(self, row: int) -> bool:
        """Whether ``row`` holds nothing yet -- what makes an insert abandonable rather than an entry.

        The **first column** by default, because that is the cell an insert opens: a row is abandoned
        exactly when the editor that insert opened closes with nothing typed into it, and by then no
        other cell has been reachable. Override where a row needs more than that to count as one.
        Deliberately not "every column": `QAbstractListModel` makes ``columnCount`` private, so a
        column sweep is not something a *generic* editor can even ask its model for.

        :param row: the row to test.
        :returns: whether its first cell strips to nothing.
        """
        return not str(self.__model.index(row, 0).data() or "").strip()

    def __wire(self) -> None:
        """Arm the item/ordering shortcuts on the view, and watch the model and the selection.

        ``__on_row_inserted`` is connected to ``rowsInserted`` **before** ``__on_model_changed`` --
        connection order is emission order, so the newly-inserted row is already recorded as pending by
        the time ``__on_model_changed`` asks whether to suppress reporting it.
        """
        for action in (
            self.__item_actions.insert_action,
            self.__item_actions.edit_action,
            self.__item_actions.delete_action,
        ):
            self.__view.addAction(action)
        self.__model.rowsInserted.connect(self.__on_row_inserted)
        for signal in (
            self.__model.rowsInserted,
            self.__model.rowsRemoved,
            self.__model.rowsMoved,
            self.__model.modelReset,
            self.__model.dataChanged,
        ):
            signal.connect(self.__on_model_changed)
        # current_index can shift without the selection model itself ever reporting a change: a move
        # carries the current row along by persistent index, silently, and a reset can invalidate it
        # with nothing to call currentChanged on. Wired here rather than left to currentChanged alone,
        # so the two columns' enabled state never goes stale after either.
        for signal in (
            self.__model.rowsInserted,
            self.__model.rowsRemoved,
            self.__model.rowsMoved,
            self.__model.modelReset,
        ):
            signal.connect(self.current_index_changed)
        selection = self.__view.selectionModel()
        selection.currentChanged.connect(self.__on_current_changed)
        delegate = self.__view.itemDelegate()
        delegate.closeEditor.connect(self.__on_editor_closed)

    def __ordering_action_list(self) -> tuple[QAction, ...]:
        """The ordering column's four actions, in column order.

        :returns: top, up, down, bottom.
        """
        actions = self.__ordering_actions
        return (
            actions.move_to_top_action,
            actions.move_up_action,
            actions.move_down_action,
            actions.move_to_bottom_action,
        )

    def __on_row_inserted(self, parent: QModelIndex, first: int, last: int) -> None:
        """Remember a freshly-inserted row as pending -- abandonable until something is typed into it.

        :param parent: the parent index the row was inserted under; unused, this model is flat.
        :param first: the first inserted row.
        :param last: the last inserted row; unused, `ItemEditor.insert` only ever inserts one at a time.
        """
        del parent, last
        self.__pending_entry = QPersistentModelIndex(self.__model.index(first, 0))

    def __on_model_changed(self, *args: object) -> None:
        """Report the edit the model just made, unless it was the silent half of an abandoned insert.

        :param args: whichever signal's arguments arrived; unused, a reader asks for the values.
        """
        del args
        if self.__quiet or self.__pending_entry_is_blank():
            return
        self.values_changed.emit()

    def __pending_entry_is_blank(self) -> bool:
        """Whether an inserted entry is still open and still blank -- a gesture, not yet a value.

        :returns: whether the pending entry exists and its row is still blank.
        """
        return self.__pending_entry.isValid() and self.row_is_blank(self.__pending_entry.row())

    def __on_current_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        """Report that :attr:`current_index` changed.

        :param current: the new current index; unused, a reader asks :attr:`current_index`.
        :param previous: the index left behind; unused.
        """
        del current, previous
        self.current_index_changed.emit()

    def __on_editor_closed(self, editor: QWidget, hint: QAbstractItemDelegate.EndEditHint) -> None:
        """Undo an insert whose entry was left blank -- an abandoned gesture, not an empty value.

        :param editor: the editor widget that closed; unused, only one entry is ever pending.
        :param hint: what the delegate wants done next; unused, a cancelled and a committed-blank
            edit are both "no entry was typed".
        """
        del editor, hint
        pending, self.__pending_entry = self.__pending_entry, QPersistentModelIndex()
        if not pending.isValid() or not self.row_is_blank(pending.row()):
            return
        # silent, like the insert that made it: the two together left the list exactly as it was
        self.__quiet = True
        try:
            self.__model.removeRow(pending.row())
        finally:
            self.__quiet = False
