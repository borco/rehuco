"""Draws a log row's message cell -- the formatted text, wrapped to the column, its links underlined."""

# The opening of paint() reads the same as LogLevelDelegate's: read the entry role, defer to the base
# delegate when the row is not a log entry. That is each delegate stating its own contract with a model
# it may not own, not shared machinery -- factoring it out would leave a helper that can neither call
# the right super() nor be read at the call site, for two lines of Qt idiom.
# pylint: disable=duplicate-code

import math
from collections.abc import Hashable
from typing import Final, override

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QPoint, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QPainter, QTextCharFormat, QTextLayout, QTextLine, QTextOption
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from .log_entry import LogEntry
from .log_metrics import TEXT_HPADDING, TEXT_VPADDING
from .log_model import LogModel

type ModelIndex = QModelIndex | QPersistentModelIndex
"""What Qt hands a delegate method; the persistent form arrives from a view holding onto an index."""

LINE_SEPARATOR: Final = "\u2028"
"""What a line break of the message is laid out as in a record with links: a `QTextLayout` is one paragraph and
does not break at a newline, which ``drawText`` does. One character for one, so a link's offsets still hold."""


class LogMessageDelegate(QStyledItemDelegate):
    """Paints a record's formatted message, word-wrapped, and reports the height that takes.

    **The message is wrapped, not elided.** A log line is often the one thing a reader came for -- a
    path, an exception's text -- and the end of it is where the answer usually is, so it is laid out
    over as many lines as it needs and the row grows. That only works if the view resizes its rows to
    the height reported here (:class:`~.log_view.LogView` does).

    The message drawn is :attr:`~.log_entry.LogEntry.message`, formatted once when the record arrived,
    so a repaint never re-runs a `logging.Formatter` and a record whose arguments were mutable reads
    the same whenever it is scrolled into view.

    **A record's links are underlined in the palette's link color** (the highlighted-text color on a selected row),
    and :meth:`link_at` answers which one is under a point. A record with none takes the plain path it always took --
    drawn, measured and wrapped by ``drawText`` -- and a record with some is laid out by one
    :class:`~PySide6.QtGui.QTextLayout`, which paint, size and hit-testing all read, so what is drawn, what room it is
    given and what a click lands on cannot disagree.

    A row whose :attr:`~.log_model.LogModel.Roles.ENTRY` is not a :class:`~.log_entry.LogEntry` is
    handed to the base delegate untouched, the same deference its sibling delegate shows.

    :param parent: optional Qt parent.
    """

    @override
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: ModelIndex) -> None:
        entry = index.data(LogModel.Roles.ENTRY)
        if not isinstance(entry, LogEntry):
            super().paint(painter, option, index)
            return

        # save/restore the painter Qt handed over, rather than opening a second one on its device: a
        # second painter is not clipped to this item, does not inherit the view's font or render hints,
        # and leaves whatever it changed behind for the next cell
        painter.save()
        try:
            if QStyle.StateFlag.State_Selected in option.state:
                painter.fillRect(option.rect, option.palette.highlight())
                pen = painter.pen()
                pen.setBrush(option.palette.highlightedText())
                painter.setPen(pen)
            if entry.links:
                LogMessageDelegate.__layout(option, entry).draw(painter, QPointF(self.text_rect(option).topLeft()))
            else:
                painter.drawText(
                    self.text_rect(option), Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, entry.message
                )
        finally:
            painter.restore()

    @staticmethod
    def text_rect(option: QStyleOptionViewItem) -> QRect:
        """The rect the message is laid out in -- the item's own, inset by the shared padding.

        The one place that inset is applied, so :meth:`paint` and :meth:`sizeHint` cannot disagree
        about how much room the text has: a wrap computed against a wider rect than the text is drawn
        into reports a height one line short, and clips the last line.

        :param option: the item's rect.
        :returns: the rect to lay the text out in.
        """
        return option.rect.adjusted(TEXT_HPADDING, TEXT_VPADDING, -TEXT_HPADDING, -TEXT_VPADDING)

    @override
    def sizeHint(self, option: QStyleOptionViewItem, index: ModelIndex) -> QSize:  # noqa: N802  (Qt API name)
        entry = index.data(LogModel.Roles.ENTRY)
        text_rect = self.text_rect(option)
        if not isinstance(entry, LogEntry) or text_rect.width() <= 0:
            # nothing to measure a wrap against: a column with no width yet (the first layout pass)
            # would make boundingRect wrap at every character and report an absurd height
            return super().sizeHint(option, index)
        if entry.links:
            layout = LogMessageDelegate.__layout(option, entry)
            lines = LogMessageDelegate.__lines(layout)
            width = math.ceil(max(line.naturalTextWidth() for line in lines))
            height = math.ceil(sum(line.height() for line in lines))
            return QSize(width + 2 * TEXT_HPADDING, height + 2 * TEXT_VPADDING)
        wrapped = option.fontMetrics.boundingRect(text_rect, Qt.TextFlag.TextWordWrap, entry.message)
        return QSize(wrapped.width() + 2 * TEXT_HPADDING, wrapped.height() + 2 * TEXT_VPADDING)

    def link_at(self, option: QStyleOptionViewItem, index: ModelIndex, pos: QPoint) -> Hashable | None:
        """The link drawn at ``pos`` in a message cell.

        Read off the same layout the cell is painted from, and only on the text: the empty space after a line's last
        character, or beside a short one, is no link, so a row whose link is its first words is not clickable all the
        way across.

        :param option: the cell's rect, font and state, as the view would paint it.
        :param index: the cell.
        :param pos: a point in the view's viewport coordinates.
        :returns: the link's target; ``None`` over plain text, over nothing, or for a row without links.
        """
        entry = index.data(LogModel.Roles.ENTRY)
        text_rect = self.text_rect(option)
        if not isinstance(entry, LogEntry) or not entry.links or text_rect.width() <= 0:
            return None
        local = pos - text_rect.topLeft()
        # held in a name: a line is a view of its layout, and outlives a temporary one only as a dangling pointer
        layout = LogMessageDelegate.__layout(option, entry)
        for line in LogMessageDelegate.__lines(layout):
            if line.y() <= local.y() < line.y() + line.height():
                if not 0 <= local.x() < line.naturalTextWidth():
                    return None
                character = line.xToCursor(local.x(), QTextLine.CursorPosition.CursorOnCharacter)
                return next((link.target for link in entry.links if link.start <= character < link.end), None)
        return None

    @staticmethod
    def __layout(option: QStyleOptionViewItem, entry: LogEntry) -> QTextLayout:
        """Lay a record with links out in its cell: wrapped at the text rect's width, each link underlined and drawn
        in the link color.

        Wrapped at a word boundary **or anywhere**, which a link needs and ``drawText``'s plain word wrap does not give:
        an address has no break in it, and would run out of the cell's right edge.

        :param option: the cell's rect, font, palette and state.
        :param entry: the record, with links.
        :returns: the laid-out text, with its first line at the origin; draw it at the text rect's corner.
        """
        selected = QStyle.StateFlag.State_Selected in option.state
        link_format = QTextCharFormat()
        link_format.setForeground(option.palette.highlightedText() if selected else option.palette.link())
        link_format.setFontUnderline(True)
        formats = []
        for link in entry.links:
            span = QTextLayout.FormatRange()
            span.start = link.start
            span.length = link.end - link.start
            span.format = link_format
            formats.append(span)

        layout = QTextLayout(entry.message.replace("\n", LINE_SEPARATOR), option.font)
        text_option = QTextOption()
        text_option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(text_option)
        layout.setFormats(formats)
        width = LogMessageDelegate.text_rect(option).width()
        height = 0.0
        layout.beginLayout()
        while (line := layout.createLine()).isValid():
            line.setLineWidth(width)
            line.setPosition(QPointF(0, height))
            height += line.height()
        layout.endLayout()
        return layout

    @staticmethod
    def __lines(layout: QTextLayout) -> list[QTextLine]:
        """The lines of a laid-out text, top to bottom.

        :param layout: the text, laid out.
        :returns: its lines; at least one, since a record's message is never empty once it has links.
        """
        return [layout.lineAt(row) for row in range(layout.lineCount())]
