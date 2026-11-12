"""A table browser: the Root Catalog's rows as a table under a filter line and over a status line, one of several per
catalog (#396, #398)."""

from collections.abc import Collection, Iterable, Sequence
from typing import Final
from uuid import UUID, uuid4

import humanize
from borco_core import fold
from borco_pyside.theming import GlyphActionIconThemeHandler
from borco_pyside.widgets import HeaderSectionsMenu, RowBandDelegate
from PySide6.QtCore import QByteArray, QItemSelection, QItemSelectionModel, QModelIndex, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QStandardItemModel
from PySide6.QtWidgets import QLineEdit, QMenu, QTableView, QWidget
from rehuco_core import CatalogField, CatalogQuery, CatalogRow, CatalogTextField

from ..glyphs import FILTER_PROBLEM_GLYPH
from ..settings.catalog_state_store import TABLE_BROWSER_KIND, BrowserState
from .browser_presets import DEFAULT_BROWSER_NAME, DEFAULT_PRESET, BrowserPreset
from .catalog_delegates import COLUMN_DELEGATES
from .catalog_table_model import (
    DEFAULT_HIDDEN,
    HIDDEN_WHEN_ADDED_LATER,
    CatalogColumn,
    CatalogTableModel,
    CatalogTotals,
    RowKey,
)
from .copied_paths import PathsWriter, json_paths, quoted_paths
from .filter_line import SCOPE_SEPARATOR, SCOPE_TOKEN, parse_filter, with_token, without_retired_tokens
from .rehuco_browser_panel_ui import Ui_RehucoBrowserPanel
from .status_line_label import StatusLineLabel

FILTER_SETTLE_MS: Final = 250
"""How long the filter line waits after the last keystroke before its rows are read again; Enter does not wait."""

PROBLEMS_ACTION_NAME: Final = "filter_problems_action"
"""The object name of the filter line's problem marker, which is how it is found again: no Python reference to it is
kept, because the wrapper of a C++-owned action has been seen invalidated while the action lived on (#459)."""

FILTER_HELP: Final = (
    'Words, each found in a title, path, author, publisher or tag; "quoted words" as one phrase; case and accents '
    f"ignored. {SCOPE_TOKEN}: keeps the words to some of those places: "
    f"{SCOPE_TOKEN}:{SCOPE_SEPARATOR.join(place.value for place in CatalogTextField)}. "
    'Then field:value or field:"quoted value" tokens, each matching a whole value: '
    f"{', '.join(field.value for field in CatalogField)}."
)
"""The filter line's tooltip: its grammar, under whatever it could not apply."""

COPY_PATHS_ENTRIES: Final[tuple[tuple[str, PathsWriter], ...]] = (
    ("Copy paths", quoted_paths),
    ("Copy paths as JSON", json_paths),
)
"""The menu's entries for a selection (#646), in menu order: each one's text and the format it copies in."""


