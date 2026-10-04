"""A table browser: the Root Catalog's rows as a table under a filter line and over a status line, one of several per
catalog (#396, #398)."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final
from uuid import UUID, uuid4

import humanize
from borco_pyside.theming import GlyphActionIconThemeHandler
from borco_pyside.widgets import HeaderSectionsMenu, RowBandDelegate
from PySide6.QtCore import QModelIndex, Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QLineEdit, QStatusBar, QTableView, QWidget
from rehuco_core import CatalogField, CatalogQuery, CatalogRow

from ..glyphs import FILTER_PROBLEM_GLYPH
from ..settings.catalog_state_store import TABLE_BROWSER_KIND, BrowserState
from .catalog_table_model import COLUMN_IDS, CatalogTableModel
from .filter_line import COLUMN_SEPARATOR, COLUMNS_TOKEN, parse_filter, with_token
from .rehuco_browser_panel_ui import Ui_RehucoBrowserPanel

FILTER_SETTLE_MS: Final = 250
"""How long the filter line waits after the last keystroke before its rows are read again; Enter does not wait."""

FILTER_HELP: Final = (
    'Free text, and field:value or field:"quoted value" tokens: '
    f"{', '.join(field.value for field in CatalogField)}.\n"
    f"{COLUMNS_TOKEN}:{COLUMN_SEPARATOR.join(COLUMN_IDS)} picks the columns shown."
)
"""The filter line's tooltip: its grammar, under whatever it could not apply."""


