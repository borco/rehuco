"""Draws the Scrapers table's Scraper column: a plain elided cell for a file that loaded no scraper, or
a real hyperlink -- via `QTextDocument`, not an embedded per-cell widget -- for a row carrying a
`~.scrapers_table_model.SITE_URL_ROLE` (#278).

**Why not `QTableView.setIndexWidget`?** It does not stop the view from also asking the delegate to
paint the cell underneath the widget, which doubled the text; and a plain `QLabel` paints its own
opaque background, which showed through as a stray gray cell. `QTextDocument` renders an `<a href>`
exactly the way `~borco_pyside.widgets.ElidedLabel`'s rich-text link does -- color, underline, a real
anchor -- with none of that, since nothing but this delegate ever draws the cell.

Installed with `QTableView.setItemDelegateForColumn`, not the view's general delegate
(`~borco_pyside.widgets.RowBandDelegate`), which this subclasses: a non-link Scraper cell (a file row's
``"—"``) is left to the base paint, and a link cell takes the same selection band under its document.
"""

from html import escape
from typing import override

from borco_pyside.widgets import RowBandDelegate
from borco_pyside.widgets.row_band_delegate import TEXT_PADDING
from PySide6.QtCore import QAbstractItemModel, QEvent, QModelIndex, QPersistentModelIndex, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetricsF, QMouseEvent, QPainter, QPalette, QTextDocument
from PySide6.QtWidgets import QStyle, QStyleOptionViewItem

from .scrapers_table_model import SITE_URL_ROLE


class ScrapersScraperColumnDelegate(RowBandDelegate):
    """Paints the Scraper column, and reports a click on its link.

    :param parent: optional Qt parent.
    """

    link_activated = Signal(str)
    """Fires with a row's `~.protocols.SiteScraper.site_url` when its link is clicked."""

    @override
    def paint(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> None:
        site_url = index.data(SITE_URL_ROLE)
        if not site_url:
            super().paint(painter, option, index)
            return
        painter.save()
        try:
            color = self.paint_band(painter, option, index)
            # the link colour is unreadable on the highlight, so a selected row draws it in the
            # highlighted-text colour
            selected = QStyle.StateFlag.State_Selected in option.state
            document = self.__document_for(option, index, color if selected else None)
            painter.translate(option.rect.topLeft())
            painter.translate(TEXT_PADDING, (option.rect.height() - document.size().height()) / 2)
            document.drawContents(painter, QRectF(0, 0, option.rect.width() - TEXT_PADDING, option.rect.height()))
        finally:
            painter.restore()

    def link_at(self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex, pos: QPointF) -> str:
        """The `~.protocols.SiteScraper.site_url` under ``pos``, or ``""`` when there is none there --
        shared by :meth:`editorEvent` and `~.scrapers_table_view.ScrapersTableView`'s own hover cursor,
        so a click and the cursor that invites it never disagree about where the link actually is.

        :param option: the cell's style option -- rect, font and palette, the three properties both a
            paint call and `~.scrapers_table_view.ScrapersTableView`'s own hover-cursor check build it
            from.
        :param index: the cell.
        :param pos: a point in the cell's own coordinates (``option.rect``'s, not the viewport's).
        :returns: the link's URL, or ``""`` when ``pos`` is not over one.
        """
        site_url = index.data(SITE_URL_ROLE)
        if not site_url:
            return ""
        document = self.__document_for(option, index)
        local = QPointF(pos) - QPointF(option.rect.topLeft())
        local.setX(local.x() - TEXT_PADDING)
        local.setY(local.y() - (option.rect.height() - document.size().height()) / 2)
        return document.documentLayout().anchorAt(local)

    @override
    def editorEvent(  # noqa: N802  (Qt API name)
        self,
        event: QEvent,
        model: QAbstractItemModel,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        if event.type() != QEvent.Type.MouseButtonRelease or not isinstance(event, QMouseEvent):
            return super().editorEvent(event, model, option, index)
        link = self.link_at(option, index, event.position())
        if not link:
            return False
        self.link_activated.emit(link)
        return True

    def __document_for(
        self,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
        color: QColor | None = None,
    ) -> QTextDocument:
        """The rich-text document a link cell is painted from and hit-tested against -- built the same
        way every time, so :meth:`paint` and :meth:`link_at` never disagree about where the anchor is.

        :param option: the cell's style option.
        :param index: the cell.
        :param color: the link colour, or ``None`` for the palette's own.
        :returns: the document."""
        site_url = str(index.data(SITE_URL_ROLE))
        site_name = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        metrics = QFontMetricsF(option.font)
        available = max(0.0, option.rect.width() - 2 * TEXT_PADDING)
        elided = metrics.elidedText(site_name, Qt.TextElideMode.ElideRight, available)
        link_color = (color or option.palette.color(QPalette.ColorRole.Link)).name()
        document = QTextDocument()
        document.setDefaultFont(option.font)
        document.setDocumentMargin(0)
        document.setHtml(
            f'<a href="{escape(site_url, quote=True)}" '
            f'style="color:{link_color}; text-decoration:underline;">{escape(elided)}</a>'
        )
        document.setTextWidth(max(0.0, option.rect.width() - TEXT_PADDING))
        return document
