"""`File ▸ Import Legacy Catalog…`: the one-time bulk `.tc` → `.rehu` migration wizard (#192).

Five steps, and **no per-item review gate** -- the design decision #192 encodes. The conversion offers
no choices (the screenshot tie-break is fixed, [[acquisition-tooling#screenshot-schemes]]), so a
per-resource confirmation pass over thousands of items would be ceremony nobody would ever finish.
Safety instead comes from retaining every backup and being able to revert one (#190), and from
flagging the minority of resources where a judgement was made (#191), reviewed afterwards at leisure
(#193). Auto-import is the right default precisely because nothing is ever deleted.

The scan (#191) runs on a worker thread so the dialog stays responsive and cancellable; the import
step enqueues one :class:`~rehuco_core.TcImportJob` per selected resource onto the app-wide queue and
watches them the way `rehuco_agent.documents.checksum_actions.ChecksumActions` watches its own --
attached as a :class:`~rehuco_core.TaskQueueListener`, marshalled onto the GUI thread, reading each
job's own outcome once it has finished rather than carrying a payload through the engine.
"""

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Final, override

from borco_pyside.logging import LogScope
from PySide6.QtCore import QByteArray, QObject, Qt, QThread, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QFileDialog, QWidget
from rehuco_core import (
    DEFAULT_UNKNOWN_USERNAME,
    FINISHED_JOB_STATES,
    JobState,
    JobStatus,
    TaskQueue,
    TcConversionTreePlan,
    TcImportJob,
    plan_tc_conversion,
)

from ..settings.excluded_files_settings import shared_excluded_files_settings
from ..settings.import_legacy_catalog_wizard_settings import ImportLegacyCatalogWizardSettings
from ..settings.persistent_settings import persistent_settings
from .import_legacy_catalog_wizard_ui import Ui_ImportLegacyCatalogWizard
from .import_wizard_import_page import ImportWizardImportPage
from .import_wizard_plan_page import ImportWizardPlanPage
from .import_wizard_result_page import ImportWizardResultPage
from .import_wizard_root_page import ImportWizardRootPage
from .import_wizard_scan_page import ImportWizardScanPage
from .tc_conversion_plan_table_model import TcConversionPlanFilterProxyModel, TcConversionPlanTableModel

LOG: Final = logging.getLogger(__name__)

SCAN_THREAD_WAIT_MS: Final = 2000
"""How long closing the wizard waits for an in-progress scan's worker thread, in milliseconds --
bounded, the same discipline :data:`~rehuco_core.DEFAULT_RENAME_YIELD_TIMEOUT` follows: the scan
notices a cancel at its next resource, which is well inside this."""

SUSPECT_MTIME_WARNING: Final = (
    "\n⚠ {count:,} resource(s) share near-identical timestamps — check before importing (#191's suspect_mtime)."
)
UNREADABLE_WARNING: Final = "\n{count} folder(s) could not be read and were left out."


class _ScanCancelled(Exception):
    """Raised inside :class:`_ScanWorker`'s progress callback to unwind out of
    :func:`~rehuco_core.plan_tc_conversion` when the wizard's Cancel was clicked mid-scan."""


class _ScanWorker(QObject):
    """Runs :func:`~rehuco_core.plan_tc_conversion` on a worker thread, so the dialog stays responsive
    and cancellable while it walks a folder tree that may hold thousands of resources.

    :param root: the folder to scan.
    :param username: the identity an actual conversion's imported per-user flags would be filed under.
    """

    progress = Signal(int)
    finished = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, root: Path, username: str) -> None:
        super().__init__()
        self.__root: Final = root
        self.__username: Final = username
        self.__cancel_requested = False

    def cancel(self) -> None:
        """Ask the scan to stop at its next resource. Called from the GUI thread."""
        self.__cancel_requested = True

    def run(self) -> None:
        """Do the scan. Called on the worker thread once the owning `QThread` starts."""
        try:
            plan = plan_tc_conversion(self.__root, username=self.__username, progress=self.__on_progress)
        except _ScanCancelled:
            self.cancelled.emit()
            return
        except Exception as error:  # pylint: disable=broad-exception-caught
            LOG.exception("The legacy catalog scan failed.")
            self.failed.emit(f"{type(error).__name__}: {error}")
            return
        self.finished.emit(plan)

    def __on_progress(self, count: int) -> None:
        """The scan's own progress callback: report, or unwind if a cancel is pending.

        :param count: resources planned so far.
        :raises _ScanCancelled: a cancel was asked for.
        """
        if self.__cancel_requested:
            raise _ScanCancelled
        self.progress.emit(count)


