"""Tests for ScrapersSettings: where the Scrapers settings page keeps the scripts folder and the
browser persona's own settings (#269, #278).

Uses a hand-rolled in-memory stand-in for ``QSettings`` (see ``test_main_window_settings.py`` for the
same rationale) rather than a real one or ``tmp_path``.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_agent.settings import persistent_settings as persistent_settings_module
from rehuco_agent.settings import scrapers_settings
from rehuco_agent.settings.scrapers_settings import (
    Browser,
    ScrapersSettings,
    default_scripts_folder,
    persona_folder,
    scraper_key,
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
    config directory (see ``test_markdown_rendering_settings.py`` for the full rationale) -- patched
    where :func:`~rehuco_agent.settings.persistent_settings.config_folder` resolves it too (#361)."""
    mocker.patch.object(scrapers_settings, "persistent_settings", return_value=FakeSettings())
    mocker.patch.object(persistent_settings_module, "persistent_settings", return_value=FakeSettings())
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


def test_persona_folder_is_nested_under_this_apps_config_directory_per_browser() -> None:
    """Each browser gets its own persona folder, nested under this app's config directory (#278).

    **Test steps:**

    * ask for Firefox's and Chrome's persona folders
    * verify both are nested under the app's config directory, by browser name
    """
    assert persona_folder(Browser.FIREFOX) == Path("/fake/borco/rehuco-agent/persona/firefox")
    assert persona_folder(Browser.CHROME) == Path("/fake/borco/rehuco-agent/persona/chrome")


def test_uses_browser_is_true_for_a_needs_browser_scraper_even_when_not_ticked() -> None:
    """A scraper declaring `needs_browser` always uses the browser, whether or not it is in
    :attr:`ScrapersSettings.browser_scrapers` (#278).

    **Test steps:**

    * build settings ticking nothing
    * verify a `needs_browser` scraper still answers `True`
    """

    @dataclass
    class GatedScraper:  # pylint: disable=missing-class-docstring
        needs_browser: bool = True

    assert ScrapersSettings().uses_browser(GatedScraper()) is True


def test_uses_browser_follows_the_ticked_set_for_an_optional_scraper() -> None:
    """A scraper that does not declare `needs_browser` uses the browser only when its key was ticked
    (#278).

    **Test steps:**

    * build a scraper and compute its key
    * verify settings ticking nothing answer `False`, and settings ticking its key answer `True`
    """

    @dataclass
    class PlainScraper:  # pylint: disable=missing-class-docstring
        needs_browser: bool = False

    scraper = PlainScraper()
    key = scraper_key(scraper)

    assert ScrapersSettings().uses_browser(scraper) is False
    assert ScrapersSettings(browser_scrapers=frozenset({key})).uses_browser(scraper) is True


def test_scraper_key_is_the_classs_module_and_qualname() -> None:
    """A scraper's key names its class by module and qualname -- stable across reloads for a scripts-
    folder scraper, whose module is always prefixed the same way (#278).

    **Test steps:**

    * build a scraper
    * verify its key matches ``<module>.<qualname>``
    """

    @dataclass
    class SomeScraper:  # pylint: disable=missing-class-docstring
        needs_browser: bool = False

    assert scraper_key(SomeScraper()) == f"{SomeScraper.__module__}.{SomeScraper.__qualname__}"


def test_every_new_value_round_trips_through_storage(settings: FakeSettings) -> None:
    """Saving and reloading reproduces the browser, show-browser flag and ticked scrapers, alongside
    the folder (#278).

    **Test steps:**

    * save a settings object with every field set to a non-default value
    * load a fresh object from the same storage
    * verify every field round-tripped
    """
    saved = ScrapersSettings(
        scripts_folder="/my/scrapers",
        browser=Browser.CHROME,
        show_browser=True,
        browser_scrapers=frozenset({"a.B", "c.D"}),
    )
    saved.save(settings)  # type: ignore[arg-type]

    loaded = ScrapersSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.browser == Browser.CHROME
    assert loaded.show_browser is True
    assert loaded.browser_scrapers == frozenset({"a.B", "c.D"})


def test_load_falls_back_to_firefox_and_nothing_ticked_on_a_fresh_install(settings: FakeSettings) -> None:
    """With nothing persisted, loading yields Firefox, showing off, and no ticked scrapers (#278).

    **Test steps:**

    * load a settings object from empty storage
    * verify the three defaults
    """
    loaded = ScrapersSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.browser == Browser.FIREFOX
    assert loaded.show_browser is False
    assert loaded.browser_scrapers == frozenset()


def test_a_stored_browser_this_build_does_not_recognize_falls_back_to_firefox(settings: FakeSettings) -> None:
    """A browser name from an older or newer build that this one does not know falls back to Firefox,
    rather than raising (#278).

    **Test steps:**

    * store an unrecognized browser name
    * load a settings object from it
    * verify it fell back to Firefox
    """
    settings.setValue("scrapers/browser", "safari")

    loaded = ScrapersSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.browser == Browser.FIREFOX


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
