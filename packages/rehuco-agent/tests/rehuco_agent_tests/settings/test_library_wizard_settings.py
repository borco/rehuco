"""Tests for LibraryWizardSettings: the root last used for each scraper wizard (#685).

Uses a hand-rolled in-memory stand-in for ``QSettings`` (see ``test_scrapers_settings.py`` for the same rationale).
"""

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

from pytest import fixture, mark
from pytest_mock import MockerFixture
from rehuco_agent.settings import library_wizard_settings
from rehuco_agent.settings.library_wizard_settings import (
    ROOTS_KEY,
    LibraryWizardSettings,
    shared_library_wizard_settings,
)


# region fixtures
# Mirrors every other settings test's FakeSettings exactly -- kept as a separate copy rather than a shared import,
# matching this codebase's settings-test convention.
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


# pylint: enable=duplicate-code


@fixture(name="settings")
def fixture_settings() -> FakeSettings:
    """A fresh in-memory settings stand-in.

    :returns: the stand-in.
    """
    return FakeSettings()


@fixture(autouse=True)
def clear_shared_instance_cache() -> Iterator[None]:
    """Clear the ``lru_cache``-backed singleton before and after every test."""
    shared_library_wizard_settings.cache_clear()
    yield
    shared_library_wizard_settings.cache_clear()


# endregion


def test_nothing_stored_reads_as_no_roots(settings: FakeSettings) -> None:
    """A store that holds nothing yet gives no remembered root.

    **Test steps:**

    * load from an empty settings stand-in
    * verify no wizard has a root
    """
    loaded = LibraryWizardSettings()

    loaded.load(settings)  # type: ignore[arg-type]  # the stand-in has the two calls load makes

    assert not loaded.roots


def test_save_then_load_round_trips_the_roots(settings: FakeSettings) -> None:
    """The roots saved are the roots loaded, by wizard key.

    **Test steps:**

    * save two wizards' roots
    * load them into a fresh instance from the same stand-in
    * verify both came back
    """
    saved = LibraryWizardSettings({"fab": uuid4(), "udemy": uuid4()})
    saved.save(settings)  # type: ignore[arg-type]  # the stand-in has the two calls save makes
    loaded = LibraryWizardSettings()

    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.roots == saved.roots


@mark.parametrize(
    "stored",
    ["", "not json", "[]", '"text"', '{"fab": "not an id"}', '{"fab": 5}', '{"fab": null}'],
)
def test_a_stored_value_that_is_no_map_of_ids_reads_as_none(settings: FakeSettings, stored: str) -> None:
    """A value another version or a hand edit left is dropped whole, never half read.

    **Test steps:**

    * store a text that is not a JSON map of wizard keys to ids
    * load it over an instance that holds a root
    * verify no root is left
    """
    settings.beginGroup(library_wizard_settings.GROUP)
    settings.setValue(ROOTS_KEY, stored)
    settings.endGroup()
    loaded = LibraryWizardSettings({"fab": uuid4()})

    loaded.load(settings)  # type: ignore[arg-type]

    assert not loaded.roots


def test_the_shared_instance_is_loaded_once(mocker: MockerFixture, settings: FakeSettings) -> None:
    """The shared settings are read from storage on the first call, and the same object is handed on after.

    **Test steps:**

    * store a root for a wizard
    * ask for the shared settings twice
    * verify both calls gave one object, holding the stored root
    """
    root = uuid4()
    LibraryWizardSettings({"fab": root}).save(settings)  # type: ignore[arg-type]
    mocker.patch.object(library_wizard_settings, "persistent_settings", return_value=settings)

    first = shared_library_wizard_settings()
    second = shared_library_wizard_settings()

    assert first is second
    assert first.roots == {"fab": root}
