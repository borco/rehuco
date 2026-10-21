"""Tests for TaskQueueWidget's record saves (#497): the Pending Saves toggle, Inspect and Discard Save, rows read
through the filter, and how a waiting job sits among the controls.

A sibling of ``test_task_queue_widget.py``, which is past the size cap: its sample jobs, fixtures and helpers are
imported from there, and the same discipline holds -- a real :class:`~rehuco_core.TaskQueue`, and every state a row
is in is one the engine genuinely put it in.
"""

import base64
import logging
from collections.abc import Callable
from typing import Any, Final, override

import cbor2
import PySide6QtAds as QtAds
from PySide6.QtCore import QItemSelectionModel
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.tasks.task_queue_model import LABEL_COLUMN
from rehuco_agent.tasks.task_queue_widget import (
    PENDING_SAVES_STATE_KEY,
    QUEUE_DOCK_NAME,
    TRY_NOW_TEXT,
    TRY_NOW_TOOLTIP,
    TaskQueueWidget,
)
from rehuco_core import SAVE_RECORD_KIND, JobControl, JobState, JobWaiting, TaskQueue

from rehuco_agent_tests.tasks.test_task_queue_widget import (  # noqa: F401  # pylint: disable=unused-import
    QUESTION,
    YES,
    FailingJob,
    GatedJob,
    fixture_deliver,
    fixture_queue,
    fixture_scoped_logger,
    fixture_widget,
    job_serial,
    layout_dock_entries,
    log_a_record_for,
    log_messages,
    running_job,
    saved_dock_entries,
    select_rows,
    ui_of,
    wait_for_state,
    widget_row_count,
    widget_status,
)

WAITING_REASON: Final = "The share holding this resource is offline."
"""What a waiting :class:`SaveJob` says it waits for."""

WAIT_SECONDS: Final = 3600.0
"""A wait no test outlives, so a waiting row stays waiting until teardown cancels it."""

EXTRA_DOCK_NAME: Final = "extra"
"""A sub-dock the shell does not build, added by a test to stand for one whose state it does not own."""


class SaveJob(GatedJob):
    """A job of the save kind, so the dock treats its row as a record save -- blocking like its base, or raising
    ``raises`` instead the moment it runs.

    Not a :class:`~rehuco_core.SaveRecordJob`: what the dock reads off a row is its kind and state, and what a real
    save does to reach one is that class's own tests' subject.

    :param label: the job's label.
    :param raises: what ``run`` raises -- a `JobWaiting` to wait, anything else to fail -- or ``None`` to block.
    """

    kind = SAVE_RECORD_KIND

    def __init__(self, label: str, raises: Exception | None = None) -> None:
        super().__init__(label)
        self.__raises: Final = raises

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

    @override
    def run(self, control: JobControl) -> None:
        if self.__raises is not None:
            raise self.__raises
        super().run(control)


# region fixtures and helpers


def waiting_save(queue: TaskQueue, label: str) -> None:
    """Enqueue a save that waits, and wait until the engine has put it there.

    :param queue: the queue to fill.
    :param label: the save's label.
    """
    queue.enqueue(SaveJob(label, JobWaiting(WAITING_REASON, WAIT_SECONDS)))
    wait_for_state(queue, label, JobState.WAITING)


def finished_save(queue: TaskQueue, label: str) -> None:
    """Enqueue a save that lands, and wait until it has.

    :param queue: the queue to fill.
    :param label: the save's label.
    """
    job = SaveJob(label)
    job.let_finish()
    queue.enqueue(job)
    wait_for_state(queue, label, JobState.DONE)


def failed_save(queue: TaskQueue, label: str) -> None:
    """Enqueue a save that fails, and wait until it has.

    :param queue: the queue to fill.
    :param label: the save's label.
    """
    queue.enqueue(SaveJob(label, OSError("the disk is full")))
    wait_for_state(queue, label, JobState.FAILED)


