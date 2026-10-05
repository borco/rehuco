"""A table browser's model over the cache: one row per record, a column per field the cache holds (#377, #379)."""

from bisect import bisect_right
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any, Final, override
from uuid import UUID

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QPersistentModelIndex, Qt
from rehuco_core import (
    CatalogRow,
    RecordKind,
    catalog_path_key,
    catalog_type_fields,
    natural_path_sort_key,
    natural_sort_key,
)

LIST_SEPARATOR: Final = ", "
"""Joins a record's authors, tags or levels into one cell, in the order the record lists them."""

PATH_ROLE: Final = Qt.ItemDataRole.UserRole
"""The role answering a row's absolute path -- what a double-click opens."""

LEGACY_FORMAT: Final = "tc"
"""What the Format column holds for a legacy ``.tc``: a format of its own, not "version 0"."""

UNKNOWN_FORMAT: Final = "?"
"""What the Format column holds for a ``.rehu`` whose version the cache does not know -- unreadable, or not read since
the cache learned to store it -- so it is never mistaken for a ``.tc``."""

type RowKey = tuple[UUID, str]
"""A resource as a browser names it to others: its root's id and its root-relative path (#379). Release 0.4.0 re-keys
the one place that resolves it, not every consumer."""


class CatalogColumn(IntEnum):
    """The table's columns, in their logical order. The first four are #377's and keep their places, so a header state
    saved before the others existed restores onto the same columns."""

    AUTHORS = 0
    TITLE = 1
    TYPE = 2
    PATH = 3
    PUBLISHER = 4
    URL = 5
    TAGS = 6
    RELEASED = 7
    SIZE = 8
    UPDATED = 9
    FORMAT = 10
    ADVERTISED_DURATION = 11
    ORIGINAL_DURATION = 12
    CURRENT_DURATION = 13
    LEVEL = 14
    ADVERTISED_COUNT = 15
    CURRENT_COUNT = 16


@dataclass(frozen=True, slots=True)
class ColumnSpec:
    """What one column shows and how it sorts.

    :param title: the header.
    :param value: the cell's actual value -- an ``int`` of bytes or seconds stays an ``int``, for a delegate to format
        and the sort to compare; ``None`` (or ``""``) where the record states none.
    :param default_visible: whether a plain browser starts with it shown.
    :param numeric: whether it is a number, aligned right.
    :param sort_key: what a present value sorts by; the value itself unless given.
    :param missing_rank: where a value sorts that is not one: ``0`` for a value, and ascending after every value, in
        either order, for each kind of missing one.
    """

    title: str
    value: Callable[[CatalogRow], object]
    default_visible: bool = True
    numeric: bool = False
    sort_key: Callable[[Any], Any] | None = None
    missing_rank: Callable[[object], int] = lambda value: 1 if value is None or value == "" else 0


def title_of(entry: CatalogRow) -> str:
    """A record's title -- or, for one that could not be read and has none, its file name, which still says which it
    is."""
    return entry.record.title or Path(entry.record.path).name


def format_of(entry: CatalogRow) -> int | str:
    """Which file format a record is in: its ``.rehu`` version, :data:`LEGACY_FORMAT` or :data:`UNKNOWN_FORMAT` --
    read from ``kind`` and the version together, never from a missing version alone."""
    record = entry.record
    if record.kind is RecordKind.TC:
        return LEGACY_FORMAT
    return UNKNOWN_FORMAT if record.format_version is None else record.format_version


def format_rank(value: object) -> int:
    """A version sorts first, then every ``.tc``, then every version not known."""
    return {LEGACY_FORMAT: 1, UNKNOWN_FORMAT: 2}.get(value, 0) if isinstance(value, str) else 0


def joined(values: Iterable[str]) -> str:
    """A list as one cell."""
    return LIST_SEPARATOR.join(values)


def folded(value: str) -> str:
    """A text cell's sort key: case ignored."""
    return value.casefold()


