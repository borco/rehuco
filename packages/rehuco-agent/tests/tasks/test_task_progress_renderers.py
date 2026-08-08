"""Tests for the progress renderers: how each unit a job can declare reads in a row (#248)."""

from typing import Final

from pytest import mark
from rehuco_agent.tasks.task_progress_renderers import progress_text
from rehuco_core import PROGRESS_UNIT_BYTES, PROGRESS_UNIT_RESOURCES, JobState, JobStatus

UNKNOWN_UNIT: Final = "furlongs"
"""A unit no renderer is registered for, which is what exercises the fallback."""


def status(done: int, total: int | None, unit: str) -> JobStatus:
    """A running job reporting ``done`` of ``total`` in ``unit``.

    :param done: units finished.
    :param total: units expected, or ``None``.
    :param unit: what the job declares it counts.
    :returns: the status to render.
    """
    return JobStatus(serial=1, label="job", state=JobState.RUNNING, done=done, total=total, progress_unit=unit)


@mark.parametrize(
    ("done", "total", "expected"),
    [
        (1536, 4096, "1.5K / 4.0K"),
        (0, 8 * 1024**3, "0B / 8.0G"),
        (1536, None, "1.5K"),
        (1536, 0, "1.5K"),
    ],
)  # (0, None) and (0, 0) are the *nothing to do* case, covered on its own below
def test_bytes_are_humanized_at_both_ends(done: int, total: int | None, expected: str) -> None:
    """A byte-counting job reads in the same GNU-style units a resource's size does, and drops the
    denominator when there is not one yet.

    **Test steps:**

    * render a byte-counting job at each of four done/total pairs
    * verify each reads as its humanized figure, with the total only when there is one
    """
    assert progress_text(status(done, total, PROGRESS_UNIT_BYTES)) == expected


@mark.parametrize(
    ("done", "total", "expected"),
    [
        (12, 40, "12 / 40 resources"),
        (1, 1, "1 / 1 resource"),
        (0, 1, "0 / 1 resource"),
        (12, None, "12 resources"),
        (1, None, "1 resource"),
    ],
)
def test_resources_are_counted_and_named(done: int, total: int | None, expected: str) -> None:
    """A resource-counting job says what it is counting, singular when there is one of them.

    The noun follows the *total* where there is one -- ``0 / 1 resource`` is about one resource, none
    of it done -- and the done count only when it is standing alone.

    **Test steps:**

    * render a resource-counting job at each of five done/total pairs
    * verify each reads as a named count agreeing in number
    """
    assert progress_text(status(done, total, PROGRESS_UNIT_RESOURCES)) == expected


@mark.parametrize(
    ("done", "total", "expected"),
    [
        (3, 4, "3/4"),
        (7, None, "7"),
    ],
)
def test_an_unregistered_unit_falls_back_to_the_bare_numbers(done: int, total: int | None, expected: str) -> None:
    """A unit this build has never heard of still shows its honest figures, unlabelled -- better than
    nothing, and better than inventing a name for them.

    **Test steps:**

    * render a job declaring a unit nothing is registered for, at two done/total pairs
    * verify each reads as the plain numbers
    """
    assert progress_text(status(done, total, UNKNOWN_UNIT)) == expected


@mark.parametrize("unit", [PROGRESS_UNIT_BYTES, PROGRESS_UNIT_RESOURCES, UNKNOWN_UNIT])
@mark.parametrize("total", [None, 0])
def test_a_job_that_counted_nothing_and_had_nothing_to_count_renders_nothing(unit: str, total: int | None) -> None:
    """*Nothing to do* is not *did nothing*: a verify whose files were all checked recently has no
    bytes to read, and its row must not read ``0B``.

    Every unit answers the same way, because the emptiness is decided before a renderer is asked.

    **Test steps:**

    * render a job reporting 0 of nothing, in each unit in turn
    * verify each comes back empty
    """
    assert progress_text(status(0, total, unit)) == ""


@mark.parametrize(
    ("unit", "expected"),
    [
        (PROGRESS_UNIT_BYTES, "0B / 8.0G"),
        (PROGRESS_UNIT_RESOURCES, "0 / 40 resources"),
        (UNKNOWN_UNIT, "0/40"),
    ],
)
def test_a_zero_against_a_real_total_still_reads(unit: str, expected: str) -> None:
    """A job that has not started but has work ahead of it is not the empty case -- forty resources
    waiting is exactly what a reader wants to see.

    **Test steps:**

    * render a job reporting 0 against a real total, in each unit in turn
    * verify each names what it is about to do
    """
    total = 8 * 1024**3 if unit == PROGRESS_UNIT_BYTES else 40

    assert progress_text(status(0, total, unit)) == expected


def test_a_job_declaring_no_unit_renders_nothing() -> None:
    """No unit is the honest answer for one indivisible step, and it renders as an empty cell rather
    than as a bar that would jump from empty to full.

    **Test steps:**

    * render a job that reported 1 of 1 and declared no unit
    * verify nothing at all comes back
    """
    assert progress_text(status(1, 1, "")) == ""
