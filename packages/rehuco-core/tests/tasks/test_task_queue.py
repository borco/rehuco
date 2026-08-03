"""Tests for the serial task-queue engine -- ordering, pause, cancellation, failure and teardown (#201).

Every job below is driven by `threading.Event`s rather than by sleeping, so a test asserts on a state
the worker has demonstrably reached instead of on one it has probably reached by now. The one place
polling is unavoidable is observing a transition the worker makes on its own -- that is what the
``settles`` fixture is for, and it waits on a condition rather than for a duration.
"""

# The engine's surface is small but its behaviors are many, and every one of them below is a distinct
# fact about it. Splitting the file would put ordering, pausing and teardown in three modules that
# share the same four fakes and the same two fixtures.
# pylint: disable=too-many-lines

import logging
from collections.abc import Callable, Iterator, Sequence
from contextvars import ContextVar
from threading import Event, get_ident
from time import monotonic, sleep
from typing import Final

import pytest
from pytest import fixture
from rehuco_core import JobControl, JobState, JobStatus, TaskQueue

TIMEOUT: Final = 5.0
"""How long a test waits for the worker before calling it a failure, in seconds.

Generous on purpose: it is a deadlock detector, not a measurement. Every wait below ends the moment
the condition holds, so a passing run never spends this."""


# region Sample classes

# a fake job is one method by definition -- ``run`` is the whole of what the engine asks of it
# pylint: disable=too-few-public-methods


class RecordingJob:
    """A job that runs to completion, checkpointing and reporting once per unit.

    :param label: the job's label.
    :param order: shared list each job appends its label to as it finishes, which is how the tests
        read back the order work actually ran in.
    :param units: how many checkpoints and progress reports to make.
    """

    def __init__(self, label: str, order: list[str] | None = None, units: int = 1) -> None:
        self.label: Final = label
        self.__order: Final = order
        self.__units: Final = units

    def run(self, control: JobControl) -> None:
        """Report progress once per unit, checkpointing before each.

        :param control: the engine's face to this job.
        """
        for unit in range(self.__units):
            control.checkpoint()
            control.report(unit + 1, self.__units)
        if self.__order is not None:
            self.__order.append(self.label)


class GatedJob:
    """A job the test holds mid-run: it announces that it started, waits to be let go, then checkpoints.

    The shape every "while a job is running..." test needs -- the queue is demonstrably busy from the
    moment :attr:`entered` is set until :attr:`release` is set, with a checkpoint waiting on the far
    side for a pause or a cancellation to be observed at.

    **A test that holds one must let it go before it ends**, cancelled or released: an abandoned one
    sits in ``release.wait`` for the whole deadlock timeout, and the fixture's shutdown waits for it.

    :param label: the job's label.
    """

    def __init__(self, label: str = "gated") -> None:
        self.label: Final = label
        self.entered: Final = Event()
        self.release: Final = Event()
        self.finished = False

    def run(self, control: JobControl) -> None:
        """Announce, wait for the test, then yield to the engine.

        :param control: the engine's face to this job.
        """
        self.entered.set()
        self.release.wait(TIMEOUT)
        control.checkpoint()
        self.finished = True


class CheckpointingJob:
    """A job that checkpoints in a loop until the test lets it stop -- somewhere a pause can land.

    Unlike :class:`GatedJob`, this one is *inside* its checkpoint repeatedly, so pausing the queue
    parks it without the test having to time anything.

    :param label: the job's label.
    """

    def __init__(self, label: str = "looping") -> None:
        self.label: Final = label
        self.entered: Final = Event()
        self.release: Final = Event()
        self.finished = False

    def run(self, control: JobControl) -> None:
        """Checkpoint until released, then finish.

        :param control: the engine's face to this job.
        """
        self.entered.set()
        while not self.release.is_set():
            control.checkpoint()
            sleep(0.001)
        control.checkpoint()
        self.finished = True


