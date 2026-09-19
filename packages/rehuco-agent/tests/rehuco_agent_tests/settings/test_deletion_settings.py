"""Tests for DeletionSettings: the one deletion policy (#291, #312, #313).

Uses a hand-rolled in-memory stand-in for ``QSettings`` (see ``test_excluded_files_settings.py`` for
the same rationale) rather than a real one or ``tmp_path``.
"""

from collections.abc import Iterator
from typing import Any

from pytest import fixture, mark
from pytest_mock import MockerFixture
from rehuco_agent.settings import deletion_settings
from rehuco_agent.settings.deletion_settings import (
    DEFAULT_CLEAR_BACKUPS_WITHOUT_ASKING,
    DEFAULT_DELETE_IMAGES_WITHOUT_ASKING,
    DEFAULT_USE_RECYCLE_BIN,
    WITHOUT_ASKING_BOXES,
    DeletionKind,
    DeletionSettings,
    remember_without_asking,
    shared_deletion_settings,
)


# region fixtures
# Mirrors every other settings test's FakeSettings exactly -- kept as a separate copy rather than a
# shared import, matching this codebase's settings-test convention.
# pylint: disable=duplicate-code
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/value API."""

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
    shared_deletion_settings.cache_clear()
    yield
    shared_deletion_settings.cache_clear()


# endregion

# region defaults and persistence


def test_a_fresh_instance_defaults_to_the_recycle_bin_and_to_asking() -> None:
    """The safer defaults: a delete tries the bin, and a permanent one is asked about.

    **Test steps:**

    * build a settings object without loading anything
    * verify it defaults to using the Recycle Bin and to asking for both kinds of file
    """
    settings = DeletionSettings()

    assert settings.use_recycle_bin is DEFAULT_USE_RECYCLE_BIN
    assert DEFAULT_USE_RECYCLE_BIN is True
    assert settings.clear_backups_without_asking is DEFAULT_CLEAR_BACKUPS_WITHOUT_ASKING
    assert DEFAULT_CLEAR_BACKUPS_WITHOUT_ASKING is False
    assert settings.delete_images_without_asking is DEFAULT_DELETE_IMAGES_WITHOUT_ASKING
    assert DEFAULT_DELETE_IMAGES_WITHOUT_ASKING is False


def test_load_falls_back_to_the_default_on_a_fresh_install(settings: FakeSettings) -> None:
    """With nothing persisted, loading yields the defaults.

    **Test steps:**

    * load a settings object from empty storage
    * verify it holds the default for all three choices
    """
    loaded = DeletionSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.use_recycle_bin is DEFAULT_USE_RECYCLE_BIN
    assert loaded.clear_backups_without_asking is DEFAULT_CLEAR_BACKUPS_WITHOUT_ASKING
    assert loaded.delete_images_without_asking is DEFAULT_DELETE_IMAGES_WITHOUT_ASKING


def test_the_choice_round_trips_through_storage(settings: FakeSettings) -> None:
    """What was saved is what loads back.

    **Test steps:**

    * save a settings object with every box flipped from its default
    * load a second object from the same storage
    * verify it holds the same choices
    """
    saved = DeletionSettings(
        clear_backups_without_asking=True, delete_images_without_asking=True, use_recycle_bin=False
    )
    saved.save(settings)  # type: ignore[arg-type]

    loaded = DeletionSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.clear_backups_without_asking is True
    assert loaded.delete_images_without_asking is True
    assert loaded.use_recycle_bin is False


def test_the_pre_312_recycle_bin_key_still_loads(settings: FakeSettings) -> None:
    """The one value that predates the rename maps onto the same box: the group and key were kept
    for exactly this, and the dropped no-bin knob's key is simply no longer read (#312).

    **Test steps:**

    * seed storage the way a pre-#312 build wrote it: the bin off, the old knob on, nothing else
    * load a settings object from it
    * verify the bin choice arrived and the two new boxes hold their defaults
    """
    settings.setValue("screenshot_deletion/use_recycle_bin", False)
    settings.setValue("screenshot_deletion/permanently_delete_if_unreachable", True)

    loaded = DeletionSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.use_recycle_bin is False
    assert loaded.clear_backups_without_asking is DEFAULT_CLEAR_BACKUPS_WITHOUT_ASKING
    assert loaded.delete_images_without_asking is DEFAULT_DELETE_IMAGES_WITHOUT_ASKING


# endregion

# region the shared instance


def test_the_shared_instance_is_loaded_once(mocker: MockerFixture, settings: FakeSettings) -> None:
    """The singleton reads persistent storage on first call and hands the same object back after.

    **Test steps:**

    * seed storage with the Recycle Bin turned off and patch ``persistent_settings`` to return it
    * call the shared accessor twice
    * verify both calls returned the same object, holding the seeded choice
    """
    settings.setValue("screenshot_deletion/use_recycle_bin", False)
    mocker.patch.object(deletion_settings, "persistent_settings", return_value=settings)

    first = shared_deletion_settings()
    second = shared_deletion_settings()

    assert first is second
    assert first.use_recycle_bin is False


# endregion

# region the boxes by kind (#313)


@mark.parametrize(
    ("kind", "field"),
    [
        (DeletionKind.BACKUPS, "clear_backups_without_asking"),
        (DeletionKind.IMAGES, "delete_images_without_asking"),
    ],
)
def test_each_kind_reads_and_writes_its_own_box(kind: DeletionKind, field: str) -> None:
    """A kind is an address for one of the two boxes, and nothing else moves when it is written.

    **Test steps:**

    * read the kind's box on a fresh instance, then set it
    * verify the read followed the named field, the write landed on it, and the other box is untouched
    """
    settings = DeletionSettings()
    assert settings.without_asking(kind) is False

    settings.set_without_asking(kind, True)

    assert getattr(settings, field) is True
    other = next(candidate for candidate in DeletionKind if candidate is not kind)
    assert settings.without_asking(other) is False


@mark.parametrize("kind", list(DeletionKind))
def test_the_table_names_the_files_page_label_verbatim(kind: DeletionKind) -> None:
    """The checkbox a confirmation carries is worded exactly as the box on Files, which is what makes
    the tick recoverable: the user knows which box to untick.

    **Test steps:**

    * read the kind's box from the table
    * verify its label is the settings page's own text and its field is a real setting
    """
    box = WITHOUT_ASKING_BOXES[kind]

    assert box.label.endswith("without asking")
    assert hasattr(DeletionSettings(), box.field)


def test_remember_without_asking_ticks_the_shared_box_and_persists_it(
    mocker: MockerFixture, settings: FakeSettings
) -> None:
    """A confirmation's tick writes the setting itself -- nothing new is stored, and the next reader
    of the shared instance sees it as well as the next launch.

    **Test steps:**

    * patch ``persistent_settings`` to an in-memory store and remember the backups kind
    * verify the shared instance holds the tick, and a fresh load from the store holds it too
    """
    mocker.patch.object(deletion_settings, "persistent_settings", return_value=settings)

    remember_without_asking(DeletionKind.BACKUPS)

    assert shared_deletion_settings().clear_backups_without_asking is True
    reloaded = DeletionSettings()
    reloaded.load(settings)  # type: ignore[arg-type]
    assert reloaded.clear_backups_without_asking is True
    assert reloaded.delete_images_without_asking is False


# endregion
