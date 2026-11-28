"""Tests for the move job (#634) when an end goes away: every phase waits, its copy kept, rather than failing.

Which end answers is :func:`borco_core.presence_of`'s to say, tested in borco-core; here it is patched per folder.
Split from :mod:`test_move_record_job`, whose fixtures and helpers are imported by name.
"""

import errno
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

from borco_core import Presence
from pytest import LogCaptureFixture, raises
from pytest_mock import MockerFixture
from rehuco_core import (
    ChecksumReport,
    JobWaiting,
    LeftoversRemoved,
    MoveMode,
    MovePhase,
    RenameCoordinator,
    VerifiedCopy,
    VerifiedCopyError,
)
from rehuco_core.save_record_job import OFFLINE_RETRY_SECONDS

from rehuco_core_tests.test_move_record_job import (  # noqa: F401  # pylint: disable=unused-import
    CONTENT,
    DESTINATION_ROOT,
    MODULE,
    SOURCE_ROOT,
    fixture_control,
    fixture_host,
    fixture_roots,
    make_record,
    mover,
    synchronous_threads,
    target_of,
)

GONE_AWAY = OSError(errno.EIO, "the share went away")


def offline(mocker: MockerFixture, *folders: Path) -> MagicMock:
    """Make every path under ``folders`` read as on a share that does not answer, every other as present.

    :param mocker: pytest-mock fixture.
    :param folders: the folders whose share is off.
    :returns: the patched probe.
    """

    def presence(path: Path, *_: Any, **__: Any) -> Presence:
        return Presence.OFFLINE if any(path.is_relative_to(folder) for folder in folders) else Presence.PRESENT

    return mocker.patch(f"{MODULE}.presence_of", side_effect=presence)


def failing_after(real: Callable[..., Any], calls: int, error: OSError) -> Callable[..., Any]:
    """A stand-in for ``real`` that does what it does ``calls`` times, then raises ``error``.

    :param real: the patched function, unbound.
    :param calls: how many calls go through.
    :param error: what every later call raises.
    :returns: the stand-in, for an ``autospec`` patch.
    """
    made: list[int] = []

    def stand_in(*args: Any, **kwargs: Any) -> Any:
        made.append(1)
        if len(made) > calls:
            raise error
        return real(*args, **kwargs)

    return stand_in


# region each phase waits
def test_a_source_verify_whose_share_goes_away_waits(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, mocker: MockerFixture
) -> None:
    """The original's verify losing its share waits for it, as long as a save waits, naming the source.

    **Test steps:**

    * make the source verify fail with an I/O error and the source root's share not answer, and move a record
    * check the move waits in its source phase, for the save's interval, saying it waits for the source
    """
    record = make_record(roots[SOURCE_ROOT])
    offline(mocker, roots[SOURCE_ROOT])
    mocker.patch(f"{MODULE}.verify_checksums", side_effect=GONE_AWAY)
    job = mover(record, host)

    with raises(JobWaiting, match="Waiting for the source") as waiting:
        job.run(control)

    assert waiting.value.retry_after == OFFLINE_RETRY_SECONDS
    assert "went away" in waiting.value.reason
    assert job.phase is MovePhase.SOURCE


def test_a_copy_whose_destination_goes_away_waits_and_resumes(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, mocker: MockerFixture
) -> None:
    """A copy losing its destination mid-way keeps what it wrote, and once the share is back goes on from there.

    **Test steps:**

    * let the copy write one file, then fail the next with the destination's share not answering
    * check the move waits in its move phase, the file written and the journal kept
    * let the share answer again and run the move: it lands, the original gone
    """
    record = make_record(roots[SOURCE_ROOT])
    probe = offline(mocker, roots[DESTINATION_ROOT])
    copy_file = mocker.patch.object(
        VerifiedCopy, "copy_file", autospec=True, side_effect=failing_after(VerifiedCopy.copy_file, 1, GONE_AWAY)
    )
    job = mover(record, host, check_source=False)

    with raises(JobWaiting, match="Waiting for the destination"):
        job.run(control)

    assert job.phase is MovePhase.MOVE
    assert job.journal.written
    assert (target_of(roots) / "content.zip").read_bytes() == CONTENT
    mocker.stop(copy_file)
    mocker.stop(probe)

    job.run(control)

    assert job.phase is MovePhase.DONE
    assert not record.parent.exists()
    assert (target_of(roots) / "info00.jpg").read_bytes() == b"shot"


