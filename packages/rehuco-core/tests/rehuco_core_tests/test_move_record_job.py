"""Tests for the move job (#339): a copy across volumes in its kept phases, and a rename on one volume verified on
request. What the queue asks of the job, how it is written down and the host the app lends it are
`test_move_record_job_state`'s, which imports this module's fixtures."""

import errno
import logging
from pathlib import Path, PurePosixPath
from typing import Any, Final
from unittest.mock import MagicMock
from uuid import UUID, uuid4

from pytest import LogCaptureFixture, fixture, raises
from pytest_mock import MockerFixture
from rehuco_core import (
    ChecksumReport,
    ChecksumTrust,
    JobCancelled,
    JobControl,
    JobPaused,
    JobWaiting,
    LinkInRecordError,
    MoveMode,
    MovePhase,
    MoveRecordJob,
    RecordLockedError,
    RecordMoveHost,
    RenameCoordinator,
    RenameYieldTimeout,
    SourceChangedError,
    VerifiedCopy,
    VerifiedCopyError,
    generate_checksums,
    move_record_job,
)

from rehuco_core_tests.real_links import directory_link

CONTENT: Final = b"content bytes"
MODULE: Final = "rehuco_core.move_record_job"
NEW_NAME: Final = "Intro [2024]"
INTO: Final = PurePosixPath("Smith") / "2024"
SOURCE_ROOT: Final = UUID("00000000-0000-0000-0000-000000000001")
DESTINATION_ROOT: Final = UUID("00000000-0000-0000-0000-000000000002")


def make_record(root: Path, *, checksums: bool = True) -> Path:
    """A folder record at ``root/Old/Intro`` with one content file and a screenshot.

    :param root: the source root's folder.
    :param checksums: whether to generate its checksum record.
    :returns: its ``info.rehu``.
    """
    folder = root / "Old" / "Intro"
    folder.mkdir(parents=True)
    (folder / "content.zip").write_bytes(CONTENT)
    (folder / "info00.jpg").write_bytes(b"shot")
    record = folder / "info.rehu"
    record.write_text("{}")
    if checksums:
        generate_checksums(record)
    return record


@fixture(name="roots")
def fixture_roots(tmp_path: Path) -> dict[UUID, Path]:
    """Two roots' folders, by id.

    :param tmp_path: pytest's folder.
    :returns: the source root's and the destination root's.
    """
    return {SOURCE_ROOT: tmp_path / "a", DESTINATION_ROOT: tmp_path / "b"}


@fixture(name="host")
def fixture_host(roots: dict[UUID, Path]) -> MagicMock:
    """A host mapping both roots, with no save pending, running each step where it is asked.

    :param roots: the roots' folders.
    :returns: the host.
    """
    host = MagicMock(spec=RecordMoveHost)
    host.root_folder.side_effect = roots.get
    host.save_pending.return_value = False
    host.run_step.side_effect = lambda step, checkpoint: step()
    return host


@fixture(name="control")
def fixture_control() -> MagicMock:
    """The engine's face to a job.

    :returns: a stand-in recording each report.
    """
    return MagicMock(spec=JobControl)


def mover(record: Path | None, host: MagicMock, **options: Any) -> MoveRecordJob:
    """A move of ``record`` from the source root into :data:`INTO` under the destination root.

    :param record: the source ``.rehu``.
    :param host: the host.
    :param options: overrides of the job's other parameters.
    :returns: the job.
    """
    arguments: dict[str, Any] = {
        "source_root": SOURCE_ROOT,
        "destination_root": DESTINATION_ROOT,
        "into": INTO,
        "new_name": NEW_NAME,
        "coordinator": RenameCoordinator(),
        "trust": None,
        "host": host,
    } | options
    return MoveRecordJob(record, **arguments)


def synchronous_threads(mocker: MockerFixture) -> None:
    """Run what the job would hand a thread of its own at once, here, so a test sees it done.

    :param mocker: pytest-mock fixture.
    """
    thread = mocker.patch(f"{MODULE}.threading.Thread")
    thread.side_effect = lambda target, **_: MagicMock(start=target)


def target_of(roots: dict[UUID, Path]) -> Path:
    """Where a moved folder record lands.

    :param roots: the roots' folders.
    :returns: its folder at the destination.
    """
    return roots[DESTINATION_ROOT].joinpath(*INTO.parts) / NEW_NAME


