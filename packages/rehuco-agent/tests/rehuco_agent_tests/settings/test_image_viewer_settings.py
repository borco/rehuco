"""Tests for ImageViewerSettings: the persisted maximized-viewer surface choice.

Uses a hand-rolled in-memory stand-in for ``QSettings`` (see ``test_main_window_settings.py`` for
the same rationale) rather than a real one or ``tmp_path``.
"""

from typing import Any

from pytest import fixture
from rehuco_agent.fields.widgets.image_lightbox import ImageViewerMode
from rehuco_agent.settings.image_viewer_settings import (
    CONTENT_FOLDER_NAMES_KEY,
    CONTENT_ROWS_MAX_HEIGHT_KEY,
    CONTENT_ROWS_MIN_HEIGHT_KEY,
    CONTENT_ZIP_NAMES_KEY,
    DEFAULT_CONTENT_FOLDER_NAMES,
    DEFAULT_CONTENT_ROWS_MAX_HEIGHT,
    DEFAULT_CONTENT_ROWS_MIN_HEIGHT,
    DEFAULT_CONTENT_ZIP_NAMES,
    DEFAULT_EDITOR_PREVIEW_HEIGHT,
    DEFAULT_LIGHTBOX_BACKDROP,
    DEFAULT_LIGHTBOX_DOUBLE_CLICK_CLOSES,
    DEFAULT_LIGHTBOX_INFO_VISIBLE,
    DEFAULT_LIGHTBOX_SELECT_LAST_VIEWED,
    DEFAULT_MODE,
    DEFAULT_PREVIEW_WRAP,
    DEFAULT_PREVIEWS_VISIBLE,
    DEFAULT_STRIP_VISIBLE,
    EDITOR_PREVIEW_HEIGHT_KEY,
    GROUP,
    LIGHTBOX_BACKDROP_KEY,
    LIGHTBOX_DOUBLE_CLICK_CLOSES_KEY,
    LIGHTBOX_INFO_VISIBLE_KEY,
    LIGHTBOX_SELECT_LAST_VIEWED_KEY,
    MODE_KEY,
    PREVIEW_WRAP_KEY,
    PREVIEWS_VISIBLE_KEY,
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


def test_save_then_load_round_trips_the_document_strip_layout(settings: FakeSettings) -> None:
    """Saving and reloading reproduces the document strip's wrap choice (#70).

    **Test steps:**

    * set a non-default layout and save
    * load into a fresh instance from the same settings stand-in
    * verify the choice came back unchanged
    """
    viewer_settings = ImageViewerSettings()
    viewer_settings.preview_wrap = True

    viewer_settings.save(settings)  # type: ignore[arg-type]

    restored = ImageViewerSettings()
    restored.load(settings)  # type: ignore[arg-type]

    assert restored.preview_wrap is True


def test_load_defaults_to_an_unwrapped_document_strip_when_nothing_was_saved(settings: FakeSettings) -> None:
    """A fresh install keeps a document's screenshots on one row (#70).

    **Test steps:**

    * load into a fresh instance from an empty settings stand-in
    * verify the strip is unwrapped
    """
    viewer_settings = ImageViewerSettings()
    viewer_settings.preview_wrap = True

    viewer_settings.load(settings)  # type: ignore[arg-type]

    assert viewer_settings.preview_wrap == DEFAULT_PREVIEW_WRAP
    assert viewer_settings.preview_wrap is False


def test_load_defaults_to_visible_previews_when_nothing_was_saved(settings: FakeSettings) -> None:
    """A fresh install shows previews -- they are the normal state the toggle is the exception to (#71).

    **Test steps:**

    * load a fresh instance from an empty settings stand-in
    * verify previews start visible
    """
    viewer_settings = ImageViewerSettings()
    viewer_settings.previews_visible = False

    viewer_settings.load(settings)  # type: ignore[arg-type]

    assert viewer_settings.previews_visible is DEFAULT_PREVIEWS_VISIBLE
    assert viewer_settings.previews_visible is True


def test_save_then_load_round_trips_hidden_previews(settings: FakeSettings) -> None:
    """Previews toggled away stay away across a restart (#71).

    The toggle is a stated preference, not a session convenience: having to re-hide previews on every
    launch would be the friction it exists to remove.

    **Test steps:**

    * hide previews and save
    * load into a fresh instance from the same settings stand-in
    * verify they are still hidden
    """
    viewer_settings = ImageViewerSettings()
    viewer_settings.previews_visible = False

    viewer_settings.save(settings)  # type: ignore[arg-type]

    restored = ImageViewerSettings()
    restored.load(settings)  # type: ignore[arg-type]

    assert restored.previews_visible is False


def test_load_defaults_the_editor_preview_to_the_selectors_own_height(settings: FakeSettings) -> None:
    """A fresh install opens the images editor's preview at the height the selector itself declares (#72).

    **Test steps:**

    * load a fresh instance from an empty settings stand-in
    * verify the editor preview height is the widget's own default
    """
    viewer_settings = ImageViewerSettings()
    viewer_settings.editor_preview_height = 999

    viewer_settings.load(settings)  # type: ignore[arg-type]

    assert viewer_settings.editor_preview_height == DEFAULT_EDITOR_PREVIEW_HEIGHT
    assert viewer_settings.editor_preview_height == 100


def test_save_then_load_round_trips_the_editor_preview_height(settings: FakeSettings) -> None:
    """A chosen images-editor preview height survives a restart (#72).

    **Test steps:**

    * set a non-default editor preview height and save
    * load into a fresh instance from the same settings stand-in
    * verify the height came back
    """
    viewer_settings = ImageViewerSettings()
    viewer_settings.editor_preview_height = 240

    viewer_settings.save(settings)  # type: ignore[arg-type]

    restored = ImageViewerSettings()
    restored.load(settings)  # type: ignore[arg-type]

    assert restored.editor_preview_height == 240


def test_load_defaults_the_content_images_choices_when_nothing_was_saved(settings: FakeSettings) -> None:
    """A fresh install gets the Content Images dock's clamp and banners, and a hidden info overlay, as
    the module declares them (#221).

    **Test steps:**

    * load a fresh instance from an empty settings stand-in
    * verify each of the five choices is its default
    """
    viewer_settings = ImageViewerSettings()
    viewer_settings.content_rows_min_height = 1
    viewer_settings.content_rows_max_height = 2
    viewer_settings.content_zip_names = False
    viewer_settings.content_folder_names = True
    viewer_settings.lightbox_info_visible = True
    viewer_settings.lightbox_double_click_closes = False
    viewer_settings.lightbox_select_last_viewed = False

    viewer_settings.load(settings)  # type: ignore[arg-type]

    assert viewer_settings.lightbox_double_click_closes is DEFAULT_LIGHTBOX_DOUBLE_CLICK_CLOSES is True
    assert viewer_settings.lightbox_select_last_viewed is DEFAULT_LIGHTBOX_SELECT_LAST_VIEWED is True
    assert viewer_settings.content_rows_min_height == DEFAULT_CONTENT_ROWS_MIN_HEIGHT == 140
    assert viewer_settings.content_rows_max_height == DEFAULT_CONTENT_ROWS_MAX_HEIGHT == 260
    assert viewer_settings.content_zip_names is DEFAULT_CONTENT_ZIP_NAMES is True
    assert viewer_settings.content_folder_names is DEFAULT_CONTENT_FOLDER_NAMES is False
    assert viewer_settings.lightbox_info_visible is DEFAULT_LIGHTBOX_INFO_VISIBLE is False


def test_save_then_load_round_trips_the_content_images_choices(settings: FakeSettings) -> None:
    """The Content Images dock's clamp and banners, and the info overlay's start, survive a restart (#221).

    **Test steps:**

    * set a non-default value for each of the five and save
    * load into a fresh instance from the same settings stand-in
    * verify each came back
    """
    viewer_settings = ImageViewerSettings()
    viewer_settings.content_rows_min_height = 100
    viewer_settings.content_rows_max_height = 400
    viewer_settings.content_zip_names = False
    viewer_settings.content_folder_names = True
    viewer_settings.lightbox_info_visible = True
    viewer_settings.lightbox_double_click_closes = False
    viewer_settings.lightbox_select_last_viewed = False

    viewer_settings.save(settings)  # type: ignore[arg-type]

    restored = ImageViewerSettings()
    restored.load(settings)  # type: ignore[arg-type]

    assert restored.lightbox_double_click_closes is False
    assert restored.lightbox_select_last_viewed is False
    assert restored.content_rows_min_height == 100
    assert restored.content_rows_max_height == 400
    assert restored.content_zip_names is False
    assert restored.content_folder_names is True
    assert restored.lightbox_info_visible is True


def test_the_backdrop_round_trips_and_an_unpaintable_one_falls_back(settings: FakeSettings) -> None:
    """The lightbox backdrop survives a restart as ``#rrggbb``; a stored value no colour can be made
    of -- a hand-edited ini -- loads as the default rather than raising (#221).

    **Test steps:**

    * save a custom backdrop and load it into a fresh instance
    * store junk under the key and load again
    """
    viewer_settings = ImageViewerSettings()
    viewer_settings.lightbox_backdrop = "#336699"
    viewer_settings.save(settings)  # type: ignore[arg-type]
    restored = ImageViewerSettings()
    restored.load(settings)  # type: ignore[arg-type]
    assert restored.lightbox_backdrop == "#336699"

    settings.beginGroup(GROUP)
    settings.setValue(LIGHTBOX_BACKDROP_KEY, "not a colour")
    settings.endGroup()
    restored.load(settings)  # type: ignore[arg-type]
    assert restored.lightbox_backdrop == DEFAULT_LIGHTBOX_BACKDROP


def test_saving_writes_every_choice_together(settings: FakeSettings) -> None:
    """One save persists the whole object, so writing any one choice cannot drop the others.

    Regression guard, and it guards more than one writer: the surface and the layouts are staged and
    saved by the settings page, while the previews toggle writes straight back as it is clicked (#71)
    -- so whichever of them saves last must not blank what the other had stored.

    **Test steps:**

    * save an instance carrying a non-default value for each choice
    * verify every raw value is stored
    """
    viewer_settings = ImageViewerSettings()
    viewer_settings.mode = ImageViewerMode.FULL_SCREEN
    viewer_settings.strip_visible = True
    viewer_settings.preview_wrap = True
    viewer_settings.previews_visible = False
    viewer_settings.editor_preview_height = 240
    viewer_settings.lightbox_info_visible = True
    viewer_settings.lightbox_double_click_closes = False
    viewer_settings.lightbox_select_last_viewed = False
    viewer_settings.content_rows_min_height = 100
    viewer_settings.content_rows_max_height = 400
    viewer_settings.content_zip_names = False
    viewer_settings.content_folder_names = True
    viewer_settings.save(settings)  # type: ignore[arg-type]

    settings.beginGroup(GROUP)
    assert settings.value(LIGHTBOX_DOUBLE_CLICK_CLOSES_KEY) is False
    assert settings.value(LIGHTBOX_SELECT_LAST_VIEWED_KEY) is False
    assert settings.value(MODE_KEY) == "full_screen"
    assert settings.value(STRIP_VISIBLE_KEY) is True
    assert settings.value(PREVIEW_WRAP_KEY) is True
    assert settings.value(PREVIEWS_VISIBLE_KEY) is False
    assert settings.value(EDITOR_PREVIEW_HEIGHT_KEY) == 240
    assert settings.value(LIGHTBOX_INFO_VISIBLE_KEY) is True
    assert settings.value(CONTENT_ROWS_MIN_HEIGHT_KEY) == 100
    assert settings.value(CONTENT_ROWS_MAX_HEIGHT_KEY) == 400
    assert settings.value(CONTENT_ZIP_NAMES_KEY) is False
    assert settings.value(CONTENT_FOLDER_NAMES_KEY) is True
