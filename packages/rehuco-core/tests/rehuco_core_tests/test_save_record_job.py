"""Tests for a record's save as a task-queue job (#497): :class:`~rehuco_core.SaveRecordJob` and the
:class:`~rehuco_core.SavePayload` it writes ([[sync#apply-payload]]).

The happy path, the per-user merge, the conflict and the gone file run through a real :class:`~rehuco_core.Records`
over files under ``tmp_path``. A held lock and a failed write come from a ``Mock(spec=Records)``, the share's presence
and device are patched, and the checksum move a first save makes is mocked: each is its own module's subject.
"""

import copy
import json
import logging
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from typing import Any, Final
from unittest.mock import Mock

from borco_core import Device, Presence, StorageKind
from pytest import LogCaptureFixture, mark, raises
from pytest_mock import MockerFixture
from rehuco_core import (
    DEFAULT_TASK_JOB_REGISTRY,
    EXCLUDED_FILE_PATTERNS,
    SAVE_RECORD_KIND,
    JobControl,
    JobOutcome,
    JobWaiting,
    RecordConflict,
    RecordLockedError,
    Records,
    RecordVersion,
    RenameCoordinator,
    ResourceKey,
    ResourceLocation,
    SavedRecord,
    SavePayload,
    SaveRecordJob,
)
from rehuco_core.save_record_job import LOCKED_RETRY_SECONDS, OFFLINE_RETRY_SECONDS, STATE_PAYLOAD_KEY

from rehuco_core_tests.access.test_records import (
    UNKNOWN,
    USERNAME,
    on_disk,
    tutorial_data,
    users_on_disk,
    write_meanwhile,
    write_record,
)

MODULE: Final = "rehuco_core.save_record_job"
"""The module under test, whose own names the tests patch."""

FAKE_RECORD: Final = Path(Path.cwd().anchor) / "library" / "sculpting" / "info.rehu"
"""A record no test touches on disk: absolute on every platform, its device always patched."""

VERSION: Final = RecordVersion("meta", "file", (("tutorial", "admin", "rating", "hash"),))
"""A version with one per-user field hash, for the payloads no save reads."""


def snapshot(path: Path, **changes: Any) -> SavePayload:
    """What Save hands over for the record at ``path`` as read now, edited by ``changes``.

    :param path: a record on disk.
    :param changes: ``core`` fields set on the payload to write.
    :returns: the payload, read at the file's version.
    """
    loaded = Records().load(ResourceKey(path), username=USERNAME, unknown_username=UNKNOWN)
    base_payload = copy.deepcopy(loaded.document.payload_to_write())
    payload = copy.deepcopy(base_payload)
    payload["core"].update(changes)
    return SavePayload(path, USERNAME, payload, base_payload, loaded.version)


def existing_record(folder: Path) -> Path:
    """Write a record, for a save whose writing is mocked but whose file must be there.

    :param folder: where.
    :returns: the record's path.
    """
    return write_record(folder / "info.rehu", tutorial_data()).path


def fake_payload(path: Path = FAKE_RECORD, **fields: Any) -> SavePayload:
    """A payload for a record no save reads, with a base.

    :param path: the record.
    :param fields: overrides of the payload's fields.
    :returns: the payload.
    """
    values: dict[str, Any] = {
        "path": path,
        "username": USERNAME,
        "payload": tutorial_data(),
        "base_payload": tutorial_data(),
        "base": VERSION,
    }
    values.update(fields)
    return SavePayload(**values)


def mock_records() -> Mock:
    """Records whose save the test decides.

    :returns: the mock.
    """
    return Mock(spec=Records)


def network_device(path: Path) -> Device:
    """The device of a share on host ``nas``, whatever ``path`` is.

    :param path: the path classified.
    :returns: the device.
    """
    del path
    return Device(StorageKind.NETWORK, Path("//nas/share/"), host="nas")


