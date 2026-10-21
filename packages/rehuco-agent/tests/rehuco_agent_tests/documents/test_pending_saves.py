"""Tests for ``PendingSaves``: one save row per record, and what each open document is told about its own (#497).

The task queue is a ``Mock(spec=TaskQueue)`` scripted by :class:`Rig` -- the engine has its own tests, and a scripted
one moves a row to exactly the state a test names, with no worker to race. The Tasks dock's model over it is the real
one, so the owner hears each change as it would in the app: a re-snapshot on the GUI thread.
"""

from dataclasses import replace
from itertools import count
from pathlib import Path
from typing import Any, Final

from PySide6.QtWidgets import QWidget
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents import pending_saves as module
from rehuco_agent.documents.document_registry import DocumentRegistry
from rehuco_agent.documents.pending_saves import SAVE_PAUSED_TEXT, SAVE_PENDING_TEXT, PendingSaves
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.resource_events import ResourceEvents
from rehuco_agent.tasks import TaskQueueModel
from rehuco_core import (
    SAVE_RECORD_KIND,
    JobState,
    JobStatus,
    RecordConflict,
    RecordVersion,
    RehuDocument,
    SaveOutcome,
    SavePayload,
    SaveRecordJob,
    TaskJob,
    TaskQueue,
)
from rehuco_core.access import Records, ResourceKey

from rehuco_agent_tests.delete_at_teardown import DeleteAtTeardown

SOURCE: Final = Path(Path.cwd().anchor) / "media" / "res" / "res.rehu"
"""The record the document under test is of -- never read: the records are a mock."""

KEY: Final = ResourceKey(SOURCE)

OTHER_SOURCE: Final = Path(Path.cwd().anchor) / "media" / "other" / "other.rehu"
"""A record no open document is of."""

FIRST_SERIAL: Final = 1000
"""Where the scripted queue's serials start: far above any a test names itself."""

USERNAME: Final = "someone"

EDITS: Final = {"core": {"title": "Mine"}}
"""What the document's snapshot carries."""

READ_VERSION: Final = RecordVersion("meta", "read", ())
"""The version of the file the open document is based on, unless a test says otherwise."""

SAVED_BASE: Final = RecordVersion("meta", "saved-base", ())
"""The version a restored save was snapshotted against -- not the open document's."""

RENAMED_SOURCE: Final = Path(Path.cwd().anchor) / "media" / "renamed" / "renamed.rehu"
"""Where the record under test went, renamed in the app."""

SIGNATURE: Final = (1234, 56)
"""The written file's signature, as a landed save reports it."""

WAIT_REASON: Final = "Waiting for the share: nas"
FAIL_REASON: Final = "FileNotFoundError: The file is gone"


def payload_of(data: dict[str, Any] | None = None, base: RecordVersion | None = None) -> SavePayload:
    """A snapshot of the record under test.

    :param data: what it writes; :data:`EDITS` when not given.
    :param base: the version it was taken against.
    :returns: the payload.
    """
    return SavePayload(SOURCE, USERNAME, dict(EDITS if data is None else data), None, base)


def outcome() -> SaveOutcome:
    """What a landed save of the record under test reports.

    :returns: the outcome.
    """
    return SaveOutcome(dict(EDITS), RecordVersion("meta", "written", ()), SIGNATURE, False)


def save_job(mocker: MockerFixture, payload: SavePayload | None = None) -> Any:
    """A stand-in for a save job, landed as far as its own fields go: :class:`SaveRecordJob` has its own tests.

    :param mocker: pytest-mock fixture.
    :param payload: what it holds, and the last Save it was handed; :func:`payload_of` when not given.
    :returns: the job.
    """
    job = mocker.Mock(spec=SaveRecordJob)
    job.payload = payload if payload is not None else payload_of()
    job.handed = job.payload
    job.result = outcome()
    job.conflict = None
    job.gone = None
    job.replace.return_value = True
    return job


