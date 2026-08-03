"""What the queue offers whoever is watching it, so the engine never has to know it is a dock
([[appendices.task-queue#observation]]).
"""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from .task_job import JobStatus


@runtime_checkable
class TaskQueueListener(Protocol):
    """Somewhere the queue's changes can be put -- a row model, a test's list, a node's status page.

    **Called synchronously, on whichever thread the change happened**: the worker thread for progress
    and outcomes, the caller's thread for an enqueue, a cancel or a reorder. That is deliberately the
    same contract `logging` gives a handler, and for the same reason -- the engine has no thread of
    the observer's to marshal onto, and inventing one would put a queue in front of a queue. A GUI
    observer is the piece that buffers, coalesces and marshals onto the GUI thread, which is what the
    log stack's bridge already does for records; the engine deliberately does none of the three, so
    that it stays usable from a headless node that needs neither.

    A listener must therefore be **quick, and must not block** -- it is holding up the job that called
    it, and a job hashing a large tree calls :meth:`job_updated` once per file. A listener that raises
    is logged and skipped for that round rather than allowed to propagate: on the worker thread its
    exception would kill the queue's loop, which is the silent stall this component must never produce.

    Five methods rather than one event stream, because each maps onto exactly one operation of the row
    model that renders it: an insert, a change, a move, a removal, and a fact about the queue as a
    whole. Satisfied structurally: a `QAbstractTableModel` cannot inherit a `Protocol` (mixing its
    metaclass with Shiboken's raises a metaclass conflict), and the engine only ever calls the methods.
    """

    def job_enqueued(self, status: JobStatus, index: int) -> None:
        """A job was accepted.

        :param status: the new job, always :attr:`~rehuco_core.tasks.JobState.QUEUED`.
        :param index: where it landed in the queue's order. Always the end today; passed anyway so a
            listener never has to keep a count of its own in step with the engine's.
        """
        ...  # pylint: disable=unnecessary-ellipsis

    def job_updated(self, status: JobStatus) -> None:
        """A job's state or progress changed.

        :param status: the job as it now is, identified by
            :attr:`~rehuco_core.tasks.JobStatus.serial`.
        """
        ...  # pylint: disable=unnecessary-ellipsis

    def jobs_reordered(self, serials: Sequence[int]) -> None:
        """The queue's order changed.

        The whole order rather than the one move that produced it: a listener holding rows can assign
        the new order outright, and never has to replay a move it may have missed the start of.

        :param serials: every job's serial, in the new order.
        """
        ...  # pylint: disable=unnecessary-ellipsis

    def jobs_removed(self, serials: Sequence[int]) -> None:
        """Jobs were dropped from the queue.

        :param serials: the serials removed, in the order they were held.
        """
        ...  # pylint: disable=unnecessary-ellipsis

    def queue_paused_changed(self, paused: bool) -> None:
        """The queue was paused or resumed.

        Says nothing about the running job, which is still running: it reports its own
        :attr:`~rehuco_core.tasks.JobState.PAUSED` through :meth:`job_updated` when it reaches a
        checkpoint, which may be a long way after this.

        :param paused: whether the queue is now paused.
        """
        ...  # pylint: disable=unnecessary-ellipsis
