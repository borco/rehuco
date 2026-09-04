"""Tests for TaskQueueWidget: the anti-optimism discipline and the controls' own logic (#202).

Uses a real :class:`~rehuco_core.TaskQueue` and cooperating jobs, mirroring ``test_task_queue_model.py``
and ``rehuco-core``'s own ``test_task_queue.py``: every job here honours its stop requests through the
shipped :class:`~rehuco_core.TaskJobBase`, so a row reaching ``paused`` or ``cancelled`` is the engine
genuinely putting it there rather than a fake asserting about itself.

**No test asserts on a cursor.** Whether a job keeps its work is read only through the one bit a
surface may ask about, :attr:`~rehuco_core.JobStatus.resumes_where_it_stopped`
([[appendices.task-queue#job-responsibility]]).
"""

# The widget's surface is small but its behaviours are many -- an enablement matrix, a context menu,
# ten controls and two bulk ones -- and every one below is a distinct fact about it. One cohesive
# module reads better than an arbitrary split.
# pylint: disable=too-many-lines

import logging
from collections.abc import Callable, Iterator
from threading import Event
from time import monotonic, sleep
from typing import Final

import cbor2
import PySide6QtAds as QtAds
from borco_core.logging import LOG_SCOPE_ATTRIBUTE
from borco_pyside.logging import LogWidget
from borco_pyside.logging.log_model import MESSAGE_COLUMN
from borco_pyside.theming import ActionIconThemeHandler, read_resource_bytes
from PySide6.QtCore import QItemSelectionModel, QPoint, Qt
from PySide6.QtWidgets import QMessageBox, QToolBar
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.app_logging import LOG_VIEW_ICON_RESOURCE, shared_log_bridge
from rehuco_agent.settings.logs_settings import shared_logs_settings
from rehuco_agent.tasks import task_queue_widget as widget_module
from rehuco_agent.tasks.task_queue_model import STARTS_OVER_HINT
from rehuco_agent.tasks.task_queue_widget import (
    PAUSE_TOOLTIP,
    STARTS_OVER_SOME_TOOLTIP,
    STATE_DOCK_MANAGER_KEY,
    STATE_VERSION,
    STATE_VERSION_KEY,
    TaskQueueWidget,
)
from rehuco_core import JobControl, JobScope, JobState, JobStatus, TaskJobBase, TaskQueue

TIMEOUT: Final = 5.0
"""How long a test waits for the worker before calling it a failure, in seconds -- a deadlock
detector, not a measurement. Every wait below ends the moment its condition holds."""

YES: Final = QMessageBox.StandardButton.Yes
NO: Final = QMessageBox.StandardButton.No

QUESTION: Final = "rehuco_agent.tasks.task_queue_widget.QMessageBox.question"
"""Where the widget's own confirmation dialog is looked up -- patched there rather than on the class,
so a test never reaches into a module's re-export of a Qt name."""


# region sample jobs


class GatedJob(TaskJobBase):
    """A job that blocks until released, checkpointing while it waits.

    Checkpointing is what makes it usable for every state these tests need: released, it returns and
    is ``done``; asked to pause or cancel, it unwinds at its next checkpoint and is recorded as
    ``paused`` or ``cancelled``. A job that never looked at its request would run to completion and be
    reported ``done`` instead ([[appendices.task-queue#pause-concept]]) -- correct, but untestable here.

    Keeps nothing across a pause, so it is also this module's *starts over on resume* case.

    :param label: the job's label.
    """

    def __init__(self, label: str) -> None:
        super().__init__()
        self.label = label
        self.entered: Final = Event()
        self.__proceed: Final = Event()

    def run(self, control: JobControl) -> None:
        control.report(1, 1)
        self.entered.set()
        while not self.__proceed.wait(0.01):
            self.checkpoint()

    def let_finish(self) -> None:
        """Release the block, letting ``run`` return."""
        self.__proceed.set()


class CursorJob(GatedJob):
    """A job that declares it picks up where it left off -- the *costs nothing to pause* case.

    Declares it rather than implementing a cursor: the declaration is the whole of what crosses the
    boundary, and nothing outside the job class may assume there is a cursor at all."""

    resumes_where_it_stopped = True


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


# endregion


# region fixtures and helpers


@fixture
def queue() -> Iterator[TaskQueue]:
    """A fresh, real `TaskQueue`, shut down after the test.

    Shutdown cancels whatever is still running, and every job here checkpoints, so a blocked job
    unwinds promptly rather than holding teardown for its own timeout.
    """
    built = TaskQueue()
    yield built
    built.shutdown(timeout=TIMEOUT)


@fixture
def widget(queue: TaskQueue, qtbot: QtBot) -> TaskQueueWidget:
    """A `TaskQueueWidget` attached to ``queue``, added to ``qtbot`` for teardown."""
    built = TaskQueueWidget(queue)
    built.attach()
    qtbot.addWidget(built)
    return built


@fixture
def deliver(qtbot: QtBot) -> Callable[[], None]:
    """Pump the Qt event loop long enough for a pending queued snapshot to run."""
    return lambda: qtbot.wait(50)


def ui_of(widget: TaskQueueWidget) -> object:
    """Reach a widget's generated UI object.

    :param widget: the widget to read.
    :returns: its UI object.
    """
    return widget._TaskQueueWidget__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access


def log_dock_of(widget: TaskQueueWidget) -> QtAds.CDockWidget:
    """Reach the shell's Log sub-dock.

    :param widget: the widget to read.
    :returns: the log sub-dock.
    """
    return widget._TaskQueueWidget__log_dock  # type: ignore[attr-defined]  # pylint: disable=protected-access


def log_messages(widget: TaskQueueWidget) -> list[str]:
    """Every message currently on the shell's log surface, top to bottom.

    Read through the surface's own model rather than its rows' painted text: what a record *says* is
    the fact these tests are about, and the table is only how it is shown.

    :param widget: the widget to read.
    :returns: the messages.
    """
    model = widget.log_widget.model
    return [model.data(model.index(row, MESSAGE_COLUMN)) for row in range(model.rowCount())]


def select_rows(widget: TaskQueueWidget, *rows: int) -> None:
    """Select exactly ``rows``, the way a click (or a ctrl-click over several) would.

    :param widget: the widget to act on.
    :param rows: the rows to select.
    """
    view = ui_of(widget).task_view  # type: ignore[attr-defined]
    model = view.model()
    selection = view.selectionModel()
    selection.clear()
    flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
    for row in rows:
        selection.select(model.index(row, 0), flags)