@fixture
def saves(queue: TaskQueue, deliver: Callable[[], None]) -> None:
    """Fill the queue with a row of every kind the save controls tell apart, each in the state its label says.

    In this order, one lane's worth: ``plain`` (a finished job that is not a save), ``failed save``, ``landed save``,
    ``dropped save`` (cancelled), ``plain failed``, ``waiting save``, ``paused`` (not a save), ``blocker`` (running,
    not a save) and ``queued save``, held in line behind it.

    :param queue: the queue to fill.
    :param deliver: pumps the event loop so the snapshot lands.
    """
    plain = GatedJob("plain")
    plain.let_finish()
    queue.enqueue(plain)
    wait_for_state(queue, "plain", JobState.DONE)
    failed_save(queue, "failed save")
    finished_save(queue, "landed save")
    running_job(queue, job=SaveJob("dropped save"))
    queue.cancel(job_serial(queue, "dropped save"))
    wait_for_state(queue, "dropped save", JobState.CANCELLED)
    queue.enqueue(FailingJob("plain failed"))
    wait_for_state(queue, "plain failed", JobState.FAILED)
    waiting_save(queue, "waiting save")
    running_job(queue, "paused")
    queue.pause_job(job_serial(queue, "paused"))
    wait_for_state(queue, "paused", JobState.PAUSED)
    running_job(queue, "blocker")
    queue.enqueue(SaveJob("queued save"))
    deliver()


def row_of(widget: TaskQueueWidget, label: str) -> int:
    """The model row of the job named ``label`` -- the view's row too, while the table is not filtered.

    :param widget: the widget to read.
    :param label: the label to find.
    :returns: that job's row.
    """
    return next(row for row in range(widget_row_count(widget)) if widget_status(widget, row).label == label)


def select_labels(widget: TaskQueueWidget, *labels: str) -> None:
    """Select exactly the rows of the jobs named ``labels``, with the table not filtered.

    :param widget: the widget to act on.
    :param labels: the jobs to select.
    """
    select_rows(widget, *(row_of(widget, label) for label in labels))


def shown_labels(widget: TaskQueueWidget) -> list[str]:
    """The labels the table shows, top to bottom -- read off the view's own model, filter and all.

    :param widget: the widget to read.
    :returns: the labels.
    """
    model = ui_of(widget).task_view.model()  # type: ignore[attr-defined]
    return [model.data(model.index(row, LABEL_COLUMN)) for row in range(model.rowCount())]


def emitted(signal: Any) -> list[Any]:
    """Collect what ``signal`` carries each time it is emitted from now on.

    :param signal: the bound signal to listen to.
    :returns: the list each payload is appended to.
    """
    payloads: list[Any] = []
    signal.connect(payloads.append)
    return payloads


def queue_dock_state(state: bytes) -> bytes | None:
    """The state the queue sub-dock's entry of a saved layout carries.

    :param state: what ``save_state`` returned.
    :returns: the decoded state, or ``None`` when the entry has none.
    """
    entry = saved_dock_entries(state)[QUEUE_DOCK_NAME]
    return base64.b64decode(entry["state"]) if "state" in entry else None


def with_queue_dock_state(state: bytes, dock_state: bytes | None) -> bytes:
    """A saved layout with the queue sub-dock's entry carrying ``dock_state`` instead.

    :param state: what ``save_state`` returned.
    :param dock_state: the state to put in the entry, or ``None`` for an entry with none, as before #497.
    :returns: the re-encoded layout.
    """
    values = cbor2.loads(state)
    for entry in layout_dock_entries(values):
        if entry["name"] == QUEUE_DOCK_NAME:
            entry.pop("state", None)
            if dock_state is not None:
                entry["state"] = base64.b64encode(dock_state).decode("ascii")
    return cbor2.dumps(values)


# endregion


# region the Pending Saves toggle


def test_the_toggle_narrows_the_table_to_the_saves_not_landed_and_back(widget: TaskQueueWidget, saves: None) -> None:
    """On, the table shows only the saves that have not landed, in queue order; off, every row again.

    **Test steps:**

    * fill the queue with every kind of row
    * check the Pending Saves toggle, and verify only the failed, waiting and queued saves are shown
    * uncheck it, and verify every row is back
    """
    del saves
    action = ui_of(widget).pending_saves_action  # type: ignore[attr-defined]
    everything = shown_labels(widget)

    action.setChecked(True)
    assert shown_labels(widget) == ["failed save", "waiting save", "queued save"]

    action.setChecked(False)
    assert shown_labels(widget) == everything
    assert len(everything) == widget_row_count(widget)


