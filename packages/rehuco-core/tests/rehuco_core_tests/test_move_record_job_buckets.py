"""Tests for a move into a bucketed place (#680): its buckets read off the disk once, kept, and settled after it lands.

Split from :mod:`test_move_record_job`, whose fixtures and helpers are imported by name. The splitter is mocked where
what is under test is when the move asks it; :mod:`test_prefix_buckets` is where a split itself is checked. One move
runs the real one, end to end.
"""

from pathlib import Path, PurePosixPath
from typing import Final
from unittest.mock import MagicMock
from uuid import UUID

from pytest import fixture, raises
from pytest_mock import MockerFixture
from rehuco_core import (
    BUCKETS_MARKER,
    MIN_SPLIT_LIMIT,
    BucketChain,
    JobWaiting,
    MoveMode,
    MovePhase,
    MoveRecordJob,
    RecordLockedError,
    RenameYieldTimeout,
    move_record_job,
)

from rehuco_core_tests.test_move_record_job import (  # noqa: F401  # pylint: disable=unused-import
    DESTINATION_ROOT,
    MODULE,
    SOURCE_ROOT,
    fixture_control,
    fixture_host,
    fixture_roots,
    make_record,
    mover,
)

LAYOUT: Final = PurePosixPath("fab")
"""The layout folder the place's bucketed level is under."""

NAME: Final = "Intro"
"""The record's name at its place, bucketed by its first letter."""

SPLIT_LIMIT: Final = 120
"""The limit the host says, so a test can tell it from the default."""


def bucketed_mover(record: Path, host: MagicMock, **options: object) -> MoveRecordJob:
    """A move of ``record`` into ``fab/{buckets}/Intro`` under the destination root.

    :param record: the source ``.rehu``.
    :param host: the host.
    :param options: overrides of the job's other parameters.
    :returns: the job.
    """
    defaults: dict[str, object] = {"into": LAYOUT, "new_name": NAME, "bucketed": (1,), "mode": MoveMode.RENAME}
    return mover(record, host, **(defaults | options))


@fixture(name="splitter")
def fixture_splitter(mocker: MockerFixture) -> MagicMock:
    """Stand in for the splitter the split phase builds.

    :param mocker: pytest-mock fixture.
    :returns: the class's stand-in; its ``return_value`` is the splitter.
    """
    return mocker.patch(f"{MODULE}.BucketSplitter")


@fixture(name="split_layout")
def fixture_split_layout(roots: dict[UUID, Path]) -> Path:
    """The destination's layout folder, already split, with the bucket ``i`` made.

    :param roots: the roots' folders.
    :returns: the layout folder.
    """
    layout = roots[DESTINATION_ROOT].joinpath(*LAYOUT.parts)
    (layout / "i").mkdir(parents=True)
    (layout / BUCKETS_MARKER).touch()
    return layout


def test_a_rename_into_a_bucketed_place_lands_in_its_bucket_then_splits(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, splitter: MagicMock, split_layout: Path
) -> None:
    """A rename reads its buckets as it starts moving, lands in the bucket, and settles the chain it went into with
    the host's limit as it is then.

    **Test steps:**

    * move a folder record into a bucketed place whose layout folder is split, the host saying a limit of its own
    * verify the record in bucket ``i``, the place kept, and the splitter asked once, with the limit, on that chain
    """
    host.split_limit.return_value = SPLIT_LIMIT
    job = bucketed_mover(make_record(roots[SOURCE_ROOT]), host)

    job.run(control)

    assert job.phase is MovePhase.DONE
    assert job.source == split_layout / "i" / NAME / "info.rehu"
    assert (job.into, job.bucketed, job.chains) == (LAYOUT / "i", (), ())
    assert splitter.call_args.args[0] == SPLIT_LIMIT
    splitter.return_value.settle.assert_called_once_with(split_layout, ("i",))


