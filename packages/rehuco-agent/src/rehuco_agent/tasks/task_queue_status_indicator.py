"""The status bar's own view of the task queue -- present whenever it holds unfinished work, so a
queue running with its dock closed is never mistaken for an idle app (#239, split out of #202).
"""

from typing import Final

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QToolButton, QWidget
from rehuco_core import FINISHED_JOB_STATES, JobState, JobStatus

from .task_progress_renderers import progress_text
from .task_queue_model import TaskQueueModel, state_text


class TaskQueueStatusIndicator(QToolButton):
    """A compact, permanent status bar widget naming the task queue's unfinished work.

    Rides :attr:`~.task_queue_model.TaskQueueModel.snapshot_taken` rather than becoming a second
    ``TaskQueueListener`` of its own -- the same reason :class:`~.task_queue_widget.TaskQueueWidget`
    does: ``queue_paused_changed`` and friends arrive on whichever thread the job stopped on, and
    touching a widget there is a plain thread-safety bug.

    **Hidden whenever the queue holds nothing unfinished.** Finished rows are *kept*
    ([[appendices.task-queue#kept]]), so "the queue is not empty" is the wrong trigger -- what is
    worth interrupting a reader for is work still to come.

    **Not a spinner.** Motion not driven by real progress is a fake percentage wearing a different
    hat, the same rule #202 already applied to the dock's own progress column.

    Clicking it does nothing on its own -- see :attr:`clicked` (inherited from ``QAbstractButton``);
    the caller wires that to revealing the dock.

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
        """Show or hide, and re-word, off the model's current rows -- called at construction and
        after every re-snapshot.
        """
        unfinished = [
            status
            for status in (self.__model.status_at(row) for row in range(self.__model.rowCount()))
            if status.state not in FINISHED_JOB_STATES
        ]
        self.setVisible(bool(unfinished))
        if unfinished:
            self.setText(TaskQueueStatusIndicator.__summary(unfinished))

    @staticmethod
    def __summary(unfinished: list[JobStatus]) -> str:
        """What the indicator says: a count, and the one job most worth naming.

        The named job is the running one if there is one, so a reader sees what is actually happening
        rather than merely queued; otherwise the first unfinished row stands in. Its progress leads
        when there is any to show (:func:`~.task_progress_renderers.progress_text`); a job with
        nothing to count yet falls back to its state (:func:`~.task_queue_model.state_text`), the same
        text the dock's own state column would show it.

        :param unfinished: every row not in :data:`~rehuco_core.FINISHED_JOB_STATES`, at least one.
        :returns: the button's text.
        """
        count = len(unfinished)
        noun = "task" if count == 1 else "tasks"
        current = next((status for status in unfinished if status.state is JobState.RUNNING), unfinished[0])
        detail = progress_text(current) or state_text(current)
        return f"{count} {noun} — {current.label} ({detail})"
