"""The queue file: what the agent writes so that quitting does not throw away planned work
([[appendices.task-queue#lifetime]]).

`rehuco-core` returns data and opens nothing, so the decisions that are genuinely an *installation's*
-- where the file lives, when it is written, and what a corrupt one costs -- are made here.
"""

import json
import logging
from collections.abc import Sequence
from pathlib import Path
from threading import RLock
from typing import Final, cast

from borco_core import atomic_write_text
from rehuco_core import (
    DEFAULT_TASK_JOB_REGISTRY,
    JobState,
    JobStatus,
    TaskJobRegistry,
    TaskQueue,
    TaskQueueItem,
)

from ..settings.persistent_settings import persistent_settings

LOG: Final = logging.getLogger(__name__)

TASK_QUEUE_FILENAME: Final = "task-queue.json"
"""What the saved queue is called, beside the settings file."""


def task_queue_path() -> Path:
    """Where the saved queue lives.

    **Beside the settings file rather than inside it**: this is a list of records with a shape of its
    own, and `QSettings`' flat key space would spell every job's opaque state as
    ``tasks/3/state/paths/7``. Sharing the settings directory is what keeps it per-user and per-scope
    without this module knowing what either means on this OS.

    :returns: the queue file's path, whether or not it exists.
    """
    return Path(persistent_settings().fileName()).parent / TASK_QUEUE_FILENAME


class TaskQueueStore:
    """Reads the saved queue at startup, and writes it whenever the queue's *shape* changes.

    **Written on structural change, never on progress** ([[appendices.task-queue#lifetime]]): an
    enqueue, a removal, a reorder, a retry and a state transition each cost one write, so a five
    thousand file checksum sweep writes about twice rather than five thousand times. What is being
    avoided is `atomic_write_text`'s durability barrier landing on the worker thread -- it is an
    ``fsync`` by design, which the page cache cannot absorb, and on an SMB mount it is worse than the
    disk numbers suggest. The file itself is tens of KB, so wear is not the argument.

    **Loading is two steps, deliberately.** :meth:`read_items` hands back a plain list and
    :meth:`restore` puts one into the queue, because the settings that decide *which* saved jobs come
    back -- and whether unfinished ones come back held or running -- belong to the surface that owns
    them, and a sealed ``load()`` would leave them nowhere to stand.

    Attached as a :class:`~rehuco_core.TaskQueueListener`, so it is called on whichever thread made the
    change; its own bookkeeping is therefore locked, and one write is never interleaved with another.

    :param queue: the queue to keep on disk.
    :param registry: what turns a saved kind back into a job; the app-wide default unless a test says
        otherwise.
    :param path: where to keep it; :func:`task_queue_path` unless a test says otherwise.
    """

    def __init__(
        self,
        queue: TaskQueue,
        registry: TaskJobRegistry = DEFAULT_TASK_JOB_REGISTRY,
        path: Path | None = None,
    ) -> None:
        self.__queue: Final = queue
        self.__registry: Final = registry
        self.__path: Final = path if path is not None else task_queue_path()
        self.__lock: Final = RLock()
        self.__states: dict[int, JobState] = {}

    # region loading

    def read_items(self) -> list[TaskQueueItem]:
        """Read the saved queue off disk, without touching the queue itself.

        **A file that cannot be read costs the saved queue and nothing else**: missing, unparseable,
        or holding something that is not a list of records, it is logged and read as empty. Startup is
        never blocked by it, and the app comes up with an empty queue rather than not at all.

        :returns: the saved items, in the order they were written; empty when there are none to read.
        """
        try:
            text = self.__path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        except OSError:
            LOG.exception("The saved task queue could not be read; starting with an empty queue.")
            return []
        try:
            saved = json.loads(text)
        except ValueError:
            LOG.exception("The saved task queue is not readable JSON; starting with an empty queue.")
            return []
        if not isinstance(saved, list):
            LOG.warning("The saved task queue is not a list of tasks; starting with an empty queue.")
            return []
        # a record off disk is only *claimed* to be an item; what it actually holds is checked where it
        # is used, by the restore that has to survive a hand-edited file anyway.
        return [cast(TaskQueueItem, item) for item in saved if isinstance(item, dict)]

    def restore(self, items: Sequence[TaskQueueItem], *, unfinished_state: JobState = JobState.PAUSED) -> None:
        """Put saved items into the queue, and start keeping it on disk.

        Restoring **nothing** is how a queue with no file yet starts being kept: the attachment is what
        this call is for, and an empty list is a legitimate thing to have read.

        :param items: what to restore -- :meth:`read_items`' answer, or whatever a caller's settings
            left of it.
        :param unfinished_state: whether unfinished work comes back held or queued.
        """
        self.__queue.restore(items, self.__registry, unfinished_state=unfinished_state)
        with self.__lock:
            self.__states = {status.serial: status.state for status in self.__queue.jobs()}
        self.__queue.add_listener(self)

    # endregion

    # region saving

    def save(self) -> None:
        """Write the queue down now.

        Also the *save* in the exit sequence ([[appendices.task-queue#teardown]]): pause, wait, save,
        shut down. Failing to write is logged rather than raised -- it happens on whichever thread
        moved a job, and a queue that could not be saved must not take the operation that changed it
        down with it.

        The snapshot is taken **before** this store's own lock. The callbacks below arrive holding the
        queue's lock and then take this one, so a direct ``save`` that held this lock while asking the
        queue for its snapshot would be the classic two-lock deadlock. Taken outside, neither lock is
        ever waited on while the other is held. What that costs is a direct save racing a structural
        change, where the older snapshot can land last -- and the exit sequence this exists for saves a
        queue that has already been paused and waited idle, where there is no change left to race.
        """
        items = self.__queue.serialize()
        with self.__lock:
            try:
                atomic_write_text(self.__path, json.dumps(items, indent=2))
            except OSError:
                LOG.exception("The task queue could not be saved to %s.", self.__path)

    def job_enqueued(self, status: JobStatus, index: int) -> None:
        """Record the new job and save.

        :param status: the job accepted.
        :param index: where it landed; the queue's own order is what gets written.
        """
        del index
        with self.__lock:
            self.__states[status.serial] = status.state
        self.save()

    def job_updated(self, status: JobStatus) -> None:
        """Save if this job *moved*, and ignore it if it only got further.

        The whole of the write-on-structure rule: a job hashing a large tree reports once per file and
        changes state twice.

        :param status: the job as it now is.
        """
        with self.__lock:
            if self.__states.get(status.serial) == status.state:
                return
            self.__states[status.serial] = status.state
        self.save()

    def jobs_reordered(self, serials: Sequence[int]) -> None:
        """Save the new order.

        :param serials: every job's serial, in the new order; unused, since the queue is asked for its
            own order when it is written.
        """
        del serials
        self.save()

    def jobs_removed(self, serials: Sequence[int]) -> None:
        """Forget the removed jobs and save.

        :param serials: the serials removed.
        """
        with self.__lock:
            for serial in serials:
                self.__states.pop(serial, None)
        self.save()

    def queue_paused_changed(self, paused: bool) -> None:
        """Ignore a fact that is derived from rows already saved.

        Every job that made this flip reported its own state through :meth:`job_updated` first, so
        acting on it would be a second write of the same change.

        :param paused: whether the queue now reads as paused.
        """
        del paused

    # endregion
