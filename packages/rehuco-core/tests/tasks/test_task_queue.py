"""Tests for the serial task-queue engine -- ordering, pause, cancellation, failure and teardown (#201),
and per-job pause, removal and retry (#237).

Every job below is driven by `threading.Event`s rather than by sleeping, so a test asserts on a state
the worker has demonstrably reached instead of on one it has probably reached by now. The one place
polling is unavoidable is observing a transition the worker makes on its own -- that is what the
``settles`` fixture is for, and it waits on a condition rather than for a duration.

**No test asserts on a cursor.** Whether a job carries on or starts over is observed through what it
did -- the values its ``run`` saw on each entry -- because the engine has no access to a cursor and
neither should its tests.
"""

# The engine's surface is small but its behaviors are many, and every one of them below is a distinct
# fact about it. Splitting the file would put ordering, pausing and teardown in three modules that
# share the same fakes and the same three fixtures.
# pylint: disable=too-many-lines

import logging
from collections.abc import Callable, Iterator, Sequence
from contextvars import ContextVar
from pathlib import Path
from threading import Event, active_count, get_ident
from time import monotonic, sleep
from typing import Final

import pytest
from pytest import fixture
from rehuco_core import (
    PROGRESS_UNIT_BYTES,
    PROGRESS_UNIT_RESOURCES,
    JobCancelled,
    JobControl,
    JobPaused,
    JobState,
    JobStatus,
    StopRequest,
    TaskJobBase,
    TaskQueue,
)

TIMEOUT: Final = 5.0
"""How long a test waits for the worker before calling it a failure, in seconds.

Generous on purpose: it is a deadlock detector, not a measurement. Every wait below ends the moment
the condition holds, so a passing run never spends this."""


# region Sample classes


# a shared base for the fakes below, so ``run`` is deliberately left to each of them
# pylint: disable-next=abstract-method
class SampleJob(TaskJobBase):
    """What every fake below shares: the real stop protocol, so these tests exercise the shipped one.

    Deliberately :class:`~rehuco_core.TaskJobBase` rather than a hand-written stand-in -- the engine's
    stop behavior is now half the job's, and a fake that reimplemented it would be testing the fake.

    :param label: the job's label.
    """

    def __init__(self, label: str) -> None:
        super().__init__()
        self.label = label


class RecordingJob(SampleJob):
    """A job that runs to completion, checkpointing and reporting once per unit.

    :param label: the job's label.
    :param order: shared list each job appends its label to as it finishes, which is how the tests
        read back the order work actually ran in.
    :param units: how many checkpoints and progress reports to make.
    """

    def __init__(self, label: str, order: list[str] | None = None, units: int = 1) -> None:
        super().__init__(label)
        self.__order: Final = order
        self.__units: Final = units

    def run(self, control: JobControl) -> None:
        """Report progress once per unit, checkpointing before each.

        :param control: the engine's face to this job.
        """
        for unit in range(self.__units):
            self.checkpoint()
            control.report(unit + 1, self.__units)
        if self.__order is not None:
            self.__order.append(self.label)


class MovableSourceJob(SampleJob):
    """A job whose ``source`` the test can move, standing in for one that follows a rename (#241).

    A plain attribute rather than a real :class:`~rehuco_core.ResourceLocation`: what the queue is
    tested on is that it *re-reads* the declaration, not how a particular job decided to answer it.

    :param label: the job's label.
    :param source: where it starts.
    """

    def __init__(self, label: str, source: Path) -> None:
        super().__init__(label)
        self.source = source

    def run(self, control: JobControl) -> None:
        """Finish immediately.

        :param control: the engine's face to this job.
        """
        del control


class GatedJob(SampleJob):
    """A job the test holds mid-run: it announces that it started, waits to be let go, then checkpoints.

    The shape every "while a job is running..." test needs -- the queue is demonstrably busy from the
    moment :attr:`entered` is set until :attr:`release` is set, with a checkpoint waiting on the far
    side for a pause or a cancellation to be observed at.

    **A test that holds one must let it go before it ends**, cancelled or released: an abandoned one
    sits in ``release.wait`` for the whole deadlock timeout, and the fixture's shutdown waits for it.

    :param label: the job's label.
    """

    def __init__(self, label: str = "gated") -> None:
        super().__init__(label)
        self.entered: Final = Event()
        self.release: Final = Event()
        self.finished = False

    def run(self, control: JobControl) -> None:
        """Announce, wait for the test, then yield to the engine.

        :param control: the engine's face to this job.
        """
        self.entered.set()
        self.release.wait(TIMEOUT)
        self.checkpoint()
        self.finished = True


class CheckpointingJob(SampleJob):
    """A job that checkpoints in a loop until the test lets it stop -- somewhere a pause can land.

    Unlike :class:`GatedJob`, this one is *inside* its checkpoint repeatedly, so pausing it unwinds it
    without the test having to time anything.

    :param label: the job's label.
    """

    def __init__(self, label: str = "looping") -> None:
        super().__init__(label)
        self.entered: Final = Event()
        self.release: Final = Event()
        self.finished = False

    def run(self, control: JobControl) -> None:
        """Checkpoint until released, then finish.

        :param control: the engine's face to this job.
        """
        self.entered.set()
        while not self.release.is_set():
            self.checkpoint()
            sleep(0.001)
        self.checkpoint()
        self.finished = True


class CursorJob(SampleJob):
    """A job that counts units and, if it says it does, picks up where it left off when re-entered.

    The A/B the whole cursor design rests on: **one class, one flag**, so a test can show that the
    same engine produces *continues* and *starts over* purely from what the job declares. What it
    keeps is a plain counter, and nothing outside this class ever reads it -- the tests assert on
    :attr:`entered_at`, which is what each ``run`` was handed, not on the counter itself.

    :param label: the job's label.
    :param units: how many units of work to do in all.
    :param hold_after: how many units to do before announcing :attr:`reached` and waiting on
        :attr:`release`, so a test can pause it at a known point. Happens once per job.
    :param resumes: what to declare as
        :attr:`~rehuco_core.TaskJob.resumes_where_it_stopped`, and whether to honor it.
    """

    def __init__(self, label: str = "cursor", units: int = 4, hold_after: int = 2, resumes: bool = True) -> None:
        super().__init__(label)
        self.resumes_where_it_stopped = resumes
        self.__units: Final = units
        self.__hold_after: Final = hold_after
        self.__cursor = 0
        self.entered_at: Final[list[int]] = []
        self.reached: Final = Event()
        self.release: Final = Event()

    def reset(self) -> None:
        """Throw the counter away, so the next run starts from the beginning."""
        super().reset()
        self.__cursor = 0

    def run(self, control: JobControl) -> None:
        """Count to :attr:`units`, from the counter or from zero, pausing once at ``hold_after``.

        :param control: the engine's face to this job.
        """
        if not self.resumes_where_it_stopped:
            self.__cursor = 0
        self.entered_at.append(self.__cursor)
        while self.__cursor < self.__units:
            self.checkpoint()
            self.__cursor += 1
            control.report(self.__cursor, self.__units)
            if self.__cursor == self.__hold_after and not self.reached.is_set():
                self.reached.set()
                self.release.wait(TIMEOUT)


# nine, because this fake is CursorJob with one more gate: the work, the point to pause it at, and a
# hold *inside* the unwind, which is the part no smaller fake can offer.
# pylint: disable-next=too-many-instance-attributes
class SlowUnwindJob(SampleJob):
    """A job whose unwind can be held open, so a test can land a call inside the raise-to-record gap.

    :class:`CursorJob` proves what pausing does; this one proves what happens to a call that arrives
    *while* a stop is in flight. It catches the raise, announces :attr:`unwinding`, waits on
    :attr:`finish_unwind`, and re-raises -- which is also the sanctioned shape for a real job that
    must tidy up before it stops, and is exactly the job whose cancel cannot be taken back.

    :param label: the job's label.
    :param stop: which stop this job expects to catch, so the test can hold either unwind open.
    :param units: how many units of work to do in all.
    :param hold_after: how many units to do before announcing :attr:`reached` and waiting on
        :attr:`proceed`, so the test can land its request at a known point.
    """

    resumes_where_it_stopped = True

    def __init__(
        self,
        label: str = "unwinding",
        stop: StopRequest = StopRequest.PAUSE,
        units: int = 4,
        hold_after: int = 2,
    ) -> None:
        super().__init__(label)
        self.__expected: Final = JobPaused if stop is StopRequest.PAUSE else JobCancelled
        self.__units: Final = units
        self.__hold_after: Final = hold_after
        self.__cursor = 0
        self.entered_at: Final[list[int]] = []
        self.reached: Final = Event()
        self.proceed: Final = Event()
        self.unwinding: Final = Event()
        self.finish_unwind: Final = Event()

    def run(self, control: JobControl) -> None:
        """Count units from the cursor, holding at ``hold_after`` and again inside the unwind.

        :param control: the engine's face to this job.
        """
        del control
        self.entered_at.append(self.__cursor)
        try:
            while self.__cursor < self.__units:
                if self.__cursor == self.__hold_after and not self.reached.is_set():
                    self.reached.set()
                    self.proceed.wait(TIMEOUT)
                self.checkpoint()
                self.__cursor += 1
        except self.__expected:
            self.unwinding.set()
            self.finish_unwind.wait(TIMEOUT)
            raise


