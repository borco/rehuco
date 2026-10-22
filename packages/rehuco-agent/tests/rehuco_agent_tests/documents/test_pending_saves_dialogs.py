"""Tests for ``PendingSaves``' questions: the differences shown before a save of a changed file, the Tasks dock's
*Inspect* and *Discard*, and the wait a close or a quit makes for a save to land (#497).

Driven through :class:`~rehuco_agent_tests.documents.test_pending_saves.Rig`, a scripted queue under the real Tasks
dock model. No dialog is shown: the conflict question, the message boxes and the progress dialog are patched.
"""

from collections.abc import Callable
from typing import Any, Final

from PySide6.QtWidgets import QMessageBox, QWidget
from pytest import fixture, mark
from pytest_mock import MockerFixture
from rehuco_agent.dialogs.record_conflict_dialog import ConflictResolution
from rehuco_agent.documents import pending_saves as module
from rehuco_core import JobState

from rehuco_agent_tests.documents.test_pending_saves import (  # noqa: F401  # pylint: disable=unused-import
    FAIL_REASON,
    OTHER_SOURCE,
    WAIT_REASON,
    Rig,
    a_conflict,
    fixture_parent,
    fixture_rig,
    payload_of,
)

KEPT: Final = {("core", "title"): "Kept"}
"""What the person keeps in the conflict dialog."""

BUTTONS: Final = QMessageBox.StandardButton


@fixture(name="ask")
def fixture_ask(mocker: MockerFixture) -> Any:
    """The conflict question, answering *Save* with :data:`KEPT` unless a test says otherwise.

    :param mocker: pytest-mock fixture.
    :returns: the patched question.
    """
    return mocker.patch.object(module, "ask_about_conflict", return_value=(ConflictResolution.SAVE, KEPT))


@fixture(autouse=True)
def no_unexpected_question(mocker: MockerFixture) -> None:
    """Fail a test at once when a message box it did not script is shown, rather than block on a real modal.

    :param mocker: pytest-mock fixture.
    """

    def refuse(box: QMessageBox) -> int:
        """Refuse to show a question no test answers.

        :param box: the question.
        :raises AssertionError: always.
        """
        raise AssertionError(f"unexpected question: {box.text()}")

    mocker.patch.object(QMessageBox, "exec", refuse)


# region the differences first


def test_a_save_of_a_conflicted_document_shows_the_differences_and_saves_what_was_kept(
    rig: Rig, parent: QWidget, mocker: MockerFixture, ask: Any
) -> None:
    """A document whose last save was refused shows what differs before anything is queued -- the file as the refused
    save read it, never read again here (#564).

    **Test steps:**

    * mark the document conflicted
    * save, answering *Save* in the dialog
    * verify the file was not read, the dialog was asked about the refusal's own file, the kept values were taken, and
      the edits were queued
    """
    conflict = a_conflict(mocker)
    rig.model.conflict = conflict

    assert rig.owner.save(parent, rig.model) is True

    rig.records.load.assert_not_called()
    ask.assert_called_once_with(parent, rig.model, conflict)
    rig.model.resolve_conflict.assert_called_once_with(KEPT)
    assert len(rig.enqueued) == 1


@mark.parametrize("with_row", [True, False])
def test_discarding_in_the_differences_reverts_and_drops_the_pending_save(
    rig: Rig, parent: QWidget, mocker: MockerFixture, ask: Any, with_row: bool
) -> None:
    """Discarding the edits in the dialog drops the record's save, if it has one -- the borrow's Drop, which reads
    the file back -- or reads the file back itself when there is none.

    **Test steps:**

    * save once (or not), then mark the document conflicted
    * save, answering *Discard*, the revert leaving the document clean
    * verify the document reverted once, nothing more was queued, and ``True`` came back
    * with a row: verify it was removed, the banner cleared, and the document told its save is over
    """
    if with_row:
        rig.owner.save(parent, rig.model)
        rig.model.pending_save = "Save pending"
    serial = rig.serial_of_save() if with_row else None
    rig.model.conflict = a_conflict(mocker)
    ask.return_value = (ConflictResolution.DISCARD, {})
    rig.model.revert.side_effect = lambda: setattr(rig.model, "dirty", False)

    assert rig.owner.save(parent, rig.model) is True

    rig.model.revert.assert_called_once_with()
    if serial is None:
        rig.queue.remove.assert_not_called()
        rig.model.fail_save.assert_not_called()
    else:
        rig.queue.remove.assert_called_once_with(serial)
        assert rig.owner.key_of(serial) is None
        assert rig.model.pending_save == ""
        rig.model.fail_save.assert_called_once_with(None)
    assert len(rig.enqueued) == (1 if with_row else 0)


