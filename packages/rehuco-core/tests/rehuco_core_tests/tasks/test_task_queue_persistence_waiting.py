"""Tests for what a restart keeps of a row's message and of a waiting job (#497).

Kept apart from `test_task_queue_persistence.py`, whose fakes and fixtures it imports, so that module stays under its
size cap; the subject is the one #497 changed there: the reason a row carries is written as ``message``, an old file's
``error`` is still read, and a wait comes back as a wait.
"""

from collections.abc import Callable
from typing import Final

import pytest
from rehuco_core import JobControl, JobState, JobWaiting, TaskJobRegistry, TaskQueue, TaskQueueItem

from .test_task_queue import (  # noqa: F401  # pylint: disable=unused-import
    RecordingListener,
    listener_fixture,
    wait_for_state,
)
from .test_task_queue_persistence import (  # noqa: F401  # pylint: disable=unused-import
    CounterJob,
    queue_fixture,
    registry_fixture,
    settles_fixture,
)

REASON: Final = "The share does not answer."
"""What the waiting job below says it waits for."""

REFUSAL: Final = "The resource no longer exists."
"""What the refusing job below objects with."""


class WaitingCounterJob(CounterJob):
    """A persistable job whose every run reports it cannot proceed for an hour."""

    def run(self, control: JobControl) -> None:
        """Report a wait.

        :param control: the engine's face to this job.
        :raises JobWaiting: always.
        """
        del control
        raise JobWaiting(REASON, 3600.0)


# region Writing the message down


def test_a_failed_jobs_reason_is_written_as_its_message(
    queue: TaskQueue, settles: Callable[[Callable[[], bool]], None]
) -> None:
    """The key is ``message`` now, and the old spelling is never written.

    **Test steps:**

    * enqueue a job that refuses to start, and let it fail
    * serialize the queue
    * verify the item carries the refusal under ``message`` and has no ``error`` key
    """
    queue.enqueue(CounterJob("gone", refusal=REFUSAL))
    settles(lambda: queue.jobs()[0].state is JobState.FAILED)

    (item,) = queue.serialize()

    assert item.get("message") == REFUSAL
    assert "error" not in item


def test_a_waiting_job_is_written_waiting_with_what_it_waits_for(queue: TaskQueue, listener: RecordingListener) -> None:
    """A wait outlives the session as a wait, saying why.

    **Test steps:**

    * enqueue a persistable job that waits
    * serialize the queue
    * verify the item is in the waiting state with the reason as its message
    """
    serial = queue.enqueue(WaitingCounterJob("waiting"))
    assert wait_for_state(listener, serial, JobState.WAITING)

    (item,) = queue.serialize()

    assert (item["job_state"], item.get("message")) == (JobState.WAITING.value, REASON)


# endregion

# region Reading it back


@pytest.mark.parametrize("unfinished_state", [JobState.PAUSED, JobState.QUEUED])
def test_a_waiting_item_comes_back_waiting_and_due_now(
    queue: TaskQueue,
    registry: TaskJobRegistry,
    listener: RecordingListener,
    settles: Callable[[Callable[[], bool]], None],
    unfinished_state: JobState,
) -> None:
    """A wait is not a hold, so it is not revived in the unfinished state, and its wait is over by the restart.

    **Test steps:**

    * restore a waiting item, asking for unfinished work to come back paused or queued
    * verify it came back waiting with its reason
    * verify it runs to the end without anybody resuming it
    """
    item: TaskQueueItem = {
        "kind": CounterJob.kind,
        "label": "was-waiting",
        "job_state": JobState.WAITING.value,
        "state": {"cursor": 0},
        "message": REASON,
    }

    queue.restore([item], registry, unfinished_state=unfinished_state)

    ((status, _),) = listener.enqueued
    assert (status.state, status.message) == (JobState.WAITING, REASON)
    settles(lambda: queue.jobs()[0].state is JobState.DONE)


@pytest.mark.parametrize("job_state", [JobState.FAILED, JobState.WAITING])
def test_an_old_files_error_is_read_as_the_message(
    queue: TaskQueue, registry: TaskJobRegistry, listener: RecordingListener, job_state: JobState
) -> None:
    """A queue file written before #497 spells the message ``error``, and a restart must not lose it.

    **Test steps:**

    * restore a failed, or a waiting, item that carries its reason only under ``error``
    * verify the row came back saying it, read as it was announced since a waiting row is due at once
    """
    item: TaskQueueItem = {
        "kind": CounterJob.kind,
        "label": "old",
        "job_state": job_state.value,
        "state": {"cursor": 0},
        "error": REASON,
    }

    queue.restore([item], registry)

    ((status, _),) = listener.enqueued
    assert (status.state, status.message) == (job_state, REASON)


# endregion