def test_a_target_check_that_could_not_read_a_dead_share_waits_and_keeps_the_copy(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, mocker: MockerFixture
) -> None:
    """A check of the copy refused because its share went away is no verdict: the copy stays, and the wait does not
    claim a mismatch.

    **Test steps:**

    * make the copy's check refuse it with the destination's share not answering, and move a record
    * check the move waits in its target phase, the copy still there, the reason naming no mismatch
    """
    record = make_record(roots[SOURCE_ROOT])
    offline(mocker, roots[DESTINATION_ROOT])
    mocker.patch.object(VerifiedCopy, "verify_target", side_effect=VerifiedCopyError("The copy did not match."))
    job = mover(record, host)

    with raises(JobWaiting, match="Waiting for the destination") as waiting:
        job.run(control)

    assert "did not match" not in waiting.value.reason
    assert job.phase is MovePhase.TARGET
    assert (target_of(roots) / "content.zip").read_bytes() == CONTENT


def test_a_reconcile_whose_source_goes_away_waits(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, mocker: MockerFixture
) -> None:
    """Bringing the copy level with the original waits for the original's share.

    **Test steps:**

    * make the reconcile fail with the source's share not answering, and move a record
    * check the move waits in its finish phase, the original whole
    """
    record = make_record(roots[SOURCE_ROOT])
    offline(mocker, roots[SOURCE_ROOT])
    mocker.patch.object(VerifiedCopy, "reconcile", side_effect=GONE_AWAY)
    job = mover(record, host)

    with raises(JobWaiting, match="Waiting for the source"):
        job.run(control)

    assert job.phase is MovePhase.FINISH
    assert record.exists()


def test_a_detach_whose_source_goes_away_waits(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, mocker: MockerFixture
) -> None:
    """The original stopping being a record, on the host's thread, waits for its share too.

    **Test steps:**

    * make the detach fail with the source's share not answering, and move a record
    * check the move waits in its finish phase, the original still a record
    """
    record = make_record(roots[SOURCE_ROOT])
    offline(mocker, roots[SOURCE_ROOT])
    mocker.patch.object(VerifiedCopy, "detach_source", side_effect=GONE_AWAY)
    job = mover(record, host)

    with raises(JobWaiting, match="Waiting for the source"):
        job.run(control)

    assert job.phase is MovePhase.FINISH
    assert record.exists()


def test_a_cleanup_whose_source_is_away_removes_nothing_and_finishes_later(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, mocker: MockerFixture
) -> None:
    """What is left of the original is not removed through a share that does not answer: the move waits for it.

    **Test steps:**

    * make the source's share not answer, and move a record
    * check the move waits in its cleanup phase, the cleanup kept and no removal tried
    * let the share answer, and run again: the move is done and clean
    """
    record = make_record(roots[SOURCE_ROOT])
    probe = offline(mocker, roots[SOURCE_ROOT])
    cleanup = mocker.patch(f"{MODULE}.remove_leftovers", autospec=True)
    job = mover(record, host)

    with raises(JobWaiting, match="Waiting for the source"):
        job.run(control)

    assert job.phase is MovePhase.CLEANUP and job.cleanup is not None
    cleanup.assert_not_called()
    mocker.stop(cleanup)
    mocker.stop(probe)

    job.run(control)

    assert job.phase is MovePhase.DONE
    assert job.outcome is not None and job.outcome.clean
    assert not record.parent.exists()