class SelfPausingJob(SampleJob):
    """A job that raises the pause exception without ever having been asked -- a contract violation
    the engine must absorb without re-running it forever.

    :param label: the job's label.
    """

    def __init__(self, label: str = "unasked") -> None:
        super().__init__(label)
        self.runs = 0

    def run(self, control: JobControl) -> None:
        """Raise the pause exception, unasked.

        :param control: unused.
        :raises JobPaused: always.
        """
        del control
        self.runs += 1
        raise JobPaused(self.label)


class StubbornJob(SampleJob):
    """A job that never checkpoints -- what work the engine cannot interrupt looks like.

    :param label: the job's label.
    """

    def __init__(self, label: str = "stubborn") -> None:
        super().__init__(label)
        self.entered: Final = Event()
        self.release: Final = Event()
        self.saw_cancellation = False
        self.saw_pause = False

    def run(self, control: JobControl) -> None:
        """Announce, wait to be let go, and read both requests without unwinding on either.

        :param control: the engine's face to this job.
        """
        self.entered.set()
        self.release.wait(TIMEOUT)
        self.saw_cancellation = self.stop_requested is StopRequest.CANCEL
        self.saw_pause = self.stop_requested is StopRequest.PAUSE


class FailingJob(SampleJob):
    """A job that raises, so the queue's failure policy has something to record.

    :param label: the job's label.
    """

    def __init__(self, label: str = "failing") -> None:
        super().__init__(label)

    def run(self, control: JobControl) -> None:
        """Raise, having done nothing.

        :param control: unused; the failure happens before any work would.
        :raises RuntimeError: always.
        """
        del control
        raise RuntimeError("the disk went away")


class IndeterminateJob(SampleJob):
    """A job that reports progress it cannot total -- a scan that discovers as it walks.

    :param label: the job's label.
    """

    def __init__(self, label: str = "scanning") -> None:
        super().__init__(label)

    def run(self, control: JobControl) -> None:
        """Report a count with no total.

        :param control: the engine's face to this job.
        """
        control.report(3)


class DeclaringJob(SampleJob):
    """A job that declares everything about itself, so a status can be checked against it.

    :param label: the job's label.
    """

    source = Path("/library/Sculpting Series/info.rehu")
    safely_interruptible = False
    resumes_where_it_stopped = True
    progress_unit = PROGRESS_UNIT_BYTES

    def __init__(self, label: str = "declaring") -> None:
        super().__init__(label)

    def run(self, control: JobControl) -> None:
        """Do nothing at all.

        :param control: unused.
        """
        del control


class ScopeReadingJob(SampleJob):
    """A job that records what a `contextvars.ContextVar` held on the worker thread.

    :param label: the job's label.
    :param variable: the variable to read once the job is running.
    """

    def __init__(self, variable: ContextVar[str], label: str = "scoped") -> None:
        super().__init__(label)
        self.__variable: Final = variable
        self.seen: str | None = None
        self.done: Final = Event()

    def run(self, control: JobControl) -> None:
        """Read the variable and announce that it was read.

        :param control: unused.
        """
        del control
        self.seen = self.__variable.get()
        self.done.set()


class RaisingListener:
    """A listener that raises on every call -- the broken observer the engine must survive."""

    def job_enqueued(self, status: JobStatus, index: int) -> None:
        """Raise, as every method here does.

        :raises ValueError: always.
        """
        del status, index
        raise ValueError("a broken observer")

    def job_updated(self, status: JobStatus) -> None:
        """Raise, as every method here does.

        :raises ValueError: always.
        """
        del status
        raise ValueError("a broken observer")

    def jobs_reordered(self, serials: Sequence[int]) -> None:
        """Raise, as every method here does.

        :raises ValueError: always.
        """
        del serials
        raise ValueError("a broken observer")

    def jobs_removed(self, serials: Sequence[int]) -> None:
        """Raise, as every method here does.

        :raises ValueError: always.
        """
        del serials
        raise ValueError("a broken observer")

    def queue_paused_changed(self, paused: bool) -> None:
        """Raise, as every method here does.

        :raises ValueError: always.
        """
        del paused
        raise ValueError("a broken observer")


class RecordingListener:
    """A listener that keeps every call it was given, and the thread it was given it on.

    Hand-written rather than a mock because the assertions are about *which* calls arrived in *which*
    order, which a call-list on a real object states more plainly than a mock's assertions do.
    """

    def __init__(self) -> None:
        self.enqueued: Final[list[tuple[JobStatus, int]]] = []
        self.updated: Final[list[JobStatus]] = []
        self.reordered: Final[list[tuple[int, ...]]] = []
        self.removed: Final[list[tuple[int, ...]]] = []
        self.paused: Final[list[bool]] = []
        self.threads: Final[set[int]] = set()

    def job_enqueued(self, status: JobStatus, index: int) -> None:
        """Record an accepted job and where it landed."""
        self.threads.add(get_ident())
        self.enqueued.append((status, index))

    def job_updated(self, status: JobStatus) -> None:
        """Record a job's new state or progress."""
        self.threads.add(get_ident())
        self.updated.append(status)

    def jobs_reordered(self, serials: Sequence[int]) -> None:
        """Record the queue's new order."""
        self.threads.add(get_ident())
        self.reordered.append(tuple(serials))

    def jobs_removed(self, serials: Sequence[int]) -> None:
        """Record the serials dropped."""
        self.threads.add(get_ident())
        self.removed.append(tuple(serials))

    def queue_paused_changed(self, paused: bool) -> None:
        """Record the queue being paused or resumed."""
        self.threads.add(get_ident())
        self.paused.append(paused)

    def states_of(self, serial: int) -> list[JobState]:
        """Every state one job was reported in, in order, with repeats collapsed.

        :param serial: which job.
        :returns: the states it passed through.
        """
        states: list[JobState] = []
        for status in self.updated:
            if status.serial == serial and (not states or states[-1] is not status.state):
                states.append(status.state)
        return states


# endregion

# region Fixtures


@fixture(name="queue")
def queue_fixture() -> Iterator[TaskQueue]:
    """A queue that is always shut down, so no test can leave a worker thread behind.

    :returns: the queue under test.
    """
    queue = TaskQueue()
    yield queue
    queue.shutdown()


@fixture(name="listener")
def listener_fixture(queue: TaskQueue) -> RecordingListener:
    """A listener already attached to the queue under test.

    :param queue: the queue under test.
    :returns: the attached listener.
    """
    listener = RecordingListener()
    queue.add_listener(listener)
    return listener


@fixture(name="settles")
def settles_fixture() -> Callable[[Callable[[], bool]], None]:
    """A wait for something the worker does on its own, e.g. picking up the next job.

    Polls rather than blocks because the fact being waited for is a state the engine reached by
    itself, with no event of the test's to hang a signal on. It returns the instant the condition
    holds, so a passing test never spends the timeout.

    :returns: a callable that waits for its predicate, and fails the test if it never holds.
    """

    def settles(predicate: Callable[[], bool]) -> None:
        """Wait for ``predicate``.

        :param predicate: the condition to wait for.
        """
        deadline = monotonic() + TIMEOUT
        while monotonic() < deadline:
            if predicate():
                return
            sleep(0.001)
        raise AssertionError("the queue never reached the expected state")

    return settles


# endregion

# region Running jobs, in order


def test_jobs_run_one_at_a_time_in_the_order_they_were_enqueued(
    queue: TaskQueue, settles: Callable[[Callable[[], bool]], None]
) -> None:
    """The whole point of the component: multi-selecting serializes the work, it does not fan it out.

    **Test steps:**

    * enqueue three jobs that append their label as they finish
    * wait for all three to be done
    * verify they finished in the order they were enqueued
    """
    order: list[str] = []
    for label in ("first", "second", "third"):
        queue.enqueue(RecordingJob(label, order))

    settles(lambda: all(status.state is JobState.DONE for status in queue.jobs()))

    assert order == ["first", "second", "third"]


def test_a_second_job_waits_while_the_first_is_running(queue: TaskQueue) -> None:
    """One job in flight, never two -- asserted while the first is demonstrably still inside ``run``.

    **Test steps:**

    * enqueue a job that blocks once it has started, then a second job
    * wait until the first announces it started
    * verify the first is running and the second has not been started
    """
    gated = GatedJob()
    queue.enqueue(gated)
    second = queue.enqueue(RecordingJob("second"))

    assert gated.entered.wait(TIMEOUT)

    states = {status.serial: status.state for status in queue.jobs()}
    gated.release.set()
    assert states[second] is JobState.QUEUED
    assert JobState.RUNNING in states.values()


