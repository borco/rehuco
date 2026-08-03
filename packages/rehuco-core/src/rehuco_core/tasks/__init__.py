"""The app-wide task queue: slow work, run one job at a time ([[appendices.task-queue]]).

The non-GUI half of the *task queue / dock* component ([[architecture-design#components]]) -- the layer
agent and node alike run jobs on. It holds the engine and the vocabulary a job is written in, and
nothing about how a queue is drawn.

The package is split by what a reader is here for:

- :mod:`~rehuco_core.tasks.task_job` -- what a job *is*: its states, the control it is handed while it
  runs, and the snapshot an observer is given.
- :mod:`~rehuco_core.tasks.task_queue_listener` -- the observation seam a dock or a status page
  implements.
- :mod:`~rehuco_core.tasks.task_queue` -- :class:`~rehuco_core.tasks.TaskQueue` itself, and its worker
  thread.

Nothing here imports Qt, and nothing here knows what any job does
([[appendices.task-queue#home]]).
"""

from .task_job import FINISHED_JOB_STATES, JobCancelled, JobControl, JobState, JobStatus, TaskJob
from .task_queue import DEFAULT_SHUTDOWN_TIMEOUT, TaskQueue
from .task_queue_listener import TaskQueueListener

__all__ = [
    "DEFAULT_SHUTDOWN_TIMEOUT",
    "FINISHED_JOB_STATES",
    "JobCancelled",
    "JobControl",
    "JobState",
    "JobStatus",
    "TaskJob",
    "TaskQueue",
    "TaskQueueListener",
]
