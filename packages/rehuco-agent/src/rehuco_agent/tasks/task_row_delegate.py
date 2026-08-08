"""Shared painting for task table cells: the row's selection fill and state tint, and the one way this
view draws its own text -- both in the paint order `LogLevelDelegate`/`LogMessageDelegate` establish
(#251).
"""

from collections.abc import Mapping
from typing import Final

from borco_pyside.logging import BAND_TINT_ALPHA
from PySide6.QtCore import QModelIndex, QObject, QPersistentModelIndex, QRect, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem
from rehuco_core import JobState

type ModelIndex = QModelIndex | QPersistentModelIndex
"""What Qt hands a delegate method; the persistent form arrives from a view holding onto an index."""

TEXT_HPADDING: Final = 4
"""Horizontal inset of a cell's text from its rect, in pixels."""


class TaskRowDelegate(QStyledItemDelegate):
    """Base for every task-table cell delegate: the row's selection fill and state tint.

    **The tint covers the whole row**, unlike the Logs dock where only the level column carries one --
    so every column's delegate shares this paint order rather than each re-deriving it:
    :meth:`paint_background` fills the selection color when selected, then the state's tint over it,
    inset by a pixel when selected, so a selected row still reads as selected while keeping the band it
    belongs to (:class:`~borco_pyside.logging.LogLevelDelegate`'s own reasoning, applied to a second
    table).

    **The colors come from the caller.** A state absent from ``state_colors`` is drawn plain -- the
    treatment ``PAUSED`` gets: there is nothing to draw attention to about a job someone parked.

    :param parent: optional Qt parent.
    :param state_colors: the tint per state; states absent from it are drawn plain.
    """

    def __init__(self, parent: QObject | None = None, *, state_colors: Mapping[JobState, QColor] | None = None) -> None:
        super().__init__(parent)
        self.__state_colors: dict[JobState, QColor] = dict(state_colors or {})

    def color_for(self, state: JobState) -> QColor | None:
        """The caller's color for ``state``, at full strength.

        What :meth:`tint_for` waters down for a background, and what anything wanting the state's own
        color to *read* -- a status glyph, a progress bar's filled part -- asks for instead.

        :param state: the state to look up.
        :returns: the color, or ``None`` when this state was given none.
        """
        color = self.__state_colors.get(state)
        return QColor(color) if color is not None else None

    def tint_for(self, state: JobState) -> QColor | None:
        """The color this delegate fills ``state``'s rows with, alpha already applied.

        :param state: the state to look up.
        :returns: the tint, or ``None`` when ``state`` is drawn plain.
        """
        color = self.color_for(state)
        if color is None:
            return None
        tint = QColor(color)
        tint.setAlpha(BAND_TINT_ALPHA)
        return tint

    def paint_background(self, painter: QPainter, option: QStyleOptionViewItem, state: JobState) -> None:
        """Fill the cell: the selection color when selected, then the state's tint over it.

        :param painter: the painter to draw with.
        :param option: the item's rect, palette and state.
        :param state: the row's job state.
        """
        selected = QStyle.StateFlag.State_Selected in option.state
        if selected:
            painter.fillRect(option.rect, option.palette.highlight())
        tint = self.tint_for(state)
        if tint is not None:
            painter.fillRect(option.rect.adjusted(1, 1, -1, -1) if selected else option.rect, tint)
        if selected:
            pen = painter.pen()
            pen.setBrush(option.palette.highlightedText())
            painter.setPen(pen)

    @staticmethod
    def paint_text(
        painter: QPainter,
        cell: QRect,
        text: str,
        *,
        alignment: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft,
    ) -> None:
        """Draw ``text``, elided to the cell's width, with the painter's current pen.

        Drawn with the painter directly rather than handed to the style: the style picks its own
        selected-text color from ``option.state``'s active/inactive distinction, which answers
        independently of the color :meth:`paint_background` just filled -- an unfocused but selected
        row would then read its highlight in one color and its text in another. Using the same pen
        :meth:`paint_background` already set (to ``option.palette.highlightedText()`` when selected)
        is what keeps the two in agreement, the same reasoning `LogMessageDelegate` applies to its own
        text.

        :param painter: the painter to draw with.
        :param cell: the rect to draw in -- the whole item's, or a slot within it.
        :param text: the text to draw.
        :param alignment: how to place it horizontally; vertically it is always centred. A progress
            bar's label is centred on its cell, a label or a failure reason starts at the left.
        """
        rect = cell.adjusted(TEXT_HPADDING, 0, -TEXT_HPADDING, 0)
        elided = painter.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, rect.width())
        painter.drawText(rect, alignment | Qt.AlignmentFlag.AlignVCenter, elided)