def test_cancelling_the_differences_saves_nothing(rig: Rig, parent: QWidget, mocker: MockerFixture, ask: Any) -> None:
    """Cancelling the dialog leaves the edits unsaved and says so.

    **Test steps:**

    * mark the document conflicted
    * save, answering *Cancel*
    * verify ``False`` came back and nothing was queued
    """
    rig.model.conflict = a_conflict(mocker)
    ask.return_value = (ConflictResolution.CANCEL, {})

    assert rig.owner.save(parent, rig.model) is False

    assert not rig.enqueued
    rig.model.resolve_conflict.assert_not_called()


def test_a_change_heard_on_disk_alone_is_the_saves_to_judge(rig: Rig, parent: QWidget, ask: Any) -> None:
    """A file changed on disk under the edits, with no save refused yet, is saved without a question or a read: the
    save's own check merges the change or refuses it as a conflict ([[sync#unlanded-save]], #564).

    **Test steps:**

    * hear a change on disk
    * save
    * verify no dialog was shown, the file was not read, and the edits were queued
    """
    rig.model.changed_on_disk = True

    assert rig.owner.save(parent, rig.model) is True

    ask.assert_not_called()
    rig.records.load.assert_not_called()
    assert len(rig.enqueued) == 1


# endregion

# region inspect


def test_inspecting_a_restored_save_saves_it_again_as_the_document_was_opened(rig: Rig, parent: QWidget) -> None:
    """*Inspect* takes the document as opening made it -- showing the save's data already -- and saves it again,
    reading and adopting nothing itself.

    **Test steps:**

    * restore a queued save row of the record, and build the owner over it
    * inspect the row with the document
    * verify the file was not read, nothing was adopted or failed, and the edits went back to the row
    """
    serial = rig.add_row(JobState.QUEUED)
    rig.start()

    rig.owner.inspect(parent, serial, rig.model)

    rig.records.load.assert_not_called()
    rig.model.adopt_unsaved.assert_not_called()
    rig.model.fail_save.assert_not_called()
    rig.jobs[serial].replace.assert_called_once_with(payload_of())


def test_inspecting_a_conflicted_save_raises_its_conflict_in_the_document_and_saves(
    rig: Rig, parent: QWidget, mocker: MockerFixture, ask: Any
) -> None:
    """*Inspect* of a save refused as a conflict shows the document in conflict -- so the differences -- and saves
    what was kept.

    **Test steps:**

    * restore a failed save row of the record carrying a conflict and a gone sentence, and build the owner over it
    * forget what the open document was told of the failure as the owner was built
    * inspect the row, the document taking the conflict it is told of
    * verify the document was told of the job's conflict and gone sentence, the dialog was asked, the kept values
      taken, and the failed row handed the edits and retried
    """
    serial = rig.add_row(JobState.FAILED, message=FAIL_REASON)
    job = rig.jobs[serial]
    job.conflict = a_conflict(mocker)
    job.gone = "The file is gone"
    rig.start()
    rig.model.fail_save.reset_mock()
    rig.model.fail_save.side_effect = lambda conflict, gone: setattr(rig.model, "conflict", conflict)

    rig.owner.inspect(parent, serial, rig.model)

    rig.model.fail_save.assert_called_once_with(job.conflict, gone="The file is gone")
    ask.assert_called_once()
    rig.model.resolve_conflict.assert_called_once_with(KEPT)
    job.replace.assert_called_once_with(payload_of())
    rig.queue.retry.assert_called_once_with(serial)


