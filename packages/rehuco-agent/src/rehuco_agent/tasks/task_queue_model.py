"""The queue as table rows -- one snapshot at a time, re-taken whenever the engine says something
changed (#202, [[appendices.task-queue#observation]]).
"""

from collections.abc import Sequence
from enum import IntEnum, unique
from typing import Any, Final, override

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QPersistentModelIndex, Qt, Signal
from rehuco_core import JobState, JobStatus, StopRequest, TaskQueue

type ModelIndex = QModelIndex | QPersistentModelIndex
"""What Qt hands a model method; the persistent form arrives from a view holding onto an index."""

LABEL_COLUMN: Final = 0
STATE_COLUMN: Final = 1
PROGRESS_COLUMN: Final = 2
COLUMN_COUNT: Final = 3
COLUMN_TITLES: Final = ("Task", "State", "Progress")

STATE_LABELS: Final = {
    JobState.QUEUED: "Queued",
    JobState.RUNNING: "Running",
    JobState.PAUSED: "Paused",
    JobState.DONE: "Done",
    JobState.FAILED: "Failed",
    JobState.CANCELLED: "Cancelled",
}
"""What a bare state reads as, before :func:`state_text` folds in a pending stop."""


def state_text(status: JobStatus) -> str:
    """What a row's state column says, one field read twice: the state, and whether a stop is pending.

    ``stop_requested`` is deliberately independent of ``state`` -- a running job that has been asked to
    stop but has not yet looked at the request is still, honestly, running
    ([[appendices.task-queue#pause-concept]]). *Cancelling…* / *Pausing…* is therefore drawn from the
    pair, never from a third flag this model would have to keep in step with the other two.

    :param status: the job to describe.
    :returns: the text a row's state column shows.
    """
    if status.stop_requested is StopRequest.CANCEL:
        return "Cancelling…"
    if status.stop_requested is StopRequest.PAUSE:
        return "Pausing…"
    return STATE_LABELS.get(status.state, status.state)


RESUMES_HINT: Final = "Resumes where it left off."
"""What pausing a job that keeps a cursor costs: nothing."""

NOT_SAVED_HINT: Final = "Not saved -- lost if the app quits before this finishes."
"""Shown on a row whose job is not persistable ([[appendices.task-queue#lifetime]]).

The opt-out is deliberately visible: ``TaskJob`` alone is legal and simply is not saved, and
:attr:`~rehuco_core.JobStatus.persistable` says so on every row *so that* a surface can mark what is
about to be lost rather than let it vanish at quit."""

STARTS_OVER_HINT: Final = "Starts again from the beginning when resumed."
"""What pausing a job that keeps nothing costs -- the sentence a row and the Pause action both show.

Read off one bit, :attr:`~rehuco_core.JobStatus.resumes_where_it_stopped`, and nothing else: *how* a
job resumes is the job class's own business ([[appendices.task-queue#job-responsibility]]), and the
only question a surface has a legitimate interest in is whether pausing costs the work done so far."""


def resume_hint(status: JobStatus) -> str:
    """What pausing this job costs, for a tooltip and the Pause action -- inform, never block
    ([[appendices.task-queue#job-responsibility]]).

    :param status: the job to describe.
    :returns: the one-sentence cost of pausing it.
    """
    return RESUMES_HINT if status.resumes_where_it_stopped else STARTS_OVER_HINT


