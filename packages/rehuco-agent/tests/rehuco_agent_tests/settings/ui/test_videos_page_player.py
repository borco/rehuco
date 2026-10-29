"""Tests for the Videos page's Playback block: where a double-clicked video opens (#318, #521).

The page's other blocks are tested in ``test_videos_page.py``, whose fixtures and helpers this module takes.
"""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.settings.tools_settings import shared_tools_settings
from rehuco_agent.settings.ui import videos_page
from rehuco_agent.settings.ui.videos_page import NEEDS_LIBRARIES_TOOLTIP, NEEDS_VLC_TOOLTIP, RESTART_TEXT, VideosPage
from rehuco_agent.settings.videos_settings import (
    FFMPEG_LIBRARIES_PLAYER,
    IN_APP_PLAYER,
    VLC_PLAYER,
    shared_videos_settings,
)
from rehuco_core import FFMPEG_LIBRARIES_TOOL, VLC_TOOL, ToolCandidate, ToolStatus

from rehuco_agent_tests.settings.ui.test_videos_page import (  # noqa: F401  # pylint: disable=unused-import
    bundled_library_loads,
    clear_shared_instance_cache,
    fake_persistent_settings,
    page_ui,
)

USABLE_VLC = ToolCandidate(Path("/opt/vlc"), "PATH", ToolStatus.USABLE, (3, 0, 23))
"""A VLC the locator found and judged usable."""

USABLE_LIBRARIES = ToolCandidate(Path("/opt/ffmpeg/bin"), "PATH", ToolStatus.USABLE, (7, 1, 5))
"""A build of the FFmpeg libraries the locator found and judged usable."""

TOO_OLD_VLC = ToolCandidate(Path("/opt/vlc"), "PATH", ToolStatus.TOO_OLD, (2, 2), "Version 3.0 or newer is needed.")
"""A VLC the locator found and judged unusable."""

NO_VLC = "No VLC was found, and none is set up."
"""What the page says when the locator finds none."""

NO_LIBRARIES = "No FFmpeg libraries was found, and none is set up."
"""What the page says when the locator finds no build of the FFmpeg libraries."""


# region playback (#318)


def find_vlc(fake_tool_locator: Any, candidate: ToolCandidate | None = USABLE_VLC) -> None:
    """Make the locator find ``candidate`` for VLC, a usable build for the FFmpeg libraries, and nothing for any
    other tool.

    :param fake_tool_locator: the mock locator.
    :param candidate: what VLC resolves to.
    """
    found = {VLC_TOOL: candidate, FFMPEG_LIBRARIES_TOOL: USABLE_LIBRARIES}
    fake_tool_locator.resolve.side_effect = lambda tool, *_: found.get(tool)


def settle_player(qtbot: QtBot, page: VideosPage) -> None:
    """Ask the page to check VLC and wait for its answer to be shown.

    :param qtbot: the pytest-qt fixture.
    :param page: the page to check.
    """
    with qtbot.waitSignal(page.player_checked, timeout=5000):
        page.refresh_availability()


def test_a_fresh_install_opens_videos_in_the_apps_player(qtbot: QtBot) -> None:
    """With nothing persisted the player that is always there is the selected one.

    **Test steps:**

    * build the page against empty persistent storage
    * verify the app's player is checked, VLC is not, and the page is clean
    """
    page = VideosPage()
    qtbot.addWidget(page)
    ui = page_ui(page)

    assert ui.in_app_player_radio_button.isChecked() is True
    assert ui.vlc_player_radio_button.isChecked() is False
    assert page.is_dirty() is False


