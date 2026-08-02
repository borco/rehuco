"""A flat list of strings as a one-column model -- what `StringListEditor` edits, and (via
:mod:`~borco_pyside.widgets.item_protocols`) the generic replacement for `QStringListModel` wherever a
list also wants insert/delete/reorder/reset through the shared list-editor machinery.
"""

# pylint: disable=duplicate-code
# The insert/delete/move-and-return-the-row shape below is the same one
# rehuco_agent.fields.widgets.authors_table_model.AuthorsTableModel independently implements for its
# own two-column model -- both satisfy ItemEditor/ItemOrderingEditor, and the two packages don't share
# a dependency edge a common base could live on without one importing the other.

from collections.abc import Sequence
from typing import Any, override

from PySide6.QtCore import QAbstractListModel, QModelIndex, QObject, QPersistentModelIndex, Qt, Signal

type ModelIndex = QModelIndex | QPersistentModelIndex
"""What Qt hands a model method; the persistent form arrives from a view holding onto an index."""


class StringItemListModel(QAbstractListModel):
    """An ordered list of strings ([[plugins#field-toolkit]]-adjacent, but generic): holds what was
    typed, unnormalized -- whether a blank entry is dropped, what casing means, and whether an emptied
    list means "nothing" or "the defaults" are all its owner's to decide.

    **Also an `ItemEditor`/`ItemOrderingEditor`** (structurally -- no explicit `Protocol` inheritance,
    since mixing `Protocol`'s metaclass with Shiboken's raises a metaclass conflict): :meth:`insert`,
    :meth:`delete`, :meth:`reset`, :meth:`move_to_top` and friends are the row-number-in, row-number-out
    shape both protocols ask for, built on `insertRows`/`removeRows`/`moveRows`.

    :param parent: optional Qt parent.
    :param defaults: what :meth:`reset` restores; settable later through :attr:`defaults`.
    """

    count_changed = Signal()
    """Fires whenever :attr:`count` changes -- the `ItemOrderingEditor` contract."""

    def __init__(self, parent: QObject | None = None, *, defaults: Sequence[str] = ()) -> None:
        super().__init__(parent)
        self.__entries: list[str] = []
        self.__defaults: tuple[str, ...] = tuple(defaults)
        self.rowsInserted.connect(self.count_changed)
        self.rowsRemoved.connect(self.count_changed)
        self.modelReset.connect(self.count_changed)

    @property
    def entries(self) -> tuple[str, ...]:
        """Every entry, in order, exactly as typed."""
        return tuple(self.__entries)

    def set_entries(self, values: Sequence[str]) -> None:
        """Replace every row, as one model reset, if the entries actually differ.

        :param values: the entries to show, in order.
        """
        replacement = list(values)
        if replacement == self.__entries:
            return
        self.beginResetModel()
        self.__entries = replacement
        self.endResetModel()

    @property
    def defaults(self) -> tuple[str, ...]:
        """What :meth:`reset` restores."""
        return self.__defaults

    @defaults.setter
    def defaults(self, defaults: Sequence[str]) -> None:
        """Set what :meth:`reset` restores.

        :param defaults: the entries reset puts back, in order.
        """
        self.__defaults = tuple(defaults)

    @property
    def count(self) -> int:
        """How many entries there are -- the `ItemOrderingEditor` contract."""
        return len(self.__entries)

    def insert(self, at: int) -> int:
        """Insert a blank entry after ``at``, or at the end -- the `ItemEditor` contract.

        :param at: the row to insert after, or a negative row to append.
        :returns: the new entry's row.
        """
        target = at + 1 if at >= 0 else len(self.__entries)
        self.insertRow(target)
        return target

    def delete(self, at: int) -> None:
        """Drop one entry -- the `ItemEditor` contract.

        :param at: the row to drop; a negative row is a no-op.
        """
        if at >= 0:
            self.removeRow(at)

    def reset(self) -> None:
        """Replace the list with :attr:`defaults` -- the `ItemEditor` contract, and the only way back
        once the list has been emptied."""
        self.set_entries(self.__defaults)

    def move_to_top(self, at: int) -> int:
        """Move one entry to the first row -- the `ItemOrderingEditor` contract.

        :param at: the row to move.
        :returns: the row it ended up at.
        """
        return self.__move(at, 0)

    def move_up(self, at: int) -> int:
        """Move one entry up a row -- the `ItemOrderingEditor` contract.

        :param at: the row to move.
        :returns: the row it ended up at.
        """
        return self.__move(at, at - 1)

    def move_down(self, at: int) -> int:
        """Move one entry down a row -- the `ItemOrderingEditor` contract.

        :param at: the row to move.
        :returns: the row it ended up at.
        """
        return self.__move(at, at + 1)

    def move_to_bottom(self, at: int) -> int:
        """Move one entry to the last row -- the `ItemOrderingEditor` contract.

        :param at: the row to move.
        :returns: the row it ended up at.
        """
        return self.__move(at, len(self.__entries) - 1)

    def __move(self, row: int, destination: int) -> int:
        """Move ``row`` to ``destination``, as one model move, and say where it ended up.

        :param row: the row to move.
        :param destination: where to move it to; out-of-range or unchanged is a no-op.
        :returns: ``destination`` if the move happened, ``row`` (unchanged) otherwise.
        """
        if row < 0 or destination == row or not 0 <= destination < len(self.__entries):
            return row
        # Qt reads the destination in the *pre-move* row space -- the row the entry is inserted
        # *before* -- so a downward move has to name one past the target, because removing the source
        # first shifts everything below it up by one.
        before = destination + 1 if destination > row else destination
        self.moveRow(QModelIndex(), row, QModelIndex(), before)
        return destination

    # region Qt model interface

    @override
    def rowCount(self, parent: ModelIndex = QModelIndex()) -> int:  # noqa: N802  (Qt API name)
        return 0 if parent.isValid() else len(self.__entries)

    @override
    def flags(self, index: ModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable

    @override
    def data(self, index: ModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return self.__entries[index.row()]
        return None

    @override
    def setData(  # noqa: N802  (Qt API name)
        self,
        index: ModelIndex,
        value: Any,
        role: int = Qt.ItemDataRole.EditRole,
    ) -> bool:
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False
        row = index.row()
        text = str(value)
        if text == self.__entries[row]:
            return False
        self.__entries[row] = text  # pylint: disable=unsupported-assignment-operation
        self.dataChanged.emit(index, index)
        return True

    @override
    def insertRows(self, row: int, count: int, parent: ModelIndex = QModelIndex()) -> bool:  # noqa: N802
        if parent.isValid() or count < 1 or not 0 <= row <= len(self.__entries):
            return False
        self.beginInsertRows(QModelIndex(), row, row + count - 1)
        self.__entries[row:row] = [""] * count  # pylint: disable=unsupported-assignment-operation
        self.endInsertRows()
        return True

    @override
    def removeRows(self, row: int, count: int, parent: ModelIndex = QModelIndex()) -> bool:  # noqa: N802
        if parent.isValid() or count < 1 or not 0 <= row <= len(self.__entries) - count:
            return False
        self.beginRemoveRows(QModelIndex(), row, row + count - 1)
        del self.__entries[row : row + count]  # pylint: disable=unsupported-delete-operation
        self.endRemoveRows()
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
        block = self.__entries[sourceRow : sourceRow + count]
        del self.__entries[sourceRow : sourceRow + count]  # pylint: disable=unsupported-delete-operation
        at = destinationChild if destinationChild < sourceRow else destinationChild - count
        self.__entries[at:at] = block  # pylint: disable=unsupported-assignment-operation
        self.endMoveRows()
        return True

    # endregion
