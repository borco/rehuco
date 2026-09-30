"""The items a card list edits, one card per row, with the per-row state a card is painted from."""

# pylint: disable=duplicate-code
# The insert/delete/move-and-return-the-row shape below is the one StringItemListModel implements for
# its strings -- both satisfy ItemEditor/ItemOrderingEditor over a different row type.

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from typing import Any, override

from PySide6.QtCore import QAbstractListModel, QModelIndex, QObject, QPersistentModelIndex, Qt, Signal

type ModelIndex = QModelIndex | QPersistentModelIndex
"""What Qt hands a model method; the persistent form arrives from a view holding onto an index."""

type CardStates = Callable[[Sequence[Any]], Sequence[Mapping[str, str]]]
"""Per row, the states a card is in -- a state name mapped to the reason, shown to the user."""


class CardListModel(QAbstractListModel):  # pylint: disable=too-many-public-methods
    """An ordered list of opaque items, one card each ([[plugins#field-toolkit]]-adjacent, but generic).

    **Also an `ItemEditor`/`ItemOrderingEditor`** (structurally, as `StringItemListModel` is): row in, row
    out, built on Qt's row signals so a :class:`~.card_list_editor.CardListEditor` updates only the cards
    involved.

    A row inserted by :meth:`insert` is **pending**: it is shown, but left out of :attr:`value` until
    :meth:`set_item` gives it a non-blank item. Nothing drops a pending row but :meth:`delete` -- a blank
    card stays until the user removes it. Rows read by :meth:`set_items` are never pending, blank or not,
    since they are the value.

    :param new_item: builds the blank item :meth:`insert` adds.
    :param is_blank: whether an item holds nothing yet.
    :param card_states: the per-row states, recomputed from every row after each change; ``None`` for none.
    :param parent: optional Qt parent.
    """

    count_changed = Signal()
    """Fires whenever :attr:`count` changes -- the `ItemOrderingEditor` contract."""

    states_changed = Signal()
    """Fires when the recomputed per-row states differ from the previous ones -- always after the row signal
    of the change that caused it, so :meth:`states` is already current when that row signal fires."""

    def __init__(
        self,
        new_item: Callable[[], Any],
        is_blank: Callable[[Any], bool],
        card_states: CardStates | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.__new_item = new_item
        self.__is_blank = is_blank
        self.__card_states = card_states
        self.__items: list[Any] = []
        self.__pending: list[bool] = []
        self.__states: list[Mapping[str, str]] = []
        self.rowsInserted.connect(self.count_changed)
        self.rowsRemoved.connect(self.count_changed)
        self.modelReset.connect(self.count_changed)

    @property
    def items(self) -> tuple[Any, ...]:
        """Every row's item, pending ones included, in order."""
        return tuple(self.__items)

    @property
    def value(self) -> list[Any]:
        """Every row's item but the pending ones, in order -- what the list stands for."""
        return [item for item, pending in zip(self.__items, self.__pending, strict=True) if not pending]

    def set_items(self, items: Sequence[Any]) -> None:
        """Replace every row, as one model reset -- unless ``items`` already is :attr:`value`.

        That equality check is the echo guard: a value this model just reported and gets back leaves every
        row alone, pending ones included.

        :param items: the items to show, in order.
        """
        replacement = list(items)
        if replacement == self.value:
            return
        self.beginResetModel()
        self.__items = replacement
        self.__pending = [False] * len(replacement)
        changed = self.__recompute_states()
        self.endResetModel()
        self.__announce_states(changed)

    def item(self, row: int) -> Any:
        """The item at ``row``.

        :param row: the row.
        :returns: its item.
        """
        return self.__items[row]

    def set_item(self, row: int, item: Any) -> None:
        """Replace one row's item, ending its pending state once it is no longer blank.

        :param row: the row.
        :param item: its new item.
        """
        if item == self.__items[row]:
            return
        self.__items[row] = item  # pylint: disable=unsupported-assignment-operation
        if self.__pending[row] and not self.__is_blank(item):
            self.__pending[row] = False  # pylint: disable=unsupported-assignment-operation
        changed = self.__recompute_states()
        index = self.index(row)
        self.dataChanged.emit(index, index)
        self.__announce_states(changed)

    def is_pending(self, row: int) -> bool:
        """Whether ``row`` is an inserted row still left out of :attr:`value`.

        :param row: the row.
        :returns: whether it is pending.
        """
        return self.__pending[row]

    def states(self, row: int) -> Mapping[str, str]:
        """The states ``row`` is in, each name mapped to its reason.

        :param row: the row.
        :returns: its states; empty for none.
        """
        return self.__states[row] if row < len(self.__states) else {}

    @property
    def count(self) -> int:
        """How many rows there are -- the `ItemOrderingEditor` contract."""
        return len(self.__items)

    def insert(self, at: int) -> int:
        """Insert a pending blank row after ``at``, or at the end -- the `ItemEditor` contract.

        :param at: the row to insert after, or a negative row to append.
        :returns: the new row.
        """
        target = at + 1 if at >= 0 else len(self.__items)
        self.__insert(target, self.__new_item(), pending=True)
        return target

    def duplicate(self, at: int) -> int:
        """Insert a copy of ``at`` below it -- the `ItemEditor` contract.

        :param at: the row to copy; a negative row is a no-op.
        :returns: the copy's row, or ``at`` when nothing was copied.
        """
        if at < 0:
            return at
        self.__insert(at + 1, deepcopy(self.__items[at]), pending=self.__pending[at])
        return at + 1

    def delete(self, at: int) -> None:
        """Drop one row -- the `ItemEditor` contract.

        :param at: the row to drop; a negative row is a no-op.
        """
        if at >= 0:
            self.removeRow(at)

    def reset(self) -> None:
        """A no-op -- the `ItemEditor` contract for a list with no defaults."""

    def move_to_top(self, at: int) -> int:
        """Move one row to the first row -- the `ItemOrderingEditor` contract.

        :param at: the row to move.
        :returns: the row it ended up at.
        """
        return self.move(at, 0)

    def move_up(self, at: int) -> int:
        """Move one row up -- the `ItemOrderingEditor` contract.

        :param at: the row to move.
        :returns: the row it ended up at.
        """
        return self.move(at, at - 1)

    def move_down(self, at: int) -> int:
        """Move one row down -- the `ItemOrderingEditor` contract.

        :param at: the row to move.
        :returns: the row it ended up at.
        """
        return self.move(at, at + 1)

    def move_to_bottom(self, at: int) -> int:
        """Move one row to the last row -- the `ItemOrderingEditor` contract.

        :param at: the row to move.
        :returns: the row it ended up at.
        """
        return self.move(at, len(self.__items) - 1)

    def move(self, at: int, to: int) -> int:
        """Move ``at`` to ``to``, as one model move -- what a drag drop lands as.

        :param at: the row to move.
        :param to: the row it should end up at; out of range or unchanged is a no-op.
        :returns: ``to`` if the move happened, ``at`` otherwise.
        """
        if at < 0 or to == at or not 0 <= to < len(self.__items):
            return at
        # Qt reads the destination in the pre-move row space -- the row the entry is inserted before --
        # so a downward move names one past the target
        self.moveRow(QModelIndex(), at, QModelIndex(), to + 1 if to > at else to)
        return to

    def __insert(self, row: int, item: Any, *, pending: bool) -> None:
        """Insert one row holding ``item``, as one model insert.

        :param row: where it goes.
        :param item: what it holds.
        :param pending: whether it is left out of :attr:`value`.
        """
        self.beginInsertRows(QModelIndex(), row, row)
        self.__items.insert(row, item)
        self.__pending.insert(row, pending)
        changed = self.__recompute_states()
        self.endInsertRows()
        self.__announce_states(changed)

    def __recompute_states(self) -> bool:
        """Recompute the per-row states from the rows as they now stand.

        Called after a change to the rows but **before** the change is announced, so a listener updating
        from the announcement already reads :meth:`states` for the new rows -- not the old ones, as it would
        if the states were recomputed from a listener of this model's own signals.

        :returns: whether the states differ from the previous ones.
        """
        states: list[Mapping[str, str]] = (
            [dict(state) for state in self.__card_states(self.__items)] if self.__card_states else []
        )
        states = states or [{} for _ in self.__items]
        if states == self.__states:
            return False
        self.__states = states
        return True

    def __announce_states(self, changed: bool) -> None:
        """Emit :attr:`states_changed` once the change it follows has been announced.

        :param changed: what :meth:`__recompute_states` returned.
        """
        if changed:
            self.states_changed.emit()

    # region Qt model interface

    @override
    def rowCount(self, parent: ModelIndex = QModelIndex()) -> int:  # noqa: N802  (Qt API name)
        return 0 if parent.isValid() else len(self.__items)

    @override
    def data(self, index: ModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or role != Qt.ItemDataRole.UserRole:
            return None
        return self.__items[index.row()]

    @override
    def removeRows(self, row: int, count: int, parent: ModelIndex = QModelIndex()) -> bool:  # noqa: N802
        if parent.isValid() or count < 1 or not 0 <= row <= len(self.__items) - count:
            return False
        self.beginRemoveRows(QModelIndex(), row, row + count - 1)
        del self.__items[row : row + count]  # pylint: disable=unsupported-delete-operation
        del self.__pending[row : row + count]  # pylint: disable=unsupported-delete-operation
        changed = self.__recompute_states()
        self.endRemoveRows()
        self.__announce_states(changed)
        return True

    @override
    def moveRows(  # noqa: N802  (Qt API name)
        self,
        sourceParent: ModelIndex,  # noqa: N803  (Qt API name)
        sourceRow: int,  # noqa: N803  (Qt API name)
        count: int,
        destinationParent: ModelIndex,  # noqa: N803  (Qt API name)
        destinationChild: int,  # noqa: N803  (Qt API name)
    ) -> bool:
        if sourceParent.isValid() or destinationParent.isValid():
            return False
        if not self.beginMoveRows(QModelIndex(), sourceRow, sourceRow + count - 1, QModelIndex(), destinationChild):
            return False
        at = destinationChild if destinationChild < sourceRow else destinationChild - count
        for rows in (self.__items, self.__pending):
            block = rows[sourceRow : sourceRow + count]
            del rows[sourceRow : sourceRow + count]
            rows[at:at] = block
        changed = self.__recompute_states()
        self.endMoveRows()
        self.__announce_states(changed)
        return True

    # endregion