def test_the_vlc_choice_is_offered_only_once_vlc_is_usable(qtbot: QtBot, fake_tool_locator: Any) -> None:
    """The choice is disabled, with the way to the Tools page beside it, until VLC can be used.

    **Test steps:**

    * build the page with no VLC found and verify the choice is disabled, with its tooltip
    * check, and verify the link to the Tools page is shown and the choice is still disabled
    * find a usable VLC and check again
    * verify the choice is enabled, the tooltip gone and the link hidden
    """
    page = VideosPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    assert ui.vlc_player_radio_button.isEnabled() is False
    assert ui.vlc_player_radio_button.toolTip() == NEEDS_VLC_TOOLTIP

    settle_player(qtbot, page)
    assert ui.vlc_player_radio_button.isEnabled() is False
    assert ui.player_tools_link_label.isHidden() is False
    assert ui.player_availability_label.isHidden() is True

    find_vlc(fake_tool_locator)
    settle_player(qtbot, page)
    assert ui.vlc_player_radio_button.isEnabled() is True
    assert ui.vlc_player_radio_button.toolTip() == ""
    assert ui.player_tools_link_label.isHidden() is True


def test_a_selected_vlc_stays_selected_when_it_goes_missing(qtbot: QtBot) -> None:
    """A choice made while VLC worked stays, and says why it cannot be honoured.

    **Test steps:**

    * save VLC as the player, build the page and check with no VLC to be found
    * verify VLC is still checked and enabled, the line gives the reason, and the page is clean
    """
    shared_videos_settings().player = VLC_PLAYER
    page = VideosPage()
    qtbot.addWidget(page)
    ui = page_ui(page)

    settle_player(qtbot, page)

    assert ui.vlc_player_radio_button.isChecked() is True
    assert ui.vlc_player_radio_button.isEnabled() is True
    assert ui.player_availability_label.isHidden() is False
    assert ui.player_availability_label.text() == NO_VLC
    assert ui.player_tools_link_label.isHidden() is False
    assert page.is_dirty() is False


def test_the_reason_is_not_shown_while_the_apps_player_is_chosen(qtbot: QtBot, fake_tool_locator: Any) -> None:
    """A VLC that is not set up is no problem for someone who never chose it: the link is there, the warning is not.

    **Test steps:**

    * find an unusable VLC and check, with the app's player chosen
    * verify the reason is hidden and the link is shown
    * choose VLC
    * verify the reason is shown
    """
    find_vlc(fake_tool_locator, TOO_OLD_VLC)
    page = VideosPage()
    qtbot.addWidget(page)
    ui = page_ui(page)

    settle_player(qtbot, page)
    assert ui.player_availability_label.isHidden() is True
    assert ui.player_tools_link_label.isHidden() is False

    ui.vlc_player_radio_button.setEnabled(True)
    ui.vlc_player_radio_button.setChecked(True)

    assert ui.player_availability_label.isHidden() is False
    assert ui.player_availability_label.text() == TOO_OLD_VLC.reason


def test_the_player_links_asks_for_the_tools_page(qtbot: QtBot) -> None:
    """The Playback block's link opens Tools as the probe block's does.

    **Test steps:**

    * build the page and activate the Playback link
    * verify the page asked for Tools
    """
    page = VideosPage()
    qtbot.addWidget(page)

    with qtbot.waitSignal(page.tools_requested, timeout=1000):
        page_ui(page).player_tools_link_label.linkActivated.emit("tools")


def test_choosing_a_player_makes_the_page_dirty_and_saving_keeps_it(qtbot: QtBot, fake_tool_locator: Any) -> None:
    """Whatever is staged is what Save writes, and the shared settings are what the Files sub-dock reads.

    **Test steps:**

    * find VLC, check, and choose it
    * verify the page is dirty and nothing is saved yet
    * save
    * verify the shared settings hold VLC, the page is clean and the choice is still on screen
    """
    find_vlc(fake_tool_locator)
    page = VideosPage()
    qtbot.addWidget(page)
    settle_player(qtbot, page)

    page_ui(page).vlc_player_radio_button.setChecked(True)
    assert page.is_dirty() is True
    assert shared_videos_settings().player == IN_APP_PLAYER

    page.save_changes()

    assert shared_videos_settings().player == VLC_PLAYER
    assert page.is_dirty() is False
    assert page_ui(page).vlc_player_radio_button.isChecked() is True