def document_model(mocker: MockerFixture) -> Any:
    """A stand-in for an open, edited document of the record under test: :class:`RehuDocumentModel` has its own tests.

    :param mocker: pytest-mock fixture.
    :returns: the model.
    """
    model = mocker.Mock(spec=RehuDocumentModel)
    model.key = KEY
    model.path = SOURCE
    model.label = "res"
    model.gone = ""
    model.conflict = None
    model.changed_on_disk = False
    model.dirty = True
    model.upgradable = False
    model.saving = False
    model.saved_on_disk = True
    model.pending_save = ""
    model.base_version = READ_VERSION
    model.snapshot.return_value = payload_of()
    model.document.payload_to_write.return_value = dict(EDITS)
    return model


def a_conflict(mocker: MockerFixture) -> RecordConflict:
    """A refused save's conflict.

    :param mocker: pytest-mock fixture.
    :returns: the conflict.
    """
    return RecordConflict(mocker.Mock(spec=RehuDocument), RecordVersion("meta", "theirs", ()))


# the queue's script, its model and the owner's collaborators, each one thing a test reaches for
# pylint: disable-next=too-many-instance-attributes
class Rig:
    """A :class:`PendingSaves` over a scripted queue, the real Tasks dock model of it, and one open document.

    :param mocker: pytest-mock fixture.
    :param qtbot: pytest-qt fixture.
    :param delete_at_teardown: deletes the bare `QObject` s built here when the test ends.
    """

    def __init__(self, mocker: MockerFixture, qtbot: QtBot, delete_at_teardown: DeleteAtTeardown) -> None:
        self.__mocker: Final = mocker
        self.__qtbot: Final = qtbot
        self.__delete: Final = delete_at_teardown
        self.__serials: Final = count(FIRST_SERIAL)
        self.statuses: Final[dict[int, JobStatus]] = {}
        """Each row, in the queue's order."""
        self.jobs: Final[dict[int, Any]] = {}
        """What :meth:`TaskQueue.job` answers for each row."""
        self.enqueued: Final[list[TaskJob]] = []
        """Every job handed to :meth:`TaskQueue.enqueue`, in order."""
        self.order: Final[list[str]] = []
        """The queue calls and job hand-overs, in the order they were made."""
        self.queue: Final = mocker.Mock(spec=TaskQueue)
        self.queue.jobs.side_effect = lambda: tuple(self.statuses.values())
        self.queue.job.side_effect = self.jobs.get
        self.queue.enqueue.side_effect = self.__enqueue
        self.queue.remove.side_effect = self.__remove
        self.queue.retry.side_effect = self.__retry
        self.rows: Final = delete_at_teardown(TaskQueueModel(self.queue))
        self.model: Final = document_model(mocker)
        self.registry: Final = mocker.Mock(spec=DocumentRegistry)
        self.registry.find.side_effect = lambda key: self.model if key == KEY else None
        self.records: Final = mocker.Mock(spec=Records)
        self.events: Final = delete_at_teardown(ResourceEvents())
        self.__owner: PendingSaves | None = None

    @property
    def owner(self) -> PendingSaves:
        """The unit under test, built on first use over the rows the queue holds by then."""
        if self.__owner is None:
            self.settle()
            self.__owner = self.__delete(
                PendingSaves(self.queue, self.rows, self.registry, self.records, self.events, None)
            )
        return self.__owner

    def start(self) -> None:
        """Build the owner now, over the rows the queue holds."""
        assert self.owner is not None

    def add_row(
        self,
        state: JobState,
        job: Any = None,
        *,
        message: str | None = None,
        source: Path | None = SOURCE,
        kind: str | None = SAVE_RECORD_KIND,
    ) -> int:
        """Put a row in the queue, as a restored queue or an earlier save left it.

        :param state: its state.
        :param job: what :meth:`TaskQueue.job` answers for it; a fresh :func:`save_job` when not given.
        :param message: its message.
        :param source: its source.
        :param kind: its kind.
        :returns: its serial.
        """
        serial = next(self.__serials)
        self.jobs[serial] = job if job is not None else save_job(self.__mocker)  # pylint: disable=unsupported-assignment-operation
        self.statuses[serial] = JobStatus(  # pylint: disable=unsupported-assignment-operation
            serial, "Save - res", state, message=message, source=source, kind=kind
        )
        return serial

    def set_state(self, serial: int, state: JobState, message: str | None = None) -> None:
        """Move a row to ``state``; the owner hears of it at the next :meth:`settle`.

        :param serial: the row.
        :param state: its new state.
        :param message: its new message.
        """
        self.statuses[serial] = replace(self.statuses[serial], state=state, message=message)  # pylint: disable=unsupported-assignment-operation

    def settle(self) -> None:
        """Have the Tasks dock model re-snapshot the queue, as a queue change does, and wait for it."""
        with self.__qtbot.waitSignal(self.rows.snapshot_taken, timeout=1000):
            self.rows.job_updated(JobStatus(0, "", JobState.QUEUED))

    def land(self, serial: int, state: JobState = JobState.DONE, message: str | None = None) -> None:
        """Move a row and let the owner hear of it.

        :param serial: the row.
        :param state: its new state.
        :param message: its new message.
        """
        self.set_state(serial, state, message)
        self.settle()

    def serial_of_save(self) -> int:
        """The row the owner keeps for the record under test.

        :returns: the serial of the last row of that record.
        """
        return [serial for serial, status in self.statuses.items() if status.source == SOURCE][-1]

    def __enqueue(self, job: TaskJob) -> int:
        """Answer :meth:`TaskQueue.enqueue`: a new queued row, answered by a stand-in holding the job's payload, and
        handed it.

        :param job: the job.
        :returns: its serial.
        """
        self.enqueued.append(job)
        self.order.append("enqueue")
        stand_in = save_job(self.__mocker, job.payload if isinstance(job, SaveRecordJob) else None)
        return self.add_row(JobState.QUEUED, stand_in, source=job.source)

    def move_row(self, serial: int, source: Path) -> None:
        """Have a row follow its record to ``source``, as a rename made in the app moves a save's source; the owner
        hears of it at the next :meth:`settle`.

        :param serial: the row.
        :param source: where the record went.
        """
        self.statuses[serial] = replace(self.statuses[serial], source=source)  # pylint: disable=unsupported-assignment-operation

    def __remove(self, *serials: int) -> None:
        """Answer :meth:`TaskQueue.remove`: the rows go.

        :param serials: the rows.
        """
        for serial in serials:
            self.statuses.pop(serial, None)
            self.jobs.pop(serial, None)

    def __retry(self, serial: int) -> None:
        """Answer :meth:`TaskQueue.retry`: the failed row is queued again.

        :param serial: the row.
        """
        self.order.append("retry")
        self.set_state(serial, JobState.QUEUED)


