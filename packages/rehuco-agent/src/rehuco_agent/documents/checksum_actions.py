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
from collections.abc import Collection, Sequence
from datetime import timedelta
from pathlib import Path
from typing import Final

from borco_pyside.logging import LogScope
from borco_pyside.theming import ActionIconThemeHandler
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu
from rehuco_core import (
    ChecksumJob,
    ChecksumRecordError,
    ChecksumReport,
    GenerateChecksumsJob,
    JobState,
    JobStatus,
    TaskQueue,
    VerifyChecksumsJob,
    checksum_record_path,
    checksum_report_summary,
    forget_checksums,
    legacy_manifest_for,
)

from ..settings.checksum_settings import shared_checksum_settings
from ..settings.excluded_files_settings import shared_excluded_files_settings
from ..tasks.already_queued import job_already_queued
from .rehu_document_model import RehuDocumentModel

LOG: Final = logging.getLogger(__name__)

GENERATE_ICON_RESOURCE: Final = ":/icons/checksum_generate.svg"
VERIFY_ICON_RESOURCE: Final = ":/icons/checksum_verify.svg"

GENERATE_TOOLTIP: Final = "Hash this resource's content and record it as the baseline."
VERIFY_OLD_TOOLTIP: Final = "Check the files that have not been checked in the last {days}."
VERIFY_ALL_TOOLTIP: Final = "Check every file, however recently it was last checked."
VERIFY_EVERY_TIME_TOOLTIP: Final = "Check every file — the staleness window is set to 0 days, so nothing is ever fresh."
"""What *Verify Old* says at a window of zero days.

Zero is a real setting rather than an unset one ([[data-model#checksums]], #242): a window of no length
leaves nothing fresh, so the action would read as *check the old ones* while checking all of them. It
says which instead, the way #242's own page has to."""

