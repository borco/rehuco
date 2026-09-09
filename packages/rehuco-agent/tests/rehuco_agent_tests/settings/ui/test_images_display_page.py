"""Tests for ImagesDisplayPage: the Images/Display settings page (#47, #160, #294)."""

from collections.abc import Iterator
from typing import Any

from PySide6.QtWidgets import QCheckBox, QRadioButton, QSpinBox
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets.image_lightbox import ImageViewerMode
from rehuco_agent.settings import image_viewer_settings, markdown_rendering_settings
from rehuco_agent.settings.image_viewer_settings import shared_image_viewer_settings
from rehuco_agent.settings.markdown_rendering_settings import (
    MarkdownRenderingSettings,
    shared_markdown_rendering_settings,
)
from rehuco_agent.settings.reference_images_settings import ReferenceImagesSettings, shared_reference_images_settings
from rehuco_agent.settings.screenshot_deletion_settings import (
    ScreenshotDeletionSettings,
    shared_screenshot_deletion_settings,
)
from rehuco_agent.settings.ui import images_display_page
from rehuco_agent.settings.ui.images_display_page import ImagesDisplayPage
from rehuco_agent.settings.ui.settings_frame_filter import SettingsFrameFilter


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
        self.__data[self.__group + key] = value  # pylint: disable=unsupported-assignment-operation

    def value(self, key: str, default: Any = None, type: Any = None) -> Any:  # noqa: A002, N802
        del type
        return self.__data.get(self.__group + key, default)


# pylint: enable=duplicate-code


@fixture(autouse=True)
def fake_persistent_settings(mocker: MockerFixture) -> FakeSettings:
    """Stand in for ``persistent_settings()`` so save/load never touch real storage.

    Patched on every module holding its own reference to it: the page (used by
    :meth:`ImagesDisplayPage.save_changes`) and each of the two settings modules whose shared
    instance the page reads, so one store backs the lazy loads and the saves alike.
    """
    fake = FakeSettings()
    mocker.patch.object(image_viewer_settings, "persistent_settings", return_value=fake)
    mocker.patch.object(markdown_rendering_settings, "persistent_settings", return_value=fake)
    mocker.patch.object(images_display_page, "persistent_settings", return_value=fake)
    return fake


@fixture(autouse=True)
def clear_shared_instance_cache() -> Iterator[None]:
    """Drop every process-wide instance around each test, so none inherits another's staged state."""
    shared_image_viewer_settings.cache_clear()
    shared_markdown_rendering_settings.cache_clear()
    yield
    shared_image_viewer_settings.cache_clear()
    shared_markdown_rendering_settings.cache_clear()


@fixture
def page(qtbot: QtBot) -> ImagesDisplayPage:
    """A freshly-built page, seeded from the (isolated) shared settings.

    :param qtbot: pytest-qt fixture.
    :returns: the page under test.
    """
    built = ImagesDisplayPage()
    qtbot.addWidget(built)
    return built


# endregion


RADIO_BUTTON_NAMES: dict[ImageViewerMode, str] = {
    ImageViewerMode.DOCUMENT_OVERLAY: "document_overlay_radio_button",
    ImageViewerMode.APP_WINDOW_OVERLAY: "app_window_overlay_radio_button",
    ImageViewerMode.FULL_SCREEN: "full_screen_radio_button",
}
"""Each surface's radio button in ``images_display_page.ui``, so a test stages a choice the way a
user does -- by checking the button -- rather than by reaching into the page."""


def check(page: ImagesDisplayPage, mode: ImageViewerMode) -> None:
    """Check ``mode``'s radio button on ``page``, as a user clicking it would.

    :param page: the page under test.
    :param mode: the surface to stage.
    """
    button = page.findChild(QRadioButton, RADIO_BUTTON_NAMES[mode])
    assert isinstance(button, QRadioButton)
    button.setChecked(True)