def test_a_job_is_reported_running_then_done(queue: TaskQueue, listener: RecordingListener) -> None:
    """A listener sees the whole life of a job, not only its outcome.

    **Test steps:**

    * enqueue one job
    * wait for it to finish
    * verify it was reported queued on arrival, then running, then done
    """
    serial = queue.enqueue(RecordingJob("only"))

    assert wait_for_state(listener, serial, JobState.DONE)

    assert listener.enqueued[0][0].state is JobState.QUEUED
    assert listener.enqueued[0][1] == 0
    assert listener.states_of(serial) == [JobState.RUNNING, JobState.DONE]


def test_progress_is_carried_through_to_the_listener(queue: TaskQueue, listener: RecordingListener) -> None:
    """What a job reports is what a view is told, unit for unit.

    **Test steps:**

    * enqueue a job that reports three units of three
    * wait for it to finish
    * verify the reported progress arrived in order, ending at three of three
    """
    serial = queue.enqueue(RecordingJob("counting", units=3))

    assert wait_for_state(listener, serial, JobState.DONE)

    progress = [(status.done, status.total) for status in listener.updated if status.state is JobState.RUNNING]
    assert progress == [(0, None), (1, 3), (2, 3), (3, 3)]


def test_a_job_that_cannot_total_its_work_reports_indeterminate(queue: TaskQueue, listener: RecordingListener) -> None:
    """A scan that discovers as it walks says so, rather than inventing a denominator.

    **Test steps:**

    * enqueue a job that reports a count with no total
    * wait for it to finish
    * verify the count arrived with ``None`` for the total
    """
    serial = queue.enqueue(IndeterminateJob())

    assert wait_for_state(listener, serial, JobState.DONE)

    assert (3, None) in [(status.done, status.total) for status in listener.updated]


def test_what_a_job_declares_about_itself_is_read_once_and_carried_on_its_status(
    queue: TaskQueue, listener: RecordingListener
) -> None:
    """A reader asks the row, never the job -- so what stopping one costs is answerable off a snapshot.

    **Test steps:**

    * enqueue a job declaring a source, that it is unsafe to interrupt, that it resumes, and a unit
    * change every declaration on the job object after the enqueue
    * verify the enqueue notification already carried all four
    * wait for it to finish and verify the final status still carries what was declared at enqueue
    """
    job = DeclaringJob()
    serial = queue.enqueue(job)
    job.source = None
    job.safely_interruptible = True
    job.resumes_where_it_stopped = False
    job.progress_unit = PROGRESS_UNIT_RESOURCES

    assert wait_for_state(listener, serial, JobState.DONE)

    accepted = listener.enqueued[0][0]
    assert (
        accepted.source,
        accepted.safely_interruptible,
        accepted.resumes_where_it_stopped,
        accepted.progress_unit,
    ) == (
        Path("/library/Sculpting Series/info.rehu"),
        False,
        True,
        PROGRESS_UNIT_BYTES,
    )
    assert queue.jobs()[0].resumes_where_it_stopped


def test_a_job_that_says_nothing_about_itself_is_interruptible_and_starts_over(
    queue: TaskQueue, listener: RecordingListener
) -> None:
    """The cautious defaults: no resource, nothing left behind, no promise to carry on, nothing to draw.

    **Test steps:**

    * enqueue a plain job that declares only a label
    * wait for it to finish
    * verify its status reports no source, safely interruptible, no resumption, and no progress unit
    """
    serial = queue.enqueue(RecordingJob("plain"))

    assert wait_for_state(listener, serial, JobState.DONE)

    status = queue.jobs()[0]
    assert (status.source, status.safely_interruptible, status.resumes_where_it_stopped, status.progress_unit) == (
        None,
        True,
        False,
        "",
    )


def test_the_scope_open_at_enqueue_is_the_one_the_job_runs_in(queue: TaskQueue) -> None:
    """A thread inherits no context, so the queue carries the caller's onto the worker itself.

    **Test steps:**

    * set a context variable, enqueue a job that reads it, then set the variable to something else
    * wait for the job to run
    * verify it saw the value that was set when it was enqueued
    """
    variable: ContextVar[str] = ContextVar("test_task_queue_scope", default="unscoped")
    job = ScopeReadingJob(variable)
    variable.set("the document being converted")
    queue.enqueue(job)
    variable.set("something else entirely")

    assert job.done.wait(TIMEOUT)

    assert job.seen == "the document being converted"


# endregion

# region Reordering


def test_a_queued_job_can_be_moved_ahead_of_the_others(
    queue: TaskQueue, listener: RecordingListener, settles: Callable[[Callable[[], bool]], None]
) -> None:
    """Reorder takes effect for jobs that have not started -- which is every job but one.

    **Test steps:**

    * hold a job running, and enqueue three more behind it
    * move the last of the three to the front of the queued run
    * release the running job and wait for everything to finish
    * verify the moved job ran first of the three, and the listener was told the new order
    """
    order: list[str] = []
    gated = GatedJob()
    queue.enqueue(gated)
    queue.enqueue(RecordingJob("a", order))
    queue.enqueue(RecordingJob("b", order))
    last = queue.enqueue(RecordingJob("c", order))
    assert gated.entered.wait(TIMEOUT)

    queue.move(last, 1)
    gated.release.set()
    settles(lambda: len(order) == 3)

    assert order == ["c", "a", "b"]
    assert listener.reordered == [(0, 3, 1, 2)]


def test_a_paused_job_is_as_reorderable_as_a_queued_one(queue: TaskQueue, listener: RecordingListener) -> None:
    """Neither is executing, so refusing to move one of them would be an arbitrary difference.

    **Test steps:**

    * hold a job running, and enqueue two behind it
    * pause the last of the two, then move it ahead of the other
    * verify the new order was reported
    """
    gated = GatedJob()
    running = queue.enqueue(gated)
    first = queue.enqueue(RecordingJob("a"))
    second = queue.enqueue(RecordingJob("b"))
    assert gated.entered.wait(TIMEOUT)

    queue.pause_job(second)
    queue.move(second, 1)
    gated.release.set()

    assert listener.reordered == [(running, second, first)]


def test_a_queued_job_cannot_be_moved_ahead_of_the_running_one(queue: TaskQueue, listener: RecordingListener) -> None:
    """Clamped rather than refused: the request is honest, only its index reaches too far.

    **Test steps:**

    * hold a job running, and enqueue two behind it
    * ask for the second queued job to be moved to the very front
    * verify it landed immediately after the running job, not before it
    """
    gated = GatedJob()
    running = queue.enqueue(gated)
    first = queue.enqueue(RecordingJob("a"))
    second = queue.enqueue(RecordingJob("b"))
    assert gated.entered.wait(TIMEOUT)

    queue.move(second, 0)
    gated.release.set()

    assert listener.reordered == [(running, second, first)]


def test_the_running_job_is_not_moved(queue: TaskQueue, listener: RecordingListener) -> None:
    """A job cannot be made to have started later than it did.

    **Test steps:**

    * hold a job running, and enqueue one behind it
    * ask for the running job to be moved to the end
    * verify nothing was reordered
    """
    gated = GatedJob()
    running = queue.enqueue(gated)
    queue.enqueue(RecordingJob("a"))
    assert gated.entered.wait(TIMEOUT)

    queue.move(running, 1)
    gated.release.set()

    assert listener.reordered == []


def test_moving_a_job_to_where_it_already_is_says_nothing(queue: TaskQueue, listener: RecordingListener) -> None:
    """No event for a move that changed no order -- a view redrawing on one would be redrawing on noise.

    **Test steps:**

    * hold a job running, and enqueue two behind it
    * move the first queued job to the position it already occupies
    * verify nothing was reordered
    """
    gated = GatedJob()
    queue.enqueue(gated)
    first = queue.enqueue(RecordingJob("a"))
    queue.enqueue(RecordingJob("b"))
    assert gated.entered.wait(TIMEOUT)

    queue.move(first, 1)
    gated.release.set()

    assert listener.reordered == []


def test_moving_a_serial_that_belongs_to_nothing_is_accepted(queue: TaskQueue, listener: RecordingListener) -> None:
    """A removed job's serial may still be in a view's hand, so this must not raise.

    **Test steps:**

    * move a serial no job has
    * verify nothing was reordered and nothing raised
    """
    queue.move(999, 0)

    assert listener.reordered == []


# endregion

# region Pausing one job


