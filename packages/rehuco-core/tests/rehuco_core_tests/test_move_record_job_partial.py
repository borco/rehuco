"""Tests for the move job's partial copy (#634): where it is said to be, kept or taken back as whoever gives the move
up asks, and never taken back through a destination that does not answer.

Split from :mod:`test_move_record_job`, whose fixtures and helpers are imported by name.
"""

import logging
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID

from pytest import LogCaptureFixture, raises
from pytest_mock import MockerFixture
from rehuco_core import (
    JobCanceled,
    JobPaused,
    MoveMode,
    MovePhase,
    MoveRecordJob,
    PartialOutputJob,
    VerifiedCopyError,
    generate_checksums,
)

from rehuco_core_tests.test_move_record_job import (  # noqa: F401  # pylint: disable=unused-import
    CONTENT,
    DESTINATION_ROOT,
    INTO,
    NEW_NAME,
    SOURCE_ROOT,
    fixture_control,
    fixture_host,
    fixture_roots,
    make_record,
    mover,
    synchronous_threads,
    target_of,
)
from rehuco_core_tests.test_move_record_job_offline import offline


def paused_copy(record: Path, host: MagicMock, control: MagicMock) -> MoveRecordJob:
    """A copy of ``record`` paused once it reported progress: its first files at the destination.

    :param record: the source ``.rehu``.
    :param host: the host.
    :param control: the engine's face, made to pause the job.
    :returns: the paused job.
    """
    job = mover(record, host, check_source=False)
    control.report.side_effect = lambda done, total=None: job.pause() if done else None
    with raises(JobPaused):
        job.run(control)
    control.report.side_effect = None
    return job


def test_a_copy_part_way_says_where_its_partial_copy_is(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock
) -> None:
    """A copy with files at the destination names their folder; before it wrote anything, and once done, there is
    none.

    **Test steps:**

    * check a move not started has no partial copy, and is one that offers it
    * pause a copy part-way: its partial copy is the record's folder at the destination
    * run it to the end: it has none
    """
    record = make_record(roots[SOURCE_ROOT])
    assert isinstance(mover(record, host), PartialOutputJob)
    assert mover(record, host).partial is None

    job = paused_copy(record, host, control)

    assert job.partial == target_of(roots)
    job.resume()
    job.run(control)
    assert job.partial is None


def test_a_file_record_partial_copy_is_the_folder_its_files_go_into(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock
) -> None:
    """A file record's copy is a set of files beside others: its partial copy is named by their folder.

    **Test steps:**

    * make a file record, and pause its copy part-way
    * check its partial copy is the destination folder
    """
    folder = roots[SOURCE_ROOT] / "Loose"
    folder.mkdir(parents=True)
    (folder / "clip.mp4").write_bytes(CONTENT)
    record = folder / "clip.rehu"
    record.write_text("{}")
    generate_checksums(record)

    job = paused_copy(record, host, control)

    assert job.partial == roots[DESTINATION_ROOT].joinpath(*INTO.parts)


def test_a_rename_has_no_partial_copy(roots: dict[UUID, Path], host: MagicMock) -> None:
    """A rename never has files in two places.

    **Test steps:**

    * build a rename in its move phase, with a journal entry
    * check it has no partial copy
    """
    job = mover(make_record(roots[SOURCE_ROOT]), host, mode=MoveMode.RENAME)
    job.phase = MovePhase.MOVE
    job.journal.wrote(NEW_NAME)

    assert job.partial is None


def test_a_running_copy_canceled_with_its_copy_kept_leaves_it_and_a_retry_resumes(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock
) -> None:
    """A cancel asked to keep the copy leaves it; a retry of the canceled row goes on from it.

    **Test steps:**

    * ask a copy to keep its partial copy, and cancel it once it reported progress
    * check the cancel came out and the copy is still at the destination
    * reset the job, as a retry does, and run it: the record moved
    """
    record = make_record(roots[SOURCE_ROOT])
    job = mover(record, host, check_source=False)
    job.keep_partial(True)
    control.report.side_effect = lambda done, total=None: job.cancel() if done else None

    with raises(JobCanceled):
        job.run(control)

    assert target_of(roots).exists()
    control.report.side_effect = None
    job.reset()
    job.run(control)

    assert not record.parent.exists()
    assert (target_of(roots) / "content.zip").read_bytes() == CONTENT


def test_an_idle_copy_given_up_on_with_its_copy_kept_leaves_it(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, mocker: MockerFixture
) -> None:
    """A paused copy canceled with its copy kept is not taken back when the queue gives it up.

    **Test steps:**

    * pause a copy part-way, ask it to keep its partial copy, and give it up
    * check the copy is still at the destination
    """
    record = make_record(roots[SOURCE_ROOT])
    synchronous_threads(mocker)
    job = paused_copy(record, host, control)
    job.keep_partial(True)

    job.abandon()

    assert target_of(roots).exists()
    assert job.partial == target_of(roots)