def test_dropping_changes_and_seeding_defaults_move_the_player_choice(qtbot: QtBot) -> None:
    """Reset puts back what was saved, and Defaults the app's own player.

    **Test steps:**

    * save VLC, build the page and stage the app's player
    * drop the changes and verify VLC is back
    * seed the defaults and verify the app's player is staged and the page is dirty
    """
    shared_videos_settings().player = VLC_PLAYER
    page = VideosPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    ui.in_app_player_radio_button.setChecked(True)
    assert page.is_dirty() is True

    page.drop_changes()
    assert ui.vlc_player_radio_button.isChecked() is True
    assert page.is_dirty() is False

    page.seed_defaults()
    assert ui.in_app_player_radio_button.isChecked() is True
    assert page.is_dirty() is True


def test_a_change_to_the_vlc_tool_checks_again_once_the_page_has_asked(qtbot: QtBot, fake_tool_locator: Any) -> None:
    """The Tools page finding or losing VLC is followed without the page being shown again.

    **Test steps:**

    * check once with no VLC, then find one and announce a change to the VLC tool
    * verify the choice becomes available
    """
    page = VideosPage()
    qtbot.addWidget(page)
    settle_player(qtbot, page)
    assert page_ui(page).vlc_player_radio_button.isEnabled() is False
    find_vlc(fake_tool_locator)

    with qtbot.waitSignal(page.player_checked, timeout=5000):
        shared_tools_settings().tool_changed.emit(VLC_TOOL.ID)

    assert page_ui(page).vlc_player_radio_button.isEnabled() is True


# endregion


# region the FFmpeg libraries choice (#580)


@fixture(name="with_libraries")
def fixture_with_libraries(mocker: MockerFixture) -> None:
    """Make the page offer the libraries choice whatever the platform, so its logic is tested everywhere.

    :param mocker: the pytest-mock fixture.
    """
    mocker.patch.object(videos_page, "PLAYERS", (IN_APP_PLAYER, FFMPEG_LIBRARIES_PLAYER, VLC_PLAYER))


def libraries_run(mocker: MockerFixture, *, loaded: bool, reason: str | None = None) -> None:
    """Say what this run did about the libraries, as the start-up recorded it.

    :param mocker: the pytest-mock fixture.
    :param loaded: whether a build was loaded.
    :param reason: why Qt's own libraries are in use although the others were asked for, or ``None``.
    """
    record = SimpleNamespace(
        requested=loaded or reason is not None,
        loaded_from=Path("/ffmpeg/bin") if loaded else None,
        fallback_reason=reason,
    )
    mocker.patch.object(videos_page, "shared_playback_libraries", return_value=record)


def test_a_platform_without_the_libraries_shows_no_such_choice(qtbot: QtBot, mocker: MockerFixture) -> None:
    """**Test steps:**

    * build the page where the player names do not include the libraries
    * verify their radio is hidden
    """
    mocker.patch.object(videos_page, "PLAYERS", (IN_APP_PLAYER, VLC_PLAYER))
    page = VideosPage()
    qtbot.addWidget(page)

    assert page_ui(page).ffmpeg_libraries_player_radio_button.isHidden() is True


@mark.usefixtures("with_libraries")
def test_the_libraries_choice_is_offered_only_once_a_build_is_usable(qtbot: QtBot, fake_tool_locator: Any) -> None:
    """The choice is disabled, with the way to the Tools page beside it, until a build can be used.

    **Test steps:**

    * build the page with no build found and verify the choice is disabled, with its tooltip
    * check, and verify the link to the Tools page is shown
    * find a usable build and check again
    * verify the choice is enabled and the tooltip gone
    """
    page = VideosPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    radio = ui.ffmpeg_libraries_player_radio_button
    assert radio.isEnabled() is False
    assert radio.toolTip() == NEEDS_LIBRARIES_TOOLTIP

    settle_player(qtbot, page)
    assert radio.isEnabled() is False
    assert ui.player_tools_link_label.isHidden() is False

    find_vlc(fake_tool_locator)
    settle_player(qtbot, page)
    assert radio.isEnabled() is True
    assert radio.toolTip() == ""


