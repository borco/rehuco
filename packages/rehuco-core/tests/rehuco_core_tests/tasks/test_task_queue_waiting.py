"""Tests for a job that waits: :class:`~rehuco_core.JobWaiting`, the ``waiting`` state, and what each control does to
a waiting row (#497), with the two small lookups the same issue added -- a status's ``kind`` and
:meth:`~rehuco_core.TaskQueue.job`.

Kept apart from `test_task_queue.py`, whose fakes and fixtures it imports, because that module is past its size cap.
**The engine's clock is frozen** (``clock``): a waiting job is due when the test moves that clock, never when real
time happens to pass, so *not yet due* and *due* are both states the test put the queue in. The worker still sleeps
real time between looks at the clock, which is why a wait is :data:`SHORT_WAIT` long.
"""

from collections.abc import Iterator
from threading import Event
from typing import Final

import pytest
from pytest import fixture
from rehuco_core import DISK_CHAIN, ChainRegistry, JobControl, JobState, JobWaiting, TaskQueue
from rehuco_core.tasks import task_queue as task_queue_module

from .test_task_queue import (  # noqa: F401  # pylint: disable=unused-import
    TIMEOUT,
    RecordingJob,
    RecordingListener,
    SampleJob,
    listener_fixture,
    wait_for_state,
)
from .test_task_queue_chains import ChainedJob, lane_workers
from .test_task_queue_persistence import CounterJob

CHAINS: Final = ChainRegistry()
"""The chain families these tests run in -- their own registry, never the app's."""

CHAINS.register(DISK_CHAIN)
LANE: Final = CHAINS.register("waiting-lane").chain()
"""The chain every waiting job below takes turns in, named so its worker thread is this module's alone."""

REASON: Final = "The share does not answer."
"""What every waiting job below says it waits for."""

SHORT_WAIT: Final = 0.01
"""How long a waiting job asks to wait, in seconds -- on the frozen clock, and the real time the worker sleeps between
looks at it."""

NOT_YET: Final = 0.05
"""How long a test watches for something that must not happen, in seconds."""


# region Sample classes


class FrozenClock:
    """A stand-in for :func:`time.monotonic` that moves only when the test moves it.

    :param start: the time it reads until moved.
    """

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        """Read the clock.

        :returns: the time it is set to.
        """
        return self.now

    def advance(self, seconds: float) -> None:
        """Move the clock forward.

        :param seconds: how far.
        """
        self.now += seconds


class WaitingJob(SampleJob):
    """A job that reports it cannot proceed on its first run and finishes, or fails, on the next.

    :param label: the job's label.
    :param fails: whether the run after the wait raises instead of finishing.
    """

    def __init__(self, label: str = "waiting", fails: bool = False) -> None:
        super().__init__(label)
        self.chain = LANE
        self.runs = 0
        self.reran: Final = Event()
        self.__fails: Final = fails

    def run(self, control: JobControl) -> None:
        """Wait the first time, then finish or fail.

        :param control: the engine's face to this job.
        :raises JobWaiting: on the first run.
        :raises RuntimeError: on a later run, when built to fail.
        """
        del control
        self.runs += 1
        if self.runs == 1:
            raise JobWaiting(REASON, SHORT_WAIT)
        self.reran.set()
        if self.__fails:
            raise RuntimeError("the share refused the write")


class GatedWaitingJob(SampleJob):
    """A job the test holds mid-run, which then reports it must wait -- without ever looking at a stop request.

    :param label: the job's label.
    """

    def __init__(self, label: str = "gated-waiting") -> None:
        super().__init__(label)
        self.chain = LANE
        self.entered: Final = Event()
        self.release: Final = Event()

    def run(self, control: JobControl) -> None:
        """Announce, wait for the test, then report a wait.

        :param control: the engine's face to this job.
        :raises JobWaiting: always.
        """
        del control
        self.entered.set()
        self.release.wait(TIMEOUT)
        raise JobWaiting(REASON, SHORT_WAIT)


def status_in(listener: RecordingListener, serial: int, state: JobState) -> int:
    """Where in the listener's updates ``serial`` was first reported in ``state``.

    :param listener: the attached listener.
    :param serial: which job.
    :param state: the state looked for.
    :returns: the index into :attr:`RecordingListener.updated`.
    """
    return next(
        index for index, status in enumerate(listener.updated) if status.serial == serial and status.state is state
    )


