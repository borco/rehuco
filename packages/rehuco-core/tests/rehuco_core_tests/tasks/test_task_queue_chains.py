"""Tests for chains: one job at a time per chain, chains side by side (#563).

Kept apart from `test_task_queue.py`, whose fakes and fixtures it imports, because that module is past its size cap
and the subject here is one: which jobs wait for which. Every job is driven by events, as there, so a test asserts on
a state the workers demonstrably reached.
"""

import logging
from collections.abc import Callable, Iterator
from threading import Event, Thread
from threading import enumerate as live_threads
from time import sleep
from typing import Any, Final

import pytest
from pytest import fixture
from rehuco_core import DISK_CHAIN, ChainRegistry, JobCancelled, JobControl, JobState, TaskJobRegistry, TaskQueue
from rehuco_core.tasks import task_queue as task_queue_module

from .test_task_queue import (  # noqa: F401  # pylint: disable=unused-import
    TIMEOUT,
    GatedJob,
    RecordingJob,
    RecordingListener,
    SampleJob,
    listener_fixture,
    settles_fixture,
    started_since,
    wait_for_state,
)

CHAINS: Final = ChainRegistry()
"""The chain families these tests run in -- their own registry, never the app's."""

CHAINS.register(DISK_CHAIN)
A_CHAIN: Final = CHAINS.register("a").chain()
B_CHAIN: Final = CHAINS.register("b").chain()
SAVE_FAMILY: Final = CHAINS.register("save")


@fixture(name="queue")
def queue_fixture() -> Iterator[TaskQueue]:
    """A queue checking chains against this module's registry, always shut down.

    :returns: the queue under test.
    """
    queue = TaskQueue(CHAINS)
    yield queue
    queue.shutdown()


# region Sample classes


class ChainedJob(GatedJob):
    """A :class:`GatedJob` in a chain the test names.

    :param label: the job's label.
    :param chain: the chain it declares, or ``None`` for an unchained one.
    """

    def __init__(self, label: str, chain: str | None) -> None:
        super().__init__(label)
        self.chain = chain


class ChainedRecordingJob(RecordingJob):
    """A :class:`RecordingJob` in a chain the test names.

    :param label: the job's label.
    :param chain: the chain it declares.
    :param order: shared list each job appends its label to as it finishes.
    """

    def __init__(self, label: str, chain: str | None, order: list[str]) -> None:
        super().__init__(label, order)
        self.chain = chain


class SlowToCancelJob(SampleJob):
    """A job that checkpoints until cancelled and then takes a fixed time to unwind, as a job closing files does.

    :param label: the job's label.
    :param chain: the chain it declares, or ``None`` for an unchained one.
    :param unwind: how long it takes to stop once it has seen the cancel, in seconds.
    """

    def __init__(self, label: str, chain: str | None, unwind: float) -> None:
        super().__init__(label)
        self.chain = chain
        self.entered: Final = Event()
        self.__unwind: Final = unwind

    def run(self, control: JobControl) -> None:
        """Checkpoint until cancelled, then take the unwind time before reporting it.

        :param control: the engine's face to this job.
        """
        self.entered.set()
        try:
            while True:
                self.checkpoint()
                sleep(0.001)
        except JobCancelled:
            sleep(self.__unwind)
            raise


class OrphanChainJob(SampleJob):
    """A persistable job declaring a chain no family of this module owns -- a class whose family a build dropped.

    :param label: the job's label.
    """

    kind = "orphan-chain"
    chain = "dropped:nas"

    def __init__(self, label: str = "orphan") -> None:
        super().__init__(label)

    def run(self, control: JobControl) -> None:
        """Finish at once.

        :param control: the engine's face to this job.
        """
        del control

    def validate(self) -> str | None:
        """Always startable.

        :returns: ``None``.
        """
        return None

    def capture_state(self) -> dict[str, Any]:
        """Keep nothing.

        :returns: an empty state.
        """
        return {}

    def restore_state(self, state: dict[str, Any]) -> None:
        """Take nothing back.

        :param state: ignored.
        """
        del state


class RestorableJob(OrphanChainJob):
    """The same persistable job on the disk chain, which this module's registry owns."""

    kind = "restorable"
    chain = DISK_CHAIN


def running_lanes(queue: TaskQueue) -> int:
    """How many jobs the queue reports running at once.

    :param queue: the queue under test.
    :returns: the count of ``RUNNING`` rows.
    """
    return sum(1 for status in queue.jobs() if status.state is JobState.RUNNING)


