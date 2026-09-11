"""`File ▸ Conversion Backups…`: discard the `.orig` backups a bulk import left behind (#193).

**This is where the review pass lives.** #192 deliberately drops the per-item confirmation, because the
conversion offers no choices worth confirming thousands of times; safety is that nothing was deleted.
That safety is only real if the backups can be reviewed afterwards, which is this dialog -- filter to the
handful of resources worth a closer look, then select-all-discard the rest. A conversion is
number-preserving (#288), so nothing is lost by converting and there is nothing to revert -- discarding
the backups is the only decision this dialog offers.

**Every discard runs on the task queue**, one :class:`~rehuco_core.DiscardBackupsJob` per resource,
whatever the selection size: it is the same code path for three rows and nine hundred, it puts each
operation under its own resource's log scope ([[appendices.task-queue#scopes]]), and cancelling stops
after the current resource for free ([[appendices.task-queue#job-responsibility]]). The scan (#193's core
module) runs on a worker thread so the dialog stays responsive and cancellable, the same shape
`rehuco_agent.dialogs.import_legacy_catalog_wizard` uses.

**Discard is the only irreversible act in the whole import flow**, and its confirmation reads that way:
it names the resource count and the byte total rather than asking a reflexive yes/no.
"""

# the queue-listener boilerplate, the geometry-persisting `done`, and the scan-worker teardown read the
# same here as in import_legacy_catalog_wizard: they are the same Qt/engine contracts, written out the way
# Qt wants them. This is now the third copy (with checksum_actions), which is a case for extracting a
# shared surface -- but that is a change to #192's freshly-landed code, not #193's to make on the way past.
# pylint: disable=duplicate-code

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Final, override

from borco_core.logging import LogScope
from PySide6.QtCore import QByteArray, QObject, Qt, QThread, Signal
from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox, QWidget
from rehuco_core import (
    FINISHED_JOB_STATES,
    ConversionBackupsTreeScan,
    DiscardBackupsJob,
    JobState,
    JobStatus,
    TaskQueue,
    TcBackupsJob,
    scan_conversion_backups,
)

from ..settings.conversion_backups_dialog_settings import ConversionBackupsDialogSettings
from ..settings.persistent_settings import persistent_settings
from .conversion_backups_dialog_ui import Ui_ConversionBackupsDialog
from .conversion_backups_table_model import (
    ConversionBackupsFilterProxyModel,
    ConversionBackupsRow,
    ConversionBackupsTableModel,
    format_size,
)

LOG: Final = logging.getLogger(__name__)

SCAN_THREAD_WAIT_MS: Final = 2000
"""How long closing the dialog waits for an in-progress scan's worker thread, in milliseconds --
bounded, the same discipline
:data:`~rehuco_agent.dialogs.import_legacy_catalog_wizard.SCAN_THREAD_WAIT_MS` follows: the scan notices
a cancel at its next resource, which is well inside this."""

NOTHING_RETAINED: Final = "No conversion backups under this folder — nothing left to discard."
"""What the summary says for a scan that found nothing, which is a real answer rather than an empty
table with no explanation."""

UNREADABLE_WARNING: Final = "\n{count} folder(s) could not be read and were left out."

DISCARD_TITLE: Final = "Discard Backups"
DISCARD_QUESTION: Final = (
    "Permanently delete the backups of {count} resource(s), freeing {size}?\n\n"
    "This cannot be undone. Their original .tc and legacy screenshots are gone for good."
)

BUSY_STATUS: Final = "{done} / {total}"
SCANNING_STATUS: Final = "Scanning… {count:,} examined"
SCAN_FAILED_STATUS: Final = "Scan failed: {message}"


class ScanCancelled(Exception):
    """Raised inside :class:`ScanWorker`'s callbacks to unwind out of
    :func:`~rehuco_core.scan_conversion_backups` when Cancel was clicked mid-scan."""


