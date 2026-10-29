"""Tests for VideosPage: the Videos settings category page (#225)."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from borco_pyside.widgets import StringListEditor
from pymediainfo import MediaInfo
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.settings import videos_settings
from rehuco_agent.settings.tools_settings import ToolDetection, shared_tools_settings
from rehuco_agent.settings.ui import videos_page
from rehuco_agent.settings.ui.settings_frame_filter import SettingsFrameFilter
from rehuco_agent.settings.ui.videos_page import CHECKING_TEXT, NEEDS_FFMPEG_TOOLTIP, VideosPage
from rehuco_agent.settings.videos_settings import VideosSettings, shared_videos_settings
from rehuco_core import (
    EXTERNAL_TOOLS,
    FFMPEG_TOOL,
    VIDEO_EXTENSIONS,
    FfprobeDurationProbe,
    MediaInfoDurationProbe,
    ToolCandidate,
    ToolStatus,
)

USABLE_FFMPEG = ToolCandidate(Path("/opt/ffmpeg/bin"), "PATH", ToolStatus.USABLE, (7, 1))
"""An FFmpeg the locator found and judged usable."""

NO_FFMPEG = "No FFmpeg was found, and none is set up."
"""What the probe says when the locator finds none."""


# region fixtures
# Mirrors test_excluded_files_page.py's (and conftest.py's) FakeSettings exactly -- kept as a separate
# copy rather than a shared import, matching this codebase's settings-test convention.
# pylint: disable=duplicate-code
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/value API (see
    ``test_videos_settings.py`` for the full rationale)."""

    def __init__(self) -> None:
        self.__data: dict[str, Any] = {}
        self.__group = ""

    def beginGroup(self, name: str) -> None:  # noqa: N802
        self.__group = f"{name}/"

    def endGroup(self) -> None:  # noqa: N802
        self.__group = ""

    def setValue(self, key: str, value: Any) -> None:  # noqa: N802
        self.__data[self.__group + key] = value

    def value(self, key: str, default: Any = None, type: Any = None) -> Any:  # noqa: A002, N802
        del type
        return self.__data.get(self.__group + key, default)


# pylint: enable=duplicate-code


@fixture(autouse=True)
def fake_persistent_settings(mocker: MockerFixture) -> FakeSettings:
    """Stand in for ``persistent_settings()`` so save/load never touch real storage.

    Patched on both modules that imported their own reference to it: the shared settings module
    (used by :func:`shared_videos_settings`'s lazy load) and the page module itself (used by
    :meth:`VideosPage.save_changes`).
    """
    fake = FakeSettings()
    mocker.patch.object(videos_settings, "persistent_settings", return_value=fake)
    mocker.patch.object(videos_page, "persistent_settings", return_value=fake)
    return fake


@fixture(autouse=True)
def bundled_library_loads(mocker: MockerFixture) -> None:
    """Report the bundled MediaInfo library as loadable, whatever the machine running the tests has.

    The availability line is the page's own answer, not the host's: leaving this to the real library
    would make every assertion on it depend on how ``pymediainfo`` happened to be installed.
    """
    mocker.patch.object(MediaInfo, "can_parse", return_value=True)


@fixture(autouse=True)
def clear_shared_instance_cache() -> Iterator[None]:
    """Clear the shared settings singleton before and after every test (see
    ``test_markdown_rendering_settings.py`` for the full rationale)."""
    shared_videos_settings.cache_clear()
    yield
    shared_videos_settings.cache_clear()


def page_ui(page: VideosPage) -> Any:
    """The page's generated UI object, for reaching its widgets.

    :param page: the page to reach into.
    :returns: the ``Ui_VideosPage`` instance.
    """
    return page._VideosPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access


def extensions_editor(page: VideosPage) -> StringListEditor:
    """The page's video-extension list editor.

    :param page: the page to reach into.
    :returns: the `StringListEditor` holding the recognized formats.
    """
    return page_ui(page).extensions_editor