@fixture(name="rig")
def fixture_rig(mocker: MockerFixture, qtbot: QtBot, delete_at_teardown: DeleteAtTeardown) -> Rig:
    """The owner under test, its scripted queue and its one open document.

    :param mocker: pytest-mock fixture.
    :param qtbot: pytest-qt fixture.
    :param delete_at_teardown: deletes the bare `QObject` s built here when the test ends.
    :returns: the rig.
    """
    return Rig(mocker, qtbot, delete_at_teardown)


@fixture(name="parent")
def fixture_parent(qtbot: QtBot) -> QWidget:
    """A real widget the (patched) dialogs are parented to.

    :param qtbot: pytest-qt fixture.
    :returns: the widget.
    """
    widget = QWidget()
    qtbot.addWidget(widget)
    return widget


def replaced_with(job: Any, rig: Rig) -> Any:
    """Record each hand-over of newer data to ``job`` in the rig's order.

    :param job: the stand-in job.
    :param rig: the rig.
    :returns: the job.
    """

    def on_replace(payload: SavePayload) -> bool:
        """Note the hand-over.

        :param payload: the newer data.
        :returns: that it was taken.
        """
        del payload
        rig.order.append("replace")
        return True

    job.replace.side_effect = on_replace
    return job


# region the coalescing rule


def test_a_save_with_no_row_queues_a_new_job(rig: Rig, parent: QWidget) -> None:
    """A record with no save row gets a new job holding the document's snapshot.

    **Test steps:**

    * save the document while the queue holds nothing
    * verify one job was queued, holding the snapshot, the document told its save began, and ``True`` answered
    """
    assert rig.owner.save(parent, rig.model) is True

    (job,) = rig.enqueued
    assert isinstance(job, SaveRecordJob)
    assert job.payload == payload_of()
    rig.model.begin_save.assert_called_once_with()
    assert rig.owner.key_of(rig.serial_of_save()) == KEY


