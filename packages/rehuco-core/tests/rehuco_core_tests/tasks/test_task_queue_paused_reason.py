"""Tests for a job that pauses itself with a reason (#682): :attr:`~rehuco_core.JobPaused.reason` on the row, and what
each control does to it.

Kept apart from `test_task_queue.py`, whose fakes and fixtures it imports, because that module is past its size cap --
as `test_task_queue_waiting.py` is, whose shape this follows: a pause the job takes itself is the outcome of a run,
like a wait, and differs in that only the user's resume brings it back.
"""

from collections.abc import Callable
from threading import Event
from typing import Final

import pytest
from rehuco_core import JobControl, JobPaused, JobState, TaskQueue

from .test_task_queue import (  # noqa: F401  # pylint: disable=unused-import
    TIMEOUT,
    GatedJob,
    RecordingListener,
    SampleJob,
    SelfPausingJob,
    listener_fixture,
    queue_fixture,
    settles_fixture,
    wait_for_state,
)

REASON: Final = "Fab asks for a challenge: solve it in the browser, then resume."
"""What every self-pausing job below says stopped it."""


class GatedSelfPausingJob(SampleJob):
    """A job the test holds mid-run, which looks at its stop request and then pauses itself with :data:`REASON`;
    its second run finishes.

    It looks before it raises, so a resume asked after that look is too late to take the stop back -- the one way a
    paused outcome lands with a resume already asked for.

    :param label: the job's label.
    """

    def __init__(self, label: str = "gated-self-pausing") -> None:
        super().__init__(label)
        self.runs = 0
        self.entered: Final = Event()
        self.release: Final = Event()
        self.looked: Final = Event()
        self.unwind: Final = Event()

    def run(self, control: JobControl) -> None:
        """Announce, wait for the test, look at the stop request, wait again, then pause itself; finish the next time.

        :param control: unused.
        :raises JobPaused: on the first run, with :data:`REASON`.
        """
        del control
        self.runs += 1
        if self.runs > 1:
            return
        self.entered.set()
        self.release.wait(TIMEOUT)
        _ = self.stop_requested
        self.looked.set()
        self.unwind.wait(TIMEOUT)
        raise JobPaused(REASON)


def test_a_job_that_pauses_itself_is_held_with_its_reason(queue: TaskQueue, listener: RecordingListener) -> None:
    """The reason the job gave is the row's message, and nothing runs it again by itself.

    **Test steps:**

    * enqueue a job that pauses itself with a reason
    * verify it is paused with that reason as its message and no stop request
    * verify it ran once
    """
    job = SelfPausingJob(reason=REASON)
    serial = queue.enqueue(job)

    assert wait_for_state(listener, serial, JobState.PAUSED)

    assert queue.wait_until_idle(TIMEOUT)
    status = queue.jobs()[0]
    assert (status.state, status.message, status.stop_requested) == (JobState.PAUSED, REASON, None)
    assert job.runs == 1


def test_a_pause_the_user_asked_for_carries_no_message(queue: TaskQueue, listener: RecordingListener) -> None:
    """A pause asked from outside has nothing to say, and the job's label never reads as one.

    **Test steps:**

    * hold a job mid-run and pause it, so it obeys at its checkpoint
    * verify it is paused with no message
    """
    job = GatedJob()
    serial = queue.enqueue(job)
    assert job.entered.wait(TIMEOUT)

    queue.pause_job(serial)
    job.release.set()

    assert wait_for_state(listener, serial, JobState.PAUSED)
    assert queue.jobs()[0].message is None


def test_resuming_a_self_paused_job_clears_its_reason_and_runs_it(
    queue: TaskQueue, listener: RecordingListener, settles: Callable[[Callable[[], bool]], None]
) -> None:
    """Resume is how the user says *look again*: the reason goes with the pause, and the job runs.

    **Test steps:**

    * let a job pause itself with a reason
    * resume it
    * verify the row went back in line with no message and the job ran again
    """
    job = SelfPausingJob(reason=REASON)
    serial = queue.enqueue(job)
    assert wait_for_state(listener, serial, JobState.PAUSED)
    assert queue.wait_until_idle(TIMEOUT)

    assert queue.resume_job(serial) is True

    queued = [status for status in listener.updated if status.serial == serial and status.state is JobState.QUEUED]
    assert queued
    assert queued[-1].message is None
    settles(lambda: listener.states_of(serial).count(JobState.PAUSED) == 2)
    assert job.runs == 2


def test_canceling_a_self_paused_job_ends_it_without_its_reason(queue: TaskQueue, listener: RecordingListener) -> None:
    """A cancel aimed at a self-paused row ends it, and what stopped it no longer applies to anything.

    **Test steps:**

    * let a job pause itself with a reason
    * cancel it
    * verify it is canceled with no message
    """
    serial = queue.enqueue(SelfPausingJob(reason=REASON))
    assert wait_for_state(listener, serial, JobState.PAUSED)

    queue.cancel(serial)

    status = queue.jobs()[0]
    assert (status.state, status.message) == (JobState.CANCELED, None)


@pytest.mark.parametrize(
    ("ask", "landed"), [("cancel", JobState.CANCELED), ("resume_job", JobState.QUEUED)], ids=["cancel", "resume"]
)
def test_a_reason_landing_after_a_cancel_or_a_late_resume_is_dropped(
    queue: TaskQueue, listener: RecordingListener, ask: str, landed: JobState
) -> None:
    """A self-pause reconciled to what was asked meanwhile lands as that, without the reason it no longer has.

    **Test steps:**

    * hold a job mid-run and ask it to pause, so it looks at the request
    * cancel it, or resume it once it has looked (too late to take the stop back)
    * let it pause itself with a reason
    * verify it landed canceled or back in line, with no message
    """
    job = GatedSelfPausingJob()
    serial = queue.enqueue(job)
    assert job.entered.wait(TIMEOUT)
    queue.pause_job(serial)
    job.release.set()
    assert job.looked.wait(TIMEOUT)

    getattr(queue, ask)(serial)
    job.unwind.set()

    assert wait_for_state(listener, serial, landed)
    landing = next(status for status in listener.updated if status.serial == serial and status.state is landed)
    assert landing.message is None
    assert JobState.PAUSED not in listener.states_of(serial)
