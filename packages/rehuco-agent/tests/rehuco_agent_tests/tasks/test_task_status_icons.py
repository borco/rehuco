"""Tests for the status-icon lookup: which glyph a row wears, and the recolored icon cache (#248)."""

from pytest import mark
from rehuco_agent.tasks.task_status_icons import PENDING_STOP_ICONS, STATE_ICONS, status_icon
from rehuco_core import JobState, JobStatus, StopRequest


def status(state: JobState, stop: StopRequest | None = None) -> JobStatus:
    """A job in ``state``, having been asked for ``stop``.

    :param state: the state the job is in.
    :param stop: what it was last asked to do about stopping.
    :returns: the status to look up.
    """
    return JobStatus(serial=1, label="job", state=state, stop_requested=stop)


# region which glyph


@mark.parametrize("state", list(JobState))
def test_every_state_has_its_own_glyph(state: JobState) -> None:
    """An icon-only column cannot have a state it draws nothing for.

    **Test steps:**

    * look up each of the six states in turn
    * verify each answers a distinct icon
    """
    assert status_icon(status(state)) == STATE_ICONS[state]
    assert len(set(STATE_ICONS.values())) == len(JobState)


@mark.parametrize("stop", list(StopRequest))
def test_a_pending_stop_wins_over_the_state_it_is_still_in(stop: StopRequest) -> None:
    """A running job asked to stop is still honestly running, and the glyph says *asked* -- the same
    precedence :func:`~.task_queue_model.state_text` reads the two fields in.

    **Test steps:**

    * look up a running job that has been asked to pause, and one asked to cancel
    * verify each answers its own pending glyph rather than the running one
    """
    drawn = status_icon(status(JobState.RUNNING, stop))

    assert drawn == PENDING_STOP_ICONS[stop]
    assert drawn != STATE_ICONS[JobState.RUNNING]


def test_a_pending_stop_reads_the_same_whatever_state_it_was_asked_in() -> None:
    """A *queued* job can be asked to cancel too, and reads as cancelling like a running one.

    **Test steps:**

    * look up a queued job asked to cancel
    * verify it answers the cancelling glyph, not the queued one
    """
    assert status_icon(status(JobState.QUEUED, StopRequest.CANCEL)) == PENDING_STOP_ICONS[StopRequest.CANCEL]


def test_the_pending_glyphs_are_not_reused_from_the_states() -> None:
    """*Pausing* must not be drawn as *paused*, or the distinction the column exists to keep is lost.

    **Test steps:**

    * compare the two pending glyphs against every state glyph
    * verify all eight are distinct
    """
    assert len(set(STATE_ICONS.values()) | set(PENDING_STOP_ICONS.values())) == len(JobState) + len(StopRequest)


# endregion
