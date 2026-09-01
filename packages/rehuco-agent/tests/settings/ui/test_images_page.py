"""Tests for ImagesPage: the Images settings category page (#47, #160, #222)."""

from collections.abc import Iterator
from typing import Any

from borco_pyside.widgets import StringListEditor
from PySide6.QtWidgets import QCheckBox, QRadioButton, QSpinBox
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets.image_lightbox import ImageViewerMode
from rehuco_agent.settings import image_viewer_settings, markdown_rendering_settings, reference_images_settings
from rehuco_agent.settings.image_viewer_settings import shared_image_viewer_settings
from rehuco_agent.settings.markdown_rendering_settings import (
    MarkdownRenderingSettings,
    shared_markdown_rendering_settings,
)
from rehuco_agent.settings.reference_images_settings import ReferenceImagesSettings, shared_reference_images_settings
from rehuco_agent.settings.ui import images_page
from rehuco_agent.settings.ui.images_page import ImagesPage
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

    Patched on every module holding its own reference to it: the page (used by
    :meth:`ImagesPage.save_changes`) and each of the three settings modules whose shared instance the
    page reads, so one store backs the lazy loads and the saves alike. Three, because this page holds
    every image-shaped setting whoever owns it -- the viewer's own, the description width cap, and the
    reference-images extension list.
    """
    fake = FakeSettings()
    mocker.patch.object(image_viewer_settings, "persistent_settings", return_value=fake)
    mocker.patch.object(markdown_rendering_settings, "persistent_settings", return_value=fake)
    mocker.patch.object(reference_images_settings, "persistent_settings", return_value=fake)
    mocker.patch.object(images_page, "persistent_settings", return_value=fake)
    return fake


@fixture(autouse=True)
def clear_shared_instance_cache() -> Iterator[None]:
    """Drop every process-wide instance around each test, so none inherits another's staged state."""
    for shared in (
        shared_image_viewer_settings,
        shared_markdown_rendering_settings,
        shared_reference_images_settings,
    ):
        shared.cache_clear()
    yield
    for shared in (
        shared_image_viewer_settings,
        shared_markdown_rendering_settings,
        shared_reference_images_settings,
    ):
        shared.cache_clear()


@fixture
def page(qtbot: QtBot) -> ImagesPage:
    """A freshly-built page, seeded from the (isolated) shared settings.

    :param qtbot: pytest-qt fixture.
    :returns: the page under test.
    """
    built = ImagesPage()
    qtbot.addWidget(built)
    return built


# endregion


RADIO_BUTTON_NAMES: dict[ImageViewerMode, str] = {
    ImageViewerMode.DOCUMENT_OVERLAY: "document_overlay_radio_button",
    ImageViewerMode.APP_WINDOW_OVERLAY: "app_window_overlay_radio_button",
    ImageViewerMode.FULL_SCREEN: "full_screen_radio_button",
}
"""Each surface's radio button in ``images_page.ui``, so a test stages a choice the way a user does
-- by checking the button -- rather than by reaching into the page."""


def check(page: ImagesPage, mode: ImageViewerMode) -> None:
    """Check ``mode``'s radio button on ``page``, as a user clicking it would.

    :param page: the page under test.
    :param mode: the surface to stage.
    """
    button = page.findChild(QRadioButton, RADIO_BUTTON_NAMES[mode])
    assert isinstance(button, QRadioButton)
    button.setChecked(True)


def test_the_page_starts_on_the_shared_settings_mode(page: ImagesPage) -> None:
    """A fresh page shows whichever surface the shared settings currently name.

    **Test steps:**

    * build a page over settings that were never saved (the document-overlay default)
    * verify it reports no pending change
    """
    assert not page.is_dirty()
    assert shared_image_viewer_settings().mode == ImageViewerMode.DOCUMENT_OVERLAY


