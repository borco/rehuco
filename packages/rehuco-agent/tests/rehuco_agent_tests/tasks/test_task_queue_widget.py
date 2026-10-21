"""Tests for TaskQueueWidget: the anti-optimism discipline and the controls' own logic (#202).

The task queue is a ``Mock(spec=TaskQueue)`` scripted by :class:`Rig` -- the engine has its own tests in
``rehuco-core``, and a scripted one puts a row in exactly the state a test names, with no worker to race. The dock's
model is the real one, told of each change through the listener methods the engine calls, so every wait here is on its
re-snapshot. What the widget asks of the engine is asserted as calls on the mock; what the engine answers is the script.

**No test asserts on a cursor.** Whether a job keeps its work is read only through the one bit a
surface may ask about, :attr:`~rehuco_core.JobStatus.resumes_where_it_stopped`
([[appendices.task-queue#job-responsibility]]).
"""

# The widget's surface is small but its behaviours are many -- an enablement matrix, a context menu,
# ten controls and two bulk ones -- and every one below is a distinct fact about it. One cohesive
# module reads better than an arbitrary split.
# pylint: disable=too-many-lines

import base64
import logging
from collections.abc import Iterator
from dataclasses import replace
from itertools import count
from typing import Any, Final
from unittest.mock import Mock, call

import cbor2
import PySide6QtAds as QtAds
from borco_core.logging import LOG_SCOPE_ATTRIBUTE
from borco_pyside.logging import LogWidget
from borco_pyside.logging.log_model import MESSAGE_COLUMN
from borco_pyside.theming import themed_svg_icon
from PySide6.QtCore import QCoreApplication, QEvent, QItemSelectionModel, QPoint, Qt
from PySide6.QtWidgets import QMessageBox, QToolBar
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.app_logging import LOG_VIEW_ICON_RESOURCE, shared_log_bridge
from rehuco_agent.settings.logs_settings import shared_logs_settings
from rehuco_agent.tasks import task_queue_widget as widget_module
from rehuco_agent.tasks.task_queue_model import STARTS_OVER_HINT
from rehuco_agent.tasks.task_queue_widget import (
    LOG_DOCK_NAME,
    PAUSE_TOOLTIP,
    QUEUE_DOCK_NAME,
    STARTS_OVER_SOME_TOOLTIP,
    TaskQueueWidget,
)
from rehuco_core import JobScope, JobState, JobStatus, StopRequest, TaskQueue

SIGNAL_TIMEOUT_MS: Final = 5000
"""How long a test waits for the model's re-snapshot before calling it a failure -- a deadlock detector, not a
measurement: the wait ends the moment the signal fires."""

FIRST_SERIAL: Final = 1000
"""Where the scripted queue's serials start: far above any a test names itself."""

YES: Final = QMessageBox.StandardButton.Yes
NO: Final = QMessageBox.StandardButton.No

QUESTION: Final = "rehuco_agent.tasks.task_queue_widget.QMessageBox.question"
"""Where the widget's own confirmation dialog is looked up -- patched there rather than on the class,
so a test never reaches into a module's re-export of a Qt name."""

SEPARATOR: Final = "separator"
"""Stands for an ``addSeparator`` call in a recorded menu's entries, so the groups are asserted in order."""


# region fixtures and helpers


class Rig:
    """A scripted :class:`~rehuco_core.TaskQueue`: ``jobs()`` answers the rows a test put in it, in order, and every
    other call is only recorded.

    :param mocker: pytest-mock fixture.
    :param qtbot: pytest-qt fixture.
    """

    def __init__(self, mocker: MockerFixture, qtbot: QtBot) -> None:
        self.__qtbot: Final = qtbot
        self.__serials: Final = count(FIRST_SERIAL)
        self.statuses: Final[dict[int, JobStatus]] = {}
        """Each row, in the queue's order."""
        self.queue: Final = mocker.Mock(spec=TaskQueue)
        self.queue.jobs.side_effect = lambda: tuple(self.statuses.values())

    def add(self, label: str, state: JobState, **fields: Any) -> int:
        """Put a row at the end of the queue; the widget hears of it at the next :meth:`settle`.

        :param label: its label, by which a test names it.
        :param state: its state.
        :param fields: any other :class:`~rehuco_core.JobStatus` field.
        :returns: its serial.
        """
        serial = next(self.__serials)
        self.statuses[serial] = JobStatus(serial, label, state, **fields)  # pylint: disable=unsupported-assignment-operation
        return serial

    def serial(self, label: str) -> int:
        """The serial of the row named ``label``.

        :param label: the row's label.
        :returns: its serial.
        """
        return next(status.serial for status in self.statuses.values() if status.label == label)

    def serials(self, *labels: str) -> list[int]:
        """The serials of the rows named ``labels``, in that order.

        :param labels: the rows' labels.
        :returns: their serials.
        """
        return [self.serial(label) for label in labels]

    def set_state(self, label: str, state: JobState, **fields: Any) -> None:
        """Move a row to ``state``; the widget hears of it at the next :meth:`settle`.

        :param label: the row's label.
        :param state: its new state.
        :param fields: any other field to change with it.
        """
        serial = self.serial(label)
        self.statuses[serial] = replace(self.statuses[serial], state=state, **fields)  # pylint: disable=unsupported-assignment-operation

    def reorder(self, *labels: str) -> None:
        """Put the rows in the order ``labels`` names, as an engine move does; heard at the next :meth:`settle`.

        :param labels: every row's label, in the new order.
        """
        rows = {status.label: status for status in self.statuses.values()}
        self.statuses.clear()
        self.statuses.update((rows[label].serial, rows[label]) for label in labels)

    def settle(self) -> None:
        """Tell the model the widget attached that the queue changed, as the engine does, and wait for its snapshot."""
        (listener,) = self.queue.add_listener.call_args.args
        with self.__qtbot.waitSignal(listener.snapshot_taken, timeout=SIGNAL_TIMEOUT_MS):
            listener.job_updated(JobStatus(0, "", JobState.QUEUED))


