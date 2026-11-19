"""Tests for the Tasks dock giving up a move with a partial copy (#634): Cancel and the Clear sweeps ask, once the
copy's place has answered, whether it goes or stays -- and say it stays when its place does not answer.

A sibling of ``test_task_queue_widget.py``, which is past the size cap: its rig, fixtures and helpers are imported by
name. The jobs are ``Mock(spec=MoveRecordJob)`` (the job's own tests are in rehuco-core), the scan answers at once
(:class:`borco_core.PresenceScan` is tested in borco-core), and the question's ``exec`` presses a button by its text.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Final
from unittest.mock import MagicMock, Mock, create_autospec

from borco_core import Presence, PresenceScan
from PySide6.QtWidgets import QMessageBox
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.tasks.task_queue_widget import TaskQueueWidget
from rehuco_core import JobState, MoveRecordJob

from rehuco_agent_tests.tasks.test_task_queue_widget import (  # noqa: F401  # pylint: disable=unused-import
    QUESTION,
    Rig,
    fixture_queue,
    fixture_rig,
    fixture_widget,
    select_rows,
    ui_of,
)

MODULE: Final = "rehuco_agent.tasks.partial_copy_question"
PLACE: Final = Path("T:/Courses/Smith/Intro")
OTHER_PLACE: Final = Path("E:/Courses/Jones/Basics")


# a record of what was shown, read by the tests, not an API
# pylint: disable-next=too-few-public-methods
class Asked:
    """The question as it was shown, and the button pressed on it.

    :param mocker: pytest-mock fixture.
    :param pressed: the text of the button to press, or ``None`` to press none (the question was closed).
    """

    def __init__(self, mocker: MockerFixture, pressed: str | None) -> None:
        self.texts: Final[list[tuple[str, str, list[str], str]]] = []
        """Each question's text, informative text, buttons and default button, read while it was shown."""
        # a plain function rather than an autospec: PySide's exec is a builtin, which an autospec does not bind
        self.exec: Final = mocker.patch.object(QMessageBox, "exec", new=self.__press(pressed))

    @property
    def shown(self) -> bool:
        """Whether the question has been shown."""
        return bool(self.texts)

    def __press(self, pressed: str | None) -> Callable[[QMessageBox], int]:
        def press(box: QMessageBox) -> int:
            buttons = {button.text(): button for button in box.buttons()}
            default = box.defaultButton()
            self.texts.append(
                (box.text(), box.informativeText(), list(buttons), "" if default is None else default.text())
            )
            if pressed is not None:
                buttons[pressed].click()
            return 0

        return press


def only_question(asked: Asked) -> tuple[str, str, list[str], str]:
    """The one question shown.

    :param asked: the question's record.
    :returns: its text, informative text, buttons and default button.
    """
    assert len(asked.texts) == 1
    return asked.texts[0]


def answering(mocker: MockerFixture, answers: dict[Path, Presence]) -> MagicMock:
    """Make each scan answer at once: every place as ``answers`` says, present by default.

    :param mocker: pytest-mock fixture.
    :param answers: the places that do not read as present.
    :returns: the patched scan class.
    """

    def scan(paths: set[Path], on_answer: Callable[[Path, Presence], None]) -> MagicMock:
        made = MagicMock(spec=PresenceScan)
        made.start.side_effect = lambda: [on_answer(path, answers.get(path, Presence.PRESENT)) for path in paths]
        return made

    return mocker.patch(f"{MODULE}.PresenceScan", side_effect=scan)


@fixture(name="jobs")
def fixture_jobs(rig: Rig) -> dict[int, Mock]:
    """The job behind each row a test gives one, answered by the rig's ``job``.

    :param rig: the rig.
    :returns: the jobs, by serial.
    """
    jobs: dict[int, Mock] = {}
    rig.queue.job.side_effect = jobs.get
    return jobs


