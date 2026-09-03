"""Tests for the task-queue job vocabulary -- the states, their finished set, the two stop exceptions
and the status snapshot (#201, #237).
"""

from dataclasses import FrozenInstanceError

import pytest
from rehuco_core import (
    FINISHED_JOB_STATES,
    MOVABLE_JOB_STATES,
    JobCancelled,
    JobPaused,
    JobState,
    JobStatus,
)


def test_a_state_is_its_own_stable_spelling() -> None:
    """Every state carries the string a stored or logged value would be, not an opaque number.

    **Test steps:**

    * read each member's value
    * verify it is the member's own lowercase name
    """
    assert [state.value for state in JobState] == [state.name.lower() for state in JobState]


def test_the_finished_states_are_the_three_a_job_never_leaves_on_its_own() -> None:
    """What ``retry`` acts on and everything else refuses, stated once rather than per call site.

    **Test steps:**

    * compare the finished set against the three terminal states
    * verify the three a job can still leave are absent -- ``paused`` above all, since a paused job is
      unfinished work that shutdown must still cancel
    """
    assert FINISHED_JOB_STATES == {JobState.DONE, JobState.FAILED, JobState.CANCELLED}
    assert not FINISHED_JOB_STATES & {JobState.QUEUED, JobState.RUNNING, JobState.PAUSED}


def test_the_movable_states_are_the_two_that_are_not_executing() -> None:
    """A paused job is as reorderable as a queued one, and only a running one is neither.

    **Test steps:**

    * compare the movable set against queued and paused
    * verify the running state is absent
    """
    assert MOVABLE_JOB_STATES == {JobState.QUEUED, JobState.PAUSED}
    assert JobState.RUNNING not in MOVABLE_JOB_STATES


def test_the_two_stops_are_separate_exceptions() -> None:
    """A pause and a cancel end a job in different states, so a job cannot end one by raising the other.

    **Test steps:**

    * verify neither exception is a subclass of the other
    * verify both are ordinary exceptions a job may let escape
    """
    assert not issubclass(JobPaused, JobCancelled)
    assert not issubclass(JobCancelled, JobPaused)
    assert issubclass(JobPaused, Exception) and issubclass(JobCancelled, Exception)


def test_a_status_starts_with_nothing_measured_nothing_wrong_and_nothing_asked() -> None:
    """A job nobody has reported on has no progress, no error and no request against it.

    **Test steps:**

    * build a status from the three facts a job has at enqueue
    * verify progress is ``0`` of an unknown total, and nothing is wrong or requested
    """
    status = JobStatus(serial=7, label="Verify checksums", state=JobState.QUEUED)

    assert (status.done, status.total, status.error) == (0, None, None)
    assert status.stop_requested is None


def test_a_status_defaults_to_the_cautious_declarations() -> None:
    """Absent a claim, a job is about no resource, leaves nothing behind, and promises no resumption.

    **Test steps:**

    * build a status without declaring any of the three
    * verify the defaults are the ones that cost a reader nothing to believe
    """
    status = JobStatus(serial=1, label="Scan", state=JobState.QUEUED)

    assert (status.source, status.safely_interruptible, status.resumes_where_it_stopped) == (None, True, False)


def test_a_status_cannot_be_changed_under_its_reader() -> None:
    """Frozen, because a snapshot crosses a thread boundary on its way to whoever is drawing it.

    **Test steps:**

    * build a status
    * verify assigning to its state raises
    """
    status = JobStatus(serial=1, label="Scan", state=JobState.RUNNING)

    with pytest.raises(FrozenInstanceError):
        status.state = JobState.DONE  # type: ignore[misc]  # refusing this is the point of the test
