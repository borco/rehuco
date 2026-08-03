"""Draws a log row's message cell -- the formatted text, wrapped to the column."""

# The opening of paint() reads the same as LogLevelDelegate's: read the entry role, defer to the base
# delegate when the row is not a log entry. That is each delegate stating its own contract with a model
# it may not own, not shared machinery -- factoring it out would leave a helper that can neither call
# the right super() nor be read at the call site, for two lines of Qt idiom.
# pylint: disable=duplicate-code

from typing import override

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from .log_entry import LogEntry
from .log_metrics import TEXT_HPADDING, TEXT_VPADDING
from .log_model import LogModel

type ModelIndex = QModelIndex | QPersistentModelIndex
"""What Qt hands a delegate method; the persistent form arrives from a view holding onto an index."""


class LogMessageDelegate(QStyledItemDelegate):
    """Paints a record's formatted message, word-wrapped, and reports the height that takes.

    **The message is wrapped, not elided.** A log line is often the one thing a reader came for -- a
    path, an exception's text -- and the end of it is where the answer usually is, so it is laid out
    over as many lines as it needs and the row grows. That only works if the view resizes its rows to
    the height reported here (:class:`~.log_view.LogView` does).

    The message drawn is :attr:`~.log_entry.LogEntry.message`, formatted once when the record arrived,
    so a repaint never re-runs a `logging.Formatter` and a record whose arguments were mutable reads
    the same whenever it is scrolled into view.

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
        wrapped = option.fontMetrics.boundingRect(text_rect, Qt.TextFlag.TextWordWrap, entry.message)
        return QSize(wrapped.width() + 2 * TEXT_HPADDING, wrapped.height() + 2 * TEXT_VPADDING)