def settle(qtbot: QtBot, page: VideosPage) -> None:
    """Ask the page to check FFmpeg and wait for its answer to be shown.

    :param qtbot: the pytest-qt fixture.
    :param page: the page to check.
    """
    with qtbot.waitSignal(page.availability_checked, timeout=5000):
        page.refresh_availability()


# endregion

# region the probe choice


def test_starts_on_the_bundled_backend_on_a_fresh_install(qtbot: QtBot) -> None:
    """With nothing persisted, the backend that works with nothing installed is the selected one (#224).

    **Test steps:**

    * build the page against empty persistent storage
    * verify the bundled backend is checked, ffprobe is not, and the page is clean
    """
    page = VideosPage()
    qtbot.addWidget(page)
    ui = page_ui(page)

    assert ui.mediainfo_probe_radio_button.isChecked() is True
    assert ui.ffprobe_probe_radio_button.isChecked() is False
    assert page.is_dirty() is False


def test_the_backends_name_themselves(qtbot: QtBot) -> None:
    """Each radio wears the probe's own ``LABEL``, so the choice tracks the registry (#224).

    **Test steps:**

    * build the page
    * verify each radio's text is its probe's label
    """
    page = VideosPage()
    qtbot.addWidget(page)
    ui = page_ui(page)

    assert ui.mediainfo_probe_radio_button.text() == MediaInfoDurationProbe.LABEL
    assert ui.ffprobe_probe_radio_button.text() == FfprobeDurationProbe.LABEL


def test_the_ffmpeg_choice_is_offered_only_once_ffmpeg_is_usable(qtbot: QtBot, fake_tool_locator: Any) -> None:
    """The choice is disabled, with the way to the Tools page beside it, until FFmpeg can be used (#521).

    **Test steps:**

    * build the page with no FFmpeg found and verify the choice is disabled, with its tooltip
    * check, and verify the link to the Tools page is shown and the choice is still disabled
    * find a usable FFmpeg and check again
    * verify the choice is enabled, the tooltip gone and the link hidden
    """
    page = VideosPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    assert ui.ffprobe_probe_radio_button.isEnabled() is False
    assert ui.ffprobe_probe_radio_button.toolTip() == NEEDS_FFMPEG_TOOLTIP

    settle(qtbot, page)
    assert ui.ffprobe_probe_radio_button.isEnabled() is False
    assert ui.tools_link_label.isHidden() is False

    fake_tool_locator.resolve.return_value = USABLE_FFMPEG
    settle(qtbot, page)
    assert ui.ffprobe_probe_radio_button.isEnabled() is True
    assert ui.ffprobe_probe_radio_button.toolTip() == ""
    assert ui.tools_link_label.isHidden() is True


def test_a_selected_ffmpeg_stays_selected_when_it_goes_missing(qtbot: QtBot) -> None:
    """A choice made while FFmpeg worked is still what the next scan uses, so it stays, and says why it cannot (#521).

    **Test steps:**

    * save ffprobe as the engine, build the page and check with no FFmpeg to be found
    * verify ffprobe is still checked and enabled, and the line gives the reason
    """
    shared_videos_settings().engine = FfprobeDurationProbe.NAME
    page = VideosPage()
    qtbot.addWidget(page)
    ui = page_ui(page)

    settle(qtbot, page)

    assert ui.ffprobe_probe_radio_button.isChecked() is True
    assert ui.ffprobe_probe_radio_button.isEnabled() is True
    assert ui.availability_label.text() == NO_FFMPEG
    assert page.is_dirty() is False


def test_the_link_asks_for_the_tools_page(qtbot: QtBot) -> None:
    """Following the link is the page's whole part in opening Tools; the dialog does the showing (#521).

    **Test steps:**

    * build the page and activate the link
    * verify the page asked for Tools
    """
    page = VideosPage()
    qtbot.addWidget(page)

    with qtbot.waitSignal(page.tools_requested, timeout=1000):
        page_ui(page).tools_link_label.linkActivated.emit("tools")