def widget_status(widget: TaskQueueWidget, row: int) -> JobStatus:
    """The `JobStatus` a widget's own model holds for ``row``.

    :param widget: the widget to read.
    :param row: the row to read.
    :returns: that row's status.
    """
    return widget._TaskQueueWidget__model.status_at(row)  # type: ignore[attr-defined]  # pylint: disable=protected-access


def widget_row_count(widget: TaskQueueWidget) -> int:
    """How many rows a widget's own model holds.

    :param widget: the widget to read.
    :returns: its row count.
    """
    return widget._TaskQueueWidget__model.rowCount()  # type: ignore[attr-defined]  # pylint: disable=protected-access


def job_serial(queue: TaskQueue, label: str) -> int:
    """The serial of the queue's job named ``label``.

    :param queue: the queue to search.
    :param label: the label to find.
    :returns: that job's serial.
    """
    return next(status.serial for status in queue.jobs() if status.label == label)


def wait_until(predicate: Callable[[], bool], description: str) -> None:
    """Wait until ``predicate`` holds, polling rather than sleeping a fixed spell.

    :param predicate: what to wait for.
    :param description: what it is, for the failure message.
    :raises AssertionError: if it never holds.
    """
    deadline = monotonic() + TIMEOUT
    while monotonic() < deadline:
        if predicate():
            return
        sleep(0.01)
    raise AssertionError(f"timed out waiting for {description}")


def wait_for_state(queue: TaskQueue, label: str, state: JobState) -> None:
    """Wait until the job named ``label`` reaches ``state``.

    Polls rather than waits on an event, because the transition being watched is one the *worker*
    makes on its own -- the same reason ``rehuco-core``'s own tests keep a settling helper.

    :param queue: the queue to watch.
    :param label: the job to watch.
    :param state: the state to wait for.
    :raises AssertionError: if it never gets there.
    """
    deadline = monotonic() + TIMEOUT
    while monotonic() < deadline:
        status = next((held for held in queue.jobs() if held.label == label), None)
        if status is not None and status.state is state:
            return
        sleep(0.01)
    raise AssertionError(f"{label!r} never reached {state}")


def running_job(queue: TaskQueue, label: str = "running", job: GatedJob | None = None) -> GatedJob:
    """Enqueue a job and wait until it is genuinely executing.

    :param queue: the queue to fill.
    :param label: the job's label, when one is not supplied.
    :param job: the job to enqueue; a plain `GatedJob` unless given.
    :returns: the running job.
    """
    started = job if job is not None else GatedJob(label)
    queue.enqueue(started)
    assert started.entered.wait(TIMEOUT)
    return started


def settle_one_job_into(queue: TaskQueue, state: JobState, deliver: Callable[[], None]) -> int:
    """Leave the queue holding a job in ``state``, and say which row it is.

    ``queued`` needs a second job: :meth:`~rehuco_core.TaskQueue.pause` holds only the jobs that
    already exist, and a newly enqueued one runs immediately regardless -- so the only honest way to
    hold a job in line is to keep the worker busy with another
    ([[appendices.task-queue#pause-concept]]).

    :param queue: the queue to fill.
    :param state: the state to leave a job in.
    :param deliver: pumps the event loop so the snapshot lands.
    :returns: the row the job in ``state`` occupies.
    """
    row = 0
    if state is JobState.FAILED:
        queue.enqueue(FailingJob("job"))
        wait_for_state(queue, "job", JobState.FAILED)
    elif state is JobState.DONE:
        job = GatedJob("job")
        job.let_finish()
        queue.enqueue(job)
        wait_for_state(queue, "job", JobState.DONE)
    elif state is JobState.CANCELLED:
        running_job(queue, "job")
        queue.cancel(job_serial(queue, "job"))
        wait_for_state(queue, "job", JobState.CANCELLED)
    elif state is JobState.PAUSED:
        running_job(queue, "job")
        queue.pause_job(job_serial(queue, "job"))
        wait_for_state(queue, "job", JobState.PAUSED)
    elif state is JobState.RUNNING:
        running_job(queue, "job")
    else:  # QUEUED -- held behind a blocker that keeps the single worker busy
        running_job(queue, "blocker")
        queue.enqueue(GatedJob("job"))
        row = 1
    deliver()
    return row


# endregion


# region the view follows the engine, never its own guess


def test_the_pause_action_does_not_change_its_own_state_until_the_engine_reports_it(
    widget: TaskQueueWidget, queue: TaskQueue, mocker: MockerFixture, deliver: Callable[[], None]
) -> None:
    """The anti-optimism test: patch ``pause_job`` to do nothing, click Pause, and the row must not
    read paused -- only a real snapshot from the engine may say so.

    **Test steps:**

    * enqueue a blocked (running) job and select its row
    * patch ``queue.pause_job`` to a no-op
    * trigger the Pause action
    * verify the row still reads ``running``, not ``paused``
    """
    running_job(queue, "job")
    deliver()
    select_rows(widget, 0)

    mocker.patch.object(queue, "pause_job")
    ui_of(widget).pause_action.trigger()  # type: ignore[attr-defined]
    deliver()

    assert widget_status(widget, 0).state is JobState.RUNNING


def test_a_move_the_engine_clamps_leaves_the_row_where_the_engine_put_it(
    widget: TaskQueueWidget, queue: TaskQueue, deliver: Callable[[], None]
) -> None:
    """Asking to move a queued job above the running one leaves the view exactly where the engine
    clamped it -- the row order always equals ``queue.jobs()``, never the request.

    **Test steps:**

    * enqueue a blocked (running) job and a queued one behind it
    * select the queued job and move it to the top
    * verify the row order still matches the engine's own, running job first
    """
    running_job(queue, "running")
    queue.enqueue(GatedJob("queued"))
    deliver()

    select_rows(widget, 1)
    ui_of(widget).move_to_top_action.trigger()  # type: ignore[attr-defined]
    deliver()

    assert [widget_status(widget, row).serial for row in range(widget_row_count(widget))] == [
        status.serial for status in queue.jobs()
    ]
    assert widget_status(widget, 0).label == "running"


# endregion


# region the toolbar


def test_clear_done_ends_the_toolbar_s_queue_controls(widget: TaskQueueWidget) -> None:
    """*Clear Done* acts on the whole queue rather than the selection, so it sits in its own slot after
    the reorder group, not folded into the per-selection run above it (#249) -- and the Log toggle, which
    acts on this shell rather than on the queue at all, gets a separated trailing slot of its own after
    it (#276).

    **Test steps:**

    * read the toolbar's own action list
    * verify Clear Done follows a separator, and the Log toggle a further one
    """
    # direct children only: the Log sub-dock's own surface carries a toolbar of its own, and a plain
    # recursive search finds whichever of the two Qt built first
    toolbar = widget.findChildren(QToolBar, options=Qt.FindChildOption.FindDirectChildrenOnly)[0]
    actions = toolbar.actions()

    assert actions[-1] is log_dock_of(widget).toggleViewAction()
    assert actions[-2].isSeparator()
    assert actions[-3] is ui_of(widget).clear_done_action  # type: ignore[attr-defined]
    assert actions[-4].isSeparator()


