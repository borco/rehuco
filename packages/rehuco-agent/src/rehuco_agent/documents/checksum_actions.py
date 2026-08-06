"""Generate and Verify, on one document, as task-queue jobs ([[data-model#checksums]], #204).

**Neither ever runs inline.** Hashing a resource is minutes to hours of reading, and the queue is what
that is for -- so both actions build a job (#203's callables wrapped by `rehuco_core.checksum_jobs`) and
hand it over. The click returns immediately, the document stays editable, and the row appears in the
Tasks dock.

What this class adds over enqueuing is everything around it: which action is even offered, what
happens when the same work is asked for twice, and where the answer goes once the run is done -- an
inline banner row for the summary (#94's shape) and the detail in the resource's own log
([[appendices.logging#scopes]]).
"""

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from borco_pyside.logging import LogScope
from borco_pyside.theming import ActionIconThemeHandler
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QAction
from rehuco_core import (
    FINISHED_JOB_STATES,
    ChecksumJob,
    ChecksumReport,
    GenerateChecksumsJob,
    JobState,
    JobStatus,
    TaskQueue,
    VerifyChecksumsJob,
    checksum_record_path,
    checksum_report_summary,
)

from ..settings.excluded_files_settings import shared_excluded_files_settings
from .rehu_document_model import RehuDocumentModel

LOG: Final = logging.getLogger(__name__)

GENERATE_ICON_RESOURCE: Final = ":/icons/checksum_generate.svg"
VERIFY_ICON_RESOURCE: Final = ":/icons/checksum_verify.svg"

GENERATE_TOOLTIP: Final = "Hash this resource's content and record it as the baseline."
VERIFY_TOOLTIP: Final = "Check this resource's content against its recorded checksums."

VERIFY_FINDING: Final = "Checksums verified: {summary}."
GENERATE_FINDING: Final = "Checksums recorded: {summary}."
"""What the inline banner says once a run has finished.

The **summary**, not the file list: a tutorial of two hundred videos reports two hundred statuses, and
the strip above a document is not where those belong -- the log dock has the detail, and the per-file
view is #244's."""

CLEAN_STATUSES: Final = frozenset({"matched", "unexpected"})
"""The verdicts that are not a finding about the files.

``unexpected`` is a *report* state rather than a resting one ([[data-model#checksums]]) -- the run
adopted the file and recorded it ``matched`` -- so a resource whose only news is an adopted screenshot
has come back clean."""

PROGRESS_COALESCING_BYTES: Final = 100 * 1024 * 1024
"""How much hashing may go by unreported before this surface wakes the GUI thread again.

A run reports once per read chunk -- 1 MB (:data:`~rehuco_core.CHECKSUM_READ_CHUNK_SIZE`) -- so a single
8 GB video posts eight thousand notifications, and every one of them would otherwise cost a queued
GUI-thread dispatch that re-``stat``s the record, in every open document, to re-answer a question no
progress report can change. 100 MB turns that into eighty.

**Progress is the only thing coalesced.** A run starting, ending or stopping is a state change, and
state changes are passed straight through -- what the strip says depends entirely on them, and a finding
that waited for the next 100 MB of a run that has already finished would never arrive at all."""


