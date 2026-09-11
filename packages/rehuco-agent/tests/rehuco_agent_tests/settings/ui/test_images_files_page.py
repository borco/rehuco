"""Tests for ImagesFilesPage: the Images/Files settings page (#47, #222, #294)."""

from collections.abc import Iterator
from typing import Any

from borco_pyside.widgets import StringListEditor
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets.image_lightbox import ImageViewerMode
from rehuco_agent.settings import reference_images_settings
from rehuco_agent.settings.image_viewer_settings import ImageViewerSettings, shared_image_viewer_settings
from rehuco_agent.settings.markdown_rendering_settings import (
    MarkdownRenderingSettings,
    shared_markdown_rendering_settings,
)
from rehuco_agent.settings.reference_images_settings import ReferenceImagesSettings, shared_reference_images_settings
from rehuco_agent.settings.ui import images_files_page
from rehuco_agent.settings.ui.images_files_page import ImagesFilesPage
from rehuco_agent.settings.ui.settings_frame_filter import SettingsFrameFilter
from rehuco_core import CONTENT_IMAGE_EXTENSIONS


# region fixtures
# Mirrors test_descriptions_page.py's (and conftest.py's) FakeSettings exactly -- kept as a separate
# copy rather than a shared import, matching this codebase's settings-test convention.
# pylint: disable=duplicate-code
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/value API (see
    ``test_markdown_rendering_settings.py`` for the full rationale)."""

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

    Patched on both modules holding their own reference to it: the page (used by
    :meth:`ImagesFilesPage.save_changes`) and the settings module whose shared instance the page
    reads -- the reference-images extension list.
    """
    fake = FakeSettings()
    mocker.patch.object(reference_images_settings, "persistent_settings", return_value=fake)
    mocker.patch.object(images_files_page, "persistent_settings", return_value=fake)
    return fake


@fixture(autouse=True)
def clear_shared_instance_cache() -> Iterator[None]:
    """Drop every process-wide instance around each test, so none inherits another's staged state."""
    shared_reference_images_settings.cache_clear()
    yield
    shared_reference_images_settings.cache_clear()


@fixture
def page(qtbot: QtBot) -> ImagesFilesPage:
    """A freshly-built page, seeded from the (isolated) shared settings.

    :param qtbot: pytest-qt fixture.
    :returns: the page under test.
    """
    built = ImagesFilesPage()
    qtbot.addWidget(built)
    return built


# endregion


def extensions_editor(page: ImagesFilesPage) -> StringListEditor:
    """The page's reference-image extension list editor.

    :param page: the page under test.
    :returns: the `StringListEditor` holding the recognized formats.
    """
    editor = page.findChild(StringListEditor, "extensions_editor")
    assert isinstance(editor, StringListEditor)
    return editor


def listed_extensions(page: ImagesFilesPage) -> tuple[str, ...]:
    """The formats the page currently shows, in order.

    :param page: the page to read.
    :returns: every entry's text.
    """
    return extensions_editor(page).values


def test_starts_on_the_shipped_image_formats_on_a_fresh_install(page: ImagesFilesPage) -> None:
    """With nothing persisted, the list shows the formats actually in force -- not an empty list (#231).

    **Test steps:**

    * build the page against empty persistent storage
    * verify it lists core's shipped set and is clean
    """
    assert listed_extensions(page) == CONTENT_IMAGE_EXTENSIONS
    assert not page.is_dirty()


def test_restores_the_saved_image_formats(qtbot: QtBot) -> None:
    """A freshly-built page reflects what was saved, in order.

    **Test steps:**

    * seed the shared settings with two formats of the user's own
    * build the page
    * verify it lists exactly those two and is clean
    """
    shared_reference_images_settings().extensions = (".bmp", ".tif")
    built = ImagesFilesPage()
    qtbot.addWidget(built)

    assert listed_extensions(built) == (".bmp", ".tif")
    assert not built.is_dirty()


def test_the_extension_editors_reset_fills_the_list_with_the_shipped_formats(page: ImagesFilesPage) -> None:
    """Reset is what the Default radio used to be: the shipped set, on request (#231).

    **Test steps:**

    * stage one format of the user's own, then fire the editor's Reset action
    * verify the shipped set is listed
    """
    extensions_editor(page).values = (".bmp",)

    extensions_editor(page).item_actions.reset_action.trigger()

    assert listed_extensions(page) == CONTENT_IMAGE_EXTENSIONS


# Mirrors test_videos_page.py's icon/dirty pair exactly -- kept as a separate copy rather than a
# shared import, matching this codebase's settings-test convention.
# pylint: disable=duplicate-code
def test_every_extension_editor_action_wears_one_of_this_apps_icons(page: ImagesFilesPage) -> None:
    """The widget ships none, so a page that forgot to dress it would show eight blank buttons (#231).

    **Test steps:**

    * build the page
    * verify all eight of the editor's actions carry an icon
    """
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


def test_editing_the_extension_list_makes_the_page_dirty(page: ImagesFilesPage) -> None:
    """Whatever the editor holds is what Save would write, so a change to it is a change to the page.

    **Test steps:**

    * drop a format out of the editor
    * verify the page went dirty
    """
    extensions_editor(page).values = CONTENT_IMAGE_EXTENSIONS[1:]

    assert page.is_dirty()


# pylint: enable=duplicate-code


def test_a_row_saving_would_drop_is_not_yet_a_change(page: ImagesFilesPage) -> None:
    """A blank insert does not make the page dirty, because applying would not change what is saved --
    the guard that keeps auto-apply from tearing a fresh row out from under its open cell (#53).

    **Test steps:**

    * add a blank row to the extension list and verify the page stays clean
    """
    extensions_editor(page).values = (*CONTENT_IMAGE_EXTENSIONS, "")

    assert page.is_dirty() is False


