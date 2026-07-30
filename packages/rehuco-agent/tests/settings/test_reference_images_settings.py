"""Tests for ReferenceImagesSettings: the default-vs-custom content-image extension choice (#222).

Uses a hand-rolled in-memory stand-in for ``QSettings`` (see ``test_main_window_settings.py`` for
the same rationale) rather than a real one or ``tmp_path``.
"""

import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

from pytest import fixture, mark
from pytest_mock import MockerFixture
from rehuco_agent.settings import reference_images_settings
from rehuco_agent.settings.reference_images_settings import (
    ReferenceImagesSettings,
    format_extensions,
    parse_extensions,
    shared_reference_images_settings,
)
from rehuco_core import CONTENT_IMAGE_EXTENSIONS, ContentImageEntry, enumerate_content_images

DIRECTORY: Final = Path("/fake/refimages")
FILE_SCOPED_PATH: Final = DIRECTORY / "foo.rehu"
ARCHIVE_PATH: Final = DIRECTORY / "foo.zip"


# region fixtures
# Mirrors every other settings test's FakeSettings exactly -- kept as a separate copy rather than a
# shared import, matching this codebase's settings-test convention.
# pylint: disable=duplicate-code
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/value API.

    Method names and the ``type=`` parameter deliberately mirror ``QSettings``'s own C++-derived
    API, since :meth:`ReferenceImagesSettings.load`/:meth:`~ReferenceImagesSettings.save` call them
    by name.
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


@fixture
def settings() -> FakeSettings:
    """A fresh in-memory settings stand-in."""
    return FakeSettings()


# pylint: enable=duplicate-code


@fixture(autouse=True)
def clear_shared_instance_cache() -> Iterator[None]:
    """Clear the ``lru_cache``-backed singleton before and after every test (see
    ``test_markdown_rendering_settings.py`` for the full rationale)."""
    shared_reference_images_settings.cache_clear()
    yield
    shared_reference_images_settings.cache_clear()


# endregion


# region parsing


@mark.parametrize("text", ["jpg", ".jpg", "  .JPG  ", "JPG"])
def test_parse_normalizes_dots_case_and_whitespace(text: str) -> None:
    """A leading dot is optional, case and surrounding whitespace are ignored -- every spelling of one
    extension parses to the same lower-cased, dot-prefixed entry.

    **Test steps:**

    * parse each spelling of ``jpg``
    * verify it comes back as the single entry ``".jpg"``
    """
    assert parse_extensions(text) == (".jpg",)


def test_parse_splits_on_commas_keeping_the_order_typed() -> None:
    """Entries are comma-separated and keep the order they were typed in.

    **Test steps:**

    * parse a three-entry list
    * verify all three come back, in that order
    """
    assert parse_extensions("png, jpg, bmp") == (".png", ".jpg", ".bmp")


def test_parse_drops_duplicates_however_they_were_spelled() -> None:
    """Duplicates are dropped rather than rejected, matched after normalization -- so ``JPG`` and
    ``.jpg`` collapse into one entry.

    **Test steps:**

    * parse a list naming ``jpg`` three ways around a distinct entry
    * verify one ``.jpg`` entry survives, at the position it was first seen
    """
    assert parse_extensions("jpg, .JPG, png,   jpg  ") == (".jpg", ".png")


def test_parse_drops_empty_entries_rather_than_rejecting_the_list() -> None:
    """Empty entries are dropped, so a trailing comma or a doubled separator is not an error.

    **Test steps:**

    * parse a list with a doubled separator, a trailing comma, and a whitespace-only entry
    * verify only the two real entries come back
    """
    assert parse_extensions("jpg,, ,png,") == (".jpg", ".png")


@mark.parametrize("text", ["", "   ", ",,,", ". , ..", ",  ,"])
def test_parse_falls_back_to_the_default_set_when_nothing_usable_is_named(text: str) -> None:
    """Text naming no usable entry resolves to core's default set -- a custom list left empty must not
    make every reference-images resource count zero images (#222).

    **Test steps:**

    * parse each of empty, whitespace-only, separators-only, and bare-dot input
    * verify each yields ``CONTENT_IMAGE_EXTENSIONS``
    """
    assert parse_extensions(text) == CONTENT_IMAGE_EXTENSIONS


