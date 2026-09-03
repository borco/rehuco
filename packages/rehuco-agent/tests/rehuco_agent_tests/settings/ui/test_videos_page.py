"""Tests for VideosPage: the Videos settings category page (#225)."""

from collections.abc import Iterator
from typing import Any

from borco_pyside.widgets import StringListEditor
from pymediainfo import MediaInfo
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.settings import videos_settings
from rehuco_agent.settings.ui import videos_page
from rehuco_agent.settings.ui.settings_frame_filter import SettingsFrameFilter
from rehuco_agent.settings.ui.videos_page import VideosPage
from rehuco_agent.settings.videos_settings import VideosSettings, shared_videos_settings
from rehuco_core import VIDEO_EXTENSIONS, FfprobeDurationProbe, MediaInfoDurationProbe

MISSING_FFPROBE = "/nowhere/ffprobe"
"""A path holding no executable, so the page has something concrete to report as unusable."""


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


def test_the_executable_row_is_live_only_while_ffprobe_is_selected(qtbot: QtBot) -> None:
    """The path is only meaningful under the backend that runs it, so it is disabled under the other.

    Disabled rather than hidden: a path already typed stays visible under the choice it belongs to,
    which is what says the two backends' settings are kept side by side (#225).

    **Test steps:**

    * build the page and verify the path row is disabled under the bundled backend
    * select ffprobe and verify the row came alive
    * select the bundled backend again and verify it went back
    """
    page = VideosPage()
    qtbot.addWidget(page)
    ui = page_ui(page)

    assert ui.ffprobe_executable_edit.isEnabled() is False
    assert ui.browse_button.isEnabled() is False

    ui.ffprobe_probe_radio_button.setChecked(True)
    assert ui.ffprobe_executable_edit.isEnabled() is True
    assert ui.browse_button.isEnabled() is True

    ui.mediainfo_probe_radio_button.setChecked(True)
    assert ui.ffprobe_executable_edit.isEnabled() is False


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


def test_reports_a_misconfigured_ffprobe_before_any_scan_is_run(qtbot: QtBot) -> None:
    """An ffprobe path holding no executable is reported here, in the probe's own words (#224, #225).

    This is the page's reason for showing a status at all: a scan under an unusable backend raises
    rather than measuring ``0``, so the misconfiguration has to be visible before Compute is pressed.

    **Test steps:**

    * build the page, select ffprobe and type a path holding no executable
    * verify the availability line names that path as unrunnable
    """
    page = VideosPage()
    qtbot.addWidget(page)
    ui = page_ui(page)

    ui.ffprobe_probe_radio_button.setChecked(True)
    ui.ffprobe_executable_edit.setText(MISSING_FFPROBE)

    assert ui.availability_label.text() == f"No runnable ffprobe at {MISSING_FFPROBE}."


def test_the_availability_line_follows_the_staged_choice_not_the_saved_one(qtbot: QtBot) -> None:
    """It answers *would this work*, so it re-checks as the choice changes rather than on Save.

    **Test steps:**

    * build the page on the bundled backend with a bad ffprobe path already saved
    * select ffprobe and verify the line switched to the ffprobe complaint
    * select the bundled backend again and verify it switched back, unsaved either way
    """
    shared_videos_settings().ffprobe_executable = MISSING_FFPROBE
    page = VideosPage()
    qtbot.addWidget(page)
    ui = page_ui(page)

    ui.ffprobe_probe_radio_button.setChecked(True)
    assert ui.availability_label.text() == f"No runnable ffprobe at {MISSING_FFPROBE}."

    ui.mediainfo_probe_radio_button.setChecked(True)
    assert ui.availability_label.text() == f"{MediaInfoDurationProbe.LABEL} is ready."


# endregion

# region the executable picker


def test_browse_fills_the_executable_from_the_file_dialog(qtbot: QtBot, mocker: MockerFixture) -> None:
    """Picking a file writes its path into the edit, so the path need not be typed by hand.

    **Test steps:**

    * build the page with the file dialog mocked to return a path
    * click Browse
    * verify the edit holds the picked path
    """
    mocker.patch(
        "rehuco_agent.settings.ui.videos_page.QFileDialog.getOpenFileName",
        return_value=(MISSING_FFPROBE, "All files (*)"),
    )
    page = VideosPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    ui.ffprobe_probe_radio_button.setChecked(True)

    ui.browse_button.click()

    assert ui.ffprobe_executable_edit.text() == MISSING_FFPROBE