def test_showing_the_page_checks_ffmpeg_again(qtbot: QtBot) -> None:
    """A tool installed since, or a share unmounted, is seen each time the page is shown (#521).

    **Test steps:**

    * build the page and show it
    * verify the check ran and its answer is on screen
    """
    page = VideosPage()
    qtbot.addWidget(page)

    with qtbot.waitSignal(page.availability_checked, timeout=5000):
        page.show()

    assert page_ui(page).ffprobe_probe_radio_button.isEnabled() is False


def test_the_check_asks_for_the_path_the_tools_page_saved(qtbot: QtBot, fake_tool_locator: Any) -> None:
    """The page asks about the saved FFmpeg, whatever the staged choice (#521).

    **Test steps:**

    * save a path for FFmpeg and check
    * verify the locator was asked about that path
    """
    shared_tools_settings().set_path(FFMPEG_TOOL.ID, "/opt/ffmpeg")
    page = VideosPage()
    qtbot.addWidget(page)

    settle(qtbot, page)

    fake_tool_locator.resolve.assert_any_call(FFMPEG_TOOL, "/opt/ffmpeg", ())


def test_choosing_a_backend_makes_the_page_dirty(qtbot: QtBot) -> None:
    """Whatever is staged is what Save would write, so switching backend is a change to the page.

    **Test steps:**

    * build the page and select the other backend
    * verify the page went dirty
    """
    page = VideosPage()
    qtbot.addWidget(page)

    page_ui(page).ffprobe_probe_radio_button.setChecked(True)

    assert page.is_dirty() is True


# endregion

# region the availability line


def test_reports_the_bundled_backend_as_ready(qtbot: QtBot) -> None:
    """A usable backend says so by name, so the line is never blank (#225).

    **Test steps:**

    * build the page on the bundled backend
    * verify the availability line names it as ready
    """
    page = VideosPage()
    qtbot.addWidget(page)

    assert page_ui(page).availability_label.text() == f"{MediaInfoDurationProbe.LABEL} is ready."


def test_reports_an_unusable_ffmpeg_before_any_scan_is_run(qtbot: QtBot) -> None:
    """An FFmpeg that cannot be used is reported here, in the probe's own words (#224, #225, #521).

    This is the page's reason for showing a status at all: a scan under an unusable backend raises
    rather than measuring ``0``, so the misconfiguration has to be visible before Compute is pressed.

    **Test steps:**

    * build the page, select ffprobe and check with none found
    * verify the line gives the probe's reason
    """
    page = VideosPage()
    qtbot.addWidget(page)
    ui = page_ui(page)

    ui.ffprobe_probe_radio_button.setChecked(True)
    settle(qtbot, page)

    assert ui.availability_label.text() == NO_FFMPEG


def test_says_it_is_checking_until_the_answer_comes(qtbot: QtBot) -> None:
    """Asking about FFmpeg runs it, so until the answer is in the line says so rather than guessing (#521).

    **Test steps:**

    * build the page with ffprobe selected, before any check has answered
    * verify the line says it is checking
    """
    page = VideosPage()
    qtbot.addWidget(page)

    page_ui(page).ffprobe_probe_radio_button.setChecked(True)

    assert page_ui(page).availability_label.text() == CHECKING_TEXT


def test_reports_a_check_that_failed(qtbot: QtBot, fake_tool_locator: Any) -> None:
    """A check that raises is shown as such, never left reading as *checking* (#521).

    **Test steps:**

    * make the locator raise, select ffprobe and check
    * verify the line names the failure
    """
    fake_tool_locator.resolve.side_effect = RuntimeError("boom")
    page = VideosPage()
    qtbot.addWidget(page)
    page_ui(page).ffprobe_probe_radio_button.setChecked(True)

    settle(qtbot, page)

    assert page_ui(page).availability_label.text() == "Checking FFmpeg failed: boom"