# region a copy across volumes
def test_a_copy_moves_the_record_and_removes_the_original(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock
) -> None:
    """A copy runs its four phases: the original checked, copied, the copy checked, the original removed -- and the
    record is then where the job's source says, on the host's thread.

    **Test steps:**

    * move a folder record with its checksums from one root to the other
    * check the copy holds its files, the original is gone, the source and outcome name the copy, and the removal ran
      through the host
    """
    record = make_record(roots[SOURCE_ROOT])
    job = mover(record, host)

    job.run(control)

    target = target_of(roots)
    assert (target / "content.zip").read_bytes() == CONTENT
    assert not record.parent.exists()
    assert job.phase is MovePhase.DONE
    assert job.source == target / "info.rehu"
    assert job.outcome is not None and job.outcome.clean
    assert job.outcome.summary == f"Moved to {target.parent}"
    host.run_step.assert_called_once()


def test_a_record_with_no_checksums_is_not_moved(roots: dict[UUID, Path], host: MagicMock, control: MagicMock) -> None:
    """With nothing to check a copy against, the move stops before anything is written.

    **Test steps:**

    * move a folder record with no checksum record, creating missing ones off
    * check it raises and the destination root holds nothing
    """
    record = make_record(roots[SOURCE_ROOT], checksums=False)

    with raises(VerifiedCopyError, match="has no checksum record"):
        mover(record, host).run(control)

    assert not roots[DESTINATION_ROOT].exists()


def test_a_missing_record_is_made_first_when_allowed(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock
) -> None:
    """With creating allowed, the original is verified even with checking it turned off -- which writes its record --
    and the move goes on.

    **Test steps:**

    * move a folder record with no checksum record, checking the original off and creating missing ones on
    * check the move landed with a checksum record at the copy
    """
    record = make_record(roots[SOURCE_ROOT], checksums=False)

    mover(record, host, check_source=False, create_if_missing=True).run(control)

    assert (target_of(roots) / "info.checksum").is_file()


def test_a_complete_record_is_not_verified_when_that_is_turned_off(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, mocker: MockerFixture
) -> None:
    """Checking the original is a setting; the copy's check is not.

    **Test steps:**

    * move a folder record with its checksums, checking the original off, counting verifies
    * check one verify ran, at the copy
    """
    record = make_record(roots[SOURCE_ROOT])
    spy = mocker.spy(VerifiedCopy, "verify_target")
    verify = mocker.patch("rehuco_core.move_record_job.verify_checksums")

    mover(record, host, check_source=False).run(control)

    verify.assert_not_called()
    spy.assert_called_once()


def test_an_original_that_does_not_verify_is_not_moved(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, mocker: MockerFixture
) -> None:
    """A source that fails its own check is never copied.

    **Test steps:**

    * make the source verify report a mismatch
    * check the move raises naming it, and nothing reached the destination
    """
    record = make_record(roots[SOURCE_ROOT])
    mocker.patch(
        "rehuco_core.move_record_job.verify_checksums",
        return_value=ChecksumReport(statuses={"content.zip": "mismatched"}),
    )

    with raises(VerifiedCopyError, match="The original did not verify"):
        mover(record, host).run(control)

    assert not roots[DESTINATION_ROOT].exists()


def test_a_corrupted_copy_keeps_the_original(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, mocker: MockerFixture
) -> None:
    """A copy whose bytes differ from the record stops the move at its check, the original untouched -- and the copy
    is removed, as a cancel removes it: nothing unverified stays at the destination.

    **Test steps:**

    * let the copy run, then change a byte of the copied content
    * check the move raises at the target phase, the original is whole, and the destination root holds nothing
    """
    record = make_record(roots[SOURCE_ROOT])
    real = VerifiedCopy.copy

    def corrupting(self: VerifiedCopy, *args: Any, **kwargs: Any) -> None:
        real(self, *args, **kwargs)
        (self.target.parent / "content.zip").write_bytes(b"X" + CONTENT[1:])

    mocker.patch.object(VerifiedCopy, "copy", autospec=True, side_effect=corrupting)
    job = mover(record, host)

    with raises(VerifiedCopyError, match="did not match"):
        job.run(control)

    assert job.phase is MovePhase.TARGET
    assert (record.parent / "content.zip").read_bytes() == CONTENT
    assert not roots[DESTINATION_ROOT].exists()