def add_move(rig: Rig, jobs: dict[int, Mock], label: str, state: JobState, partial: Path | None) -> Mock:
    """Put a move's row in the queue, its job naming ``partial`` as its partial copy.

    :param rig: the rig.
    :param jobs: the jobs by serial.
    :param label: the row's label.
    :param state: its state.
    :param partial: where its partial copy is, or ``None``.
    :returns: its job.
    """
    serial = rig.add(label, state)
    job = create_autospec(MoveRecordJob, instance=True)
    # a runtime protocol is checked by getattr_static, which sees no attribute a mock makes on demand: every data
    # member a real job holds is set, as the real one sets it in its constructor
    job.configure_mock(
        label=label,
        partial=partial,
        chain=None,
        source=None,
        progress_unit=MoveRecordJob.progress_unit,
        safely_interruptible=MoveRecordJob.safely_interruptible,
        resumes_where_it_stopped=MoveRecordJob.resumes_where_it_stopped,
    )
    jobs[serial] = job
    return job


def wait_for_question(qtbot: QtBot, asked: Asked) -> None:
    """Wait for the question, which shows once the scan's answer crossed to the GUI thread.

    :param qtbot: pytest-qt fixture.
    :param asked: the question's record.
    """
    qtbot.waitUntil(lambda: asked.shown)


# region cancel
def test_a_cancel_removing_the_partial_copy_is_the_default_and_tells_the_job(
    widget: TaskQueueWidget, rig: Rig, jobs: dict[int, Mock], mocker: MockerFixture, qtbot: QtBot
) -> None:
    """Canceling a move with a partial copy says where it is, offers removing it first, and has the job take it back.

    **Test steps:**

    * script a running move with a partial copy, its place answering, select it, and press Cancel
    * press Remove Partial Copy
    * check the question named the copy's place, Remove was the default, and the job was told to keep nothing and
      canceled; the plain question was not asked
    """
    job = add_move(rig, jobs, "Move - Intro", JobState.RUNNING, PLACE)
    rig.settle()
    answering(mocker, {})
    plain = mocker.patch(QUESTION)
    asked = Asked(mocker, "Remove Partial Copy")
    select_rows(widget, 0)

    ui_of(widget).cancel_action.trigger()  # type: ignore[attr-defined]
    wait_for_question(qtbot, asked)

    text, informative, buttons, default = only_question(asked)
    assert text == "Cancel this job?"
    assert str(PLACE) in informative
    assert buttons == ["Remove Partial Copy", "Keep Partial Copy", "Don't Cancel"]
    assert default == "Remove Partial Copy"
    job.keep_partial.assert_called_once_with(False)
    rig.queue.cancel.assert_called_once_with(rig.serial("Move - Intro"))
    plain.assert_not_called()


def test_a_cancel_keeping_the_partial_copy_tells_the_job_to_keep_it(
    widget: TaskQueueWidget, rig: Rig, jobs: dict[int, Mock], mocker: MockerFixture, qtbot: QtBot
) -> None:
    """Keep leaves the copy where it is, for a Retry to go on from.

    **Test steps:**

    * script a paused move with a partial copy, select it, press Cancel, and press Keep Partial Copy
    * check the job was told to keep it, and canceled
    """
    job = add_move(rig, jobs, "Move - Intro", JobState.PAUSED, PLACE)
    rig.settle()
    answering(mocker, {})
    asked = Asked(mocker, "Keep Partial Copy")
    select_rows(widget, 0)

    ui_of(widget).cancel_action.trigger()  # type: ignore[attr-defined]
    wait_for_question(qtbot, asked)

    job.keep_partial.assert_called_once_with(True)
    rig.queue.cancel.assert_called_once_with(rig.serial("Move - Intro"))


def test_a_cancel_refused_or_closed_cancels_nothing(
    widget: TaskQueueWidget, rig: Rig, jobs: dict[int, Mock], mocker: MockerFixture, qtbot: QtBot
) -> None:
    """Don't Cancel, or closing the question, gives nothing up and tells the job nothing.

    **Test steps:**

    * script a running move with a partial copy, select it, press Cancel and Don't Cancel; then Cancel and close it
    * check nothing was canceled and the job was told nothing
    """
    job = add_move(rig, jobs, "Move - Intro", JobState.RUNNING, PLACE)
    rig.settle()
    answering(mocker, {})
    select_rows(widget, 0)

    for pressed in ("Don't Cancel", None):
        asked = Asked(mocker, pressed)
        ui_of(widget).cancel_action.trigger()  # type: ignore[attr-defined]
        wait_for_question(qtbot, asked)
        mocker.stop(asked.exec)

    rig.queue.cancel.assert_not_called()
    job.keep_partial.assert_not_called()


