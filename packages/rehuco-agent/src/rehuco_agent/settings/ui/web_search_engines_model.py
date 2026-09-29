"""The web search engines as a two-column model: a name and the URL template it searches with (#388)."""

# The Qt row plumbing and the two protocols' row operations read the same as
# `LocationReplacementsModel`'s, because they are the same contract `ItemListEditor` drives every list
# model through; the rows each holds differ, and a shared generic base would have to be typed over both
# entry shapes for no gain.
# pylint: disable=duplicate-code

from collections.abc import Sequence
from typing import Any, Final, override

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QPersistentModelIndex, Qt, Signal
from PySide6.QtGui import QBrush, QColor

from ...fields.colors import WARNING_COLOR
from ..web_search_settings import DEFAULT_ENGINES, EMPTY_NAME_PROBLEM, SearchEngine, engine_problem

NAME_COLUMN: Final = 0
"""The engine's name -- the cell an insert opens. Column 0 in the *model* because that is the cell
`ItemListEditor` opens on Add; the radio column is moved ahead of it in the view alone."""

URL_COLUMN: Final = 1
"""The URL template, holding the query placeholder."""

ACTIVE_COLUMN: Final = 2
"""A radio button: whether searches go through this engine. Exactly one row is on. Shown first."""

COLUMN_COUNT: Final = 3

COLUMN_TITLES: Final = ("Name", "URL", "Use")

type ModelIndex = QModelIndex | QPersistentModelIndex
"""What Qt hands a model method; the persistent form arrives from a view holding onto an index."""


