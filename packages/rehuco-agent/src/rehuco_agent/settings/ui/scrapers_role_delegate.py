"""Draws the Scrapers table's two role columns: the glyph of how a class fares as a scraper or as a scraper wizard,
centered in its cell (#683).

Installed with `QTableView.setItemDelegateForColumn` on each of the two, as the checkbox's and the link's delegates
are. A decoration handed to the base delegate is placed beside the cell's *text*, which these columns have none of, so
the glyph is drawn here; it takes the row's own text color, as the checksum glyphs do.
"""

from typing import Final, override

from borco_pyside.widgets import RowBandDelegate
from PySide6.QtCore import QModelIndex, QObject, QPersistentModelIndex, QRect
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QStyleOptionViewItem

from ...svg_icon_cache import SvgIconCache
from .scrapers_table_model import ROLE_ICON_ROLE

ROLE_ICON_SIZE: Final = 16
"""The side of a role glyph, in pixels: the checksum glyphs' own size."""


class ScrapersRoleDelegate(RowBandDelegate):
    """Paints a role cell's glyph over the row's band; a cell with none stays empty.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__icons: Final = SvgIconCache()

    @override
    def paint(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> None:
        path = index.data(ROLE_ICON_ROLE)
        painter.save()
        try:
            color = self.paint_band(painter, option, index)
            if path:
                self.__icons.icon(path, color).paint(painter, self.icon_rect(option.rect))
        finally:
            painter.restore()

    @staticmethod
    def icon_rect(cell: QRect) -> QRect:
        """A glyph-sized rect in the middle of ``cell``.

        :param cell: the item's rect.
        :returns: the rect the glyph is drawn in, never larger than the cell.
        """
        side = min(ROLE_ICON_SIZE, cell.width(), cell.height())
        rect = QRect(0, 0, side, side)
        rect.moveCenter(cell.center())
        return rect