def test_a_paused_copy_comes_back_from_its_saved_state_and_finishes(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock
) -> None:
    """A copy paused part-way is written down, and a job restored from that state finishes it.

    **Test steps:**

    * pause a move at its first checkpoint, which is in the copy, and capture its state
    * restore a new job from it and run that
    * check the paused job was in the move phase, and the restored one moved the record
    """
    record = make_record(roots[SOURCE_ROOT])
    job = mover(record, host, check_source=False)
    job.pause()

    with raises(JobPaused):
        job.run(control)

    assert job.phase is MovePhase.MOVE
    restored = mover(None, host)
    restored.restore_state(job.capture_state())
    restored.run(control)

    assert not record.parent.exists()
    assert (target_of(roots) / "content.zip").read_bytes() == CONTENT


def test_a_cancelled_copy_takes_back_what_it_wrote(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock
) -> None:
    """Cancelling a copy part-way removes what it wrote and made; the original is untouched.

    **Test steps:**

    * cancel a move once its copy has reported progress
    * check the cancel came out, the destination root holds nothing, and the original is whole
    """
    record = make_record(roots[SOURCE_ROOT])
    job = mover(record, host, check_source=False)
    control.report.side_effect = lambda done, total=None: job.cancel() if done else None

    with raises(JobCancelled):
        job.run(control)

    assert not roots[DESTINATION_ROOT].exists()
    assert (record.parent / "content.zip").read_bytes() == CONTENT


def test_a_cancel_that_cannot_take_everything_back_logs_what_stayed(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, mocker: MockerFixture, caplog: LogCaptureFixture
) -> None:
    """What a cancelled copy cannot remove is logged; the cancel still comes out.

    **Test steps:**

    * make taking a copy back leave one item, and cancel a move once its copy reported progress
    * check the cancel came out and the item was logged
    """
    record = make_record(roots[SOURCE_ROOT])
    mocker.patch.object(VerifiedCopy, "remove_copy", return_value=["kept.txt (Access is denied)"])
    job = mover(record, host, check_source=False)
    control.report.side_effect = lambda done, total=None: job.cancel() if done else None

    with caplog.at_level(logging.WARNING), raises(JobCancelled):
        job.run(control)

    assert "kept.txt (Access is denied)" in caplog.text


def test_a_move_with_nothing_to_move_or_nowhere_to_go_is_refused(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock
) -> None:
    """Run without the start check, a move with no record, or with a destination root unmapped, raises.

    **Test steps:**

    * run a move with no record, then one to a root this machine does not map
    * check each raises ``ValueError`` saying which
    """
    with raises(ValueError, match="no record"):
        mover(None, host).run(control)
    with raises(ValueError, match="not mapped"):
        mover(make_record(roots[SOURCE_ROOT]), host, destination_root=uuid4(), check_source=False).run(control)


def test_a_paused_copy_given_up_on_takes_back_what_it_wrote(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, mocker: MockerFixture
) -> None:
    """The queue never runs a paused job it cancels or removes; told so, the job takes its copy back itself.

    **Test steps:**

    * pause a copy once it has reported progress, then tell the job it was given up on
    * check the destination root holds nothing, and the original is whole
    """
    record = make_record(roots[SOURCE_ROOT])
    synchronous_threads(mocker)
    job = mover(record, host, check_source=False)
    control.report.side_effect = lambda done, total=None: job.pause() if done else None
    with raises(JobPaused):
        job.run(control)
    assert roots[DESTINATION_ROOT].exists()

    job.abandon()

    assert not roots[DESTINATION_ROOT].exists()
    assert (record.parent / "content.zip").read_bytes() == CONTENT


def test_a_copy_given_up_on_with_its_root_unmapped_is_left_and_said_so(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, mocker: MockerFixture, caplog: LogCaptureFixture
) -> None:
    """With the destination root no longer mapped there is nowhere to take the copy back from: it stays, logged.

    **Test steps:**

    * pause a copy once it has reported progress, unmap its destination root, and give the job up
    * check the copy is still there and the log says so
    """
    record = make_record(roots[SOURCE_ROOT])
    synchronous_threads(mocker)
    job = mover(record, host, check_source=False)
    control.report.side_effect = lambda done, total=None: job.pause() if done else None
    with raises(JobPaused):
        job.run(control)
    destination = roots.pop(DESTINATION_ROOT)

    with caplog.at_level(logging.WARNING):
        job.abandon()

    assert destination.exists()
    assert "was left in place" in caplog.text