def test_a_cancelled_pick_leaves_the_executable_alone(qtbot: QtBot, mocker: MockerFixture) -> None:
    """Cancelling the dialog must not blank a path that was already configured.

    **Test steps:**

    * build the page over a configured executable, with the file dialog mocked to return nothing
    * click Browse
    * verify the edit still holds what it did
    """
    shared_videos_settings().ffprobe_executable = MISSING_FFPROBE
    mocker.patch("rehuco_agent.settings.ui.videos_page.QFileDialog.getOpenFileName", return_value=("", ""))
    page = VideosPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    ui.ffprobe_probe_radio_button.setChecked(True)

    ui.browse_button.click()

    assert ui.ffprobe_executable_edit.text() == MISSING_FFPROBE


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


# Mirrors test_images_page.py's icon-wearing test exactly -- kept as a separate copy rather than a
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
    """``save_changes`` writes the backend, its executable and the list to storage (#225).

    **Test steps:**

    * build the page, select ffprobe with a path, and replace the format list
    * call ``save_changes``
    * verify the shared settings hold all three, the page is clean, and a fresh load agrees
    """
    page = VideosPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    ui.ffprobe_probe_radio_button.setChecked(True)
    ui.ffprobe_executable_edit.setText(MISSING_FFPROBE)
    extensions_editor(page).values = (".mp4",)

    page.save_changes()

    shared = shared_videos_settings()
    assert shared.engine == FfprobeDurationProbe.NAME
    assert shared.ffprobe_executable == MISSING_FFPROBE
    assert shared.video_extensions == (".mp4",)
    assert page.is_dirty() is False

    reloaded = VideosSettings()
    reloaded.load(fake_persistent_settings)  # type: ignore[arg-type]
    assert reloaded.engine == FfprobeDurationProbe.NAME
    assert reloaded.ffprobe_executable == MISSING_FFPROBE
    assert reloaded.extensions == (".mp4",)


def test_a_saved_page_reopens_on_what_it_saved(qtbot: QtBot) -> None:
    """A freshly-built page reflects the saved backend, executable and list -- the round trip (#225).

    **Test steps:**

    * seed the shared settings with ffprobe, a path and one format
    * build a page
    * verify all three are on screen and the page is clean
    """
    shared = shared_videos_settings()
    shared.engine = FfprobeDurationProbe.NAME
    shared.ffprobe_executable = MISSING_FFPROBE
    shared.extensions = (".mp4",)
    page = VideosPage()
    qtbot.addWidget(page)
    ui = page_ui(page)

    assert ui.ffprobe_probe_radio_button.isChecked() is True
    assert ui.ffprobe_executable_edit.text() == MISSING_FFPROBE
    assert extensions_editor(page).values == (".mp4",)
    assert page.is_dirty() is False


def test_switching_backend_on_the_page_keeps_the_other_ones_settings(qtbot: QtBot) -> None:
    """A path typed under ffprobe survives a save made with the bundled backend selected (#225).

    The side-by-side storage is only worth having if the page keeps both halves too: dropping the path
    when the other radio is chosen would lose it on the very next Save.

    **Test steps:**

    * build the page, select ffprobe and type a path
    * select the bundled backend again and save
    * verify the saved settings kept the path, and a fresh page still shows it
    """
    page = VideosPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    ui.ffprobe_probe_radio_button.setChecked(True)
    ui.ffprobe_executable_edit.setText(MISSING_FFPROBE)
    ui.mediainfo_probe_radio_button.setChecked(True)

    page.save_changes()

    assert shared_videos_settings().engine == MediaInfoDurationProbe.NAME
    assert shared_videos_settings().ffprobe_executable == MISSING_FFPROBE

    reopened = VideosPage()
    qtbot.addWidget(reopened)
    assert page_ui(reopened).ffprobe_executable_edit.text() == MISSING_FFPROBE


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
    * stage the other backend, a path and a different list
    * call ``drop_changes``
    * verify the seeded values are back and the page is clean
    """
    shared_videos_settings().extensions = (".mp4",)
    page = VideosPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    ui.ffprobe_probe_radio_button.setChecked(True)
    ui.ffprobe_executable_edit.setText(MISSING_FFPROBE)
    extensions_editor(page).values = (".mkv",)

    page.drop_changes()

    assert ui.mediainfo_probe_radio_button.isChecked() is True
    assert ui.ffprobe_executable_edit.text() == ""
    assert extensions_editor(page).values == (".mp4",)
    assert page.is_dirty() is False


# endregion

# region the page shell


def test_title_is_videos(qtbot: QtBot) -> None:
    """The page's category-tree title is "Videos".

    **Test steps:**

    * construct the page
    * verify ``title``
    """
    page = VideosPage()
    qtbot.addWidget(page)

    assert page.title == "Videos"


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
    frame_filter = SettingsFrameFilter(page, page.title)
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
