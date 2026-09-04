"""The app-wide task queue: slow work, run one job at a time ([[appendices.task-queue]]).

The non-GUI half of the *task queue / dock* component ([[architecture-design#components]]) -- the layer
agent and node alike run jobs on. It holds the engine and the vocabulary a job is written in, and
nothing about how a queue is drawn.

The package is split by what a reader is here for:

- :mod:`~rehuco_core.tasks.task_job` -- what a job *is*: its states, what it can be asked, the control
  it is handed while it runs, and the snapshot an observer is given.
- :mod:`~rehuco_core.tasks.task_job_base` -- the stop protocol written once, which is what most jobs
  inherit rather than implement.
- :mod:`~rehuco_core.tasks.persistable_task_job` -- what a job adds to survive a restart, and the
  record it survives as.
- :mod:`~rehuco_core.tasks.task_job_registry` -- what turns a saved kind back into a job.
- :mod:`~rehuco_core.tasks.task_queue_listener` -- the observation seam a dock or a status page
  implements.
- :mod:`~rehuco_core.tasks.task_queue` -- :class:`~rehuco_core.tasks.TaskQueue` itself, and its worker
  thread.

Nothing here imports Qt, and nothing here knows what any job does
([[appendices.task-queue#home]]).
"""

from .persistable_task_job import PersistableTaskJob, TaskQueueItem
from .task_job import (
    FINISHED_JOB_STATES,
    PROGRESS_UNIT_BYTES,
    PROGRESS_UNIT_RESOURCES,
    JobCancelled,
    JobControl,
    JobPaused,
    JobScope,
    JobState,
    JobStatus,
    StopRequest,
    TaskJob,
)
from .task_job_base import TaskJobBase
from .task_job_registry import DEFAULT_TASK_JOB_REGISTRY, TaskJobRegistry
from .task_queue import (
    DEFAULT_SHUTDOWN_TIMEOUT,
    MOVABLE_JOB_STATES,
    RESTORED_UNFINISHED_STATES,
    TaskQueue,
)
from .task_queue_listener import TaskQueueListener

__all__ = [
    "DEFAULT_SHUTDOWN_TIMEOUT",
    "DEFAULT_TASK_JOB_REGISTRY",
    "FINISHED_JOB_STATES",
    "MOVABLE_JOB_STATES",
    "PROGRESS_UNIT_BYTES",
    "PROGRESS_UNIT_RESOURCES",
    "RESTORED_UNFINISHED_STATES",
    "JobCancelled",
    "JobControl",
    "JobPaused",
    "JobScope",
    "JobState",
    "JobStatus",
    "PersistableTaskJob",
    "StopRequest",
    "TaskJob",
    "TaskJobBase",
    "TaskJobRegistry",
    "TaskQueue",
    "TaskQueueItem",
    "TaskQueueListener",
]