# region happy path
def test_a_save_writes_the_record_and_reports_what_landed(tmp_path: Path) -> None:
    """A save writes the payload over the record it was read from, and reports the written record, its version and
    signature, and no merge.

    **Test steps:**

    * write a record, snapshot it with an edited description, and write the job's payload
    * verify the file holds the edit, and the result is the file as written, its fresh version and its signature
    * verify the outcome reads "Saved", with no conflict and nothing gone
    """
    path = tmp_path / "info.rehu"
    write_record(path, tutorial_data())
    job = SaveRecordJob(snapshot(path, description="edited"))

    result = job.write()

    stored = on_disk(path)
    stat = path.stat()
    reloaded = Records().load(ResourceKey(path), username=USERNAME, unknown_username=UNKNOWN)
    assert stored["core"]["description"] == "edited"
    assert result.written == stored
    assert result.version == reloaded.version
    assert result.signature == (stat.st_mtime_ns, stat.st_size)
    assert result.users_merged is False
    assert job.result is result
    assert job.outcome == JobOutcome("Saved")
    assert (job.conflict, job.gone) == (None, None)


def test_a_save_reports_per_user_fields_merged_from_the_file(tmp_path: Path) -> None:
    """A per-user field written meanwhile is merged in, and the outcome says so.

    **Test steps:**

    * write a record and snapshot it with an edited description
    * meanwhile, another writer rates it for ``bob``
    * write the job's payload; verify ``bob``'s sidecar keeps his rating and the record the edit
    * verify the result reports the merge and the outcome names it
    """
    path = tmp_path / "info.rehu"
    write_record(path, tutorial_data())
    job = SaveRecordJob(snapshot(path, description="edited"))
    write_meanwhile(path, {"bob": {"rating": 2}})

    result = job.write()

    assert users_on_disk(path) == {"bob": {"rating": 2}}
    assert on_disk(path)["core"]["description"] == "edited"
    assert result.users_merged is True
    assert job.outcome == JobOutcome("Saved; per-user fields merged from the file")


def test_run_writes_the_payload(mocker: MockerFixture) -> None:
    """The queue's entry point is :meth:`~rehuco_core.SaveRecordJob.write`, called once.

    **Test steps:**

    * patch the job's write and run the job with a mocked control
    * verify write was called once and the control was told nothing
    """
    write = mocker.patch.object(SaveRecordJob, "write")
    control = Mock(spec=JobControl)

    SaveRecordJob(fake_payload()).run(control)

    write.assert_called_once_with()
    control.report.assert_not_called()


# region refusals
def test_a_conflict_is_kept_and_raised(tmp_path: Path) -> None:
    """A metadata edit made on disk since the snapshot refuses the save, and the conflict stays on the job.

    **Test steps:**

    * write a record and snapshot it with an edited description
    * meanwhile, another writer changes the description
    * verify the write raises the conflict, the job keeps it, nothing landed and the file is the other writer's
    """
    path = tmp_path / "info.rehu"
    write_record(path, tutorial_data())
    job = SaveRecordJob(snapshot(path, description="mine"))
    write_meanwhile(path, description="theirs")

    with raises(RecordConflict) as caught:
        job.write()

    assert job.conflict is caught.value
    assert (job.result, job.outcome) == (None, None)
    assert on_disk(path)["core"]["description"] == "theirs"


def test_a_lock_held_elsewhere_waits(mocker: MockerFixture, tmp_path: Path) -> None:
    """A lock someone else holds makes the save wait, saying who holds it.

    **Test steps:**

    * write a record, patch its share present and make the save raise a held lock
    * verify the write raises waiting for the lock's retry, with the lock's sentence and the lock as its cause
    """
    mocker.patch(f"{MODULE}.presence_of", return_value=Presence.PRESENT)
    path = existing_record(tmp_path)
    records = mock_records()
    locked = RecordLockedError(path, None)
    records.save.side_effect = locked

    with raises(JobWaiting) as caught:
        SaveRecordJob(fake_payload(path), records=records).write()

    assert caught.value.retry_after == LOCKED_RETRY_SECONDS
    assert caught.value.reason == str(locked)
    assert caught.value.__cause__ is locked