def lane_workers(chain: str) -> list[Thread]:
    """The live worker threads serving ``chain``, found by the name the engine gives them.

    :param chain: the chain.
    :returns: its live workers.
    """
    return [thread for thread in live_threads() if thread.name == f"rehuco-task-queue:{chain}"]


# endregion

# region Declaring a chain


def test_a_job_that_names_no_chain_runs_on_the_disk_chain(queue: TaskQueue, listener: RecordingListener) -> None:
    """Every job that has not thought about it keeps taking turns as before.

    **Test steps:**

    * enqueue a plain recording job
    * verify its status carries the disk chain
    """
    serial = queue.enqueue(RecordingJob("plain"))

    assert wait_for_state(listener, serial, JobState.DONE)
    assert queue.jobs()[0].chain == DISK_CHAIN


def test_a_jobs_chain_is_carried_on_its_status(queue: TaskQueue) -> None:
    """The chain is read once at enqueue, like every declaration but ``source``.

    **Test steps:**

    * enqueue a held job in a named chain and an unchained one
    * verify each status carries what the job declared
    * release both
    """
    named = ChainedJob("named", SAVE_FAMILY.chain("nas"))
    unchained = ChainedJob("free", None)
    queue.enqueue(named)
    queue.enqueue(unchained)

    assert [status.chain for status in queue.jobs()] == ["save:nas", None]
    named.release.set()
    unchained.release.set()


# endregion

# region Which jobs wait


def test_jobs_of_one_chain_take_turns_in_queue_order(
    queue: TaskQueue, settles: Callable[[Callable[[], bool]], None]
) -> None:
    """Serial per chain: the second job of a chain does not start while the first runs.

    **Test steps:**

    * hold a job of chain ``a`` running, and enqueue a second held job and a third of ``a``
    * verify the second has not started after a short wait, both later jobs still queued
    * release the first and verify the second starts; release it and verify the third finishes last
    """
    order: list[str] = []
    first, second = ChainedJob("first", A_CHAIN), ChainedJob("second", A_CHAIN)
    queue.enqueue(first)
    assert first.entered.wait(TIMEOUT)
    queue.enqueue(second)
    queue.enqueue(ChainedRecordingJob("third", A_CHAIN, order))

    assert not second.entered.wait(0.05)
    assert [status.state for status in queue.jobs()][1:] == [JobState.QUEUED, JobState.QUEUED]
    first.release.set()
    assert second.entered.wait(TIMEOUT)
    assert not order
    second.release.set()
    settles(lambda: order == ["third"])


def test_a_job_of_another_chain_runs_beside_a_running_one(queue: TaskQueue) -> None:
    """A save to a share lands beside a sweep of the disks rather than behind it.

    **Test steps:**

    * hold a disk-chain job running
    * enqueue a job in another chain
    * verify it starts while the first is still held, and both read as running
    * release both
    """
    sweep = ChainedJob("sweep", DISK_CHAIN)
    queue.enqueue(sweep)
    assert sweep.entered.wait(TIMEOUT)
    save = ChainedJob("save", SAVE_FAMILY.chain("nas"))

    queue.enqueue(save)

    assert save.entered.wait(TIMEOUT)
    assert running_lanes(queue) == 2
    save.release.set()
    sweep.release.set()


def test_unchained_jobs_each_run_at_once(queue: TaskQueue) -> None:
    """``None`` takes turns with nothing: two unchained jobs run together, beside a chained one.

    **Test steps:**

    * hold a disk-chain job running
    * enqueue two unchained jobs
    * verify both start while the first is held, three running at once
    * release all three
    """
    held = ChainedJob("held", DISK_CHAIN)
    queue.enqueue(held)
    assert held.entered.wait(TIMEOUT)
    free = [ChainedJob("free one", None), ChainedJob("free two", None)]

    for job in free:
        queue.enqueue(job)

    assert all(job.entered.wait(TIMEOUT) for job in free)
    assert running_lanes(queue) == 3
    for job in (*free, held):
        job.release.set()


def test_waiting_for_idle_waits_for_every_chain(queue: TaskQueue) -> None:
    """Quitting writes the queue once *nothing* runs, not once one chain is quiet.

    **Test steps:**

    * hold one job running in each of two chains
    * release one and verify the queue is still not idle
    * release the other and verify it is
    """
    left, right = ChainedJob("left", A_CHAIN), ChainedJob("right", B_CHAIN)
    queue.enqueue(left)
    queue.enqueue(right)
    assert left.entered.wait(TIMEOUT) and right.entered.wait(TIMEOUT)

    left.release.set()
    assert not queue.wait_until_idle(0.05)

    right.release.set()
    assert queue.wait_until_idle(TIMEOUT)


