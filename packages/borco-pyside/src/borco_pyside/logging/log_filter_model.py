"""Narrows a log table to what is being looked for, without throwing anything away."""

from collections.abc import Iterable
from typing import override

from PySide6.QtCore import QModelIndex, QObject, QPersistentModelIndex, QSortFilterProxyModel

from .log_entry import LogEntry
from .log_level_band import LogLevelBand
from .log_model import LogModel

type ModelIndex = QModelIndex | QPersistentModelIndex
"""What Qt hands a model method; the persistent form arrives from a view holding onto an index."""


class LogFilterModel(QSortFilterProxyModel):
    """Shows the part of a :class:`~.log_model.LogModel` in the chosen bands and matching a search.

    **Independent bands, not a floor.** Each :class:`~.log_level_band.LogLevelBand` is shown or hidden
    on its own, so a reader can ask for exactly the debugs -- with no infos, warnings or errors beside
    them, however many exist. A threshold cannot express that: *"debugs"* would drag in everything
    above them, which during a loud job is the noise the reader was trying to get out of the way. All
    four start shown; turning them all off shows nothing, which is a state a reader chose rather than
    one to be quietly corrected.

    **Filtering hides; it never discards.** The entries stay in the source model, so narrowing to
    errors and then widening again brings everything back -- including whatever arrived while the view
    was narrow. That is the difference between this and a level set on the handler, which would decide
    what is *kept* rather than what is shown, before anyone knew what they would want to look at.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__visible_bands = frozenset(LogLevelBand)
        self.__search = ""

    @property
    def visible_bands(self) -> frozenset[LogLevelBand]:
        """The bands currently shown; every band to begin with, and possibly none."""
        return self.__visible_bands

    @visible_bands.setter
    def visible_bands(self, bands: Iterable[LogLevelBand]) -> None:
        """Show exactly these bands and hide the rest.

        :param bands: the bands to show; empty hides everything.
        """
        replacement = frozenset(bands)
        if replacement == self.__visible_bands:
            return
        self.__visible_bands = replacement
        self.__refilter()

    def set_band_visible(self, band: LogLevelBand, visible: bool) -> None:
        """Show or hide one band, leaving the other three as they are.

        What one toggle button drives -- so a surface wires four buttons to one method rather than
        four, and the bands stay independent of each other's state.

        :param band: the band to change.
        :param visible: whether to show it.
        """
        if visible:
            self.visible_bands = self.__visible_bands | {band}
        else:
            self.visible_bands = self.__visible_bands - {band}

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
        if LogLevelBand.of(entry.record.levelno) not in self.__visible_bands:
            return False
        return not self.__search or self.__search.casefold() in entry.message.casefold()
