"""Tests for NodeHost: the node as a child process, started late and stopped fast (#506)."""

import sys
from pathlib import Path

from PySide6.QtCore import QProcess
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent import node_host
from rehuco_agent.node_host import NodeHost, NodeState, node_command
from rehuco_agent.settings.node_settings import NodeSettings

# captured at import, before the autouse conftest fixture replaces it on the class for every test
REAL_START_LATER = NodeHost.start_later

WAITS_FOR_STDIN = [sys.executable, "-c", "import sys; sys.stdin.read()"]
"""A child that lives until its stdin is closed, as the node does."""

EXITS_WITH_3 = [sys.executable, "-c", "raise SystemExit(3)"]
NO_SUCH_PROGRAM = ["rehuco-no-such-program-for-the-tests"]


@fixture
def settings() -> NodeSettings:
    """Node settings with the node on."""
    return NodeSettings()


def wait_for(qtbot: QtBot, host: NodeHost, state: NodeState) -> None:
    """Block until the host reports ``state``.

    :param qtbot: the bot.
    :param host: the host to watch.
    :param state: the state to wait for.
    """
    if host.state != state:
        qtbot.waitUntil(lambda: host.state == state, timeout=15000)


def test_node_command_runs_the_launched_executable_with_node(mocker: MockerFixture) -> None:
    """Launched as an executable, the node is that executable with ``--node``; a settings dir is passed on.

    **Test steps:**

    * make ``argv[0]`` an exe and the settings dir a folder
    * verify the command
    """
    mocker.patch.object(sys, "argv", ["C:\\apps\\Rehuco.exe"])
    mocker.patch.object(node_host, "settings_dir", return_value=Path("C:/state"))

    assert node_command() == [
        str(Path("C:\\apps\\Rehuco.exe").resolve()),
        "--node",
        "--settings-dir",
        str(Path("C:/state")),
    ]


def test_node_command_goes_through_the_interpreter_for_python_m(mocker: MockerFixture) -> None:
    """Launched as ``python -m rehuco_agent`` (``argv[0]`` a ``.py`` file), the node is ``python -m rehuco_agent
    --node``, with no settings dir when none is set.

    **Test steps:**

    * make ``argv[0]`` a ``__main__.py`` path and the settings dir ``None``
    * verify the command
    """
    mocker.patch.object(sys, "argv", ["C:\\src\\rehuco_agent\\__main__.py"])
    mocker.patch.object(node_host, "settings_dir", return_value=None)

    assert node_command() == [sys.executable, "-m", "rehuco_agent", "--node"]


def test_initial_state_follows_the_setting(settings: NodeSettings) -> None:
    """A host over an enabled setting starts stopped; over a disabled one, disabled.

    **Test steps:**

    * build a host with the node on and one with it off
    * verify the states and that neither reports a pid
    """
    on = NodeHost(settings, WAITS_FOR_STDIN)
    settings_off = NodeSettings()
    settings_off.enabled = False
    off = NodeHost(settings_off, WAITS_FOR_STDIN)

    assert on.state == NodeState.STOPPED
    assert off.state == NodeState.DISABLED
    assert on.pid == 0


def test_start_runs_the_node_and_stop_ends_it(qtbot: QtBot, settings: NodeSettings) -> None:
    """``start`` goes through starting to running with a pid; ``stop`` closes the child's stdin and the child
    leaves on its own, ending stopped.

    **Test steps:**

    * start, wait for running, record the pid
    * stop, verify stopped with no pid, and that the process is gone
    """
    host = NodeHost(settings, WAITS_FOR_STDIN)
    states: list[NodeState] = []
    host.state_changed.connect(states.append)

    host.start()
    wait_for(qtbot, host, NodeState.RUNNING)
    assert host.pid > 0
    host.stop()

    assert host.state == NodeState.STOPPED
    assert host.pid == 0
    assert states[:2] == [NodeState.STARTING, NodeState.RUNNING]
    assert states[-1] == NodeState.STOPPED


def test_a_second_start_while_running_is_ignored(qtbot: QtBot, settings: NodeSettings) -> None:
    """Starting a running node starts nothing: the pid stays the same.

    **Test steps:**

    * start and wait for running; start again
    * verify the pid is unchanged, then stop
    """
    host = NodeHost(settings, WAITS_FOR_STDIN)
    host.start()
    wait_for(qtbot, host, NodeState.RUNNING)
    pid = host.pid

    host.start()

    assert host.pid == pid
    host.stop()


def test_stop_kills_a_node_that_is_still_starting(qtbot: QtBot, settings: NodeSettings, mocker: MockerFixture) -> None:
    """A stop that arrives while the process still reports *starting* kills it outright, with no grace and no
    attempt to close its stdin.

    **Test steps:**

    * start and wait for the process to be up, then make it report ``Starting`` to the host
    * stop; verify ``kill`` ran and ``closeWriteChannel`` did not, and that the process is gone
    """
    host = NodeHost(settings, WAITS_FOR_STDIN)
    host.start()
    wait_for(qtbot, host, NodeState.RUNNING)
    process = host.findChild(QProcess)
    assert process is not None
    mocker.patch.object(process, "state", return_value=QProcess.ProcessState.Starting)
    kill = mocker.spy(process, "kill")
    close_stdin = mocker.spy(process, "closeWriteChannel")

    host.stop()

    kill.assert_called_once()
    close_stdin.assert_not_called()
    qtbot.waitUntil(lambda: host.state != NodeState.RUNNING, timeout=15000)