def test_a_cleanup_whose_source_goes_away_while_removing_waits_though_nothing_reads_as_left(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, mocker: MockerFixture
) -> None:
    """A share that is off reads as *nothing there*, which a removal takes for *already gone*: the cleanup asks the
    source again once it removed, rather than believe a removal that reported nothing left.

    **Test steps:**

    * make the removal remove nothing and report nothing left, the source's share going away under it, and move a
      record
    * check the move waits in its cleanup phase, the cleanup kept and the original's files still there
    * let the share answer and the removal work, and run again: the move is done and clean
    """
    record = make_record(roots[SOURCE_ROOT])
    probes: list[MagicMock] = []

    def going_offline(*_: Any) -> LeftoversRemoved:
        probes.append(offline(mocker, roots[SOURCE_ROOT]))
        return LeftoversRemoved(0, 0, [])

    cleanup = mocker.patch(f"{MODULE}.remove_leftovers", autospec=True, side_effect=going_offline)
    job = mover(record, host)

    with raises(JobWaiting, match="Waiting for the source"):
        job.run(control)

    assert job.phase is MovePhase.CLEANUP and job.cleanup is not None
    assert (record.parent / "content.zip").is_file()
    mocker.stop(cleanup)
    mocker.stop(probes[0])

    job.run(control)

    assert job.phase is MovePhase.DONE
    assert job.outcome is not None and job.outcome.clean
    assert not record.parent.exists()


def test_a_cleanup_left_with_its_shares_answering_is_reported_not_waited_for(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, mocker: MockerFixture
) -> None:
    """Only the source's share counts in the cleanup: an item left with it answering is said, as before, even with the
    destination's share off.

    **Test steps:**

    * make the cleanup leave an item with only the destination's share not answering, and move a record
    * check the move is done, its outcome naming the item
    """
    record = make_record(roots[SOURCE_ROOT])
    mocker.patch(f"{MODULE}.remove_leftovers", return_value=LeftoversRemoved(0, 0, ["kept.txt (Access is denied)"]))
    job = mover(record, host)
    real = VerifiedCopy.detach_source

    def going_offline(self: VerifiedCopy, listing: Any) -> Any:
        offline(mocker, roots[DESTINATION_ROOT])
        return real(self, listing)

    mocker.patch.object(VerifiedCopy, "detach_source", autospec=True, side_effect=going_offline)

    job.run(control)

    assert job.phase is MovePhase.DONE
    assert job.outcome is not None and "kept.txt" in job.outcome.summary


def test_a_rename_whose_share_goes_away_waits(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, mocker: MockerFixture
) -> None:
    """A rename losing its share waits, and stays a rename.

    **Test steps:**

    * make the rename fail with the source's share not answering, and move a record as a rename
    * check the move waits in its move phase, still a rename, the record where it was
    """
    record = make_record(roots[SOURCE_ROOT])
    offline(mocker, roots[SOURCE_ROOT])
    mocker.patch.object(RenameCoordinator, "rename", side_effect=GONE_AWAY)
    job = mover(record, host, mode=MoveMode.RENAME)

    with raises(JobWaiting, match="Waiting for the source"):
        job.run(control)

    assert job.mode is MoveMode.RENAME and job.phase is MovePhase.MOVE
    assert record.exists()


def test_a_check_after_a_rename_that_could_not_read_a_dead_share_waits_and_is_made_again(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, mocker: MockerFixture
) -> None:
    """A renamed record whose check could not read its share is not done: the move waits in its target phase, and
    checks again once the share answers.

    **Test steps:**

    * make the check after the rename report a missing file with the destination's share not answering, and rename
      with verifying on
    * check the move waits in its target phase
    * let the share answer and the check come out clean, and run again: the check was made again and the move is done
    """
    record = make_record(roots[SOURCE_ROOT])
    clean = ChecksumReport(statuses={"content.zip": "matched"})
    verify = mocker.patch(
        f"{MODULE}.verify_checksums", side_effect=[clean, ChecksumReport(statuses={"content.zip": "missing"}), clean]
    )
    probe = offline(mocker, roots[DESTINATION_ROOT])
    job = mover(record, host, mode=MoveMode.RENAME, check_renamed=True)

    with raises(JobWaiting, match="Waiting for the destination"):
        job.run(control)

    assert job.phase is MovePhase.TARGET
    mocker.stop(probe)

    job.run(control)

    assert job.phase is MovePhase.DONE
    assert verify.call_count == 3


