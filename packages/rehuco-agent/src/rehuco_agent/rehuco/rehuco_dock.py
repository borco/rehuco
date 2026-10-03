"""The Root Catalog dock: one opened ``.rehuco``, its roots, and the resources its cache lists
(#377, [[plugins#rehuco-dock]], [[data-model#cache-schema]]).
"""

import logging
import sqlite3
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Final, cast

import PySide6QtAds as QtAds
from borco_core.logging import LogScope
from borco_pyside.qtads import (
    QtAdsAutoHideButtonSuppressor,
    QtAdsFocusTracker,
    QtAdsTabContextActions,
    remove_dock_widget,
)
from borco_pyside.theming import ActionIconThemeHandler
from borco_pyside.widgets import MessageBanner, MessageBannerRow, MessageBannerSeverity, RowBandDelegate
from PySide6.QtCore import QByteArray, QItemSelectionModel, QObject, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMainWindow, QMessageBox, QTableView, QWidget
from rehuco_core import (
    DEFAULT_RENAME_COORDINATOR,
    FINISHED_JOB_STATES,
    CatalogCache,
    CatalogRecordUpdater,
    JobStatus,
    RehucoFile,
    RehucoFileError,
    Relocation,
    RemoveCatalogRootJob,
    RenameCoordinator,
    ScanCatalogRootJob,
    TaskJob,
    TaskQueue,
    rehudb_path,
)

from ..dock_maximize import attach_maximize_handler
from ..glyphs import TAB_CLOSE_GLYPH
from ..resource_events import ResourceEvents
from ..settings.catalog_state_store import CatalogState, CatalogStateStore
from ..settings.persistent_settings import cache_folder
from .rehuco_roots_model import RehucoRootsModel
from .rehuco_roots_panel_ui import Ui_RehucoRootsPanel
from .table_browser import TableBrowser

LOG: Final = logging.getLogger(__name__)

SCAN_ICON: Final = ":/icons/roots_scan.svg"
ADD_ROOT_ICON: Final = ":/icons/roots_add.svg"
REMOVE_ROOT_ICON: Final = ":/icons/roots_delete.svg"
ROOTS_ICON: Final = ":/icons/file_browser_folder.svg"
NEW_BROWSER_ICON: Final = ":/icons/browser_add.svg"
RENAME_BROWSER_ICON: Final = ":/icons/browser_rename.svg"
CLONE_BROWSER_ICON: Final = ":/icons/browser_clone.svg"

ROOTS_DOCK_NAME: Final = "roots"
"""Object name of the Roots sub-dock. A browser's is its id, so a saved layout finds each one."""

ROOTS_DOCK_TITLE: Final = "Roots"


