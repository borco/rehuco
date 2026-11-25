"""What the app lends a record's move (#339): this machine's roots, its saves, and the GUI thread for its renames; and a
rebalance of a root's buckets (#681): the replacements, and the moves it must wait for.

A move job (:class:`~rehuco_core.MoveRecordJob`) runs on a worker, but a rename may not: the rename barrier calls its
before-listeners -- a video player letting go of a file -- on the thread that renames, and they are widgets. So the step
that renames or removes the original is handed to the GUI thread, and the worker waits for it **holding nothing**: no
lock of the barrier's is taken until the step runs there, so an inline rename the user asks for meanwhile simply runs
first. While it waits, the worker keeps calling its job's checkpoint, so a pause or a quit abandons a step that has not
started -- and never one that has.
"""

import logging
import threading
from collections.abc import Callable, Sequence
from enum import Enum, auto
from pathlib import Path
from typing import Final
from uuid import UUID

from PySide6.QtCore import QObject, QThread, Signal
from rehuco_core import (
    FINISHED_JOB_STATES,
    RECORD_MOVE_KIND,
    ROOT_MAPPINGS_FILE_NAME,
    JobState,
    MovePhase,
    MoveRecordJob,
    ReplacementRule,
    ResourceKey,
    RootMappings,
    RootMappingsError,
    SavePayload,
    TaskQueue,
)

from ..settings.location_replacements_settings import shared_location_replacements_settings
from ..settings.move_settings import shared_move_settings
from ..settings.persistent_settings import config_folder

LOG: Final = logging.getLogger(__name__)

STEP_POLL_SECONDS: Final = 0.1
"""How often a worker waiting for its step looks at its job's checkpoint, in seconds."""


class StepState(Enum):
    """Where one handed-over step is."""

    PENDING = auto()
    RUNNING = auto()
    DONE = auto()
    ABANDONED = auto()


class HandedStep:
    """One step handed from a worker to the GUI thread, and what came of it.

    :param step: what to run.
    """

    def __init__(self, step: Callable[[], object]) -> None:
        self.__step: Final = step
        self.__lock: Final = threading.Lock()
        self.__state = StepState.PENDING
        self.done: Final = threading.Event()
        self.error: BaseException | None = None

    def run(self) -> None:
        """Run the step, unless its worker gave up on it first; keep what it raised for the worker."""
        with self.__lock:
            if self.__state is not StepState.PENDING:
                return
            self.__state = StepState.RUNNING
        try:
            self.__step()
        except BaseException as error:  # pylint: disable=broad-exception-caught  # handed back to the worker
            self.error = error
        finally:
            with self.__lock:
                self.__state = StepState.DONE
            self.done.set()

    def abandon(self) -> bool:
        """Give up on the step, if it has not started.

        :returns: whether it was abandoned -- ``False`` once it runs, which the worker then waits out.
        """
        with self.__lock:
            if self.__state is not StepState.PENDING:
                return False
            self.__state = StepState.ABANDONED
            return True