@mark.usefixtures("with_libraries")
def test_the_libraries_choice_checks_its_own_tool(qtbot: QtBot, fake_tool_locator: Any) -> None:
    """VLC being fine says nothing about the libraries, and the other way round.

    **Test steps:**

    * find a usable VLC and no libraries, and check
    * verify VLC is offered and the libraries are not
    """
    fake_tool_locator.resolve.side_effect = lambda tool, *_: USABLE_VLC if tool is VLC_TOOL else None
    page = VideosPage()
    qtbot.addWidget(page)

    settle_player(qtbot, page)

    assert page_ui(page).vlc_player_radio_button.isEnabled() is True
    assert page_ui(page).ffmpeg_libraries_player_radio_button.isEnabled() is False


@mark.usefixtures("with_libraries")
def test_a_selected_libraries_choice_stays_selected_and_says_why_it_cannot_be_honoured(qtbot: QtBot) -> None:
    """**Test steps:**

    * save the libraries as the player, build the page and check with none to be found
    * verify the choice is still checked and enabled, the line gives the reason, and the page is clean
    """
    shared_videos_settings().player = FFMPEG_LIBRARIES_PLAYER
    page = VideosPage()
    qtbot.addWidget(page)
    ui = page_ui(page)

    settle_player(qtbot, page)

    assert ui.ffmpeg_libraries_player_radio_button.isChecked() is True
    assert ui.ffmpeg_libraries_player_radio_button.isEnabled() is True
    assert ui.player_availability_label.text() == NO_LIBRARIES
    assert page.is_dirty() is False


@mark.usefixtures("with_libraries")
def test_choosing_the_libraries_is_saved_and_says_it_takes_effect_at_the_next_start(
    qtbot: QtBot, mocker: MockerFixture, fake_tool_locator: Any
) -> None:
    """The libraries load before the player's code, so a change reaches the next start only, and the page says so.

    **Test steps:**

    * run with Qt's own libraries, find a usable build, and choose the libraries
    * verify the page is dirty, the next-start note is shown, and saving writes the choice
    * choose the app's player again and verify the note is gone
    """
    libraries_run(mocker, loaded=False)
    find_vlc(fake_tool_locator)
    page = VideosPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    settle_player(qtbot, page)
    assert ui.player_restart_label.isHidden() is True

    ui.ffmpeg_libraries_player_radio_button.setChecked(True)
    assert page.is_dirty() is True
    assert ui.player_restart_label.isHidden() is False
    assert ui.player_restart_label.text() == RESTART_TEXT

    page.save_changes()
    assert shared_videos_settings().player == FFMPEG_LIBRARIES_PLAYER

    ui.in_app_player_radio_button.setChecked(True)
    assert ui.player_restart_label.isHidden() is True


@mark.usefixtures("with_libraries")
def test_leaving_the_libraries_also_waits_for_the_next_start(qtbot: QtBot, mocker: MockerFixture) -> None:
    """This run has the build loaded; it stays loaded until the process ends.

    **Test steps:**

    * run with a build loaded and the libraries saved
    * verify no note is shown
    * choose the app's player and verify the next-start note is
    """
    libraries_run(mocker, loaded=True)
    shared_videos_settings().player = FFMPEG_LIBRARIES_PLAYER
    page = VideosPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    assert ui.player_restart_label.isHidden() is True

    ui.in_app_player_radio_button.setChecked(True)

    assert ui.player_restart_label.text() == RESTART_TEXT


