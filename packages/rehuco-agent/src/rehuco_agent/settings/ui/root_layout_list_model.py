"""The default root layouts as an editable list of their names, each carrying its maps (#578)."""

# The Qt row plumbing and the two protocols' row operations read the same as `LocationReplacementsModel`'s,
# because they are the same contract `ItemListEditor` drives every list model through.
# pylint: disable=duplicate-code

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any, override

from PySide6.QtCore import QAbstractListModel, QModelIndex, QObject, QPersistentModelIndex, Qt, Signal
from PySide6.QtGui import QBrush, QColor
from rehuco_core import Layouts

from ...fields.colors import WARNING_COLOR
from ..root_catalog_settings import DEFAULT_ROOT_LAYOUTS, RootLayout

type ModelIndex = QModelIndex | QPersistentModelIndex
"""What Qt hands a model method; the persistent form arrives from a view holding onto an index."""


class RootLayoutListModel(QAbstractListModel):
    """The default root layouts, one row each, showing and editing its name; its maps ride along, edited beside the
    list (:meth:`set_maps`).

    **An empty name is flagged, never refused**, as a replacement rule's empty text is: the row is coloured and says
    why, and it is saved as it is. A new row starts unnamed, with the maps of a root made from a folder by
    default. **Order is the Add Roots dialog's combo order**, so the moves are real edits.

    :param parent: optional Qt parent.
    """

    count_changed = Signal()
    """Fires whenever :attr:`count` changes -- the `ItemOrderingEditor` contract."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__entries: list[RootLayout] = []
        self.rowsInserted.connect(self.count_changed)
        self.rowsRemoved.connect(self.count_changed)
        self.modelReset.connect(self.count_changed)

    @property
    def count(self) -> int:
        """How many layouts there are -- the `ItemOrderingEditor` contract."""
        return len(self.__entries)

    @property
    def entries(self) -> tuple[RootLayout, ...]:
        """Every layout, in row order, exactly as edited."""
        return tuple(self.__entries)

    def set_entries(self, entries: Sequence[RootLayout]) -> None:
        """Replace every row, as one model reset, if the layouts differ.

        :param entries: the layouts, in order.
        """
        if list(entries) == self.__entries:
            return
        self.beginResetModel()
        self.__entries = list(entries)
        self.endResetModel()

    def set_maps(self, row: int, layouts: Layouts, fallbacks: Mapping[str, str]) -> None:
        """Replace one layout's maps.

        :param row: the layout's row.
        :param layouts: its layouts.
        :param fallbacks: its fallbacks.
        """
        entry = self.__entries[row]
        changed = replace(entry, layouts=dict(layouts), fallbacks=dict(fallbacks))
        if changed != entry:
            self.__entries[row] = changed  # pylint: disable=unsupported-assignment-operation
            index = self.index(row)
            self.dataChanged.emit(index, index)

    # region ItemEditor and ItemOrderingEditor

    def insert(self, at: int) -> int:
        """Insert a new layout after ``at``, or at the end -- the `ItemEditor` contract.

        :param at: the row to insert after, or a negative row to append.
        :returns: the new row.
        """
        target = at + 1 if at >= 0 else len(self.__entries)
        self.insertRow(target)
        return target

    def duplicate(self, at: int) -> int:
        """Insert a copy of ``at`` below it -- the `ItemEditor` contract.

        :param at: the row to copy; a negative row is a no-op.
        :returns: the copy's row, or ``at`` when nothing was copied.
        """
        if at < 0:
            return at
        target = at + 1
        self.beginInsertRows(QModelIndex(), target, target)
        self.__entries.insert(target, self.__entries[at])
        self.endInsertRows()
        return target

    def delete(self, at: int) -> None:
        """Drop one layout -- the `ItemEditor` contract.

        :param at: the row to drop; a negative row is a no-op.
        """
        if at >= 0:
            self.removeRow(at)

    def reset(self) -> None:
        """Put the shipped layouts back -- the `ItemEditor` contract."""
        self.set_entries(DEFAULT_ROOT_LAYOUTS)

    def move_to_top(self, at: int) -> int:
        """Move one layout to the first row -- the `ItemOrderingEditor` contract.

        :param at: the row to move.
        :returns: the row it ended up at.
        """
        return self.__move(at, 0)

    def move_up(self, at: int) -> int:
        """Move one layout up -- the `ItemOrderingEditor` contract.

        :param at: the row to move.
        :returns: the row it ended up at.
        """
        return self.__move(at, at - 1)

    def move_down(self, at: int) -> int:
        """Move one layout down -- the `ItemOrderingEditor` contract.

        :param at: the row to move.
        :returns: the row it ended up at.
        """
        return self.__move(at, at + 1)

    def move_to_bottom(self, at: int) -> int:
        """Move one layout to the last row -- the `ItemOrderingEditor` contract.

        :param at: the row to move.
        :returns: the row it ended up at.
        """
        return self.__move(at, len(self.__entries) - 1)

    def __move(self, row: int, destination: int) -> int:
        """Move ``row`` to ``destination``, as one model move.

        :param row: the row to move.
        :param destination: where to; out of range or unchanged is a no-op.
        :returns: ``destination`` if the move happened, ``row`` otherwise.
        """
        if row < 0 or destination == row or not 0 <= destination < len(self.__entries):
            return row
        # Qt reads the destination in the pre-move row space, so a downward move names one past the target
        before = destination + 1 if destination > row else destination
        self.moveRow(QModelIndex(), row, QModelIndex(), before)
        return destination

    # endregion

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
        label = self.__entries[index.row()].label
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return label
        if label:
            return None
        if role == Qt.ItemDataRole.ToolTipRole:
            return "No name: the Add Roots dialog shows this layout blank."
        if role == Qt.ItemDataRole.ForegroundRole:
            return QBrush(QColor(WARNING_COLOR))
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
        entry = self.__entries[index.row()]
        changed = replace(entry, label=str(value).strip())
        if changed == entry:
            return False
        self.__entries[index.row()] = changed  # pylint: disable=unsupported-assignment-operation
        self.dataChanged.emit(index, index)
        return True

    @override
    def insertRows(self, row: int, count: int, parent: ModelIndex = QModelIndex()) -> bool:  # noqa: N802
        if parent.isValid() or count < 1 or not 0 <= row <= len(self.__entries):
            return False
        self.beginInsertRows(QModelIndex(), row, row + count - 1)
        self.__entries[row:row] = [RootLayout("")] * count  # pylint: disable=unsupported-assignment-operation
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
