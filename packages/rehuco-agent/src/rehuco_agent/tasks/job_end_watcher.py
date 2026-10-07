"""Tells a surface, on the GUI thread, that a job it enqueued has ended (#457).

The queue calls its listeners on the worker thread with its lock held, so a surface that wants to *act* on a job's end
-- announce the record a verify rewrote, so every view of it refreshes -- cannot do it from the listener. This holds the
callbacks, and hands each one over through a queued signal, once, when its job reaches a finished state or is removed.

The same shape as :class:`~rehuco_agent.rehuco.root_catalog.RootCatalog`'s own tracking of the jobs it enqueued, for the
surfaces that want a callback per job and not one answer for a whole batch.
"""

from collections.abc import Callable, Sequence
from threading import Lock
from typing import Final

from PySide6.QtCore import QObject, Qt, Signal
from rehuco_core import FINISHED_JOB_STATES, JobStatus, TaskQueue


class JobEndWatcher(QObject):
    """Calls back, on the thread this lives on, when a watched job ends.

    :param queue: the queue the jobs are on.
    :param parent: optional Qt parent.
    """

    _ended = Signal(int)
    """Carries a serial across the thread boundary, and nothing else."""

    def __init__(self, queue: TaskQueue, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__queue: Final = queue
        self.__lock: Final = Lock()
        self.__callbacks: Final[dict[int, Callable[[], None]]] = {}
        self._ended.connect(self.__on_ended, Qt.ConnectionType.QueuedConnection)
        queue.add_listener(self)

    def watch(self, serial: int, callback: Callable[[], None]) -> None:
        """Call ``callback`` once ``serial``'s job has ended.

        The job may have finished before this was called, in which case no listener call is left to say so: the queue
        is asked once now.

        :param serial: the job, as :meth:`~rehuco_core.TaskQueue.enqueue` returned it.
        :param callback: what to do, on this object's thread.
        """
        with self.__lock:
            self.__callbacks[serial] = callback  # pylint: disable=unsupported-assignment-operation
        if any(status.serial == serial and status.state in FINISHED_JOB_STATES for status in self.__queue.jobs()):
            self._ended.emit(serial)

    def detach(self) -> None:
        """Stop listening, for a window that is closing."""
        self.__queue.remove_listener(self)
        with self.__lock:
            self.__callbacks.clear()

    def __on_ended(self, serial: int) -> None:
        """Run the callback of a job that ended, once (GUI thread).

        :param serial: the job.
        """
        with self.__lock:
            callback = self.__callbacks.pop(serial, None)
        if callback is not None:
            callback()

    # region TaskQueueListener -- called on the worker thread, under the queue's lock

    def job_enqueued(self, status: JobStatus, index: int) -> None:
        """See :class:`~rehuco_core.TaskQueueListener`."""
        del status, index

    def job_updated(self, status: JobStatus) -> None:
        """See :class:`~rehuco_core.TaskQueueListener`."""
        if status.state not in FINISHED_JOB_STATES:
            return
        with self.__lock:
            watched = status.serial in self.__callbacks
        if watched:
            self._ended.emit(status.serial)

    def jobs_reordered(self, serials: Sequence[int]) -> None:
        """See :class:`~rehuco_core.TaskQueueListener`."""
        del serials

    def jobs_removed(self, serials: Sequence[int]) -> None:
        """See :class:`~rehuco_core.TaskQueueListener`: a job the reader cleared says nothing more."""
        with self.__lock:
            for serial in serials:
                self.__callbacks.pop(serial, None)

    def queue_paused_changed(self, paused: bool) -> None:
        """See :class:`~rehuco_core.TaskQueueListener`."""
        del paused

    # endregion