def test_choosing_another_surface_makes_the_page_dirty(page: ImagesPage) -> None:
    """Picking a different surface is a staged change until it is applied.

    **Test steps:**

    * check the full-screen radio button
    * verify the page is dirty and the shared settings are untouched
    """
    check(page, ImageViewerMode.FULL_SCREEN)

    assert page.is_dirty()
    assert shared_image_viewer_settings().mode == ImageViewerMode.DOCUMENT_OVERLAY


def test_save_changes_pushes_the_chosen_surface_into_the_shared_settings(page: ImagesPage) -> None:
    """Applying the page writes the staged surface into the shared settings and persists it.

    **Test steps:**

    * stage the app-window overlay and apply
    * verify the shared settings now name it, and a reload from storage agrees
    """
    check(page, ImageViewerMode.APP_WINDOW_OVERLAY)

    page.save_changes()

    assert shared_image_viewer_settings().mode == ImageViewerMode.APP_WINDOW_OVERLAY
    assert not page.is_dirty()


def test_drop_changes_reverts_to_the_saved_surface(page: ImagesPage) -> None:
    """Resetting the page discards the staged surface, re-checking the saved one.

    **Test steps:**

    * stage the full-screen surface without applying, then reset
    * verify the page is back on the saved (document-overlay) surface
    """
    check(page, ImageViewerMode.FULL_SCREEN)
    assert page.is_dirty()

    page.drop_changes()

    assert not page.is_dirty()


def test_no_surface_checked_falls_back_to_the_default(page: ImagesPage) -> None:
    """With no radio checked at all, the page reports the default surface rather than nothing.

    Defensive: Qt's exclusive grouping keeps exactly one checked in normal use, so this covers the
    state only a programmatic uncheck can reach.

    **Test steps:**

    * clear every radio button's exclusivity and uncheck them all
    * apply and verify the default surface was written
    """
    for name in RADIO_BUTTON_NAMES.values():
        button = page.findChild(QRadioButton, name)
        assert isinstance(button, QRadioButton)
        button.setAutoExclusive(False)
        button.setChecked(False)

    page.save_changes()

    assert shared_image_viewer_settings().mode == ImageViewerMode.DOCUMENT_OVERLAY


def test_the_surface_group_is_filterable_by_its_captions(page: ImagesPage) -> None:
    """The page's frame is found by the filter through the text its radio buttons carry (#67).

    **Test steps:**

    * build a frame filter over the page
    * verify a term from a radio button's label is part of its gathered text
    """
    frame_filter = SettingsFrameFilter(page, page.title)

    assert any("full-screen" in text for text in frame_filter.field_labels())


def spin_box(page: ImagesPage, name: str) -> QSpinBox:
    """One of the page's height spin boxes, by its ``images_page.ui`` name.

    :param page: the page under test.
    :param name: the spin box's object name.
    :returns: that spin box.
    """
    box = page.findChild(QSpinBox, name)
    assert isinstance(box, QSpinBox)
    return box


def strip_check_box(page: ImagesPage) -> QCheckBox:
    """The page's thumbnail-strip toggle.

    :param page: the page under test.
    :returns: the check box staging the strip's starting visibility.
    """
    box = page.findChild(QCheckBox, "strip_visible_check_box")
    assert isinstance(box, QCheckBox)
    return box


def wrap_check_box(page: ImagesPage) -> QCheckBox:
    """The page's document-strip wrap toggle (#70).

    :param page: the page under test.
    :returns: the check box staging whether a document's strip wraps its thumbnails.
    """
    box = page.findChild(QCheckBox, "wrap_check_box")
    assert isinstance(box, QCheckBox)
    return box


def test_the_page_starts_on_every_saved_choice(page: ImagesPage) -> None:
    """A fresh page shows the toggles and all three heights the shared settings hold (#161, #70, #72).

    **Test steps:**

    * build a page over settings that were never saved
    * verify each widget shows that setting's default and nothing reads as pending
    """
    settings = shared_image_viewer_settings()

    assert strip_check_box(page).isChecked() == settings.strip_visible
    assert wrap_check_box(page).isChecked() == settings.preview_wrap
    assert spin_box(page, "preview_height_spin_box").value() == settings.preview_image_height
    assert spin_box(page, "lightbox_height_spin_box").value() == settings.lightbox_image_height
    assert spin_box(page, "editor_preview_height_spin_box").value() == settings.editor_preview_height
    assert not page.is_dirty()