def test_a_save_of_a_queued_row_hands_it_the_newer_data(rig: Rig, parent: QWidget) -> None:
    """A Save while the record's row is still queued replaces that row's data rather than queueing a second write.

    **Test steps:**

    * save once, then save again with the row still queued and the snapshot changed
    * verify no second job was queued, the row's job took the newer data, and the row was not resumed
    """
    rig.owner.save(parent, rig.model)
    serial = rig.serial_of_save()
    rig.model.snapshot.return_value = payload_of({"core": {"title": "Newer"}})

    rig.owner.save(parent, rig.model)

    assert len(rig.enqueued) == 1
    rig.jobs[serial].replace.assert_called_once_with(payload_of({"core": {"title": "Newer"}}))
    rig.queue.resume_job.assert_not_called()
    rig.queue.retry.assert_not_called()


@mark.parametrize("state", [JobState.WAITING, JobState.PAUSED])
def test_a_save_of_a_waiting_or_paused_row_replaces_and_resumes_it(rig: Rig, parent: QWidget, state: JobState) -> None:
    """A Save while the record's row waits or is paused hands it the newer data and puts it back in line at once.

    **Test steps:**

    * save once, and move the row to waiting or paused
    * save again
    * verify the row's job took the newer data, the row was resumed, and no second job was queued
    """
    rig.owner.save(parent, rig.model)
    serial = rig.serial_of_save()
    rig.land(serial, state, WAIT_REASON)

    rig.owner.save(parent, rig.model)

    rig.jobs[serial].replace.assert_called_once_with(payload_of())
    rig.queue.resume_job.assert_called_once_with(serial)
    assert len(rig.enqueued) == 1


def test_a_save_of_a_failed_row_hands_it_the_newer_data_then_retries_it(rig: Rig, parent: QWidget) -> None:
    """A failed save wrote nothing, so it is still the pending one: handed the newer data, then put back in line --
    in that order, since a row back in line may start before the hand-over.

    **Test steps:**

    * save once, and fail the row
    * save again
    * verify its job took the newer data before the row was retried, nothing resumed, and no second job queued
    """
    rig.owner.save(parent, rig.model)
    serial = rig.serial_of_save()
    replaced_with(rig.jobs[serial], rig)
    rig.land(serial, JobState.FAILED, FAIL_REASON)

    rig.owner.save(parent, rig.model)

    assert rig.order == ["enqueue", "replace", "retry"]
    rig.queue.resume_job.assert_not_called()


@mark.parametrize("state", [JobState.DONE, JobState.CANCELLED])
def test_a_save_after_a_landed_or_cancelled_row_is_a_new_job(rig: Rig, parent: QWidget, state: JobState) -> None:
    """A row that landed or was cancelled is history: the next Save is a job of its own, and the row the record keeps.

    **Test steps:**

    * save once, and land or cancel the row
    * save again
    * verify a second job was queued, the old row's job was not handed anything, and the new row is the record's
    """
    rig.owner.save(parent, rig.model)
    first = rig.serial_of_save()
    rig.land(first, state)

    rig.owner.save(parent, rig.model)

    assert len(rig.enqueued) == 2
    rig.jobs[first].replace.assert_not_called()
    second = rig.serial_of_save()
    assert second != first
    assert rig.owner.key_of(second) == KEY
    assert rig.owner.key_of(first) is None


@mark.parametrize(("base", "rebased"), [(READ_VERSION, True), (outcome().version, False)], ids=["unheard", "heard"])
def test_a_save_after_a_landed_row_is_moved_onto_what_it_wrote_unless_already_based_on_it(
    rig: Rig, parent: QWidget, mocker: MockerFixture, base: RecordVersion, rebased: bool
) -> None:
    """A Save made after the record's last save landed but before its document heard so is still based on the version
    that landing replaced: it is moved onto what was written, rather than refused as a conflict with its own record's
    save. One already based on what was written is queued as it is.

    **Test steps:**

    * save once, and land the row
    * save again, the snapshot based on the version before the landing, or on the one it wrote
    * verify the new job holds the snapshot moved onto the landed save's payload and outcome only in the first case
    """
    moved = payload_of({"core": {"title": "Moved"}})
    rebase = mocker.patch.object(module, "rebase_payload", return_value=moved)
    rig.owner.save(parent, rig.model)
    first = rig.serial_of_save()
    rig.land(first)
    landed = rig.jobs[first]
    later = payload_of({"core": {"title": "Later"}}, base=base)
    rig.model.snapshot.return_value = later

    rig.owner.save(parent, rig.model)

    (_, second) = rig.enqueued
    assert isinstance(second, SaveRecordJob)
    if rebased:
        rebase.assert_called_once_with(later, landed.payload, landed.result)
        assert second.payload == moved
    else:
        rebase.assert_not_called()
        assert second.payload == later


