"""Tests for the task-queue job vocabulary -- the states, their finished set, and the status snapshot
(#201).
"""

from dataclasses import FrozenInstanceError

import pytest
from rehuco_core import FINISHED_JOB_STATES, JobState, JobStatus


def test_a_state_is_its_own_stable_spelling() -> None:
    """Every state carries the string a stored or logged value would be, not an opaque number.

    **Test steps:**

    * read each member's value
    * verify it is the member's own lowercase name
    """
    assert [state.value for state in JobState] == [state.name.lower() for state in JobState]


def test_the_finished_states_are_the_three_a_job_never_leaves() -> None:
    """What ``clear_finished`` removes and ``cancel`` refuses, stated once rather than per call site.

    **Test steps:**

    * compare the finished set against the three terminal states
    * verify the three a job can still leave are absent
    """
    assert FINISHED_JOB_STATES == {JobState.DONE, JobState.FAILED, JobState.CANCELLED}
    assert not FINISHED_JOB_STATES & {JobState.QUEUED, JobState.RUNNING, JobState.PAUSED}


def test_a_status_starts_with_nothing_measured_and_nothing_wrong() -> None:
    """A job nobody has reported on has no progress and no error -- not a zero-of-zero or an empty string.

    **Test steps:**

    * build a status from the three facts a job has at enqueue
    * verify progress is ``0`` of an unknown total, and there is no error
    """
    status = JobStatus(serial=7, label="Verify checksums", state=JobState.QUEUED)

    assert (status.done, status.total, status.error) == (0, None, None)


def test_a_status_cannot_be_changed_under_its_reader() -> None:
    """Frozen, because a snapshot crosses a thread boundary on its way to whoever is drawing it.

    **Test steps:**

    * build a status
    * verify assigning to its state raises
    """
    status = JobStatus(serial=1, label="Scan", state=JobState.RUNNING)

    with pytest.raises(FrozenInstanceError):
        status.state = JobState.DONE  # type: ignore[misc]  # refusing this is the point of the test
