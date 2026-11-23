"""The scripts' scrapers and scraper wizards as table rows, one per class or per problem file, with an icon for each
role a class declares and a checkable **Use browser** column ([[acquisition-tooling#scraper-registry]],
[[acquisition-tooling#browser-persona]]).
"""

from typing import Any, Final, override

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QPersistentModelIndex, Qt
from PySide6.QtGui import QBrush, QColor

from ...fields.colors import ERROR_COLOR, WARNING_COLOR
from ...scraping.registry import ScraperRow
from ...scraping.role_report import RoleState

SCRAPER_NAME_COLUMN: Final = 0
SOURCE_COLUMN: Final = 1
SCRAPER_ROLE_COLUMN: Final = 2
WIZARD_ROLE_COLUMN: Final = 3
USE_BROWSER_COLUMN: Final = 4
ERROR_COLUMN: Final = 5
COLUMN_COUNT: Final = 6
COLUMN_TITLES: Final = ("Name", "Source", "Scraper", "Wizard", "Use browser", "Error")

NO_SCRAPERS_TEXT: Final = "—"
"""What the Name column shows for a file's own row: one that failed to load, or declares neither a scraper nor a
scraper wizard."""

ROLE_ICONS: Final = {
    RoleState.OK: ":/icons/module_ok.svg",
    RoleState.ERROR: ":/icons/module_error.svg",
    RoleState.OVERRIDDEN_OK: ":/icons/module_overridden_ok.svg",
    RoleState.OVERRIDDEN_ERROR: ":/icons/module_overridden_error.svg",
}
"""The glyph of each way a class fares in a role it declares; a role it does not declare has none, and its cell
stays empty (#683)."""

ROLE_TOOLTIPS: Final = {
    RoleState.OK: "Works",
    RoleState.ERROR: "Declared, but cannot be used: see Error",
    RoleState.OVERRIDDEN_OK: "Works, but another with the same key is used instead: see Error",
    RoleState.OVERRIDDEN_ERROR: "Cannot be used, and another with the same key is used instead: see Error",
}
"""What a role cell's tooltip says of its glyph."""

ROLE_ICON_ROLE: Final = Qt.ItemDataRole.UserRole + 1
"""Carries a role cell's glyph, as its resource path, for `~.scrapers_role_delegate.ScrapersRoleDelegate` to draw
centered -- ``None`` for a role the row's class does not declare."""

SITE_URL_ROLE: Final = Qt.ItemDataRole.UserRole
"""Carries a `~rehuco_agent.scraping.registry.ScraperRow.site_url` on a `SCRAPER_NAME_COLUMN` cell, for
`~.scrapers_scraper_column_delegate.ScrapersScraperColumnDelegate` to render and hit-test as a link --
empty for a row with none."""

type ModelIndex = QModelIndex | QPersistentModelIndex
"""What Qt hands a model method; the persistent form arrives from a view holding onto an index."""


