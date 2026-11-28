"""Tests for what a record's move says in the log as each of its steps ends (#713).

Split from :mod:`test_move_record_job`, whose fixtures and helpers are imported by name.
"""

import logging
from pathlib import Path
from typing import Final
from unittest.mock import MagicMock
from uuid import UUID

from pytest import LogCaptureFixture, mark, raises
from pytest_mock import MockerFixture
from rehuco_core import JobCanceled, JobPaused, LeftoversRemoved, MoveMode, MovePhase
from rehuco_core.move_step_log import MoveStepLog, counted, size_text

from rehuco_core_tests.test_move_record_job import (  # noqa: F401  # pylint: disable=unused-import
    DESTINATION_ROOT,
    MODULE,
    SOURCE_ROOT,
    fixture_control,
    fixture_host,
    fixture_roots,
    make_record,
    mover,
    target_of,
)

LABEL: Final = "Move - Intro"
"""What the job of a record made by :func:`make_record` is called."""


def said(caplog: LogCaptureFixture, label: str = LABEL) -> list[str]:
    """What the move said, each line without its label.

    :param caplog: pytest's log capture, at INFO.
    :param label: the move's.
    :returns: the lines, in the order they were written.
    """
    prefix = f"{label}: "
    return [
        record.getMessage().removeprefix(prefix)
        for record in caplog.records
        if record.name == MODULE and record.getMessage().startswith(prefix)
    ]


def size_of(folder: Path) -> int:
    """The size of what a folder holds.

    :param folder: the folder.
    :returns: the bytes its files hold, at any depth.
    """
    return sum(path.stat().st_size for path in folder.rglob("*") if path.is_file())


# region the lines of a copy
def test_a_copy_says_each_of_its_steps(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, caplog: LogCaptureFixture
) -> None:
    """A copy that goes well writes one line a step, in order, with the counts and the places.

    **Test steps:**

    * move a folder record of one content file across roots, checking the original first
    * check the lines: verified before, copied, the files no checksum covers compared, verified after, removed
    """
    record = make_record(roots[SOURCE_ROOT])
    original = record.parent.parent
    job = mover(record, host)

    with caplog.at_level(logging.INFO):
        job.run(control)

    target = target_of(roots)
    assert said(caplog) == [
        "verified the checksums of 1 file before copying: 1 matched",
        f"copied 4 files ({size_of(target)} bytes) to {target.parent}",
        "verified the checksums of 1 file after copying: 1 matched",
        "compared 2 files no checksum covers, byte for byte: info00.jpg, info.rehu",
        f"removed 4 files and 1 folder from {original}",
    ]


def test_a_resumed_copy_says_what_an_earlier_run_had_written(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, caplog: LogCaptureFixture
) -> None:
    """The copy line counts what the run wrote and, apart, what a run before it had.

    **Test steps:**

    * pause a move that skips its original's check, once its first file was written
    * restore it into a new job and run that
    * check the second run says it goes on from its move phase, and its copy line counts one file as already
      there
    """
    record = make_record(roots[SOURCE_ROOT])
    job = mover(record, host, check_source=False)
    control.report.side_effect = lambda done, total=None: job.pause() if done >= len(b"content bytes") else None
    with raises(JobPaused):
        job.run(control)
    control.report.side_effect = None
    restored = mover(None, host)
    restored.restore_state(job.capture_state())

    with caplog.at_level(logging.INFO):
        restored.run(control)

    assert said(caplog)[0] == "going on from its move phase"
    copied = [line for line in said(caplog) if line.startswith("copied")]
    assert len(copied) == 1 and copied[0].endswith("; 1 file already there from an earlier run")
    assert copied[0].startswith("copied 3 files (")


def test_a_move_with_no_check_before_says_none(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, caplog: LogCaptureFixture
) -> None:
    """A step that did not run says nothing: no verify line before a copy whose setting is off.

    **Test steps:**

    * move a record whose original is complete, with the check of the original off
    * check no line says the original was verified, and the copy was verified
    """
    record = make_record(roots[SOURCE_ROOT])

    with caplog.at_level(logging.INFO):
        mover(record, host, check_source=False).run(control)

    lines = said(caplog)
    assert not any("before copying" in line for line in lines)
    assert any("after copying" in line for line in lines)


def test_a_canceled_copy_says_it_took_the_copy_back(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, caplog: LogCaptureFixture
) -> None:
    """A copy taken back on a cancel says what it removed and from where.

    **Test steps:**

    * cancel a move once its copy has reported progress
    * check the lines say it was canceled, then that the copy was taken back, counting the files and folders it
      had written and made
    """
    record = make_record(roots[SOURCE_ROOT])
    job = mover(record, host, check_source=False)
    control.report.side_effect = lambda done, total=None: job.cancel() if done else None

    with caplog.at_level(logging.INFO), raises(JobCanceled):
        job.run(control)

    canceled, last = said(caplog)
    assert canceled == "canceled"
    assert last.startswith("took back the copy: 1 file and 4 folders of it from ")
    assert last.endswith(str(roots[DESTINATION_ROOT] / "Smith" / "2024"))