def test_show_pending_saves_checks_the_toggle(widget: TaskQueueWidget, saves: None) -> None:
    """What the status bar's counter asks for is the toggle itself, so the toolbar and the table agree.

    **Test steps:**

    * fill the queue with every kind of row
    * call ``show_pending_saves``
    * verify the toggle is checked and the table filtered
    """
    del saves

    widget.show_pending_saves()

    assert ui_of(widget).pending_saves_action.isChecked()  # type: ignore[attr-defined]
    assert shown_labels(widget) == ["failed save", "waiting save", "queued save"]


def test_the_toggle_rides_the_queue_dock_s_saved_state(queue: TaskQueue, qtbot: QtBot) -> None:
    """Checked, the toggle is saved into the queue sub-dock's entry and comes back checked; unchecked, the entry
    carries nothing at all.

    **Test steps:**

    * save a shell's state with the toggle off, and verify the queue entry has no state
    * check it and save again, and verify the entry carries it
    * restore that state into a second shell
    * verify the restore succeeded and the second shell's toggle is checked
    """
    source = TaskQueueWidget(queue)
    qtbot.addWidget(source)
    assert queue_dock_state(source.save_state()) is None

    ui_of(source).pending_saves_action.setChecked(True)  # type: ignore[attr-defined]
    state = source.save_state()
    assert queue_dock_state(state) == cbor2.dumps({PENDING_SAVES_STATE_KEY: True})

    restored = TaskQueueWidget(queue)
    qtbot.addWidget(restored)

    assert restored.restore_state(state) is True
    assert ui_of(restored).pending_saves_action.isChecked()  # type: ignore[attr-defined]


def test_a_layout_from_before_the_toggle_restores_it_off(queue: TaskQueue, qtbot: QtBot) -> None:
    """A layout saved before #497 has no state on the queue's entry, and a shell restored from it shows every row.

    **Test steps:**

    * save a shell's state with the toggle on, and strip the queue entry's state, as an older layout has none
    * restore that into a second shell
    * verify the restore succeeded and the toggle is off
    """
    source = TaskQueueWidget(queue)
    qtbot.addWidget(source)
    ui_of(source).pending_saves_action.setChecked(True)  # type: ignore[attr-defined]
    old = with_queue_dock_state(source.save_state(), None)

    restored = TaskQueueWidget(queue)
    qtbot.addWidget(restored)

    assert restored.restore_state(old) is True
    assert not ui_of(restored).pending_saves_action.isChecked()  # type: ignore[attr-defined]


def test_a_queue_state_that_does_not_say_on_reads_off(widget: TaskQueueWidget) -> None:
    """Only the toggle saved as ``True`` turns it on: a mapping without it, or with anything else there, is off.

    **Test steps:**

    * check the toggle and save the state
    * restore it with the queue entry's mapping holding no toggle, then holding ``1``
    * verify each time the toggle reads off
    """
    action = ui_of(widget).pending_saves_action  # type: ignore[attr-defined]
    action.setChecked(True)
    state = widget.save_state()

    for saved in ({}, {PENDING_SAVES_STATE_KEY: 1}):
        action.setChecked(True)
        assert widget.restore_state(with_queue_dock_state(state, cbor2.dumps(saved))) is True
        assert not action.isChecked(), saved


def test_an_unreadable_queue_state_leaves_the_toggle_as_it_is(widget: TaskQueueWidget) -> None:
    """A queue entry whose state is not CBOR, or not a mapping, is ignored rather than read as either answer.

    **Test steps:**

    * check the toggle and save the state
    * restore it with the queue entry's state undecodable, then a list
    * verify each restore succeeded and the toggle is still checked
    """
    action = ui_of(widget).pending_saves_action  # type: ignore[attr-defined]
    action.setChecked(True)
    state = widget.save_state()

    for saved in (b"\x1c", cbor2.dumps([PENDING_SAVES_STATE_KEY, True])):
        assert widget.restore_state(with_queue_dock_state(state, saved)) is True
        assert action.isChecked(), saved


