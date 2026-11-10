"""Tests for RecordMoves (#339): which move a click on a root's place makes -- a rename at once, or a task -- and how
a task's end reaches the document's banner."""

from pathlib import Path, PurePosixPath
from typing import Final
from unittest.mock import MagicMock, Mock
from uuid import UUID

from PySide6.QtCore import QCoreApplication
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.name_suggestion_model import RootDestination
from rehuco_agent.documents.record_moves import RecordMoves
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.settings.move_settings import shared_move_settings
from rehuco_core import (
    RECORD_MOVE_KIND,
    JobOutcome,
    JobState,
    JobStatus,
    MoveMode,
    MoveRecordJob,
    RootStorage,
    TaskQueue,
)

MODULE: Final = "rehuco_agent.documents.record_moves"
ROOT: Final = Path(Path.cwd().anchor) / "tutorials"
ARCHIVE: Final = Path(Path.cwd().anchor) / "archive"
RECORD: Final = ROOT / "Old" / "Foo" / "info.rehu"
ROOT_ID: Final = UUID("00000000-0000-0000-0000-000000000001")
ARCHIVE_ID: Final = UUID("00000000-0000-0000-0000-000000000002")
PLACE: Final = RootDestination("Archive", PurePosixPath("Jane/Foo"), ARCHIVE, ARCHIVE_ID, False, ROOT, ROOT_ID)
SERIAL: Final = 7


@fixture(name="model")
def fixture_model() -> Mock:
    """A document at :data:`RECORD`, ready to move.

    :returns: it.
    """
    model = Mock(spec=RehuDocumentModel)
    model.path = RECORD
    model.current_name = "Foo"
    model.label = "Foo"
    model.loading = False
    model.prepare_move.return_value = True
    return model


@fixture(name="queue")
def fixture_queue() -> Mock:
    """An empty queue, handing out :data:`SERIAL`.

    :returns: it.
    """
    queue = Mock(spec=TaskQueue)
    queue.jobs.return_value = ()
    queue.enqueue.return_value = SERIAL
    return queue


@fixture(name="job_class")
def fixture_job_class(mocker: MockerFixture) -> MagicMock:
    """The move job, its instances stand-ins reading as a move of :data:`RECORD`.

    :param mocker: pytest-mock fixture.
    :returns: the patched class.
    """
    job_class = mocker.patch(f"{MODULE}.MoveRecordJob")
    job_class.return_value.label = "Move to Archive: Jane/Foo - Foo"
    job_class.return_value.source = RECORD
    job_class.return_value.outcome = None
    return job_class


def volume(mocker: MockerFixture, *, same: bool, storage: RootStorage = RootStorage.LOCAL) -> None:
    """Say whether the place is on the record's volume, and what that volume is.

    :param mocker: pytest-mock fixture.
    :param same: whether moving there is a rename.
    :param storage: the place's storage.
    """
    mocker.patch(f"{MODULE}.same_volume", return_value=same)
    mocker.patch(f"{MODULE}.storage_of", return_value=storage)


# region which move
def test_a_rename_with_no_verify_asked_runs_at_once(
    qtbot: QtBot, model: Mock, queue: Mock, job_class: MagicMock, mocker: MockerFixture
) -> None:
    """On one local volume, with *on a local disk* off, the move is a rename, here and now, to the record's root.

    **Test steps:**

    * make the place on the record's local volume, and move there
    * check the model moved into ``Jane`` as ``Foo``, its own root given, and nothing was queued
    """
    del qtbot
    volume(mocker, same=True)

    RecordMoves(model, queue).move(PLACE)

    model.move_in_root.assert_called_once_with(ARCHIVE / "Jane", "Foo", ROOT)
    job_class.assert_not_called()
    queue.enqueue.assert_not_called()


def test_a_rename_on_a_share_is_verified_as_a_task(
    qtbot: QtBot, model: Mock, queue: Mock, job_class: MagicMock, mocker: MockerFixture
) -> None:
    """On one share, with *on a network share* on (as shipped), the rename is a task verifying before and after.

    **Test steps:**

    * make the place on the record's share, and move there
    * check the record was prepared, and a rename job queued with its rename checks on, in the record's log scope
    """
    del qtbot
    volume(mocker, same=True, storage=RootStorage.NETWORK)
    scope = mocker.patch(f"{MODULE}.LogScope.open")

    RecordMoves(model, queue).move(PLACE)

    model.prepare_move.assert_called_once_with(f"Archive: {Path('Jane', 'Foo')}")
    kwargs = job_class.call_args.kwargs
    assert (kwargs["mode"], kwargs["check_renamed"]) == (MoveMode.RENAME, True)
    queue.enqueue.assert_called_once_with(job_class.return_value)
    scope.assert_called_once_with(RECORD)