def test_a_share_that_does_not_answer_waits_without_a_write(mocker: MockerFixture) -> None:
    """A share found offline before the write makes the save wait, naming the host, and nothing is attempted.

    **Test steps:**

    * patch the share offline on host ``nas``
    * verify the write raises waiting for the offline retry, naming ``nas``
    * verify the records were never asked to save
    """
    mocker.patch(f"{MODULE}.presence_of", return_value=Presence.OFFLINE)
    mocker.patch(f"{MODULE}.device_of", side_effect=network_device)
    records = mock_records()

    with raises(JobWaiting) as caught:
        SaveRecordJob(fake_payload(), records=records).write()

    assert caught.value.retry_after == OFFLINE_RETRY_SECONDS
    assert caught.value.reason == "Waiting for the share: nas"
    records.save.assert_not_called()


def test_a_failed_write_on_a_share_gone_offline_waits(mocker: MockerFixture, tmp_path: Path) -> None:
    """A write that fails because the share stopped answering during it waits, rather than failing.

    **Test steps:**

    * write a record on a share on ``nas``, patched present before the write and offline after it
    * make the save raise an ``OSError``
    * verify the write raises waiting for the offline retry, naming ``nas``, with the failure as its cause
    """
    mocker.patch(f"{MODULE}.presence_of", side_effect=[Presence.PRESENT, Presence.OFFLINE])
    mocker.patch(f"{MODULE}.device_of", side_effect=network_device)
    path = existing_record(tmp_path)
    records = mock_records()
    failure = OSError("the network name is no longer available")
    records.save.side_effect = failure

    with raises(JobWaiting) as caught:
        SaveRecordJob(fake_payload(path), records=records).write()

    assert caught.value.retry_after == OFFLINE_RETRY_SECONDS
    assert caught.value.reason == "Waiting for the share: nas"
    assert caught.value.__cause__ is failure


def test_a_failed_write_on_a_share_still_there_fails(mocker: MockerFixture, tmp_path: Path) -> None:
    """A write that fails with the share still answering is a failure, raised as it was.

    **Test steps:**

    * write a record, patch its share present throughout, and make the save raise an ``OSError``
    * verify that very error escapes the write
    """
    mocker.patch(f"{MODULE}.presence_of", return_value=Presence.PRESENT)
    path = existing_record(tmp_path)
    records = mock_records()
    failure = OSError("disk full")
    records.save.side_effect = failure

    with raises(OSError) as caught:
        SaveRecordJob(fake_payload(path), records=records).write()

    assert caught.value is failure


def test_a_gone_folder_fails_and_is_never_recreated(mocker: MockerFixture, tmp_path: Path) -> None:
    """A record whose folder is gone fails with a sentence naming the folder, and no folder is made for it.

    **Test steps:**

    * patch the presence of a missing folder as gone, and write a first save of a record inside it
    * verify the write raises file-not-found with the job's sentence naming the folder
    * verify the folder still does not exist
    """
    mocker.patch(f"{MODULE}.presence_of", return_value=Presence.GONE)
    take = mocker.patch(f"{MODULE}.take_enclosing_claims")
    folder = tmp_path / "gone"
    job = SaveRecordJob(fake_payload(folder / "info.rehu", base=None, base_payload=None, first_save=True))

    with raises(FileNotFoundError, match="folder is gone"):
        job.write()

    assert job.gone == f"The resource's folder is gone: {folder}"
    assert not folder.exists()
    take.assert_not_called()


def test_a_read_records_gone_file_fails_and_is_never_recreated(tmp_path: Path) -> None:
    """A record read from a file that has since gone fails with a sentence naming the file, and is not written.

    **Test steps:**

    * write a record, snapshot it, and delete the file
    * verify the write raises file-not-found, the job names the file, and no file was written
    """
    path = tmp_path / "info.rehu"
    write_record(path, tutorial_data())
    job = SaveRecordJob(snapshot(path))
    path.unlink()

    with raises(FileNotFoundError, match="file is gone"):
        job.write()

    assert job.gone == f"The file is gone: {path}"
    assert not path.exists()


