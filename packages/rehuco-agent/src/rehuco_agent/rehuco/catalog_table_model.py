"""The bare resource table over the cache: one row per record, four columns (#377)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, override
from uuid import UUID

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QPersistentModelIndex, Qt
from rehuco_core import CatalogRow, RecordKind, catalog_type_fields

AUTHORS_COLUMN: Final = 0
TITLE_COLUMN: Final = 1
TYPE_COLUMN: Final = 2
PATH_COLUMN: Final = 3
COLUMN_TITLES: Final = ("Authors", "Title", "Type", "Path")
COLUMN_IDS: Final = tuple(title.lower() for title in COLUMN_TITLES)
"""What the filter line's ``columns:`` token calls each column (#398), in column order."""

AUTHORS_SEPARATOR: Final = ", "
"""Joins a record's authors into one cell, in the order the record lists them."""

PATH_ROLE: Final = Qt.ItemDataRole.UserRole
"""The role answering a row's absolute path -- what a double-click opens."""


@dataclass(frozen=True, slots=True)
class CatalogTotals:
    """What the rows a model holds add up to (#454). ``None`` is not ``0``: ``0`` is a measurement (an empty pack), and
    ``None`` is a record stating none, so a total says how many rows it left out.

    :param count: the rows.
    :param legacy: how many of them are legacy ``.tc`` files. Their sizes and image counts are old claims -- often a
        literal ``0`` -- so the totals below leave them out and the status line names them instead.
    :param size: the sum of every ``.rehu`` row's ``current_size`` that is not ``None``, in bytes.
    :param unmeasured_size: the ``.rehu`` rows with no ``current_size``.
    :param images: the sum of every ``.rehu`` row's ``current_count`` that is not ``None``.
    :param unmeasured_images: the ``.rehu`` rows of a type that declares ``current_count`` and state none.
    :param has_images: whether any ``.rehu`` row has a ``current_count`` or is of a type that declares one -- whether
        an image total means anything for these rows.
    """

    count: int = 0
    legacy: int = 0
    size: int = 0
    unmeasured_size: int = 0
    images: int = 0
    unmeasured_images: int = 0
    has_images: bool = False