def test_a_sub_dock_the_shell_does_not_own_saves_and_restores_no_state(widget: TaskQueueWidget) -> None:
    """A sub-dock that is neither the table nor the log has no state of this shell's to carry, either way.

    **Test steps:**

    * add a third sub-dock to the shell's manager, check the toggle, and save the state
    * verify the extra dock's entry carries no state
    * restore the state with a state put on the extra dock's entry
    * verify the restore succeeded and neither the toggle nor the log's filters moved
    """
    manager = widget._TaskQueueWidget__dock_manager  # type: ignore[attr-defined]  # pylint: disable=protected-access
    extra = QtAds.CDockWidget(manager, EXTRA_DOCK_NAME)
    extra.setObjectName(EXTRA_DOCK_NAME)
    manager.addDockWidget(QtAds.BottomDockWidgetArea, extra)
    action = ui_of(widget).pending_saves_action  # type: ignore[attr-defined]
    action.setChecked(True)
    log_state = widget.log_widget.save_state()
    values = cbor2.loads(widget.save_state())
    (entry,) = [entry for entry in layout_dock_entries(values) if entry["name"] == EXTRA_DOCK_NAME]
    assert "state" not in entry

    entry["state"] = base64.b64encode(cbor2.dumps({PENDING_SAVES_STATE_KEY: False})).decode("ascii")

    assert widget.restore_state(cbor2.dumps(values)) is True
    assert action.isChecked()
    assert widget.log_widget.save_state() == log_state


# endregion


# region Inspect Save and Discard Save


def test_inspect_is_offered_for_exactly_one_failed_or_waiting_save(widget: TaskQueueWidget, saves: None) -> None:
    """Inspect is for one save with a reason it has not landed: a failed or a waiting one, alone.

    **Test steps:**

    * fill the queue with every kind of row
    * select each lone failed or waiting save, and verify Inspect is enabled
    * select a queued save, a landed one, a failed job that is not a save, and two failed-or-waiting saves
      together, and verify it is disabled for each
    """
    del saves
    action = ui_of(widget).inspect_save_action  # type: ignore[attr-defined]

    for label in ("failed save", "waiting save"):
        select_labels(widget, label)
        assert action.isEnabled(), label

    for labels in (("queued save",), ("landed save",), ("plain failed",), ("failed save", "waiting save")):
        select_labels(widget, *labels)
        assert not action.isEnabled(), labels


def test_discard_is_offered_while_the_selection_holds_a_save_not_landed(widget: TaskQueueWidget, saves: None) -> None:
    """Discard is for the saves that have not landed, and any one of them in a selection is enough.

    **Test steps:**

    * fill the queue with every kind of row
    * select each save not landed, and one beside a job that is not a save, and verify Discard is enabled
    * select a landed save, a cancelled one, and jobs that are not saves, and verify it is disabled
    """
    del saves
    action = ui_of(widget).discard_save_action  # type: ignore[attr-defined]

    for labels in (("failed save",), ("waiting save",), ("queued save",), ("plain", "waiting save")):
        select_labels(widget, *labels)
        assert action.isEnabled(), labels

    for labels in (("landed save",), ("dropped save",), ("plain", "plain failed", "paused")):
        select_labels(widget, *labels)
        assert not action.isEnabled(), labels


def test_inspect_asks_for_the_selected_save_by_serial(widget: TaskQueueWidget, queue: TaskQueue, saves: None) -> None:
    """Inspect only says which save was asked for; showing it is the owner's.

    **Test steps:**

    * fill the queue with every kind of row and select the waiting save
    * trigger Inspect Save
    * verify ``inspect_save_requested`` carried that save's serial, once
    """
    del saves
    asked = emitted(widget.inspect_save_requested)
    select_labels(widget, "waiting save")

    ui_of(widget).inspect_save_action.trigger()  # type: ignore[attr-defined]

    assert asked == [job_serial(queue, "waiting save")]


def test_discard_asks_for_only_the_selected_saves_not_landed(
    widget: TaskQueueWidget, queue: TaskQueue, saves: None
) -> None:
    """The rest of a selection is not a save to discard, and is left out of what Discard asks for.

    **Test steps:**

    * fill the queue with every kind of row
    * select a finished job, the failed save, the landed save and the waiting save
    * trigger Discard Save
    * verify ``discard_saves_requested`` carried the failed and waiting saves' serials, in view order, once
    """
    del saves
    asked = emitted(widget.discard_saves_requested)
    select_labels(widget, "plain", "failed save", "landed save", "waiting save")

    ui_of(widget).discard_save_action.trigger()  # type: ignore[attr-defined]

    assert asked == [[job_serial(queue, "failed save"), job_serial(queue, "waiting save")]]