def test_a_cancel_taken_back_leaves_the_copy_alone(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock
) -> None:
    """A cancel dropped by a resume before the run is no cancel: the move runs to its end and keeps its copy.

    **Test steps:**

    * cancel a move, resume it, and run it
    * check the record moved
    """
    record = make_record(roots[SOURCE_ROOT])
    job = mover(record, host)
    job.cancel()
    job.resume()

    job.run(control)

    assert (target_of(roots) / "info.rehu").is_file()
    assert not record.parent.exists()


def test_removing_the_original_waits_for_a_save(roots: dict[UUID, Path], host: MagicMock, control: MagicMock) -> None:
    """A save of the record still on its way would land in a folder about to go: the move waits for it.

    **Test steps:**

    * say a save of the record is pending, and move it
    * check the move waits at its finish phase, the original still there
    """
    record = make_record(roots[SOURCE_ROOT])
    host.save_pending.return_value = True
    job = mover(record, host)

    with raises(JobWaiting, match="save"):
        job.run(control)

    assert job.phase is MovePhase.FINISH
    assert record.exists()


def test_removing_the_original_waits_for_another_process_lock(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, mocker: MockerFixture
) -> None:
    """A record another process holds the lock of is being written: the move waits rather than removing it.

    **Test steps:**

    * make the record's lock read as held, and move it
    * check the move waits at its finish phase
    """
    record = make_record(roots[SOURCE_ROOT])
    mocker.patch(
        "rehuco_core.move_record_job.RecordFileLock.refuse_if_held", side_effect=RecordLockedError(record, None)
    )
    job = mover(record, host)

    with raises(JobWaiting, match="locked"):
        job.run(control)

    assert job.phase is MovePhase.FINISH


def test_what_the_original_kept_is_said_in_the_outcome(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, mocker: MockerFixture
) -> None:
    """A file of the original that will not go makes the move's outcome not clean, naming it.

    **Test steps:**

    * make the cleanup leave one item, and move the record
    * check the outcome is not clean and names it
    """
    record = make_record(roots[SOURCE_ROOT])
    mocker.patch(f"{MODULE}.remove_leftovers", return_value=["kept.txt (Access is denied)"])
    job = mover(record, host)

    job.run(control)

    assert job.outcome is not None and not job.outcome.clean
    assert "kept.txt (Access is denied)" in job.outcome.summary


def test_a_quit_before_the_cleanup_still_removes_what_is_left(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, mocker: MockerFixture
) -> None:
    """Once the original stopped being a record, what is left of it is written down: a retry stays in the cleanup,
    and a job restored from that state removes it.

    **Test steps:**

    * make the cleanup fail the first time, and move a record: the job stops in its cleanup phase, the copy whole
    * retry it in place: the phase stays
    * restore a new job from its state and run it: the original is gone, the left folders too
    """
    record = make_record(roots[SOURCE_ROOT])
    cleanup = mocker.patch(f"{MODULE}.remove_leftovers", side_effect=PermissionError(errno.EACCES, "denied"))
    job = mover(record, host, remove_empty_folders=True)

    with raises(PermissionError):
        job.run(control)

    assert job.phase is MovePhase.CLEANUP
    assert not record.exists() and (record.parent / "content.zip").exists()
    job.reset()
    assert job.phase is MovePhase.CLEANUP

    mocker.stop(cleanup)
    restored = mover(None, host)
    restored.restore_state(job.capture_state())
    restored.run(control)

    assert restored.phase is MovePhase.DONE and restored.cleanup is None
    assert not (roots[SOURCE_ROOT] / "Old").exists()
    assert restored.outcome is not None and restored.outcome.clean


def test_a_move_given_up_on_in_its_cleanup_finishes_removing_the_original(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, mocker: MockerFixture
) -> None:
    """The copy verified, so a cancel past that point takes nothing back: the job given up on finishes the cleanup,
    and the copy stays.

    **Test steps:**

    * make the cleanup fail once, and move a record: the job stops in its cleanup phase
    * give the job up
    * check the original is gone, the copy is whole, and the job is done
    """
    record = make_record(roots[SOURCE_ROOT])
    synchronous_threads(mocker)
    cleanup = mocker.patch(f"{MODULE}.remove_leftovers", side_effect=PermissionError(errno.EACCES, "denied"))
    job = mover(record, host)
    with raises(PermissionError):
        job.run(control)
    mocker.stop(cleanup)

    job.abandon()

    assert job.phase is MovePhase.DONE
    assert not record.parent.exists()
    assert (target_of(roots) / "content.zip").read_bytes() == CONTENT


