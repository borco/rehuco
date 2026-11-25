"""Tests for the rebalance joining the split folders no layout buckets any more (#681).
:mod:`test_rebalance_buckets_job`, whose fixtures are imported by name, tests the rest of the job.
"""

from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID

from pytest import fixture, mark
from pytest_mock import MockerFixture
from rehuco_core import (
    BUCKETS_MARKER,
    NOTHING_TO_REBALANCE,
    Bucketing,
    JobOutcome,
    JobPaused,
    RebalanceBucketsJob,
    is_split,
)

from rehuco_core_tests.test_prefix_buckets import file_record, mark_split, names_under
from rehuco_core_tests.test_rebalance_buckets_job import (  # noqa: F401  # pylint: disable=unused-import
    FAB,
    MODULE,
    SPLIT_LIMIT,
    fixture_cache,
    fixture_control,
    fixture_fab,
    fixture_found,
    fixture_host,
    fixture_job,
    fixture_root_file,
)


@fixture(name="rules")
def fixture_rules(mocker: MockerFixture, found: MagicMock) -> MagicMock:
    """Replace the rules, governing no split folder, and have the finder answer none.

    :param mocker: pytest-mock fixture.
    :param found: the finder.
    :returns: the rules' stand-in.
    """
    found.return_value = ()
    rules = mocker.patch(f"{MODULE}.BucketRules")
    rules.return_value.of.return_value = Bucketing.UNGOVERNED
    return rules


def crowd(folder: Path) -> list[str]:
    """Fill a split folder's buckets with more entries than the join limit, and more than the split limit.

    :param folder: the folder.
    :returns: the entries' names.
    """
    names = [f"{index:02}" for index in range(SPLIT_LIMIT + 1)]
    mark_split(folder)
    for name in names:
        file_record(folder / name[0], name)
    return names


# pylint: disable-next=too-many-arguments,too-many-positional-arguments  # each is what the job asks or is asked
def test_a_folder_no_rule_buckets_is_joined_whatever_it_holds(
    job: RebalanceBucketsJob, control: MagicMock, rules: MagicMock, cache: MagicMock, host: MagicMock, fab: Path
) -> None:
    """The rule removed, its folder is joined whole, over both limits; the rules are asked with what the cache and the
    root's file say.

    **Test steps:**

    * crowd a split folder no rule buckets
    * run the job
    * verify every record in the folder itself, no marker, the outcome, and what the rules were built from
    """
    names = crowd(fab)

    job.run(control)

    assert sorted(path.stem for path in fab.glob("*.rehu")) == names
    assert not is_split(fab)
    assert job.outcome == JobOutcome(f"{len(names)} moves, 1 folder joined")
    assert rules.call_args.args[0] == cache.root_rows.return_value
    assert rules.call_args.args[2] is host.location_rules.return_value
    assert rules.call_args.kwargs == {"split": (FAB,), "scanned": True}
    rules.return_value.of.assert_called_once_with(FAB)


def test_a_folder_a_rule_buckets_is_not_flattened(
    job: RebalanceBucketsJob, control: MagicMock, rules: MagicMock, fab: Path
) -> None:
    """A governed folder is left to the walk of the bucketed ones.

    **Test steps:**

    * crowd a split folder a rule buckets, the finder answering none
    * run the job
    * verify nothing moved
    """
    rules.return_value.of.return_value = Bucketing.GOVERNED
    crowd(fab)

    job.run(control)

    assert is_split(fab)
    assert job.outcome == JobOutcome(NOTHING_TO_REBALANCE)


def test_a_folder_nothing_is_known_of_is_joined_within_the_join_limit_only(
    job: RebalanceBucketsJob, control: MagicMock, rules: MagicMock, fab: Path, tmp_path: Path
) -> None:
    """A library never scanned stays as it is; a folder emptied by hand loses its empty buckets and its marker.

    **Test steps:**

    * crowd one split folder, and empty another, two levels deep, nothing known of either
    * run the job
    * verify the first as it was and the second plain and empty
    """
    rules.return_value.of.return_value = Bucketing.UNKNOWN
    crowd(fab)
    emptied = tmp_path / "Old"
    mark_split(emptied)
    mark_split(emptied / "a")
    (emptied / "a" / "ab").mkdir()

    job.run(control)

    assert is_split(fab)
    assert not list(emptied.iterdir())
    reason = "it is not known whether a layout still buckets it: check the root's layouts, and scan it"
    assert job.outcome == JobOutcome(f"0 moves, 1 folder joined; left: {fab}: {reason}", clean=False)


