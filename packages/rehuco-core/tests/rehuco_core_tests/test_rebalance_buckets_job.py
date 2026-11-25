"""Tests for the job that brings a root's prefix buckets in line with the limits it is given (#681).

The cache, the folder finder, the rules, the splitter and the joiner are each tested on their own (:mod:`test_rehudb`,
:mod:`test_bucketed_folders`, :mod:`test_prefix_buckets`, :mod:`test_bucket_joiner`); here the cache, the finder and the
rules are mocked, and the two that move are where what is asserted is only the job's part. The tests of the walk run the
real ones on ``tmp_path``.
"""

from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any, Final
from unittest.mock import MagicMock
from uuid import UUID, uuid4

from borco_core import Presence
from pytest import fixture, mark, param, raises
from pytest_mock import MockerFixture
from rehuco_core import (
    BUCKET_REBALANCE_KIND,
    BUCKETS_GUARD,
    BUCKETS_MARKER,
    DEFAULT_TASK_JOB_REGISTRY,
    EXCLUDED_FILE_PATTERNS,
    LIBRARY_CHAIN,
    MIN_SPLIT_LIMIT,
    NOTHING_TO_REBALANCE,
    PROGRESS_UNIT_RESOURCES,
    Bucketing,
    CatalogRoot,
    JobCanceled,
    JobControl,
    JobOutcome,
    JobPaused,
    JobWaiting,
    JoinResult,
    RebalanceBucketsJob,
    RecordLockedError,
    RecordMoveHost,
    RehurootFileError,
    RenameCoordinator,
    RenameYieldTimeout,
    is_split,
)

from rehuco_core_tests.test_prefix_buckets import file_record, folder_record, mark_split, names_under

MODULE: Final = "rehuco_core.rebalance_buckets_job"
CACHE: Final = Path("/fake/cache/rehuco.rehudb")
ROOT_FILE: Final = Path("/fake/catalog/library.rehuroot")
ROOT_ID: Final = uuid4()

FAB: Final = PurePosixPath("Fab")
"""The bucketed folder the finder answers."""

SPLIT_LIMIT: Final = MIN_SPLIT_LIMIT
JOIN_LIMIT: Final = 20


@fixture(name="host")
def fixture_host(tmp_path: Path) -> MagicMock:
    """A host mapping the root to ``tmp_path``, with no move under way, running each step where it is asked.

    :param tmp_path: pytest fixture.
    :returns: the host.
    """
    host = MagicMock(spec=RecordMoveHost)
    host.root_folder.return_value = tmp_path
    host.run_step.side_effect = lambda step, checkpoint: step()
    host.location_rules.return_value = ()
    host.blocking_move.return_value = None
    return host


@fixture(name="control")
def fixture_control() -> MagicMock:
    """The engine's face to a job.

    :returns: a stand-in recording each report.
    """
    return MagicMock(spec=JobControl)


@fixture(name="cache")
def fixture_cache(mocker: MockerFixture, tmp_path: Path) -> MagicMock:
    """Replace the cache the job opens with one listing the root.

    :param mocker: pytest-mock fixture.
    :param tmp_path: pytest fixture.
    :returns: the cache a ``with`` block hands the job.
    """
    cache = mocker.patch("rehuco_core.rehudb_jobs.CatalogCache.open").return_value.__enter__.return_value
    cache.roots.return_value = (CatalogRoot(ROOT_ID, "Library", tmp_path, 0, False, True, 1.0, ROOT_FILE),)
    cache.root_rows.return_value = []
    return cache


@fixture(name="root_file")
def fixture_root_file(mocker: MockerFixture) -> MagicMock:
    """Replace what reads the root's file.

    :param mocker: pytest-mock fixture.
    :returns: the stand-in for ``RehurootFile.load``.
    """
    return mocker.patch(f"{MODULE}.RehurootFile.load")


@fixture(name="found")
def fixture_found(mocker: MockerFixture, cache: MagicMock, root_file: MagicMock) -> MagicMock:
    """Replace the finder, answering :data:`FAB`, and the rules, which govern every split folder.

    :param mocker: pytest-mock fixture.
    :param cache: the cache, listing the root.
    :param root_file: the root's file, read.
    :returns: the finder's stand-in.
    """
    del cache, root_file
    mocker.patch(f"{MODULE}.BucketRules").return_value.of.return_value = Bucketing.GOVERNED
    return mocker.patch(f"{MODULE}.bucketed_folders", return_value=(FAB,))