def test_pausing_the_running_job_lets_the_next_one_start(
    queue: TaskQueue, listener: RecordingListener, settles: Callable[[Callable[[], bool]], None]
) -> None:
    """The heart of #237: the queue does not stop because one job did.

    **Test steps:**

    * start a job that holds part-way, with a second behind it
    * pause the running one and let it reach its next checkpoint
    * verify it went to paused, the second ran to done, and the paused one kept its place at the front
    """
    order: list[str] = []
    job = CursorJob()
    paused = queue.enqueue(job)
    queue.enqueue(RecordingJob("next", order))
    assert job.reached.wait(TIMEOUT)

    queue.pause_job(paused)
    job.release.set()

    assert wait_for_state(listener, paused, JobState.PAUSED)
    settles(lambda: order == ["next"])
    assert [status.serial for status in queue.jobs()] == [paused, paused + 1]


def test_a_paused_job_has_returned_rather_than_parked(
    queue: TaskQueue, listener: RecordingListener, settles: Callable[[Callable[[], bool]], None]
) -> None:
    """A cursor, not a held stack: pausing costs no thread, and that is why it costs nothing at all.

    **Test steps:**

    * start a checkpointing job and count the threads while it runs
    * pause it and wait for it to unwind
    * verify the thread count is unchanged and the worker is idle
    * verify the settled job carries no leftover stop request (#260)
    """
    job = CheckpointingJob()
    serial = queue.enqueue(job)
    assert job.entered.wait(TIMEOUT)
    while_running = active_count()

    queue.pause_job(serial)

    assert wait_for_state(listener, serial, JobState.PAUSED)
    settles(lambda: active_count() == while_running)
    assert queue.wait_until_idle(TIMEOUT)
    assert queue.jobs()[0].stop_requested is None
    job.release.set()


def test_a_job_that_says_it_resumes_carries_on_where_it_stopped(queue: TaskQueue, listener: RecordingListener) -> None:
    """The promise ``resumes_where_it_stopped`` makes, and the one it can be held to.

    **Test steps:**

    * start a job that holds after two of its four units, and pause it there
    * resume it and wait for it to finish
    * verify its second run began at two, not at zero
    """
    job = CursorJob(units=4, hold_after=2, resumes=True)
    serial = queue.enqueue(job)
    assert job.reached.wait(TIMEOUT)
    queue.pause_job(serial)
    job.release.set()
    assert wait_for_state(listener, serial, JobState.PAUSED)

    queue.resume_job(serial)

    assert wait_for_state(listener, serial, JobState.DONE)
    assert job.entered_at == [0, 2]


def test_a_job_that_starts_over_is_resumed_from_the_top_and_that_is_correct(
    queue: TaskQueue, listener: RecordingListener
) -> None:
    """Starting over is a supported answer, not a defect -- pausing such a job is wasteful, not wrong.

    **Test steps:**

    * start a job that declares it does not resume, hold it after two of four units, and pause it
    * resume it and wait for it to finish
    * verify its second run began at zero, and that it still finished
    """
    job = CursorJob(units=4, hold_after=2, resumes=False)
    serial = queue.enqueue(job)
    assert job.reached.wait(TIMEOUT)
    queue.pause_job(serial)
    job.release.set()
    assert wait_for_state(listener, serial, JobState.PAUSED)

    queue.resume_job(serial)

    assert wait_for_state(listener, serial, JobState.DONE)
    assert job.entered_at == [0, 0]


def test_pausing_a_queued_job_takes_it_out_of_the_running_without_losing_its_place(
    queue: TaskQueue, listener: RecordingListener, settles: Callable[[Callable[[], bool]], None]
) -> None:
    """A queued job has nothing to unwind, so asking it to pause simply *is* pausing it.

    **Test steps:**

    * hold a job running, with three queued behind it
    * pause the middle queued job, then release the running one
    * verify the other two ran, the paused one did not, and the order is untouched
    """
    order: list[str] = []
    gated = GatedJob()
    running = queue.enqueue(gated)
    first = queue.enqueue(RecordingJob("a", order))
    held = queue.enqueue(RecordingJob("b", order))
    last = queue.enqueue(RecordingJob("c", order))
    assert gated.entered.wait(TIMEOUT)

    queue.pause_job(held)
    gated.release.set()

    settles(lambda: order == ["a", "c"])
    assert listener.states_of(held) == [JobState.PAUSED]
    assert [status.serial for status in queue.jobs()] == [running, first, held, last]


def test_a_job_that_never_checkpoints_cannot_be_paused_either(queue: TaskQueue, listener: RecordingListener) -> None:
    """The same cooperative rule as cancellation: a job that never yields runs to completion.

    **Test steps:**

    * start a job that never checkpoints and ask it to pause
    * let it return of its own accord
    * verify it saw the request, finished done, and carries the request on its status
    """
    job = StubbornJob()
    serial = queue.enqueue(job)
    assert job.entered.wait(TIMEOUT)

    queue.pause_job(serial)
    job.release.set()

    assert wait_for_state(listener, serial, JobState.DONE)
    assert job.saw_pause
    assert queue.jobs()[0].stop_requested is StopRequest.PAUSE


def test_a_cancel_beats_a_pause_at_the_same_checkpoint(queue: TaskQueue, listener: RecordingListener) -> None:
    """The stronger request wins: a cancelled job has nothing to resume to.

    **Test steps:**

    * start a job that blocks before its checkpoint
    * ask it to pause and to cancel, then release it into the checkpoint
    * verify it was reported cancelled
    """
    gated = GatedJob()
    serial = queue.enqueue(gated)
    assert gated.entered.wait(TIMEOUT)

    queue.pause_job(serial)
    queue.cancel(serial)
    gated.release.set()

    assert wait_for_state(listener, serial, JobState.CANCELLED)
    assert not gated.finished


def test_a_resume_landing_while_the_pause_is_in_flight_keeps_the_job_going(
    queue: TaskQueue, listener: RecordingListener
) -> None:
    """A retracted pause is honored on whichever side of the raise the retraction lands.

    The raise and its recording are two moments with the job's own cleanup between them; a resume in
    that gap must not leave the job parked on a request nobody holds any more.

    **Test steps:**

    * hold a job at a known point, pause it, and let it raise -- holding its unwind open
    * resume it while it is demonstrably still unwinding
    * let the unwind finish, and verify it re-entered where it stopped and was never reported paused
    """
    job = SlowUnwindJob()
    serial = queue.enqueue(job)
    assert job.reached.wait(TIMEOUT)
    queue.pause_job(serial)
    job.proceed.set()
    assert job.unwinding.wait(TIMEOUT)

    queue.resume_job(serial)
    job.finish_unwind.set()

    assert wait_for_state(listener, serial, JobState.DONE)
    assert job.entered_at == [0, 2]
    assert JobState.PAUSED not in listener.states_of(serial)


def test_a_cancel_the_job_has_not_looked_at_is_taken_back_by_a_resume(
    queue: TaskQueue, listener: RecordingListener, settles: Callable[[Callable[[], bool]], None]
) -> None:
    """The mis-click this whole seam exists for: Cancel, then Resume, and the job never knew.

    The engine cannot tell a cancel nobody has read from one already half-way through a rollback --
    that distinction lives inside the job -- so it asks, and the job answers.

    **Test steps:**

    * start a job that blocks before its first checkpoint, and cancel it
    * resume it before it can look
    * verify the resume was accepted, the request is gone, and the job ran to completion
    """
    gated = GatedJob("mis-clicked")
    serial = queue.enqueue(gated)
    assert gated.entered.wait(TIMEOUT)
    queue.cancel(serial)

    assert queue.resume_job(serial)

    gated.release.set()
    settles(lambda: gated.finished)
    assert wait_for_state(listener, serial, JobState.DONE)
    assert queue.jobs()[0].stop_requested is None


def test_a_cancel_the_job_has_acted_on_is_not_taken_back(queue: TaskQueue, listener: RecordingListener) -> None:
    """Once the job has been told, the engine can no longer promise nothing has begun -- and a job
    part-way through undoing its work must not be told to carry on.

    **Test steps:**

    * start a job that blocks, cancel it, and let it reach the checkpoint so it unwinds
    * resume it while it is still unwinding
    * verify the resume was refused and the job was recorded cancelled
    """
    job = SlowUnwindJob(stop=StopRequest.CANCEL)
    serial = queue.enqueue(job)
    assert job.reached.wait(TIMEOUT)
    queue.cancel(serial)
    job.proceed.set()
    assert job.unwinding.wait(TIMEOUT)

    assert not queue.resume_job(serial)

    job.finish_unwind.set()
    assert wait_for_state(listener, serial, JobState.CANCELLED)