def test_the_availability_line_follows_the_staged_choice_not_the_saved_one(
    qtbot: QtBot, fake_tool_locator: Any
) -> None:
    """It answers *would this work*, so it re-checks as the choice changes rather than on Save.

    **Test steps:**

    * build the page on the bundled backend with a usable FFmpeg, and check
    * select ffprobe and verify the line names it as ready
    * select the bundled backend again and verify it switched back, unsaved either way
    """
    fake_tool_locator.resolve.return_value = USABLE_FFMPEG
    page = VideosPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    settle(qtbot, page)

    ui.ffprobe_probe_radio_button.setChecked(True)
    assert ui.availability_label.text() == f"{FfprobeDurationProbe.LABEL} is ready."

    ui.mediainfo_probe_radio_button.setChecked(True)
    assert ui.availability_label.text() == f"{MediaInfoDurationProbe.LABEL} is ready."


# endregion

# region the extension list


def test_starts_on_the_shipped_formats_on_a_fresh_install(qtbot: QtBot) -> None:
    """With nothing persisted, the list shows the formats actually in force -- not an empty list.

    **Test steps:**

    * build the page against empty persistent storage
    * verify it lists the shipped video formats and is clean
    """
    page = VideosPage()
    qtbot.addWidget(page)

    assert extensions_editor(page).values == VIDEO_EXTENSIONS
    assert page.is_dirty() is False


def test_a_row_saving_would_drop_is_not_yet_a_change(qtbot: QtBot) -> None:
    """A blank insert does not make the page dirty, because applying would not change what is saved --
    the guard that keeps auto-apply from tearing a fresh row out from under its open cell (#53).

    **Test steps:**

    * add a blank row to the extension list and verify the page stays clean
    """
    page = VideosPage()
    qtbot.addWidget(page)

    extensions_editor(page).values = (*VIDEO_EXTENSIONS, "")

    assert page.is_dirty() is False


# Mirrors test_images_files_page.py's icon-wearing test exactly -- kept as a separate copy rather than a
# shared import, matching this codebase's settings-test convention.
# pylint: disable=duplicate-code
def test_every_editor_action_wears_one_of_this_apps_icons(qtbot: QtBot) -> None:
    """The widget ships none, so a page that forgot to dress it would show eight blank buttons (#231).

    **Test steps:**

    * build the page
    * verify all eight of the editor's actions carry an icon
    """
    page = VideosPage()
    qtbot.addWidget(page)
    editor = extensions_editor(page)

    actions = (
        editor.item_actions.insert_action,
        editor.item_actions.edit_action,
        editor.item_actions.delete_action,
        editor.item_actions.reset_action,
        editor.ordering_actions.move_to_top_action,
        editor.ordering_actions.move_up_action,
        editor.ordering_actions.move_down_action,
        editor.ordering_actions.move_to_bottom_action,
    )
    assert [action.icon().isNull() for action in actions] == [False] * 8


# pylint: enable=duplicate-code


def test_the_editor_restores_the_shipped_formats_not_an_empty_list(qtbot: QtBot) -> None:
    """Reset is a user who emptied the list's only way back, so it restores what the app ships.

    **Test steps:**

    * seed the shared settings with one format of the user's own and build the page
    * fire the editor's Reset action
    * verify the shipped formats are listed
    """
    shared_videos_settings().extensions = (".mp4",)
    page = VideosPage()
    qtbot.addWidget(page)

    extensions_editor(page).item_actions.reset_action.trigger()

    assert extensions_editor(page).values == VIDEO_EXTENSIONS


# endregion

# region save and drop


