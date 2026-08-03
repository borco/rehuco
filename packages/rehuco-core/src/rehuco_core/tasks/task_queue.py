"""The app-wide queue of slow work: one job at a time, in an order the user can change
([[architecture-design#components]], [[appendices.task-queue]]).

GUI-free and Qt-free on purpose ([[appendices.task-queue#home]]): the queue's contract is written in
rehuco's own specification, a headless node is specified to run jobs too, and the observation seam
(:class:`~rehuco_core.tasks.TaskQueueListener`) is all a dock needs to render one.
"""

import logging
from collections.abc import Callable
from contextvars import Context, copy_context
from dataclasses import dataclass
from threading import Condition, RLock, Thread
from typing import Final, override

from .task_job import FINISHED_JOB_STATES, JobCancelled, JobControl, JobState, JobStatus, TaskJob
from .task_queue_listener import TaskQueueListener

LOG: Final = logging.getLogger(__name__)

DEFAULT_SHUTDOWN_TIMEOUT: Final = 5.0
"""How long :meth:`TaskQueue.shutdown` waits for the running job to notice, in seconds.

Long enough for a cooperative job to reach its next checkpoint and unwind, short enough that quitting
the app never feels hung. A job that ignores its checkpoints outlives this, which is why the worker is
a daemon thread as well -- the wait is a courtesy, not the thing that makes the process exit."""


