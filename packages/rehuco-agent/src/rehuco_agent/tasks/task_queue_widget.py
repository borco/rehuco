"""The visible task queue: a nested dock shell over a table of every job, a toolbar and a context menu
acting on the selection, and a Log sub-dock following the selected job
(#202, #276, [[architecture-design#components]], [[appendices.task-queue#dock]]).
"""

from typing import Any, Final, cast

import cbor2
import PySide6QtAds as QtAds
from borco_pyside.logging import LogWidget
from borco_pyside.qtads import QtAdsFocusTracker
from borco_pyside.theming import ActionIconThemeHandler
from PySide6.QtCore import QByteArray, QItemSelectionModel, QPoint
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHeaderView, QMainWindow, QMenu, QMessageBox, QWidget
from rehuco_core import (
    FINISHED_JOB_STATES,
    MOVABLE_JOB_STATES,
    JobScope,
    JobState,
    JobStatus,
    StopRequest,
    TaskQueue,
)

from ..app_logging import LOG_VIEW_ICON_RESOURCE, build_log_widget, shared_log_bridge
from ..fields.colors import DONE_COLOR, ERROR_COLOR, INFO_COLOR, QUEUED_COLOR
from ..glyphs import TAB_CLOSE_GLYPH
from ..settings.logs_settings import shared_logs_settings
from .task_info_delegate import TaskInfoDelegate
from .task_queue_model import INFO_COLUMN, LABEL_COLUMN, STARTS_OVER_HINT, STATE_COLUMN, TaskQueueModel
from .task_queue_widget_ui import Ui_TaskQueueWidget
from .task_state_delegate import STATE_COLUMN_WIDTH, TaskStateDelegate
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

QUEUE_DOCK_NAME: Final = "queue"
LOG_DOCK_NAME: Final = "log"
"""Object names of this shell's two sub-docks -- the queue table and the selected job's log (#276) --
and the keys their layout is restored under."""

QUEUE_DOCK_TITLE: Final = "Queue"
LOG_DOCK_TITLE: Final = "Log"
"""Tab titles of the two sub-docks. ``Log`` matches the window's own dock and every resource's, because
all three are the same surface about a different subject ([[appendices.logging#surfaces]])."""

STATE_VERSION_KEY: Final = "version"
STATE_VERSION: Final = 1
"""Schema version of :meth:`TaskQueueWidget.save_state`'s blob. The nested layout is keyed by dock
object name, so any change to the sub-dock set makes an older blob incompatible: QtAds's
``restoreState`` would accept it and silently hide the current docks. Bump this on any such change;
:meth:`TaskQueueWidget.restore_state` ignores a blob whose version differs, keeping the built default
(the table alone, the log hidden) instead."""

STATE_DOCK_MANAGER_KEY: Final = "dock_manager"
STATE_LOG_WIDGET_KEY: Final = "log_widget"
"""Where the nested dock layout and the log surface's own filters live in that blob. The second is read
outside :data:`STATE_VERSION`'s guard on purpose, the same way ``MainWindow``'s is: that version guards
the *dock set*, while this is one widget's bands, search and tail-follow, each defaulted individually
([[appendices.logging#surfaces]])."""

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


