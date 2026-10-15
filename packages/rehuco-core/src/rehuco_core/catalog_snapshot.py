"""The catalog's rows held in memory, filtered there rather than by the cache (#455).

A browser's filter line used to read the cache on every settled keystroke; it now filters the rows the last read
loaded. **One matching rule, two implementations**: :class:`CatalogMatcher` must pick exactly the rows
:meth:`~rehuco_core.CatalogCache.rows` picks for the same :class:`~rehuco_core.CatalogQuery` -- a ``LIKE`` over
folded text, SQLite's ASCII-only ``NOCASE``, the ``folder`` key range -- and a contract test runs both, so neither
can drift.

**Building is the cost, so it is done once per read, off the GUI thread**: :meth:`CatalogSnapshot.build` folds every
row's searchable text into a :class:`CatalogSearchKey`, and :meth:`CatalogSnapshot.patched` brings a snapshot up to
date after a few rows changed. Both are meant for a worker; :meth:`CatalogSnapshot.select` is meant for the GUI
thread, per keystroke.

**A key adds one object the cyclic collector tracks, and no more** (#500): it holds its row, so nothing pairs the
two, and its names are tuples of strings, which Python never tracks. A read's rows are walked by the collector's first
pass once it is back on (:meth:`~rehuco_agent.rehuco.catalog_rows_loader.CatalogRowsLoader.collector_paused`), holding
the GIL, so every tracked object a row makes is a stall on the GUI thread.
"""

import string
from collections.abc import Collection, Iterable, KeysView
from dataclasses import dataclass
from operator import attrgetter
from typing import Final
from uuid import UUID

from borco_core import fold

from .rehudb import KEY_RANGE_END, CatalogField, CatalogQuery, CatalogRow, catalog_path_key

ASCII_LOWER: Final = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)
"""Lowers ASCII letters and nothing else -- what SQLite's ``LIKE`` and ``NOCASE`` fold, without ICU."""


# one field per thing a query compares, so a match reads each without a lookup
@dataclass(frozen=True, slots=True)
class CatalogSearchKey:  # pylint: disable=too-many-instance-attributes
    """One row's text as a query compares it, folded once, with the row it was folded from.

    :param row: the row.
    :param title: the title, folded (:func:`borco_core.fold`) and then ASCII-lowered, as ``LIKE`` compares it.
    :param path: the root-relative path, the same way.
    :param type: the type, ASCII-lowered, as ``NOCASE`` compares it.
    :param label: the root's label, the same way.
    :param path_key: the path as the filesystem compares it (:func:`~rehuco_core.catalog_path_key`).
    :param authors: every author, folded -- a tuple, not a set: the collector tracks every set, never a tuple of
        strings, and a record names a few.
    :param tags: every tag, folded.
    :param publishers: every publisher, folded.
    """

    row: CatalogRow
    title: str
    path: str
    type: str
    label: str
    path_key: str
    authors: tuple[str, ...]
    tags: tuple[str, ...]
    publishers: tuple[str, ...]

    @classmethod
    def of(cls, row: CatalogRow) -> CatalogSearchKey:
        """The key of ``row``.

        :param row: a row the cache read.
        :returns: its key.
        """
        record = row.record
        return cls(
            row,
            fold(record.title).translate(ASCII_LOWER),
            fold(record.path).translate(ASCII_LOWER),
            record.type.translate(ASCII_LOWER),
            row.root_label.translate(ASCII_LOWER),
            catalog_path_key(record.path),
            tuple(fold(name) for name in record.authors),
            tuple(fold(name) for name in record.tags),
            tuple(fold(name) for name in record.publishers),
        )


