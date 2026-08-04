"""The app-wide queue of slow work: one job at a time, in an order the user can change
([[architecture-design#components]], [[appendices.task-queue]]).

GUI-free and Qt-free on purpose ([[appendices.task-queue#home]]): the queue's contract is written in
rehuco's own specification, a headless node is specified to run jobs too, and the observation seam
(:class:`~rehuco_core.tasks.TaskQueueListener`) is all a dock needs to render one.
"""

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import Context, copy_context
from dataclasses import dataclass
from pathlib import Path
from threading import Condition, RLock, Thread
from typing import Final

from .task_job import (
    FINISHED_JOB_STATES,
    JobCancelled,
    JobPaused,
    JobState,
    JobStatus,
    StopRequest,
    TaskJob,
)
from .task_queue_listener import TaskQueueListener

LOG: Final = logging.getLogger(__name__)

DEFAULT_SHUTDOWN_TIMEOUT: Final = 5.0
"""How long :meth:`TaskQueue.shutdown` and :meth:`TaskQueue.wait_until_idle` wait for the running job
to notice, in seconds.

Long enough for a cooperative job to reach its next checkpoint and unwind, short enough that quitting
the app never feels hung. A job that ignores its checkpoints outlives this, which is why the worker is
a daemon thread as well -- the wait is a courtesy, not the thing that makes the process exit."""

MOVABLE_JOB_STATES: Final = frozenset({JobState.QUEUED, JobState.PAUSED})
"""The states a job can be reordered in ([[appendices.task-queue#reorder]]).

Both, because neither is executing and both are still waiting their turn: a paused job is as
reorderable as a queued one, and refusing to move it would be an arbitrary difference between two jobs
that are equally not running."""