def waiting_beside_paused(queue: TaskQueue, listener: RecordingListener) -> tuple[int, int]:
    """Put one job of :data:`LANE` in ``waiting`` and another in ``paused``.

    :param queue: the queue under test.
    :param listener: the attached listener.
    :returns: the waiting job's serial and the paused one's.
    """
    waiting = queue.enqueue(WaitingJob())
    assert wait_for_state(listener, waiting, JobState.WAITING)
    held = ChainedJob("held", LANE)
    paused = queue.enqueue(held)
    assert held.entered.wait(TIMEOUT)
    queue.pause_job(paused)
    held.release.set()
    assert wait_for_state(listener, paused, JobState.PAUSED)
    return waiting, paused


# endregion

# region Fixtures


@fixture(name="clock")
def clock_fixture(monkeypatch: pytest.MonkeyPatch) -> FrozenClock:
    """The engine's monotonic clock, frozen until the test moves it.

    :param monkeypatch: what swaps the engine module's own ``monotonic`` name.
    :returns: the clock.
    """
    clock = FrozenClock()
    monkeypatch.setattr(task_queue_module, "monotonic", clock)
    return clock


@fixture(name="queue")
def queue_fixture(clock: FrozenClock) -> Iterator[TaskQueue]:
    """A queue checking chains against this module's registry, on the frozen clock, always shut down.

    :param clock: the frozen clock, patched in before the queue exists.
    :returns: the queue under test.
    """
    del clock
    queue = TaskQueue(CHAINS)
    yield queue
    queue.shutdown()


# endregion

# region Waiting and coming back


def test_a_job_that_waits_is_held_with_its_reason_until_its_wait_ends(
    queue: TaskQueue, listener: RecordingListener, clock: FrozenClock
) -> None:
    """The row says what the job waits for, and the job runs again once -- and only once -- the clock says so.

    **Test steps:**

    * enqueue a job that waits on its first run
    * verify it is reported waiting with its reason and no stop request, and is not run again meanwhile
    * move the clock to exactly when its wait ends
    * verify it went back in line with its reason cleared, ran again and finished
    """
    job = WaitingJob()
    serial = queue.enqueue(job)
    assert wait_for_state(listener, serial, JobState.WAITING)
    waiting = listener.updated[status_in(listener, serial, JobState.WAITING)]
    assert (waiting.message, waiting.stop_requested) == (REASON, None)
    assert not job.reran.wait(NOT_YET)

    clock.advance(SHORT_WAIT)

    assert wait_for_state(listener, serial, JobState.DONE)
    assert listener.states_of(serial) == [
        JobState.RUNNING,
        JobState.WAITING,
        JobState.QUEUED,
        JobState.RUNNING,
        JobState.DONE,
    ]
    assert listener.updated[status_in(listener, serial, JobState.QUEUED)].message is None
    assert job.runs == 2


