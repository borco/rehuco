"""The Scrapers table, promoted to a `~.settings_frame_filter.ValueControl` so its **Use browser**
column gets the same dirty highlighting and Apply/Reset/Defaults header every other settings value
does (#342, #278).
"""

from typing import override

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QStyleOptionViewItem, QTableView, QWidget

from .scrapers_scraper_column_delegate import ScrapersScraperColumnDelegate
from .scrapers_table_model import SCRAPER_COLUMN, ScrapersTableModel


class ScrapersTableView(QTableView):
    """A plain `QTableView`, structurally satisfying `~.settings_frame_filter.ValueControl` the same
    way `~.color_swatch_button.ColorSwatchButton` does: its "value" is the staged **Use browser** set,
    which `~.settings_frame_filter.SettingsFrameFilter` cannot read off a table by any generic rule.

    Also gives the mouse a pointing-hand cursor over a Scraper cell's link, the same hover cue
    `~borco_pyside.widgets.ElidedLabel`'s own links give -- `QTableView` has no concept of "this cell is
    a link" to hand that off to, since the link itself is delegate-painted rich text
    (`~.scrapers_scraper_column_delegate.ScrapersScraperColumnDelegate`), not a widget with its own
    cursor handling.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)

    @override
    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802  (Qt API name)
        super().mouseMoveEvent(event)
        index = self.indexAt(event.position().toPoint())
        delegate = self.itemDelegateForColumn(SCRAPER_COLUMN)
        over_link = (
            index.isValid()
            and index.column() == SCRAPER_COLUMN
            and isinstance(delegate, ScrapersScraperColumnDelegate)
            and bool(delegate.link_at(self.__option_for(index), index, event.position()))
        )
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor if over_link else Qt.CursorShape.ArrowCursor)

    def __option_for(self, index: QModelIndex | QPersistentModelIndex) -> QStyleOptionViewItem:
        """A style option over ``index``'s current cell rect, font and palette -- the same three
        properties `~.scrapers_scraper_column_delegate.ScrapersScraperColumnDelegate.link_at` reads to
        rebuild the exact document :meth:`ScrapersScraperColumnDelegate.paint` drew."""
        option = QStyleOptionViewItem()
        option.rect = self.visualRect(index)
        option.font = self.font()
        option.palette = self.palette()
        return option

    def settings_value(self) -> object:
        """The staged **Use browser** set, for the frame snapshot."""
        model = self.model()
        return model.browser_scrapers() if isinstance(model, ScrapersTableModel) else frozenset()

    def set_settings_value(self, value: object) -> None:
        """Write a set `settings_value` returned earlier back into the model.

        :param value: a `frozenset` of scraper keys.
        """
        model = self.model()
        if isinstance(model, ScrapersTableModel) and isinstance(value, frozenset):
            model.set_browser_scrapers(value)