class ImportLegacyCatalogWizard(QDialog):  # pylint: disable=too-many-instance-attributes
    """The five-step bulk `.tc` import wizard (#192): root, dry-run scan, plan, import, result.

    Shown with :meth:`~PySide6.QtWidgets.QDialog.exec` from `File ▸ Import Legacy Catalog…`, a task run
    over a tree rather than a view kept open -- so it is a dialog, not a dock. Geometry is persisted the
    same way `~rehuco_agent.dialogs.unsaved_changes_dialog.UnsavedChangesDialog`'s is: restored in
    :meth:`__init__`, captured in :meth:`done`, the one hook every exit path funnels through.

    :param queue: the app-wide queue this wizard enqueues :class:`~rehuco_core.TcImportJob` s onto.
    :param username: the identity an actual conversion's imported per-user flags are filed under.
    :param parent: optional Qt parent.
    """

    class Marshaller(QObject):
        """Carries "one of our jobs may have moved" across the thread boundary, and nothing else.

        Nested and undocumented outside this class for the same reason
        :class:`~rehuco_agent.documents.checksum_actions.ChecksumActions.Marshaller` is: a mangled
        class name is not one Qt or the linters will accept.
        """

        queue_changed = Signal()

    def __init__(
        self, queue: TaskQueue, *, username: str = DEFAULT_UNKNOWN_USERNAME, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.__queue: Final = queue
        self.__username: Final = username
        self.__settings: Final = ImportLegacyCatalogWizardSettings()
        self.__settings.load(persistent_settings())

        self.__ui: Final = Ui_ImportLegacyCatalogWizard()
        self.__ui.setupUi(self)

        self.__root_page: Final = ImportWizardRootPage()
        self.__scan_page: Final = ImportWizardScanPage()
        self.__plan_page: Final = ImportWizardPlanPage()
        self.__import_page: Final = ImportWizardImportPage()
        self.__result_page: Final = ImportWizardResultPage()
        for page in (self.__root_page, self.__scan_page, self.__plan_page, self.__import_page, self.__result_page):
            self.__ui.page_stack.addWidget(page)

        self.__model: Final = TcConversionPlanTableModel(self)
        self.__proxy: Final = TcConversionPlanFilterProxyModel(self)
        self.__proxy.setSourceModel(self.__model)
        self.__plan_page.ui.plan_table_view.setModel(self.__proxy)
        self.__result_page.ui.result_table_view.setModel(self.__proxy)
        self.__model.dataChanged.connect(self.__on_model_changed)
        self.__plan_page.ui.filter_edit.textChanged.connect(self.__proxy.set_filter_text)

        self.__root: Path | None = None
        self.__thread: QThread | None = None
        self.__scan_worker: _ScanWorker | None = None

        self.__jobs: Final[dict[int, TcImportJob]] = {}
        """This wizard's own enqueued jobs, by serial -- what tells this wizard's listener callbacks
        apart from every other job on the shared queue."""
        self.__seen: Final[dict[int, JobStatus]] = {}
        """The latest status this wizard has heard for each of :attr:`__jobs`, keyed by serial."""
        self.__reported: Final[set[int]] = set()
        """Serials whose finished outcome has already been written to the model, so a status repeated
        after it finished (the engine may notify more than once) is not double-counted."""
        self.__completed = 0
        self.__selected_total = 0

        self.__marshaller: Final = ImportLegacyCatalogWizard.Marshaller(self)
        self.__marshaller.queue_changed.connect(self.__on_queue_changed, Qt.ConnectionType.QueuedConnection)
        self.__queue.add_listener(self)

        self.__root_page.ui.browse_button.clicked.connect(self.__on_browse)
        self.__root_page.ui.recent_roots_combo.activated.connect(self.__on_recent_root_chosen)
        self.__result_page.ui.retry_failed_button.clicked.connect(self.__on_retry_failed)
        self.__result_page.ui.copy_button.clicked.connect(self.__on_copy)
        self.__result_page.ui.save_button.clicked.connect(self.__on_save)
        self.__ui.back_button.clicked.connect(self.__on_back)
        self.__ui.next_button.clicked.connect(self.__on_next)
        self.__ui.cancel_button.clicked.connect(self.__on_cancel)

        self.__populate_recent_roots()
        self.__update_nav()
        if self.__settings.geometry:
            self.restoreGeometry(QByteArray(self.__settings.geometry))

    @property
    def root(self) -> Path | None:
        """The folder currently chosen on the root step, or ``None`` before one is."""
        return self.__root

    @property
    def model(self) -> TcConversionPlanTableModel:
        """The plan/result table's model, for a caller (or a test) that wants to read its rows."""
        return self.__model

    @override
    def done(self, result: int) -> None:
        """Stop any in-progress scan, detach from the queue and persist geometry, on every exit path --
        Close, Cancel, the titlebar close button and Escape alike.

        :param result: the dialog's result code, passed straight through to :meth:`QDialog.done`.
        """
        if self.__scan_worker is not None:
            self.__scan_worker.cancel()
        if self.__thread is not None and self.__thread.isRunning():
            self.__thread.quit()
            self.__thread.wait(SCAN_THREAD_WAIT_MS)
        self.__queue.remove_listener(self)
        self.__settings.geometry = bytes(self.saveGeometry().data())
        self.__settings.save(persistent_settings())
        super().done(result)

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

    def __observe(self, status: JobStatus) -> None:
        """Record one of this wizard's own jobs' latest status, and wake the GUI thread on a state change.

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

    # region Navigation

    def __on_back(self) -> None:
        self.__ui.page_stack.setCurrentWidget(self.__root_page)
        self.__update_nav()

    def __on_next(self) -> None:
        current = self.__ui.page_stack.currentWidget()
        if current is self.__root_page:
            self.__begin_scan()
        elif current is self.__plan_page:
            self.__begin_import([row.plan.tc_path for row in self.__model.checked_rows()])
        # Next is disabled on the scan and import steps (`__update_nav`), so the three handled here are
        # the only pages it can be clicked on -- there is no fall-through case to answer for.
        elif current is self.__result_page:  # pragma: no branch
            self.accept()
        self.__update_nav()

    def __on_cancel(self) -> None:
        current = self.__ui.page_stack.currentWidget()
        if current is self.__scan_page and self.__scan_worker is not None:
            self.__scan_worker.cancel()
            return
        if current is self.__import_page:
            for serial in self.__jobs:
                self.__queue.cancel(serial)
            return
        self.reject()

    def __on_model_changed(self) -> None:
        self.__update_nav()

    def __update_nav(self) -> None:
        """Set what Back/Next/Cancel say and offer, entirely from which page is current."""
        current = self.__ui.page_stack.currentWidget()
        back = self.__ui.back_button
        forward = self.__ui.next_button
        cancel = self.__ui.cancel_button
        back.setEnabled(current is self.__plan_page)
        cancel.setEnabled(current is not self.__result_page)
        forward.setText("Next >")
        if current is self.__root_page:
            forward.setEnabled(self.__root is not None)
        elif current is self.__scan_page:
            forward.setEnabled(False)
        elif current is self.__plan_page:
            forward.setEnabled(bool(self.__model.checked_rows()))
            forward.setText("Import")
        elif current is self.__import_page:
            forward.setEnabled(False)
        elif current is self.__result_page:  # pragma: no branch  (the stack holds these five and no others)
            forward.setEnabled(True)
            forward.setText("Close")

    # endregion

    # region Step 1 -- root

    def __populate_recent_roots(self) -> None:
        combo = self.__root_page.ui.recent_roots_combo
        combo.clear()
        for root in self.__settings.newest_roots_first():
            combo.addItem(str(root), root)

    def __on_browse(self) -> None:
        start = str(self.__root) if self.__root is not None else ""
        directory = QFileDialog.getExistingDirectory(self, "Choose the legacy catalog folder", start)
        if directory:
            self.__set_root(Path(directory))

    def __on_recent_root_chosen(self, index: int) -> None:
        root = self.__root_page.ui.recent_roots_combo.itemData(index)
        # `activated` carries an item the user picked, and every item this combo holds was added with a
        # root as its data (`__populate_recent_roots`) -- unlike `currentIndexChanged`, it does not fire
        # for the -1 a `clear()` leaves behind, which is the only index that would answer with nothing.
        if root is not None:  # pragma: no branch
            self.__set_root(Path(root))

    def __set_root(self, root: Path) -> None:
        self.__root = root
        self.__root_page.ui.root_edit.setText(str(root))
        self.__update_nav()

    # endregion

    # region Step 2 -- scan

    def __begin_scan(self) -> None:
        root = self.__root
        # Next stays disabled on the root step until a root is chosen (`__update_nav`), so this cannot
        # be reached without one; the guard is here to narrow `Path | None` for `_ScanWorker` rather
        # than to answer a case the UI allows.
        if root is None:  # pragma: no cover
            return
        self.__ui.page_stack.setCurrentWidget(self.__scan_page)
        self.__scan_page.ui.status_label.setText("Scanning…")
        self.__scan_page.ui.scan_progress_bar.setRange(0, 0)
        self.__thread = QThread(self)
        self.__scan_worker = _ScanWorker(root, self.__username)
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

    def __on_scan_progress(self, count: int) -> None:
        self.__scan_page.ui.status_label.setText(f"Scanning… {count:,} found")

    def __on_scan_finished(self, plan: TcConversionTreePlan) -> None:
        self.__scan_worker = None
        # A scan only starts from a root and nothing clears one, so the recording always happens; the
        # check narrows `Path | None` for `record_root`.
        if self.__root is not None:  # pragma: no branch
            self.__settings.record_root(self.__root)
            self.__settings.save(persistent_settings())
            self.__populate_recent_roots()
        self.__model.set_plans(plan.root, plan.resources)
        self.__plan_page.ui.summary_label.setText(self.__summary_text(plan))
        self.__ui.page_stack.setCurrentWidget(self.__plan_page)
        self.__update_nav()

    def __on_scan_failed(self, message: str) -> None:
        self.__scan_worker = None
        self.__scan_page.ui.status_label.setText(f"Scan failed: {message}")
        self.__scan_page.ui.scan_progress_bar.setRange(0, 1)

    def __on_scan_cancelled(self) -> None:
        self.__scan_worker = None
        self.__ui.page_stack.setCurrentWidget(self.__root_page)
        self.__update_nav()

    @staticmethod
    def __summary_text(plan: TcConversionTreePlan) -> str:
        """The plan step's header line, e.g. ``"9,847 clean · 153 flagged · 12 blocked"``.

        A large :attr:`~rehuco_core.TcConversionPlan.suspect_mtime` count is named on its own line
        rather than left as one flag among six (#192's notes): once the `.tc` files are gone, a wall
        of clobbered timestamps is unrecoverable, so it is a reason to stop and look.

        :param plan: the finished scan.
        :returns: the summary text.
        """
        text = f"{plan.clean:,} clean · {plan.flagged:,} flagged · {plan.blocked:,} blocked"
        suspect = sum(1 for resource in plan.resources if resource.suspect_mtime)
        if suspect:
            text += SUSPECT_MTIME_WARNING.format(count=suspect)
        if plan.unreadable:
            text += UNREADABLE_WARNING.format(count=len(plan.unreadable))
        return text

    # endregion

    # region Step 4 -- import

    def __begin_import(self, tc_paths: Sequence[Path]) -> None:
        """Enqueue one job per path in ``tc_paths``, and mark every never-run row outside it skipped.

        A row outside ``tc_paths`` that already carries an outcome **keeps it**: Retry Failed re-enters
        here with only the failed rows, and stamping the rest *skipped* would overwrite ``converted``
        on work that genuinely happened -- a result table that lies about the catalog's own state.

        :param tc_paths: the `.tc` paths to convert -- the checked rows' own, or Retry Failed's.
        """
        self.__jobs.clear()
        self.__seen.clear()
        self.__reported.clear()
        self.__completed = 0
        self.__selected_total = len(tc_paths)
        wanted = set(tc_paths)
        for row in self.__model.rows():
            if row.plan.tc_path not in wanted:
                if row.outcome is None:
                    self.__model.set_row_outcome(row.plan.tc_path, "skipped")
                continue
            self.__model.set_row_outcome(row.plan.tc_path, "pending")
            job = TcImportJob(
                row.plan.tc_path,
                overwrite=row.plan.rehu_exists,
                keep_backups=True,
                username=self.__username,
                excluded_patterns=shared_excluded_files_settings().excluded_file_patterns,
            )
            with LogScope.open(row.plan.tc_path):
                serial = self.__queue.enqueue(job)
            self.__jobs[serial] = job  # pylint: disable=unsupported-assignment-operation
        self.__import_page.ui.import_progress_bar.setRange(0, max(self.__selected_total, 1))
        self.__import_page.ui.import_progress_bar.setValue(0)
        self.__import_page.ui.status_label.setText(f"0 / {self.__selected_total}")
        self.__ui.page_stack.setCurrentWidget(self.__import_page)

    def __on_queue_changed(self) -> None:
        """Read back whichever of this wizard's jobs have finished, on the GUI thread.

        Iterates a snapshot of :attr:`__seen`, the same discipline
        :meth:`~rehuco_agent.documents.checksum_actions.ChecksumActions.__on_queue_changed` follows for
        its own pending list: :meth:`__observe` writes to it from whichever thread the engine calls it
        on, which can be mid-iteration here on the GUI thread.
        """
        newly_finished = 0
        for serial, status in list(self.__seen.items()):
            if status.state not in FINISHED_JOB_STATES or serial in self.__reported or status.source is None:
                continue
            self.__reported.add(serial)
            newly_finished += 1
            outcome, message = self.__outcome_for(status)
            self.__model.set_row_outcome(status.source, outcome, message)
        if not newly_finished:
            return
        self.__completed += newly_finished
        self.__import_page.ui.import_progress_bar.setValue(self.__completed)
        self.__import_page.ui.status_label.setText(f"{self.__completed} / {self.__selected_total}")
        if self.__completed >= self.__selected_total:
            self.__ui.page_stack.setCurrentWidget(self.__result_page)
            self.__result_page.ui.summary_label.setText(self.__result_summary_text())
            self.__update_nav()

    @staticmethod
    def __outcome_for(status: JobStatus) -> tuple[str, str | None]:
        """What a finished job's status means for its row.

        :param status: the finished job's last status.
        :returns: the outcome, and a failure's message.
        """
        if status.state is JobState.DONE:
            return "converted", None
        if status.state is JobState.CANCELLED:
            return "cancelled", None
        return "failed", status.error

    def __result_summary_text(self) -> str:
        """The result step's header line, counting each outcome across every row."""
        rows = self.__model.rows()
        converted = sum(1 for row in rows if row.outcome == "converted")
        failed = sum(1 for row in rows if row.outcome == "failed")
        skipped = sum(1 for row in rows if row.outcome in ("skipped", "cancelled"))
        return f"{converted:,} converted · {failed:,} failed · {skipped:,} skipped"

    # endregion

    # region Step 5 -- result

    def __on_retry_failed(self) -> None:
        failed_paths = [row.plan.tc_path for row in self.__model.rows() if row.outcome == "failed"]
        if not failed_paths:
            return
        self.__begin_import(failed_paths)
        self.__update_nav()

    def __on_copy(self) -> None:
        clipboard = QGuiApplication.clipboard()
        # Optional in the binding, never absent in a running GUI application -- the same shape
        # `settings_dialog` answers the same way.
        if clipboard is not None:  # pragma: no branch
            clipboard.setText(self.__result_text())

    def __on_save(self) -> None:
        path, _selected_filter = QFileDialog.getSaveFileName(self, "Save Import Results", "", "Text files (*.txt)")
        if not path:
            return
        Path(path).write_text(self.__result_text(), encoding="utf-8")

    def __result_text(self) -> str:
        """Every row, one line each, for the Copy/Save actions -- a plain, greppable report."""
        lines = []
        for row in self.__model.rows():
            line = f"{row.plan.tc_path}\t{row.outcome or 'skipped'}"
            if row.message:
                line += f"\t{row.message}"
            lines.append(line)
        return "\n".join(lines)

    # endregion
