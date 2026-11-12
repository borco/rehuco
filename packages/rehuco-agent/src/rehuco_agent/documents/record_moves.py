"""One document's moves to a root's place (#339): a rename at once, or a verified move on the task queue.

**Which is decided up front** ([[mounts-and-storage#safe-move-rename]]). A place on the record's own volume -- the same
local disk, or the same share however it is reached -- is a rename; when the Files page asks for that rename to be
verified (*on a local disk*, *on a network share*), it is a task that verifies before and after, and otherwise it runs
at once, as #579's move in place does. A place on another volume is always a task: a copy, checked against the
record, the original removed only once the copy matched.

A task's end is told on the document's banner: a failure, or a move that left part of the original behind, as the
rename failures are; a clean landing as a rename's, so the record is read again where it now is. Its progress is the
Tasks dock's. **A move this document did not queue is told the same way** -- one the queue restored after a restart,
or queued from another view of the record: every unfinished move of the record is taken up when the document opens.
"""

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from borco_core.logging import LogScope
from PySide6.QtCore import QObject, Qt, Signal
from rehuco_core import (
    FINISHED_JOB_STATES,
    RECORD_MOVE_KIND,
    JobState,
    JobStatus,
    MoveMode,
    MoveRecordJob,
    RootStorage,
    TaskQueue,
    is_directory_scoped,
    same_volume,
    storage_of,
)

from ..fields.widgets.place_marker import NO_MARKERS, PlaceMarker
from ..settings.checksum_settings import shared_checksum_settings
from ..settings.excluded_files_settings import shared_excluded_files_settings
from ..settings.move_settings import MoveSettings, shared_move_settings
from ..tasks.already_queued import job_already_queued
from .name_suggestion_model import RootDestination
from .rehu_document_model import RehuDocumentModel

LOG: Final = logging.getLogger(__name__)


def verifies_rename(settings: MoveSettings, folder: Path) -> bool:
    """Whether a rename onto ``folder``'s volume verifies, by its storage: a share's box, or the local disk's.

    :param settings: the move settings.
    :param folder: where the record lands.
    :returns: the box that applies.
    """
    if storage_of(folder) is RootStorage.NETWORK:
        return settings.verify_renamed_network
    return settings.verify_renamed_local


def plan_move(record: Path, into: Path, settings: MoveSettings | None) -> PlaceMarker:
    """What moving ``record`` into ``into`` involves (#649): the one answer a click acts on and the path row draws.

    :param record: the record's path.
    :param into: the folder the record's own entry would land in.
    :param settings: the move settings; ``None`` when there is no queue to move on, so the move is a rename at once,
        unverified.
    :returns: :attr:`PlaceMarker.NETWORK` when the record's folder or ``into`` is on a share, :attr:`PlaceMarker.COPY`
        when they are on different volumes, :attr:`PlaceMarker.VERIFIED` when the move verifies the checksums: a copy
        always, a rename by the box of the storage it lands on.
    """
    left = record.parent.parent if is_directory_scoped(record) else record.parent
    plan = NO_MARKERS
    if RootStorage.NETWORK in (storage_of(left), storage_of(into)):
        plan |= PlaceMarker.NETWORK
    if settings is None:
        return plan
    if not same_volume(left, into):
        return plan | PlaceMarker.COPY | PlaceMarker.VERIFIED
    if verifies_rename(settings, into):
        plan |= PlaceMarker.VERIFIED
    return plan