def test_the_records_newest_save_is_the_one_made_last_whatever_the_queues_order(rig: Rig, parent: QWidget) -> None:
    """A record's save is the row made last, told by its serial: a row moved up the queue -- past an older, landed
    save of the record -- is still the newer one, and still the record's pending save.

    **Test steps:**

    * save once and land the row; save again
    * move the second row above the first in the queue's order, and let the owner re-read the queue
    * verify the second row is still the record's, and its data the record's pending save
    """
    rig.owner.save(parent, rig.model)
    first = rig.serial_of_save()
    rig.land(first)
    rig.owner.save(parent, rig.model)
    second = rig.serial_of_save()
    rows = dict(rig.statuses)
    rig.statuses.clear()
    rig.statuses[second] = rows.pop(second)  # pylint: disable=unsupported-assignment-operation
    rig.statuses.update(rows)

    rig.settle()

    assert rig.owner.key_of(second) == KEY
    assert rig.owner.key_of(first) is None
    assert rig.owner.pending_payload(KEY) == rig.jobs[second].handed


def test_a_save_of_a_row_whose_job_is_gone_is_a_new_job(rig: Rig, parent: QWidget) -> None:
    """A row the queue no longer answers a job for gets a new job rather than a hand-over to nothing.

    **Test steps:**

    * restore a queued row of the record whose job the queue does not answer
    * save
    * verify a new job was queued
    """
    rig.add_row(JobState.QUEUED, object())

    rig.owner.save(parent, rig.model)

    assert len(rig.enqueued) == 1


def test_a_save_while_the_row_writes_hands_it_the_newer_data(rig: Rig, parent: QWidget) -> None:
    """A Save while the record's row is writing hands that row the newer data, which its run writes right after.

    **Test steps:**

    * save once, and move the row to running
    * save again with the snapshot changed
    * verify the row's job took the newer data, nothing was resumed or retried, and no second job was queued -- nor
      once the row lands
    """
    rig.owner.save(parent, rig.model)
    serial = rig.serial_of_save()
    rig.land(serial, JobState.RUNNING)
    rig.model.snapshot.return_value = payload_of({"core": {"title": "Newer"}})

    rig.owner.save(parent, rig.model)

    rig.jobs[serial].replace.assert_called_once_with(payload_of({"core": {"title": "Newer"}}))
    rig.queue.resume_job.assert_not_called()
    rig.queue.retry.assert_not_called()
    rig.land(serial)
    assert len(rig.enqueued) == 1


def test_a_save_landed_meanwhile_is_a_new_job_moved_onto_what_it_wrote(
    rig: Rig, parent: QWidget, mocker: MockerFixture
) -> None:
    """A row that landed between the look and the hand-over refuses the data: the Save is a job of its own, rebased
    onto what the landed one wrote, and the row the record keeps.

    **Test steps:**

    * save once, and make the row's job refuse newer data, as one that landed does
    * save again with the snapshot changed
    * verify the rebase was asked of the newer snapshot, the landed job's payload and its outcome, and a second job
      was queued holding what it answered, the record's row now, with the document told its save began again
    """
    rebased = payload_of({"core": {"title": "Rebased"}})
    rebase = mocker.patch.object(module, "rebase_payload", return_value=rebased)
    rig.owner.save(parent, rig.model)
    first = rig.serial_of_save()
    landed = rig.jobs[first]
    landed.replace.return_value = False
    rig.model.snapshot.return_value = payload_of({"core": {"title": "Newer"}})

    rig.owner.save(parent, rig.model)

    rebase.assert_called_once_with(payload_of({"core": {"title": "Newer"}}), landed.payload, landed.result)
    (_, second) = rig.enqueued
    assert isinstance(second, SaveRecordJob)
    assert second.payload == rebased
    assert rig.owner.key_of(rig.serial_of_save()) == KEY
    assert rig.serial_of_save() != first
    assert rig.model.begin_save.call_count == 2


