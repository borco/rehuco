"""The screenshot "try it" table: a sample filename beside the slot the current patterns would assign
it ([[acquisition-tooling#screenshot-schemes]], #287).
"""

# The Qt half and the two protocols' row operations are `ScreenshotNamePatternsModel`'s almost line for
# line -- see that module's own note on why this is a copy rather than a shared generic base.
# pylint: disable=duplicate-code

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Final, override

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QPersistentModelIndex, Qt, Signal
from rehuco_core import ScreenshotNamePattern, ScreenshotNamePatterns

FILENAME_COLUMN: Final = 0
"""The sample filename or stem the user types -- the only editable cell."""

SLOT_COLUMN: Final = 1
"""The slot the current patterns assign the filename, or "not a screenshot" -- read-only, recomputed
from :attr:`ScreenshotTryItModel.patterns_provider`."""

COLUMN_COUNT: Final = 2

COLUMN_TITLES: Final = ("Sample filename", "Slot")

NOT_A_SCREENSHOT: Final = "not a screenshot"
"""Shown in :data:`SLOT_COLUMN` when no pattern matches the sample."""

type ModelIndex = QModelIndex | QPersistentModelIndex
"""What Qt hands a model method; the persistent form arrives from a view holding onto an index."""


# the count is `QAbstractTableModel`'s surface plus the two protocols `ItemListEditor` drives the model
# through -- four ordering methods, three editing ones -- none of which this class chose; splitting it
# would separate the rows from the operations performed on them
# pylint: disable-next=too-many-public-methods
class ScreenshotTryItModel(QAbstractTableModel):
    """Sample filenames, each shown beside the slot the live pattern list would assign it (#287).

    The samples are a settings-page value like the patterns above them: the page stages them here,
    and `ScreenshotPatternsSettings` keeps them. This model holds them as typed and normalizes nothing.
    There is no "invalid" concept for a sample row: an empty filename simply has no slot, the same as
    one no pattern recognizes.

    :attr:`SLOT_COLUMN` never edits or moves on its own -- it is a pure function of
    :attr:`patterns_provider`'s current return value, called fresh on every read. When the pattern list
    changes, call :meth:`refresh_slots` (a full reset -- this table never holds enough rows for a partial
    invalidation to be worth the extra bookkeeping) so the column reflects it.

    :param defaults: what :meth:`reset` restores; empty unless a caller says otherwise, since a widget
        promoted into a ``.ui`` is built with only a parent and the page sets the rest.
    :param parent: optional Qt parent.
    :param patterns_provider: called on every read of :attr:`SLOT_COLUMN` to get the live pattern list --
        the settings page hands this the patterns editor's own :attr:`~ItemListEditor.values` getter, so
        an edit there is visible here without either widget holding a reference to the other's model.
        Empty (no pattern ever matches) until set, for the same reason ``defaults`` is.
    """

    count_changed = Signal()
    """Fires whenever :attr:`count` changes -- the `ItemOrderingEditor` contract."""

    def __init__(
        self,
        defaults: Sequence[str] = (),
        parent: QObject | None = None,
        *,
        patterns_provider: Callable[[], Sequence[ScreenshotNamePattern]] = tuple,
    ) -> None:
        super().__init__(parent)
        self.patterns_provider = patterns_provider
        self.__entries: list[str] = []
        self.__defaults: tuple[str, ...] = tuple(defaults)
        self.rowsInserted.connect(self.count_changed)
        self.rowsRemoved.connect(self.count_changed)
        self.modelReset.connect(self.count_changed)

    @property
    def count(self) -> int:
        """How many sample rows there are -- the `ItemOrderingEditor` contract."""
        return len(self.__entries)

    @property
    def entries(self) -> tuple[str, ...]:
        """Every sample filename, in row order, exactly as typed."""
        return tuple(self.__entries)

    def set_entries(self, entries: Sequence[str]) -> None:
        """Replace every row, as one model reset, if the samples actually differ.

        :param entries: the sample filenames to show, in order.
        """
        replacement = list(entries)
        if replacement == self.__entries:
            return
        self.beginResetModel()
        self.__entries = replacement
        self.endResetModel()

    @property
    def defaults(self) -> tuple[str, ...]:
        """What :meth:`reset` restores; an empty one means there is nothing to restore."""
        return self.__defaults

    @defaults.setter
    def defaults(self, defaults: Sequence[str]) -> None:
        """Set what :meth:`reset` restores.

        :param defaults: the sample filenames Reset should put back.
        """
        self.__defaults = tuple(defaults)

    def refresh_slots(self) -> None:
        """Recompute :attr:`SLOT_COLUMN` against the current :attr:`patterns_provider`.

        A full reset rather than a targeted ``dataChanged`` on the slot column -- this table is never
        going to hold thousands of rows, so simple and correct beats partial invalidation.
        """
        self.beginResetModel()
        self.endResetModel()

    def insert(self, at: int) -> int:
        """Insert a blank sample after ``at``, or at the end -- the `ItemEditor` contract.

        :param at: the row to insert after, or a negative row to append.
        :returns: the new row.
        """
        target = at + 1 if at >= 0 else len(self.__entries)
        self.insertRow(target)
        return target

    def delete(self, at: int) -> None:
        """Drop one sample -- the `ItemEditor` contract.

        :param at: the row to drop; a negative row is a no-op.
        """
        if at >= 0:
            self.removeRow(at)

    def reset(self) -> None:
        """Put :attr:`defaults` back -- the `ItemEditor` contract."""
        self.set_entries(self.__defaults)

    def move_to_top(self, at: int) -> int:
        """Move one sample to the first row -- the `ItemOrderingEditor` contract.

        :param at: the row to move.
        :returns: the row it ended up at.
        """
        return self.__move(at, 0)

    def move_up(self, at: int) -> int:
        """Move one sample up a row -- the `ItemOrderingEditor` contract.

        :param at: the row to move.
        :returns: the row it ended up at.
        """
        return self.__move(at, at - 1)

    def move_down(self, at: int) -> int:
        """Move one sample down a row -- the `ItemOrderingEditor` contract.

        :param at: the row to move.
        :returns: the row it ended up at.
        """
        return self.__move(at, at + 1)

    def move_to_bottom(self, at: int) -> int:
        """Move one sample to the last row -- the `ItemOrderingEditor` contract.

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
        before = destination + 1 if destination > row else destination
        self.moveRow(QModelIndex(), row, QModelIndex(), before)
        return destination

    def __slot_text(self, filename: str) -> str:
        """The slot :attr:`patterns_provider`'s current patterns assign ``filename``, as display text.

        :param filename: the sample filename or stem, as typed.
        :returns: a zero-padded two-digit slot (``"07"``), or :data:`NOT_A_SCREENSHOT`.
        """
        stem = Path(filename).stem if filename.strip() else ""
        if not stem:
            return NOT_A_SCREENSHOT
        patterns = ScreenshotNamePatterns(tuple(self.patterns_provider()))
        slot = patterns.slot(stem)
        return f"{slot:02d}" if slot is not None else NOT_A_SCREENSHOT

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
        return COLUMN_TITLES[section]

    @override
    def flags(self, index: ModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == FILENAME_COLUMN:
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    @override
    def data(self, index: ModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        if role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return None
        filename = self.__entries[index.row()]
        if index.column() == FILENAME_COLUMN:
            return filename
        if role == Qt.ItemDataRole.EditRole:
            return None
        return self.__slot_text(filename)

    @override
    def setData(  # noqa: N802  (Qt API name)
        self,
        index: ModelIndex,
        value: Any,
        role: int = Qt.ItemDataRole.EditRole,
    ) -> bool:
        if not index.isValid() or role != Qt.ItemDataRole.EditRole or index.column() != FILENAME_COLUMN:
            return False
        row = index.row()
        text = str(value).strip()
        if text == self.__entries[row]:
            return False
        self.__entries[row] = text  # pylint: disable=unsupported-assignment-operation
        # both columns: the slot column is a pure function of this one
        self.dataChanged.emit(index.sibling(row, FILENAME_COLUMN), index.sibling(row, SLOT_COLUMN))
        return True

    @override
    def insertRows(self, row: int, count: int, parent: ModelIndex = QModelIndex()) -> bool:  # noqa: N802
        if parent.isValid() or count < 1 or not 0 <= row <= len(self.__entries):
            return False
        self.beginInsertRows(QModelIndex(), row, row + count - 1)
        self.__entries[row:row] = ["" for _ in range(count)]  # pylint: disable=unsupported-assignment-operation
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