def test_a_record_holding_a_link_is_not_moved_and_leaves_nothing(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock
) -> None:
    """A link found in the record refuses the move, and nothing is left at the destination.

    **Test steps:**

    * link an outside folder into a record, and move it with checking the original off
    * check the move raises, the destination root holds nothing, and the original is whole
    """
    record = make_record(roots[SOURCE_ROOT])
    outside = roots[SOURCE_ROOT].parent / "outside"
    outside.mkdir()
    directory_link(record.parent / "linked", outside)

    with raises(LinkInRecordError):
        mover(record, host, check_source=False).run(control)

    assert not roots[DESTINATION_ROOT].exists()
    assert record.exists()


def test_a_copy_stopped_by_anything_but_a_refusal_is_kept_to_resume_from(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, mocker: MockerFixture
) -> None:
    """A share that goes away is no verdict on the copy: what was copied stays, for a retry to resume from.

    **Test steps:**

    * make the copy's check fail with an I/O error, and move a record
    * check the error came out and the copy is still at the destination
    """
    record = make_record(roots[SOURCE_ROOT])
    mocker.patch.object(VerifiedCopy, "verify_target", side_effect=OSError(errno.EIO, "the share went away"))

    with raises(OSError, match="went away"):
        mover(record, host).run(control)

    assert (target_of(roots) / "content.zip").read_bytes() == CONTENT


def test_a_reader_that_does_not_let_go_makes_the_move_wait(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, mocker: MockerFixture
) -> None:
    """A reader still holding the record when the original is to be detached, or renamed, is waited for, not failed
    on.

    **Test steps:**

    * make the barrier time out, and move a record as a copy, then another as a rename
    * check each waits, the copy at its finish phase with the original whole
    """
    record = make_record(roots[SOURCE_ROOT])
    mocker.patch.object(RenameCoordinator, "run", side_effect=RenameYieldTimeout("A task is still reading."))
    copying = mover(record, host)
    renaming = mover(record, host, mode=MoveMode.RENAME, new_name="Other")

    with raises(JobWaiting, match="still reading"):
        copying.run(control)
    with raises(JobWaiting, match="still reading"):
        renaming.run(control)

    assert copying.phase is MovePhase.FINISH
    assert record.exists()


def test_an_original_that_changed_is_compared_again(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, mocker: MockerFixture
) -> None:
    """An original found changed when it is to be detached is brought level again, and then detached.

    **Test steps:**

    * make the first detach say the original changed, and move a record, counting the comparisons
    * check the copy was brought level twice, and the move landed
    """
    record = make_record(roots[SOURCE_ROOT])
    real = VerifiedCopy.detach_source
    calls: list[int] = []

    def changed_once(self: VerifiedCopy, listing: Any) -> Any:
        calls.append(1)
        if len(calls) == 1:
            raise SourceChangedError("The record changed while being moved.")
        return real(self, listing)

    mocker.patch.object(VerifiedCopy, "detach_source", autospec=True, side_effect=changed_once)
    reconcile = mocker.spy(VerifiedCopy, "reconcile")

    mover(record, host).run(control)

    assert reconcile.call_count == 2
    assert not record.parent.exists()


def test_the_original_place_is_forgotten_by_the_trust(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock
) -> None:
    """Once the original is gone, the trust it earned where it was is dropped; the copy earned its own.

    **Test steps:**

    * move a record with a trust stand-in
    * check the original's place was forgotten
    """
    record = make_record(roots[SOURCE_ROOT])
    trust = MagicMock(spec=ChecksumTrust)
    trust.trusted_since.return_value = None

    mover(record, host, trust=trust).run(control)

    trust.forget.assert_called_once_with(record)


def test_the_left_folders_go_when_asked(roots: dict[UUID, Path], host: MagicMock, control: MagicMock) -> None:
    """With the setting on, the folders the record left are removed while empty, up to its root.

    **Test steps:**

    * move a folder record with removing left-behind folders on
    * check its old parent folder is gone and its root is not
    """
    record = make_record(roots[SOURCE_ROOT])

    mover(record, host, remove_empty_folders=True).run(control)

    assert not (roots[SOURCE_ROOT] / "Old").exists()
    assert roots[SOURCE_ROOT].is_dir()