COLUMNS: Final[Mapping[CatalogColumn, ColumnSpec]] = {
    CatalogColumn.AUTHORS: ColumnSpec("Authors", lambda entry: joined(entry.record.authors), sort_key=folded),
    CatalogColumn.TITLE: ColumnSpec("Title", title_of, sort_key=folded),
    CatalogColumn.TYPE: ColumnSpec("Type", lambda entry: entry.record.type, sort_key=folded),
    CatalogColumn.PATH: ColumnSpec(
        "Path", lambda entry: f"{entry.root_label}/{entry.record.path}", sort_key=natural_path_sort_key
    ),
    CatalogColumn.PUBLISHER: ColumnSpec("Publisher", lambda entry: entry.record.publisher, sort_key=folded),
    CatalogColumn.URL: ColumnSpec("URL", lambda entry: entry.record.url, default_visible=False),
    CatalogColumn.TAGS: ColumnSpec("Tags", lambda entry: joined(entry.record.tags), sort_key=folded),
    CatalogColumn.RELEASED: ColumnSpec("Released", lambda entry: entry.record.released),
    CatalogColumn.SIZE: ColumnSpec("Size", lambda entry: entry.record.current_size, numeric=True),
    CatalogColumn.UPDATED: ColumnSpec("Updated", lambda entry: entry.record.updated),
    CatalogColumn.FORMAT: ColumnSpec("Format", format_of, numeric=True, missing_rank=format_rank),
    CatalogColumn.ADVERTISED_DURATION: ColumnSpec(
        "Advertised duration", lambda entry: entry.record.advertised_duration, default_visible=False, numeric=True
    ),
    CatalogColumn.ORIGINAL_DURATION: ColumnSpec(
        "Original duration", lambda entry: entry.record.original_duration, default_visible=False, numeric=True
    ),
    CatalogColumn.CURRENT_DURATION: ColumnSpec(
        "Current duration", lambda entry: entry.record.current_duration, default_visible=False, numeric=True
    ),
    CatalogColumn.LEVEL: ColumnSpec(
        "Level", lambda entry: joined(entry.record.level), default_visible=False, sort_key=folded
    ),
    CatalogColumn.ADVERTISED_COUNT: ColumnSpec(
        "Advertised count",
        lambda entry: entry.record.advertised_count,
        default_visible=False,
        numeric=True,
        # a claim such as "500+" sorts by its number, not as text
        sort_key=natural_sort_key,
    ),
    CatalogColumn.CURRENT_COUNT: ColumnSpec(
        "Current count", lambda entry: entry.record.current_count, default_visible=False, numeric=True
    ),
}
"""Every column, in :class:`CatalogColumn` order."""

DEFAULT_HIDDEN: Final = frozenset(column for column, spec in COLUMNS.items() if not spec.default_visible)
"""The columns a plain browser starts with hidden: the URL, and the type-specific ones a preset shows (#400)."""

TYPE_COLUMNS: Final[Mapping[str, CatalogColumn]] = {
    "advertised_duration": CatalogColumn.ADVERTISED_DURATION,
    "original_duration": CatalogColumn.ORIGINAL_DURATION,
    "current_duration": CatalogColumn.CURRENT_DURATION,
    "level": CatalogColumn.LEVEL,
    "advertised_count": CatalogColumn.ADVERTISED_COUNT,
    "current_count": CatalogColumn.CURRENT_COUNT,
}
"""The column each of the cache's type-specific fields (:data:`~rehuco_core.TYPE_FIELD_COLUMNS`) shows in, by the
field's name -- what turns a type's :func:`~rehuco_core.catalog_type_fields` into columns (#400)."""


@dataclass(frozen=True, slots=True)
class Descending:
    """A sort key turned round, so one key function serves both orders -- for :func:`sorted` and for :func:`bisect`
    alike, which takes no ``reverse``.

    :param value: the key it wraps.
    """

    value: Any

    def __lt__(self, other: Descending) -> bool:
        return other.value < self.value


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


