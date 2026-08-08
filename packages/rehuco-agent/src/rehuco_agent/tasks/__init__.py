"""The agent's half of the task queue: where the queue is kept between runs, and the dock that shows it
(#202).

The engine is `rehuco-core`'s and opens nothing ([[appendices.task-queue#home]]); this is the surface
that owns the file, decides when it is written, and hands what it read back to the engine
([[appendices.task-queue#lifetime]]) -- plus the pure view over it ([[appendices.task-queue#observation]]).

It is also where a job's progress is *rendered*: core declares what a run counts and this side decides
how that reads ([[appendices.task-queue#dock]], #248).
"""

from .already_queued import job_already_queued
from .task_info_delegate import TaskInfoDelegate
from .task_progress_renderers import PROGRESS_RENDERERS, progress_text
from .task_queue_model import TaskQueueModel
from .task_queue_store import TASK_QUEUE_FILENAME, TaskQueueStore, task_queue_path
from .task_queue_widget import TaskQueueWidget
from .task_state_delegate import TaskStateDelegate
from .task_status_icons import PENDING_STOP_ICONS, STATE_ICONS, status_icon

__all__ = [
    "PENDING_STOP_ICONS",
    "PROGRESS_RENDERERS",
    "STATE_ICONS",
    "TASK_QUEUE_FILENAME",
    "TaskInfoDelegate",
    "TaskStateDelegate",
    "TaskQueueModel",
    "TaskQueueStore",
    "TaskQueueWidget",
    "job_already_queued",
    "progress_text",
    "status_icon",
    "task_queue_path",
]
