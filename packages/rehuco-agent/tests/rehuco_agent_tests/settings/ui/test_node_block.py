"""Tests for NodeBlock: the Local node block's wiring shared by the System Integration pages (#506)."""

import sys

from PySide6.QtWidgets import QCheckBox, QLabel
from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.node_host import NodeHost, NodeState
from rehuco_agent.settings.node_settings import NodeSettings, shared_node_settings
from rehuco_agent.settings.ui.node_block import NO_HOST_STATUS, STATUS_TEXTS, NodeBlock

WAITS_FOR_STDIN = [sys.executable, "-c", "import sys; sys.stdin.read()"]


@fixture
def widgets(qtbot: QtBot) -> tuple[QCheckBox, QLabel]:
    """A checkbox and a label, each kept alive by the bot for the test."""
    check_box, label = QCheckBox(), QLabel()
    qtbot.addWidget(check_box)
    qtbot.addWidget(label)
    return check_box, label


def test_without_a_host_the_status_line_is_static(widgets: tuple[QCheckBox, QLabel]) -> None:
    """A block built with no host says so once and never changes the line.

    **Test steps:**

    * build the block with ``None`` for the host
    * verify the static text
    """
    check_box, label = widgets

    NodeBlock(check_box, label, None)

    assert label.text() == NO_HOST_STATUS


def test_the_status_line_follows_the_host(qtbot: QtBot, widgets: tuple[QCheckBox, QLabel]) -> None:
    """The line shows the host's state at construction and after every change, with the pid while running.

    **Test steps:**

    * build the block over a stopped host; verify the stopped text
    * start the host and wait for running; verify the running text carries the pid
    * stop and verify the stopped text again
    """
    check_box, label = widgets
    host = NodeHost(NodeSettings(), WAITS_FOR_STDIN)
    # kept for the test's duration: the block is a plain object, and its slot goes with it when it is collected
    block = NodeBlock(check_box, label, host)
    assert label.text() == STATUS_TEXTS[NodeState.STOPPED]

    host.start()
    qtbot.waitUntil(lambda: host.state == NodeState.RUNNING, timeout=15000)
    assert label.text() == STATUS_TEXTS[NodeState.RUNNING].format(pid=host.pid)
    assert str(host.pid) in label.text()

    host.stop()
    assert label.text() == STATUS_TEXTS[NodeState.STOPPED]
    assert block.is_dirty() is False


def test_staging_save_drop_and_defaults(widgets: tuple[QCheckBox, QLabel]) -> None:
    """The checkbox stages the shared setting: dirty when it differs, saved by ``save_changes``, reverted by
    ``drop_changes``, and ``seed_defaults`` stages the factory value (on).

    **Test steps:**

    * build the block (shared setting on by default); verify not dirty and checked
    * uncheck; verify dirty; save; verify the shared setting is off and the block clean
    * check again and drop; verify unchecked; seed defaults; verify checked and dirty
    """
    check_box, label = widgets
    block = NodeBlock(check_box, label, None)
    assert check_box.isChecked() is True
    assert block.is_dirty() is False

    check_box.setChecked(False)
    assert block.is_dirty() is True
    block.save_changes()
    assert shared_node_settings().enabled is False
    assert block.is_dirty() is False

    check_box.setChecked(True)
    block.drop_changes()
    assert check_box.isChecked() is False
    block.seed_defaults()
    assert check_box.isChecked() is True
    assert block.is_dirty() is True
