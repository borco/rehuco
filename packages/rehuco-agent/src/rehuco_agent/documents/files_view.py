"""One resource's own folder, browsable ([[plugins#files-subdock]], #266).

The record says what a resource *is*; this says what is actually in its folder -- which is where the
app's own renames, conversions and drops land, and the one thing none of the other inspection docks can
show. A reader who has just converted a resource, curated its screenshots or dropped an image on it can
read the result here without leaving the document.

**Confined to the resource's own folder.** The root is the record's directory and there is no way above
it: the ``..`` row and the up action both stop there. Going up would leave the resource entirely, and a
general file manager is not what this is -- the sibling folder a reader wants is reached by opening that
resource, which is what the foreign-record rows are for.

**What a row lets you do is decided by what the file is to this resource** -- the kinds
:mod:`rehuco_core.rehu_file_kinds` names, turned into an enabled state by
:data:`~rehuco_agent.documents.files_rows.INTERACTIVE_KINDS`. A disabled row cannot be activated at all,
because it answers :data:`~PySide6.QtCore.Qt.ItemFlag.NoItemFlags`; the four things a double-click *can*
do are each routed out of here rather than done here:

- **a folder** -- walked into, unless a foreign ``info.rehu`` in this listing says the folders beside it
  are that resource's (#254), in which case its own row is the way in;
- **another resource's record** -- opened, or focused if it is already open, through
  :attr:`record_activated`;
- **this resource's checksum record** -- a *Verify All* over this resource, through the callable the
  document hands in;
- **an image** -- opened maximized through :attr:`images_activated`, against **every image in the
  folder**, curated or not: this is a view of the folder, not of the lightbox's set, and a screenshot
  someone curated out is exactly the one they may want to look at here.

Anything else is handed to the system's default handler, which is the only sensible thing to do with a
video or a PDF and the one route that does not involve this app pretending to open it.

**It refreshes when shown, and on demand -- never in between.** The dock starts hidden, and a listing is
a filesystem round trip on a share ([[packaging-deployment#ts230-as-nas]]), so a document that is open
but whose folder nobody is looking at costs nothing. Deliberately **not** a ``QFileSystemModel``: that
model installs a watcher which holds handles open on Windows, and a held handle is exactly what makes a
rename or a delete of the resource's own files fail -- the app would be locking what it is about to move.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Final, override

from borco_pyside.theming import ActionIconThemeHandler
from PySide6.QtCore import QModelIndex, QPersistentModelIndex, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QShowEvent
from PySide6.QtWidgets import QHeaderView, QToolBar, QWidget
from rehuco_core import IMAGE_EXTENSIONS, FileKind

from ..settings.checksum_settings import shared_checksum_settings
from ..settings.excluded_files_settings import shared_excluded_files_settings
from ..settings.screenshot_patterns_settings import shared_screenshot_patterns_settings
from .files_row_delegate import CHECKSUM_COLUMN_WIDTH, FilesRowDelegate
from .files_rows import (
    CHECKSUM_COLUMN,
    KIND_COLUMN,
    MODIFIED_COLUMN,
    NAME_COLUMN,
    SIZE_COLUMN,
    FileRow,
    FilesRows,
    FilesRowsLoader,
    FilesRowsReader,
    FilesSortProxy,
    FilesTableModel,
)
from .files_view_ui import Ui_FilesView
from .rehu_document_model import RehuDocumentModel

REFRESH_ICON_RESOURCE: Final = ":/icons/refresh.svg"
UP_ICON_RESOURCE: Final = ":/icons/file_browser_folder.svg"
"""The up action wears the folder glyph: it is *go to that folder*, and the browser has no second
drawing of a folder for it to be confused with."""

LOADING_SUMMARY: Final = "Reading…"
"""What the summary line says while the listing is out.

