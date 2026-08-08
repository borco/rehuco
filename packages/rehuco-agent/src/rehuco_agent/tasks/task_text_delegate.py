"""Draws a task row's plain-text cells -- the label and the state -- over the row's selection fill and
state tint (#251).
"""

from typing import override

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QStyleOptionViewItem
from rehuco_core import JobStatus

from .task_queue_model import TaskQueueModel
from .task_row_delegate import ModelIndex, TaskRowDelegate


class TaskTextDelegate(TaskRowDelegate):
    """Paints :attr:`~.task_queue_model.LABEL_COLUMN` and :attr:`~.task_queue_model.STATE_COLUMN`: the
    cell's own display text, over the row's selection fill and state tint -- the plain-text sibling to
    :class:`~.task_info_delegate.TaskInfoDelegate`, sharing
    :meth:`~.task_row_delegate.TaskRowDelegate.paint_background` and
    :meth:`~.task_row_delegate.TaskRowDelegate.paint_text` rather than duplicating either.

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
            text = index.data(Qt.ItemDataRole.DisplayRole)
            self.paint_text(painter, option.rect, text if isinstance(text, str) else "")
        finally:
            painter.restore()