class TaskQueue:
    """Runs jobs one at a time, and lets them be paused, reordered and cancelled while they wait.

    **Serial by construction, not by configuration** ([[appendices.task-queue#serial]]). There is one
    worker thread and there is no number to raise: the specified behavior is that multi-selecting ten
    resources serializes the work rather than running it all at once, because ten hashes against one
    disk are slower than one, not faster. A future parallel lane over a genuinely different resource
    would be a second queue, never a count on this one.

    **Nothing is remembered across a restart** ([[appendices.task-queue#lifetime]]). A job is an object
    the caller built, closing over whatever it needs; quitting drops the queue. Persisting it would
    mean every job becoming a registered kind plus serializable arguments -- a constraint on every
    client the queue will ever have, bought for the ability to resume one interrupted sweep.

    Every observable change reaches :class:`~rehuco_core.tasks.TaskQueueListener`, called under this
    queue's own lock so that a row model is never told about a change out of order. The lock is
    re-entrant, so a listener that calls back in (a dock cancelling a job as it sees it fail) is safe;
    a listener that blocks is not, and the protocol says so.
    """

    # Nine, and each is a distinct fact about one job: its identity and label, the job itself, the
    # context it was enqueued in, where it has got to, what it reported, why it failed, and whether a
    # stop was asked for. Folding any pair together would be a tuple pretending to be a concept.
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
        state: JobState = JobState.QUEUED
        done: int = 0
        total: int | None = None
        error: str | None = None
        cancelled: bool = False

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
            )

    class Control(JobControl):
        """The engine's face to the one running job -- :class:`~rehuco_core.tasks.JobControl`, realized.

        Built per job, from inside :class:`TaskQueue`'s own body, which is why it takes its
        collaborators as plain arguments rather than reaching for the queue: a nested class cannot read
        an outer class's private members (name mangling resolves them against the *inner* class), while
        a callable written in the outer body closes over them correctly.

        :param condition: the queue's condition; guards ``entry`` and is what a parked job waits on.
        :param entry: the job this control belongs to.
        :param paused: reads whether the queue is paused right now.
        :param notify: tells the queue's listeners that ``entry`` changed; called with the condition
            already held.
        """

        def __init__(
            self,
            condition: Condition,
            entry: TaskQueue.Entry,
            paused: Callable[[], bool],
            notify: Callable[[TaskQueue.Entry], None],
        ) -> None:
            self.__condition: Final = condition
            self.__entry: Final = entry
            self.__paused: Final = paused
            self.__notify: Final = notify

        @override
        def checkpoint(self) -> None:
            """Stop if this job was cancelled, and park while the queue is paused.

            Waiting on the condition rather than on a "paused" event is what makes a *parked* job
            cancellable: the wait ends on either fact changing, so a cancel arriving while the whole
            queue is paused is obeyed then and there rather than at the next resume -- which is what
            lets shutdown reach a paused job at all.

            :raises JobCancelled: when this job was cancelled, before or during the pause.
            """
            with self.__condition:
                if self.__entry.cancelled:
                    raise JobCancelled(self.__entry.label)
                if not self.__paused():
                    return
                self.__entry.state = JobState.PAUSED
                self.__notify(self.__entry)
                while self.__paused() and not self.__entry.cancelled:
                    self.__condition.wait()
                if self.__entry.cancelled:
                    raise JobCancelled(self.__entry.label)
                self.__entry.state = JobState.RUNNING
                self.__notify(self.__entry)

        @override
        def report(self, done: int, total: int | None = None) -> None:
            """Record how far this job has got and tell the listeners.

            :param done: units finished so far.
            :param total: units expected, or ``None`` for indeterminate.
            """
            with self.__condition:
                self.__entry.done = done
                self.__entry.total = total
                self.__notify(self.__entry)

        @property
        @override
        def cancelled(self) -> bool:
            """Whether a stop has been asked for, without unwinding on it."""
            with self.__condition:
                return self.__entry.cancelled

    def __init__(self) -> None:
        self.__condition: Final = Condition(RLock())
        self.__entries: list[TaskQueue.Entry] = []
        self.__listeners: list[TaskQueueListener] = []
        self.__next_serial = 0
        self.__paused = False
        self.__stopping = False
        self.__worker: Thread | None = None

    # region observation

    def add_listener(self, listener: TaskQueueListener) -> None:
        """Start telling ``listener`` about changes.

        Nothing is replayed: a listener attaching to a queue that already holds jobs seeds itself from
        :meth:`jobs` and is told about everything after that. Deliberately not the log bridge's
        replay-on-attach, because a queue's history *is* its current state -- there is no record of a
        job that was cleared, and none is owed.

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
        """Whether the queue is paused.

        ``True`` says no *further* job will be started and the running one will park at its next
        checkpoint -- not that anything has stopped yet.
        """
        with self.__condition:
            return self.__paused

    # endregion

    # region the queue

    def enqueue(self, job: TaskJob) -> int:
        """Accept ``job``, starting the worker thread if this is the first one.

        The job's :attr:`~rehuco_core.tasks.TaskJob.label` is read here, once, and carried on every
        status from now on.

        **The caller's context is captured here and the job runs inside it**
        ([[appendices.task-queue#scopes]]): a thread does not inherit a context, so a job enqueued
        inside a document's log scope would otherwise log under nothing while working on that
        document. ``copy_context`` is generic -- this knows nothing about what is in the context, only
        that the caller's belongs to the work.

        :param job: the work to run.
        :returns: the job's serial, for :meth:`cancel` and :meth:`move`.
        :raises RuntimeError: if the queue has been shut down; shutdown is terminal, and silently
            accepting work that will never run would be worse than refusing it.
        """
        with self.__condition:
            if self.__stopping:
                raise RuntimeError("This task queue has been shut down.")
            entry = TaskQueue.Entry(serial=self.__next_serial, job=job, label=job.label, context=copy_context())
            self.__next_serial += 1
            self.__entries.append(entry)
            index = len(self.__entries) - 1
            status = entry.status()
            self.__ensure_worker()
            self.__notify(lambda listener: listener.job_enqueued(status, index))
            self.__condition.notify_all()
            return entry.serial

    def pause(self) -> None:
        """Stop starting jobs, and park the running one at its next checkpoint.

        Idempotent. A job that never checkpoints runs to completion regardless -- pausing is a request
        the jobs honor, exactly as cancelling is.
        """
        self.__set_paused(True)

    def resume(self) -> None:
        """Start jobs again, and release a parked one.

        Idempotent.
        """
        self.__set_paused(False)

    def cancel(self, serial: int) -> None:
        """Ask the job with ``serial`` to stop.

        A queued job is cancelled outright and never runs. The running one has the request recorded
        and stops at its next :meth:`~rehuco_core.tasks.JobControl.checkpoint` -- including when it is
        parked, since a parked job is waiting on this same condition. A job that never checkpoints
        cannot be interrupted, and is still reported
        :attr:`~rehuco_core.tasks.JobState.CANCELLED` when it returns: a cancelled job must never read
        as done. A finished job, and a serial belonging to nothing, are both no-ops.

        :param serial: which job, as returned by :meth:`enqueue`.
        """
        with self.__condition:
            entry = self.__entry(serial)
            if entry is None or entry.state in FINISHED_JOB_STATES:
                return
            entry.cancelled = True
            if entry.state is JobState.QUEUED:
                entry.state = JobState.CANCELLED
                self.__notify_updated(entry)
            self.__condition.notify_all()

    def move(self, serial: int, index: int) -> None:
        """Move a queued job to position ``index``.

        Only a :attr:`~rehuco_core.tasks.JobState.QUEUED` job moves: a running job cannot be made to
        have started later, and a finished one has no position left to matter. ``index`` is clamped
        into the run of queued jobs, so a job can never be placed ahead of the one already running --
        that would promise an order the queue cannot deliver.

        :param serial: which job, as returned by :meth:`enqueue`.
        :param index: where to put it, in the queue's own order; clamped as above.
        """
        with self.__condition:
            entry = self.__entry(serial)
            if entry is None or entry.state is not JobState.QUEUED:
                return
            queued = [position for position, held in enumerate(self.__entries) if held.state is JobState.QUEUED]
            target = min(max(index, queued[0]), queued[-1])
            if target == self.__entries.index(entry):
                return
            self.__entries.remove(entry)
            self.__entries.insert(target, entry)
            order = tuple(held.serial for held in self.__entries)
            self.__notify(lambda listener: listener.jobs_reordered(order))

    def clear_finished(self) -> None:
        """Drop every done, failed and cancelled job.

        What a queued or running job holds is untouched, so this is safe to offer while work is in
        flight.
        """
        with self.__condition:
            removed = tuple(entry.serial for entry in self.__entries if entry.state in FINISHED_JOB_STATES)
            if not removed:
                return
            self.__entries = [entry for entry in self.__entries if entry.state not in FINISHED_JOB_STATES]
            self.__notify(lambda listener: listener.jobs_removed(removed))

    def shutdown(self, timeout: float = DEFAULT_SHUTDOWN_TIMEOUT) -> None:
        """Cancel everything and wait for the worker to stop ([[appendices.task-queue#teardown]]).

        Releases a pause first, so a parked job sees its cancellation rather than waiting for a resume
        that is never coming. Terminal: a queue that has been shut down accepts no more work.

        The worker is a **daemon** thread, so a job that ignores its checkpoints can never hold the
        process open past this -- the wait is what gives a cooperative job the chance to close what it
        opened, and a job that outlives it is logged rather than waited on forever.

        :param timeout: how long to wait for the running job to unwind, in seconds.
        """
        with self.__condition:
            self.__stopping = True
            was_paused = self.__paused
            self.__paused = False
            for entry in self.__entries:
                if entry.state in FINISHED_JOB_STATES:
                    continue
                entry.cancelled = True
                if entry.state is JobState.QUEUED:
                    entry.state = JobState.CANCELLED
                    self.__notify_updated(entry)
            if was_paused:
                self.__notify(lambda listener: listener.queue_paused_changed(False))
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
        :returns: the entry, or ``None`` when no job has that serial (it was cleared, or never
            existed).
        """
        for entry in self.__entries:
            if entry.serial == serial:
                return entry
        return None

    def __set_paused(self, paused: bool) -> None:
        """Pause or resume, telling the listeners only when it actually changed.

        :param paused: the state to move to.
        """
        with self.__condition:
            if self.__paused == paused:
                return
            self.__paused = paused
            self.__notify(lambda listener: listener.queue_paused_changed(paused))
            self.__condition.notify_all()

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
        once the last has returned.
        """
        while True:
            with self.__condition:
                entry = self.__next_queued()
                while not self.__stopping and (self.__paused or entry is None):
                    self.__condition.wait()
                    entry = self.__next_queued()
                if self.__stopping or entry is None:
                    return
                entry.state = JobState.RUNNING
                self.__notify_updated(entry)
                control = TaskQueue.Control(self.__condition, entry, lambda: self.__paused, self.__notify_updated)
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

        :param entry: the job to run.
        :param control: what it is handed.
        """
        state, error = entry.context.run(self.__invoke, entry, control)
        with self.__condition:
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

        :param entry: the job being run.
        :param control: what it was handed.
        :returns: the terminal state, and the failure text for a failed job.
        """
        try:
            entry.job.run(control)
        except JobCancelled:
            LOG.debug("Task cancelled: %s", entry.label)
            return JobState.CANCELLED, None
        except Exception as error:  # pylint: disable=broad-exception-caught
            LOG.error("Task failed: %s", entry.label, exc_info=error)
            return JobState.FAILED, f"{type(error).__name__}: {error}"
        if entry.cancelled:
            # asked to stop and returned anyway -- a job that never reaches a checkpoint, or one that
            # tidied up and returned instead of unwinding. Either way it is not a job that ran to
            # completion, and reporting it as done would say it did.
            return JobState.CANCELLED, None
        return JobState.DONE, None

    # endregion