def test_save_pushes_every_staged_choice_and_persists_it(qtbot: QtBot, fake_persistent_settings: FakeSettings) -> None:
    """``save_changes`` writes the backend and the list to storage (#225).

    **Test steps:**

    * build the page, select ffprobe, and replace the format list
    * call ``save_changes``
    * verify the shared settings hold both, the page is clean, and a fresh load agrees
    """
    page = VideosPage()
    qtbot.addWidget(page)
    page_ui(page).ffprobe_probe_radio_button.setChecked(True)
    extensions_editor(page).values = (".mp4",)

    page.save_changes()

    shared = shared_videos_settings()
    assert shared.engine == FfprobeDurationProbe.NAME
    assert shared.video_extensions == (".mp4",)
    assert page.is_dirty() is False

    reloaded = VideosSettings()
    reloaded.load(fake_persistent_settings)  # type: ignore[arg-type]
    assert reloaded.engine == FfprobeDurationProbe.NAME
    assert reloaded.extensions == (".mp4",)


def test_a_saved_page_reopens_on_what_it_saved(qtbot: QtBot) -> None:
    """A freshly-built page reflects the saved backend and list -- the round trip (#225).

    **Test steps:**

    * seed the shared settings with ffprobe and one format
    * build a page
    * verify both are on screen and the page is clean
    """
    shared = shared_videos_settings()
    shared.engine = FfprobeDurationProbe.NAME
    shared.extensions = (".mp4",)
    page = VideosPage()
    qtbot.addWidget(page)

    assert page_ui(page).ffprobe_probe_radio_button.isChecked() is True
    assert extensions_editor(page).values == (".mp4",)
    assert page.is_dirty() is False


def test_saving_normalizes_the_formats_on_screen(qtbot: QtBot) -> None:
    """A typed ``MP4`` is saved as ``.mp4``, and the page is reloaded so it shows what a scan matches.

    Normalizing is the settings object's, not the editor's -- the editor holds what was typed (#231).

    **Test steps:**

    * build the page and stage a bare, upper-cased format twice over
    * call ``save_changes``
    * verify what was saved and what is shown are the same normalized single entry
    """
    page = VideosPage()
    qtbot.addWidget(page)
    extensions_editor(page).values = ("MP4", "mp4", "")

    page.save_changes()

    assert shared_videos_settings().extensions == (".mp4",)
    assert extensions_editor(page).values == (".mp4",)
    assert page.is_dirty() is False


def test_saving_an_emptied_list_restores_the_shipped_formats_on_screen(qtbot: QtBot) -> None:
    """Emptying the list means the shipped formats, and the page shows that rather than a lie (#225).

    **Test steps:**

    * build the page and empty the editor
    * call ``save_changes``
    * verify the shipped formats are both in force and back on screen, and the page is clean
    """
    page = VideosPage()
    qtbot.addWidget(page)
    extensions_editor(page).values = ()

    page.save_changes()

    assert shared_videos_settings().video_extensions == VIDEO_EXTENSIONS
    assert extensions_editor(page).values == VIDEO_EXTENSIONS
    assert page.is_dirty() is False


def test_drop_changes_reverts_every_staged_choice(qtbot: QtBot) -> None:
    """``drop_changes`` re-seeds the page from the shared settings -- a revert, not a no-op.

    **Test steps:**

    * seed the shared settings with the bundled backend and one format, and build the page
    * stage the other backend and a different list
    * call ``drop_changes``
    * verify the seeded values are back and the page is clean
    """
    shared_videos_settings().extensions = (".mp4",)
    page = VideosPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    ui.ffprobe_probe_radio_button.setChecked(True)
    extensions_editor(page).values = (".mkv",)

    page.drop_changes()

    assert ui.mediainfo_probe_radio_button.isChecked() is True
    assert extensions_editor(page).values == (".mp4",)
    assert page.is_dirty() is False


