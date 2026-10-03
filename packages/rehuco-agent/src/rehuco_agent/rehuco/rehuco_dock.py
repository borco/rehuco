"""The Root Catalog dock: one opened ``.rehuco``, its roots, and the resources its cache lists
(#377, [[plugins#rehuco-dock]], [[data-model#cache-schema]]).
"""

import logging
import sqlite3
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final, cast

import cbor2
import humanize
import PySide6QtAds as QtAds
from borco_core.logging import LogScope
from borco_pyside.qtads import QtAdsAutoHideButtonSuppressor, QtAdsFocusTracker
from borco_pyside.theming import ActionIconThemeHandler
from borco_pyside.widgets import MessageBanner, MessageBannerRow, MessageBannerSeverity, RowBandDelegate
from PySide6.QtCore import QAbstractItemModel, QByteArray, QItemSelectionModel, QModelIndex, QObject, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFileDialog, QMainWindow, QMessageBox, QStatusBar, QTableView, QWidget
from rehuco_core import (
    DEFAULT_RENAME_COORDINATOR,
    FINISHED_JOB_STATES,
    CatalogCache,
    JobStatus,
    RehucoFile,
    RehucoFileError,
    RemoveCatalogRootJob,
    RenameCoordinator,
    ScanCatalogRootJob,
    TaskJob,
    TaskQueue,
    rehudb_path,
)

from ..dock_maximize import attach_maximize_handler
from ..glyphs import TAB_CLOSE_GLYPH
from ..settings.persistent_settings import cache_folder
from .catalog_table_model import SIZE_ROLE, CatalogTableModel
from .rehuco_browser_panel_ui import Ui_RehucoBrowserPanel
from .rehuco_roots_model import RehucoRootsModel
from .rehuco_roots_panel_ui import Ui_RehucoRootsPanel

LOG: Final = logging.getLogger(__name__)

SCAN_ICON: Final = ":/icons/refresh.svg"
ADD_ROOT_ICON: Final = ":/icons/items_add.svg"
REMOVE_ROOT_ICON: Final = ":/icons/items_delete.svg"

ROOTS_DOCK_NAME: Final = "roots"
BROWSER_DOCK_NAME: Final = "browser"
"""Object names of this shell's two sub-docks -- the roots list and the resource table -- and the keys
their layout is restored under."""

ROOTS_DOCK_TITLE: Final = "Roots"
BROWSER_DOCK_TITLE: Final = "Browser"

STATE_VERSION_KEY: Final = "version"
STATE_VERSION: Final = 1
"""Schema version of :meth:`RehucoDock.save_state`'s blob. The nested layout is keyed by dock object name,
so any change to the sub-dock set makes an older blob incompatible: QtAds's ``restoreState`` would accept it
and silently hide the current docks. Bump this on any such change; :meth:`RehucoDock.restore_state` ignores
a blob whose version differs, keeping the built default instead."""

STATE_DOCK_MANAGER_KEY: Final = "dock_manager"
STATE_CATALOG_HEADER_KEY: Final = "catalog_header"
STATE_ROOTS_HEADER_KEY: Final = "roots_header"
"""Where the two tables' header states -- column widths and order, and the browser's sort -- live in that blob.
Read outside :data:`STATE_VERSION`'s guard on purpose, the way the Tasks dock reads its log filters: that version
guards the sub-dock set, and a header's state is one table's own, which Qt validates itself."""