# endregion


# region the context menu


def test_the_context_menu_offers_the_per_selection_actions_then_the_sweeps(
    widget: TaskQueueWidget, mocker: MockerFixture
) -> None:
    """The menu is the four per-selection actions plus Clear, then a separator, then the three sweeps.

    The separator is the point: a sweep acts on the *queue*, not on what is selected, and running one
    by reflex after aiming at a row is exactly what the split guards against.

    **Test steps:**

    * patch ``QMenu`` so nothing is actually shown
    * ask for the context menu
    * verify the entries and the separator, in order
    """
    menu = mocker.patch.object(widget_module, "QMenu").return_value
    ui = ui_of(widget)

    widget._TaskQueueWidget__show_context_menu(QPoint(0, 0))  # type: ignore[attr-defined]  # pylint: disable=protected-access

    assert [call.args[0] for call in menu.addAction.call_args_list] == [
        ui.pause_action,  # type: ignore[attr-defined]
        ui.resume_action,  # type: ignore[attr-defined]
        ui.cancel_action,  # type: ignore[attr-defined]
        ui.retry_action,  # type: ignore[attr-defined]
        ui.clear_action,  # type: ignore[attr-defined]
        ui.clear_done_action,  # type: ignore[attr-defined]
        ui.clear_failed_action,  # type: ignore[attr-defined]
        ui.clear_all_action,  # type: ignore[attr-defined]
    ]
    menu.addSeparator.assert_called_once_with()
    menu.exec.assert_called_once()


def test_the_clear_entry_counts_what_it_would_remove(
    widget: TaskQueueWidget, queue: TaskQueue, mocker: MockerFixture, deliver: Callable[[], None]
) -> None:
    """*Clear job* becomes *Clear 2 jobs* over a multi-selection, so the entry says what it will do.

    **Test steps:**

    * leave two finished jobs in the queue and select both
    * open the context menu, and verify the Clear entry names the count
    * select one and verify it goes back to the singular
    """
    mocker.patch.object(widget_module, "QMenu")
    for index in range(2):
        job = GatedJob(f"job-{index}")
        job.let_finish()
        queue.enqueue(job)
        wait_for_state(queue, f"job-{index}", JobState.DONE)
    deliver()
    ui = ui_of(widget)

    select_rows(widget, 0, 1)
    widget._TaskQueueWidget__show_context_menu(QPoint(0, 0))  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert ui.clear_action.text() == "Clear 2 jobs"  # type: ignore[attr-defined]

    select_rows(widget, 0)
    widget._TaskQueueWidget__show_context_menu(QPoint(0, 0))  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert ui.clear_action.text() == "Clear job"  # type: ignore[attr-defined]


# endregion


# region enablement across every state


def test_every_control_is_disabled_with_nothing_selected(widget: TaskQueueWidget) -> None:
    """An empty selection is nothing to act on, so every per-selection control is off.

    **Test steps:**

    * build a widget over an empty queue
    * verify each per-selection action is disabled
    """
    ui = ui_of(widget)

    for action in (
        ui.pause_action,  # type: ignore[attr-defined]
        ui.resume_action,  # type: ignore[attr-defined]
        ui.cancel_action,  # type: ignore[attr-defined]
        ui.retry_action,  # type: ignore[attr-defined]
        ui.clear_action,  # type: ignore[attr-defined]
        ui.move_to_top_action,  # type: ignore[attr-defined]
        ui.move_up_action,  # type: ignore[attr-defined]
        ui.move_down_action,  # type: ignore[attr-defined]
        ui.move_to_bottom_action,  # type: ignore[attr-defined]
    ):
        assert not action.isEnabled(), action.text()


@mark.parametrize(
    ("state", "expected"),
    [
        (JobState.QUEUED, {"pause", "cancel", "clear", "move"}),
        (JobState.RUNNING, {"pause", "cancel", "clear"}),
        (JobState.PAUSED, {"resume", "cancel", "clear", "move"}),
        (JobState.DONE, {"clear"}),
        (JobState.FAILED, {"retry", "clear"}),
        (JobState.CANCELLED, {"retry", "clear"}),
    ],
)
def test_each_state_enables_exactly_the_controls_that_can_act_on_it(
    widget: TaskQueueWidget, queue: TaskQueue, deliver: Callable[[], None], state: JobState, expected: set[str]
) -> None:
    """Every control is offered for exactly the states the engine would let it act on.

    A **running** job never moves -- it cannot be made to have started later than it did -- and a
    finished one has no position left to matter. Retry covers only ``failed`` and ``cancelled``:
    re-running work that succeeded is not what it is for ([[appendices.task-queue#kept]]).

    **Test steps:**

    * put one job into ``state`` and select it
    * verify exactly the expected controls are enabled
    """
    row = settle_one_job_into(queue, state, deliver)
    select_rows(widget, row)
    ui = ui_of(widget)

    actual = {
        "pause": ui.pause_action.isEnabled(),  # type: ignore[attr-defined]
        "resume": ui.resume_action.isEnabled(),  # type: ignore[attr-defined]
        "cancel": ui.cancel_action.isEnabled(),  # type: ignore[attr-defined]
        "retry": ui.retry_action.isEnabled(),  # type: ignore[attr-defined]
        "clear": ui.clear_action.isEnabled(),  # type: ignore[attr-defined]
        "move": ui.move_to_top_action.isEnabled(),  # type: ignore[attr-defined]
    }

    assert {name for name, is_on in actual.items() if is_on} == expected


def test_resume_is_offered_for_a_running_job_with_a_stop_pending(
    widget: TaskQueueWidget, queue: TaskQueue, mocker: MockerFixture, deliver: Callable[[], None]
) -> None:
    """Cancel-then-Resume is a recoverable mis-click while the job has not looked at the request yet.

    The job is kept from acting on the request (its checkpoint patched out) so the row stays
    ``running`` with a stop pending -- exactly the window the retraction exists for.

    **Test steps:**

    * enqueue a blocked job, stop it from checkpointing, and ask it to cancel
    * select it, and verify Resume is offered while it still reads as running
    """
    job = running_job(queue, "job")
    mocker.patch.object(job, "checkpoint")
    queue.cancel(job_serial(queue, "job"))
    deliver()
    select_rows(widget, 0)

    assert widget_status(widget, 0).state is JobState.RUNNING
    assert ui_of(widget).resume_action.isEnabled()  # type: ignore[attr-defined]

    # Release the gate directly, rather than leaving teardown to it. This is the one test that patches
    # `checkpoint` out, and that is exactly what a job unwinds on -- so the cancel `queue.shutdown`
    # sends can never land, and the fixture sat out its whole TIMEOUT before giving up on a job that
    # was never going to answer. The patch is still in force at that point: every autouse fixture in
    # this package's conftest requests `mocker`, so it is built before this test's own fixtures and
    # torn down after them (#262).
    job.let_finish()


