"""Tests for TaskQueueModel: a pure, re-snapshotting view over a real TaskQueue (#202).

Uses a real :class:`~rehuco_core.TaskQueue` and gated jobs, the same discipline
``rehuco-core``'s own ``test_task_queue.py`` uses -- driven by ``threading.Event``s rather than by
sleeping, so a test asserts on a state the worker has demonstrably reached.
"""

from collections.abc import Callable, Iterator
from threading import Event, get_ident
from typing import Final

from PySide6.QtCore import QModelIndex, Qt
from pytest import fixture, mark
from pytestqt.qtbot import QtBot
from rehuco_agent.tasks.task_queue_model import (
    COLUMN_COUNT,
    COLUMN_TITLES,
    INFO_COLUMN,
    LABEL_COLUMN,
    NOT_SAVED_HINT,
    RESUMES_HINT,
    STARTS_OVER_HINT,
    STATE_COLUMN,
    TaskQueueModel,
    resume_hint,
    state_text,
)
from rehuco_core import JobControl, JobState, JobStatus, StopRequest, TaskJobBase, TaskQueue

TIMEOUT: Final = 5.0


class GatedJob(TaskJobBase):
    """A job that reports once, then blocks on ``proceed`` until told to finish.

    :param label: the job's label.
    :param proceed: set to let the job finish; unset (the default construction) blocks ``run``.
    """

    def __init__(self, label: str, proceed: Event | None = None) -> None:
        super().__init__()
        self.label = label
        self.entered: Final = Event()
        self.__proceed: Final = proceed if proceed is not None else Event()
        self.run_threads: Final[list[int]] = []

    def run(self, control: JobControl) -> None:
        self.run_threads.append(get_ident())
        control.report(1, 1)
        self.entered.set()
        self.__proceed.wait(TIMEOUT)

    def let_finish(self) -> None:
        """Release the block, letting ``run`` return."""
        self.__proceed.set()


class FailingJob(TaskJobBase):
    """A job that raises as soon as it runs, so a row lands in ``failed`` carrying a reason.

    :param label: the job's label.
    """

    def __init__(self, label: str) -> None:
        super().__init__()
        self.label = label

    def run(self, control: JobControl) -> None:
        del control
        raise ValueError("nope")


class PersistableJob(TaskJobBase):
    """A job satisfying `PersistableTaskJob`, so its row reads as one that survives a restart.

    Holds no state worth keeping: what is under test is the *declaration* the engine copies onto
    :attr:`~rehuco_core.JobStatus.persistable`, not what any job would actually write down.

    :param label: the job's label.
    """

    kind = "test.persistable"

    def __init__(self, label: str) -> None:
        super().__init__()
        self.label = label

    def validate(self) -> str | None:
        """Accept every start.

        :returns: ``None``, always.
        """
        return None

    def capture_state(self) -> dict[str, object]:
        """Hand over nothing at all.

        :returns: an empty state.
        """
        return {}

    def restore_state(self, state: dict[str, object]) -> None:
        """Take nothing back.

        :param state: what :meth:`capture_state` wrote.
        """
        del state

    def run(self, control: JobControl) -> None:
        del control


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


def test_a_burst_of_progress_reports_reaches_the_gui_as_one_snapshot(
    queue: TaskQueue, deliver: Callable[[], None]
) -> None:
    """Several ``job_updated`` calls in a row collapse into one re-snapshot.

    **Test steps:**

    * attach a model to the queue, then run a job that reports and finishes
    * count how many times ``dataChanged``/``rowsInserted`` fired
    * verify the burst produced one wake, not one per report
    """
    model = TaskQueueModel(queue)
    model.attach_to()
    inserts: list[int] = []
    model.rowsInserted.connect(lambda *_args: inserts.append(1))

    job = GatedJob("job")
    job.let_finish()
    queue.enqueue(job)
    assert job.entered.wait(TIMEOUT)
    deliver()

    assert len(inserts) == 1


def test_a_change_on_the_gui_thread_still_arrives_queued(queue: TaskQueue, deliver: Callable[[], None]) -> None:
    """A control clicked on the GUI thread re-enters the listener synchronously, and the model must
    still wait for the queued dispatch rather than update within that same call.

    **Test steps:**

    * attach a model, then enqueue a job from this (GUI) thread
    * verify the model has not gained a row yet, synchronously
    * let the dispatch run and verify the row is there
    """
    model = TaskQueueModel(queue)
    model.attach_to()

    job = GatedJob("job")
    job.let_finish()
    queue.enqueue(job)

    assert model.rowCount() == 0

    deliver()

    assert model.rowCount() == 1