def test_seed_defaults_stages_the_factory_values_over_saved_ones(qtbot: QtBot) -> None:
    """``seed_defaults`` shows what a fresh install would -- the bundled backend, the shipped
    formats -- as a staged edit against whatever is saved (#342).

    **Test steps:**

    * save the other backend and one format, and build the page
    * call ``seed_defaults``
    * verify the factory values are on screen and the page is dirty
    """
    settings = shared_videos_settings()
    settings.engine = FfprobeDurationProbe.NAME
    settings.extensions = (".mp4",)
    page = VideosPage()
    qtbot.addWidget(page)
    ui = page_ui(page)

    page.seed_defaults()

    assert ui.mediainfo_probe_radio_button.isChecked() is True
    assert extensions_editor(page).values == VIDEO_EXTENSIONS
    assert page.is_dirty() is True


def test_applying_one_frame_through_the_filter_saves_it_alone_on_a_page_that_reseeds_on_save(
    qtbot: QtBot,
) -> None:
    """The generic one-frame commit (`SettingsFrameFilter.apply_frame`) on a real page whose
    ``save_changes`` ends by re-seeding every widget from what was saved: the probe frame's choice
    lands in the settings, the extensions frame's staged list does not, and after the save the staged
    list is back on screen and that frame alone reads dirty (#342).

    **Test steps:**

    * stage ffprobe in the probe frame and a different list in the extensions frame
    * ``apply_frame`` the probe frame with the page's own ``save_changes``
    * verify what was saved, what is still on screen, and which frame is dirty
    """
    page = VideosPage()
    qtbot.addWidget(page)
    frame_filter = SettingsFrameFilter(page, "Videos")
    ui = page_ui(page)
    ui.ffprobe_probe_radio_button.setChecked(True)
    extensions_editor(page).values = (".mkv",)

    frame_filter.apply_frame(ui.probe_frame, page.save_changes)

    settings = shared_videos_settings()
    assert settings.engine == FfprobeDurationProbe.NAME
    assert settings.video_extensions == VIDEO_EXTENSIONS
    assert ui.ffprobe_probe_radio_button.isChecked() is True
    assert extensions_editor(page).values == (".mkv",)
    assert frame_filter.dirty_frames() == [ui.extensions_frame]
    assert page.is_dirty() is True


# endregion

# region the page shell


def test_the_wrapping_notes_are_never_clipped_at_any_width(qtbot: QtBot) -> None:
    """Each note gets the height its text needs at the width it is given, and gives it back on widening.

    The rule #229 left behind: a page declares no heights of its own, and a `WrappingLabel` measures
    itself. Giving the height *back* is asserted too, not just never-clipped -- a ratcheted label is too
    tall, which never-clipped alone would wave through.

    **Test steps:**

    * build the page and resize it through a range of widths, narrow and wide, then back
    * verify at every step that each note is at least as tall as its text needs
    * verify a width seen before gets exactly the heights it got the first time
    """
    page = VideosPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    page.show()

    first_seen: dict[int, tuple[int, ...]] = {}
    for width in (320, 900, 420, 640, 320, 900):
        page.setGeometry(0, 0, width, 700)
        ui.main_layout.activate()
        for label in (ui.probe_note_label, ui.extensions_note_label, ui.availability_label):
            assert label.height() >= label.heightForWidth(label.width()), (
                f"{label.objectName()} clipped at page width {width}"
            )
        heights = (ui.probe_note_label.height(), ui.extensions_note_label.height(), ui.availability_label.height())
        assert first_seen.setdefault(width, heights) == heights, f"heights ratcheted at page width {width}"


def test_frame_filter_discovers_both_frames_independently(qtbot: QtBot) -> None:
    """The backend and the format list are separate top-level frames, so each filters on its own (#67).

    **Test steps:**

    * build a frame filter over the page
    * filter by the probe header and verify only that frame stays shown
    * filter by the extensions header and verify the other one shows instead
    * filter by a non-matching term and verify both hide
    """
    page = VideosPage()
    qtbot.addWidget(page)
    frame_filter = SettingsFrameFilter(page, "Videos")
    ui = page_ui(page)

    frame_filter.apply("duration probe", show_full_on_title_match=False)
    assert ui.probe_frame.isVisibleTo(page) is True
    assert ui.extensions_frame.isVisibleTo(page) is False

    frame_filter.apply("video extensions", show_full_on_title_match=False)
    assert ui.extensions_frame.isVisibleTo(page) is True
    assert ui.probe_frame.isVisibleTo(page) is False

    frame_filter.apply("no-such-term", show_full_on_title_match=False)
    assert ui.probe_frame.isVisibleTo(page) is False
    assert ui.extensions_frame.isVisibleTo(page) is False


