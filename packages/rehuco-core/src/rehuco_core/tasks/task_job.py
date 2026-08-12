"""What a task-queue job is, and what one is handed while it runs ([[appendices.task-queue#jobs]]).

The vocabulary the engine and its clients share, kept apart from
:mod:`~rehuco_core.tasks.task_queue` so that a client writing a job -- a checksum run, a scan, a
conversion -- imports what a job *is* without importing the machinery that runs one.

Grouped rather than split one class per file because none of these means anything on its own: a state
is the state of a job, a control is what that job is handed, a status is that job seen from outside,
and the two exceptions are how a job reports that it stopped.
"""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, Protocol, runtime_checkable


class JobState(StrEnum):
    """Where a job is in its life ([[appendices.task-queue#jobs]]).

    Six, not four: :attr:`PAUSED` is a state of the *job*, because a job asked to pause does not stop
    the moment it is asked -- it stops where it chose to, and until it gets there it is genuinely
    still running. Collapsing the two would make a job that has not yielded yet indistinguishable from
    one that has.
    """

    QUEUED = "queued"
    """Accepted, waiting its turn. Queued and *scheduled* are the same concept, which is why there is
    no state for the second: a resumed job is queued like any other
    ([[appendices.task-queue#reorder]])."""

    RUNNING = "running"
    """The worker thread is inside this job's ``run``. Exactly one job is ever in this state, and it is
    the only job the engine ever calls :meth:`TaskJob.pause`, :meth:`TaskJob.resume` or
    :meth:`TaskJob.cancel` on."""

    PAUSED = "paused"
    """Asked to pause, and it obeyed: its ``run`` has *returned* and the next job was free to start.
    Resuming calls ``run`` again, and whether that continues or starts over is the job's own
    :attr:`TaskJob.resumes_where_it_stopped`. Not terminal -- a paused job is unfinished work still
    holding its place in the order."""

    DONE = "done"
    """Returned without raising. A job that finished is done even if a stop was asked for: the request
    was never acted on, and reporting an outcome the work did not have would describe an intention."""

    FAILED = "failed"
    """Raised. The exception is kept as :attr:`JobStatus.error` and written to the log; the queue then
    starts the next job ([[appendices.task-queue#failure]]). Kept rather than swept, because a failure
    is usually retryable -- see :meth:`~rehuco_core.tasks.TaskQueue.retry`."""

    CANCELLED = "cancelled"
    """Stopped on request -- either before it ever ran, or by the job obeying one."""


FINISHED_JOB_STATES: Final = frozenset({JobState.DONE, JobState.FAILED, JobState.CANCELLED})
"""The states a job never leaves on its own.

What :meth:`~rehuco_core.tasks.TaskQueue.retry` acts on and what everything else refuses to act on.
:attr:`JobState.PAUSED` is deliberately not among them: a paused job is unfinished, is what a stop
request still applies to, and is what shutdown must still cancel."""


class StopRequest(StrEnum):
    """What a job has been asked to do about stopping ([[appendices.task-queue#pause-concept]]).

    **One slot, not two flags.** A job is asked for at most one thing at a time and the latest
    instruction replaces the one before it, so asking a cancelling job to pause *downgrades* the
    request rather than leaving two contradictory ones for a checkpoint to arbitrate. Two independent
    booleans could express "cancel and pause", which is not a state anybody can act on and not a
    state any surface can draw.
    """

    PAUSE = "pause"
    """Stop, and keep whatever you need to carry on. Resumable."""

    CANCEL = "cancel"
    """Stop for good. Whatever the job undoes on the way out is the job's own business."""


PROGRESS_UNIT_BYTES: Final = "bytes"
"""What a job counting the bytes it has read or written declares (#248).

**Names rather than an enumeration**, so that a job this package has never heard of can declare a unit
of its own and a surface that does not recognize it still draws something honest. The two below are
what the jobs shipped here count, and they exist so that neither side spells the string by hand."""

PROGRESS_UNIT_RESOURCES: Final = "resources"
"""What a job counting whole resources declares (#248)."""


