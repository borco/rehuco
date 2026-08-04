"""Tests for what survives a restart: serialization, restoration, and validation on start (#238).

Kept apart from `test_task_queue.py` because the subject is different -- that file is about what the
engine *does* with jobs, this one is about what it writes down and what it can build again -- and
because every fake here is persistable, which none of that file's are.

**No test asserts on a cursor** ([[appendices.task-queue#job-responsibility]]), here either. What a job
kept is observed through the state it handed over and through where its ``run`` picked up, never by
reaching into the job.
"""

import logging
from collections.abc import Callable, Iterator
from threading import Event
from time import monotonic, sleep
from typing import Any, Final

import pytest
from pytest import fixture
from rehuco_core import (
    JobControl,
    JobState,
    TaskJobBase,
    TaskJobRegistry,
    TaskQueue,
    TaskQueueItem,
)

TIMEOUT: Final = 5.0
"""How long a test waits for the worker before calling it a failure, in seconds. A deadlock detector,
not a measurement -- every wait below ends the moment its condition holds."""


# region Sample classes


# eleven, and this is one test double standing in for four jobs: the work, the two gates, the cursor,
# the two records the assertions read, and the knobs that make it resume, hold or refuse to start.
# pylint: disable-next=too-many-instance-attributes
class CounterJob(TaskJobBase):
    """A persistable job that counts to :attr:`units`, and whose whole state is how far it got.

    The one fake the persistence tests need, because a saved job is only interesting when it has
    something to save. It can be held mid-run (``hold_after``), can refuse to start (``refusal``), and
    can be told whether it carries on or starts over -- which is the declaration that decides whether
    its progress is written down at all.

    :param label: the job's label.
    :param units: how far to count.
    :param resumes: what to declare as :attr:`resumes_where_it_stopped`.
    :param hold_after: how many units to do before announcing :attr:`reached` and waiting on
        :attr:`release`, or ``None`` to run straight through.
    :param refusal: what ``validate`` should object with, or ``None`` to accept every start.
    """

    # its counting loop is `test_task_queue.py`'s CursorJob's, deliberately: that file's fakes prove
    # what pausing does and this one's prove what is written down, and making them share a base would
    # couple two files that must be free to describe different things.
    # pylint: disable=duplicate-code

    kind = "counter"

    def __init__(
        self,
        label: str = "counter",
        units: int = 4,
        resumes: bool = False,
        hold_after: int | None = None,
        refusal: str | None = None,
    ) -> None:
        super().__init__()
        self.label = label
        self.resumes_where_it_stopped = resumes
        self.refusal = refusal
        self.__units: Final = units
        self.__hold_after: Final = hold_after
        self.__cursor = 0
        self.__running = False
        self.entered_at: Final[list[int]] = []
        self.captured_while_running: Final[list[bool]] = []
        self.reached: Final = Event()
        self.release: Final = Event()

    def validate(self) -> str | None:
        """Object if this job was built to.

        :returns: the refusal it was given, or ``None``.
        """
        return self.refusal

    def capture_state(self) -> dict[str, Any]:
        """Hand over the cursor, and record whether the engine asked while ``run`` was executing.

        :returns: the state to write down.
        """
        self.captured_while_running.append(self.__running)
        return {"cursor": self.__cursor}

    def restore_state(self, state: dict[str, Any]) -> None:
        """Take the cursor back.

        :param state: what :meth:`capture_state` wrote.
        """
        self.__cursor = int(state["cursor"])

    def reset(self) -> None:
        """Throw the cursor away, so a retried job counts from the top again."""
        super().reset()
        self.__cursor = 0

    def run(self, control: JobControl) -> None:
        """Count from the cursor to ``units``, checkpointing once per unit.

        :param control: the engine's face to this job.
        """
        self.__running = True
        try:
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
        finally:
            self.__running = False


class PlainJob(TaskJobBase):
    """A job that is not persistable -- the opt-out the design has to keep working.

    :param label: the job's label.
    """

    def __init__(self, label: str = "plain") -> None:
        super().__init__()
        self.label = label

    def run(self, control: JobControl) -> None:
        """Do one unit of nothing.

        :param control: the engine's face to this job.
        """
        control.report(1, 1)


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


@fixture(name="registry")
def registry_fixture() -> TaskJobRegistry:
    """A registry holding the one kind these tests save and restore.

    :returns: a registry of its own, never the app-wide default.
    """
    registry = TaskJobRegistry()
    registry.register(CounterJob.kind, CounterJob)
    return registry


