"""The app-wide queue of slow work: one job at a time, in an order the user can change
([[architecture-design#components]], [[appendices.task-queue]]).

GUI-free and Qt-free on purpose ([[appendices.task-queue#home]]): the queue's contract is written in
rehuco's own specification, a headless node is specified to run jobs too, and the observation seam
(:class:`~rehuco_core.tasks.TaskQueueListener`) is all a dock needs to render one.
"""

# One class, one lock, one worker loop: scheduling, stopping, ordering and persistence are the same
# invariants seen from four sides, and every method below reads or writes the same entry list under the
# same condition. Splitting it would put those invariants in two files that have to be read together.
# pylint: disable=too-many-lines

import logging
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from contextvars import Context, copy_context
from dataclasses import dataclass
from pathlib import Path
from threading import Condition, RLock, Thread
from typing import Any, Final

from .persistable_task_job import PersistableTaskJob, TaskQueueItem
from .task_job import (
    FINISHED_JOB_STATES,
    JobCancelled,
    JobPaused,
    JobState,
    JobStatus,
    StopRequest,
    TaskJob,
)
from .task_job_registry import TaskJobRegistry
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

RESTORED_UNFINISHED_STATES: Final = frozenset({JobState.QUEUED, JobState.PAUSED})
"""The states unfinished work may be brought back in ([[appendices.task-queue#lifetime]]).

Which of the two :meth:`TaskQueue.restore` is asked for is a setting a surface owns -- come back held,
or come back running -- and nothing else is a legal answer: a restored job has neither run nor been
stopped in this session, so every other state would be a claim about a session that is over."""


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

    @dataclass(frozen=True)
    class Captured:
        """What a persistable job last handed over, and how far it had got when it did.

        The three are taken together and kept together, because a state and a progress bar that
        disagree describe two different moments of one job: restoring a bar that has run ahead of the
        state behind it would show work that is about to be done again.

        :param state: the job's own :meth:`~rehuco_core.tasks.PersistableTaskJob.capture_state`.
        :param done: units finished as of that capture.
        :param total: units expected as of that capture, or ``None``.
        """

        state: dict[str, Any]
        done: int
        total: int | None

    # Sixteen, and each is a distinct fact about one job: its identity and label, the job itself, the
    # context it was enqueued in, what it declared about itself, where it has got to, what it
    # reported, why it failed, what it was asked, and what it last gave the queue to write down.
    # `resume_requested` alone stays off the status: it exists for one gap -- a pause taken back too
    # late to stop the unwind -- and its only observable effect is the state that outcome is recorded
    # as.
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
        progress_unit: str = ""
        persistable: bool = False
        captured: TaskQueue.Captured | None = None
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
                progress_unit=self.progress_unit,
                error=self.error,
                stop_requested=self.stop_requested,
                source=self.source,
                safely_interruptible=self.safely_interruptible,
                resumes_where_it_stopped=self.resumes_where_it_stopped,
                persistable=self.persistable,
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
        :attr:`~rehuco_core.tasks.TaskJob.safely_interruptible`,
        :attr:`~rehuco_core.tasks.TaskJob.resumes_where_it_stopped` and
        :attr:`~rehuco_core.tasks.TaskJob.progress_unit` -- are read here and carried on
        every status from now on. All but one are read *only* here, because each answers a question
        about the row a reader is looking at, and an answer that changed while the job ran would
        rewrite it. ``source`` is the exception: it names where the work is rather than describing it,
        and :meth:`resync_sources` re-reads it when a rename has moved that place (#241).
        Whether it is a :class:`~rehuco_core.tasks.PersistableTaskJob` is settled here too, and a job
        that is one is asked for its state now, so that a queue written while it runs still holds it.

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
            entry = self.__accept(job)
            self.__condition.notify_all()
            return entry.serial

    def resync_sources(self) -> None:
        """Re-read every job's :attr:`~rehuco_core.tasks.TaskJob.source` and announce the ones that
        moved (#241).

        **The one declaration that is not read once.** :attr:`~rehuco_core.tasks.TaskJob.label` and the
        rest are read at enqueue and never again, because an answer that changed while the job ran would
        rewrite a row a reader is looking at. ``source`` is different in kind: it is not a claim about
        the job, it is *where the work is*, and a rename moves that while the job runs. A row still
        naming the old path would send a reader to a folder that no longer exists -- which is exactly
        the confusion a rename-aware job exists to spare them.

        Called by whoever knows a rename happened, not discovered here: the queue never learns what a
        :class:`~rehuco_core.RenameCoordinator` is, and the app wires the coordinator's own
        notification to this. Every entry is re-read, finished ones included, since a done job's row
        names a path a reader may still click.

        Only the entries whose source actually changed are announced, so a rename touching nothing this
        queue holds is silent rather than a burst of identical updates.
        """
        with self.__condition:
            for entry in self.__entries:
                source = entry.job.source
                if source == entry.source:
                    continue
                entry.source = source
                self.__notify_updated(entry)

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

        What a persistable job would be written down as is re-read here, so that a queue saved
        afterwards never restores it to the very cursor Retry has just thrown away.

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
                self.__capture(entry)
                self.__notify_updated(entry)
            self.__condition.notify_all()

    # endregion

    # region persistence

    def serialize(self) -> tuple[TaskQueueItem, ...]:
        """Write down every job that can be written down ([[appendices.task-queue#lifetime]]).

        **Everything persistable, including the finished ones.** Since jobs leave only when removed
        ([[appendices.task-queue#kept]]), dropping the done, failed and cancelled ones at quit would be
        exactly the implicit removal that rule exists to prevent -- and it would take the retryable
        failures with it. A job that is not a :class:`~rehuco_core.tasks.PersistableTaskJob` is
        skipped; its row said so all along, through
        :attr:`~rehuco_core.tasks.JobStatus.persistable`.

        **The running job is written from what it last gave the queue**, never asked now:
        :meth:`~rehuco_core.tasks.PersistableTaskJob.capture_state` is specified as called only when
        the job is not running, so a queue written mid-run holds the running job as of its last safe
        moment rather than dropping it. The specified exit sequence -- pause, wait, save, shut down
        ([[appendices.task-queue#teardown]]) -- has nothing running by the time it saves, and it is
        the *structural* writes during a run that this is for.

        :returns: one item per persistable job, in the queue's own order.
        """
        with self.__condition:
            items: list[TaskQueueItem] = []
            for entry in self.__entries:
                if not entry.persistable:
                    continue
                if entry.state is not JobState.RUNNING:
                    self.__capture(entry)
                if entry.captured is None:
                    continue
                items.append(self.__item(entry, entry.captured))
            return tuple(items)

    def restore(
        self,
        items: Iterable[TaskQueueItem],
        registry: TaskJobRegistry,
        *,
        unfinished_state: JobState = JobState.PAUSED,
    ) -> tuple[int, ...]:
        """Bring a saved queue back, in the order it was saved in.

        **Unfinished jobs come back held and finished ones keep their state**, so a restarted app comes
        up with nothing running while a job added afterwards starts immediately -- eligibility is
        per-job, and nothing restored is eligible. ``unfinished_state`` is the seam a *resume tasks on
        restart* setting turns; filtering *which* items come back at all is the caller's, which is why
        this takes a list it hands over rather than a file it opens.

        **An item this build cannot use is dropped, never fatal**: an unknown kind, one whose job
        refuses the state, or one that is not shaped like an item at all. A queue file from a newer
        build, or one naming a feature that has been removed, must not stop the app starting, so the
        loss is logged with a count and the rest of the queue comes back.

        :param items: the saved items, oldest position first.
        :param registry: what turns each item's kind back into a job.
        :param unfinished_state: the state to revive unfinished work in; one of
            :data:`RESTORED_UNFINISHED_STATES`.
        :returns: the serial of each restored job, in order.
        :raises ValueError: if ``unfinished_state`` is not a state work can be restored in.
        :raises RuntimeError: if the queue already holds jobs, or has been shut down. This is a startup
            operation -- making it merge would invite a question about identity and order that nobody
            has asked.
        """
        if unfinished_state not in RESTORED_UNFINISHED_STATES:
            raise ValueError(f"Restored work cannot be revived in {unfinished_state}.")
        with self.__condition:
            if self.__stopping:
                raise RuntimeError("This task queue has been shut down.")
            if self.__entries:
                raise RuntimeError("This task queue already holds jobs; restore is a startup operation.")
            serials: list[int] = []
            dropped = 0
            for item in items:
                entry = self.__revive(item, registry, unfinished_state)
                if entry is None:
                    dropped += 1
                    continue
                serials.append(entry.serial)
            if dropped:
                LOG.warning("%d saved task(s) could not be restored by this build and were dropped.", dropped)
            self.__condition.notify_all()
            return tuple(serials)

    # endregion

    # region waiting and teardown

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

    # six, because a restored job is accepted with everything an earlier session left it holding; the
    # alternative is a second acceptance path that would have to keep the first one's invariants.
    # pylint: disable-next=too-many-arguments
    def __accept(
        self,
        job: TaskJob,
        *,
        label: str | None = None,
        state: JobState = JobState.QUEUED,
        done: int = 0,
        total: int | None = None,
        error: str | None = None,
    ) -> TaskQueue.Entry:
        """Take a job into the queue and tell the listeners, whether it is new or restored.

        Written once for both, because everything an enqueue does -- read the declarations, mint a
        serial, capture the caller's context, start the worker, announce the row -- a restore does too.
        The only difference is where the job starts from, which is what the keyword arguments carry.

        Called with the condition held.

        :param job: the work to hold.
        :param label: what to call it, for a restored job whose row was named in an earlier session;
            ``None`` to ask the job, which is what a new one does.
        :param state: the state to hold it in.
        :param done: units already finished.
        :param total: units expected, or ``None``.
        :param error: why it failed, for a job restored as failed.
        :returns: the entry now in the queue.
        :raises RuntimeError: if the queue has been shut down.
        """
        if self.__stopping:
            raise RuntimeError("This task queue has been shut down.")
        entry = TaskQueue.Entry(
            serial=self.__next_serial,
            job=job,
            label=label if label else job.label,
            context=copy_context(),
            source=job.source,
            safely_interruptible=job.safely_interruptible,
            resumes_where_it_stopped=job.resumes_where_it_stopped,
            progress_unit=job.progress_unit,
            persistable=isinstance(job, PersistableTaskJob),
            state=state,
            done=done,
            total=total,
            error=error,
        )
        self.__next_serial += 1
        self.__capture(entry)
        with self.__watching_paused():
            self.__entries.append(entry)
            index = len(self.__entries) - 1
            status = entry.status()
            self.__ensure_worker()
            self.__notify(lambda listener: listener.job_enqueued(status, index))
        return entry

    def __revive(
        self,
        item: TaskQueueItem,
        registry: TaskJobRegistry,
        unfinished_state: JobState,
    ) -> TaskQueue.Entry | None:
        """Turn one saved item back into a job the queue holds.

        Reads the item defensively rather than trusting it: what arrives here came off disk, possibly
        from another build and possibly from an editor. Anything unreadable is one dropped row, which
        :meth:`restore` counts and logs.

        Called with the condition held.

        :param item: the saved item.
        :param registry: what turns its kind into a job.
        :param unfinished_state: the state to revive unfinished work in.
        :returns: the entry, or ``None`` when this build cannot make one.
        """
        kind = item.get("kind")
        state = item.get("state")
        if not isinstance(kind, str) or not isinstance(state, dict):
            return None
        job = registry.create(kind, state)
        if job is None:
            return None
        saved = self.__saved_state(item.get("job_state"))
        if saved is None:
            return None
        restored = saved if saved in FINISHED_JOB_STATES else unfinished_state
        error = item.get("error") if saved is JobState.FAILED else None
        done, total = self.__saved_progress(item, job)
        label = item.get("label")
        return self.__accept(
            job,
            label=label if isinstance(label, str) else None,
            state=restored,
            done=done,
            total=total,
            error=error if isinstance(error, str) else None,
        )

    @staticmethod
    def __saved_state(value: object) -> JobState | None:
        """Read the state a saved item was written in.

        :param value: whatever was under ``job_state``.
        :returns: the state, or ``None`` when it names none -- a queue file from a build whose states
            were not these.
        """
        try:
            return JobState(value)
        except ValueError:
            return None

    @staticmethod
    def __saved_progress(item: TaskQueueItem, job: TaskJob) -> tuple[int, int | None]:
        """Read how far a saved item had got, if it is entitled to say.

        **The job's declaration wins over the file**: progress is restored only for a job that says it
        resumes where it stopped, because only such a job genuinely is as far along as its bar. One
        that starts over comes back at zero however far the file says it got.

        :param item: the saved item.
        :param job: the job just rebuilt from it.
        :returns: the units done and the units expected.
        """
        if not job.resumes_where_it_stopped:
            return 0, None
        done = item.get("done")
        total = item.get("total")
        return done if isinstance(done, int) else 0, total if isinstance(total, int) else None

    def __capture(self, entry: TaskQueue.Entry) -> None:
        """Ask a persistable job for its state, and keep it with the progress of the same moment.

        Called only where the job is demonstrably not running -- at enqueue, at restore, on retry, and
        from :meth:`serialize` for the jobs that are not the running one -- which is the whole of the
        *called only when the job is not running* contract.

        A job that raises rather than answering keeps whatever was captured before it: the queue is
        still worth writing, and a state it could not produce is not one worth inventing.

        Called with the condition held.

        :param entry: the job to ask.
        """
        if not entry.persistable:
            return
        try:
            state = entry.job.capture_state()  # pyright: ignore[reportAttributeAccessIssue]
        except Exception:  # pylint: disable=broad-exception-caught
            LOG.exception("Task %r could not say what it would need to carry on; its last state stands.", entry.label)
            return
        entry.captured = TaskQueue.Captured(state=state, done=entry.done, total=entry.total)

    @staticmethod
    def __item(entry: TaskQueue.Entry, captured: TaskQueue.Captured) -> TaskQueueItem:
        """Write one job down.

        :param entry: the job to write.
        :param captured: what it last handed over.
        :returns: the saved item.
        """
        item: TaskQueueItem = {
            "kind": entry.job.kind,  # pyright: ignore[reportAttributeAccessIssue]
            "label": entry.label,
            "job_state": entry.state.value,
            "state": captured.state,
            "error": entry.error,
        }
        if entry.resumes_where_it_stopped:
            item["done"] = captured.done
            item["total"] = captured.total
        return item

    def __validated(self, entry: TaskQueue.Entry) -> bool:
        """Ask a job whether it can still be started, just before starting it.

        **Before every start, not only after a restore**, so one rule covers the restored resource that
        is gone and the one deleted while its job waited in the queue. A job that objects is failed
        with its own sentence rather than given a state of its own -- a failure is kept and retryable,
        so fixing the cause and pressing Retry is the recovery, and no surface has to learn a seventh
        state.

        A job that raises out of ``validate`` is failed the same way: it has said it cannot start, and
        how it said so is not worth a second path ([[appendices.task-queue#failure]]).

        Called on the worker thread with the condition held.

        :param entry: the job about to run.
        :returns: ``True`` when it may start; ``False`` when it has been failed instead.
        """
        if not entry.persistable:
            return True
        try:
            reason = entry.job.validate()  # pyright: ignore[reportAttributeAccessIssue]
        except Exception as error:  # pylint: disable=broad-exception-caught
            LOG.error("Task could not be checked before starting: %s", entry.label, exc_info=error)
            reason = f"{type(error).__name__}: {error}"
        if reason is None:
            return True
        LOG.warning("Task refused to start: %s -- %s", entry.label, reason)
        with self.__watching_paused():
            entry.state = JobState.FAILED
            entry.error = reason
            self.__notify_updated(entry)
        return False

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
                if not self.__validated(entry):
                    self.__condition.notify_all()
                    continue
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
