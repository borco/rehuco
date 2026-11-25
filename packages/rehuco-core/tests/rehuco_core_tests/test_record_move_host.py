"""Tests for the host the app lends a record's move (#339): the stand-in with nothing installed, and the app's host
once it is.

The ``host`` and ``roots`` fixtures are :mod:`test_move_record_job`'s, imported by name.
"""

from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID

from rehuco_core import DEFAULT_SPLIT_LIMIT, RecordMoveHosting, ReplacementRule

from rehuco_core_tests.test_move_record_job import (  # noqa: F401  # pylint: disable=unused-import
    SOURCE_ROOT,
    fixture_host,
    fixture_roots,
)


def test_with_no_host_installed_a_step_runs_here() -> None:
    """The stand-in maps no root, knows of no save and no move, splits at the shipped limit (#680) with no
    replacements (#681), and runs a step at once, after its checkpoint.

    **Test steps:**

    * ask a hosting with nothing installed
    * check each answer, and that the checkpoint ran before the step
    """
    hosting = RecordMoveHosting()
    calls: list[str] = []

    hosting.run_step(lambda: calls.append("step"), lambda: calls.append("checkpoint"))

    assert hosting.root_folder(SOURCE_ROOT) is None
    assert not hosting.save_pending(Path("/r/info.rehu"))
    assert hosting.split_limit() == DEFAULT_SPLIT_LIMIT
    assert hosting.location_rules() == ()
    assert hosting.blocking_move(SOURCE_ROOT) is None
    assert calls == ["checkpoint", "step"]


def test_an_installed_host_answers_for_every_move(host: MagicMock, roots: dict[UUID, Path]) -> None:
    """Once installed, the app's host answers; taking it back restores the stand-in.

    **Test steps:**

    * install a host, ask each question, run a step; then take it back
    * check the host answered and ran the step, and the stand-in answers again
    """
    hosting = RecordMoveHosting()
    hosting.install(host)
    host.split_limit.return_value = 75
    host.location_rules.return_value = (ReplacementRule(": ", " - "),)
    host.blocking_move.side_effect = lambda root_id: f"Move into {root_id}"
    step = MagicMock()

    assert hosting.root_folder(SOURCE_ROOT) == roots[SOURCE_ROOT]
    assert not hosting.save_pending(Path("/r/info.rehu"))
    assert hosting.split_limit() == 75
    assert hosting.location_rules() == (ReplacementRule(": ", " - "),)
    assert hosting.blocking_move(SOURCE_ROOT) == f"Move into {SOURCE_ROOT}"
    hosting.run_step(step, MagicMock())
    hosting.install(None)

    step.assert_called_once()
    assert hosting.root_folder(SOURCE_ROOT) is None
