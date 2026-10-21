"""Tests for ``PendingSaves``: what each open document is told about its record's save row, and what else the owner
listens to -- the registry, the roots, its own detach (#497).

Driven through :class:`~rehuco_agent_tests.documents.test_pending_saves.Rig`, a scripted queue under the real Tasks
dock model.
"""

from dataclasses import replace
from uuid import uuid4

from PySide6.QtWidgets import QWidget
from pytest import mark
from pytest_mock import MockerFixture
from rehuco_agent.documents import pending_saves as module
from rehuco_agent.documents.pending_saves import SAVE_PENDING_TEXT
from rehuco_core import JobState, RecordVersion

from rehuco_agent_tests.documents.test_pending_saves import (  # noqa: F401  # pylint: disable=unused-import
    EDITS,
    FAIL_REASON,
    KEY,
    OTHER_SOURCE,
    SAVED_BASE,
    SIGNATURE,
    WAIT_REASON,
    Rig,
    a_conflict,
    fixture_parent,
    fixture_rig,
    outcome,
    payload_of,
    save_job,
)

# region what a document is told


def test_a_landed_save_goes_back_to_the_document_that_took_its_snapshot(rig: Rig, parent: QWidget) -> None:
    """The owner of a landed save takes back what it last handed the save, with nothing newer pending.

    **Test steps:**

    * save
    * land the row
    * verify the document completed the save with the job's last hand-over, its outcome and no newer pending save,
      and its banner is empty
    """
    rig.owner.save(parent, rig.model)
    serial = rig.serial_of_save()

    rig.land(serial)

    job = rig.jobs[serial]
    rig.model.complete_save.assert_called_once_with(job.handed, job.result, latest=None)
    assert rig.model.pending_save == ""


def test_a_landed_save_completes_a_document_that_did_not_take_it_but_is_based_on_its_version(
    rig: Rig, mocker: MockerFixture
) -> None:
    """A document opened after a restart takes a landed save as its own when it is based on the version the save
    was snapshotted against -- it shows the save's data, its saved state.

    **Test steps:**

    * restore a queued row of the record snapshotted against a version, and build the owner over it
    * have the document based on that version, and land the row
    * verify the document completed the save with the job's last hand-over and nothing newer, and heard no stat
    """
    serial = rig.add_row(JobState.QUEUED, save_job(mocker, payload_of(base=SAVED_BASE)))
    rig.start()
    rig.model.base_version = SAVED_BASE

    rig.land(serial)

    job = rig.jobs[serial]
    rig.model.complete_save.assert_called_once_with(job.handed, job.result, latest=None)
    rig.model.note_file_signature.assert_not_called()


def test_an_earlier_row_s_landing_completes_its_owner_with_the_newer_save(
    rig: Rig, parent: QWidget, mocker: MockerFixture
) -> None:
    """A save that landed while a newer one of the record was queued goes back to its document all the same, which
    judges its edits against the newer save -- and the newer row keeps the banner.

    **Test steps:**

    * save once, move the row to running, and have it refuse newer data, as one that landed does
    * save again, which queues a second row
    * land the first row
    * verify the document completed the first save with the second row's hand-over as the newer pending save, was
      told of no failure, and its banner names the second row
    """
    mocker.patch.object(module, "rebase_payload", return_value=payload_of({"core": {"title": "Rebased"}}))
    rig.owner.save(parent, rig.model)
    first = rig.serial_of_save()
    rig.land(first, JobState.RUNNING)
    rig.jobs[first].replace.return_value = False
    rig.owner.save(parent, rig.model)
    second = rig.serial_of_save()

    rig.land(first)

    earlier = rig.jobs[first]
    rig.model.complete_save.assert_called_once_with(earlier.handed, earlier.result, latest=rig.jobs[second].handed)
    rig.model.fail_save.assert_not_called()
    assert rig.model.pending_save == SAVE_PENDING_TEXT