# the public surface is the file operations plus read accessors for the views and actions, which the window
# and the tests drive -- one cohesive widget, not a class waiting to be split
class RehucoDock(QMainWindow):  # pylint: disable=too-many-instance-attributes,too-many-public-methods
    """A nested dock shell over one open ``.rehuco``: its roots in one sub-dock, any number of **table
    browsers** over the resources its ``.rehudb`` cache lists, and a toolbar to scan, to edit the roots and to
    add and rename browsers.

    **Browsers are the agent's, not the catalog's.** Each is a closable sub-dock named by a stable id, with a name,
    a filter and a header state. They are remembered per catalog, with where every sub-dock sits, in a
    :class:`~rehuco_agent.settings.catalog_state_store.CatalogStateStore` keyed by the rehuco id: read when a file
    is opened and written when it is closed, replaced or the dock is detached. ``rehuco-core`` and the ``.rehuco``
    know nothing of them. A catalog with none saved opens with one default browser.

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
    :param catalog_store: where each catalog's browsers and layout are remembered; the app's own by default.
    :param resource_events: the app's file announcements (#376), which keep the cache current between scans
        without reading anything a rename moved: a rename rebases the rows it moved
        (:meth:`~rehuco_core.CatalogCache.apply_relocation`), and a record the app wrote is read back into its
        row (:class:`~rehuco_core.CatalogRecordUpdater`). ``None`` leaves the cache to the scans alone.
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

    def __init__(  # pylint: disable=too-many-arguments
        self,
        queue: TaskQueue,
        parent: QWidget | None = None,
        *,
        stylesheet_host: QWidget | None = None,
        rename_coordinator: RenameCoordinator = DEFAULT_RENAME_COORDINATOR,
        catalog_store: CatalogStateStore | None = None,
        resource_events: ResourceEvents | None = None,
    ) -> None:
        super().__init__(parent)
        self.__queue: Final = queue
        self.__rename_coordinator: Final = rename_coordinator
        self.__catalog_store: Final = catalog_store if catalog_store is not None else CatalogStateStore()
        self.__events: Final = resource_events
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

        self.__roots_panel: Final = QWidget(self)
        self.__roots_ui: Final = Ui_RehucoRootsPanel()
        self.__roots_ui.setupUi(self.__roots_panel)
        self.__roots_ui.roots_view.setModel(self.__roots_model)
        # the row band every other table here paints, so a selected row reads as one band, not boxed cells
        self.__roots_ui.roots_view.setItemDelegate(RowBandDelegate(self.__roots_ui.roots_view))
        self.__banner: Final = MessageBanner(self.__roots_panel)
        self.__roots_ui.main_layout.insertWidget(0, self.__banner)

        self.__browsers: Final[dict[QtAds.CDockWidget, TableBrowser]] = {}
        """Every browser's dock, in the order the browsers were added."""

        self.__dock_manager: Final = QtAds.CDockManager(self)
        self.__focus_tracker: Final = QtAdsFocusTracker(
            self.__dock_manager, close_glyph=TAB_CLOSE_GLYPH, stylesheet_host=stylesheet_host
        )
        # pinning belongs to the window's own docks, and this shell's sub-docks live inside one of them
        QtAdsAutoHideButtonSuppressor(self.__dock_manager)
        self.__maximize_handler: Final = attach_maximize_handler(self.__dock_manager)
        self.__tab_menus: Final = QtAdsTabContextActions(self.__dock_manager)
        self.__roots_dock: Final = self.__add_roots_dock()

        self.__new_browser_action: Final = QAction("New Table Browser", self)
        self.__new_browser_action.setToolTip("Add a table browser over this catalog's resources.")
        self.__rename_browser_action: Final = QAction("Rename Browser...", self)
        self.__rename_browser_action.setToolTip("Rename the current browser.")
        self.__setup_toolbar()
        # selection_model() is None only before a model is set (setModel just did)
        self.__roots_selection: Final = cast(QItemSelectionModel, self.__roots_ui.roots_view.selectionModel())
        self.__roots_selection.selectionChanged.connect(self.__update_enablement)
        self.__roots_model.modelReset.connect(self.__update_enablement)
        self.__focus_tracker.current_dock_changed.connect(self.__update_enablement)
        self.__update_enablement()
        queue.add_listener(self)
        if resource_events is not None:
            resource_events.moved.connect(self.__on_moved)
            resource_events.changed.connect(self.__on_files_changed)

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
        """Stop listening to the queue and the file announcements, and close the cache, before the window goes
        ([[appendices.task-queue#teardown]])."""
        self.__queue.remove_listener(self)
        if self.__events is not None:
            self.__events.moved.disconnect(self.__on_moved)
            self.__events.changed.disconnect(self.__on_files_changed)
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
        self.__open_browsers(file)
        self.__refresh()
        self.__update_enablement()
        self.rehuco_path_changed.emit(file.path)
        return True

    def __release_session(self, *, keep_jobs: bool = False) -> None:
        """Remember the open catalog's browsers and layout, close its browsers and its cache, and forget the file.

        :param keep_jobs: whether to go on tracking the jobs this dock enqueued -- only right when the cache
            about to be shown is the one they write to.
        """
        if self.__file is not None:
            self.__remember_catalog(self.__file)
        self.__close_browsers()
        if self.__cache is not None:
            self.__cache.close()
        self.__cache = None
        self.__file = None
        if not keep_jobs:
            with self.__lock:
                self.__serials.clear()

    # endregion

    # region the views and the browsers

    @property
    def roots_model(self) -> RehucoRootsModel:
        """The roots list's model."""
        return self.__roots_model

    @property
    def roots_view(self) -> QTableView:
        """The roots list."""
        return self.__roots_ui.roots_view

    @property
    def roots_dock(self) -> QtAds.CDockWidget:
        """The Roots sub-dock, closable and shown again by :attr:`roots_action`."""
        return self.__roots_dock

    @property
    def browsers(self) -> tuple[TableBrowser, ...]:
        """Every browser, in the order they were added."""
        return tuple(self.__browsers.values())

    @property
    def current_browser(self) -> TableBrowser | None:
        """The browser whose sub-dock is the focus tracker's current one, or ``None`` while that is the Roots
        list or nothing. The resource the current-resource sub-docks show is this browser's selection (#381)."""
        current = self.__focus_tracker.current_dock
        return None if current is None else self.__browsers.get(current)

    def browser_dock(self, browser: TableBrowser) -> QtAds.CDockWidget:
        """The sub-dock holding ``browser``.

        :param browser: one of :attr:`browsers`.
        :returns: its dock.
        """
        return next(dock for dock, held in self.__browsers.items() if held is browser)

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

    @property
    def roots_action(self) -> QAction:
        """Shows and hides the Roots sub-dock; checked while it is shown."""
        return self.__roots_dock.toggleViewAction()

    @property
    def new_browser_action(self) -> QAction:
        """Adds a table browser."""
        return self.__new_browser_action

    @property
    def rename_browser_action(self) -> QAction:
        """Renames the current browser."""
        return self.__rename_browser_action

    def ask_browser_name(self, current: str, title: str = "Rename Browser") -> str | None:
        """Ask for a browser's name; the one modal behind a rename and a clone, so a test replaces it per instance.

        :param current: the name the box opens on.
        :param title: the box's title.
        :returns: the typed name, or ``None`` if the box was cancelled.
        """
        name, accepted = QInputDialog.getText(self, title, "Name:", text=current)
        return name if accepted else None

    def __refresh(self) -> None:
        """Show what the file and the cache hold now.

        A read failure keeps what is on screen: the cache is disposable and the next scan rebuilds it, so
        a log line is the proportionate answer.
        """
        if self.__file is None or self.__cache is None:
            self.__roots_model.set_roots((), {})
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
        root_paths = {root.root_id: root.path for root in roots}
        for browser in self.__browsers.values():
            browser.set_rows(rows, root_paths)
        lock_reason = self.__file.lock_reason
        self.__banner.set_rows(
            [] if lock_reason is None else [MessageBannerRow(MessageBannerSeverity.WARNING, lock_reason.message)]
        )

    def __add_roots_dock(self) -> QtAds.CDockWidget:
        """Place the Roots list on this shell's own manager, closable: hidden by its [x] and shown again by
        :attr:`roots_action`, so closing it loses nothing.

        :returns: the Roots sub-dock.
        """
        features = QtAds.CDockWidget.DockWidgetFeature
        roots = QtAds.CDockWidget(self.__dock_manager, ROOTS_DOCK_TITLE)
        roots.setObjectName(ROOTS_DOCK_NAME)
        roots.setFeatures(features.DockWidgetClosable | features.DockWidgetFocusable | features.DockWidgetMovable)
        roots.setWidget(self.__roots_panel)
        self.__dock_manager.addDockWidget(QtAds.LeftDockWidgetArea, roots)
        return roots

    def __setup_toolbar(self) -> None:
        """Fill this shell's toolbar -- Scan, the two root edits, the Roots toggle, then New and Rename Browser --
        each with its themed icon."""
        ui = self.__roots_ui
        toolbar = self.addToolBar("Root Catalog")
        toolbar.addAction(ui.scan_action)
        toolbar.addSeparator()
        toolbar.addActions([ui.add_root_action, ui.remove_root_action])
        toolbar.addSeparator()
        toolbar.addAction(self.roots_action)
        toolbar.addSeparator()
        toolbar.addActions([self.__new_browser_action, self.__rename_browser_action])
        for action, icon in (
            (ui.scan_action, SCAN_ICON),
            (ui.add_root_action, ADD_ROOT_ICON),
            (ui.remove_root_action, REMOVE_ROOT_ICON),
            (self.roots_action, ROOTS_ICON),
            (self.__new_browser_action, NEW_BROWSER_ICON),
            (self.__rename_browser_action, RENAME_BROWSER_ICON),
        ):
            ActionIconThemeHandler(action, icon)
        ui.scan_action.triggered.connect(self.scan)
        ui.add_root_action.triggered.connect(self.__on_add_root)
        ui.remove_root_action.triggered.connect(self.__on_remove_root)
        self.__new_browser_action.triggered.connect(self.__on_new_browser)
        self.__rename_browser_action.triggered.connect(self.__on_rename_current_browser)

    def __update_enablement(self) -> None:
        """Enable Scan while a file is open, and the two root edits only while it can also be saved -- Remove
        needing a selected root besides. New Browser needs a catalog to hold it, and Rename Browser a browser to be
        the current sub-dock, not the Roots one."""
        file = self.__file
        editable = file is not None and file.lock_reason is None
        has_root = self.__roots_model.root_at(self.__selected_row()) is not None
        self.__roots_ui.scan_action.setEnabled(file is not None)
        self.__roots_ui.add_root_action.setEnabled(editable)
        self.__roots_ui.remove_root_action.setEnabled(editable and has_root)
        self.__new_browser_action.setEnabled(file is not None)
        self.__rename_browser_action.setEnabled(self.current_browser is not None)

    def __selected_row(self) -> int:
        """The selected root's row, or ``-1`` while none is selected."""
        rows = self.__roots_selection.selectedRows()
        return rows[0].row() if rows else -1

    # endregion

    # region the browsers

    def __open_browsers(self, file: RehucoFile) -> None:
        """Build ``file``'s browsers as the catalog remembered them -- one default one if it remembered none --
        and put every sub-dock back where it sat.

        Every browser exists *before* the layout is restored: QtAds restores by dock object name and creates none.

        :param file: the catalog just opened.
        """
        state = self.__catalog_store.load(file.rehuco_id)
        for browser in [TableBrowser(saved) for saved in state.browsers] or [TableBrowser()]:
            self.__add_browser(browser)
        restored = bool(state.layout) and bool(self.__dock_manager.restoreState(QByteArray(state.layout)))
        # a browser the layout does not know is left closed, or in an area the restore took out of the manager --
        # shown there it would be invisible, and every browser added beside it too. It is placed again instead
        for dock in [dock for dock in self.__browsers if not self.__is_placed(dock)]:
            remove_dock_widget(self.__dock_manager, dock)
            self.__place(dock)
        if not restored:
            self.__roots_dock.toggleView(True)
        if state.roots_header:
            self.__roots_ui.roots_view.horizontalHeader().restoreState(QByteArray(state.roots_header))

    def __remember_catalog(self, file: RehucoFile) -> None:
        """Write ``file``'s browsers, and where every sub-dock sits, to the catalog store.

        :param file: the catalog being left.
        """
        with self.__maximize_handler.unmaximized():
            layout = bytes(self.__dock_manager.saveState().data())
        roots_header = bytes(self.__roots_ui.roots_view.horizontalHeader().saveState().data())
        browsers = [browser.state() for browser in self.__browsers.values()]
        self.__catalog_store.save(file.rehuco_id, CatalogState(browsers, layout, roots_header))

    def __close_browsers(self) -> None:
        """Remove every browser's sub-dock, leaving the Roots list alone on the manager."""
        for dock in list(self.__browsers):
            self.__remove_browser(dock)

    def __add_browser(self, browser: TableBrowser, *, beside: QtAds.CDockWidget | None = None) -> QtAds.CDockWidget:
        """Put ``browser`` in a closable sub-dock named by its id, with its own actions on the dock's title bar and
        tab menu.

        :param browser: the browser to show.
        :param beside: the sub-dock whose tab strip to join; see :meth:`__place`.
        :returns: its sub-dock.
        """
        features = QtAds.CDockWidget.DockWidgetFeature
        dock = QtAds.CDockWidget(self.__dock_manager, browser.name)
        dock.setObjectName(str(browser.browser_id))
        # [x] deletes the browser, which is this shell's to do: QtAds would only hide it
        dock.setFeatures(
            features.CustomCloseHandling
            | features.DockWidgetClosable
            | features.DockWidgetFocusable
            | features.DockWidgetMovable
        )
        dock.setWidget(browser)
        dock.setTitleBarActions(self.__browser_actions(dock))
        self.__place(dock, beside)
        browser.row_activated.connect(self.open_requested)
        dock.closeRequested.connect(lambda: self.__close_browser(dock))
        self.__browsers[dock] = browser  # pylint: disable=unsupported-assignment-operation
        return dock

    def __place(self, dock: QtAds.CDockWidget, beside: QtAds.CDockWidget | None = None) -> None:
        """Add a browser's sub-dock to the manager: into the tab strip of ``beside``, else of the first browser that
        is on screen, else to the right of the Roots list; and give its tab its actions.

        :param dock: the browser's sub-dock, not on the manager.
        :param beside: the sub-dock whose tab strip to join.
        """
        anchor = (
            beside
            if beside is not None
            else next((other for other in self.__browsers if self.__is_placed(other)), None)
        )
        area = None if anchor is None else anchor.dockAreaWidget()
        if area is not None:
            self.__dock_manager.addDockWidget(QtAds.CenterDockWidgetArea, dock, area)
        else:
            self.__dock_manager.addDockWidget(QtAds.RightDockWidgetArea, dock)
        self.__tab_menus.add(dock, dock.titleBarActions(), lambda: self.__focus_tracker.set_current_dock(dock))

    def __is_placed(self, dock: QtAds.CDockWidget) -> bool:
        """Whether ``dock`` is open in an area the manager -- or a floating window of it -- shows.

        :param dock: a browser's sub-dock.
        :returns: ``False`` for a dock closed, or left in an area a layout restore took off the manager.
        """
        if dock.isClosed():
            return False
        return dock.isFloating() or dock.dockAreaWidget() in self.__dock_manager.openedDockAreas()

    def __browser_actions(self, dock: QtAds.CDockWidget) -> list[QAction]:
        """Rename and Clone for ``dock``'s browser, bound to that dock whichever one is current. Deleting is its [x].

        :param dock: the browser's sub-dock.
        :returns: the actions, in menu order.
        """
        rename = QAction("Rename...", dock)
        rename.triggered.connect(lambda: self.__rename_browser(dock))
        clone = QAction("Clone...", dock)
        clone.triggered.connect(lambda: self.__clone_browser(dock))
        for action, icon in ((rename, RENAME_BROWSER_ICON), (clone, CLONE_BROWSER_ICON)):
            ActionIconThemeHandler(action, icon)
        return [rename, clone]

    def __remove_browser(self, dock: QtAds.CDockWidget) -> None:
        """Take ``dock`` off the manager and delete it, with its browser.

        :param dock: the browser's sub-dock.
        """
        self.__browsers.pop(dock, None)
        remove_dock_widget(self.__dock_manager, dock)
        dock.deleteLater()

    def __on_new_browser(self) -> None:
        """Add a default table browser and make it current."""
        if self.__file is None:
            return
        browser = TableBrowser()
        dock = self.__add_browser(browser)
        self.__fill(browser)
        self.__focus_tracker.set_current_dock(dock)

    def __on_rename_current_browser(self) -> None:
        """Rename the current browser, if one is."""
        current = self.__focus_tracker.current_dock
        if current in self.__browsers:
            self.__rename_browser(cast(QtAds.CDockWidget, current))

    def __rename_browser(self, dock: QtAds.CDockWidget) -> None:
        """Ask for a new name for ``dock``'s browser and set it: on the dock's ``windowTitle`` and the browser.
        Never the dock's ``objectName`` -- ``CDockManager`` keys its registry by the name a dock was added under,
        and a changed one dangles (#364). An empty or unchanged name is a cancel.

        :param dock: the browser's sub-dock.
        """
        browser = self.__browsers[dock]
        name = self.ask_browser_name(browser.name)
        name = name.strip() if name is not None else ""
        if name and name != browser.name:
            browser.name = name
            dock.setWindowTitle(name)

    def __clone_browser(self, dock: QtAds.CDockWidget) -> None:
        """Ask for a name and add a copy of ``dock``'s browser -- the same filter and columns -- beside it.

        :param dock: the sub-dock of the browser to copy.
        """
        source = self.__browsers[dock]
        name = self.ask_browser_name(f"{source.name} copy", "Clone Browser")
        name = name.strip() if name is not None else ""
        if not name:
            return
        clone = TableBrowser(source.clone_state(name))
        clone_dock = self.__add_browser(clone, beside=dock)
        self.__fill(clone)
        self.__focus_tracker.set_current_dock(clone_dock)

    def __close_browser(self, dock: QtAds.CDockWidget) -> None:
        """Delete ``dock``'s browser, as its [x] asks: a browser is only a view, so nothing is asked first.

        :param dock: the browser's sub-dock.
        """
        if dock in self.__browsers:
            self.__remove_browser(dock)
            self.__update_enablement()

    def __fill(self, browser: TableBrowser) -> None:
        """Give a browser added after the rows were read the rows the others show.

        :param browser: the new browser.
        """
        file, cache = self.__file, self.__cache
        if file is None or cache is None:
            return
        try:
            wanted = {root.root_id for root in file.roots}
            rows = [row for row in cache.rows() if row.root_id in wanted]
        except sqlite3.Error as error:
            LOG.error("Could not read the cache of %s: %s", file.path, error)
            return
        browser.set_rows(rows, {root.root_id: root.path for root in file.roots})

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

    # region the app's own file changes

    def __on_moved(self, relocation: Relocation) -> None:
        """Rebase the rows a rename moved, reading nothing, and show them (#376).

        A scan still running under a renamed folder already reads on under the new name (its tracked
        locations were rewritten by the coordinator), so its rows land under the paths this rebased the old
        ones to.

        :param relocation: the rename's executed plan.
        """
        cache = self.__cache
        if cache is None or not relocation.pairs:
            return
        try:
            moved = cache.apply_relocation(relocation.pairs)
        except sqlite3.Error as error:
            LOG.error("Could not follow a rename in the cache of %s: %s", self.rehuco_path, error)
            return
        if moved:
            self.__refresh()

    def __on_files_changed(self, paths: tuple[Path, ...]) -> None:
        """Read each record the app wrote back into its row, and show what changed (#376).

        A path that is not a record, or not under a root, is passed over by the updater itself.

        :param paths: the files written or replaced.
        """
        cache = self.__cache
        if cache is None:
            return
        updater = CatalogRecordUpdater(cache, coordinator=self.__rename_coordinator)
        changed = False
        try:
            for path in paths:
                changed = updater.upsert(path) or changed
        except (OSError, sqlite3.Error) as error:
            LOG.error("Could not update the cache of %s: %s", self.rehuco_path, error)
        if changed:
            self.__refresh()

    # endregion
