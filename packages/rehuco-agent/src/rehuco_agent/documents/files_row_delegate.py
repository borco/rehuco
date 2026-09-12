"""Draws a file browser row: its selection fill, its two glyphs and its text (#266).

**The row is painted here rather than left to the style**, which is the arrangement the Logs and Tasks
tables already keep (`LogMessageDelegate`, `TaskRowDelegate`): the style draws a selected row cell by
cell, and with no grid between them a selection reads as a run of separate boxes with the focus frame's
edges showing between each. Filling the item's whole rect and drawing the content over it is what makes
one selected row look like one selected row.

It also puts the glyphs where they belong. A decoration handed to the base delegate is placed relative
to the cell's *text*, so the checksum column -- which has no text at all -- got it wherever an empty
string put it rather than in the middle of the row.
"""

from typing import Final, override

from PySide6.QtCore import QObject, QRect, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from ..svg_icon_cache import SvgIconCache
from .files_rows import (
    CHECKSUM_COLUMN,
    CHECKSUM_STATE_ICONS,
    FILE_TYPE_ICONS,
    NAME_COLUMN,
    SIZE_COLUMN,
    FileRow,
    FilesTableModel,
    ModelIndex,
)

ICON_SIZE: Final = 16
"""How big a glyph is drawn, in pixels -- the size the app's other 16px icon slots use (#248), and the
size a row is tall enough for without growing."""

ICON_TEXT_GAP: Final = 6
"""Space between the Name column's type glyph and the name beside it, in pixels."""

TEXT_PADDING: Final = 4
"""Horizontal inset of a cell's text from its rect, in pixels -- the same inset the task table draws
its own text with, so the two read as tables of one application."""

CHECKSUM_COLUMN_WIDTH: Final = 28
"""How wide the checksum column is, in pixels: one glyph and a little air.

Sized for its **contents**, unlike the task queue's State column, which had to be sized for its header
-- this column's title is deliberately empty, so there is nothing for it to be elided to."""