@mark.usefixtures("with_libraries")
def test_a_start_that_could_not_load_the_libraries_says_why(qtbot: QtBot, mocker: MockerFixture) -> None:
    """The choice stays what the user made; the page says Qt's own FFmpeg is in use and why.

    **Test steps:**

    * run with the libraries saved and a start that fell back
    * verify the note names Qt's own FFmpeg, the reason and that the next start tries again
    * choose the app's player and verify the note is gone
    """
    libraries_run(mocker, loaded=False, reason="avutil-59.dll did not load.")
    shared_videos_settings().player = FFMPEG_LIBRARIES_PLAYER
    page = VideosPage()
    qtbot.addWidget(page)
    ui = page_ui(page)

    assert ui.player_restart_label.isHidden() is False
    assert "avutil-59.dll did not load." in ui.player_restart_label.text()
    assert "next start" in ui.player_restart_label.text()

    ui.in_app_player_radio_button.setChecked(True)
    assert ui.player_restart_label.text() == ""


@mark.usefixtures("with_libraries")
def test_dropping_and_seeding_move_the_libraries_choice_too(qtbot: QtBot) -> None:
    """**Test steps:**

    * save the libraries, build the page and stage VLC
    * drop the changes and verify the libraries are back
    * seed the defaults and verify the app's player is staged
    """
    shared_videos_settings().player = FFMPEG_LIBRARIES_PLAYER
    page = VideosPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    ui.vlc_player_radio_button.setChecked(True)
    assert page.is_dirty() is True

    page.drop_changes()
    assert ui.ffmpeg_libraries_player_radio_button.isChecked() is True
    assert page.is_dirty() is False

    page.seed_defaults()
    assert ui.in_app_player_radio_button.isChecked() is True


@mark.usefixtures("with_libraries")
def test_a_change_to_the_libraries_tool_checks_again(qtbot: QtBot, fake_tool_locator: Any) -> None:
    """**Test steps:**

    * check once with no build, then find one and announce a change to the libraries tool
    * verify the choice becomes available
    """
    page = VideosPage()
    qtbot.addWidget(page)
    settle_player(qtbot, page)
    assert page_ui(page).ffmpeg_libraries_player_radio_button.isEnabled() is False
    find_vlc(fake_tool_locator)

    with qtbot.waitSignal(page.player_checked, timeout=5000):
        shared_tools_settings().tool_changed.emit(FFMPEG_LIBRARIES_TOOL.ID)

    assert page_ui(page).ffmpeg_libraries_player_radio_button.isEnabled() is True


@mark.usefixtures("with_libraries")
def test_a_check_that_fails_is_reported_naming_the_tool(qtbot: QtBot, fake_tool_locator: Any) -> None:
    """**Test steps:**

    * make asking the locator raise, and choose the libraries
    * verify the line names the tool and the error
    """
    fake_tool_locator.resolve.side_effect = RuntimeError("boom")
    shared_videos_settings().player = FFMPEG_LIBRARIES_PLAYER
    page = VideosPage()
    qtbot.addWidget(page)

    settle_player(qtbot, page)

    assert page_ui(page).player_availability_label.text() == "Checking FFmpeg libraries failed: boom"


# endregion


@mark.usefixtures("with_libraries")
def test_staging_vlc_says_nothing_about_a_restart(qtbot: QtBot, mocker: MockerFixture) -> None:
    """VLC applies at once, and whatever is loaded stays loaded for SHIFT+double-click.

    **Test steps:**

    * run with a build loaded and the libraries saved, then stage VLC
    * verify no next-start note
    """
    libraries_run(mocker, loaded=True)
    shared_videos_settings().player = FFMPEG_LIBRARIES_PLAYER
    page = VideosPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    ui.vlc_player_radio_button.setEnabled(True)

    ui.vlc_player_radio_button.setChecked(True)

    assert ui.player_restart_label.isHidden() is True
