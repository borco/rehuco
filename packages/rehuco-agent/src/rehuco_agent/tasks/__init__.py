"""The agent's half of the task queue: where the queue is kept between runs, and the dock that shows it
(#202).

The engine is `rehuco-core`'s and opens nothing ([[appendices.task-queue#home]]); this is the surface
that owns the file, decides when it is written, and hands what it read back to the engine
([[appendices.task-queue#lifetime]]) -- plus the pure view over it ([[appendices.task-queue#observation]]).
"""

from .already_queued import job_already_queued
from .task_progress_delegate import TaskProgressDelegate
from .task_queue_model import TaskQueueModel
from .task_queue_store import TASK_QUEUE_FILENAME, TaskQueueStore, task_queue_path
from .task_queue_widget import TaskQueueWidget

__all__ = [
    "TASK_QUEUE_FILENAME",
    "TaskProgressDelegate",
    "TaskQueueModel",
    "TaskQueueStore",
    "TaskQueueWidget",
    "job_already_queued",
    "task_queue_path",
]