class RecordMoves(QObject):
    """Moves one document's record to the places the path row offers, and reports what became of each (#339).

    Attached to the queue as a :class:`~rehuco_core.TaskQueueListener`, marshalled onto the GUI thread as
    :class:`~rehuco_agent.documents.checksum_actions.ChecksumActions` is: the engine calls its listeners on whichever
    thread the change happened on.

    A rename is the same record, so its moves still report here; another record loaded in its place (a preview moving
    on) is not, so they stop reporting here and that record's own moves are taken up instead.

    :param model: the document whose record moves.
    :param queue: the app-wide queue a verified move runs on.
    :param parent: optional Qt parent.
    """

    class Marshaller(QObject):
        """Carries "one of our moves finished" across the thread boundary, and nothing else."""

        queue_changed = Signal()
        """Fires when a job this document queued reached a state it never leaves on its own."""

    def __init__(self, model: RehuDocumentModel, queue: TaskQueue, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__model: Final = model
        self.__queue: Final = queue
        self.__pending: Final[dict[int, MoveRecordJob]] = {}
        """The record's moves that have not been read back, by serial."""
        self.__marshaller: Final = RecordMoves.Marshaller(self)
        self.__marshaller.queue_changed.connect(self.__on_queue_changed, Qt.ConnectionType.QueuedConnection)
        model.path_changed.connect(self.__on_path_changed)  # type: ignore[attr-defined]
        queue.add_listener(self)
        self.__adopt()

    def detach(self) -> None:
        """Stop listening, for a document being closed; its moves go on, in the Tasks dock."""
        self.__queue.remove_listener(self)
        self.__pending.clear()

    def __adopt(self) -> None:
        """Take up every unfinished move of this record already in the queue."""
        path = self.__model.path
        if path is None:
            return
        for status in self.__queue.jobs():
            if status.kind != RECORD_MOVE_KIND or status.state in FINISHED_JOB_STATES or status.source != path:
                continue
            job = self.__queue.job(status.serial)
            if isinstance(job, MoveRecordJob):
                self.__pending[status.serial] = job  # pylint: disable=unsupported-assignment-operation

    def __on_path_changed(self, _path: Path | None) -> None:
        """Let go of the moves of a record another was loaded in place of, and take up the new record's.

        :param _path: the model's new path; unused.
        """
        if self.__model.loading:
            self.__pending.clear()
            self.__adopt()

    def move(self, place: RootDestination) -> None:
        """Move the record to ``place``: a rename at once, or a move on the queue.

        :param place: the place, as the path row offered it.
        """
        path = self.__model.path
        if path is None or place.here:
            return
        settings = shared_move_settings()
        plan = plan_move(path, place.into, settings)
        if PlaceMarker.VERIFIED not in plan:
            self.__model.move_in_root(place.into, place.name, place.source_root)
            return
        target = f"{place.label}: {Path(place.relative)}"
        if not self.__model.prepare_move(target):
            return
        self.__enqueue(place, target, settings, MoveMode.COPY if PlaceMarker.COPY in plan else MoveMode.RENAME)

    def __enqueue(self, place: RootDestination, target: str, settings: MoveSettings, mode: MoveMode) -> None:
        """Queue the move, unless the same one is already waiting, inside the record's own log scope.

        :param place: the place.
        :param target: how the place reads.
        :param settings: the move settings, captured into the job.
        :param mode: a rename or a copy.
        """
        path = self.__model.path
        checksums = shared_checksum_settings()
        job = MoveRecordJob(
            path,
            source_root=place.source_root_id,
            destination_root=place.root_id,
            into=place.relative.parent,
            new_name=place.name,
            mode=mode,
            check_source=settings.verify_original_before_copy,
            check_renamed=verifies_rename(settings, place.into),
            create_if_missing=checksums.create_missing_on_verify,
            remove_empty_folders=settings.remove_empty_folders,
            algorithm=checksums.algorithm,
            excluded_patterns=shared_excluded_files_settings().excluded_file_patterns,
            label=f"Move to {target} - {self.__model.label}",
        )
        if job_already_queued(self.__queue, label=job.label, source=job.source):
            LOG.info("%s is already in the task queue; it was not queued again.", job.label)
            return
        with LogScope.open(path):
            serial = self.__queue.enqueue(job)
        self.__pending[serial] = job  # pylint: disable=unsupported-assignment-operation

    # region TaskQueueListener -- only a move of ours finishing is news here

    def job_enqueued(self, status: JobStatus, index: int) -> None:
        """See :class:`~rehuco_core.TaskQueueListener`."""
        del status, index

    def job_updated(self, status: JobStatus) -> None:
        """See :class:`~rehuco_core.TaskQueueListener`; called on the engine's thread, so it only wakes the GUI's."""
        if status.serial in self.__pending and status.state in FINISHED_JOB_STATES:
            self.__marshaller.queue_changed.emit()

    def jobs_reordered(self, serials: Sequence[int]) -> None:
        """See :class:`~rehuco_core.TaskQueueListener`."""
        del serials

    def jobs_removed(self, serials: Sequence[int]) -> None:
        """See :class:`~rehuco_core.TaskQueueListener`."""
        del serials

    def queue_paused_changed(self, paused: bool) -> None:
        """See :class:`~rehuco_core.TaskQueueListener`."""
        del paused

    # endregion

    def __on_queue_changed(self) -> None:
        """Read back each move of ours that finished, on the GUI thread: a failure or a move that left something
        behind goes on the banner, a clean landing has the record read where it now is."""
        statuses = {status.serial: status for status in self.__queue.jobs()}
        for serial, job in list(self.__pending.items()):
            status = statuses.get(serial)
            if status is None or status.state not in FINISHED_JOB_STATES:
                continue
            del self.__pending[serial]  # pylint: disable=unsupported-delete-operation
            if status.state is JobState.FAILED:
                # a status carries "TypeName: message"; the banner reads the message
                reason = (status.message or "").partition(": ")[2] or status.message
                self.__model.move_failed(f"{status.label} failed: {reason}")
            elif status.state is JobState.DONE and job.outcome is not None and not job.outcome.clean:
                self.__model.move_failed(job.outcome.summary)
            elif status.state is JobState.DONE:
                self.__model.move_landed()