class JobCancelled(Exception):
    """Raised out of a job to report that it obeyed a cancel.

    An exception rather than a return value: a job is a call stack several frames deep when it
    notices, and every frame between would otherwise need a "and if it said stop, stop" branch. The
    engine catches it and records :attr:`JobState.CANCELLED`, so a job may let it escape -- and must
    not swallow it, since a caught-and-ignored cancellation is a job that cannot be stopped at all.
    """


class JobPaused(Exception):
    """Raised out of a job to report that it obeyed a pause.

    The same shape as :class:`JobCancelled`, for the same reason, differing only in what the engine
    records: :attr:`JobState.PAUSED`, which is resumable rather than terminal.

    **Pausing returns rather than parks** ([[appendices.task-queue#cursor]]). A paused job's ``run``
    has unwound and the worker thread has gone on to the next job; resuming calls ``run`` again and the
    job carries on from whatever it kept for itself.
    """


@runtime_checkable
# one method is the design, not an omission -- see the docstring below
# pylint: disable-next=too-few-public-methods
class JobControl(Protocol):
    """What a running job is handed: the way to say how far it has got.

    One method, because **stopping is not the engine's business**
    ([[appendices.task-queue#job-responsibility]]). A job holds its own stop request, decides where
    its work divides, and decides what obeying costs; the engine only needs to be told about progress,
    which it cannot observe and a view cannot draw without.

    Called on the worker thread, from inside the job's own ``run``.
    """

    def report(self, done: int, total: int | None = None) -> None:
        """Say how far this job has got.

        :param done: units finished so far, in whatever unit this job counts -- **which unit that is,
            the job says once**, in :attr:`TaskJob.progress_unit` (#248). Nothing here converts,
            labels or scales it.
        :param total: units expected in all, or ``None`` when the job cannot say -- a scan that
            discovers as it walks genuinely does not know, and an honest *indeterminate* is what a
            view can draw. Deliberately not a percentage: only the job knows what it is counting.
        """