@fixture(name="rig")
def fixture_rig(mocker: MockerFixture, qtbot: QtBot) -> Rig:
    """The scripted queue under the widget.

    :param mocker: pytest-mock fixture.
    :param qtbot: pytest-qt fixture.
    :returns: the rig.
    """
    return Rig(mocker, qtbot)


@fixture(name="queue")
def fixture_queue(rig: Rig) -> Mock:
    """The rig's scripted queue, for a test that builds its own widget or asserts the calls made of it.

    :param rig: the rig.
    :returns: the queue.
    """
    return rig.queue


@fixture(name="widget")
def fixture_widget(rig: Rig, qtbot: QtBot) -> TaskQueueWidget:
    """A `TaskQueueWidget` attached to the rig's queue, added to ``qtbot`` for teardown.

    :param rig: the rig.
    :param qtbot: pytest-qt fixture.
    :returns: the widget.
    """
    built = TaskQueueWidget(rig.queue)
    built.attach()
    qtbot.addWidget(built)
    return built


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
    return widget.model.status_at(row)


def widget_row_count(widget: TaskQueueWidget) -> int:
    """How many rows a widget's own model holds.

    :param widget: the widget to read.
    :returns: its row count.
    """
    return widget.model.rowCount()


def widget_labels(widget: TaskQueueWidget) -> list[str]:
    """The labels of a widget's own model's rows, top to bottom.

    :param widget: the widget to read.
    :returns: the labels.
    """
    return [widget_status(widget, row).label for row in range(widget_row_count(widget))]


# endregion


# region the view follows the engine, never its own guess


def test_the_pause_action_does_not_change_its_own_state_until_the_engine_reports_it(
    widget: TaskQueueWidget, rig: Rig
) -> None:
    """The anti-optimism test: the engine asked to pause leaves the row running, and after a re-snapshot the row
    must still read running -- only the engine's own snapshot may say paused.

    **Test steps:**

    * script a running job and select its row
    * trigger the Pause action, and verify the engine was asked to pause that serial
    * re-snapshot with the script unchanged
    * verify the row still reads ``running``, not ``paused``
    """
    serial = rig.add("job", JobState.RUNNING)
    rig.settle()
    select_rows(widget, 0)

    ui_of(widget).pause_action.trigger()  # type: ignore[attr-defined]
    rig.queue.pause_job.assert_called_once_with(serial)
    rig.settle()

    assert widget_status(widget, 0).state is JobState.RUNNING


def test_a_move_the_engine_clamps_leaves_the_row_where_the_engine_put_it(widget: TaskQueueWidget, rig: Rig) -> None:
    """Asking to move a queued job above the running one leaves the view exactly where the engine
    clamped it -- the row order always equals ``queue.jobs()``, never the request.

    **Test steps:**

    * script a running job and a queued one behind it
    * select the queued job and move it to the top, and verify the engine was asked to move it to index 0
    * re-snapshot with the script unchanged, as the engine's clamp leaves it
    * verify the row order still matches the script, running job first
    """
    rig.add("running", JobState.RUNNING)
    queued = rig.add("queued", JobState.QUEUED)
    rig.settle()

    select_rows(widget, 1)
    ui_of(widget).move_to_top_action.trigger()  # type: ignore[attr-defined]
    rig.settle()

    rig.queue.move.assert_called_once_with(queued, 0)
    assert widget_labels(widget) == ["running", "queued"]


# endregion


# region the toolbar


def test_clear_done_ends_the_toolbar_s_queue_controls(widget: TaskQueueWidget) -> None:
    """*Clear Done* acts on the whole queue rather than the selection, so it sits in its own slot after
    the reorder group, not folded into the per-selection run above it (#249) -- and the two view toggles,
    the Log and Pending Saves, which act on this shell rather than on the queue at all, share a separated
    trailing slot after it (#276, #497).

    **Test steps:**

    * read the toolbar's own action list
    * verify Clear Done follows a separator, and the Log and Pending Saves toggles a further one
    """
    # direct children only: the Log sub-dock's own surface carries a toolbar of its own, and a plain
    # recursive search finds whichever of the two Qt built first
    toolbar = widget.findChildren(QToolBar, options=Qt.FindChildOption.FindDirectChildrenOnly)[0]
    actions = toolbar.actions()

    assert actions[-1] is ui_of(widget).pending_saves_action  # type: ignore[attr-defined]
    assert actions[-2] is log_dock_of(widget).toggleViewAction()
    assert actions[-3].isSeparator()
    assert actions[-4] is ui_of(widget).clear_done_action  # type: ignore[attr-defined]
    assert actions[-5].isSeparator()


# endregion


# region the context menu


def test_the_context_menu_offers_the_per_selection_actions_then_the_sweeps(
    widget: TaskQueueWidget, mocker: MockerFixture
) -> None:
    """The menu is the four per-selection actions plus Clear, then the two save actions, then the three
    sweeps, then the Pending Saves toggle -- each group behind a separator (#497).

    The separator before the sweeps is the point: a sweep acts on the *queue*, not on what is selected, and
    running one by reflex after aiming at a row is exactly what the split guards against.

    **Test steps:**

    * patch ``QMenu`` so nothing is actually shown
    * ask for the context menu
    * verify the entries and the separators, in order
    """
    menu = mocker.patch.object(widget_module, "QMenu").return_value
    ui = ui_of(widget)

    widget._TaskQueueWidget__show_context_menu(QPoint(0, 0))  # type: ignore[attr-defined]  # pylint: disable=protected-access

    entries = [
        made.args[0] if made[0] == "addAction" else SEPARATOR
        for made in menu.method_calls
        if made[0] in ("addAction", "addSeparator")
    ]
    assert entries == [
        ui.pause_action,  # type: ignore[attr-defined]
        ui.resume_action,  # type: ignore[attr-defined]
        ui.cancel_action,  # type: ignore[attr-defined]
        ui.retry_action,  # type: ignore[attr-defined]
        ui.clear_action,  # type: ignore[attr-defined]
        SEPARATOR,
        ui.inspect_save_action,  # type: ignore[attr-defined]
        ui.discard_save_action,  # type: ignore[attr-defined]
        SEPARATOR,
        ui.clear_done_action,  # type: ignore[attr-defined]
        ui.clear_failed_action,  # type: ignore[attr-defined]
        ui.clear_all_action,  # type: ignore[attr-defined]
        SEPARATOR,
        ui.pending_saves_action,  # type: ignore[attr-defined]
    ]
    menu.exec.assert_called_once()