class FilesRowDelegate(QStyledItemDelegate):
    """Paints every cell of the file browser's table (#266).

    Two glyph columns and three of text, in one delegate rather than one per column: what they share is
    the row -- its selection fill and the pen its content is drawn with -- and splitting them would
    make that agreement something to keep rather than something structural.

    **The glyph takes the row's own text color**, so a disabled row's icon dims with its text: a row a
    reader may not act on answers :data:`~PySide6.QtCore.Qt.ItemFlag.NoItemFlags`
    (:meth:`~rehuco_agent.documents.files_rows.FilesTableModel.flags`, #266), and the palette's
    *disabled* group is what draws it. The group is read from the **index's own flags** rather than from
    whichever group the incoming palette happens to be set to, so the colour is a property of the row
    rather than of who called.

    A cell whose row cannot be read is handed to the base delegate untouched, the same deference
    `LogMessageDelegate` and :class:`~rehuco_agent.tasks.task_state_delegate.TaskStateDelegate` show a
    model they may not own.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__icons: Final = SvgIconCache()

    @override
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: ModelIndex) -> None:
        row = index.data(FilesTableModel.ROW_ROLE)
        if not isinstance(row, FileRow):
            super().paint(painter, option, index)
            return
        # save/restore the painter Qt handed over rather than opening a second one on its device: a
        # second painter is not clipped to this item and leaves whatever it changed behind for the next
        # cell (`LogMessageDelegate`'s own reasoning)
        painter.save()
        try:
            pen_color = self.__paint_background(painter, option, index)
            column = index.column()
            if column == CHECKSUM_COLUMN:
                path = CHECKSUM_STATE_ICONS.get(row.checksum_state)
                if path is not None:
                    self.__icons.icon(path, pen_color).paint(painter, FilesRowDelegate.__centred(option.rect))
                return
            cell = option.rect
            if column == NAME_COLUMN:
                # centred in the row, then moved to its left edge -- the same vertical placement the
                # checksum glyph gets, so the two columns' glyphs sit on one line
                glyph = FilesRowDelegate.__centred(cell)
                glyph.moveLeft(cell.left() + TEXT_PADDING)
                self.__icons.icon(FILE_TYPE_ICONS[row.file_type], pen_color).paint(painter, glyph)
                cell = cell.adjusted(TEXT_PADDING + ICON_SIZE + ICON_TEXT_GAP, 0, 0, 0)
            alignment = Qt.AlignmentFlag.AlignRight if column == SIZE_COLUMN else Qt.AlignmentFlag.AlignLeft
            FilesRowDelegate.__paint_text(painter, cell, str(index.data() or ""), alignment)
        finally:
            painter.restore()

    def __paint_background(self, painter: QPainter, option: QStyleOptionViewItem, index: ModelIndex) -> QColor:
        """Fill the cell and decide the colour its content is drawn in.

        :param painter: the painter to draw with.
        :param option: the item's rect, palette and state.
        :param index: the cell, for its row's flags.
        :returns: the colour the glyph and the text are drawn in.
        """
        selected = QStyle.StateFlag.State_Selected in option.state
        if selected:
            painter.fillRect(option.rect, option.palette.highlight())
        enabled = bool(index.flags() & Qt.ItemFlag.ItemIsEnabled)
        if selected:
            color = option.palette.color(QPalette.ColorRole.HighlightedText)
        else:
            group = QPalette.ColorGroup.Normal if enabled else QPalette.ColorGroup.Disabled
            color = option.palette.color(group, QPalette.ColorRole.Text)
        pen = painter.pen()
        pen.setColor(color)
        painter.setPen(pen)
        return color

    @staticmethod
    def __centred(cell: QRect) -> QRect:
        """A glyph-sized rect in the middle of ``cell``.

        What the checksum column needs and the base delegate cannot give it: with no text to be placed
        relative to, a decoration ends up wherever an empty string leaves it.

        :param cell: the item's rect.
        :returns: the rect to draw the glyph in, never larger than the cell.
        """
        side = min(ICON_SIZE, cell.width(), cell.height())
        rect = QRect(0, 0, side, side)
        rect.moveCenter(cell.center())
        return rect

    @staticmethod
    def __paint_text(painter: QPainter, cell: QRect, text: str, alignment: Qt.AlignmentFlag) -> None:
        """Draw ``text``, elided to the cell's width, with the painter's current pen.

        Drawn with the painter directly rather than handed to the style, for the reason
        :meth:`~rehuco_agent.tasks.task_row_delegate.TaskRowDelegate.paint_text` gives: the style picks
        its own selected-text colour from the active/inactive distinction, which would leave an
        unfocused selected row reading its highlight in one colour and its text in another.

        :param painter: the painter to draw with.
        :param cell: the rect to draw in.
        :param text: the text to draw.
        :param alignment: how to place it horizontally; vertically it is always centred.
        """
        rect = cell.adjusted(TEXT_PADDING, 0, -TEXT_PADDING, 0)
        elided = painter.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, rect.width())
        painter.drawText(rect, alignment | Qt.AlignmentFlag.AlignVCenter, elided)

    @override
    def sizeHint(self, option: QStyleOptionViewItem, index: ModelIndex) -> QSize:  # noqa: N802  (Qt API name)
        """Ask for the glyph's own width on the checksum column, and room for both on the Name column.

        :param option: the item's option.
        :param index: the cell.
        :returns: the hint.
        """
        if index.column() == CHECKSUM_COLUMN:
            return QSize(CHECKSUM_COLUMN_WIDTH, ICON_SIZE)
        hint = super().sizeHint(option, index)
        if index.column() == NAME_COLUMN:
            # the base measured the text alone; the glyph and its gap sit to the left of it
            return QSize(hint.width() + TEXT_PADDING + ICON_SIZE + ICON_TEXT_GAP, hint.height())
        return hint
