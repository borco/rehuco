"""The Root Catalog dock's content: the open ``.rehuco``'s roots, the folders and files under them, and the
details of the current one (#377, #378, #461, [[plugins#rehuco-dock]]).
"""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Final, cast
from uuid import UUID

from borco_pyside.file_browser import reveal_in_file_browser
from borco_pyside.theming import ActionIconThemeHandler
from borco_pyside.widgets import MessageBanner, MessageBannerRow, MessageBannerSeverity
from PySide6.QtCore import QItemSelectionModel, QModelIndex, QPersistentModelIndex, QPoint, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import QComboBox, QDialog, QLineEdit, QMenu, QMessageBox, QWidget
from rehuco_core import (
    CHECKSUM_RECORD_SUFFIX,
    DEFAULT_CHECKSUM_TRUST,
    DEFAULT_RENAME_COORDINATOR,
    CatalogField,
    FileType,
    RehucoFile,
    RehucoRoot,
    Relocation,
    RenameCoordinator,
    RootFolderLister,
    RootStorage,
    TaskQueue,
    checksum_record_path,
)

from ..resource_events import ResourceEvents
from ..tasks.job_end_watcher import JobEndWatcher
from .add_root_dialog import AddRootDialog
from .rehuco_roots_panel_ui import Ui_RehucoRootsPanel
from .root_catalog import RootCatalog
from .root_storage import selected_root_storage
from .roots_checksum_verbs import RootsChecksumVerbs
from .roots_column_view import RootsColumnView
from .roots_folder_model import RootsFolderModel, RootsNodeKind
from .roots_lightbox import RootsLightbox
from .roots_management import selected_record
from .roots_opening import RootsOpening
from .roots_preview import RootsPreview
from .roots_row_actions import RootsRowActions

LOG: Final = logging.getLogger(__name__)

SCAN_ICON: Final = ":/icons/roots_scan.svg"
ADD_ROOT_ICON: Final = ":/icons/roots_add.svg"
REMOVE_ROOT_ICON: Final = ":/icons/roots_delete.svg"
REFRESH_ROOTS_ICON: Final = ":/icons/refresh.svg"
MOVE_TO_TOP_ICON: Final = ":/icons/items_top.svg"
MOVE_UP_ICON: Final = ":/icons/items_up.svg"
MOVE_DOWN_ICON: Final = ":/icons/items_down.svg"
MOVE_TO_BOTTOM_ICON: Final = ":/icons/items_bottom.svg"

DETAILS_PANE_WIDTH: Final = 320
"""How wide the details pane beside the Roots view's columns starts, in pixels."""


