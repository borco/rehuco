"""A map of strings to strings as an editable two-column list: a root's layouts or fallbacks (#578)."""

# The Qt row plumbing and the two protocols' row operations read the same as `LocationReplacementsModel`'s,
# because they are the same contract `ItemListEditor` drives every list model through.
# pylint: disable=duplicate-code

from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, Final, override

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QPersistentModelIndex, Qt, Signal
from PySide6.QtGui import QBrush, QColor

from ..fields.colors import WARNING_COLOR

KEY_COLUMN: Final = 0
"""The key -- the cell an insert opens."""

VALUE_COLUMN: Final = 1
"""What the key maps to."""

COLUMN_COUNT: Final = 2

type ModelIndex = QModelIndex | QPersistentModelIndex
"""What Qt hands a model method; the persistent form arrives from a view holding onto an index."""


# the count is `QAbstractTableModel`'s surface plus the two protocols `ItemListEditor` drives the model through,
# none of which this class chose
# pylint: disable-next=too-many-public-methods
class StringMapModel(QAbstractTableModel):
    """A ``str -> str`` map as editable rows of a key and a value, in the order they were given.

    **A row whose key is empty, or repeats an earlier row's, is flagged, never refused**: its key cell is coloured and
    says why in a tooltip, and :attr:`mapping` leaves it out, so a typo is fixed in place rather than retyped.

    **A value can be flagged too** (#637): once :meth:`set_value_problem` is given a check, a row whose value it faults
    has its value cell coloured with the reason as its tooltip, and is still kept.

    **A key can repeat** once :meth:`set_repeated_keys` says so (#638): a row is then flagged only for an empty key or
    for repeating an earlier row whole, key and value, and :attr:`rows` lists the rows that count, in order.

    **The keys can be fixed** (:meth:`set_fixed_keys`): one row per key, in that order, the key column read-only, no row
    added, removed or reset, and a row with an empty value left out of :attr:`mapping`.

    **Also an `ItemEditor`/`ItemOrderingEditor`** (structurally, as `LocationReplacementsModel` is): the order is only
    how the rows are shown, since a map has none.

    :param titles: the two columns' headers.
    :param parent: optional Qt parent.
    """

    count_changed = Signal()
    """Fires whenever :attr:`count` changes -- the `ItemOrderingEditor` contract."""

    def __init__(self, titles: tuple[str, str], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__titles = titles
        self.__entries: list[tuple[str, str]] = []
        self.__defaults: dict[str, str] = {}
        self.__fixed_keys: tuple[str, ...] | None = None
        self.__repeated_keys = False
        self.__value_problem: Callable[[str, str], str] | None = None
        self.rowsInserted.connect(self.count_changed)
        self.rowsRemoved.connect(self.count_changed)
        self.modelReset.connect(self.count_changed)

    @property
    def count(self) -> int:
        """How many rows there are -- the `ItemOrderingEditor` contract."""
        return len(self.__entries)

    @property
    def mapping(self) -> dict[str, str]:
        """The map the rows make: every row with a key, the first of rows sharing one."""
        result: dict[str, str] = {}
        for key, value in self.__entries:
            if key and key not in result and (value or self.__fixed_keys is None):
                result[key] = value
        return result

    @property
    def rows(self) -> tuple[tuple[str, str], ...]:
        """The rows that count, in order: every row with a key and a value, the first of rows alike in both."""
        return tuple(entry for row, entry in enumerate(self.__entries) if not self.__ignored(row))

    @property
    def fixed_keys(self) -> tuple[str, ...] | None:
        """The keys the rows are fixed to, or ``None`` when rows are added and removed freely."""
        return self.__fixed_keys

    def set_repeated_keys(self) -> None:
        """Let rows share a key (#638): the order of the rows is then what a caller reads."""
        self.__repeated_keys = True

    def set_value_problem(self, value_problem: Callable[[str, str], str] | None) -> None:
        """Flag values by this check, repainting every row shown.

        :param value_problem: why a row's value is unusable, given its key and value, ``""`` when it is fine; ``None``
            flags nothing.
        """
        self.__value_problem = value_problem
        if self.__entries:
            self.dataChanged.emit(self.index(0, VALUE_COLUMN), self.index(len(self.__entries) - 1, VALUE_COLUMN))

    def set_fixed_keys(self, keys: Sequence[str]) -> None:
        """Fix the rows to these keys, each with an empty value until :meth:`set_mapping` fills it.

        :param keys: the keys, in row order.
        """
        self.beginResetModel()
        self.__fixed_keys = tuple(keys)
        self.__entries = [(key, "") for key in self.__fixed_keys]
        self.endResetModel()

    def set_mapping(self, mapping: Mapping[str, str]) -> None:
        """Replace every row with the map's entries, as one model reset, unless the rows are those entries already.

        :param mapping: the map to show.
        """
        entries = (
            list(mapping.items()) if self.__fixed_keys is None else [(k, mapping.get(k, "")) for k in self.__fixed_keys]
        )
        if entries == self.__entries:
            return
        self.beginResetModel()
        self.__entries = entries
        self.endResetModel()

    def set_rows(self, rows: Iterable[tuple[str, str]]) -> None:
        """Replace every row, as one model reset, unless the rows are these already (#638).

        :param rows: the ``(key, value)`` rows to show, in order.
        """
        entries = list(rows)
        if entries == self.__entries:
            return
        self.beginResetModel()
        self.__entries = entries
        self.endResetModel()

    def set_titles(self, titles: tuple[str, str]) -> None:
        """Rename the two columns.

        :param titles: the key column's header and the value column's.
        """
        self.__titles = titles
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, KEY_COLUMN, VALUE_COLUMN)

    @property
    def defaults(self) -> dict[str, str]:
        """What :meth:`reset` restores."""
        return dict(self.__defaults)

    @defaults.setter
    def defaults(self, defaults: Mapping[str, str]) -> None:
        self.__defaults = dict(defaults)

    def problem(self, row: int) -> str:
        """Why a row is left out of :attr:`mapping`, if it is.

        :param row: the row.
        :returns: the reason, or ``""`` for a row that counts.
        """
        key, value = self.__entries[row]
        if self.__fixed_keys is not None:
            return ""
        if not key:
            return "No key: this row is ignored."
        if self.__repeated_keys:
            if (key, value) in self.__entries[:row]:
                return f"'{key} \N{RIGHTWARDS ARROW} {value}' is already a row above: this row is ignored."
        elif any(other == key for other, _ in self.__entries[:row]):
            return f"'{key}' is already a key above: this row is ignored."
        return ""

    def __ignored(self, row: int) -> bool:
        """Whether a row is left out of :attr:`rows`.

        :param row: the row.
        :returns: whether it has no key or no value, or repeats an earlier row whole.
        """
        key, value = self.__entries[row]
        return not key or not value or (key, value) in self.__entries[:row]

    # region ItemEditor and ItemOrderingEditor

    def insert(self, at: int) -> int:
        """Insert a blank row after ``at``, or at the end -- the `ItemEditor` contract.

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
        if at < 0 or self.__fixed_keys is not None:
            return at
        target = at + 1
        self.beginInsertRows(QModelIndex(), target, target)
        self.__entries.insert(target, self.__entries[at])
        self.endInsertRows()
        return target

    def delete(self, at: int) -> None:
        """Drop one row -- the `ItemEditor` contract.

        :param at: the row to drop; a negative row is a no-op.
        """
        if at >= 0:
            self.removeRow(at)  # a fixed set of keys refuses

    def reset(self) -> None:
        """Put :attr:`defaults` back -- the `ItemEditor` contract; a fixed set of keys has none."""
        if self.__fixed_keys is not None:
            return
        self.beginResetModel()
        self.__entries = list(self.__defaults.items())
        self.endResetModel()

    def move_to_top(self, at: int) -> int:
        """Move one row to the first row -- the `ItemOrderingEditor` contract.

        :param at: the row to move.
        :returns: the row it ended up at.
        """
        return self.__move(at, 0)

    def move_up(self, at: int) -> int:
        """Move one row up -- the `ItemOrderingEditor` contract.

        :param at: the row to move.
        :returns: the row it ended up at.
        """
        return self.__move(at, at - 1)

    def move_down(self, at: int) -> int:
        """Move one row down -- the `ItemOrderingEditor` contract.

        :param at: the row to move.
        :returns: the row it ended up at.
        """
        return self.__move(at, at + 1)

    def move_to_bottom(self, at: int) -> int:
        """Move one row to the last row -- the `ItemOrderingEditor` contract.

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
    def columnCount(self, parent: ModelIndex = QModelIndex()) -> int:  # noqa: N802  (Qt API name)
        return 0 if parent.isValid() else COLUMN_COUNT

    @override
    def headerData(  # noqa: N802  (Qt API name)
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if role != Qt.ItemDataRole.DisplayRole or orientation != Qt.Orientation.Horizontal:
            return None
        return self.__titles[section]

    @override
    def flags(self, index: ModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if self.__fixed_keys is None or index.column() == VALUE_COLUMN:
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    @override
    def data(self, index: ModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        key, value = self.__entries[index.row()]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return key if index.column() == KEY_COLUMN else value
        reason = (
            self.problem(index.row())
            if index.column() == KEY_COLUMN
            else (self.__value_problem(key, value) if self.__value_problem is not None else "")
        )
        if role == Qt.ItemDataRole.ToolTipRole:
            return reason or None
        if role == Qt.ItemDataRole.ForegroundRole and reason:
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
        row = index.row()
        key, old = self.__entries[row]
        text = str(value).strip() if index.column() == KEY_COLUMN else str(value)
        entry = (text, old) if index.column() == KEY_COLUMN else (key, text)
        if entry == self.__entries[row]:
            return False
        self.__entries[row] = entry  # pylint: disable=unsupported-assignment-operation
        # a key's change can flag or clear every row below that shares it
        self.dataChanged.emit(index, self.index(len(self.__entries) - 1, VALUE_COLUMN))
        return True

    @override
    def insertRows(self, row: int, count: int, parent: ModelIndex = QModelIndex()) -> bool:  # noqa: N802
        if self.__fixed_keys is not None or parent.isValid() or count < 1 or not 0 <= row <= len(self.__entries):
            return False
        self.beginInsertRows(QModelIndex(), row, row + count - 1)
        self.__entries[row:row] = [("", "")] * count  # pylint: disable=unsupported-assignment-operation
        self.endInsertRows()
        return True

    @override
    def removeRows(self, row: int, count: int, parent: ModelIndex = QModelIndex()) -> bool:  # noqa: N802
        if (
            self.__fixed_keys is not None
            or parent.isValid()
            or count < 1
            or not 0 <= row <= len(self.__entries) - count
        ):
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
