"""The machinery a list editor is made of: a view over a model, and the two action columns."""

from typing import Final, override

from PySide6.QtCore import (
    QAbstractItemModel,
    QAbstractProxyModel,
    QEvent,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QSizePolicy,
    QWidget,
)

from .item_action_button_column import ItemEditActionsColumn, ItemOrderingActionsColumn
from .item_protocols import ItemEditor, ItemOrderingEditor


# the two attributes past the limit are the abandoned-insert rule's: state of one rule that only this
# widget can see, which is why it is kept here rather than in a helper object holding half of the view's
# signals
# pylint: disable-next=too-many-instance-attributes
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

    **When a blank insert is abandoned.** At once when its editor is cancelled, and at once when the
    editor closes on a row with no second editable cell to go on to (a one-column list). Otherwise the
    editor closed because the user is heading for another cell of the row, so the row waits: it is
    abandoned only when the user *leaves* it still blank -- the current row moves to another row, or the
    focus goes to something outside the view -- and then on the next pass through the event loop, never
    from inside the signal that reported the leaving: the view moves the current row off a row it is
    about to remove, and Qt goes on to open the next cell's editor by the index it computed before the
    row went, so a row taken out *during* either would take the wrong row with it or leave the next
    editor unopened. Focus is watched through an event filter this widget installs on the application
    while a row waits (:meth:`eventFilter`), not a connection to ``focusChanged``: Qt drops a destroyed
    object from every filter list, where a connected slot would outlive the view it reads and be called
    on the next focus change with nothing behind it. A row is blank only while **every** editable cell is
    (`row_is_blank`), so a row can be filled in any order: text in any one cell keeps it. Whether a row
    that is kept but still incomplete counts as a value is the model's business, not this widget's.

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
        # the application this widget filters focus events on while a blank insert waits to be left,
        # else None
        self.__leave_watch: QApplication | None = None
        # set between rowsAboutToBeRemoved and rowsRemoved when the removal takes the blank pending row
        # with it -- a Delete on it, say -- which is that insert abandoned, and not an edit to report
        self.__removing_pending = False
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

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt override)
        """Abandon a waiting blank insert once the focus lands somewhere outside the view.

        Installed on the application only while a row waits (:meth:`__wait_for_leave`). Focus landing
        nowhere -- the window deactivating, say to fetch a link from a browser and drop it here -- sends
        no ``FocusIn``, and so is not leaving the row.

        :param watched: the object the event is for.
        :param event: the event; only a widget's ``FocusIn`` is read, and nothing is ever consumed.
        :returns: ``False``, always -- this filter only watches.
        """
        if event.type() == QEvent.Type.FocusIn and isinstance(watched, QWidget):
            if watched is not self.__view and not self.__view.isAncestorOf(watched):
                self.__abandon_later()
        return False

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

        **Every editable cell** by default: a row is abandoned when it is cancelled or left with this
        still true, so text typed into any cell keeps it, in whatever order the cells were filled. Cells
        the user cannot type into -- a checkbox, a column derived from the others -- say nothing about
        whether anything was entered, and are not read. Override where a row needs a different test.

        :param row: the row to test.
        :returns: whether every editable cell's text strips to nothing.
        """
        return not any(str(cell.data() or "").strip() for cell in self.__editable_cells(row))

    def __editable_cells(self, row: int) -> list[QModelIndex]:
        """The cells of ``row`` a user can type into, left to right.

        Found by walking the columns until the model hands back an invalid index, rather than by asking
        ``columnCount``: `QAbstractListModel` makes that private, and its ``index`` already answers
        invalid past the one column it has.

        :param row: the row to read.
        :returns: its editable cells.
        """
        cells = []
        column = 0
        while (cell := self.__model.index(row, column)).isValid():
            if self.__model.flags(cell) & Qt.ItemFlag.ItemIsEditable:
                cells.append(cell)
            column += 1
        return cells

    def __wire(self) -> None:
        """Arm the item/ordering shortcuts on the view, and watch the model and the selection.

        ``__on_row_inserted`` is connected to ``rowsInserted`` **before** ``__on_rows_inserted`` --
        connection order is emission order, so the newly-inserted row is already recorded as pending by
        the time ``__on_rows_inserted`` asks whether to suppress reporting it.
        """
        for action in (
            self.__item_actions.insert_action,
            self.__item_actions.duplicate_action,
            self.__item_actions.edit_action,
            self.__item_actions.delete_action,
        ):
            self.__view.addAction(action)
        self.__model.rowsInserted.connect(self.__on_row_inserted)
        self.__model.rowsInserted.connect(self.__on_rows_inserted)
        self.__model.rowsAboutToBeRemoved.connect(self.__on_rows_about_to_be_removed)
        self.__model.rowsRemoved.connect(self.__on_rows_removed)
        self.__model.dataChanged.connect(self.__on_data_changed)
        for signal in (self.__model.rowsMoved, self.__model.modelReset):
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
        """Remember a freshly-inserted *blank* row as pending -- abandonable until something is typed
        into it.

        A row inserted already filled -- a `ItemEditor.duplicate` copy -- is a value from the moment it
        lands, not a gesture, so it is never pending: were it recorded, clearing it in the next cell edit
        would silently remove it, where clearing any other row leaves a blank one.

        :param parent: the parent index the row was inserted under; unused, this model is flat.
        :param first: the first inserted row.
        :param last: the last inserted row; unused, the editor protocol only ever inserts one at a time.
        """
        del parent, last
        if self.row_is_blank(first):
            # a blank row still waiting to be left is left now: the insert made the new row current
            stale = self.__pending_entry if self.__leave_watch is not None else None
            self.__end_pending()
            self.__pending_entry = QPersistentModelIndex(self.__model.index(first, 0))
            if stale is not None and stale.isValid():
                QTimer.singleShot(0, self, lambda: self.__abandon_stale(stale))

    def __on_model_changed(self, *args: object) -> None:
        """Report a move or a reset.

        :param args: whichever signal's arguments arrived; unused, a reader asks for the values.
        """
        del args
        self.values_changed.emit()

    def __on_rows_about_to_be_removed(self, parent: QModelIndex, first: int, last: int) -> None:
        """Take a removal of the blank pending row as that insert being abandoned.

        Read here, before the rows go, because the removal invalidates the persistent index that names
        the pending row -- and forgotten here, so the current row moving off the doomed row (which the
        view does next, from inside this same removal) finds nothing left to abandon.

        :param parent: the parent index; unused, this model is flat.
        :param first: the first row about to go.
        :param last: the last row about to go.
        """
        del parent
        if self.__touches_blank_pending(first, last):
            self.__end_pending()
            self.__removing_pending = True

    def __on_rows_removed(self, parent: QModelIndex, first: int, last: int) -> None:
        """Report a removal, unless it was an abandoned insert's -- silent, like the insert itself.

        :param parent: the parent index; unused.
        :param first: the first removed row; unused.
        :param last: the last removed row; unused.
        """
        del parent, first, last
        if self.__removing_pending:
            self.__removing_pending = False
            return
        if not self.__quiet:
            self.values_changed.emit()

    def __on_rows_inserted(self, parent: QModelIndex, first: int, last: int) -> None:
        """Report an insert, unless it made the blank pending row -- a gesture, not yet a value.

        :param parent: the parent index; unused, this model is flat.
        :param first: the first inserted row.
        :param last: the last inserted row.
        """
        del parent
        if not self.__quiet and not self.__touches_blank_pending(first, last):
            self.values_changed.emit()

    def __on_data_changed(self, top_left: QModelIndex, bottom_right: QModelIndex, roles: list[int]) -> None:
        """Report a cell edit, unless it left the pending row blank (a whitespace commit, say).

        Only an edit to the pending row itself is held back: another row edited while a blank insert
        waits to be left is an edit like any other.

        :param top_left: the first changed cell.
        :param bottom_right: the last changed cell.
        :param roles: the roles that changed; unused.
        """
        del roles
        first, last = top_left.row(), bottom_right.row()
        if self.__quiet or self.__touches_blank_pending(first, last):
            return
        # a pending insert that has been typed into is a value from now on, not a gesture: forget it
        # here rather than only when an editor closes, since a row can be inserted and filled with no
        # editor ever opening (a settings frame restoring a snapshotted list row by row) -- left armed,
        # it would turn the next clearing of that row into a silent removal
        if self.__pending_entry.isValid() and first <= self.__pending_entry.row() <= last:
            self.__end_pending()
        self.values_changed.emit()

    def __touches_blank_pending(self, first: int, last: int) -> bool:
        """Whether rows ``first``..``last`` include the pending insert while it is still blank.

        :param first: the first row of the change.
        :param last: the last row of the change.
        :returns: whether the change is to that row.
        """
        return self.__pending_entry_is_blank() and first <= self.__pending_entry.row() <= last

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
        if self.__leave_watch is not None and self.current_index != self.__pending_entry.row():
            self.__abandon_later()
        self.current_index_changed.emit()

    def __on_editor_closed(self, editor: QWidget, hint: QAbstractItemDelegate.EndEditHint) -> None:
        """Undo an insert whose entry was left blank -- an abandoned gesture, not an empty value -- or
        keep it waiting to be left, when its first editor closed on the way to another cell.

        :param editor: the editor widget that closed; unused, only one entry is ever pending.
        :param hint: what the delegate wants done next; a cancel ends the gesture at once, where a
            commit or a focus loss only does when there is no second cell to go on to.
        """
        del editor
        if not self.__pending_entry_is_blank():
            self.__end_pending()
            return
        row = self.__pending_entry.row()
        # cancelled, or nothing further in the row to type into, or already left: the gesture is over.
        # Otherwise the editor closed because the user is heading for another cell of the same row.
        no_more_cells = len(self.__editable_cells(row)) < 2
        if hint == QAbstractItemDelegate.EndEditHint.RevertModelCache or no_more_cells or self.current_index != row:
            self.__abandon_pending()
        else:
            self.__wait_for_leave()

    def __abandon_pending(self) -> None:
        """Undo the pending insert and forget it."""
        pending = self.__pending_entry
        self.__end_pending()
        self.__remove_quietly(pending)

    def __remove_quietly(self, pending: QPersistentModelIndex) -> None:
        """Take an abandoned row out of the model without reporting an edit.

        :param pending: the row to remove.
        """
        # silent, like the insert that made it: the two together left the list exactly as it was
        self.__quiet = True
        try:
            self.__model.removeRow(pending.row())
        finally:
            self.__quiet = False

    def __wait_for_leave(self) -> None:
        """Keep a blank pending row until the user leaves it, instead of abandoning it now.

        Armed by filtering the application's focus events (:meth:`eventFilter`), disarmed by
        :meth:`__end_pending`; the other half of "leaving" -- the current row moving away -- is read in
        :meth:`__on_current_changed`.
        """
        app = QApplication.instance()
        if self.__leave_watch is None and isinstance(app, QApplication):
            self.__leave_watch = app
            app.installEventFilter(self)

    def __end_pending(self) -> None:
        """Forget the pending insert, and stop waiting for it to be left."""
        self.__pending_entry = QPersistentModelIndex()
        if self.__leave_watch is not None:
            self.__leave_watch.removeEventFilter(self)
            self.__leave_watch = None

    def __abandon_later(self) -> None:
        """Abandon the pending insert on the next pass through the event loop, if it is still blank then.

        Deferred rather than done here, for the reason the class docstring gives: this is called from
        inside a signal of the view's or the application's, and a row removed from inside one is removed
        under whatever that signal's sender does next.
        """
        QTimer.singleShot(0, self, self.__abandon_if_blank)

    def __abandon_if_blank(self) -> None:
        """Abandon the pending insert if there still is one and it is still blank; forget it either way."""
        if self.__pending_entry_is_blank():
            self.__abandon_pending()
        else:
            self.__end_pending()

    def __abandon_stale(self, stale: QPersistentModelIndex) -> None:
        """Abandon a blank row that a later insert overtook, if it is still blank.

        :param stale: the row that was pending when the later insert landed.
        """
        if stale.isValid() and self.row_is_blank(stale.row()):
            self.__remove_quietly(stale)
