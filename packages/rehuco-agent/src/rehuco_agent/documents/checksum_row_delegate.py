"""Draws a checksum-dock row: its selection fill, its Status glyph and its text (#244, #303).

Mirrors :class:`~rehuco_agent.documents.files_row_delegate.FilesRowDelegate`'s idiom -- the style draws
a selected row cell by cell, and with no grid between them a selection reads as a run of separate boxes
with the focus frame's edges showing between each; filling the item's whole rect and drawing the content
over it is what makes one selected row look like one selected row. It also puts the Status glyph where
it belongs: a decoration handed to the base delegate is placed relative to the cell's *text*, which the
Status column has none of.

Deliberately its own class rather than a shared one with :class:`FilesRowDelegate`: the two tables
disagree on more than they share -- three columns here against five there, no per-row glyph on the File
column, no disabled rows -- and reuse would cost a branch on what kind of row it is for every cell drawn.
What genuinely is shared -- the glyph set (:data:`~rehuco_agent.documents.files_rows.CHECKSUM_STATE_ICONS`)
and the layout constants below -- is imported rather than duplicated.
"""

from math import ceil
from typing import Final, override

from PySide6.QtCore import QObject, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFontMetricsF, QPainter, QPalette
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from ..svg_icon_cache import SvgIconCache
from .checksum_rows import DATE_COLUMN, STATUS_COLUMN, ChecksumRow, ChecksumTableModel, ModelIndex
from .files_row_delegate import CHECKSUM_COLUMN_WIDTH, DIGITS, ICON_SIZE, MODIFIED_SHAPE, SHAPE_DIGIT, TEXT_PADDING
from .files_rows import CHECKSUM_STATE_ICONS


class ChecksumRowDelegate(QStyledItemDelegate):
    """Paints every cell of the checksum dock's table (#244, #303).

    **The glyph takes the row's own text color**, the same as the file browser's checksum column: this
    table has no disabled rows today, but painting through the palette rather than a fixed color keeps
    the two docks' glyphs consistent under every theme without either one hard-coding a color.

    A cell whose row cannot be read is handed to the base delegate untouched, the same deference
    :class:`~rehuco_agent.documents.files_row_delegate.FilesRowDelegate` shows a model it may not own.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__icons: Final = SvgIconCache()

    @override
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: ModelIndex) -> None:
        row = index.data(ChecksumTableModel.ROW_ROLE)
        if not isinstance(row, ChecksumRow):
            super().paint(painter, option, index)
            return
        # save/restore the painter Qt handed over rather than opening a second one on its device: a
        # second painter is not clipped to this item and leaves whatever it changed behind for the next
        # cell (`FilesRowDelegate`'s own reasoning)
        painter.save()
        try:
            pen_color = self.__paint_background(painter, option)
            column = index.column()
            if column == STATUS_COLUMN:
                path = CHECKSUM_STATE_ICONS.get(row.checksum_state)
                if path is not None:
                    self.__icons.icon(path, pen_color).paint(painter, ChecksumRowDelegate.__centred(option.rect))
                return
            ChecksumRowDelegate.__paint_text(painter, option.rect, str(index.data() or ""))
        finally:
            painter.restore()

    def __paint_background(self, painter: QPainter, option: QStyleOptionViewItem) -> QColor:
        """Fill the cell and decide the colour its content is drawn in.

        :param painter: the painter to draw with.
        :param option: the item's rect, palette and state.
        :returns: the colour the glyph and the text are drawn in.
        """
        selected = QStyle.StateFlag.State_Selected in option.state
        if selected:
            painter.fillRect(option.rect, option.palette.highlight())
            color = option.palette.color(QPalette.ColorRole.HighlightedText)
        else:
            color = option.palette.color(QPalette.ColorRole.Text)
        pen = painter.pen()
        pen.setColor(color)
        painter.setPen(pen)
        return color

    # these two mirror `FilesRowDelegate`'s own near-verbatim -- one glyph column and one plain-text
    # painter, both the same idiom over a different row type; kept as a separate copy for the reason
    # every delegate/table pair in this module already is, rather than a shared base neither needs
    # pylint: disable=duplicate-code
    @staticmethod
    def __centred(cell: QRect) -> QRect:
        """A glyph-sized rect in the middle of ``cell``.

        What the Status column needs and the base delegate cannot give it: with no text to be placed
        relative to, a decoration ends up wherever an empty string leaves it.

        :param cell: the item's rect.
        :returns: the rect to draw the glyph in, never larger than the cell.
        """
        side = min(ICON_SIZE, cell.width(), cell.height())
        rect = QRect(0, 0, side, side)
        rect.moveCenter(cell.center())
        return rect

    @staticmethod
    def __paint_text(painter: QPainter, cell: QRect, text: str) -> None:
        """Draw ``text``, elided to the cell's width, with the painter's current pen.

        Drawn with the painter directly rather than handed to the style, the same reason
        :class:`~rehuco_agent.documents.files_row_delegate.FilesRowDelegate` does: the style picks its
        own selected-text colour from the active/inactive distinction, which would leave an unfocused
        selected row reading its highlight in one colour and its text in another.

        :param painter: the painter to draw with.
        :param cell: the rect to draw in.
        :param text: the text to draw.
        """
        rect = cell.adjusted(TEXT_PADDING, 0, -TEXT_PADDING, 0)
        elided = painter.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, rect.width())
        painter.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided)

    # pylint: enable=duplicate-code

    @override
    def sizeHint(self, option: QStyleOptionViewItem, index: ModelIndex) -> QSize:  # noqa: N802  (Qt API name)
        """Measure a cell the way this delegate actually draws it.

        Reuses :class:`~rehuco_agent.documents.files_row_delegate.FilesRowDelegate`'s own fix for the
        fractional-pixel rounding that used to elide the last character of a wide column (``eb5482d``):
        the *Checked* column is measured from :data:`~rehuco_agent.documents.files_row_delegate.MODIFIED_SHAPE`'s
        widest digit rather than from font metrics' rounded-down whole-pixel answer.

        :param option: the item's option, for its font metrics.
        :param index: the cell.
        :returns: the hint, including the padding this delegate draws with.
        """
        if index.column() == STATUS_COLUMN:
            return QSize(CHECKSUM_COLUMN_WIDTH, ICON_SIZE)
        metrics = QFontMetricsF(option.font)
        if index.column() == DATE_COLUMN:
            widest_digit = max(DIGITS, key=metrics.horizontalAdvance)
            text = MODIFIED_SHAPE.replace(SHAPE_DIGIT, widest_digit)
        else:
            text = str(index.data() or "")
        width = ceil(metrics.horizontalAdvance(text)) + 2 * TEXT_PADDING
        return QSize(width, max(ICON_SIZE, ceil(metrics.height())))
