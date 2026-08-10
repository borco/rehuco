"""Tests for TaskQueueStatusIndicator: the status bar's own view of the queue (#239).

Uses a real :class:`~rehuco_core.TaskQueue` and gated jobs, the same discipline
``test_task_queue_widget.py`` and ``test_task_queue_model.py`` use -- driven by ``threading.Event``s
rather than by sleeping, so a test asserts on a state the worker has demonstrably reached.
"""

from collections.abc import Callable, Iterator
from threading import Event
from time import monotonic, sleep
from typing import Final

from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.tasks.task_queue_model import TaskQueueModel, state_text
from rehuco_agent.tasks.task_queue_status_indicator import TaskQueueStatusIndicator
from rehuco_core import PROGRESS_UNIT_RESOURCES, JobControl, JobState, TaskJobBase, TaskQueue

TIMEOUT: Final = 5.0


class GatedJob(TaskJobBase):
    """A job that reports once, then blocks until released, checkpointing while it waits -- so a
    pause request genuinely lands as ``paused`` rather than sitting pending forever.

    :param label: the job's label.
    :param progress_unit: what :attr:`~rehuco_core.TaskJob.progress_unit` to declare -- ``""`` unless
        given, the same default a job that counts nothing carries.
    """

    def __init__(self, label: str, progress_unit: str = "") -> None:
        super().__init__()
        self.label = label
        self.progress_unit = progress_unit
        self.entered: Final = Event()
        self.__proceed: Final = Event()

    def run(self, control: JobControl) -> None:
        control.report(3, 10)
        self.entered.set()
        while not self.__proceed.wait(0.01):
            self.checkpoint()

    def let_finish(self) -> None:
        """Release the block, letting ``run`` return."""
        self.__proceed.set()


@fixture
def queue() -> Iterator[TaskQueue]:
    """A fresh, real `TaskQueue`, shut down after the test."""
    built = TaskQueue()
    yield built
    built.shutdown(timeout=TIMEOUT)


@fixture
def deliver(qtbot: QtBot) -> Callable[[], None]:
    """Pump the Qt event loop long enough for a pending queued snapshot to run."""
    return lambda: qtbot.wait(50)


@fixture
def indicator(queue: TaskQueue, qtbot: QtBot) -> TaskQueueStatusIndicator:
    """A `TaskQueueStatusIndicator` attached to a model over ``queue``."""
    model = TaskQueueModel(queue)
    model.attach_to()
    built = TaskQueueStatusIndicator(model)
    qtbot.addWidget(built)
    return built


def test_starts_hidden_over_an_empty_queue(indicator: TaskQueueStatusIndicator) -> None:
    """An empty queue has nothing to interrupt a reader for.

    **Test steps:**

    * build an indicator over an empty queue
    * verify it is not visible
    """
    assert not indicator.isVisible()


def test_becomes_visible_once_a_job_is_running(
    queue: TaskQueue, indicator: TaskQueueStatusIndicator, deliver: Callable[[], None]
) -> None:
    """A running job is unfinished work, so the indicator appears.

    **Test steps:**

    * enqueue a job and let it start running
    * verify the indicator became visible
    """
    job = GatedJob("copy")
    queue.enqueue(job)
    assert job.entered.wait(TIMEOUT)
    deliver()

    assert indicator.isVisible()

    job.let_finish()


def test_hides_again_once_the_only_job_finishes(
    queue: TaskQueue, indicator: TaskQueueStatusIndicator, deliver: Callable[[], None]
) -> None:
    """Once nothing is left unfinished, the indicator goes away.

    **Test steps:**

    * run a job to completion
    * verify the indicator is hidden again
    """
    job = GatedJob("copy")
    queue.enqueue(job)
    assert job.entered.wait(TIMEOUT)
    deliver()
    assert indicator.isVisible()

    job.let_finish()
    deliver()

    assert not indicator.isVisible()


def test_stays_hidden_over_a_queue_holding_only_finished_rows(
    queue: TaskQueue, indicator: TaskQueueStatusIndicator, deliver: Callable[[], None]
) -> None:
    """Finished rows are *kept* ([[appendices.task-queue#kept]]), so a queue holding only them is not
    "not empty" for this indicator's purposes.

    **Test steps:**

    * run a job to completion, leaving its finished row behind
    * verify the indicator reads hidden, not merely "was hidden and never checked again"
    """
    job = GatedJob("copy")
    queue.enqueue(job)
    assert job.entered.wait(TIMEOUT)
    job.let_finish()
    deliver()

    assert queue.jobs()  # the finished row is still there
    assert not indicator.isVisible()