# the count is `QAbstractTableModel`'s surface plus the two protocols `ItemListEditor` drives the model
# through -- four ordering methods, four editing ones -- none of which this class chose
# pylint: disable-next=too-many-public-methods
class WebSearchEnginesModel(QAbstractTableModel):
    """The engine list as editable rows of an *active* radio, a *name* and a *URL* (#388).

    **Exactly one row is active while any row is:** turning one on turns the others off, the radio cannot
    be cleared, and deleting the active row (or setting a list with none active) activates the first
    usable row. A copy made by :meth:`duplicate` starts inactive.

    **Validation is flagged, never enforced**, as in `LocationReplacementsModel`: a row failing
    :func:`~rehuco_agent.settings.web_search_settings.engine_problem` colors its cell and explains itself
    in a tooltip, and is kept so a typo is fixed in place. The name cell shows an empty name, the URL
    cell the other two problems.

    **Also an `ItemEditor`/`ItemOrderingEditor`** (structurally -- no explicit `Protocol` inheritance,
    since mixing `Protocol`'s metaclass with Shiboken's raises a metaclass conflict).

    :param defaults: what :meth:`reset` restores; :data:`DEFAULT_ENGINES` unless a caller says otherwise.
    :param parent: optional Qt parent.
    """

    count_changed = Signal()
    """Fires whenever :attr:`count` changes -- the `ItemOrderingEditor` contract."""

    def __init__(self, defaults: Sequence[SearchEngine] = DEFAULT_ENGINES, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__entries: list[SearchEngine] = []
        self.__defaults: tuple[SearchEngine, ...] = tuple(defaults)
        self.rowsInserted.connect(self.count_changed)
        self.rowsRemoved.connect(self.count_changed)
        self.modelReset.connect(self.count_changed)

    @property
    def count(self) -> int:
        """How many engines there are -- the `ItemOrderingEditor` contract."""
        return len(self.__entries)

    @property
    def entries(self) -> tuple[SearchEngine, ...]:
        """Every engine, in row order, exactly as typed."""
        return tuple(self.__entries)

    def set_entries(self, entries: Sequence[SearchEngine]) -> None:
        """Replace every row, as one model reset, if the engines actually differ.

        :param entries: the engines to show, in order.
        """
        replacement = self.__with_one_active(entries)
        if replacement == self.__entries:
            return
        self.beginResetModel()
        self.__entries = replacement
        self.endResetModel()

    @staticmethod
    def __with_one_active(entries: Sequence[SearchEngine]) -> list[SearchEngine]:
        """``entries`` with at most the first active row still active, and the first usable row active
        when none was.

        :param entries: the engines as given.
        :returns: the same rows with the active flag made exclusive.
        """
        rows = list(entries)
        first = next((row for row, entry in enumerate(rows) if entry.active), None)
        if first is None:
            first = next((row for row, entry in enumerate(rows) if not engine_problem(entry)), None)
        return [entry._replace(active=row == first) for row, entry in enumerate(rows)]

    @property
    def defaults(self) -> tuple[SearchEngine, ...]:
        """What :meth:`reset` restores; an empty one means there is nothing to restore."""
        return self.__defaults

    @defaults.setter
    def defaults(self, defaults: Sequence[SearchEngine]) -> None:
        """Set what :meth:`reset` restores.

        :param defaults: the engines Reset should put back.
        """
        self.__defaults = tuple(defaults)

    def insert(self, at: int) -> int:
        """Insert a blank engine after ``at``, or at the end -- the `ItemEditor` contract.

        :param at: the row to insert after, or a negative row to append.
        :returns: the new engine's row.
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
        self.__entries.insert(target, self.__entries[at]._replace(active=False))
        self.endInsertRows()
        return target

    def delete(self, at: int) -> None:
        """Drop one engine -- the `ItemEditor` contract.

        :param at: the row to drop; a negative row is a no-op.
        """
        if at >= 0:
            self.removeRow(at)

    def reset(self) -> None:
        """Put :attr:`defaults` back -- the `ItemEditor` contract."""
        self.set_entries(self.__defaults)

    def move_to_top(self, at: int) -> int:
        """Move one engine to the first row -- the `ItemOrderingEditor` contract.

        :param at: the row to move.
        :returns: the row it ended up at.
        """
        return self.__move(at, 0)

    def move_up(self, at: int) -> int:
        """Move one engine up a row -- the `ItemOrderingEditor` contract.

        :param at: the row to move.
        :returns: the row it ended up at.
        """
        return self.__move(at, at - 1)

    def move_down(self, at: int) -> int:
        """Move one engine down a row -- the `ItemOrderingEditor` contract.

        :param at: the row to move.
        :returns: the row it ended up at.
        """
        return self.__move(at, at + 1)

    def move_to_bottom(self, at: int) -> int:
        """Move one engine to the last row -- the `ItemOrderingEditor` contract.

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
        # *before* -- so a downward move has to name one past the target
        before = destination + 1 if destination > row else destination
        self.moveRow(QModelIndex(), row, QModelIndex(), before)
        return destination

    def invalid_reason(self, row: int) -> str:
        """Why the engine at ``row`` cannot be searched with, if it cannot.

        :param row: the row to test.
        :returns: the explanation, or an empty string when the engine is fine.
        """
        return engine_problem(self.__entries[row])

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
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == ACTIVE_COLUMN:
            return base | Qt.ItemFlag.ItemIsUserCheckable
        return base | Qt.ItemFlag.ItemIsEditable

    @override
    # three columns' worth of role handling -- collapsing them behind one exit would need a sentinel
    # meaning both "no answer" and "the answer is None"
    def data(self, index: ModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # pylint: disable=too-many-return-statements
        if not index.isValid():
            return None
        entry = self.__entries[index.row()]
        column = index.column()
        if column == ACTIVE_COLUMN:
            if role == Qt.ItemDataRole.CheckStateRole:
                return Qt.CheckState.Checked if entry.active else Qt.CheckState.Unchecked
            # EditRole too, which is what the settings dialog's frame snapshot reads and writes back
            return entry.active if role == Qt.ItemDataRole.EditRole else None
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return entry.name if column == NAME_COLUMN else entry.url
        reason = self.invalid_reason(index.row())
        # a missing name is the name cell's problem; the other two are the URL's
        if not reason or (reason == EMPTY_NAME_PROBLEM) != (column == NAME_COLUMN):
            return None
        if role == Qt.ItemDataRole.ToolTipRole:
            return reason
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
        if not index.isValid():
            return False
        row = index.row()
        if index.column() == ACTIVE_COLUMN:
            if role == Qt.ItemDataRole.CheckStateRole:
                return self.__activate(row, Qt.CheckState(value) == Qt.CheckState.Checked)
            return self.__activate(row, bool(value)) if role == Qt.ItemDataRole.EditRole else False
        if role != Qt.ItemDataRole.EditRole:
            return False
        entry = self.__entries[row]
        replacement = (
            entry._replace(name=str(value)) if index.column() == NAME_COLUMN else entry._replace(url=str(value))
        )
        if replacement == entry:
            return False
        self.__entries[row] = replacement  # pylint: disable=unsupported-assignment-operation
        # a name edit can change which cell is flagged on the row, so both are refreshed
        self.dataChanged.emit(self.index(row, 0), self.index(row, COLUMN_COUNT - 1))
        return True

    def __activate(self, row: int, active: bool) -> bool:
        """Make ``row`` the active engine; asking for it to be inactive changes nothing, since a radio
        is only ever cleared by another being set.

        :param row: the row asked about.
        :param active: whether it was asked to become active.
        :returns: whether the active engine changed.
        """
        if not active or self.__entries[row].active:
            return False
        self.__entries = [entry._replace(active=at == row) for at, entry in enumerate(self.__entries)]
        self.dataChanged.emit(self.index(0, ACTIVE_COLUMN), self.index(len(self.__entries) - 1, ACTIVE_COLUMN))
        return True

    @override
    def insertRows(self, row: int, count: int, parent: ModelIndex = QModelIndex()) -> bool:  # noqa: N802
        if parent.isValid() or count < 1 or not 0 <= row <= len(self.__entries):
            return False
        self.beginInsertRows(QModelIndex(), row, row + count - 1)
        self.__entries[row:row] = [SearchEngine("", "")] * count  # pylint: disable=unsupported-assignment-operation
        self.endInsertRows()
        return True

    @override
    def removeRows(self, row: int, count: int, parent: ModelIndex = QModelIndex()) -> bool:  # noqa: N802
        if parent.isValid() or count < 1 or not 0 <= row <= len(self.__entries) - count:
            return False
        self.beginRemoveRows(QModelIndex(), row, row + count - 1)
        del self.__entries[row : row + count]  # pylint: disable=unsupported-delete-operation
        self.endRemoveRows()
        activated = self.__with_one_active(self.__entries)
        if activated != self.__entries:
            self.__entries = activated
            self.dataChanged.emit(self.index(0, ACTIVE_COLUMN), self.index(len(activated) - 1, ACTIVE_COLUMN))
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