def test_a_mixed_selection_moves_nothing(
    widget: TaskQueueWidget, queue: TaskQueue, deliver: Callable[[], None]
) -> None:
    """Reordering is offered only when *every* selected row can move -- a partial move would silently
    leave some of the selection where it was.

    **Test steps:**

    * put one running job beside one queued one, and select both
    * verify the move controls are off, while Clear (which acts on both) is on
    """
    running_job(queue, "running")
    queue.enqueue(GatedJob("queued"))
    deliver()

    select_rows(widget, 0, 1)
    ui = ui_of(widget)

    assert not ui.move_to_top_action.isEnabled()  # type: ignore[attr-defined]
    assert ui.clear_action.isEnabled()  # type: ignore[attr-defined]


def test_a_retry_is_refused_over_a_selection_holding_anything_unfinished(
    widget: TaskQueueWidget, queue: TaskQueue, deliver: Callable[[], None]
) -> None:
    """Retry is finished-only, so one unfinished row in the selection withdraws it.

    **Test steps:**

    * leave a failed job beside a queued one, and select both
    * verify Retry is not offered
    """
    queue.enqueue(FailingJob("failed"))
    wait_for_state(queue, "failed", JobState.FAILED)
    running_job(queue, "blocker")
    queue.enqueue(GatedJob("queued"))
    deliver()

    select_rows(widget, 0, 2)

    assert not ui_of(widget).retry_action.isEnabled()  # type: ignore[attr-defined]


# endregion


# region what Pause says it will cost


def test_pause_says_nothing_extra_for_a_job_that_keeps_its_work(
    widget: TaskQueueWidget, queue: TaskQueue, deliver: Callable[[], None]
) -> None:
    """A job with a cursor loses nothing, so Pause carries only its plain tooltip.

    **Test steps:**

    * run a job that resumes where it stopped, and select it
    * verify Pause's tooltip carries no cost line
    """
    running_job(queue, job=CursorJob("keeps"))
    deliver()
    select_rows(widget, 0)

    assert ui_of(widget).pause_action.toolTip() == PAUSE_TOOLTIP  # type: ignore[attr-defined]


def test_pause_says_a_single_job_would_start_over(
    widget: TaskQueueWidget, queue: TaskQueue, deliver: Callable[[], None]
) -> None:
    """A row that starts over says so **on Pause**, not only on its own tooltip -- and Pause stays
    enabled, because starting over is wasteful rather than wrong.

    **Test steps:**

    * run a job that keeps nothing, and select it
    * verify Pause's tooltip names the cost, and the action is still enabled
    """
    running_job(queue, "starts over")
    deliver()
    select_rows(widget, 0)
    ui = ui_of(widget)

    assert STARTS_OVER_HINT in ui.pause_action.toolTip()  # type: ignore[attr-defined]
    assert ui.pause_action.isEnabled()  # type: ignore[attr-defined]


def test_pause_says_some_of_a_batch_would_start_over(
    widget: TaskQueueWidget, queue: TaskQueue, deliver: Callable[[], None]
) -> None:
    """Over a mixed multi-selection the warning is phrased for a batch rather than for one row.

    **Test steps:**

    * run a job that keeps its work with one behind it that does not, and select both
    * verify Pause's tooltip uses the batch wording
    """
    running_job(queue, job=CursorJob("keeps"))
    queue.enqueue(GatedJob("starts over"))
    deliver()
    select_rows(widget, 0, 1)

    assert STARTS_OVER_SOME_TOOLTIP in ui_of(widget).pause_action.toolTip()  # type: ignore[attr-defined]


def test_a_batch_that_all_keeps_its_work_is_not_warned_about(
    widget: TaskQueueWidget, queue: TaskQueue, deliver: Callable[[], None]
) -> None:
    """A multi-selection where nothing starts over gets no warning either.

    **Test steps:**

    * run two jobs that both keep their work, and select both
    * verify Pause's tooltip carries no cost line
    """
    running_job(queue, job=CursorJob("keeps"))
    queue.enqueue(CursorJob("also keeps"))
    deliver()
    select_rows(widget, 0, 1)

    assert ui_of(widget).pause_action.toolTip() == PAUSE_TOOLTIP  # type: ignore[attr-defined]


def test_a_finished_row_costs_nothing_to_pause(
    widget: TaskQueueWidget, queue: TaskQueue, deliver: Callable[[], None]
) -> None:
    """Pause would not touch a finished job, so it is not counted when naming the cost.

    **Test steps:**

    * let a job that keeps nothing run to completion, then select it
    * verify Pause's tooltip carries no cost line
    """
    settle_one_job_into(queue, JobState.DONE, deliver)
    select_rows(widget, 0)

    assert ui_of(widget).pause_action.toolTip() == PAUSE_TOOLTIP  # type: ignore[attr-defined]


# endregion


# region the bulk pair


def test_the_bulk_pair_is_off_over_an_empty_queue(widget: TaskQueueWidget) -> None:
    """An empty queue is neither running nor held, so neither bulk control is offered.

    **Test steps:**

    * build a widget over an empty queue
    * verify both bulk actions are disabled
    """
    ui = ui_of(widget)

    assert not ui.pause_all_action.isEnabled()  # type: ignore[attr-defined]
    assert not ui.resume_all_action.isEnabled()  # type: ignore[attr-defined]


def test_resume_all_is_offered_while_one_job_is_held_beside_one_still_running(
    widget: TaskQueueWidget, queue: TaskQueue, deliver: Callable[[], None]
) -> None:
    """The bulk pair mirrors what its own calls would touch, not the derived ``queue.paused``.

    ``paused`` means *every* unfinished job is held, so it is ``False`` here -- and gating Resume All
    on it would refuse a resume the engine would happily perform.

    **Test steps:**

    * pause one queued job while another runs
    * verify the queue does not read as paused, yet both bulk controls are offered
    """
    running_job(queue, "running")
    queue.enqueue(GatedJob("queued"))
    queue.pause_job(job_serial(queue, "queued"))
    deliver()
    ui = ui_of(widget)

    assert not queue.paused
    assert ui.resume_all_action.isEnabled()  # type: ignore[attr-defined]
    assert ui.pause_all_action.isEnabled()  # type: ignore[attr-defined]


