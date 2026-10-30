"""Tests for a time spelled as a clock (#572, [[plugins#in-app-player]])."""

from pytest import mark
from rehuco_agent.documents.clock_text import clock_text


@mark.parametrize(
    ("milliseconds", "text"),
    [
        (0, "0:00"),
        (999, "0:00"),
        (5_000, "0:05"),
        (65_000, "1:05"),
        (3_599_000, "59:59"),
        (3_600_000, "1:00:00"),
        (3_725_000, "1:02:05"),
        (-5_000, "0:00"),
    ],
)
def test_a_time_reads_as_minutes_and_seconds_and_hours_from_an_hour_on(milliseconds: int, text: str) -> None:
    """**Test steps:**

    * spell a time
    * verify ``m:ss`` below an hour, ``h:mm:ss`` from it, whole seconds only, and zero for a negative one
    """
    assert clock_text(milliseconds) == text