def test_the_bulk_resume_never_un_cancels_anything(
    queue: TaskQueue, listener: RecordingListener, settles: Callable[[Callable[[], bool]], None]
) -> None:
    """Pressing Resume over the whole queue is the inverse of Pause, not an undo for a cancel someone
    made deliberately -- pointing at one row is how that is asked for.

    **Test steps:**

    * hold a job running, with two queued behind it; cancel one and pause the other
    * resume the whole queue
    * verify the paused one went back in line and the cancelled one stayed cancelled
    """
    gated = GatedJob()
    queue.enqueue(gated)
    cancelled = queue.enqueue(RecordingJob("never"))
    paused = queue.enqueue(RecordingJob("later"))
    assert gated.entered.wait(TIMEOUT)
    queue.cancel(cancelled)
    queue.pause_job(paused)

    queue.resume()
    gated.release.set()

    settles(lambda: queue.jobs()[2].state is JobState.DONE)
    assert listener.states_of(cancelled) == [JobState.CANCELLED]


def test_a_cancel_after_a_pause_replaces_it_rather_than_joining_it(
    queue: TaskQueue, listener: RecordingListener
) -> None:
    """One slot, latest instruction wins -- so *cancel and pause* is never a state anything arbitrates.

    **Test steps:**

    * start a job that blocks before its checkpoint
    * ask it to pause, then to cancel, then release it
    * verify it was reported cancelled, carrying no leftover request
    """
    gated = GatedJob()
    serial = queue.enqueue(gated)
    assert gated.entered.wait(TIMEOUT)

    queue.pause_job(serial)
    queue.cancel(serial)
    gated.release.set()

    assert wait_for_state(listener, serial, JobState.CANCELLED)
    assert queue.jobs()[0].stop_requested is None


def test_a_pause_after_a_cancel_downgrades_it(queue: TaskQueue, listener: RecordingListener) -> None:
    """The same rule in the direction that costs less: asking a cancelling job to pause keeps the work.

    **Test steps:**

    * start a job that blocks before its checkpoint
    * ask it to cancel, then to pause, then release it
    * verify it was reported paused rather than cancelled, carrying no leftover request
    """
    gated = GatedJob()
    serial = queue.enqueue(gated)
    assert gated.entered.wait(TIMEOUT)

    queue.cancel(serial)
    queue.pause_job(serial)
    gated.release.set()

    assert wait_for_state(listener, serial, JobState.PAUSED)
    assert queue.jobs()[0].stop_requested is None


def test_resuming_a_job_with_nothing_pending_is_accepted(queue: TaskQueue) -> None:
    """A Resume on a row nothing was asked of has nothing to take back, and says so rather than lying.

    **Test steps:**

    * start a job with no request against it and resume it
    * verify the answer was yes and the job is untouched
    """
    gated = GatedJob()
    serial = queue.enqueue(gated)
    assert gated.entered.wait(TIMEOUT)

    assert queue.resume_job(serial)

    assert queue.jobs()[0].state is JobState.RUNNING
    gated.release.set()


def test_resuming_a_finished_job_reports_that_it_took_nothing_back(
    queue: TaskQueue, listener: RecordingListener
) -> None:
    """Retry is the verb for a finished job; Resume has nothing to offer one and does not pretend to.

    **Test steps:**

    * run a job to completion
    * resume it
    * verify the answer was no and it is still done
    """
    serial = queue.enqueue(RecordingJob("done"))
    assert wait_for_state(listener, serial, JobState.DONE)

    assert not queue.resume_job(serial)

    assert queue.jobs()[0].state is JobState.DONE


def test_a_cancel_landing_while_the_pause_is_in_flight_is_not_stranded(
    queue: TaskQueue, listener: RecordingListener
) -> None:
    """The other request in the same gap, with more at stake: a cancel recorded onto a parked job
    would wait forever, because nothing ever picks a paused job up.

    **Test steps:**

    * hold a job at a known point, pause it, and let it raise -- holding its unwind open
    * cancel it while it is still unwinding
    * let the unwind finish, and verify it was recorded cancelled, not paused, and never re-entered
    """
    job = SlowUnwindJob()
    serial = queue.enqueue(job)
    assert job.reached.wait(TIMEOUT)
    queue.pause_job(serial)
    job.proceed.set()
    assert job.unwinding.wait(TIMEOUT)

    queue.cancel(serial)
    job.finish_unwind.set()

    assert wait_for_state(listener, serial, JobState.CANCELLED)
    assert JobState.PAUSED not in listener.states_of(serial)
    assert job.entered_at == [0]


def test_a_job_raising_the_pause_exception_unasked_is_paused_once_not_looped(
    queue: TaskQueue, listener: RecordingListener
) -> None:
    """The reconciliation keys on a *retracted* request, never on a missing one -- and this is why:
    inferring a resume from the absent request would re-run an unasked raise forever.

    **Test steps:**

    * enqueue a job that raises the pause exception with no request against it
    * wait for it to be reported paused
    * verify it ran exactly once and stays paused
    """
    job = SelfPausingJob()
    serial = queue.enqueue(job)

    assert wait_for_state(listener, serial, JobState.PAUSED)

    assert queue.wait_until_idle(TIMEOUT)
    assert job.runs == 1
    assert queue.jobs()[0].state is JobState.PAUSED


def test_pausing_a_finished_job_changes_nothing(queue: TaskQueue, listener: RecordingListener) -> None:
    """A view's pause button can be pressed on a row that finished a moment earlier.

    **Test steps:**

    * run a job to completion, then pause it
    * verify it is still reported done
    """
    serial = queue.enqueue(RecordingJob("done"))
    assert wait_for_state(listener, serial, JobState.DONE)

    queue.pause_job(serial)

    assert listener.states_of(serial)[-1] is JobState.DONE


# endregion

# region Pausing the queue


def test_pausing_the_queue_pauses_every_unfinished_job(
    queue: TaskQueue, listener: RecordingListener, settles: Callable[[Callable[[], bool]], None]
) -> None:
    """One pause concept, not two: the queue's pause is the per-job one applied to all of them.

    **Test steps:**

    * hold a job running, with two queued behind it
    * pause the queue and release the running job
    * verify all three ended up paused, and the queue reads as paused
    """
    job = CursorJob()
    running = queue.enqueue(job)
    first = queue.enqueue(RecordingJob("a"))
    second = queue.enqueue(RecordingJob("b"))
    assert job.reached.wait(TIMEOUT)

    queue.pause()
    job.release.set()

    assert wait_for_state(listener, running, JobState.PAUSED)
    settles(lambda: all(status.state is JobState.PAUSED for status in queue.jobs()))
    assert queue.paused
    assert (listener.states_of(first), listener.states_of(second)) == ([JobState.PAUSED], [JobState.PAUSED])


def test_the_queue_reads_as_paused_only_once_every_unfinished_job_is(
    queue: TaskQueue, listener: RecordingListener
) -> None:
    """Derived, not held -- so a half-paused queue never claims to be a paused one.

    **Test steps:**

    * hold a job running, with two queued behind it
    * pause one queued job, and verify the queue does not read as paused
    * pause the rest, and verify it does
    """
    gated = GatedJob()
    running = queue.enqueue(gated)
    first = queue.enqueue(RecordingJob("a"))
    second = queue.enqueue(RecordingJob("b"))
    assert gated.entered.wait(TIMEOUT)

    queue.pause_job(first)

    assert not queue.paused
    assert listener.paused == []

    queue.pause_job(second)
    queue.cancel(running)
    gated.release.set()

    assert wait_for_state(listener, running, JobState.CANCELLED)
    assert queue.paused
    assert listener.paused == [True]


def test_resuming_one_job_is_enough_to_unpause_the_queue(queue: TaskQueue, listener: RecordingListener) -> None:
    """``paused`` means *all of them*, so putting one back in line ends it.

    **Test steps:**

    * hold a job running with a second behind it, and pause the queue so both end up paused
    * resume the second, which then starts and holds in its turn
    * verify the queue was reported paused, then unpaused
    """
    first = GatedJob("first")
    running = queue.enqueue(first)
    second = GatedJob("second")
    resumed = queue.enqueue(second)
    assert first.entered.wait(TIMEOUT)
    queue.pause()
    first.release.set()
    assert wait_for_state(listener, running, JobState.PAUSED)
    assert queue.paused

    queue.resume_job(resumed)

    assert second.entered.wait(TIMEOUT)
    assert not queue.paused
    assert listener.paused == [True, False]
    second.release.set()


def test_a_queue_holding_nothing_unfinished_does_not_read_as_paused(
    queue: TaskQueue, listener: RecordingListener
) -> None:
    """Vacuously true would read as *the queue is held*, which is the opposite of what empty means.

    **Test steps:**

    * verify an empty queue does not read as paused, and that pausing it says nothing
    * run a job to completion, then pause again
    * verify a queue holding only a finished job is not paused either -- pausing passes over it
    """
    assert not queue.paused
    queue.pause()
    assert not queue.paused

    serial = queue.enqueue(RecordingJob("only"))
    assert wait_for_state(listener, serial, JobState.DONE)
    queue.pause()

    assert not queue.paused
    assert listener.states_of(serial)[-1] is JobState.DONE
    assert listener.paused == []


