"""Tests for the stop protocol written once -- the request slot, the checkpoint, and who may take a
stop back (#237).

These are the job's half of the contract, tested with no queue in sight: everything below is a direct
call, on one thread, because what is being pinned is the state machine rather than any interleaving.
The engine's use of it is :mod:`test_task_queue`.
"""

import pytest
from pytest import fixture, mark
from rehuco_core import JobCancelled, JobControl, JobPaused, StopRequest, TaskJobBase

# region Sample classes

# a fake job is one method by definition -- ``run`` is the whole of what a subclass owes
# pylint: disable=too-few-public-methods


class CountingJob(TaskJobBase):
    """A job that counts its checkpoints, so a test can see how far it got before it unwound."""

    def __init__(self) -> None:
        super().__init__()
        self.label = "counting"
        self.reached = 0

    def run(self, control: JobControl) -> None:
        """Checkpoint three times, counting each one that returned.

        :param control: unused.
        """
        del control
        for _ in range(3):
            self.checkpoint()
            self.reached += 1


# not overriding ``run`` is the whole point of this fake -- it is what the NotImplementedError guards
# pylint: disable-next=abstract-method
class BareJob(TaskJobBase):
    """A job that implements nothing beyond the base -- what the ``NotImplementedError`` guards."""


# endregion

# region Fixtures


@fixture(name="job")
def job_fixture() -> CountingJob:
    """A job with a clean request slot.

    :returns: the job under test.
    """
    return CountingJob()


# endregion

# region The request slot


def test_a_job_with_nothing_asked_of_it_runs_through(job: CountingJob) -> None:
    """A checkpoint costs nothing when nothing is pending, which is why it can be called often.

    **Test steps:**

    * run the job with no request against it
    * verify every checkpoint returned
    """
    job.run(NoControl())

    assert job.reached == 3


@mark.parametrize(
    ("ask", "expected"),
    [("pause", JobPaused), ("cancel", JobCancelled)],
)
def test_a_pending_request_unwinds_the_job_at_its_next_checkpoint(
    job: CountingJob, ask: str, expected: type[Exception]
) -> None:
    """Both stops leave by the same door, and differ only in which exception the engine reads.

    **Test steps:**

    * ask the job to stop, then run it
    * verify it raised the matching exception at the first checkpoint, having done nothing
    """
    getattr(job, ask)()

    with pytest.raises(expected):
        job.run(NoControl())

    assert job.reached == 0


def test_the_latest_instruction_replaces_the_one_before_it(job: CountingJob) -> None:
    """One slot, not two flags: *cancel and pause* is not a state a checkpoint could act on.

    **Test steps:**

    * ask for a cancel, then ask for a pause
    * run the job and verify it paused rather than cancelled
    """
    job.cancel()
    job.pause()

    with pytest.raises(JobPaused):
        job.run(NoControl())


def test_a_request_survives_the_run_that_obeyed_it_until_something_clears_it(job: CountingJob) -> None:
    """The slot is not cleared on entry to ``run``, deliberately -- doing that discards a request made
    before the job first started, which is legal. Clearing is :meth:`resume`'s job, and the engine
    calls it on every job it puts back in line.

    **Test steps:**

    * pause the job and run it, so it unwinds with the request still set
    * run it again with nothing having cleared it
    * verify it stopped again at once, rather than silently forgetting what was asked
    """
    job.pause()
    with pytest.raises(JobPaused):
        job.run(NoControl())

    with pytest.raises(JobPaused):
        job.run(NoControl())

    assert job.reached == 0


# endregion

# region Taking a stop back


def test_a_request_nothing_has_looked_at_is_taken_back_cleanly(job: CountingJob) -> None:
    """The whole point of asking the job rather than guessing: it knows nothing has begun.

    **Test steps:**

    * ask the job to cancel, then tell it to carry on before it ever runs
    * verify it said the stop was taken back, and then ran through
    """
    job.cancel()

    assert job.resume()

    job.run(NoControl())
    assert job.reached == 3


def test_a_request_the_job_has_acted_on_cannot_be_taken_back(job: CountingJob) -> None:
    """Once the job has unwound, a resume is a re-entry rather than a retraction, and it says so.

    **Test steps:**

    * pause the job and run it so it acts on the request
    * tell it to carry on
    * verify it reported the stop as already under way
    """
    job.pause()
    with pytest.raises(JobPaused):
        job.run(NoControl())

    assert not job.resume()


def test_reading_the_request_is_an_acknowledgement(job: CountingJob) -> None:
    """A job that looks in order to tidy up has been told, and the engine can no longer promise that
    nothing has begun -- so looking costs the retraction.

    **Test steps:**

    * ask the job to cancel and read the pending request
    * verify it read back, and that a resume then reports it as under way
    """
    job.cancel()

    assert job.stop_requested is StopRequest.CANCEL

    assert not job.resume()


def test_reading_an_empty_request_acknowledges_nothing(job: CountingJob) -> None:
    """A job that polls and finds nothing has not been told anything, so it keeps its retraction.

    **Test steps:**

    * read the request with nothing pending
    * ask for a cancel and verify it can still be taken back cleanly
    """
    assert job.stop_requested is None

    job.cancel()

    assert job.resume()


def test_a_resume_clears_the_slot_even_when_it_is_too_late_to_help(job: CountingJob) -> None:
    """It is also how a stopped job is made ready to run again, so the clearing is unconditional and
    only the *answer* is about what already happened.

    **Test steps:**

    * pause the job, run it so it unwinds, then resume it
    * run it again and verify it went through rather than pausing at once
    """
    job.pause()
    with pytest.raises(JobPaused):
        job.run(NoControl())

    assert not job.resume()

    job.run(NoControl())
    assert job.reached == 3


def test_reset_drops_a_request_nobody_asked_of_the_retried_job(job: CountingJob) -> None:
    """A retried job inherits the work, never the instruction that stopped the last attempt.

    **Test steps:**

    * cancel the job and run it so it unwinds
    * reset it, then run it again
    * verify it ran through
    """
    job.cancel()
    with pytest.raises(JobCancelled):
        job.run(NoControl())

    job.reset()

    job.run(NoControl())
    assert job.reached == 3


# endregion

# region What a subclass owes


def test_a_job_that_supplies_no_work_refuses_rather_than_succeeds_at_nothing() -> None:
    """``run`` is the one thing the base cannot guess at, so it says so rather than pass silently --
    which would report ``done`` on a job that did nothing.

    **Test steps:**

    * build a job that implements nothing beyond the base
    * verify running it refuses
    """
    bare = BareJob()

    with pytest.raises(NotImplementedError):
        bare.run(NoControl())


def test_the_declarations_default_to_the_cautious_answers() -> None:
    """A job that says nothing is about no resource, leaves nothing behind, and promises no resumption.

    **Test steps:**

    * read the three declarations off a job that overrides none of them
    * verify the defaults
    """
    bare = BareJob()

    assert (bare.source, bare.safely_interruptible, bare.resumes_where_it_stopped) == (None, True, False)


# endregion


class NoControl:
    """A :class:`~rehuco_core.JobControl` that discards progress -- these tests are about stopping."""

    def report(self, done: int, total: int | None = None) -> None:
        """Discard a progress report."""
        del done, total