@fixture(name="joiner")
def fixture_joiner(mocker: MockerFixture) -> MagicMock:
    """Replace the joiner, joining nothing.

    :param mocker: pytest-mock fixture.
    :returns: the class's stand-in.
    """
    joiner = mocker.patch(f"{MODULE}.BucketJoiner")
    joiner.return_value.join.return_value = JoinResult.NONE
    joiner.return_value.left = ()
    return joiner


@fixture(name="splitter")
def fixture_splitter(mocker: MockerFixture) -> MagicMock:
    """Replace the splitter.

    :param mocker: pytest-mock fixture.
    :returns: the class's stand-in.
    """
    splitter = mocker.patch(f"{MODULE}.BucketSplitter")
    splitter.return_value.left = ()
    return splitter


@fixture(name="job")
def fixture_job(tmp_path: Path, host: MagicMock) -> RebalanceBucketsJob:
    """A rebalance of the root.

    :param tmp_path: pytest fixture.
    :param host: the host.
    :returns: the job.
    """
    return RebalanceBucketsJob(
        CACHE,
        ROOT_ID,
        tmp_path,
        root_label="Library",
        split_limit=SPLIT_LIMIT,
        join_limit=JOIN_LIMIT,
        coordinator=RenameCoordinator(),
        host=host,
    )


@fixture(name="fab")
def fixture_fab(tmp_path: Path) -> Path:
    """The bucketed folder, empty.

    :param tmp_path: pytest fixture.
    :returns: the folder.
    """
    folder = tmp_path / FAB.name
    folder.mkdir()
    return folder


# region What the queue reads


def test_a_rebalance_takes_turns_with_the_library_scans(job: RebalanceBucketsJob, tmp_path: Path) -> None:
    """It declares the scans' chain, the root's folder, that a pause keeps its work, and a readable name.

    **Test steps:**

    * build a job
    * verify its declarations
    """
    assert job.chain == LIBRARY_CHAIN
    assert job.label == f"Balance buckets ({SPLIT_LIMIT}/{JOIN_LIMIT}) - Library"
    assert job.source == tmp_path
    assert job.resumes_where_it_stopped
    assert job.progress_unit == PROGRESS_UNIT_RESOURCES
    assert job.outcome is None


def test_a_job_is_rebuilt_from_its_saved_state(tmp_path: Path) -> None:
    """The registry's job, handed a saved state, is the job that was saved, its junk patterns and limits with it.

    **Test steps:**

    * capture a job's state and restore it through the registry
    * verify the restored job
    """
    job = RebalanceBucketsJob(
        CACHE,
        ROOT_ID,
        tmp_path,
        root_label="Library",
        split_limit=75,
        join_limit=30,
        excluded_patterns=("*.tmp",),
    )

    restored = DEFAULT_TASK_JOB_REGISTRY.create(BUCKET_REBALANCE_KIND, job.capture_state())

    assert isinstance(restored, RebalanceBucketsJob)
    assert (restored.cache_path, restored.root_id, restored.source) == (CACHE, ROOT_ID, tmp_path)
    assert (restored.label, restored.excluded_patterns) == (job.label, ("*.tmp",))
    assert restored.label == "Balance buckets (75/30) - Library"
    assert restored.limits == (75, 30)
    assert restored.validate() is None


@mark.parametrize(
    "broken, message",
    [
        param({"path": ""}, "names no folder", id="no-folder"),
        param({"path": 3}, "names no folder", id="a-folder-that-is-no-text"),
        param({"excluded_patterns": "*.tmp"}, "not a list", id="patterns-that-are-no-list"),
        param({"excluded_patterns": [1]}, "not a list", id="patterns-that-are-no-names"),
        param({"split_limit": "75"}, "limits are not numbers", id="a-split-limit-that-is-no-number"),
        param({"split_limit": True}, "limits are not numbers", id="a-split-limit-that-is-a-flag"),
        param({"join_limit": None}, "limits are not numbers", id="no-join-limit"),
        param({"root_id": None}, "names no root", id="no-root"),
    ],
)
def test_a_state_this_job_did_not_write_is_refused(tmp_path: Path, broken: dict[str, Any], message: str) -> None:
    """A state missing what the job needs is refused, for the registry to drop.

    **Test steps:**

    * restore a state with one part broken
    * verify the refusal
    """
    state = RebalanceBucketsJob(CACHE, ROOT_ID, tmp_path).capture_state() | broken

    with raises(ValueError, match=message):
        RebalanceBucketsJob().restore_state(state)