def test_a_job_enqueued_after_a_pause_runs_at_once(
    queue: TaskQueue, listener: RecordingListener, settles: Callable[[Callable[[], bool]], None]
) -> None:
    """Eligibility is per job, so a pause is over the jobs it was asked about and no others.

    **Test steps:**

    * enqueue a job and pause the queue so it is held
    * enqueue a second job
    * verify the second runs while the first stays paused
    """
    order: list[str] = []
    gated = GatedJob()
    held = queue.enqueue(gated)
    assert gated.entered.wait(TIMEOUT)
    queue.pause()
    gated.release.set()
    assert wait_for_state(listener, held, JobState.PAUSED)

    queue.enqueue(RecordingJob("fresh", order))

    settles(lambda: order == ["fresh"])
    assert queue.jobs()[0].state is JobState.PAUSED


def test_pausing_or_resuming_a_serial_that_belongs_to_nothing_is_accepted(queue: TaskQueue) -> None:
    """A removed job's serial may still be in a view's hand, exactly as for cancel, move and retry.

    **Test steps:**

    * pause and resume a serial no job has
    * verify nothing raised and the queue still holds nothing
    """
    queue.pause_job(999)
    queue.resume_job(999)

    assert queue.jobs() == ()


def test_pausing_twice_is_reported_once(queue: TaskQueue, listener: RecordingListener) -> None:
    """A listener is told when something changed, not when something was asked for again.

    **Test steps:**

    * hold a job running and pause the queue so it unwinds
    * pause it again, then resume twice
    * verify exactly one pause and one resume were reported
    """
    gated = GatedJob()
    serial = queue.enqueue(gated)
    assert gated.entered.wait(TIMEOUT)
    queue.pause()
    gated.release.set()
    assert wait_for_state(listener, serial, JobState.PAUSED)

    queue.pause()
    queue.resume()
    queue.resume()

    assert listener.paused == [True, False]


# endregion

# region Cancelling


def test_cancelling_a_queued_job_means_it_never_runs(
    queue: TaskQueue, listener: RecordingListener, settles: Callable[[Callable[[], bool]], None]
) -> None:
    """Cancelled before it started is the cheap case, and the one a bulk enqueue produces most.

    **Test steps:**

    * hold a job running and enqueue a second behind it
    * cancel the second, then release the first
    * verify the second was reported cancelled and never ran
    * verify it carries no leftover stop request, settled outright by the engine (#260)
    """
    order: list[str] = []
    gated = GatedJob()
    queue.enqueue(gated)
    second = queue.enqueue(RecordingJob("second", order))
    assert gated.entered.wait(TIMEOUT)

    queue.cancel(second)
    gated.release.set()

    settles(lambda: gated.finished)
    assert listener.states_of(second) == [JobState.CANCELLED]
    assert not order
    assert next(status for status in queue.jobs() if status.serial == second).stop_requested is None


def test_cancelling_the_running_job_reaches_it_at_its_checkpoint(queue: TaskQueue, listener: RecordingListener) -> None:
    """What makes cancellation cooperative rather than a kill: the job unwinds itself.

    **Test steps:**

    * start a job that blocks and then checkpoints
    * cancel it, then release it into its checkpoint
    * verify it was reported cancelled and never reached the line past the checkpoint
    * verify the settled job carries no leftover stop request (#260)
    """
    gated = GatedJob()
    serial = queue.enqueue(gated)
    assert gated.entered.wait(TIMEOUT)

    queue.cancel(serial)
    gated.release.set()

    assert wait_for_state(listener, serial, JobState.CANCELLED)
    assert not gated.finished
    assert queue.jobs()[0].stop_requested is None


def test_a_cancel_request_is_announced_before_the_job_obeys_it(queue: TaskQueue, listener: RecordingListener) -> None:
    """A request is a fact of its own, so a watcher can be honest about it while nothing has happened yet.

    **Test steps:**

    * start a job that blocks before its checkpoint
    * cancel it, and verify the request reached the listener while the job is still running
    * release it and verify it then goes to cancelled
    """
    gated = GatedJob()
    serial = queue.enqueue(gated)
    assert gated.entered.wait(TIMEOUT)

    queue.cancel(serial)

    requested = [
        status for status in listener.updated if status.serial == serial and status.stop_requested is StopRequest.CANCEL
    ]
    assert requested[0].state is JobState.RUNNING
    gated.release.set()
    assert wait_for_state(listener, serial, JobState.CANCELLED)


def test_cancelling_a_paused_job_stops_it_without_resuming_it(queue: TaskQueue, listener: RecordingListener) -> None:
    """A paused job is not running, so there is nothing to reach: it is cancelled where it stands.

    **Test steps:**

    * start a checkpointing job and pause it so it unwinds
    * cancel it without resuming
    * verify it was reported cancelled
    """
    job = CheckpointingJob()
    serial = queue.enqueue(job)
    assert job.entered.wait(TIMEOUT)
    queue.pause_job(serial)
    assert wait_for_state(listener, serial, JobState.PAUSED)

    queue.cancel(serial)

    assert wait_for_state(listener, serial, JobState.CANCELLED)
    assert not job.finished
    job.release.set()


def test_a_job_that_finished_is_done_even_though_a_stop_was_asked_for(
    queue: TaskQueue, listener: RecordingListener
) -> None:
    """Reversing #201: the request was never acted on, and the work genuinely finished.

    A job that never checkpoints cannot be interrupted, so reporting it *cancelled* would describe an
    intention rather than an outcome. The request is not lost -- it is on the status, where it belongs.

    **Test steps:**

    * start a job that never checkpoints
    * cancel it, then let it return of its own accord
    * verify it saw the cancellation, was reported done, and still carries the request
    """
    job = StubbornJob()
    serial = queue.enqueue(job)
    assert job.entered.wait(TIMEOUT)

    queue.cancel(serial)
    job.release.set()

    assert wait_for_state(listener, serial, JobState.DONE)
    assert job.saw_cancellation
    assert queue.jobs()[0].stop_requested is StopRequest.CANCEL


def test_cancelling_a_finished_job_changes_nothing(queue: TaskQueue, listener: RecordingListener) -> None:
    """A view's cancel button can be pressed on a row that finished a moment earlier.

    **Test steps:**

    * run a job to completion
    * cancel it afterwards
    * verify it is still reported done
    """
    serial = queue.enqueue(RecordingJob("done"))
    assert wait_for_state(listener, serial, JobState.DONE)

    queue.cancel(serial)

    assert listener.states_of(serial)[-1] is JobState.DONE


def test_cancelling_a_serial_that_belongs_to_nothing_is_accepted(queue: TaskQueue) -> None:
    """Same reason as the move: a removed job's serial may still be in a view's hand.

    **Test steps:**

    * cancel a serial no job has
    * verify nothing raised and the queue still holds nothing
    """
    queue.cancel(999)

    assert queue.jobs() == ()


# endregion

# region Failing


def test_a_failing_job_is_recorded_and_the_queue_carries_on(
    queue: TaskQueue, listener: RecordingListener, settles: Callable[[Callable[[], bool]], None]
) -> None:
    """A queue that stopped on the first failure would strand every job behind it.

    **Test steps:**

    * enqueue a job that raises, followed by one that does not
    * wait for both to finish
    * verify the first is failed with its exception's type and message, and the second ran
    """
    order: list[str] = []
    failed = queue.enqueue(FailingJob())
    queue.enqueue(RecordingJob("after", order))

    settles(lambda: order == ["after"])

    assert wait_for_state(listener, failed, JobState.FAILED)
    status = [held for held in queue.jobs() if held.serial == failed][0]
    assert status.error == "RuntimeError: the disk went away"


def test_a_failure_is_written_to_the_log(
    queue: TaskQueue, listener: RecordingListener, caplog: pytest.LogCaptureFixture
) -> None:
    """The one place a failed job's detail is readable afterwards is the log ([[appendices.logging]]).

    **Test steps:**

    * enqueue a job that raises, with error-level capture on
    * wait for it to be reported failed
    * verify an error record naming the job was written, carrying the exception
    """
    with caplog.at_level(logging.ERROR):
        failed = queue.enqueue(FailingJob())
        assert wait_for_state(listener, failed, JobState.FAILED)

    assert [record for record in caplog.records if "failing" in record.getMessage() and record.exc_info]


# endregion

# region Listeners