def test_pause_all_goes_off_once_everything_is_held(
    widget: TaskQueueWidget, queue: TaskQueue, deliver: Callable[[], None]
) -> None:
    """With nothing left to ask, Pause All is not offered -- and Resume All is.

    **Test steps:**

    * run a job, then pause the whole queue and let it settle
    * verify Pause All is off and Resume All is on
    """
    running_job(queue, "job")
    queue.pause()
    wait_for_state(queue, "job", JobState.PAUSED)
    deliver()
    ui = ui_of(widget)

    assert not ui.pause_all_action.isEnabled()  # type: ignore[attr-defined]
    assert ui.resume_all_action.isEnabled()  # type: ignore[attr-defined]


def test_the_bulk_pair_is_off_once_every_job_has_finished(
    widget: TaskQueueWidget, queue: TaskQueue, deliver: Callable[[], None]
) -> None:
    """Finished rows are kept, but neither bulk control has anything to do with them.

    **Test steps:**

    * run one job to completion
    * verify both bulk actions are disabled while the row remains
    """
    settle_one_job_into(queue, JobState.DONE, deliver)
    ui = ui_of(widget)

    assert widget_row_count(widget) == 1
    assert not ui.pause_all_action.isEnabled()  # type: ignore[attr-defined]
    assert not ui.resume_all_action.isEnabled()  # type: ignore[attr-defined]


def test_the_bulk_controls_hold_and_release_every_unfinished_job(
    widget: TaskQueueWidget, queue: TaskQueue, deliver: Callable[[], None]
) -> None:
    """Pause All holds *everything* unfinished, and Resume All puts it all back.

    Asserted through the queue's own state rather than by patching its methods: the bulk actions are
    connected to the engine's bound ``pause``/``resume`` at construction, so a later patch would never
    be seen -- and what is worth pinning is the effect anyway.

    **Test steps:**

    * run one job with another queued behind it
    * trigger Pause All, and verify the whole queue reads as held
    * trigger Resume All, and verify it does not
    """
    running_job(queue, "running")
    queue.enqueue(GatedJob("queued"))
    deliver()
    ui = ui_of(widget)

    ui.pause_all_action.trigger()  # type: ignore[attr-defined]
    wait_until(lambda: queue.paused, "the queue to read as paused")
    deliver()

    ui.resume_all_action.trigger()  # type: ignore[attr-defined]
    wait_until(lambda: not queue.paused, "the queue to stop reading as paused")


# endregion


# region the per-selection actions


def test_pause_and_resume_act_on_every_selected_row(
    widget: TaskQueueWidget, queue: TaskQueue, mocker: MockerFixture, deliver: Callable[[], None]
) -> None:
    """Both controls act on the whole selection, one engine call per row.

    **Test steps:**

    * hold one job beside one still running, and select both so each control is enabled
    * trigger Pause, then Resume
    * verify each engine call was made once per selected serial
    """
    running_job(queue, "running")
    queue.enqueue(GatedJob("queued"))
    queue.pause_job(job_serial(queue, "queued"))
    deliver()
    serials = [status.serial for status in queue.jobs()]
    pause_job = mocker.patch.object(queue, "pause_job")
    resume_job = mocker.patch.object(queue, "resume_job")
    ui = ui_of(widget)

    select_rows(widget, 0, 1)
    ui.pause_action.trigger()  # type: ignore[attr-defined]
    ui.resume_action.trigger()  # type: ignore[attr-defined]

    assert [call.args[0] for call in pause_job.call_args_list] == serials
    assert [call.args[0] for call in resume_job.call_args_list] == serials


def test_cancel_prompts_once_for_a_whole_batch(
    widget: TaskQueueWidget, queue: TaskQueue, mocker: MockerFixture, deliver: Callable[[], None]
) -> None:
    """Cancel asks **once** however many rows are selected -- never once per row.

    **Test steps:**

    * leave three unfinished jobs in the queue and select all of them
    * answer Yes to the prompt
    * verify exactly one dialog was raised, and every job was cancelled
    """
    running_job(queue, "running")
    for index in range(2):
        queue.enqueue(GatedJob(f"queued-{index}"))
    deliver()
    serials = [status.serial for status in queue.jobs()]
    question = mocker.patch(QUESTION, return_value=YES)
    cancel = mocker.patch.object(queue, "cancel")

    select_rows(widget, 0, 1, 2)
    ui_of(widget).cancel_action.trigger()  # type: ignore[attr-defined]

    question.assert_called_once()
    assert [call.args[0] for call in cancel.call_args_list] == serials


def test_a_refused_cancel_cancels_nothing(
    widget: TaskQueueWidget, queue: TaskQueue, mocker: MockerFixture, deliver: Callable[[], None]
) -> None:
    """Answering No leaves every selected job exactly as it was.

    **Test steps:**

    * run a job, select it, and answer No to the prompt
    * verify the engine was never asked to cancel
    """
    running_job(queue, "job")
    deliver()
    mocker.patch(QUESTION, return_value=NO)
    cancel = mocker.patch.object(queue, "cancel")

    select_rows(widget, 0)
    ui_of(widget).cancel_action.trigger()  # type: ignore[attr-defined]

    cancel.assert_not_called()


def test_cancel_over_an_empty_selection_never_prompts(widget: TaskQueueWidget, mocker: MockerFixture) -> None:
    """With nothing selected there is nothing to confirm, so no dialog is raised at all.

    **Test steps:**

    * call the Cancel handler with an empty selection
    * verify no prompt appeared
    """
    question = mocker.patch(QUESTION)

    widget._TaskQueueWidget__cancel_selection()  # type: ignore[attr-defined]  # pylint: disable=protected-access

    question.assert_not_called()


def test_retry_asks_the_engine_to_run_a_failed_job_again(
    widget: TaskQueueWidget, queue: TaskQueue, mocker: MockerFixture, deliver: Callable[[], None]
) -> None:
    """Retry hands the failed job back to the engine, which is where *from the top* is decided.

    Asserted at the call rather than at the resulting state: a retried job is re-queued and the single
    worker picks it straight back up, so any state read afterwards is a race with the worker.

    **Test steps:**

    * run a job that fails, select it, and trigger Retry
    * verify the engine was asked to retry exactly that serial
    """
    settle_one_job_into(queue, JobState.FAILED, deliver)
    serial = job_serial(queue, "job")
    retry = mocker.patch.object(queue, "retry")

    select_rows(widget, 0)
    ui_of(widget).retry_action.trigger()  # type: ignore[attr-defined]

    retry.assert_called_once_with(serial)