@fixture(name="settles")
def settles_fixture() -> Callable[[Callable[[], bool]], None]:
    """A wait for something the worker does on its own.

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

# region Serializing


def test_a_finished_job_is_written_down_too(queue: TaskQueue, settles: Callable[[Callable[[], bool]], None]) -> None:
    """Jobs leave only when removed, so dropping the finished ones at quit would be an implicit removal.

    **Test steps:**

    * run one job to completion
    * serialize the queue
    * verify the done job is in the file with the state it ended in
    """
    queue.enqueue(CounterJob("done-one"))

    settles(lambda: all(status.state is JobState.DONE for status in queue.jobs()))
    items = queue.serialize()

    assert [item["label"] for item in items] == ["done-one"]
    assert items[0]["job_state"] == JobState.DONE.value


def test_a_job_that_is_not_persistable_is_skipped_and_says_so(queue: TaskQueue) -> None:
    """The opt-out has to survive, and has to be visible on the row rather than discovered at quit.

    **Test steps:**

    * enqueue a persistable job and one that is not
    * verify only the persistable one is written down
    * verify each row declares which it is
    """
    queue.pause()
    persistable = queue.enqueue(CounterJob("saved"))
    plain = queue.enqueue(PlainJob("lost"))

    items = queue.serialize()

    assert [item["label"] for item in items] == ["saved"]
    declared = {status.serial: status.persistable for status in queue.jobs()}
    assert declared[persistable] is True
    assert declared[plain] is False


def test_progress_is_written_only_for_a_job_that_carries_on(
    queue: TaskQueue, settles: Callable[[Callable[[], bool]], None]
) -> None:
    """A bar is restored only where it is still true; for a job that starts over it is about to reset.

    **Test steps:**

    * pause one job that resumes where it stopped part-way through, and one that starts over
    * serialize the queue
    * verify the resuming job's progress is written and the other's is absent
    """
    resuming = CounterJob("resuming", units=4, resumes=True, hold_after=2)
    starting_over = CounterJob("starting-over", units=4, hold_after=2)
    for job in (resuming, starting_over):
        serial = queue.enqueue(job)
        assert job.reached.wait(TIMEOUT)
        queue.pause_job(serial)
        job.release.set()
        settles(lambda: any(status.state is JobState.PAUSED for status in queue.jobs()))

    items = {item["label"]: item for item in queue.serialize()}

    assert items["resuming"].get("done") == 2
    assert items["resuming"].get("total") == 4
    assert "done" not in items["starting-over"]
    assert "total" not in items["starting-over"]


def test_the_running_job_is_written_from_what_it_last_gave_the_queue(queue: TaskQueue) -> None:
    """``capture_state`` is specified as called only when the job is not running -- and it is.

    A queue written *while* work is going on is the ordinary case, since every enqueue writes one; the
    running job is still in the file, as of the last moment it could safely be asked.

    **Test steps:**

    * hold one job mid-run
    * serialize the queue
    * verify the running job is written down, and was never asked while it was running
    """
    running = CounterJob("running", units=4, resumes=True, hold_after=2)
    queue.enqueue(running)

    assert running.reached.wait(TIMEOUT)
    items = queue.serialize()
    running.release.set()

    assert [item["label"] for item in items] == ["running"]
    assert items[0]["state"] == {"cursor": 0}
    assert running.captured_while_running == [False]


def test_a_job_that_cannot_say_what_it_would_need_is_skipped_and_logged(
    queue: TaskQueue, caplog: pytest.LogCaptureFixture
) -> None:
    """The queue is still worth writing; a state the job could not produce is not one worth inventing.

    **Test steps:**

    * hold the queue and enqueue a job whose ``capture_state`` raises
    * serialize the queue
    * verify that job is absent from the file, that the other one is in it, and that the failure was
      logged
    """

    class SpeechlessJob(CounterJob):
        """A job that cannot hand over its state."""

        def capture_state(self) -> dict[str, Any]:
            """Raise instead of answering.

            :raises RuntimeError: always.
            """
            raise RuntimeError("nothing to say")

    queue.pause()
    with caplog.at_level(logging.ERROR):
        queue.enqueue(SpeechlessJob("speechless"))
        queue.enqueue(CounterJob("ordinary"))

        items = queue.serialize()

    assert [item["label"] for item in items] == ["ordinary"]
    assert "speechless" in caplog.text


def test_a_round_trip_preserves_the_order(
    queue: TaskQueue, registry: TaskJobRegistry, settles: Callable[[Callable[[], bool]], None]
) -> None:
    """The order is the user's, so it is the one thing a restart must not quietly rearrange.

    **Test steps:**

    * run three jobs, serialize them, and restore them into a fresh queue
    * verify the labels come back in the order they were written
    """
    for label in ("first", "second", "third"):
        queue.enqueue(CounterJob(label))
    settles(lambda: all(status.state is JobState.DONE for status in queue.jobs()))
    items = queue.serialize()

    restored = TaskQueue()
    try:
        restored.restore(items, registry)
        assert [status.label for status in restored.jobs()] == ["first", "second", "third"]
    finally:
        restored.shutdown()


# endregion

# region Restoring


def test_unfinished_work_comes_back_held(queue: TaskQueue, registry: TaskJobRegistry) -> None:
    """A restarted app comes up with everything held, so nothing starts before anyone has looked at it.

    **Test steps:**

    * restore a queued job and a paused one
    * verify both come back paused, and neither has run
    """
    items: list[TaskQueueItem] = [
        {"kind": "counter", "label": "was-queued", "job_state": "queued", "state": {"cursor": 0}},
        {"kind": "counter", "label": "was-paused", "job_state": "paused", "state": {"cursor": 2}},
    ]

    queue.restore(items, registry)

    assert [status.state for status in queue.jobs()] == [JobState.PAUSED, JobState.PAUSED]


def test_a_job_saved_while_running_comes_back_as_unfinished_work(queue: TaskQueue, registry: TaskJobRegistry) -> None:
    """A queue written mid-run -- or left by a crash -- holds a job in ``running``, which no restore
    can honestly resurrect as such.

    **Test steps:**

    * restore an item saved in the running state
    * verify it comes back held like any other unfinished job, not dropped and not running
    """
    items: list[TaskQueueItem] = [
        {"kind": "counter", "label": "was-running", "job_state": "running", "state": {"cursor": 2}}
    ]

    queue.restore(items, registry)

    assert [status.state for status in queue.jobs()] == [JobState.PAUSED]


def test_a_failed_job_comes_back_failed_with_its_reason(queue: TaskQueue, registry: TaskJobRegistry) -> None:
    """A failure is the row a reader came back for; restoring it without its reason would waste the trip.

    **Test steps:**

    * restore a failed job carrying an error
    * verify it is still failed, and still says why
    """
    items: list[TaskQueueItem] = [
        {
            "kind": "counter",
            "label": "broken",
            "job_state": "failed",
            "state": {"cursor": 1},
            "error": "OSError: the disk went away",
        }
    ]

    queue.restore(items, registry)

    status = queue.jobs()[0]
    assert status.state is JobState.FAILED
    assert status.error == "OSError: the disk went away"


def test_a_restored_job_that_carries_on_keeps_its_bar(
    queue: TaskQueue, registry: TaskJobRegistry, settles: Callable[[Callable[[], bool]], None]
) -> None:
    """Across-restart resume is the same mechanism as in-session pause: ``run`` is re-entered, not restarted.

    **Test steps:**

    * restore a paused job that declares it resumes where it stopped, with progress
    * verify its bar came back
    * resume it and verify its ``run`` picked up from where the state said, not from zero
    """
    items: list[TaskQueueItem] = [
        {
            "kind": "counter",
            "label": "resuming",
            "job_state": "paused",
            "state": {"cursor": 3},
            "done": 3,
            "total": 4,
        }
    ]
    registry = TaskJobRegistry()
    resumed = CounterJob("resuming", units=4, resumes=True)
    registry.register("counter", lambda: resumed)

    queue.restore(items, registry)
    assert queue.jobs()[0].done == 3
    queue.resume()

    settles(lambda: queue.jobs()[0].state is JobState.DONE)
    assert resumed.entered_at == [3]


def test_a_restored_job_that_starts_over_comes_back_at_zero(queue: TaskQueue, registry: TaskJobRegistry) -> None:
    """Restoring a bar that the first checkpoint is about to reset would be a lie with a witness.

    **Test steps:**

    * restore a job that does not resume, whose saved item nonetheless carries progress
    * verify it comes back at zero
    """
    items: list[TaskQueueItem] = [
        {
            "kind": "counter",
            "label": "starting-over",
            "job_state": "paused",
            "state": {"cursor": 3},
            "done": 3,
            "total": 4,
        }
    ]

    queue.restore(items, registry)

    status = queue.jobs()[0]
    assert status.done == 0
    assert status.total is None


def test_a_job_added_after_a_restore_runs_at_once(
    queue: TaskQueue, registry: TaskJobRegistry, settles: Callable[[Callable[[], bool]], None]
) -> None:
    """Eligibility is per-job, so *everything restored is held* does not mean *the queue is held*.

    **Test steps:**

    * restore two unfinished jobs
    * enqueue a fresh one
    * verify the fresh one runs to completion while the restored two stay paused
    """
    items: list[TaskQueueItem] = [
        {"kind": "counter", "label": "held-one", "job_state": "queued", "state": {"cursor": 0}},
        {"kind": "counter", "label": "held-two", "job_state": "queued", "state": {"cursor": 0}},
    ]
    queue.restore(items, registry)

    fresh = queue.enqueue(CounterJob("fresh"))

    settles(lambda: any(status.serial == fresh and status.state is JobState.DONE for status in queue.jobs()))
    held = [status.state for status in queue.jobs() if status.serial != fresh]
    assert held == [JobState.PAUSED, JobState.PAUSED]


def test_unfinished_work_can_be_restored_running_instead(
    queue: TaskQueue, registry: TaskJobRegistry, settles: Callable[[Callable[[], bool]], None]
) -> None:
    """The seam a *resume tasks on restart* setting turns; the engine takes the state rather than choosing it.

    **Test steps:**

    * restore an unfinished job asking for it to come back queued
    * verify it runs without anybody resuming it
    """
    items: list[TaskQueueItem] = [{"kind": "counter", "label": "eager", "job_state": "paused", "state": {"cursor": 0}}]

    queue.restore(items, registry, unfinished_state=JobState.QUEUED)

    settles(lambda: queue.jobs()[0].state is JobState.DONE)


def test_work_cannot_be_restored_into_a_state_no_session_produced(queue: TaskQueue, registry: TaskJobRegistry) -> None:
    """A restored job has neither run nor been stopped here, so ``running`` is a claim about a dead session.

    **Test steps:**

    * restore unfinished work asking for it to come back running
    * verify the call is refused
    """
    with pytest.raises(ValueError, match="running"):
        queue.restore([], registry, unfinished_state=JobState.RUNNING)


def test_an_unknown_kind_is_dropped_and_logged(
    queue: TaskQueue, registry: TaskJobRegistry, caplog: pytest.LogCaptureFixture
) -> None:
    """A queue file naming a feature this build does not ship must not stop the app starting.

    **Test steps:**

    * restore two items, one of a kind nothing registered
    * verify only the known one came back, and the loss was logged with a count
    """
    items: list[TaskQueueItem] = [
        {"kind": "checksum-verify", "label": "from-the-future", "job_state": "queued", "state": {}},
        {"kind": "counter", "label": "known", "job_state": "queued", "state": {"cursor": 0}},
    ]

    with caplog.at_level(logging.WARNING):
        serials = queue.restore(items, registry)

    assert len(serials) == 1
    assert [status.label for status in queue.jobs()] == ["known"]
    assert "1 saved task" in caplog.text


def test_an_item_that_is_not_shaped_like_one_is_dropped(queue: TaskQueue, registry: TaskJobRegistry) -> None:
    """What arrives here came off disk, possibly from an editor; one bad record costs one row.

    **Test steps:**

    * restore items missing a kind, missing a state, and naming a state no build has
    * verify none of them came back, and the queue is usable
    """
    # deliberately not typed as items: these are what a hand-edited or foreign file holds, which is
    # exactly what the restore has to survive.
    items: list[Any] = [
        {"label": "no-kind", "job_state": "queued", "state": {}},
        {"kind": "counter", "label": "no-state", "job_state": "queued"},
        {"kind": "counter", "label": "odd-state", "job_state": "sleeping", "state": {"cursor": 0}},
    ]

    assert queue.restore(items, registry) == ()
    assert queue.jobs() == ()


def test_restore_is_refused_on_a_queue_that_already_holds_jobs(queue: TaskQueue, registry: TaskJobRegistry) -> None:
    """A startup operation, deliberately: making it merge invites a question nobody has asked.

    **Test steps:**

    * enqueue a job
    * restore into the same queue
    * verify the call is refused
    """
    queue.pause()
    queue.enqueue(CounterJob("already-here"))

    with pytest.raises(RuntimeError, match="startup"):
        queue.restore([], registry)


def test_restore_is_refused_on_a_queue_that_has_been_shut_down(registry: TaskJobRegistry) -> None:
    """Shutdown is terminal for restoring as it is for enqueueing; work that will never run is refused.

    **Test steps:**

    * shut a queue down
    * restore into it
    * verify the call is refused
    """
    queue = TaskQueue()
    queue.shutdown()

    with pytest.raises(RuntimeError, match="shut down"):
        queue.restore([], registry)


# endregion

# region Validating on start


def test_a_job_that_objects_is_failed_with_its_own_sentence(
    queue: TaskQueue, settles: Callable[[Callable[[], bool]], None]
) -> None:
    """No seventh state: a job that cannot start is a failure, which is kept and retryable.

    **Test steps:**

    * enqueue a job whose ``validate`` objects
    * verify it is failed with that sentence, and never entered ``run``
    """
    job = CounterJob("gone", refusal="The resource no longer exists.")
    queue.enqueue(job)

    settles(lambda: queue.jobs()[0].state is JobState.FAILED)

    assert queue.jobs()[0].error == "The resource no longer exists."
    assert not job.entered_at


def test_validation_runs_before_every_start_not_only_after_a_restore(
    queue: TaskQueue, settles: Callable[[Callable[[], bool]], None]
) -> None:
    """One rule for the restored resource that is gone and the one deleted while its job waited.

    **Test steps:**

    * enqueue a job that objects, and let it fail
    * take the objection away and retry it
    * verify it runs the second time
    """
    job = CounterJob("deleted-while-queued", refusal="The resource no longer exists.")
    serial = queue.enqueue(job)
    settles(lambda: queue.jobs()[0].state is JobState.FAILED)

    job.refusal = None
    queue.retry(serial)

    settles(lambda: queue.jobs()[0].state is JobState.DONE)
    assert job.entered_at == [0]


def test_a_job_that_raises_out_of_validate_is_failed_the_same_way(
    queue: TaskQueue, settles: Callable[[Callable[[], bool]], None], caplog: pytest.LogCaptureFixture
) -> None:
    """It has said it cannot start; how it said so is not worth a second path.

    **Test steps:**

    * enqueue a job whose ``validate`` raises
    * verify it is failed with the exception's text, and the failure was logged
    """

    class ExplodingJob(CounterJob):
        """A job whose check itself goes wrong."""

        def validate(self) -> str | None:
            """Raise instead of answering.

            :raises OSError: always.
            """
            raise OSError("the mount is gone")

    queue.enqueue(ExplodingJob("exploding"))

    with caplog.at_level(logging.ERROR):
        settles(lambda: queue.jobs()[0].state is JobState.FAILED)

    assert queue.jobs()[0].error == "OSError: the mount is gone"
    assert "exploding" in caplog.text


def test_a_queue_carries_on_past_a_job_that_refuses_to_start(
    queue: TaskQueue, settles: Callable[[Callable[[], bool]], None]
) -> None:
    """A refusal costs its own job and nothing else, exactly as a failure does.

    **Test steps:**

    * enqueue a job that objects, followed by one that does not
    * verify the second still runs
    """
    queue.enqueue(CounterJob("gone", refusal="The resource no longer exists."))
    queue.enqueue(CounterJob("fine"))

    settles(lambda: [status.state for status in queue.jobs()] == [JobState.FAILED, JobState.DONE])


# endregion

# region Retrying restored work


def test_a_restored_failure_can_be_retried(
    queue: TaskQueue, registry: TaskJobRegistry, settles: Callable[[Callable[[], bool]], None]
) -> None:
    """The recovery a kept failure exists for still works on one that came back off disk.

    **Test steps:**

    * restore a failed job
    * retry it
    * verify it runs and its reason is cleared
    """
    items: list[TaskQueueItem] = [
        {
            "kind": "counter",
            "label": "broken",
            "job_state": "failed",
            "state": {"cursor": 2},
            "error": "OSError: the disk went away",
        }
    ]
    serial = queue.restore(items, registry)[0]

    queue.retry(serial)

    settles(lambda: queue.jobs()[0].state is JobState.DONE)
    assert queue.jobs()[0].error is None


def test_a_retried_job_starts_over_even_when_it_would_otherwise_carry_on(
    queue: TaskQueue, settles: Callable[[Callable[[], bool]], None]
) -> None:
    """Retry's reset is the whole difference between Retry and Resume, restored jobs included.

    **Test steps:**

    * restore a resuming job as failed, part-way through
    * retry it, and let it finish
    * verify its ``run`` was entered at zero, and the state that would be saved says so too
    """
    resumed = CounterJob("resuming", units=4, resumes=True)
    registry = TaskJobRegistry()
    registry.register("counter", lambda: resumed)
    items: list[TaskQueueItem] = [
        {
            "kind": "counter",
            "label": "resuming",
            "job_state": "failed",
            "state": {"cursor": 3},
            "done": 3,
            "total": 4,
            "error": "OSError: the disk went away",
        }
    ]
    serial = queue.restore(items, registry)[0]

    queue.retry(serial)

    settles(lambda: queue.jobs()[0].state is JobState.DONE)
    assert resumed.entered_at == [0]


# endregion
