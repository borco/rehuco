"""Tests for ImagesPage: the Images settings category page (#47, #160)."""

from collections.abc import Iterator
from typing import Any

from PySide6.QtWidgets import QRadioButton
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets.image_lightbox import ImageViewerMode
from rehuco_agent.settings import image_viewer_settings
from rehuco_agent.settings.image_viewer_settings import shared_image_viewer_settings
from rehuco_agent.settings.ui import images_page
from rehuco_agent.settings.ui.images_page import ImagesPage
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
        self.__data[self.__group + key] = value

    def value(self, key: str, default: Any = None, type: Any = None) -> Any:  # noqa: A002, N802
        del type
        return self.__data.get(self.__group + key, default)


# pylint: enable=duplicate-code


@fixture(autouse=True)
def fake_persistent_settings(mocker: MockerFixture) -> FakeSettings:
    """Stand in for ``persistent_settings()`` so save/load never touch real storage.

    Patched on both modules that imported their own reference to it: the settings module (used by
    :func:`shared_image_viewer_settings`'s lazy load) and the page module itself (used by
    :meth:`ImagesPage.save_changes`).
    """
    fake = FakeSettings()
    mocker.patch.object(image_viewer_settings, "persistent_settings", return_value=fake)
    mocker.patch.object(images_page, "persistent_settings", return_value=fake)
    return fake


@fixture(autouse=True)
def clear_shared_instance_cache() -> Iterator[None]:
    """Drop the process-wide instance around each test, so none inherits another's staged mode."""
    shared_image_viewer_settings.cache_clear()
    yield
    shared_image_viewer_settings.cache_clear()


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