def test_clear_removes_exactly_the_selected_rows(
    widget: TaskQueueWidget, queue: TaskQueue, deliver: Callable[[], None]
) -> None:
    """Clear is the only way a job leaves the queue, and it takes only what was aimed at.

    **Test steps:**

    * finish two jobs, select the first, and trigger Clear
    * verify only the other one is left
    """
    for index in range(2):
        job = GatedJob(f"job-{index}")
        job.let_finish()
        queue.enqueue(job)
        wait_for_state(queue, f"job-{index}", JobState.DONE)
    deliver()

    select_rows(widget, 0)
    ui_of(widget).clear_action.trigger()  # type: ignore[attr-defined]
    deliver()

    assert [status.label for status in queue.jobs()] == ["job-1"]


def test_clear_over_an_empty_selection_removes_nothing(
    widget: TaskQueueWidget, queue: TaskQueue, mocker: MockerFixture
) -> None:
    """Nothing selected is nothing to clear.

    **Test steps:**

    * call the Clear handler with an empty selection
    * verify the engine was never asked to remove anything
    """
    remove = mocker.patch.object(queue, "remove")

    widget._TaskQueueWidget__clear_selection()  # type: ignore[attr-defined]  # pylint: disable=protected-access

    remove.assert_not_called()


def test_the_sweeps_drop_only_their_own_kind(
    widget: TaskQueueWidget, queue: TaskQueue, deliver: Callable[[], None]
) -> None:
    """*Clear done* and *Clear failed* each take exactly one kind, leaving the rest -- deciding which
    jobs a sweep drops is the view's business, which is why #237 deleted the engine's own sweep.

    **Test steps:**

    * leave one done job, one failed job and one running job in the queue
    * trigger Clear done, then Clear failed
    * verify each removed only its own kind, and the unfinished job survived both
    """
    done = GatedJob("done")
    done.let_finish()
    queue.enqueue(done)
    wait_for_state(queue, "done", JobState.DONE)
    queue.enqueue(FailingJob("failed"))
    wait_for_state(queue, "failed", JobState.FAILED)
    running_job(queue, "running")
    deliver()
    ui = ui_of(widget)

    ui.clear_done_action.trigger()  # type: ignore[attr-defined]
    deliver()
    assert sorted(status.label for status in queue.jobs()) == ["failed", "running"]

    ui.clear_failed_action.trigger()  # type: ignore[attr-defined]
    deliver()
    assert [status.label for status in queue.jobs()] == ["running"]


def test_a_sweep_with_nothing_of_its_kind_removes_nothing(
    widget: TaskQueueWidget, queue: TaskQueue, mocker: MockerFixture, deliver: Callable[[], None]
) -> None:
    """A sweep over a queue holding none of its kind is a no-op, not an empty removal.

    **Test steps:**

    * leave one running job in the queue and trigger Clear done
    * verify the engine was never asked to remove anything
    """
    running_job(queue, "running")
    deliver()
    remove = mocker.patch.object(queue, "remove")

    ui_of(widget).clear_done_action.trigger()  # type: ignore[attr-defined]

    remove.assert_not_called()


def test_clear_all_cancels_what_is_unfinished_and_empties_the_queue(
    widget: TaskQueueWidget, queue: TaskQueue, deliver: Callable[[], None]
) -> None:
    """*Clear all* is a clean slate: it stops whatever is unfinished first, then removes everything.

    **Test steps:**

    * leave one done job beside one running one
    * trigger Clear all
    * verify the queue is empty
    """
    done = GatedJob("done")
    done.let_finish()
    queue.enqueue(done)
    wait_for_state(queue, "done", JobState.DONE)
    running_job(queue, "running")
    deliver()

    ui_of(widget).clear_all_action.trigger()  # type: ignore[attr-defined]
    deliver()

    assert queue.jobs() == ()


def test_clear_all_over_an_empty_queue_removes_nothing(
    widget: TaskQueueWidget, queue: TaskQueue, mocker: MockerFixture
) -> None:
    """An empty queue is already a clean slate.

    **Test steps:**

    * trigger Clear all over an empty queue
    * verify the engine was never asked to remove anything
    """
    remove = mocker.patch.object(queue, "remove")

    ui_of(widget).clear_all_action.trigger()  # type: ignore[attr-defined]

    remove.assert_not_called()


def test_retry_never_prompts(
    widget: TaskQueueWidget, queue: TaskQueue, mocker: MockerFixture, deliver: Callable[[], None]
) -> None:
    """Retry acts immediately, with no confirmation dialog -- unlike Cancel.

    **Test steps:**

    * run a job to completion, select it, and trigger Retry
    * verify no dialog was ever asked for
    """
    question = mocker.patch(QUESTION)
    settle_one_job_into(queue, JobState.FAILED, deliver)

    select_rows(widget, 0)
    ui_of(widget).retry_action.trigger()  # type: ignore[attr-defined]

    question.assert_not_called()


def test_pause_and_resume_never_prompt(
    widget: TaskQueueWidget, queue: TaskQueue, mocker: MockerFixture, deliver: Callable[[], None]
) -> None:
    """Pausing informs rather than blocks, so neither control raises a dialog -- even over a job that
    will lose the work it has done.

    **Test steps:**

    * run a job that keeps nothing, select it, and trigger Pause then Resume
    * verify no dialog was ever asked for
    """
    question = mocker.patch(QUESTION)
    running_job(queue, "starts over")
    deliver()
    ui = ui_of(widget)

    select_rows(widget, 0)
    ui.pause_action.trigger()  # type: ignore[attr-defined]
    wait_for_state(queue, "starts over", JobState.PAUSED)
    deliver()
    select_rows(widget, 0)
    ui.resume_action.trigger()  # type: ignore[attr-defined]

    question.assert_not_called()


# endregion


# region reordering


def test_up_and_down_move_a_row_one_place(
    widget: TaskQueueWidget, queue: TaskQueue, deliver: Callable[[], None]
) -> None:
    """Down then Up returns a row to where it started.

    **Test steps:**

    * hold three queued jobs behind a blocker, and select the first of them
    * trigger Down, then Up
    * verify the order came back to the original
    """
    running_job(queue, "blocker")
    for index in range(3):
        queue.enqueue(GatedJob(f"job-{index}"))
    deliver()
    ui = ui_of(widget)

    select_rows(widget, 1)
    ui.move_down_action.trigger()  # type: ignore[attr-defined]
    deliver()
    assert [status.label for status in queue.jobs()] == ["blocker", "job-1", "job-0", "job-2"]

    select_rows(widget, 2)
    ui.move_up_action.trigger()  # type: ignore[attr-defined]
    deliver()
    assert [status.label for status in queue.jobs()] == ["blocker", "job-0", "job-1", "job-2"]


