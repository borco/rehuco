"""Draws the Scrapers table's Source and Error columns (#278) -- the Scraper column has its own delegate
(`~.scrapers_scraper_column_delegate.ScrapersScraperColumnDelegate`, for a row's site link) and so does
**Use browser** (`~.scrapers_checkbox_delegate.ScrapersCheckboxDelegate`), both via
`QTableView.setItemDelegateForColumn`; this one is the view's general delegate, for what neither wants.

**Mostly, nothing is overridden.** `QStyledItemDelegate.paint` already elides text (`ElideRight` is
`QTableView`'s own default `textElideMode`), aligns it left/vcenter, and reads
`Qt.ItemDataRole.ForegroundRole` into its palette to color it -- which is what tints a broken row's
`~rehuco_agent.settings.ui.scrapers_table_model.ERROR_COLUMN` red, with no delegate code of this
module's own. Two things it does add:

* :meth:`paint` strips `QStyle.StateFlag.State_MouseOver` before delegating -- the base class draws a
  hover highlight box under that flag, which `~.scrapers_table_view.ScrapersTableView`'s own
  `setMouseTracking` (needed for the Scraper column's link cursor) now keeps live over every cell,
  turning a settings table with no concept of "hovering a row" into one with a distracting gray box.
* :meth:`sizeHint` corrects for the base class's own `sizeHint` measuring with an integer
  `QFontMetrics`, so a cell whose real advance rounds down does not lose its last character to an
  ellipsis it never needed -- the same reasoning
  `~rehuco_agent.documents.files_row_delegate.FilesRowDelegate.sizeHint` gives.
"""

from math import ceil
from typing import Final, override

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFontMetricsF, QPainter
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from .scrapers_table_model import ModelIndex

TEXT_PADDING: Final = 6
"""Horizontal inset of a cell's text from its rect, in pixels -- the same width
`~rehuco_agent.documents.files_row_delegate.TEXT_PADDING` uses, matching what the base delegate's own
item-view style applies so this `sizeHint` measures the same rect the base `paint` draws into."""


class ScrapersRowDelegate(QStyledItemDelegate):
    """Draws the Source and Error columns of the Scrapers table, with no hover highlight.

    :param parent: optional Qt parent.
    """

    @override
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: ModelIndex) -> None:
        option = QStyleOptionViewItem(option)
        option.state &= ~QStyle.StateFlag.State_MouseOver
        super().paint(painter, option, index)

    @override
    def sizeHint(self, option: QStyleOptionViewItem, index: ModelIndex) -> QSize:  # noqa: N802  (Qt API name)
        metrics = QFontMetricsF(option.font)
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        width = ceil(metrics.horizontalAdvance(text)) + 2 * TEXT_PADDING
        return QSize(width, ceil(metrics.height()))
