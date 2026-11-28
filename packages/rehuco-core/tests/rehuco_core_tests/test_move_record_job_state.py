"""Tests for the move job (#339) as the queue and a saved queue see it: what it answers before a start, and each end
saved by its root.

Split from :mod:`test_move_record_job`, whose fixtures and helpers are imported by name.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any, Final
from unittest.mock import MagicMock
from uuid import UUID, uuid4

from pytest import raises
from pytest_mock import MockerFixture
from rehuco_core import (
    DEFAULT_TASK_JOB_REGISTRY,
    RECORD_MOVE_KIND,
    LeftoversRemoved,
    MoveMode,
    MovePhase,
    MoveRecordJob,
    RenameCoordinator,
)

from rehuco_core_tests.test_move_record_job import (  # noqa: F401  # pylint: disable=unused-import
    DESTINATION_ROOT,
    MODULE,
    NEW_NAME,
    SOURCE_ROOT,
    fixture_control,
    fixture_host,
    fixture_roots,
    make_record,
    mover,
    target_of,
)

LEFT: Final = ["content.zip (Access is denied)"]
"""What a cleanup that could not remove everything says it left."""


# region what the queue asks
def test_a_move_says_why_it_cannot_start(roots: dict[UUID, Path], host: MagicMock) -> None:
    """Before every start: a record to move, still there, and a destination this machine maps.

    **Test steps:**

    * validate a job with no record, one whose record is gone, one whose destination root is unmapped, and a sound one
    * check each says why, and the sound one says nothing
    """
    record = make_record(roots[SOURCE_ROOT])

    assert mover(None, host).validate() == "This task has no record."
    assert mover(record.parent / "gone.rehu", host).validate() is not None
    assert "not mapped" in str(mover(record, host, destination_root=uuid4()).validate())
    assert mover(record, host, destination_root=None).destination is None
    assert mover(record, host).validate() is None


def test_a_retry_starts_from_the_first_phase_unless_it_finished(roots: dict[UUID, Path], host: MagicMock) -> None:
    """Retry starts over from checking the source; a move that finished stays finished.

    **Test steps:**

    * reset a job in its target phase, and one that is done
    * check the first is back at the source phase and the second still done
    """
    record = make_record(roots[SOURCE_ROOT])
    halfway = mover(record, host)
    halfway.phase = MovePhase.TARGET
    finished = mover(record, host)
    finished.phase = MovePhase.DONE

    halfway.reset()
    finished.reset()

    assert halfway.phase is MovePhase.SOURCE
    assert finished.phase is MovePhase.DONE
    assert halfway.outcome is None


def test_a_move_names_its_record() -> None:
    """A row reads the record's name, or just *Move* before it has one.

    **Test steps:**

    * build a move of ``Intro`` and one of nothing
    * check their labels
    """
    assert MoveRecordJob(Path("/r/Old/Intro/info.rehu")).label == "Move - Intro"
    assert MoveRecordJob().label == "Move"


def test_the_registry_builds_a_move_from_its_kind() -> None:
    """A saved move comes back as a move.

    **Test steps:**

    * create a job of the move's kind from a state naming a rootless record
    * check it is a move of that record
    """
    state = {"source_root": None, "source": str(Path("/r/info.rehu")), "destination_root": str(DESTINATION_ROOT)}
    job = DEFAULT_TASK_JOB_REGISTRY.create(RECORD_MOVE_KIND, state | {"into": "x", "name": "y"})

    assert isinstance(job, MoveRecordJob)
    assert job.source == Path("/r/info.rehu")


# endregion


# region being written down
def test_a_source_under_a_root_is_saved_by_its_root(roots: dict[UUID, Path], host: MagicMock) -> None:
    """Each end is its root and the path under it, so a remapped drive still finds the record.

    **Test steps:**

    * capture a move of a record under the source root, then remap the source root and restore it
    * check the state names the root and the relative path, and the restored source is under the new folder
    """
    record = make_record(roots[SOURCE_ROOT])
    state = mover(record, host).capture_state()
    roots[SOURCE_ROOT] = Path("/remapped")

    restored = mover(None, host)
    restored.restore_state(state)

    assert (state["source_root"], state["source"]) == (str(SOURCE_ROOT), "Old/Intro/info.rehu")
    assert (state["destination_root"], state["into"], state["name"]) == (str(DESTINATION_ROOT), "Smith/2024", NEW_NAME)
    assert restored.source == Path("/remapped/Old/Intro/info.rehu")


def test_a_source_under_no_root_is_saved_by_its_path(tmp_path: Path, host: MagicMock) -> None:
    """A record under no root has no root to be named by: its absolute path is kept.

    **Test steps:**

    * capture a move of a record under no root and restore it
    * check the state holds the path, and the restored job's source is the record
    """
    record = make_record(tmp_path / "stray")
    state = mover(record, host, source_root=None).capture_state()

    restored = mover(None, host)
    restored.restore_state(state)

    assert (state["source_root"], state["source"]) == (None, str(record))
    assert restored.source == record


def test_a_source_root_unmapped_on_restore_waits_for_its_mapping(roots: dict[UUID, Path], host: MagicMock) -> None:
    """A saved move whose source root this machine no longer maps is kept, says so, and is saved again as it was.

    **Test steps:**

    * capture a move, unmap the source root, restore it
    * check it has no source, validates as unmapped, and captures the same source again
    """
    record = make_record(roots[SOURCE_ROOT])
    state = mover(record, host).capture_state()
    del roots[SOURCE_ROOT]

    restored = mover(None, host)
    restored.restore_state(state)

    assert restored.source is None
    assert "not mapped" in str(restored.validate())
    assert restored.capture_state()["source"] == "Old/Intro/info.rehu"


def test_a_move_with_no_record_saves_no_source(host: MagicMock) -> None:
    """A job built empty writes an empty source, which restoring refuses.

    **Test steps:**

    * capture a job built with no record, then restore its state
    * check the source is empty and restoring raises
    """
    state = mover(None, host, source_root=None).capture_state()

    assert state["source"] == ""
    with raises(ValueError, match="names no record"):
        mover(None, host).restore_state(state)


def test_a_state_that_describes_no_move_is_refused(roots: dict[UUID, Path], host: MagicMock) -> None:
    """Each part of a saved move is checked: a broken one drops the item rather than restoring a broken job.

    **Test steps:**

    * break one key at a time of a sound state
    * check each restore raises ``ValueError``
    """
    sound = mover(make_record(roots[SOURCE_ROOT]), host).capture_state()
    broken: list[Callable[[dict[str, Any]], dict[str, Any]]] = [
        lambda state: state | {"destination_root": None},
        lambda state: state | {"destination_root": "not an id"},
        lambda state: state | {"name": ""},
        lambda state: state | {"into": 3},
        lambda state: state | {"algorithm": "rot13"},
        lambda state: state | {"verified": "content.zip"},
        lambda state: state | {"cleanup": 3},
        lambda state: state | {"cleanup": {"files": "x", "folders": [], "left": ""}},
        lambda state: state | {"cleanup": {"files": [1], "folders": [], "left": ""}},
        lambda state: state | {"phase": "cleanup"},
    ]

    for breaking in broken:
        with raises(ValueError):
            mover(None, host).restore_state(breaking(dict(sound)))


def test_a_state_restores_every_choice(roots: dict[UUID, Path], host: MagicMock) -> None:
    """Every setting a move was queued with comes back with it.

    **Test steps:**

    * capture a rename in its target phase with every option away from its default, and restore it
    * check each one
    """
    job = mover(
        make_record(roots[SOURCE_ROOT]),
        host,
        mode=MoveMode.RENAME,
        check_source=False,
        check_renamed=True,
        create_if_missing=True,
        remove_empty_folders=True,
        algorithm="sha256",
        excluded_patterns=("*.tmp",),
    )
    job.phase = MovePhase.TARGET
    job.verified = ("content.zip",)

    restored = mover(None, host)
    restored.restore_state(job.capture_state())

    assert (restored.mode, restored.phase, restored.verified) == (MoveMode.RENAME, MovePhase.TARGET, ("content.zip",))
    assert (restored.check_source, restored.check_renamed) == (False, True)
    assert (restored.create_if_missing, restored.remove_empty_folders) == (True, True)
    assert (restored.algorithm, restored.excluded_patterns) == ("sha256", ("*.tmp",))
    assert restored.label == "Move - Intro"


# endregion


# region a move that left part of its original (#712)


def test_a_retry_of_a_move_that_left_files_removes_only_those(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, mocker: MockerFixture
) -> None:
    """A move done but for what its original kept goes back to removing that, and nothing else: no check, no copy.

    **Test steps:**

    * make the cleanup leave the original's files the first time, and move a record: done, not clean
    * let the cleanup work, retry the job and run it, counting the checks
    * check no check or copy ran, the original is gone, the copy whole, and the outcome clean
    """
    record = make_record(roots[SOURCE_ROOT])
    cleanup = mocker.patch(f"{MODULE}.remove_leftovers", return_value=LeftoversRemoved(0, 0, LEFT))
    job = mover(record, host)
    job.run(control)
    assert job.outcome is not None and not job.outcome.clean
    assert job.phase is MovePhase.DONE and job.leftover is not None
    mocker.stop(cleanup)
    verify = mocker.patch(f"{MODULE}.verify_checksums")
    copy = mocker.patch(f"{MODULE}.VerifiedCopy")

    job.reset()
    assert job.phase is MovePhase.CLEANUP
    job.run(control)

    verify.assert_not_called()
    copy.assert_not_called()
    assert not record.parent.exists()
    assert (target_of(roots) / "info.rehu").exists()
    assert job.phase is MovePhase.DONE and job.leftover is None
    assert job.outcome is not None and job.outcome.clean


def test_a_retry_that_still_cannot_remove_everything_keeps_what_is_left(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, mocker: MockerFixture
) -> None:
    """A retried removal that is refused again says so again, and can be retried again.

    **Test steps:**

    * make every cleanup leave the original's files, move a record, then retry it
    * check the outcome is still not clean and the leftover is kept for the next retry
    """
    mocker.patch(f"{MODULE}.remove_leftovers", return_value=LeftoversRemoved(0, 0, LEFT))
    job = mover(make_record(roots[SOURCE_ROOT]), host)
    job.run(control)

    job.reset()
    job.run(control)

    assert job.outcome is not None and not job.outcome.clean
    assert job.leftover is not None


def test_what_a_move_left_and_where_it_came_from_survive_a_restart(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock, mocker: MockerFixture
) -> None:
    """A move restored after a restart still knows what its original kept and where it was.

    **Test steps:**

    * make the cleanup leave the original's files, move a record, and restore a new job from its state
    * check the restored job names the same leftover and origin, and a retry of it goes back to removing
    """
    record = make_record(roots[SOURCE_ROOT])
    mocker.patch(f"{MODULE}.remove_leftovers", return_value=LeftoversRemoved(0, 0, LEFT))
    job = mover(record, host)
    job.run(control)

    restored = mover(None, host)
    restored.restore_state(job.capture_state())

    assert restored.leftover == job.leftover
    assert restored.origin == record
    restored.reset()
    assert restored.phase is MovePhase.CLEANUP


def test_a_move_names_where_its_record_was_and_where_it_goes(
    roots: dict[UUID, Path], host: MagicMock, control: MagicMock
) -> None:
    """The origin follows the record until it leaves, and stays where it was then; the landing is its place there.

    **Test steps:**

    * build a copy and a rename of a record and read both places
    * run each and read them again
    """
    record = make_record(roots[SOURCE_ROOT])
    copying = mover(record, host)
    assert (copying.origin, copying.landing) == (record, target_of(roots))

    copying.run(control)

    assert (copying.origin, copying.landing) == (record, target_of(roots))
    assert copying.source == target_of(roots) / "info.rehu"
    other = make_record(roots[DESTINATION_ROOT] / "elsewhere")
    renaming = mover(other, host, mode=MoveMode.RENAME, new_name="Other")
    renaming.run(control)
    assert renaming.origin == other
    assert mover(record, host, destination_root=uuid4()).landing is None


def test_a_moved_record_s_landing_follows_it(roots: dict[UUID, Path], host: MagicMock, control: MagicMock) -> None:
    """Once the record moved, its landing is where the record is, not the place the move named: a bucket split or a
    rename may have taken it on.

    **Test steps:**

    * move a record, then rename it where it landed, through the move's own rename barrier
    * check the landing is the renamed folder
    """
    coordinator = RenameCoordinator()
    job = mover(make_record(roots[SOURCE_ROOT]), host, coordinator=coordinator)
    job.run(control)
    assert job.source is not None

    coordinator.rename(job.source, "Renamed")

    assert job.landing == target_of(roots).parent / "Renamed"


def test_a_move_saved_before_it_named_its_origin_names_none_once_moved(
    roots: dict[UUID, Path], host: MagicMock
) -> None:
    """A state written without the origin cannot say where a record that left was, so it says nothing.

    **Test steps:**

    * capture a finished move, drop its origin, and restore it; then one still in its source phase
    * check the first names no origin, and the second names where its record is
    """
    record = make_record(roots[SOURCE_ROOT])
    done = mover(record, host)
    done.phase = MovePhase.DONE
    state = done.capture_state()
    del state["origin"]
    waiting = mover(record, host)

    restored, unstarted = mover(None, host), mover(None, host)
    restored.restore_state(state)
    unstarted.restore_state(waiting.capture_state())

    assert restored.origin is None
    assert unstarted.origin == record


# endregion