def test_toggling_the_document_strip_layout_makes_the_page_dirty(page: ImagesPage) -> None:
    """The document strip's wrap choice is a staged change until it is applied (#70).

    **Test steps:**

    * check the wrap toggle
    * verify the page is dirty and the shared settings are untouched
    """
    wrap_check_box(page).setChecked(True)

    assert page.is_dirty()
    assert shared_image_viewer_settings().preview_wrap is False


def test_toggling_the_strip_makes_the_page_dirty(page: ImagesPage) -> None:
    """The thumbnail-strip starting point is a staged change until it is applied (#161).

    **Test steps:**

    * check the strip toggle
    * verify the page is dirty and the shared settings are untouched
    """
    strip_check_box(page).setChecked(True)

    assert page.is_dirty()
    assert shared_image_viewer_settings().strip_visible is False


def test_changing_a_height_makes_the_page_dirty(page: ImagesPage) -> None:
    """Either thumbnail height is a staged change until it is applied (#161).

    **Test steps:**

    * change the document strip's height
    * verify the page is dirty and the shared settings are untouched
    """
    saved = shared_image_viewer_settings().preview_image_height

    spin_box(page, "preview_height_spin_box").setValue(saved + 20)

    assert page.is_dirty()
    assert shared_image_viewer_settings().preview_image_height == saved


def test_save_changes_pushes_every_choice_into_the_shared_settings(page: ImagesPage) -> None:
    """Applying the page writes all six choices, not just the surface (#161, #70, #72).

    **Test steps:**

    * stage a surface, both toggles, and all three heights, then apply
    * verify the shared settings carry every one of them
    """
    check(page, ImageViewerMode.FULL_SCREEN)
    strip_check_box(page).setChecked(True)
    wrap_check_box(page).setChecked(True)
    spin_box(page, "preview_height_spin_box").setValue(200)
    spin_box(page, "lightbox_height_spin_box").setValue(120)
    spin_box(page, "editor_preview_height_spin_box").setValue(180)

    page.save_changes()

    settings = shared_image_viewer_settings()
    assert settings.mode == ImageViewerMode.FULL_SCREEN
    assert settings.strip_visible is True
    assert settings.preview_wrap is True
    assert settings.preview_image_height == 200
    assert settings.lightbox_image_height == 120
    assert settings.editor_preview_height == 180
    assert not page.is_dirty()


def test_drop_changes_reverts_every_staged_choice(page: ImagesPage) -> None:
    """Resetting the page discards the staged strip toggle and heights, not only the surface (#161).

    **Test steps:**

    * stage a change to each widget without applying, then reset
    * verify every widget is back on the saved value
    """
    settings = shared_image_viewer_settings()
    strip_check_box(page).setChecked(not settings.strip_visible)
    wrap_check_box(page).setChecked(not settings.preview_wrap)
    spin_box(page, "preview_height_spin_box").setValue(settings.preview_image_height + 20)
    spin_box(page, "lightbox_height_spin_box").setValue(settings.lightbox_image_height + 20)
    spin_box(page, "editor_preview_height_spin_box").setValue(settings.editor_preview_height + 20)
    assert page.is_dirty()

    page.drop_changes()

    assert not page.is_dirty()
    assert strip_check_box(page).isChecked() == settings.strip_visible
    assert wrap_check_box(page).isChecked() == settings.preview_wrap
    assert spin_box(page, "preview_height_spin_box").value() == settings.preview_image_height
    assert spin_box(page, "lightbox_height_spin_box").value() == settings.lightbox_image_height
    assert spin_box(page, "editor_preview_height_spin_box").value() == settings.editor_preview_height