def test_inspecting_its_own_save_adopts_nothing(rig: Rig, parent: QWidget) -> None:
    """*Inspect* of a save the document itself made leaves its edits as they are, and saves them again.

    **Test steps:**

    * save
    * inspect the row with the same document
    * verify the file was not read, nothing was adopted, and the row's job took the edits again
    """
    rig.owner.save(parent, rig.model)
    serial = rig.serial_of_save()

    rig.owner.inspect(parent, serial, rig.model)

    rig.records.load.assert_not_called()
    rig.model.adopt_unsaved.assert_not_called()
    rig.jobs[serial].replace.assert_called_once_with(payload_of())


def test_inspecting_with_a_document_with_no_record_reads_nothing(rig: Rig, parent: QWidget) -> None:
    """A document with no record to read adopts nothing, and becomes the row's document all the same.

    **Test steps:**

    * restore a queued save row of the record, build the owner, and take the document's key away
    * inspect the row with the document
    * verify the file was not read and nothing was adopted
    """
    serial = rig.add_row(JobState.QUEUED)
    rig.start()
    rig.model.key = None
    rig.model.dirty = False

    rig.owner.inspect(parent, serial, rig.model)

    rig.records.load.assert_not_called()
    rig.model.adopt_unsaved.assert_not_called()


def test_inspecting_a_row_whose_job_is_no_save_does_nothing(rig: Rig, parent: QWidget) -> None:
    """A row whose job is no save has nothing to inspect.

    **Test steps:**

    * restore a save row whose job the queue does not answer as a save
    * inspect it
    * verify nothing was read, adopted, saved or queued
    """
    serial = rig.add_row(JobState.QUEUED, object())
    rig.start()

    rig.owner.inspect(parent, serial, rig.model)

    rig.records.load.assert_not_called()
    rig.model.adopt_unsaved.assert_not_called()
    rig.model.snapshot.assert_not_called()
    assert not rig.enqueued


# endregion

# region discard


@mark.parametrize("saved_on_disk", [True, False])
def test_discarding_a_save_drops_it_and_reverts_its_saved_document(
    rig: Rig, parent: QWidget, mocker: MockerFixture, saved_on_disk: bool
) -> None:
    """*Discard*, confirmed, removes the row; its open document goes back to its file -- if it has ever had one.

    **Test steps:**

    * save; make the document clean, and one saved on disk, or a never-saved one
    * discard the row, answering *Yes*
    * verify the question named one save, the row was removed, the banner cleared, the document told its save is
      over, and reverted only when it has a file -- left dirty when it has none
    """
    question = mocker.patch.object(QMessageBox, "question", return_value=BUTTONS.Yes)
    rig.owner.save(parent, rig.model)
    serial = rig.serial_of_save()
    rig.model.saved_on_disk = saved_on_disk
    rig.model.dirty = False
    rig.model.pending_save = "Save pending"

    rig.owner.discard(parent, [serial])

    (_, title, text) = question.call_args.args
    assert title == "Discard Saves"
    assert text.startswith("Discard 1 pending save? The edits it holds are lost")
    rig.queue.remove.assert_called_once_with(serial)
    assert rig.model.pending_save == ""
    rig.model.fail_save.assert_called_once_with(None)
    assert rig.model.revert.called is saved_on_disk
    assert rig.model.dirty is not saved_on_disk


