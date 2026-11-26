"""Tests for how every log surface reports a clicked link (#700): through one relay, whatever surface it was in."""

from pytestqt.qtbot import QtBot
from rehuco_agent.app_logging import build_log_widget, shared_log_link_relay


def test_the_relay_is_shared() -> None:
    """Every surface and the window meet at the same object.

    **Test steps:**

    * ask for the relay twice
    * verify it is one object
    """
    assert shared_log_link_relay() is shared_log_link_relay()


def test_a_link_clicked_in_a_built_log_widget_reaches_the_relay(qtbot: QtBot) -> None:
    """The window's, a document's and the Tasks dock's logs are all built here, so each reports to the relay.

    **Test steps:**

    * build two log widgets and listen on the relay
    * make each report a link target
    * verify the relay carried both, in order, as the objects they were
    """
    first, second = build_log_widget(), build_log_widget()
    qtbot.addWidget(first)
    qtbot.addWidget(second)
    reported: list[object] = []
    shared_log_link_relay().activated.connect(reported.append)
    target = object()

    first.link_activated.emit("https://store.example/pack")
    second.link_activated.emit(target)

    assert reported == ["https://store.example/pack", target]
