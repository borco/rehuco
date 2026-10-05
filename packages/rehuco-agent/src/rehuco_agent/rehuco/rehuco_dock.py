"""The Root Catalog dock: one opened ``.rehuco``, its roots, and the resources its cache lists
(#377, [[plugins#rehuco-dock]], [[data-model#cache-schema]]).
"""

# one cohesive module: the shell's file, its roots, its browsers and the reads that fill them all turn on the same
# open catalog and cache, and a scoped disable reads better than an arbitrary split (same precedent as
# document_sub_docks.py, [[appendices.code-conventions]])
# pylint: disable=too-many-lines

import logging
import os
import sqlite3
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final, cast
from uuid import UUID

import PySide6QtAds as QtAds
from borco_core.logging import LogScope
from borco_pyside.qtads import (
    QtAdsAutoHideButtonSuppressor,
    QtAdsFocusTracker,
    QtAdsTabContextActions,
    remove_dock_widget,
)
from borco_pyside.theming import ActionIconThemeHandler
from borco_pyside.widgets import MessageBanner, MessageBannerRow, MessageBannerSeverity
from PySide6.QtCore import QByteArray, QItemSelectionModel, QModelIndex, QObject, QPoint, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QFont
from PySide6.QtWidgets import QComboBox, QDialog, QInputDialog, QLineEdit, QMainWindow, QMenu, QMessageBox, QWidget
from rehuco_core import (
    DEFAULT_RENAME_COORDINATOR,
    FINISHED_JOB_STATES,
    INFO_REHU_FILENAME,
    CatalogCache,
    CatalogField,
    CatalogQuery,
    CatalogRecordUpdater,
    CatalogRow,
    FileType,
    JobStatus,
    RehucoFile,
    RehucoFileError,
    RehucoRoot,
    Relocation,
    RemoveCatalogRootJob,
    RenameCoordinator,
    RootFolderLister,
    RootStorage,
    ScanCatalogRootJob,
    TaskJob,
    TaskQueue,
    VerifyChecksumsJob,
    rehudb_path,
)

from ..dock_maximize import attach_maximize_handler
from ..filter_urls import filter_url_token
from ..glyphs import TAB_CLOSE_GLYPH
from ..resource_events import ResourceEvents
from ..settings.catalog_state_store import CatalogState, CatalogStateStore
from ..settings.checksum_settings import shared_checksum_settings
from ..settings.excluded_files_settings import shared_excluded_files_settings
from ..settings.persistent_settings import cache_folder
from ..tasks.already_queued import job_already_queued
from .add_root_dialog import AddRootDialog
from .rehuco_roots_panel_ui import Ui_RehucoRootsPanel
from .root_storage import selected_root_storage
from .roots_column_view import RootsColumnView
from .roots_folder_model import RootsFolderModel, RootsNodeKind
from .roots_preview import RootsPreview
from .table_browser import TableBrowser

LOG: Final = logging.getLogger(__name__)

SCAN_ICON: Final = ":/icons/roots_scan.svg"
ADD_ROOT_ICON: Final = ":/icons/roots_add.svg"
REMOVE_ROOT_ICON: Final = ":/icons/roots_delete.svg"
REFRESH_ROOTS_ICON: Final = ":/icons/refresh.svg"
MOVE_TO_TOP_ICON: Final = ":/icons/items_top.svg"
MOVE_UP_ICON: Final = ":/icons/items_up.svg"
MOVE_DOWN_ICON: Final = ":/icons/items_down.svg"
MOVE_TO_BOTTOM_ICON: Final = ":/icons/items_bottom.svg"
ROOTS_ICON: Final = ":/icons/roots_view.svg"

