"""Tests for a save not landed as a borrowed copy of its record (#497, [[sync#unlanded-save]]): what
:class:`~rehuco_core.SaveRecordJob` does with a later Save handed to it, :func:`~rehuco_core.rebase_payload`, and
how the job follows a rename and checks a first save.

The writes run through a real :class:`~rehuco_core.Records` over files under ``tmp_path``; where a Save must be handed
*during* a write, or a write must fail, a ``Mock(spec=Records)`` does so before handing on to the real one. The rename
is a real :class:`~rehuco_core.RenameCoordinator`'s; the rename barrier itself is mocked where only its use is asked.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any, Final
from unittest.mock import MagicMock, Mock

from borco_core import Presence
from pytest import raises
from pytest_mock import MockerFixture
from rehuco_core import (
    JobWaiting,
    RecordConflict,
    RecordLockedError,
    Records,
    RecordVersion,
    RenameCoordinator,
    ResourceKey,
    ResourceLocation,
    SavedRecord,
    SaveOutcome,
    SavePayload,
    SaveRecordJob,
    rebase_payload,
)

from rehuco_core_tests.access.test_records import UNKNOWN, USERNAME, on_disk, tutorial_data, write_record
from rehuco_core_tests.test_save_record_job import MODULE, VERSION, fake_payload, snapshot

DISK_FULL: Final = "disk full"
"""The failure a scripted write raises."""

CREATED: Final = "2026-10-21T00:00:00Z"
"""The ``created`` stamp an earlier write left."""

WRITTEN_VERSION: Final = RecordVersion("written-meta", "written-file", ())
"""The version an earlier write left, for the payloads no save reads."""


def disk_full() -> None:
    """Fail a write as a full disk would.

    :raises OSError: always.
    """
    raise OSError(DISK_FULL)


def scripted_records(actions: list[Callable[[], object]]) -> Mock:
    """Records that save for real, each save first running the next of ``actions`` -- which may raise instead.

    :param actions: what each save does first, in order; saves past the list just save.
    :returns: the mock.
    """
    real = Records()
    records = Mock(spec=Records)

    def save(*args: Any, **kwargs: Any) -> SavedRecord:
        """Run the next action, then save for real.

        :param args: the save's positional arguments.
        :param kwargs: its keyword arguments.
        :returns: the real save's record.
        """
        if actions:
            actions.pop(0)()
        return real.save(*args, **kwargs)

    records.save.side_effect = save
    return records


def resource(tmp_path: Path) -> Path:
    """Write a record in a resource folder of its own.

    :param tmp_path: the test's folder.
    :returns: the record's path.
    """
    folder = tmp_path / "sculpting"
    folder.mkdir()
    return write_record(folder / "info.rehu", tutorial_data()).path


def version_now(path: Path) -> RecordVersion | None:
    """The record's version as a fresh read finds it.

    :param path: the record.
    :returns: its version.
    """
    return Records().load(ResourceKey(path), username=USERNAME, unknown_username=UNKNOWN).version


# region rebase_payload
def test_rebase_puts_the_later_edits_onto_what_was_written() -> None:
    """A later Save moved onto an earlier save's write keeps the write's stamps and merged fields, adds only what the
    user changed since, and is checked against the written version.

    **Test steps:**

    * build an earlier snapshot, a later one that also changes the description and discards a second block, and the
      outcome the earlier one landed with a ``created`` stamp and ``bob``'s merged rating
    * rebase the later snapshot onto it
    * verify the payload is the written record with the later description, the base is the written version and the
      base payload the written record, each a copy of it, the outcome itself untouched
    * verify only the block the earlier save had not discarded is left to log, it is no first save, and the later
      snapshot's path, user and dropped blocks are kept
    """
    landed_from = fake_payload(discarded=("audiopack",))
    newer = fake_payload(
        payload=tutorial_data(description="later"),
        discarded=("audiopack", "reference_images"),
        dropped=("reference_images",),
        first_save=True,
    )
    written = tutorial_data({"bob": {"rating": 2}}, created=CREATED)
    outcome = SaveOutcome(written, WRITTEN_VERSION, None, True)

    rebased = rebase_payload(newer, landed_from, outcome)

    assert rebased.payload == tutorial_data({"bob": {"rating": 2}}, created=CREATED, description="later")
    assert rebased.base == WRITTEN_VERSION
    assert rebased.base_payload == written
    assert rebased.base_payload is not written
    assert rebased.payload is not written
    assert written == tutorial_data({"bob": {"rating": 2}}, created=CREATED)
    assert rebased.discarded == ("reference_images",)
    assert rebased.first_save is False
    assert (rebased.path, rebased.username, rebased.dropped) == (newer.path, newer.username, newer.dropped)


# region a Save handed while the job writes
def test_a_save_handed_during_a_write_is_rebased_and_written_by_the_same_run(tmp_path: Path) -> None:
    """A Save handed while a write is under way is at once what the job hands back as the record's saved state, and the
    same run writes it right after, moved onto the first write, so it never conflicts with it; the job lands once.

    **Test steps:**

    * write a record; snapshot it with a new description, and again with that and a new title
    * make the first save hand the job the second snapshot, noting what the job holds then
    * write; verify, mid-write, the job took it and handed it back while still writing the first
    * verify the run saved twice, the file holds both edits, and the second write was checked against the first's
    * verify the job holds what it wrote and still hands back the second snapshot, and a later replace is refused
    """
    path = resource(tmp_path)
    first = snapshot(path, description="first")
    second = snapshot(path, description="first", title="second")
    seen: list[tuple[bool, SavePayload | None, SavePayload | None]] = []
    records = scripted_records([lambda: seen.append((job.replace(second), job.handed, job.payload))])
    job = SaveRecordJob(first, records=records, coordinator=None)

    result = job.write()

    assert seen == [(True, second, first)]
    assert records.save.call_count == 2
    stored = on_disk(path)
    assert (stored["core"]["description"], stored["core"]["title"]) == ("first", "second")
    after_first = records.save.call_args_list[1].args[2]
    assert after_first != first.base
    written = job.payload
    assert written is not None
    assert written.base == after_first
    assert job.result is result
    assert result.version == version_now(path)
    assert job.handed is second
    assert not job.replace(snapshot(path, description="third"))


def test_a_failure_before_anything_landed_keeps_the_save_handed_meanwhile(tmp_path: Path) -> None:
    """A write that fails before anything landed leaves the Save handed during it as the job's data, as handed, and a
    retry writes it.

    **Test steps:**

    * write a record; snapshot it twice, the second with another description
    * make the first save hand the job the second snapshot, then find the lock held; write and verify it waits
    * verify the job holds and hands back the second snapshot unchanged
    * reset and write again; verify the file holds the second snapshot's description
    """
    path = resource(tmp_path)
    second = snapshot(path, description="second")

    def hand_then_find_locked() -> None:
        """Hand the job a later Save, then find the lock held.

        :raises RecordLockedError: always.
        """
        job.replace(second)
        raise RecordLockedError(path, None)

    job = SaveRecordJob(
        snapshot(path, description="first"), records=scripted_records([hand_then_find_locked]), coordinator=None
    )

    with raises(JobWaiting):
        job.write()

    assert job.payload is second
    assert job.handed is second
    job.reset()
    job.write()
    assert on_disk(path)["core"]["description"] == "second"


def test_a_failure_after_a_landed_write_moves_the_save_handed_meanwhile_onto_it(tmp_path: Path) -> None:
    """A Save handed during a run's second write, which fails, is moved onto the first write that landed, so the retry
    does not conflict with it.

    **Test steps:**

    * write a record; snapshot it three times from the same read: a description, then that and a title, then all
      that and a note
    * make the first save hand the job the second snapshot, and the second save hand it the third and fail
    * write; verify the failure escapes
    * verify the job holds the third snapshot moved onto the first write -- based on its version -- and hands back
      the third as handed
    * reset and write again; verify the file holds all three edits
    """
    path = resource(tmp_path)
    second = snapshot(path, description="first", title="second")
    third = snapshot(path, description="first", title="second", notes="third")

    def hand_then_fail() -> None:
        """Hand the job a later Save, then fail the write.

        :raises OSError: always.
        """
        job.replace(third)
        disk_full()

    records = scripted_records([lambda: job.replace(second), hand_then_fail])
    job = SaveRecordJob(snapshot(path, description="first"), records=records, coordinator=None)

    with raises(OSError, match=DISK_FULL):
        job.write()

    after_first = version_now(path)
    held = job.payload
    assert held is not None
    assert held.base == after_first
    assert held.payload["core"]["notes"] == "third"
    assert job.handed is third
    job.reset()
    job.write()
    stored = on_disk(path)
    assert (stored["core"]["description"], stored["core"]["title"], stored["core"]["notes"]) == (
        "first",
        "second",
        "third",
    )


def test_a_save_handed_after_a_run_failed_past_a_landed_write_is_moved_onto_it(tmp_path: Path) -> None:
    """Once a run landed one write and failed the next, a later Save made against the version before is moved onto the
    landed write, and one made against the landed write is taken as it is.

    **Test steps:**

    * write a record; snapshot it twice from the same read: a description, then that and a title
    * make the first save hand the job the second snapshot, and the second save fail; write and verify it fails
    * hand the job a third snapshot taken before the run; verify it is moved onto the landed write
    * hand it a fourth, read after the landed write; verify it is held as handed
    * reset and write again; verify the file holds the fourth's edit and the landed write's
    """
    path = resource(tmp_path)
    second = snapshot(path, description="first", title="second")
    third = snapshot(path, description="first", title="third")
    records = scripted_records([lambda: job.replace(second), disk_full])
    job = SaveRecordJob(snapshot(path, description="first"), records=records, coordinator=None)
    with raises(OSError, match=DISK_FULL):
        job.write()
    after_first = version_now(path)

    assert job.replace(third)
    moved = job.payload
    assert moved is not None
    assert moved.base == after_first
    assert moved.payload["core"]["title"] == "third"
    fourth = snapshot(path, notes="fourth")
    assert job.replace(fourth)
    assert job.payload is fourth

    job.reset()
    job.write()
    stored = on_disk(path)
    assert (stored["core"]["description"], stored["core"]["notes"]) == ("first", "fourth")


# region renames and the rename barrier
def test_a_save_follows_an_in_app_rename_of_its_record(tmp_path: Path) -> None:
    """A record renamed in the app while its save waits is written where it went, and the job says so.

    **Test steps:**

    * write a record in its own folder, and build a save of an edit to it, tracked through a real coordinator
    * rename the folder through the coordinator; verify the job's source is the renamed record
    * write; verify the renamed record holds the edit, the payload names it, and the old path is not recreated
    """
    path = resource(tmp_path)
    coordinator = RenameCoordinator()
    job = SaveRecordJob(snapshot(path, description="edited"), coordinator=coordinator)

    renamed = coordinator.rename(path, "carving")

    assert job.source == renamed
    job.write()
    payload = job.payload
    assert payload is not None
    assert payload.path == renamed
    assert on_disk(renamed)["core"]["description"] == "edited"
    assert not path.parent.exists()


def test_a_job_handed_its_first_save_tracks_it_and_follows_a_later_path(tmp_path: Path) -> None:
    """A job built empty starts following its record when handed one, keeps following it across a rename and a Save
    made there, and follows a Save that names another path.

    **Test steps:**

    * build an empty job over a real coordinator, and hand it a save of a record; verify its source is the record
    * rename the record's folder; verify the source followed
    * hand it a save made at the renamed record, then rename again; verify the source followed again
    * hand it a save of a record elsewhere; verify the source is that record
    """
    path = resource(tmp_path)
    coordinator = RenameCoordinator()
    job = SaveRecordJob(coordinator=coordinator)

    assert job.replace(snapshot(path))
    assert job.source == path
    renamed = coordinator.rename(path, "carving")
    assert job.source == renamed
    assert job.replace(snapshot(renamed, description="edited"))
    again = coordinator.rename(renamed, "modelling")
    assert job.source == again
    elsewhere = fake_payload(tmp_path / "elsewhere" / "info.rehu")
    assert job.replace(elsewhere)
    assert job.source == elsewhere.path


def test_a_job_with_no_coordinator_answers_its_payloads_path() -> None:
    """With no rename barrier the job follows nothing: its source is the path of what it holds.

    **Test steps:**

    * build a job with no coordinator; verify its source is its payload's path
    * hand it a payload at another path; verify the source is that path
    """
    first = fake_payload()
    job = SaveRecordJob(first, coordinator=None)

    assert job.source == first.path
    later = fake_payload(first.path.parent.parent / "carving" / "info.rehu")
    job.replace(later)
    assert job.source == later.path


def test_the_write_is_made_inside_the_rename_barrier(mocker: MockerFixture, tmp_path: Path) -> None:
    """The save is made while the coordinator holds the rename barrier, so a rename never moves the record from under
    it.

    **Test steps:**

    * patch the share present, mock a coordinator that tracks the record where it is and whose hold notes entry and
      exit, and mock records whose save notes itself
    * write; verify the save came after entering the hold and before leaving it
    """
    mocker.patch(f"{MODULE}.presence_of", return_value=Presence.PRESENT)
    path = resource(tmp_path)
    events: list[str] = []
    hold = MagicMock()
    hold.__enter__.side_effect = lambda *_: events.append("enter")
    hold.__exit__.side_effect = lambda *_: events.append("exit")
    coordinator = Mock(spec=RenameCoordinator)
    coordinator.track.side_effect = ResourceLocation
    coordinator.holding.return_value = hold
    records = Mock(spec=Records)
    records.save.side_effect = lambda *_, **__: events.append("save") or SavedRecord(VERSION, None, False)

    SaveRecordJob(fake_payload(path), records=records, coordinator=coordinator).write()

    assert events == ["enter", "save", "exit"]


# region a first save
def test_a_first_save_onto_a_record_created_meanwhile_is_a_conflict(mocker: MockerFixture, tmp_path: Path) -> None:
    """A record saved for the first time that someone else created meanwhile is not written over: the save fails as a
    conflict carrying the other record, kept on the job.

    **Test steps:**

    * patch the checksum move; build a first save of a new record, then write another record at its path
    * verify the write raises a conflict, the job keeps it, and it carries the other record
    * verify the file is the other writer's, untouched, and no checksums were moved
    """
    take = mocker.patch(f"{MODULE}.take_enclosing_claims")
    path = tmp_path / "info.rehu"
    job = SaveRecordJob(SavePayload(path, USERNAME, tutorial_data(), None, None, first_save=True), coordinator=None)
    write_record(path, tutorial_data(description="theirs"))
    before = path.read_text(encoding="utf-8")

    with raises(RecordConflict) as caught:
        job.write()

    assert job.conflict is caught.value
    assert caught.value.theirs.data["core"]["description"] == "theirs"
    assert path.read_text(encoding="utf-8") == before
    take.assert_not_called()