class ScanWorker(QObject):
    """Runs :func:`~rehuco_core.scan_conversion_backups` on a worker thread, so the dialog stays
    responsive and cancellable while it walks a folder tree that may hold thousands of resources.

    The counterpart of `rehuco_agent.dialogs.import_legacy_catalog_wizard`'s own scan worker, and
    deliberately a second one rather than a shared base: the two walk for different things and report
    different progress, and what they have in common is the eight lines of `QThread` wiring that Qt
    would want written out either way.

    :param root: the folder to scan.
    """

    progress = Signal(int)
    finished = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, root: Path) -> None:
        super().__init__()
        self.__root: Final = root
        self.__cancel_requested = False

    def cancel(self) -> None:
        """Ask the scan to stop at its next directory or resource. Called from the GUI thread."""
        self.__cancel_requested = True

    def run(self) -> None:
        """Do the scan. Called on the worker thread once the owning `QThread` starts."""
        try:
            scan = scan_conversion_backups(self.__root, progress=self.__on_progress, checkpoint=self.__checkpoint)
        except ScanCancelled:
            self.cancelled.emit()
            return
        except Exception as error:  # pylint: disable=broad-exception-caught
            LOG.exception("The conversion-backups scan failed.")
            self.failed.emit(f"{type(error).__name__}: {error}")
            return
        self.finished.emit(scan)

    def __checkpoint(self) -> None:
        """The walk's own cancellation hook, called once per directory -- before a single resource has
        been read, which over a mount is most of the wait.

        :raises ScanCancelled: a cancel was asked for.
        """
        if self.__cancel_requested:
            raise ScanCancelled

    def __on_progress(self, count: int) -> None:
        """The scan's own progress callback: report, or unwind if a cancel is pending.

        :param count: resources examined so far.
        :raises ScanCancelled: a cancel was asked for.
        """
        self.__checkpoint()
        self.progress.emit(count)