def test_a_copy_into_a_bucketed_place_settles_after_its_cleanup(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, splitter: MagicMock, split_layout: Path
) -> None:
    """A copy lands in the bucket read when it started copying, and the split comes once its original is gone.

    **Test steps:**

    * copy a folder record into a bucketed place
    * verify the copy in the bucket, the original gone, and the split asked
    """
    record = make_record(roots[SOURCE_ROOT])
    job = bucketed_mover(record, host, mode=MoveMode.COPY)

    job.run(control)

    assert (split_layout / "i" / NAME / "content.zip").is_file()
    assert not record.exists()
    splitter.return_value.settle.assert_called_once_with(split_layout, ("i",))


def test_a_verified_rename_settles_after_its_check(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, splitter: MagicMock, split_layout: Path
) -> None:
    """A rename verified after it lands is settled once its check passed.

    **Test steps:**

    * rename a folder record into a bucketed place, verifying it after
    * verify the move done and the split asked
    """
    job = bucketed_mover(make_record(roots[SOURCE_ROOT]), host, check_renamed=True)

    job.run(control)

    assert job.phase is MovePhase.DONE
    splitter.return_value.settle.assert_called_once_with(split_layout, ("i",))


def test_a_place_with_no_buckets_is_never_settled(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, splitter: MagicMock
) -> None:
    """A move to a place without buckets ends at its landing, as it always did.

    **Test steps:**

    * rename a folder record into a plain place
    * verify the move done and no splitter built
    """
    job = mover(make_record(roots[SOURCE_ROOT]), host, mode=MoveMode.RENAME)

    job.run(control)

    assert job.phase is MovePhase.DONE
    splitter.assert_not_called()


def test_a_split_waits_for_a_locked_record_or_a_busy_reader(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, splitter: MagicMock, split_layout: Path
) -> None:
    """A record the split must move that is locked elsewhere, or a reader slow to let go, makes the move wait in its
    split phase, the chain kept for the retry.

    **Test steps:**

    * have the splitter raise a lock error, then a reader timeout
    * run the move each time
    * verify each wait's retry, the phase still the split's and the chain kept
    """
    del split_layout
    job = bucketed_mover(make_record(roots[SOURCE_ROOT]), host)
    record = roots[SOURCE_ROOT] / "x.rehu"
    splitter.return_value.settle.side_effect = [RecordLockedError(record, None), RenameYieldTimeout("busy")]

    with raises(JobWaiting) as locked:
        job.run(control)
    with raises(JobWaiting) as busy:
        job.run(control)

    assert locked.value.retry_after == move_record_job.LOCK_HELD_RETRY
    assert busy.value.retry_after == move_record_job.READERS_BUSY_RETRY
    assert job.phase is MovePhase.SPLIT
    assert job.chains == (BucketChain(LAYOUT, ("i",)),)


def test_a_level_whose_layout_folder_is_gone_is_not_settled(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, splitter: MagicMock
) -> None:
    """A level whose layout folder another move's split took away, on a root that answers, ends the move instead of
    failing it: the record landed, and the folder it is in now is settled by the next arrival.

    **Test steps:**

    * run a job in its split phase, with one chain under a folder that is not there and one under a folder that is
    * verify the move done, and only the folder that is there settled
    """
    job = bucketed_mover(make_record(roots[SOURCE_ROOT]), host)
    there = roots[DESTINATION_ROOT].joinpath(*LAYOUT.parts)
    there.mkdir(parents=True)
    job.phase = MovePhase.SPLIT
    job.chains = (BucketChain(PurePosixPath("gone"), ("a",)), BucketChain(LAYOUT, ()))

    job.run(control)

    assert job.phase is MovePhase.DONE
    splitter.return_value.settle.assert_called_once_with(there, ())


def test_a_retry_in_the_split_goes_on_with_the_split(roots: dict[UUID, Path], host: MagicMock) -> None:
    """A retried move whose record has landed only settles its buckets again.

    **Test steps:**

    * reset a job in its split phase
    * verify it is still there
    """
    job = bucketed_mover(make_record(roots[SOURCE_ROOT]), host)
    job.phase = MovePhase.SPLIT

    job.reset()

    assert job.phase is MovePhase.SPLIT