# endregion

# region Stopping one job, whatever its chain


def test_pausing_a_job_leaves_another_chains_job_running(queue: TaskQueue, listener: RecordingListener) -> None:
    """A pause is asked of one entry; the other chain's job is not touched.

    **Test steps:**

    * hold one job running in each of two chains
    * pause the first and release it, so it unwinds at its checkpoint
    * verify it is paused while the second is still running
    * release the second and verify it finishes
    """
    paused, running = ChainedJob("paused", A_CHAIN), ChainedJob("running", B_CHAIN)
    paused_serial = queue.enqueue(paused)
    running_serial = queue.enqueue(running)
    assert paused.entered.wait(TIMEOUT) and running.entered.wait(TIMEOUT)

    queue.pause_job(paused_serial)
    paused.release.set()

    assert wait_for_state(listener, paused_serial, JobState.PAUSED)
    assert queue.jobs()[1].state is JobState.RUNNING
    running.release.set()
    assert wait_for_state(listener, running_serial, JobState.DONE)


def test_cancelling_and_removing_act_on_one_entry_whatever_its_chain(
    queue: TaskQueue, listener: RecordingListener
) -> None:
    """Cancel and remove reach a job in any chain, and only that job.

    **Test steps:**

    * hold one job running in each of two chains
    * cancel the first and remove the second, releasing both
    * verify the first is cancelled, the second is gone, and nothing else changed
    """
    cancelled, removed = ChainedJob("cancelled", A_CHAIN), ChainedJob("removed", B_CHAIN)
    cancelled_serial = queue.enqueue(cancelled)
    removed_serial = queue.enqueue(removed)
    assert cancelled.entered.wait(TIMEOUT) and removed.entered.wait(TIMEOUT)

    queue.cancel(cancelled_serial)
    queue.remove(removed_serial)
    cancelled.release.set()
    removed.release.set()

    assert wait_for_state(listener, cancelled_serial, JobState.CANCELLED)
    assert [status.serial for status in queue.jobs()] == [cancelled_serial]
    assert listener.removed == [(removed_serial,)]


# endregion

# region Workers coming and going


