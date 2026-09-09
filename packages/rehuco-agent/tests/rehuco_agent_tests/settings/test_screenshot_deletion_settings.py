"""Tests for ScreenshotDeletionSettings: whether a deleted screenshot goes to the Recycle Bin (#291).

Uses a hand-rolled in-memory stand-in for ``QSettings`` (see ``test_excluded_files_settings.py`` for
the same rationale) rather than a real one or ``tmp_path``.
"""

from collections.abc import Iterator
from typing import Any

from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_agent.settings import screenshot_deletion_settings
from rehuco_agent.settings.screenshot_deletion_settings import (
    DEFAULT_USE_RECYCLE_BIN,
    ScreenshotDeletionSettings,
    shared_screenshot_deletion_settings,
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
    shared_screenshot_deletion_settings.cache_clear()
    yield
    shared_screenshot_deletion_settings.cache_clear()


# endregion

# region defaults and persistence


def test_a_fresh_instance_defaults_to_the_recycle_bin() -> None:
    """On: the safer default is the everyday case, a permanent delete the deliberate exception.

    **Test steps:**

    * build a settings object without loading anything
    * verify it defaults to using the Recycle Bin
    """
    assert ScreenshotDeletionSettings().use_recycle_bin is DEFAULT_USE_RECYCLE_BIN
    assert DEFAULT_USE_RECYCLE_BIN is True


def test_load_falls_back_to_the_default_on_a_fresh_install(settings: FakeSettings) -> None:
    """With nothing persisted, loading yields the default.

    **Test steps:**

    * load a settings object from empty storage
    * verify it holds the default
    """
    loaded = ScreenshotDeletionSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.use_recycle_bin is DEFAULT_USE_RECYCLE_BIN


def test_the_choice_round_trips_through_storage(settings: FakeSettings) -> None:
    """What was saved is what loads back.

    **Test steps:**

    * save a settings object with the Recycle Bin turned off
    * load a second object from the same storage
    * verify it holds the same choice
    """
    saved = ScreenshotDeletionSettings(use_recycle_bin=False)
    saved.save(settings)  # type: ignore[arg-type]

    loaded = ScreenshotDeletionSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.use_recycle_bin is False


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
    mocker.patch.object(screenshot_deletion_settings, "persistent_settings", return_value=settings)

    first = shared_screenshot_deletion_settings()
    second = shared_screenshot_deletion_settings()

    assert first is second
    assert first.use_recycle_bin is False


# endregion