def test_a_bucketed_move_whose_root_is_not_mapped_cannot_read_its_buckets(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock
) -> None:
    """With the destination root unmapped, there is no disk to read the buckets off.

    **Test steps:**

    * run a bucketed move whose destination root this machine does not map
    * verify the error saying so
    """
    host.root_folder.side_effect = {SOURCE_ROOT: roots[SOURCE_ROOT]}.get
    job = bucketed_mover(make_record(roots[SOURCE_ROOT]), host)

    with raises(ValueError, match="not mapped"):
        job.run(control)


def test_a_bucketed_move_keeps_its_buckets_across_a_restart(roots: dict[UUID, Path], host: MagicMock) -> None:
    """The levels still to resolve and the chains still to settle are written down and read back.

    **Test steps:**

    * capture a job with levels to resolve, then one with a chain to settle, and restore each into a fresh job
    * verify each comes back as it was
    """
    record = make_record(roots[SOURCE_ROOT])
    waiting = bucketed_mover(record, host)
    settling = bucketed_mover(record, host, bucketed=())
    settling.chains = (BucketChain(LAYOUT, ("i", "in")),)

    for job in (waiting, settling):
        restored = MoveRecordJob(host=host)
        restored.restore_state(job.capture_state())
        assert (restored.bucketed, restored.chains) == (job.bucketed, job.chains)


def test_a_state_saved_before_buckets_has_none(roots: dict[UUID, Path], host: MagicMock) -> None:
    """A move saved before buckets existed restores with none to resolve or settle.

    **Test steps:**

    * capture a plain move, drop the bucket keys, and restore it
    * verify no levels and no chains
    """
    state = mover(make_record(roots[SOURCE_ROOT]), host).capture_state()
    del state[move_record_job.STATE_BUCKETED_KEY], state[move_record_job.STATE_CHAINS_KEY]

    restored = MoveRecordJob(host=host)
    restored.restore_state(state)

    assert (restored.bucketed, restored.chains) == ((), ())


def test_a_state_with_malformed_buckets_is_refused(roots: dict[UUID, Path], host: MagicMock) -> None:
    """Levels that are not indices, or chains that are not a list, refuse the state.

    **Test steps:**

    * restore a state whose levels hold a name, then one whose chains are an object
    * verify both refused
    """
    state = mover(make_record(roots[SOURCE_ROOT]), host).capture_state()

    with raises(ValueError, match="indices"):
        MoveRecordJob(host=host).restore_state(state | {move_record_job.STATE_BUCKETED_KEY: ["1"]})
    with raises(ValueError, match="not a list"):
        MoveRecordJob(host=host).restore_state(state | {move_record_job.STATE_CHAINS_KEY: {}})


def test_a_move_into_a_crowded_layout_folder_splits_it(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock
) -> None:
    """End to end: a record moved into a layout folder already at the limit splits it, every record in its bucket.

    **Test steps:**

    * fill the destination's layout folder with as many file records as the limit
    * move a folder record into ``fab/{buckets}/Intro`` with the host at that limit
    * verify the marker, the moved record in ``i``, and every other record in the bucket of its first character
    """
    layout = roots[DESTINATION_ROOT].joinpath(*LAYOUT.parts)
    layout.mkdir(parents=True)
    for index in range(MIN_SPLIT_LIMIT):
        (layout / f"{index % 10}{index:03}.rehu").write_text("{}", encoding="utf-8")
    host.split_limit.return_value = MIN_SPLIT_LIMIT
    job = bucketed_mover(make_record(roots[SOURCE_ROOT]), host)

    job.run(control)

    assert (layout / BUCKETS_MARKER).is_file()
    assert job.source == layout / "i" / NAME / "info.rehu"
    assert all(path.parent.name == path.name[0] for path in layout.rglob("*.rehu") if path.name != "info.rehu")
    assert not list(layout.glob("*.rehu"))
