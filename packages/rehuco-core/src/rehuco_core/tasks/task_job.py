"""What a task-queue job is, and what one is handed while it runs ([[appendices.task-queue#jobs]]).

The vocabulary the engine and its clients share, kept apart from
:mod:`~rehuco_core.tasks.task_queue` so that a client writing a job -- a checksum run, a scan, a
conversion -- imports what a job *is* without importing the machinery that runs one.

Grouped rather than split one class per file because none of these five means anything on its own: a
state is the state of a job, a control is what that job is handed, a status is that job seen from
outside, and the exception is how a job says it obeyed a stop.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Protocol, runtime_checkable


class JobState(StrEnum):
    """Where a job is in its life ([[appendices.task-queue#jobs]]).

    Six, not four: :attr:`PAUSED` is a state of the *job* and not only of the queue, because a queue
    asked to pause does not stop the moment it is asked -- the running job stops at its next
    checkpoint, and until it reaches one it is genuinely still running. Collapsing the two would make
    a job that has not yielded yet indistinguishable from one that has.
    """

    QUEUED = "queued"
    """Accepted, not started. The only state a job can be reordered in
    ([[appendices.task-queue#reorder]])."""

    RUNNING = "running"
    """The worker thread is inside this job's ``run``. Exactly one job is ever in this state."""

    PAUSED = "paused"
    """Started, and parked at a checkpoint because the queue was paused. Resuming continues it from
    where it stopped -- nothing is re-run."""

    DONE = "done"
    """Returned without raising, and without a cancellation having been asked for."""

    FAILED = "failed"
    """Raised. The exception is kept as :attr:`JobStatus.error` and written to the log; the queue then
    starts the next job ([[appendices.task-queue#failure]])."""

    CANCELLED = "cancelled"
    """Stopped on request -- either before it ever ran, or by obeying
    :meth:`JobControl.checkpoint`."""


FINISHED_JOB_STATES: Final = frozenset({JobState.DONE, JobState.FAILED, JobState.CANCELLED})
"""The states a job never leaves. What :meth:`~rehuco_core.tasks.TaskQueue.clear_finished` removes,
what :meth:`~rehuco_core.tasks.TaskQueue.cancel` refuses to act on, and what shutdown leaves alone."""


class JobCancelled(Exception):
    """Raised out of :meth:`JobControl.checkpoint` to unwind a job that was asked to stop.

    An exception rather than a return value the job has to check and propagate: a job is a call stack
    several frames deep by the time it notices, and every frame between would otherwise need a "and
    if it said stop, stop" branch. The engine catches it and records :attr:`JobState.CANCELLED`, so a
    job may let it escape -- and must not swallow it, since a caught-and-ignored cancellation is a job
    that cannot be stopped at all.
    """


@runtime_checkable
class JobControl(Protocol):
    """What a running job is handed: the way to yield, and the way to say how far it has got.

    **Cancellation is cooperative**, which is the whole reason this exists. A thread cannot be killed
    safely -- a job halfway through a rename, holding a file handle, must be allowed to unwind rather
    than be shot -- so stopping is something a job *does* on being asked. :meth:`checkpoint` is where
    it asks, and the same call is where a pause parks it, so a job that can be cancelled can be paused
    for free.

    Every method is called on the worker thread, from inside the job's own ``run``.
    """

    def checkpoint(self) -> None:
        """Yield to the engine: block while the queue is paused, and stop if cancellation was asked.

        Call it wherever the work divides -- once per file, once per chunk -- and nowhere else: a job
        that never calls it runs to completion and cannot be interrupted, and a job that calls it
        between two halves of an atomic step can be stopped in the middle of one.

        :raises JobCancelled: when this job was cancelled, whether before or during the pause.
        """
        ...  # pylint: disable=unnecessary-ellipsis

    def report(self, done: int, total: int | None = None) -> None:
        """Say how far this job has got.

        :param done: units finished so far, in whatever unit this job counts.
        :param total: units expected in all, or ``None`` when the job cannot say -- a scan that
            discovers as it walks genuinely does not know, and an honest *indeterminate* is what a
            view can draw. Deliberately not a percentage: only the job knows what it is counting.
        """
        ...  # pylint: disable=unnecessary-ellipsis

    @property
    def cancelled(self) -> bool:
        """Whether a stop has been asked for, without unwinding on it.

        For a job that would rather finish tidying up than be raised out of -- a conversion writing
        its rollback record. Ordinary jobs call :meth:`checkpoint` and never read this.
        """
        ...  # pylint: disable=unnecessary-ellipsis


@runtime_checkable
class TaskJob(Protocol):
    """One unit of slow work the queue runs ([[architecture-design#components]]).

    **The engine knows nothing about any job.** A checksum run, a directory scan, a bulk conversion
    and a test's fake all satisfy this and nothing else is required of them -- which is what keeps the
    queue from accumulating a case per client.

    Satisfied structurally, and by a plain object rather than a subclass: a job is usually a small
    dataclass closing over the paths and settings it needs, and asking it to inherit a base would buy
    nothing the two members below do not already state.
    """

    @property
    def label(self) -> str:
        """How this job is named to a reader, e.g. ``"Verify checksums - Sculpting Series"``.

        Read once, when the job is enqueued, and carried on every :class:`JobStatus` from then on: a
        label that changed while the job ran would rewrite a row a reader is looking at.
        """
        ...  # pylint: disable=unnecessary-ellipsis

    def run(self, control: JobControl) -> None:
        """Do the work, on the worker thread.

        Touches no GUI object and no state another thread reads without a lock of its own -- what it
        may touch is the filesystem and whatever plain Python state it was constructed with. Progress
        and cancellation go through ``control``; anything else it wants to say, it logs (its records
        land under the scope open when it was enqueued, [[appendices.task-queue#scopes]]).

        :param control: the engine's face to this job.
        :raises JobCancelled: propagated from :meth:`JobControl.checkpoint`; the engine catches it.
        """
        ...  # pylint: disable=unnecessary-ellipsis


@dataclass(frozen=True)
class JobStatus:
    """One job as an observer sees it -- a snapshot, taken at the moment something about it changed.

    Frozen, and handed out rather than the engine's own record, because a status crosses a thread
    boundary on its way to whoever is watching: a mutable one would go on changing under a reader
    that is halfway through drawing it.

    :param serial: the job's identity, minted by the engine at enqueue and never reused.
    :param label: the job's :attr:`TaskJob.label`, read once at enqueue.
    :param state: where the job is now.
    :param done: units finished, as last reported.
    :param total: units expected, or ``None`` for indeterminate -- see :meth:`JobControl.report`.
    :param error: why a :attr:`JobState.FAILED` job failed, as ``"TypeName: message"``, else ``None``.
        The text rather than the exception: the full traceback is written to the log, where it can be
        read, and a snapshot carrying a live exception invites a reader to re-raise it on a thread
        that has nothing to do with where it happened.
    """

    serial: int
    label: str
    state: JobState
    done: int = 0
    total: int | None = None
    error: str | None = None
