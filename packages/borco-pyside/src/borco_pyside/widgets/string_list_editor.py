"""Edit a list of strings: a row-sized view over a string-list model, and two action columns."""

from collections.abc import Sequence
from typing import Final

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QStringListModel, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QAbstractItemDelegate, QHBoxLayout, QSizePolicy, QWidget

from .content_sized_list_view import ContentSizedListView
from .item_action_columns import ItemActionsColumn, ItemOrderingColumn


class StringListEditor(QWidget):
    """Edit an ordered list of strings in place, with buttons and keys for both halves of the job.

    The whole widget is a `QStringListModel`, a view onto it, and two `ActionButtonColumn`s:
    `ItemActionsColumn` for what the list holds (insert, edit, delete, reset) and `ItemOrderingColumn`
    for the order it holds it in (top, up, down, bottom). Both columns are reachable through
    :attr:`item_actions` and :attr:`ordering_actions`, which is where a consuming app hangs its icons --
    this widget ships none, so it never drags an icon set into a generic library.

    **The model is the list.** Every action is one model call -- ``moveRow``, ``insertRow``,
    ``removeRow``, ``setStringList`` -- so each edit is a single primitive that says exactly what it
    was: a move reports ``rowsMoved`` and leaves every row's index intact, rather than a removal
    followed by an insertion that any attached selection or persistent index has to survive. Nothing
    here rebuilds the list to reorder it, and nothing hand-emits :attr:`values_changed`: the model's own
    signals are what report an edit, so there is one path in and one path out.

    It owns no persistence and no normalization policy: it edits a list, exposes it as :attr:`values`,
    and says so with :attr:`values_changed`. Whether a blank entry is dropped, what casing means, and
    whether an emptied list means "nothing" or "the defaults" are all its owner's to decide -- two
    callers of one widget normalize differently, and a rule pulled in here would make one of them
    wrong. The one exception is an entry inserted and then left blank, which is undone rather than
    stored: an insert always opens the editor, so a blank one is an abandoned gesture, not a value --
    and since inserting it and taking it away again leaves the list as it was, neither is reported.

    The shortcuts (``Ins``, ``F2``, ``Del``, ``Ctrl+Home``/``Up``/``Down``/``End``) are armed on the
    view alone, so they fire only while the view itself has focus. That is what makes ``Del`` delete a
    *character* while an entry is open for editing: the delegate's editor is a `QLineEdit` child holding
    the focus in the view's stead, and a `Qt.ShortcutContext.WidgetShortcut` armed on the view does not
    reach it. ``Ctrl+Home``/``Ctrl+End`` take those keys away from the view's own jump-to-first/last-row
    navigation, which is the trade this widget makes deliberately.

    The view is a `ContentSizedListView`: it grows with its rows rather than scrolling them, so an
    enclosing page's scroll area does the scrolling instead of a second scrollbar appearing inside a
    widget the reader must first scroll *to*.

    :param parent: optional Qt parent.
    :param defaults: what Reset restores; also what disables Reset while it is empty, since a Reset
        with nothing to restore promises an action that does nothing. Settable later through
        :attr:`defaults`, which is how a widget promoted into a ``.ui`` (constructed with a parent and
        nothing else) gets its own.
    :param with_ordering: whether the ordering column is shown. Off for a list whose order carries no
        meaning, where four move buttons would invite an edit that changes nothing. Settable later
        through :meth:`set_ordering_visible`, for the same ``.ui``-promotion reason.
    """

    values_changed = Signal()
    """Emitted once per edit -- an entry added, retyped, deleted, moved, or the whole list replaced."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        defaults: Sequence[str] = (),
        with_ordering: bool = True,
    ) -> None:
        super().__init__(parent)
        self.__defaults: tuple[str, ...] = tuple(defaults)
        # the row an insert just made, until its editor closes -- persistent, so it still names that
        # entry if anything shifts the rows underneath it (see __on_editor_closed)
        self.__pending_entry = QPersistentModelIndex()
        # set only around the insert-then-abandon pair, the one edit that must report nothing because
        # it undoes itself; every other change is a single model call that reports itself once
        self.__quiet = False

        self.__model: Final = QStringListModel(self)
        self.__view: Final = ContentSizedListView(self)
        self.__view.setModel(self.__model)
        # banded rows: the entries are short strings with no other structure to read a row boundary
        # from, and this list has no header or grid to supply one
        self.__view.setAlternatingRowColors(True)
        self.__item_actions: Final = ItemActionsColumn(self)
        self.__ordering_actions: Final = ItemOrderingColumn(self)

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

        self.__wire_actions()
        self.__wire_model()
        self.set_ordering_visible(with_ordering)
        self.__update_action_states()

    @property
    def item_actions(self) -> ItemActionsColumn:
        """The insert/edit/delete/reset column -- where a consuming app sets those four icons."""
        return self.__item_actions

    @property
    def ordering_actions(self) -> ItemOrderingColumn:
        """The top/up/down/bottom column -- where a consuming app sets those four icons."""
        return self.__ordering_actions

    @property
    def values(self) -> tuple[str, ...]:
        """Every entry, in order, exactly as typed -- unnormalized, since normalizing is the owner's."""
        return tuple(self.__model.stringList())

    @values.setter
    def values(self, values: Sequence[str]) -> None:
        """Replace every entry, reporting one edit if the list actually changed.

        One ``setStringList`` rather than a clear and a refill, so the whole replacement is a single
        model reset and a single :attr:`values_changed`.

        :param values: the entries to show, in order.
        """
        self.__show(values)

    def __show(self, values: Sequence[str]) -> None:
        """Put ``values`` in the model, reporting one edit if that changed anything.

        What the :attr:`values` setter does, reached separately so Reset can do it too without a slot
        assigning to its own class's property from the inside.

        :param values: the entries to show, in order.
        """
        replacement = list(values)
        if tuple(replacement) != self.values:
            self.__model.setStringList(replacement)

    @property
    def defaults(self) -> tuple[str, ...]:
        """What Reset restores; an empty one disables Reset rather than offering to empty the list."""
        return self.__defaults

    @defaults.setter
    def defaults(self, defaults: Sequence[str]) -> None:
        """Set what Reset restores.

        :param defaults: the entries Reset puts back, in order.
        """
        self.__defaults = tuple(defaults)
        self.__update_action_states()

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

    def __wire_actions(self) -> None:
        """Connect every action to what it does, and arm its shortcut on the view."""
        actions = self.__item_actions
        actions.insert_action.triggered.connect(self.__on_insert)
        actions.edit_action.triggered.connect(self.__on_edit)
        actions.delete_action.triggered.connect(self.__on_delete)
        actions.reset_action.triggered.connect(self.__on_reset)
        for action in (
            actions.insert_action,
            actions.edit_action,
            actions.delete_action,
            actions.reset_action,
        ):
            self.__view.addAction(action)

        ordering = self.__ordering_actions
        ordering.move_to_top_action.triggered.connect(self.__on_move_to_top)
        ordering.move_up_action.triggered.connect(self.__on_move_up)
        ordering.move_down_action.triggered.connect(self.__on_move_down)
        ordering.move_to_bottom_action.triggered.connect(self.__on_move_to_bottom)

    def __wire_model(self) -> None:
        """Let every way the model can change report itself, and track the current row separately."""
        # one slot for all five: each is a single edit, and none of them needs to say which rows moved
        # -- a reader asks `values`. Qt passes each signal's own arguments and Python drops them.
        for signal in (
            self.__model.rowsInserted,
            self.__model.rowsRemoved,
            self.__model.rowsMoved,
            self.__model.modelReset,
            self.__model.dataChanged,
        ):
            signal.connect(self.__on_model_changed)
        selection = self.__view.selectionModel()
        selection.currentChanged.connect(self.__on_current_changed)
        self.__view.itemDelegate().closeEditor.connect(self.__on_editor_closed)

    def __ordering_action_list(self) -> tuple[QAction, ...]:
        """The ordering column's four actions, in column order.

        :returns: top, up, down, bottom.
        """
        ordering = self.__ordering_actions
        return (
            ordering.move_to_top_action,
            ordering.move_up_action,
            ordering.move_down_action,
            ordering.move_to_bottom_action,
        )

    def __current_row(self) -> int:
        """The row being acted on.

        :returns: the current row, or ``-1`` when there is none.
        """
        return self.__view.currentIndex().row()

    def __on_insert(self) -> None:
        """Insert a blank entry below the current one and open it for typing straight away.

        With no current row the entry goes last, which is how an emptied list is refilled. The blank
        row itself reports nothing: it is a value only once something is typed into it, which the
        commit reports on its own, and until then it may still be abandoned as though never inserted.
        """
        row = self.__current_row()
        at = row + 1 if row >= 0 else self.__model.rowCount()
        self.__quiet = True
        try:
            self.__model.insertRow(at)
        finally:
            self.__quiet = False
        index = self.__model.index(at, 0)
        self.__view.setCurrentIndex(index)
        self.__pending_entry = QPersistentModelIndex(index)
        self.__view.edit(index)

    def __on_edit(self) -> None:
        """Open the current entry for in-place editing."""
        index = self.__view.currentIndex()
        if index.isValid():
            self.__view.edit(index)

    def __on_delete(self) -> None:
        """Drop the current entry."""
        row = self.__current_row()
        if row >= 0:
            self.__model.removeRow(row)

    def __on_reset(self) -> None:
        """Replace the list with :attr:`defaults` -- the only way back once it has been emptied."""
        self.__show(self.__defaults)

    def __on_move_to_top(self) -> None:
        """Move the current entry to the first row."""
        self.__move_current_to(0)

    def __on_move_up(self) -> None:
        """Move the current entry one row up."""
        self.__move_current_to(self.__current_row() - 1)

    def __on_move_down(self) -> None:
        """Move the current entry one row down."""
        self.__move_current_to(self.__current_row() + 1)

    def __on_move_to_bottom(self) -> None:
        """Move the current entry to the last row."""
        self.__move_current_to(self.__model.rowCount() - 1)

    def __move_current_to(self, destination: int) -> None:
        """Move the current row to ``destination``, as one model move.

        `QAbstractItemModel.moveRow` is the whole operation: the model reports a single ``rowsMoved``,
        every other row keeps its index, and the selection follows the entry rather than the position
        it used to sit at. Nothing is taken out and put back, so nothing has to be repaired afterwards.

        :param destination: the row to move it to; out-of-range or unchanged is a no-op.
        """
        row = self.__current_row()
        if row < 0 or destination == row or not 0 <= destination < self.__model.rowCount():
            return
        # Qt reads the destination in the *pre-move* row space -- the row the entry is inserted
        # *before* -- so a downward move has to name one past the target, because removing the source
        # first shifts everything below it up by one.
        before = destination + 1 if destination > row else destination
        self.__model.moveRow(QModelIndex(), row, QModelIndex(), before)

    def __on_model_changed(self, *args: object) -> None:
        """Report the edit the model just made, and refresh what the actions offer.

        :param args: whichever signal's arguments arrived; unused, a reader asks :attr:`values`.
        """
        del args
        if self.__quiet or self.__pending_entry_is_blank():
            return
        self.__update_action_states()
        self.values_changed.emit()

    def __pending_entry_is_blank(self) -> bool:
        """Whether an inserted entry is still open and still blank -- a gesture, not yet a value.

        A whitespace-only commit lands in the model (``dataChanged``) an instant before
        ``closeEditor`` undoes it, and reporting that instant would leave the last report
        disagreeing with the state the silent undo settles on. While this holds, nothing is
        reported; the only edit that can reach the model meanwhile is that entry's own commit,
        since the values setter's reset would invalidate the pending index.

        :returns: whether the pending entry exists and strips to nothing.
        """
        return self.__pending_entry.isValid() and not str(self.__pending_entry.data()).strip()

    def __on_current_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        """Refresh which actions are available for the newly-current row.

        :param current: the new current index; unused, read back off the view instead.
        :param previous: the index left behind; unused.
        """
        del current, previous
        self.__update_action_states()

    def __on_editor_closed(self, editor: QWidget, hint: QAbstractItemDelegate.EndEditHint) -> None:
        """Undo an insert whose entry was left blank -- an abandoned gesture, not an empty value.

        :param editor: the editor widget that closed; unused, only one entry is ever pending.
        :param hint: what the delegate wants done next; unused, a cancelled and a committed-blank
            edit are both "no entry was typed".
        """
        del editor, hint
        pending, self.__pending_entry = self.__pending_entry, QPersistentModelIndex()
        if not pending.isValid() or str(pending.data()).strip():
            return
        # silent, like the insert that made it: the two together left the list exactly as it was
        self.__quiet = True
        try:
            self.__model.removeRow(pending.row())
        finally:
            self.__quiet = False
        self.__update_action_states()

    def __update_action_states(self) -> None:
        """Enable each action for what the current row makes possible.

        Insert and Reset are list-wide, so neither answers to the current row: Insert is how an emptied
        list gets one back, and Reset asks only whether there is anything to restore.
        """
        self.__item_actions.reset_action.setEnabled(bool(self.__defaults))
        row = self.__current_row()
        count = self.__model.rowCount()
        has_current = row >= 0
        self.__item_actions.edit_action.setEnabled(has_current)
        self.__item_actions.delete_action.setEnabled(has_current)
        self.__ordering_actions.move_to_top_action.setEnabled(has_current and row > 0)
        self.__ordering_actions.move_up_action.setEnabled(has_current and row > 0)
        self.__ordering_actions.move_down_action.setEnabled(has_current and row < count - 1)
        self.__ordering_actions.move_to_bottom_action.setEnabled(has_current and row < count - 1)