class TableBrowser(QWidget):  # pylint: disable=too-many-instance-attributes
    """The cache's resources as a table, with a filter line over it and the count and total size under it.

    **Every browser owns its model.** A :class:`CatalogTableModel` sorts its rows in place, so one shared by
    several browsers would sort them all alike; each browser is fed its own rows and keeps its own order.

    **The filter line picks the rows by query, not by proxy** ([[plugins#rehuco-dock]]): as its text settles it is
    read into a :class:`~rehuco_core.CatalogQuery` and :attr:`query_changed` asks the shell for the rows that match,
    so the model only ever holds what the table shows -- and the status line, which follows the view's model,
    counts exactly that. A ``columns:`` token sets which columns show; a change from the header's own menu is
    written back into the text, so one string always says both. What the line could not apply is reported on it,
    never dropped.

    A browser carries the state a catalog remembers about it -- its id, name, filter text and header state -- but
    not its dock: what a name *looks like* on a tab is the shell's.

    :param state: the browser as remembered, or ``None`` for a new one: a fresh id and the name ``"Browser"``.
    :param parent: optional Qt parent.
    """

    row_activated: Signal = Signal(object)
    """Emitted with a resource's absolute :class:`~pathlib.Path` when its row is double-clicked. Typed as plain
    ``object`` for the reason ``RehucoDock.open_requested`` is."""

    query_changed: Signal = Signal(object)
    """Emitted with the new :class:`~rehuco_core.CatalogQuery` once the filter line's text has settled on one that
    picks other rows; a change of columns alone is not one."""

    DEFAULT_NAME: Final = "Browser"
    """What a browser made without a name is called."""

    def __init__(self, state: BrowserState | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__browser_id: Final = state.browser_id if state is not None else uuid4()
        self.__name = state.name if state is not None else self.DEFAULT_NAME
        self.__filter_text = state.filter if state is not None else ""
        self.__parsed = parse_filter(self.__filter_text, COLUMN_IDS)
        self.__writing_columns = False
        """Set while the header's columns are being written into the text, so they are not applied back."""
        self.__model: Final = CatalogTableModel(self)
        self.__ui: Final = Ui_RehucoBrowserPanel()
        self.__ui.setupUi(self)
        view = self.__ui.catalog_view
        view.setModel(self.__model)
        view.setItemDelegate(RowBandDelegate(view))
        # unsorted until a header is clicked: the header's own default puts an arrow on the first column while
        # the rows are still in the cache's order
        view.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.__sections_menu: Final = HeaderSectionsMenu(view.horizontalHeader())
        view.doubleClicked.connect(self.__on_double_clicked)
        for signal in (self.__model.modelReset, self.__model.rowsInserted, self.__model.rowsRemoved):
            signal.connect(self.__update_status)
        self.__update_status()

        line = self.__ui.filter_edit
        self.__problems_action: Final = line.addAction(QIcon(), QLineEdit.ActionPosition.TrailingPosition)
        GlyphActionIconThemeHandler(self.__problems_action, FILTER_PROBLEM_GLYPH.codepoint, FILTER_PROBLEM_GLYPH.family)
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
        # the header state keeps the widths and the order; a columns token in the saved text has the last word on
        # which show, so the two agree from the start
        self.__show_parsed()
        self.__sections_menu.sections_visibility_changed.connect(self.__on_sections_toggled)

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

    def set_filter_text(self, text: str) -> None:
        """Put ``text`` on the filter line and apply it now, without waiting for it to settle.

        :param text: the new line.
        """
        self.__ui.filter_edit.setText(text)
        self.__apply(text)

    def set_token(self, name: str, value: str | None) -> None:
        """Set one token on the filter line and apply it now: any word naming ``name`` is replaced, the rest kept.

        :param name: the token's name -- a field's spelling, or ``columns``.
        :param value: its value; ``None`` only removes it.
        """
        self.set_filter_text(with_token(self.__ui.filter_edit.text(), COLUMN_IDS, name, value))

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
        """What a copy of this browser starts as: the same filter and columns under a new id and ``name``.

        :param name: the copy's name.
        :returns: the state to build the copy from.
        """
        current = self.state()
        return BrowserState(uuid4(), self.kind, name, current.filter, current.columns)

    def restore_columns(self, header_state: bytes) -> None:
        """Put back the header state a browser was saved with, then sort as the header now says.

        A header state that does not fit the model leaves every column shown (:meth:`HeaderSectionsMenu.restore_state`).

        :param header_state: bytes from :meth:`state`; empty leaves the defaults.
        """
        header = self.__ui.catalog_view.horizontalHeader()
        if header_state:
            self.__sections_menu.restore_state(header_state)
        self.__model.sort(header.sortIndicatorSection(), header.sortIndicatorOrder())

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
        self.__parsed = parse_filter(text, COLUMN_IDS)
        self.__show_parsed()
        if self.__parsed.query != previous:
            self.query_changed.emit(self.__parsed.query)

    def __show_parsed(self) -> None:
        """Show the columns the line names, and on the line what it could not apply."""
        columns = self.__parsed.columns
        if columns is not None and not self.__writing_columns:
            header = self.__ui.catalog_view.horizontalHeader()
            for section, column in enumerate(COLUMN_IDS):
                header.setSectionHidden(section, column not in columns)
        problems = self.__parsed.problems
        self.__problems_action.setVisible(bool(problems))
        tooltip = "\n".join(problems)
        self.__problems_action.setToolTip(tooltip)
        self.__ui.filter_edit.setToolTip(f"{tooltip}\n\n{FILTER_HELP}" if problems else FILTER_HELP)

    def __on_sections_toggled(self) -> None:
        """Write the columns the header now shows into the line: a ``columns:`` token naming them, in the order they
        show, or no token once every column shows again."""
        header = self.__ui.catalog_view.horizontalHeader()
        logical = [header.logicalIndex(visual) for visual in range(header.count())]
        visible = [COLUMN_IDS[section] for section in logical if not header.isSectionHidden(section)]
        text = self.__ui.filter_edit.text()
        named = any(token.name == COLUMNS_TOKEN for token in parse_filter(text, COLUMN_IDS).tokens)
        value = None if len(visible) == len(COLUMN_IDS) else COLUMN_SEPARATOR.join(visible)
        if value is None and not named:
            return
        self.__writing_columns = True
        try:
            self.set_token(COLUMNS_TOKEN, value)
        finally:
            self.__writing_columns = False

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