class ConversionBackupsDialog(QDialog):  # pylint: disable=too-many-instance-attributes
    """The backups manager: scan a folder, review what still has backups, and discard them (#193).

    Shown with :meth:`~PySide6.QtWidgets.QDialog.exec` from `File ▸ Conversion Backups…`, a task run over
    a tree rather than a view kept open -- so it is a dialog, not a dock, the same call
    `~rehuco_agent.dialogs.import_legacy_catalog_wizard.ImportLegacyCatalogWizard` makes. Geometry is
    persisted in :meth:`done`, the one hook every exit path funnels through.

    Attached to the queue as a :class:`~rehuco_core.TaskQueueListener` and marshalled onto the GUI thread
    the way `~rehuco_agent.documents.checksum_actions.ChecksumActions` is: the engine calls its listeners
    on whichever thread the change happened on ([[appendices.task-queue#observation]]), and touching a
    widget there would be a plain thread-safety bug.

    :param queue: the app-wide queue this dialog enqueues its jobs onto.
    :param parent: optional Qt parent.
    """

    class Marshaller(QObject):
        """Carries "one of our jobs may have moved" across the thread boundary, and nothing else.

        Nested and undocumented outside this class for the same reason
        :class:`~rehuco_agent.documents.checksum_actions.ChecksumActions.Marshaller` is: a mangled class
        name is not one Qt or the linters will accept.
        """

        queue_changed = Signal()

    def __init__(self, queue: TaskQueue, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__queue: Final = queue
        self.__settings: Final = ConversionBackupsDialogSettings()
        self.__settings.load(persistent_settings())

        self.__ui: Final = Ui_ConversionBackupsDialog()
        self.__ui.setupUi(self)

        self.__model: Final = ConversionBackupsTableModel(self)
        self.__proxy: Final = ConversionBackupsFilterProxyModel(self)
        self.__proxy.setSourceModel(self.__model)
        self.__ui.backups_table_view.setModel(self.__proxy)

        self.__root: Path | None = None
        self.__thread: QThread | None = None
        self.__scan_worker: ScanWorker | None = None
        self.__scan: ConversionBackupsTreeScan | None = None

        self.__jobs: Final[dict[int, TcBackupsJob]] = {}
        """This dialog's own enqueued jobs, by serial -- what tells its listener callbacks apart from
        every other job on the shared queue."""
        self.__seen: Final[dict[int, JobStatus]] = {}
        """The latest status this dialog has heard for each of :attr:`__jobs`, keyed by serial."""
        self.__reported: Final[set[int]] = set()
        """Serials whose finished outcome has already been written to the model, so a status repeated
        after it finished (the engine may notify more than once) is not double-counted."""
        self.__completed = 0
        self.__running_total = 0
        self.__closed = False
        """Whether :meth:`done` has run with jobs still unfinished, deferring the queue detach until
        the batch settles (#246) -- rows already enqueued stay in the Tasks dock and this dialog keeps
        listening for them until every one has."""

        self.__marshaller: Final = ConversionBackupsDialog.Marshaller(self)
        self.__marshaller.queue_changed.connect(self.__on_queue_changed, Qt.ConnectionType.QueuedConnection)
        self.__queue.add_listener(self)

        self.__ui.browse_button.clicked.connect(self.__on_browse)
        self.__ui.rescan_button.clicked.connect(self.__on_rescan)
        self.__ui.recent_roots_combo.activated.connect(self.__on_recent_root_chosen)
        self.__ui.filter_edit.textChanged.connect(self.__on_filter_changed)
        self.__ui.select_all_check_box.clicked.connect(self.__on_select_all_clicked)
        self.__ui.discard_button.clicked.connect(self.__on_discard)
        self.__ui.cancel_button.clicked.connect(self.__on_cancel)
        self.__ui.close_button.clicked.connect(self.accept)
        self.__model.dataChanged.connect(self.__on_model_changed)
        self.__model.modelReset.connect(self.__on_model_changed)

        self.__populate_recent_roots()
        self.__update_summary()
        self.__update_controls()
        if self.__settings.geometry:
            self.restoreGeometry(QByteArray(self.__settings.geometry))

    @property
    def root(self) -> Path | None:
        """The folder currently chosen, or ``None`` before one is."""
        return self.__root

    @property
    def model(self) -> ConversionBackupsTableModel:
        """The table's model, for a caller (or a test) that wants to read its rows."""
        return self.__model

    @override
    def done(self, result: int) -> None:
        """Stop any in-progress scan, detach from the queue and persist geometry, on every exit path --
        Close, the titlebar close button and Escape alike.

        Jobs already enqueued are left alone: closing this dialog does not cancel work already asked
        for, and their rows stay in the Tasks dock. **And they are still listened for** (#246), so their
        rows in this dialog's own table keep updating for as long as it takes -- the detach is deferred
        until the batch settles (:meth:`__on_queue_changed`) rather than skipped, safe because this
        dialog outlives its close (parented to the window) and ``MainWindow`` shuts the queue down before
        teardown, so no callback can reach a deleted object.

        :param result: the dialog's result code, passed straight through to :meth:`QDialog.done`.
        """
        if self.__scan_worker is not None:
            self.__scan_worker.cancel()
        if self.__thread is not None and self.__thread.isRunning():
            self.__thread.quit()
            self.__thread.wait(SCAN_THREAD_WAIT_MS)
        if self.__unfinished_jobs():
            self.__closed = True
        else:
            self.__queue.remove_listener(self)
        self.__settings.geometry = bytes(self.saveGeometry().data())
        self.__settings.save(persistent_settings())
        super().done(result)

    def __unfinished_jobs(self) -> bool:
        """Whether any job this dialog enqueued is still on the queue and not yet finished.

        Asked of the queue itself rather than answered from :attr:`__seen`'s bookkeeping: a job removed
        from the Tasks dock without ever running settles the batch too, and the queue's snapshot is the
        one place that cannot disagree with itself about which jobs still stand.
        """
        return any(
            status.serial in self.__jobs and status.state not in FINISHED_JOB_STATES for status in self.__queue.jobs()
        )

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
        """See :class:`~rehuco_core.TaskQueueListener`.

        One of this dialog's own jobs being removed (deleted from the Tasks dock without running) is
        worth a wake: it may be the last thing a deferred detach (#246) was waiting on.
        """
        if any(serial in self.__jobs for serial in serials):
            self.__marshaller.queue_changed.emit()

    def queue_paused_changed(self, paused: bool) -> None:
        """See :class:`~rehuco_core.TaskQueueListener`."""
        del paused

    def __observe(self, status: JobStatus) -> None:
        """Record one of this dialog's own jobs' latest status, and wake the GUI thread on a state change.

        Called on whichever thread the change happened on, under the queue's own lock -- so this stays
        arithmetic, and the engine's serialization is what makes it safe.

        :param status: the job as the engine has just seen it.
        """
        if status.serial not in self.__jobs:
            return
        previous = self.__seen.get(status.serial)
        self.__seen[status.serial] = status  # pylint: disable=unsupported-assignment-operation
        if previous is None or previous.state is not status.state:
            self.__marshaller.queue_changed.emit()

    # endregion

    # region Choosing a folder and scanning it

    def __populate_recent_roots(self) -> None:
        combo = self.__ui.recent_roots_combo
        combo.clear()
        for root in self.__settings.newest_roots_first():
            combo.addItem(str(root), root)

    def __on_browse(self) -> None:
        start = str(self.__root) if self.__root is not None else ""
        directory = QFileDialog.getExistingDirectory(self, "Choose the folder to look through", start)
        if directory:
            self.__set_root(Path(directory))

    def __on_recent_root_chosen(self, index: int) -> None:
        root = self.__ui.recent_roots_combo.itemData(index)
        if root is not None:
            self.__set_root(Path(root))

    def __on_rescan(self) -> None:
        """Read the folder again -- what makes the table honest after an action has run over it."""
        self.__begin_scan()

    def __set_root(self, root: Path) -> None:
        self.__root = root
        self.__ui.root_edit.setText(str(root))
        self.__begin_scan()

    def __begin_scan(self) -> None:
        root = self.__root
        if root is None or self.__scan_worker is not None:
            return
        self.__ui.scan_progress_bar.setVisible(True)
        self.__ui.scan_progress_bar.setRange(0, 0)
        self.__ui.status_label.setText(SCANNING_STATUS.format(count=0))
        self.__thread = QThread(self)
        self.__scan_worker = ScanWorker(root)
        self.__scan_worker.moveToThread(self.__thread)
        self.__thread.started.connect(self.__scan_worker.run)
        self.__scan_worker.progress.connect(self.__on_scan_progress)
        self.__scan_worker.finished.connect(self.__on_scan_finished)
        self.__scan_worker.failed.connect(self.__on_scan_failed)
        self.__scan_worker.cancelled.connect(self.__on_scan_cancelled)
        for done_signal in (self.__scan_worker.finished, self.__scan_worker.failed, self.__scan_worker.cancelled):
            done_signal.connect(self.__thread.quit)
        self.__thread.finished.connect(self.__scan_worker.deleteLater)
        self.__thread.start()
        self.__update_controls()

    def __on_scan_progress(self, count: int) -> None:
        self.__ui.status_label.setText(SCANNING_STATUS.format(count=count))

    def __on_scan_finished(self, scan: ConversionBackupsTreeScan) -> None:
        self.__scan_worker = None
        self.__scan = scan
        # the scan's own root, not this dialog's: it is the folder that was actually walked, which is
        # the one worth remembering even if the field has moved on since
        self.__settings.record_root(scan.root)
        self.__settings.save(persistent_settings())
        self.__populate_recent_roots()
        self.__model.set_backups(scan.root, scan.resources)
        self.__end_scan("")

    def __on_scan_failed(self, message: str) -> None:
        self.__scan_worker = None
        self.__end_scan(SCAN_FAILED_STATUS.format(message=message))

    def __on_scan_cancelled(self) -> None:
        self.__scan_worker = None
        self.__end_scan("Scan cancelled.")

    def __end_scan(self, status: str) -> None:
        """Leave the scanning state, however it ended.

        :param status: what to say about it, or empty when the summary already says everything.
        """
        self.__ui.scan_progress_bar.setVisible(False)
        self.__ui.status_label.setText(status)
        self.__update_summary()
        self.__update_controls()

    # endregion

    # region What the header says

    def __update_summary(self) -> None:
        """Rebuild the header line from the current selection.

        Reads the **checked** rows rather than the scan, because the byte total is the number that makes
        the decision easy and the decision is about what is selected right now.
        """
        scan = self.__scan
        if scan is None:
            self.__ui.summary_label.setText("")
            return
        if not scan.resources:
            self.__ui.summary_label.setText(NOTHING_RETAINED + self.__unreadable_text(scan))
            return
        checked = self.__model.checked_rows()
        files = sum(len(row.backups.backups) for row in checked)
        total_bytes = sum(row.backups.total_bytes for row in checked)
        text = (
            f"{len(scan.resources):,} of {scan.examined:,} resources still have backups · "
            f"{len(checked):,} selected · {files:,} files · {format_size(total_bytes)} reclaimable"
        )
        if scan.tie_break:
            text += f"\n{scan.tie_break:,} had a screenshot tie-break — filter by “tie-break” to review them."
        self.__ui.summary_label.setText(text + self.__unreadable_text(scan))

    @staticmethod
    def __unreadable_text(scan: ConversionBackupsTreeScan) -> str:
        """What a scan says about the branches it could not list, or nothing when it saw everything."""
        return UNREADABLE_WARNING.format(count=len(scan.unreadable)) if scan.unreadable else ""

    def __on_model_changed(self) -> None:
        self.__update_summary()
        self.__update_controls()

    def __on_filter_changed(self, text: str) -> None:
        self.__proxy.set_filter_text(text)
        self.__update_controls()

    # endregion

    # region Selection

    def __shown_rows(self) -> list[ConversionBackupsRow]:
        """The rows the filter currently lets through, in the proxy's own order.

        What *select all shown* acts on: having filtered to the tie-breaks, selecting all of them and
        then selecting the whole scan are very different asks, and only one of them was made.
        """
        rows = self.__model.rows()
        return [
            rows[self.__proxy.mapToSource(self.__proxy.index(row, 0)).row()] for row in range(self.__proxy.rowCount())
        ]

    def __on_select_all_clicked(self) -> None:
        """Check or uncheck every row the filter currently shows.

        Reads the box's *resulting* state rather than the tri-state it was showing: Qt cycles a
        tristate box through partial, which as an instruction means nothing -- a reader clicking it
        means all or none.
        """
        shown = self.__shown_rows()
        wanted = not all(row.checked for row in shown) if shown else False
        self.__model.set_checked([row.path for row in shown], wanted)

    def __update_controls(self) -> None:
        """Offer each control exactly while it means something."""
        scanning = self.__scan_worker is not None
        running = bool(self.__jobs) and self.__completed < self.__running_total
        busy = scanning or running
        shown = self.__shown_rows()
        checked = self.__model.checked_rows()
        self.__ui.browse_button.setEnabled(not busy)
        self.__ui.rescan_button.setEnabled(not busy and self.__root is not None)
        self.__ui.recent_roots_combo.setEnabled(not busy)
        self.__ui.discard_button.setEnabled(not busy and bool(checked))
        self.__ui.cancel_button.setEnabled(busy)
        self.__ui.select_all_check_box.setEnabled(not busy and bool(shown))
        self.__ui.select_all_check_box.setCheckState(self.__select_all_state(shown))

    @staticmethod
    def __select_all_state(shown: Sequence[ConversionBackupsRow]) -> Qt.CheckState:
        """What the select-all box shows for the rows currently on screen.

        :param shown: the rows the filter lets through.
        :returns: checked when every one is, unchecked when none is, partially otherwise.
        """
        checked = sum(1 for row in shown if row.checked)
        if not shown or not checked:
            return Qt.CheckState.Unchecked
        return Qt.CheckState.Checked if checked == len(shown) else Qt.CheckState.PartiallyChecked

    # endregion

    # region Acting

    def __on_discard(self) -> None:
        """Confirm, then enqueue a discard over every selected resource.

        Every selected row can take one: a discard only deletes the `.orig` siblings, and a resource is
        in this table exactly because it has some.
        """
        selected = self.__model.checked_rows()
        if not selected or not self.__confirm_discard(selected):
            return
        self.__enqueue(DiscardBackupsJob, selected)

    def __confirm_discard(self, rows: Sequence[ConversionBackupsRow]) -> bool:
        """Ask before discarding, naming the count and the bytes rather than asking a bare yes/no.

        :param rows: the resources whose backups are about to be deleted.
        :returns: whether to go ahead.
        """
        total_bytes = sum(row.backups.total_bytes for row in rows)
        return self.__ask(DISCARD_TITLE, DISCARD_QUESTION.format(count=len(rows), size=format_size(total_bytes)))

    def __ask(self, title: str, question: str) -> bool:
        """Put one destructive question, defaulting to No.

        :param title: the dialog's title.
        :param question: what is being asked.
        :returns: whether the answer was Yes.
        """
        answer = QMessageBox.warning(
            self,
            title,
            question,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def __enqueue(self, job_class: type[TcBackupsJob], rows: Sequence[ConversionBackupsRow]) -> None:
        """Put one job per resource on the queue, inside that resource's own log scope.

        The queue copies the caller's context at enqueue and runs the job in it
        ([[appendices.task-queue#scopes]]), which is what makes the detail behind a failed row readable
        on the resource it is about.

        Nothing about *how* a discard deletes is handed over here: a `DiscardBackupsJob` resolves its
        deleter when it runs, from the process-wide provider the window installs, so a job rebuilt from
        the saved queue after a restart honours the Recycle Bin setting exactly as one enqueued here
        does (#298).

        :param job_class: which operation to queue.
        :param rows: the resources to run it over.
        """
        self.__jobs.clear()
        self.__seen.clear()
        self.__reported.clear()
        self.__completed = 0
        self.__running_total = len(rows)
        for row in rows:
            self.__model.set_row_outcome(row.path, "pending")
            job = job_class(row.path)
            with LogScope.open(row.path):
                serial = self.__queue.enqueue(job)
            self.__jobs[serial] = job  # pylint: disable=unsupported-assignment-operation
        self.__ui.scan_progress_bar.setVisible(True)
        self.__ui.scan_progress_bar.setRange(0, max(self.__running_total, 1))
        self.__ui.scan_progress_bar.setValue(0)
        self.__ui.status_label.setText(BUSY_STATUS.format(done=0, total=self.__running_total))
        self.__update_controls()

    def __on_cancel(self) -> None:
        """Stop the scan, or cancel every job still queued.

        The one already running is left to finish on its own -- these operations are not safely
        interruptible, so *cancel stops after the current resource* is the only honest meaning
        ([[appendices.task-queue#job-responsibility]]).
        """
        if self.__scan_worker is not None:
            self.__scan_worker.cancel()
            return
        for serial in self.__jobs:
            self.__queue.cancel(serial)

    def __on_queue_changed(self) -> None:
        """Read back whichever of this dialog's jobs have finished, on the GUI thread.

        Iterates a snapshot of :attr:`__seen`, the same discipline
        :meth:`~rehuco_agent.dialogs.import_legacy_catalog_wizard.ImportLegacyCatalogWizard.__on_queue_changed`
        follows: :meth:`__observe` writes to it from whichever thread the engine calls it on, which can
        be mid-iteration here on the GUI thread.

        Once the whole batch has settled with the dialog already closed, the deferred queue detach
        :meth:`done` left behind finally runs -- checked even on a wake that finished nothing, because a
        job removed without running settles the batch without ever producing an outcome to read.
        """
        newly_finished = 0
        for serial, status in list(self.__seen.items()):
            if status.state not in FINISHED_JOB_STATES or serial in self.__reported or status.source is None:
                continue
            self.__reported.add(serial)
            newly_finished += 1
            outcome, message = self.__outcome_for(status)
            self.__model.set_row_outcome(status.source, outcome, message)
        if newly_finished:
            self.__completed += newly_finished
            self.__ui.scan_progress_bar.setValue(self.__completed)
            self.__ui.status_label.setText(BUSY_STATUS.format(done=self.__completed, total=self.__running_total))
            if self.__completed >= self.__running_total:
                self.__ui.scan_progress_bar.setVisible(False)
            self.__update_controls()
        if self.__closed and not self.__unfinished_jobs():
            self.__queue.remove_listener(self)
            self.__closed = False

    @staticmethod
    def __outcome_for(status: JobStatus) -> tuple[str, str | None]:
        """What a finished job's status means for its row.

        :param status: its last status.
        :returns: the outcome, and a failure's message.
        """
        if status.state is JobState.DONE:
            return "discarded", None
        if status.state is JobState.CANCELLED:
            return "cancelled", None
        return "failed", status.error

    # endregion