def test_the_page_starts_on_the_shared_settings_mode(page: ImagesDisplayPage) -> None:
    """A fresh page shows whichever surface the shared settings currently name.

    **Test steps:**

    * build a page over settings that were never saved (the document-overlay default)
    * verify it reports no pending change
    """
    assert not page.is_dirty()
    assert shared_image_viewer_settings().mode == ImageViewerMode.DOCUMENT_OVERLAY


def test_choosing_another_surface_makes_the_page_dirty(page: ImagesDisplayPage) -> None:
    """Picking a different surface is a staged change until it is applied.

    **Test steps:**

    * check the full-screen radio button
    * verify the page is dirty and the shared settings are untouched
    """
    check(page, ImageViewerMode.FULL_SCREEN)

    assert page.is_dirty()
    assert shared_image_viewer_settings().mode == ImageViewerMode.DOCUMENT_OVERLAY


def test_save_changes_pushes_the_chosen_surface_into_the_shared_settings(page: ImagesDisplayPage) -> None:
    """Applying the page writes the staged surface into the shared settings and persists it.

    **Test steps:**

    * stage the app-window overlay and apply
    * verify the shared settings now name it, and a reload from storage agrees
    """
    check(page, ImageViewerMode.APP_WINDOW_OVERLAY)

    page.save_changes()

    assert shared_image_viewer_settings().mode == ImageViewerMode.APP_WINDOW_OVERLAY
    assert not page.is_dirty()


def test_drop_changes_reverts_to_the_saved_surface(page: ImagesDisplayPage) -> None:
    """Resetting the page discards the staged surface, re-checking the saved one.

    **Test steps:**

    * stage the full-screen surface without applying, then reset
    * verify the page is back on the saved (document-overlay) surface
    """
    check(page, ImageViewerMode.FULL_SCREEN)
    assert page.is_dirty()

    page.drop_changes()

    assert not page.is_dirty()


def test_no_surface_checked_falls_back_to_the_default(page: ImagesDisplayPage) -> None:
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


def test_the_surface_group_is_filterable_by_its_captions(page: ImagesDisplayPage) -> None:
    """The page's frame is found by the filter through the text its radio buttons carry (#67).

    **Test steps:**

    * build a frame filter over the page
    * verify a term from a radio button's label is part of its gathered text
    """
    frame_filter = SettingsFrameFilter(page, "Display")

    assert any("full-screen" in text for text in frame_filter.field_labels())


def spin_box(page: ImagesDisplayPage, name: str) -> QSpinBox:
    """One of the page's height spin boxes, by its ``images_display_page.ui`` name.

    :param page: the page under test.
    :param name: the spin box's object name.
    :returns: that spin box.
    """
    box = page.findChild(QSpinBox, name)
    assert isinstance(box, QSpinBox)
    return box


def strip_check_box(page: ImagesDisplayPage) -> QCheckBox:
    """The page's thumbnail-strip toggle.

    :param page: the page under test.
    :returns: the check box staging the strip's starting visibility.
    """
    box = page.findChild(QCheckBox, "strip_visible_check_box")
    assert isinstance(box, QCheckBox)
    return box


def wrap_check_box(page: ImagesDisplayPage) -> QCheckBox:
    """The page's document-strip wrap toggle (#70).

    :param page: the page under test.
    :returns: the check box staging whether a document's strip wraps its thumbnails.
    """
    box = page.findChild(QCheckBox, "wrap_check_box")
    assert isinstance(box, QCheckBox)
    return box


def test_the_page_starts_on_every_saved_choice(page: ImagesDisplayPage) -> None:
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


def test_toggling_the_document_strip_layout_makes_the_page_dirty(page: ImagesDisplayPage) -> None:
    """The document strip's wrap choice is a staged change until it is applied (#70).

    **Test steps:**

    * check the wrap toggle
    * verify the page is dirty and the shared settings are untouched
    """
    wrap_check_box(page).setChecked(True)

    assert page.is_dirty()
    assert shared_image_viewer_settings().preview_wrap is False


