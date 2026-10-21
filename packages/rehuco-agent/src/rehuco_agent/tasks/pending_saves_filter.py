"""The task queue narrowed to the record saves that have not landed (#497).

A save is a job like any other ([[appendices.task-queue#jobs]]), so the dock shows it among the rest; this is
the one view of the queue a reader asking *is my work on disk yet?* needs, and what the status bar's pending-saves
counter opens.
"""

from typing import Final, override

from PySide6.QtCore import QModelIndex, QObject, QPersistentModelIndex, QSortFilterProxyModel
from rehuco_core import SAVE_RECORD_KIND, JobState, JobStatus

from .task_queue_model import TaskQueueModel

type ModelIndex = QModelIndex | QPersistentModelIndex
"""What Qt hands a model method; the persistent form arrives from a view holding onto an index."""

SETTLED_SAVE_STATES: Final = frozenset({JobState.DONE, JobState.CANCELLED})
"""The states in which a save is no longer pending: it landed, or it was dropped on purpose.

``FAILED`` is deliberately absent: a failed save's edits are still only in memory, which is exactly what a
reader looking for pending saves has to be shown."""


def is_pending_save(status: JobStatus) -> bool:
    """Whether a row is a record save that has not landed -- the one predicate the filter and the counter share.

    :param status: the row to test.
    :returns: ``True`` for a save-kind job not in :data:`SETTLED_SAVE_STATES`.
    """
    return status.kind == SAVE_RECORD_KIND and status.state not in SETTLED_SAVE_STATES


class PendingSavesFilter(QSortFilterProxyModel):
    """Keeps only the rows :func:`is_pending_save` accepts while enabled; passes every row through while not.

    Rows leave on their own as their saves land: ``dynamicSortFilter`` (Qt's default) re-tests a row on every
    ``dataChanged`` the :class:`~.task_queue_model.TaskQueueModel` emits, so nothing here has to watch the queue.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__enabled = False

    @property
    def enabled(self) -> bool:
        """Whether only pending saves are shown."""
        return self.__enabled

    def set_enabled(self, enabled: bool) -> None:
        """Show only pending saves, or every row again.

        :param enabled: ``True`` to filter.
        """
        if enabled == self.__enabled:
            return
        self.__enabled = enabled
        # invalidateFilter() is deprecated in this Qt version; invalidate() is the plain equivalent, and the re-sort
        # it adds is harmless -- this proxy never sorts, so rows keep the queue's own order
        self.invalidate()

    @override
    def filterAcceptsRow(self, source_row: int, source_parent: ModelIndex) -> bool:  # noqa: N802  (Qt API name)
        if not self.__enabled:
            return True
        source = self.sourceModel()
        status = source.data(source.index(source_row, 0, source_parent), TaskQueueModel.Roles.STATUS)
        return isinstance(status, JobStatus) and is_pending_save(status)