# the public surface is the file operations plus read accessors for the views and actions, which the window
# and the tests drive -- one cohesive widget, not a class waiting to be split
class RehucoDock(QMainWindow):  # pylint: disable=too-many-instance-attributes,too-many-public-methods
    """A nested dock shell over one open ``.rehuco``: its roots in one sub-dock, the resources its
    ``.rehudb`` cache lists in another, and a toolbar to scan and to edit the roots.

    **The ``.rehuco`` is the source of truth for the roots, the cache for everything under them.** An
    open reconciles the cache's roots to the file's, so the two cannot disagree for longer than it takes to
    save; what is *found* under a root only ever arrives from a scan.

    **A scan is a queue job per root**, never run here: each opens its own connection on the worker, and
    this dock reads through its own on the GUI thread (SQLite's one connection per thread,
    [[data-model#cache-schema]]). The dock is a queue listener only to learn when one of its own jobs has
    finished, and then reads the rows again -- the same marshalling the checksum actions use
    ([[appendices.task-queue#observation]]).

    **A file newer than this build opens read-only**: its :attr:`~rehuco_core.RehucoFile.lock_reason` is
    shown on a banner and every edit of the roots is off. Scanning stays on, since it writes only the
    disposable cache.

    :param queue: the task queue scans and removals are enqueued on.
    :param parent: optional Qt parent.
    :param stylesheet_host: the widget carrying the dock styling for the whole nest -- normally the window's
        outermost ``CDockManager``.
    :param rename_coordinator: what a scan holds each directory and record read under, so it never blocks a
        rename ([[mounts-and-storage#out-of-band]]).
    """

    open_requested: Signal = Signal(object)
    """Emitted with a resource's absolute :class:`~pathlib.Path` when its row is double-clicked. Typed as
    plain ``object`` for the reason ``DocumentsDock.open_requested`` is."""

    rehuco_path_changed: Signal = Signal(object)
    """Emitted with the open ``.rehuco``'s :class:`~pathlib.Path`, or ``None`` once none is open."""

    class Marshaller(QObject):
        """Carries "one of our jobs may have finished" across the thread boundary, and nothing else."""

        queue_changed = Signal()
        """Carries nothing: the payload is whatever the queue says by the time the slot runs."""

    def __init__(
        self,
        queue: TaskQueue,
        parent: QWidget | None = None,
        *,
        stylesheet_host: QWidget | None = None,
        rename_coordinator: RenameCoordinator = DEFAULT_RENAME_COORDINATOR,
    ) -> None:
        super().__init__(parent)
        self.__queue: Final = queue
        self.__rename_coordinator: Final = rename_coordinator
        self.__file: RehucoFile | None = None
        self.__cache: CatalogCache | None = None
        self.__load_error = ""

        self.__lock: Final = threading.Lock()
        self.__serials: Final[set[int]] = set()
        """The jobs this dock enqueued that have not been read back yet. Written under :attr:`__lock` from
        both the GUI thread and the worker's listener callbacks; the lock is never held while calling the
        queue, whose own lock the listener callbacks arrive under."""

        self.__marshaller: Final = RehucoDock.Marshaller(self)
        self.__marshaller.queue_changed.connect(self.__on_queue_changed, Qt.ConnectionType.QueuedConnection)

        self.__roots_model: Final = RehucoRootsModel(self)
        self.__catalog_model: Final = CatalogTableModel(self)

        self.__roots_panel: Final = QWidget(self)
        self.__roots_ui: Final = Ui_RehucoRootsPanel()
        self.__roots_ui.setupUi(self.__roots_panel)
        self.__roots_ui.roots_view.setModel(self.__roots_model)
        # the row band every other table here paints, so a selected row reads as one band, not boxed cells
        self.__roots_ui.roots_view.setItemDelegate(RowBandDelegate(self.__roots_ui.roots_view))
        self.__banner: Final = MessageBanner(self.__roots_panel)
        self.__roots_ui.main_layout.insertWidget(0, self.__banner)

        self.__browser_panel: Final = QWidget(self)
        self.__browser_ui: Final = Ui_RehucoBrowserPanel()
        self.__browser_ui.setupUi(self.__browser_panel)
        catalog_view = self.__browser_ui.catalog_view
        catalog_view.setModel(self.__catalog_model)
        catalog_view.setItemDelegate(RowBandDelegate(catalog_view))
        # unsorted until a header is clicked: the header's own default puts an arrow on the first column
        # while the rows are still in the cache's order
        catalog_view.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        # the count follows what the view shows, so it listens to the view's model: today the catalog's own,
        # later a filter proxy over it (#396, #398)
        shown = cast(QAbstractItemModel, catalog_view.model())
        for signal in (shown.modelReset, shown.rowsInserted, shown.rowsRemoved):
            signal.connect(self.__update_resource_count)
        self.__update_resource_count()

        self.__dock_manager: Final = QtAds.CDockManager(self)
        # nothing holds onto the tracker: it parents itself to the manager it tracks
        QtAdsFocusTracker(self.__dock_manager, close_glyph=TAB_CLOSE_GLYPH, stylesheet_host=stylesheet_host)
        # pinning belongs to the window's own docks, and this shell's sub-docks live inside one of them
        QtAdsAutoHideButtonSuppressor(self.__dock_manager)
        self.__maximize_handler: Final = attach_maximize_handler(self.__dock_manager)
        self.__add_sub_docks()

        self.__setup_toolbar()
        self.__browser_ui.catalog_view.doubleClicked.connect(self.__on_row_activated)
        # selection_model() is None only before a model is set (setModel just did)
        self.__roots_selection: Final = cast(QItemSelectionModel, self.__roots_ui.roots_view.selectionModel())
        self.__roots_selection.selectionChanged.connect(self.__update_enablement)
        self.__roots_model.modelReset.connect(self.__update_enablement)
        self.__update_enablement()
        queue.add_listener(self)

    # region the open file

    @property
    def rehuco_path(self) -> Path | None:
        """The open ``.rehuco``'s path, or ``None`` while none is open."""
        return None if self.__file is None else self.__file.path

    @property
    def load_error(self) -> str:
        """Why the last :meth:`open_rehuco` or :meth:`new_rehuco` failed, in a sentence a reader can act on;
        empty before any failure."""
        return self.__load_error

    def new_rehuco(self, path: Path) -> bool:
        """Create an empty ``.rehuco`` at ``path`` and open it, replacing the open one.

        :param path: where to write it.
        :returns: whether it was created and opened; ``False`` leaves the open file as it was, with
            :attr:`load_error` saying why.
        """
        file = RehucoFile.new()
        # the cache first: a file written and then reported as not created would be a stray on disk that
        # the next New prompts to overwrite
        cache = self.__open_cache(file, path)
        if cache is None:
            return False
        try:
            file.save(path)
        except (OSError, ValueError) as error:
            cache.close()
            return self.__fail(f"Could not create {path}: {error}")
        return self.__adopt(file, cache)

    def open_rehuco(self, path: Path) -> bool:
        """Open the ``.rehuco`` at ``path``, replacing the open one, and bring its cache in line with it.

        :param path: the file to open.
        :returns: whether it was opened; ``False`` leaves the open file as it was, with :attr:`load_error`
            saying why.
        """
        try:
            file = RehucoFile.load(path)
        except (OSError, RehucoFileError) as error:
            return self.__fail(f"Could not open {path}: {error}")
        cache = self.__open_cache(file, path)
        return cache is not None and self.__adopt(file, cache)

    def close_rehuco(self) -> None:
        """Close the open ``.rehuco`` and its cache, leaving the dock empty. A no-op when none is open."""
        if self.__file is None:
            return
        self.__release_session()
        self.__refresh()
        self.__update_enablement()
        self.rehuco_path_changed.emit(None)

    def detach(self) -> None:
        """Stop listening to the queue and close the cache, before the window goes
        ([[appendices.task-queue#teardown]])."""
        self.__queue.remove_listener(self)
        self.__release_session()

    def __fail(self, message: str) -> bool:
        """Log and keep ``message`` as :attr:`load_error`.

        :param message: why the open or create failed.
        :returns: ``False``, so a caller can ``return self.__fail(...)``.
        """
        LOG.error(message)
        self.__load_error = message
        return False

    def __open_cache(self, file: RehucoFile, path: Path) -> CatalogCache | None:
        """Open ``file``'s cache, named by its rehuco id, and bring its roots in line with the file's.

        :param file: the file whose cache to open.
        :param path: where ``file`` lives or is about to be written, for the error message.
        :returns: the open cache, or ``None`` with :attr:`load_error` saying why.
        """
        try:
            cache = CatalogCache.open(rehudb_path(cache_folder(), file.rehuco_id))
        except (OSError, sqlite3.Error) as error:
            self.__fail(f"Could not open the cache of {path}: {error}")
            return None
        try:
            cache.reconcile_roots(file.roots)
        except sqlite3.Error as error:
            cache.close()
            self.__fail(f"Could not read the cache of {path}: {error}")
            return None
        return cache

    def __adopt(self, file: RehucoFile, cache: CatalogCache) -> bool:
        """Make ``file`` and its open ``cache`` the current ones, releasing the previous pair.

        The jobs still tracked are kept when the new file is the same catalog -- the same rehuco id, so the
        same cache -- which is what re-opening the open file from the recents is: its running scans still
        end in the cache now shown, and the table must still be read again when they do.

        :param file: the file to show.
        :param cache: its cache, open and reconciled.
        :returns: ``True``, for the callers that return this.
        """
        same_catalog = self.__file is not None and self.__file.rehuco_id == file.rehuco_id
        self.__release_session(keep_jobs=same_catalog)
        self.__file = file
        self.__cache = cache
        self.__refresh()
        self.__update_enablement()
        self.rehuco_path_changed.emit(file.path)
        return True

    def __release_session(self, *, keep_jobs: bool = False) -> None:
        """Close the open cache and forget the open file.

        :param keep_jobs: whether to go on tracking the jobs this dock enqueued -- only right when the cache
            about to be shown is the one they write to.
        """
        if self.__cache is not None:
            self.__cache.close()
        self.__cache = None
        self.__file = None
        if not keep_jobs:
            with self.__lock:
                self.__serials.clear()

    # endregion

    # region the views

    @property
    def roots_model(self) -> RehucoRootsModel:
        """The roots list's model."""
        return self.__roots_model

    @property
    def catalog_model(self) -> CatalogTableModel:
        """The resource table's model."""
        return self.__catalog_model

    @property
    def roots_view(self) -> QTableView:
        """The roots list."""
        return self.__roots_ui.roots_view

    @property
    def catalog_view(self) -> QTableView:
        """The resource table."""
        return self.__browser_ui.catalog_view

    @property
    def browser_status_bar(self) -> QStatusBar:
        """The status bar under the resource table, which says how many resources the table shows."""
        return self.__browser_ui.status_bar

    @property
    def scan_action(self) -> QAction:
        """Scans every root into the cache, on the queue."""
        return self.__roots_ui.scan_action

    @property
    def add_root_action(self) -> QAction:
        """Adds a folder as a root."""
        return self.__roots_ui.add_root_action

    @property
    def remove_root_action(self) -> QAction:
        """Removes the selected root."""
        return self.__roots_ui.remove_root_action

    def __refresh(self) -> None:
        """Show what the file and the cache hold now.

        A read failure keeps what is on screen: the cache is disposable and the next scan rebuilds it, so
        a log line is the proportionate answer.
        """
        if self.__file is None or self.__cache is None:
            self.__roots_model.set_roots((), {})
            self.__catalog_model.set_rows((), {})
            self.__banner.set_rows(())
            return
        roots = self.__file.roots
        try:
            reachable = {root.root_id: root.reachable for root in self.__cache.roots()}
            wanted = {root.root_id for root in roots}
            # a root removed from the file keeps its rows until its removal job has run; they are not shown
            rows = [row for row in self.__cache.rows() if row.root_id in wanted]
        except sqlite3.Error as error:
            LOG.error("Could not read the cache of %s: %s", self.__file.path, error)
            return
        self.__roots_model.set_roots(roots, reachable)
        self.__catalog_model.set_rows(rows, {root.root_id: root.path for root in roots})
        lock_reason = self.__file.lock_reason
        self.__banner.set_rows(
            [] if lock_reason is None else [MessageBannerRow(MessageBannerSeverity.WARNING, lock_reason.message)]
        )

    def __update_resource_count(self) -> None:
        """Say in the browser's status bar how many rows the table's model holds now, and their sizes added up."""
        model = self.__browser_ui.catalog_view.model()
        count = model.rowCount()
        if count == 0:
            self.__browser_ui.status_bar.showMessage("No resources")
            return
        total = sum(model.index(row, 0).data(SIZE_ROLE) for row in range(count))
        noun = "resource" if count == 1 else "resources"
        self.__browser_ui.status_bar.showMessage(f"{count} {noun} / {humanize.naturalsize(total, gnu=True)}")

    def __add_sub_docks(self) -> None:
        """Place the Browser in the centre and the Roots list to its left, on this shell's own manager."""
        features = QtAds.CDockWidget.DockWidgetFeature
        # neither is closable: closing the only things this dock exists to show would leave it empty with
        # no control to bring them back
        browser = QtAds.CDockWidget(self.__dock_manager, BROWSER_DOCK_TITLE)
        browser.setObjectName(BROWSER_DOCK_NAME)
        browser.setFeatures(features.DockWidgetFocusable | features.DockWidgetMovable)
        browser.setWidget(self.__browser_panel)
        self.__dock_manager.addDockWidget(QtAds.CenterDockWidgetArea, browser)

        roots = QtAds.CDockWidget(self.__dock_manager, ROOTS_DOCK_TITLE)
        roots.setObjectName(ROOTS_DOCK_NAME)
        roots.setFeatures(features.DockWidgetFocusable | features.DockWidgetMovable)
        roots.setWidget(self.__roots_panel)
        self.__dock_manager.addDockWidget(QtAds.LeftDockWidgetArea, roots)

    def __setup_toolbar(self) -> None:
        """Fill this shell's toolbar: Scan, then the two root edits, each with its themed icon."""
        ui = self.__roots_ui
        toolbar = self.addToolBar("Root Catalog")
        toolbar.addAction(ui.scan_action)
        toolbar.addSeparator()
        toolbar.addActions([ui.add_root_action, ui.remove_root_action])
        for action, icon in (
            (ui.scan_action, SCAN_ICON),
            (ui.add_root_action, ADD_ROOT_ICON),
            (ui.remove_root_action, REMOVE_ROOT_ICON),
        ):
            ActionIconThemeHandler(action, icon)
        ui.scan_action.triggered.connect(self.scan)
        ui.add_root_action.triggered.connect(self.__on_add_root)
        ui.remove_root_action.triggered.connect(self.__on_remove_root)

    def __update_enablement(self) -> None:
        """Enable Scan while a file is open, and the two root edits only while it can also be saved -- Remove
        needing a selected root besides."""
        file = self.__file
        editable = file is not None and file.lock_reason is None
        has_root = self.__roots_model.root_at(self.__selected_row()) is not None
        self.__roots_ui.scan_action.setEnabled(file is not None)
        self.__roots_ui.add_root_action.setEnabled(editable)
        self.__roots_ui.remove_root_action.setEnabled(editable and has_root)

    def __selected_row(self) -> int:
        """The selected root's row, or ``-1`` while none is selected."""
        rows = self.__roots_selection.selectedRows()
        return rows[0].row() if rows else -1

    def __on_row_activated(self, index: QModelIndex) -> None:
        """Ask for the double-clicked resource to be opened, by its absolute path.

        :param index: the activated cell.
        """
        path = self.__catalog_model.absolute_path(index.row())
        if path is not None:
            self.open_requested.emit(path)

    # endregion

    # region editing the roots

    def __on_add_root(self) -> None:
        """Prompt for a folder and add it as a root, saving the file at once."""
        file = self.__file
        if file is None or file.lock_reason is not None:
            return
        chosen = QFileDialog.getExistingDirectory(self, "Add Root")
        if not chosen:
            return
        try:
            file.add_root(chosen)
        except ValueError as error:
            QMessageBox.warning(self, "Add Root", str(error))
            return
        if self.__save_file():
            self.__reconcile_cache()
        self.__refresh()

    def __on_remove_root(self) -> None:
        """Remove the selected root from the file, saving it at once, and its rows from the cache on the
        queue."""
        file = self.__file
        cache = self.__cache
        if file is None or cache is None or file.lock_reason is not None:
            return
        row = self.__selected_row()
        if self.__roots_model.root_at(row) is None:
            return
        removed = file.remove_root(row)
        if self.__save_file():
            self.__enqueue(RemoveCatalogRootJob(cache.path, removed.root_id, root_label=removed.label), removed.path)
        self.__refresh()

    def __save_file(self) -> bool:
        """Write the edited file. On failure the in-memory edit is not what is on disk, so the file is read
        back and the edit is gone from the screen too.

        :returns: whether it was saved.
        """
        file = self.__file
        if file is None:  # pragma: no cover  (only called with a file open)
            return False
        try:
            file.save()
        except OSError as error:
            LOG.error("Could not save %s: %s", file.path, error)
            QMessageBox.warning(self, "Save Root Catalog", f"Could not save {file.path}: {error}")
            self.__reload_from_disk(file)
            return False
        return True

    def __reload_from_disk(self, file: RehucoFile) -> None:
        """Replace an edited ``file`` that could not be saved with what is on disk, or close it when even that
        cannot be read.

        :param file: the file whose save failed.
        """
        path = file.path
        try:
            if path is None:  # pragma: no cover  (an open file always has a path)
                raise OSError("The file has no path.")
            self.__file = RehucoFile.load(path)
        except (OSError, RehucoFileError) as error:
            LOG.error("Could not read %s back: %s", path, error)
            self.close_rehuco()

    def __reconcile_cache(self) -> None:
        """Bring the cache's roots in line with the file's after an edit; a failure is logged, since the next
        scan rebuilds the cache anyway."""
        if self.__file is None or self.__cache is None:  # pragma: no cover  (only called with a file open)
            return
        try:
            self.__cache.reconcile_roots(self.__file.roots)
        except sqlite3.Error as error:
            LOG.error("Could not update the cache of %s: %s", self.__file.path, error)

    # endregion

    # region scanning

    def scan(self) -> None:
        """Enqueue one scan job per root, skipping a root whose scan is already waiting."""
        file = self.__file
        cache = self.__cache
        if file is None or cache is None:
            return
        for root in file.roots:
            self.__enqueue(
                ScanCatalogRootJob(
                    cache.path, root.root_id, root.path, root_label=root.label, coordinator=self.__rename_coordinator
                ),
                root.path,
            )

    def __enqueue(self, job: TaskJob, scope: Path) -> None:
        """Put ``job`` on the queue inside ``scope``'s log scope, and remember its serial so its end can be
        read back.

        **Asked twice is not asked again** ([[data-model#checksums]]'s rule for the checksum jobs), but only among
        the jobs this dock itself enqueued and still tracks: a queue-wide match on label and folder would also
        refuse another catalog's scan of a root with the same label and folder. A job naming no folder -- a
        removal -- is never refused: its label is all a row shows, and two removals of roots that happened to
        share a label would read alike, while running one twice is a cascade over nothing.

        :param job: the job.
        :param scope: the folder the job is about, which its log records are attributed to.
        """
        with self.__lock:
            tracked = set(self.__serials)
        waiting = (status for status in self.__queue.jobs() if status.serial in tracked)
        if job.source is not None and any(
            status.state not in FINISHED_JOB_STATES and status.label == job.label and status.source == job.source
            for status in waiting
        ):
            LOG.info("%s is already in the task queue; it was not queued again.", job.label)
            return
        with LogScope.open(scope):
            serial = self.__queue.enqueue(job)
        with self.__lock:
            self.__serials.add(serial)
        # the job may have finished before its serial was remembered, in which case no callback is left
        # to say so: ask once now
        self.__marshaller.queue_changed.emit()

    def __on_queue_changed(self) -> None:
        """Read the rows again once the **last** of this dock's own jobs has ended (GUI thread).

        One read for a whole Scan rather than one per root: each read is the whole cache and a reset of both
        tables, which drops the selection, so eight roots finishing one after another would be eight stalls
        and eight lost selections for one picture that is only complete at the end.
        """
        with self.__lock:
            tracked = set(self.__serials)
        if not tracked:
            return
        present = {status.serial: status for status in self.__queue.jobs()}
        # a serial the queue no longer lists was cleared by the user: nothing more will be said about it
        ended = {serial for serial in tracked if serial not in present or present[serial].state in FINISHED_JOB_STATES}
        if not ended:
            return
        with self.__lock:
            self.__serials.difference_update(ended)
            remaining = bool(self.__serials)
        if not remaining:
            self.__refresh()

    # region TaskQueueListener -- called on the worker thread, under the queue's lock

    def job_enqueued(self, status: JobStatus, index: int) -> None:
        """See :class:`~rehuco_core.TaskQueueListener`."""
        del status, index

    def job_updated(self, status: JobStatus) -> None:
        """See :class:`~rehuco_core.TaskQueueListener`."""
        if status.state not in FINISHED_JOB_STATES:
            return
        with self.__lock:
            tracked = status.serial in self.__serials
        if tracked:
            self.__marshaller.queue_changed.emit()

    def jobs_reordered(self, serials: Sequence[int]) -> None:
        """See :class:`~rehuco_core.TaskQueueListener`."""
        del serials

    def jobs_removed(self, serials: Sequence[int]) -> None:
        """See :class:`~rehuco_core.TaskQueueListener`."""
        with self.__lock:
            tracked = any(serial in self.__serials for serial in serials)
        if tracked:
            self.__marshaller.queue_changed.emit()

    def queue_paused_changed(self, paused: bool) -> None:
        """See :class:`~rehuco_core.TaskQueueListener`."""
        del paused

    # endregion

    # endregion

    # region layout

    def save_state(self) -> bytes:
        """Serialize this shell's nested dock layout and its two tables' header states.

        :returns: cbor2-encoded state, suitable for :meth:`restore_state`.
        """
        with self.__maximize_handler.unmaximized():
            dock_manager_state = bytes(self.__dock_manager.saveState().data())
        return cbor2.dumps(
            {
                STATE_VERSION_KEY: STATE_VERSION,
                STATE_DOCK_MANAGER_KEY: dock_manager_state,
                STATE_CATALOG_HEADER_KEY: bytes(self.__browser_ui.catalog_view.horizontalHeader().saveState().data()),
                STATE_ROOTS_HEADER_KEY: bytes(self.__roots_ui.roots_view.horizontalHeader().saveState().data()),
            }
        )

    def restore_state(self, state: bytes) -> bool:
        """Restore a layout previously captured by :meth:`save_state`.

        The header states are restored first and whatever the version says: column widths, order and sort are one
        table's own choices, and Qt itself refuses a header state that does not fit. The browser is then sorted as
        its restored header says.

        :param state: the cbor2-encoded state to restore.
        :returns: ``True`` if the nested dock manager's state was restored; ``False`` if ``state`` was
            empty, malformed, not in the expected shape, or of an incompatible :data:`STATE_VERSION` (in
            which case the built default layout is kept).
        """
        try:
            values: Any = cbor2.loads(state)
        except cbor2.CBORDecodeError:
            return False
        if not isinstance(values, dict):
            return False
        self.__restore_headers(values)
        if values.get(STATE_VERSION_KEY) != STATE_VERSION:
            return False
        dock_manager_state = values.get(STATE_DOCK_MANAGER_KEY, b"")
        if not isinstance(dock_manager_state, bytes) or not dock_manager_state:
            return False
        return bool(self.__dock_manager.restoreState(QByteArray(dock_manager_state)))

    def __restore_headers(self, values: dict[Any, Any]) -> None:
        """Put back both tables' header states from a saved blob, each only when present and well-formed, then
        sort the browser as its header now says.

        :param values: the decoded blob.
        """
        for key, view in (
            (STATE_CATALOG_HEADER_KEY, self.__browser_ui.catalog_view),
            (STATE_ROOTS_HEADER_KEY, self.__roots_ui.roots_view),
        ):
            header_state = values.get(key)
            if isinstance(header_state, bytes) and header_state:
                view.horizontalHeader().restoreState(QByteArray(header_state))
        header = self.__browser_ui.catalog_view.horizontalHeader()
        self.__catalog_model.sort(header.sortIndicatorSection(), header.sortIndicatorOrder())

    # endregion