def test_a_save_landed_meanwhile_with_no_outcome_is_a_new_job_of_the_plain_snapshot(
    rig: Rig, parent: QWidget, mocker: MockerFixture
) -> None:
    """A refused hand-over whose job reports no outcome has nothing to rebase onto: the new job holds the snapshot.

    **Test steps:**

    * save once, and make the row's job refuse newer data and report no outcome
    * save again with the snapshot changed
    * verify no rebase was asked, and the second job holds the newer snapshot as it is
    """
    rebase = mocker.patch.object(module, "rebase_payload")
    rig.owner.save(parent, rig.model)
    landed = rig.jobs[rig.serial_of_save()]
    landed.replace.return_value = False
    landed.result = None
    rig.model.snapshot.return_value = payload_of({"core": {"title": "Newer"}})

    rig.owner.save(parent, rig.model)

    rebase.assert_not_called()
    (_, second) = rig.enqueued
    assert isinstance(second, SaveRecordJob)
    assert second.payload == payload_of({"core": {"title": "Newer"}})


@mark.parametrize(("state", "call"), [(JobState.WAITING, "resume_job"), (JobState.FAILED, "retry")])
def test_a_clean_document_s_save_of_a_pending_record_tries_it_now(
    rig: Rig, parent: QWidget, state: JobState, call: str
) -> None:
    """A clean document has nothing new to hand over, but its record's save not landed is still saved again: a
    waiting one is tried now, a failed one retried -- how a failure is settled from the document.

    **Test steps:**

    * restore a waiting or failed save row of the record, build the owner, and make the document clean
    * save
    * verify ``True`` came back, the row's job was handed the snapshot, the row was resumed or retried, and no new
      job was queued
    """
    serial = rig.add_row(state, message=WAIT_REASON)
    rig.start()
    rig.model.dirty = False

    assert rig.owner.save(parent, rig.model) is True

    rig.jobs[serial].replace.assert_called_once_with(payload_of())
    getattr(rig.queue, call).assert_called_once_with(serial)
    assert not rig.enqueued


def test_a_save_of_a_gone_record_is_refused(rig: Rig, parent: QWidget) -> None:
    """A document whose file or folder is gone is not saved, and nothing more is said than its banner does.

    **Test steps:**

    * mark the document gone
    * save
    * verify ``False`` came back, nothing was queued, and the document was not told a save began
    """
    rig.model.gone = "The resource's folder is gone"

    assert rig.owner.save(parent, rig.model) is False

    assert not rig.enqueued
    rig.model.begin_save.assert_not_called()


def test_a_save_with_nothing_to_save_queues_nothing(rig: Rig, parent: QWidget) -> None:
    """A clean document that needs no upgrade has nothing to hand a save.

    **Test steps:**

    * make the document clean
    * save
    * verify ``True`` came back and nothing was queued
    """
    rig.model.dirty = False

    assert rig.owner.save(parent, rig.model) is True

    assert not rig.enqueued


def test_an_upgradable_clean_document_is_saved(rig: Rig, parent: QWidget) -> None:
    """A clean document whose file wants an upgrade is saved all the same (the Upgrade action).

    **Test steps:**

    * make the document clean but upgradable
    * save
    * verify a job was queued
    """
    rig.model.dirty = False
    rig.model.upgradable = True

    rig.owner.save(parent, rig.model)

    assert len(rig.enqueued) == 1


# endregion

# region the pending payload


def test_the_owner_hands_the_registry_where_pending_saves_are_found(rig: Rig) -> None:
    """Built, the owner tells the registry to read a record's pending save through it, for every document it holds
    and opens.

    **Test steps:**

    * build the owner
    * verify the registry was handed the owner's ``pending_payload``, once
    """
    rig.start()

    rig.registry.follow_pending_saves.assert_called_once_with(rig.owner.pending_payload)