def test_a_cancel_whose_copy_s_place_does_not_answer_says_it_stays(
    widget: TaskQueueWidget, rig: Rig, jobs: dict[int, Mock], mocker: MockerFixture, qtbot: QtBot
) -> None:
    """A copy on a share that does not answer cannot be removed: the question says it stays, offers only to cancel or
    not -- not canceling the default -- and the job is told to keep it.

    **Test steps:**

    * script a waiting move whose copy's place does not answer, select it, press Cancel, and press Cancel
    * check the question said the copy stays, offered Cancel and Don't Cancel with Don't Cancel the default, and the
      job was told to keep its copy and canceled
    """
    job = add_move(rig, jobs, "Move - Intro", JobState.WAITING, PLACE)
    rig.settle()
    answering(mocker, {PLACE: Presence.OFFLINE})
    asked = Asked(mocker, "Cancel")
    select_rows(widget, 0)

    ui_of(widget).cancel_action.trigger()  # type: ignore[attr-defined]
    wait_for_question(qtbot, asked)

    _, informative, buttons, default = only_question(asked)
    assert "does not answer" in informative and "remove by hand" in informative
    assert buttons == ["Cancel", "Don't Cancel"]
    assert default == "Don't Cancel"
    job.keep_partial.assert_called_once_with(True)
    rig.queue.cancel.assert_called_once_with(rig.serial("Move - Intro"))


def test_one_question_covers_a_selection_of_moves_and_other_jobs(
    widget: TaskQueueWidget, rig: Rig, jobs: dict[int, Mock], mocker: MockerFixture, qtbot: QtBot
) -> None:
    """A selection gets one question: copies that answer go as chosen, one that does not stays, and a job with no
    copy is canceled with them.

    **Test steps:**

    * script a move whose copy's place answers, one whose does not, and a plain job; select all, press Cancel and
      Remove Partial Copy
    * check the question counted three jobs and named both copies; the first move was told to keep nothing, the
      second to keep its copy, and all three were canceled
    """
    here = add_move(rig, jobs, "Move - Intro", JobState.RUNNING, PLACE)
    away = add_move(rig, jobs, "Move - Basics", JobState.QUEUED, OTHER_PLACE)
    rig.add("plain", JobState.QUEUED)
    rig.settle()
    answering(mocker, {OTHER_PLACE: Presence.OFFLINE})
    asked = Asked(mocker, "Remove Partial Copy")
    select_rows(widget, 0, 1, 2)

    ui_of(widget).cancel_action.trigger()  # type: ignore[attr-defined]
    wait_for_question(qtbot, asked)

    text, informative, _, _ = only_question(asked)
    assert text == "Cancel 3 jobs?"
    assert str(PLACE) in informative and str(OTHER_PLACE) in informative
    here.keep_partial.assert_called_once_with(False)
    away.keep_partial.assert_called_once_with(True)
    assert [made.args[0] for made in rig.queue.cancel.call_args_list] == rig.serials(
        "Move - Intro", "Move - Basics", "plain"
    )


def test_a_move_with_no_partial_copy_gets_the_plain_question(
    widget: TaskQueueWidget, rig: Rig, jobs: dict[int, Mock], mocker: MockerFixture
) -> None:
    """A move that wrote nothing yet has nothing to ask about: Cancel asks what it always asked.

    **Test steps:**

    * script a queued move with no partial copy, select it, and press Cancel, answering Yes
    * check no scan started, and the job was canceled
    """
    add_move(rig, jobs, "Move - Intro", JobState.QUEUED, None)
    rig.settle()
    scan = answering(mocker, {})
    mocker.patch(QUESTION, return_value=QMessageBox.StandardButton.Yes)
    select_rows(widget, 0)

    ui_of(widget).cancel_action.trigger()  # type: ignore[attr-defined]

    scan.assert_not_called()
    rig.queue.cancel.assert_called_once_with(rig.serial("Move - Intro"))