# the public surface is read accessors for the view and its actions, which the window and the tests drive -- one
# cohesive widget, not a class waiting to be split
class RootsPanel(QWidget):  # pylint: disable=too-many-instance-attributes,too-many-public-methods
    """The open :class:`~.root_catalog.RootCatalog`'s roots as a column view, a details pane beside it and a
    banner over both -- everything about the ``.rehuco`` and its roots, which the window's **Root Catalog** dock
    holds (#461). The resources the cache lists are the **Browsers** dock's
    (:class:`~.browsers_dock.BrowsersDock`).

    **A row's actions have one home**, :class:`~.roots_row_actions.RootsRowActions`: the menu, the details pane's
    buttons and what a double-click runs. Scan, Add Root and Remove Root are
    rare enough that the ``Root Catalog`` menu is their home (Remove Root is also a root's own menu and button), and
    the dock holding this panel shows only Refresh on its title bar (:attr:`title_bar_actions`,
    [[appendices.code-conventions#command-surfaces]]).

    **An edit of the roots is saved at once**, through the catalog; a file newer than this build opens read-only,
    its :attr:`~rehuco_core.RehucoFile.lock_reason` on the banner and every edit off.

    :param catalog: the open catalog, whose roots this shows and edits.
    :param queue: the task queue the checksum verbs are enqueued on.
    :param parent: optional Qt parent.
    :param rename_coordinator: what a folder listing holds each directory read under, so it never blocks a
        rename ([[mounts-and-storage#out-of-band]]).
    :param resource_events: the app's file announcements (#376): a rename moves the rows it moved, and a folder the
        app changed is listed again. ``None`` leaves the view to F5.
    """

    open_requested: Signal = Signal(object)
    """Emitted with a record's absolute :class:`~pathlib.Path` when it is asked to open. Typed as plain
    ``object`` for the reason ``DocumentsDock.open_requested`` is."""

    open_folder_requested: Signal = Signal(object)
    """Emitted with a folder's :class:`~pathlib.Path` when its associated rehu is asked for: the ``info.rehu`` in it,
    or a new one if there is none yet ([[data-model#resource-scoping]]). Typed as plain ``object``, as above."""

    open_companion_requested: Signal = Signal(object)
    """Emitted with a file's :class:`~pathlib.Path` when its associated rehu is asked for: the one that shares its
    name, or a new one if there is none yet."""

    record_selected: Signal = Signal(object)
    """Emitted with the ``(root_id, relative)`` key of the record the current row stands for -- a record itself, a
    folder's ``info.rehu``, a file's same-name ``.rehu``, the ``.tc`` of either when that is all there is -- or
    ``None`` when it has none (#381). Selecting never creates a record. Typed as plain ``object``, as above."""

    filter_requested: Signal = Signal(object, str)
    """Emitted with a :class:`~rehuco_core.CatalogField` and a value when the current browser is to be filtered on
    them -- the folder filter (#398); the window hands it to the Browsers dock."""

    def __init__(  # pylint: disable=too-many-arguments,useless-suppression
        self,
        catalog: RootCatalog,
        queue: TaskQueue,
        parent: QWidget | None = None,
        *,
        rename_coordinator: RenameCoordinator = DEFAULT_RENAME_COORDINATOR,
        resource_events: ResourceEvents | None = None,
    ) -> None:
        super().__init__(parent)
        self.__catalog: Final = catalog
        self.__rename_coordinator: Final = rename_coordinator
        self.__events: Final = resource_events
        self.__listening_to_events = resource_events is not None
        self.__watcher: Final = JobEndWatcher(queue, self)

        self.__roots_model: Final = RootsFolderModel(self)
        self.__target: QPersistentModelIndex | None = None
        """The row a background menu is for while it is open: the folder its column lists. It is not the current row,
        which the menu leaves where it was; every action reads the row it acts on through :meth:`__acting_index`."""
        self.__notice = ""
        """What the last thing asked of a row has to say, on the banner until the selection moves."""
        self.__fallback: tuple[UUID, tuple[str, ...]] | None = None
        """Where the Roots selection goes once the rows it was in are removed: the folder they were in."""
        # connected before the view's selection model exists, so it runs before that model moves the current row to a
        # neighbour of the removed one -- which is the one thing this has to see unmoved
        self.__roots_model.rowsAboutToBeRemoved.connect(self.__on_roots_rows_about_to_be_removed)
        self.__roots_model.rowsRemoved.connect(self.__on_roots_rows_removed)
        # queued: a drop is handled inside the view's own event, and the move changes the rows it is dropping on
        self.__roots_model.root_move_requested.connect(self.__on_root_dropped, Qt.ConnectionType.QueuedConnection)

        self.__roots_ui: Final = Ui_RehucoRootsPanel()
        self.__roots_ui.setupUi(self)
        self.__opening: Final = RootsOpening(
            self.__roots_model, self.__roots_ui, catalog, rename_coordinator, self, self.__show_notice
        )
        self.__verbs: Final = RootsChecksumVerbs(
            self.__roots_model,
            self.__roots_ui,
            queue,
            rename_coordinator,
            self.__watcher,
            self.__announce_rewritten,
            self.__acting_index,
        )
        self.__rows: Final = RootsRowActions(self.__roots_model, self.__roots_ui, self.__opening, self.__verbs, self)
        # the details of the current row, whatever it is, sit beside the columns
        self.__preview: Final = RootsPreview(
            self.__roots_model,
            rename_coordinator,
            self.__rows.buttons,
            self.__rows.folder_record,
            self.__opening.pack_of,
            drag_image=self.__opening.drag_image,
        )
        splitter = self.__roots_ui.roots_splitter
        splitter.addWidget(self.__preview)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([DETAILS_PANE_WIDTH * 2, DETAILS_PANE_WIDTH])
        self.__roots_model.dataChanged.connect(self.__preview.follow)
        self.__roots_model.rowsRemoved.connect(self.__preview.forget_if_gone)
        self.__roots_ui.roots_view.setModel(self.__roots_model)
        self.__roots_ui.roots_view.doubleClicked.connect(self.__on_roots_double_clicked)
        self.__roots_ui.roots_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.__roots_ui.roots_view.customContextMenuRequested.connect(self.__on_roots_context_menu)
        self.__banner: Final = MessageBanner(self)
        self.__roots_ui.main_layout.insertWidget(0, self.__banner)
        # F5 works from any column, since they are all this panel's children
        self.addAction(self.__roots_ui.refresh_roots_action)

        self.__setup_actions()
        # selection_model() is None only before a model is set (setModel just did)
        # a local, not a kept wrapper: the selection model is an object Qt made (#459)
        selection = cast(QItemSelectionModel, self.__roots_ui.roots_view.selectionModel())
        selection.currentChanged.connect(self.__on_roots_current_row_changed)
        for signal in (
            self.__roots_model.rowsInserted,
            self.__roots_model.rowsRemoved,
            self.__roots_model.rowsMoved,
            self.__roots_model.dataChanged,
        ):
            signal.connect(self.__on_roots_current_changed)
        self.__preview.root_name_edit.editingFinished.connect(self.__on_root_name_edited)
        self.__preview.root_storage_combo.activated.connect(self.__on_root_storage_chosen)
        catalog.refreshed.connect(self.__refresh)
        catalog.rehuco_path_changed.connect(self.__update_enablement)
        self.__update_enablement()
        if resource_events is not None:
            resource_events.moved.connect(self.__on_moved)
            resource_events.folder_changed.connect(self.__on_folder_changed)
            resource_events.changed.connect(self.__on_files_changed)

    def detach(self) -> None:
        """Stop listening to the file announcements before the window goes. Safe to call again: the second time
        there is nothing left to disconnect."""
        if self.__events is not None and self.__listening_to_events:
            self.__listening_to_events = False
            self.__events.moved.disconnect(self.__on_moved)
            self.__events.folder_changed.disconnect(self.__on_folder_changed)
            self.__events.changed.disconnect(self.__on_files_changed)
        self.__watcher.detach()

    # region the view and its actions

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
    def title_bar_actions(self) -> list[QAction]:
        """What the dock holding this panel shows on its title bar: Refresh alone. Scan and the root edits are used
        too rarely to stand there; the ``Root Catalog`` menu carries them (#461)."""
        return [self.__roots_ui.refresh_roots_action]

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
    def verify_old_checksums_action(self) -> QAction:
        """Verifies what the selected checksum file's resource has not had checked lately, and records its new files:
        the checksum file's default action."""
        return self.__roots_ui.verify_old_checksums_action

    @property
    def verify_checksums_action(self) -> QAction:
        """Verifies every file of the selected checksum file's resource, whatever its last check was."""
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
    def open_lightbox_action(self) -> QAction:
        """Shows the selected image, or the images of the selected reference pack, in the lightbox (#456)."""
        return self.__roots_ui.open_lightbox_action

    @property
    def lightbox(self) -> RootsLightbox:
        """What opens the lightbox for the Roots view."""
        return self.__opening.lightbox

    @property
    def open_companion_action(self) -> QAction:
        """Opens the rehu that describes the selected folder or file, which is there."""
        return self.__roots_ui.open_companion_action

    @property
    def create_companion_action(self) -> QAction:
        """Starts a new rehu for the selected folder or file, which has none; nothing is written until it is saved."""
        return self.__roots_ui.create_companion_action

    @property
    def verify_record_action(self) -> QAction:
        """Verifies what has not been checked lately of every file the selected row's record manages (#469)."""
        return self.__roots_ui.verify_record_action

    @property
    def generate_record_action(self) -> QAction:
        """Records a checksum for every file the selected row's record manages, where it has no checksum file yet."""
        return self.__roots_ui.generate_record_action

    @property
    def verify_file_action(self) -> QAction:
        """Checks the selected file against its checksum now, whatever its last check was."""
        return self.__roots_ui.verify_file_action

    @property
    def add_file_checksum_action(self) -> QAction:
        """Hashes the selected file, which has no checksum, and records it."""
        return self.__roots_ui.add_file_checksum_action

    @property
    def update_file_checksum_action(self) -> QAction:
        """Hashes the selected file, which no longer matches, and records the result as its checksum."""
        return self.__roots_ui.update_file_checksum_action

    @property
    def filter_folder_action(self) -> QAction:
        """Filters the current browser to the resources under the selected root or folder."""
        return self.__roots_ui.filter_folder_action

    def __refresh(self) -> None:
        """Show the roots the open file lists now, and why it is read-only if it is."""
        file = self.__catalog.file
        if file is None:
            self.__roots_model.set_roots((), None)
        else:
            roots = file.roots
            self.__roots_model.set_roots(
                roots, RootFolderLister(roots, coordinator=self.__rename_coordinator, trust=DEFAULT_CHECKSUM_TRUST)
            )
        self.__show_banner()
        self.__update_enablement()

    def __show_banner(self) -> None:
        """Show on the banner why the open file is read-only, if it is, and the notice of the last action."""
        file = self.__catalog.file
        lock_reason = None if file is None else file.lock_reason
        rows = [] if lock_reason is None else [MessageBannerRow(MessageBannerSeverity.WARNING, lock_reason.message)]
        if self.__notice:
            rows.append(MessageBannerRow(MessageBannerSeverity.WARNING, self.__notice))
        self.__banner.set_rows(rows)

    def __show_notice(self, notice: str) -> None:
        """Say something about what was just asked of a row, until the selection moves.

        :param notice: the sentence; empty to take it down.
        """
        self.__notice = notice
        self.__show_banner()

    def __setup_actions(self) -> None:
        """Give every action its themed icon and connect it."""
        ui = self.__roots_ui
        for action, icon in (
            (ui.scan_action, SCAN_ICON),
            (ui.add_root_action, ADD_ROOT_ICON),
            (ui.remove_root_action, REMOVE_ROOT_ICON),
            (ui.refresh_roots_action, REFRESH_ROOTS_ICON),
            (ui.move_to_top_action, MOVE_TO_TOP_ICON),
            (ui.move_up_action, MOVE_UP_ICON),
            (ui.move_down_action, MOVE_DOWN_ICON),
            (ui.move_to_bottom_action, MOVE_TO_BOTTOM_ICON),
        ):
            ActionIconThemeHandler(action, icon)
        ui.scan_action.triggered.connect(self.__catalog.scan)
        ui.add_root_action.triggered.connect(self.__on_add_root)
        ui.remove_root_action.triggered.connect(self.__on_remove_root)
        ui.refresh_roots_action.triggered.connect(self.__on_refresh_roots)
        ui.filter_folder_action.triggered.connect(self.__on_filter_folder)
        ui.open_record_action.triggered.connect(self.__on_open_record)
        ui.open_explorer_action.triggered.connect(self.__on_open_explorer)
        ui.open_file_action.triggered.connect(self.__on_open_file)
        ui.open_lightbox_action.triggered.connect(self.__on_open_lightbox)
        ui.open_companion_action.triggered.connect(self.__on_companion)
        ui.create_companion_action.triggered.connect(self.__on_companion)
        for action, move in (
            (ui.move_to_top_action, RehucoFile.move_to_top),
            (ui.move_up_action, RehucoFile.move_up),
            (ui.move_down_action, RehucoFile.move_down),
            (ui.move_to_bottom_action, RehucoFile.move_to_bottom),
        ):
            action.triggered.connect(lambda _checked=False, move=move: self.__move_root(move))

    def __update_enablement(self, *_args: object) -> None:
        """Enable Scan while a file is open, and the root edits only while it can also be saved -- Remove and the moves
        needing a selected **root row** besides, the moves not at the end they move towards. Refresh and the folder
        filter need a catalog, the filter a root or folder to name."""
        is_open = self.__catalog.file is not None
        editable = self.__catalog.editable
        ui = self.__roots_ui
        current = self.__acting_index()
        row = current.row() if self.__roots_model.root_at(current) is not None else -1
        last = self.__roots_model.rowCount() - 1
        self.__preview.set_editable(editable)
        self.__roots_model.set_reorderable(editable)
        ui.scan_action.setEnabled(is_open)
        ui.add_root_action.setEnabled(editable)
        ui.remove_root_action.setEnabled(editable and row >= 0)
        ui.refresh_roots_action.setEnabled(is_open)
        ui.move_to_top_action.setEnabled(editable and row > 0)
        ui.move_up_action.setEnabled(editable and row > 0)
        ui.move_down_action.setEnabled(editable and 0 <= row < last)
        ui.move_to_bottom_action.setEnabled(editable and 0 <= row < last)
        ui.filter_folder_action.setEnabled(
            is_open and self.__roots_model.node_kind(current) in (RootsNodeKind.ROOT, RootsNodeKind.FOLDER)
        )

    def __on_moved(self, relocation: Relocation) -> None:
        """Move the rows a rename moved, wherever the view has them listed (#376).

        :param relocation: the rename's executed plan.
        """
        if self.__catalog.file is not None and relocation.pairs:
            self.__roots_model.relocate(relocation)

    # endregion

    # region the Roots view

    def __on_roots_current_row_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        """List the folder that became current if nobody has yet, whether or not the view is on screen to ask, and
        bring the actions and the card in line.

        :param current: the new current row.
        :param _previous: the row that was current.
        """
        self.__roots_model.fetchMore(current)
        if self.__notice:
            self.__show_notice("")
        self.__preview.show_index(current)
        self.__on_roots_current_changed()
        self.record_selected.emit(selected_record(self.__roots_model, current))

    def __on_roots_current_changed(self, *_args: object) -> None:
        """Bring the actions in line with the current row, whatever changed it."""
        self.__update_enablement()

    def __acting_index(self) -> QModelIndex:
        """The row the actions act on: the one a background menu is open for, else the current row.

        :returns: its index.
        """
        target = self.__target
        if target is not None and target.isValid():
            return target.model().index(target.row(), target.column(), target.parent())
        return self.__roots_ui.roots_view.currentIndex()

    def __current_root_row(self) -> int:
        """The row the actions act on, if it is a root row.

        :returns: its row, which is also its place in the file; ``-1`` for a folder, a file, or none.
        """
        current = self.__acting_index()
        return current.row() if self.__roots_model.root_at(current) is not None else -1

    def __on_root_name_edited(self) -> None:
        """Rename the current root to what was typed in the details pane, as its label; nothing on disk changes.

        An empty name, or one another root already has, is refused with a warning and the field goes back to the
        label the root has.
        """
        file, row = self.__catalog.file, self.__current_root_row()
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
        file, row = self.__catalog.file, self.__current_root_row()
        if file is None or file.lock_reason is not None or row < 0:
            return
        storage = selected_root_storage(self.__preview.root_storage_combo)
        if file.roots[row].storage is storage:
            return
        file.set_storage(row, storage)
        self.__commit_root_edit()

    def __commit_root_edit(self) -> None:
        """Save an edit of a root, bring the cache's copy of it in line, and show it."""
        self.__commit()
        self.__preview.refresh()

    def __move_root(self, move: Callable[[RehucoFile, int], int]) -> None:
        """Move the current root with one of the file's ordering operations, and keep it current.

        :param move: the :class:`~rehuco_core.RehucoFile` operation; takes the row and returns where it ended up.
        """
        file, row = self.__catalog.file, self.__current_root_row()
        if file is None or file.lock_reason is not None or row < 0:
            return
        root_id = file.roots[row].root_id
        if move(file, row) == row:
            return
        self.__commit()
        self.__roots_ui.roots_view.setCurrentIndex(self.__roots_model.index_for(root_id, ()))

    def __on_root_dropped(self, root_id: UUID, to: int) -> None:
        """Move a root that was dragged to its new place: the file is reordered, saved and shown, as the move buttons
        do, and the root stays current.

        :param root_id: the root dropped.
        :param to: the row it should end up at.
        """
        file = self.__catalog.file
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
        """Run a row's default action (:meth:`RootsRowActions.default_action`); a root has none, and only navigates.

        **Ctrl+Alt** held hands an image or an archive to the system's application instead (#456); Ctrl or Shift alone
        belong to the lightbox's choice of surface.

        :param index: the row.
        """
        if self.__opening.external_requested(index):
            self.__run(self.__roots_ui.open_file_action, index)
            return
        self.__run(self.__rows.default_action(index), index)

    def __on_open_record(self) -> None:
        """Open the current row's record in Documents."""
        self.__run(self.__roots_ui.open_record_action, self.__acting_index())

    def __on_open_file(self) -> None:
        """Open the current row's file with the application the system associates with it."""
        self.__run(self.__roots_ui.open_file_action, self.__acting_index())

    def __on_open_lightbox(self) -> None:
        """Show the current row's images in the lightbox."""
        self.__run(self.__roots_ui.open_lightbox_action, self.__acting_index())

    def __on_open_explorer(self) -> None:
        """Show the current row in the system file manager: a folder opened, a file shown selected in its folder."""
        self.__run(self.__roots_ui.open_explorer_action, self.__acting_index())

    def __announce_rewritten(self, resource: Path) -> None:
        """Say the checksum record a finished run may have rewritten has changed, so every view of it follows -- the
        rows here, an open document's Files and Checksums views, the catalog's row for the record (#457).

        :param resource: the ``.rehu`` whose record was verified or generated.
        """
        record = checksum_record_path(resource)
        if self.__events is not None:
            self.__events.announce_changed((record,))
        else:
            self.__roots_model.relist_under(record.parent)

    def __on_companion(self) -> None:
        """Ask for the rehu that describes the current folder or file: a folder's ``info.rehu``, a file's same-name
        ``.rehu``. The main window opens the one there is or starts a new, unsaved one, which is why opening and
        creating ask the same question; which of them the menu offered is only a matter of what is on disk."""
        index = self.__acting_index()
        self.__run(self.__rows.companion_action(index), index)

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
        elif action in (ui.verify_old_checksums_action, ui.verify_checksums_action):
            if action.isEnabled():
                action.trigger()
        elif action is ui.open_explorer_action:
            reveal_in_file_browser(path)
        elif action is ui.open_file_action:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        elif action is ui.open_lightbox_action:
            self.__opening.open(index, path)
        elif self.__roots_model.node_kind(index) is RootsNodeKind.FOLDER:
            self.open_folder_requested.emit(path)
        else:
            self.open_companion_requested.emit(path)

    def __on_folder_changed(self, directory: Path) -> None:
        """List a folder again that the app changed the contents of, if the Roots view has it loaded.

        :param directory: the folder.
        """
        self.__roots_model.relist_folder(directory)

    def reselect(self) -> None:
        """Say again which record the current row stands for, for a listener that has just started to care (#457)."""
        self.record_selected.emit(selected_record(self.__roots_model, self.__roots_ui.roots_view.currentIndex()))

    def __on_files_changed(self, paths: tuple[Path, ...]) -> None:
        """List again the folders whose checksum record the app rewrote, if the Roots view has them loaded (#457).

        A directory-scoped record covers its subfolders too, so every loaded folder at or under it is listed again;
        a file-scoped one only changes its own folder, which is the same call.

        :param paths: the files the app wrote or replaced.
        """
        for path in paths:
            if path.suffix.lower() == CHECKSUM_RECORD_SUFFIX:
                self.__roots_model.relist_under(path.parent)

    def __on_filter_folder(self) -> None:
        """Filter the current browser to the resources under the current root or folder (#398)."""
        model = self.__roots_model
        current = self.__acting_index()
        root, key = model.root_of(current), model.key(current)
        if root is None or key is None or model.node_kind(current) not in (RootsNodeKind.ROOT, RootsNodeKind.FOLDER):
            return
        self.filter_requested.emit(CatalogField.FOLDER, "/".join((root.label, *key[1])))

    def roots_context_actions(self, index: QModelIndex) -> list[QAction]:
        """What the Roots view's context menu holds for a row (#469): see :meth:`RootsRowActions.context_actions`.

        :param index: the row the menu is for.
        :returns: the actions in menu order, a separator among them where the groups change.
        """
        return self.__rows.context_actions(index)

    def __on_roots_context_menu(self, position: QPoint) -> None:
        """Open the Roots view's context menu on the row under the pointer, making it the current row first so the
        actions act on it. **On the empty part of a column** it opens the menu of the folder that column lists, as a
        file manager does for a folder's background, and the selection stays where it was (#469); on the column of
        roots that is Scan, Add Root and Refresh.

        :param position: where it was asked for, in the view's coordinates.
        """
        view = self.__roots_ui.roots_view
        global_position = view.mapToGlobal(position)
        index = view.index_at_global(global_position)
        if index.isValid():
            actions = self.roots_context_actions(index)
            if actions:
                view.setCurrentIndex(index)
                self.__exec_menu(actions, global_position, None)
            return
        holder = view.column_root_at_global(global_position)
        if holder is None:
            return
        if holder.isValid():
            self.__exec_menu(self.roots_context_actions(holder), global_position, QPersistentModelIndex(holder))
        else:
            ui = self.__roots_ui
            self.__exec_menu([ui.scan_action, ui.add_root_action, ui.refresh_roots_action], global_position, None)

    def __exec_menu(self, actions: list[QAction], position: QPoint, target: QPersistentModelIndex | None) -> None:
        """Show a menu of actions at a point and run what is chosen.

        :param actions: its entries.
        :param position: where, in global coordinates.
        :param target: the row the actions act on while it is open, when it is not the current one. The shared actions
            are then put back for the current row, which the details pane's buttons mirror.
        """
        self.__target = target
        try:
            self.__update_enablement()
            menu = QMenu(self)
            menu.addActions(actions)
            try:
                menu.exec(position)
            finally:
                menu.deleteLater()
        finally:
            if target is not None:
                self.__target = None
                self.__update_enablement()
                self.__preview.refresh()

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
        file = self.__catalog.file
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
        self.__commit()
        self.__roots_ui.roots_view.setCurrentIndex(self.__roots_model.index_for(root_id, ()))

    def __on_remove_root(self) -> None:
        """Remove the current root from the file, once confirmed, saving it at once, and its rows from the cache on
        the queue."""
        file = self.__catalog.file
        if file is None or file.lock_reason is not None:
            return
        row = self.__current_root_row()
        if row < 0:
            return
        root = file.roots[row]
        if not self.confirm_remove_root(root, self.__catalog.resource_count(root)):
            return
        if not self.__catalog.remove_root(row):
            self.__warn_unsaved()

    def __commit(self) -> None:
        """Save an edit of the roots through the catalog, which shows it; say so if it could not be saved."""
        if not self.__catalog.commit_roots():
            self.__warn_unsaved()

    def __warn_unsaved(self) -> None:
        """Say an edit of the roots could not be saved, and why; the catalog has already put the file back."""
        QMessageBox.warning(self, "Save Root Catalog", self.__catalog.save_error)

    # endregion
