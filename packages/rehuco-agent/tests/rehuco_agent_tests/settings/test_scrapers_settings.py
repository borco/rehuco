"""Tests for ScrapersSettings: where the Scrapers settings page keeps the scripts folder (#269).

Uses a hand-rolled in-memory stand-in for ``QSettings`` (see ``test_main_window_settings.py`` for the
same rationale) rather than a real one or ``tmp_path``.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_agent.settings import scrapers_settings
from rehuco_agent.settings.scrapers_settings import (
    ScrapersSettings,
    default_scripts_folder,
    shared_scrapers_settings,
)


# region fixtures
# Mirrors every other settings test's FakeSettings exactly -- kept as a separate copy rather than a
# shared import, matching this codebase's settings-test convention.
# pylint: disable=duplicate-code
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/value API, plus ``fileName`` -- what
    :func:`default_scripts_folder` derives its default folder from.
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

    def fileName(self) -> str:  # noqa: N802
        return "/fake/borco/rehuco-agent.ini"


@fixture
def settings() -> FakeSettings:
    """A fresh in-memory settings stand-in."""
    return FakeSettings()


# pylint: enable=duplicate-code


@fixture(autouse=True)
def clear_shared_instance_cache(mocker: MockerFixture) -> Iterator[None]:
    """Clear the ``lru_cache``-backed singleton before and after every test, and patch
    ``persistent_settings`` so :func:`default_scripts_folder` never reaches the developer's real
    config directory (see ``test_markdown_rendering_settings.py`` for the full rationale)."""
    mocker.patch.object(scrapers_settings, "persistent_settings", return_value=FakeSettings())
    shared_scrapers_settings.cache_clear()
    yield
    shared_scrapers_settings.cache_clear()


# endregion


def test_effective_scripts_folder_falls_back_to_the_default_when_empty() -> None:
    """An empty ``scripts_folder`` resolves to :func:`default_scripts_folder`, not to a blank path
    (#269).

    **Test steps:**

    * build a settings object with no configured folder
    * verify the effective folder is the default one
    """
    settings_object = ScrapersSettings()

    assert settings_object.effective_scripts_folder == default_scripts_folder()


def test_default_scripts_folder_lives_under_this_apps_own_config_directory() -> None:
    """The default is the ``.ini``'s directory plus this app's own name plus ``scrapers`` -- not the
    organization directory alone, which every borco app shares (#269).

    **Test steps:**

    * ask for the default scripts folder
    * verify it is nested under the app name, under the fake ``.ini``'s parent
    """
    assert default_scripts_folder() == Path("/fake/borco/rehuco-agent/scrapers")


def test_effective_scripts_folder_returns_the_configured_value() -> None:
    """A configured ``scripts_folder`` is returned as-is, not replaced by the default (#269).

    **Test steps:**

    * build a settings object with a configured folder
    * verify the effective folder matches it
    """
    settings_object = ScrapersSettings(scripts_folder="/my/scrapers")

    assert settings_object.effective_scripts_folder == Path("/my/scrapers")


def test_load_falls_back_to_empty_on_a_fresh_install(settings: FakeSettings) -> None:
    """With nothing persisted, loading yields an empty ``scripts_folder`` (#269).

    **Test steps:**

    * load a settings object from empty storage
    * verify the folder is empty
    """
    loaded = ScrapersSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.scripts_folder == ""


def test_every_value_round_trips_through_storage(settings: FakeSettings) -> None:
    """Saving and reloading reproduces the same configured folder (#269).

    **Test steps:**

    * save a settings object with a configured folder
    * load a fresh object from the same storage
    * verify the folder round-tripped
    """
    saved = ScrapersSettings(scripts_folder="/my/scrapers")
    saved.save(settings)  # type: ignore[arg-type]

    loaded = ScrapersSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.scripts_folder == "/my/scrapers"


def test_the_shared_instance_is_loaded_once(mocker: MockerFixture, settings: FakeSettings) -> None:
    """The singleton reads persistent storage on first call and hands the same object back after
    (#269).

    **Test steps:**

    * seed storage with a folder and patch ``persistent_settings`` to return it
    * call the shared accessor twice
    * verify both calls returned the same object, holding the seeded folder
    """
    settings.setValue("scrapers/scripts_folder", "/my/scrapers")
    mocker.patch.object(scrapers_settings, "persistent_settings", return_value=settings)

    first = shared_scrapers_settings()
    second = shared_scrapers_settings()

    assert first is second
    assert first.scripts_folder == "/my/scrapers"