def test_a_job_with_no_payload_refuses_to_start_and_to_write() -> None:
    """The job the registry builds before a state arrives is not runnable, and writing it raises.

    **Test steps:**

    * build a job with no payload
    * verify validate refuses it and write raises ``ValueError``
    * verify it still takes a payload afterwards, and then validates
    """
    job = SaveRecordJob()

    assert job.validate() == "This save has no record to write."
    with raises(ValueError, match="no record to write"):
        job.write()
    assert job.replace(fake_payload())
    assert job.validate() is None


# region after the write
def test_a_save_logs_the_blocks_it_discarded(tmp_path: Path, caplog: LogCaptureFixture) -> None:
    """The blocks a payload names as discarded are logged once the write lands.

    **Test steps:**

    * write a record and snapshot it naming ``audiopack`` as discarded
    * write it; verify one INFO record names the block and the record
    """
    path = tmp_path / "info.rehu"
    write_record(path, tutorial_data())
    read = snapshot(path)
    job = SaveRecordJob(replace(read, discarded=("audiopack",)))

    with caplog.at_level(logging.INFO, logger=MODULE):
        job.write()

    discards = [record for record in caplog.records if "discarded on save" in record.getMessage()]
    assert [record.getMessage() for record in discards] == [f"audiopack block discarded on save from {path}"]


def test_a_save_never_adds_back_a_block_it_drops(tmp_path: Path) -> None:
    """A block the document claimed and abandoned stays out of the file, even when the file holds another user's
    fields in it that the merge would otherwise carry over ([[plugins#plugin-blocks]]).

    **Test steps:**

    * write a record whose ``reference_images`` block holds ``bob``'s rating, and read it
    * snapshot it without that block, named as dropped; meanwhile another writer adds a progress entry, so the save
      merges
    * write it; verify the file no longer holds the block
    """
    path = tmp_path / "info.rehu"
    data = tutorial_data()
    data["reference_images"] = {"format_version": 1, "users": {"bob": {"rating": 2}}}
    write_record(path, data)
    read = snapshot(path)
    payload = {key: value for key, value in read.payload.items() if key != "reference_images"}
    write_meanwhile(path, {USERNAME: {"progress": {"a.mp4": 12}}})

    SaveRecordJob(replace(read, payload=payload, dropped=("reference_images",))).write()

    assert "reference_images" not in on_disk(path)


def test_the_blocks_a_save_drops_round_trip_and_a_malformed_list_reads_as_none() -> None:
    """The dropped blocks are written down with the payload and read back; a malformed value reads as none dropped.

    **Test steps:**

    * write a payload dropping one block to JSON and read it back; verify it is equal
    * read a JSON whose ``dropped`` is not a list; verify nothing is dropped
    """
    payload = fake_payload(dropped=("gone",))

    assert SavePayload.from_json(json.loads(json.dumps(payload.to_json()))) == payload
    assert not SavePayload.from_json({**payload.to_json(), "dropped": "gone"}).dropped


def test_a_first_save_stamps_created_and_takes_the_enclosing_claims(mocker: MockerFixture, tmp_path: Path) -> None:
    """A record's first save stamps ``created`` and moves the checksums it covers into its own record.

    **Test steps:**

    * patch the checksum move, and mock the coordinator: it tracks the record where it is and holds nothing
    * write a first save of a new record with no base
    * verify the file carries a ``created`` stamp
    * verify the move was asked for that record, with the job's coordinator and the payload's exclusions
    """
    take = mocker.patch(f"{MODULE}.take_enclosing_claims")
    coordinator = Mock(spec=RenameCoordinator)
    coordinator.track.side_effect = ResourceLocation
    coordinator.holding.return_value = nullcontext()
    path = tmp_path / "info.rehu"
    payload = SavePayload(path, USERNAME, tutorial_data(), None, None, first_save=True, excluded_patterns=("*.tmp",))

    SaveRecordJob(payload, coordinator=coordinator).write()

    assert on_disk(path)["core"]["created"]
    take.assert_called_once_with(path, coordinator=coordinator, excluded_patterns=("*.tmp",))


