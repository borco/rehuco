"""One resource's checksums, per file ([[data-model#checksums]], #244).

#203 records which hash was used per content file, when it was last checked and what the answer was,
and #204 runs the checks -- but a verify over a tutorial of two hundred videos reports three mismatches
into a log line, and deciding which of them is a legitimate repack and accepting *just that one* is the
loop #203's targeted generate was built for. This is the surface that loop needs: the files, their
answers, and a selection.

**The toolbar only checks; changing the record needs a selection.** That is the rule the two menus
encode, and it is what makes the toolbar safe to click -- nothing reachable from it can overwrite a hash
or drop an entry. *Verify Old* and *Verify All* are the whole of it; *Generate Selection* and *Delete
Missing* live in the context menu, behind a selection that is itself the deliberate act.

**Every action is greyed while the resource is unreachable**, decided at the enumeration rather than
from the rows: the record lives beside the files and shares their fate, so a mount that is away makes
the ``.checksum`` as unreachable as the content it describes (#245). Showing an empty table over an
offline mount would look exactly like a resource with no files, which is the one thing this must not
say.
"""

from collections.abc import Sequence
from typing import Final, cast, override

from borco_pyside.theming import ActionIconThemeHandler
from PySide6.QtCore import QItemSelectionModel, QPoint
from PySide6.QtGui import QAction, QShowEvent
from PySide6.QtWidgets import QMenu, QToolBar, QWidget

from ..settings.excluded_files_settings import shared_excluded_files_settings
from .checksum_actions import GENERATE_ICON_RESOURCE, VERIFY_ICON_RESOURCE, ChecksumActions
from .checksum_rows import (
    MISSING_STATUS,
    PATH_COLUMN,
    ChecksumRows,
    ChecksumRowsLoader,
    ChecksumSortProxy,
    ChecksumTableModel,
    tally_rows,
    tally_text,
)
from .checksum_view_ui import Ui_ChecksumView
from .rehu_document_model import RehuDocumentModel

DELETE_ICON_RESOURCE: Final = ":/icons/items_delete.svg"

LOADING_SUMMARY: Final = "Reading…"
"""What the summary line says while the walk is out.

A resource of thousands of files on an SMB mount ([[packaging-deployment#ts230-as-nas]]) is not an
instant answer, and a blank line for that whole time is indistinguishable from an empty resource."""

UNREACHABLE_SUMMARY: Final = "This resource is not reachable right now."
"""What the summary line says instead of drawing an empty table over an away mount (#245, #244)."""

UNREADABLE_RECORD_SUMMARY: Final = "The checksum record could not be read: {error}"
"""What the summary line says for a ``.checksum`` this build cannot parse.

The content files are still listed underneath it -- they were enumerated, and what could be read is
worth showing -- but every status is empty, which is honest: this build knows nothing about them."""

NO_PATH_SUMMARY: Final = "This document has not been saved yet, so it has no files to check."
"""What the summary line says for a never-saved document -- there is nothing on disk to enumerate."""


