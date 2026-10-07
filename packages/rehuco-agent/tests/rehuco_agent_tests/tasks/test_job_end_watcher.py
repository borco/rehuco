"""Tests for JobEndWatcher: the GUI-thread call back when a job a surface enqueued has ended (#457)."""

from collections.abc import Iterator
from threading import Event
from typing import Final

from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.tasks.job_end_watcher import JobEndWatcher
from rehuco_core import FINISHED_JOB_STATES, JobControl, TaskJobBase, TaskQueue

TIMEOUT_MS: Final = 5_000


class GateJob(TaskJobBase):
    """A job that waits to be let go, so the test decides when it ends."""

    def __init__(self) -> None:
        super().__init__()
        self.label = "gate"
        self.release: Final = Event()

    def run(self, control: JobControl) -> None:
        """Wait for the test.

        :param control: unused.
        """
        del control
        self.release.wait(TIMEOUT_MS / 1000)


@fixture(name="queue")
def queue_fixture() -> Iterator[TaskQueue]:
    """A queue that is always shut down.

    :returns: the queue.
    """
    queue = TaskQueue()
    yield queue
    queue.shutdown()


@fixture(name="watcher")
def watcher_fixture(qtbot: QtBot, queue: TaskQueue) -> Iterator[JobEndWatcher]:
    """A watcher over the queue, detached when the test ends.

    :param qtbot: pytest-qt fixture.
    :param queue: the queue to watch.
    :returns: the watcher.
    """
    del qtbot
    watcher = JobEndWatcher(queue)
    yield watcher
    watcher.detach()


def test_the_callback_runs_once_when_the_watched_job_ends(
    qtbot: QtBot, queue: TaskQueue, watcher: JobEndWatcher
) -> None:
    """A surface that wants to act on a job's end -- announce what a verify rewrote -- is called on the GUI thread.

    **Test steps:**

    * enqueue a held job and watch it, then let it finish
    * verify the callback ran once, and not before the job ended
    """
    job = GateJob()
    calls: list[str] = []
    serial = queue.enqueue(job)
    watcher.watch(serial, lambda: calls.append("ended"))

    qtbot.wait(50)
    assert not calls
    job.release.set()

    qtbot.waitUntil(lambda: calls == ["ended"], timeout=TIMEOUT_MS)
    qtbot.wait(50)
    assert calls == ["ended"]


def test_a_job_that_ended_before_it_was_watched_is_still_called_back(
    qtbot: QtBot, queue: TaskQueue, watcher: JobEndWatcher
) -> None:
    """The queue tells its listeners as a job ends, not afterwards: a watch asked for late must ask the queue.

    **Test steps:**

    * run a job to completion, then watch it
    * verify the callback runs
    """
    job = GateJob()
    job.release.set()
    serial = queue.enqueue(job)
    qtbot.waitUntil(lambda: queue.jobs()[0].state in FINISHED_JOB_STATES, timeout=TIMEOUT_MS)
    calls: list[str] = []

    watcher.watch(serial, lambda: calls.append("late"))

    qtbot.waitUntil(lambda: calls == ["late"], timeout=TIMEOUT_MS)


def test_a_job_the_reader_clears_says_nothing_more(qtbot: QtBot, queue: TaskQueue, watcher: JobEndWatcher) -> None:
    """Clearing a row is not an ending anyone asked to hear about, and an unwatched job's end is not either.

    **Test steps:**

    * watch a held job and remove it, then finish another job nobody watches
    * verify no callback ran
    """
    held, unwatched = GateJob(), GateJob()
    calls: list[str] = []
    serial = queue.enqueue(held)
    queue.enqueue(unwatched)
    watcher.watch(serial, lambda: calls.append("ended"))

    queue.remove(serial)
    held.release.set()
    unwatched.release.set()
    queue.wait_until_idle(TIMEOUT_MS / 1000)
    qtbot.wait(100)

    assert not calls


def test_a_detached_watcher_calls_nothing_back(qtbot: QtBot, queue: TaskQueue) -> None:
    """A window that is closing detaches it, and what was waiting is dropped.

    **Test steps:**

    * watch a held job, detach, and let the job finish
    * verify no callback ran
    """
    watcher = JobEndWatcher(queue)
    job = GateJob()
    calls: list[str] = []
    serial = queue.enqueue(job)
    watcher.watch(serial, lambda: calls.append("ended"))

    watcher.detach()
    job.release.set()
    queue.wait_until_idle(TIMEOUT_MS / 1000)
    qtbot.wait(100)

    assert not calls


def test_an_ending_nobody_watches_is_ignored(watcher: JobEndWatcher) -> None:
    """A serial with no callback -- cleared, detached, or called back already -- is not an error to be told of twice.

    **Test steps:**

    * hand the watcher the end of a job it holds nothing for
    * verify nothing is raised
    """
    watcher._JobEndWatcher__on_ended(12345)  # type: ignore[attr-defined]  # pylint: disable=protected-access


def test_the_other_queue_notifications_are_not_the_watchers_business(watcher: JobEndWatcher) -> None:
    """It answers the whole listener protocol and acts on none of the rest.

    **Test steps:**

    * tell it of a reorder and of the queue pausing
    * verify nothing is raised
    """
    watcher.jobs_reordered([2, 1])
    watcher.queue_paused_changed(True)
