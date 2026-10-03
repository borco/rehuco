"""A table browser: the Root Catalog's rows as a table with a status line, one of several per catalog (#396)."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final, cast
from uuid import UUID, uuid4

import humanize
from borco_pyside.widgets import RowBandDelegate
from PySide6.QtCore import QAbstractItemModel, QByteArray, QModelIndex, Qt, Signal
from PySide6.QtWidgets import QStatusBar, QTableView, QWidget
from rehuco_core import CatalogRow

from ..settings.catalog_state_store import TABLE_BROWSER_KIND, BrowserState
from .catalog_table_model import SIZE_ROLE, CatalogTableModel
from .rehuco_browser_panel_ui import Ui_RehucoBrowserPanel


class TableBrowser(QWidget):
    """The cache's resources as a table, with the count and total size under it.

    **Every browser owns its model.** A :class:`CatalogTableModel` sorts its rows in place, so one shared by
    several browsers would sort them all alike; each browser is fed the same rows and keeps its own order. The
    status line follows the *view's* model rather than the catalog's, so a filter proxy over it (#398) is counted
    as what it shows.

    A browser carries the state a catalog remembers about it -- its id, name, filter text and header state -- but
    not its dock: what a name *looks like* on a tab is the shell's.

    :param state: the browser as remembered, or ``None`` for a new one: a fresh id and the name ``"Browser"``.
    :param parent: optional Qt parent.
    """

    row_activated: Signal = Signal(object)
    """Emitted with a resource's absolute :class:`~pathlib.Path` when its row is double-clicked. Typed as plain
    ``object`` for the reason ``RehucoDock.open_requested`` is."""

    DEFAULT_NAME: Final = "Browser"
    """What a browser made without a name is called."""

    def __init__(self, state: BrowserState | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__browser_id: Final = state.browser_id if state is not None else uuid4()
        self.__name = state.name if state is not None else self.DEFAULT_NAME
        self.__filter_text = state.filter if state is not None else ""
        self.__model: Final = CatalogTableModel(self)
        self.__ui: Final = Ui_RehucoBrowserPanel()
        self.__ui.setupUi(self)
        view = self.__ui.catalog_view
        view.setModel(self.__model)
        view.setItemDelegate(RowBandDelegate(view))
        # unsorted until a header is clicked: the header's own default puts an arrow on the first column while
        # the rows are still in the cache's order
        view.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        view.doubleClicked.connect(self.__on_double_clicked)
        shown = cast(QAbstractItemModel, view.model())
        for signal in (shown.modelReset, shown.rowsInserted, shown.rowsRemoved):
            signal.connect(self.__update_status)
        self.__update_status()
        if state is not None:
            self.restore_columns(state.columns)

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
        """The filter line's text; always empty until the filter line exists (#398)."""
        return self.__filter_text

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

        :param rows: the cache's rows.
        :param root_paths: each root's folder, by id, for the rows' absolute paths.
        """
        self.__model.set_rows(rows, root_paths)

    def state(self) -> BrowserState:
        """This browser as a catalog remembers it: the header state is read now."""
        return BrowserState(
            self.__browser_id,
            self.kind,
            self.__name,
            self.__filter_text,
            bytes(self.__ui.catalog_view.horizontalHeader().saveState().data()),
        )

    def clone_state(self, name: str) -> BrowserState:
        """What a copy of this browser starts as: the same filter and columns under a new id and ``name``.

        :param name: the copy's name.
        :returns: the state to build the copy from.
        """
        return BrowserState(uuid4(), self.kind, name, self.__filter_text, self.state().columns)

    def restore_columns(self, header_state: bytes) -> None:
        """Put back the header state a browser was saved with, then sort as the header now says.

        Qt itself refuses a header state that does not fit the model, so a damaged one leaves the defaults.

        :param header_state: bytes from :meth:`state`; empty leaves the defaults.
        """
        header = self.__ui.catalog_view.horizontalHeader()
        if header_state:
            header.restoreState(QByteArray(header_state))
        self.__model.sort(header.sortIndicatorSection(), header.sortIndicatorOrder())

    def __on_double_clicked(self, index: QModelIndex) -> None:
        """Ask for the double-clicked resource to be opened, by its absolute path.

        :param index: the activated cell.
        """
        path = self.__model.absolute_path(index.row())
        if path is not None:
            self.row_activated.emit(path)

    def __update_status(self) -> None:
        """Say how many rows the table shows now, and their sizes added up."""
        model = self.__ui.catalog_view.model()
        count = model.rowCount()
        if count == 0:
            self.__ui.status_bar.showMessage("No resources")
            return
        total = sum(model.index(row, 0).data(SIZE_ROLE) for row in range(count))
        noun = "resource" if count == 1 else "resources"
        self.__ui.status_bar.showMessage(f"{count} {noun} / {humanize.naturalsize(total, gnu=True)}")
