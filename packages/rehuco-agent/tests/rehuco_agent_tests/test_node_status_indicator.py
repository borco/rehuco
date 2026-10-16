"""Tests for NodeStatusIndicator: the status bar's word on the local node (#506)."""

from PySide6.QtCore import QObject, Signal
from pytestqt.qtbot import QtBot
from rehuco_agent.node_host import NodeState
from rehuco_agent.node_status_indicator import RUNNING_TEXT, STOPPED_TEXT, NodeStatusIndicator


class FakeHost(QObject):
    """A host whose state and pid a test sets directly."""

    state_changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.state = NodeState.STOPPED
        self.pid = 0

    def become(self, state: NodeState, pid: int = 0) -> None:
        """Move to ``state`` with ``pid`` and announce it.

        :param state: the new state.
        :param pid: the pid to report.
        """
        self.state = state
        self.pid = pid
        self.state_changed.emit(state)


def test_starts_greyed_out_and_stopped(qtbot: QtBot) -> None:
    """Built over a stopped host, the label says Stopped and is disabled, so the palette greys it.

    **Test steps:**

    * build the indicator over a fake host that is stopped
    * verify the text, the enabled flag and the tooltip
    """
    host = FakeHost()
    indicator = NodeStatusIndicator(host)  # type: ignore[arg-type]
    qtbot.addWidget(indicator)

    assert indicator.text() == STOPPED_TEXT
    assert indicator.isEnabled() is False
    assert "not running" in indicator.toolTip()


def test_running_reads_running_with_the_pid_in_the_tooltip(qtbot: QtBot) -> None:
    """Once the host runs, the label says Running, is enabled, and the tooltip names the pid.

    **Test steps:**

    * move the fake host to running with a pid
    * verify the text, the enabled flag and the pid in the tooltip
    """
    host = FakeHost()
    indicator = NodeStatusIndicator(host)  # type: ignore[arg-type]
    qtbot.addWidget(indicator)

    host.become(NodeState.RUNNING, pid=777)

    assert indicator.text() == RUNNING_TEXT
    assert indicator.isEnabled() is True
    assert "777" in indicator.toolTip()


def test_every_other_state_reads_stopped_with_its_own_tooltip(qtbot: QtBot) -> None:
    """Disabled, starting and failed all show Stopped greyed out; only the tooltip tells them apart.

    **Test steps:**

    * move the fake host through disabled, starting and failed
    * verify the text and flag each time, and that the tooltips differ
    """
    host = FakeHost()
    indicator = NodeStatusIndicator(host)  # type: ignore[arg-type]
    qtbot.addWidget(indicator)
    tooltips: set[str] = set()

    for state in (NodeState.DISABLED, NodeState.STARTING, NodeState.FAILED):
        host.become(state)
        assert indicator.text() == STOPPED_TEXT
        assert indicator.isEnabled() is False
        tooltips.add(indicator.toolTip())

    assert len(tooltips) == 3