def test_save_pushes_the_staged_image_formats_and_persists_them(
    page: ImagesFilesPage, fake_persistent_settings: FakeSettings
) -> None:
    """``save_changes`` writes the staged list into the shared settings and to storage.

    **Test steps:**

    * replace the shipped set with one format of the user's own, then apply
    * verify the shared settings hold it, the page is clean, and a fresh load agrees
    """
    extensions_editor(page).values = (".bmp",)

    page.save_changes()

    assert shared_reference_images_settings().content_image_extensions == (".bmp",)
    assert not page.is_dirty()

    reloaded = ReferenceImagesSettings()
    reloaded.load(fake_persistent_settings)  # type: ignore[arg-type]
    assert reloaded.extensions == (".bmp",)


def test_saving_normalizes_the_image_formats_on_screen(page: ImagesFilesPage) -> None:
    """``BMP`` is stored as ``.bmp``, and the page is reloaded so it shows what is actually matched.

    Normalizing is the settings object's, not the editor's -- the editor holds what was typed (#231).

    **Test steps:**

    * stage messily-typed formats, one blank and one duplicate among them, then apply
    * verify what was saved and what is shown are the same normalized list
    """
    extensions_editor(page).values = ("BMP ", "", ".bmp", "tif")

    page.save_changes()

    assert shared_reference_images_settings().extensions == (".bmp", ".tif")
    assert listed_extensions(page) == (".bmp", ".tif")
    assert not page.is_dirty()


def test_saving_an_emptied_extension_list_restores_the_shipped_formats_on_screen(page: ImagesFilesPage) -> None:
    """Emptying the list means the shipped formats, and the page shows that rather than a lie.

    **Test steps:**

    * empty the editor, then apply
    * verify the shipped set is both in force and back on screen, and the page is clean
    """
    extensions_editor(page).values = ()

    page.save_changes()

    assert shared_reference_images_settings().content_image_extensions == CONTENT_IMAGE_EXTENSIONS
    assert listed_extensions(page) == CONTENT_IMAGE_EXTENSIONS
    assert not page.is_dirty()


def test_drop_changes_reverts_the_staged_extension_list(qtbot: QtBot) -> None:
    """``drop_changes`` refills the editor from the shared settings -- a revert, not a no-op.

    **Test steps:**

    * seed the shared settings with two formats and build the page
    * stage a different list entirely, then reset
    * verify the seeded pair is back and the page is clean
    """
    shared_reference_images_settings().extensions = (".bmp", ".tif")
    built = ImagesFilesPage()
    qtbot.addWidget(built)
    extensions_editor(built).values = (".psd",)

    built.drop_changes()

    assert listed_extensions(built) == (".bmp", ".tif")
    assert not built.is_dirty()


def test_the_wrapping_extensions_note_is_never_clipped_at_any_width(page: ImagesFilesPage) -> None:
    """The note gets the height its text needs at the width it is given, and gives it back on widening.

    Same guard as `ExcludedFilesPage`'s: a plain wrapping `QLabel` hints as though its text were one wide
    line, and the frame sized from that hint paints the paragraph past its border (#226, fixed in #229).

    **Test steps:**

    * resize the page through a range of widths, narrow and wide, then back
    * verify at every step that the note is at least as tall as its text needs
    * verify a width seen before gets exactly the height it got the first time
    """
    ui = page._ImagesFilesPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access
    label = ui.extensions_note_label
    page.show()

    first_seen: dict[int, int] = {}
    for width in (320, 900, 420, 640, 320, 900):
        page.setGeometry(0, 0, width, 900)
        ui.main_layout.activate()
        assert label.height() >= label.heightForWidth(label.width()), f"note clipped at page width {width}"
        assert first_seen.setdefault(width, label.height()) == label.height(), f"height ratcheted at {width}"


def test_the_page_neither_reads_nor_writes_the_display_pages_settings(
    page: ImagesFilesPage, mocker: MockerFixture
) -> None:
    """The split is clean (#294): a Display-side change is not this page's dirt, and saving here never
    persists the viewer settings or the description width cap -- each object is one page's alone.

    **Test steps:**

    * change both Display-side shared objects under the page, and verify it stays clean
    * stage an extension-list edit and apply, and verify neither Display-side object was saved
    """
    viewer_save = mocker.patch.object(ImageViewerSettings, "save")
    rendering_save = mocker.patch.object(MarkdownRenderingSettings, "save")
    shared_image_viewer_settings().mode = ImageViewerMode.FULL_SCREEN
    shared_markdown_rendering_settings().max_image_width = 777
    assert not page.is_dirty()

    extensions_editor(page).values = (".bmp",)
    page.save_changes()

    viewer_save.assert_not_called()
    rendering_save.assert_not_called()


def test_the_extensions_block_is_a_filterable_frame_of_its_own(page: ImagesFilesPage) -> None:
    """The block is a discoverable top-level frame, so the filter finds it by its own text -- the
    frame is the smallest unit shown or hidden (#67).

    **Test steps:**

    * filter by a term only the extensions block carries
    * verify that frame stays shown
    """
    frame_filter = SettingsFrameFilter(page, "Sidecar Extensions")
    ui = page._ImagesFilesPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access

    frame_filter.apply("sidecar image extensions", show_full_on_title_match=False)

    assert ui.reference_images_frame.isVisibleTo(page) is True