def test_toggling_the_strip_makes_the_page_dirty(page: ImagesDisplayPage) -> None:
    """The thumbnail-strip starting point is a staged change until it is applied (#161).

    **Test steps:**

    * check the strip toggle
    * verify the page is dirty and the shared settings are untouched
    """
    strip_check_box(page).setChecked(True)

    assert page.is_dirty()
    assert shared_image_viewer_settings().strip_visible is False


def test_changing_a_height_makes_the_page_dirty(page: ImagesDisplayPage) -> None:
    """Either thumbnail height is a staged change until it is applied (#161).

    **Test steps:**

    * change the document strip's height
    * verify the page is dirty and the shared settings are untouched
    """
    saved = shared_image_viewer_settings().preview_image_height

    spin_box(page, "preview_height_spin_box").setValue(saved + 20)

    assert page.is_dirty()
    assert shared_image_viewer_settings().preview_image_height == saved


def test_save_changes_pushes_every_choice_into_the_shared_settings(page: ImagesDisplayPage) -> None:
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


def test_drop_changes_reverts_every_staged_choice(page: ImagesDisplayPage) -> None:
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


def width_spin_box(page: ImagesDisplayPage) -> QSpinBox:
    """The cap on how wide an image embedded in a description is drawn.

    :param page: the page under test.
    :returns: that spin box.
    """
    return spin_box(page, "max_image_width_spin_box")


def test_the_page_starts_on_the_saved_image_width(page: ImagesDisplayPage) -> None:
    """The width cap is seeded from `MarkdownRenderingSettings`, not this page's own settings object.

    **Test steps:**

    * build a page over never-saved settings
    * verify the spin box shows what the shared markdown settings hold, with nothing staged
    """
    assert width_spin_box(page).value() == shared_markdown_rendering_settings().max_image_width
    assert not page.is_dirty()


def test_changing_the_image_width_makes_the_page_dirty(page: ImagesDisplayPage) -> None:
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
    page: ImagesDisplayPage, fake_persistent_settings: FakeSettings
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


def test_saving_leaves_a_still_staged_description_edit_alone(page: ImagesDisplayPage) -> None:
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


def test_drop_changes_reverts_the_staged_image_width(page: ImagesDisplayPage) -> None:
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


def test_the_page_neither_reads_nor_writes_the_files_pages_settings(
    page: ImagesDisplayPage, mocker: MockerFixture
) -> None:
    """The split is clean (#294): a Files-side change is not this page's dirt, and saving here never
    persists the extension list or the Recycle Bin choice -- each object is one page's alone.

    **Test steps:**

    * change both Files-side shared objects under the page, and verify it stays clean
    * stage a surface here and apply, and verify neither Files-side object was saved
    """
    files_save = mocker.patch.object(ReferenceImagesSettings, "save")
    deletion_save = mocker.patch.object(ScreenshotDeletionSettings, "save")
    shared_reference_images_settings().extensions = (".bmp",)
    shared_screenshot_deletion_settings().use_recycle_bin = False
    assert not page.is_dirty()

    check(page, ImageViewerMode.FULL_SCREEN)
    page.save_changes()

    files_save.assert_not_called()
    deletion_save.assert_not_called()


def test_the_surface_and_description_frames_are_filterable_frames_of_their_own(page: ImagesDisplayPage) -> None:
    """Each block is a discoverable top-level frame, so the filter hides one without the other -- the
    frame is the smallest unit shown or hidden (#67).

    **Test steps:**

    * filter by a term only the description-width block carries
    * verify that frame stays shown and the surface frame hides
    """
    frame_filter = SettingsFrameFilter(page, "Display")
    ui = page._ImagesDisplayPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access

    frame_filter.apply("maximum image width", show_full_on_title_match=False)

    assert ui.descriptions_frame.isVisibleTo(page) is True
    assert ui.surface_frame.isVisibleTo(page) is False