# endregion


# region watch progress (#316)


def test_the_watch_checkboxes_start_on_and_a_save_reaches_the_shared_settings(qtbot: QtBot) -> None:
    """The three watch settings show their defaults, and Save puts what is ticked into the settings core's rules and
    size match are read from.

    **Test steps:**

    * build the page against empty storage and verify the three boxes are ticked and the page is clean
    * clear all three, verify the page is dirty, and save
    * verify the shared settings hold all three off and the page is clean again
    """
    page = VideosPage()
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
    page = VideosPage()
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


def test_the_check_is_given_what_the_discovery_found(qtbot: QtBot, fake_tool_locator: Any) -> None:
    """An empty path is the best install recorded, so nothing is searched for here (#521).

    **Test steps:**

    * record an install for FFmpeg and check
    * verify the locator was handed the recorded installs and searched for nothing
    """
    shared_tools_settings().set_detection(FFMPEG_TOOL.ID, ToolDetection(True, (USABLE_FFMPEG,)))
    page = VideosPage()
    qtbot.addWidget(page)

    settle(qtbot, page)

    fake_tool_locator.resolve.assert_any_call(FFMPEG_TOOL, "", (USABLE_FFMPEG,))
    fake_tool_locator.detect.assert_not_called()


def test_showing_the_page_again_does_not_check_again(qtbot: QtBot, fake_tool_locator: Any) -> None:
    """The page asks once; the Tools settings say when the answer may have changed (#521).

    **Test steps:**

    * show the page, hide it and show it again
    * verify the locator was asked once about each tool the page needs
    """
    page = VideosPage()
    qtbot.addWidget(page)

    with qtbot.waitSignals([page.availability_checked, page.player_checked], timeout=5000):
        page.show()
    page.hide()
    page.show()

    assert fake_tool_locator.resolve.call_count == len(EXTERNAL_TOOLS)


def test_a_change_to_the_tool_checks_again_once_the_page_has_asked(qtbot: QtBot, fake_tool_locator: Any) -> None:
    """A search finishing, or the Tools page saving a path, is followed without the page being shown again (#521).

    **Test steps:**

    * check once, then find FFmpeg: record an install for it
    * verify the page checked again and now offers the choice
    * change a tool the page does not use and verify nothing more was asked
    """
    page = VideosPage()
    qtbot.addWidget(page)
    settle(qtbot, page)
    fake_tool_locator.resolve.return_value = USABLE_FFMPEG

    with qtbot.waitSignal(page.availability_checked, timeout=5000):
        shared_tools_settings().set_detection(FFMPEG_TOOL.ID, ToolDetection(True, (USABLE_FFMPEG,)))

    assert page_ui(page).ffprobe_probe_radio_button.isEnabled() is True
    calls = fake_tool_locator.resolve.call_count
    shared_tools_settings().set_path("unrelated", "/somewhere")
    assert fake_tool_locator.resolve.call_count == calls


def test_a_tool_change_before_the_page_asked_does_not_check(qtbot: QtBot, fake_tool_locator: Any) -> None:
    """The start-up search reports while the page is not on screen; it is not worth a check nobody sees (#521).

    **Test steps:**

    * build the page and record an install for FFmpeg
    * verify the locator was not asked
    """
    page = VideosPage()
    qtbot.addWidget(page)

    shared_tools_settings().set_detection(FFMPEG_TOOL.ID, ToolDetection(True, (USABLE_FFMPEG,)))

    fake_tool_locator.resolve.assert_not_called()