def test_the_clear_entry_counts_what_it_would_remove(widget: TaskQueueWidget, rig: Rig, mocker: MockerFixture) -> None:
    """*Clear job* becomes *Clear 2 jobs* over a multi-selection, so the entry says what it will do.

    **Test steps:**

    * script two finished jobs and select both
    * open the context menu, and verify the Clear entry names the count
    * select one and verify it goes back to the singular
    """
    mocker.patch.object(widget_module, "QMenu")
    for index in range(2):
        rig.add(f"job-{index}", JobState.DONE)
    rig.settle()
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
    widget: TaskQueueWidget, rig: Rig, state: JobState, expected: set[str]
) -> None:
    """Every control is offered for exactly the states the engine would let it act on.

    A **running** job never moves -- it cannot be made to have started later than it did -- and a
    finished one has no position left to matter. Retry covers only ``failed`` and ``cancelled``:
    re-running work that succeeded is not what it is for ([[appendices.task-queue#kept]]).

    **Test steps:**

    * script one job in ``state`` and select it
    * verify exactly the expected controls are enabled
    """
    rig.add("job", state)
    rig.settle()
    select_rows(widget, 0)
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


def test_resume_is_offered_for_a_running_job_with_a_stop_pending(widget: TaskQueueWidget, rig: Rig) -> None:
    """Cancel-then-Resume is a recoverable mis-click while the job has not looked at the request yet.

    The row is scripted ``running`` with a cancel pending -- exactly the window the retraction exists for.

    **Test steps:**

    * script a running job with a cancel requested, and select it
    * verify Resume is offered while it still reads as running
    """
    rig.add("job", JobState.RUNNING, stop_requested=StopRequest.CANCEL)
    rig.settle()
    select_rows(widget, 0)

    assert widget_status(widget, 0).state is JobState.RUNNING
    assert ui_of(widget).resume_action.isEnabled()  # type: ignore[attr-defined]


def test_a_mixed_selection_moves_nothing(widget: TaskQueueWidget, rig: Rig) -> None:
    """Reordering is offered only when *every* selected row can move -- a partial move would silently
    leave some of the selection where it was.

    **Test steps:**

    * script one running job beside one queued one, and select both
    * verify the move controls are off, while Clear (which acts on both) is on
    """
    rig.add("running", JobState.RUNNING)
    rig.add("queued", JobState.QUEUED)
    rig.settle()

    select_rows(widget, 0, 1)
    ui = ui_of(widget)

    assert not ui.move_to_top_action.isEnabled()  # type: ignore[attr-defined]
    assert ui.clear_action.isEnabled()  # type: ignore[attr-defined]


def test_a_retry_is_refused_over_a_selection_holding_anything_unfinished(widget: TaskQueueWidget, rig: Rig) -> None:
    """Retry is finished-only, so one unfinished row in the selection withdraws it.

    **Test steps:**

    * script a failed job, a running one and a queued one, and select the failed and the queued
    * verify Retry is not offered
    """
    rig.add("failed", JobState.FAILED, message="ValueError: nope")
    rig.add("blocker", JobState.RUNNING)
    rig.add("queued", JobState.QUEUED)
    rig.settle()

    select_rows(widget, 0, 2)

    assert not ui_of(widget).retry_action.isEnabled()  # type: ignore[attr-defined]


# endregion


# region what Pause says it will cost


def test_pause_says_nothing_extra_for_a_job_that_keeps_its_work(widget: TaskQueueWidget, rig: Rig) -> None:
    """A job with a cursor loses nothing, so Pause carries only its plain tooltip.

    **Test steps:**

    * script a running job that resumes where it stopped, and select it
    * verify Pause's tooltip carries no cost line
    """
    rig.add("keeps", JobState.RUNNING, resumes_where_it_stopped=True)
    rig.settle()
    select_rows(widget, 0)

    assert ui_of(widget).pause_action.toolTip() == PAUSE_TOOLTIP  # type: ignore[attr-defined]


def test_pause_says_a_single_job_would_start_over(widget: TaskQueueWidget, rig: Rig) -> None:
    """A row that starts over says so **on Pause**, not only on its own tooltip -- and Pause stays
    enabled, because starting over is wasteful rather than wrong.

    **Test steps:**

    * script a running job that keeps nothing, and select it
    * verify Pause's tooltip names the cost, and the action is still enabled
    """
    rig.add("starts over", JobState.RUNNING)
    rig.settle()
    select_rows(widget, 0)
    ui = ui_of(widget)

    assert STARTS_OVER_HINT in ui.pause_action.toolTip()  # type: ignore[attr-defined]
    assert ui.pause_action.isEnabled()  # type: ignore[attr-defined]


def test_pause_says_some_of_a_batch_would_start_over(widget: TaskQueueWidget, rig: Rig) -> None:
    """Over a mixed multi-selection the warning is phrased for a batch rather than for one row.

    **Test steps:**

    * script a running job that keeps its work with a queued one behind it that does not, and select both
    * verify Pause's tooltip uses the batch wording
    """
    rig.add("keeps", JobState.RUNNING, resumes_where_it_stopped=True)
    rig.add("starts over", JobState.QUEUED)
    rig.settle()
    select_rows(widget, 0, 1)

    assert STARTS_OVER_SOME_TOOLTIP in ui_of(widget).pause_action.toolTip()  # type: ignore[attr-defined]