def test_a_cancel_keeping_the_copy_says_where_it_stays_and_a_retry_says_it_starts_over(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, caplog: LogCaptureFixture
) -> None:
    """A cancel asked to keep the copy says where it is; the retry says it starts over with it.

    **Test steps:**

    * ask a copy to keep its partial copy, and cancel it once it reported progress
    * check the one line says it was canceled and names the kept copy
    * reset the job, as a retry does, and run it: its first line says it starts over with one file kept
    """
    record = make_record(roots[SOURCE_ROOT])
    job = mover(record, host, check_source=False)
    job.keep_partial(True)
    control.report.side_effect = lambda done, total=None: job.cancel() if done else None

    with caplog.at_level(logging.INFO), raises(JobCanceled):
        job.run(control)

    assert said(caplog) == [f"canceled; the copy in {target_of(roots)} was kept"]
    caplog.clear()
    control.report.side_effect = None
    job.reset()

    with caplog.at_level(logging.INFO):
        job.run(control)

    assert said(caplog)[0] == "starting over with 1 file of an earlier copy kept, each checked again"


def test_a_move_that_leaves_part_of_its_original_says_so(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, caplog: LogCaptureFixture, mocker: MockerFixture
) -> None:
    """The removal line is written whatever happened, with what stayed.

    **Test steps:**

    * make the cleanup remove three files and one folder and leave one item, and move a record
    * check the removal line counts them and says one item could not be removed
    """
    record = make_record(roots[SOURCE_ROOT])
    mocker.patch(f"{MODULE}.remove_leftovers", return_value=LeftoversRemoved(3, 1, ["kept.txt (Access is denied)"]))

    with caplog.at_level(logging.INFO):
        mover(record, host).run(control)

    assert said(caplog)[-1] == (
        f"removed 3 files and 1 folder from {record.parent.parent}; 1 item could not be removed"
    )


# endregion


# region the lines of a rename
def test_a_verified_rename_says_its_checks_and_its_places(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, caplog: LogCaptureFixture
) -> None:
    """A rename says so in one line with its two places, and its checks when the setting asks for them.

    **Test steps:**

    * move a folder record as a rename, verifying on
    * check the lines: verified before renaming, renamed from the old folder to the new, verified after renaming
    """
    record = make_record(roots[SOURCE_ROOT])
    old = record.parent

    with caplog.at_level(logging.INFO):
        mover(record, host, mode=MoveMode.RENAME, check_renamed=True).run(control)

    assert said(caplog) == [
        "verified the checksums of 1 file before renaming: 1 matched",
        f"renamed {old} to {target_of(roots)}",
        "verified the checksums of 1 file after renaming: 1 matched",
    ]


def test_an_unverified_rename_says_only_the_rename(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, caplog: LogCaptureFixture
) -> None:
    """With its setting off a rename reads nothing, and says only that it was done.

    **Test steps:**

    * move a folder record as a rename, verifying off
    * check there is one line, the rename's
    """
    record = make_record(roots[SOURCE_ROOT])
    old = record.parent

    with caplog.at_level(logging.INFO):
        job = mover(record, host, mode=MoveMode.RENAME)
        job.run(control)

    assert said(caplog) == [f"renamed {old} to {target_of(roots)}"]
    assert job.phase is MovePhase.DONE


def test_a_file_record_rename_names_its_files(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, caplog: LogCaptureFixture
) -> None:
    """A rename of a file record says which ``.rehu`` went where.

    **Test steps:**

    * move a file record as a rename
    * check the line names the old ``.rehu`` and the new one
    """
    folder = roots[SOURCE_ROOT] / "Old"
    folder.mkdir(parents=True)
    record = folder / "Intro.rehu"
    record.write_text("{}")

    job = mover(record, host, mode=MoveMode.RENAME)

    with caplog.at_level(logging.INFO):
        job.run(control)

    destination = target_of(roots).parent
    assert said(caplog, job.label) == [f"renamed {record} to {destination / 'Intro [2024].rehu'}"]


# endregion


def test_nothing_compared_says_nothing(caplog: LogCaptureFixture) -> None:
    """A step that compared no file writes no line.

    **Test steps:**

    * say that no files were compared
    * check nothing was logged
    """
    with caplog.at_level(logging.INFO):
        MoveStepLog(logging.getLogger(MODULE), lambda: LABEL).compared([])

    assert not caplog.records


# region the words
@mark.parametrize(
    ("count", "text"),
    [(0, "0 files"), (1, "1 file"), (2, "2 files")],
)
def test_a_count_agrees_with_its_noun(count: int, text: str) -> None:
    """A count and its noun are plural except for one.

    **Test steps:**

    * count zero, one and two files
    * check each reads right
    """
    assert counted(count, "file") == text


@mark.parametrize(
    ("size", "text"),
    [
        (0, "0 bytes"),
        (1023, "1023 bytes"),
        (1024, "1.0 KiB"),
        (1536, "1.5 KiB"),
        (5 * 1024**3, "5.0 GiB"),
        (3 * 1024**5, "3072.0 TiB"),
    ],
)
def test_a_size_reads_in_the_largest_unit_above_one(size: int, text: str) -> None:
    """A size is named in the unit that keeps it above one, up to tebibytes.

    **Test steps:**

    * name sizes at and around each unit's edge
    * check each reads right
    """
    assert size_text(size) == text


# endregion
