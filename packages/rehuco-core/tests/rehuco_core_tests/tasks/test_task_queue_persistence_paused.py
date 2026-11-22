"""Tests for what a restart keeps of a job that paused itself with a reason (#682).

Kept apart from `test_task_queue_persistence.py`, whose fakes and fixtures it imports, so that module stays under its
size cap, as `test_task_queue_persistence_waiting.py` is: the reason is written as the row's ``message``, and comes
back only with the pause.
"""

from typing import Final

from rehuco_core import JobControl, JobPaused, JobState, TaskJobRegistry, TaskQueue, TaskQueueItem

from .test_task_queue import (  # noqa: F401  # pylint: disable=unused-import
    RecordingListener,
    listener_fixture,
    wait_for_state,
)
from .test_task_queue_persistence import (  # noqa: F401  # pylint: disable=unused-import
    CounterJob,
    queue_fixture,
    registry_fixture,
)

REASON: Final = "The disk holding the root is full."
"""What the self-pausing job below says stopped it."""


class SelfPausingCounterJob(CounterJob):
    """A persistable job whose every run pauses itself with :data:`REASON`."""

    def run(self, control: JobControl) -> None:
        """Pause itself.

        :param control: unused.
        :raises JobPaused: always.
        """
        del control
        raise JobPaused(REASON)


def paused_item() -> TaskQueueItem:
    """A saved item of a job that paused itself with :data:`REASON`.

    :returns: the item.
    """
    return {
        "kind": CounterJob.kind,
        "label": "was-paused",
        "job_state": JobState.PAUSED.value,
        "state": {"cursor": 0},
        "message": REASON,
    }


def test_a_self_paused_job_is_written_paused_with_its_reason(queue: TaskQueue, listener: RecordingListener) -> None:
    """What stopped a job outlives the session, so the restored row still says what to do.

    **Test steps:**

    * enqueue a persistable job that pauses itself with a reason
    * serialize the queue
    * verify the item is in the paused state with the reason as its message
    """
    serial = queue.enqueue(SelfPausingCounterJob("paused"))
    assert wait_for_state(listener, serial, JobState.PAUSED)

    (item,) = queue.serialize()

    assert (item["job_state"], item.get("message")) == (JobState.PAUSED.value, REASON)


def test_a_self_paused_item_restored_paused_keeps_its_reason(
    queue: TaskQueue, registry: TaskJobRegistry, listener: RecordingListener
) -> None:
    """Unfinished work revived held comes back with what stopped it.

    **Test steps:**

    * restore a self-paused item, asking for unfinished work to come back paused
    * verify it came back paused with its reason
    """
    queue.restore([paused_item()], registry, unfinished_state=JobState.PAUSED)

    ((status, _),) = listener.enqueued
    assert (status.state, status.message) == (JobState.PAUSED, REASON)


def test_a_self_paused_item_restored_queued_drops_its_reason(
    queue: TaskQueue, registry: TaskJobRegistry, listener: RecordingListener
) -> None:
    """Revived queued, the job looks again at what stopped it, so the old reason would describe nothing.

    **Test steps:**

    * restore a self-paused item, asking for unfinished work to come back queued
    * verify it came back queued with no message
    """
    queue.restore([paused_item()], registry, unfinished_state=JobState.QUEUED)

    ((status, _),) = listener.enqueued
    assert (status.state, status.message) == (JobState.QUEUED, None)