def test_a_batch_that_all_keeps_its_work_is_not_warned_about(widget: TaskQueueWidget, rig: Rig) -> None:
    """A multi-selection where nothing starts over gets no warning either.

    **Test steps:**

    * script two jobs that both keep their work, one running and one queued, and select both
    * verify Pause's tooltip carries no cost line
    """
    rig.add("keeps", JobState.RUNNING, resumes_where_it_stopped=True)
    rig.add("also keeps", JobState.QUEUED, resumes_where_it_stopped=True)
    rig.settle()
    select_rows(widget, 0, 1)

    assert ui_of(widget).pause_action.toolTip() == PAUSE_TOOLTIP  # type: ignore[attr-defined]


def test_a_finished_row_costs_nothing_to_pause(widget: TaskQueueWidget, rig: Rig) -> None:
    """Pause would not touch a finished job, so it is not counted when naming the cost.

    **Test steps:**

    * script a finished job that keeps nothing, and select it
    * verify Pause's tooltip carries no cost line
    """
    rig.add("job", JobState.DONE)
    rig.settle()
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
    widget: TaskQueueWidget, rig: Rig
) -> None:
    """The bulk pair mirrors what its own calls would touch, not the derived ``queue.paused``.

    ``paused`` means *every* unfinished job is held, so it is ``False`` here -- and gating Resume All
    on it would refuse a resume the engine would happily perform.

    **Test steps:**

    * script one running job beside one paused, with the queue answering ``paused`` as ``False``
    * verify both bulk controls are offered
    """
    rig.queue.paused = False
    rig.add("running", JobState.RUNNING)
    rig.add("paused", JobState.PAUSED)
    rig.settle()
    ui = ui_of(widget)

    assert ui.resume_all_action.isEnabled()  # type: ignore[attr-defined]
    assert ui.pause_all_action.isEnabled()  # type: ignore[attr-defined]


def test_pause_all_goes_off_once_everything_is_held(widget: TaskQueueWidget, rig: Rig) -> None:
    """With nothing left to ask, Pause All is not offered -- and Resume All is.

    **Test steps:**

    * script the queue's one job paused
    * verify Pause All is off and Resume All is on
    """
    rig.add("job", JobState.PAUSED)
    rig.settle()
    ui = ui_of(widget)

    assert not ui.pause_all_action.isEnabled()  # type: ignore[attr-defined]
    assert ui.resume_all_action.isEnabled()  # type: ignore[attr-defined]


def test_the_bulk_pair_is_off_once_every_job_has_finished(widget: TaskQueueWidget, rig: Rig) -> None:
    """Finished rows are kept, but neither bulk control has anything to do with them.

    **Test steps:**

    * script one finished job
    * verify both bulk actions are disabled while the row remains
    """
    rig.add("job", JobState.DONE)
    rig.settle()
    ui = ui_of(widget)

    assert widget_row_count(widget) == 1
    assert not ui.pause_all_action.isEnabled()  # type: ignore[attr-defined]
    assert not ui.resume_all_action.isEnabled()  # type: ignore[attr-defined]


def test_the_bulk_controls_hold_and_release_every_unfinished_job(widget: TaskQueueWidget, rig: Rig) -> None:
    """Pause All asks the engine to hold *everything* unfinished, and Resume All to put it all back -- each one call to
    the engine's own bulk method, never one per row.

    **Test steps:**

    * script one running job with another queued behind it
    * trigger Pause All, and verify the engine's ``pause`` was called once and ``resume`` not at all
    * script both jobs paused and re-snapshot, and verify Pause All is off and Resume All on
    * trigger Resume All, and verify the engine's ``resume`` was called once
    """
    rig.add("running", JobState.RUNNING)
    rig.add("queued", JobState.QUEUED)
    rig.settle()
    ui = ui_of(widget)

    ui.pause_all_action.trigger()  # type: ignore[attr-defined]
    rig.queue.pause.assert_called_once_with()
    rig.queue.resume.assert_not_called()

    rig.set_state("running", JobState.PAUSED)
    rig.set_state("queued", JobState.PAUSED)
    rig.settle()
    assert not ui.pause_all_action.isEnabled()  # type: ignore[attr-defined]
    assert ui.resume_all_action.isEnabled()  # type: ignore[attr-defined]

    ui.resume_all_action.trigger()  # type: ignore[attr-defined]
    rig.queue.resume.assert_called_once_with()


# endregion


# region the per-selection actions


def test_pause_and_resume_act_on_every_selected_row(widget: TaskQueueWidget, rig: Rig) -> None:
    """Both controls act on the whole selection, one engine call per row.

    **Test steps:**

    * script one paused job beside one still running, and select both so each control is enabled
    * trigger Pause, then Resume
    * verify each engine call was made once per selected serial
    """
    serials = [rig.add("running", JobState.RUNNING), rig.add("paused", JobState.PAUSED)]
    rig.settle()
    ui = ui_of(widget)

    select_rows(widget, 0, 1)
    ui.pause_action.trigger()  # type: ignore[attr-defined]
    ui.resume_action.trigger()  # type: ignore[attr-defined]

    assert rig.queue.pause_job.call_args_list == [call(serial) for serial in serials]
    assert rig.queue.resume_job.call_args_list == [call(serial) for serial in serials]


def test_cancel_prompts_once_for_a_whole_batch(widget: TaskQueueWidget, rig: Rig, mocker: MockerFixture) -> None:
    """Cancel asks **once** however many rows are selected -- never once per row.

    **Test steps:**

    * script three unfinished jobs and select all of them
    * answer Yes to the prompt
    * verify exactly one dialog was raised, and the engine was asked to cancel every job
    """
    serials = [
        rig.add("running", JobState.RUNNING),
        rig.add("queued-0", JobState.QUEUED),
        rig.add("queued-1", JobState.QUEUED),
    ]
    rig.settle()
    question = mocker.patch(QUESTION, return_value=YES)

    select_rows(widget, 0, 1, 2)
    ui_of(widget).cancel_action.trigger()  # type: ignore[attr-defined]

    question.assert_called_once()
    assert rig.queue.cancel.call_args_list == [call(serial) for serial in serials]


