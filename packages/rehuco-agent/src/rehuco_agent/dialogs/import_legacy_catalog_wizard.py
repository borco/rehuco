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

**The one import option is whether to read the content** (#256). Every conversion carries the resource's
legacy `.sfv` into a `.checksum` regardless -- that costs no bytes and the job does it itself -- so the
checkbox buys only the check: a second job per resource, verifying the seeded record where a manifest
made a claim and baselining from disk where none did. Off by default, because on it reads the whole
library; and self-healing either way, since a seeded entry carries no date and a dateless entry is never
fresh, so the next sweep checks every resource this import left unread.

**The scan finds a second kind of row** (#259): an already-converted resource still carrying the legacy
manifest its `.checksum` was made from, which a hand conversion left behind before seeding retired
anything. It enqueues a :class:`~rehuco_core.RetireLegacyManifestJob` rather than a conversion, and
belongs on this table for the reason the conversions do -- one resource, one job, one outcome, and the
same Retry Failed. It reads no content, so the option above does not reach it.
"""

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Final, override

from borco_core.logging import LogScope
from PySide6.QtCore import QByteArray, QObject, Qt, QThread, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QFileDialog, QWidget
from rehuco_core import (
    DEFAULT_UNKNOWN_USERNAME,
    FINISHED_JOB_STATES,
    ChecksumJob,
    GenerateChecksumsJob,
    JobState,
    JobStatus,
    LegacyScreenshotRule,
    RetireLegacyManifestJob,
    StrandedManifestPlan,
    TaskJob,
    TaskQueue,
    TcConversionPlan,
    TcConversionTreePlan,
    TcImportJob,
    VerifyChecksumsJob,
    plan_tc_conversion,
)

from ..settings.checksum_settings import shared_checksum_settings
from ..settings.excluded_files_settings import shared_excluded_files_settings
from ..settings.import_legacy_catalog_wizard_settings import ImportLegacyCatalogWizardSettings
from ..settings.legacy_screenshots_settings import shared_legacy_screenshots_settings
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

POPULATION_SUMMARY: Final = (
    "{to_convert:,} to convert · {already_converted:,} already converted · {stranded:,} with a loose manifest"
)
BUCKET_SUMMARY: Final = "\n{clean:,} clean · {flagged:,} flagged · {blocked:,} blocked"
SUSPECT_MTIME_WARNING: Final = "\n⚠ {count:,} resource(s) share near-identical timestamps — check before importing."
UNREADABLE_WARNING: Final = "\n{count} folder(s) could not be read and were left out."
CHECKS_QUEUED_NOTE: Final = "\n{count:,} content check(s) were queued — the Tasks dock is where they finish."
STRANDED_NOTE: Final = (
    "\n{count:,} converted resource(s) still carry the legacy manifest their .checksum was made from — "
    "listed below, and retired when you import."
)


class _ScanCancelled(Exception):
    """Raised inside :class:`_ScanWorker`'s progress callback to unwind out of
    :func:`~rehuco_core.plan_tc_conversion` when the wizard's Cancel was clicked mid-scan."""


class _ScanWorker(QObject):
    """Runs :func:`~rehuco_core.plan_tc_conversion` on a worker thread, so the dialog stays responsive
    and cancellable while it walks a folder tree that may hold thousands of resources.

    :param root: the folder to scan.
    :param username: the identity an actual conversion's imported per-user flags would be filed under.
    :param legacy_screenshot_rules: the naming rules the legacy screenshots are recognized by (#53),
        resolved on the GUI thread before the worker starts so the dry run and the import it previews
        read the same set.
    """

    progress = Signal(int)
    finished = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, root: Path, username: str, legacy_screenshot_rules: tuple[LegacyScreenshotRule, ...]) -> None:
        super().__init__()
        self.__root: Final = root
        self.__username: Final = username
        self.__legacy_screenshot_rules: Final = legacy_screenshot_rules
        self.__cancel_requested = False

    def cancel(self) -> None:
        """Ask the scan to stop at its next resource. Called from the GUI thread."""
        self.__cancel_requested = True

    def run(self) -> None:
        """Do the scan. Called on the worker thread once the owning `QThread` starts."""
        try:
            plan = plan_tc_conversion(
                self.__root,
                username=self.__username,
                legacy_screenshot_rules=self.__legacy_screenshot_rules,
                progress=self.__on_progress,
            )
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

        self.__jobs: Final[dict[int, TaskJob]] = {}
        """This wizard's own enqueued jobs, by serial -- what tells this wizard's listener callbacks
        apart from every other job on the shared queue.

        Both kinds the table holds: a conversion and a manifest retirement (#259). They differ only in
        the word their finished row reads (:meth:`__outcome_for`), which is read back off the job here
        rather than carried on the row -- the job is what the queue answers about."""
        self.__seen: Final[dict[int, JobStatus]] = {}
        """The latest status this wizard has heard for each of :attr:`__jobs`, keyed by serial."""
        self.__reported: Final[set[int]] = set()
        """Serials whose finished outcome has already been written to the model, so a status repeated
        after it finished (the engine may notify more than once) is not double-counted."""
        self.__completed = 0
        self.__selected_total = 0
        self.__checks: Final[list[int]] = []
        """The serials of the content checks the last import queued (#256).

        Serials and nothing more, where a conversion is held as a whole job: their outcome is not a
        conversion's and belongs on no row of this table, and they outlive the dialog by hours, which is
        what the Tasks dock is for. What is still owed them here is Cancel -- somebody stopping an import
        mid-run means the hashing too."""

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
            self.__begin_import([row.path for row in self.__model.checked_rows()])
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
            # the checks too (#256): stopping an import means stopping the hashing it queued, and a
            # check left behind would go on reading the library for hours after the wizard said stop
            for serial in (*self.__jobs, *self.__checks):
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
        self.__scan_worker = _ScanWorker(
            root, self.__username, shared_legacy_screenshots_settings().legacy_screenshot_rules
        )
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
        self.__model.set_plans(plan.root, plan.resources, plan.stranded)
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
        """The plan step's header, e.g. ``"1,200 to convert · 137 already converted · 42 with a loose
        manifest\\n9,847 clean · 153 flagged · 12 blocked"``.

        The first line says how far along the migration is (#258): how much of the tree still needs
        converting, how much already has a record, and how much of that carries a loose manifest --
        answered from the same walk, since descending every directory to find the `.tc` side also finds
        the `.rehu` side.

        The second line's counts are the conversions' own. Stranded manifests (#259) are named again on
        their own line below rather than folded into *clean*: they are not conversions, nothing about
        them is a judgement call, and a reader who came here to convert a tree deserves to be told the
        run will also tidy up after an earlier one.

        A large :attr:`~rehuco_core.TcConversionPlan.suspect_mtime` count is named on its own line
        rather than left as one flag among six (#192's notes): once the `.tc` files are gone, a wall
        of clobbered timestamps is unrecoverable, so it is a reason to stop and look.

        :param plan: the finished scan.
        :returns: the summary text.
        """
        text = POPULATION_SUMMARY.format(
            to_convert=plan.to_convert, already_converted=plan.already_converted, stranded=len(plan.stranded)
        )
        text += BUCKET_SUMMARY.format(clean=plan.clean, flagged=plan.flagged, blocked=plan.blocked)
        suspect = sum(1 for resource in plan.resources if resource.suspect_mtime)
        if suspect:
            text += SUSPECT_MTIME_WARNING.format(count=suspect)
        if plan.stranded:
            text += STRANDED_NOTE.format(count=len(plan.stranded))
        if plan.unreadable:
            text += UNREADABLE_WARNING.format(count=len(plan.unreadable))
        return text

    # endregion

    # region Step 4 -- import

    def __begin_import(self, paths: Sequence[Path]) -> None:
        """Enqueue one job per path in ``paths``, and mark every never-run row outside it skipped.

        A row outside ``paths`` that already carries an outcome **keeps it**: Retry Failed re-enters
        here with only the failed rows, and stamping the rest *skipped* would overwrite ``converted``
        on work that genuinely happened -- a result table that lies about the catalog's own state.

        With *Check the content of every converted resource* ticked, each conversion is followed onto the
        queue by its own checksum job (:meth:`__enqueue_check`, #256) -- **a second job, never more work
        in the first**: a conversion is not safely interruptible, and folding a multi-hour read into one
        would make a catalog-wide import unstoppable.

        A stranded-manifest row (#259) enqueues a :class:`~rehuco_core.RetireLegacyManifestJob` instead
        of a conversion, and never a content check: nothing about it reads a byte, and the record it
        merges into lands dateless exactly as a seeded one does, so the next sweep checks it.

        :param paths: the resources to act on, spelled as :attr:`~.TcConversionRow.path` spells them --
            the checked rows' own, or Retry Failed's.
        """
        self.__jobs.clear()
        self.__seen.clear()
        self.__reported.clear()
        self.__completed = 0
        self.__selected_total = len(paths)
        self.__checks.clear()
        check_content = self.__plan_page.ui.verify_content_check.isChecked()
        wanted = set(paths)
        excluded = shared_excluded_files_settings().excluded_file_patterns
        screenshot_rules = shared_legacy_screenshots_settings().legacy_screenshot_rules
        for row in self.__model.rows():
            if row.path not in wanted:
                if row.outcome is None:
                    self.__model.set_row_outcome(row.path, "skipped")
                continue
            self.__model.set_row_outcome(row.path, "pending")
            job: TaskJob
            if isinstance(row.plan, StrandedManifestPlan):
                job = RetireLegacyManifestJob(
                    row.plan.rehu_path, excluded_patterns=excluded, legacy_screenshot_rules=screenshot_rules
                )
            else:
                job = TcImportJob(
                    row.plan.tc_path,
                    overwrite=row.plan.rehu_exists,
                    keep_backups=True,
                    username=self.__username,
                    excluded_patterns=excluded,
                    legacy_screenshot_rules=screenshot_rules,
                )
            with LogScope.open(row.path):
                serial = self.__queue.enqueue(job)
            self.__jobs[serial] = job  # pylint: disable=unsupported-assignment-operation
            if check_content and isinstance(row.plan, TcConversionPlan):
                self.__enqueue_check(row.plan)
        self.__import_page.ui.import_progress_bar.setRange(0, max(self.__selected_total, 1))
        self.__import_page.ui.import_progress_bar.setValue(0)
        self.__import_page.ui.status_label.setText(f"0 / {self.__selected_total}")
        self.__ui.page_stack.setCurrentWidget(self.__import_page)

    def __enqueue_check(self, plan: TcConversionPlan) -> None:
        """Queue the content check that follows one conversion (#256).

        Which of the two runs it is was decided by the scan, from a listing it read anyway
        (:attr:`~rehuco_core.TcConversionPlan.legacy_manifest`): with a manifest the conversion seeded a
        record from, this **verifies** that record and is forbidden to seed or create one -- the claim is
        already in there, and seeding twice would spend the resource's one seed on a file it has read.
        With no manifest there is nothing to check against, so it **generates**, which is the honest name
        for adopting today's bytes as the baseline.

        Neither is tracked by this wizard. They are not conversions, so an outcome of theirs on a
        conversion's row would say the wrong thing about the catalog; they run long after this dialog is
        closed; and the Tasks dock is where a run measured in hours is watched, paused and retried.

        Ordering needs no arranging: the queue runs what it was handed in the order it was handed, so a
        check follows its own conversion. One that somehow does not -- a conversion that failed -- costs
        a ``stat`` and fails its validation with a sentence, which Retry answers.

        :param plan: the resource's scan plan, for the `.rehu` the conversion writes and the manifest
            beside it.
        """
        checksums = shared_checksum_settings()
        excluded = shared_excluded_files_settings().excluded_file_patterns
        screenshot_rules = shared_legacy_screenshots_settings().legacy_screenshot_rules
        job: ChecksumJob
        if plan.legacy_manifest is not None:
            job = VerifyChecksumsJob(
                plan.rehu_path,
                algorithm=checksums.algorithm,
                create_if_missing=False,
                seed_legacy=False,
                migrate_to=checksums.migrate_target,
                excluded_patterns=excluded,
                legacy_screenshot_rules=screenshot_rules,
            )
        else:
            job = GenerateChecksumsJob(
                plan.rehu_path,
                algorithm=checksums.algorithm,
                excluded_patterns=excluded,
                legacy_screenshot_rules=screenshot_rules,
            )
        with LogScope.open(plan.rehu_path):
            self.__checks.append(self.__queue.enqueue(job))

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
            outcome, message = self.__outcome_for(status, self.__jobs.get(serial))
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
    def __outcome_for(status: JobStatus, job: TaskJob | None) -> tuple[str, str | None]:
        """What a finished job's status means for its row.

        Only success has two words: a retirement that *converted* nothing would say the wrong thing
        about the catalog, while a failure or a cancel means the same for either kind and the message
        carries whatever else there is to know.

        :param status: the finished job's last status.
        :param job: the job that reported it, which decides the success word.
        :returns: the outcome, and a failure's message.
        """
        if status.state is JobState.DONE:
            return ("retired" if isinstance(job, RetireLegacyManifestJob) else "converted"), None
        if status.state is JobState.CANCELLED:
            return "cancelled", None
        return "failed", status.error

    def __result_summary_text(self) -> str:
        """The result step's header line, counting each outcome across every row.

        The queued checks are named on their own line when there are any (#256): the conversions are
        finished and these are not, so leaving them out would read as *the import is done* over hours of
        hashing still to run.
        """
        rows = self.__model.rows()
        converted = sum(1 for row in rows if row.outcome == "converted")
        failed = sum(1 for row in rows if row.outcome == "failed")
        skipped = sum(1 for row in rows if row.outcome in ("skipped", "cancelled"))
        text = f"{converted:,} converted · {failed:,} failed · {skipped:,} skipped"
        retired = sum(1 for row in rows if row.outcome == "retired")
        if retired:
            text += f" · {retired:,} manifest(s) retired"
        if self.__checks:
            text += CHECKS_QUEUED_NOTE.format(count=len(self.__checks))
        return text

    # endregion

    # region Step 5 -- result

    def __on_retry_failed(self) -> None:
        failed_paths = [row.path for row in self.__model.rows() if row.outcome == "failed"]
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
            line = f"{row.path}\t{row.outcome or 'skipped'}"
            if row.message:
                line += f"\t{row.message}"
            lines.append(line)
        return "\n".join(lines)

    # endregion