@mark.parametrize("state", [JobState.RUNNING, JobState.DONE, JobState.CANCELLED])
def test_discarding_a_save_that_is_writing_or_settled_asks_nothing_and_drops_nothing(
    rig: Rig, parent: QWidget, mocker: MockerFixture, state: JobState
) -> None:
    """*Discard* on a save that is writing does nothing -- its write cannot be stopped, so dropping the row would
    only hide a save that lands anyway -- nor on one that landed or was cancelled, which is no pending save.

    **Test steps:**

    * save, and have the row writing, landed or cancelled
    * discard it
    * verify no question was asked, nothing was removed, and the document was not reverted
    """
    question = mocker.patch.object(QMessageBox, "question", return_value=BUTTONS.Yes)
    rig.owner.save(parent, rig.model)
    serial = rig.serial_of_save()
    rig.set_state(serial, state)

    rig.owner.discard(parent, [serial])

    question.assert_not_called()
    rig.queue.remove.assert_not_called()
    rig.model.revert.assert_not_called()


def test_discarding_several_saves_asks_once_for_all(rig: Rig, parent: QWidget, mocker: MockerFixture) -> None:
    """*Discard* of several rows asks once, in the plural, and drops them all -- an unopened record's too.

    **Test steps:**

    * restore a save row of the record and one of a record nobody has open, and build the owner
    * discard both, answering *Yes*
    * verify the question named two saves, and both rows were removed
    """
    question = mocker.patch.object(QMessageBox, "question", return_value=BUTTONS.Yes)
    mine = rig.add_row(JobState.WAITING, message=WAIT_REASON)
    other = rig.add_row(JobState.FAILED, source=OTHER_SOURCE)
    rig.start()

    rig.owner.discard(parent, [mine, other])

    (_, _, text) = question.call_args.args
    assert text.startswith("Discard 2 pending saves? The edits they hold are lost")
    rig.queue.remove.assert_called_once_with(mine, other)


def test_discarding_refused_keeps_every_save(rig: Rig, parent: QWidget, mocker: MockerFixture) -> None:
    """Answering *No* to *Discard* drops nothing.

    **Test steps:**

    * save, then discard the row, answering *No*
    * verify nothing was removed and the document was not reverted
    """
    mocker.patch.object(QMessageBox, "question", return_value=BUTTONS.No)
    rig.owner.save(parent, rig.model)

    rig.owner.discard(parent, [rig.serial_of_save()])

    rig.queue.remove.assert_not_called()
    rig.model.revert.assert_not_called()


def test_discarding_rows_that_are_no_saves_asks_nothing(rig: Rig, parent: QWidget, mocker: MockerFixture) -> None:
    """*Discard* of rows no record is known by asks no question.

    **Test steps:**

    * build the owner over an empty queue
    * discard a serial it does not know
    * verify no question was asked and nothing removed
    """
    question = mocker.patch.object(QMessageBox, "question")

    rig.owner.discard(parent, [42])

    question.assert_not_called()
    rig.queue.remove.assert_not_called()


# endregion

# region save and wait


def patch_wait(mocker: MockerFixture, steps: list[Callable[[], None]]) -> tuple[Any, Any]:
    """Patch the progress dialog and its event loop, each run of the loop playing the next of ``steps``.

    :param mocker: pytest-mock fixture.
    :param steps: what happens while each wait runs.
    :returns: the patched dialog class and loop class.
    """
    dialog_class = mocker.patch.object(module, "QProgressDialog")
    loop_class = mocker.patch.object(module, "QEventLoop")

    def run() -> int:
        """Play the next step.

        :returns: the loop's exit code.
        """
        steps.pop(0)()
        return 0

    loop_class.return_value.exec.side_effect = run
    return dialog_class, loop_class


def patch_answers(mocker: MockerFixture, answers: list[QMessageBox.StandardButton]) -> list[tuple[str, str, str]]:
    """Patch the *Save Not Landed* question to answer each of ``answers`` in turn.

    :param mocker: pytest-mock fixture.
    :param answers: the answers.
    :returns: each question's text and its two renamed buttons' texts, as asked.
    """
    asked: list[tuple[str, str, str]] = []

    def answer(box: QMessageBox) -> int:
        """Note the question and answer it.

        :param box: the question.
        :returns: the next answer.
        """
        asked.append((box.text(), box.button(BUTTONS.Retry).text(), box.button(BUTTONS.Ignore).text()))
        return answers.pop(0).value

    mocker.patch.object(QMessageBox, "exec", answer)
    return asked