def test_an_existing_records_save_never_stamps_created(tmp_path: Path) -> None:
    """A save of a record read from its file is not its first write, so a record with no ``created`` keeps none.

    **Test steps:**

    * write a record with no ``created``, snapshot it with an edit, and write it
    * verify the file still has no ``created``
    """
    path = tmp_path / "info.rehu"
    write_record(path, tutorial_data())

    SaveRecordJob(snapshot(path, description="edited")).write()

    assert "created" not in on_disk(path)["core"]


def test_a_failed_checksum_move_is_logged_not_raised(
    mocker: MockerFixture, tmp_path: Path, caplog: LogCaptureFixture
) -> None:
    """The record landed, so a checksum move that fails costs a warning, not the save.

    **Test steps:**

    * make the checksum move raise an ``OSError``, and write a first save
    * verify the write returns its result, the record is on disk, and a warning names the record and the error
    """
    mocker.patch(f"{MODULE}.take_enclosing_claims", side_effect=OSError("enclosing record is read-only"))
    path = tmp_path / "info.rehu"
    job = SaveRecordJob(SavePayload(path, USERNAME, tutorial_data(), None, None, first_save=True))

    with caplog.at_level(logging.WARNING, logger=MODULE):
        result = job.write()

    assert job.result is result
    assert path.exists()
    warnings = [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]
    assert warnings == [
        f"The checksums {path} covers could not be moved into its own record: enclosing record is read-only"
    ]


# region replace and reset
def test_replace_before_a_run_takes_the_newer_data() -> None:
    """A pending save takes a later Save's data in place of its own.

    **Test steps:**

    * build a job, replace its payload, and verify it now holds the newer one
    """
    job = SaveRecordJob(fake_payload())
    newer = fake_payload(username="bob")

    assert job.replace(newer)
    assert job.payload is newer


def test_replace_during_a_run_is_written_next_and_refused_after_it_landed(
    mocker: MockerFixture, tmp_path: Path
) -> None:
    """A Save handed while a write is under way is taken and written by the same run; once it landed, a replace is
    refused until a reset.

    **Test steps:**

    * write a record, and make the mocked save try a replace on its first call only; run the write
    * verify that replace was taken and the run saved twice, the second time as the later Save's user
    * verify a replace after the landed run is refused and the job keeps what it wrote
    * reset the job; verify a replace is taken again
    """
    mocker.patch(f"{MODULE}.presence_of", return_value=Presence.PRESENT)
    path = existing_record(tmp_path)
    records = mock_records()
    job = SaveRecordJob(fake_payload(path), records=records)
    during: list[bool] = []

    def save(*args: Any, **kwargs: Any) -> SavedRecord:
        """Try a replace on the first save, as a later Save would mid-write.

        :param args: the save's positional arguments.
        :param kwargs: its keyword arguments.
        :returns: a saved record.
        """
        del args, kwargs
        if not during:
            during.append(job.replace(fake_payload(path, username="bob")))
        return SavedRecord(VERSION, None, False)

    records.save.side_effect = save

    job.write()

    assert during == [True]
    assert [call.kwargs["username"] for call in records.save.call_args_list] == [USERNAME, "bob"]
    written = job.payload
    assert not job.replace(fake_payload(path, username="carol"))
    assert job.payload is written
    job.reset()
    assert job.replace(fake_payload(path, username="dave"))


def test_replace_is_taken_after_a_run_that_waited(mocker: MockerFixture, tmp_path: Path) -> None:
    """A run that waited wrote nothing, so newer data may take its data's place before it runs again.

    **Test steps:**

    * write a record, make the save raise a held lock, and write; verify it waits
    * verify a replace is then taken
    """
    mocker.patch(f"{MODULE}.presence_of", return_value=Presence.PRESENT)
    path = existing_record(tmp_path)
    records = mock_records()
    records.save.side_effect = RecordLockedError(path, None)
    job = SaveRecordJob(fake_payload(path), records=records)

    with raises(JobWaiting):
        job.write()

    newer = fake_payload(path, username="bob")
    assert job.replace(newer)
    assert job.payload is newer