def test_inspect_and_discard_ask_for_nothing_when_they_have_nothing_to_act_on(
    widget: TaskQueueWidget, saves: None
) -> None:
    """Reached with nothing they could act on, neither asks the owner for anything.

    Called directly: a disabled action's ``trigger`` does nothing, so this is the guard behind it.

    **Test steps:**

    * fill the queue with every kind of row and select two saves, so Inspect has no one save
    * run Inspect's handler, and verify nothing was asked for
    * select only the landed save, run Discard's handler, and verify nothing was asked for
    """
    del saves
    inspected = emitted(widget.inspect_save_requested)
    discarded = emitted(widget.discard_saves_requested)

    select_labels(widget, "failed save", "waiting save")
    widget._TaskQueueWidget__inspect_selection()  # type: ignore[attr-defined]  # pylint: disable=protected-access
    select_labels(widget, "landed save")
    widget._TaskQueueWidget__discard_selection()  # type: ignore[attr-defined]  # pylint: disable=protected-access

    assert not inspected
    assert not discarded


# endregion


# region rows read through the filter


def test_a_filtered_selection_is_read_as_the_model_s_own_rows(
    widget: TaskQueueWidget, queue: TaskQueue, saves: None
) -> None:
    """While the toggle filters, a view row is not a model row: the controls and what they ask for follow the
    job the reader points at.

    **Test steps:**

    * fill the queue with every kind of row, and check the toggle
    * select the view's first row, the failed save -- the model's first row is a finished job that is not a save
    * verify Inspect and Retry are enabled, and Inspect asks for the failed save's serial
    """
    del saves
    ui = ui_of(widget)
    ui.pending_saves_action.setChecked(True)  # type: ignore[attr-defined]
    asked = emitted(widget.inspect_save_requested)

    select_rows(widget, 0)
    ui.inspect_save_action.trigger()  # type: ignore[attr-defined]

    assert ui.retry_action.isEnabled()  # type: ignore[attr-defined]
    assert asked == [job_serial(queue, "failed save")]


def test_a_filtered_current_row_points_the_log_at_its_own_job(
    widget: TaskQueueWidget,
    queue: TaskQueue,
    saves: None,
    scoped_logger: logging.Logger,
    deliver: Callable[[], None],
) -> None:
    """The log follows the current row of the filtered table, mapped to its own job.

    **Test steps:**

    * fill the queue with every kind of row, log a record under the failed and the waiting save's scopes, and
      check the toggle
    * select the view's first two rows, the current index on the second
    * verify the log shows the waiting save's record only
    """
    del saves
    log_a_record_for(queue, scoped_logger, "failed save")
    log_a_record_for(queue, scoped_logger, "waiting save")
    deliver()
    ui = ui_of(widget)
    ui.pending_saves_action.setChecked(True)  # type: ignore[attr-defined]
    view = ui.task_view  # type: ignore[attr-defined]
    rows = QItemSelectionModel.SelectionFlag.Rows
    view.selectionModel().select(view.model().index(0, 0), QItemSelectionModel.SelectionFlag.Select | rows)

    view.selectionModel().setCurrentIndex(view.model().index(1, 0), QItemSelectionModel.SelectionFlag.Select | rows)

    assert log_messages(widget) == ["about waiting save"]


# endregion


# region Cancel and Clear over saves


def serials_of(queue: TaskQueue, *labels: str) -> list[int]:
    """The serials of the jobs named ``labels``, in that order.

    :param queue: the queue to read.
    :param labels: the jobs.
    :returns: their serials.
    """
    return [job_serial(queue, label) for label in labels]


def test_cancel_sends_the_pending_saves_to_their_owner_and_cancels_the_rest(
    widget: TaskQueueWidget, queue: TaskQueue, saves: None, mocker: MockerFixture
) -> None:
    """Cancelling a save not landed is a Drop the save owner asks about: Cancel hands those rows to it, and asks
    its own question only about the rest, which it cancels.

    **Test steps:**

    * fill the queue with every kind of row, and select the waiting save, the paused job and the queued save
    * trigger Cancel, answering *Yes*
    * verify ``discard_saves_requested`` carried the two saves once, the question counted only the paused job, and
      only it was cancelled
    """
    del saves
    asked = emitted(widget.discard_saves_requested)
    question = mocker.patch(QUESTION, return_value=YES)
    cancel = mocker.patch.object(queue, "cancel")
    select_labels(widget, "waiting save", "paused", "queued save")

    ui_of(widget).cancel_action.trigger()  # type: ignore[attr-defined]

    assert asked == [serials_of(queue, "waiting save", "queued save")]
    (_, _, text, _) = question.call_args.args
    assert text == "Cancel this job?"
    cancel.assert_called_once_with(job_serial(queue, "paused"))