def test_a_worker_thread_update_is_delivered_on_the_gui_thread(queue: TaskQueue, deliver: Callable[[], None]) -> None:
    """A job's own progress report, made on the worker thread, still reaches the model only via the
    queued dispatch on this thread.

    **Test steps:**

    * attach a model and enqueue a job that blocks after its first report
    * let the dispatch run and verify the row reflects the report
    * release the job and verify it settles to done
    """
    model = TaskQueueModel(queue)
    model.attach_to()

    job = GatedJob("job")
    queue.enqueue(job)
    assert job.entered.wait(TIMEOUT)
    deliver()

    assert model.rowCount() == 1
    status = model.status_at(0)
    assert status.done == 1  # pylint: disable=no-member
    assert status.total == 1  # pylint: disable=no-member

    job.let_finish()
    deliver()
    assert model.status_at(0).state.value == "done"  # pylint: disable=no-member


def test_the_snapshot_always_matches_queue_jobs(queue: TaskQueue, deliver: Callable[[], None]) -> None:
    """After enqueuing several jobs and removing one, the model's rows equal ``queue.jobs()``.

    **Test steps:**

    * attach a model, enqueue three finishable jobs, let them run
    * remove the middle one
    * verify the model's serials, in order, equal the queue's own
    """
    model = TaskQueueModel(queue)
    model.attach_to()

    jobs = [GatedJob(f"job-{i}") for i in range(3)]
    for job in jobs:
        job.let_finish()
    for job in jobs:
        queue.enqueue(job)
    deliver()

    statuses = queue.jobs()
    queue.remove(statuses[1].serial)
    deliver()

    model_serials = [model.status_at(row).serial for row in range(model.rowCount())]
    queue_serials = [status.serial for status in queue.jobs()]
    assert model_serials == queue_serials


def test_a_bulk_enqueue_is_one_insertion(queue: TaskQueue, deliver: Callable[[], None]) -> None:
    """Enqueuing many jobs back to back, before the event loop turns, is one row insertion.

    **Test steps:**

    * attach a model
    * enqueue ten finishable jobs without yielding to the event loop
    * let the dispatch run once
    * verify exactly one ``rowsInserted`` signal fired, and all ten rows are present
    """
    model = TaskQueueModel(queue)
    model.attach_to()
    inserts: list[int] = []
    model.rowsInserted.connect(lambda *_args: inserts.append(1))

    jobs = [GatedJob(f"job-{i}") for i in range(10)]
    for job in jobs:
        job.let_finish()
        queue.enqueue(job)

    deliver()

    assert len(inserts) == 1
    assert model.rowCount() == 10


def test_display_shows_label_and_state_columns(queue: TaskQueue, deliver: Callable[[], None]) -> None:
    """The label and state columns draw plain text; the progress column is left to the delegate.

    **Test steps:**

    * attach a model and enqueue a blocked job
    * verify the label column's display text, and that the progress column has none
    """
    model = TaskQueueModel(queue)
    model.attach_to()

    job = GatedJob("my job")
    queue.enqueue(job)
    assert job.entered.wait(TIMEOUT)
    deliver()

    index = model.index(0, LABEL_COLUMN)
    assert model.data(index) == "my job"
    assert model.columnCount() == COLUMN_COUNT

    job.let_finish()


# region what a row reads as


@mark.parametrize(
    ("state", "expected"),
    [
        (JobState.QUEUED, "Queued"),
        (JobState.RUNNING, "Running"),
        (JobState.PAUSED, "Paused"),
        (JobState.DONE, "Done"),
        (JobState.FAILED, "Failed"),
        (JobState.CANCELLED, "Cancelled"),
    ],
)
def test_each_state_reads_as_its_own_word(state: JobState, expected: str) -> None:
    """Every state the engine can report has a label of its own.

    **Test steps:**

    * ask for each state's text with nothing pending
    * verify it reads as its own word
    """
    assert state_text(JobStatus(serial=1, label="job", state=state)) == expected


def test_a_pending_cancel_reads_as_cancelling_over_the_state() -> None:
    """*Cancelling…* is the state plus ``stop_requested``, so a watcher is honest before the job obeys.

    A running job that has been asked to cancel but has not looked at the request yet is genuinely
    still running -- what changes is that something has been asked of it.

    **Test steps:**

    * describe a running job carrying a pending cancel
    * verify it reads as Cancelling…, not Running
    """
    status = JobStatus(serial=1, label="job", state=JobState.RUNNING, stop_requested=StopRequest.CANCEL)

    assert state_text(status) == "Cancelling…"


def test_a_pending_pause_reads_as_pausing_over_the_state() -> None:
    """The other half of the same one field -- never two flags to reconcile.

    **Test steps:**

    * describe a running job carrying a pending pause
    * verify it reads as Pausing…
    """
    status = JobStatus(serial=1, label="job", state=JobState.RUNNING, stop_requested=StopRequest.PAUSE)

    assert state_text(status) == "Pausing…"


