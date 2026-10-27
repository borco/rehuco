"""Tests for MainWindow's quit on close: an accepted close always quits the app, floating docks or not (#507)."""

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication
from pytest import mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.documents_dock import DocumentsDock
from rehuco_agent.main_window import PLAYBACK_WRITE_TIMEOUT, MainWindow
from rehuco_agent.node_host import NodeHost

from rehuco_agent_tests.test_main_window import browsers_dock_widget, float_open_settings_dock

pytestmark = mark.usefixtures("stub_settings_pages", "stub_sub_docks")
"""Every window here is built over stub settings pages, and every document it opens over stub sub-docks (#545), but
where a test asks for the real ones (``real_settings_pages``, ``real_sub_docks``)."""


def test_an_accepted_close_quits_the_app_even_with_floating_docks_still_up(
    mocker: MockerFixture, qtbot: QtBot, real_path_stat: None
) -> None:
    """Closing the main window with tray mode off quits the app explicitly, so a floated Settings or Browsers
    window -- a top-level window Qt never counts as closed with this one -- cannot keep a headless process alive
    (#507).

    **Test steps:**

    * build the window, float the Settings dock and the Browsers dock, show both containers
    * spy on ``QApplication.quit`` and deliver an accepted close with no tray icon
    * verify ``quit`` was called exactly once
    """
    del real_path_stat
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    settings = float_open_settings_dock(window)
    browsers_dock = browsers_dock_widget(window)
    browsers_dock.toggleView(True)
    browsers_dock.setFloating()
    settings.show()
    quit_call = mocker.patch.object(QApplication, "quit")

    event = QCloseEvent()
    window.closeEvent(event)

    assert event.isAccepted()
    quit_call.assert_called_once()


def test_a_refused_close_does_not_quit(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A close the dirty-document guard refuses leaves the app running (#507 must not quit past a cancelled
    prompt).

    **Test steps:**

    * build the window and make the dirty-document guard refuse
    * spy on ``QApplication.quit`` and deliver a close
    * verify the event is ignored and ``quit`` was never called
    """
    window = MainWindow()
    qtbot.addWidget(window)
    mocker.patch("rehuco_agent.main_window.confirm_and_save_dirty", return_value=False)
    quit_call = mocker.patch.object(QApplication, "quit")

    event = QCloseEvent()
    window.closeEvent(event)

    assert not event.isAccepted()
    quit_call.assert_not_called()


def test_an_accepted_close_stops_the_node_before_anything_else_is_torn_down(
    mocker: MockerFixture, qtbot: QtBot, real_path_stat: None
) -> None:
    """The node host is stopped first thing once the guards pass (#506), ahead of the catalog's detach.

    **Test steps:**

    * build the window; record the order of ``NodeHost.stop`` and the root catalog's ``detach``
    * deliver an accepted close
    * verify ``stop`` ran once, before ``detach``
    """
    del real_path_stat
    window = MainWindow()
    qtbot.addWidget(window)
    order: list[str] = []
    mocker.patch.object(NodeHost, "stop", side_effect=lambda: order.append("stop"))
    mocker.patch.object(window._MainWindow__root_catalog, "detach", side_effect=lambda: order.append("detach"))  # type: ignore[attr-defined]  # pylint: disable=protected-access
    mocker.patch.object(QApplication, "quit")

    window.closeEvent(QCloseEvent())

    assert order == ["stop", "detach"]


def test_an_accepted_close_stops_the_players_and_waits_for_what_they_recorded(
    mocker: MockerFixture, qtbot: QtBot, real_path_stat: None
) -> None:
    """A video still playing as the app quits is stopped where it is, and the progress it recorded is written before
    the process goes: the thread that writes it is a daemon (#317).

    **Test steps:**

    * build the window and spy on the Documents dock's ``stop_playback``
    * deliver an accepted close
    * verify it was called once, with the time quitting allows for the writes
    """
    del real_path_stat
    window = MainWindow()
    qtbot.addWidget(window)
    mocker.patch.object(QApplication, "quit")
    stop_playback = mocker.patch.object(DocumentsDock, "stop_playback")

    window.closeEvent(QCloseEvent())

    stop_playback.assert_called_once_with(PLAYBACK_WRITE_TIMEOUT)


def test_a_refused_close_leaves_the_players_playing(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Stopping a video is part of going, not of being asked: a close the dirty-document guard refuses leaves it
    playing (#317).

    **Test steps:**

    * build the window, make the dirty-document guard refuse, and spy on ``stop_playback``
    * deliver a close
    * verify nothing was stopped
    """
    window = MainWindow()
    qtbot.addWidget(window)
    mocker.patch("rehuco_agent.main_window.confirm_and_save_dirty", return_value=False)
    stop_playback = mocker.patch.object(DocumentsDock, "stop_playback")

    window.closeEvent(QCloseEvent())

    stop_playback.assert_not_called()