def test_cancel_over_only_pending_saves_asks_its_own_question_about_nothing(
    widget: TaskQueueWidget, queue: TaskQueue, saves: None, mocker: MockerFixture
) -> None:
    """A Cancel of saves not landed alone leaves this dock nothing to confirm: the owner asks, and nothing is
    cancelled here.

    **Test steps:**

    * fill the queue with every kind of row, and select the failed and the waiting save
    * trigger Cancel
    * verify ``discard_saves_requested`` carried both, no question was asked here, and nothing was cancelled
    """
    del saves
    asked = emitted(widget.discard_saves_requested)
    question = mocker.patch(QUESTION, return_value=YES)
    cancel = mocker.patch.object(queue, "cancel")
    select_labels(widget, "failed save", "waiting save")

    ui_of(widget).cancel_action.trigger()  # type: ignore[attr-defined]

    assert asked == [serials_of(queue, "failed save", "waiting save")]
    question.assert_not_called()
    cancel.assert_not_called()


def test_clear_sends_the_pending_saves_to_their_owner_and_removes_the_rest(
    widget: TaskQueueWidget, queue: TaskQueue, saves: None, mocker: MockerFixture
) -> None:
    """Clearing a save not landed is a Drop too: Clear hands those rows to the owner and removes the rest -- a
    landed save among them, which is history.

    **Test steps:**

    * fill the queue with every kind of row, and select a finished job, the failed save, the landed save and the
      queued save
    * trigger Clear
    * verify ``discard_saves_requested`` carried the failed and the queued save once, and only the finished job and
      the landed save were removed
    """
    del saves
    asked = emitted(widget.discard_saves_requested)
    remove = mocker.patch.object(queue, "remove")
    select_labels(widget, "plain", "failed save", "landed save", "queued save")

    ui_of(widget).clear_action.trigger()  # type: ignore[attr-defined]

    assert asked == [serials_of(queue, "failed save", "queued save")]
    remove.assert_called_once_with(*serials_of(queue, "plain", "landed save"))


def test_clear_over_only_pending_saves_removes_nothing_here(
    widget: TaskQueueWidget, queue: TaskQueue, saves: None, mocker: MockerFixture
) -> None:
    """A Clear of saves not landed alone removes nothing itself: the rows go to the owner.

    **Test steps:**

    * fill the queue with every kind of row, and select the waiting save
    * trigger Clear
    * verify ``discard_saves_requested`` carried it and nothing was removed
    """
    del saves
    asked = emitted(widget.discard_saves_requested)
    remove = mocker.patch.object(queue, "remove")
    select_labels(widget, "waiting save")

    ui_of(widget).clear_action.trigger()  # type: ignore[attr-defined]

    assert asked == [serials_of(queue, "waiting save")]
    remove.assert_not_called()


def test_the_sweeps_leave_a_failed_save_alone(
    widget: TaskQueueWidget, queue: TaskQueue, saves: None, mocker: MockerFixture
) -> None:
    """Clear Done and Clear Failed sweep their own kind but a save not landed: a failed save still holds the edits it
    could not write, and no sweep asks the owner for a Drop.

    **Test steps:**

    * fill the queue with every kind of row
    * trigger Clear Done, then Clear Failed
    * verify the first removed the finished job and the landed save, the second only the failed job that is no
      save, and nothing was handed to the owner
    """
    del saves
    asked = emitted(widget.discard_saves_requested)
    remove = mocker.patch.object(queue, "remove")
    ui = ui_of(widget)

    ui.clear_done_action.trigger()  # type: ignore[attr-defined]
    ui.clear_failed_action.trigger()  # type: ignore[attr-defined]

    assert [call.args for call in remove.call_args_list] == [
        tuple(serials_of(queue, "plain", "landed save")),
        tuple(serials_of(queue, "plain failed")),
    ]
    assert not asked