def test_format_then_parse_round_trips_a_set_unchanged() -> None:
    """Formatting a set and parsing it back reproduces it -- which is what lets the Default label's
    text double as a copy-paste starting point for the custom list.

    **Test steps:**

    * format a known set and parse the result
    * verify the set came back unchanged, and the string is the comma-separated spelling
    """
    extensions = (".png", ".jpg", ".bmp")

    formatted = format_extensions(extensions)

    assert formatted == ".png, .jpg, .bmp"
    assert parse_extensions(formatted) == extensions


# endregion

# region the effective set


def test_defaults_to_cores_content_image_extensions() -> None:
    """A fresh instance selects the default choice, and its effective set is core's -- read, not
    restated (#222).

    **Test steps:**

    * construct the settings with no arguments
    * verify the default choice is selected, the custom list is empty, and the effective set is
      ``CONTENT_IMAGE_EXTENSIONS``
    """
    section = ReferenceImagesSettings()

    assert section.use_custom_extensions is False
    assert section.custom_extensions == ""
    assert section.content_image_extensions == CONTENT_IMAGE_EXTENSIONS


def test_a_selected_custom_list_is_the_effective_set_normalized() -> None:
    """With Custom selected, the effective set is the custom list, parsed under the normal rules.

    **Test steps:**

    * select the custom choice with a messily-typed list
    * verify the effective set is its normalized form
    """
    section = ReferenceImagesSettings(use_custom_extensions=True, custom_extensions="BMP , .bmp,tif ,")

    assert section.content_image_extensions == (".bmp", ".tif")


def test_an_unselected_custom_list_does_not_leak_into_the_effective_set() -> None:
    """With Default selected, the effective set is core's, whatever the custom list says.

    **Test steps:**

    * keep the default choice while the custom list names something else
    * verify the effective set is still ``CONTENT_IMAGE_EXTENSIONS``
    """
    section = ReferenceImagesSettings(use_custom_extensions=False, custom_extensions="bmp")

    assert section.content_image_extensions == CONTENT_IMAGE_EXTENSIONS


@mark.parametrize("text", ["", "   ", ",,,"])
def test_a_selected_custom_list_naming_nothing_falls_back_to_the_default_set(text: str) -> None:
    """A selected custom list naming no usable entry resolves to the default set rather than to none --
    a broken preference must not make every resource count zero images (#222).

    **Test steps:**

    * select the custom choice with empty/whitespace/separators-only text
    * verify the effective set fell back to ``CONTENT_IMAGE_EXTENSIONS``
    """
    section = ReferenceImagesSettings(use_custom_extensions=True, custom_extensions=text)

    assert section.content_image_extensions == CONTENT_IMAGE_EXTENSIONS


# endregion

# region persistence


def test_save_then_load_round_trips_both_fields(settings: FakeSettings) -> None:
    """Saving and reloading reproduces both the choice and the custom list.

    **Test steps:**

    * select the custom choice with a known list and save
    * load into a fresh instance from the same settings stand-in
    * verify both fields came back unchanged and the effective set follows them
    """
    section = ReferenceImagesSettings(use_custom_extensions=True, custom_extensions="bmp, tif")

    section.save(settings)  # type: ignore[arg-type]

    restored = ReferenceImagesSettings()
    restored.load(settings)  # type: ignore[arg-type]

    assert restored.use_custom_extensions is True
    assert restored.custom_extensions == "bmp, tif"
    assert restored.content_image_extensions == (".bmp", ".tif")


def test_the_custom_list_round_trips_verbatim_even_while_default_is_selected(settings: FakeSettings) -> None:
    """The custom list is persisted and restored exactly as typed even when it is not the selected
    choice -- switching back to Default never costs a retyped list (#222).

    **Test steps:**

    * save with the default choice selected but a custom list filled in, spelled messily
    * load into a fresh instance
    * verify the choice is default, the custom text is byte-identical, and the effective set is core's
    """
    section = ReferenceImagesSettings(use_custom_extensions=False, custom_extensions="BMP , .tga,")

    section.save(settings)  # type: ignore[arg-type]

    restored = ReferenceImagesSettings()
    restored.load(settings)  # type: ignore[arg-type]

    assert restored.use_custom_extensions is False
    assert restored.custom_extensions == "BMP , .tga,"
    assert restored.content_image_extensions == CONTENT_IMAGE_EXTENSIONS