class TaskQueueWidget(QMainWindow):  # pylint: disable=too-many-instance-attributes
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

    **A nested dock shell, like a document's** ([[appendices.task-queue#dock]], #276): a `CDockManager`
    of its own holding the queue table in one sub-dock and a **Log** sub-dock beside it, hidden until its
    toolbar toggle asks for it -- the table alone is what a reader who only wants progress sees. That log
    is the same surface the window and every resource host ([[appendices.logging#surfaces]]), attached to
    the :class:`~rehuco_core.JobScope` of whichever row is current and to nothing while none is, so
    selecting a job is how its records are reached from here. Because a record carries every scope that
    was open when it was written ([[appendices.logging#scopes]]), those records also stay in the log of
    the document the job was enqueued for and in the window's own -- three ways to the same records, not
    three copies of the routing.

    Deliberately **no** ``FocusHighlighting``: this is a fourth `CDockManager` in a window that already
    shares one native `QWindow` between three, and QtAds keeps the focused dock on that shared window
    ([[appendices.qt-ads#focus-highlighting]]). :class:`~borco_pyside.qtads.QtAdsFocusTracker` is the
    equivalent that keeps its own bookkeeping, and carries the ``stylesheet_host`` seam that keeps this
    manager from holding a fifth copy of QtAds' default sheet
    ([[appendices.qt-ads#per-manager-stylesheet]]).

    :param queue: the queue to show and act on.
    :param parent: optional Qt parent.
    :param stylesheet_host: the widget carrying the dock styling for the whole nest -- normally the
        window's outermost ``CDockManager``. Given one, this shell's manager sets no stylesheet of its
        own at all, since the host's already cascades over it.
    """

    def __init__(
        self, queue: TaskQueue, parent: QWidget | None = None, *, stylesheet_host: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.__queue: Final = queue
        self.__model: Final = TaskQueueModel(queue, self)

        # the generated form is set up on a plain panel rather than on `self`: this is a QMainWindow now,
        # whose central widget is the nested CDockManager, so a layout laid directly on it would have
        # nowhere to go. The panel is what the queue sub-dock hosts, and the toolbar the form's actions
        # fill moves to this window's own toolbar area (__setup_toolbar).
        self.__panel: Final = QWidget(self)
        self.__ui: Final = Ui_TaskQueueWidget()
        self.__ui.setupUi(self.__panel)
        self.__ui.task_view.setModel(self.__model)
        self.__ui.task_view.setItemDelegateForColumn(
            LABEL_COLUMN, TaskTextDelegate(self, state_colors=TASK_STATE_COLORS)
        )
        self.__ui.task_view.setItemDelegateForColumn(
            STATE_COLUMN, TaskStateDelegate(self, state_colors=TASK_STATE_COLORS)
        )
        self.__ui.task_view.setItemDelegateForColumn(
            INFO_COLUMN, TaskInfoDelegate(self, state_colors=TASK_STATE_COLORS)
        )
        # fixed, and to the header rather than the contents: the state cells hold one 16px glyph and
        # would collapse to a letter of their own title (#248)
        header = self.__ui.task_view.horizontalHeader()
        header.setSectionResizeMode(STATE_COLUMN, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(STATE_COLUMN, STATE_COLUMN_WIDTH)
        # selectionModel() is None only before a model is set (setModel just did)
        self.__selection_model: Final = cast(QItemSelectionModel, self.__ui.task_view.selectionModel())

        self.__log_scope: JobScope | None = None
        """The job whose log this shell's surface is currently attached under, or ``None`` while no row
        is selected. Held rather than re-read off the selection, because a change has to detach the sink
        from the scope it was attached with, not the new one (the same reason ``DocumentWidget`` holds
        its own)."""

        self.__log_widget: Final = build_log_widget(limit=shared_logs_settings().effective_resource_limit)
        """The selected job's log surface, capped like a resource's rather than like the app's: a job's
        surface has the same lifetime shape as a document's, and shows one subject's records
        ([[appendices.logging#configured-limits]])."""

        self.__dock_manager: Final = QtAds.CDockManager(self)
        # nothing holds onto it: the tracker parents itself to the manager it tracks, so Qt frees the two
        # together and there is no state here to read back off it (the current sub-dock of a two-dock
        # shell is not worth persisting, unlike a document's split)
        QtAdsFocusTracker(self.__dock_manager, close_glyph=TAB_CLOSE_GLYPH, stylesheet_host=stylesheet_host)
        self.__add_queue_dock()
        self.__log_dock: Final = self.__add_log_dock()

        self.__setup_toolbar()
        self.__setup_context_menu()
        self.__selection_model.selectionChanged.connect(self.__update_enablement)
        self.__model.snapshot_taken.connect(self.__update_enablement)
        self.__model.snapshot_taken.connect(self.__update_bulk_toggle)
        # three ways the selected job can change, and all of them have to re-point the log: the current
        # row moving, the selection being cleared (which leaves the current index right where it was),
        # and a snapshot removing or reordering rows under a selection that never moved at all
        self.__selection_model.currentChanged.connect(self.__sync_log_scope)
        self.__selection_model.selectionChanged.connect(self.__sync_log_scope)
        self.__model.snapshot_taken.connect(self.__sync_log_scope)
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

    @property
    def model(self) -> TaskQueueModel:
        """The dock's own table model -- what :class:`~.task_queue_status_indicator.TaskQueueStatusIndicator`
        (#239) follows, rather than becoming a second listener on the queue itself."""
        return self.__model

    # region toolbar and context menu

    def __setup_toolbar(self) -> None:
        ui = self.__ui
        toolbar = self.addToolBar("Tasks")
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
        toolbar.addSeparator()
        # the one control here that acts on this shell rather than on the queue, so it gets the trailing
        # slot of its own that Clear Done used to have -- a view toggle among the job controls would read
        # as a third thing done *to* the selection (#276)
        toolbar.addAction(self.__log_dock.toggleViewAction())

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

    # region the dock shell and the selected job's log

    def __add_queue_dock(self) -> None:
        """Put the queue table in this shell's first sub-dock.

        **Not closable**, unlike the log beside it: closing the only thing this dock exists to show
        would leave the Tasks dock empty with no control on it to bring the table back -- so nothing
        needs a handle on it either, and the manager it is registered with owns it.
        """
        dock = QtAds.CDockWidget(self.__dock_manager, QUEUE_DOCK_TITLE)
        dock.setObjectName(QUEUE_DOCK_NAME)
        features = QtAds.CDockWidget.DockWidgetFeature
        dock.setFeatures(features.DockWidgetFocusable | features.DockWidgetMovable)
        dock.setWidget(self.__panel)
        self.__dock_manager.addDockWidget(QtAds.CenterDockWidgetArea, dock)

    def __add_log_dock(self) -> QtAds.CDockWidget:
        """Put the selected job's log surface beside the table, hidden (#276).

        Nothing is attached here: the scope is a *selection*, so :meth:`__sync_log_scope` owns every
        attach and detach, including the first one.

        :returns: the dock, hidden.
        """
        settings = shared_logs_settings()
        dock = QtAds.CDockWidget(self.__dock_manager, LOG_DOCK_TITLE)
        dock.setObjectName(LOG_DOCK_NAME)
        features = QtAds.CDockWidget.DockWidgetFeature
        dock.setFeatures(
            features.DockWidgetFocusable
            | features.DockWidgetClosable
            | features.DockWidgetForceCloseWithArea
            | features.DockWidgetMovable
        )
        dock.setWidget(self.__log_widget)
        self.__dock_manager.addDockWidget(QtAds.RightDockWidgetArea, dock)
        ActionIconThemeHandler(dock.toggleViewAction(), LOG_VIEW_ICON_RESOURCE)
        dock.toggleView(False)
        settings.resource_limit_changed.connect(self.__on_resource_log_limit_changed)  # type: ignore[attr-defined]
        settings.app_limit_changed.connect(self.__on_resource_log_limit_changed)  # type: ignore[attr-defined]
        return dock

    def __sync_log_scope(self) -> None:
        """Point the log surface at the currently selected job, or at nothing.

        A no-op while the scope has not actually changed, which is what makes it safe to connect to
        every signal that *might* have moved the selection -- a snapshot arrives for every progress
        report, and re-attaching on each would replay the job's whole history several times a second.

        **The rows do not survive the swap**, unlike a resource's re-scope: this surface has moved to a
        different job rather than followed the same one under a new name, so what was shown is another
        subject's history. The replay on attach is what refills it, which is why a finished job's records
        still show ([[appendices.logging#replay]]).
        """
        scope = self.__current_job_scope()
        if scope == self.__log_scope:
            return
        bridge = shared_log_bridge()
        if self.__log_scope is not None:
            self.__log_widget.detach_from(bridge)
        self.__log_scope = scope
        self.__log_widget.clear()
        if scope is not None:
            self.__log_widget.attach_to(bridge, scope)

    def __current_job_scope(self) -> JobScope | None:
        """The :class:`~rehuco_core.JobScope` of the row the log follows, or ``None`` when there is none.

        Read off the *current* index, which is the one row of a multi-selection a reader is actually
        pointing at -- but gated on there being a selection at all, since clearing one leaves the current
        index exactly where it was and the surface would otherwise go on showing a job nothing points to.
        A selection whose current index is not part of it falls back to its topmost row: a selection made
        programmatically moves no current index at all, and answering ``None`` for one would make the
        surface depend on *how* the rows came to be selected.

        The row needs no bounds check, for the reason :meth:`__update_enablement` needs none either: Qt
        drops a removed row from the selection inside ``endRemoveRows`` and clears the selection outright
        on a reset, both of which run before ``snapshot_taken`` reaches this -- so a selected row is
        always a row the model still holds.

        :returns: the selected job's scope, or ``None``.
        """
        rows = self.__selected_row_indices()
        if not rows:
            return None
        current = self.__selection_model.currentIndex().row()
        row = current if current in rows else rows[0]
        return self.__model.status_at(row).scope

    def __on_resource_log_limit_changed(self, limit: int) -> None:
        """Re-cap this shell's log surface as either configured limit changes.

        Connected to **both** signals and reading neither payload, exactly as a document's is: what
        applies here is :attr:`~rehuco_agent.settings.logs_settings.LogsSettings.effective_resource_limit`,
        the per-resource limit held down to the app-wide one, so raising the app limit can raise this
        surface's cap without the per-resource number having changed at all (#236).

        :param limit: the newly-configured limit; unused, see above.
        """
        del limit
        self.__log_widget.limit = shared_logs_settings().effective_resource_limit

    @property
    def log_widget(self) -> LogWidget:
        """The selected job's log surface (#276) -- empty while no row is selected."""
        return self.__log_widget

    def save_state(self) -> bytes:
        """Serialize this shell's nested dock layout and its log surface's own filters.

        :returns: cbor2-encoded state, suitable for :meth:`restore_state`.
        """
        return cbor2.dumps(
            {
                STATE_VERSION_KEY: STATE_VERSION,
                STATE_DOCK_MANAGER_KEY: bytes(self.__dock_manager.saveState().data()),
                STATE_LOG_WIDGET_KEY: self.__log_widget.save_state(),
            }
        )

    def restore_state(self, state: bytes) -> bool:
        """Restore a layout previously captured by :meth:`save_state`.

        The log surface's filters are restored first and unconditionally: they are one widget's own
        choices, each read defensively, and a blob whose *dock set* no longer matches is still a
        perfectly good answer about them.

        :param state: the cbor2-encoded state to restore.
        :returns: ``True`` if the nested dock manager's own state was restored; ``False`` if ``state``
            was empty, malformed, not in the expected shape, or of an incompatible
            :data:`STATE_VERSION` (in which case the built default layout is kept).
        """
        try:
            values: Any = cbor2.loads(state)
        except cbor2.CBORDecodeError:
            return False
        if not isinstance(values, dict):
            return False

        log_widget_state = values.get(STATE_LOG_WIDGET_KEY)
        if isinstance(log_widget_state, bytes):
            self.__log_widget.restore_state(log_widget_state)

        # an incompatible blob would restore cleanly yet hide the current sub-docks, leaving the Tasks
        # dock blank -- ignore it and keep the built default instead
        if values.get(STATE_VERSION_KEY) != STATE_VERSION:
            return False
        dock_manager_state = values.get(STATE_DOCK_MANAGER_KEY, b"")
        if not isinstance(dock_manager_state, bytes) or not dock_manager_state:
            return False
        return bool(self.__dock_manager.restoreState(QByteArray(dock_manager_state)))

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
