"""The agent's side of the local node: a child process started late and stopped fast (#506, [[nodes#two-roles]]).

The node runs as the agent's user, for as long as the agent runs -- in the tray included -- and is **never
allowed to slow the agent down**: it starts on a timer a few seconds after the window is up, so opening a file
pays nothing for it, and a quit that arrives while it is still starting kills it outright rather than waiting.
A running node is asked to stop by closing its stdin (the pipe the node watches, see ``rehuco_node``), with a
short grace before it is killed.
"""

import logging
from collections.abc import Sequence
from enum import StrEnum
from typing import Final

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from .own_program import own_program
from .settings.node_settings import NodeSettings
from .settings.persistent_settings import settings_dir

LOG: Final = logging.getLogger(__name__)

START_DELAY_MS: Final = 3000
"""How long after :meth:`NodeHost.start_later` the node is started: past the window's own first paint and the
first document's open."""

STOP_GRACE_MS: Final = 1500
"""How long a running node gets to leave on its own after its stdin is closed, before it is killed."""

KILL_WAIT_MS: Final = 500
"""How long a kill is waited on, so the process is gone before the agent exits."""


class NodeState(StrEnum):
    """Where the hosted node is in its life, as the System Integration page shows it."""

    DISABLED = "disabled"
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    FAILED = "failed"


def node_command() -> list[str]:
    """The command that runs the node the same way this agent was run.

    ``rehuco-agent --node`` reaches the node's ``main``, so the packaged exe, the dev launcher and the console
    script all host it as themselves; only ``python -m rehuco_agent`` (``argv[0]`` a ``.py`` file) has to go back
    through the interpreter. A settings dir is passed on, so the node writes where this agent reads
    ([[packaging-deployment#app-folders]]).

    :returns: the program and its arguments.
    """
    command = [*own_program(), "--node"]
    folder = settings_dir()
    if folder is not None:
        command += ["--settings-dir", str(folder)]
    return command


class NodeHost(QObject):
    """Starts, watches and stops the local node process, following `NodeSettings.enabled` live.

    :param settings: the shared node settings; ``enabled`` is followed as it changes.
    :param command: the program and arguments that run the node; :func:`node_command` by default.
    :param parent: optional Qt parent.
    """

    state_changed = Signal(object)
    """Emitted with the new :class:`NodeState` whenever it changes."""

    def __init__(
        self, settings: NodeSettings, command: Sequence[str] | None = None, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self.__settings: Final = settings
        self.__command: Final = list(node_command() if command is None else command)
        self.__process: Final = QProcess(self)
        self.__process.setProcessChannelMode(QProcess.ProcessChannelMode.ForwardedChannels)
        self.__process.started.connect(self.__on_started)
        self.__process.finished.connect(self.__on_finished)
        self.__process.errorOccurred.connect(self.__on_error)
        self.__state: NodeState = NodeState.DISABLED if not settings.enabled else NodeState.STOPPED
        # a start requested while the node is already leaving (enabled toggled off and on quickly) waits for the exit
        self.__restart_pending = False
        settings.enabled_changed.connect(self.__on_enabled_changed)  # type: ignore[attr-defined]

    @property
    def state(self) -> NodeState:
        """Where the node is in its life."""
        return self.__state

    @property
    def pid(self) -> int:
        """The node's process id while it runs, ``0`` otherwise."""
        return int(self.__process.processId()) if self.__state == NodeState.RUNNING else 0

    def start_later(self, delay_ms: int = START_DELAY_MS) -> None:
        """Start the node after ``delay_ms``, if it is enabled then.

        :param delay_ms: the delay; :data:`START_DELAY_MS` by default.
        """
        QTimer.singleShot(delay_ms, self, self.__start_if_enabled)

    def start(self) -> None:
        """Start the node now, unless it already runs or is starting."""
        if self.__process.state() != QProcess.ProcessState.NotRunning:
            return
        self.__restart_pending = False
        LOG.info("starting the local node: %s", " ".join(self.__command))
        self.__set_state(NodeState.STARTING)
        self.__process.start(self.__command[0], self.__command[1:])

    def stop(self) -> None:
        """Stop the node, fast: a node still starting is killed at once, a running one gets :data:`STOP_GRACE_MS`
        after its stdin is closed, then is killed too. Returns with the process gone."""
        self.__restart_pending = False
        state = self.__process.state()
        if state == QProcess.ProcessState.NotRunning:
            return
        if state == QProcess.ProcessState.Starting:
            LOG.info("the local node was still starting; killing it")
            self.__process.kill()
            self.__process.waitForFinished(KILL_WAIT_MS)
            return
        LOG.info("asking the local node to stop")
        self.__process.closeWriteChannel()
        if not self.__process.waitForFinished(STOP_GRACE_MS):
            LOG.warning("the local node did not stop in %d ms; killing it", STOP_GRACE_MS)
            self.__process.kill()
            self.__process.waitForFinished(KILL_WAIT_MS)

    def __start_if_enabled(self) -> None:
        """The timer's target: start only if the setting is still on by the time it fires."""
        if self.__settings.enabled:
            self.start()

    def __on_enabled_changed(self, enabled: bool) -> None:
        """Follow the setting live: start when turned on, stop when turned off.

        :param enabled: the new value.
        """
        if enabled:
            if self.__process.state() == QProcess.ProcessState.NotRunning:
                self.start()
            else:
                # the process is still on its way out from a stop; start again once it has gone
                self.__restart_pending = True
        else:
            self.stop()
            self.__set_state(NodeState.DISABLED)

    def __on_started(self) -> None:
        """The process is up."""
        LOG.info("the local node runs, pid %d", self.__process.processId())
        self.__set_state(NodeState.RUNNING)

    def __on_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        """The process is gone, however it went.

        :param exit_code: its exit code.
        :param exit_status: whether it exited or crashed.
        """
        crashed = exit_status == QProcess.ExitStatus.CrashExit
        if crashed or exit_code != 0:
            LOG.warning("the local node ended with code %d (%s)", exit_code, exit_status.name)
            self.__set_state(NodeState.FAILED)
        else:
            LOG.info("the local node stopped")
            self.__set_state(NodeState.DISABLED if not self.__settings.enabled else NodeState.STOPPED)
        if self.__restart_pending and self.__settings.enabled:
            self.start()

    def __on_error(self, error: QProcess.ProcessError) -> None:
        """The process could not be started or broke; a crash also reaches :meth:`__on_finished`.

        :param error: what went wrong.
        """
        if error == QProcess.ProcessError.FailedToStart:
            LOG.error("the local node could not be started: %s", self.__process.errorString())
            self.__set_state(NodeState.FAILED)

    def __set_state(self, state: NodeState) -> None:
        """Record and announce a state, once per change.

        :param state: the new state.
        """
        if state == self.__state:
            return
        self.__state = state
        self.state_changed.emit(state)
