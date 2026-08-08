"""Draws a task row's progress cell -- a bar for unfinished work, the failure reason for a failed one
(#202).
"""

from typing import Final, override

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionProgressBar, QStyleOptionViewItem
from rehuco_core import JobState, JobStatus

from .task_queue_model import TaskQueueModel
from .task_row_delegate import ModelIndex, TaskRowDelegate

PROGRESS_MAXIMUM: Final = 1000
"""The bar's own scale, independent of a job's ``total`` -- a percentage with three decimal digits of
resolution, which is plenty for any ``done``/``total`` pair a job reports."""


class TaskProgressDelegate(TaskRowDelegate):
    """Paints :attr:`~rehuco_agent.tasks.task_queue_model.PROGRESS_COLUMN`: a bar for a job still doing
    something, its failure reason -- elided, with the full text on the row's tooltip -- for one that
    is not, over the row's selection fill and state tint (:class:`~.task_row_delegate.TaskRowDelegate`,
    #251).

    **Indeterminate is drawn honestly, not guessed at.** ``total is None`` (a job that cannot estimate
    one) and ``total == 0`` both draw a busy bar rather than a stalled one at either extreme, and
    ``done > total`` clamps the bar to full while the numbers underneath still disagree -- the engine
    clamps nothing, so a reader is shown the true figures rather than a corrected lie
    ([[appendices.task-queue]] notes).

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
                self.paint_text(painter, option, status.error or "")
                return
            self.__paint_bar(painter, option, status)
        finally:
            painter.restore()

    @staticmethod
    def __paint_bar(painter: QPainter, option: QStyleOptionViewItem, status: JobStatus) -> None:
        """Draw a progress bar: determinate when ``total`` is a positive number, busy otherwise.

        :param painter: the painter to draw with.
        :param option: the item's rect, palette and state.
        :param status: the job to draw.
        """
        total = status.total
        option_bar = QStyleOptionProgressBar()
        option_bar.rect = option.rect
        option_bar.minimum = 0
        if total is not None and total > 0:
            option_bar.maximum = PROGRESS_MAXIMUM
            option_bar.progress = round(min(1.0, status.done / total) * PROGRESS_MAXIMUM)
            option_bar.text = f"{status.done}/{total}"
        else:
            option_bar.maximum = 0  # a maximum of 0 is QProgressBar's own "indeterminate" spelling
            option_bar.progress = -1  # its "no data yet" sentinel for a busy indicator
            option_bar.text = str(status.done) if status.done else ""
        option_bar.textVisible = bool(option_bar.text)
        option_bar.textAlignment = Qt.AlignmentFlag.AlignCenter
        style = QApplication.style()
        if style is not None:
            style.drawControl(QStyle.ControlElement.CE_ProgressBar, option_bar, painter)