def test_save_and_wait_answers_true_once_the_save_lands(rig: Rig, parent: QWidget, mocker: MockerFixture) -> None:
    """A close's save waits behind a progress dialog until its row lands, through a write still under way.

    **Test steps:**

    * patch the wait: the row first starts writing, then lands
    * save and wait
    * verify ``True`` came back, the dialog said what it saves, the loop was left only once the row landed, and the
      dialog went
    """
    dialog_class, loop_class = patch_wait(mocker, [])
    loop = loop_class.return_value
    quits_while_running: list[int] = []

    def write_then_land() -> None:
        """Start the write, note whether the wait ended, then land it."""
        rig.land(rig.serial_of_save(), JobState.RUNNING)
        quits_while_running.append(loop.quit.call_count)
        rig.land(rig.serial_of_save())

    loop.exec.side_effect = write_then_land

    assert rig.owner.save_and_wait(parent, rig.model) is True

    assert quits_while_running == [0]
    loop.quit.assert_called_once_with()
    (text, cancel, _, _, owner) = dialog_class.call_args.args
    assert (text, cancel, owner) == ("Saving res…", "Cancel", parent)
    dialog = dialog_class.return_value
    dialog.setWindowTitle.assert_called_once_with("Saving")
    dialog.deleteLater.assert_called_once_with()


def test_save_and_wait_with_nothing_to_wait_for_answers_at_once(
    rig: Rig, parent: QWidget, mocker: MockerFixture
) -> None:
    """A document with nothing to save, or one whose save is refused, waits for nothing.

    **Test steps:**

    * patch the progress dialog
    * save and wait a clean document, then a gone one
    * verify ``True`` then ``False`` came back, and no dialog was built
    """
    dialog_class, _ = patch_wait(mocker, [])
    rig.model.dirty = False

    assert rig.owner.save_and_wait(parent, rig.model) is True

    rig.model.gone = "The file is gone"
    assert rig.owner.save_and_wait(parent, rig.model) is False
    dialog_class.assert_not_called()


def test_save_and_wait_shows_a_conflict_and_saves_what_was_kept(
    rig: Rig, parent: QWidget, mocker: MockerFixture, ask: Any
) -> None:
    """A wait whose save is refused as a conflict shows the differences, then saves again with what was kept.

    **Test steps:**

    * patch the wait: the row fails as a conflict, then -- saved again -- lands
    * have resolving clear the conflict
    * save and wait
    * verify the dialog was asked once, the failed row was retried with the kept data, and ``True`` came back
    """
    conflict = a_conflict(mocker)
    rig.model.resolve_conflict.side_effect = lambda values: setattr(rig.model, "conflict", None)

    def refuse() -> None:
        """Fail the row as a conflict."""
        rig.model.conflict = conflict
        rig.land(rig.serial_of_save(), JobState.FAILED, "RecordConflict: changed")

    patch_wait(mocker, [refuse, lambda: rig.land(rig.serial_of_save())])

    assert rig.owner.save_and_wait(parent, rig.model) is True

    ask.assert_called_once()
    rig.model.resolve_conflict.assert_called_once_with(KEPT)
    rig.queue.retry.assert_called_once_with(rig.serial_of_save())
    assert len(rig.enqueued) == 1


def test_save_and_wait_of_a_record_gone_meanwhile_stops(rig: Rig, parent: QWidget, mocker: MockerFixture) -> None:
    """A wait whose save fails because the record went stops the caller, asking nothing.

    **Test steps:**

    * patch the wait: the record goes and the row fails
    * save and wait
    * verify ``False`` came back and no question was asked
    """
    asked = patch_answers(mocker, [])

    def go() -> None:
        """Lose the record and fail the row."""
        rig.model.gone = "The file is gone"
        rig.land(rig.serial_of_save(), JobState.FAILED, FAIL_REASON)

    patch_wait(mocker, [go])

    assert rig.owner.save_and_wait(parent, rig.model) is False

    assert not asked


