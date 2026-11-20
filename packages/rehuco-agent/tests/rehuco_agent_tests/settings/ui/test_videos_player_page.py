"""Tests for VideosPlayerPage: the Videos / Player settings page -- where a double-clicked video opens, how watching
is tracked, where the maximized player goes and how its subtitles are chosen (#316, #318, #521, #574, #618, #692)."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets.overlay_surface import OverlayMode
from rehuco_agent.settings import videos_settings
from rehuco_agent.settings.tools_settings import shared_tools_settings
from rehuco_agent.settings.ui import videos_player_page
from rehuco_agent.settings.ui.settings_frame_filter import SettingsFrameFilter
from rehuco_agent.settings.ui.videos_player_page import (
    NEEDS_LIBRARIES_TOOLTIP,
    NEEDS_VLC_TOOLTIP,
    RESTART_TEXT,
    VideosPlayerPage,
)
from rehuco_agent.settings.videos_settings import (
    FFMPEG_LIBRARIES_PLAYER,
    IN_APP_PLAYER,
    VLC_PLAYER,
    VideosSettings,
    shared_videos_settings,
)
from rehuco_core import FFMPEG_LIBRARIES_TOOL, VLC_TOOL, ToolCandidate, ToolStatus

from rehuco_agent_tests.settings.ui.test_videos_probe_page import FakeSettings

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


# region fixtures
@fixture(autouse=True)
def fake_persistent_settings(mocker: MockerFixture) -> FakeSettings:
    """Stand in for ``persistent_settings()`` so save/load never touch real storage.

    Patched on both modules that imported their own reference to it: the shared settings module
    (used by :func:`shared_videos_settings`'s lazy load) and the page module itself (used by
    :meth:`VideosPlayerPage.save_changes`).
    """
    fake = FakeSettings()
    mocker.patch.object(videos_settings, "persistent_settings", return_value=fake)
    mocker.patch.object(videos_player_page, "persistent_settings", return_value=fake)
    return fake


def page_ui(page: VideosPlayerPage) -> Any:
    """The page's generated UI object, for reaching its widgets.

    :param page: the page to reach into.
    :returns: the ``Ui_VideosPlayerPage`` instance.
    """
    return page._VideosPlayerPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access


# endregion

# region playback (#318)


def find_vlc(fake_tool_locator: Any, candidate: ToolCandidate | None = USABLE_VLC) -> None:
    """Make the locator find ``candidate`` for VLC, a usable build for the FFmpeg libraries, and nothing for any
    other tool.

    :param fake_tool_locator: the mock locator.
    :param candidate: what VLC resolves to.
    """
    found = {VLC_TOOL: candidate, FFMPEG_LIBRARIES_TOOL: USABLE_LIBRARIES}
    fake_tool_locator.resolve.side_effect = lambda tool, *_: found.get(tool)


def settle_player(qtbot: QtBot, page: VideosPlayerPage) -> None:
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
    page = VideosPlayerPage()
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
    page = VideosPlayerPage()
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
    """A choice made while VLC worked stays, and says why it cannot be honored.

    **Test steps:**

    * save VLC as the player, build the page and check with no VLC to be found
    * verify VLC is still checked and enabled, the line gives the reason, and the page is clean
    """
    shared_videos_settings().player = VLC_PLAYER
    page = VideosPlayerPage()
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
    page = VideosPlayerPage()
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
    """The Playback block's link opens Tools as the Duration Probe page's does.

    **Test steps:**

    * build the page and activate the Playback link
    * verify the page asked for Tools
    """
    page = VideosPlayerPage()
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
    page = VideosPlayerPage()
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
    page = VideosPlayerPage()
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


def test_showing_the_page_checks_the_players_tools_once(qtbot: QtBot, fake_tool_locator: Any) -> None:
    """The page asks about VLC and the FFmpeg libraries the first time it is shown, and not again on a later show.

    **Test steps:**

    * show the page, hide it and show it again
    * verify the locator was asked once about each of the two tools
    """
    page = VideosPlayerPage()
    qtbot.addWidget(page)

    with qtbot.waitSignal(page.player_checked, timeout=5000):
        page.show()
    page.hide()
    page.show()

    assert fake_tool_locator.resolve.call_count == 2


def test_a_change_to_the_vlc_tool_checks_again_once_the_page_has_asked(qtbot: QtBot, fake_tool_locator: Any) -> None:
    """The Tools page finding or losing VLC is followed without the page being shown again.

    **Test steps:**

    * check once with no VLC, then find one and announce a change to the VLC tool
    * verify the choice becomes available
    """
    page = VideosPlayerPage()
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
    mocker.patch.object(videos_player_page, "PLAYERS", (IN_APP_PLAYER, FFMPEG_LIBRARIES_PLAYER, VLC_PLAYER))


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
    mocker.patch.object(videos_player_page, "shared_playback_libraries", return_value=record)


def test_a_platform_without_the_libraries_shows_no_such_choice(qtbot: QtBot, mocker: MockerFixture) -> None:
    """**Test steps:**

    * build the page where the player names do not include the libraries
    * verify their radio is hidden
    """
    mocker.patch.object(videos_player_page, "PLAYERS", (IN_APP_PLAYER, VLC_PLAYER))
    page = VideosPlayerPage()
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
    page = VideosPlayerPage()
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
    page = VideosPlayerPage()
    qtbot.addWidget(page)

    settle_player(qtbot, page)

    assert page_ui(page).vlc_player_radio_button.isEnabled() is True
    assert page_ui(page).ffmpeg_libraries_player_radio_button.isEnabled() is False


@mark.usefixtures("with_libraries")
def test_a_selected_libraries_choice_stays_selected_and_says_why_it_cannot_be_honored(qtbot: QtBot) -> None:
    """**Test steps:**

    * save the libraries as the player, build the page and check with none to be found
    * verify the choice is still checked and enabled, the line gives the reason, and the page is clean
    """
    shared_videos_settings().player = FFMPEG_LIBRARIES_PLAYER
    page = VideosPlayerPage()
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
    page = VideosPlayerPage()
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
    page = VideosPlayerPage()
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
    page = VideosPlayerPage()
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
    page = VideosPlayerPage()
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
    page = VideosPlayerPage()
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
    page = VideosPlayerPage()
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
    page = VideosPlayerPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    ui.vlc_player_radio_button.setEnabled(True)

    ui.vlc_player_radio_button.setChecked(True)

    assert ui.player_restart_label.isHidden() is True


def test_choosing_vlc_says_it_takes_effect_at_the_next_start_only_when_another_vlc_was_loaded(
    qtbot: QtBot, mocker: MockerFixture, fake_tool_locator: Any
) -> None:
    """VLC applies at the next video selected; only another VLC's library already loaded this run waits for a start.

    **Test steps:**

    * find a usable VLC and choose it, with no library loaded this run; verify no note
    * have this run's libvlc be another install's; verify the next-start note
    """
    find_vlc(fake_tool_locator)
    restart = mocker.patch("rehuco_agent.settings.ui.videos_player_page.vlc_restart_needed", return_value=False)
    page = VideosPlayerPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    settle_player(qtbot, page)

    ui.vlc_player_radio_button.setChecked(True)
    assert ui.player_restart_label.isHidden() is True

    restart.return_value = True
    ui.in_app_player_radio_button.setChecked(True)
    ui.vlc_player_radio_button.setChecked(True)
    assert ui.player_restart_label.isHidden() is False
    assert ui.player_restart_label.text() == RESTART_TEXT


# region watch progress (#316)


def test_the_watch_checkboxes_start_on_and_a_save_reaches_the_shared_settings(qtbot: QtBot) -> None:
    """The three watch settings show their defaults, and Save puts what is ticked into the settings core's rules and
    size match are read from.

    **Test steps:**

    * build the page against empty storage and verify the three boxes are ticked and the page is clean
    * clear all three, verify the page is dirty, and save
    * verify the shared settings hold all three off and the page is clean again
    """
    page = VideosPlayerPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    boxes = (ui.mark_file_viewed_check_box, ui.mark_tutorial_viewed_check_box, ui.match_renamed_by_size_check_box)

    assert all(box.isChecked() for box in boxes)
    assert page.is_dirty() is False

    for box in boxes:
        box.setChecked(False)
    assert page.is_dirty() is True
    page.save_changes()

    settings = shared_videos_settings()
    assert settings.mark_file_viewed_at_end is False
    assert settings.mark_tutorial_viewed_on_last_file is False
    assert settings.match_renamed_by_size is False
    assert page.is_dirty() is False


def test_dropping_changes_and_seeding_defaults_move_the_watch_checkboxes(qtbot: QtBot) -> None:
    """Drop restores what is saved, and the factory defaults stage all three on.

    **Test steps:**

    * save the three off, then tick one by hand and drop the change
    * verify the box is cleared again
    * seed the defaults and verify all three are ticked, and dirty against the saved values
    """
    page = VideosPlayerPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    for box in (ui.mark_file_viewed_check_box, ui.mark_tutorial_viewed_check_box, ui.match_renamed_by_size_check_box):
        box.setChecked(False)
    page.save_changes()

    ui.mark_file_viewed_check_box.setChecked(True)
    page.drop_changes()
    assert ui.mark_file_viewed_check_box.isChecked() is False

    page.seed_defaults()
    assert ui.mark_file_viewed_check_box.isChecked() is True
    assert ui.mark_tutorial_viewed_check_box.isChecked() is True
    assert ui.match_renamed_by_size_check_box.isChecked() is True
    assert page.is_dirty() is True


# endregion


def test_the_maximize_surface_is_staged_saved_dropped_and_defaulted(qtbot: QtBot) -> None:
    """**Test steps:**

    * verify the document's choice starts checked and the page is clean
    * check the main window's, verify the page is dirty, save, and verify the shared settings hold it
    * check full-screen and drop the change, and verify the main window's is checked again
    * stage the defaults and verify the document's is checked
    """
    page = VideosPlayerPage()
    qtbot.addWidget(page)
    ui = page_ui(page)

    assert ui.maximize_document_radio_button.isChecked() is True
    assert page.is_dirty() is False

    ui.maximize_app_window_radio_button.setChecked(True)
    assert page.is_dirty() is True
    page.save_changes()
    assert shared_videos_settings().maximize_mode is OverlayMode.APP_WINDOW_OVERLAY

    ui.maximize_full_screen_radio_button.setChecked(True)
    page.drop_changes()
    assert ui.maximize_app_window_radio_button.isChecked() is True

    page.seed_defaults()
    assert ui.maximize_document_radio_button.isChecked() is True


# region Subtitles


def test_the_subtitle_choices_are_staged_saved_dropped_and_defaulted(qtbot: QtBot) -> None:
    """**Test steps:**

    * verify the page starts clean with subtitles on, every language shown and English listed
    * switch subtitles off, show only the selected languages, list Romanian then Unknown with a name VLC does not
      know, and verify the page is dirty
    * save, and verify the shared settings hold the choices with the odd name dropped, and the page is clean again
    * change one and drop it, and verify the saved choice is back
    * stage the defaults, and verify they are what a fresh settings object holds
    """
    page = VideosPlayerPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    assert (ui.subtitles_on_check_box.isChecked(), ui.subtitles_all_radio_button.isChecked()) == (True, True)
    assert ui.subtitle_languages_editor.values == ("English",)
    assert page.is_dirty() is False

    ui.subtitles_on_check_box.setChecked(False)
    ui.subtitles_selected_radio_button.setChecked(True)
    ui.subtitle_languages_editor.values = ("romanian", "Unknown", "Klingon")
    assert page.is_dirty() is True
    page.save_changes()

    settings = shared_videos_settings()
    assert (settings.subtitles_on, settings.subtitles_show_all) == (False, False)
    assert settings.subtitle_languages == ("Romanian", "Unknown")
    assert page.is_dirty() is False
    ui.subtitles_all_radio_button.setChecked(True)
    page.drop_changes()
    assert ui.subtitles_selected_radio_button.isChecked() is True

    page.seed_defaults()
    assert (ui.subtitles_on_check_box.isChecked(), ui.subtitles_all_radio_button.isChecked()) == (True, True)
    assert ui.subtitle_languages_editor.values == VideosSettings().subtitle_languages


def test_a_list_edit_that_normalizes_to_the_saved_one_is_not_a_change(qtbot: QtBot) -> None:
    """**Test steps:**

    * type the saved language in other letters and add a name VLC does not know
    * verify the page is not dirty, since saving would write what is there
    """
    page = VideosPlayerPage()
    qtbot.addWidget(page)

    page_ui(page).subtitle_languages_editor.values = ("ENGLISH", "Klingon")

    assert page.is_dirty() is False


# endregion

# region the page shell


def test_applying_one_frame_through_the_filter_saves_it_alone_on_a_page_that_reseeds_on_save(
    qtbot: QtBot,
) -> None:
    """The generic one-frame commit (`SettingsFrameFilter.apply_frame`) on a real page whose
    ``save_changes`` ends by re-seeding every widget from what was saved: the watch frame's choice
    lands in the settings, the subtitles frame's staged list does not, and after the save the staged
    list is back on screen and that frame alone reads dirty (#342).

    **Test steps:**

    * clear a checkbox in the watch frame and stage a different list in the subtitles frame
    * ``apply_frame`` the watch frame with the page's own ``save_changes``
    * verify what was saved, what is still on screen, and which frame is dirty
    """
    page = VideosPlayerPage()
    qtbot.addWidget(page)
    frame_filter = SettingsFrameFilter(page, "Player")
    ui = page_ui(page)
    ui.mark_file_viewed_check_box.setChecked(False)
    ui.subtitle_languages_editor.values = ("Romanian",)

    frame_filter.apply_frame(ui.watch_frame, page.save_changes)

    settings = shared_videos_settings()
    assert settings.mark_file_viewed_at_end is False
    assert settings.subtitle_languages == VideosSettings().subtitle_languages
    assert ui.mark_file_viewed_check_box.isChecked() is False
    assert ui.subtitle_languages_editor.values == ("Romanian",)
    assert frame_filter.dirty_frames() == [ui.subtitles_frame]
    assert page.is_dirty() is True


# endregion