def test_a_listener_attached_late_seeds_itself_from_the_queue(queue: TaskQueue, listener: RecordingListener) -> None:
    """Nothing is replayed, because a queue's history *is* its current state.

    **Test steps:**

    * run a job to completion, then attach a second listener
    * verify the new listener was told nothing
    * verify the queue's own snapshot holds the finished job
    """
    serial = queue.enqueue(RecordingJob("early"))
    assert wait_for_state(listener, serial, JobState.DONE)

    late = RecordingListener()
    queue.add_listener(late)

    assert (late.enqueued, late.updated) == ([], [])
    assert [status.state for status in queue.jobs()] == [JobState.DONE]


def test_a_removed_listener_is_told_nothing_further(queue: TaskQueue, listener: RecordingListener) -> None:
    """Detaching is how a closing dock stops being written to.

    **Test steps:**

    * detach the listener, then enqueue a job
    * verify it was told nothing
    """
    queue.remove_listener(listener)

    queue.enqueue(RecordingJob("unwatched"))

    assert listener.enqueued == []


def test_removing_a_listener_that_was_never_attached_is_accepted(queue: TaskQueue) -> None:
    """Teardown never has to ask first.

    **Test steps:**

    * remove a listener that was never added
    * verify nothing raised
    """
    queue.remove_listener(RecordingListener())

    assert queue.jobs() == ()


def test_a_raising_listener_does_not_kill_the_worker(
    queue: TaskQueue, listener: RecordingListener, caplog: pytest.LogCaptureFixture
) -> None:
    """One bad observer must cost its own round, never the queue -- a dead worker is the silent stall
    the component exists to prevent.

    **Test steps:**

    * attach a listener that raises on every call, ahead of the recording one
    * enqueue two jobs, with error-level capture on
    * verify both still ran to done, the recording listener was still told everything, and the
      failure was logged
    """
    queue.add_listener(RaisingListener())
    queue.remove_listener(listener)
    queue.add_listener(listener)  # re-attach behind the raising one, so the round demonstrably continues

    with caplog.at_level(logging.ERROR):
        first = queue.enqueue(RecordingJob("first"))
        second = queue.enqueue(RecordingJob("second"))
        assert wait_for_state(listener, first, JobState.DONE)
        assert wait_for_state(listener, second, JobState.DONE)

    assert [record for record in caplog.records if "listener failed" in record.getMessage() and record.exc_info]


def test_a_raising_listener_does_not_fail_the_call_that_notified_it(queue: TaskQueue) -> None:
    """An enqueue that happened must not report failure to its caller over an observer's bug.

    **Test steps:**

    * attach only a listener that raises
    * enqueue a job
    * verify the enqueue returned its serial and the job is genuinely in the queue
    """
    queue.add_listener(RaisingListener())
    gated = GatedJob()

    serial = queue.enqueue(gated)

    assert serial in [status.serial for status in queue.jobs()]
    gated.release.set()


def test_progress_is_reported_on_the_worker_thread(queue: TaskQueue, listener: RecordingListener) -> None:
    """Stated rather than assumed: a GUI listener has to marshal, and this is what it is marshalling.

    **Test steps:**

    * enqueue a job and wait for it to finish
    * verify the listener was called on a thread that is not the test's
    """
    serial = queue.enqueue(RecordingJob("threaded"))
    assert wait_for_state(listener, serial, JobState.DONE)

    assert listener.threads - {get_ident()}


# endregion

# region Removing and retrying


def test_nothing_leaves_the_queue_until_it_is_asked_for(
    queue: TaskQueue, listener: RecordingListener, settles: Callable[[Callable[[], bool]], None]
) -> None:
    """Jobs leave only when told to: a failure is kept because it is the thing worth acting on.

    **Test steps:**

    * hold a job running, with a failing one and a third behind it, and cancel the third
    * release everything and wait for the queue to go quiet
    * verify all three are still held, and nothing was reported removed
    """
    gated = GatedJob("fine")
    queue.enqueue(gated)
    queue.enqueue(FailingJob())
    cancelled = queue.enqueue(RecordingJob("never"))
    assert gated.entered.wait(TIMEOUT)
    queue.cancel(cancelled)
    gated.release.set()

    settles(lambda: all(status.state is not JobState.QUEUED for status in queue.jobs()))

    assert {status.state for status in queue.jobs()} == {JobState.DONE, JobState.FAILED, JobState.CANCELLED}
    assert listener.removed == []


def test_remove_drops_only_the_jobs_it_was_named(queue: TaskQueue, listener: RecordingListener) -> None:
    """A multi-selection is removed in one call, and everything else keeps its place.

    **Test steps:**

    * hold a job running, with three queued behind it
    * remove two of the queued ones
    * verify only those two went, in the order they were held
    """
    gated = GatedJob()
    running = queue.enqueue(gated)
    first = queue.enqueue(RecordingJob("a"))
    second = queue.enqueue(RecordingJob("b"))
    third = queue.enqueue(RecordingJob("c"))
    assert gated.entered.wait(TIMEOUT)

    queue.remove(third, first)
    gated.release.set()

    assert listener.removed == [(first, third)]
    assert [status.serial for status in queue.jobs()] == [running, second]


def test_removing_the_running_job_cancels_it_and_drops_its_outcome(
    queue: TaskQueue, listener: RecordingListener
) -> None:
    """Telling a listener that a row it deleted has just been cancelled would announce a job that,
    as far as anyone watching is concerned, no longer exists.

    **Test steps:**

    * start a job that blocks before its checkpoint
    * remove it, then release it into the checkpoint
    * wait for the worker to go idle, and verify the job unwound but was never reported cancelled
    """
    gated = GatedJob()
    serial = queue.enqueue(gated)
    assert gated.entered.wait(TIMEOUT)

    queue.remove(serial)
    gated.release.set()

    assert queue.wait_until_idle(TIMEOUT)
    assert not gated.finished
    assert listener.removed == [(serial,)]
    assert JobState.CANCELLED not in listener.states_of(serial)


def test_removing_serials_that_belong_to_nothing_says_nothing(queue: TaskQueue, listener: RecordingListener) -> None:
    """No event for a removal that removed nothing, so a caller never has to filter its selection.

    **Test steps:**

    * remove serials no job has, on an empty queue
    * verify nothing was reported removed
    """
    queue.remove(999, 1000)

    assert listener.removed == []


def test_retry_runs_a_finished_job_again(
    queue: TaskQueue, listener: RecordingListener, settles: Callable[[Callable[[], bool]], None]
) -> None:
    """The recovery a kept failure exists for: fix the cause, press Retry.

    **Test steps:**

    * run a job to completion
    * retry it
    * verify it went back to queued and its ``run`` was entered a second time
    """
    job = CursorJob(units=1, hold_after=99)
    serial = queue.enqueue(job)
    assert wait_for_state(listener, serial, JobState.DONE)

    queue.retry(serial)

    settles(lambda: len(job.entered_at) == 2)
    assert JobState.QUEUED in listener.states_of(serial)


def test_retry_clears_a_failed_jobs_reason(queue: TaskQueue, listener: RecordingListener) -> None:
    """A stale reason on a row that is about to run again would describe the wrong attempt.

    **Test steps:**

    * run a job that raises
    * retry it and wait for it to fail again
    * verify the listener saw it queued with no error in between
    """
    serial = queue.enqueue(FailingJob())
    assert wait_for_state(listener, serial, JobState.FAILED)

    queue.retry(serial)

    assert wait_for_state(listener, serial, JobState.QUEUED)
    requeued = [status for status in listener.updated if status.serial == serial and status.state is JobState.QUEUED]
    assert (requeued[0].error, requeued[0].done, requeued[0].total) == (None, 0, None)


def test_retry_starts_a_job_over_even_when_it_would_otherwise_carry_on(
    queue: TaskQueue, listener: RecordingListener, settles: Callable[[Callable[[], bool]], None]
) -> None:
    """Clearing what the job kept is the whole difference between Retry and Resume.

    **Test steps:**

    * run a job that resumes where it stopped all the way to done
    * retry it
    * verify its second run began at zero rather than at the end it had reached
    """
    job = CursorJob(units=3, hold_after=99, resumes=True)
    serial = queue.enqueue(job)
    assert wait_for_state(listener, serial, JobState.DONE)

    queue.retry(serial)

    settles(lambda: len(job.entered_at) == 2)
    assert job.entered_at == [0, 0]


def test_retrying_a_job_that_has_not_finished_is_a_no_op(queue: TaskQueue, listener: RecordingListener) -> None:
    """Interpreting it as a restart would throw away work nobody asked to lose.

    **Test steps:**

    * hold a job running, with one queued behind it
    * retry both
    * verify neither changed state
    """
    gated = GatedJob()
    running = queue.enqueue(gated)
    queued = queue.enqueue(RecordingJob("a"))
    assert gated.entered.wait(TIMEOUT)

    queue.retry(running)
    queue.retry(queued)

    assert listener.states_of(running) == [JobState.RUNNING]
    assert listener.states_of(queued) == []
    gated.release.set()