def test_a_record_under_no_root_is_asked_about_through_its_own_folder(
    tmp_path: Path, host: MagicMock, control: MagicMock, mocker: MockerFixture
) -> None:
    """A record under no root has no root's folder to ask through: the folder its own entry is in is asked.

    **Test steps:**

    * make a record under no root, its folder's share not answering, and fail its verify
    * check the move waits for the source
    """
    record = make_record(tmp_path / "loose")
    offline(mocker, tmp_path / "loose")
    mocker.patch(f"{MODULE}.verify_checksums", side_effect=GONE_AWAY)

    with raises(JobWaiting, match="Waiting for the source"):
        mover(record, host, source_root=None).run(control)


# endregion


# region what still fails
def test_a_refusal_with_both_ends_answering_still_fails(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, mocker: MockerFixture
) -> None:
    """A denial with both shares answering is the disk's answer, not a share gone: the move fails, its copy kept.

    **Test steps:**

    * let both ends answer, make the copy's second file refused, and move a record
    * check the denial came out, and the first file is still at the destination
    """
    record = make_record(roots[SOURCE_ROOT])
    offline(mocker)
    denied = PermissionError(errno.EACCES, "denied")
    mocker.patch.object(
        VerifiedCopy, "copy_file", autospec=True, side_effect=failing_after(VerifiedCopy.copy_file, 1, denied)
    )

    with raises(PermissionError):
        mover(record, host, check_source=False).run(control)

    assert (target_of(roots) / "content.zip").read_bytes() == CONTENT


def test_a_verdict_with_both_ends_answering_still_refuses_and_takes_the_copy_back(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, mocker: MockerFixture
) -> None:
    """A copy the check refuses with both shares answering is refused as before: nothing stays at the destination.

    **Test steps:**

    * let both ends answer, make the copy's check refuse it, and move a record
    * check the refusal came out and the destination root holds nothing
    """
    record = make_record(roots[SOURCE_ROOT])
    offline(mocker)
    mocker.patch.object(VerifiedCopy, "verify_target", side_effect=VerifiedCopyError("The copy did not match."))

    with raises(VerifiedCopyError):
        mover(record, host).run(control)

    assert not roots[DESTINATION_ROOT].exists()


# endregion


# region before a start, and given up on
def test_a_record_whose_share_does_not_answer_may_start_and_a_gone_one_may_not(
    roots: dict[UUID, Path], host: MagicMock, mocker: MockerFixture
) -> None:
    """The check before every start lets a waiting move be tried again while its share is off; a record its share
    answers for without holding is gone.

    **Test steps:**

    * validate a move whose record cannot be seen because its share does not answer, then one whose record is gone
      from a share that answers
    * check the first may start and the second says the record no longer exists
    """
    record = roots[SOURCE_ROOT] / "Old" / "Intro" / "info.rehu"
    probe = offline(mocker, roots[SOURCE_ROOT])

    assert mover(record, host).validate() is None

    probe.side_effect = lambda *_, **__: Presence.GONE

    assert "no longer exists" in str(mover(record, host).validate())


def test_a_move_given_up_on_in_its_cleanup_with_its_source_away_leaves_the_rest(
    roots: dict[UUID, Path],
    host: MagicMock,
    control: MagicMock,
    mocker: MockerFixture,
    caplog: LogCaptureFixture,
) -> None:
    """Given up on in its cleanup while the source's share is off, the job removes what it can and says the rest
    stays, rather than raising on its own thread.

    **Test steps:**

    * make the cleanup leave an item with the source's share not answering, and move a record: it waits
    * give the job up
    * check the job stays in its cleanup phase and the log says what is left stays
    """
    record = make_record(roots[SOURCE_ROOT])
    synchronous_threads(mocker)
    offline(mocker, roots[SOURCE_ROOT])
    mocker.patch(
        f"{MODULE}.remove_leftovers", return_value=LeftoversRemoved(0, 0, ["content.zip (The network name is gone)"])
    )
    job = mover(record, host)
    with raises(JobWaiting):
        job.run(control)

    with caplog.at_level(logging.WARNING):
        job.abandon()

    assert job.phase is MovePhase.CLEANUP
    assert "what is left of the original stays" in caplog.text


# endregion
