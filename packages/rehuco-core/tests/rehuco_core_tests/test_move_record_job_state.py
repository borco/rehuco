"""Tests for the move job (#339) as the queue and a saved queue see it: what it answers before a start, each end saved
by its root, and the host the app lends it.

Split from :mod:`test_move_record_job`, whose fixtures and helpers are imported by name.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

from pytest import raises
from rehuco_core import (
    DEFAULT_TASK_JOB_REGISTRY,
    RECORD_MOVE_KIND,
    MoveMode,
    MovePhase,
    MoveRecordJob,
    RecordMoveHosting,
)

from rehuco_core_tests.test_move_record_job import (  # noqa: F401  # pylint: disable=unused-import
    DESTINATION_ROOT,
    NEW_NAME,
    SOURCE_ROOT,
    fixture_host,
    fixture_roots,
    make_record,
    mover,
)


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


# region the host
def test_with_no_host_installed_a_step_runs_here() -> None:
    """The stand-in maps no root, knows of no save, and runs a step at once, after its checkpoint.

    **Test steps:**

    * ask a hosting with nothing installed
    * check each answer, and that the checkpoint ran before the step
    """
    hosting = RecordMoveHosting()
    calls: list[str] = []

    hosting.run_step(lambda: calls.append("step"), lambda: calls.append("checkpoint"))

    assert hosting.root_folder(SOURCE_ROOT) is None
    assert not hosting.save_pending(Path("/r/info.rehu"))
    assert calls == ["checkpoint", "step"]


def test_an_installed_host_answers_for_every_move(host: MagicMock, roots: dict[UUID, Path]) -> None:
    """Once installed, the app's host answers; taking it back restores the stand-in.

    **Test steps:**

    * install a host, ask each question, run a step; then take it back
    * check the host answered and ran the step, and the stand-in answers again
    """
    hosting = RecordMoveHosting()
    hosting.install(host)
    step = MagicMock()

    assert hosting.root_folder(SOURCE_ROOT) == roots[SOURCE_ROOT]
    assert not hosting.save_pending(Path("/r/info.rehu"))
    hosting.run_step(step, MagicMock())
    hosting.install(None)

    step.assert_called_once()
    assert hosting.root_folder(SOURCE_ROOT) is None


# endregion
