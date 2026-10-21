"""The status bar's count of record saves that have not landed (#497) -- so edits still only in memory, a save
waiting for its share or one that failed, are never mistaken for work already on disk.
"""

from typing import Final

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QToolButton, QWidget

from .pending_saves_filter import is_pending_save
from .task_queue_model import TaskQueueModel


class PendingSavesIndicator(QToolButton):
    """A compact, permanent status bar widget counting the pending saves.

    Rides :attr:`~.task_queue_model.TaskQueueModel.snapshot_taken`, for the reason
    :class:`~.task_queue_status_indicator.TaskQueueStatusIndicator` does: the queue's listener calls arrive on
    whichever thread a job changed on.

    **Hidden at zero.** A save that landed is nothing to report, and one that is pending is worth the space.

    Clicking it does nothing on its own -- see :attr:`clicked` (inherited from ``QAbstractButton``); the caller
    wires that to showing the pending saves (:meth:`~.task_queue_widget.TaskQueueWidget.show_pending_saves`).

    :param model: the dock's own model to follow, rather than a second listener on the queue itself.
    :param parent: optional Qt parent.
    """

    def __init__(self, model: TaskQueueModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__model: Final = model
        self.setAutoRaise(True)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        model.snapshot_taken.connect(self.__resync)
        self.__resync()

    def __resync(self) -> None:
        """Show or hide, and re-count, off the model's current rows -- called at construction and after every
        re-snapshot.
        """
        count = sum(1 for row in range(self.__model.rowCount()) if is_pending_save(self.__model.status_at(row)))
        self.setVisible(count > 0)
        if count:
            self.setText(f"{count} pending save" if count == 1 else f"{count} pending saves")