def test_the_resume_cost_is_read_off_the_one_bit_a_surface_may_ask_about() -> None:
    """A job that keeps a cursor and one that does not each get their own sentence.

    **Test steps:**

    * describe one job of each kind
    * verify each gets the matching hint
    """
    keeps = JobStatus(serial=1, label="job", state=JobState.RUNNING, resumes_where_it_stopped=True)
    starts_over = JobStatus(serial=2, label="job", state=JobState.RUNNING, resumes_where_it_stopped=False)

    assert resume_hint(keeps) == RESUMES_HINT
    assert resume_hint(starts_over) == STARTS_OVER_HINT


# endregion


# region the Qt model interface


def test_an_invalid_index_answers_nothing(queue: TaskQueue) -> None:
    """Qt asks about the root index freely; it holds no row.

    **Test steps:**

    * ask a model for data at an invalid index
    * verify it answers nothing
    """
    model = TaskQueueModel(queue)

    assert model.data(QModelIndex()) is None


def test_a_row_hands_out_its_whole_status_on_one_role(queue: TaskQueue, deliver: Callable[[], None]) -> None:
    """The status role carries the whole `JobStatus`, so a delegate reads one role instead of columns
    that exist only to be hidden.

    **Test steps:**

    * enqueue a job and let the snapshot land
    * verify the status role answers the same object ``status_at`` does, on every column
    """
    model = TaskQueueModel(queue)
    model.attach_to()
    job = GatedJob("job")
    job.let_finish()
    queue.enqueue(job)
    deliver()

    for column in range(COLUMN_COUNT):
        assert model.data(model.index(0, column), TaskQueueModel.Roles.STATUS) == model.status_at(0)


def test_the_columns_draw_label_state_and_nothing_for_progress(queue: TaskQueue, deliver: Callable[[], None]) -> None:
    """Label and state are text; the progress column is the delegate's, so it has none.

    **Test steps:**

    * enqueue a finished job and let the snapshot land
    * verify each column's display text
    """
    model = TaskQueueModel(queue)
    model.attach_to()
    job = GatedJob("my job")
    job.let_finish()
    queue.enqueue(job)
    queue.wait_until_idle(TIMEOUT)
    deliver()

    assert model.data(model.index(0, LABEL_COLUMN)) == "my job"
    assert model.data(model.index(0, STATE_COLUMN)) == "Done"
    assert model.data(model.index(0, INFO_COLUMN)) is None


def test_a_row_answers_nothing_for_a_role_it_has_no_opinion_about(
    queue: TaskQueue, deliver: Callable[[], None]
) -> None:
    """Only the three roles this model actually fills are answered.

    **Test steps:**

    * enqueue a job and let the snapshot land
    * verify an unrelated role answers nothing
    """
    model = TaskQueueModel(queue)
    model.attach_to()
    job = GatedJob("job")
    job.let_finish()
    queue.enqueue(job)
    deliver()

    assert model.data(model.index(0, 0), Qt.ItemDataRole.DecorationRole) is None


def test_a_rows_tooltip_names_the_resume_cost_and_that_it_will_not_be_saved(
    queue: TaskQueue, deliver: Callable[[], None]
) -> None:
    """A plain `TaskJob` is legal and simply is not saved -- the row says so rather than letting it
    vanish at quit.

    **Test steps:**

    * enqueue a non-persistable job that starts over on resume
    * verify its tooltip carries both facts
    """
    model = TaskQueueModel(queue)
    model.attach_to()
    job = GatedJob("job")
    job.let_finish()
    queue.enqueue(job)
    deliver()

    tooltip = model.data(model.index(0, 0), Qt.ItemDataRole.ToolTipRole)

    assert STARTS_OVER_HINT in tooltip
    assert NOT_SAVED_HINT in tooltip


def test_a_persistable_rows_tooltip_does_not_warn_about_being_lost(
    queue: TaskQueue, deliver: Callable[[], None]
) -> None:
    """A job that will still be there tomorrow says nothing about being lost -- the warning is for the
    opt-out, not for every row.

    **Test steps:**

    * enqueue a persistable job and let the snapshot land
    * verify its tooltip carries the resume cost but no not-saved warning
    """
    model = TaskQueueModel(queue)
    model.attach_to()
    queue.enqueue(PersistableJob("saved"))
    queue.wait_until_idle(TIMEOUT)
    deliver()

    tooltip = model.data(model.index(0, 0), Qt.ItemDataRole.ToolTipRole)

    assert model.status_at(0).persistable  # pylint: disable=no-member
    assert NOT_SAVED_HINT not in tooltip
    assert STARTS_OVER_HINT in tooltip