def test_an_inner_folder_is_joined_before_the_one_around_it(
    job: RebalanceBucketsJob, control: MagicMock, rules: MagicMock, fab: Path
) -> None:
    """Folders nested in another's buckets are joined first; an inner one still governed is moved whole, as it is.

    **Test steps:**

    * split a folder holding, in a bucket, a split author folder the rules still govern and one they do not
    * run the job
    * verify both author folders up in the folder, the first still split, the second flat
    """
    rules.return_value.of.side_effect = lambda folder: (
        Bucketing.GOVERNED if folder.name == "Jane" else Bucketing.UNGOVERNED
    )
    mark_split(fab)
    for author in ("Jane", "John"):
        mark_split(fab / "j" / author)
        file_record(fab / "j" / author / "i", "Intro")

    job.run(control)

    assert names_under(fab) == {
        f"Jane/{BUCKETS_MARKER}",
        "Jane/i/Intro.rehu",
        "Jane/i/Intro00.jpg",
        "John/Intro.rehu",
        "John/Intro00.jpg",
    }


@mark.usefixtures("rules")
def test_a_pinned_bucket_keeps_a_folder_no_rule_buckets_split(
    job: RebalanceBucketsJob, control: MagicMock, fab: Path
) -> None:
    """The owner's *never split* keeps it, as any folder; unlike in a bucketed one it is said, since nothing may be put
    there meanwhile.

    **Test steps:**

    * mark a bucket of a folder no rule buckets never to be split
    * run the job
    * verify nothing moved, and the outcome says why
    """
    mark_split(fab)
    file_record(fab / "a", "abc")
    (fab / "a" / BUCKETS_MARKER).mkdir()

    job.run(control)

    assert is_split(fab)
    reason = "no layout buckets it any more, but a bucket in it is marked never to be split"
    assert job.outcome == JobOutcome(f"0 moves, 0 folders joined; left: {fab}: {reason}", clean=False)


@mark.usefixtures("rules")
def test_a_stray_keeps_a_folder_no_rule_buckets_split(job: RebalanceBucketsJob, control: MagicMock, fab: Path) -> None:
    """What keeps any folder split keeps this one, named by the outcome.

    **Test steps:**

    * put a note in a bucket of a folder no rule buckets
    * run the job
    * verify the folder still split and the outcome naming the note
    """
    crowd(fab)
    (fab / "0" / "notes.txt").write_text("x", encoding="utf-8")

    job.run(control)

    assert is_split(fab)
    assert job.outcome is not None and not job.outcome.clean and "notes.txt" in job.outcome.summary


@mark.usefixtures("rules")
@mark.parametrize("stop", range(0, 3 * SPLIT_LIMIT, 10))
def test_a_whole_join_stopped_anywhere_goes_on(
    job: RebalanceBucketsJob, control: MagicMock, host: MagicMock, fab: Path, stop: int
) -> None:
    """Stopped at a step, every record is in one place, and the next run finishes it.

    **Test steps:**

    * crowd a folder no rule buckets, and ask for a pause at one of the job's questions
    * run the job, then resume and run it again
    * verify every record in one place after the first, and in the folder itself after the second
    """
    names = crowd(fab)
    asked = iter(range(10_000))

    def blocking_move(_root_id: UUID) -> None:
        """Ask for the pause at the chosen question."""
        if next(asked) == stop:
            job.pause()

    host.blocking_move.side_effect = blocking_move
    stopped = False

    try:
        job.run(control)
    except JobPaused:
        stopped = True

    assert sorted(path.stem for path in fab.rglob("*.rehu")) == names
    assert stopped or not is_split(fab)
    host.blocking_move.side_effect = None
    host.blocking_move.return_value = None
    job.resume()
    job.run(control)
    assert sorted(path.stem for path in fab.glob("*.rehu")) == names
    assert not is_split(fab)