# endregion


# region a rename on one volume
def test_a_verified_rename_checks_before_and_after(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, mocker: MockerFixture
) -> None:
    """A rename with its setting on verifies the record, renames it on the host's thread, and verifies it again.

    **Test steps:**

    * move a folder record as a rename, verifying on, counting verifies
    * check two verifies ran, the record is at the destination, and the outcome names it
    """
    record = make_record(roots[SOURCE_ROOT])
    spy = mocker.spy(move_record_job, "verify_checksums")
    job = mover(record, host, mode=MoveMode.RENAME, check_renamed=True)

    job.run(control)

    assert spy.call_count == 2
    assert job.source == target_of(roots) / "info.rehu"
    assert job.outcome is not None and job.outcome.summary == f"Moved to {target_of(roots).parent}"


def test_an_unverified_rename_reads_nothing(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, mocker: MockerFixture
) -> None:
    """With its setting off, a rename is only the rename.

    **Test steps:**

    * move a folder record with no checksums as a rename, verifying off, removing left folders on
    * check nothing was verified, the record moved, and its old parent is gone
    """
    record = make_record(roots[SOURCE_ROOT], checksums=False)
    verify = mocker.patch("rehuco_core.move_record_job.verify_checksums")

    mover(record, host, mode=MoveMode.RENAME, remove_empty_folders=True).run(control)

    verify.assert_not_called()
    assert (target_of(roots) / "content.zip").is_file()
    assert not (roots[SOURCE_ROOT] / "Old").exists()


def test_a_rename_that_does_not_verify_after_says_so(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, mocker: MockerFixture
) -> None:
    """The record moved, so a failed check after it is reported as that, not as a failed move.

    **Test steps:**

    * make the first verify clean and the second report a mismatch, and rename with verifying on
    * check the move raises naming the check after, and the record is at the destination
    """
    record = make_record(roots[SOURCE_ROOT])
    mocker.patch(
        "rehuco_core.move_record_job.verify_checksums",
        side_effect=[ChecksumReport(statuses={"content.zip": "matched"}), ChecksumReport(statuses={"a": "missing"})],
    )
    job = mover(record, host, mode=MoveMode.RENAME, check_renamed=True)

    with raises(VerifiedCopyError, match="did not verify there"):
        job.run(control)

    assert job.phase is MovePhase.DONE
    assert (target_of(roots) / "info.rehu").is_file()


def test_a_rename_across_devices_becomes_a_copy(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, mocker: MockerFixture
) -> None:
    """A rename the system refuses as crossing devices is done as a verified copy instead.

    **Test steps:**

    * make the coordinator's rename raise ``EXDEV``, and move a folder record as a rename
    * check the job turned into a copy and the record moved
    """
    record = make_record(roots[SOURCE_ROOT])
    mocker.patch.object(RenameCoordinator, "rename", side_effect=OSError(errno.EXDEV, "cross-device link"))
    job = mover(record, host, mode=MoveMode.RENAME)

    job.run(control)

    assert job.mode is MoveMode.COPY
    assert not record.parent.exists()
    assert (target_of(roots) / "content.zip").read_bytes() == CONTENT


def test_a_rename_failing_otherwise_fails_the_move(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, mocker: MockerFixture
) -> None:
    """Any other refusal is the move's failure, and the job stays a rename.

    **Test steps:**

    * make the coordinator's rename raise a denial, and move a folder record as a rename
    * check the denial came out, and nothing was undone (a rename's cancel has nothing to take back)
    """
    record = make_record(roots[SOURCE_ROOT])
    mocker.patch.object(RenameCoordinator, "rename", side_effect=PermissionError(errno.EACCES, "denied"))
    job = mover(record, host, mode=MoveMode.RENAME)

    with raises(PermissionError):
        job.run(control)

    assert job.mode is MoveMode.RENAME


def test_a_cancelled_rename_has_nothing_to_take_back(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock
) -> None:
    """A rename cancelled before it ran leaves everything as it was.

    **Test steps:**

    * cancel a verified rename before it starts
    * check the cancel came out and the record is where it was
    """
    record = make_record(roots[SOURCE_ROOT])
    job = mover(record, host, mode=MoveMode.RENAME, check_renamed=True)
    job.cancel()

    with raises(JobCancelled):
        job.run(control)

    assert record.exists()


# endregion
