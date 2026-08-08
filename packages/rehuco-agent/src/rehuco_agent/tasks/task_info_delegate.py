"""Draws a task row's `Info` cell -- a progress bar and its figure side by side, the failure reason for
a failed job, or nothing (#202, #248).
"""

from typing import Final, override

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QStyleOptionViewItem
from rehuco_core import JobState, JobStatus

from .task_progress_renderers import progress_text
from .task_queue_model import TaskQueueModel
from .task_row_delegate import TEXT_HPADDING, ModelIndex, TaskRowDelegate

FIGURE_WIDTH: Final = 100
"""How much of the cell's right-hand edge is kept for the progress figure, in pixels.

Wide enough for every figure the shipped renderers produce but the largest catalogs' -- measured in the
UI font, a byte pair is 48-85px and a resource count 73-117px, so a four-digit sweep is the one case
that elides. Fixed rather than fitted to the text, so a running row's figure does not walk left and
right as its digits change, and so the bars of two rows start and end at the same place."""

BAR_HEIGHT: Final = 14
"""How tall the bar is drawn, in pixels -- DownThemAll's own figure for a 26px row, and short enough to
read as a bar rather than as a filled cell."""

BAR_RADIUS: Final = 2
"""The bar's corner radius, in pixels."""

GROOVE_ALPHA: Final = 60
"""How strongly the empty part of the bar is outlined, out of 255.

Drawn from the row's own text pen rather than a color of its own, so it holds up on the selection fill
and in both themes without a second value to keep in step."""

PLAIN_CHUNK_ALPHA: Final = 110
"""How strongly the filled part is drawn for a state with no color of its own -- ``PAUSED``.

The same reasoning as its missing row tint (#251): a job someone parked earns no accent. Drawn in the
row's ink at part strength, which reads as *muted* rather than as *another state*."""