DETAILS_PANE_WIDTH: Final = 320
"""How wide the details pane beside the Roots view's columns starts, in pixels."""
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

    open_folder_requested: Signal = Signal(object)
    """Emitted with a folder's :class:`~pathlib.Path` when its associated rehu is asked for: the ``info.rehu`` in it,
    or a new one if there is none yet ([[data-model#resource-scoping]]). Typed as plain ``object``, as above."""

    open_companion_requested: Signal = Signal(object)
    """Emitted with a file's :class:`~pathlib.Path` when its associated rehu is asked for: the one that shares its
    name, or a new one if there is none yet."""

    rehuco_path_changed: Signal = Signal(object)
    """Emitted with the open ``.rehuco``'s :class:`~pathlib.Path`, or ``None`` once none is open."""

    class Marshaller(QObject):
        """Carries "one of our jobs may have finished" across the thread boundary, and nothing else."""

        queue_changed = Signal()
        """Carries nothing: the payload is whatever the queue says by the time the slot runs."""

    def __init__(  # pylint: disable=too-many-arguments,too-many-statements
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

        self.__roots_model: Final = RootsFolderModel(self)
        self.__fallback: tuple[UUID, tuple[str, ...]] | None = None
        """Where the Roots selection goes once the rows it was in are removed: the folder they were in."""
        # connected before the view's selection model exists, so it runs before that model moves the current row to a
        # neighbour of the removed one -- which is the one thing this has to see unmoved
        self.__roots_model.rowsAboutToBeRemoved.connect(self.__on_roots_rows_about_to_be_removed)
        self.__roots_model.rowsRemoved.connect(self.__on_roots_rows_removed)
        # queued: a drop is handled inside the view's own event, and the move changes the rows it is dropping on
        self.__roots_model.root_move_requested.connect(self.__on_root_dropped, Qt.ConnectionType.QueuedConnection)

        self.__roots_panel: Final = QWidget(self)
        self.__roots_ui: Final = Ui_RehucoRootsPanel()
        self.__roots_ui.setupUi(self.__roots_panel)
        # the details of the current row, whatever it is, sit beside the columns
        self.__preview: Final = RootsPreview(self.__roots_model, rename_coordinator, self.__actions_for_row)
        splitter = self.__roots_ui.roots_splitter
        splitter.addWidget(self.__preview)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([DETAILS_PANE_WIDTH * 2, DETAILS_PANE_WIDTH])
        self.__roots_model.dataChanged.connect(self.__preview.follow)
        self.__roots_model.rowsRemoved.connect(self.__preview.forget_if_gone)
        self.__roots_ui.roots_view.setModel(self.__roots_model)
        self.__roots_ui.roots_view.doubleClicked.connect(self.__on_roots_double_clicked)
        self.__banner: Final = MessageBanner(self.__roots_panel)
        self.__roots_ui.main_layout.insertWidget(0, self.__banner)

        self.__browsers: Final[dict[QtAds.CDockWidget, TableBrowser]] = {}
        """Every browser's dock, in the order the browsers were added."""
        self.__last_browser: TableBrowser | None = None
        """The browser that was current last, which a filter set from outside lands on while the Roots view is
        the current sub-dock."""

        self.__dock_manager: Final = QtAds.CDockManager(self)
        self.__focus_tracker: Final = QtAdsFocusTracker(
            self.__dock_manager, close_glyph=TAB_CLOSE_GLYPH, stylesheet_host=stylesheet_host
        )
        # pinning belongs to the window's own docks, and this shell's sub-docks live inside one of them
        QtAdsAutoHideButtonSuppressor(self.__dock_manager)
        self.__maximize_handler: Final = attach_maximize_handler(self.__dock_manager)
        self.__tab_menus: Final = QtAdsTabContextActions(self.__dock_manager)
        self.__roots_dock: Final = self.__add_roots_dock()

        # a root's menu has two groups to divide, and one action cannot sit twice in a menu, so two separators, made
        # once: the menu and the details pane ask for a row's actions on every selection
        self.__separators: Final = (QAction(self), QAction(self))
        for separator in self.__separators:
            separator.setSeparator(True)
        self.__new_browser_action: Final = QAction("New Table Browser", self)
        self.__new_browser_action.setToolTip("Add a table browser over this catalog's resources.")
        self.__rename_browser_action: Final = QAction("Rename Browser...", self)
        self.__rename_browser_action.setToolTip("Rename the current browser.")
        self.__setup_toolbar()
        # selection_model() is None only before a model is set (setModel just did)
        self.__roots_selection: Final = cast(QItemSelectionModel, self.__roots_ui.roots_view.selectionModel())
        self.__roots_selection.currentChanged.connect(self.__on_roots_current_row_changed)
        for signal in (
            self.__roots_model.rowsInserted,
            self.__roots_model.rowsRemoved,
            self.__roots_model.rowsMoved,
            self.__roots_model.dataChanged,
        ):
            signal.connect(self.__on_roots_current_changed)
        self.__preview.root_name_edit.editingFinished.connect(self.__on_root_name_edited)
        self.__preview.root_storage_combo.activated.connect(self.__on_root_storage_chosen)
        self.__focus_tracker.current_dock_changed.connect(self.__update_enablement)
        self.__focus_tracker.current_dock_changed.connect(self.__remember_current_browser)
        self.__update_enablement()
        queue.add_listener(self)
        if resource_events is not None:
            resource_events.moved.connect(self.__on_moved)
            resource_events.changed.connect(self.__on_files_changed)
            resource_events.folder_changed.connect(self.__on_folder_changed)

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
            self.__events.folder_changed.disconnect(self.__on_folder_changed)
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
    def roots_model(self) -> RootsFolderModel:
        """The Roots view's model: the roots, and the folders and files under them."""
        return self.__roots_model

    @property
    def roots_view(self) -> RootsColumnView:
        """The Roots view: one column per open level, the roots in the first."""
        return self.__roots_ui.roots_view

    @property
    def root_name_edit(self) -> QLineEdit:
        """The name field the details pane shows for a root."""
        return self.__preview.root_name_edit

    @property
    def root_storage_combo(self) -> QComboBox:
        """The storage combo the details pane shows for a root."""
        return self.__preview.root_storage_combo

    @property
    def roots_dock(self) -> QtAds.CDockWidget:
        """The Roots sub-dock, closable and shown again by :attr:`roots_action`."""
        return self.__roots_dock

    @property
    def browsers(self) -> tuple[TableBrowser, ...]:
        """Every browser, in the order they were added."""
        return tuple(self.__browsers.values())

    def open_browsers(self) -> tuple[TableBrowser, ...]:
        """Every browser whose sub-dock is open, in the order they were added -- the set the Browsers menu lists."""
        return tuple(browser for dock, browser in self.__browsers.items() if not dock.isClosed())

    def focused_browser(self) -> TableBrowser | None:
        """The browser the Browsers menu checks: :attr:`current_browser`, under the name its menu reads it by."""
        return self.current_browser

    def focus_browser(self, browser: TableBrowser) -> None:
        """Show ``browser``'s sub-dock, bring its tab to the front and make it the current one.

        :param browser: one of :attr:`browsers`.
        """
        dock = self.browser_dock(browser)
        dock.toggleView(True)
        dock.setAsCurrentTab()
        self.__focus_tracker.set_current_dock(dock)

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

    def set_filter_token(self, field: CatalogField, value: str) -> bool:
        """Filter the current browser on ``value`` in ``field``, replacing any filter on that field it had
        ([[plugins#rehuco-dock]]): what a click-to-filter link and the Roots view's folder filter do.

        The current browser is the focused one, else the one last focused -- the Roots view may be current -- else
        the first one open. With none open, a default browser is opened to carry the filter.

        :param field: the field to filter on.
        :param value: the value, as its resource spells it.
        :returns: whether it was set; never while no catalog is open.
        """
        if self.__file is None:
            return False
        browser = self.__filter_target()
        if browser is None:
            browser = self.__new_browser()
        else:
            self.focus_browser(browser)
        browser.set_token(field.value, value)
        return True

    def apply_filter_url(self, url: str) -> bool:
        """Set the filter a click-to-filter link stands for on the current browser (:meth:`set_filter_token`).

        :param url: a ``filter://`` link ([[plugins#filter-urls]]).
        :returns: whether a filter was set; not for a link that names none, nor while no catalog is open.
        """
        token = filter_url_token(url)
        if token is None:
            LOG.warning("Not a filter link: %s", url)
            return False
        return self.set_filter_token(*token)

    def __filter_target(self) -> TableBrowser | None:
        """The browser a filter set from outside lands on; see :meth:`set_filter_token`.

        :returns: the browser, or ``None`` while none is open.
        """
        if self.current_browser is not None:
            return self.current_browser
        opened = self.open_browsers()
        if self.__last_browser in opened:
            return self.__last_browser
        return opened[0] if opened else None

    def __remember_current_browser(self) -> None:
        """Keep the browser that is current now as the last one, whenever one is."""
        if self.current_browser is not None:
            self.__last_browser = self.current_browser

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
        """Removes the selected root, after asking."""
        return self.__roots_ui.remove_root_action

    @property
    def refresh_roots_action(self) -> QAction:
        """Lists the open columns of the Roots view again (F5)."""
        return self.__roots_ui.refresh_roots_action

    @property
    def move_root_actions(self) -> tuple[QAction, QAction, QAction, QAction]:
        """Move the selected root to the top, up, down and to the bottom, in that order."""
        ui = self.__roots_ui
        return ui.move_to_top_action, ui.move_up_action, ui.move_down_action, ui.move_to_bottom_action

    @property
    def verify_checksums_action(self) -> QAction:
        """Verifies the resource of the selected checksum file, on the task queue."""
        return self.__roots_ui.verify_checksums_action

    @property
    def open_explorer_action(self) -> QAction:
        """Shows the selected root or folder in the system's file manager."""
        return self.__roots_ui.open_explorer_action

    @property
    def open_record_action(self) -> QAction:
        """Opens the selected ``.rehu`` or ``.tc`` file in Documents."""
        return self.__roots_ui.open_record_action

    @property
    def open_file_action(self) -> QAction:
        """Opens the selected file with the application the system associates with it."""
        return self.__roots_ui.open_file_action

    @property
    def open_companion_action(self) -> QAction:
        """Opens the rehu that describes the selected folder or file, which is there."""
        return self.__roots_ui.open_companion_action

    @property
    def create_companion_action(self) -> QAction:
        """Starts a new rehu for the selected folder or file, which has none; nothing is written until it is saved."""
        return self.__roots_ui.create_companion_action

    @property
    def filter_folder_action(self) -> QAction:
        """Filters the current browser to the resources under the selected root or folder."""
        return self.__roots_ui.filter_folder_action

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
            self.__roots_model.set_roots((), None)
            self.__banner.set_rows(())
            return
        roots = self.__file.roots
        matching: dict[CatalogQuery, list[CatalogRow]] = {}
        try:
            wanted = {root.root_id for root in roots}
            # browsers filtering alike share one read
            for browser in self.__browsers.values():
                if browser.query not in matching:
                    matching[browser.query] = self.__matching_rows(self.__cache, browser.query, wanted)
        except sqlite3.Error as error:
            LOG.error("Could not read the cache of %s: %s", self.__file.path, error)
            return
        self.__roots_model.set_roots(roots, RootFolderLister(roots, coordinator=self.__rename_coordinator))
        root_paths = {root.root_id: root.path for root in roots}
        for browser in self.__browsers.values():
            browser.set_rows(matching[browser.query], root_paths)
        lock_reason = self.__file.lock_reason
        self.__banner.set_rows(
            [] if lock_reason is None else [MessageBannerRow(MessageBannerSeverity.WARNING, lock_reason.message)]
        )

    @staticmethod
    def __matching_rows(cache: CatalogCache, query: CatalogQuery, wanted: set[UUID]) -> list[CatalogRow]:
        """The rows ``query`` matches under the roots the file lists.

        :param cache: the open cache.
        :param query: a browser's query.
        :param wanted: the file's root ids -- a root removed from it keeps its rows until its removal job has run, and
            they are not shown.
        :returns: the rows, in the cache's order.
        :raises sqlite3.Error: when the cache cannot be read.
        """
        return [row for row in cache.rows(query) if row.root_id in wanted]

    def __add_roots_dock(self) -> QtAds.CDockWidget:
        """Place the Roots view on this shell's own manager, closable: hidden by its [x] and shown again by
        :attr:`roots_action`, so closing it loses nothing.

        :returns: the Roots sub-dock.
        """
        features = QtAds.CDockWidget.DockWidgetFeature
        roots = QtAds.CDockWidget(self.__dock_manager, ROOTS_DOCK_TITLE)
        roots.setObjectName(ROOTS_DOCK_NAME)
        roots.setFeatures(features.DockWidgetClosable | features.DockWidgetFocusable | features.DockWidgetMovable)
        roots.setWidget(self.__roots_panel)
        # the root edits affect this view and nothing else, so they sit on its own title bar and its context menu
        # rather than on the shell's toolbar ([[appendices.code-conventions#command-surfaces]])
        ui = self.__roots_ui
        roots.setTitleBarActions([ui.add_root_action, ui.remove_root_action, ui.refresh_roots_action])
        # F5 works from any column, since they are all this panel's children
        self.__roots_panel.addAction(ui.refresh_roots_action)
        ui.roots_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        ui.roots_view.customContextMenuRequested.connect(self.__on_roots_context_menu)
        self.__dock_manager.addDockWidget(QtAds.LeftDockWidgetArea, roots)
        return roots

    def __setup_toolbar(self) -> None:
        """Fill this shell's toolbar -- Scan, the Roots toggle, then New and Rename Browser -- each with its themed
        icon, and give the two root edits theirs, which they show on the Roots sub-dock's title bar instead.

        Scan stays here because it affects every browser; New Table Browser because it creates one in this shell
        ([[appendices.code-conventions#command-surfaces]])."""
        ui = self.__roots_ui
        toolbar = self.addToolBar("Root Catalog")
        toolbar.addAction(ui.scan_action)
        toolbar.addSeparator()
        toolbar.addAction(self.roots_action)
        toolbar.addSeparator()
        toolbar.addActions([self.__new_browser_action, self.__rename_browser_action])
        for action, icon in (
            (ui.scan_action, SCAN_ICON),
            (ui.add_root_action, ADD_ROOT_ICON),
            (ui.remove_root_action, REMOVE_ROOT_ICON),
            (ui.refresh_roots_action, REFRESH_ROOTS_ICON),
            (ui.move_to_top_action, MOVE_TO_TOP_ICON),
            (ui.move_up_action, MOVE_UP_ICON),
            (ui.move_down_action, MOVE_DOWN_ICON),
            (ui.move_to_bottom_action, MOVE_TO_BOTTOM_ICON),
            (self.roots_action, ROOTS_ICON),
            (self.__new_browser_action, NEW_BROWSER_ICON),
            (self.__rename_browser_action, RENAME_BROWSER_ICON),
        ):
            ActionIconThemeHandler(action, icon)
        ui.scan_action.triggered.connect(self.scan)
        ui.add_root_action.triggered.connect(self.__on_add_root)
        ui.remove_root_action.triggered.connect(self.__on_remove_root)
        ui.refresh_roots_action.triggered.connect(self.__on_refresh_roots)
        ui.filter_folder_action.triggered.connect(self.__on_filter_folder)
        ui.open_record_action.triggered.connect(self.__on_open_record)
        ui.open_explorer_action.triggered.connect(self.__on_open_explorer)
        ui.verify_checksums_action.triggered.connect(self.__on_verify_checksums)
        ui.open_file_action.triggered.connect(self.__on_open_file)
        ui.open_companion_action.triggered.connect(self.__on_companion)
        ui.create_companion_action.triggered.connect(self.__on_companion)
        for action, move in (
            (ui.move_to_top_action, RehucoFile.move_to_top),
            (ui.move_up_action, RehucoFile.move_up),
            (ui.move_down_action, RehucoFile.move_down),
            (ui.move_to_bottom_action, RehucoFile.move_to_bottom),
        ):
            action.triggered.connect(lambda _checked=False, move=move: self.__move_root(move))
        self.__new_browser_action.triggered.connect(self.__on_new_browser)
        self.__rename_browser_action.triggered.connect(self.__on_rename_current_browser)

    def __update_enablement(self) -> None:
        """Enable Scan while a file is open, and the root edits only while it can also be saved -- Remove and the moves
        needing a selected **root row** besides, the moves not at the end they move towards. Refresh and the folder
        filter need a catalog, the filter a root or folder to name. New Browser needs a catalog to hold it, and
        Rename Browser a browser to be the current sub-dock, not the Roots one."""
        file = self.__file
        editable = file is not None and file.lock_reason is None
        ui = self.__roots_ui
        current = ui.roots_view.currentIndex()
        row = current.row() if self.__roots_model.root_at(current) is not None else -1
        last = self.__roots_model.rowCount() - 1
        self.__preview.set_editable(editable)
        self.__roots_model.set_reorderable(editable)
        ui.scan_action.setEnabled(file is not None)
        ui.add_root_action.setEnabled(editable)
        ui.remove_root_action.setEnabled(editable and row >= 0)
        ui.refresh_roots_action.setEnabled(file is not None)
        ui.move_to_top_action.setEnabled(editable and row > 0)
        ui.move_up_action.setEnabled(editable and row > 0)
        ui.move_down_action.setEnabled(editable and 0 <= row < last)
        ui.move_to_bottom_action.setEnabled(editable and 0 <= row < last)
        ui.filter_folder_action.setEnabled(
            file is not None and self.__roots_model.node_kind(current) in (RootsNodeKind.ROOT, RootsNodeKind.FOLDER)
        )
        self.__new_browser_action.setEnabled(file is not None)
        self.__rename_browser_action.setEnabled(self.current_browser is not None)

    # endregion

    # region the Roots view

    def __on_roots_current_row_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        """List the folder that became current if nobody has yet, whether or not the view is on screen to ask, and
        bring the actions and the card in line.

        :param current: the new current row.
        :param _previous: the row that was current.
        """
        self.__roots_model.fetchMore(current)
        self.__preview.show_index(current)
        self.__on_roots_current_changed()

    def __on_roots_current_changed(self, *_args: object) -> None:
        """Bring the actions in line with the current row, whatever changed it."""
        self.__update_enablement()

    def __current_root_row(self) -> int:
        """The current row of the Roots view if it is a root row.

        :returns: its row, which is also its place in the file; ``-1`` for a folder, a file, or none.
        """
        current = self.__roots_ui.roots_view.currentIndex()
        return current.row() if self.__roots_model.root_at(current) is not None else -1

    def __on_root_name_edited(self) -> None:
        """Rename the current root to what was typed in the details pane, as its label; nothing on disk changes.

        An empty name, or one another root already has, is refused with a warning and the field goes back to the
        label the root has.
        """
        file, row = self.__file, self.__current_root_row()
        if file is None or file.lock_reason is not None or row < 0:
            return
        root = file.roots[row]
        edit = self.__preview.root_name_edit
        name = edit.text().strip()
        if name == root.label:
            edit.setText(root.label)
            return
        try:
            file.relabel_root(row, name)
        except ValueError as error:
            QMessageBox.warning(self, "Rename Root", str(error))
            edit.setText(root.label)
            return
        self.__commit_root_edit()

    def __on_root_storage_chosen(self) -> None:
        """Set the current root to the storage chosen in the details pane; nothing on disk changes."""
        file, row = self.__file, self.__current_root_row()
        if file is None or file.lock_reason is not None or row < 0:
            return
        storage = selected_root_storage(self.__preview.root_storage_combo)
        if file.roots[row].storage is storage:
            return
        file.set_storage(row, storage)
        self.__commit_root_edit()

    def __commit_root_edit(self) -> None:
        """Save an edit of a root, bring the cache's copy of it in line, and show it."""
        if self.__save_file():
            self.__reconcile_cache()
        self.__refresh()
        self.__preview.refresh()

    def __move_root(self, move: Callable[[RehucoFile, int], int]) -> None:
        """Move the current root with one of the file's ordering operations, and keep it current.

        :param move: the :class:`~rehuco_core.RehucoFile` operation; takes the row and returns where it ended up.
        """
        file, row = self.__file, self.__current_root_row()
        if file is None or file.lock_reason is not None or row < 0:
            return
        root_id = file.roots[row].root_id
        if move(file, row) == row:
            return
        if self.__save_file():
            self.__reconcile_cache()
        self.__refresh()
        self.__roots_ui.roots_view.setCurrentIndex(self.__roots_model.index_for(root_id, ()))

    def __on_root_dropped(self, root_id: UUID, to: int) -> None:
        """Move a root that was dragged to its new place: the file is reordered, saved and shown, as the move buttons
        do, and the root stays current.

        :param root_id: the root dropped.
        :param to: the row it should end up at.
        """
        file = self.__file
        row = None if file is None else next((i for i, r in enumerate(file.roots) if r.root_id == root_id), None)
        if file is None or file.lock_reason is not None or row is None:
            return
        self.__roots_ui.roots_view.setCurrentIndex(self.__roots_model.index(row, 0))
        self.__move_root(lambda moved, at: moved.move(at, to))

    def __on_refresh_roots(self) -> None:
        """List the columns on screen again (F5): the current row's chain, or every root while none is current."""
        model = self.__roots_model
        current = self.__roots_ui.roots_view.currentIndex()
        if current.isValid():
            model.relist_chain(current)
            return
        for row in range(model.rowCount()):
            model.relist(model.index(row, 0))

    def __on_roots_double_clicked(self, index: QModelIndex) -> None:
        """Run a row's default action (:meth:`__default_action`); a root has none, and only navigates.

        :param index: the row.
        """
        self.__run(self.__default_action(index), index)

    def __on_open_record(self) -> None:
        """Open the current row's record in Documents."""
        self.__run(self.__roots_ui.open_record_action, self.__roots_ui.roots_view.currentIndex())

    def __on_open_file(self) -> None:
        """Open the current row's file with the application the system associates with it."""
        self.__run(self.__roots_ui.open_file_action, self.__roots_ui.roots_view.currentIndex())

    def __on_open_explorer(self) -> None:
        """Show the current root or folder in the system's file manager."""
        self.__run(self.__roots_ui.open_explorer_action, self.__roots_ui.roots_view.currentIndex())

    def __on_verify_checksums(self) -> None:
        """Queue a verification of the resource the current checksum file belongs to.

        The Checksums dock's plain *Verify* -- every file checked, with the same settings -- not its *Verify Old*,
        which skips what was checked recently; the two derive the same label, so a verify already waiting for this
        resource, asked from either place, is not asked again.
        """
        resource = self.__verify_resource(self.__roots_ui.roots_view.currentIndex())
        if resource is None:
            return
        checksums = shared_checksum_settings()
        job = VerifyChecksumsJob(
            resource,
            coordinator=self.__rename_coordinator,
            algorithm=checksums.algorithm,
            excluded_patterns=shared_excluded_files_settings().excluded_file_patterns,
            create_if_missing=True if checksums.create_missing_on_verify else None,
            migrate_to=checksums.migrate_target,
        )
        if job_already_queued(self.__queue, label=job.label, source=job.source):
            LOG.info("%s is already in the task queue; it was not queued again.", job.label)
            return
        with LogScope.open(resource):
            self.__queue.enqueue(job)

    def __on_companion(self) -> None:
        """Ask for the rehu that describes the current folder or file: a folder's ``info.rehu``, a file's same-name
        ``.rehu``. The main window opens the one there is or starts a new, unsaved one, which is why opening and
        creating ask the same question; which of them the menu offered is only a matter of what is on disk."""
        index = self.__roots_ui.roots_view.currentIndex()
        self.__run(self.__companion_action(index), index)

    def __run(self, action: QAction | None, index: QModelIndex) -> None:
        """Do what one of the row actions stands for, to a row.

        :param action: the action, or ``None`` for a row with nothing to do.
        :param index: the row.
        """
        path = self.__roots_model.path_of(index)
        if action is None or path is None:
            return
        ui = self.__roots_ui
        if action is ui.open_record_action:
            if self.__roots_model.file_type_of(index) is FileType.RECORD:
                self.open_requested.emit(path)
        elif action in (ui.open_file_action, ui.open_explorer_action):
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        elif self.__roots_model.node_kind(index) is RootsNodeKind.FOLDER:
            self.open_folder_requested.emit(path)
        else:
            self.open_companion_requested.emit(path)

    def __on_folder_changed(self, directory: Path) -> None:
        """List a folder again that the app changed the contents of, if the Roots view has it loaded.

        :param directory: the folder.
        """
        self.__roots_model.relist_folder(directory)

    def __on_filter_folder(self) -> None:
        """Filter the current browser to the resources under the current root or folder (#398)."""
        model = self.__roots_model
        current = self.__roots_ui.roots_view.currentIndex()
        root, key = model.root_of(current), model.key(current)
        if root is None or key is None or model.node_kind(current) not in (RootsNodeKind.ROOT, RootsNodeKind.FOLDER):
            return
        self.set_filter_token(CatalogField.FOLDER, "/".join((root.label, *key[1])))

    def roots_context_actions(self, index: QModelIndex) -> list[QAction]:
        """What the Roots view's context menu holds for a row.

        A root: the folder filter and Open in file explorer, then the four moves, then Remove. A folder: **Open
        associated rehu** if it has one, **Create info.rehu** if not, then the folder filter and Open in file explorer.
        A rehu record: Open. A checksum file: Open with its application, Verify checksums, then the associated rehu.
        Any other file: Open with its application, then Open associated rehu or Create <name>.rehu likewise. A
        placeholder: nothing. The row's default action, which a double-click runs, is drawn bold: Open, in every case
        but a folder with no rehu, whose double-click does nothing -- **a rehu is only ever created from this menu**.

        :param index: the row the menu is for.
        :returns: the actions in menu order, a separator among them where the groups change.
        """
        ui = self.__roots_ui
        match self.__roots_model.node_kind(index):
            case RootsNodeKind.ROOT:
                actions = [
                    ui.filter_folder_action,
                    ui.open_explorer_action,
                    self.__separators[0],
                    *self.move_root_actions,
                    self.__separators[1],
                    ui.remove_root_action,
                ]
            case RootsNodeKind.FOLDER:
                actions = [self.__companion_action(index), ui.filter_folder_action, ui.open_explorer_action]
            case RootsNodeKind.FILE:
                file_type = self.__roots_model.file_type_of(index)
                if file_type is FileType.RECORD:
                    actions = [ui.open_record_action]
                elif file_type is FileType.MANIFEST:
                    actions = [ui.open_file_action, self.__verify_action(index), self.__companion_action(index)]
                else:
                    actions = [ui.open_file_action, self.__companion_action(index)]
            case _:
                return []
        default = self.__default_action(index)
        bold = QFont()
        bold.setBold(True)
        # the actions are shared by every row's menu, so which one is bold is decided each time it is asked for
        for action in (
            ui.open_record_action,
            ui.open_file_action,
            ui.open_companion_action,
            ui.create_companion_action,
            ui.filter_folder_action,
            ui.open_explorer_action,
            ui.verify_checksums_action,
        ):
            action.setFont(bold if action is default else QFont())
        return actions

    def __actions_for_row(self, index: QModelIndex) -> tuple[list[QAction], QAction | None]:
        """What the details pane makes buttons of for a row: its context menu, and its default.

        :param index: the row.
        :returns: the actions in menu order, and the default one. A root has no move buttons: its grip moves it, and
            the moves stay in its menu.
        """
        if self.__roots_model.node_kind(index) is RootsNodeKind.ROOT:
            ui = self.__roots_ui
            first_separator = self.__separators[0]
            return [ui.filter_folder_action, ui.open_explorer_action, first_separator, ui.remove_root_action], None
        return self.roots_context_actions(index), self.__default_action(index)

    def __default_action(self, index: QModelIndex) -> QAction | None:
        """What a double-click on a row does, and what the details pane's Open button runs.

        :param index: the row.
        :returns: a folder's associated rehu if it has one, a record's Open, any other file's Open with its
            application; ``None`` for a root and a placeholder, which only navigate, and for a folder with no rehu --
            a double-click never creates one.
        """
        ui = self.__roots_ui
        match self.__roots_model.node_kind(index):
            case RootsNodeKind.FOLDER:
                return ui.open_companion_action if self.__companion_exists(index) else None
            case RootsNodeKind.FILE:
                if self.__roots_model.file_type_of(index) is FileType.RECORD:
                    return ui.open_record_action
                return ui.open_file_action
        return None

    def __companion_action(self, index: QModelIndex) -> QAction:
        """What the associated rehu of a folder or file is asked for as: opening it if it is there, creating it if not.
        The create action names the record it would start -- ``info.rehu``, or the file's own name with ``.rehu``.

        :param index: the folder or file.
        :returns: the open action or the create action.
        """
        ui = self.__roots_ui
        if self.__companion_exists(index):
            return ui.open_companion_action
        record = self.__companion_record(index)
        if record is not None:
            ui.create_companion_action.setText(f"Create {record.name}")
        return ui.create_companion_action

    def __companion_record(self, index: QModelIndex) -> Path | None:
        """Where the ``.rehu`` of a folder or file is, or would be.

        :param index: the folder or file.
        :returns: its ``info.rehu`` for a folder, its same-name ``.rehu`` for a file; ``None`` for any other row.
        """
        path = self.__roots_model.path_of(index)
        if path is None:
            return None
        if self.__roots_model.node_kind(index) is RootsNodeKind.FOLDER:
            return path / INFO_REHU_FILENAME
        return path.with_suffix(".rehu")

    def __companion_exists(self, index: QModelIndex) -> bool:
        """Whether a folder or file already has its rehu: the folder's ``info.rehu`` or ``info.tc``, the file's
        same-name ``.rehu`` or ``.tc``.

        Answered from the listing when it has one -- a file's neighbours are always listed, a folder's only once it
        has been opened -- and from the disk otherwise.

        :param index: the folder or file.
        :returns: whether there is one to open.
        """
        record = self.__companion_record(index)
        if record is None:
            return False
        holder = index if self.__roots_model.node_kind(index) is RootsNodeKind.FOLDER else index.parent()
        candidates = (record, record.with_suffix(".tc"))
        names = self.__roots_model.child_names(holder)
        if names is None:
            return any(candidate.exists() for candidate in candidates)
        wanted = {os.path.normcase(candidate.name) for candidate in candidates}
        return bool(wanted & {os.path.normcase(name) for name in names})

    def __verify_action(self, index: QModelIndex) -> QAction:
        """The Verify action for a checksum file, on only while the resource it belongs to is there to be checked.

        :param index: the checksum file.
        :returns: the action, enabled or not, with a tooltip saying which.
        """
        ui = self.__roots_ui
        resource = self.__verify_resource(index)
        ui.verify_checksums_action.setEnabled(resource is not None)
        ui.verify_checksums_action.setToolTip(
            "Check the files of the resource this checksum record belongs to against it, on the task queue."
            if resource is not None
            else "There is no .rehu with this name beside it to check the files of."
        )
        return ui.verify_checksums_action

    def __verify_resource(self, index: QModelIndex) -> Path | None:
        """The resource a checksum file records: the ``.rehu`` that shares its name.

        :param index: the checksum file.
        :returns: the ``.rehu``'s path when it is there, else ``None``. Answered from the listing, which a file's
            neighbours always have.
        """
        path = self.__roots_model.path_of(index)
        names = self.__roots_model.child_names(index.parent())
        if path is None or names is None:
            return None
        resource = path.with_suffix(".rehu")
        return resource if os.path.normcase(resource.name) in {os.path.normcase(name) for name in names} else None

    def __on_roots_context_menu(self, position: QPoint) -> None:
        """Open the Roots view's context menu on the row under the pointer, making it the current row first so the
        actions act on it.

        :param position: where it was asked for, in the view's coordinates.
        """
        view = self.__roots_ui.roots_view
        global_position = view.mapToGlobal(position)
        index = view.index_at_global(global_position)
        actions = self.roots_context_actions(index)
        if not actions:
            return
        view.setCurrentIndex(index)
        menu = QMenu(self)
        menu.addActions(actions)
        menu.exec(global_position)
        menu.deleteLater()

    def __on_roots_rows_about_to_be_removed(self, parent: QModelIndex, first: int, last: int) -> None:
        """Remember where the selection falls back to if the rows about to go hold it: the folder they are in.

        Qt would move it to a neighbour of the removed row, which is a different folder from the one the reader was
        in; the nearest surviving ancestor is the better answer (a folder deleted outside the app, then F5).

        :param parent: the row the removed rows are under.
        :param first: the first removed row.
        :param last: the last removed row.
        """
        self.__fallback = None
        if not parent.isValid():
            return
        index = self.__roots_ui.roots_view.currentIndex()
        while index.isValid():
            if index.parent() == parent and first <= index.row() <= last:
                key = self.__roots_model.key(parent)
                self.__fallback = key
                return
            index = index.parent()

    def __on_roots_rows_removed(self) -> None:
        """Select the folder remembered by :meth:`__on_roots_rows_about_to_be_removed`, if there is one."""
        fallback, self.__fallback = self.__fallback, None
        if fallback is not None:
            self.__roots_ui.roots_view.setCurrentIndex(self.__roots_model.index_for(*fallback))

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

    def __remember_catalog(self, file: RehucoFile) -> None:
        """Write ``file``'s browsers, and where every sub-dock sits, to the catalog store.

        :param file: the catalog being left.
        """
        with self.__maximize_handler.unmaximized():
            layout = bytes(self.__dock_manager.saveState().data())
        browsers = [browser.state() for browser in self.__browsers.values()]
        self.__catalog_store.save(file.rehuco_id, CatalogState(browsers, layout))

    def __close_browsers(self) -> None:
        """Remove every browser's sub-dock, leaving the Roots view alone on the manager."""
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
        # registered before it is placed: placing it can make it the current sub-dock, and whoever hears that asks
        # which browser it is
        self.__browsers[dock] = browser  # pylint: disable=unsupported-assignment-operation
        self.__place(dock, beside)
        browser.row_activated.connect(self.open_requested)
        browser.query_changed.connect(lambda: self.__fill(browser))
        dock.closeRequested.connect(lambda: self.__close_browser(dock))
        return dock

    def __place(self, dock: QtAds.CDockWidget, beside: QtAds.CDockWidget | None = None) -> None:
        """Add a browser's sub-dock to the manager: into the tab strip of ``beside``, else of the first browser that
        is on screen, else to the right of the Roots view; and give its tab its actions.

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
        if self.__browsers.pop(dock, None) is self.__last_browser:
            self.__last_browser = None
        remove_dock_widget(self.__dock_manager, dock)
        dock.deleteLater()

    def __on_new_browser(self) -> None:
        """Add a default table browser and make it current."""
        if self.__file is not None:
            self.__new_browser()

    def __new_browser(self) -> TableBrowser:
        """Add a default table browser, filled, and make it current.

        :returns: the new browser.
        """
        browser = TableBrowser()
        dock = self.__add_browser(browser)
        self.__fill(browser)
        self.__focus_tracker.set_current_dock(dock)
        return browser

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
        """Read one browser's rows again: a browser added after the others were read, or one whose filter changed.

        :param browser: the browser.
        """
        file, cache = self.__file, self.__cache
        if file is None or cache is None:
            return
        try:
            rows = self.__matching_rows(cache, browser.query, {root.root_id for root in file.roots})
        except sqlite3.Error as error:
            LOG.error("Could not read the cache of %s: %s", file.path, error)
            return
        browser.set_rows(rows, {root.root_id: root.path for root in file.roots})

    # endregion

    # region editing the roots

    def ask_root_to_add(self) -> tuple[str, RootStorage] | None:
        """Ask for a root to add: its storage, then its folder. The one modal behind Add Root, so a test replaces it
        per instance.

        :returns: the folder and what it lives on, or ``None`` if the dialog was cancelled.
        """
        dialog = AddRootDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.folder, dialog.storage

    def confirm_remove_root(self, root: RehucoRoot, cached: int) -> bool:
        """Ask whether to remove a root, saying what goes and what stays. The one modal behind Remove Root, so a test
        replaces it per instance.

        :param root: the root to remove.
        :param cached: how many cached resources go with it.
        :returns: whether to go ahead.
        """
        entries = "1 cached entry is" if cached == 1 else f"{cached} cached entries are"
        answer = QMessageBox.question(
            self,
            "Remove Root",
            f'Remove the root "{root.label}" from this catalog?\n\n'
            f"Its files stay where they are, in {root.path}. {entries} removed from the cache; a scan would bring "
            "them back if the folder were added again.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def __on_add_root(self) -> None:
        """Ask for a folder and what it lives on and add it as a root, saving the file at once, and make it current."""
        file = self.__file
        if file is None or file.lock_reason is not None:
            return
        chosen = self.ask_root_to_add()
        if chosen is None:
            return
        folder, storage = chosen
        try:
            row = file.add_root(folder, storage=storage)
        except ValueError as error:
            QMessageBox.warning(self, "Add Root", str(error))
            return
        root_id = file.roots[row].root_id
        if self.__save_file():
            self.__reconcile_cache()
        self.__refresh()
        self.__roots_ui.roots_view.setCurrentIndex(self.__roots_model.index_for(root_id, ()))

    def __on_remove_root(self) -> None:
        """Remove the current root from the file, once confirmed, saving it at once, and its rows from the cache on
        the queue."""
        file = self.__file
        cache = self.__cache
        if file is None or cache is None or file.lock_reason is not None:
            return
        row = self.__current_root_row()
        if row < 0:
            return
        root = file.roots[row]
        try:
            cached = cache.resource_count(root.root_id)
        except sqlite3.Error as error:
            LOG.error("Could not count the cached entries of %s: %s", root.label, error)
            cached = 0
        if not self.confirm_remove_root(root, cached):
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
        self.__roots_model.relocate(relocation)
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