def test_a_place_on_another_volume_is_a_copy_naming_both_roots(
    qtbot: QtBot, model: Mock, queue: Mock, job_class: MagicMock, mocker: MockerFixture
) -> None:
    """Another volume is always a task: a copy, carrying both roots, the place under its root and the settings.

    **Test steps:**

    * make the place on another volume, turn checking the original off, and move there
    * check the job is a copy of the record from its root into ``Jane`` under the other, as ``Foo``, the original
      unchecked
    """
    del qtbot
    volume(mocker, same=False)
    shared_move_settings().verify_original_before_copy = False

    RecordMoves(model, queue).move(PLACE)

    job_class.assert_called_once()
    assert job_class.call_args.args == (RECORD,)
    kwargs = job_class.call_args.kwargs
    assert (kwargs["source_root"], kwargs["destination_root"]) == (ROOT_ID, ARCHIVE_ID)
    assert (kwargs["into"], kwargs["new_name"], kwargs["mode"]) == (PurePosixPath("Jane"), "Foo", MoveMode.COPY)
    assert kwargs["check_source"] is False
    assert kwargs["label"] == f"Move to Archive: {Path('Jane', 'Foo')} - Foo"


def test_a_move_the_record_refuses_is_not_queued(
    qtbot: QtBot, model: Mock, queue: Mock, job_class: MagicMock, mocker: MockerFixture
) -> None:
    """A record that cannot be moved now -- a save not landed, a save that failed -- queues nothing.

    **Test steps:**

    * make preparing the record refuse, and move to another volume
    * check nothing was queued
    """
    del qtbot, job_class
    volume(mocker, same=False)
    model.prepare_move.return_value = False

    RecordMoves(model, queue).move(PLACE)

    queue.enqueue.assert_not_called()


def test_asking_twice_queues_once(
    qtbot: QtBot, model: Mock, queue: Mock, job_class: MagicMock, mocker: MockerFixture
) -> None:
    """A move like one already waiting is not queued again.

    **Test steps:**

    * have the queue hold an unfinished row reading as the same move, and move there
    * check nothing was queued
    """
    del qtbot
    volume(mocker, same=False)
    job = job_class.return_value
    queue.jobs.return_value = (JobStatus(1, job.label, JobState.QUEUED, source=RECORD),)

    RecordMoves(model, queue).move(PLACE)

    queue.enqueue.assert_not_called()


def test_nothing_moves_to_where_the_record_is_or_without_a_record(
    qtbot: QtBot, model: Mock, queue: Mock, mocker: MockerFixture
) -> None:
    """The place the record is at, or a document with no path, moves nothing.

    **Test steps:**

    * move to a place marked as where the record is, then move a document with no path
    * check neither renamed nor prepared anything
    """
    del qtbot
    volume(mocker, same=True)
    here = RootDestination("Archive", PLACE.relative, ARCHIVE, ARCHIVE_ID, True, ROOT, ROOT_ID)
    moves = RecordMoves(model, queue)

    moves.move(here)
    model.path = None
    moves.move(PLACE)

    model.move_in_root.assert_not_called()
    model.prepare_move.assert_not_called()


# endregion


# region a task's end
def finish(qtbot: QtBot, moves: RecordMoves, queue: Mock, status: JobStatus) -> None:
    """Have the queue report ``status`` and wait for the GUI thread to have read it back.

    :param qtbot: pytest-qt fixture.
    :param moves: the moves listening.
    :param queue: the queue.
    :param status: the job's status now.
    """
    queue.jobs.return_value = (status,)
    with qtbot.waitSignal(moves._RecordMoves__marshaller.queue_changed, timeout=1000):  # type: ignore[attr-defined]  # pylint: disable=protected-access
        moves.job_updated(status)
    QCoreApplication.processEvents()


@fixture(name="queued")
def fixture_queued(model: Mock, queue: Mock, job_class: MagicMock, mocker: MockerFixture) -> RecordMoves:
    """Moves that have queued one copy, as :data:`SERIAL`.

    :param model: the document.
    :param queue: the queue.
    :param job_class: the job class.
    :param mocker: pytest-mock fixture.
    :returns: the moves.
    """
    del job_class
    volume(mocker, same=False)
    moves = RecordMoves(model, queue)
    moves.move(PLACE)
    return moves


def test_a_failed_move_is_told_on_the_banner(qtbot: QtBot, model: Mock, queue: Mock, queued: RecordMoves) -> None:
    """A move that failed is reported naming the place and the reason, without the error's type.

    **Test steps:**

    * finish the queued move as failed
    * check the banner reads the row's label and the reason
    """
    finish(qtbot, queued, queue, JobStatus(SERIAL, "Move to X", JobState.FAILED, message="VerifiedCopyError: no match"))

    model.move_failed.assert_called_once_with("Move to X failed: no match")