def test_a_cancel_asks_nothing_about_the_copy_of_a_finished_move(
    widget: TaskQueueWidget, rig: Rig, jobs: dict[int, Mock], mocker: MockerFixture
) -> None:
    """A cancel does nothing to a finished row, so it offers nothing about its copy: that is its Clear's to ask.

    **Test steps:**

    * script a failed move with a partial copy and a queued plain job, select both, and press Cancel, answering Yes
    * check no scan started, no question about a copy was shown, and the failed move's job was told nothing
    """
    failed = add_move(rig, jobs, "Move - Intro", JobState.FAILED, PLACE)
    rig.add("plain", JobState.QUEUED)
    rig.settle()
    scan = answering(mocker, {})
    asked = Asked(mocker, None)
    mocker.patch(QUESTION, return_value=QMessageBox.StandardButton.Yes)
    select_rows(widget, 0, 1)

    ui_of(widget).cancel_action.trigger()  # type: ignore[attr-defined]

    scan.assert_not_called()
    assert not asked.shown
    failed.keep_partial.assert_not_called()


def test_a_cancel_asked_again_while_the_first_waits_for_its_scan_is_dropped(
    widget: TaskQueueWidget, rig: Rig, jobs: dict[int, Mock], mocker: MockerFixture
) -> None:
    """One question at a time: a second press while the first waits for the place to answer starts nothing.

    **Test steps:**

    * script a move with a partial copy, make the scan never answer, select it, and press Cancel twice
    * check one scan was started, and nothing was canceled
    """
    add_move(rig, jobs, "Move - Intro", JobState.RUNNING, PLACE)
    rig.settle()
    scan = mocker.patch(f"{MODULE}.PresenceScan")
    select_rows(widget, 0)

    ui_of(widget).cancel_action.trigger()  # type: ignore[attr-defined]
    ui_of(widget).cancel_action.trigger()  # type: ignore[attr-defined]

    scan.assert_called_once()
    rig.queue.cancel.assert_not_called()


# endregion


# region clear
def test_clearing_a_failed_move_removes_its_partial_copy_by_default(
    widget: TaskQueueWidget, rig: Rig, jobs: dict[int, Mock], mocker: MockerFixture, qtbot: QtBot
) -> None:
    """A failed move's copy would block a new move to the same place: clearing it offers removing it first.

    **Test steps:**

    * script a failed move with a partial copy, select it, press Clear, and press Remove Partial Copy
    * check the question asked to clear, Remove was the default, the job removed its copy, and the row was removed
    """
    job = add_move(rig, jobs, "Move - Intro", JobState.FAILED, PLACE)
    rig.settle()
    answering(mocker, {})
    asked = Asked(mocker, "Remove Partial Copy")
    select_rows(widget, 0)

    ui_of(widget).clear_action.trigger()  # type: ignore[attr-defined]
    wait_for_question(qtbot, asked)

    text, _, buttons, default = only_question(asked)
    assert text == "Clear this job?"
    assert buttons == ["Remove Partial Copy", "Keep Partial Copy", "Don't Clear"]
    assert default == "Remove Partial Copy"
    job.discard_partial.assert_called_once_with()
    rig.queue.remove.assert_called_once_with(rig.serial("Move - Intro"))


def test_clearing_a_move_keeping_its_partial_copy_removes_only_the_row(
    widget: TaskQueueWidget, rig: Rig, jobs: dict[int, Mock], mocker: MockerFixture, qtbot: QtBot
) -> None:
    """Keep leaves the copy; the row goes.

    **Test steps:**

    * script a canceled move with a kept partial copy, select it, press Clear, and press Keep Partial Copy
    * check the copy was not removed and the row was
    """
    job = add_move(rig, jobs, "Move - Intro", JobState.CANCELED, PLACE)
    rig.settle()
    answering(mocker, {})
    asked = Asked(mocker, "Keep Partial Copy")
    select_rows(widget, 0)

    ui_of(widget).clear_action.trigger()  # type: ignore[attr-defined]
    wait_for_question(qtbot, asked)

    job.discard_partial.assert_not_called()
    rig.queue.remove.assert_called_once_with(rig.serial("Move - Intro"))


