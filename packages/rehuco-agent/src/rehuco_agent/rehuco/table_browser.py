"""A table browser: the Root Catalog's rows as a table under a filter line and over a status line, one of several per
catalog (#396, #398)."""

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Final
from uuid import UUID, uuid4

import humanize
from borco_pyside.theming import GlyphActionIconThemeHandler
from borco_pyside.widgets import HeaderSectionsMenu, RowBandDelegate
from PySide6.QtCore import QByteArray, QModelIndex, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QStandardItemModel
from PySide6.QtWidgets import QLineEdit, QMenu, QStatusBar, QTableView, QWidget
from rehuco_core import CatalogField, CatalogQuery, CatalogRow

from ..glyphs import FILTER_PROBLEM_GLYPH
from ..settings.catalog_state_store import TABLE_BROWSER_KIND, BrowserState
from .browser_presets import DEFAULT_BROWSER_NAME, DEFAULT_PRESET, BrowserPreset
from .catalog_delegates import COLUMN_DELEGATES
from .catalog_table_model import DEFAULT_HIDDEN, CatalogColumn, CatalogTableModel, RowKey
from .filter_line import parse_filter, with_token, without_retired_tokens
from .rehuco_browser_panel_ui import Ui_RehucoBrowserPanel

FILTER_SETTLE_MS: Final = 250
"""How long the filter line waits after the last keystroke before its rows are read again; Enter does not wait."""

PROBLEMS_ACTION_NAME: Final = "filter_problems_action"
"""The object name of the filter line's problem marker, which is how it is found again: no Python reference to it is
kept, because the wrapper of a C++-owned action has been seen invalidated while the action lived on (#459)."""

FILTER_HELP: Final = (
    f'Free text, and field:value or field:"quoted value" tokens: {", ".join(field.value for field in CatalogField)}.'
)
"""The filter line's tooltip: its grammar, under whatever it could not apply."""


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

    A browser carries the state a catalog remembers about it -- its id, name, filter text and header state -- but
    not its dock: what a name *looks like* on a tab is the shell's.

    :param state: the browser as remembered, or ``None`` for a new one: a fresh id, and the rest from ``preset``.
    :param parent: optional Qt parent.
    :param preset: what a new browser starts as (#400) -- its name, hidden columns and filter line; a plain browser
        unless given. Unused with a ``state``.
    """

    row_activated: Signal = Signal(object)
    """Emitted with a resource's absolute :class:`~pathlib.Path` when its row is double-clicked. Typed as plain
    ``object`` for the reason ``BrowsersDock.open_requested`` is."""

    query_changed: Signal = Signal(object)
    """Emitted with the new :class:`~rehuco_core.CatalogQuery` once the filter line's text has settled on one that
    picks other rows."""

    current_changed: Signal = Signal(object)
    """Emitted with the new :attr:`current_resource` -- a ``(root_id, relative)`` pair, or ``None`` -- whenever it
    changes: by a selection, or by the selected row itself being renamed or removed."""

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
        self.__model: Final = CatalogTableModel(self)
        self.__ui: Final = Ui_RehucoBrowserPanel()
        self.__ui.setupUi(self)
        view = self.__ui.catalog_view
        view.setModel(self.__model)
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
    def status_bar(self) -> QStatusBar:
        """The status line under the table: how many resources it shows."""
        return self.__ui.status_bar

    def set_rows(self, rows: Sequence[CatalogRow], root_paths: Mapping[UUID, Path]) -> None:
        """Show ``rows``, in the sort this browser last asked for.

        :param rows: the rows :attr:`query` matches.
        :param root_paths: each root's folder, by id, for the rows' absolute paths.
        """
        self.__model.set_rows(rows, root_paths)

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
        those past it are put back to the defaults -- as is every column, for a state the header refuses.

        :param header_state: bytes from :meth:`state`; empty leaves the defaults.
        """
        header = self.__ui.catalog_view.horizontalHeader()
        if header_state:
            covered = self.saved_column_count(header_state) if self.__sections_menu.restore_state(header_state) else 0
            for column in DEFAULT_HIDDEN:
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
            self.current_changed.emit(current)

    def __on_context_menu(self, position: QPoint) -> None:
        """Open the menu of the cell under the pointer, if it has one: an Authors cell offers to filter by each of its
        authors (#460). Any other cell, and a row with no authors, opens nothing.

        :param position: where it was asked for, in the table's viewport coordinates.
        """
        view = self.__ui.catalog_view
        index = view.indexAt(position)
        if not index.isValid() or index.column() != CatalogColumn.AUTHORS:
            return
        authors = self.__model.authors_of(index.row())
        if not authors:
            return
        applied = {
            token.value.casefold()
            for token in parse_filter(self.__ui.filter_edit.text()).tokens
            if token.name == "authors"
        }
        # a child of this widget, so a failed ``exec`` must not leave it behind for the browser's life (#459)
        menu = QMenu(self)
        try:
            for author in authors:
                clearing = author.casefold() in applied
                text = f"Clear the filter by {author}" if clearing else f"Filter by {author}"
                action = menu.addAction(text)
                action.triggered.connect(
                    lambda _checked=False, name=author, clear=clearing: self.__toggle_author(name, clear)
                )
            menu.exec(view.viewport().mapToGlobal(position))
        finally:
            menu.deleteLater()

    def __toggle_author(self, name: str, clear: bool) -> None:
        """Filter by ``name`` alone, or drop the authors filter it already is.

        :param name: an author of the clicked row.
        :param clear: whether the line already filters by ``name``.
        """
        self.set_token("authors", None if clear else name)

    def __on_double_clicked(self, index: QModelIndex) -> None:
        """Ask for the double-clicked resource to be opened, by its absolute path.

        :param index: the activated cell.
        """
        path = self.__model.absolute_path(index.row())
        if path is not None:
            self.row_activated.emit(path)

    def __update_status(self) -> None:
        """Say how many rows the table shows now, their sizes and, where it means anything, their image counts added
        up over the ``.rehu`` rows, the legacy ``.tc`` ones counted apart -- each total saying how many rows it left
        out, never silently understating."""
        totals = self.__model.totals
        if totals.count == 0:
            self.__ui.status_bar.showMessage("No resources")
            return
        noun = "resource" if totals.count == 1 else "resources"
        parts = [f"{totals.count:,} {noun}"]
        if totals.legacy:
            parts.append(f"{totals.legacy:,} legacy .tc")
        parts.append(humanize.naturalsize(totals.size, gnu=True) + self.__unmeasured(totals.unmeasured_size))
        if totals.has_images:
            noun = "image" if totals.images == 1 else "images"
            parts.append(f"{totals.images:,} {noun}{self.__unmeasured(totals.unmeasured_images)}")
        self.__ui.status_bar.showMessage(" / ".join(parts))

    @staticmethod
    def __unmeasured(missing: int) -> str:
        """The parenthesis after a partial total; nothing when no row is missing."""
        return f" ({missing} unmeasured)" if missing else ""