@mark.parametrize("clean", [True, False])
def test_a_finished_move_lands_or_says_what_it_left(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    qtbot: QtBot, model: Mock, queue: Mock, job_class: MagicMock, queued: RecordMoves, clean: bool
) -> None:
    """A move that finished clean lands, as a rename does; one that left part of the original says so on the banner.

    **Test steps:**

    * give the job an outcome, clean or not, and finish it as done
    * check the model heard the landing, or the outcome as a failure
    """
    job_class.return_value.outcome = JobOutcome("Moved; kept x", clean=clean)

    finish(qtbot, queued, queue, JobStatus(SERIAL, "Move", JobState.DONE))

    if clean:
        model.move_landed.assert_called_once_with()
        model.move_failed.assert_not_called()
    else:
        model.move_failed.assert_called_once_with("Moved; kept x")


def test_a_cancelled_move_says_nothing_and_an_unfinished_one_waits(
    qtbot: QtBot, model: Mock, queue: Mock, queued: RecordMoves
) -> None:
    """A cancelled move is the user's own doing; an update about another row, or about ours still running, changes
    nothing.

    **Test steps:**

    * report another row finishing, and ours running: nothing is read back
    * read back with ours running, then cancelled
    * check the model heard nothing either way
    """
    queued.job_updated(JobStatus(SERIAL + 1, "Other", JobState.DONE))
    queued.job_updated(JobStatus(SERIAL, "Move", JobState.RUNNING))
    queue.jobs.return_value = (JobStatus(SERIAL, "Move", JobState.RUNNING),)
    queued._RecordMoves__on_queue_changed()  # type: ignore[attr-defined]  # pylint: disable=protected-access

    finish(qtbot, queued, queue, JobStatus(SERIAL, "Move", JobState.CANCELLED))

    model.move_failed.assert_not_called()
    model.move_landed.assert_not_called()


def test_a_move_already_in_the_queue_is_taken_up(qtbot: QtBot, model: Mock, queue: Mock) -> None:
    """A move of the record the queue restored reports to its document as one queued here does; another record's
    move, a finished one, another kind of job and a row with no job behind it do not.

    **Test steps:**

    * hold a paused move of the record, with rows that must not be taken up beside it, and build the moves
    * finish each row as failed
    * check only the record's own move reached the banner
    """
    job = MagicMock(spec=MoveRecordJob)
    job.outcome = None
    queue.jobs.return_value = (
        JobStatus(1, "Move", JobState.PAUSED, source=RECORD, kind=RECORD_MOVE_KIND),
        JobStatus(2, "Move", JobState.PAUSED, source=ARCHIVE / "info.rehu", kind=RECORD_MOVE_KIND),
        JobStatus(3, "Move", JobState.DONE, source=RECORD, kind=RECORD_MOVE_KIND),
        JobStatus(4, "Verify", JobState.PAUSED, source=RECORD, kind="checksum-verify"),
        JobStatus(5, "Move", JobState.PAUSED, source=RECORD, kind=RECORD_MOVE_KIND),
    )
    queue.job.side_effect = lambda serial: job if serial == 1 else None
    moves = RecordMoves(model, queue)

    for serial in (2, 3, 4, 5):
        moves.job_updated(JobStatus(serial, "Other", JobState.FAILED, message="X: no"))
    finish(qtbot, moves, queue, JobStatus(1, "Move to X", JobState.FAILED, message="OSError: gone"))

    model.move_failed.assert_called_once_with("Move to X failed: gone")


def test_another_record_loaded_in_its_place_lets_go_of_the_moves(
    qtbot: QtBot, model: Mock, queue: Mock, queued: RecordMoves
) -> None:
    """A rename is the same record, so its move still reports; a preview loading another record is not, so the move
    stops reporting here -- and a document with no path takes up nothing.

    **Test steps:**

    * tell the moves the path changed with the model not loading: the queued move is kept
    * tell them again while the model loads another record, with no path yet: the move is let go
    * finish the move as failed, and check the banner heard nothing
    """
    on_path_changed = model.path_changed.connect.call_args.args[0]
    on_path_changed(RECORD)  # pylint: disable=not-callable  # a slot read off the mocked signal
    queued.job_updated(JobStatus(SERIAL, "Move", JobState.RUNNING))
    model.loading = True
    model.path = None

    on_path_changed(None)  # pylint: disable=not-callable
    queue.jobs.return_value = (JobStatus(SERIAL, "Move", JobState.FAILED, message="X: no"),)
    queued.job_updated(queue.jobs.return_value[0])
    queued._RecordMoves__on_queue_changed()  # type: ignore[attr-defined]  # pylint: disable=protected-access
    del qtbot

    model.move_failed.assert_not_called()


def test_detaching_stops_listening_and_the_rest_of_the_queue_is_no_news(queue: Mock, queued: RecordMoves) -> None:
    """A closed document stops listening; reorders, removals, enqueues and a paused queue are nothing to it.

    **Test steps:**

    * tell the moves of every other kind of change, then detach them
    * check they took themselves off the queue
    """
    queued.job_enqueued(JobStatus(SERIAL, "Move", JobState.QUEUED), 0)
    queued.jobs_reordered([SERIAL])
    queued.jobs_removed([SERIAL])
    queued.queue_paused_changed(True)

    queued.detach()

    queue.remove_listener.assert_called_once_with(queued)


# endregion
