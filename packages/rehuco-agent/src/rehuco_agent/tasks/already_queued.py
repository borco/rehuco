"""Whether the work about to be enqueued is already waiting ([[data-model#checksums]], #204).

**Asking twice is not asking again.** Clicking Verify on a document whose verify is still queued, or
sweeping a folder that is already being swept, should leave the queue as it is rather than add a second
identical row -- and the rule has to hold for a job restored from the last session too, which is why it
is asked of the queue's own rows rather than of anything this process remembers.

One function rather than a copy per surface: the document actions and the sweep must agree on what
*the same work* means, and two implementations of that are two chances to disagree.
"""

from pathlib import Path

from rehuco_core import FINISHED_JOB_STATES, TaskQueue


def job_already_queued(queue: TaskQueue, *, label: str, source: Path | None) -> bool:
    """Whether an unfinished job doing this same work is in the queue already.

    Matched on the row as a reader sees it -- its label and its resource -- rather than on a job's type
    or its private parameters: the label already carries the verb and the resource's name, and a second
    row reading exactly like the first is the thing worth refusing.

    :param queue: the queue to look in.
    :param label: the label the job about to be enqueued would carry.
    :param source: the resource or folder that job is about, as it is now.
    :returns: whether one like it is already waiting, running or paused.
    """
    return any(
        status.state not in FINISHED_JOB_STATES and status.label == label and status.source == source
        for status in queue.jobs()
    )