def test_clearing_a_move_whose_copy_s_place_does_not_answer_leaves_the_copy(
    widget: TaskQueueWidget, rig: Rig, jobs: dict[int, Mock], mocker: MockerFixture, qtbot: QtBot
) -> None:
    """A copy whose place does not answer stays whatever is pressed; the question says so, and the row goes on Clear.

    **Test steps:**

    * script a failed move whose copy's place does not answer, select it, press Clear, and press Clear
    * check the question offered Clear and Don't Clear, the copy was not removed, and the row was
    """
    job = add_move(rig, jobs, "Move - Intro", JobState.FAILED, PLACE)
    rig.settle()
    answering(mocker, {PLACE: Presence.OFFLINE})
    asked = Asked(mocker, "Clear")
    select_rows(widget, 0)

    ui_of(widget).clear_action.trigger()  # type: ignore[attr-defined]
    wait_for_question(qtbot, asked)

    _, _, buttons, _ = only_question(asked)
    assert buttons == ["Clear", "Don't Clear"]
    job.discard_partial.assert_not_called()
    rig.queue.remove.assert_called_once_with(rig.serial("Move - Intro"))


def test_the_clear_sweeps_ask_about_a_partial_copy_too(
    widget: TaskQueueWidget, rig: Rig, jobs: dict[int, Mock], mocker: MockerFixture, qtbot: QtBot
) -> None:
    """Clear Failed Jobs and Clear All Finished Jobs remove rows too: a move among them with a copy is asked about.

    **Test steps:**

    * script a done job and a failed move with a partial copy
    * trigger Clear Failed Jobs and press Don't Clear, then Clear All and press Remove Partial Copy
    * check the first removed nothing; the second had the move remove its copy and removed both rows
    """
    rig.add("done", JobState.DONE)
    job = add_move(rig, jobs, "Move - Intro", JobState.FAILED, PLACE)
    rig.settle()
    answering(mocker, {})

    refused = Asked(mocker, "Don't Clear")
    ui_of(widget).clear_failed_action.trigger()  # type: ignore[attr-defined]
    wait_for_question(qtbot, refused)
    mocker.stop(refused.exec)
    rig.queue.remove.assert_not_called()

    removed = Asked(mocker, "Remove Partial Copy")
    ui_of(widget).clear_all_action.trigger()  # type: ignore[attr-defined]
    wait_for_question(qtbot, removed)

    job.discard_partial.assert_called_once_with()
    rig.queue.remove.assert_called_once_with(*rig.serials("done", "Move - Intro"))


def test_clearing_with_remove_leaves_a_copy_whose_place_does_not_answer(
    widget: TaskQueueWidget, rig: Rig, jobs: dict[int, Mock], mocker: MockerFixture, qtbot: QtBot
) -> None:
    """Remove reaches only the copies whose place answers: the other stays, as the question said, and both rows go.

    **Test steps:**

    * script two failed moves, one copy's place answering and one not; select both, press Clear and Remove Partial
      Copy
    * check only the first move removed its copy, and both rows were removed
    """
    here = add_move(rig, jobs, "Move - Intro", JobState.FAILED, PLACE)
    away = add_move(rig, jobs, "Move - Basics", JobState.FAILED, OTHER_PLACE)
    rig.settle()
    answering(mocker, {OTHER_PLACE: Presence.OFFLINE})
    asked = Asked(mocker, "Remove Partial Copy")
    select_rows(widget, 0, 1)

    ui_of(widget).clear_action.trigger()  # type: ignore[attr-defined]
    wait_for_question(qtbot, asked)

    here.discard_partial.assert_called_once_with()
    away.discard_partial.assert_not_called()
    rig.queue.remove.assert_called_once_with(*rig.serials("Move - Intro", "Move - Basics"))


# endregion
