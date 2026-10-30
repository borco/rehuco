"""Tests for which player a double-clicked video goes to (#318, [[plugins#in-app-player]]).

The browser reads the Videos page's choice at the double-click, so these set the shared settings after the view is
shown and check which signal answers; the players themselves are the document's, and tested where they live.
"""

from pathlib import Path
from typing import Any, Final

from PySide6.QtCore import Qt
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.files_view import VLC_UNUSABLE_TEMPLATE, FilesView
from rehuco_agent.settings.videos_settings import IN_APP_PLAYER, VLC_PLAYER, shared_videos_settings
from rehuco_core import ToolCandidate, ToolStatus

from rehuco_agent_tests.documents.test_files_view_progress import (  # noqa: F401  # pylint: disable=unused-import
    fixture_model,
    fixture_view,
    names,
)

pytestmark = mark.usefixtures("real_path_stat")

USABLE_VLC: Final = ToolCandidate(Path("/opt/vlc"), "PATH", ToolStatus.USABLE, (3, 0, 23))
"""A VLC the locator found and judged usable."""

TOO_OLD_VLC: Final = ToolCandidate(
    Path("/opt/vlc"), "PATH", ToolStatus.TOO_OLD, (2, 2), "Version 3.0 or newer is needed."
)
"""A VLC the locator found and judged unusable."""


class Routing:  # pylint: disable=too-few-public-methods
    """What a double-click on the tutorial's first video answered with."""

    def __init__(self, view: FilesView) -> None:
        self.in_app: list[str] = []
        self.external: list[str] = []
        self.status: list[str] = []
        self.__view = view
        view.video_activated.connect(self.in_app.append)
        view.external_video_requested.connect(self.external.append)
        view.status_message.connect(self.status.append)

    def double_click(self) -> None:
        """Double-click the video at the top of the tutorial."""
        self.__view.activate(names(self.__view).index("a.mp4"))


@fixture(name="routing")
def fixture_routing(qtbot: QtBot, view: FilesView) -> Routing:
    """The answers of a shown browser, listening before any setting is changed.

    :param qtbot: pytest-qt fixture.
    :param view: the browser over the tutorial.
    :returns: the recorded answers.
    """
    del qtbot
    return Routing(view)


def test_the_apps_player_plays_a_video_by_default(routing: Routing) -> None:
    """A fresh install opens a video in the player dock, whether or not VLC is set up.

    **Test steps:**

    * double-click a video with the settings as installed
    * verify the in-app signal carried its key and nothing else was said
    """
    routing.double_click()

    assert routing.in_app == ["a.mp4"]
    assert not routing.external
    assert not routing.status


def test_vlc_gets_the_video_once_chosen_and_set_up(routing: Routing, fake_tool_locator: Any) -> None:
    """The choice is read at the double-click, so it applies to a document that is already open.

    **Test steps:**

    * open the browser on the app's player, then choose VLC and set it up
    * double-click a video
    * verify the external signal carried its key and the app's player was not asked
    """
    fake_tool_locator.resolve.return_value = USABLE_VLC
    shared_videos_settings().player = VLC_PLAYER

    routing.double_click()

    assert routing.external == ["a.mp4"]
    assert not routing.in_app
    assert not routing.status


def test_shift_plays_in_the_apps_player_whatever_is_chosen(
    routing: Routing, fake_tool_locator: Any, mocker: MockerFixture
) -> None:
    """SHIFT reaches the in-app player even where VLC is chosen and works.

    **Test steps:**

    * choose VLC and set it up, and hold SHIFT
    * double-click a video
    * verify the app's player was asked, VLC was not, and nothing needed explaining
    """
    fake_tool_locator.resolve.return_value = USABLE_VLC
    shared_videos_settings().player = VLC_PLAYER
    mocker.patch(
        "rehuco_agent.documents.files_view.QApplication.keyboardModifiers",
        return_value=Qt.KeyboardModifier.ShiftModifier,
    )

    routing.double_click()

    assert routing.in_app == ["a.mp4"]
    assert not routing.external
    assert not routing.status


@mark.parametrize("candidate", [None, TOO_OLD_VLC], ids=["not-set-up", "unusable"])
def test_vlc_chosen_but_unusable_falls_back_to_the_apps_player_and_says_why(
    routing: Routing, fake_tool_locator: Any, candidate: ToolCandidate | None
) -> None:
    """The in-app player is always there, so a VLC that is chosen but not usable never leaves a double-click dead.

    **Test steps:**

    * choose VLC with none set up, or one the locator judges unusable
    * double-click a video
    * verify the app's player was asked, VLC was not, and the status bar gave the reason
    """
    fake_tool_locator.resolve.return_value = candidate
    shared_videos_settings().player = VLC_PLAYER
    reason = candidate.reason if candidate is not None else "No VLC was found, and none is set up."

    routing.double_click()

    assert routing.in_app == ["a.mp4"]
    assert not routing.external
    assert routing.status == [VLC_UNUSABLE_TEMPLATE.format(reason=reason)]


def test_choosing_the_apps_player_again_takes_the_video_back(routing: Routing, fake_tool_locator: Any) -> None:
    """The choice is not remembered by the browser: each double-click asks the settings.

    **Test steps:**

    * choose VLC and double-click, then choose the app's player and double-click
    * verify the first went to VLC and the second to the app's player
    """
    fake_tool_locator.resolve.return_value = USABLE_VLC
    shared_videos_settings().player = VLC_PLAYER
    routing.double_click()
    shared_videos_settings().player = IN_APP_PLAYER

    routing.double_click()

    assert routing.external == ["a.mp4"]
    assert routing.in_app == ["a.mp4"]
