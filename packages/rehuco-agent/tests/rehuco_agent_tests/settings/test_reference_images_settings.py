"""Tests for ReferenceImagesSettings: the recognized content-image extension list (#222, #231).

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
    normalize_extensions,
    read_extensions,
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


# region normalizing


@mark.parametrize("entry", ["jpg", ".jpg", "  .JPG  ", "JPG"])
def test_normalize_handles_dots_case_and_whitespace(entry: str) -> None:
    """A leading dot is optional, case and surrounding whitespace are ignored -- every spelling of one
    extension normalizes to the same lower-cased, dot-prefixed entry.

    **Test steps:**

    * normalize each spelling of ``jpg``
    * verify it comes back as the single entry ``".jpg"``
    """
    assert normalize_extensions([entry]) == (".jpg",)


def test_normalize_keeps_the_order_the_entries_are_listed_in() -> None:
    """Entries keep the order they sit in, so the list reads the way it was arranged.

    **Test steps:**

    * normalize a three-entry list
    * verify all three come back, in that order
    """
    assert normalize_extensions(["png", "jpg", "bmp"]) == (".png", ".jpg", ".bmp")


def test_normalize_drops_duplicates_however_they_were_spelled() -> None:
    """Duplicates are dropped rather than rejected, matched after normalization -- so ``JPG`` and
    ``.jpg`` collapse into one entry.

    **Test steps:**

    * normalize a list naming ``jpg`` three ways around a distinct entry
    * verify one ``.jpg`` entry survives, at the position it was first seen
    """
    assert normalize_extensions(["jpg", ".JPG", "png", "  jpg  "]) == (".jpg", ".png")


def test_normalize_drops_blank_entries_rather_than_rejecting_the_list() -> None:
    """A blank row is dropped, so an abandoned entry is not an error the user has to find and fix.

    **Test steps:**

    * normalize a list holding a blank and a whitespace-only entry between two real ones
    * verify only the two real entries come back
    """
    assert normalize_extensions(["jpg", "", "   ", "png"]) == (".jpg", ".png")


@mark.parametrize("values", [[], ["", "   "], [".", ".."]])
def test_normalize_falls_back_to_the_shipped_set_when_nothing_usable_is_named(values: list[str]) -> None:
    """A list naming no usable entry resolves to core's shipped set -- an emptied list must not make
    every reference-images resource count zero images (#222).

    **Test steps:**

    * normalize each of an empty, a whitespace-only, and a bare-dot list
    * verify each yields ``CONTENT_IMAGE_EXTENSIONS``
    """
    assert normalize_extensions(values) == CONTENT_IMAGE_EXTENSIONS


# endregion

# region reading what was stored


def test_a_stored_list_is_read_as_it_stands() -> None:
    """One entry per element, in order.

    **Test steps:**

    * read a stored list
    * verify it comes back unchanged
    """
    assert read_extensions(["bmp", ".tif"]) == ("bmp", ".tif")


def test_a_bare_string_is_read_as_the_one_element_list_it_was_saved_as() -> None:
    """The ini backend writes a single-element list as a plain string and hands it back that way, so a
    one-format list must not read as no list at all.

    **Test steps:**

    * read a bare string
    * verify it came back as one entry
    """
    assert read_extensions("bmp") == ("bmp",)


def test_blank_entries_are_dropped() -> None:
    """A list editor shows one entry per row, so a blank row is nothing to carry.

    **Test steps:**

    * read a list holding a blank between two real entries
    * verify only the real entries survive
    """
    assert read_extensions(["bmp", "", "tif"]) == ("bmp", "tif")


@mark.parametrize("value", [None, 7, {"bmp": True}])
def test_a_value_of_a_type_this_was_never_saved_as_reads_as_no_list(value: object) -> None:
    """Absent, or of a type nothing ever wrote: either way there is no list, which resolves to the
    shipped set rather than to no recognized formats at all.

    **Test steps:**

    * read each of an absent, numeric and mapping value
    * verify each yields no entries
    """
    assert not read_extensions(value)


def test_a_non_string_inside_a_stored_list_is_skipped_not_stringified() -> None:
    """A number that found its way into the list is not an extension, and reading it as ``"7"`` would
    make it one.

    **Test steps:**

    * read a list holding a number between two real entries
    * verify only the two entries survive
    """
    assert read_extensions(["bmp", 7, "tif"]) == ("bmp", "tif")


# endregion

# region the effective set


def test_defaults_to_cores_content_image_extensions() -> None:
    """A fresh instance stores nothing, and its effective set is core's -- read, not restated (#222).

    **Test steps:**

    * construct the settings with no arguments
    * verify the stored list is empty and the effective set is ``CONTENT_IMAGE_EXTENSIONS``
    """
    section = ReferenceImagesSettings()

    assert not section.extensions
    assert section.content_image_extensions == CONTENT_IMAGE_EXTENSIONS


def test_the_stored_list_is_the_effective_set_normalized() -> None:
    """The effective set is the stored list under the normal rules.

    **Test steps:**

    * store a messily-typed list
    * verify the effective set is its normalized form
    """
    section = ReferenceImagesSettings(extensions=("BMP ", ".bmp", "tif "))

    assert section.content_image_extensions == (".bmp", ".tif")


@mark.parametrize("values", [(), ("",), ("   ", ".")])
def test_a_stored_list_naming_nothing_falls_back_to_the_shipped_set(values: tuple[str, ...]) -> None:
    """A list naming no usable entry resolves to the shipped set rather than to none -- a broken
    preference must not make every resource count zero images (#222).

    **Test steps:**

    * store an empty, blank, or bare-dot list
    * verify the effective set fell back to ``CONTENT_IMAGE_EXTENSIONS``
    """
    section = ReferenceImagesSettings(extensions=values)

    assert section.content_image_extensions == CONTENT_IMAGE_EXTENSIONS


# endregion

# region persistence


def test_save_then_load_round_trips_the_list(settings: FakeSettings) -> None:
    """Saving and reloading reproduces the list, in order.

    **Test steps:**

    * save a known list
    * load into a fresh instance from the same settings stand-in
    * verify it came back unchanged and the effective set follows it
    """
    section = ReferenceImagesSettings(extensions=("bmp", "tif"))

    section.save(settings)  # type: ignore[arg-type]

    restored = ReferenceImagesSettings()
    restored.load(settings)  # type: ignore[arg-type]

    assert restored.extensions == ("bmp", "tif")
    assert restored.content_image_extensions == (".bmp", ".tif")


def test_an_entry_holding_a_comma_survives_the_round_trip(settings: FakeSettings) -> None:
    """The list is stored as a list, so an entry is never split by what it contains -- the thing #222's
    single comma-separated string could not do (#231).

    **Test steps:**

    * save a list whose entry contains a comma
    * load it back and verify the entry is intact
    """
    section = ReferenceImagesSettings(extensions=("we,ird", "bmp"))

    section.save(settings)  # type: ignore[arg-type]

    restored = ReferenceImagesSettings()
    restored.load(settings)  # type: ignore[arg-type]

    assert restored.extensions == ("we,ird", "bmp")


def test_load_falls_back_to_the_shipped_set_when_nothing_was_saved(settings: FakeSettings) -> None:
    """Loading from settings that never had the group saved yields an empty list, hence the shipped set.

    **Test steps:**

    * load into an instance holding other values, from an empty settings stand-in
    * verify the stored list is empty and the effective set is core's
    """
    section = ReferenceImagesSettings(extensions=("bmp",))

    section.load(settings)  # type: ignore[arg-type]

    assert not section.extensions
    assert section.content_image_extensions == CONTENT_IMAGE_EXTENSIONS


# endregion

# region the shared instance


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
    * verify the returned instance reflects the pre-populated list
    """
    fake = FakeSettings()
    ReferenceImagesSettings(extensions=("bmp",)).save(fake)  # type: ignore[arg-type]
    mocker.patch.object(reference_images_settings, "persistent_settings", return_value=fake)

    instance = shared_reference_images_settings()

    assert instance.extensions == ("bmp",)


# endregion

# region what the enumeration counts


def test_the_saved_list_is_what_the_content_image_enumeration_counts(
    settings: FakeSettings, mocker: MockerFixture
) -> None:
    """The whole point of the page: a saved list changes what #197's enumeration counts, so a reference
    pack in a format the shipped set omits stops counting zero ([[data-model#resource-scoping]]).

    **Test steps:**

    * mock ``foo.rehu``'s sibling archive to hold one ``.bmp`` and one ``.jpg``
    * enumerate under a freshly-loaded (empty) list, and verify only the ``.jpg`` counts
    * save a ``bmp``-only list, load it back, and enumerate under it
    * verify only the ``.bmp`` counts
    """
    mocker.patch.object(Path, "iterdir", return_value=[ARCHIVE_PATH])
    opened = mocker.MagicMock()
    opened.__enter__.return_value.infolist.return_value = [
        zipfile.ZipInfo("page01.bmp"),
        zipfile.ZipInfo("page02.jpg"),
    ]
    mocker.patch("rehuco_core.rehu_content_images.zipfile.ZipFile", return_value=opened)
    ReferenceImagesSettings(extensions=("bmp",)).save(settings)  # type: ignore[arg-type]
    section = ReferenceImagesSettings()

    shipped_entries = enumerate_content_images(FILE_SCOPED_PATH, section.content_image_extensions)
    section.load(settings)  # type: ignore[arg-type]
    configured_entries = enumerate_content_images(FILE_SCOPED_PATH, section.content_image_extensions)

    assert shipped_entries == [ContentImageEntry(ARCHIVE_PATH, "page02.jpg")]
    assert configured_entries == [ContentImageEntry(ARCHIVE_PATH, "page01.bmp")]


# endregion