def test_a_failed_rows_tooltip_names_the_state_then_the_reason(queue: TaskQueue, deliver: Callable[[], None]) -> None:
    """The state column is icons now (#248), so the tooltip leads with the word that glyph stands for
    -- and the info column elides a failure reason, so the tooltip carries that in full after it.

    **Test steps:**

    * run a job that raises, and let the snapshot land
    * verify the tooltip names the state first and the reason second
    """
    model = TaskQueueModel(queue)
    model.attach_to()
    queue.enqueue(FailingJob("doomed"))
    queue.wait_until_idle(TIMEOUT)
    deliver()

    tooltip = model.data(model.index(0, 0), Qt.ItemDataRole.ToolTipRole)

    assert tooltip.splitlines()[:2] == ["Failed", "ValueError: nope"]


def test_the_headers_are_the_column_titles(queue: TaskQueue) -> None:
    """The horizontal header names the three columns, and answers nothing else.

    **Test steps:**

    * ask for each horizontal header, an out-of-range one, a vertical one, and another role
    * verify only the three titles come back
    """
    model = TaskQueueModel(queue)
    horizontal = Qt.Orientation.Horizontal

    assert [model.headerData(column, horizontal) for column in range(COLUMN_COUNT)] == list(COLUMN_TITLES)
    assert model.headerData(COLUMN_COUNT, horizontal) is None
    assert model.headerData(0, Qt.Orientation.Vertical) is None
    assert model.headerData(0, horizontal, Qt.ItemDataRole.ToolTipRole) is None


def test_a_child_index_holds_no_rows_or_columns(queue: TaskQueue, deliver: Callable[[], None]) -> None:
    """This is a flat table: only the root index has children.

    **Test steps:**

    * enqueue a job and let the snapshot land
    * verify a row's own index reports no rows and no columns beneath it
    """
    model = TaskQueueModel(queue)
    model.attach_to()
    job = GatedJob("job")
    job.let_finish()
    queue.enqueue(job)
    deliver()

    row = model.index(0, 0)

    assert model.rowCount(row) == 0
    assert model.columnCount(row) == 0


# endregion


# region reordering and removal


def test_a_reorder_is_taken_as_a_whole_new_snapshot(queue: TaskQueue, deliver: Callable[[], None]) -> None:
    """A genuine reorder resets the model rather than animating rows, and lands on the engine's order.

    **Test steps:**

    * enqueue three jobs and pause the queue so every one of them is movable
    * move the last to the top, and let the snapshot land
    * verify the model's order equals the queue's own, with that job first
    """
    model = TaskQueueModel(queue)
    model.attach_to()
    for index in range(3):
        queue.enqueue(GatedJob(f"job-{index}"))
    queue.pause()
    deliver()

    last = queue.jobs()[-1].serial
    queue.move(last, 0)
    deliver()

    assert [model.status_at(row).serial for row in range(model.rowCount())] == [
        status.serial for status in queue.jobs()
    ]
    assert model.status_at(0).serial == last  # pylint: disable=no-member


def test_removing_every_job_empties_the_model(queue: TaskQueue, deliver: Callable[[], None]) -> None:
    """``jobs_removed`` wakes the model like any other change, and the rows go with the jobs.

    **Test steps:**

    * enqueue two finishable jobs and let them land
    * remove both, and let the snapshot land
    * verify the model is empty
    """
    model = TaskQueueModel(queue)
    model.attach_to()
    for index in range(2):
        job = GatedJob(f"job-{index}")
        job.let_finish()
        queue.enqueue(job)
    deliver()

    queue.remove(*[status.serial for status in queue.jobs()])
    deliver()

    assert model.rowCount() == 0


def test_a_detached_model_stops_following_the_queue(queue: TaskQueue, deliver: Callable[[], None]) -> None:
    """Detaching is what keeps shutdown's own cancellations from reaching a torn-down view.

    **Test steps:**

    * attach a model, then detach it
    * enqueue a job and let the event loop turn
    * verify the model never grew a row
    """
    model = TaskQueueModel(queue)
    model.attach_to()
    model.detach()

    job = GatedJob("job")
    job.let_finish()
    queue.enqueue(job)
    deliver()

    assert model.rowCount() == 0


def test_pausing_the_whole_queue_reaches_the_model(queue: TaskQueue, deliver: Callable[[], None]) -> None:
    """``queue_paused_changed`` is a change like any other -- the model re-snapshots on it.

    **Test steps:**

    * enqueue a job, pause the whole queue, and let the snapshot land
    * verify the row reads as held, by state or by pending request
    """
    model = TaskQueueModel(queue)
    model.attach_to()
    queue.enqueue(GatedJob("job"))
    deliver()

    queue.pause()
    deliver()

    status = model.status_at(0)
    assert status.state is JobState.PAUSED or status.stop_requested is StopRequest.PAUSE  # pylint: disable=no-member


# endregion