def test_a_refused_cancel_cancels_nothing(widget: TaskQueueWidget, rig: Rig, mocker: MockerFixture) -> None:
    """Answering No leaves every selected job exactly as it was.

    **Test steps:**

    * script a running job, select it, and answer No to the prompt
    * verify the engine was never asked to cancel
    """
    rig.add("job", JobState.RUNNING)
    rig.settle()
    question = mocker.patch(QUESTION, return_value=NO)

    select_rows(widget, 0)
    ui_of(widget).cancel_action.trigger()  # type: ignore[attr-defined]

    question.assert_called_once()
    rig.queue.cancel.assert_not_called()


def test_cancel_over_an_empty_selection_never_prompts(widget: TaskQueueWidget, mocker: MockerFixture) -> None:
    """With nothing selected there is nothing to confirm, so no dialog is raised at all.

    **Test steps:**

    * call the Cancel handler with an empty selection
    * verify no prompt appeared
    """
    question = mocker.patch(QUESTION)

    widget._TaskQueueWidget__cancel_selection()  # type: ignore[attr-defined]  # pylint: disable=protected-access

    question.assert_not_called()


def test_retry_asks_the_engine_to_run_a_failed_job_again(widget: TaskQueueWidget, rig: Rig) -> None:
    """Retry hands the failed job back to the engine, which is where *from the top* is decided.

    **Test steps:**

    * script a failed job, select it, and trigger Retry
    * verify the engine was asked to retry exactly that serial
    """
    serial = rig.add("job", JobState.FAILED, message="ValueError: nope")
    rig.settle()

    select_rows(widget, 0)
    ui_of(widget).retry_action.trigger()  # type: ignore[attr-defined]

    rig.queue.retry.assert_called_once_with(serial)


def test_clear_removes_exactly_the_selected_rows(widget: TaskQueueWidget, rig: Rig) -> None:
    """Clear is the only way a job leaves the queue, and it takes only what was aimed at.

    **Test steps:**

    * script two finished jobs, select the first, and trigger Clear
    * verify the engine was asked to remove only the first
    """
    for index in range(2):
        rig.add(f"job-{index}", JobState.DONE)
    rig.settle()

    select_rows(widget, 0)
    ui_of(widget).clear_action.trigger()  # type: ignore[attr-defined]

    rig.queue.remove.assert_called_once_with(rig.serial("job-0"))


def test_clear_over_an_empty_selection_removes_nothing(widget: TaskQueueWidget, queue: Mock) -> None:
    """Nothing selected is nothing to clear.

    **Test steps:**

    * call the Clear handler with an empty selection
    * verify the engine was never asked to remove anything
    """
    widget._TaskQueueWidget__clear_selection()  # type: ignore[attr-defined]  # pylint: disable=protected-access

    queue.remove.assert_not_called()


def test_the_sweeps_drop_only_their_own_kind(widget: TaskQueueWidget, rig: Rig) -> None:
    """*Clear done* and *Clear failed* each take exactly one kind, leaving the rest -- deciding which
    jobs a sweep drops is the view's business, which is why #237 deleted the engine's own sweep.

    **Test steps:**

    * script one done job, one failed job and one running job
    * trigger Clear done, then Clear failed
    * verify each asked the engine to remove only its own kind, and the unfinished job was in neither
    """
    rig.add("done", JobState.DONE)
    rig.add("failed", JobState.FAILED, message="ValueError: nope")
    rig.add("running", JobState.RUNNING)
    rig.settle()
    ui = ui_of(widget)

    ui.clear_done_action.trigger()  # type: ignore[attr-defined]
    ui.clear_failed_action.trigger()  # type: ignore[attr-defined]

    assert rig.queue.remove.call_args_list == [call(rig.serial("done")), call(rig.serial("failed"))]


def test_a_sweep_with_nothing_of_its_kind_removes_nothing(widget: TaskQueueWidget, rig: Rig) -> None:
    """A sweep over a queue holding none of its kind is a no-op, not an empty removal.

    **Test steps:**

    * script one running job and trigger Clear done
    * verify the engine was never asked to remove anything
    """
    rig.add("running", JobState.RUNNING)
    rig.settle()

    ui_of(widget).clear_done_action.trigger()  # type: ignore[attr-defined]

    rig.queue.remove.assert_not_called()


def test_clear_all_cancels_what_is_unfinished_and_empties_the_queue(widget: TaskQueueWidget, rig: Rig) -> None:
    """*Clear all* is a clean slate: it stops whatever is unfinished first, then removes everything.

    **Test steps:**

    * script one done job beside one running one
    * trigger Clear all
    * verify the engine was asked to cancel only the running job, then to remove both
    """
    rig.add("done", JobState.DONE)
    rig.add("running", JobState.RUNNING)
    rig.settle()
    calls = Mock()
    calls.attach_mock(rig.queue.cancel, "cancel")
    calls.attach_mock(rig.queue.remove, "remove")

    ui_of(widget).clear_all_action.trigger()  # type: ignore[attr-defined]

    assert calls.mock_calls == [call.cancel(rig.serial("running")), call.remove(*rig.serials("done", "running"))]


def test_clear_all_over_an_empty_queue_removes_nothing(widget: TaskQueueWidget, queue: Mock) -> None:
    """An empty queue is already a clean slate.

    **Test steps:**

    * trigger Clear all over an empty queue
    * verify the engine was never asked to remove anything
    """
    ui_of(widget).clear_all_action.trigger()  # type: ignore[attr-defined]

    queue.remove.assert_not_called()


def test_retry_never_prompts(widget: TaskQueueWidget, rig: Rig, mocker: MockerFixture) -> None:
    """Retry acts immediately, with no confirmation dialog -- unlike Cancel.

    **Test steps:**

    * script a failed job, select it, and trigger Retry
    * verify the engine was asked to retry it, and no dialog was ever asked for
    """
    question = mocker.patch(QUESTION)
    serial = rig.add("job", JobState.FAILED, message="ValueError: nope")
    rig.settle()

    select_rows(widget, 0)
    ui_of(widget).retry_action.trigger()  # type: ignore[attr-defined]

    rig.queue.retry.assert_called_once_with(serial)
    question.assert_not_called()