def test_a_job_with_no_root_cannot_start() -> None:
    """A job built bare names nothing to work on, nor does one with a root and no folder; neither is saved as if it
    did.

    **Test steps:**

    * validate a bare job and one with no folder
    * capture the latter's state
    * verify the refusals and the empty folder
    """
    assert RebalanceBucketsJob().validate() == "This task names no catalog root."
    job = RebalanceBucketsJob(CACHE, ROOT_ID)

    assert job.validate() == "This task names no root's folder."
    assert job.capture_state()["path"] == ""


# endregion

# region The walk


def test_a_lowered_split_limit_splits_what_no_record_arrived_in(
    job: RebalanceBucketsJob, control: MagicMock, found: MagicMock, fab: Path
) -> None:
    """Every folder over the limit splits, a bucket of a folder already split too, and the row counts the moves.

    **Test steps:**

    * crowd a bucket of a split folder past the split limit, beside one within it
    * run the job
    * verify the crowded bucket split, the other plain, and the outcome and the progress
    """
    del found
    mark_split(fab)
    for index in range(SPLIT_LIMIT + 1):
        file_record(fab / "a", f"a{index:02}")
    file_record(fab / "b", "b00")

    job.run(control)

    assert is_split(fab / "a")
    assert (fab / "a" / "a0" / "a00.rehu").is_file()
    assert not is_split(fab / "b")
    assert job.outcome == JobOutcome(f"{SPLIT_LIMIT + 1} moves, 0 folders joined")
    assert control.report.call_args.args == (SPLIT_LIMIT + 1,)


def test_a_bucket_within_the_join_limit_is_joined_in_a_folder_that_is_not(
    job: RebalanceBucketsJob, control: MagicMock, found: MagicMock, fab: Path
) -> None:
    """A folder too full to be joined has its buckets looked at in turn.

    **Test steps:**

    * split a folder holding a split bucket with one record and a plain one with more than the join limit
    * run the job
    * verify the bucket joined, the folder still split, and the outcome
    """
    del found
    mark_split(fab)
    mark_split(fab / "a")
    file_record(fab / "a" / "ab", "abc")
    for index in range(JOIN_LIMIT + 1):
        file_record(fab / "b", f"b{index:02}")

    job.run(control)

    assert names_under(fab / "a") == {"abc.rehu", "abc00.jpg"}
    assert is_split(fab)
    assert job.outcome == JobOutcome("1 move, 1 folder joined")


def test_a_raised_join_limit_joins_the_whole_folder(
    job: RebalanceBucketsJob, control: MagicMock, found: MagicMock, fab: Path
) -> None:
    """A folder whose whole subtree fits is joined at once, not bucket by bucket.

    **Test steps:**

    * split a folder two levels deep with two records
    * run the job
    * verify the folder flat, and one join told
    """
    del found
    mark_split(fab)
    mark_split(fab / "a")
    file_record(fab / "a" / "ab", "abc")
    folder_record(fab / "b", "b")

    job.run(control)

    assert names_under(fab) == {"abc.rehu", "abc00.jpg", "b/info.rehu"}
    assert job.outcome is not None and job.outcome.summary.endswith("1 folder joined")


def test_a_folder_within_the_limits_is_left_alone(
    job: RebalanceBucketsJob, control: MagicMock, found: MagicMock, fab: Path
) -> None:
    """A plain folder under the split limit, or a split one over the join limit, moves nothing.

    **Test steps:**

    * write a few records into the bucketed folder
    * run the job
    * verify nothing moved and the outcome says so
    """
    del found
    file_record(fab, "abc")

    job.run(control)

    assert names_under(fab) == {"abc.rehu", "abc00.jpg"}
    assert job.outcome == JobOutcome(NOTHING_TO_REBALANCE)


@mark.usefixtures("found")
def test_a_folder_marked_never_split_is_left_alone(
    job: RebalanceBucketsJob, control: MagicMock, fab: Path, joiner: MagicMock, splitter: MagicMock
) -> None:
    """The owner's *never split* keeps a folder from both.

    **Test steps:**

    * mark the bucketed folder as never split, by a folder named like the marker
    * run the job
    * verify neither the joiner nor the splitter was asked
    """
    (fab / BUCKETS_MARKER).mkdir()

    job.run(control)

    joiner.return_value.join.assert_not_called()
    splitter.return_value.settle_folder.assert_not_called()