@mark.parametrize("state", [JobState.QUEUED, JobState.WAITING, JobState.PAUSED, JobState.FAILED, JobState.RUNNING])
def test_a_save_not_landed_is_the_record_s_pending_payload(rig: Rig, mocker: MockerFixture, state: JobState) -> None:
    """A record's newest save row that has not landed answers the last Save handed to it -- not what it holds to
    write next.

    **Test steps:**

    * restore a save row of the record in a state short of landing, its job handed other data than it holds
    * build the owner
    * verify the record's pending payload is what the job was handed
    """
    job = save_job(mocker)
    job.handed = payload_of({"core": {"title": "Handed"}})
    rig.add_row(state, job)
    rig.start()

    assert rig.owner.pending_payload(KEY) is job.handed


@mark.parametrize("state", [JobState.DONE, JobState.CANCELLED])
def test_a_settled_save_is_no_pending_payload(rig: Rig, state: JobState) -> None:
    """A save that landed, or was dropped at a shutdown, is history: the record has no pending payload.

    **Test steps:**

    * restore a landed or cancelled save row of the record, and build the owner
    * verify the record's pending payload is ``None``
    """
    rig.add_row(state)
    rig.start()

    assert rig.owner.pending_payload(KEY) is None


def test_a_record_with_no_save_row_has_no_pending_payload(rig: Rig) -> None:
    """A record the queue holds no save of has nothing pending.

    **Test steps:**

    * restore a save row of another record, and build the owner
    * verify the record under test has no pending payload
    """
    rig.add_row(JobState.QUEUED, source=OTHER_SOURCE)
    rig.start()

    assert rig.owner.pending_payload(KEY) is None


def test_a_row_whose_job_is_no_save_has_no_pending_payload(rig: Rig) -> None:
    """A save row the queue answers no save job for has nothing to hand a document.

    **Test steps:**

    * restore a queued save row of the record whose job is not a save, and build the owner
    * verify the record has no pending payload
    """
    rig.add_row(JobState.QUEUED, object())
    rig.start()

    assert rig.owner.pending_payload(KEY) is None


def test_a_row_that_followed_a_rename_is_found_under_the_new_key(rig: Rig, parent: QWidget) -> None:
    """A save row whose record was renamed in the app is the record's under where it went: its pending payload is
    found there and not at the old place, and a Save of the renamed document hands it the edits.

    **Test steps:**

    * restore a queued save row of the record, and build the owner
    * move the row's source to the renamed record, and re-snapshot
    * verify the row is the renamed record's, its pending payload is found there and not under the old key
    * save a document of the renamed record, and verify the row's job took the edits and nothing was queued
    """
    serial = rig.add_row(JobState.QUEUED)
    rig.start()
    renamed = ResourceKey(RENAMED_SOURCE)

    rig.move_row(serial, RENAMED_SOURCE)
    rig.settle()

    assert rig.owner.key_of(serial) == renamed
    assert rig.owner.pending_payload(renamed) is rig.jobs[serial].handed
    assert rig.owner.pending_payload(KEY) is None
    rig.model.key = renamed
    rig.owner.save(parent, rig.model)
    rig.jobs[serial].replace.assert_called_once_with(payload_of())
    assert not rig.enqueued


# endregion

# region the banner


@mark.parametrize(
    ("state", "message", "text"),
    [
        (JobState.QUEUED, None, SAVE_PENDING_TEXT),
        (JobState.WAITING, WAIT_REASON, f"Save waiting: {WAIT_REASON}"),
        (JobState.WAITING, None, "Save waiting"),
        (JobState.PAUSED, None, SAVE_PAUSED_TEXT),
        (JobState.FAILED, FAIL_REASON, f"Save failed: {FAIL_REASON}"),
        (JobState.FAILED, None, "Save failed"),
        (JobState.RUNNING, None, ""),
        (JobState.DONE, None, ""),
        (JobState.CANCELLED, None, ""),
    ],
)
def test_the_banner_names_each_state_a_save_can_wait_in(state: JobState, message: str | None, text: str) -> None:
    """A document's banner says what its save row is doing, and nothing for a row that landed or is writing.

    **Test steps:**

    * build a save row in each state, with and without a message
    * verify the banner text for each
    """
    assert PendingSaves.pending_text(JobStatus(FIRST_SERIAL, "Save - res", state, message=message)) == text


# endregion
