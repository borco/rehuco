"""What a restart does with the saved task queue ([[appendices.task-queue#lifetime]], #202)."""

from dataclasses import dataclass, field
from typing import Final, cast

from PySide6.QtCore import QSettings

GROUP: Final = "tasks"
CLEAR_DONE_ON_RESTART_KEY: Final = "clear_done_on_restart"
CLEAR_FAILED_ON_RESTART_KEY: Final = "clear_failed_on_restart"
RESUME_ON_RESTART_KEY: Final = "resume_on_restart"


@dataclass
class TasksSettings:
    """Three restart-time choices, **all off by default** -- nothing is swept or restarted unless
    asked ([[appendices.task-queue#lifetime]]).

    Read once at startup, before :meth:`~rehuco_agent.tasks.task_queue_store.TaskQueueStore.restore`
    runs, and never again this session: nothing already open has to react to these changing, which is
    what keeps this a plain dataclass rather than the reactive ``QObject`` shape
    :class:`~rehuco_agent.settings.logs_settings.LogsSettings` uses.
    """

    clear_done_on_restart: bool = field(default=False)
    """Drop every ``done`` job read off the saved queue before it is restored."""

    clear_failed_on_restart: bool = field(default=False)
    """Drop every ``failed`` job read off the saved queue before it is restored.

    **No equivalent for ``cancelled``.** A cancelled job was stopped on purpose and is the one most
    likely to be retried; *Clear all jobs* in the dock already covers a clean slate."""

    resume_on_restart: bool = field(default=False)
    """Bring restored unfinished jobs back ``queued`` so the topmost starts immediately, instead of
    ``paused``."""

    def load(self, settings: QSettings) -> None:
        """Replace the current choices with what's in persistent storage.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        self.clear_done_on_restart = cast(bool, settings.value(CLEAR_DONE_ON_RESTART_KEY, False, type=bool))
        self.clear_failed_on_restart = cast(bool, settings.value(CLEAR_FAILED_ON_RESTART_KEY, False, type=bool))
        self.resume_on_restart = cast(bool, settings.value(RESUME_ON_RESTART_KEY, False, type=bool))
        settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Save the current choices to persistent storage.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        settings.setValue(CLEAR_DONE_ON_RESTART_KEY, self.clear_done_on_restart)
        settings.setValue(CLEAR_FAILED_ON_RESTART_KEY, self.clear_failed_on_restart)
        settings.setValue(RESUME_ON_RESTART_KEY, self.resume_on_restart)
        settings.endGroup()
