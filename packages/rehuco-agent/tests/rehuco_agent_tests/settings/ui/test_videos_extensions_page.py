"""Tests for VideosExtensionsPage: the Videos / Extensions settings page (#225, #692)."""

from typing import Any

from borco_pyside.widgets import StringListEditor
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.settings import videos_settings
from rehuco_agent.settings.ui import videos_extensions_page
from rehuco_agent.settings.ui.settings_frame_filter import SettingsFrameFilter
from rehuco_agent.settings.ui.videos_extensions_page import VideosExtensionsPage
from rehuco_agent.settings.videos_settings import VideosSettings, shared_videos_settings
from rehuco_core import VIDEO_EXTENSIONS

from rehuco_agent_tests.settings.ui.test_videos_probe_page import FakeSettings


# region fixtures
@fixture(autouse=True)
def fake_persistent_settings(mocker: MockerFixture) -> FakeSettings:
    """Stand in for ``persistent_settings()`` so save/load never touch real storage.

    Patched on both modules that imported their own reference to it: the shared settings module
    (used by :func:`shared_videos_settings`'s lazy load) and the page module itself (used by
    :meth:`VideosExtensionsPage.save_changes`).
    """
    fake = FakeSettings()
    mocker.patch.object(videos_settings, "persistent_settings", return_value=fake)
    mocker.patch.object(videos_extensions_page, "persistent_settings", return_value=fake)
    return fake


def page_ui(page: VideosExtensionsPage) -> Any:
    """The page's generated UI object, for reaching its widgets.

    :param page: the page to reach into.
    :returns: the ``Ui_VideosExtensionsPage`` instance.
    """
    return page._VideosExtensionsPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access


def extensions_editor(page: VideosExtensionsPage) -> StringListEditor:
    """The page's video-extension list editor.

    :param page: the page to reach into.
    :returns: the `StringListEditor` holding the recognized formats.
    """
    return page_ui(page).extensions_editor


# endregion

# region the extension list


def test_starts_on_the_shipped_formats_on_a_fresh_install(qtbot: QtBot) -> None:
    """With nothing persisted, the list shows the formats actually in force -- not an empty list.

    **Test steps:**

    * build the page against empty persistent storage
    * verify it lists the shipped video formats and is clean
    """
    page = VideosExtensionsPage()
    qtbot.addWidget(page)

    assert extensions_editor(page).values == VIDEO_EXTENSIONS
    assert page.is_dirty() is False


def test_a_row_saving_would_drop_is_not_yet_a_change(qtbot: QtBot) -> None:
    """A blank insert does not make the page dirty, because applying would not change what is saved --
    the guard that keeps auto-apply from tearing a fresh row out from under its open cell (#53).

    **Test steps:**

    * add a blank row to the extension list and verify the page stays clean
    """
    page = VideosExtensionsPage()
    qtbot.addWidget(page)

    extensions_editor(page).values = (*VIDEO_EXTENSIONS, "")

    assert page.is_dirty() is False


# Mirrors test_images_files_page.py's icon-wearing test exactly -- kept as a separate copy rather than a
# shared import, matching this codebase's settings-test convention.
# pylint: disable=duplicate-code
def test_every_editor_action_wears_one_of_this_apps_icons(qtbot: QtBot) -> None:
    """The widget ships none, so a page that forgot to dress it would show seven blank buttons (#231).

    **Test steps:**

    * build the page
    * verify all seven of the editor's actions carry an icon
    """
    page = VideosExtensionsPage()
    qtbot.addWidget(page)
    editor = extensions_editor(page)

    actions = (
        editor.item_actions.insert_action,
        editor.item_actions.delete_action,
        editor.item_actions.reset_action,
        editor.ordering_actions.move_to_top_action,
        editor.ordering_actions.move_up_action,
        editor.ordering_actions.move_down_action,
        editor.ordering_actions.move_to_bottom_action,
    )
    assert [action.icon().isNull() for action in actions] == [False] * 7


# pylint: enable=duplicate-code


def test_the_editor_restores_the_shipped_formats_not_an_empty_list(qtbot: QtBot) -> None:
    """Reset is a user who emptied the list's only way back, so it restores what the app ships.

    **Test steps:**

    * seed the shared settings with one format of the user's own and build the page
    * fire the editor's Reset action
    * verify the shipped formats are listed
    """
    shared_videos_settings().extensions = (".mp4",)
    page = VideosExtensionsPage()
    qtbot.addWidget(page)

    extensions_editor(page).item_actions.reset_action.trigger()

    assert extensions_editor(page).values == VIDEO_EXTENSIONS