class StubbornJob:
    """A job that never checkpoints -- what work the engine cannot interrupt looks like.

    :param label: the job's label.
    """

    def __init__(self, label: str = "stubborn") -> None:
        self.label: Final = label
        self.entered: Final = Event()
        self.release: Final = Event()
        self.saw_cancellation = False

    def run(self, control: JobControl) -> None:
        """Announce, wait to be let go, and read the cancellation flag without unwinding on it.

        :param control: the engine's face to this job.
        """
        self.entered.set()
        self.release.wait(TIMEOUT)
        self.saw_cancellation = control.cancelled


class FailingJob:
    """A job that raises, so the queue's failure policy has something to record.

    :param label: the job's label.
    """

    def __init__(self, label: str = "failing") -> None:
        self.label: Final = label

    def run(self, control: JobControl) -> None:
        """Raise, having done nothing.

        :param control: unused; the failure happens before any work would.
        :raises RuntimeError: always.
        """
        del control
        raise RuntimeError("the disk went away")


class IndeterminateJob:
    """A job that reports progress it cannot total -- a scan that discovers as it walks.

    :param label: the job's label.
    """

    def __init__(self, label: str = "scanning") -> None:
        self.label: Final = label

    def run(self, control: JobControl) -> None:
        """Report a count with no total.

        :param control: the engine's face to this job.
        """
        control.report(3)


class ScopeReadingJob:
    """A job that records what a `contextvars.ContextVar` held on the worker thread.

    :param label: the job's label.
    :param variable: the variable to read once the job is running.
    """

    def __init__(self, variable: ContextVar[str], label: str = "scoped") -> None:
        self.label: Final = label
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
    """A cleared job's serial may still be in a view's hand, so this must not raise.

    **Test steps:**

    * move a serial no job has
    * verify nothing was reordered and nothing raised
    """
    queue.move(999, 0)

    assert listener.reordered == []


# endregion

# region Pausing


def test_pausing_parks_the_running_job_at_its_next_checkpoint(
    queue: TaskQueue, listener: RecordingListener, settles: Callable[[Callable[[], bool]], None]
) -> None:
    """Cooperative, not immediate: the job stops where it chose to yield, and says it has.

    **Test steps:**

    * start a job that checkpoints in a loop
    * pause the queue
    * verify the queue reports paused and the job reaches the paused state
    """
    job = CheckpointingJob()
    serial = queue.enqueue(job)
    assert job.entered.wait(TIMEOUT)

    queue.pause()

    assert queue.paused
    settles(lambda: any(status.state is JobState.PAUSED for status in queue.jobs()))
    assert listener.paused == [True]
    assert JobState.PAUSED in listener.states_of(serial)
    job.release.set()


def test_resuming_continues_the_parked_job(
    queue: TaskQueue, listener: RecordingListener, settles: Callable[[Callable[[], bool]], None]
) -> None:
    """Nothing is re-run: the job carries on from the checkpoint it stopped at.

    **Test steps:**

    * start a checkpointing job and pause the queue
    * wait for the job to park, then resume
    * release the job and verify it ran to completion
    """
    job = CheckpointingJob()
    serial = queue.enqueue(job)
    assert job.entered.wait(TIMEOUT)
    queue.pause()
    settles(lambda: any(status.state is JobState.PAUSED for status in queue.jobs()))

    queue.resume()
    job.release.set()

    assert wait_for_state(listener, serial, JobState.DONE)
    assert job.finished
    assert listener.paused == [True, False]


def test_a_paused_queue_starts_no_further_job(queue: TaskQueue, settles: Callable[[Callable[[], bool]], None]) -> None:
    """Pause is about the queue, not only about the job that happened to be running.

    **Test steps:**

    * pause an empty queue, then enqueue a job
    * verify it stays queued
    * resume and verify it then runs
    """
    queue.pause()
    order: list[str] = []
    queue.enqueue(RecordingJob("waited", order))

    sleep(0.05)
    assert [status.state for status in queue.jobs()] == [JobState.QUEUED]

    queue.resume()
    settles(lambda: order == ["waited"])


def test_pausing_twice_is_reported_once(queue: TaskQueue, listener: RecordingListener) -> None:
    """A listener is told when something changed, not when something was asked for again.

    **Test steps:**

    * pause the queue twice, then resume it twice
    * verify exactly one pause and one resume were reported
    """
    queue.pause()
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