class TaskQueue:
    """Runs jobs one at a time, and lets them be paused, reordered, removed and retried.

    **Serial by construction, not by configuration** ([[appendices.task-queue#serial]]). There is one
    worker thread and there is no number to raise: the specified behavior is that multi-selecting ten
    resources serializes the work rather than running it all at once, because ten hashes against one
    disk are slower than one, not faster. A future parallel lane over a genuinely different resource
    would be a second queue, never a count on this one.

    **The engine schedules; the job stops itself** ([[appendices.task-queue#job-responsibility]]).
    Asking a running job to pause or cancel is a call *into* the job, which holds the request and acts
    on it wherever its work divides. That is what lets a resume be answered honestly: only the job
    knows whether a cancel has been merely recorded or is already halfway through undoing the work,
    so only the job can say whether taking it back is still possible.

    **Pausing a job returns it rather than parking it** ([[appendices.task-queue#cursor]]). A job asked
    to pause unwinds out of its own ``run``, the worker goes straight on to the next job, and resuming
    calls ``run`` again -- so pausing the running job is not pausing the queue, and there is never a
    Python stack held open on a job's behalf.

    **Jobs leave only when told to** ([[appendices.task-queue#kept]]). Nothing sweeps: a failed or
    cancelled job is kept because it is usually retryable. :meth:`remove` is the only way out.

    Every observable change reaches :class:`~rehuco_core.tasks.TaskQueueListener`, called under this
    queue's own lock so that a row model is never told about a change out of order. The lock is
    re-entrant, so a listener that calls back in (a dock cancelling a job as it sees it fail) is safe;
    a listener that blocks is not, and the protocol says so.

    > A job's :meth:`~rehuco_core.tasks.TaskJob.pause`, ``cancel`` and ``resume`` are likewise called
    > with this lock held, so they must be quick and must not call back into the queue. They are
    > specified as recording a request, which is all that needs doing under a lock.
    """

    # Thirteen, and each is a distinct fact about one job: its identity and label, the job itself, the
    # context it was enqueued in, what it declared about itself, where it has got to, what it
    # reported, why it failed, and what it was asked. `resume_requested` alone stays off the status:
    # it exists for one gap -- a pause taken back too late to stop the unwind -- and its only
    # observable effect is the state that outcome is recorded as.
    @dataclass
    # pylint: disable-next=too-many-instance-attributes
    class Entry:
        """One job and everything the queue knows about it -- the mutable original a
        :class:`~rehuco_core.tasks.JobStatus` is snapshotted from.

        Nested and undocumented outside this class because nothing else has a reason to hold one: what
        leaves the queue is always the frozen snapshot. Every field below is read and written only
        while the queue's condition is held.
        """

        serial: int
        job: TaskJob
        label: str
        context: Context
        source: Path | None = None
        safely_interruptible: bool = True
        resumes_where_it_stopped: bool = False
        state: JobState = JobState.QUEUED
        done: int = 0
        total: int | None = None
        error: str | None = None
        stop_requested: StopRequest | None = None
        resume_requested: bool = False

        def status(self) -> JobStatus:
            """Snapshot this entry for an observer.

            :returns: the frozen view of it, as of now.
            """
            return JobStatus(
                serial=self.serial,
                label=self.label,
                state=self.state,
                done=self.done,
                total=self.total,
                error=self.error,
                stop_requested=self.stop_requested,
                source=self.source,
                safely_interruptible=self.safely_interruptible,
                resumes_where_it_stopped=self.resumes_where_it_stopped,
            )

        def unfinished(self) -> bool:
            """Whether this job still has somewhere to go.

            :returns: ``True`` unless it is done, failed or cancelled -- a paused job is unfinished.
            """
            return self.state not in FINISHED_JOB_STATES

    # one method is the design, not an omission: stopping belongs to the job, so progress is all the
    # engine still has to offer a running one ([[appendices.task-queue#job-responsibility]]).
    # pylint: disable-next=too-few-public-methods
    class Control:
        """The engine's face to the one running job -- what satisfies
        :class:`~rehuco_core.tasks.JobControl`.

        One method, because stopping is the job's own business now: all the engine offers a running job
        is somewhere to put its progress.

        **Satisfied structurally, not inherited**, like every other protocol implementer in this repo.
        Inheriting bought a checked ``@override`` back when the protocol had three members; with one,
        the same drift is caught where it matters anyway -- passing this to
        :meth:`~rehuco_core.tasks.TaskJob.run` fails type-checking with the exact parameter that
        disagrees. What inheriting costs is worse than what it bought: it would make the protocol's own
        method bodies live inherited code rather than the unreachable declarations they are everywhere
        else.

        Built per job, from inside :class:`TaskQueue`'s own body, which is why it takes its
        collaborators as plain arguments rather than reaching for the queue: a nested class cannot read
        an outer class's private members (name mangling resolves them against the *inner* class), while
        a callable written in the outer body closes over them correctly.

        :param condition: the queue's condition; guards ``entry``.
        :param entry: the job this control belongs to.
        :param notify: tells the queue's listeners that ``entry`` changed; called with the condition
            already held.
        """

        def __init__(
            self,
            condition: Condition,
            entry: TaskQueue.Entry,
            notify: Callable[[TaskQueue.Entry], None],
        ) -> None:
            self.__condition: Final = condition
            self.__entry: Final = entry
            self.__notify: Final = notify

        def report(self, done: int, total: int | None = None) -> None:
            """Record how far this job has got and tell the listeners.

            :param done: units finished so far.
            :param total: units expected, or ``None`` for indeterminate.
            """
            with self.__condition:
                self.__entry.done = done
                self.__entry.total = total
                self.__notify(self.__entry)

    def __init__(self) -> None:
        self.__condition: Final = Condition(RLock())
        self.__entries: list[TaskQueue.Entry] = []
        self.__listeners: list[TaskQueueListener] = []
        self.__next_serial = 0
        self.__running: TaskQueue.Entry | None = None
        self.__stopping = False
        self.__worker: Thread | None = None

    # region observation

    def add_listener(self, listener: TaskQueueListener) -> None:
        """Start telling ``listener`` about changes.

        Nothing is replayed: a listener attaching to a queue that already holds jobs seeds itself from
        :meth:`jobs` and is told about everything after that. Deliberately not the log bridge's
        replay-on-attach, because a queue's history *is* its current state -- there is no record of a
        job that was removed, and none is owed.

        :param listener: where changes go from now on.
        """
        with self.__condition:
            self.__listeners.append(listener)

    def remove_listener(self, listener: TaskQueueListener) -> None:
        """Stop telling ``listener`` about changes.

        A listener that is not attached is silently accepted, so teardown never has to ask first.

        :param listener: the listener to detach.
        """
        with self.__condition:
            self.__listeners = [attached for attached in self.__listeners if attached is not listener]

    def jobs(self) -> tuple[JobStatus, ...]:
        """Every job the queue holds, in its current order.

        :returns: a snapshot per job, oldest position first.
        """
        with self.__condition:
            return tuple(entry.status() for entry in self.__entries)

    @property
    def paused(self) -> bool:
        """Whether every unfinished job is paused.

        **Derived, and it gates nothing** ([[appendices.task-queue#pause-concept]]): dispatch reads
        per-job state only, and this exists so a surface can draw one Pause/Resume control over the
        queue rather than make the reader infer it from the rows. ``False`` on a queue holding nothing
        unfinished -- vacuously true would read as *the queue is held* to anyone drawing it, which is
        the opposite of what an empty queue means.
        """
        with self.__condition:
            return self.__paused_now()

    # endregion

    # region the queue

    def enqueue(self, job: TaskJob) -> int:
        """Accept ``job``, starting the worker thread if this is the first one.

        The job's declarations -- :attr:`~rehuco_core.tasks.TaskJob.label`,
        :attr:`~rehuco_core.tasks.TaskJob.source`,
        :attr:`~rehuco_core.tasks.TaskJob.safely_interruptible` and
        :attr:`~rehuco_core.tasks.TaskJob.resumes_where_it_stopped` -- are read here, once, and
        carried on every status from now on. Once, because each of them answers a question about the
        row a reader is looking at, and an answer that changed while the job ran would rewrite it.

        **The caller's context is captured here and the job runs inside it**
        ([[appendices.task-queue#scopes]]): a thread does not inherit a context, so a job enqueued
        inside a document's log scope would otherwise log under nothing while working on that
        document. ``copy_context`` is generic -- this knows nothing about what is in the context, only
        that the caller's belongs to the work.

        :param job: the work to run.
        :returns: the job's serial, for :meth:`cancel`, :meth:`move`, :meth:`remove` and the rest.
        :raises RuntimeError: if the queue has been shut down; shutdown is terminal, and silently
            accepting work that will never run would be worse than refusing it.
        """
        with self.__condition:
            if self.__stopping:
                raise RuntimeError("This task queue has been shut down.")
            entry = TaskQueue.Entry(
                serial=self.__next_serial,
                job=job,
                label=job.label,
                context=copy_context(),
                source=job.source,
                safely_interruptible=job.safely_interruptible,
                resumes_where_it_stopped=job.resumes_where_it_stopped,
            )
            self.__next_serial += 1
            with self.__watching_paused():
                self.__entries.append(entry)
                index = len(self.__entries) - 1
                status = entry.status()
                self.__ensure_worker()
                self.__notify(lambda listener: listener.job_enqueued(status, index))
            self.__condition.notify_all()
            return entry.serial

    def pause(self) -> None:
        """Ask every unfinished job to pause.

        **One pause concept, not two** ([[appendices.task-queue#pause-concept]]): this is
        :meth:`pause_job` applied to all of them, not a separate queue-wide flag that dispatch
        consults. Idempotent, and a job that never looks at its request runs to completion regardless
        -- pausing is a request the jobs honor, exactly as cancelling is.
        """
        with self.__condition:
            with self.__watching_paused():
                for entry in self.__entries:
                    if entry.unfinished():
                        self.__ask_stop(entry, StopRequest.PAUSE)
            self.__condition.notify_all()

    def resume(self) -> None:
        """Put every *paused* job back in line.

        Deliberately narrower than :meth:`resume_job`: this is the inverse of :meth:`pause` and
        touches only jobs whose pending request is a pause. A cancel is never retracted in bulk --
        pressing Resume over a multi-selection to un-cancel something the user cancelled earlier would
        be a surprise, and pointing at that one row with :meth:`resume_job` is how it is asked for.
        """
        with self.__condition:
            with self.__watching_paused():
                for entry in self.__entries:
                    if entry.stop_requested is StopRequest.PAUSE or entry.state is JobState.PAUSED:
                        self.__ask_resume(entry)
            self.__condition.notify_all()

    def pause_job(self, serial: int) -> None:
        """Ask one job to pause.

        Pausing the *running* job parks it and **lets the next one start** -- the queue does not stop
        because one job did. The request replaces any cancel already asked for
        ([[appendices.task-queue#pause-concept]]): a job is asked for one thing at a time, and the
        latest instruction is the one that counts.

        Whether resuming it continues or starts it over is the job's own
        :attr:`~rehuco_core.tasks.TaskJob.resumes_where_it_stopped`, carried on its status so a reader
        can be told the cost before paying it. A finished job, and a serial belonging to nothing, are
        both no-ops.

        :param serial: which job, as returned by :meth:`enqueue`.
        """
        with self.__condition:
            entry = self.__entry(serial)
            if entry is None or not entry.unfinished():
                return
            with self.__watching_paused():
                self.__ask_stop(entry, StopRequest.PAUSE)
            self.__condition.notify_all()

    def resume_job(self, serial: int) -> bool:
        """Tell one job to carry on, and say whether the stop was taken back in time.

        A **paused** job returns to :attr:`~rehuco_core.tasks.JobState.QUEUED` in the position it held
        and runs when its turn comes round: there is no force-start
        ([[appendices.task-queue#reorder]]). The queue runs exactly one job at a time, so its order
        already answers *what runs next* -- to run a job now, :meth:`move` it to the top.

        A **running** job is asked to take its pending stop back, and **the job answers**. If it has
        not acted on the request yet, it simply carries on as though nothing was asked -- which is
        what makes Cancel followed by Resume a recoverable mis-click rather than a lost job. If it has
        already begun stopping, the answer is ``False``: a pause that far along still costs only a
        re-entry, so the engine re-queues the job when it lands, while a cancel that far along may
        already have undone work, so it runs to its end and :meth:`retry` is the recovery.

        :param serial: which job, as returned by :meth:`enqueue`.
        :returns: ``True`` when there was nothing pending, or the job took it back cleanly; ``False``
            when the job was already stopping.
        """
        with self.__condition:
            entry = self.__entry(serial)
            if entry is None or not entry.unfinished():
                return False
            with self.__watching_paused():
                taken_back = self.__ask_resume(entry)
            self.__condition.notify_all()
            return taken_back

    def cancel(self, serial: int) -> None:
        """Ask the job with ``serial`` to stop for good.

        A queued or paused job is cancelled outright and never runs again. The running one is *told*,
        and stops wherever its work divides; what it undoes on the way is its own business. The
        request replaces any pause already asked for.

        A job that never looks at its request cannot be interrupted and is reported
        :attr:`~rehuco_core.tasks.JobState.DONE` when it returns: the request was never acted on, the
        work genuinely finished, and calling that *cancelled* would report an intention rather than an
        outcome. The request is kept on the status either way, so nothing about it is lost.

        A finished job, and a serial belonging to nothing, are both no-ops.

        :param serial: which job, as returned by :meth:`enqueue`.
        """
        with self.__condition:
            entry = self.__entry(serial)
            if entry is None or not entry.unfinished():
                return
            with self.__watching_paused():
                self.__ask_stop(entry, StopRequest.CANCEL)
            self.__condition.notify_all()

    def move(self, serial: int, index: int) -> None:
        """Move a queued or paused job to position ``index``.

        Only a job in :data:`MOVABLE_JOB_STATES` moves: a running job cannot be made to have started
        later, and a finished one has no position left to matter. ``index`` is clamped into the run of
        movable jobs, so a job can never be placed ahead of the one already running -- that would
        promise an order the queue cannot deliver.

        :param serial: which job, as returned by :meth:`enqueue`.
        :param index: where to put it, in the queue's own order; clamped as above.
        """
        with self.__condition:
            entry = self.__entry(serial)
            if entry is None or entry.state not in MOVABLE_JOB_STATES:
                return
            movable = [position for position, held in enumerate(self.__entries) if held.state in MOVABLE_JOB_STATES]
            target = min(max(index, movable[0]), movable[-1])
            if target == self.__entries.index(entry):
                return
            self.__entries.remove(entry)
            self.__entries.insert(target, entry)
            order = tuple(held.serial for held in self.__entries)
            self.__notify(lambda listener: listener.jobs_reordered(order))

    def remove(self, *serials: int) -> None:
        """Drop the named jobs from the queue.

        **The only way out** ([[appendices.task-queue#kept]]). Nothing is swept: a failed or cancelled
        job is kept until someone says otherwise, because it is usually :meth:`retry`-able and
        dropping it silently would throw away the thing worth acting on.

        Removing the *running* job cancels it first, and it goes on running until it notices --
        stopping is cooperative, so a detached job may outlive its row. The engine drops its terminal
        notification rather than announce a job the caller has already removed.

        Serials belonging to nothing are ignored, so a caller never has to filter its selection.

        :param serials: which jobs, as returned by :meth:`enqueue`.
        """
        with self.__condition:
            wanted = set(serials)
            removed = tuple(entry.serial for entry in self.__entries if entry.serial in wanted)
            if not removed:
                return
            with self.__watching_paused():
                for entry in self.__entries:
                    if entry.serial in wanted and entry.state is JobState.RUNNING:
                        self.__ask_stop(entry, StopRequest.CANCEL)
                self.__entries = [entry for entry in self.__entries if entry.serial not in wanted]
                self.__notify(lambda listener: listener.jobs_removed(removed))
            self.__condition.notify_all()

    def retry(self, serial: int) -> None:
        """Put a finished job back in line and run it **from the top**.

        Clears the error, the progress and the request, and calls
        :meth:`~rehuco_core.tasks.TaskJob.reset` so that even a job which would otherwise carry on
        starts over: **that reset is the whole difference between Retry and Resume**. What it discards
        is the job's own business -- the engine cannot see what it is throwing away, and does not need
        to.

        Re-entering a job blindly is safe because a job that changes anything guards its own
        re-entry -- a conversion refuses to start over a leftover backup
        ([[acquisition-tooling#convert-mechanics]]) rather than trust the caller not to ask twice.

        A job that has not finished is a no-op: retrying something still running or still waiting has
        no meaning, and interpreting it as a restart would throw away work nobody asked to lose.

        :param serial: which job, as returned by :meth:`enqueue`.
        """
        with self.__condition:
            entry = self.__entry(serial)
            if entry is None or entry.unfinished():
                return
            entry.job.reset()
            with self.__watching_paused():
                entry.state = JobState.QUEUED
                entry.done = 0
                entry.total = None
                entry.error = None
                entry.stop_requested = None
                entry.resume_requested = False
                self.__notify_updated(entry)
            self.__condition.notify_all()

    def wait_until_idle(self, timeout: float = DEFAULT_SHUTDOWN_TIMEOUT) -> bool:
        """Wait until no job is running.

        The other half of a clean exit ([[appendices.task-queue#teardown]]): :meth:`pause` asks, this
        waits for the answer, and only then is the queue in a state worth writing down -- the running
        job has unwound to :attr:`~rehuco_core.tasks.JobState.PAUSED` and kept whatever it needs to
        carry on. Quitting is therefore *pause, wait, save, shut down*, not *cancel and hope*.

        Deliberately separate from :meth:`pause` rather than folded into it, because pausing from a
        dock must never block the thread drawing the dock. The caller decides where the waiting
        happens.

        :param timeout: how long to wait, in seconds.
        :returns: ``True`` when nothing is running, ``False`` when the wait ran out -- which means a
            job is ignoring its checkpoints, and the caller must decide whether to write what it has
            or wait longer.
        """
        with self.__condition:
            return self.__condition.wait_for(lambda: self.__running is None, timeout)

    def shutdown(self, timeout: float = DEFAULT_SHUTDOWN_TIMEOUT) -> None:
        """Cancel everything and wait for the worker to stop ([[appendices.task-queue#teardown]]).

        Terminal: a queue that has been shut down accepts no more work. Cancelling is the right verb
        here and the wrong one for quitting with work outstanding -- for that, :meth:`pause` and
        :meth:`wait_until_idle` first, and shut down once what matters has been written.

        The worker is a **daemon** thread, so a job that ignores its checkpoints can never hold the
        process open past this -- the wait is what gives a cooperative job the chance to close what it
        opened, and a job that outlives it is logged rather than waited on forever.

        :param timeout: how long to wait for the running job to unwind, in seconds.
        """
        with self.__condition:
            self.__stopping = True
            with self.__watching_paused():
                for entry in self.__entries:
                    if entry.unfinished():
                        self.__ask_stop(entry, StopRequest.CANCEL)
            self.__condition.notify_all()
            worker = self.__worker
            self.__worker = None
        if worker is not None:
            worker.join(timeout)
            if worker.is_alive():
                LOG.warning("A task outlived the %.1fs shutdown wait and is still running.", timeout)

    # endregion

    # region internals

    def __entry(self, serial: int) -> TaskQueue.Entry | None:
        """Find the entry with ``serial``.

        :param serial: the job's serial.
        :returns: the entry, or ``None`` when no job has that serial (it was removed, or never
            existed).
        """
        for entry in self.__entries:
            if entry.serial == serial:
                return entry
        return None

    def __paused_now(self) -> bool:
        """Work out whether the queue reads as paused.

        :returns: ``True`` when there is unfinished work and every bit of it is paused.
        """
        unfinished = [entry for entry in self.__entries if entry.unfinished()]
        return bool(unfinished) and all(entry.state is JobState.PAUSED for entry in unfinished)

    @contextmanager
    def __watching_paused(self) -> Iterator[None]:
        """Tell the listeners if the derived :attr:`paused` changed over the block.

        Every operation that can move a job in or out of
        :attr:`~rehuco_core.tasks.JobState.PAUSED` -- including a job unwinding on the worker thread
        -- runs inside this, which is what lets ``paused`` be derived without any caller having to
        remember to announce it. Sampled around the whole block rather than per job, so pausing eight
        jobs says so once.

        :yields: nothing; the block does the work.
        """
        before = self.__paused_now()
        yield
        after = self.__paused_now()
        if before != after:
            self.__notify(lambda listener: listener.queue_paused_changed(after))

    def __ask_stop(self, entry: TaskQueue.Entry, request: StopRequest) -> None:
        """Ask one unfinished job to stop, the way its state allows.

        The running job is **told** -- the request is recorded inside it, and it acts wherever its work
        divides. A job that is not running has no request to act on: it never started, or it already
        stopped, so the engine settles it here and the job is never troubled.

        :param entry: the job to ask.
        :param request: what to ask of it.
        """
        changed = entry.stop_requested is not request
        entry.stop_requested = request
        entry.resume_requested = False
        if entry.state is JobState.RUNNING:
            if request is StopRequest.CANCEL:
                entry.job.cancel()
            else:
                entry.job.pause()
        elif request is StopRequest.CANCEL:
            entry.state = JobState.CANCELLED
            changed = True
        elif entry.state is JobState.QUEUED:
            entry.state = JobState.PAUSED
            changed = True
        if changed:
            self.__notify_updated(entry)

    def __ask_resume(self, entry: TaskQueue.Entry) -> bool:
        """Tell one job to carry on, and find out whether its stop was taken back in time.

        A job that is not running is simply put back in line -- the ``resume`` call is its chance to
        drop a request it has finished with, and its answer is about the stop that already happened,
        so it is not the answer this returns. Only the running job can genuinely refuse.

        :param entry: the job to tell.
        :returns: ``True`` when nothing was pending or the job took it back cleanly.
        """
        if entry.state is JobState.PAUSED:
            entry.job.resume()
            entry.state = JobState.QUEUED
            entry.stop_requested = None
            entry.resume_requested = False
            self.__notify_updated(entry)
            return True
        if entry.state is not JobState.RUNNING or entry.stop_requested is None:
            return True
        pending = entry.stop_requested
        if entry.job.resume():
            entry.stop_requested = None
            entry.resume_requested = False
            self.__notify_updated(entry)
            return True
        # too late to stop the unwind. A pause costs only a re-entry, so schedule one; a cancel may
        # already have undone work, so it stands and Retry is the recovery.
        entry.resume_requested = pending is StopRequest.PAUSE
        return False

    def __notify(self, call: Callable[[TaskQueueListener], None]) -> None:
        """Make one call on every attached listener.

        Called with the condition held, which is what keeps a row model from being told about an
        enqueue and a progress report in the opposite order to the one they happened in. Iterates a
        copy, so a listener that detaches itself while being told does not truncate the round.

        **A listener's exception is logged, never propagated** -- the same contract ``logging`` gives
        a broken handler, for the same two reasons. On the worker thread it would escape the loop and
        kill it, turning one bad observer into the silent stall this component must never produce:
        every queued job waiting forever on a thread that no longer exists. On a caller's thread it
        would raise out of an ``enqueue`` or a ``cancel`` that already happened, telling the caller an
        operation failed when it did not.

        :param call: what to say to each listener.
        """
        for listener in tuple(self.__listeners):
            try:
                call(listener)
            except Exception:  # pylint: disable=broad-exception-caught
                LOG.exception("A task-queue listener failed; detach it or fix it -- it was skipped.")

    def __notify_updated(self, entry: TaskQueue.Entry) -> None:
        """Tell the listeners that ``entry`` changed.

        :param entry: the entry to snapshot and report.
        """
        status = entry.status()
        self.__notify(lambda listener: listener.job_updated(status))

    def __ensure_worker(self) -> None:
        """Start the worker thread if it is not running yet.

        Lazy rather than started in ``__init__``: a queue nobody has given work to should not cost a
        thread, and the agent builds one at startup whether or not anything is ever enqueued.
        """
        if self.__worker is not None:
            return
        self.__worker = Thread(target=self.__work, name="rehuco-task-queue", daemon=True)
        self.__worker.start()

    def __work(self) -> None:
        """Take jobs one at a time, forever, until shutdown.

        The whole of the serialization: one thread, one job in flight, and the next one chosen only
        once the last has returned. **A paused job is simply not eligible** -- there is no queue-wide
        flag in this loop, which is what makes pausing one job leave the rest running.
        """
        while True:
            with self.__condition:
                entry = self.__next_queued()
                while not self.__stopping and entry is None:
                    self.__condition.wait()
                    entry = self.__next_queued()
                if self.__stopping or entry is None:
                    return
                with self.__watching_paused():
                    entry.state = JobState.RUNNING
                    self.__running = entry
                    self.__notify_updated(entry)
                control = TaskQueue.Control(self.__condition, entry, self.__notify_updated)
            self.__run(entry, control)

    def __next_queued(self) -> TaskQueue.Entry | None:
        """Find the job to run next.

        :returns: the first queued entry in the queue's order, or ``None`` when there is none.
        """
        for entry in self.__entries:
            if entry.state is JobState.QUEUED:
                return entry
        return None

    def __run(self, entry: TaskQueue.Entry, control: TaskQueue.Control) -> None:
        """Run one job to its outcome and record it, outside the lock.

        **The outcome is dropped if the entry was removed while it ran.** Stopping is cooperative, so
        :meth:`remove` can detach a running job that then goes on to notice; telling a listener that a
        row it deleted has just failed would be announcing a job that, as far as anyone watching is
        concerned, no longer exists.

        **A paused outcome is reconciled against what was asked by the time it lands.** The job's raise
        and this recording are two moments with its own cleanup between them, and a request can arrive
        in the gap. A cancel that came after the pause wins, since recorded onto a parked job it would
        be stranded -- nothing ever picks a paused job up. A pause taken back too late to stop the
        unwind re-queues the job, because that costs one re-entry and nothing else.

        :param entry: the job to run.
        :param control: what it is handed.
        """
        state, error = entry.context.run(self.__invoke, entry, control)
        with self.__condition:
            self.__running = None
            if self.__entry(entry.serial) is entry:
                with self.__watching_paused():
                    if state is JobState.PAUSED:
                        if entry.stop_requested is StopRequest.CANCEL:
                            state = JobState.CANCELLED
                        elif entry.resume_requested:
                            state = JobState.QUEUED
                            entry.stop_requested = None
                    entry.resume_requested = False
                    entry.state = state
                    entry.error = error
                    self.__notify_updated(entry)
            self.__condition.notify_all()

    @staticmethod
    def __invoke(entry: TaskQueue.Entry, control: TaskQueue.Control) -> tuple[JobState, str | None]:
        """Call the job and turn however it ended into an outcome.

        Runs **inside the job's captured context**, which is why the failure is logged here rather than
        by the caller: a record written after the context was left would land under nothing, and the
        one place a failed job's detail is meant to be readable afterwards is the log.

        The blanket catch is the point rather than a shortcut: a job is arbitrary caller code, and an
        exception escaping it must cost that job and nothing else -- a queue that stopped on the first
        failure would strand every job behind it ([[appendices.task-queue#failure]]).

        **Returning normally is** :attr:`~rehuco_core.tasks.JobState.DONE`, stop request or not. A job
        that never looked was never stopped, and the work it did is finished; the request survives on
        :attr:`~rehuco_core.tasks.JobStatus.stop_requested`, where it describes what was asked without
        overwriting what happened.

        :param entry: the job being run.
        :param control: what it was handed.
        :returns: the state it ended in, and the failure text for a failed job.
        """
        try:
            entry.job.run(control)
        except JobCancelled:
            LOG.debug("Task cancelled: %s", entry.label)
            return JobState.CANCELLED, None
        except JobPaused:
            LOG.debug("Task paused: %s", entry.label)
            return JobState.PAUSED, None
        except Exception as error:  # pylint: disable=broad-exception-caught
            LOG.error("Task failed: %s", entry.label, exc_info=error)
            return JobState.FAILED, f"{type(error).__name__}: {error}"
        return JobState.DONE, None

    # endregion