VERIFY_OLD_LABEL: Final = "&Verify Old ({days})"
VERIFY_ALL_LABEL: Final = "Verify &All"
"""What the two checking actions are called.

**The main one names the window it would use** (#244), the way #242's migrate checkbox names the
algorithm it would migrate to -- rebuilt whenever the setting is read, so it can never name a window
that is no longer set."""

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

    record_changed = Signal()
    """Fires on the GUI thread when this resource's ``.checksum`` may have changed -- one of these
    jobs finished, or entries were forgotten (#244).

    What the per-file view refreshes on. Deliberately separate from :attr:`finding_changed`: a run
    that established nothing worth a banner row still rewrote dates, and a forget writes the record
    without producing a finding at all."""

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

        self.__verify_action: Final = QAction(VERIFY_ALL_LABEL, self)
        self.__verify_action.setToolTip(VERIFY_ALL_TOOLTIP)
        ActionIconThemeHandler(self.__verify_action, VERIFY_ICON_RESOURCE)
        self.__verify_action.triggered.connect(self.verify)

        self.__verify_old_action: Final = QAction(self)
        ActionIconThemeHandler(self.__verify_old_action, VERIFY_ICON_RESOURCE)
        self.__verify_old_action.triggered.connect(self.verify_old)
        # the main action carries the other as its menu, so one toolbar button offers both and the
        # dock toolbar, the document toolbar and the context menu all reach the same two QActions --
        # three surfaces that can never drift because there is nothing to keep in step (#244)
        self.__verify_menu: Final = QMenu()
        self.__verify_menu.addAction(self.__verify_action)
        self.__verify_old_action.setMenu(self.__verify_menu)

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
        """Checks **every** file against the record, on the queue -- ``stale_after=None``, which is how
        #203 spells *force*. Reached through :attr:`verify_old_action`'s menu, and directly from the
        dock's context menu."""
        return self.__verify_action

    @property
    def verify_old_action(self) -> QAction:
        """Checks the files last checked longer ago than the staleness window (#242, #244).

        The main checking action, and the one that carries the other as a menu. Its label names the
        window it would use, so a reader never has to remember what the setting says."""
        return self.__verify_old_action

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
        """Enqueue a full baseline over this resource.

        **Not reachable from any toolbar over a resource that already has a record** (#244): a blanket
        re-baseline records whatever is on disk as correct, including bytes a verify has just called
        ``mismatched``, which is corruption laundered into a record that then looks clean forever. It
        stays here for the one case where there is nothing to launder -- a resource with no record at
        all, where every hash is new -- and re-baselining anything else is *Generate Selection*.
        """
        self.__enqueue(GenerateChecksumsJob)

    def verify(self) -> None:
        """Enqueue a verify over every file in this resource, however recently it was checked."""
        self.__enqueue(VerifyChecksumsJob)

    def verify_old(self) -> None:
        """Enqueue a verify that skips what was checked inside the staleness window (#242, #244)."""
        self.__enqueue(VerifyChecksumsJob, stale_after=shared_checksum_settings().stale_after)

    def verify_selection(self, names: Collection[str]) -> None:
        """Enqueue a verify over exactly ``names``.

        :param names: the record-relative names to check; nothing happens for an empty selection.
        """
        if names:
            self.__enqueue(VerifyChecksumsJob, only=tuple(names))

    def generate_selection(self, names: Collection[str]) -> None:
        """Enqueue a re-baseline over exactly ``names`` -- how a genuine change is accepted (#203).

        Needs no confirmation, and deliberately: it takes a selection, which *is* the deliberate act,
        and the verify-inspect-accept loop it serves would be unusable behind a prompt.

        :param names: the record-relative names to re-baseline; nothing happens for an empty selection.
        """
        if names:
            self.__enqueue(GenerateChecksumsJob, only=tuple(names))

    def forget(self, names: Collection[str]) -> tuple[str, ...]:
        """Drop ``names`` from the record, in place (#244).

        **Not a queue job**: nothing is read and nothing is hashed, so this is one small atomic write,
        and putting it behind the queue would make an instant edit wait behind a terabyte of hashing.

        :param names: the record-relative names to forget.
        :returns: the names actually dropped, empty when there was nothing to drop or no record to drop
            it from -- a resource with no record has already forgotten everything.
        """
        path = self.__model.path
        if path is None or not names:
            return ()
        with LogScope.open(path):
            try:
                dropped = forget_checksums(path, only=names)
            except (OSError, ChecksumRecordError) as error:
                LOG.warning("The checksum record could not be updated: %s", error)
                return ()
        if dropped:
            LOG.info("Forgot %d checksum entr%s.", len(dropped), "y" if len(dropped) == 1 else "ies")
            self.record_changed.emit()
        return dropped

    def __enqueue(
        self,
        job_class: type[ChecksumJob],
        *,
        only: tuple[str, ...] | None = None,
        stale_after: timedelta | None = None,
    ) -> None:
        """Build one job and hand it to the queue, unless the same work is already waiting.

        The enqueue happens **inside this document's log scope**, so the records the run makes on the
        worker thread land on this resource's own log surface: the queue copies the caller's context at
        enqueue and runs the job in it ([[appendices.task-queue#scopes]]), which is what makes the
        detail behind the banner readable at all.

        :param job_class: which of the two runs to queue.
        :param only: the names to work on, or ``None`` for the whole resource.
        :param stale_after: the window to skip recently-checked entries by, or ``None`` to check
            everything.
        """
        path = self.__model.path
        if path is None:
            return
        checksums = shared_checksum_settings()
        job = job_class(
            path,
            algorithm=checksums.algorithm,
            only=only,
            stale_after=stale_after,
            # the setting can only ever turn adoption *on*: left off, each job keeps its own answer, so
            # a generate still creates the record it is for while a verify still refuses to (#242)
            create_if_missing=True if checksums.create_missing_on_verify else None,
            migrate_to=checksums.migrate_target,
            excluded_patterns=shared_excluded_files_settings().excluded_file_patterns,
            label=self.__label_for(job_class, only),
        )
        # *asking twice is not asking again* holds for the whole-resource runs, where a second ask is
        # always the same work (#204) -- and deliberately not for a selection: its label carries a
        # count, not an identity, so label-matching cannot tell *Verify a.mp4* from *Verify b.mp4*, and
        # silently refusing the second would break the very accept-one-change loop the dock is for
        # (#244). A duplicated selection run re-reads a few files; a swallowed one loses real work.
        if only is None and job_already_queued(self.__queue, label=job.label, source=job.source):
            LOG.info("%s is already in the task queue; it was not queued again.", job.label)
            return
        self.__pending.append(job)
        with LogScope.open(path):
            self.__queue.enqueue(job)

    def __label_for(self, job_class: type[ChecksumJob], only: tuple[str, ...] | None) -> str:
        """What a queued run is called in the Tasks dock.

        A selection-scoped run says how many files it is about, which is also what keeps *asking twice
        is not asking again* honest: two verifies over the same resource collide only when they cover
        the same thing, and a run over three files is not the run over all of them
        ([[appendices.task-queue#lifetime]], #204).

        :param job_class: which run.
        :param only: the names it covers, or ``None`` for the whole resource.
        :returns: the label.
        """
        scope = "" if only is None else f" ({len(only)} file{'' if len(only) == 1 else 's'})"
        return f"{job_class.verb} checksums{scope} - {self.__model.label}"

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
        finished = False
        for job in list(self.__pending):
            report = job.report
            if report is None:
                continue
            self.__pending.remove(job)
            finished = True
            template = VERIFY_FINDING if isinstance(job, VerifyChecksumsJob) else GENERATE_FINDING
            reported = template.format(summary=checksum_report_summary(report))
            clean = ChecksumActions.__nothing_wrong(report)
        if reported:
            self.__finding = reported
            self.__finding_clean = clean
            self.finding_changed.emit()
        self.__update_enabled()
        if finished:
            # after __update_enabled, so a view refreshing on this already sees the settled actions
            self.record_changed.emit()

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
        hash -- and Verify is offered only once there is a record to verify against, or a legacy
        manifest to seed one from (#243), which is the rule [[data-model#checksums]] states as *a
        resource with no manifest offers Generate*. The record is one ``stat``, re-taken whenever the
        queue moves, so a first generate turns Verify on without the document having to be reopened.

        Unless *Create missing checksum on verify* is set (#242), which makes a verify over a resource
        with no record a legitimate run rather than a refusal. The setting is re-read here rather than
        watched: this runs on every path change and every queue movement, which is soon enough after a
        Save, and one checkbox does not earn a reactive settings object.
        """
        path = self.__model.path
        checksums = shared_checksum_settings()
        has_record = path is not None and self.__has_something_to_verify(path)
        self.__generate_action.setEnabled(path is not None)
        # the one place a full re-baseline is offered from a toolbar: a resource with no record, where
        # there is no recorded hash for it to overwrite, so nothing can be laundered (#244). Once there
        # is a record, re-baselining is Generate Selection and nothing else
        self.__generate_action.setVisible(path is not None and not has_record)
        verifiable = path is not None and (checksums.create_missing_on_verify or has_record)
        self.__verify_action.setEnabled(verifiable)
        self.__verify_old_action.setEnabled(verifiable)
        self.__name_the_window(checksums.stale_days)

    def __name_the_window(self, stale_days: int) -> None:
        """Put the staleness window on the main action's own label (#242, #244).

        Re-read on every update rather than watched: this already runs on every path change and every
        queue movement, which is soon enough after a settings Save, and the alternative is a reactive
        settings object for one spin box.

        :param stale_days: the window, in whole days.
        """
        days = f"{stale_days} day{'' if stale_days == 1 else 's'}"
        self.__verify_old_action.setText(VERIFY_OLD_LABEL.format(days=days))
        self.__verify_old_action.setToolTip(
            VERIFY_EVERY_TIME_TOOLTIP if stale_days == 0 else VERIFY_OLD_TOOLTIP.format(days=days)
        )

    @staticmethod
    def __has_something_to_verify(rehu_path: Path) -> bool:
        """Whether this resource has a record, or the makings of one.

        A legacy ``.sfv``/``.md5``/``.sha*`` beside it counts (#243): a verify seeds a record from it
        and checks that, so greying Verify out here would offer Generate instead -- which throws away
        the one claim the old file is good for. Looked for only where there is no ``.checksum``, so a
        resource that has been verified once is back to the single ``stat`` this used to be.

        :param rehu_path: the resource's ``.rehu`` file.
        :returns: whether a verify has something to check against. An unreadable mount answers
            ``False``, which offers Generate over a resource that may well have one -- the honest fix
            for that is the one #245 tracks, where core stops reading *unreachable* as *empty*.
        """
        try:
            if checksum_record_path(rehu_path).exists():
                return True
        except OSError:
            return False
        return legacy_manifest_for(rehu_path) is not None