class TaskQueueModel(QAbstractTableModel):
    """A pure view over a :class:`~rehuco_core.TaskQueue`: it re-snapshots, it never replays.

    **Re-snapshotting rather than replaying** ([[appendices.task-queue#observation]]) is the whole of
    what this class decides. The engine's five listener methods all collapse to *something changed*;
    on the next GUI-thread turn, this model takes a fresh :meth:`~rehuco_core.TaskQueue.jobs` and diffs
    it against what it is holding. Per-serial last-wins coalescing -- the cheap way to replay -- is
    unsound the moment a reorder or a removal interleaves with an update, and keeping it correct needs
    an ordered op-log that coalesces almost nothing. Re-snapshotting is correct by construction: this
    model is always exactly the queue at a recent instant.

    Satisfies ``TaskQueueListener`` structurally, the same reason `LogModel` does not inherit the
    `Protocol` it satisfies: a `QAbstractTableModel` and a `Protocol` share no metaclass Shiboken will
    accept.

    **Marshalling is a nested `Marshaller(QObject)` with one payload-free signal on an explicit
    `QueuedConnection`**, the shape :class:`~borco_pyside.logging.LogBridge` uses. Explicit-queued is
    load-bearing: a control clicked on the GUI thread re-enters a listener method synchronously and
    must still take the queued path, which is what makes "the view follows the engine, not its own
    optimistic guess" mechanical rather than a discipline someone has to remember.

    :param queue: the queue to watch; not attached until :meth:`attach_to`.
    :param parent: optional Qt parent.
    """

    snapshot_taken = Signal()
    """Fires on the GUI thread after every re-snapshot -- after the row signals above, so a slot
    reading rows or :attr:`~rehuco_core.TaskQueue.paused` off this always sees the settled state.

    What a derived, non-row bit of UI (the widget's bulk Pause/Resume toggle) should connect to instead
    of becoming a second `TaskQueueListener` of its own: `queue_paused_changed` is called on whichever
    thread the queue's own last unfinished job stopped on, and touching a `QAction` there would be a
    plain GUI-thread-safety bug. This signal is only ever emitted from :meth:`__resnapshot`, which the
    marshaller's queued connection already guarantees runs on the GUI thread."""

    class Marshaller(QObject):
        """Carries "the queue changed" across the thread boundary, and nothing else.

        Nested and undocumented outside this class for the same reason
        :class:`~borco_pyside.logging.LogBridge.Marshaller` is: a mangled class name is not one Qt or
        the linters will accept, and nothing outside :class:`TaskQueueModel` has a reason to build one.
        """

        snapshot_due = Signal()
        """Fires when the held rows may be stale. Carries nothing: the payload is whatever
        :meth:`~rehuco_core.TaskQueue.jobs` answers by the time the slot runs."""

    @unique
    class Roles(IntEnum):
        """Roles beyond Qt's own."""

        STATUS = Qt.ItemDataRole.UserRole + 1
        """The whole :class:`~rehuco_core.JobStatus` for the row, on any column."""

    def __init__(self, queue: TaskQueue, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__queue: Final = queue
        self.__marshaller: Final = TaskQueueModel.Marshaller()
        self.__marshaller.snapshot_due.connect(self.__resnapshot, Qt.ConnectionType.QueuedConnection)
        self.__pending = False
        self.__rows: list[JobStatus] = list(queue.jobs())

    # region attachment

    def attach_to(self, queue: TaskQueue | None = None) -> None:
        """Start listening, and seed the rows from the current snapshot.

        A newly added listener is not replayed anything by the queue itself
        ([[appendices.task-queue#observation]]), so seeding here is this model's own doing.

        :param queue: the queue to attach to; the one given at construction unless a test says
            otherwise.
        """
        target = queue if queue is not None else self.__queue
        self.__rows = list(target.jobs())
        target.add_listener(self)

    def detach(self) -> None:
        """Stop listening.

        Called before :meth:`~rehuco_core.TaskQueue.shutdown`: shutdown synchronously emits
        ``job_updated`` for each job it cancels, and each would otherwise schedule a wake-up whose
        dispatch runs against a model whose view is being torn down.
        """
        self.__queue.remove_listener(self)

    # endregion

    # region TaskQueueListener -- every method is "something changed", nothing more

    def job_enqueued(self, status: JobStatus, index: int) -> None:
        """See :class:`~rehuco_core.TaskQueueListener`."""
        del status, index
        self.__wake()

    def job_updated(self, status: JobStatus) -> None:
        """See :class:`~rehuco_core.TaskQueueListener`."""
        del status
        self.__wake()

    def jobs_reordered(self, serials: Sequence[int]) -> None:
        """See :class:`~rehuco_core.TaskQueueListener`."""
        del serials
        self.__wake()

    def jobs_removed(self, serials: Sequence[int]) -> None:
        """See :class:`~rehuco_core.TaskQueueListener`."""
        del serials
        self.__wake()

    def queue_paused_changed(self, paused: bool) -> None:
        """See :class:`~rehuco_core.TaskQueueListener`."""
        del paused
        self.__wake()

    def __wake(self) -> None:
        """Ask the GUI thread for a re-snapshot, once per burst.

        Called under the queue's own lock, on whichever thread the change happened on -- so this must
        stay quick and must never touch the model's rows itself. Emitted only once per pending batch:
        a job hashing a large tree calls this once per file, and the queued connection lets every one
        of those arriving before the GUI thread wakes join the same, single re-snapshot.
        """
        if self.__pending:
            return
        self.__pending = True
        self.__marshaller.snapshot_due.emit()

    def __resnapshot(self) -> None:
        """Replace the held rows with a fresh :meth:`~rehuco_core.TaskQueue.jobs`.

        Runs on the GUI thread. **Removals and insertions are row operations**, which is what makes a
        bulk enqueue of thousands of jobs one :meth:`beginInsertRows` rather than one per row -- the
        common case, since neither a job finishing nor one being paused moves its position. **An actual
        reorder is a full reset.** It only happens from an explicit, infrequent user action (the
        Top/Up/Down/Bottom buttons), never from progress, so trading its row-level animation for a
        simple, unambiguous "everything changed" is the trade worth making: hand-rolling
        ``beginMoveRows``' original-index/adjusted-destination semantics correctly is easy to get subtly
        wrong, and getting it wrong here would show a row where the engine did not put it.
        """
        self.__pending = False
        fresh = list(self.__queue.jobs())
        fresh_by_serial = {status.serial: status for status in fresh}
        old_kept_order = [status.serial for status in self.__rows if status.serial in fresh_by_serial]
        fresh_serials = [status.serial for status in fresh]
        old_serial_set = {status.serial for status in self.__rows}
        fresh_kept_order = [serial for serial in fresh_serials if serial in old_serial_set]

        if old_kept_order != fresh_kept_order:
            self.beginResetModel()
            self.__rows = fresh
            self.endResetModel()
            self.snapshot_taken.emit()
            return

        self.__remove_missing(fresh_by_serial)
        self.__insert_missing(fresh, fresh_serials)
        self.__update_changed(fresh_by_serial)
        self.snapshot_taken.emit()

    def __remove_missing(self, fresh_by_serial: dict[int, JobStatus]) -> None:
        """Drop every held row whose serial is no longer in ``fresh_by_serial``, as contiguous runs,
        back to front.
        """
        index = len(self.__rows) - 1
        while index >= 0:
            if self.__rows[index].serial in fresh_by_serial:
                index -= 1
                continue
            end = index
            while index >= 0 and self.__rows[index].serial not in fresh_by_serial:
                index -= 1
            self.beginRemoveRows(QModelIndex(), index + 1, end)
            del self.__rows[index + 1 : end + 1]  # pylint: disable=unsupported-delete-operation
            self.endRemoveRows()

    def __insert_missing(self, fresh: list[JobStatus], fresh_order: list[int]) -> None:
        """Insert whatever ``fresh`` holds that this model does not yet, as contiguous runs."""
        held_serials = {status.serial for status in self.__rows}
        index = 0
        while index < len(fresh_order):
            if fresh_order[index] in held_serials:
                index += 1
                continue
            start = index
            while index < len(fresh_order) and fresh_order[index] not in held_serials:
                index += 1
            batch = fresh[start:index]
            self.beginInsertRows(QModelIndex(), start, start + len(batch) - 1)
            self.__rows[start:start] = batch  # pylint: disable=unsupported-assignment-operation
            self.endInsertRows()
            held_serials.update(status.serial for status in batch)

    def __update_changed(self, fresh_by_serial: dict[int, JobStatus]) -> None:
        """Replace and signal every row whose content differs from the fresh snapshot."""
        for row, status in enumerate(self.__rows):
            fresh_status = fresh_by_serial[status.serial]
            if fresh_status == status:
                continue
            self.__rows[row] = fresh_status  # pylint: disable=unsupported-assignment-operation
            top_left = self.index(row, 0)
            bottom_right = self.index(row, COLUMN_COUNT - 1)
            self.dataChanged.emit(top_left, bottom_right)

    # endregion

    # region Qt model interface

    @override
    def rowCount(self, parent: ModelIndex = QModelIndex()) -> int:  # noqa: N802  (Qt API name)
        return 0 if parent.isValid() else len(self.__rows)

    @override
    def columnCount(self, parent: ModelIndex = QModelIndex()) -> int:  # noqa: N802  (Qt API name)
        return 0 if parent.isValid() else COLUMN_COUNT

    @override
    def data(self, index: ModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        status = self.__rows[index.row()]
        if role == TaskQueueModel.Roles.STATUS:
            return status
        if role == Qt.ItemDataRole.DisplayRole:
            return self.__display(status, index.column())
        if role == Qt.ItemDataRole.ToolTipRole:
            return self.__tooltip(status)
        return None

    @staticmethod
    def __display(status: JobStatus, column: int) -> str | None:
        """What a cell's plain text is -- the label and state columns; the progress column is drawn by
        :class:`~rehuco_agent.tasks.task_progress_delegate.TaskProgressDelegate`, not read as text.
        """
        if column == LABEL_COLUMN:
            return status.label
        if column == STATE_COLUMN:
            return state_text(status)
        return None

    @staticmethod
    def __tooltip(status: JobStatus) -> str:
        """The full story a cell's text elides: the failure reason in full, the resume cost, and
        whether this row is about to be lost at quit.
        """
        lines = [status.error] if status.error else []
        lines.append(resume_hint(status))
        if not status.persistable:
            lines.append(NOT_SAVED_HINT)
        return "\n".join(lines)

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

    # region convenience for the widget

    def status_at(self, row: int) -> JobStatus:
        """The `JobStatus` a row holds.

        :param row: the row.
        :returns: its status.
        """
        return self.__rows[row]

    # endregion