def test_retrying_a_serial_that_belongs_to_nothing_is_accepted(queue: TaskQueue) -> None:
    """A removed job's serial may still be in a view's hand, exactly as for cancel and move.

    **Test steps:**

    * retry a serial no job has
    * verify nothing raised
    """
    queue.retry(999)

    assert queue.jobs() == ()


# endregion

# region Teardown


def test_shutdown_stops_the_worker_and_cancels_what_is_left(queue: TaskQueue, listener: RecordingListener) -> None:
    """Quitting with work in flight must leave no thread and no queued job pretending it will run.

    **Test steps:**

    * hold a job running with a second queued behind it
    * release the running job and shut the queue down
    * verify the queued job was cancelled and no worker thread survives
    """
    gated = GatedJob()
    queue.enqueue(gated)
    queued = queue.enqueue(RecordingJob("never"))
    assert gated.entered.wait(TIMEOUT)
    gated.release.set()

    queue.shutdown()

    assert listener.states_of(queued) == [JobState.CANCELLED]
    assert all(status.state is not JobState.RUNNING for status in queue.jobs())


def test_shutdown_cancels_a_paused_job(queue: TaskQueue, listener: RecordingListener) -> None:
    """A paused job is unfinished work, so shutdown owes it the same answer as a queued one.

    **Test steps:**

    * start a checkpointing job and pause it so it unwinds
    * shut the queue down
    * verify the job was cancelled
    """
    job = CheckpointingJob()
    serial = queue.enqueue(job)
    assert job.entered.wait(TIMEOUT)
    queue.pause_job(serial)
    assert wait_for_state(listener, serial, JobState.PAUSED)

    queue.shutdown()

    assert listener.states_of(serial)[-1] is JobState.CANCELLED
    job.release.set()


def test_wait_until_idle_returns_once_the_running_job_has_paused(queue: TaskQueue, listener: RecordingListener) -> None:
    """The clean exit #238 saves from: pause, wait, and only then is there a queue worth writing down.

    **Test steps:**

    * start a job that holds part-way, pause the whole queue, and let it reach its checkpoint
    * wait for the queue to go idle
    * verify the wait succeeded and the job is paused with the work it did intact
    """
    job = CursorJob(units=4, hold_after=2)
    serial = queue.enqueue(job)
    assert job.reached.wait(TIMEOUT)
    queue.pause()
    job.release.set()

    assert queue.wait_until_idle(TIMEOUT)

    assert wait_for_state(listener, serial, JobState.PAUSED)
    assert queue.jobs()[0].done == 2


def test_wait_until_idle_gives_up_on_a_job_that_ignores_its_checkpoints(queue: TaskQueue) -> None:
    """It reports rather than hangs, so the caller decides whether to save what it has or wait longer.

    **Test steps:**

    * start a job that never checkpoints and ask the queue to pause
    * wait for it to go idle, with a wait too short for the job
    * verify the wait reported failure, then release the job
    """
    job = StubbornJob()
    queue.enqueue(job)
    assert job.entered.wait(TIMEOUT)
    queue.pause()

    assert not queue.wait_until_idle(timeout=0.01)

    job.release.set()


def test_wait_until_idle_on_a_queue_with_nothing_running_returns_at_once(queue: TaskQueue) -> None:
    """Most quits happen with nothing in flight, and none of them should cost a wait.

    **Test steps:**

    * wait for a queue that was never given work to go idle
    * verify it reported success
    """
    assert queue.wait_until_idle(TIMEOUT)


def test_shutdown_reports_a_job_that_outlives_the_wait(queue: TaskQueue, caplog: pytest.LogCaptureFixture) -> None:
    """A daemon worker means the process still exits; what is owed is a record of why it took a moment.

    **Test steps:**

    * start a job that never checkpoints and never returns until told
    * shut the queue down with a wait too short for it
    * verify a warning was written, then release the job
    """
    job = StubbornJob()
    queue.enqueue(job)
    assert job.entered.wait(TIMEOUT)

    with caplog.at_level(logging.WARNING):
        queue.shutdown(timeout=0.01)

    assert [record for record in caplog.records if "outlived" in record.getMessage()]
    job.release.set()


def test_quitting_with_a_paused_and_a_running_job_leaves_no_thread(
    queue: TaskQueue, listener: RecordingListener
) -> None:
    """The state an app closes in, end to end: one job held, one still working, and nothing left over.

    **Test steps:**

    * pause one job so it unwinds, then start a second and hold it running
    * count the threads, release the second, and shut the queue down
    * verify the thread count came back to what it was before either job existed
    """
    before = active_count()
    first = CheckpointingJob("held")
    held = queue.enqueue(first)
    assert first.entered.wait(TIMEOUT)
    queue.pause_job(held)
    assert wait_for_state(listener, held, JobState.PAUSED)
    first.release.set()
    second = GatedJob("working")
    queue.enqueue(second)
    assert second.entered.wait(TIMEOUT)

    second.release.set()
    queue.shutdown()

    assert active_count() == before


def test_shutting_down_a_queue_that_never_ran_anything_is_accepted(queue: TaskQueue) -> None:
    """There is no worker to join, and the app quits without ever having enqueued anything most runs.

    **Test steps:**

    * shut down a queue that was never given work
    * verify nothing raised
    """
    queue.shutdown()

    assert queue.jobs() == ()


def test_a_queue_that_has_been_shut_down_refuses_work(queue: TaskQueue) -> None:
    """Silently accepting work that will never run would be worse than refusing it.

    **Test steps:**

    * shut the queue down
    * verify enqueueing after that raises
    """
    queue.shutdown()

    with pytest.raises(RuntimeError):
        queue.enqueue(RecordingJob("too late"))


# endregion


# region Sources that move (#241)
def test_resync_sources_announces_a_job_whose_source_moved(queue: TaskQueue, listener: RecordingListener) -> None:
    """A job that followed its resource is re-read, and its row is told the new path.

    The row a reader clicks has to name somewhere that exists; a rename mid-sweep would otherwise leave
    it pointing at a folder that is gone.

    **Test steps:**

    * enqueue a job over a movable source and check the row carries the original path
    * move the source and ask the queue to re-read
    * check exactly one update arrived, carrying the new path
    """
    job = MovableSourceJob("scan", Path("/fake/library/old_folder/info.rehu"))
    serial = queue.enqueue(job)
    assert listener.enqueued[0][0].source == Path("/fake/library/old_folder/info.rehu")
    listener.updated.clear()

    job.source = Path("/fake/library/new_name/info.rehu")
    queue.resync_sources()

    assert [(status.serial, status.source) for status in listener.updated] == [
        (serial, Path("/fake/library/new_name/info.rehu"))
    ]


def test_resync_sources_is_silent_when_nothing_moved(queue: TaskQueue, listener: RecordingListener) -> None:
    """A rename that touched nothing this queue holds announces nothing.

    Without the comparison, every rename would burst one identical update per job -- and a catalog-wide
    sweep holds a great many.

    **Test steps:**

    * enqueue a job over a fixed source and a job about no resource at all
    * re-read sources without moving anything
    * check no update arrived
    """
    queue.enqueue(MovableSourceJob("scan", Path("/fake/library/old_folder/info.rehu")))
    queue.enqueue(RecordingJob("sourceless"))
    listener.updated.clear()

    queue.resync_sources()

    assert listener.updated == []


def test_resync_sources_re_reads_finished_jobs_too(
    queue: TaskQueue, listener: RecordingListener, settles: Callable[[Callable[[], bool]], None]
) -> None:
    """A done job's row names a path a reader may still click, so it follows the rename as well.

    **Test steps:**

    * run a job to completion over a movable source
    * move the source and re-read
    * check the finished row was updated, and is still reported done
    """
    job = MovableSourceJob("scan", Path("/fake/library/old_folder/info.rehu"))
    serial = queue.enqueue(job)
    settles(lambda: wait_for_state(listener, serial, JobState.DONE))
    listener.updated.clear()

    job.source = Path("/fake/library/new_name/info.rehu")
    queue.resync_sources()

    assert [(status.source, status.state) for status in listener.updated] == [
        (Path("/fake/library/new_name/info.rehu"), JobState.DONE)
    ]


# endregion


def wait_for_state(listener: RecordingListener, serial: int, state: JobState) -> bool:
    """Wait until ``listener`` has been told that ``serial`` reached ``state``.

    A plain wait rather than a fixture because it takes the listener under test as its subject; the
    poll is the same bounded one :func:`settles_fixture` explains.

    :param listener: the attached listener.
    :param serial: which job.
    :param state: the state to wait for.
    :returns: ``True`` once it was reported, ``False`` if the timeout ran out first.
    """
    deadline = monotonic() + TIMEOUT
    while monotonic() < deadline:
        if any(status.serial == serial and status.state is state for status in list(listener.updated)):
            return True
        sleep(0.001)
    return False