def test_a_folder_left_split_is_told_by_the_outcome(
    job: RebalanceBucketsJob, control: MagicMock, found: MagicMock, fab: Path
) -> None:
    """A stray file that kept a folder split makes the outcome one to look at; running again tells it once.

    **Test steps:**

    * split a folder with a note in its bucket
    * run the job twice
    * verify the outcome names the note, once, and is not clean
    """
    del found
    mark_split(fab)
    file_record(fab / "a", "abc")
    stray = fab / "a" / "notes.txt"
    stray.write_text("x", encoding="utf-8")

    job.run(control)
    job.run(control)

    expected = f"0 moves, 0 folders joined; left: {fab}: {stray} belongs to no record"
    assert job.outcome == JobOutcome(expected, clean=False)


def test_an_entry_left_where_it_is_is_told_by_the_outcome(
    job: RebalanceBucketsJob, control: MagicMock, found: MagicMock, fab: Path
) -> None:
    """A duplicate stops nothing: the rest is rebalanced, and the outcome names it.

    **Test steps:**

    * split a folder holding a record beside the buckets whose name is taken in one, and more than the join limit
    * run the job
    * verify it finished, its outcome naming the record
    """
    del found
    mark_split(fab)
    folder_record(fab / "a", "abc")
    folder_record(fab, "abc")
    for index in range(JOIN_LIMIT):
        file_record(fab / "b", f"b{index:02}")

    job.run(control)

    assert job.outcome == JobOutcome(
        f"0 moves, 0 folders joined; left: {fab / 'abc'}: its name is taken in {fab / 'a'}", clean=False
    )


@mark.usefixtures("found", "fab")
def test_a_halted_join_is_not_split_again_in_the_same_run(
    job: RebalanceBucketsJob, control: MagicMock, joiner: MagicMock, splitter: MagicMock
) -> None:
    """Splitting a folder whose join was halted would only move its entries down again.

    **Test steps:**

    * have the joiner say it halted
    * run the job
    * verify the splitter was not asked, and no folder is told as joined
    """
    halted = joiner.return_value
    halted.join.return_value = JoinResult.HALTED
    halted.left = ("a reason",)
    # the first two are for the folders no rule buckets, of which there is none
    joiner.side_effect = [MagicMock(left=()), MagicMock(left=()), halted]

    job.run(control)

    splitter.return_value.settle_folder.assert_not_called()
    assert job.outcome == JobOutcome("0 moves, 0 folders joined; left: a reason", clean=False)


def test_junk_goes_by_the_jobs_own_patterns(
    job: RebalanceBucketsJob, control: MagicMock, found: MagicMock, fab: Path, mocker: MockerFixture
) -> None:
    """What a join deletes are the files the job's patterns name, through the app's deleter.

    **Test steps:**

    * split a folder with a ``.DS_Store`` in its bucket, the app's deleter a stand-in
    * run the job
    * verify the deleter was handed the file
    """
    del found
    deleter = mocker.patch(f"{MODULE}.DEFAULT_DELETER_PROVIDER").resolve.return_value
    deleter.delete.side_effect = Path.unlink
    mark_split(fab)
    file_record(fab / "a", "abc")
    junk = fab / "a" / ".DS_Store"
    junk.write_bytes(b"x")

    job.run(control)

    assert job.excluded_patterns == EXCLUDED_FILE_PATTERNS
    deleter.delete.assert_called_once_with(junk)
    assert names_under(fab) == {"abc.rehu", "abc00.jpg"}


# pylint: disable-next=too-many-arguments,too-many-positional-arguments  # each is what the job asks or is asked
def test_the_folders_are_those_the_roots_records_are_at_their_place_in(
    job: RebalanceBucketsJob,
    control: MagicMock,
    cache: MagicMock,
    root_file: MagicMock,
    found: MagicMock,
    host: MagicMock,
    joiner: MagicMock,
    tmp_path: Path,
) -> None:
    """The finder is handed the root's cached records, its layouts and the replacements, and each folder it answers is
    walked in its order; one that is gone is passed over.

    **Test steps:**

    * have the finder answer an inner folder, one that is not there, and an outer one
    * run the job
    * verify what it was handed, and the folders walked
    """
    found.return_value = (PurePosixPath("Fab", "j"), PurePosixPath("gone"), FAB)
    (tmp_path / "Fab" / "j").mkdir(parents=True)

    job.run(control)

    cache.root_rows.assert_called_with(ROOT_ID)
    root_file.assert_called_with(ROOT_FILE)
    found.assert_called_once_with([], root_file.return_value, host.location_rules.return_value)
    assert [call.args for call in joiner.return_value.join.call_args_list] == [
        (tmp_path / "Fab" / "j", 0),
        (tmp_path / "Fab", 0),
    ]