def test_names_the_count_and_the_running_jobs_label(
    queue: TaskQueue, indicator: TaskQueueStatusIndicator, deliver: Callable[[], None]
) -> None:
    """The text says how many jobs are outstanding and what is happening.

    **Test steps:**

    * queue a held second job behind one running job
    * verify the text carries the count and the running job's label
    """
    running = GatedJob("copy files")
    queued = GatedJob("verify files")
    queue.enqueue(running)
    assert running.entered.wait(TIMEOUT)
    # the queue is serial by construction ([[appendices.task-queue#serial]]), so this second job stays
    # queued behind the first rather than starting alongside it
    queue.enqueue(queued)
    deliver()

    text = indicator.text()
    assert "2" in text
    assert "copy files" in text

    running.let_finish()
    assert queued.entered.wait(TIMEOUT)
    queued.let_finish()


def test_shows_progress_when_the_running_job_declares_a_unit(
    queue: TaskQueue, indicator: TaskQueueStatusIndicator, deliver: Callable[[], None]
) -> None:
    """A job counting something shows its progress, the same figures the dock's own Info column would.

    **Test steps:**

    * run a job declaring resources counted, reporting 3 of 10
    * verify the text carries that fraction
    """
    job = GatedJob("scan", progress_unit=PROGRESS_UNIT_RESOURCES)
    queue.enqueue(job)
    assert job.entered.wait(TIMEOUT)
    deliver()

    assert "3 / 10" in indicator.text()

    job.let_finish()


def test_with_nothing_running_the_first_unfinished_job_stands_in(
    queue: TaskQueue, indicator: TaskQueueStatusIndicator, deliver: Callable[[], None]
) -> None:
    """A queue holding outstanding work but running nothing -- the shape a restart leaves behind when
    unfinished jobs come back held rather than resumed -- names its first unfinished row instead.

    **Test steps:**

    * pause a running job and wait until the engine has genuinely parked it
    * verify the indicator still shows, counting the one held job and reading its state text

    The parenthetical is asserted against :func:`~.task_queue_model.state_text`'s live answer rather
    than a literal: what a parked row's state *reads as* is that function's own decision (today the
    engine keeps the acted-on pause request on the status, so it says "Pausing…"), and pinning the
    word here would make this test fail over a change that belongs to `state_text`'s own tests.
    """
    job = GatedJob("verify")
    serial = queue.enqueue(job)
    assert job.entered.wait(TIMEOUT)
    queue.pause_job(serial)
    deadline = monotonic() + TIMEOUT
    while queue.jobs()[0].state is not JobState.PAUSED and monotonic() < deadline:
        sleep(0.01)
    deliver()

    assert indicator.isVisible()
    assert indicator.text() == f"1 task — verify ({state_text(queue.jobs()[0])})"


def test_falls_back_to_the_state_when_there_is_no_progress_to_show(
    queue: TaskQueue, indicator: TaskQueueStatusIndicator, deliver: Callable[[], None]
) -> None:
    """A job declaring no unit has nothing to count, so its state stands in.

    **Test steps:**

    * run a job that reports no unit
    * verify the text says it is running, not a bare figure
    """
    job = GatedJob("import")
    queue.enqueue(job)
    assert job.entered.wait(TIMEOUT)
    deliver()

    assert "Running" in indicator.text()

    job.let_finish()


def test_worker_thread_progress_only_lands_once_the_gui_thread_is_pumped(
    queue: TaskQueue, indicator: TaskQueueStatusIndicator, deliver: Callable[[], None]
) -> None:
    """A report from the job's own worker thread reaches the indicator only through the model's
    marshalled ``snapshot_taken`` -- never touched directly off that thread.

    **Test steps:**

    * run a job to the point its worker thread has reported progress, without pumping events
    * verify the indicator has not moved yet -- the marshalled wake is still pending
    * pump the event loop once
    * verify it now shows what the worker thread reported
    """
    job = GatedJob("copy", progress_unit=PROGRESS_UNIT_RESOURCES)
    queue.enqueue(job)
    assert job.entered.wait(TIMEOUT)

    assert not indicator.isVisible()

    deliver()

    assert indicator.isVisible()
    assert "3 / 10" in indicator.text()

    job.let_finish()