def test_reset_drops_the_last_runs_findings_and_keeps_the_data(tmp_path: Path) -> None:
    """A retry starts clean: reset drops the conflict a run found, keeping the payload.

    **Test steps:**

    * write a record, snapshot it, and make another writer edit it meanwhile; write and catch the conflict
    * reset the job; verify no conflict, no result and nothing gone, and the payload is the one it held
    """
    path = tmp_path / "info.rehu"
    write_record(path, tutorial_data())
    payload = snapshot(path, description="mine")
    job = SaveRecordJob(payload)
    write_meanwhile(path, description="theirs")
    with raises(RecordConflict):
        job.write()

    job.reset()

    assert (job.conflict, job.result, job.gone, job.outcome) == (None, None, None, None)
    assert job.payload is payload


def test_reset_drops_a_gone_finding(mocker: MockerFixture) -> None:
    """A reset drops the sentence a gone record left on the job.

    **Test steps:**

    * patch the folder gone and write; verify the job names it
    * reset; verify the sentence is gone
    """
    mocker.patch(f"{MODULE}.presence_of", return_value=Presence.GONE)
    mocker.patch(f"{MODULE}.device_of", side_effect=network_device)
    job = SaveRecordJob(fake_payload(), records=mock_records())
    with raises(FileNotFoundError):
        job.write()
    assert job.gone is not None

    job.reset()

    assert job.gone is None


# region what the job says about itself
def test_a_job_on_a_share_names_the_resource_and_takes_the_hosts_chain(mocker: MockerFixture) -> None:
    """A save is labelled with the resource's name, is about its record, and takes turns with saves to its host.

    **Test steps:**

    * patch the record's device as a share on ``nas``, and build a job
    * verify the label names the folder, the source is the record and the chain is ``save:nas``
    """
    mocker.patch(f"{MODULE}.device_of", side_effect=network_device)

    job = SaveRecordJob(fake_payload())

    assert job.label == "Save - sculpting"
    assert job.source == FAKE_RECORD
    assert job.chain == "save:nas"
    assert job.kind == SAVE_RECORD_KIND


def test_a_job_on_a_drive_takes_the_drives_chain(mocker: MockerFixture) -> None:
    """A save to a drive with no host takes turns with saves to that drive's root.

    **Test steps:**

    * patch the record's device as a local drive rooted at the path's anchor, and build a job
    * verify the chain is ``save:`` and that root
    """
    root = Path(FAKE_RECORD.anchor)
    mocker.patch(f"{MODULE}.device_of", return_value=Device(StorageKind.LOCAL, root))

    job = SaveRecordJob(fake_payload())

    assert job.chain == f"save:{root}"


def test_a_job_with_no_payload_says_nothing_about_a_resource() -> None:
    """Before a state arrives, a job has no label, no source and the family's bare chain.

    **Test steps:**

    * build a job with no payload; verify its label, source and chain
    """
    job = SaveRecordJob()

    assert (job.label, job.source, job.chain) == ("", None, "save")


# region persistence
def test_a_captured_job_restores_as_the_same_save(mocker: MockerFixture) -> None:
    """A capture/restore round trip, through JSON text, gives back the same payload and what the job says.

    **Test steps:**

    * patch the device, and build a job with every field set
    * capture its state, pass it through JSON text, and restore it into a bare job
    * verify the payload, label, source and chain match
    """
    mocker.patch(f"{MODULE}.device_of", side_effect=network_device)
    payload = fake_payload(discarded=("audiopack",), first_save=True, excluded_patterns=("*.tmp", "Thumbs.db"))
    job = SaveRecordJob(payload)

    state = json.loads(json.dumps(job.capture_state()))
    restored = SaveRecordJob()
    restored.restore_state(state)

    assert restored.payload == payload
    assert (restored.label, restored.source, restored.chain) == (job.label, job.source, job.chain)