def test_cancelling_the_running_job_reaches_it_at_its_checkpoint(queue: TaskQueue, listener: RecordingListener) -> None:
    """What makes cancellation cooperative rather than a kill: the job unwinds itself.

    **Test steps:**

    * start a job that blocks and then checkpoints
    * cancel it, then release it into its checkpoint
    * verify it was reported cancelled and never reached the line past the checkpoint
    """
    gated = GatedJob()
    serial = queue.enqueue(gated)
    assert gated.entered.wait(TIMEOUT)

    queue.cancel(serial)
    gated.release.set()

    assert wait_for_state(listener, serial, JobState.CANCELLED)
    assert not gated.finished


def test_cancelling_a_parked_job_does_not_wait_for_a_resume(
    queue: TaskQueue, listener: RecordingListener, settles: Callable[[Callable[[], bool]], None]
) -> None:
    """A parked job waits on the same condition a cancel notifies, so it is reachable while paused.

    **Test steps:**

    * start a checkpointing job and pause the queue so it parks
    * cancel it without resuming
    * verify it was reported cancelled
    """
    job = CheckpointingJob()
    serial = queue.enqueue(job)
    assert job.entered.wait(TIMEOUT)
    queue.pause()
    settles(lambda: any(status.state is JobState.PAUSED for status in queue.jobs()))

    queue.cancel(serial)

    assert wait_for_state(listener, serial, JobState.CANCELLED)
    assert not job.finished


def test_a_job_that_never_checkpoints_is_still_reported_cancelled(
    queue: TaskQueue, listener: RecordingListener
) -> None:
    """It cannot be interrupted, and it must not read as done -- those are two different facts.

    **Test steps:**

    * start a job that never checkpoints
    * cancel it, then let it return of its own accord
    * verify it saw the cancellation and was reported cancelled rather than done
    """
    job = StubbornJob()
    serial = queue.enqueue(job)
    assert job.entered.wait(TIMEOUT)

    queue.cancel(serial)
    job.release.set()

    assert wait_for_state(listener, serial, JobState.CANCELLED)
    assert job.saw_cancellation


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
    """Same reason as the move: a cleared job's serial may still be in a view's hand.

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

# region Clearing


def test_clearing_drops_the_finished_and_keeps_the_rest(queue: TaskQueue, listener: RecordingListener) -> None:
    """Safe to offer while work is in flight, which is when a user reaches for it.

    **Test steps:**

    * run one job to completion, then hold a second running with a third queued behind it
    * clear the finished jobs
    * verify only the finished one was removed
    """
    finished = queue.enqueue(RecordingJob("finished"))
    assert wait_for_state(listener, finished, JobState.DONE)
    gated = GatedJob()
    running = queue.enqueue(gated)
    queued = queue.enqueue(RecordingJob("queued"))
    assert gated.entered.wait(TIMEOUT)

    queue.clear_finished()
    gated.release.set()

    assert listener.removed == [(finished,)]
    assert [status.serial for status in queue.jobs()] == [running, queued]


def test_clearing_nothing_says_nothing(queue: TaskQueue, listener: RecordingListener) -> None:
    """No event for a clear that removed nothing.

    **Test steps:**

    * clear an empty queue
    * verify nothing was reported removed
    """
    queue.clear_finished()

    assert listener.removed == []


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


def test_shutdown_reaches_a_paused_job(
    queue: TaskQueue, listener: RecordingListener, settles: Callable[[Callable[[], bool]], None]
) -> None:
    """The pause is released first, or a parked job would wait for a resume that is never coming.

    **Test steps:**

    * start a checkpointing job and pause the queue so it parks
    * shut the queue down
    * verify the job was cancelled and the queue was reported unpaused
    """
    job = CheckpointingJob()
    serial = queue.enqueue(job)
    assert job.entered.wait(TIMEOUT)
    queue.pause()
    settles(lambda: any(status.state is JobState.PAUSED for status in queue.jobs()))

    queue.shutdown()

    assert listener.states_of(serial)[-1] is JobState.CANCELLED
    assert listener.paused == [True, False]


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