def test_a_landed_save_is_a_change_on_disk_to_a_document_based_on_another_version(rig: Rig) -> None:
    """A document opened after a restart whose edits were made against another version of the file hears a landed
    save as any change on disk: a stat.

    **Test steps:**

    * restore a queued row of the record, and build the owner over it
    * have the dirty document based on a version other than the row's, and land the row
    * verify the document was handed the written file's signature and completed nothing
    """
    serial = rig.add_row(JobState.QUEUED)
    rig.start()
    rig.model.base_version = RecordVersion("other", "other", ())

    rig.land(serial)

    rig.model.note_file_signature.assert_called_once_with(*SIGNATURE)
    rig.model.complete_save.assert_not_called()


def test_a_landed_save_without_a_signature_tells_a_clean_document_nothing(rig: Rig, mocker: MockerFixture) -> None:
    """A landed save that could not stat its file says nothing to a clean document that did not take it.

    **Test steps:**

    * restore a queued row of the record whose outcome carries no signature, and build the owner over it
    * make the document clean, and land the row
    * verify the document neither completed a save nor was handed a signature
    """
    job = save_job(mocker)
    job.result = replace(outcome(), signature=None)
    serial = rig.add_row(JobState.QUEUED, job)
    rig.start()
    rig.model.dirty = False

    rig.land(serial)

    rig.model.complete_save.assert_not_called()
    rig.model.note_file_signature.assert_not_called()


def test_a_landed_save_with_no_open_document_tells_nobody(rig: Rig) -> None:
    """A save of a record nobody has open lands with nothing to hand it to.

    **Test steps:**

    * restore a queued row of another record, and build the owner over it
    * land the row
    * verify the open document was told nothing
    """
    serial = rig.add_row(JobState.QUEUED, source=OTHER_SOURCE)
    rig.start()

    rig.land(serial)

    rig.model.complete_save.assert_not_called()
    rig.model.note_file_signature.assert_not_called()


def test_a_failed_save_tells_its_document_why(rig: Rig, parent: QWidget, mocker: MockerFixture) -> None:
    """A failed row hands its document the job's conflict and gone sentence, and its banner names the failure.

    **Test steps:**

    * save, and give the row's job a conflict and a gone sentence
    * fail the row
    * verify the document was told of the failure with both, and its banner reads the failure
    """
    rig.owner.save(parent, rig.model)
    serial = rig.serial_of_save()
    job = rig.jobs[serial]
    job.conflict = a_conflict(mocker)
    job.gone = "The file is gone"

    rig.land(serial, JobState.FAILED, FAIL_REASON)

    rig.model.fail_save.assert_called_once_with(job.conflict, gone="The file is gone")
    assert rig.model.pending_save == f"Save failed: {FAIL_REASON}"


def test_a_cancelled_save_tells_its_document_it_did_not_land(rig: Rig, parent: QWidget) -> None:
    """A cancelled row tells its document its save is over, with no conflict.

    **Test steps:**

    * save, and cancel the row
    * verify the document was told of the failure with no conflict, and its banner is empty
    """
    rig.owner.save(parent, rig.model)

    rig.land(rig.serial_of_save(), JobState.CANCELLED)

    rig.model.fail_save.assert_called_once_with(None)
    assert rig.model.pending_save == ""


@mark.parametrize("state", [JobState.FAILED, JobState.CANCELLED])
def test_a_save_that_did_not_land_with_no_open_document_tells_nobody(rig: Rig, state: JobState) -> None:
    """A save of a record nobody has open fails or is cancelled with nothing to tell.

    **Test steps:**

    * restore a queued row of another record, and build the owner over it
    * fail or cancel the row
    * verify the open document was told nothing
    """
    serial = rig.add_row(JobState.QUEUED, source=OTHER_SOURCE)
    rig.start()

    rig.land(serial, state)

    rig.model.fail_save.assert_not_called()


def test_a_state_already_handled_is_not_handled_again(rig: Rig, parent: QWidget) -> None:
    """A re-snapshot that finds a row where it last was tells its document nothing new.

    **Test steps:**

    * save, and fail the row
    * re-snapshot twice more
    * verify the document was told of the failure once
    """
    rig.owner.save(parent, rig.model)
    rig.land(rig.serial_of_save(), JobState.FAILED, FAIL_REASON)

    rig.settle()
    rig.settle()

    rig.model.fail_save.assert_called_once()