# endregion


# region save and drop


def test_save_pushes_the_staged_list_and_persists_it(qtbot: QtBot, fake_persistent_settings: FakeSettings) -> None:
    """``save_changes`` writes the list to storage (#225).

    **Test steps:**

    * build the page and replace the format list
    * call ``save_changes``
    * verify the shared settings hold it, the page is clean, and a fresh load agrees
    """
    page = VideosExtensionsPage()
    qtbot.addWidget(page)
    extensions_editor(page).values = (".mp4",)

    page.save_changes()

    assert shared_videos_settings().video_extensions == (".mp4",)
    assert page.is_dirty() is False

    reloaded = VideosSettings()
    reloaded.load(fake_persistent_settings)  # type: ignore[arg-type]
    assert reloaded.extensions == (".mp4",)


def test_a_saved_page_reopens_on_what_it_saved(qtbot: QtBot) -> None:
    """A freshly-built page reflects the saved list -- the round trip (#225).

    **Test steps:**

    * seed the shared settings with one format
    * build a page
    * verify it is on screen and the page is clean
    """
    shared_videos_settings().extensions = (".mp4",)
    page = VideosExtensionsPage()
    qtbot.addWidget(page)

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
    page = VideosExtensionsPage()
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
    page = VideosExtensionsPage()
    qtbot.addWidget(page)
    extensions_editor(page).values = ()

    page.save_changes()

    assert shared_videos_settings().video_extensions == VIDEO_EXTENSIONS
    assert extensions_editor(page).values == VIDEO_EXTENSIONS
    assert page.is_dirty() is False


def test_drop_changes_reverts_the_staged_list(qtbot: QtBot) -> None:
    """``drop_changes`` re-seeds the page from the shared settings -- a revert, not a no-op.

    **Test steps:**

    * seed the shared settings with one format, and build the page
    * stage a different list
    * call ``drop_changes``
    * verify the seeded list is back and the page is clean
    """
    shared_videos_settings().extensions = (".mp4",)
    page = VideosExtensionsPage()
    qtbot.addWidget(page)
    extensions_editor(page).values = (".mkv",)

    page.drop_changes()

    assert extensions_editor(page).values == (".mp4",)
    assert page.is_dirty() is False


def test_seed_defaults_stages_the_shipped_formats_over_a_saved_list(qtbot: QtBot) -> None:
    """``seed_defaults`` shows what a fresh install would -- the shipped formats -- as a staged edit (#342).

    **Test steps:**

    * save one format and build the page
    * call ``seed_defaults``
    * verify the shipped formats are on screen and the page is dirty
    """
    shared_videos_settings().extensions = (".mp4",)
    page = VideosExtensionsPage()
    qtbot.addWidget(page)

    page.seed_defaults()

    assert extensions_editor(page).values == VIDEO_EXTENSIONS
    assert page.is_dirty() is True


# endregion

# region the page shell


def test_the_wrapping_note_is_never_clipped_at_any_width(qtbot: QtBot) -> None:
    """The note gets the height its text needs at the width it is given, and gives it back on widening.

    **Test steps:**

    * build the page and resize it through a range of widths, narrow and wide, then back
    * verify at every step that the note is at least as tall as its text needs
    * verify a width seen before gets exactly the height it got the first time
    """
    page = VideosExtensionsPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    page.show()

    first_seen: dict[int, int] = {}
    for width in (320, 900, 420, 640, 320, 900):
        page.setGeometry(0, 0, width, 700)
        ui.main_layout.activate()
        label = ui.extensions_note_label
        assert label.height() >= label.heightForWidth(label.width()), f"clipped at page width {width}"
        assert first_seen.setdefault(width, label.height()) == label.height(), f"ratcheted at page width {width}"


def test_frame_filter_finds_the_extensions_frame(qtbot: QtBot) -> None:
    """The format list filters on its own header (#67).

    **Test steps:**

    * build a frame filter over the page
    * filter by the extensions header and verify the frame stays shown
    * filter by a non-matching term and verify it hides
    """
    page = VideosExtensionsPage()
    qtbot.addWidget(page)
    frame_filter = SettingsFrameFilter(page, "Extensions")
    ui = page_ui(page)

    frame_filter.apply("video extensions", show_full_on_title_match=False)
    assert ui.extensions_frame.isVisibleTo(page) is True

    frame_filter.apply("no-such-term", show_full_on_title_match=False)
    assert ui.extensions_frame.isVisibleTo(page) is False


# endregion