# region the description image-width cap (moved here from DescriptionsPage)


def width_spin_box(page: ImagesPage) -> QSpinBox:
    """The cap on how wide an image embedded in a description is drawn.

    :param page: the page under test.
    :returns: that spin box.
    """
    return spin_box(page, "max_image_width_spin_box")


def test_the_page_starts_on_the_saved_image_width(page: ImagesPage) -> None:
    """The width cap is seeded from `MarkdownRenderingSettings`, not this page's own settings object.

    **Test steps:**

    * build a page over never-saved settings
    * verify the spin box shows what the shared markdown settings hold, with nothing staged
    """
    assert width_spin_box(page).value() == shared_markdown_rendering_settings().max_image_width
    assert not page.is_dirty()


def test_changing_the_image_width_makes_the_page_dirty(page: ImagesPage) -> None:
    """A staged width cap counts as this page's pending change, though another object owns it.

    **Test steps:**

    * raise the width spin box without applying
    * verify the page is dirty and the shared markdown settings are untouched
    """
    saved = shared_markdown_rendering_settings().max_image_width

    width_spin_box(page).setValue(saved + 111)

    assert page.is_dirty()
    assert shared_markdown_rendering_settings().max_image_width == saved


def test_save_changes_pushes_the_image_width_into_the_markdown_settings(
    page: ImagesPage, fake_persistent_settings: FakeSettings
) -> None:
    """Applying writes the staged cap into the shared markdown settings and persists it.

    **Test steps:**

    * stage a width cap and apply
    * verify the shared markdown settings hold it, the page is clean, and a reload agrees
    """
    width_spin_box(page).setValue(777)

    page.save_changes()

    assert shared_markdown_rendering_settings().max_image_width == 777
    assert not page.is_dirty()

    reloaded = MarkdownRenderingSettings()
    reloaded.load(fake_persistent_settings)  # type: ignore[arg-type]
    assert reloaded.max_image_width == 777


def test_saving_leaves_a_still_staged_description_edit_alone(page: ImagesPage) -> None:
    """Saving here re-persists the engine and CSS unchanged rather than picking up or clobbering a
    `DescriptionsPage` edit still staged -- what the shared object holds is the last-saved pair.

    **Test steps:**

    * seed the shared markdown settings, then apply this page with a staged width cap
    * verify the engine and CSS are exactly as they were
    """
    settings = shared_markdown_rendering_settings()
    settings.engine = "mistletoe"
    settings.markdown_css = "saved-css"
    width_spin_box(page).setValue(640)

    page.save_changes()

    assert settings.engine == "mistletoe"
    assert settings.markdown_css == "saved-css"


def test_drop_changes_reverts_the_staged_image_width(page: ImagesPage) -> None:
    """Resetting the page discards a staged width cap along with everything else.

    **Test steps:**

    * stage a width cap without applying, then reset
    * verify the spin box is back on the saved value
    """
    saved = shared_markdown_rendering_settings().max_image_width
    width_spin_box(page).setValue(saved + 111)

    page.drop_changes()

    assert width_spin_box(page).value() == saved
    assert not page.is_dirty()


# endregion

# region the reference-images extension list (moved here from ReferenceImagesPage)


def extensions_editor(page: ImagesPage) -> StringListEditor:
    """The page's reference-image extension list editor.

    :param page: the page under test.
    :returns: the `StringListEditor` holding the recognized formats.
    """
    editor = page.findChild(StringListEditor, "extensions_editor")
    assert isinstance(editor, StringListEditor)
    return editor


def listed_extensions(page: ImagesPage) -> tuple[str, ...]:
    """The formats the page currently shows, in order.

    :param page: the page to read.
    :returns: every entry's text.
    """
    return extensions_editor(page).values


def test_starts_on_the_shipped_image_formats_on_a_fresh_install(page: ImagesPage) -> None:
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
    built = ImagesPage()
    qtbot.addWidget(built)

    assert listed_extensions(built) == (".bmp", ".tif")
    assert not built.is_dirty()