def test_a_row_whose_job_is_gone_tells_its_document_nothing(rig: Rig) -> None:
    """A save row the queue no longer answers a job for is skipped.

    **Test steps:**

    * restore a failed row of the record whose job the queue does not answer, and build the owner over it
    * verify the document was told nothing, its banner untouched
    """
    rig.add_row(JobState.FAILED, object(), message=FAIL_REASON)

    rig.start()

    rig.model.fail_save.assert_not_called()
    assert rig.model.pending_save == ""


def test_rows_of_other_kinds_or_with_no_source_are_ignored(rig: Rig) -> None:
    """Only save rows with a record are a document's concern.

    **Test steps:**

    * restore a failed row of another kind on the record, and a failed save row with no source
    * build the owner over them
    * verify neither is the record's row, and the document was told nothing
    """
    other_kind = rig.add_row(JobState.FAILED, kind="verify-checksums")
    no_source = rig.add_row(JobState.FAILED, source=None)

    assert rig.owner.key_of(other_kind) is None
    assert rig.owner.key_of(no_source) is None
    rig.model.fail_save.assert_not_called()


def test_a_restored_save_row_is_found_by_kind_and_source(rig: Rig) -> None:
    """A row restored from the saved queue is the record's, so a document opened after a restart hears of it.

    **Test steps:**

    * restore a waiting save row of the record, and build the owner over it
    * verify the row is the record's, and the open document's banner names the wait
    """
    serial = rig.add_row(JobState.WAITING, message=WAIT_REASON)

    assert rig.owner.key_of(serial) == KEY
    assert rig.model.pending_save == f"Save waiting: {WAIT_REASON}"


def test_an_earlier_landed_row_of_the_record_is_not_its_row(rig: Rig) -> None:
    """Two rows of one record -- an earlier landed save and a newer one -- leave the newer as the record's row and
    its banner; the earlier one's landing is heard all the same, as a change on disk by a document based on another
    version.

    **Test steps:**

    * restore a landed save row of the record, then a queued one, and build the owner over both
    * verify the newer row is the record's, the banner names it, the earlier landing reached the document as a stat,
      and nothing was completed
    """
    earlier = rig.add_row(JobState.DONE)
    newer = rig.add_row(JobState.QUEUED)

    assert rig.owner.key_of(newer) == KEY
    assert rig.owner.key_of(earlier) is None
    rig.model.complete_save.assert_not_called()
    rig.model.note_file_signature.assert_called_once_with(*SIGNATURE)
    assert rig.model.pending_save == SAVE_PENDING_TEXT


@mark.parametrize("missing", ["result", "handed"])
def test_a_landed_save_with_nothing_to_hand_back_tells_the_document_nothing(
    rig: Rig, mocker: MockerFixture, missing: str
) -> None:
    """A landed row whose job reports no outcome, or was never handed a Save, has nothing to give its document.

    **Test steps:**

    * restore a queued row of the record whose job has no outcome, or no hand-over, and build the owner over it
    * have the document based on the save's version, and land the row
    * verify the document neither completed a save nor was handed a signature
    """
    job = save_job(mocker)
    setattr(job, missing, None)
    serial = rig.add_row(JobState.QUEUED, job)
    rig.start()
    rig.model.base_version = None

    rig.land(serial)

    rig.model.complete_save.assert_not_called()
    rig.model.note_file_signature.assert_not_called()