def test_load_falls_back_to_the_default_state_when_nothing_was_saved(settings: FakeSettings) -> None:
    """Loading from settings that never had the group saved yields the defaults-selected, empty-custom
    state.

    **Test steps:**

    * load into an instance holding other values, from an empty settings stand-in
    * verify the default choice, an empty custom list, and core's effective set
    """
    section = ReferenceImagesSettings(use_custom_extensions=True, custom_extensions="bmp")

    section.load(settings)  # type: ignore[arg-type]

    assert section.use_custom_extensions is False
    assert section.custom_extensions == ""
    assert section.content_image_extensions == CONTENT_IMAGE_EXTENSIONS


def test_shared_instance_is_the_same_object_across_calls(mocker: MockerFixture) -> None:
    """``shared_reference_images_settings`` returns the identical instance every call.

    **Test steps:**

    * mock ``persistent_settings`` so the first call's ``load`` doesn't touch real storage
    * call the accessor twice
    * verify both calls return the same object
    """
    mocker.patch.object(reference_images_settings, "persistent_settings", return_value=FakeSettings())

    first = shared_reference_images_settings()
    second = shared_reference_images_settings()

    assert first is second


def test_shared_instance_loads_from_persistent_settings_on_first_call(mocker: MockerFixture) -> None:
    """``shared_reference_images_settings`` loads its value from ``persistent_settings()`` the first
    time it's constructed.

    **Test steps:**

    * pre-populate a fake settings store and mock ``persistent_settings`` to return it
    * call the accessor
    * verify the returned instance reflects the pre-populated choice and list
    """
    fake = FakeSettings()
    ReferenceImagesSettings(use_custom_extensions=True, custom_extensions="bmp").save(fake)  # type: ignore[arg-type]
    mocker.patch.object(reference_images_settings, "persistent_settings", return_value=fake)

    instance = shared_reference_images_settings()

    assert instance.use_custom_extensions is True
    assert instance.custom_extensions == "bmp"


# endregion

# region what the enumeration counts


def test_the_saved_choice_is_what_the_content_image_enumeration_counts(
    settings: FakeSettings, mocker: MockerFixture
) -> None:
    """The whole point of the page: a saved custom choice changes what #197's enumeration counts, so a
    reference pack in a format the default set omits stops counting zero
    ([[data-model#resource-scoping]]).

    **Test steps:**

    * mock ``foo.rehu``'s sibling archive to hold one ``.bmp`` and one ``.jpg``
    * enumerate under a freshly-loaded (default) choice, and verify only the ``.jpg`` counts
    * save a selected ``bmp``-only custom list, load it back, and enumerate under it
    * verify only the ``.bmp`` counts
    """
    mocker.patch.object(Path, "iterdir", return_value=[ARCHIVE_PATH])
    opened = mocker.MagicMock()
    opened.__enter__.return_value.infolist.return_value = [
        zipfile.ZipInfo("page01.bmp"),
        zipfile.ZipInfo("page02.jpg"),
    ]
    mocker.patch("rehuco_core.rehu_content_images.zipfile.ZipFile", return_value=opened)
    custom = ReferenceImagesSettings(use_custom_extensions=True, custom_extensions="bmp")
    custom.save(settings)  # type: ignore[arg-type]
    section = ReferenceImagesSettings()

    default_entries = enumerate_content_images(FILE_SCOPED_PATH, section.content_image_extensions)
    section.load(settings)  # type: ignore[arg-type]
    configured_entries = enumerate_content_images(FILE_SCOPED_PATH, section.content_image_extensions)

    assert default_entries == [ContentImageEntry(ARCHIVE_PATH, "page02.jpg")]
    assert configured_entries == [ContentImageEntry(ARCHIVE_PATH, "page01.bmp")]


# endregion
