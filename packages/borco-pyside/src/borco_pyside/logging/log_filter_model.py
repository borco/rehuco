"""Narrows a log table to what is being looked for, without throwing anything away."""

import logging
from typing import override

from PySide6.QtCore import QModelIndex, QObject, QPersistentModelIndex, QSortFilterProxyModel

from .log_entry import LogEntry
from .log_model import LogModel

type ModelIndex = QModelIndex | QPersistentModelIndex
"""What Qt hands a model method; the persistent form arrives from a view holding onto an index."""


class LogFilterModel(QSortFilterProxyModel):
    """Shows the part of a :class:`~.log_model.LogModel` matching a level floor and a search string.

    **A floor, not a set of toggles.** Levels are ordered and a reader's question is almost always
    *"show me this and anything worse"* -- so one threshold, which a single control can express, and
    which cannot land in the contradictory states a checkbox per level allows (errors hidden while
    warnings show). A reader after exactly one level has the search box.

    **Filtering hides; it never discards.** The entries stay in the source model, so narrowing to
    errors and then widening again brings everything back -- including whatever arrived while the view
    was narrow. That is the difference between this and a level set on the handler, which would decide
    what is *kept* rather than what is shown, before anyone knew what they would want to look at.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__minimum_level = logging.NOTSET
        self.__search = ""

    @property
    def minimum_level(self) -> int:
        """The lowest level shown; anything below it is hidden. `logging.NOTSET` shows everything."""
        return self.__minimum_level

    @minimum_level.setter
    def minimum_level(self, level: int) -> None:
        """Show only records at ``level`` or above.

        :param level: a `logging` level number, not necessarily one of the named ones.
        """
        if level == self.__minimum_level:
            return
        self.__minimum_level = level
        self.__refilter()

    @property
    def search(self) -> str:
        """Substring a record's formatted message must contain, case-insensitively; empty matches all."""
        return self.__search

    @search.setter
    def search(self, search: str) -> None:
        """Show only records whose message contains ``search``.

        Matched against the formatted message rather than the raw one, so what a reader searches for
        is what the table shows them -- including the parts the format string added.

        :param search: the substring to look for; empty to stop searching.
        """
        if search == self.__search:
            return
        self.__search = search
        self.__refilter()

    def __refilter(self) -> None:
        """Re-evaluate every row against the current filters.

        ``invalidateFilter()`` and ``invalidateRowsFilter()`` are both deprecated in this Qt version;
        ``invalidate()`` is the plain equivalent. It re-sorts as well, which is harmless here -- this
        proxy never overrides ``lessThan``, so rows keep the source model's order, which for a log is
        the order things happened in.
        """
        self.invalidate()

    @override
    def filterAcceptsRow(self, source_row: int, source_parent: ModelIndex) -> bool:  # noqa: N802  (Qt API name)
        source = self.sourceModel()
        entry = source.data(source.index(source_row, 0, source_parent), LogModel.Roles.ENTRY)
        if not isinstance(entry, LogEntry):
            return super().filterAcceptsRow(source_row, source_parent)
        if entry.record.levelno < self.__minimum_level:
            return False
        return not self.__search or self.__search.casefold() in entry.message.casefold()