@mark.parametrize("saved_on_disk", [True, False])
def test_a_removed_row_that_had_not_landed_is_a_drop(rig: Rig, parent: QWidget, saved_on_disk: bool) -> None:
    """A row that left the queue before landing is the borrow's Drop: the save is over, what it failed on goes, and
    the document goes back to its file -- or, never written, keeps what it holds as unsaved edits.

    **Test steps:**

    * save, wait the row, and leave the document clean, in conflict and gone; saved on disk, or never written
    * remove the row from the queue
    * verify the row is no longer the record's, the banner is empty, the document was told its save is over, its
      conflict and gone sentence cleared, and it reverted -- or, never written, was left dirty instead
    * edit the document again, and verify the next Save queues a new job
    """
    rig.owner.save(parent, rig.model)
    serial = rig.serial_of_save()
    rig.land(serial, JobState.WAITING, WAIT_REASON)
    rig.model.dirty = False
    rig.model.saved_on_disk = saved_on_disk
    rig.model.conflict = object()
    rig.model.gone = "The file is gone"

    rig.queue.remove(serial)
    rig.settle()

    assert rig.owner.key_of(serial) is None
    assert rig.model.pending_save == ""
    rig.model.fail_save.assert_called_once_with(None)
    assert rig.model.conflict is None
    assert rig.model.gone == ""
    assert rig.model.revert.called is saved_on_disk
    assert rig.model.dirty is not saved_on_disk
    rig.model.dirty = True
    rig.owner.save(parent, rig.model)
    assert len(rig.enqueued) == 2


def test_a_removed_landed_row_tells_its_document_only_the_banner(rig: Rig, parent: QWidget) -> None:
    """A landed save cleared from the dock is history: its banner clears, and nothing the document holds goes.

    **Test steps:**

    * save, land the row, and give the document a banner and a clean state again
    * remove the row
    * verify the banner is empty, and the document was told of no failure, not reverted, and left clean
    """
    rig.owner.save(parent, rig.model)
    serial = rig.serial_of_save()
    rig.land(serial)
    rig.model.pending_save = "stale"
    rig.model.dirty = False

    rig.queue.remove(serial)
    rig.settle()

    assert rig.owner.key_of(serial) is None
    assert rig.model.pending_save == ""
    rig.model.fail_save.assert_not_called()
    rig.model.revert.assert_not_called()
    assert rig.model.dirty is False


def test_a_removed_row_with_no_open_document_is_forgotten(rig: Rig) -> None:
    """A removed save row of a record nobody has open is forgotten with nothing to tell.

    **Test steps:**

    * restore a queued row of another record, and build the owner over it
    * remove the row
    * verify it is no longer any record's row
    """
    serial = rig.add_row(JobState.QUEUED, source=OTHER_SOURCE)
    rig.start()

    rig.queue.remove(serial)
    rig.settle()

    assert rig.owner.key_of(serial) is None


def test_a_removed_earlier_row_of_the_record_is_forgotten_quietly(rig: Rig, parent: QWidget) -> None:
    """Removing a landed row the record has a newer save after leaves the newer one, and the document, alone.

    **Test steps:**

    * save and land the row, then save again
    * remove the landed row
    * verify the newer row is still the record's, and the banner still names it
    """
    rig.owner.save(parent, rig.model)
    first = rig.serial_of_save()
    rig.land(first)
    rig.owner.save(parent, rig.model)
    second = rig.serial_of_save()
    rig.settle()

    rig.queue.remove(first)
    rig.settle()

    assert rig.owner.key_of(second) == KEY
    assert rig.model.pending_save == SAVE_PENDING_TEXT
    rig.model.fail_save.assert_not_called()


# endregion

# region the owner's other ears


def test_a_document_just_opened_hears_of_its_pending_save(rig: Rig) -> None:
    """A document opened while its record's save waits is told so at once.

    **Test steps:**

    * restore a waiting save row of the record, build the owner, and clear the document's banner
    * hand the owner the document as the registry would on opening it
    * verify its banner names the wait
    """
    rig.add_row(JobState.WAITING, message=WAIT_REASON)
    rig.start()
    rig.model.pending_save = ""

    (on_acquired,) = rig.registry.model_acquired.connect.call_args.args
    on_acquired(rig.model)

    assert rig.model.pending_save == f"Save waiting: {WAIT_REASON}"