def test_top_and_bottom_keep_a_multi_selection_in_its_own_order(
    widget: TaskQueueWidget, queue: TaskQueue, deliver: Callable[[], None]
) -> None:
    """Moving several rows to an end preserves their relative order there.

    **Test steps:**

    * hold four queued jobs behind a blocker and select the last two
    * trigger Top, and verify they lead in their original order
    * select them again and verify Bottom does the same
    """
    running_job(queue, "blocker")
    for index in range(4):
        queue.enqueue(GatedJob(f"job-{index}"))
    deliver()
    ui = ui_of(widget)

    select_rows(widget, 3, 4)
    ui.move_to_top_action.trigger()  # type: ignore[attr-defined]
    deliver()
    assert [status.label for status in queue.jobs()] == ["blocker", "job-2", "job-3", "job-0", "job-1"]

    select_rows(widget, 1, 2)
    ui.move_to_bottom_action.trigger()  # type: ignore[attr-defined]
    deliver()
    assert [status.label for status in queue.jobs()] == ["blocker", "job-0", "job-1", "job-2", "job-3"]


def test_moving_up_from_the_top_of_the_movable_run_stays_put(
    widget: TaskQueueWidget, queue: TaskQueue, deliver: Callable[[], None]
) -> None:
    """The engine clamps a move that reaches past the movable run, and the view follows it.

    **Test steps:**

    * hold two queued jobs behind a blocker, select the first of them, and trigger Up
    * verify the order is unchanged
    """
    running_job(queue, "blocker")
    for index in range(2):
        queue.enqueue(GatedJob(f"job-{index}"))
    deliver()

    select_rows(widget, 1)
    ui_of(widget).move_up_action.trigger()  # type: ignore[attr-defined]
    deliver()

    assert [status.label for status in queue.jobs()] == ["blocker", "job-0", "job-1"]


# endregion


# region the Log sub-dock


@fixture
def scoped_logger() -> Iterator[logging.Logger]:
    """Provide a logger feeding the shared bridge and nothing else.

    Propagation off, so these records reach the bridge under test and never the console or another
    handler a different test left behind.

    :returns: the logger.
    """
    bridge = shared_log_bridge()
    logger = logging.getLogger("rehuco_agent.tests.task_queue_log_dock")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.addHandler(bridge)
    yield logger
    logger.removeHandler(bridge)


def two_finished_jobs(queue: TaskQueue, deliver: Callable[[], None]) -> None:
    """Leave the queue holding two ``done`` jobs -- ``first`` on row 0, ``second`` on row 1.

    Finished rather than running, because what these tests are about is the surface following a
    *selection*: a settled queue is what keeps the rows still while it does.

    :param queue: the queue to fill.
    :param deliver: pumps the event loop so the snapshot lands.
    """
    for label in ("first", "second"):
        job = GatedJob(label)
        job.let_finish()
        queue.enqueue(job)
        wait_for_state(queue, label, JobState.DONE)
    deliver()


def log_a_record_for(queue: TaskQueue, logger: logging.Logger, label: str) -> None:
    """Write one record under the scope of the queue's job named ``label``.

    Logged with the scope named at the call site rather than from inside the job: what the job's own
    ``run`` is wrapped in is the engine's contract (#271), and what this module is about is the surface
    that reads it.

    :param queue: the queue holding the job.
    :param logger: the logger feeding the shared bridge.
    :param label: the job whose scope to write under; also the record's message.
    """
    logger.info(f"about {label}", extra={LOG_SCOPE_ATTRIBUTE: JobScope(job_serial(queue, label))})


def test_the_log_sub_dock_exists_and_starts_hidden(widget: TaskQueueWidget) -> None:
    """The shell's Log sub-dock is built, and hidden until asked for (#276).

    The table alone is what a reader who only wants progress sees.

    **Test steps:**

    * build the widget
    * verify the sub-dock exists, hosts this shell's ``log_widget``, and its toggle reports unchecked
    """
    assert isinstance(log_dock_of(widget).widget(), LogWidget)
    assert widget.log_widget is log_dock_of(widget).widget()
    assert log_dock_of(widget).toggleViewAction().isChecked() is False


def test_the_log_sub_dock_toggle_carries_the_log_view_icon(widget: TaskQueueWidget) -> None:
    """Its toggle wears the same log icon the window's and every resource's do (#276).

    The same icon for all three on purpose: they are the same surface about different subjects
    ([[appendices.logging#surfaces]]).

    **Test steps:**

    * find the ``ActionIconThemeHandler`` instances parented to the toggle action
    * verify one was built from the log icon's SVG bytes
    """
    handlers = log_dock_of(widget).toggleViewAction().findChildren(ActionIconThemeHandler)
    svgs = {handler._ActionIconThemeHandler__svg for handler in handlers}  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert read_resource_bytes(LOG_VIEW_ICON_RESOURCE) in svgs


def test_the_toggle_shows_the_hidden_sub_dock(widget: TaskQueueWidget) -> None:
    """Asking for the log is what puts it on screen (#276).

    **Test steps:**

    * trigger the sub-dock's toggle action
    * verify the dock is no longer closed
    """
    log_dock_of(widget).toggleViewAction().trigger()

    assert log_dock_of(widget).isClosed() is False


def test_nothing_selected_is_the_log_of_nothing(
    widget: TaskQueueWidget, queue: TaskQueue, scoped_logger: logging.Logger, deliver: Callable[[], None]
) -> None:
    """With no row selected the surface stays empty, whatever the jobs have written (#276).

    **Test steps:**

    * settle two jobs and log a record under each one's scope
    * verify the surface holds nothing
    """
    two_finished_jobs(queue, deliver)
    log_a_record_for(queue, scoped_logger, "first")
    log_a_record_for(queue, scoped_logger, "second")
    deliver()

    assert log_messages(widget) == []


def test_selecting_a_row_shows_that_job_s_replayed_records(
    widget: TaskQueueWidget, queue: TaskQueue, scoped_logger: logging.Logger, deliver: Callable[[], None]
) -> None:
    """Selecting a job attaches the surface to its scope and replays what that job wrote (#276).

    The records were made *before* the row was ever selected and both jobs have already finished, which
    is the case that makes replay-on-attach load-bearing here ([[appendices.logging#replay]]).

    **Test steps:**

    * settle two jobs and log a record under each one's scope
    * select the first row
    * verify only that job's record is shown
    """
    two_finished_jobs(queue, deliver)
    log_a_record_for(queue, scoped_logger, "first")
    log_a_record_for(queue, scoped_logger, "second")
    deliver()

    select_rows(widget, 0)

    assert log_messages(widget) == ["about first"]


