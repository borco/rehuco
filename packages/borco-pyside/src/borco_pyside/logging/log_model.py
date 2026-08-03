"""Log entries as table rows -- one bounded history, owned by whoever built the model."""

from collections import deque
from collections.abc import Sequence
from enum import IntEnum, unique
from typing import Any, Final, override

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QPersistentModelIndex, Qt, Signal

from .log_bridge import DEFAULT_LOG_LIMIT
from .log_entry import LogEntry

type ModelIndex = QModelIndex | QPersistentModelIndex
"""What Qt hands a model method; the persistent form arrives from a view holding onto an index."""

LEVEL_COLUMN: Final = 0
"""Column showing the record's level name."""

MESSAGE_COLUMN: Final = 1
"""Column showing the formatted message."""

COLUMN_COUNT: Final = 2

COLUMN_TITLES: Final = ("Level", "Message")


class LogModel(QAbstractTableModel):
    """A bounded, self-contained table of log entries -- and a `LogRecordSink`.

    **Its history is its own.** Several of these exist at once: one showing everything, one per thing
    with a log of its own. Each keeps its own buffer, drops its own oldest entries, and is cleared on
    its own; emptying one says nothing about any other, and nothing about what
    :class:`~.log_bridge.LogBridge` still holds for the next surface to attach. The only thing several
    models are likely to share is the *number* in :attr:`limit`, and even that is their owner's doing
    rather than something arranged here -- a table model is a poor place to put a policy about other
    table models.

    **Two columns, and the entry behind them.** Level and message are what a table lays out; everything
    else a surface might want -- the timestamp, the scope, the source file and line, the exception --
    is on the entry itself, reachable through :attr:`Roles.ENTRY`. A delegate painting by level and a
    proxy filtering by it both read that one role, so neither needs a column that exists only to be
    hidden.

    Satisfies `LogRecordSink` structurally -- no explicit `Protocol` inheritance, since mixing
    `Protocol`'s metaclass with Shiboken's raises a metaclass conflict.

    :param parent: optional Qt parent.
    :param limit: how many entries to keep; see :attr:`limit`.
    """

    dropped_changed = Signal(int)
    """Fires with :attr:`dropped` whenever entries are discarded to stay within :attr:`limit`.

    So a surface can say *"N earlier records dropped"* without polling: the number changes while the
    view is busy showing the rows that displaced them."""

    @unique
    class Roles(IntEnum):
        """Roles beyond Qt's own."""

        ENTRY = Qt.ItemDataRole.UserRole + 1
        """The whole :class:`~.log_entry.LogEntry` for the row, on any column."""

    def __init__(self, parent: QObject | None = None, *, limit: int = DEFAULT_LOG_LIMIT) -> None:
        super().__init__(parent)
        self.__limit = max(1, limit)
        self.__entries: deque[LogEntry] = deque(maxlen=self.__limit)
        self.__dropped = 0

    # region the history

    @property
    def limit(self) -> int:
        """How many entries to keep before dropping the oldest.

        Settable while running, and applied at once rather than at the next restart: a reader who
        lowers this in a settings dialog is telling an open, scrolled-back view what to hold now.
        """
        return self.__limit

    @limit.setter
    def limit(self, limit: int) -> None:
        """Re-cap the history, removing the oldest rows if it no longer fits.

        :param limit: the new cap; anything below 1 is raised to 1.
        """
        limit = max(1, limit)
        if limit == self.__limit:
            return
        self.__limit = limit
        self.__discard(max(0, len(self.__entries) - limit))
        # a deque's maxlen is read-only, so re-capping means building the replacement; __discard has
        # already taken it down to size, through the row removal a view needs to see
        self.__entries = deque(self.__entries, maxlen=limit)

    @property
    def dropped(self) -> int:
        """How many entries this model has discarded to stay within :attr:`limit`, over the whole run.

        Not reset by :meth:`clear`: it answers *"is anything missing"*, and clearing a view does not
        bring back what was already gone before it."""
        return self.__dropped

    def clear(self) -> None:
        """Drop every row.

        Empties this model and nothing else -- not the bridge's replay cache, and not another model
        showing the same records.
        """
        if not self.__entries:
            return
        self.beginResetModel()
        self.__entries.clear()
        self.endResetModel()

    def handle_log_records(self, entries: Sequence[LogEntry]) -> None:
        """Append a batch of entries, dropping as many of the oldest as it displaces.

        One removal and one insertion for the whole batch, whatever its size: the batch arrives as a
        batch precisely so that a burst costs a view one relayout instead of one per record.

        :param entries: the entries to append, oldest first.
        """
        if not entries:
            return
        # a longer batch than the buffer can hold keeps its newest, which is what the ring would have
        # left after appending them one by one -- and the rest is dropped, so it is counted as dropped
        # rather than quietly never arriving
        arriving = list(entries)[-self.__limit :]
        self.__count_dropped(len(entries) - len(arriving))
        self.__discard(len(self.__entries) + len(arriving) - self.__limit)
        first = len(self.__entries)
        self.beginInsertRows(QModelIndex(), first, first + len(arriving) - 1)
        self.__entries.extend(arriving)
        self.endInsertRows()

    def __discard(self, count: int) -> None:
        """Remove ``count`` of the oldest entries, as one row removal.

        A removal rather than a reset even though it is always the top of the list: a reset would cost
        the view its selection and its scroll position on every batch that overflows the buffer, which
        during a loud job is every batch.

        :param count: how many to remove; zero or fewer is a no-op.
        """
        if count <= 0:
            return
        self.beginRemoveRows(QModelIndex(), 0, count - 1)
        for _ in range(count):
            self.__entries.popleft()
        self.endRemoveRows()
        self.__count_dropped(count)

    def __count_dropped(self, count: int) -> None:
        """Record that ``count`` entries will not be shown, and say so.

        Separate from :meth:`__discard` because entries are lost two ways -- displaced out of the
        buffer, and never put in it because the batch that carried them was longer than the buffer --
        and a reader asking *"is anything missing"* is owed both.

        :param count: how many were lost; zero or fewer is a no-op.
        """
        if count <= 0:
            return
        self.__dropped += count
        self.dropped_changed.emit(self.__dropped)

    # endregion

    # region Qt model interface

    @override
    def rowCount(self, parent: ModelIndex = QModelIndex()) -> int:  # noqa: N802  (Qt API name)
        return 0 if parent.isValid() else len(self.__entries)

    @override
    def columnCount(self, parent: ModelIndex = QModelIndex()) -> int:  # noqa: N802  (Qt API name)
        return 0 if parent.isValid() else COLUMN_COUNT

    @override
    def data(self, index: ModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        entry = self.__entries[index.row()]
        if role == LogModel.Roles.ENTRY:
            return entry
        if role == Qt.ItemDataRole.DisplayRole:
            return entry.record.levelname if index.column() == LEVEL_COLUMN else entry.message
        return None

    @override
    def headerData(  # noqa: N802  (Qt API name)
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if role != Qt.ItemDataRole.DisplayRole or orientation != Qt.Orientation.Horizontal:
            return None
        return COLUMN_TITLES[section] if 0 <= section < COLUMN_COUNT else None

    # endregion