class CatalogTableModel(QAbstractTableModel):
    """A read-only table over :class:`~rehuco_core.CatalogRow` entries.

    **Reset whenever the rows are replaced.** Updating in place -- rows renamed, moved, inserted and
    removed as the app announces them -- is the real browser's job (#379); this is the tracer's table, and
    a reset is the least that is correct.

    **Sorted here, not by a proxy and not by the query.** Every row is already in memory, so a header click
    is one Python sort on a precomputed, case-insensitive key per column -- tens of milliseconds at a hundred
    thousand rows, where a `QSortFilterProxyModel` calls back into :meth:`data` twice per comparison, and an
    ``ORDER BY`` would re-read the whole cache and reset the view. The sort a view asked for is kept and
    re-applied to every new set of rows; column ``-1`` is the cache's own order (root, then path).

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__source: list[CatalogRow] = []
        """The rows in the cache's own order -- what an unsorted view shows."""
        self.__rows: list[CatalogRow] = []
        self.__root_paths: dict[UUID, Path] = {}
        self.__totals = CatalogTotals()
        self.__sort_column = -1
        self.__sort_order = Qt.SortOrder.AscendingOrder

    @property
    def totals(self) -> CatalogTotals:
        """What the rows add up to, kept by the model so a status line reads it without calling :meth:`data`."""
        return self.__totals

    def set_rows(self, rows: Sequence[CatalogRow], root_paths: Mapping[UUID, Path]) -> None:
        """Replace every row, in the sort the view last asked for.

        :param rows: the rows, in the cache's order.
        :param root_paths: each root's folder by id, which is what turns a record's root-relative path
            into an absolute one.
        """
        self.beginResetModel()
        self.__source = list(rows)
        self.__root_paths = dict(root_paths)
        self.__totals = self.__totalled(self.__source)
        self.__rows = self.__sorted()
        self.endResetModel()

    @staticmethod
    def __totalled(rows: Sequence[CatalogRow]) -> CatalogTotals:
        """Add up ``rows`` in one pass; ``None`` is never read as ``0``."""
        declares_count: dict[str, bool] = {}
        size = unmeasured_size = images = unmeasured_images = legacy = 0
        has_images = False
        for entry in rows:
            record = entry.record
            if record.kind is RecordKind.TC:
                legacy += 1
                continue
            if record.current_size is None:
                unmeasured_size += 1
            else:
                size += record.current_size
            declared = declares_count.get(record.type)
            if declared is None:
                declared = declares_count[record.type] = "current_count" in catalog_type_fields(record.type)
            if record.current_count is not None:
                images += record.current_count
                has_images = True
            elif declared:
                unmeasured_images += 1
            has_images = has_images or declared
        return CatalogTotals(len(rows), legacy, size, unmeasured_size, images, unmeasured_images, has_images)

    @override
    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        """Order the rows by ``column``, ignoring case; a row's persistent indexes follow it, so the selection
        survives.

        :param column: the column to sort on; out of range (``-1``) is the cache's own order.
        :param order: ascending or descending.
        """
        self.__sort_column = column
        self.__sort_order = order
        self.layoutAboutToBeChanged.emit()
        persistent = self.persistentIndexList()
        followed = [self.__rows[index.row()] for index in persistent]
        self.__rows = self.__sorted()
        row_of = {id(entry): row for row, entry in enumerate(self.__rows)}
        self.changePersistentIndexList(
            persistent,
            [self.index(row_of[id(entry)], index.column()) for index, entry in zip(persistent, followed, strict=True)],
        )
        self.layoutChanged.emit()

    def __sorted(self) -> list[CatalogRow]:
        """The source rows in the current sort; a stable sort, so equal keys keep the cache's order."""
        if not 0 <= self.__sort_column < len(COLUMN_TITLES):
            return list(self.__source)
        column = self.__sort_column
        return sorted(
            self.__source,
            key=lambda entry: self.__cell(entry, column).casefold(),
            reverse=self.__sort_order == Qt.SortOrder.DescendingOrder,
        )

    @staticmethod
    def __cell(entry: CatalogRow, column: int) -> str:
        """What ``entry`` shows in ``column`` -- the one rule both the display and the sort key read.

        :param entry: the row.
        :param column: a column in range.
        :returns: the cell's text.
        """
        record = entry.record
        if column == AUTHORS_COLUMN:
            return AUTHORS_SEPARATOR.join(record.authors)
        if column == TITLE_COLUMN:
            # a record that could not be read has no title: its file name still says which it is
            return record.title or Path(record.path).name
        if column == TYPE_COLUMN:
            return record.type
        return f"{entry.root_label}/{record.path}"

    def absolute_path(self, row: int) -> Path | None:
        """Where a row's record lives on disk.

        :param row: the row.
        :returns: the record's absolute path, or ``None`` when ``row`` is out of range or its root is gone.
        """
        if not 0 <= row < len(self.__rows):
            return None
        entry = self.__rows[row]
        root = self.__root_paths.get(entry.root_id)
        return None if root is None else root / entry.record.path

    @override
    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.__rows)

    @override
    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(COLUMN_TITLES)

    @override
    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> str | None:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMN_TITLES[section]
        return None

    @override
    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if not index.isValid() or index.row() >= len(self.__rows):
            return None
        entry = self.__rows[index.row()]
        if role == PATH_ROLE:
            return self.absolute_path(index.row())
        if role == Qt.ItemDataRole.ToolTipRole and entry.record.error:
            return entry.record.error
        if role != Qt.ItemDataRole.DisplayRole or not 0 <= index.column() < len(COLUMN_TITLES):
            return None
        return self.__cell(entry, index.column())