def test_a_refused_copy_is_taken_back_even_when_asked_to_keep_it(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, mocker: MockerFixture
) -> None:
    """Keeping is a cancel's choice: a copy the check refuses is unverified, and goes regardless.

    **Test steps:**

    * ask a move to keep its partial copy, make the copy's check refuse it, and run it
    * check the refusal came out and the destination root holds nothing
    """
    record = make_record(roots[SOURCE_ROOT])
    mocker.patch(
        "rehuco_core.move_record_job.VerifiedCopy.verify_target",
        side_effect=VerifiedCopyError("The copy did not match."),
    )
    job = mover(record, host)
    job.keep_partial(True)

    with raises(VerifiedCopyError):
        job.run(control)

    assert not roots[DESTINATION_ROOT].exists()


def test_a_retry_forgets_a_kept_copy_choice(roots: dict[UUID, Path], host: MagicMock, control: MagicMock) -> None:
    """A retried move starts afresh: a later cancel of it takes its copy back unless asked again.

    **Test steps:**

    * ask a move to keep its partial copy, then reset it, as a retry does
    * cancel it once it reported progress: the destination root holds nothing
    """
    record = make_record(roots[SOURCE_ROOT])
    job = mover(record, host, check_source=False)
    job.keep_partial(True)
    job.reset()
    control.report.side_effect = lambda done, total=None: job.cancel() if done else None

    with raises(JobCanceled):
        job.run(control)

    assert not roots[DESTINATION_ROOT].exists()


def test_a_retried_copy_given_up_on_before_it_copies_again_is_still_named_and_taken_back(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, mocker: MockerFixture
) -> None:
    """A retry starts over from the source check with its copy kept, so the copy is one to ask about and take back
    there too.

    **Test steps:**

    * pause a copy part-way and reset it, as a retry does
    * check it is in its source phase and still names its partial copy
    * give it up: the destination root holds nothing, and no partial copy is left to name
    """
    record = make_record(roots[SOURCE_ROOT])
    synchronous_threads(mocker)
    job = paused_copy(record, host, control)
    job.reset()

    assert job.phase is MovePhase.SOURCE
    assert job.partial == target_of(roots)

    job.abandon()

    assert not roots[DESTINATION_ROOT].exists()
    assert job.partial is None


def test_a_copy_that_wrote_nothing_has_nothing_to_leave(
    roots: dict[UUID, Path], host: MagicMock, mocker: MockerFixture, caplog: LogCaptureFixture
) -> None:
    """A move given up on before it copied anything says nothing of a copy left behind, its destination away or not.

    **Test steps:**

    * make the destination's share not answer, and give up a move that never ran
    * check the log says nothing of a copy left in place
    """
    record = make_record(roots[SOURCE_ROOT])
    synchronous_threads(mocker)
    probe = offline(mocker, roots[DESTINATION_ROOT])
    job = mover(record, host)

    with caplog.at_level(logging.WARNING):
        job.abandon()

    probe.assert_not_called()
    assert "left in place" not in caplog.text


def test_a_discarded_partial_copy_is_removed(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, mocker: MockerFixture
) -> None:
    """Clearing a row whose copy was kept removes the copy, on a thread of its own.

    **Test steps:**

    * pause a copy part-way, and discard its partial copy
    * check the destination root holds nothing, the original is whole, and no partial copy is left to name
    """
    record = make_record(roots[SOURCE_ROOT])
    synchronous_threads(mocker)
    job = paused_copy(record, host, control)

    job.discard_partial()

    assert not roots[DESTINATION_ROOT].exists()
    assert (record.parent / "content.zip").read_bytes() == CONTENT
    assert job.partial is None


def test_a_copy_whose_destination_does_not_answer_is_left_and_said_so(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, mocker: MockerFixture, caplog: LogCaptureFixture
) -> None:
    """Nothing is removed through a share that does not answer: the copy is left, logged, and still named, so a later
    clear can offer to remove it.

    **Test steps:**

    * pause a copy part-way, make the destination's share not answer, and discard its partial copy
    * check the copy is still there, the log says so, and the job still names it
    """
    record = make_record(roots[SOURCE_ROOT])
    synchronous_threads(mocker)
    job = paused_copy(record, host, control)
    offline(mocker, roots[DESTINATION_ROOT])

    with caplog.at_level(logging.WARNING):
        job.discard_partial()

    assert target_of(roots).exists()
    assert "the destination does not answer" in caplog.text
    assert job.partial == target_of(roots)