@runtime_checkable
class TaskJob(Protocol):
    """One unit of slow work the queue runs ([[architecture-design#components]]).

    **The job class is the unit of responsibility** ([[appendices.task-queue#job-responsibility]]).
    The engine schedules, orders and records; everything about *stopping* belongs here. A job holds
    its own stop request, chooses where its work divides, decides whether a stop can still be taken
    back, and owns whatever it keeps between runs. A new kind of resumable work is a new class, not a
    new engine feature.

    Most jobs should inherit :class:`~rehuco_core.tasks.TaskJobBase`, which implements the whole stop
    protocol over one request slot and offers the ``checkpoint`` that raises. Implementing this
    directly is supported and is what a job with genuinely different stop semantics does.

    **Threading.** ``run`` executes on the worker thread. :meth:`pause`, :meth:`resume` and
    :meth:`cancel` are called from whichever thread asked -- the GUI thread, in practice -- **while
    that** ``run`` **is executing**, and only ever on the one job that is running. A job that keeps
    mutable stop state therefore owns its own locking; :class:`~rehuco_core.tasks.TaskJobBase` does
    this and is the reason it exists. :attr:`label` and the other declarations are read once at
    enqueue, and :meth:`reset` is called only on a job that has finished, so neither ever overlaps
    ``run``. :attr:`source` is the exception on both counts: it is re-read whenever
    :meth:`~rehuco_core.TaskQueue.resync_sources` is called, **which does overlap** ``run``, so a job
    whose source can move must answer from something safe to read on another thread -- a
    :class:`~rehuco_core.ResourceLocation` is exactly that, and is why it holds one.
    """

    @property
    def label(self) -> str:  # pyright: ignore[reportReturnType]
        """How this job is named to a reader, e.g. ``"Verify checksums - Sculpting Series"``.

        Read once, when the job is enqueued, and carried on every :class:`JobStatus` from then on: a
        label that changed while the job ran would rewrite a row a reader is looking at.
        """

    @property
    def source(self) -> Path | None:
        """Where this job's work **is** -- the ``.rehu`` it is about, or ``None`` for work about no one
        resource.

        The job's own declaration rather than something the enqueuer passes alongside, so there is one
        answer and nothing to keep in step.

        **The one declaration that may change while the job runs** (#241). Everything else here is read
        once at enqueue, because an answer that moved would rewrite a row a reader is looking at; this
        one is not a claim about the job but a location, and a rename moves locations under running
        work. A job that follows its resource returns its
        :class:`~rehuco_core.ResourceLocation`'s current path from here, and
        :meth:`~rehuco_core.TaskQueue.resync_sources` is how the queue is told to look again. A job that
        does not care answers the same path forever and costs nothing.
        """

    @property
    def safely_interruptible(self) -> bool:  # pyright: ignore[reportReturnType]
        """Whether stopping this job part-way leaves nothing behind.

        ``True`` for work that only reads, or only writes files it would rewrite from scratch anyway.
        ``False`` for work that is part-way through changing something when it stops.

        **Distinct from *revertible*.** A conversion undoes itself when it fails
        ([[acquisition-tooling#convert-mechanics]]) and is still not safely interruptible: it has
        touched the directory. Read once at enqueue and carried on :class:`JobStatus`, so a surface
        can warn before stopping one.
        """

    @property
    def resumes_where_it_stopped(self) -> bool:  # pyright: ignore[reportReturnType]
        """Whether pausing this job keeps the work already done.

        Deliberately named for the **consequence** rather than the mechanism: nothing outside the job
        class may assume there is anything kept between runs at all. This answers the only question a
        surface has a legitimate interest in -- *will pausing this cost the work done so far?* -- so a
        dock can say so before someone pauses a forty-minute sweep that will start again.

        **Starting over is a supported answer, not a defect.** A verify job that records only which
        manifest it checks against is correct; pausing and resuming it is wasteful rather than wrong.
        """

    @property
    def progress_unit(self) -> str:  # pyright: ignore[reportReturnType]
        """What this job's :meth:`JobControl.report` counts, e.g. :data:`PROGRESS_UNIT_BYTES` -- or
        ``""`` for a job with no progress worth showing (#248).

        **The job is what knows.** ``done`` and ``total`` are bare numbers, so a run hashing four
        gigabytes and a sweep over forty resources are indistinguishable to anything downstream; a
        surface handed both would have to guess, and would draw one of them wrong. This is the fact that
        makes them tellable apart, and it is the job's own for the same reason ``source`` and
        ``resumes_where_it_stopped`` are ([[appendices.task-queue#job-responsibility]]).

        **A unit, not a rendering.** Nothing here says how wide a bar is, what a byte count is spelled
        as, or whether anything is drawn at all -- this package has no view in it and gains no
        formatting dependency ([[appendices.task-queue#home]]). It says what is being counted, and a
        surface decides what to do about that. ``""`` is the honest answer for a job whose progress is
        one step: a bar that jumps from empty to full says nothing a state column does not.

        Read once at enqueue and carried on every :class:`JobStatus`, like every declaration here but
        :attr:`source`.
        """

    def run(self, control: JobControl) -> None:
        """Do the work, on the worker thread.

        Called again after a pause, and again after a retry. Which of the two it is looking at is the
        job's own business: a job that resumes reads whatever it kept, and one that does not starts
        from the top. A stop request left over from the run that obeyed it is **cleared by**
        :meth:`resume`, which the engine calls on every job it puts back in line -- so a job re-entered
        through the queue never has a stale one to trip over.

        Touches no GUI object and no state another thread reads without a lock of its own. Progress
        goes through ``control``; anything else it wants to say, it logs (its records land under the
        scope open when it was enqueued, [[appendices.task-queue#scopes]]).

        :param control: the engine's face to this job.
        :raises JobCancelled: to report that it obeyed a cancel; the engine catches it.
        :raises JobPaused: to report that it obeyed a pause; likewise.
        """

    def pause(self) -> None:
        """Be asked to stop and keep what you have.

        Called on the caller's thread while ``run`` executes. Records the request; it is the job's own
        ``run`` that acts on it, wherever it chooses to. A job that never looks runs to completion,
        exactly as one that never looked for a cancel always has.
        """

    def cancel(self) -> None:
        """Be asked to stop for good.

        Called on the caller's thread while ``run`` executes, and replaces any pause already asked
        for. What the job undoes on the way out -- a conversion's rollback
        ([[acquisition-tooling#convert-mechanics]]) -- is its own business and invisible to the
        engine.
        """

    def resume(self) -> bool:  # pyright: ignore[reportReturnType]
        """Be told to carry on, and say whether the stop was taken back in time.

        Called on the caller's thread while ``run`` executes, and also on a job that has already
        stopped and is going back in line -- in which case the answer is ignored and the call is
        simply the job's chance to drop a request it has finished with.

        **This is the one question only the job can answer.** The engine cannot know whether a
        cancel has been merely recorded or is already halfway through undoing the work, because that
        distinction lives entirely inside the job. So the job answers it.

        :returns: ``True`` when the request had not been acted on and the job is carrying on as
            though it was never asked; ``False`` when it was too late -- the job is already stopping
            and the engine must treat the outcome as real. A ``False`` after a *pause* still costs
            nothing but a re-entry, and the engine re-queues the job for one; a ``False`` after a
            *cancel* is final, and the recovery is :meth:`~rehuco_core.tasks.TaskQueue.retry`.
        """

    def reset(self) -> None:
        """Throw away whatever was kept, so the next :meth:`run` starts from the beginning.

        The engine saying *start over*; what that means is the job's, because the engine cannot see
        what it would be discarding. Called by :meth:`~rehuco_core.tasks.TaskQueue.retry` and by
        nothing else -- **this is the whole difference between Retry and Resume** -- and only on a job
        that has finished, so it never overlaps ``run``.
        """


