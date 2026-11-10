"""Tests for a job told it was given up on while it was not running (#339): :class:`~rehuco_core.AbandonableTaskJob`.

Kept apart from `test_task_queue.py`, whose fakes and fixtures it imports, because that module is past its size cap.
"""

import logging

from pytest import LogCaptureFixture
from rehuco_core import AbandonableTaskJob, JobState, TaskQueue

from .test_task_queue import (  # noqa: F401  # pylint: disable=unused-import
    GatedJob,
    RecordingJob,
    RecordingListener,
    listener_fixture,
    queue_fixture,
    wait_for_state,
)


class LeavingJob(GatedJob):
    """A gated job that counts how often it was told it was given up on.

    :param label: the job's label.
    :param fails: whether being told raises.
    """

    def __init__(self, label: str = "leaving", fails: bool = False) -> None:
        super().__init__(label)
        self.abandoned = 0
        self.__fails = fails

    def abandon(self) -> None:
        """Count the call.

        :raises RuntimeError: when built to fail.
        """
        self.abandoned += 1
        if self.__fails:
            raise RuntimeError("nothing could be taken back")


def test_a_job_with_the_method_is_one_and_a_plain_job_is_not() -> None:
    """The protocol is structural: having ``abandon`` is what opts a job in.

    **Test steps:**

    * check a job with the method against the protocol, then one without
    """
    assert isinstance(LeavingJob(), AbandonableTaskJob)
    assert not isinstance(RecordingJob("plain"), AbandonableTaskJob)


def test_a_queued_job_cancelled_is_told(queue: TaskQueue) -> None:
    """A job cancelled before it ever ran is told, once.

    **Test steps:**

    * pause the queue, enqueue a job, and cancel it
    * check it was told once and reads cancelled
    """
    queue.pause()
    job = LeavingJob()
    serial = queue.enqueue(job)

    queue.cancel(serial)

    assert job.abandoned == 1
    assert queue.jobs()[0].state is JobState.CANCELLED


def test_a_paused_job_cancelled_is_told(queue: TaskQueue, listener: RecordingListener) -> None:
    """A job paused part-way and then cancelled never runs again, so it is told to take back what it left.

    **Test steps:**

    * run a job, pause it at its checkpoint, then cancel it
    * check it was told once
    """
    job = LeavingJob()
    serial = queue.enqueue(job)
    assert job.entered.wait(5)
    queue.pause_job(serial)
    job.release.set()
    assert wait_for_state(listener, serial, JobState.PAUSED)

    queue.cancel(serial)

    assert job.abandoned == 1


def test_a_running_job_cancelled_is_not_told(queue: TaskQueue, listener: RecordingListener) -> None:
    """The running job hears its cancel through ``cancel``, and undoes what it must on its own way out.

    **Test steps:**

    * run a job, cancel it while it runs, and let it stop
    * check it was never told it was given up on
    """
    job = LeavingJob()
    serial = queue.enqueue(job)
    assert job.entered.wait(5)

    queue.cancel(serial)
    job.release.set()

    assert wait_for_state(listener, serial, JobState.CANCELLED)
    assert job.abandoned == 0


def test_an_unfinished_job_removed_is_told_and_a_finished_one_is_not(queue: TaskQueue) -> None:
    """Removing a row gives up on a job that had not finished; a cancelled one was told already.

    **Test steps:**

    * pause the queue, enqueue two jobs, remove the first: it is told
    * cancel the second, then remove it: it was told once, by the cancel
    """
    queue.pause()
    first, second = LeavingJob("first"), LeavingJob("second")
    first_serial, second_serial = queue.enqueue(first), queue.enqueue(second)

    queue.remove(first_serial)
    queue.cancel(second_serial)
    queue.remove(second_serial)

    assert (first.abandoned, second.abandoned) == (1, 1)


def test_a_job_that_cannot_take_anything_back_is_logged(queue: TaskQueue, caplog: LogCaptureFixture) -> None:
    """What ``abandon`` raises is logged, and the cancel stands.

    **Test steps:**

    * pause the queue, enqueue a job whose ``abandon`` raises, and cancel it
    * check it reads cancelled and the failure was logged
    """
    queue.pause()
    serial = queue.enqueue(LeavingJob(fails=True))

    with caplog.at_level(logging.ERROR):
        queue.cancel(serial)

    assert queue.jobs()[0].state is JobState.CANCELLED
    assert "could not take back what it left" in caplog.text