@mark.usefixtures("found", "fab")
def test_the_limits_are_those_it_was_given(
    host: MagicMock, control: MagicMock, joiner: MagicMock, splitter: MagicMock, tmp_path: Path
) -> None:
    """Whatever the settings say meanwhile, the job works with its own limits, clamped as they are used.

    **Test steps:**

    * run a job given a join limit above half its split limit, the host saying another split limit
    * verify what the splitter and the folders' joiner were built with
    """
    host.split_limit.return_value = 1000
    job = RebalanceBucketsJob(CACHE, ROOT_ID, tmp_path, split_limit=300, join_limit=200, host=host)

    job.run(control)

    assert job.label == "Balance buckets (300/150)"
    assert splitter.call_args.args[0] == 300
    assert joiner.call_args.args[0] == 150


# endregion

# region Stopping and waiting


def test_a_pause_leaves_the_rest_for_the_next_run(
    job: RebalanceBucketsJob, control: MagicMock, host: MagicMock, found: MagicMock, fab: Path
) -> None:
    """A pause between two moves unwinds with every record in one place, and the next run finishes.

    **Test steps:**

    * crowd the folder and ask for a pause once the third record moved
    * run the job, then resume and run it again
    * verify the pause, every record in one place, then all in their buckets and counted once
    """
    del found
    names = [f"{index:02}" for index in range(SPLIT_LIMIT + 1)]
    for name in names:
        file_record(fab, name)
    steps = iter(range(1000))

    def run_step(step: Callable[[], object], _checkpoint: Callable[[], None]) -> None:
        """Run a step, and ask for the pause after the third."""
        step()
        if next(steps) == 2:
            job.pause()

    host.run_step.side_effect = run_step

    with raises(JobPaused):
        job.run(control)
    assert sorted(path.stem for path in fab.rglob("*.rehu")) == names
    assert job.outcome is None

    job.resume()
    job.run(control)
    assert all((fab / name[0] / f"{name}.rehu").is_file() for name in names)
    assert job.outcome == JobOutcome(f"{SPLIT_LIMIT + 1} moves, 0 folders joined")


@mark.usefixtures("found", "fab")
def test_a_cancel_stops_it(job: RebalanceBucketsJob, control: MagicMock) -> None:
    """A cancel is obeyed before the next folder.

    **Test steps:**

    * cancel a job and run it
    * verify it says so
    """
    job.cancel()

    with raises(JobCanceled):
        job.run(control)


@mark.usefixtures("found")
def test_a_move_into_the_root_is_waited_for(
    job: RebalanceBucketsJob, control: MagicMock, host: MagicMock, fab: Path
) -> None:
    """A move of the root's records is waited for before any step, and named; it is asked for with the guard held that a
    move reads its buckets under.

    **Test steps:**

    * crowd the folder, with a move into the root under way
    * run the job
    * verify the wait names the move, and nothing moved
    """
    for index in range(SPLIT_LIMIT + 1):
        file_record(fab, f"{index:02}")
    guarded: list[bool] = []

    def blocking_move(_root_id: UUID) -> str:
        """Say a move is under way, and whether the guard was held."""
        guarded.append(BUCKETS_GUARD.locked())
        return "Move to Library - Intro"

    host.blocking_move.side_effect = blocking_move

    with raises(JobWaiting, match="Move to Library - Intro"):
        job.run(control)

    host.blocking_move.assert_called_once_with(ROOT_ID)
    assert guarded == [True]
    assert not BUCKETS_GUARD.locked()
    assert not is_split(fab)


@mark.usefixtures("found", "fab")
@mark.parametrize(
    "error, waits",
    [
        param(RecordLockedError(Path("a.rehu"), None), True, id="a-locked-record"),
        param(RenameYieldTimeout("a reader"), True, id="a-slow-reader"),
        param(FileExistsError("taken"), False, id="a-taken-name"),
    ],
)
def test_a_record_held_elsewhere_is_waited_for(
    job: RebalanceBucketsJob, control: MagicMock, splitter: MagicMock, error: OSError, waits: bool
) -> None:
    """A locked record or a slow reader is waited for; a move the disk refuses fails the job.

    **Test steps:**

    * have the splitter raise each error
    * run the job
    * verify a wait, or the error itself
    """
    splitter.return_value.settle_folder.side_effect = error

    with raises(JobWaiting if waits else FileExistsError):
        job.run(control)