def test_stop_kills_a_node_that_ignores_its_stdin(qtbot: QtBot, settings: NodeSettings, mocker: MockerFixture) -> None:
    """A child that does not leave within the grace is killed, and the kill is waited on.

    **Test steps:**

    * start a child that never reads stdin, wait for running
    * make the grace zero and stop
    * verify ``kill`` ran and the process is gone
    """
    mocker.patch.object(node_host, "STOP_GRACE_MS", 1)
    host = NodeHost(settings, [sys.executable, "-c", "import time; time.sleep(60)"])
    host.start()
    wait_for(qtbot, host, NodeState.RUNNING)
    process = host.findChild(QProcess)
    assert process is not None
    kill = mocker.spy(process, "kill")

    host.stop()

    kill.assert_called_once()
    assert process.state() == QProcess.ProcessState.NotRunning


def test_stop_with_nothing_running_does_nothing(settings: NodeSettings) -> None:
    """``stop`` on a host that never started is a no-op.

    **Test steps:**

    * stop a fresh host
    * verify the state is unchanged
    """
    host = NodeHost(settings, WAITS_FOR_STDIN)

    host.stop()

    assert host.state == NodeState.STOPPED


def test_a_child_that_exits_with_an_error_reads_as_failed(qtbot: QtBot, settings: NodeSettings) -> None:
    """A node process ending with a non-zero code is a failure, logged, not a stop.

    **Test steps:**

    * start a child that exits with 3
    * verify the host ends failed
    """
    host = NodeHost(settings, EXITS_WITH_3)

    host.start()
    wait_for(qtbot, host, NodeState.FAILED)

    assert host.state == NodeState.FAILED


def test_a_program_that_cannot_start_reads_as_failed(qtbot: QtBot, settings: NodeSettings) -> None:
    """A command that does not exist fails to start, and the host says so.

    **Test steps:**

    * start a host over a program name nothing resolves
    * verify the host ends failed
    """
    host = NodeHost(settings, NO_SUCH_PROGRAM)

    host.start()
    wait_for(qtbot, host, NodeState.FAILED)

    assert host.state == NodeState.FAILED


def test_the_setting_starts_and_stops_the_node_live(qtbot: QtBot, settings: NodeSettings) -> None:
    """Turning the setting off stops a running node and reads disabled; turning it on starts it again.

    **Test steps:**

    * start and wait for running; set ``enabled`` ``False``
    * verify disabled and the process gone; set ``enabled`` ``True``
    * verify running again, then stop
    """
    host = NodeHost(settings, WAITS_FOR_STDIN)
    host.start()
    wait_for(qtbot, host, NodeState.RUNNING)

    settings.enabled = False
    assert host.state == NodeState.DISABLED
    assert host.pid == 0

    settings.enabled = True
    wait_for(qtbot, host, NodeState.RUNNING)
    assert host.pid > 0
    host.stop()


def test_enabling_while_the_old_process_is_still_leaving_restarts_once_it_has_gone(
    qtbot: QtBot, settings: NodeSettings
) -> None:
    """An enable that lands while the previous process is still on its way out waits for its exit and starts
    then, rather than starting nothing or starting twice.

    **Test steps:**

    * start, wait for running; make the process report ``Running`` to the enable handler as if still leaving
    * set ``enabled`` ``True`` on an already-enabled host through the handler and let the real process finish
    * verify the node is running again afterwards
    """
    host = NodeHost(settings, WAITS_FOR_STDIN)
    host.start()
    wait_for(qtbot, host, NodeState.RUNNING)
    process = host.findChild(QProcess)
    assert process is not None
    # the enable arrives while the process still runs: the host must defer the start to the exit
    host._NodeHost__on_enabled_changed(True)  # type: ignore[attr-defined]  # pylint: disable=protected-access
    first_pid = host.pid

    process.closeWriteChannel()
    qtbot.waitUntil(lambda: host.state == NodeState.RUNNING and host.pid != first_pid, timeout=15000)

    assert host.pid not in (0, first_pid)
    host.stop()


def test_start_later_starts_only_if_still_enabled(qtbot: QtBot, settings: NodeSettings) -> None:
    """The timer's start honours the setting at the time it fires: off means nothing starts.

    **Test steps:**

    * arm the real ``start_later`` with no delay on a host, then turn the setting off before it fires
    * verify nothing started; arm again with the setting on and verify it did
    """
    host = NodeHost(settings, WAITS_FOR_STDIN)
    REAL_START_LATER(host, 0)
    settings.enabled = False
    qtbot.wait(50)
    assert host.state == NodeState.DISABLED

    settings.enabled = True  # starts at once through the live handler; stop it to test the timer alone
    wait_for(qtbot, host, NodeState.RUNNING)
    host.stop()
    REAL_START_LATER(host, 0)
    wait_for(qtbot, host, NodeState.RUNNING)

    assert host.pid > 0
    host.stop()
