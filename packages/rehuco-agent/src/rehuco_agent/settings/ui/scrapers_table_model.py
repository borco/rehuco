"""The scripts folder's scrapers as read-only table rows, one row per file
([[acquisition-tooling#scraper-registry]]).
"""

from typing import Any, Final, override

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QPersistentModelIndex, Qt
from PySide6.QtGui import QBrush, QColor

from ...fields.colors import ERROR_COLOR
from ...scraping.registry import LoadedScraperModule

FILE_COLUMN: Final = 0
SCRAPERS_COLUMN: Final = 1
ERROR_COLUMN: Final = 2
COLUMN_COUNT: Final = 3
COLUMN_TITLES: Final = ("File", "Scrapers", "Error")

NO_SCRAPERS_TEXT: Final = "—"
"""What the Scrapers column shows for a file that loaded cleanly but defines no `SiteScraper` -- not an
error, simply a file contributing nothing yet."""

type ModelIndex = QModelIndex | QPersistentModelIndex
"""What Qt hands a model method; the persistent form arrives from a view holding onto an index."""


class ScrapersTableModel(QAbstractTableModel):
    """A read-only view over `rehuco_agent.scraping.registry.ScraperRegistry.modules`.

    Rebuilt as a whole on every :meth:`set_modules` -- unlike `rehuco_agent.tasks.TaskQueueModel`, this
    table changes only on an explicit Reload or Save, never live, so there is no burst of small updates
    worth diffing against.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__modules: tuple[LoadedScraperModule, ...] = ()

    def set_modules(self, modules: tuple[LoadedScraperModule, ...]) -> None:
        """Replace every row.

        :param modules: the rows to show, in scan order.
        """
        self.beginResetModel()
        self.__modules = modules
        self.endResetModel()

    # region Qt model interface

    @override
    def rowCount(self, parent: ModelIndex = QModelIndex()) -> int:  # noqa: N802  (Qt API name)
        return 0 if parent.isValid() else len(self.__modules)

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
    def data(self, index: ModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        module = self.__modules[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return self.__display(module, index.column())
        if role == Qt.ItemDataRole.ForegroundRole and index.column() == ERROR_COLUMN and module.error:
            return QBrush(QColor(ERROR_COLOR))
        return None

    @staticmethod
    def __display(module: LoadedScraperModule, column: int) -> str:
        """What a cell's plain text is; the column is one of the three, since a view never asks for
        an index this model did not hand it."""
        if column == FILE_COLUMN:
            return module.path.name
        if column == SCRAPERS_COLUMN:
            return ScrapersTableModel.__scrapers_text(module)
        return module.error or ""

    @staticmethod
    def __scrapers_text(module: LoadedScraperModule) -> str:
        """What the Scrapers column shows for one row.

        :param module: the row.
        :returns: every scraper's ``label (publisher)``, comma-joined, or :data:`NO_SCRAPERS_TEXT`.
        """
        if not module.scrapers:
            return NO_SCRAPERS_TEXT
        return ", ".join(f"{scraper.label} ({scraper.publisher})" for scraper in module.scrapers)

    # endregion