def test_pause_and_resume_never_prompt(widget: TaskQueueWidget, rig: Rig, mocker: MockerFixture) -> None:
    """Pausing informs rather than blocks, so neither control raises a dialog -- even over a job that
    will lose the work it has done.

    **Test steps:**

    * script a running job that keeps nothing, select it, and trigger Pause
    * script it paused, re-snapshot, select it again, and trigger Resume
    * verify the engine was asked to pause and to resume it, and no dialog was ever asked for
    """
    question = mocker.patch(QUESTION)
    serial = rig.add("starts over", JobState.RUNNING)
    rig.settle()
    ui = ui_of(widget)

    select_rows(widget, 0)
    ui.pause_action.trigger()  # type: ignore[attr-defined]
    rig.set_state("starts over", JobState.PAUSED)
    rig.settle()
    select_rows(widget, 0)
    ui.resume_action.trigger()  # type: ignore[attr-defined]

    rig.queue.pause_job.assert_called_once_with(serial)
    rig.queue.resume_job.assert_called_once_with(serial)
    question.assert_not_called()


# endregion


# region reordering


def test_up_and_down_move_a_row_one_place(widget: TaskQueueWidget, rig: Rig) -> None:
    """Down then Up asks for a row one place on and one place back, each read off the engine's order at the time.

    **Test steps:**

    * script three queued jobs behind a running blocker, and select the first of them
    * trigger Down, and verify the engine was asked to move it to index 2
    * script that move and re-snapshot, select the row where it went, and trigger Up
    * verify the engine was asked to move it back to index 1
    """
    rig.add("blocker", JobState.RUNNING)
    for index in range(3):
        rig.add(f"job-{index}", JobState.QUEUED)
    rig.settle()
    ui = ui_of(widget)
    moved = rig.serial("job-0")

    select_rows(widget, 1)
    ui.move_down_action.trigger()  # type: ignore[attr-defined]
    assert rig.queue.move.call_args_list == [call(moved, 2)]

    rig.reorder("blocker", "job-1", "job-0", "job-2")
    rig.settle()
    select_rows(widget, 2)
    ui.move_up_action.trigger()  # type: ignore[attr-defined]
    assert rig.queue.move.call_args_list == [call(moved, 2), call(moved, 1)]


def test_top_and_bottom_keep_a_multi_selection_in_its_own_order(widget: TaskQueueWidget, rig: Rig) -> None:
    """Moving several rows to an end asks for them in the order that lands them there in their own order: each move
    goes ahead of whatever is at its target, so Top asks back to front and Bottom front to back.

    **Test steps:**

    * script four queued jobs behind a running blocker and select the last two
    * trigger Top, and verify the engine was asked to move the last, then the one before it, to index 0
    * script them leading, re-snapshot and select them again
    * trigger Bottom, and verify the engine was asked to move the first, then the second, past the last row
    """
    rig.add("blocker", JobState.RUNNING)
    for index in range(4):
        rig.add(f"job-{index}", JobState.QUEUED)
    rig.settle()
    ui = ui_of(widget)
    second, third = rig.serials("job-2", "job-3")

    select_rows(widget, 3, 4)
    ui.move_to_top_action.trigger()  # type: ignore[attr-defined]
    assert rig.queue.move.call_args_list == [call(third, 0), call(second, 0)]
    rig.queue.move.reset_mock()

    rig.reorder("blocker", "job-2", "job-3", "job-0", "job-1")
    rig.settle()
    select_rows(widget, 1, 2)
    ui.move_to_bottom_action.trigger()  # type: ignore[attr-defined]
    assert rig.queue.move.call_args_list == [call(second, 5), call(third, 5)]


def test_moving_up_from_the_top_of_the_movable_run_stays_put(widget: TaskQueueWidget, rig: Rig) -> None:
    """The engine clamps a move that reaches past the movable run, and the view follows it.

    **Test steps:**

    * script two queued jobs behind a running blocker, select the first of them, and trigger Up
    * verify the engine was asked to move it to index 0
    * re-snapshot with the script unchanged, as the engine's clamp leaves it, and verify the order is unchanged
    """
    rig.add("blocker", JobState.RUNNING)
    for index in range(2):
        rig.add(f"job-{index}", JobState.QUEUED)
    rig.settle()

    select_rows(widget, 1)
    ui_of(widget).move_up_action.trigger()  # type: ignore[attr-defined]
    rig.settle()

    rig.queue.move.assert_called_once_with(rig.serial("job-0"), 0)
    assert widget_labels(widget) == ["blocker", "job-0", "job-1"]


# endregion


# region the Log sub-dock


@fixture(name="scoped_logger")
def fixture_scoped_logger() -> Iterator[logging.Logger]:
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


def two_finished_jobs(rig: Rig) -> None:
    """Script two ``done`` jobs -- ``first`` on row 0, ``second`` on row 1 -- and let the widget hear of them.

    Finished rather than running, because what these tests are about is the surface following a
    *selection*: a settled queue is what keeps the rows still while it does.

    :param rig: the rig.
    """
    for label in ("first", "second"):
        rig.add(label, JobState.DONE)
    rig.settle()


def log_a_record_for(rig: Rig, logger: logging.Logger, label: str) -> None:
    """Write one record under the scope of the scripted job named ``label``.

    Logged with the scope named at the call site rather than from inside a job: what a job's own
    ``run`` is wrapped in is the engine's contract (#271), and what this module is about is the surface
    that reads it.

    :param rig: the rig holding the job.
    :param logger: the logger feeding the shared bridge.
    :param label: the job whose scope to write under; also the record's message.
    """
    logger.info(f"about {label}", extra={LOG_SCOPE_ATTRIBUTE: JobScope(rig.serial(label))})