class MainThreadMoveHost(QObject):
    """The app's :class:`~rehuco_core.RecordMoveHost`, installed process-wide before the task queue restores its jobs.

    Roots are read from this machine's mappings file each time a move asks, so a root mapped after the move was queued
    is found. Saves are asked of the window's save owner once it exists (:meth:`follow_pending_saves`), and moves of
    the queue (:meth:`follow_queue`).

    :param mappings_path: this machine's root mappings file; the app's own in its config folder when ``None``.
    :param parent: the Qt parent, which lives on the GUI thread.
    """

    step_requested: Signal = Signal(object)
    """Emitted, from a worker, with a :class:`HandedStep` for the GUI thread to run."""

    def __init__(self, mappings_path: Path | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__mappings_path: Final = (
            mappings_path if mappings_path is not None else config_folder() / ROOT_MAPPINGS_FILE_NAME
        )
        self.__pending_save_of: Callable[[ResourceKey], SavePayload | None] | None = None
        self.__queue: TaskQueue | None = None
        self.__moves: Final = shared_move_settings()
        """Taken here, on the GUI thread, so a worker asking :meth:`split_limit` never builds the shared object."""
        self.__replacements: Final = shared_location_replacements_settings()
        """Taken here for the same reason, for :meth:`location_rules`."""
        self.step_requested.connect(self.__run)

    def follow_pending_saves(self, pending_save_of: Callable[[ResourceKey], SavePayload | None]) -> None:
        """Ask the window's save owner whether a record's save has landed.

        :param pending_save_of: its answer to *what is this record's save not landed yet*.
        """
        self.__pending_save_of = pending_save_of

    def follow_queue(self, queue: TaskQueue) -> None:
        """Ask the app's queue which moves are under way.

        :param queue: the queue moves run on.
        """
        self.__queue = queue

    def root_folder(self, root_id: UUID) -> Path | None:
        """Where this machine finds a root, read from its mappings file now.

        :param root_id: the root.
        :returns: its folder, or ``None`` when it is unmapped or the file cannot be read -- logged.
        """
        try:
            mapping = RootMappings.load(self.__mappings_path).mapping(root_id)
        except (OSError, RootMappingsError) as error:
            LOG.error("Could not read the root mappings %s: %s", self.__mappings_path, error)
            return None
        return None if mapping is None else mapping.path

    def save_pending(self, rehu_path: Path) -> bool:
        """Whether a save of the record has not landed yet; asked on the GUI thread, inside a step.

        :param rehu_path: the record's ``.rehu`` file.
        :returns: whether one is queued or running.
        """
        return self.__pending_save_of is not None and self.__pending_save_of(ResourceKey(rehu_path)) is not None

    def run_step(self, step: Callable[[], object], checkpoint: Callable[[], None]) -> None:
        """Run ``step`` on the GUI thread and wait for it, the job's checkpoint asked while it has not started.

        :param step: what to run; what it raises is raised here.
        :param checkpoint: the job's; what it raises abandons a step not yet started, and is raised here.
        """
        if QThread.currentThread() == self.thread():
            checkpoint()
            step()
            return
        handed = HandedStep(step)
        self.step_requested.emit(handed)
        while not handed.done.wait(STEP_POLL_SECONDS):
            try:
                checkpoint()
            # whatever the checkpoint raises -- a pause, a cancel -- is the job's to raise, once the step is dropped
            except BaseException:  # pylint: disable=broad-exception-caught
                if handed.abandon():
                    raise
        if handed.error is not None:
            raise handed.error

    def split_limit(self) -> int:
        """How many entries a folder of buckets holds before it splits, as the Files page says now (#680): a plain
        attribute read, safe from a worker.

        :returns: the limit.
        """
        return self.__moves.split_limit

    def location_rules(self) -> Sequence[ReplacementRule]:
        """The Location Replacements, as their page says now (#681): a plain attribute read, safe from a worker.

        :returns: the rules, in table order.
        """
        return self.__replacements.rules

    def blocking_move(self, root_id: UUID) -> str | None:
        """The move whose files a rebalance of a root would take from under it (#681): one into its buckets not ended,
        or stopped with part of its copy there, and one out of it about to remove what is left of the original. Safe
        from a worker: the queue is, and a move's own state is read, not kept.

        :param root_id: the root.
        :returns: how its row names it; ``None`` when there is none, or no queue yet.
        """
        if self.__queue is None:
            return None
        for status in self.__queue.jobs():
            job = self.__queue.job(status.serial) if status.kind == RECORD_MOVE_KIND else None
            if isinstance(job, MoveRecordJob) and self.__blocks(job, status.state, root_id):
                return status.label
        return None

    @staticmethod
    def __blocks(job: MoveRecordJob, state: JobState, root_id: UUID) -> bool:
        """Whether a move keeps a root from being rebalanced.

        :param job: the move.
        :param state: its state on the queue.
        :param root_id: the root.
        :returns: whether a rebalance waits for it.
        """
        ended = state in FINISHED_JOB_STATES
        into = job.destination_root == root_id and bool(job.chains) and job.phase is not MovePhase.DONE
        out = job.source_root == root_id and job.phase in (MovePhase.FINISH, MovePhase.CLEANUP)
        # a move that failed, or was canceled with its copy kept, has a half record there until its row is cleared
        return (out and not ended) or (into and (not ended or job.partial is not None))

    def __run(self, handed: HandedStep) -> None:
        """Run a step a worker handed over, on this object's thread.

        :param handed: the step.
        """
        handed.run()