def test_a_document_just_opened_hears_what_its_failed_save_found(rig: Rig, mocker: MockerFixture) -> None:
    """A document opened while its record's save is failed is told the failure's conflict and gone sentence, so
    its Save shows the differences, and its banner names the failure.

    **Test steps:**

    * restore a failed save row of the record whose job holds a conflict and a gone sentence, build the owner, and
      forget what the document was told meanwhile
    * hand the owner the document as the registry would on opening it
    * verify the document was told of the failure with both, and its banner reads the failure
    """
    job = save_job(mocker)
    job.conflict = a_conflict(mocker)
    job.gone = "The file is gone"
    rig.add_row(JobState.FAILED, job, message=FAIL_REASON)
    rig.start()
    rig.model.fail_save.reset_mock()
    rig.model.pending_save = ""

    (on_acquired,) = rig.registry.model_acquired.connect.call_args.args
    on_acquired(rig.model)

    rig.model.fail_save.assert_called_once_with(job.conflict, gone="The file is gone")
    assert rig.model.pending_save == f"Save failed: {FAIL_REASON}"


@mark.parametrize("keyed", [True, False])
def test_a_document_just_opened_with_no_pending_save_hears_nothing(rig: Rig, keyed: bool) -> None:
    """A document opened with no save row of its record -- or with no record at all -- is told nothing.

    **Test steps:**

    * build the owner over an empty queue; give the document no key, or keep its own
    * hand the owner the document as the registry would on opening it
    * verify its banner is untouched
    """
    rig.start()
    rig.model.pending_save = "untouched"
    if not keyed:
        rig.model.key = None

    (on_acquired,) = rig.registry.model_acquired.connect.call_args.args
    on_acquired(rig.model)

    assert rig.model.pending_save == "untouched"


def test_a_root_answering_again_tries_every_waiting_save(rig: Rig) -> None:
    """A root becoming reachable puts every waiting save back in line at once, and nothing else.

    **Test steps:**

    * restore a waiting save, a queued save and a waiting row of another kind, and build the owner
    * announce a root reachable
    * verify only the waiting save was resumed
    """
    waiting = rig.add_row(JobState.WAITING, message=WAIT_REASON)
    rig.add_row(JobState.QUEUED, source=OTHER_SOURCE)
    rig.add_row(JobState.WAITING, kind="verify-checksums")
    rig.start()

    rig.events.root_reachable.emit(uuid4(), True)

    rig.queue.resume_job.assert_called_once_with(waiting)


def test_a_root_going_unreachable_tries_nothing(rig: Rig) -> None:
    """A root that stopped answering resumes nothing.

    **Test steps:**

    * restore a waiting save, and build the owner
    * announce a root unreachable
    * verify nothing was resumed
    """
    rig.add_row(JobState.WAITING, message=WAIT_REASON)
    rig.start()

    rig.events.root_reachable.emit(uuid4(), False)

    rig.queue.resume_job.assert_not_called()


def test_a_detached_owner_hears_nothing_more(rig: Rig, parent: QWidget) -> None:
    """Once detached, before the queue shuts down, a row's change reaches no document.

    **Test steps:**

    * save, then detach the owner
    * fail the row, and announce a root reachable
    * verify the document was told nothing, the registry's signal was let go, and nothing was resumed
    """
    rig.owner.save(parent, rig.model)
    serial = rig.serial_of_save()
    rig.owner.detach()

    rig.land(serial, JobState.FAILED, FAIL_REASON)
    rig.set_state(serial, JobState.WAITING, WAIT_REASON)
    rig.events.root_reachable.emit(uuid4(), True)

    rig.model.fail_save.assert_not_called()
    rig.registry.model_acquired.disconnect.assert_called_once()
    rig.queue.resume_job.assert_not_called()


def test_detaching_twice_lets_go_once(rig: Rig) -> None:
    """A window closed twice detaches its save owner once: the second call disconnects nothing.

    **Test steps:**

    * detach the owner twice
    * verify the registry's signal was let go exactly once
    """
    rig.owner.detach()
    rig.owner.detach()

    rig.registry.model_acquired.disconnect.assert_called_once()


# endregion