class CatalogMatcher:
    """A :class:`~rehuco_core.CatalogQuery` compiled to test :class:`CatalogSearchKey` objects -- the cache's ``WHERE``
    (:meth:`~rehuco_core.CatalogCache.rows`) in Python.

    Every term must be found in the title or the path, and every token must match. A whole list is narrowed one
    condition at a time (:meth:`pick`): a comprehension per condition measured 6-17 ms per query at 100k rows, against
    50-120 ms testing each row against every condition.

    :param query: what to match.
    """

    def __init__(self, query: CatalogQuery) -> None:
        # a LIKE pattern is the folded term with its wildcards escaped, so it is found as a plain substring; LIKE then
        # ignores ASCII case on both sides
        self.__terms: Final = tuple(fold(term).translate(ASCII_LOWER) for term in query.terms)
        self.__types: Final = tuple(
            value.translate(ASCII_LOWER) for field, value in query.tokens if field is CatalogField.TYPE
        )
        self.__values: Final = tuple(
            (attrgetter(field.value), fold(value))
            for field, value in query.tokens
            if field in (CatalogField.AUTHORS, CatalogField.TAGS, CatalogField.PUBLISHERS)
        )
        self.__folders: Final = tuple(
            self.__folder_ranges(value) for field, value in query.tokens if field is CatalogField.FOLDER
        )

    def matches(self, key: CatalogSearchKey) -> bool:
        """Whether the row ``key`` describes matches the query.

        :param key: the row's key.
        :returns: whether it does.
        """
        return bool(self.pick((key,)))

    def pick(self, keys: Iterable[CatalogSearchKey]) -> list[CatalogRow]:
        """The rows of ``keys`` the query matches, in their order.

        :param keys: the rows' keys.
        :returns: the matching rows.
        """
        picked = list(keys)
        for term in self.__terms:
            picked = [key for key in picked if term in key.title or term in key.path]
        for value in self.__types:
            picked = [key for key in picked if key.type == value]
        for names, value in self.__values:
            picked = [key for key in picked if value in names(key)]
        for ranges in self.__folders:
            picked = [key for key in picked if self.__in_folder(key, ranges)]
        return [key.row for key in picked]

    @staticmethod
    def __folder_ranges(value: str) -> tuple[tuple[str, str | None], ...]:
        """Every way a ``folder`` token's value splits into a root's label and a path beneath it, as the cache tries
        them.

        :param value: the token's value, ``/``-separated.
        :returns: per split, the ASCII-lowered label and the path's key prefix -- ``None`` for the root itself.
        """
        parts = value.strip("/").split("/")
        ranges: list[tuple[str, str | None]] = []
        for split in range(1, len(parts) + 1):
            label, relative = "/".join(parts[:split]), "/".join(parts[split:])
            ranges.append((label.translate(ASCII_LOWER), catalog_path_key(f"{relative}/") if relative else None))
        return tuple(ranges)

    @staticmethod
    def __in_folder(key: CatalogSearchKey, ranges: tuple[tuple[str, str | None], ...]) -> bool:
        """Whether the row lies under any of a ``folder`` token's splits.

        :param key: the row's key.
        :param ranges: what :meth:`__folder_ranges` made of the token.
        :returns: whether it does -- by the same key range the cache reads, not a prefix test, so the two agree on
            every key.
        """
        return any(
            key.label == label and (prefix is None or prefix <= key.path_key < prefix + KEY_RANGE_END)
            for label, prefix in ranges
        )


class CatalogSnapshot:
    """Every row of one read of the catalog, in the cache's order, each with its :class:`CatalogSearchKey`.

    Never changed once built: a change makes a new snapshot (:meth:`patched`), so a worker can build the next one while
    the GUI thread still selects from this one.

    :param keys: every row's key, in the cache's order.
    :param root_ids: the roots' ids in the roots' order, which places a row a patch adds where the cache would.
    """

    def __init__(self, keys: Iterable[CatalogSearchKey], root_ids: Iterable[UUID]) -> None:
        self.__keys: Final = tuple(keys)
        self.__rows: Final = tuple(key.row for key in self.__keys)
        self.__root_ids: Final = tuple(root_ids)
        self.__positions: Final = {row.resource_id: position for position, row in enumerate(self.__rows)}

    @classmethod
    def build(cls, rows: Iterable[CatalogRow], root_ids: Iterable[UUID]) -> CatalogSnapshot:
        """Key every row of a read -- the slow half, meant for a worker.

        :param rows: the rows, in the cache's order.
        :param root_ids: the roots' ids, in the roots' order.
        :returns: the snapshot.
        """
        return cls((CatalogSearchKey.of(row) for row in rows), root_ids)

    @property
    def rows(self) -> tuple[CatalogRow, ...]:
        """Every row, in the cache's order."""
        return self.__rows

    @property
    def root_ids(self) -> tuple[UUID, ...]:
        """The roots' ids, in the roots' order."""
        return self.__root_ids

    @property
    def ids(self) -> KeysView[int]:
        """Every row's id, as a view a membership test on costs nothing to make."""
        return self.__positions.keys()

    def __len__(self) -> int:
        """How many rows it holds."""
        return len(self.__rows)

    def select(self, query: CatalogQuery, ids: Collection[int] | None = None) -> list[CatalogRow]:
        """The rows ``query`` matches, in the cache's order -- what :meth:`~rehuco_core.CatalogCache.rows` reads.

        :param query: what to match.
        :param ids: only these rows, for an update in place; every row when ``None``.
        :returns: the rows.
        """
        matcher = CatalogMatcher(query)
        if ids is None:
            return matcher.pick(self.__keys)
        positions = sorted(self.__positions[resource_id] for resource_id in ids if resource_id in self.__positions)
        return matcher.pick(self.__keys[position] for position in positions)

    def patched(self, affected: Collection[int], fresh: Iterable[CatalogRow]) -> CatalogSnapshot:
        """This snapshot after a change touched ``affected`` rows -- meant for a worker, since it copies every row.

        :param affected: the ids of every row the change may have touched.
        :param fresh: those of them that exist now, as the cache reads them.
        :returns: the new snapshot; rows the change removed are gone, and changed or added ones sit where the cache
            orders them.
        """
        changed = {row.resource_id: row for row in fresh}
        gone = set(affected) | changed.keys()
        kept = [key for key in self.__keys if key.row.resource_id not in gone]
        kept += [CatalogSearchKey.of(row) for row in changed.values()]
        positions = {root_id: position for position, root_id in enumerate(self.__root_ids)}
        # mostly sorted already, which the sort runs through in near-linear time
        kept.sort(key=lambda key: (positions.get(key.row.root_id, len(positions)), key.path_key))
        return CatalogSnapshot(kept, self.__root_ids)