class TaskInfoDelegate(TaskRowDelegate):
    """Paints :attr:`~rehuco_agent.tasks.task_queue_model.INFO_COLUMN`, over the row's selection fill
    and state tint (:class:`~.task_row_delegate.TaskRowDelegate`, #251).

    **The bar and its figure sit side by side, never on top of each other.** The figure has the cell's
    rightmost :data:`FIGURE_WIDTH` and the bar takes what is left. Text centred *on* a bar was tried
    and is worse than either half suggests: the color that reads over the filled part is the wrong one
    over the empty part, so one end of the bar always loses its text -- and no single pen fixes it,
    because the surface under the text changes as the job runs. Two areas, each with one background,
    is the whole fix. It is also what DownThemAll does, which reaches the same place from the other
    direction: it gives the bar a column and the figures columns of their own.

    **The job decides how its progress reads; this paints what it is handed** (#248). ``done`` and
    ``total`` are bare numbers, so a run hashing four gigabytes and a sweep over forty resources are
    the same pair of integers here -- :attr:`~rehuco_core.JobStatus.progress_unit` is what tells them
    apart, and :mod:`~rehuco_agent.tasks.task_progress_renderers` turns one into a line of text. A job
    declaring no unit draws an **empty cell**, which is the honest answer for work that is one
    indivisible step.

    **The bar is drawn here rather than by the style**, for the reason :meth:`__paint_bar` gives, and
    its filled part takes the state's own color -- the same value that tints the row and colors the
    status glyph beside it.

    **There is no busy bar, and this is a reversal.** Until #248 a ``total`` of ``None`` or ``0`` drew
    ``QStyleOptionProgressBar`` with ``maximum = 0``, on the reasoning that an honest *indeterminate*
    beats a bar stalled at either extreme. That reasoning was right about the alternatives and wrong
    about the medium: Qt's busy indicator is an *animation*, and a delegate repaints only when its row's
    data changes, so it never runs and the cell paints as garbage. A bar is drawn only where there is a
    fraction to draw; everything else is the figure alone, or nothing. Restoring the branch would
    restore the garbage.

    ``done > total`` still clamps the bar to full while the numbers underneath disagree -- the engine
    clamps nothing, so a reader is shown the true figures rather than a corrected lie.

    A cell whose :attr:`~.task_queue_model.TaskQueueModel.Roles.STATUS` is not a
    :class:`~rehuco_core.JobStatus` is handed to the base delegate untouched, the same deference
    `LogLevelDelegate` shows a foreign model.

    :param parent: optional Qt parent.
    :param state_colors: the tint per state; states absent from it are drawn plain.
    """

    @override
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: ModelIndex) -> None:
        status = index.data(TaskQueueModel.Roles.STATUS)
        if not isinstance(status, JobStatus):
            super().paint(painter, option, index)
            return
        painter.save()
        try:
            self.paint_background(painter, option, status.state)
            if status.state == JobState.FAILED:
                # a reason is a sentence, so it takes the whole cell rather than the figure's slot
                self.paint_text(painter, option.rect, status.error or "")
                return
            self.__paint_progress(painter, option, status)
        finally:
            painter.restore()

    def __paint_progress(self, painter: QPainter, option: QStyleOptionViewItem, status: JobStatus) -> None:
        """Draw the figure in its slot, and a bar in what is left when there is a fraction.

        :param painter: the painter to draw with.
        :param option: the item's rect, palette and state.
        :param status: the job to draw.
        """
        if not status.progress_unit:
            return
        text = progress_text(status)
        if text:
            figure = TaskInfoDelegate.figure_rect(option.rect)
            self.paint_text(painter, figure, text, alignment=Qt.AlignmentFlag.AlignRight)
        total = status.total
        if total is not None and total > 0:
            self.__paint_bar(painter, option, status.state, status.done / total)

    def __paint_bar(self, painter: QPainter, option: QStyleOptionViewItem, state: JobState, fraction: float) -> None:
        """Draw the bar: an outlined groove, filled to ``fraction`` in the state's own color.

        **Drawn here rather than through the style** (#251's rule, applied to the one cell that had
        escaped it). ``CE_ProgressBar`` draws a groove that is *opaque* under some styles -- Fusion
        fills the whole cell with one -- which covers the selection fill and state tint this delegate
        just painted, so a selected row did not read as selected here; and the bar it draws fills the
        cell's full height, which is what forced the figure on top of it in the first place. Twenty
        lines of rounded rectangle buy a cell whose every pixel this delegate decided, and one that
        looks the same on all three platforms.

        :param painter: the painter to draw with.
        :param option: the item's rect, palette and state.
        :param state: the row's job state, which colors the filled part.
        :param fraction: how much of the work is done, clamped to full above ``1.0``.
        """
        groove = TaskInfoDelegate.bar_rect(option.rect)
        if groove.width() <= 0:
            return
        ink = painter.pen().color()
        painter.save()
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            outline = QColor(ink)
            outline.setAlpha(GROOVE_ALPHA)
            painter.setBrush(outline)
            painter.drawRoundedRect(QRectF(groove), BAR_RADIUS, BAR_RADIUS)
            chunk = QRectF(groove)
            chunk.setWidth(groove.width() * min(1.0, fraction))
            painter.setBrush(self.__chunk_color(state, ink))
            painter.drawRoundedRect(chunk, BAR_RADIUS, BAR_RADIUS)
        finally:
            painter.restore()

    def __chunk_color(self, state: JobState, ink: QColor) -> QColor:
        """What the filled part is drawn in: the state's own color, else the row's ink, muted.

        :param state: the row's job state.
        :param ink: the row's current text color, for a state with no color of its own.
        :returns: the color to fill with.
        """
        color = self.color_for(state)
        if color is not None:
            return color
        muted = QColor(ink)
        muted.setAlpha(PLAIN_CHUNK_ALPHA)
        return muted

    @staticmethod
    def figure_rect(cell: QRect) -> QRect:
        """The cell's right-hand slot, where the progress figure goes.

        :param cell: the whole cell.
        :returns: the figure's rect, never wider than the cell itself.
        """
        width = min(FIGURE_WIDTH, cell.width())
        return QRect(cell.right() - width + 1, cell.top(), width, cell.height())

    @staticmethod
    def bar_rect(cell: QRect) -> QRect:
        """What is left of the cell for the bar, vertically centred at :data:`BAR_HEIGHT`.

        :param cell: the whole cell.
        :returns: the bar's rect; empty when the cell is too narrow to hold both.
        """
        left = cell.left() + TEXT_HPADDING
        right = TaskInfoDelegate.figure_rect(cell).left() - TEXT_HPADDING
        if right <= left:
            return QRect()
        height = min(BAR_HEIGHT, cell.height())
        top = cell.top() + (cell.height() - height) // 2
        return QRect(left, top, right - left, height)
