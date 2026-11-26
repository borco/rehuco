"""Tests for the Tasks dock's log surface as a place a link is clicked (#700)."""

from rehuco_agent.app_logging import shared_log_link_relay
from rehuco_agent.tasks.task_queue_widget import TaskQueueWidget

from rehuco_agent_tests.tasks.test_task_queue_widget import (  # noqa: F401  # pylint: disable=unused-import
    fixture_queue,
    fixture_rig,
    fixture_widget,
)


def test_a_link_clicked_in_the_tasks_docks_log_reaches_the_shared_relay(widget: TaskQueueWidget) -> None:
    """The Tasks dock's log surface is one the app builds, so a scan's links clicked there are opened as those in the
    window's log are.

    **Test steps:**

    * listen on the shared relay
    * have the Tasks dock's log surface report a clicked link
    * verify the relay carried it
    """
    reported: list[object] = []
    shared_log_link_relay().activated.connect(reported.append)

    widget.log_widget.link_activated.emit("https://store.example/pack")

    assert reported == ["https://store.example/pack"]
