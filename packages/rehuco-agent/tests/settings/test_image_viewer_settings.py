"""Tests for ImageViewerSettings: the persisted maximized-viewer surface choice.

Uses a hand-rolled in-memory stand-in for ``QSettings`` (see ``test_main_window_settings.py`` for
the same rationale) rather than a real one or ``tmp_path``.
"""

from typing import Any

from pytest import fixture
from rehuco_agent.fields.widgets.image_lightbox import ImageViewerMode
from rehuco_agent.settings.image_viewer_settings import (
    DEFAULT_MODE,
    DEFAULT_STRIP_VISIBLE,
    GROUP,
    MODE_KEY,
    STRIP_VISIBLE_KEY,
    ImageViewerSettings,
)


# region fixtures
# Mirrors test_theme_settings.py's FakeSettings exactly -- kept as a separate copy rather than a
# shared import, matching this codebase's settings-test convention.
# pylint: disable=duplicate-code
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/value API.

    Method names and the ``type=`` parameter deliberately mirror ``QSettings``'s own C++-derived
    API, since :meth:`ImageViewerSettings.load`/:meth:`~ImageViewerSettings.save` call them by name.
    """

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


@fixture
def settings() -> FakeSettings:
    """A fresh in-memory settings stand-in."""
    return FakeSettings()


# endregion


def test_save_then_load_round_trips_the_mode(settings: FakeSettings) -> None:
    """Saving and reloading reproduces the same surface choice.

    **Test steps:**

    * set a non-default mode and save
    * load into a fresh instance from the same settings stand-in
    * verify the mode came back unchanged
    """
    viewer_settings = ImageViewerSettings()
    viewer_settings.mode = ImageViewerMode.FULL_SCREEN

    viewer_settings.save(settings)  # type: ignore[arg-type]

    restored = ImageViewerSettings()
    restored.load(settings)  # type: ignore[arg-type]

    assert restored.mode == ImageViewerMode.FULL_SCREEN


def test_the_persisted_value_is_the_modes_readable_name(settings: FakeSettings) -> None:
    """The stored value is the mode's own readable string, so a hand-read ``.ini`` makes sense.

    **Test steps:**

    * save the app-window-overlay mode
    * verify the raw stored value is that member's string
    """
    viewer_settings = ImageViewerSettings()
    viewer_settings.mode = ImageViewerMode.APP_WINDOW_OVERLAY
    viewer_settings.save(settings)  # type: ignore[arg-type]

    settings.beginGroup(GROUP)
    assert settings.value(MODE_KEY) == "app_window_overlay"


def test_load_defaults_to_the_document_overlay_when_nothing_was_saved(settings: FakeSettings) -> None:
    """A fresh install (nothing persisted) opens screenshots as a document overlay.

    **Test steps:**

    * load into a fresh instance from an empty settings stand-in
    * verify the mode is the document overlay
    """
    viewer_settings = ImageViewerSettings()

    viewer_settings.load(settings)  # type: ignore[arg-type]

    assert viewer_settings.mode == ImageViewerMode.DOCUMENT_OVERLAY
    assert viewer_settings.mode == DEFAULT_MODE


def test_load_falls_back_to_the_default_for_an_unrecognized_mode(settings: FakeSettings) -> None:
    """A stored mode this build doesn't know (an ``.ini`` from a newer version) loads as the default.

    Regression: mapping it straight through the enum would raise, and an unreadable preference must
    not stop a screenshot from opening at all.

    **Test steps:**

    * store a mode string no member matches
    * load and verify the default was used instead
    """
    settings.beginGroup(GROUP)
    settings.setValue(MODE_KEY, "picture_in_picture")
    settings.endGroup()
    viewer_settings = ImageViewerSettings()
    viewer_settings.mode = ImageViewerMode.FULL_SCREEN

    viewer_settings.load(settings)  # type: ignore[arg-type]

    assert viewer_settings.mode == DEFAULT_MODE


def test_save_then_load_round_trips_the_thumbnail_row_choice(settings: FakeSettings) -> None:
    """Saving and reloading reproduces the maximized viewer's thumbnail-row choice (#161).

    **Test steps:**

    * set a non-default row visibility and save
    * load into a fresh instance from the same settings stand-in
    * verify the choice came back unchanged
    """
    viewer_settings = ImageViewerSettings()
    viewer_settings.strip_visible = True

    viewer_settings.save(settings)  # type: ignore[arg-type]

    restored = ImageViewerSettings()
    restored.load(settings)  # type: ignore[arg-type]

    assert restored.strip_visible is True


def test_load_defaults_to_a_hidden_thumbnail_row_when_nothing_was_saved(settings: FakeSettings) -> None:
    """A fresh install opens a maximized screenshot with no thumbnail row (#161).

    **Test steps:**

    * load into a fresh instance from an empty settings stand-in
    * verify the row starts hidden
    """
    viewer_settings = ImageViewerSettings()
    viewer_settings.strip_visible = True

    viewer_settings.load(settings)  # type: ignore[arg-type]

    assert viewer_settings.strip_visible == DEFAULT_STRIP_VISIBLE
    assert viewer_settings.strip_visible is False


def test_saving_writes_both_choices_together(settings: FakeSettings) -> None:
    """One save persists the whole object, so writing either choice cannot drop the other.

    Regression guard: the surface is staged and saved by the settings page, while the row is written
    straight back as the user toggles it inside a viewer -- two writers of the same group.

    **Test steps:**

    * save an instance carrying a non-default value for each choice
    * verify both raw values are stored
    """
    viewer_settings = ImageViewerSettings()
    viewer_settings.mode = ImageViewerMode.FULL_SCREEN
    viewer_settings.strip_visible = True
    viewer_settings.save(settings)  # type: ignore[arg-type]

    settings.beginGroup(GROUP)
    assert settings.value(MODE_KEY) == "full_screen"
    assert settings.value(STRIP_VISIBLE_KEY) is True
