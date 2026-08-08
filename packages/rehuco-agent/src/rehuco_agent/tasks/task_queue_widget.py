"""The visible task queue: a table of every job, a toolbar and a context menu acting on the selection
(#202, [[architecture-design#components]]).
"""

from typing import Final, cast

from borco_pyside.theming import ActionIconThemeHandler
from PySide6.QtCore import QItemSelectionModel, QPoint
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QMenu, QMessageBox, QToolBar, QWidget
from rehuco_core import FINISHED_JOB_STATES, MOVABLE_JOB_STATES, JobState, JobStatus, StopRequest, TaskQueue

from ..fields.colors import DONE_COLOR, ERROR_COLOR, INFO_COLOR, QUEUED_COLOR
from .task_progress_delegate import TaskProgressDelegate
from .task_queue_model import LABEL_COLUMN, PROGRESS_COLUMN, STARTS_OVER_HINT, STATE_COLUMN, TaskQueueModel
from .task_queue_widget_ui import Ui_TaskQueueWidget
from .task_text_delegate import TaskTextDelegate

TASK_PAUSE_ICON: Final = ":/icons/task_pause.svg"
TASK_RUN_ICON: Final = ":/icons/task_run.svg"
TASK_CANCEL_ICON: Final = ":/icons/task_cancel.svg"
ITEMS_RESTORE_ICON: Final = ":/icons/items_restore.svg"
ITEMS_DELETE_ICON: Final = ":/icons/items_delete.svg"
TASK_CLEAR_DONE_ICON: Final = ":/icons/task_clear_done.svg"
ITEMS_TOP_ICON: Final = ":/icons/items_top.svg"
ITEMS_UP_ICON: Final = ":/icons/items_up.svg"
ITEMS_DOWN_ICON: Final = ":/icons/items_down.svg"
ITEMS_BOTTOM_ICON: Final = ":/icons/items_bottom.svg"

RETRIABLE_STATES: Final = frozenset({JobState.FAILED, JobState.CANCELLED})
"""The states :meth:`~rehuco_core.TaskQueue.retry` accepts -- a finished job that can be run again.

``DONE`` is deliberately absent: retrying it is not *wrong*, but offering it as a control invites
re-running work that succeeded ([[appendices.task-queue#kept]] frames retry as the recovery for a
failure or a cancellation)."""

TASK_STATE_COLORS: Final[dict[JobState, QColor]] = {
    JobState.QUEUED: QColor(QUEUED_COLOR),
    JobState.RUNNING: QColor(INFO_COLOR),
    JobState.DONE: QColor(DONE_COLOR),
    JobState.FAILED: QColor(ERROR_COLOR),
    JobState.CANCELLED: QColor(ERROR_COLOR),
}
"""What a task row is tinted by (#251), from the same tokens the log dock and the inline notice banner
use (`rehuco_agent.fields.colors`) -- ``FAILED``/``CANCELLED`` sharing :data:`~.fields.colors.ERROR_COLOR`
by decision: both are *did not finish*, and what separates a job that broke from one that was stopped
on purpose is left to the state column's text.

``JobState.PAUSED`` is deliberately absent, which paints it plain, the same way
:attr:`~borco_pyside.logging.LogLevelBand.DEBUGS` is left out of the log dock's own map -- there is
nothing to draw attention to about a job someone parked."""

PAUSE_TOOLTIP: Final = "Ask the selected jobs to pause."
STARTS_OVER_SOME_TOOLTIP: Final = "Some of them start again from the beginning when resumed."
"""Said on Pause when a *multi*-selection mixes jobs that keep their work with jobs that do not --
:data:`~.task_queue_model.STARTS_OVER_HINT` names one row's cost, this names a batch's."""