@mark.parametrize(
    ("answer", "result"), [(BUTTONS.Ignore, True), (BUTTONS.Cancel, False)], ids=["leave-it-pending", "cancel"]
)
def test_a_save_that_cannot_land_asks_what_to_do(
    rig: Rig, parent: QWidget, mocker: MockerFixture, answer: QMessageBox.StandardButton, result: bool
) -> None:
    """A save that waits asks: leaving it pending lets the caller go on, cancelling stops it.

    **Test steps:**

    * patch the wait: the row waits for its share
    * save and wait, answering *Leave It Pending* or *Cancel*
    * verify the question named the document and the wait, its buttons were renamed, and the answer came back
    """
    asked = patch_answers(mocker, [answer])
    patch_wait(mocker, [lambda: rig.land(rig.serial_of_save(), JobState.WAITING, WAIT_REASON)])

    assert rig.owner.save_and_wait(parent, rig.model) is result

    assert asked == [(f'Could not save "res": {WAIT_REASON}', "Try Again", "Leave It Pending")]


def test_try_again_saves_once_more(rig: Rig, parent: QWidget, mocker: MockerFixture) -> None:
    """*Try Again* hands the waiting row the edits again and puts it back in line, then asks again if it still waits.

    **Test steps:**

    * patch the wait: the row waits for its share
    * save and wait, answering *Try Again*, then -- the row waiting still, so nothing to wait through -- *Leave It
      Pending*
    * verify the question was asked twice, the row was handed the edits again and resumed, and the wait ran once
    """
    asked = patch_answers(mocker, [BUTTONS.Retry, BUTTONS.Ignore])
    _, loop_class = patch_wait(mocker, [lambda: rig.land(rig.serial_of_save(), JobState.WAITING, WAIT_REASON)])

    assert rig.owner.save_and_wait(parent, rig.model) is True

    assert [text for text, _, _ in asked] == [f'Could not save "res": {WAIT_REASON}'] * 2
    serial = rig.serial_of_save()
    rig.jobs[serial].replace.assert_called_once_with(payload_of())
    rig.queue.resume_job.assert_called_once_with(serial)
    loop_class.return_value.exec.assert_called_once_with()


def test_a_save_failed_for_no_given_reason_names_its_state(rig: Rig, parent: QWidget, mocker: MockerFixture) -> None:
    """A save that failed with no message is named by its state in the question.

    **Test steps:**

    * patch the wait: the row fails with no reason given
    * save and wait, answering *Cancel*
    * verify the question named the state, and ``False`` came back
    """
    asked = patch_answers(mocker, [BUTTONS.Cancel])
    patch_wait(mocker, [lambda: rig.land(rig.serial_of_save(), JobState.FAILED)])

    assert rig.owner.save_and_wait(parent, rig.model) is False

    assert [text for text, _, _ in asked] == ['Could not save "res": failed']


def test_cancelling_the_progress_stops_the_caller_and_leaves_the_row(
    rig: Rig, parent: QWidget, mocker: MockerFixture
) -> None:
    """*Cancel* on the progress dialog stops waiting; the row stays where it is.

    **Test steps:**

    * patch the wait: the dialog's Cancel is pressed
    * save and wait
    * verify ``False`` came back, and the row was neither cancelled nor removed
    """
    steps: list[Callable[[], None]] = []
    dialog_class, _ = patch_wait(mocker, steps)

    def press_cancel() -> None:
        """Press the dialog's Cancel."""
        (on_cancel,) = dialog_class.return_value.canceled.connect.call_args.args
        on_cancel()

    steps.append(press_cancel)

    assert rig.owner.save_and_wait(parent, rig.model) is False

    rig.queue.cancel.assert_not_called()
    rig.queue.remove.assert_not_called()
    assert rig.statuses[rig.serial_of_save()].state is JobState.QUEUED


# endregion