@mark.usefixtures("found", "fab")
def test_a_root_that_stops_answering_is_waited_for(
    job: RebalanceBucketsJob, control: MagicMock, splitter: MagicMock, mocker: MockerFixture
) -> None:
    """A failure on a root that no longer answers is a wait, which names its server or drive.

    **Test steps:**

    * have the root answer as the job starts, and not once the splitter failed
    * run the job
    * verify the wait
    """
    splitter.return_value.settle_folder.side_effect = OSError("network name no longer available")
    mocker.patch(f"{MODULE}.presence_of", side_effect=[Presence.PRESENT, Presence.OFFLINE])

    with raises(JobWaiting, match="does not answer"):
        job.run(control)


@mark.usefixtures("found")
def test_a_folder_that_reads_as_gone_is_waited_for_when_the_root_is_off(
    job: RebalanceBucketsJob, control: MagicMock, mocker: MockerFixture
) -> None:
    """A share that is off reads every folder as missing, which is no reason to pass it over.

    **Test steps:**

    * leave the bucketed folder missing, the root answering as the job starts and not after
    * run the job
    * verify the wait
    """
    mocker.patch(f"{MODULE}.presence_of", side_effect=[Presence.PRESENT, Presence.OFFLINE])

    with raises(JobWaiting, match="does not answer"):
        job.run(control)


def test_an_unmapped_root_pauses_it(job: RebalanceBucketsJob, control: MagicMock, host: MagicMock) -> None:
    """A root this machine no longer maps is the user's to map.

    **Test steps:**

    * run the job with a host that maps no root
    * verify the pause and its reason
    """
    host.root_folder.return_value = None

    with raises(JobPaused) as paused:
        job.run(control)

    assert paused.value.reason is not None and "maps no folder" in paused.value.reason


@mark.usefixtures("found")
@mark.parametrize("rows", [param((), id="removed"), param((None,), id="with-no-file")])
def test_a_root_the_catalog_no_longer_lists_pauses_it(
    job: RebalanceBucketsJob, control: MagicMock, cache: MagicMock, rows: tuple[None, ...], tmp_path: Path
) -> None:
    """A root removed from the catalog has no records to find its folders by.

    **Test steps:**

    * run the job on a cache that lists no such root, or lists it with no file
    * verify the pause and its reason
    """
    cache.roots.return_value = tuple(
        CatalogRoot(ROOT_ID, "Library", tmp_path, 0, False, True, 1.0, root_file) for root_file in rows
    )

    with raises(JobPaused) as paused:
        job.run(control)

    assert paused.value.reason is not None and "no longer in the catalog" in paused.value.reason


@mark.usefixtures("found")
@mark.parametrize(
    "error, offline, expected",
    [
        param(RehurootFileError("not an object"), False, JobPaused, id="unreadable"),
        param(OSError("denied"), False, JobPaused, id="denied"),
        param(OSError("network path not found"), True, JobWaiting, id="on-a-share-that-is-off"),
    ],
)
# pylint: disable-next=too-many-arguments,too-many-positional-arguments  # one error, and what it means
def test_a_root_file_that_cannot_be_read_stops_it(
    job: RebalanceBucketsJob,
    control: MagicMock,
    root_file: MagicMock,
    mocker: MockerFixture,
    error: Exception,
    offline: bool,
    expected: type[Exception],
) -> None:
    """Without the root's layouts there is nothing to find: the user's to look at, unless its share is off.

    **Test steps:**

    * have the root's file fail to load
    * run the job
    * verify a pause, or a wait when its folder does not answer
    """
    root_file.side_effect = error
    mocker.patch(
        f"{MODULE}.presence_of",
        side_effect=lambda path: Presence.OFFLINE if offline and path == ROOT_FILE.parent else Presence.PRESENT,
    )

    with raises(expected):
        job.run(control)


@mark.usefixtures("found")
def test_a_retry_starts_its_counts_over(job: RebalanceBucketsJob, control: MagicMock, fab: Path) -> None:
    """A finished job run again by Retry says what that run did.

    **Test steps:**

    * run a job that joins a folder, then reset it and run it again
    * verify the outcome after the reset, then after the second run
    """
    mark_split(fab)
    file_record(fab / "a", "abc")
    job.run(control)

    job.reset()

    assert job.outcome is None
    job.run(control)
    assert job.outcome == JobOutcome(NOTHING_TO_REBALANCE)


# endregion