def test_a_payload_with_no_base_round_trips() -> None:
    """A never-read record's payload has no base and no base payload, and comes back without them.

    **Test steps:**

    * write a payload with no base to JSON and read it back; verify it is equal
    """
    payload = fake_payload(base=None, base_payload=None)

    assert SavePayload.from_json(json.loads(json.dumps(payload.to_json()))) == payload


def test_a_job_with_no_payload_captures_none() -> None:
    """A bare job writes down that it holds nothing, which a restore refuses.

    **Test steps:**

    * capture a bare job's state; verify it holds ``None``
    * verify restoring that state raises ``ValueError``
    """
    state = SaveRecordJob().capture_state()

    assert state == {STATE_PAYLOAD_KEY: None}
    with raises(ValueError):
        SaveRecordJob().restore_state(state)


def test_the_kind_is_registered_so_a_saved_queue_can_rebuild_it(mocker: MockerFixture) -> None:
    """The kind names this class in the registry a restore reads.

    **Test steps:**

    * patch the device, and create a job from the app-wide registry with a captured state
    * verify the class and the restored payload
    """
    mocker.patch(f"{MODULE}.device_of", side_effect=network_device)
    payload = fake_payload()

    job = DEFAULT_TASK_JOB_REGISTRY.create(SAVE_RECORD_KIND, SaveRecordJob(payload).capture_state())

    assert isinstance(job, SaveRecordJob)
    assert job.payload == payload


def json_state(**changes: Any) -> dict[str, Any]:
    """A payload's JSON state, with fields replaced (or removed where the value is ``...``).

    :param changes: the fields to replace.
    :returns: the state.
    """
    state = fake_payload().to_json()
    for key, value in changes.items():
        if value is ...:
            del state[key]
        else:
            state[key] = value
    return state


def version_state(**changes: Any) -> dict[str, Any]:
    """A payload's JSON state whose version has fields replaced.

    :param changes: the version's fields to replace.
    :returns: the state.
    """
    state = fake_payload().to_json()
    state["base"].update(changes)
    return state


@mark.parametrize(
    "state",
    [
        [],
        json_state(path=...),
        json_state(path=""),
        json_state(path=3),
        json_state(username=None),
        json_state(payload=[]),
        json_state(base="v1"),
        version_state(metadata_hash=None),
        version_state(file_hash=1),
        version_state(user_fields={}),
        version_state(user_fields=["abcd"]),
        version_state(user_fields=[["a", "b", "c"]]),
        version_state(user_fields=[["a", "b", "c", 4]]),
    ],
    ids=[
        "not-an-object",
        "no-path",
        "empty-path",
        "path-not-text",
        "no-user",
        "payload-not-an-object",
        "version-not-an-object",
        "metadata-hash-not-text",
        "file-hash-not-text",
        "user-fields-not-a-list",
        "user-field-not-a-list",
        "user-field-too-short",
        "user-field-part-not-text",
    ],
)
def test_a_malformed_payload_is_refused(state: Any) -> None:
    """A hand-edited queue file that does not describe a save costs its own item.

    **Test steps:**

    * verify reading the malformed state raises ``ValueError``
    """
    with raises(ValueError):
        SavePayload.from_json(state)


def test_optional_fields_read_leniently() -> None:
    """Fields a save can do without fall back to their defaults when a file holds something else.

    **Test steps:**

    * read a state whose base payload, discards, first-save flag and exclusions are malformed or missing
    * verify no base payload, no discards, not a first save, and the built-in exclusions
    * read one whose discards mix text with other values; verify only the text is kept
    """
    lenient = SavePayload.from_json(
        json_state(base_payload="x", discarded="audiopack", first_save=..., excluded_patterns=["*.tmp", 3])
    )
    mixed = SavePayload.from_json(json_state(discarded=["audiopack", 3], excluded_patterns="*.tmp"))

    assert lenient.base_payload is None
    assert not lenient.discarded
    assert lenient.first_save is False
    assert lenient.excluded_patterns == EXCLUDED_FILE_PATTERNS
    assert mixed.discarded == ("audiopack",)
    assert mixed.excluded_patterns == EXCLUDED_FILE_PATTERNS