class CatalogTableModel(QAbstractTableModel):  # pylint: disable=too-many-instance-attributes
    """A read-only table over :class:`~rehuco_core.CatalogRow` entries.

    **Cells hold values, delegates format them.** A size is its ``int`` of bytes and a duration its seconds, so two
    sizes that read alike on screen still sort apart, and a delegate on the view says how each reads.

    **Reset only when every row is replaced** (:meth:`set_rows`, after a scan or a new filter). What the app itself
    renames, writes or deletes arrives through :meth:`update_rows`: each row it touched is changed, moved, inserted or
    removed where it stands, so a selection survives, and the totals are adjusted by that row alone -- never recomputed.

    **Sorted here, not by a proxy and not by the query.** Every row is already in memory, so a header click is one
    Python sort on a typed key per column, where a `QSortFilterProxyModel` calls back into :meth:`data` twice per
    comparison and an ``ORDER BY`` would re-read the whole cache and reset the view. A missing value sorts after every
    value in either order. The sort a view asked for is kept and applied to new rows; column ``-1`` is the cache's own
    order (root, then path).

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__source: list[CatalogRow] = []
        """The rows in the cache's own order -- what an unsorted view shows."""
        self.__rows: list[CatalogRow] = []
        self.__by_id: dict[int, CatalogRow] = {}
        self.__root_paths: dict[UUID, Path] = {}
        self.__root_positions: dict[UUID, int] = {}
        self.__sort_column = -1
        self.__sort_order = Qt.SortOrder.AscendingOrder
        self.__declares_count: dict[str, bool] = {}
        self.__count = self.__legacy = self.__size = self.__unmeasured_size = 0
        self.__images = self.__unmeasured_images = self.__image_rows = 0

    @property
    def totals(self) -> CatalogTotals:
        """What the rows add up to, kept by the model so a status line reads it without calling :meth:`data`."""
        return CatalogTotals(
            self.__count,
            self.__legacy,
            self.__size,
            self.__unmeasured_size,
            self.__images,
            self.__unmeasured_images,
            self.__image_rows > 0,
        )

    def set_rows(self, rows: Sequence[CatalogRow], root_paths: Mapping[UUID, Path]) -> None:
        """Replace every row, in the sort the view last asked for.

        :param rows: the rows, in the cache's order.
        :param root_paths: each root's folder by id, in the roots' order -- which is what turns a record's
            root-relative path into an absolute one, and places a row inserted later where the cache would.
        """
        self.beginResetModel()
        self.__source = list(rows)
        self.__by_id = {entry.resource_id: entry for entry in self.__source}
        self.__root_paths = dict(root_paths)
        self.__root_positions = {root_id: position for position, root_id in enumerate(root_paths)}
        self.__count = self.__legacy = self.__size = self.__unmeasured_size = 0
        self.__images = self.__unmeasured_images = self.__image_rows = 0
        for entry in self.__source:
            self.__account(entry, 1)
        self.__rows = self.__sorted()
        self.endResetModel()

    def update_rows(self, affected: Iterable[int], fresh: Sequence[CatalogRow]) -> None:
        """Bring the rows a change touched up to date in place -- never a reset (#379).

        :param affected: the ids of every row the change may have touched, whether or not this model shows it.
        :param fresh: those of them that exist and match this model's query now, as the cache reads them.
        """
        current = {entry.resource_id: entry for entry in fresh}
        for resource_id in sorted(set(affected) | set(current)):
            old, new = self.__by_id.get(resource_id), current.get(resource_id)
            if old is not None and new is not None:
                self.__replace(old, new)
            elif old is not None:
                self.__remove(old)
            elif new is not None:
                self.__insert(new)

    def row_key(self, row: int) -> RowKey | None:
        """Which resource a row is, as a browser names it to others.

        :param row: the row.
        :returns: its root's id and root-relative path; ``None`` out of range.
        """
        if not 0 <= row < len(self.__rows):
            return None
        entry = self.__rows[row]
        return entry.root_id, entry.record.path

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

    # region Sorting

    @override
    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        """Order the rows by ``column``; a row's persistent indexes follow it, so the selection survives.

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
        if not self.__sorting():
            return list(self.__source)
        return sorted(self.__source, key=self.__sort_key)

    def __sorting(self) -> bool:
        """Whether a column is sorted on, rather than the cache's own order shown."""
        return 0 <= self.__sort_column < len(COLUMNS)

    def __sort_key(self, entry: CatalogRow) -> tuple[Any, ...]:
        """Where ``entry`` sorts in the current order: its column's value, missing ones after every value either way
        round, then the cache's order between equals.

        :param entry: the row.
        :returns: its key.
        """
        if not self.__sorting():
            return self.__cache_key(entry)
        spec = COLUMNS[CatalogColumn(self.__sort_column)]
        value = spec.value(entry)
        rank = spec.missing_rank(value)
        if rank:
            return rank, 0, self.__cache_key(entry)
        key = spec.sort_key(value) if spec.sort_key is not None else value
        if self.__sort_order == Qt.SortOrder.DescendingOrder:
            key = Descending(key)
        return 0, key, self.__cache_key(entry)

    def __cache_key(self, entry: CatalogRow) -> tuple[int, str]:
        """Where the cache would put ``entry``: by its root's position, then by its path's key."""
        position = self.__root_positions.get(entry.root_id, len(self.__root_positions))
        return position, catalog_path_key(entry.record.path)

    # endregion

    # region Updating in place

    def __replace(self, old: CatalogRow, new: CatalogRow) -> None:
        """Show ``new`` in ``old``'s row, moving it where the sort now puts it."""
        # the containers through locals: pylint_qt reads a subscript on a QObject's attribute as a signal's
        rows, source, by_id = self.__rows, self.__source, self.__by_id
        self.__account(old, -1)
        self.__account(new, 1)
        by_id[new.resource_id] = new
        # a rename changes where the cache would put it, too
        source.remove(old)
        source.insert(bisect_right(source, self.__cache_key(new), key=self.__cache_key), new)
        row = rows.index(old)
        rows.pop(row)
        target = bisect_right(rows, self.__sort_key(new), key=self.__sort_key)
        if target == row:
            rows.insert(row, new)
        else:
            rows.insert(row, old)
            # Qt names the row the moved one goes *before*, counted before it left
            self.beginMoveRows(QModelIndex(), row, row, QModelIndex(), target + 1 if target > row else target)
            rows.pop(row)
            rows.insert(target, new)
            self.endMoveRows()
            row = target
        self.dataChanged.emit(self.index(row, 0), self.index(row, len(COLUMNS) - 1))

    def __insert(self, new: CatalogRow) -> None:
        """Show a row this model did not have, where the sort puts it."""
        rows, source, by_id = self.__rows, self.__source, self.__by_id
        self.__account(new, 1)
        by_id[new.resource_id] = new
        source.insert(bisect_right(source, self.__cache_key(new), key=self.__cache_key), new)
        target = bisect_right(rows, self.__sort_key(new), key=self.__sort_key)
        self.beginInsertRows(QModelIndex(), target, target)
        rows.insert(target, new)
        self.endInsertRows()

    def __remove(self, old: CatalogRow) -> None:
        """Drop a row that is gone or no longer matches."""
        rows, by_id = self.__rows, self.__by_id
        row = rows.index(old)
        self.beginRemoveRows(QModelIndex(), row, row)
        rows.pop(row)
        self.__source.remove(old)
        by_id.pop(old.resource_id)
        self.__account(old, -1)
        self.endRemoveRows()

    def __account(self, entry: CatalogRow, sign: int) -> None:
        """Add one row to the totals, or with ``sign`` ``-1`` take it out -- the one rule both a reset and an update in
        place keep them by; ``None`` is never read as ``0``."""
        record = entry.record
        self.__count += sign
        if record.kind is RecordKind.TC:
            self.__legacy += sign
            return
        if record.current_size is None:
            self.__unmeasured_size += sign
        else:
            self.__size += sign * record.current_size
        declares = self.__declares_count
        declared = declares.get(record.type)
        if declared is None:
            declared = declares[record.type] = "current_count" in catalog_type_fields(record.type)
        if record.current_count is not None:
            self.__images += sign * record.current_count
        elif declared:
            self.__unmeasured_images += sign
        if record.current_count is not None or declared:
            self.__image_rows += sign

    # endregion

    # region Qt

    @override
    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.__rows)

    @override
    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(COLUMNS)

    @override
    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> str | None:
        if (
            orientation == Qt.Orientation.Horizontal
            and role == Qt.ItemDataRole.DisplayRole
            and 0 <= section < len(COLUMNS)
        ):
            return COLUMNS[CatalogColumn(section)].title
        return None

    @override
    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if not index.isValid() or index.row() >= len(self.__rows) or not 0 <= index.column() < len(COLUMNS):
            return None
        entry = self.__rows[index.row()]
        column = CatalogColumn(index.column())
        if role == PATH_ROLE:
            return self.absolute_path(index.row())
        if role == Qt.ItemDataRole.DisplayRole:
            value = COLUMNS[column].value(entry)
            return None if value == "" else value
        if role == Qt.ItemDataRole.ToolTipRole:
            return self.__tooltip(entry, column)
        if role == Qt.ItemDataRole.TextAlignmentRole and COLUMNS[column].numeric:
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        return None

    @staticmethod
    def __tooltip(entry: CatalogRow, column: CatalogColumn) -> str | None:
        """What hovering a cell says: why its record could not be read, else what its formatting hides."""
        record = entry.record
        if record.error:
            return record.error
        if column is CatalogColumn.SIZE and record.current_size is not None:
            return f"{record.current_size:,} bytes"
        if column is CatalogColumn.FORMAT and format_of(entry) == UNKNOWN_FORMAT:
            return "Not read since the cache began recording format versions; a scan reads it."
        return None

    # endregion
