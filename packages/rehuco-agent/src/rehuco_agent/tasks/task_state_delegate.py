"""Draws a task row's state cell -- one glyph, in the state's own color, and no words (#248)."""

from collections.abc import Mapping
from typing import Final, override

from PySide6.QtCore import QObject, QRect, QSize
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QStyleOptionViewItem
from rehuco_core import JobState, JobStatus

from .task_queue_model import TaskQueueModel
from .task_row_delegate import ModelIndex, TaskRowDelegate
from .task_status_icons import StatusIconCache, status_icon

STATUS_ICON_SIZE: Final = 16
"""How big a status glyph is drawn, in pixels -- the size the app's other 16px icon slots use, and the
size a row is tall enough for without growing."""

STATE_COLUMN_WIDTH: Final = 52
"""How wide the state column is, in pixels.

Sized for its **header**, not its contents: the cells hold one 16px glyph and would collapse to almost
nothing, leaving *State* elided to a letter. A fixed width rather than a resize mode, because
``ResizeToContents`` would measure the display text this delegate deliberately does not draw."""


class TaskStateDelegate(TaskRowDelegate):
    """Paints :attr:`~.task_queue_model.STATE_COLUMN`: the status glyph, centred, over the row's
    selection fill and state tint (:class:`~.task_row_delegate.TaskRowDelegate`, #251).

    **Icons, not words.** The column named eight readings in text -- six states plus *Pausing…* and
    *Cancelling…* -- and each now has a glyph instead
    (:mod:`~rehuco_agent.tasks.task_status_icons`), which is what lets the column shrink to the width
    of its own header and gives the eye something to scan a long queue by. The sentence is not lost:
    it stays on the row's tooltip, which is also what an icon-only cell owes a reader who cannot tell
    the glyphs apart yet.

    **The glyph takes the state's own color** at full strength, the same value that tints the row at
    alpha 48 -- so a row and its icon are one signal seen twice rather than two colors to reconcile. A
    state given no color (``PAUSED``, deliberately, #251) draws in the row's own text pen: there is
    nothing to draw attention to about a job someone parked, and that is exactly what *no accent*
    says. A pending stop takes the color of the state it is still in, because it *is* still in it.

    A cell whose :attr:`~.task_queue_model.TaskQueueModel.Roles.STATUS` is not a
    :class:`~rehuco_core.JobStatus` is handed to the base delegate untouched, the same deference
    `LogLevelDelegate` shows a foreign model.

    :param parent: optional Qt parent.
    :param state_colors: the color per state; states absent from it draw plain.
    """

    def __init__(self, parent: QObject | None = None, *, state_colors: Mapping[JobState, QColor] | None = None) -> None:
        super().__init__(parent, state_colors=state_colors)
        self.__icons: Final = StatusIconCache()

    @override
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: ModelIndex) -> None:
        status = index.data(TaskQueueModel.Roles.STATUS)
        if not isinstance(status, JobStatus):
            super().paint(painter, option, index)
            return
        painter.save()
        try:
            self.paint_background(painter, option, status.state)
            # the pen paint_background just set is the row's own ink, which is what a state with no
            # color of its own draws in
            color = self.color_for(status.state) or painter.pen().color()
            self.__icons.icon(status_icon(status), color).paint(painter, TaskStateDelegate.__icon_rect(option))
        finally:
            painter.restore()

    @staticmethod
    def __icon_rect(option: QStyleOptionViewItem) -> QRect:
        """Where the glyph goes: centred in the cell, never larger than it.

        :param option: the item's rect.
        :returns: the rect to draw the glyph in.
        """
        side = min(STATUS_ICON_SIZE, option.rect.width(), option.rect.height())
        rect = QRect(0, 0, side, side)
        rect.moveCenter(option.rect.center())
        return rect

    @override
    def sizeHint(self, option: QStyleOptionViewItem, index: ModelIndex) -> QSize:  # noqa: N802  (Qt API name)
        """Ask for the glyph's own width rather than the display text's.

        The model still answers :attr:`~PySide6.QtCore.Qt.ItemDataRole.DisplayRole` with the state's
        sentence -- it is what the tooltip and any reader of the model see -- so the base's hint would
        size this column for *Cancelling…*, text this delegate never draws.
        """
        del option, index
        return QSize(STATUS_ICON_SIZE, STATUS_ICON_SIZE)