class TableBrowser(QWidget):  # pylint: disable=too-many-instance-attributes
    """The cache's resources as a table, with a filter line over it and the count and total size under it.

    **Every browser owns its model.** A :class:`CatalogTableModel` sorts its rows in place, so one shared by
    several browsers would sort them all alike; each browser is fed its own rows and keeps its own order.

    **The filter line picks the rows by query, not by proxy** ([[plugins#rehuco-dock]]): as its text settles it is
    read into a :class:`~rehuco_core.CatalogQuery` and :attr:`query_changed` asks the shell for the rows that match,
    so the model only ever holds what the table shows -- and the status line, which follows the view's model,
    counts exactly that. What the line could not apply is reported on it, never dropped.

    **Which columns show is the header's alone** (#379): its context menu toggles them, and the header state keeps the
    choice with the widths, order and sort; the filter line never names a column. A plain browser starts with
    every column shown but :data:`~.catalog_table_model.DEFAULT_HIDDEN`, one made from a preset with the preset's.

    **The rows change in place** when the app renames, writes or deletes a record (:meth:`update_rows`), so a
    selection survives; exactly one selected row is the browser's **current resource** (:attr:`current_changed`).

    **The selection comes back with the rows** ([[plugins#session-restore]], #576): the one remembered is held until the
    first read of every row and applied quietly, so it does not move the preview the session restores on its own. Until
    then it is what :meth:`state` says, so quitting first loses nothing; a selection the reader makes overtakes it.

    A browser carries the state a catalog remembers about it -- its id, name, filter text and header state -- but
    not its dock: what a name *looks like* on a tab is the shell's.

    :param state: the browser as remembered, or ``None`` for a new one: a fresh id, and the rest from ``preset``.
    :param parent: optional Qt parent.
    :param preset: what a new browser starts as (#400) -- its name, hidden columns and filter line; a plain browser
        unless given. Unused with a ``state``.
    """

    row_activated: Signal = Signal(object)
    """Emitted with a resource's :data:`~rehuco_agent.rehuco.catalog_table_model.RowKey` when its row is
    double-clicked. Typed as plain ``object`` for the reason ``BrowsersDock.open_requested`` is."""

    query_changed: Signal = Signal(object)
    """Emitted with the new :class:`~rehuco_core.CatalogQuery` once the filter line's text has settled on one that
    picks other rows."""

    current_changed: Signal = Signal(object)
    """Emitted with the new :attr:`current_resource` -- a ``(root_id, relative)`` pair, or ``None`` -- whenever it
    changes: by a selection, or by the selected row itself being renamed or removed."""

    copy_paths_requested: Signal = Signal(object, object)
    """Emitted when *Copy paths* or *Copy paths as JSON* is chosen (#646), with the selected rows'
    :data:`~rehuco_agent.rehuco.catalog_table_model.RowKey` tuple in the table's order and the
    :data:`~.copied_paths.PathsWriter` that writes their paths: the browser cannot resolve a key to a path, the catalog
    can. Typed as plain ``object`` for the reason ``BrowsersDock.open_requested`` is."""

    DEFAULT_NAME: Final = DEFAULT_BROWSER_NAME
    """What a browser made without a name is called."""

    def __init__(
        self,
        state: BrowserState | None = None,
        parent: QWidget | None = None,
        *,
        preset: BrowserPreset = DEFAULT_PRESET,
    ) -> None:
        super().__init__(parent)
        self.__browser_id: Final = state.browser_id if state is not None else uuid4()
        self.__name = state.name if state is not None else preset.name
        # a word an older build wrote and this one no longer reads is not this reader's mistake to be told about
        self.__filter_text = without_retired_tokens(state.filter) if state is not None else preset.filter
        self.__parsed = parse_filter(self.__filter_text)
        self.__current: RowKey | None = None
        self.__held_selection: tuple[RowKey, ...] = state.selection if state is not None else ()
        self.__restoring_selection = False
        self.__model: Final = CatalogTableModel(self)
        self.__ui: Final = Ui_RehucoBrowserPanel()
        self.__ui.setupUi(self)
        view = self.__ui.catalog_view
        view.setModel(self.__model)
        self.__status_line: Final = StatusLineLabel()
        self.__ui.status_bar.addWidget(self.__status_line, 1)
        view.setItemDelegate(RowBandDelegate(view))
        for column, delegate in COLUMN_DELEGATES.items():
            view.setItemDelegateForColumn(column, delegate(view))
        # unsorted until a header is clicked: the header's own default puts an arrow on the first column while
        # the rows are still in the cache's order
        view.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.__sections_menu: Final = HeaderSectionsMenu(view.horizontalHeader())
        for column in DEFAULT_HIDDEN if state is not None else preset.hidden:
            view.horizontalHeader().setSectionHidden(column, True)
        view.doubleClicked.connect(self.__on_double_clicked)
        view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        view.customContextMenuRequested.connect(self.__on_context_menu)
        model = self.__model
        for signal in (model.modelReset, model.rowsInserted, model.rowsRemoved, model.dataChanged):
            signal.connect(self.__update_status)
        view.selectionModel().selectionChanged.connect(self.__update_status)
        view.selectionModel().selectionChanged.connect(self.__let_go_of_held_selection)
        # connected after setModel, so the selection model has followed a removed or moved row before this asks it
        view.selectionModel().selectionChanged.connect(self.__update_current)
        for signal in (model.modelReset, model.rowsRemoved, model.rowsMoved, model.dataChanged, model.layoutChanged):
            signal.connect(self.__update_current)
        self.__update_status()

        line = self.__ui.filter_edit
        problems_action = line.addAction(QIcon(), QLineEdit.ActionPosition.TrailingPosition)
        problems_action.setObjectName(PROBLEMS_ACTION_NAME)
        GlyphActionIconThemeHandler(problems_action, FILTER_PROBLEM_GLYPH.codepoint, FILTER_PROBLEM_GLYPH.family)
        self.__settle_timer: Final = QTimer(self)
        self.__settle_timer.setSingleShot(True)
        self.__settle_timer.setInterval(FILTER_SETTLE_MS)
        self.__settle_timer.timeout.connect(self.__apply_typed)
        line.setText(self.filter_text)
        # any change of text settles, a clear button's included; a programmatic one is applied at once, which
        # stops the timer this starts
        line.textChanged.connect(self.__settle_timer.start)
        line.returnPressed.connect(self.__apply_typed)

        if state is not None:
            self.restore_columns(state.columns)
        self.__show_problems()

    @property
    def browser_id(self) -> UUID:
        """The id its dock is named by, stable for the browser's life."""
        return self.__browser_id

    @property
    def kind(self) -> str:
        """What this browser shows."""
        return TABLE_BROWSER_KIND

    @property
    def name(self) -> str:
        """What its tab says."""
        return self.__name

    @name.setter
    def name(self, name: str) -> None:
        self.__name = name

    @property
    def filter_text(self) -> str:
        """The filter line's text as last applied -- what :attr:`query` was read from."""
        return self.__filter_text

    @property
    def query(self) -> CatalogQuery:
        """What the rows are read with: the filter line's free text and field tokens."""
        return self.__parsed.query

    @property
    def filter_problems(self) -> tuple[str, ...]:
        """What the filter line could not apply, one sentence each; empty while it applied whole."""
        return self.__parsed.problems

    @property
    def current_resource(self) -> RowKey | None:
        """The resource of the one selected row, as ``(root_id, relative)``; ``None`` while none or several are."""
        return self.__current

    @property
    def filter_edit(self) -> QLineEdit:
        """The filter line."""
        return self.__ui.filter_edit

    @property
    def sections_menu(self) -> HeaderSectionsMenu:
        """The header's menu of columns."""
        return self.__sections_menu

    @property
    def model(self) -> CatalogTableModel:
        """The table's own model."""
        return self.__model

    @property
    def view(self) -> QTableView:
        """The table."""
        return self.__ui.catalog_view

    @property
    def status_line(self) -> StatusLineLabel:
        """The status line under the table: what it shows and, after that, what is selected."""
        return self.__status_line

    def set_rows(
        self, rows: Sequence[CatalogRow], root_ids: Iterable[UUID], *, catalog: Collection[int] | None = None
    ) -> None:
        """Show ``rows``, in the sort this browser last asked for.

        :param rows: the rows :attr:`query` matches.
        :param root_ids: the roots' ids, in the roots' order.
        :param catalog: the ids of every row the catalog holds now, after a read of them all; ``None`` for a filter
            over the same rows (:meth:`CatalogTableModel.set_rows`).
        """
        self.__model.set_rows(rows, root_ids, catalog=catalog)
        if catalog is not None:
            self.__restore_selection()

    def update_rows(self, affected: Iterable[int], fresh: Sequence[CatalogRow]) -> None:
        """Bring the rows a rename, a write or a deletion touched up to date, in place.

        :param affected: the ids of every row the change may have touched.
        :param fresh: those of them that exist and match :attr:`query` now.
        """
        self.__model.update_rows(affected, fresh)

    def set_filter_text(self, text: str) -> None:
        """Put ``text`` on the filter line and apply it now, without waiting for it to settle.

        :param text: the new line.
        """
        self.__ui.filter_edit.setText(text)
        self.__apply(text)

    def set_token(self, name: str, value: str | None) -> None:
        """Set one token on the filter line and apply it now: any word naming ``name`` is replaced, the rest kept.

        :param name: the token's name -- a field's spelling.
        :param value: its value; ``None`` only removes it.
        """
        self.set_filter_text(with_token(self.__ui.filter_edit.text(), name, value))

    def state(self) -> BrowserState:
        """This browser as a catalog remembers it: the filter line as it reads now, and the header state."""
        return BrowserState(
            self.__browser_id,
            self.kind,
            self.__name,
            self.__ui.filter_edit.text(),
            bytes(self.__ui.catalog_view.horizontalHeader().saveState().data()),
            self.__held_selection or self.__selected_keys(),
        )

    def clone_state(self, name: str) -> BrowserState:
        """What a copy of this browser starts as: the same filter and header -- columns, widths, order and sort --
        under a new id and ``name``.

        :param name: the copy's name.
        :returns: the state to build the copy from.
        """
        current = self.state()
        return BrowserState(uuid4(), self.kind, name, current.filter, current.columns)

    def restore_columns(self, header_state: bytes) -> None:
        """Put back the header state a browser was saved with, then sort as the header now says.

        A state saved before the later columns existed covers only the first ones: Qt shows every column past it, so
        those past it are put back to the defaults, or hidden if a column came later -- as is every column, for a
        state the header refuses.

        :param header_state: bytes from :meth:`state`; empty leaves the defaults.
        """
        header = self.__ui.catalog_view.horizontalHeader()
        if header_state:
            covered = self.saved_column_count(header_state) if self.__sections_menu.restore_state(header_state) else 0
            # a state the header refuses is back to the defaults, a new browser's: the later columns shown
            later = HIDDEN_WHEN_ADDED_LATER if covered else frozenset()
            for column in DEFAULT_HIDDEN | later:
                if column >= covered:
                    header.setSectionHidden(column, True)
        self.__model.sort(header.sortIndicatorSection(), header.sortIndicatorOrder())

    @staticmethod
    def saved_column_count(header_state: bytes) -> int:
        """How many columns a saved header state describes.

        Read by restoring it onto a scratch one-column table, whose header grows to the state's count -- Qt keeps no
        other public account of it, and parsing its bytes would tie this to its private format.

        :param header_state: bytes from :meth:`state`.
        :returns: the count; ``0`` for bytes the header refuses.
        """
        scratch = QTableView()
        scratch.setModel(QStandardItemModel(0, 1, scratch))
        header = scratch.horizontalHeader()
        count = header.count() if header.restoreState(QByteArray(header_state)) else 0
        scratch.deleteLater()
        return count

    def __selected_keys(self) -> tuple[RowKey, ...]:
        """Which resources the selected rows are.

        :returns: their keys, in the table's order -- not the order they were selected in.
        """
        rows = sorted(index.row() for index in self.__ui.catalog_view.selectionModel().selectedRows())
        keys = (self.__model.row_key(row) for row in rows)
        return tuple(key for key in keys if key is not None)

    def __restore_selection(self) -> None:
        """Select the rows remembered, now every row is here, and say nothing: nothing follows a restored selection.

        A read that brought no rows at all -- a cache still being built -- says nothing about them yet, so they are
        held on for the next one; a read with rows that lack them says they are gone.
        """
        if not self.__held_selection or self.__model.rowCount() == 0:
            return
        held, self.__held_selection = self.__held_selection, ()
        rows = self.__model.rows_of(frozenset(held))
        if not rows:
            return
        view = self.__ui.catalog_view
        selection = QItemSelection()
        for row in rows:
            selection.select(self.__model.index(row, 0), self.__model.index(row, 0))
        model = view.selectionModel()
        flags = QItemSelectionModel.SelectionFlag
        self.__restoring_selection = True
        try:
            model.select(selection, flags.ClearAndSelect | flags.Rows)
            model.setCurrentIndex(self.__model.index(rows[0], 0), flags.NoUpdate)
        finally:
            self.__restoring_selection = False
        view.scrollTo(self.__model.index(rows[0], 0))

    def __let_go_of_held_selection(self) -> None:
        """Give up the selection held: the reader has selected something themselves."""
        if not self.__restoring_selection:
            self.__held_selection = ()

    def __apply_typed(self) -> None:
        """Apply what has been typed, now."""
        self.__apply(self.__ui.filter_edit.text())

    def __apply(self, text: str) -> None:
        """Read ``text`` and show what it says, asking for other rows if it picks other ones.

        :param text: the filter line's text.
        """
        self.__settle_timer.stop()
        previous = self.__parsed.query
        self.__filter_text = text
        self.__parsed = parse_filter(text)
        # the rows come first: the marker is only decoration, and a failure showing it must not leave the old rows
        # on screen under a cleared line (#459)
        if self.__parsed.query != previous:
            self.query_changed.emit(self.__parsed.query)
        self.__show_problems()

    def __show_problems(self) -> None:
        """Show on the line what it could not apply."""
        problems = self.__parsed.problems
        tooltip = "\n".join(problems)
        edit = self.__ui.filter_edit
        marker = next((action for action in edit.actions() if action.objectName() == PROBLEMS_ACTION_NAME), None)
        if marker is not None:
            marker.setVisible(bool(problems))
            marker.setToolTip(tooltip)
        self.__ui.filter_edit.setToolTip(f"{tooltip}\n\n{FILTER_HELP}" if problems else FILTER_HELP)

    def __update_current(self) -> None:
        """Say which resource is current now, if that changed: the one selected row's, else none."""
        rows = self.__ui.catalog_view.selectionModel().selectedRows()
        current = self.__model.row_key(rows[0].row()) if len(rows) == 1 else None
        if current != self.__current:
            self.__current = current
            if not self.__restoring_selection:
                self.current_changed.emit(current)

    def __on_context_menu(self, position: QPoint) -> None:
        """Open the table's menu, if it has anything to offer: an Authors cell offers to filter by each of its authors
        (#460), and a selection to copy its rows' paths (#646), after a separator when both do. A cell with no authors
        and nothing selected opens nothing.

        :param position: where it was asked for, in the table's viewport coordinates.
        """
        view = self.__ui.catalog_view
        index = view.indexAt(position)
        authors = self.__model.authors_of(index.row()) if index.column() == CatalogColumn.AUTHORS else ()
        selected = self.__selected_keys()
        if not authors and not selected:
            return
        # a child of this widget, so a failed ``exec`` must not leave it behind for the browser's life (#459)
        menu = QMenu(self)
        try:
            self.__add_author_entries(menu, authors)
            if authors and selected:
                menu.addSeparator()
            if selected:
                for text, write in COPY_PATHS_ENTRIES:
                    action = menu.addAction(text)
                    action.triggered.connect(
                        lambda _checked=False, writer=write: self.copy_paths_requested.emit(selected, writer)
                    )
            menu.exec(view.viewport().mapToGlobal(position))
        finally:
            menu.deleteLater()

    def __add_author_entries(self, menu: QMenu, authors: Sequence[str]) -> None:
        """Add an entry per author to ``menu``: filter by that author, or clear the filter by one the line names.

        :param menu: the menu being built.
        :param authors: the clicked row's authors, in the record's order; none adds nothing.
        """
        applied = {
            fold(token.value) for token in parse_filter(self.__ui.filter_edit.text()).tokens if token.name == "authors"
        }
        for author in authors:
            clearing = fold(author) in applied
            text = f"Clear the filter by {author}" if clearing else f"Filter by {author}"
            action = menu.addAction(text)
            action.triggered.connect(
                lambda _checked=False, name=author, clear=clearing: self.__toggle_author(name, clear)
            )

    def __toggle_author(self, name: str, clear: bool) -> None:
        """Filter by ``name`` alone, or drop the authors filter it already is.

        :param name: an author of the clicked row.
        :param clear: whether the line already filters by ``name``.
        """
        self.set_token("authors", None if clear else name)

    def __on_double_clicked(self, index: QModelIndex) -> None:
        """Ask for the double-clicked resource to be opened, by its row key.

        :param index: the activated cell.
        """
        key = self.__model.row_key(index.row())
        if key is not None:
            self.row_activated.emit(key)

    def __update_status(self) -> None:
        """Say what the table shows now, and after it what is selected (#462): the rows, their sizes and, where it
        means anything, their image counts added up over the ``.rehu`` rows, the legacy ``.tc`` ones counted apart --
        each total saying how many rows it left out, never silently understating."""
        totals = self.__model.totals
        if totals.count == 0:
            self.__status_line.set_parts("No resources")
            return
        selected = set[int]()
        selection = self.view.selectionModel().selection()
        for position in range(selection.count()):
            chosen_range = selection.at(position)
            selected.update(range(chosen_range.top(), chosen_range.bottom() + 1))
        secondary = ""
        if selected:
            chosen = self.__model.totals_of(selected)
            secondary = self.__describe(chosen, f"{chosen.count:,} selected")
        self.__status_line.set_parts(self.__describe(totals, self.__resources(totals)), secondary)

    @staticmethod
    def __resources(totals: CatalogTotals) -> str:
        """How many resources, the singular spelled right."""
        return f"{totals.count:,} {'resource' if totals.count == 1 else 'resources'}"

    def __describe(self, totals: CatalogTotals, lead: str) -> str:
        """One part of the status line.

        :param totals: what it adds up.
        :param lead: how it starts: the count of rows it speaks of.
        :returns: the part.
        """
        parts = [lead]
        if totals.legacy:
            parts.append(f"{totals.legacy:,} legacy .tc")
        parts.append(humanize.naturalsize(totals.size, gnu=True) + self.__unmeasured(totals.unmeasured_size))
        if totals.has_images:
            noun = "image" if totals.images == 1 else "images"
            parts.append(f"{totals.images:,} {noun}{self.__unmeasured(totals.unmeasured_images)}")
        return " / ".join(parts)

    @staticmethod
    def __unmeasured(missing: int) -> str:
        """The parenthesis after a partial total; nothing when no row is missing."""
        return f" ({missing} unmeasured)" if missing else ""