# the members are this surface's parts -- the model, the proxy, the selection, the loader, the two
# collaborators and the reachability bit -- and collapsing any of them into a bag would only move
# the count, the same reason ChecksumActions carries this disable
# pylint: disable-next=too-many-instance-attributes
class ChecksumView(QWidget):
    """The per-file checksum table, its toolbar and its context menu (#244).

    A pure view over the record: it re-reads and redraws, and every action calls into
    :class:`~rehuco_agent.documents.checksum_actions.ChecksumActions`, which enqueues. Nothing here
    hashes, and nothing here guesses at what a run will do -- the table is refreshed once the run has
    actually written.

    **Refreshed at the three seams that change the record**: one of this document's own jobs finishing,
    a forget, and a rename (the model re-syncs its path, #241). Not on a timer and not on every queue
    movement -- a re-read is a directory walk, and one per progress report would put a walk on the mount
    every 100 MB. **And never while hidden**, which this dock is by default: the read is deferred to
    the next :meth:`showEvent`, so opening a document costs nothing until the table is asked for.

    :param model: the document whose record this shows.
    :param actions: the document's checksum actions, whose two checking actions this shares.
    :param parent: optional Qt parent.
    """

    def __init__(self, model: RehuDocumentModel, actions: ChecksumActions, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__model: Final = model
        self.__actions: Final = actions
        self.__reachable = True
        self.__stale = True

        self.__ui: Final = Ui_ChecksumView()
        self.__ui.setupUi(self)
        self.__rows: Final = ChecksumTableModel(self)
        self.__proxy: Final = ChecksumSortProxy(self)
        self.__proxy.setSourceModel(self.__rows)
        self.__ui.file_view.setModel(self.__proxy)
        # selectionModel() is None only before a model is set (setModel just did)
        self.__selection: Final = cast(QItemSelectionModel, self.__ui.file_view.selectionModel())

        self.__loader: Final = ChecksumRowsLoader(self)
        self.__loader.loaded.connect(self.__show)

        self.__setup_toolbar()
        self.__setup_context_menu()
        self.__selection.selectionChanged.connect(self.__update_enablement)
        actions.record_changed.connect(self.refresh)
        model.path_changed.connect(self.refresh)  # type: ignore[attr-defined]
        self.refresh()

    # region Reading

    def refresh(self, *_args: object) -> None:
        """Re-read the record and the content enumeration, off the GUI thread.

        **A hidden dock reads nothing**, the discipline the other inspection surfaces already keep
        (#111): this dock starts closed, a read is a directory walk over an SMB mount
        ([[packaging-deployment#ts230-as-nas]]), and walking every opened document's whole tree for a
        table nobody is looking at is a cost paid for nothing. A refresh asked for while hidden only
        flags the table stale, and :meth:`showEvent` catches it up.

        :param _args: whatever value the triggering notify signal carried; unused -- the path is always
            re-read from the model.
        """
        if not self.isVisible():
            self.__stale = True
            return
        self.__stale = False
        path = self.__model.path
        if path is None:
            self.__reachable = False
            self.__rows.set_rows(())
            self.__ui.summary_label.setText(NO_PATH_SUMMARY)
            self.__update_enablement()
            return
        self.__ui.summary_label.setText(LOADING_SUMMARY)
        self.__loader.start(path, shared_excluded_files_settings().excluded_file_patterns)

    @override
    def showEvent(self, event: QShowEvent) -> None:
        """Catch up a read deferred while hidden -- the dock being opened, or its tab switched back to.

        :param event: the Qt show event, forwarded to the base class.
        """
        super().showEvent(event)
        if self.__stale:
            self.refresh()

    def __show(self, rows: ChecksumRows) -> None:
        """Draw what the read came back with.

        :param rows: what the read established.
        """
        self.__reachable = rows.reachable
        self.__rows.set_rows(rows.rows)
        self.__ui.summary_label.setText(ChecksumView.__summary(rows))
        self.__update_enablement()

    @staticmethod
    def __summary(rows: ChecksumRows) -> str:
        """The line under the table: what is wrong, or how many of what.

        :param rows: what the read established.
        :returns: the summary line.
        """
        if not rows.reachable:
            return UNREACHABLE_SUMMARY
        if rows.error:
            return UNREADABLE_RECORD_SUMMARY.format(error=rows.error)
        return tally_text(tally_rows(rows.rows))

    # endregion

    # region Toolbar and context menu

    def __setup_toolbar(self) -> None:
        """Put the two checking actions on the dock's own toolbar.

        The very same ``QAction`` objects the document toolbar carries -- Qt allows one action in
        several widgets -- so the two surfaces cannot drift apart, because there is nothing to keep in
        step (#244).

        Generate rides along for the same reason it is on the document toolbar: it is visible **only**
        while the resource has no record, where there is no recorded hash for it to overwrite, and
        without it a dock opened on a never-checksummed resource would list its files under a greyed
        toolbar with nothing to press.
        """
        toolbar = QToolBar(self)
        toolbar.addAction(self.__actions.verify_old_action)
        toolbar.addAction(self.__actions.generate_action)
        self.__ui.main_layout.insertWidget(0, toolbar)

        ui = self.__ui
        for action, icon in (
            (ui.verify_selection_action, VERIFY_ICON_RESOURCE),
            (ui.generate_selection_action, GENERATE_ICON_RESOURCE),
            (ui.delete_missing_action, DELETE_ICON_RESOURCE),
        ):
            ActionIconThemeHandler(action, icon)
        ui.verify_selection_action.triggered.connect(lambda: self.__actions.verify_selection(self.selected_names()))
        ui.generate_selection_action.triggered.connect(lambda: self.__actions.generate_selection(self.selected_names()))
        ui.delete_missing_action.triggered.connect(self.__delete_missing)

    def __setup_context_menu(self) -> None:
        """Wire the table's right-click menu."""
        self.__ui.file_view.customContextMenuRequested.connect(self.__show_context_menu)

    def __show_context_menu(self, position: QPoint) -> None:
        """Offer the selection-scoped actions, and the two checking ones under them.

        The checking pair is repeated here deliberately: the toolbar is not the only route to them, and
        a reader who has just selected a row should not have to travel back up to check the resource.

        :param position: where the click landed, in the viewport's coordinates.
        """
        ui = self.__ui
        menu = QMenu(self)
        menu.addAction(ui.verify_selection_action)
        menu.addAction(ui.generate_selection_action)
        menu.addAction(ui.delete_missing_action)
        menu.addSeparator()
        menu.addAction(self.__actions.verify_old_action)
        menu.addAction(self.__actions.verify_action)
        menu.exec(ui.file_view.viewport().mapToGlobal(position))

    def __delete_missing(self) -> None:
        """Forget the selected entries whose files are gone, and redraw.

        Always *the missing ones among what you selected*, which serves both sizes of the job without a
        second action: sort by status and prune the block, or ``Ctrl+A`` and prune every gone file in
        the resource at once (#244).
        """
        self.__actions.forget(self.selected_names(status=MISSING_STATUS))

    # endregion

    # region Selection

    def selected_names(self, status: str | None = None) -> tuple[str, ...]:
        """The names behind the selected rows, in view order.

        :param status: keep only the rows carrying this status, or ``None`` for all of them.
        :returns: the record-relative names.
        """
        rows = [self.__rows.row_at(self.__proxy.mapToSource(index).row()) for index in self.__selection.selectedRows()]
        return tuple(row.name for row in rows if status is None or row.status == status)

    def __update_enablement(self, *_args: object) -> None:
        """Offer each action exactly while it can do something.

        Three rules, and each is a decision rather than defensiveness: **nothing at all while the
        resource is unreachable** (#245); the selection-scoped entries only with a selection; and
        **Delete Missing only when the selection holds a ``missing`` row**, since dropping the entry of
        a file that is still on disk achieves nothing -- the next verify adopts it straight back
        ([[data-model#checksums]]). Scoping the action removes that trap rather than explaining it.

        :param _args: whatever the triggering selection signal carried; unused.
        """
        ui = self.__ui
        selected = self.selected_names()
        ui.verify_selection_action.setEnabled(self.__reachable and bool(selected))
        ui.generate_selection_action.setEnabled(self.__reachable and bool(selected))
        ui.delete_missing_action.setEnabled(self.__reachable and bool(self.selected_names(status=MISSING_STATUS)))

    # endregion

    # region This dock's own actions

    @property
    def verify_selection_action(self) -> QAction:
        """Checks exactly the selected files, on the queue. Disabled with an empty selection."""
        return self.__ui.verify_selection_action

    @property
    def generate_selection_action(self) -> QAction:
        """Re-baselines exactly the selected files -- how a genuine change is accepted (#203)."""
        return self.__ui.generate_selection_action

    @property
    def delete_missing_action(self) -> QAction:
        """Forgets the selected entries whose files are gone. Disabled unless the selection holds one:
        dropping the entry of a file still on disk achieves nothing ([[data-model#checksums]])."""
        return self.__ui.delete_missing_action

    @property
    def proxy(self) -> ChecksumSortProxy:
        """The sorting proxy the table draws through, and what numbers its rows."""
        return self.__proxy

    @property
    def summary(self) -> str:
        """The line under the table -- the counts, or why there are none."""
        return self.__ui.summary_label.text()

    def select_rows(self, rows: Sequence[int]) -> None:
        """Select the given *view* rows, replacing whatever was selected.

        :param rows: the row numbers as drawn, which is what a reader clicks and therefore the only
            numbering a caller outside this widget has any business speaking in.
        """
        self.__selection.clearSelection()
        for row in rows:
            self.__selection.select(
                self.__proxy.index(row, PATH_COLUMN),
                QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
            )

    # endregion