def test_a_chains_worker_goes_once_idle_and_a_new_one_serves_the_next_job(
    queue: TaskQueue, listener: RecordingListener, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A chain nobody uses costs no thread, and work arriving later is still served.

    **Test steps:**

    * shorten the idle wait, then run one job in chain ``a`` to the end
    * verify the chain's worker thread exits
    * enqueue another job in ``a`` and verify it runs on a fresh worker
    """
    monkeypatch.setattr(task_queue_module, "WORKER_IDLE_SECONDS", 0.01)
    first = queue.enqueue(ChainedRecordingJob("first", A_CHAIN, []))
    assert wait_for_state(listener, first, JobState.DONE)
    for worker in lane_workers(A_CHAIN):
        worker.join(TIMEOUT)
    assert not lane_workers(A_CHAIN)

    second = queue.enqueue(ChainedRecordingJob("second", A_CHAIN, []))

    assert wait_for_state(listener, second, JobState.DONE)


def test_retrying_a_job_in_an_idle_chain_runs_it(
    queue: TaskQueue,
    listener: RecordingListener,
    settles: Callable[[Callable[[], bool]], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retry starts a worker for a chain whose worker has already gone.

    **Test steps:**

    * shorten the idle wait, run a job of chain ``a`` to the end and let its worker exit
    * retry the job
    * verify it runs again and is done
    """
    monkeypatch.setattr(task_queue_module, "WORKER_IDLE_SECONDS", 0.01)
    order: list[str] = []
    serial = queue.enqueue(ChainedRecordingJob("again", A_CHAIN, order))
    assert wait_for_state(listener, serial, JobState.DONE)
    for worker in lane_workers(A_CHAIN):
        worker.join(TIMEOUT)

    queue.retry(serial)

    settles(lambda: order == ["again", "again"])
    settles(lambda: queue.jobs()[0].state is JobState.DONE)


def test_resuming_a_paused_job_in_an_idle_chain_runs_it(
    queue: TaskQueue, listener: RecordingListener, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resume starts a worker for a chain whose worker has already gone.

    **Test steps:**

    * shorten the idle wait, pause the queue, then enqueue a job of chain ``a`` and pause it before it runs
    * let the chain's worker exit
    * resume the job and verify it runs to the end
    """
    monkeypatch.setattr(task_queue_module, "WORKER_IDLE_SECONDS", 0.01)
    order: list[str] = []
    held = ChainedJob("held", A_CHAIN)
    queue.enqueue(held)
    assert held.entered.wait(TIMEOUT)
    waiting = queue.enqueue(ChainedRecordingJob("waiting", A_CHAIN, order))
    queue.pause_job(waiting)
    held.release.set()
    assert queue.wait_until_idle(TIMEOUT)
    for worker in lane_workers(A_CHAIN):
        worker.join(TIMEOUT)
    assert not lane_workers(A_CHAIN)

    queue.resume_job(waiting)

    assert wait_for_state(listener, waiting, JobState.DONE)
    assert order == ["waiting"]


def test_shutdown_joins_every_chains_worker(queue: TaskQueue) -> None:
    """Quitting waits for every chain's job to unwind, not only the first one's.

    **Test steps:**

    * run one job in each of three lanes -- two chains and an unchained job -- each taking longer than the one
      before it to unwind from a cancel
    * shut down
    * verify no thread started since before is still alive: the later jobs were waited for too
    """
    before = set(live_threads())
    jobs = [
        SlowToCancelJob("a", A_CHAIN, 0.05),
        SlowToCancelJob("b", B_CHAIN, 0.15),
        SlowToCancelJob("free", None, 0.25),
    ]
    for job in jobs:
        queue.enqueue(job)
    assert all(job.entered.wait(TIMEOUT) for job in jobs)

    queue.shutdown()

    assert not started_since(before)


def test_retrying_after_shutdown_starts_no_worker(queue: TaskQueue, listener: RecordingListener) -> None:
    """A queue that has been shut down starts no thread, even for a retry that puts a job back in line.

    **Test steps:**

    * run a job to the end and shut the queue down
    * retry the job
    * verify no worker thread was started and the job never runs again
    """
    order: list[str] = []
    serial = queue.enqueue(ChainedRecordingJob("late", A_CHAIN, order))
    assert wait_for_state(listener, serial, JobState.DONE)
    queue.shutdown()
    before = set(live_threads())

    queue.retry(serial)

    assert not started_since(before)
    assert order == ["late"]


# endregion


# region Chains only a family hands out


def test_a_job_in_a_chain_no_family_owns_is_refused(queue: TaskQueue, listener: RecordingListener) -> None:
    """Two kinds of job cannot share a chain by spelling it alike, nor a typo run one beside the work it waits for.

    **Test steps:**

    * enqueue a job whose chain names no registered family
    * verify the enqueue raises, naming the chain
    * verify nothing was added and no listener was told
    """
    before = set(live_threads())

    with pytest.raises(ValueError, match="'nas'"):
        queue.enqueue(ChainedJob("typo", "nas"))

    assert queue.jobs() == ()
    assert not listener.enqueued
    assert not started_since(before)


def test_a_key_another_family_would_spell_is_refused_unless_that_family_is_registered(queue: TaskQueue) -> None:
    """A key is owned by the family whose name it starts with, so ``other:a`` is not chain ``a``'s.

    **Test steps:**

    * enqueue a job whose chain starts with an unregistered family's name and holds a registered one's after it
    * verify it is refused
    """
    with pytest.raises(ValueError, match="no chain family owns"):
        queue.enqueue(ChainedJob("borrowed", f"other:{A_CHAIN}"))


def test_restoring_a_job_whose_chain_family_is_gone_drops_that_job_only(
    queue: TaskQueue, caplog: pytest.LogCaptureFixture
) -> None:
    """A saved job whose family this build no longer registers is one dropped row, never a failed start.

    **Test steps:**

    * restore two saved items: one of a job in an unowned chain, one plain recording job's kind
    * verify only the second came back, and the drop was logged
    """
    registry = TaskJobRegistry()
    registry.register(OrphanChainJob.kind, OrphanChainJob)
    registry.register(RestorableJob.kind, RestorableJob)

    with caplog.at_level(logging.WARNING):
        serials = queue.restore(
            [
                {"kind": OrphanChainJob.kind, "label": "orphan", "job_state": "paused", "state": {}},
                {"kind": RestorableJob.kind, "label": "kept", "job_state": "paused", "state": {}},
            ],
            registry,
        )

    assert len(serials) == 1
    assert [status.label for status in queue.jobs()] == ["kept"]
    assert "dropped:nas" in caplog.text


# endregion