class ChecksumActions(QObject):  # pylint: disable=too-many-instance-attributes
    """One document's Generate and Verify actions, and what becomes of their runs (#204).

    **A verify failing is not an error dialog.** It is a finding about the files, and the document is
    still perfectly editable -- so it lands in the same inline strip the lock reasons and the rename
    failure already use, as a warning row, and nothing is interrupted. The same shape reports a clean
    run, because *nothing was wrong* is the answer the user asked for.

    **Asking twice is not asking again.** A resource that already has an unfinished job of the same
    kind in the queue is left alone rather than given a second one: two identical runs over the same
    terabyte is never what was meant, and the queue is serial, so the second would only make the first
    take longer to matter. Matched on the row a reader can see -- the job's label and its source --
    rather than on an identity this class would have to keep, which is what makes it still true for a
    job restored from the last session (#238).

    Attached to the queue as a :class:`~rehuco_core.TaskQueueListener`, marshalled onto the GUI thread
    the way :class:`~rehuco_agent.tasks.TaskQueueModel` is and for the same reason: the engine calls
    its listeners on whichever thread the change happened on
    ([[appendices.task-queue#observation]]), and touching a ``QAction`` there would be a plain
    thread-safety bug.

    **Progress is sampled, state is not.** A hash reports every 1 MB and says nothing this surface
    can act on, so those wake the GUI thread once per :data:`PROGRESS_COALESCING_BYTES`; a job starting,
    finishing or stopping wakes it immediately, because that is the only kind of change the strip and
    the two actions are actually about.

    :param model: the document these actions are about.
    :param queue: the app-wide queue to enqueue into.
    :param parent: optional Qt parent.
    """

    finding_changed = Signal()
    """Fires on the GUI thread when :attr:`finding` changes -- what the document's banner rebuilds on."""

    class Marshaller(QObject):
        """Carries "one of our jobs may have moved" across the thread boundary, and nothing else.

        Nested and undocumented outside this class for the same reason
        :class:`~rehuco_agent.tasks.TaskQueueModel.Marshaller` is: a mangled class name is not one Qt
        or the linters will accept.
        """

        queue_changed = Signal()
        """Fires when the queue changed in a way worth reading back -- every state change, and one
        progress report in each :data:`PROGRESS_COALESCING_BYTES`. Carries nothing: the payload is
        whatever the queue and the jobs this class is holding say by the time the slot runs."""

    def __init__(self, model: RehuDocumentModel, queue: TaskQueue, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__model: Final = model
        self.__queue: Final = queue
        self.__finding = ""
        self.__finding_clean = True
        self.__pending: Final[list[ChecksumJob]] = []
        """The jobs this document enqueued that have not been read back yet -- how the findings of a
        run reach a surface at all. The engine carries progress and an outcome, deliberately not a
        payload ([[appendices.task-queue#job-responsibility]]), so the report is read off the job
        object by whoever built it, once it has finished."""

        self.__seen: Final[dict[int, tuple[JobState, int]]] = {}
        """Where each job the queue has mentioned was, and how far it had got, when last heard about --
        what :meth:`__observe` compares against to tell a state change from mere progress.

        Keyed by serial, which the engine never reuses, so an entry that outlives the row it describes
        is stale rather than wrong; it is dropped when the document detaches. Written only from the
        engine's own callbacks, which arrive under the queue's lock and are therefore serialized."""

        self.__unreported = 0
        """Bytes of progress seen since the GUI thread was last woken ([[appendices.task-queue#observation]])."""

        self.__marshaller: Final = ChecksumActions.Marshaller(self)
        self.__marshaller.queue_changed.connect(self.__on_queue_changed, Qt.ConnectionType.QueuedConnection)

        self.__generate_action: Final = QAction("Generate &Checksums", self)
        self.__generate_action.setToolTip(GENERATE_TOOLTIP)
        ActionIconThemeHandler(self.__generate_action, GENERATE_ICON_RESOURCE)
        self.__generate_action.triggered.connect(self.generate)

        self.__verify_action: Final = QAction("&Verify Checksums", self)
        self.__verify_action.setToolTip(VERIFY_TOOLTIP)
        ActionIconThemeHandler(self.__verify_action, VERIFY_ICON_RESOURCE)
        self.__verify_action.triggered.connect(self.verify)

        model.path_changed.connect(self.__update_enabled)  # type: ignore[attr-defined]
        self.__update_enabled()
        queue.add_listener(self)

    # region What the document shows

    @property
    def generate_action(self) -> QAction:
        """(Re-)baselines this resource's ``.checksum`` record, on the queue."""
        return self.__generate_action

    @property
    def verify_action(self) -> QAction:
        """Checks this resource's content against its record, on the queue. Disabled while there is no
        record: a resource with no manifest is offered Generate ([[data-model#checksums]], #204)."""
        return self.__verify_action

    @property
    def finding(self) -> str:
        """What the last run over this resource established, or an empty string before one has.

        One sentence, counting verdicts rather than naming files, for the document's inline notice
        strip. Cleared by the next run, so the strip always describes the most recent answer rather
        than accumulating a history the log already keeps.
        """
        return self.__finding

    @property
    def finding_clean(self) -> bool:
        """Whether the last run found nothing to act on -- what decides the banner row's severity.

        A clean run is still worth a row: *nothing was wrong* is the answer the user asked for, and
        drawing nothing would be indistinguishable from a run that never happened.
        """
        return self.__finding_clean

    def detach(self) -> None:
        """Stop listening, for a document that is being closed.

        Called before the widget is destroyed (`DocumentsDock`), because the engine calls its listeners
        on the worker thread: one arriving after the C++ object has gone would emit from a deleted
        ``QObject``. The jobs themselves are untouched -- closing a document does not cancel work
        already asked for, and their rows stay in the Tasks dock.
        """
        self.__queue.remove_listener(self)
        self.__pending.clear()
        self.__seen.clear()

    # endregion

    # region Enqueuing

    def generate(self) -> None:
        """Enqueue a full baseline over this resource."""
        self.__enqueue(GenerateChecksumsJob)

    def verify(self) -> None:
        """Enqueue a verify over this resource."""
        self.__enqueue(VerifyChecksumsJob)

    def __enqueue(self, job_class: type[ChecksumJob]) -> None:
        """Build one job and hand it to the queue, unless the same work is already waiting.

        The enqueue happens **inside this document's log scope**, so the records the run makes on the
        worker thread land on this resource's own log surface: the queue copies the caller's context at
        enqueue and runs the job in it ([[appendices.task-queue#scopes]]), which is what makes the
        detail behind the banner readable at all.

        :param job_class: which of the two runs to queue.
        """
        path = self.__model.path
        if path is None:
            return
        job = job_class(
            path,
            excluded_patterns=shared_excluded_files_settings().excluded_file_patterns,
            label=f"{job_class.verb} checksums - {self.__model.label}",
        )
        if self.__already_queued(job):
            LOG.info("%s is already in the task queue; it was not queued again.", job.label)
            return
        self.__pending.append(job)
        with LogScope.open(path):
            self.__queue.enqueue(job)

    def __already_queued(self, job: ChecksumJob) -> bool:
        """Whether an unfinished job doing this same work is in the queue already.

        :param job: the job about to be enqueued.
        :returns: whether one like it is already waiting or running.
        """
        return any(
            status.state not in FINISHED_JOB_STATES and status.label == job.label and status.source == job.source
            for status in self.__queue.jobs()
        )

    # endregion

    # region TaskQueueListener -- every method is "something changed", nothing more

    def job_enqueued(self, status: JobStatus, index: int) -> None:
        """See :class:`~rehuco_core.TaskQueueListener`."""
        del index
        self.__observe(status)

    def job_updated(self, status: JobStatus) -> None:
        """See :class:`~rehuco_core.TaskQueueListener`."""
        self.__observe(status)

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

    def __observe(self, status: JobStatus) -> None:
        """Decide whether what the engine has just said is worth waking the GUI thread for.

        **A state change always is.** A run starting, finishing, failing or being stopped is the only
        kind of news that can change what the strip says or which action is offerable, so it is passed
        straight through -- a finding must never wait behind a byte count.

        **Progress almost never is**, and there is a great deal of it: a run reports every 1 MB,
        and each wake costs a queued dispatch that re-reads the queue and re-``stat``s the record in
        every open document, only to conclude that a job which is still running is still running. They
        are added up instead, and one wake is posted per :data:`PROGRESS_COALESCING_BYTES`.

        Called on whichever thread the change happened on and under the queue's own lock
        ([[appendices.task-queue#observation]]), so this stays arithmetic: no widget is touched here,
        and the engine's serialization is what makes the bookkeeping safe.

        :param status: the job as the engine has just seen it.
        """
        previous = self.__seen.get(status.serial)
        self.__seen[status.serial] = (status.state, status.done)  # pylint: disable=unsupported-assignment-operation
        if previous is None or previous[0] is not status.state:
            self.__wake()
            return
        # a retry rewinds `done` to zero, which is not negative progress -- and it changes the state
        # too, so the branch above has already woken for it
        self.__unreported += max(0, status.done - previous[1])
        if self.__unreported >= PROGRESS_COALESCING_BYTES:
            self.__wake()

    def __wake(self) -> None:
        """Ask the GUI thread to read the queue back, and start counting bytes again."""
        self.__unreported = 0
        self.__marshaller.queue_changed.emit()

    def __on_queue_changed(self) -> None:
        """Read back whichever of this document's jobs have finished, on the GUI thread.

        Reads the *job*, not the status: a run's findings live on the object this class built, and it
        is safe to read once the job has finished, which is the same discipline the engine's own state
        capture is under ([[appendices.task-queue#lifetime]]). A job that ended without a report --
        cancelled, or failed before it established anything -- says nothing here, because a run that
        was stopped part-way has established nothing to say ([[data-model#checksums]]).
        """
        reported = ""
        clean = True
        for job in list(self.__pending):
            report = job.report
            if report is None:
                continue
            self.__pending.remove(job)
            template = VERIFY_FINDING if isinstance(job, VerifyChecksumsJob) else GENERATE_FINDING
            reported = template.format(summary=checksum_report_summary(report))
            clean = ChecksumActions.__nothing_wrong(report)
        if reported:
            self.__finding = reported
            self.__finding_clean = clean
            self.finding_changed.emit()
        self.__update_enabled()

    @staticmethod
    def __nothing_wrong(report: ChecksumReport) -> bool:
        """Whether a run found nothing to act on.

        :param report: what the run established.
        :returns: whether every verdict was a clean one and nothing went unread.
        """
        return (
            all(status in CLEAN_STATUSES for status in report.statuses.values())
            and not report.unreadable
            and not report.unnamed_malformed
            # a run that could not list part of the tree is not a clean run, whether or not the record
            # happened to hold entries under the branch it could not see (#245)
            and not report.unreadable_directories
        )

    def __update_enabled(self) -> None:
        """Offer each action exactly while it means something.

        Neither is offered for a document with no path -- a never-saved one has nothing on disk to
        hash -- and Verify is offered only once there is a record to verify against, which is the rule
        [[data-model#checksums]] states as *a resource with no manifest offers Generate*. The record is
        one ``stat``, re-taken whenever the queue moves, so a first generate turns Verify on without
        the document having to be reopened.
        """
        path = self.__model.path
        self.__generate_action.setEnabled(path is not None)
        self.__verify_action.setEnabled(path is not None and self.__record_exists(path))

    @staticmethod
    def __record_exists(rehu_path: Path) -> bool:
        """Whether this resource has a ``.checksum`` yet.

        :param rehu_path: the resource's ``.rehu`` file.
        :returns: whether the record is there. An unreadable mount answers ``False``, which offers
            Generate over a resource that may well have one -- the honest fix for that is the one
            #245 tracks, where core stops reading *unreachable* as *empty*.
        """
        try:
            return checksum_record_path(rehu_path).exists()
        except OSError:
            return False