def test_the_extension_editors_reset_fills_the_list_with_the_shipped_formats(page: ImagesPage) -> None:
    """Reset is what the Default radio used to be: the shipped set, on request (#231).

    **Test steps:**

    * stage one format of the user's own, then fire the editor's Reset action
    * verify the shipped set is listed
    """
    extensions_editor(page).values = (".bmp",)

    extensions_editor(page).item_actions.reset_action.trigger()

    assert listed_extensions(page) == CONTENT_IMAGE_EXTENSIONS


def test_every_extension_editor_action_wears_one_of_this_apps_icons(page: ImagesPage) -> None:
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


def test_editing_the_extension_list_makes_the_page_dirty(page: ImagesPage) -> None:
    """Whatever the editor holds is what Save would write, so a change to it is a change to the page.

    **Test steps:**

    * drop a format out of the editor
    * verify the page went dirty
    """
    extensions_editor(page).values = CONTENT_IMAGE_EXTENSIONS[1:]

    assert page.is_dirty()


def test_a_row_saving_would_drop_is_not_yet_a_change(page: ImagesPage) -> None:
    """A blank insert does not make the page dirty, because applying would not change what is saved --
    the guard that keeps auto-apply from tearing a fresh row out from under its open cell (#53).

    **Test steps:**

    * add a blank row to the extension list and verify the page stays clean
    """
    extensions_editor(page).values = (*CONTENT_IMAGE_EXTENSIONS, "")

    assert page.is_dirty() is False


def test_save_pushes_the_staged_image_formats_and_persists_them(
    page: ImagesPage, fake_persistent_settings: FakeSettings
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


def test_saving_normalizes_the_image_formats_on_screen(page: ImagesPage) -> None:
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


def test_saving_an_emptied_extension_list_restores_the_shipped_formats_on_screen(page: ImagesPage) -> None:
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
    built = ImagesPage()
    qtbot.addWidget(built)
    extensions_editor(built).values = (".psd",)

    built.drop_changes()

    assert listed_extensions(built) == (".bmp", ".tif")
    assert not built.is_dirty()


def test_the_wrapping_extensions_note_is_never_clipped_at_any_width(page: ImagesPage) -> None:
    """The note gets the height its text needs at the width it is given, and gives it back on widening.

    Same guard as `ExcludedFilesPage`'s: a plain wrapping `QLabel` hints as though its text were one wide
    line, and the frame sized from that hint paints the paragraph past its border (#226, fixed in #229).

    **Test steps:**

    * resize the page through a range of widths, narrow and wide, then back
    * verify at every step that the note is at least as tall as its text needs
    * verify a width seen before gets exactly the height it got the first time
    """
    ui = page._ImagesPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access
    label = ui.extensions_note_label
    page.show()

    first_seen: dict[int, int] = {}
    for width in (320, 900, 420, 640, 320, 900):
        page.setGeometry(0, 0, width, 900)
        ui.main_layout.activate()
        assert label.height() >= label.heightForWidth(label.width()), f"note clipped at page width {width}"
        assert first_seen.setdefault(width, label.height()) == label.height(), f"height ratcheted at {width}"


def test_both_moved_in_blocks_are_filterable_frames_of_their_own(page: ImagesPage) -> None:
    """Each block arrived as a discoverable top-level frame, so the filter hides one without the
    other -- the frame is the smallest unit shown or hidden (#67).

    **Test steps:**

    * filter by a term only the extensions block carries
    * verify that frame stays shown and the description-width frame hides
    """
    frame_filter = SettingsFrameFilter(page, page.title)
    ui = page._ImagesPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access

    frame_filter.apply("reference image extensions", show_full_on_title_match=False)

    assert ui.reference_images_frame.isVisibleTo(page) is True
    assert ui.descriptions_frame.isVisibleTo(page) is False


# endregion