def test_selecting_another_row_swaps_the_surface(
    widget: TaskQueueWidget, queue: TaskQueue, scoped_logger: logging.Logger, deliver: Callable[[], None]
) -> None:
    """The surface follows the selection rather than accumulating the jobs it has visited (#276).

    Unlike a renamed resource's, these rows do not stay: this is a different job, not the same one under
    a new name.

    **Test steps:**

    * settle two jobs and log a record under each one's scope
    * select the first row, then the second
    * verify only the second job's record is shown
    """
    two_finished_jobs(queue, deliver)
    log_a_record_for(queue, scoped_logger, "first")
    log_a_record_for(queue, scoped_logger, "second")
    deliver()

    select_rows(widget, 0)
    select_rows(widget, 1)

    assert log_messages(widget) == ["about second"]


def test_clearing_the_selection_empties_the_surface(
    widget: TaskQueueWidget, queue: TaskQueue, scoped_logger: logging.Logger, deliver: Callable[[], None]
) -> None:
    """Selecting nothing is the log of nothing -- the current index left behind does not count (#276).

    ``clearSelection`` rather than ``clear``: it leaves the current index exactly where it was, which is
    the case a surface reading only that index would get wrong.

    **Test steps:**

    * settle two jobs, log under the first's scope, and select its row
    * clear the selection, then log under that same scope again
    * verify the surface emptied and stayed empty
    """
    two_finished_jobs(queue, deliver)
    log_a_record_for(queue, scoped_logger, "first")
    deliver()
    select_rows(widget, 0)
    assert log_messages(widget) == ["about first"]

    ui_of(widget).task_view.selectionModel().clearSelection()  # type: ignore[attr-defined]
    log_a_record_for(queue, scoped_logger, "first")
    deliver()

    assert log_messages(widget) == []


def test_the_surface_follows_a_selected_job_live(
    widget: TaskQueueWidget, queue: TaskQueue, scoped_logger: logging.Logger, deliver: Callable[[], None]
) -> None:
    """A record written while a row is selected lands on the surface without re-selecting it (#276).

    **Test steps:**

    * settle two jobs and select the first row
    * log a record under each job's scope
    * verify only the selected job's record arrived
    """
    two_finished_jobs(queue, deliver)
    select_rows(widget, 0)

    log_a_record_for(queue, scoped_logger, "first")
    log_a_record_for(queue, scoped_logger, "second")
    deliver()

    assert log_messages(widget) == ["about first"]


def test_the_surface_is_capped_at_the_per_resource_limit(queue: TaskQueue, qtbot: QtBot) -> None:
    """A job's surface is capped like a resource's, not like the app's (#276).

    Its lifetime shape is a document's -- one subject's records, for as long as that subject is on
    screen -- so it reads
    :attr:`~rehuco_agent.settings.logs_settings.LogsSettings.effective_resource_limit`.

    **Test steps:**

    * set the two configured limits so the per-resource one is the effective cap
    * build a widget
    * verify its surface carries that cap
    """
    settings = shared_logs_settings()
    settings.app_limit = 500
    settings.resource_limit = 17

    built = TaskQueueWidget(queue)
    qtbot.addWidget(built)

    assert built.log_widget.limit == 17


def test_the_surface_is_re_capped_as_either_limit_changes(widget: TaskQueueWidget) -> None:
    """Lowering either configured limit reaches a surface that is already built (#236, #276).

    **Test steps:**

    * lower the per-resource limit, then hold it down with a lower app limit
    * verify the surface followed both
    """
    settings = shared_logs_settings()
    settings.app_limit = 500

    settings.resource_limit = 40
    assert widget.log_widget.limit == 40

    settings.app_limit = 12
    assert widget.log_widget.limit == 12


def test_the_nested_layout_round_trips(queue: TaskQueue, qtbot: QtBot) -> None:
    """A shown Log sub-dock is shown again in a shell restored from the saved blob (#276).

    **Test steps:**

    * show the log sub-dock on one shell and save its state
    * build a second shell and restore that state into it
    * verify the restore reported success and the second shell's log dock is open
    """
    source = TaskQueueWidget(queue)
    qtbot.addWidget(source)
    log_dock_of(source).toggleView(True)
    state = source.save_state()

    restored = TaskQueueWidget(queue)
    qtbot.addWidget(restored)

    assert restored.restore_state(state) is True
    assert log_dock_of(restored).isClosed() is False


def test_an_unusable_blob_keeps_the_built_layout(widget: TaskQueueWidget) -> None:
    """An empty, malformed or foreign-versioned blob is refused, leaving the log hidden as built (#276).

    Restoring one would succeed and then hide whichever sub-docks it had never heard of, which for a
    two-dock shell is a blank Tasks dock.

    **Test steps:**

    * hand the widget an empty blob, a malformed one, one that is not a mapping at all, one carrying a
      foreign version, and two of the right version whose layout bytes are unusable
    * verify each was refused and the log dock is still closed
    """
    foreign = cbor2.dumps({STATE_VERSION_KEY: STATE_VERSION + 1, STATE_DOCK_MANAGER_KEY: b"whatever"})
    # the right version, but nothing to restore from: an absent key, and a value of the wrong type.
    # Handing either to ``restoreState`` is what Qt logs a spurious "Input data is corrupted" for
    missing_layout = cbor2.dumps({STATE_VERSION_KEY: STATE_VERSION})
    wrong_type_layout = cbor2.dumps({STATE_VERSION_KEY: STATE_VERSION, STATE_DOCK_MANAGER_KEY: 42})

    assert widget.restore_state(b"") is False
    assert widget.restore_state(b"not cbor at all") is False
    assert widget.restore_state(cbor2.dumps(["not", "a", "mapping"])) is False
    assert widget.restore_state(foreign) is False
    assert widget.restore_state(missing_layout) is False
    assert widget.restore_state(wrong_type_layout) is False
    assert log_dock_of(widget).isClosed() is True


def test_the_log_surface_s_own_filters_survive_a_restore(queue: TaskQueue, qtbot: QtBot) -> None:
    """What the reader narrowed the log to is part of this shell's state (#276).

    Restored ahead of the version guard, since a blob whose *dock set* no longer matches is still a
    perfectly good answer about one widget's filters.

    **Test steps:**

    * turn the debug band off on one shell and save its state
    * restore that state into a second shell
    * verify the band came back off
    """
    source = TaskQueueWidget(queue)
    qtbot.addWidget(source)
    source_ui = source.log_widget._LogWidget__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access
    source_ui.show_debugs_action.setChecked(False)
    state = source.save_state()

    restored = TaskQueueWidget(queue)
    qtbot.addWidget(restored)
    restored.restore_state(state)

    restored_ui = restored.log_widget._LogWidget__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert restored_ui.show_debugs_action.isChecked() is False


# endregion