def test_clear_all_leaves_every_pending_save_alone(
    widget: TaskQueueWidget, queue: TaskQueue, saves: None, mocker: MockerFixture
) -> None:
    """Clear All empties the queue but of its saves not landed: those are neither cancelled nor removed, and no Drop
    is asked of the owner.

    **Test steps:**

    * fill the queue with every kind of row
    * trigger Clear All
    * verify only the unfinished jobs that are no save were cancelled, every row but the failed, waiting and queued
      saves was removed, and nothing was handed to the owner
    """
    del saves
    asked = emitted(widget.discard_saves_requested)
    cancel = mocker.patch.object(queue, "cancel")
    remove = mocker.patch.object(queue, "remove")

    ui_of(widget).clear_all_action.trigger()  # type: ignore[attr-defined]

    assert [call.args[0] for call in cancel.call_args_list] == serials_of(queue, "paused", "blocker")
    remove.assert_called_once_with(
        *serials_of(queue, "plain", "landed save", "dropped save", "plain failed", "paused", "blocker")
    )
    assert not asked


# endregion


# region a waiting job among the controls


def test_a_waiting_save_can_be_paused_cancelled_tried_now_moved_inspected_and_discarded(
    widget: TaskQueueWidget, saves: None
) -> None:
    """Pointing at a waiting save and pausing it is how a reader stops it retrying by itself; it can be cancelled,
    tried now, moved, cleared, inspected and discarded too -- but not retried, since it has not failed.

    **Test steps:**

    * fill the queue with every kind of row and select the waiting save
    * verify exactly the expected controls are enabled
    """
    del saves
    select_labels(widget, "waiting save")
    ui = ui_of(widget)

    actual = {
        "pause": ui.pause_action.isEnabled(),  # type: ignore[attr-defined]
        "resume": ui.resume_action.isEnabled(),  # type: ignore[attr-defined]
        "cancel": ui.cancel_action.isEnabled(),  # type: ignore[attr-defined]
        "retry": ui.retry_action.isEnabled(),  # type: ignore[attr-defined]
        "clear": ui.clear_action.isEnabled(),  # type: ignore[attr-defined]
        "move": ui.move_to_top_action.isEnabled(),  # type: ignore[attr-defined]
        "inspect": ui.inspect_save_action.isEnabled(),  # type: ignore[attr-defined]
        "discard": ui.discard_save_action.isEnabled(),  # type: ignore[attr-defined]
    }

    assert {name for name, is_on in actual.items() if is_on} == {
        "pause",
        "resume",
        "cancel",
        "clear",
        "move",
        "inspect",
        "discard",
    }


def test_resume_reads_try_now_over_waiting_rows_only(widget: TaskQueueWidget, saves: None) -> None:
    """A waiting job was never held, so Resume over it says what the engine does: *Try Now*. Over anything it
    would resume that is not waiting, it says Resume again.

    **Test steps:**

    * fill the queue with every kind of row, and note Resume's own text and tooltip
    * select the waiting save, and verify Resume is enabled and reads *Try Now*
    * add the paused job to the selection, and verify it reads as it was built
    * select the waiting save beside a finished job Resume does not act on, and verify it reads *Try Now*
    * select the paused job alone, and verify it reads as it was built
    """
    del saves
    action = ui_of(widget).resume_action  # type: ignore[attr-defined]
    built = (action.text(), action.toolTip())

    select_labels(widget, "waiting save")
    assert action.isEnabled()
    assert (action.text(), action.toolTip()) == (TRY_NOW_TEXT, TRY_NOW_TOOLTIP)

    select_labels(widget, "waiting save", "paused")
    assert (action.text(), action.toolTip()) == built

    select_labels(widget, "plain", "waiting save")
    assert (action.text(), action.toolTip()) == (TRY_NOW_TEXT, TRY_NOW_TOOLTIP)

    select_labels(widget, "paused")
    assert (action.text(), action.toolTip()) == built


def test_a_waiting_job_alone_enables_neither_bulk_control(
    widget: TaskQueueWidget, queue: TaskQueue, deliver: Callable[[], None]
) -> None:
    """The engine's bulk pause and resume both leave a waiting job alone, so one alone offers neither.

    **Test steps:**

    * leave the queue holding only a waiting save
    * verify Pause All and Resume All are both disabled
    """
    waiting_save(queue, "waiting save")
    deliver()
    ui = ui_of(widget)

    assert widget_status(widget, 0).state is JobState.WAITING
    assert not ui.pause_all_action.isEnabled()  # type: ignore[attr-defined]
    assert not ui.resume_all_action.isEnabled()  # type: ignore[attr-defined]


# endregion