class TaskQueueWidget(QWidget):
    """A pure view over a :class:`~rehuco_core.TaskQueue`: every control here calls into the queue and
    waits for :class:`~.task_queue_model.TaskQueueModel` to say what happened, never redraws itself
    optimistically ([[appendices.task-queue#observation]]).

    **Reorder by buttons only, no drag-and-drop** ([[appendices.task-queue#reorder]]): Qt's internal-move
    drag-and-drop needs the *model* to perform the move, which contradicts being a pure view, and the
    engine clamps an out-of-range move -- a drop would visibly spring back. Buttons are also the only
    usable gesture at thousands of rows.

    **Pausing never prompts.** A row that starts over on resume says so on its own tooltip and on the
    Pause action (:meth:`__pause_tooltip`), and stays every bit as enabled as one that keeps its work:
    starting over is *wasteful, not wrong* ([[appendices.task-queue#job-responsibility]]), so a modal on
    every pause of a cheap job would be worse than the thing it warns about. Cancel is the one action
    that prompts, and once per batch rather than once per row.

    :param queue: the queue to show and act on.
    :param parent: optional Qt parent.
    """

    def __init__(self, queue: TaskQueue, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__queue: Final = queue
        self.__model: Final = TaskQueueModel(queue, self)

        self.__ui: Final = Ui_TaskQueueWidget()
        self.__ui.setupUi(self)
        self.__ui.task_view.setModel(self.__model)
        text_delegate = TaskTextDelegate(self, state_colors=TASK_STATE_COLORS)
        self.__ui.task_view.setItemDelegateForColumn(LABEL_COLUMN, text_delegate)
        self.__ui.task_view.setItemDelegateForColumn(STATE_COLUMN, text_delegate)
        self.__ui.task_view.setItemDelegateForColumn(
            PROGRESS_COLUMN, TaskProgressDelegate(self, state_colors=TASK_STATE_COLORS)
        )
        # selectionModel() is None only before a model is set (setModel just did)
        self.__selection_model: Final = cast(QItemSelectionModel, self.__ui.task_view.selectionModel())

        self.__setup_toolbar()
        self.__setup_context_menu()
        self.__selection_model.selectionChanged.connect(self.__update_enablement)
        self.__model.snapshot_taken.connect(self.__update_enablement)
        self.__model.snapshot_taken.connect(self.__update_bulk_toggle)
        self.__update_enablement()
        self.__update_bulk_toggle()

    def attach(self) -> None:
        """Start showing the queue's current jobs.

        Not done at construction: the model seeds itself from the queue's own snapshot the same moment
        it starts listening, so a caller controls exactly when that happens relative to a restore.
        """
        self.__model.attach_to(self.__queue)
        self.__update_bulk_toggle()

    def detach(self) -> None:
        """Stop listening, before the queue is shut down ([[appendices.task-queue#teardown]])."""
        self.__model.detach()

    # region toolbar and context menu

    def __setup_toolbar(self) -> None:
        ui = self.__ui
        toolbar = QToolBar(self)
        # the bulk pause/resume pair stands alone, separated by layout as well as by label from the
        # per-selection controls that follow -- the issue's own requirement, so a reader is never one
        # misclick away from stopping every job instead of the one they meant
        toolbar.addActions([ui.pause_all_action, ui.resume_all_action])
        toolbar.addSeparator()
        toolbar.addActions([ui.pause_action, ui.resume_action, ui.cancel_action, ui.retry_action])
        toolbar.addSeparator()
        toolbar.addActions([ui.move_to_top_action, ui.move_up_action, ui.move_down_action, ui.move_to_bottom_action])
        toolbar.addSeparator()
        # acts on the whole queue rather than the selection, so it gets its own trailing slot rather
        # than joining the per-selection run above (#249)
        toolbar.addAction(ui.clear_done_action)
        ui.main_layout.insertWidget(0, toolbar)

        for action, icon in (
            (ui.pause_all_action, TASK_PAUSE_ICON),
            (ui.resume_all_action, TASK_RUN_ICON),
            (ui.pause_action, TASK_PAUSE_ICON),
            (ui.resume_action, TASK_RUN_ICON),
            (ui.cancel_action, TASK_CANCEL_ICON),
            (ui.retry_action, ITEMS_RESTORE_ICON),
            (ui.clear_action, ITEMS_DELETE_ICON),
            (ui.clear_done_action, TASK_CLEAR_DONE_ICON),
            (ui.move_to_top_action, ITEMS_TOP_ICON),
            (ui.move_up_action, ITEMS_UP_ICON),
            (ui.move_down_action, ITEMS_DOWN_ICON),
            (ui.move_to_bottom_action, ITEMS_BOTTOM_ICON),
        ):
            ActionIconThemeHandler(action, icon)

        ui.pause_all_action.triggered.connect(self.__queue.pause)
        ui.resume_all_action.triggered.connect(self.__queue.resume)
        ui.pause_action.triggered.connect(self.__pause_selection)
        ui.resume_action.triggered.connect(self.__resume_selection)
        ui.cancel_action.triggered.connect(self.__cancel_selection)
        ui.retry_action.triggered.connect(self.__retry_selection)
        ui.clear_action.triggered.connect(self.__clear_selection)
        ui.clear_done_action.triggered.connect(lambda: self.__clear_in({JobState.DONE}))
        ui.clear_failed_action.triggered.connect(lambda: self.__clear_in({JobState.FAILED}))
        ui.clear_all_action.triggered.connect(self.__clear_all)
        ui.move_to_top_action.triggered.connect(lambda: self.__move_to_end(top=True))
        ui.move_up_action.triggered.connect(lambda: self.__move_by(-1))
        ui.move_down_action.triggered.connect(lambda: self.__move_by(1))
        ui.move_to_bottom_action.triggered.connect(lambda: self.__move_to_end(top=False))

    def __setup_context_menu(self) -> None:
        ui = self.__ui
        ui.task_view.customContextMenuRequested.connect(self.__show_context_menu)

    def __show_context_menu(self, position: QPoint) -> None:
        ui = self.__ui
        count = len(self.__selected_serials())
        ui.clear_action.setText(f"Clear {count} jobs" if count > 1 else "Clear job")

        menu = QMenu(self)
        menu.addAction(ui.pause_action)
        menu.addAction(ui.resume_action)
        menu.addAction(ui.cancel_action)
        menu.addAction(ui.retry_action)
        menu.addAction(ui.clear_action)
        menu.addSeparator()
        menu.addAction(ui.clear_done_action)
        menu.addAction(ui.clear_failed_action)
        menu.addAction(ui.clear_all_action)
        menu.exec(ui.task_view.viewport().mapToGlobal(position))

    # endregion

    # region selection and enablement

    def __selected_row_indices(self) -> list[int]:
        """Every selected row, sorted, deduplicated across columns of the same row."""
        return sorted({index.row() for index in self.__selection_model.selectedRows()})

    def __selected_serials(self) -> list[int]:
        """The serial behind every currently selected row, in view order."""
        return [self.__model.status_at(row).serial for row in self.__selected_row_indices()]

    def __update_enablement(self) -> None:
        """Enable each per-selection action for exactly the states it can act on, and say on Pause
        what pausing the selection would cost.

        Connected to both the selection and :attr:`~.task_queue_model.TaskQueueModel.snapshot_taken`:
        a job the user has selected can change state on its own (a running one finishing), and the
        controls must follow that without the selection itself having moved.
        """
        statuses = [self.__model.status_at(row) for row in self.__selected_row_indices()]
        states = {status.state for status in statuses}
        resumable_running = any(
            status.state is JobState.RUNNING and status.stop_requested is not None for status in statuses
        )
        ui = self.__ui
        ui.pause_action.setEnabled(bool(states & {JobState.RUNNING, JobState.QUEUED}))
        ui.pause_action.setToolTip(TaskQueueWidget.__pause_tooltip(statuses))
        ui.resume_action.setEnabled(JobState.PAUSED in states or resumable_running)
        ui.cancel_action.setEnabled(bool(states - FINISHED_JOB_STATES))
        ui.retry_action.setEnabled(bool(states) and states <= RETRIABLE_STATES)
        ui.clear_action.setEnabled(bool(statuses))
        movable = bool(states) and states <= MOVABLE_JOB_STATES
        for action in (ui.move_to_top_action, ui.move_up_action, ui.move_down_action, ui.move_to_bottom_action):
            action.setEnabled(movable)

    @staticmethod
    def __pause_tooltip(statuses: list[JobStatus]) -> str:
        """What Pause says it will cost over ``statuses`` -- **inform, never block**
        ([[appendices.task-queue#job-responsibility]]).

        Starting over is *wasteful, not wrong*, so this is the whole of the warning: the action stays
        enabled either way, and there is no prompt. Only rows Pause would actually act on are
        considered -- a finished job in the selection is not about to lose anything.

        :param statuses: the currently selected jobs.
        :returns: the Pause action's tooltip.
        """
        pausable = [status for status in statuses if status.state in {JobState.RUNNING, JobState.QUEUED}]
        starting_over = [status for status in pausable if not status.resumes_where_it_stopped]
        if not starting_over:
            return PAUSE_TOOLTIP
        cost = STARTS_OVER_HINT if len(pausable) == 1 else STARTS_OVER_SOME_TOOLTIP
        return f"{PAUSE_TOOLTIP}\n{cost}"

    def __update_bulk_toggle(self) -> None:
        """Enable the bulk Pause/Resume pair for exactly what the engine's own bulk calls would touch.

        **Not** off :attr:`~rehuco_core.TaskQueue.paused`, which the engine documents as a derived
        convenience meaning *every* unfinished job is paused: one job paused beside one still running
        makes it ``False``, which would disable Resume All even though
        :meth:`~rehuco_core.TaskQueue.resume` has a paused job to put back in line
        ([[appendices.task-queue#pause-concept]]). Each control instead mirrors its own call's
        predicate -- ``pause()`` asks every *unfinished* job, ``resume()`` touches exactly those whose
        pending request is a pause or which are already paused.

        Read here, on the GUI thread, off :attr:`~.task_queue_model.TaskQueueModel.snapshot_taken`
        rather than from a second `TaskQueueListener` of this widget's own: ``queue_paused_changed`` is
        called on whichever thread the queue's last unfinished job stopped on, and touching a `QAction`
        there would be a plain GUI-thread-safety bug the model's already-marshalled signal avoids.
        """
        statuses = [self.__model.status_at(row) for row in range(self.__model.rowCount())]
        self.__ui.pause_all_action.setEnabled(
            any(status.state not in FINISHED_JOB_STATES and not TaskQueueWidget.__held(status) for status in statuses)
        )
        self.__ui.resume_all_action.setEnabled(any(TaskQueueWidget.__held(status) for status in statuses))

    @staticmethod
    def __held(status: JobStatus) -> bool:
        """Whether :meth:`~rehuco_core.TaskQueue.resume` would put this job back in line -- its own
        predicate: already paused, or pausing.

        :param status: the job to test.
        :returns: whether a bulk resume touches it.
        """
        return status.state is JobState.PAUSED or status.stop_requested is StopRequest.PAUSE

    # endregion

    # region actions

    def __pause_selection(self) -> None:
        for serial in self.__selected_serials():
            self.__queue.pause_job(serial)

    def __resume_selection(self) -> None:
        for serial in self.__selected_serials():
            self.__queue.resume_job(serial)

    def __cancel_selection(self) -> None:
        serials = self.__selected_serials()
        if not serials:
            return
        count = len(serials)
        question = f"Cancel {count} jobs?" if count > 1 else "Cancel this job?"
        buttons = QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        if QMessageBox.question(self, "Cancel", question, buttons) != QMessageBox.StandardButton.Yes:
            return
        for serial in serials:
            self.__queue.cancel(serial)

    def __retry_selection(self) -> None:
        for serial in self.__selected_serials():
            self.__queue.retry(serial)

    def __clear_selection(self) -> None:
        serials = self.__selected_serials()
        if serials:
            self.__queue.remove(*serials)

    def __clear_in(self, states: set[JobState]) -> None:
        """Remove every job currently in one of ``states`` -- a dock sweep, not an engine feature
        (#237 deleted ``clear_finished()`` for exactly this reason: deciding *which* jobs a sweep drops
        is a view's business).

        :param states: which finished states to drop.
        """
        serials = [status.serial for status in self.__queue.jobs() if status.state in states]
        if serials:
            self.__queue.remove(*serials)

    def __clear_all(self) -> None:
        """Cancel whatever is unfinished, then remove everything."""
        statuses = self.__queue.jobs()
        for status in statuses:
            if status.state not in FINISHED_JOB_STATES:
                self.__queue.cancel(status.serial)
        serials = [status.serial for status in statuses]
        if serials:
            self.__queue.remove(*serials)

    def __move_by(self, delta: int) -> None:
        """Move every selected, movable row by ``delta`` positions.

        Re-reads the queue's own order before each move: a prior move in the same batch has already
        shifted everyone else's index, and moving off a snapshot taken before the batch started would
        send a row somewhere the queue never agreed to.

        :param delta: ``-1`` for Up, ``1`` for Down.
        """
        serials = self.__movable_selected_serials()
        ordered = serials if delta < 0 else list(reversed(serials))
        for serial in ordered:
            order = [status.serial for status in self.__queue.jobs()]
            current = order.index(serial)
            self.__queue.move(serial, max(0, current + delta))

    def __move_to_end(self, *, top: bool) -> None:
        """Move every selected, movable row to the top or the bottom of the movable run, preserving
        their relative order there.

        Both ends are built the same way: each move inserts its job right at the target index, ahead
        of whatever is already there, so the row processed *last* ends up closest to the edge. To land
        with the original top-to-bottom order intact, Top therefore processes its serials back to
        front (the first-selected job is moved into place last, landing first) and Bottom processes
        them front to back (the first-selected job is moved into place first, landing first after it).

        :param top: ``True`` for Top, ``False`` for Bottom.
        """
        serials = self.__movable_selected_serials()
        ordered = list(reversed(serials)) if top else serials
        target = 0 if top else self.__model.rowCount()
        for serial in ordered:
            self.__queue.move(serial, target)

    def __movable_selected_serials(self) -> list[int]:
        """The selected serials whose state permits a move, in view order."""
        return [
            self.__model.status_at(row).serial
            for row in self.__selected_row_indices()
            if self.__model.status_at(row).state in MOVABLE_JOB_STATES
        ]

    # endregion