class ScrapersTableModel(QAbstractTableModel):
    """A view over `rehuco_agent.scraping.registry.ScraperRegistry.rows`, with one staged, checkable
    edit of its own: which scrapers the **Use browser** column has ticked
    (`~rehuco_agent.settings.scrapers_settings.ScrapersSettings.browser_scrapers`).

    Rebuilt as a whole on every :meth:`set_rows` -- unlike `rehuco_agent.tasks.TaskQueueModel`, this
    table changes only on an explicit Reload or Save, never live, so there is no burst of small updates
    worth diffing against. The staged checkbox set is **not** reset by :meth:`set_rows`: a Reload must
    not discard an unsaved tick.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__rows: tuple[ScraperRow, ...] = ()
        self.__browser_scrapers: frozenset[str] = frozenset()

    def set_rows(self, rows: tuple[ScraperRow, ...]) -> None:
        """Replace every row, keeping the staged **Use browser** set as it was.

        :param rows: the rows to show, in scan order.
        """
        self.beginResetModel()
        self.__rows = rows
        self.endResetModel()

    def browser_scrapers(self) -> frozenset[str]:
        """The staged **Use browser** set: keys the user ticked -- a
        `~rehuco_agent.scraping.registry.ScraperRow.needs_browser` row is checked in the table too, but
        that is forced, not staged, and its key is never in this set (matching
        `~rehuco_agent.settings.scrapers_settings.ScrapersSettings.browser_scrapers`, which only ever
        holds the user's own picks)."""
        return frozenset(
            row.key for row in self.__rows if row.key is not None and not row.needs_browser and self.__is_checked(row)
        )

    def set_browser_scrapers(self, keys: frozenset[str]) -> None:
        """Replace the staged **Use browser** set, e.g. from the saved settings or a Reset/Defaults.

        :param keys: the scraper keys to show ticked.
        """
        self.beginResetModel()
        self.__browser_scrapers = keys
        self.endResetModel()

    def __is_checked(self, row: ScraperRow) -> bool:
        """Whether ``row``'s checkbox reads checked: always for a `ScraperRow.needs_browser` scraper,
        otherwise following the staged set."""
        return row.needs_browser or row.key in self.__browser_scrapers

    # region Qt model interface

    @override
    def rowCount(self, parent: ModelIndex = QModelIndex()) -> int:  # noqa: N802  (Qt API name)
        return 0 if parent.isValid() else len(self.__rows)

    @override
    def columnCount(self, parent: ModelIndex = QModelIndex()) -> int:  # noqa: N802  (Qt API name)
        return 0 if parent.isValid() else COLUMN_COUNT

    @override
    def headerData(  # noqa: N802  (Qt API name)
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if role != Qt.ItemDataRole.DisplayRole or orientation != Qt.Orientation.Horizontal:
            return None
        return COLUMN_TITLES[section] if 0 <= section < COLUMN_COUNT else None

    @override
    def flags(self, index: ModelIndex) -> Qt.ItemFlag:  # noqa: N802  (Qt API name)
        base = super().flags(index)
        if not index.isValid() or index.column() != USE_BROWSER_COLUMN:
            return base
        row = self.__rows[index.row()]
        if row.key is None:
            return base
        checkable = base | Qt.ItemFlag.ItemIsUserCheckable
        return checkable & ~Qt.ItemFlag.ItemIsEnabled if row.needs_browser else checkable

    @override
    def data(self, index: ModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # pylint: disable=too-many-return-statements
        if not index.isValid():
            return None
        row = self.__rows[index.row()]
        state = self.__role_state(row, index.column())
        if role == ROLE_ICON_ROLE:
            return None if state is None else ROLE_ICONS[state]
        if role == Qt.ItemDataRole.ToolTipRole and state is not None:
            return ROLE_TOOLTIPS[state]
        if role == Qt.ItemDataRole.DisplayRole and index.column() != USE_BROWSER_COLUMN:
            return self.__display(row, index.column())
        if role == Qt.ItemDataRole.CheckStateRole and index.column() == USE_BROWSER_COLUMN and row.key is not None:
            return Qt.CheckState.Checked if self.__is_checked(row) else Qt.CheckState.Unchecked
        if role == SITE_URL_ROLE and index.column() == SCRAPER_NAME_COLUMN:
            return row.site_url
        if role == Qt.ItemDataRole.ForegroundRole and index.column() == ERROR_COLUMN and (row.error or row.warning):
            # a note -- what replaced the class -- is no fault, and keeps the plain text color
            return QBrush(QColor(ERROR_COLOR if row.error else WARNING_COLOR))
        if role == Qt.ItemDataRole.ToolTipRole and index.column() == ERROR_COLUMN:
            # the column is nowhere near wide enough for a real import error (a syntax error's file,
            # line and message), and `~borco_pyside.widgets.RowBandDelegate` elides it -- the
            # tooltip is where the whole message actually lives
            return self.__message(row) or None
        return None

    @override
    def setData(self, index: ModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:  # noqa: N802
        if role != Qt.ItemDataRole.CheckStateRole or index.column() != USE_BROWSER_COLUMN or not index.isValid():
            return False
        row = self.__rows[index.row()]
        if row.key is None or row.needs_browser:
            return False
        checked = Qt.CheckState(value) == Qt.CheckState.Checked
        self.__browser_scrapers = (
            self.__browser_scrapers | {row.key} if checked else self.__browser_scrapers - {row.key}
        )
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
        return True

    @staticmethod
    def __display(row: ScraperRow, column: int) -> str:
        """What a cell's plain text is, for every column but the checkbox one.

        A Name cell's `site_name` is returned here whether or not the row also carries a
        `SITE_URL_ROLE`: `~.scrapers_scraper_column_delegate.ScrapersScraperColumnDelegate` reads this
        role for the text a link cell shows too, rather than duplicating it."""
        if column == SCRAPER_NAME_COLUMN:
            return row.site_name or NO_SCRAPERS_TEXT
        if column == SOURCE_COLUMN:
            return row.source
        if column == ERROR_COLUMN:
            return ScrapersTableModel.__message(row)
        return ""

    @staticmethod
    def __message(row: ScraperRow) -> str:
        """What the Error column says of a row: its fault, else its warning, else its note.

        :param row: the row.
        :returns: the text; empty for a row with nothing to say.
        """
        return row.error or row.warning or row.note

    @staticmethod
    def __role_state(row: ScraperRow, column: int) -> RoleState | None:
        """How a row's class fares in the role a column stands for.

        :param row: the row.
        :param column: the cell's column.
        :returns: the state; ``None`` for a column of no role, or a role the class does not declare.
        """
        if column == SCRAPER_ROLE_COLUMN:
            return row.scraper
        return row.wizard if column == WIZARD_ROLE_COLUMN else None

    # endregion