def test_a_lanes_worker_stays_while_a_job_waits_and_goes_after(
    queue: TaskQueue, listener: RecordingListener, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A lane holding a waiting job is never idle: its one thread is what ends the wait.

    **Test steps:**

    * shorten the idle wait, and enqueue a job that waits
    * verify the lane's worker is still alive well past the idle wait, the clock not having moved
    * move the clock past the wait and verify the job finishes
    * verify the worker then goes, idle
    """
    monkeypatch.setattr(task_queue_module, "WORKER_IDLE_SECONDS", 0.001)
    serial = queue.enqueue(WaitingJob())
    assert wait_for_state(listener, serial, JobState.WAITING)
    (worker,) = lane_workers(LANE)

    worker.join(NOT_YET)
    assert worker.is_alive()

    clock.advance(SHORT_WAIT)
    assert wait_for_state(listener, serial, JobState.DONE)
    worker.join(TIMEOUT)
    assert not worker.is_alive()


# endregion

# region What each control does to a waiting row


def test_resuming_a_waiting_job_tries_it_now(queue: TaskQueue, listener: RecordingListener) -> None:
    """*Try now*: a resume puts a waiting job back in line at once, without its wait ending.

    **Test steps:**

    * let a job wait, the clock frozen
    * resume it
    * verify the resume reports it was taken, the row went back in line with its reason cleared, and the job finished
    """
    serial = queue.enqueue(WaitingJob())
    assert wait_for_state(listener, serial, JobState.WAITING)

    assert queue.resume_job(serial) is True

    assert wait_for_state(listener, serial, JobState.DONE)
    assert listener.states_of(serial)[2] is JobState.QUEUED
    assert listener.updated[status_in(listener, serial, JobState.QUEUED)].message is None


def test_pausing_a_waiting_job_holds_it_past_its_wait(
    queue: TaskQueue, listener: RecordingListener, clock: FrozenClock
) -> None:
    """A pause aimed at one waiting row holds it, and its wait ending no longer brings it back.

    **Test steps:**

    * let a job wait, then pause it
    * verify it is paused with no reason left on it
    * move the clock past its wait and verify it is not run
    * resume it and verify it runs again
    """
    job = WaitingJob()
    serial = queue.enqueue(job)
    assert wait_for_state(listener, serial, JobState.WAITING)

    queue.pause_job(serial)

    status = queue.jobs()[0]
    assert (status.state, status.message) == (JobState.PAUSED, None)
    clock.advance(1.0)
    assert not job.reran.wait(NOT_YET)
    queue.resume_job(serial)
    assert job.reran.wait(TIMEOUT)


def test_cancelling_a_waiting_job_ends_it(queue: TaskQueue, listener: RecordingListener, clock: FrozenClock) -> None:
    """A cancel aimed at a waiting row ends it for good, and its reason with it.

    **Test steps:**

    * let a job wait, then cancel it
    * verify it is cancelled with no reason left on it
    * move the clock past its wait and verify it is not run
    """
    job = WaitingJob()
    serial = queue.enqueue(job)
    assert wait_for_state(listener, serial, JobState.WAITING)

    queue.cancel(serial)

    status = queue.jobs()[0]
    assert (status.state, status.message) == (JobState.CANCELLED, None)
    clock.advance(1.0)
    assert not job.reran.wait(NOT_YET)


def test_pausing_the_queue_leaves_a_waiting_job_waiting(
    queue: TaskQueue, listener: RecordingListener, clock: FrozenClock
) -> None:
    """The bulk pause is the user's hold; a wait is the job's own, so the job still lands by itself.

    **Test steps:**

    * let a job wait, then pause the whole queue
    * verify the job still waits with its reason, and the queue does not read as paused
    * move the clock past its wait and verify the job finishes
    """
    serial = queue.enqueue(WaitingJob())
    assert wait_for_state(listener, serial, JobState.WAITING)

    queue.pause()

    status = queue.jobs()[0]
    assert (status.state, status.message) == (JobState.WAITING, REASON)
    assert queue.paused is False
    clock.advance(SHORT_WAIT)
    assert wait_for_state(listener, serial, JobState.DONE)


def test_shutting_down_leaves_a_waiting_job_waiting(queue: TaskQueue, listener: RecordingListener) -> None:
    """A job waiting for its share when the queue shuts down is still waiting -- the state the exit sequence wrote down,
    so a save waiting for its share comes back waiting, not cancelled (#497).

    **Test steps:**

    * let a job wait, then shut the queue down
    * verify it still waits with its reason, and was told nothing more
    """
    serial = queue.enqueue(WaitingJob())
    assert wait_for_state(listener, serial, JobState.WAITING)
    told = len(listener.states_of(serial))

    queue.shutdown()

    status = queue.jobs()[0]
    assert (status.state, status.message) == (JobState.WAITING, REASON)
    assert len(listener.states_of(serial)) == told


def test_the_queue_reads_as_paused_with_a_job_still_waiting(queue: TaskQueue, listener: RecordingListener) -> None:
    """A waiting row is not one a bulk pause can reach, so it does not keep the Pause control from reading *paused*.

    **Test steps:**

    * hold one job waiting and another paused
    * verify the queue reads as paused
    """
    waiting_beside_paused(queue, listener)

    assert queue.paused is True


def test_resuming_the_queue_leaves_a_waiting_job_waiting(queue: TaskQueue, listener: RecordingListener) -> None:
    """The bulk resume ends the holds the user placed, not a wait nobody asked for.

    **Test steps:**

    * hold one job waiting and another paused
    * resume the whole queue
    * verify the waiting job still waits with its reason, and the paused one ran to the end
    """
    waiting, paused = waiting_beside_paused(queue, listener)

    queue.resume()

    status = queue.jobs()[0]
    assert (status.serial, status.state, status.message) == (waiting, JobState.WAITING, REASON)
    assert wait_for_state(listener, paused, JobState.DONE)


@pytest.mark.parametrize(
    ("ask", "landed"),
    [("pause_job", JobState.PAUSED), ("cancel", JobState.CANCELLED)],
)
def test_a_stop_asked_during_a_run_that_then_waits_is_obeyed(
    queue: TaskQueue, listener: RecordingListener, ask: str, landed: JobState
) -> None:
    """The user's word beats the job's wait: a run that reports *not now* after a pause or cancel lands as that.

    **Test steps:**

    * hold a job mid-run, ask it to pause or cancel, then let it report a wait without looking at the request
    * verify it landed paused or cancelled, never waiting, with no reason and no request left on it
    """
    job = GatedWaitingJob()
    serial = queue.enqueue(job)
    assert job.entered.wait(TIMEOUT)

    getattr(queue, ask)(serial)
    job.release.set()

    assert wait_for_state(listener, serial, landed)
    status = queue.jobs()[0]
    assert (status.message, status.stop_requested) == (None, None)
    assert JobState.WAITING not in listener.states_of(serial)


def test_a_waiting_job_can_be_moved(queue: TaskQueue, listener: RecordingListener) -> None:
    """A waiting job is still waiting its turn, so it is as reorderable as a queued one.

    **Test steps:**

    * let two jobs of one lane wait
    * move the second to the top
    * verify the new order was announced
    """
    first = queue.enqueue(WaitingJob("first"))
    second = queue.enqueue(WaitingJob("second"))
    assert wait_for_state(listener, first, JobState.WAITING)
    assert wait_for_state(listener, second, JobState.WAITING)

    queue.move(second, 0)

    assert listener.reordered == [(second, first)]


def test_retrying_a_job_that_waited_and_then_failed_clears_its_reason(
    queue: TaskQueue, listener: RecordingListener, clock: FrozenClock
) -> None:
    """Retry puts a job back in line with nothing left of how its last run ended.

    **Test steps:**

    * let a job wait, move the clock past its wait, and let its next run fail
    * retry it
    * verify the row it went back in line as carries no reason
    """
    serial = queue.enqueue(WaitingJob(fails=True))
    assert wait_for_state(listener, serial, JobState.WAITING)
    clock.advance(SHORT_WAIT)
    assert wait_for_state(listener, serial, JobState.FAILED)
    failed_at = status_in(listener, serial, JobState.FAILED)
    assert listener.updated[failed_at].message == "RuntimeError: the share refused the write"

    queue.retry(serial)

    requeued = next(
        status for status in listener.updated[failed_at:] if status.serial == serial and status.state is JobState.QUEUED
    )
    assert requeued.message is None


# endregion

# region Looking a job up


def test_a_status_names_a_persistable_jobs_kind_and_no_kind_for_another(queue: TaskQueue) -> None:
    """A surface picks one family of rows out by kind, without holding the job objects.

    **Test steps:**

    * enqueue a persistable job and one that is not
    * verify the first row carries the job's kind and the second none
    """
    queue.enqueue(CounterJob("saved"))
    queue.enqueue(RecordingJob("plain"))

    assert [status.kind for status in queue.jobs()] == [CounterJob.kind, None]


def test_a_job_is_found_by_its_serial(queue: TaskQueue) -> None:
    """The surface owning a kind of job reaches the object behind a row, and an unknown serial finds nothing.

    **Test steps:**

    * enqueue a job
    * verify its serial finds that very job, and a serial no row has finds ``None``
    """
    job = RecordingJob("found")
    serial = queue.enqueue(job)

    assert queue.job(serial) is job
    assert queue.job(serial + 1000) is None


# endregion