A folder on an SMB mount ([[packaging-deployment#ts230-as-nas]]) is not an instant answer, and a blank
line for that whole time is indistinguishable from an empty folder."""

UNREACHABLE_SUMMARY: Final = "This folder is not reachable right now."
"""What the summary line says instead of drawing an empty table over an away mount (#245)."""

NO_PATH_SUMMARY: Final = "This document has not been saved yet, so it has no folder to show."
"""What the summary line says for a never-saved document -- there is nowhere to list."""

UNREADABLE_RECORD_SUMMARY: Final = "The checksum record could not be read: {error}"
"""What the summary line says for a ``.checksum`` this build cannot parse.

The folder is still listed underneath it -- it is still the folder -- with every checksum cell empty,
which is honest: this build knows nothing about any of them."""

OTHER_RESOURCE_SUMMARY: Final = "The folders here belong to “{record}”; open it to browse them."
"""What the summary line says where a foreign ``info.rehu`` covers this directory (#254).

The subdirectory rows are greyed, and a greyed row with no reason given reads as a bug; this names the
record that owns them and the one thing to do about it, which is the row right there."""

TALLY_SUMMARY: Final = "{folders} folder{folders_plural}, {files} file{files_plural}"
"""The ordinary summary: how much is in this folder."""


# the members are this surface's parts -- the model, the proxy, the loader, the document, the verify it
# was handed, the folder it is showing and the stale bit -- and collapsing any of them into a bag would
# only move the count, the same reason `ChecksumView` carries this disable
# pylint: disable-next=too-many-instance-attributes
class FilesView(QWidget):
    """The resource's folder as a table, with its toolbar (#266).

    A pure view over the filesystem: it lists and redraws, and every activation is routed to whoever
    owns the answer -- the document (a verify, a lightbox) or the window (opening another resource).
    Nothing here writes, deletes or renames anything.

    **Refreshed at four seams**: being shown, ``F5``, the refresh button, and the two things that change
    what it is a view *of* -- this document's path moving (a convert, a completed rename) and one of its
    checksum runs finishing, which is the only way the checksum column can change without the folder
    changing. Not on a timer and not on a watcher, for the reasons the module docstring gives.

    :param model: the document whose folder this shows.
    :param parent: optional Qt parent.
    :param verify: what the checksum record's row calls -- this document's *Verify All*, or ``None``
        where the document has no queue to put a run on, which also greys that row's activation.
    """

    record_activated: Signal = Signal(object)
    """Emitted with the :class:`~pathlib.Path` of another resource's record the reader double-clicked.

    Relayed up to ``MainWindow``, which opens it the same way every other open goes -- resolved,
    revealed, and remembered in ``Open recents`` -- rather than this dock reaching sideways into the
    documents area. Typed as plain ``object`` for the marshalling reason ``DocumentsDock`` documents."""

    images_activated: Signal = Signal(object, object)
    """Emitted ``(images, clicked)`` when an image row is double-clicked: every image in the browsed
    folder in row order, and the one to open first.

    The document decides where a maximized image opens (#160), so this reports rather than opens -- the
    same owner-routed activation the viewer's own strip uses, with a different set: **the folder's**,
    curation ignored."""

    def __init__(
        self, model: RehuDocumentModel, parent: QWidget | None = None, verify: Callable[[], None] | None = None
    ) -> None:
        super().__init__(parent)
        self.__model: Final = model
        self.__verify: Final = verify
        self.__stale = True
        self.__directory: Path | None = None
        """The folder currently browsed, or ``None`` before the first read has been set up -- reset to
        the root whenever the document's path moves."""

        self.__ui: Final = Ui_FilesView()
        self.__ui.setupUi(self)
        self.__rows: Final = FilesTableModel(self)
        self.__proxy: Final = FilesSortProxy(self)
        self.__proxy.setSourceModel(self.__rows)
        self.__ui.file_view.setModel(self.__proxy)
        self.__ui.file_view.setItemDelegate(FilesRowDelegate(self))
        self.__ui.file_view.sortByColumn(NAME_COLUMN, Qt.SortOrder.AscendingOrder)
        # the **Name** column takes whatever the others leave, and the header's own
        # stretch-last-section is off (in the `.ui`) so it does not compete for it: with both on, the
        # spare width went to Modified and a long filename was elided in a half-empty dock
        header = self.__ui.file_view.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(NAME_COLUMN, QHeaderView.ResizeMode.Stretch)
        for column in (CHECKSUM_COLUMN, KIND_COLUMN, SIZE_COLUMN, MODIFIED_COLUMN):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setMinimumSectionSize(CHECKSUM_COLUMN_WIDTH)
        self.__loader: Final = FilesRowsLoader(self)
        self.__loader.loaded.connect(self.__show)

        self.__setup_toolbar()
        self.__ui.file_view.doubleClicked.connect(self.__on_double_clicked)
        model.path_changed.connect(self.__on_path_changed)  # type: ignore[attr-defined]
        self.__reset_to_root()

    # region Reading

    def refresh(self, *_args: object) -> None:
        """Read the browsed folder again, off the GUI thread.

        **A hidden dock reads nothing**, the discipline every other inspection surface keeps (#111): a
        refresh asked for while hidden only flags the table stale, and :meth:`showEvent` catches it up.

        :param _args: whatever value the triggering signal carried; unused -- the folder and the
            document's path are always re-read from here.
        """
        if not self.isVisible():
            self.__stale = True
            return
        self.__stale = False
        path = self.__model.path
        directory = self.__directory
        if path is None or directory is None:
            self.__rows.set_rows(())
            self.__ui.path_label.setText("")
            self.__ui.summary_label.setText(NO_PATH_SUMMARY)
            self.__ui.up_action.setEnabled(False)
            return
        self.__ui.summary_label.setText(LOADING_SUMMARY)
        reader = FilesRowsReader(
            path,
            shared_excluded_files_settings().excluded_file_patterns,
            shared_screenshot_patterns_settings().screenshot_name_patterns,
            shared_checksum_settings().stale_after,
        )
        self.__loader.start(reader, directory)

    @override
    def showEvent(self, event: QShowEvent) -> None:
        """Catch up a read deferred while hidden -- the dock being opened, or its tab switched back to.

        :param event: the Qt show event, forwarded to the base class.
        """
        super().showEvent(event)
        if self.__stale:
            self.refresh()

    def __show(self, rows: FilesRows) -> None:
        """Draw what the read came back with.

        :param rows: what the read established.
        """
        self.__directory = rows.directory
        self.__rows.set_rows(rows.rows)
        self.__ui.path_label.setText(self.__relative_label(rows.directory))
        self.__ui.summary_label.setText(FilesView.__summary(rows))
        self.__ui.up_action.setEnabled(not rows.at_root)

    def __relative_label(self, directory: Path) -> str:
        """Where the reader is, spelled from the resource's own folder.

        The absolute path is on every row's tooltip; what a reader browsing needs above the table is how
        deep they have walked, and a full path would only be the resource's whole location repeated.

        :param directory: the folder being shown.
        :returns: the resource's own name at the root, else the path under it.
        """
        path = self.__model.path
        if path is None:
            return ""
        root = path.parent
        if directory == root:
            return root.name
        return f"{root.name}/{directory.relative_to(root).as_posix()}"

    @staticmethod
    def __summary(rows: FilesRows) -> str:
        """The line under the table: what is wrong, or how much is here.

        :param rows: what the read established.
        :returns: the summary line.
        """
        if not rows.reachable:
            return UNREACHABLE_SUMMARY
        if rows.record_error:
            return UNREADABLE_RECORD_SUMMARY.format(error=rows.record_error)
        folders = sum(1 for row in rows.rows if row.is_directory) - (0 if rows.at_root else 1)
        files = len(rows.rows) - folders - (0 if rows.at_root else 1)
        tally = TALLY_SUMMARY.format(
            folders=folders,
            folders_plural="" if folders == 1 else "s",
            files=files,
            files_plural="" if files == 1 else "s",
        )
        if rows.subdirectories_navigable or not folders:
            # nothing to explain where there are no folders to refuse
            return tally
        return f"{tally}. {OTHER_RESOURCE_SUMMARY.format(record=rows.foreign_record)}"

    # endregion

    # region Navigating and activating

    def __reset_to_root(self) -> None:
        """Point the browser back at the resource's own folder, and read it.

        What the first read starts from, and where a path change lands: a rename or a convert moves the
        folder this is a view of, so a subdirectory of the old one is not somewhere to stay.
        """
        path = self.__model.path
        self.__directory = None if path is None else path.parent
        self.refresh()

    def __on_path_changed(self, _path: Path | None) -> None:
        """Re-scope to the new folder when the document's path moves (#52's landmine, for a folder).

        :param _path: the model's new path; unused -- :meth:`__reset_to_root` re-reads it, and the
            folder is its parent either way.
        """
        self.__reset_to_root()

    def __on_double_clicked(self, index: QModelIndex | QPersistentModelIndex) -> None:
        """Act on the row the reader double-clicked, by what it is.

        A disabled row never arrives here -- it answers ``NoItemFlags``, so the view will not activate
        it -- which is why there is no guard for one: the refusal lives in the model, once, rather than
        as a check in each branch below.

        :param index: the activated *proxy* index.
        """
        row = index.data(FilesTableModel.ROW_ROLE)
        if not isinstance(row, FileRow):
            return
        if row.is_directory:
            self.__directory = row.path
            self.refresh()
        elif row.kind is FileKind.FOREIGN_RECORD:
            self.record_activated.emit(row.path)
        elif row.kind is FileKind.OWN_MANIFEST:
            if self.__verify is not None:
                self.__verify()
        elif row.path.suffix.lower() in IMAGE_EXTENSIONS:
            self.images_activated.emit(self.__folder_images(), row.path)
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(row.path))

    def __folder_images(self) -> list[Path]:
        """Every image in the browsed folder, in the order the table draws them.

        **Curation is ignored on purpose** ([[data-model#image-meanings]]): the lightbox's own set is the
        checked screenshots, and this is a view of the folder -- a screenshot someone curated out, and a
        neighbour's, are both here and both worth looking at from here.

        :returns: the image paths, in row order.
        """
        images: list[Path] = []
        for position in range(self.__proxy.rowCount()):
            row = self.__proxy.index(position, NAME_COLUMN).data(FilesTableModel.ROW_ROLE)
            if isinstance(row, FileRow) and not row.is_directory and row.path.suffix.lower() in IMAGE_EXTENSIONS:
                images.append(row.path)
        return images

    def __on_up_triggered(self) -> None:
        """Walk out of the browsed folder -- the ``..`` row's act, on a button.

        Refuses at the root, where the action is disabled anyway; this only guards a stale trigger.
        """
        path = self.__model.path
        directory = self.__directory
        if path is None or directory is None or directory == path.parent:
            return
        self.__directory = directory.parent
        self.refresh()

    # endregion

    # region This dock's own actions

    def __setup_toolbar(self) -> None:
        """Put the two navigation actions on the dock's own toolbar."""
        ui = self.__ui
        for action, icon in ((ui.up_action, UP_ICON_RESOURCE), (ui.refresh_action, REFRESH_ICON_RESOURCE)):
            ActionIconThemeHandler(action, icon)
        # scoped to this widget's own subtree, not the window: every open document has a browser of its
        # own, and a WindowShortcut would make two of them ambiguous on one key -- firing neither, the
        # trap `DocumentWidget`'s save action documents
        ui.refresh_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.addAction(ui.refresh_action)
        ui.refresh_action.triggered.connect(self.refresh)
        ui.up_action.triggered.connect(self.__on_up_triggered)
        ui.up_action.setEnabled(False)

        toolbar = QToolBar(self)
        toolbar.addAction(ui.up_action)
        toolbar.addAction(ui.refresh_action)
        ui.main_layout.insertWidget(0, toolbar)

    @property
    def refresh_action(self) -> QAction:
        """Reads this folder again; also bound to ``F5`` while the browser has focus."""
        return self.__ui.refresh_action

    @property
    def up_action(self) -> QAction:
        """Goes to the folder above. Disabled at the resource's own folder, which is as far up as this
        browser goes."""
        return self.__ui.up_action

    @property
    def directory(self) -> Path | None:
        """The folder currently browsed, or ``None`` for a document with no path yet."""
        return self.__directory

    @property
    def proxy(self) -> FilesSortProxy:
        """The sorting proxy the table draws through -- what a caller reads rows in view order from."""
        return self.__proxy

    @property
    def summary(self) -> str:
        """The line under the table -- how much is here, or why there is nothing."""
        return self.__ui.summary_label.text()

    @property
    def path_label(self) -> str:
        """The line above the table -- how deep into the resource's folder the reader has walked."""
        return self.__ui.path_label.text()

    def activate(self, row: int) -> None:
        """Act on a *view* row as a double-click would, for a caller outside this widget.

        :param row: the row number as drawn, which is what a reader clicks and therefore the only
            numbering anything outside this widget has business speaking in.
        """
        index = self.__proxy.index(row, NAME_COLUMN)
        if self.__proxy.flags(index) & Qt.ItemFlag.ItemIsEnabled:
            self.__on_double_clicked(index)

    # endregion