# Twelve, and each is a distinct fact a reader of one row wants: who it is, what it is doing, how far
# it has got and in what, what went wrong, what has been asked of it, what stopping it would cost, and
# whether it will still be here tomorrow. The last five are the job's own declarations, copied here so that a
# status answers without reaching back for the job object -- which a reader on another thread has no
# business holding.
@dataclass(frozen=True)
# pylint: disable-next=too-many-instance-attributes
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
    :param progress_unit: the job's :attr:`TaskJob.progress_unit`, read once at enqueue -- what the two
        numbers above are *in*, without which they cannot be drawn honestly (#248). ``""`` on a job with
        no progress worth showing.
    :param error: why a :attr:`JobState.FAILED` job failed, as ``"TypeName: message"``, else ``None``.
        The text rather than the exception: the full traceback is written to the log, where it can be
        read, and a snapshot carrying a live exception invites a reader to re-raise it on a thread
        that has nothing to do with where it happened.
    :param stop_requested: what the job was last asked to do about stopping, or ``None``. A **fact
        separate from the state**, so a watcher can be honest while the running job has not acted yet
        -- and so that a job which finished anyway can be reported :attr:`JobState.DONE` without the
        request being lost. What the engine last *asked and has not seen answered*: a request the
        engine settled itself, or watched the job unwind under, is cleared with the settling (#260),
        so no row goes on reading *Pausing…* after the pause has happened. Whether the running job
        has acted on its request yet is the job's to know, and a surface finds out by asking for a
        resume.
    :param source: where the job's work is, as of this snapshot -- its :attr:`TaskJob.source`, read at
        enqueue and re-read whenever the queue is told a rename moved something
        (:meth:`~rehuco_core.TaskQueue.resync_sources`, #241). The one declaration below that is not
        fixed for the job's lifetime, because it names a place rather than describing the work.
    :param safely_interruptible: the job's :attr:`TaskJob.safely_interruptible`, read once at enqueue.
    :param resumes_where_it_stopped: the job's :attr:`TaskJob.resumes_where_it_stopped`, read once at
        enqueue.
    :param persistable: whether this job satisfies
        :class:`~rehuco_core.tasks.PersistableTaskJob` and will therefore still be here after a
        restart. **The opt-out has to be visible** ([[appendices.task-queue#lifetime]]): a surface that
        knows a row is about to be lost at quit can say so, where one that does not would let it vanish
        silently.
    """

    serial: int
    label: str
    state: JobState
    done: int = 0
    total: int | None = None
    progress_unit: str = ""
    error: str | None = None
    stop_requested: StopRequest | None = None
    source: Path | None = None
    safely_interruptible: bool = True
    resumes_where_it_stopped: bool = False
    persistable: bool = False
