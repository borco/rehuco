"""Tests for trying a refused filesystem call again."""

from typing import Final

import pytest
from borco_core import retry_refused
from pytest_mock import MockerFixture

DELAYS: Final = (0.01, 0.02, 0.05)


def test_a_call_refused_for_a_moment_is_tried_again_after_each_delay(mocker: MockerFixture) -> None:
    """A call refused twice then allowed lands, having waited the first two delays.

    **Test steps:**

    * patch ``time.sleep``; make a call that is refused twice, then succeeds
    * run it through ``retry_refused``
    * verify three calls, and a sleep for each of the first two delays
    """
    sleep = mocker.patch("borco_core.retry_refused.time.sleep")
    attempt = mocker.Mock(side_effect=[PermissionError, PermissionError, None])
    retry_refused(attempt, DELAYS)
    assert attempt.call_count == 3
    assert sleep.call_args_list == [mocker.call(DELAYS[0]), mocker.call(DELAYS[1])]


def test_a_call_refused_past_every_delay_raises_the_last_refusal(mocker: MockerFixture) -> None:
    """A call refused after the last delay is spent raises that refusal: one call per delay, and one more.

    **Test steps:**

    * patch ``time.sleep``; make a call that is always refused
    * run it through ``retry_refused``
    * verify it raises ``PermissionError`` after four calls, having slept every delay
    """
    sleep = mocker.patch("borco_core.retry_refused.time.sleep")
    attempt = mocker.Mock(side_effect=PermissionError("held"))
    with pytest.raises(PermissionError, match="held"):
        retry_refused(attempt, DELAYS)
    assert attempt.call_count == len(DELAYS) + 1
    assert sleep.call_args_list == [mocker.call(delay) for delay in DELAYS]


def test_another_failure_passes_straight_through(mocker: MockerFixture) -> None:
    """Only a refusal is retried: any other error is the call's own, raised at once.

    **Test steps:**

    * patch ``time.sleep``; make a call that raises ``FileNotFoundError``
    * run it through ``retry_refused``
    * verify it raises after one call, with no sleep
    """
    sleep = mocker.patch("borco_core.retry_refused.time.sleep")
    attempt = mocker.Mock(side_effect=FileNotFoundError)
    with pytest.raises(FileNotFoundError):
        retry_refused(attempt, DELAYS)
    attempt.assert_called_once()
    sleep.assert_not_called()
