"""Tests for the queue file: what the agent writes, when it writes it, and what a bad file costs (#238).

Nothing here touches a real disk. `atomic_write_text` and `Path.read_text` are replaced by a
dictionary standing in for the filesystem, which is also what makes *how many times the file was
written* something a test can assert on -- and that count is the whole point of the write-on-structural-
change rule.
"""

import json
import logging
from collections.abc import Callable, Iterator
from pathlib import Path
from threading import Event
from time import monotonic, sleep
from typing import Any, Final

import pytest
from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_agent.tasks import TASK_QUEUE_FILENAME, TaskQueueStore, task_queue_path
from rehuco_agent.tasks import task_queue_store as store_module
from rehuco_core import JobControl, JobState, TaskJobBase, TaskJobRegistry, TaskQueue

QUEUE_PATH: Final = Path.cwd() / "fake" / TASK_QUEUE_FILENAME
TIMEOUT: Final = 5.0
"""How long a test waits for the worker before calling it a failure, in seconds."""


# region Sample classes


class CounterJob(TaskJobBase):
    """A persistable job whose whole state is how far it counted, and which can be held mid-run.

    :param label: the job's label.
    :param units: how far to count, and therefore how many progress reports it makes.
    """

    kind = "counter"

    def __init__(self, label: str = "counter", units: int = 3) -> None:
        super().__init__()
        self.label = label
        self.__units: Final = units
        self.__cursor = 0

    def validate(self) -> str | None:
        """Accept every start.

        :returns: ``None``, always.
        """
        return None

    def capture_state(self) -> dict[str, Any]:
        """Hand over the cursor.

        :returns: the state to write down.
        """
        return {"cursor": self.__cursor}

    def restore_state(self, state: dict[str, Any]) -> None:
        """Take the cursor back.

        :param state: what :meth:`capture_state` wrote.
        """
        self.__cursor = int(state["cursor"])

    def run(self, control: JobControl) -> None:
        """Count to ``units``, reporting each one.

        :param control: the engine's face to this job.
        """
        while self.__cursor < self.__units:
            self.checkpoint()
            self.__cursor += 1
            control.report(self.__cursor, self.__units)


class GateJob(TaskJobBase):
    """A job that occupies the worker until released, so everything behind it stays queued.

    **Not a `PersistableTaskJob`**, deliberately: :meth:`~rehuco_core.TaskQueue.serialize` skips a job
    that cannot be written down, so this holds the queue without appearing in the file a test is
    asserting on.

    Checkpoints while it waits, so the cancel ``queue.shutdown`` sends in teardown unwinds it at once
    rather than being waited out.
    """

    def __init__(self, label: str = "gate") -> None:
        super().__init__()
        self.label = label
        self.entered: Final = Event()
        self.__proceed: Final = Event()

    def run(self, control: JobControl) -> None:
        """Block until released, checkpointing throughout.

        :param control: the engine's face to this job.
        """
        del control
        self.entered.set()
        while not self.__proceed.wait(0.01):
            self.checkpoint()

    def let_finish(self) -> None:
        """Release the block, letting ``run`` return."""
        self.__proceed.set()


class FakeDisk:
    """The one file these tests have, held in memory.

    :param text: what the file already holds, or ``None`` for a file that does not exist.
    """

    def __init__(self, text: str | None = None) -> None:
        self.text = text
        self.writes = 0

    def write(self, path: Path | str, text: str, *, encoding: str = "utf-8") -> None:
        """Stand in for `atomic_write_text`.

        :param path: unused; these tests have one file.
        :param text: what was written.
        :param encoding: unused.
        """
        del path, encoding
        self.text = text
        self.writes += 1

    def read(self, *args: Any, **kwargs: Any) -> str:
        """Stand in for ``Path.read_text``.

        Takes no path: patched onto ``Path`` as a *bound* method of this object, it never receives the
        path it was called on -- which costs nothing, since these tests have one file.

        :param args: unused.
        :param kwargs: unused.
        :returns: what the file holds.
        :raises FileNotFoundError: when nothing has been written.
        """
        del args, kwargs
        if self.text is None:
            raise FileNotFoundError(QUEUE_PATH)
        return self.text

    def items(self) -> list[dict[str, Any]]:
        """Read the file back as the records it holds.

        :returns: the saved items.
        """
        assert self.text is not None
        saved = json.loads(self.text)
        assert isinstance(saved, list)
        return saved


# endregion

# region Fixtures


@fixture(name="disk")
def disk_fixture(mocker: MockerFixture) -> FakeDisk:
    """The filesystem the store is allowed to touch.

    :param mocker: the patcher.
    :returns: the in-memory file, ready to be read and written.
    """
    disk = FakeDisk()
    mocker.patch.object(store_module, "atomic_write_text", disk.write)
    mocker.patch.object(Path, "read_text", disk.read)
    return disk