def deliver_records() -> None:
    """Hand the shared bridge's pending records to its sinks now.

    The bridge wakes its sinks through a queued call it posts as a record is logged; this sends the queued calls
    already posted, so a record has reached every surface attached by the time it returns -- or none, which is what
    a test that expects nothing needs, and no signal could say.
    """
    QCoreApplication.sendPostedEvents(None, QEvent.Type.MetaCall.value)


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

    * compare the toggle action's icon against the shared themed icon for the log SVG
    * verify they are the very same icon
    """
    action = log_dock_of(widget).toggleViewAction()
    assert action.icon().cacheKey() == themed_svg_icon(LOG_VIEW_ICON_RESOURCE).cacheKey()


def test_the_toggle_shows_the_hidden_sub_dock(widget: TaskQueueWidget) -> None:
    """Asking for the log is what puts it on screen (#276).

    **Test steps:**

    * trigger the sub-dock's toggle action
    * verify the dock is no longer closed
    """
    log_dock_of(widget).toggleViewAction().trigger()

    assert log_dock_of(widget).isClosed() is False


def test_nothing_selected_is_the_log_of_nothing(
    widget: TaskQueueWidget, rig: Rig, scoped_logger: logging.Logger
) -> None:
    """With no row selected the surface stays empty, whatever the jobs have written (#276).

    **Test steps:**

    * script two finished jobs and log a record under each one's scope
    * deliver the records
    * verify the surface holds nothing
    """
    two_finished_jobs(rig)
    log_a_record_for(rig, scoped_logger, "first")
    log_a_record_for(rig, scoped_logger, "second")
    deliver_records()

    assert log_messages(widget) == []


def test_selecting_a_row_shows_that_job_s_replayed_records(
    widget: TaskQueueWidget, rig: Rig, scoped_logger: logging.Logger
) -> None:
    """Selecting a job attaches the surface to its scope and replays what that job wrote (#276).

    The records were made *before* the row was ever selected and both jobs have already finished, which
    is the case that makes replay-on-attach load-bearing here ([[appendices.logging#replay]]).

    **Test steps:**

    * script two finished jobs, log a record under each one's scope, and deliver them
    * select the first row
    * verify only that job's record is shown
    """
    two_finished_jobs(rig)
    log_a_record_for(rig, scoped_logger, "first")
    log_a_record_for(rig, scoped_logger, "second")
    deliver_records()

    select_rows(widget, 0)

    assert log_messages(widget) == ["about first"]


def test_selecting_another_row_swaps_the_surface(
    widget: TaskQueueWidget, rig: Rig, scoped_logger: logging.Logger
) -> None:
    """The surface follows the selection rather than accumulating the jobs it has visited (#276).

    Unlike a renamed resource's, these rows do not stay: this is a different job, not the same one under
    a new name.

    **Test steps:**

    * script two finished jobs, log a record under each one's scope, and deliver them
    * select the first row, then the second
    * verify only the second job's record is shown
    """
    two_finished_jobs(rig)
    log_a_record_for(rig, scoped_logger, "first")
    log_a_record_for(rig, scoped_logger, "second")
    deliver_records()

    select_rows(widget, 0)
    select_rows(widget, 1)

    assert log_messages(widget) == ["about second"]


def test_clearing_the_selection_empties_the_surface(
    widget: TaskQueueWidget, rig: Rig, scoped_logger: logging.Logger
) -> None:
    """Selecting nothing is the log of nothing -- the current index left behind does not count (#276).

    ``clearSelection`` rather than ``clear``: it leaves the current index exactly where it was, which is
    the case a surface reading only that index would get wrong.

    **Test steps:**

    * script two finished jobs, log under the first's scope, deliver it, and select its row
    * clear the selection, then log under that same scope again and deliver it
    * verify the surface emptied and stayed empty
    """
    two_finished_jobs(rig)
    log_a_record_for(rig, scoped_logger, "first")
    deliver_records()
    select_rows(widget, 0)
    assert log_messages(widget) == ["about first"]

    ui_of(widget).task_view.selectionModel().clearSelection()  # type: ignore[attr-defined]
    log_a_record_for(rig, scoped_logger, "first")
    deliver_records()

    assert log_messages(widget) == []


def test_the_surface_follows_a_selected_job_live(
    widget: TaskQueueWidget, rig: Rig, scoped_logger: logging.Logger
) -> None:
    """A record written while a row is selected lands on the surface without re-selecting it (#276).

    **Test steps:**

    * script two finished jobs and select the first row
    * log a record under each job's scope, and deliver them
    * verify only the selected job's record arrived
    """
    two_finished_jobs(rig)
    select_rows(widget, 0)

    log_a_record_for(rig, scoped_logger, "first")
    log_a_record_for(rig, scoped_logger, "second")
    deliver_records()

    assert log_messages(widget) == ["about first"]


def test_the_surface_is_capped_at_the_per_resource_limit(queue: Mock, qtbot: QtBot) -> None:
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


def layout_dock_entries(layout: object) -> list[dict[str, Any]]:
    """Every dock entry of a stored layout tree (`~borco_pyside.qtads.QtAdsLayout`, #102), in place.

    :param layout: the decoded tree, or any node of it.
    :returns: the entries themselves, wherever they sit in the tree.
    """
    if isinstance(layout, list):
        return [entry for item in layout for entry in layout_dock_entries(item)]
    if not isinstance(layout, dict):
        return []
    if "name" in layout:
        return [layout]
    return [entry for value in layout.values() for entry in layout_dock_entries(value)]


def saved_dock_entries(state: bytes) -> dict[str, dict[str, Any]]:
    """The dock entries of a shell's saved state, by dock name.

    :param state: what ``save_state`` returned.
    :returns: each dock's entry.
    """
    return {entry["name"]: entry for entry in layout_dock_entries(cbor2.loads(state))}


def test_the_nested_layout_round_trips(queue: Mock, qtbot: QtBot) -> None:
    """A shown Log sub-dock is shown again in a shell restored from the saved state, and the log
    surface's filters ride the log dock's own entry (#276, #102).

    **Test steps:**

    * show the log sub-dock and turn the debug band off on one shell, and save its state
    * verify the log dock's entry carries the surface's state and the table's carries none
    * build a second shell and restore that state into it
    * verify the restore reported success, the second shell's log dock is open, and the band came back off
    """
    source = TaskQueueWidget(queue)
    qtbot.addWidget(source)
    log_dock_of(source).toggleView(True)
    source_ui = source.log_widget._LogWidget__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access
    source_ui.show_debugs_action.setChecked(False)
    state = source.save_state()

    entries = saved_dock_entries(state)
    log_entry = entries[LOG_DOCK_NAME]
    assert base64.b64decode(log_entry["state"]) == source.log_widget.save_state()
    assert "state" not in entries[QUEUE_DOCK_NAME]

    restored = TaskQueueWidget(queue)
    qtbot.addWidget(restored)

    assert restored.restore_state(state) is True
    assert log_dock_of(restored).isClosed() is False
    restored_ui = restored.log_widget._LogWidget__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert restored_ui.show_debugs_action.isChecked() is False


def test_an_unusable_blob_keeps_the_built_layout(widget: TaskQueueWidget) -> None:
    """An empty, malformed or non-layout blob is refused, leaving the log hidden as built (#276, #102).

    **Test steps:**

    * hand the widget an empty blob, a malformed one, one that is not a mapping at all, one of another
      format, and the envelope a shell saved before #102
    * verify each was refused and the log dock is still closed
    """
    other_format = cbor2.dumps({"format": 0, "main": {"area": [{"name": LOG_DOCK_NAME, "closed": False}]}})
    old_envelope = cbor2.dumps({"version": 1, "dock_manager": b"an opaque QtAds blob", "log_widget": b""})

    assert widget.restore_state(b"") is False
    assert widget.restore_state(b"not cbor at all") is False
    assert widget.restore_state(cbor2.dumps(["not", "a", "mapping"])) is False
    assert widget.restore_state(other_format) is False
    assert widget.restore_state(old_envelope) is False
    assert log_dock_of(widget).isClosed() is True


def test_the_log_filters_restore_only_with_the_layout(widget: TaskQueueWidget) -> None:
    """The log surface's filters ride the layout (#102): a state the layout cannot restore leaves them as
    they are.

    **Test steps:**

    * turn the debug band off and save the state, then turn it back on
    * restore that state with its format number changed
    * verify it was refused and the band is still on
    """
    ui = widget.log_widget._LogWidget__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access
    ui.show_debugs_action.setChecked(False)
    values = cbor2.loads(widget.save_state())
    ui.show_debugs_action.setChecked(True)
    values["format"] = 0

    assert widget.restore_state(cbor2.dumps(values)) is False
    assert ui.show_debugs_action.isChecked() is True


def test_a_layout_that_never_names_the_log_puts_it_back_hidden_at_the_right(
    widget: TaskQueueWidget, qtbot: QtBot
) -> None:
    """A saved layout that does not name the log dock restores, and the log goes back where it is built:
    hidden, beside the table on its right (#102).

    **Test steps:**

    * save the shell's state with the log's entry renamed away, then open the log
    * restore that state
    * verify it restored and the log is closed
    * show the shell and toggle the log on; verify it sits in its own area, to the right of the table
    """
    values = cbor2.loads(widget.save_state())
    for entry in layout_dock_entries(values):
        if entry["name"] == LOG_DOCK_NAME:
            entry["name"] = "no such dock"
    state = cbor2.dumps(values)
    log_dock_of(widget).toggleView(True)

    assert widget.restore_state(state) is True
    assert log_dock_of(widget).isClosed() is True

    widget.resize(800, 600)
    widget.show()
    log_dock_of(widget).toggleView(True)
    manager = widget._TaskQueueWidget__dock_manager  # type: ignore[attr-defined]  # pylint: disable=protected-access
    queue_dock = manager.findDockWidget(QUEUE_DOCK_NAME)
    log_area = log_dock_of(widget).dockAreaWidget()
    queue_area = queue_dock.dockAreaWidget()
    assert log_area is not None and queue_area is not None
    assert log_area is not queue_area
    qtbot.waitUntil(lambda: log_area.geometry().left() >= queue_area.geometry().right(), timeout=10_000)


# endregion


# region maximizing a sub-dock over the shell (#341)


def test_a_sub_dock_maximizes_and_a_capture_reads_it_undone(widget: TaskQueueWidget, qtbot: QtBot) -> None:
    """Each sub-dock's tab carries the maximize toggle, and ``save_state`` reads the layout with it
    undone (#341).

    **Test steps:**

    * show the shell with its Log sub-dock revealed, capture the layout
    * maximize the Log sub-dock through its tab's button
    * verify only that area is open, ``save_state`` still equals the un-maximized capture, and the
      maximize stands afterwards
    """
    widget.resize(800, 600)
    widget.show()
    log_dock_of(widget).toggleView(True)
    manager = widget._TaskQueueWidget__dock_manager  # type: ignore[attr-defined]  # pylint: disable=protected-access
    handler = widget._TaskQueueWidget__maximize_handler  # type: ignore[attr-defined]  # pylint: disable=protected-access
    log_area = log_dock_of(widget).dockAreaWidget()
    assert log_area is not None
    # the baseline must be a settled layout: the reveal's splitter re-division lands on a posted
    # layout request, and a capture before it would differ from every later one
    qtbot.waitUntil(lambda: all(size > 0 for size in manager.splitterSizes(log_area)), timeout=10_000)
    unmaximized = widget.save_state()
    qtbot.waitUntil(lambda: handler.button(log_dock_of(widget)) is not None, timeout=10_000)
    button = handler.button(log_dock_of(widget))
    assert button is not None

    button.click()

    assert manager.openedDockAreas() == [log_area]
    assert widget.save_state() == unmaximized
    assert manager.openedDockAreas() == [log_area]
    assert button.isChecked()


# endregion