@fixture(name="queue")
def queue_fixture() -> Iterator[TaskQueue]:
    """A queue that is always shut down, so no test leaves a worker thread behind.

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


@fixture(name="store")
def store_fixture(queue: TaskQueue, registry: TaskJobRegistry, disk: FakeDisk) -> TaskQueueStore:
    """A store over the queue under test, writing to the in-memory file.

    :param queue: the queue under test.
    :param registry: what it restores from.
    :param disk: the file it writes to; taken so the patching is in place first.
    :returns: the store under test, not yet attached.
    """
    del disk
    return TaskQueueStore(queue, registry, QUEUE_PATH)


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

# region Where the file lives


def test_the_queue_file_sits_beside_the_settings_file(mocker: MockerFixture) -> None:
    """Per-user and per-scope without this module knowing what either means on this OS.

    **Test steps:**

    * point the settings at a known file
    * verify the queue file is named beside it
    """
    settings = mocker.Mock()
    settings.fileName.return_value = str(Path.cwd() / "fake" / "rehuco-agent.ini")
    mocker.patch.object(store_module, "persistent_settings", return_value=settings)

    assert task_queue_path() == Path.cwd() / "fake" / TASK_QUEUE_FILENAME


# endregion

# region Reading


def test_a_saved_queue_is_read_back_as_records(store: TaskQueueStore, disk: FakeDisk) -> None:
    """The load path is a plain list, so the settings that filter it have somewhere to stand.

    **Test steps:**

    * put two saved records on disk
    * read them
    * verify both come back, in order
    """
    disk.text = json.dumps(
        [
            {"kind": "counter", "label": "first", "job_state": "paused", "state": {"cursor": 1}},
            {"kind": "counter", "label": "second", "job_state": "queued", "state": {"cursor": 0}},
        ]
    )

    assert [item["label"] for item in store.read_items()] == ["first", "second"]


def test_no_file_yet_reads_as_an_empty_queue(store: TaskQueueStore) -> None:
    """A first run has no file, which is not a problem worth logging.

    **Test steps:**

    * read with nothing on disk
    * verify the answer is empty
    """
    assert store.read_items() == []


def test_a_corrupt_file_starts_empty_and_says_so(
    store: TaskQueueStore, disk: FakeDisk, caplog: pytest.LogCaptureFixture
) -> None:
    """A queue file must never be able to stop the app starting.

    **Test steps:**

    * put text that is not JSON on disk
    * read it
    * verify the queue reads as empty and the failure was logged
    """
    disk.text = "{not json at all"

    with caplog.at_level(logging.ERROR):
        assert store.read_items() == []

    assert "task queue" in caplog.text


def test_a_file_holding_something_other_than_records_starts_empty(store: TaskQueueStore, disk: FakeDisk) -> None:
    """Readable JSON is not the same as a readable queue.

    **Test steps:**

    * put a JSON object, and then a list holding a string, on disk
    * verify each reads as empty
    """
    disk.text = json.dumps({"tasks": []})
    assert store.read_items() == []

    disk.text = json.dumps(["a task, allegedly"])
    assert store.read_items() == []


def test_an_unreadable_file_starts_empty_and_says_so(
    store: TaskQueueStore, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    """A locked or unreadable file costs the saved queue and nothing else.

    **Test steps:**

    * make reading the file raise
    * read it
    * verify the queue reads as empty and the failure was logged
    """
    mocker.patch.object(Path, "read_text", side_effect=PermissionError("denied"))

    with caplog.at_level(logging.ERROR):
        assert store.read_items() == []

    assert "task queue" in caplog.text


# endregion

# region Writing


def test_the_file_is_written_atomically(store: TaskQueueStore, queue: TaskQueue, disk: FakeDisk) -> None:
    """A half-written queue file is a queue file that starts the app empty; the write is the barrier.

    **Test steps:**

    * attach the store and enqueue a job
    * verify the file was written through the atomic writer, holding that job
    """
    queue.pause()
    store.restore([])

    queue.enqueue(CounterJob("saved"))

    assert [item["label"] for item in disk.items()] == ["saved"]


def test_a_structural_change_is_written_and_progress_is_not(
    store: TaskQueueStore,
    queue: TaskQueue,
    disk: FakeDisk,
    settles: Callable[[Callable[[], bool]], None],
) -> None:
    """O(jobs), not O(work units): a five thousand file sweep must not mean five thousand `fsync`s.

    **Test steps:**

    * attach the store and run a job that reports progress many times
    * verify it was written once per structural change -- the enqueue, the start, the outcome -- and
      not once per report
    """
    store.restore([])

    queue.enqueue(CounterJob("many-units", units=50))
    settles(lambda: all(status.state is JobState.DONE for status in queue.jobs()))

    assert disk.writes == 3
    assert disk.items()[0]["job_state"] == JobState.DONE.value


def test_a_removal_is_written(
    store: TaskQueueStore,
    queue: TaskQueue,
    disk: FakeDisk,
    settles: Callable[[Callable[[], bool]], None],
) -> None:
    """Removal is the one way out of the queue, so the file has to stop holding what left it.

    **Test steps:**

    * run a job to completion with the store attached
    * remove it
    * verify the file is empty afterwards
    """
    store.restore([])
    serial = queue.enqueue(CounterJob("gone-later"))
    settles(lambda: all(status.state is JobState.DONE for status in queue.jobs()))

    queue.remove(serial)

    assert disk.items() == []


def test_a_reorder_is_written(store: TaskQueueStore, queue: TaskQueue, disk: FakeDisk) -> None:
    """The order is the user's, so it is part of what quitting must not throw away.

    **Test steps:**

    * occupy the worker, so the two jobs enqueued behind it stay movable
    * move the second above the first
    * verify the file holds the new order
    """
    # A gate rather than `queue.pause()`, which reads as holding the queue but cannot hold *this* one:
    # pause is pause_job applied to the jobs there are ([[appendices.task-queue#pause-concept]]), so on
    # an empty queue it asks nobody, and the worker starts "first" the moment it is enqueued. Only a
    # job in MOVABLE_JOB_STATES moves, so once "first" has left QUEUED the move clamps to where
    # "second" already is and does nothing -- leaving the file holding the original order. That is a
    # race with the worker, which the main thread nearly always won until a cov-parallel run put four
    # coverage-traced workers on four cores and it started losing (#262).
    gate = GateJob()
    store.restore([])
    queue.enqueue(gate)
    assert gate.entered.wait(TIMEOUT)
    queue.enqueue(CounterJob("first"))
    second = queue.enqueue(CounterJob("second"))

    queue.move(second, 0)

    # the gate is not persistable, so `serialize` skips it and the file holds only the two below it
    assert [item["label"] for item in disk.items()] == ["second", "first"]

    gate.let_finish()


def test_a_write_that_fails_is_logged_rather_than_raised(
    store: TaskQueueStore, queue: TaskQueue, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    """Saving happens on whichever thread moved a job; it must not take that operation down with it.

    **Test steps:**

    * make writing the file raise
    * attach the store and enqueue a job
    * verify the enqueue succeeded and the failure was logged
    """
    queue.pause()
    store.restore([])
    mocker.patch.object(store_module, "atomic_write_text", side_effect=OSError("the disk is full"))

    with caplog.at_level(logging.ERROR):
        queue.enqueue(CounterJob("saved-nowhere"))

    assert len(queue.jobs()) == 1
    assert "could not be saved" in caplog.text


# endregion

# region Restoring


def test_a_restored_queue_comes_back_held_and_is_then_kept(
    store: TaskQueueStore, queue: TaskQueue, disk: FakeDisk
) -> None:
    """The whole feature, end to end: close it, reopen it, the list is still there.

    **Test steps:**

    * read a saved queue off disk and restore it
    * verify the jobs came back paused
    * enqueue another and verify the file now holds all three
    """
    disk.text = json.dumps(
        [
            {"kind": "counter", "label": "first", "job_state": "paused", "state": {"cursor": 1}},
            {"kind": "counter", "label": "second", "job_state": "queued", "state": {"cursor": 0}},
        ]
    )

    store.restore(store.read_items())

    assert [status.state for status in queue.jobs()] == [JobState.PAUSED, JobState.PAUSED]
    queue.enqueue(CounterJob("third"))
    queue.pause()
    assert [item["label"] for item in disk.items()] == ["first", "second", "third"]


def test_restoring_asks_for_the_state_it_was_given(store: TaskQueueStore, queue: TaskQueue, disk: FakeDisk) -> None:
    """The *resume tasks on restart* seam: the store passes the answer through rather than deciding it.

    **Test steps:**

    * restore a saved job asking for unfinished work to come back queued
    * verify it did not come back paused
    """
    disk.text = json.dumps([{"kind": "counter", "label": "eager", "job_state": "paused", "state": {"cursor": 0}}])

    store.restore(store.read_items(), unfinished_state=JobState.QUEUED)

    assert queue.jobs()[0].state is not JobState.PAUSED


# endregion
