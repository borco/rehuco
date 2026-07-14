"""Tests for ThemeSettings: the persisted app-wide theme mode.

Uses a hand-rolled in-memory stand-in for ``QSettings`` (see ``test_main_window_settings.py`` for
the same rationale) rather than a real one or ``tmp_path``.
"""

from typing import Any

from PySide6.QtCore import Qt
from pytest import fixture
from rehuco_agent.settings.theme_settings import ThemeSettings


# region fixtures
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/value API.

    Method names and the ``type=`` parameter deliberately mirror ``QSettings``'s own C++-derived
    API, since :meth:`ThemeSettings.load`/:meth:`~ThemeSettings.save` call them by name.
    """

    def __init__(self) -> None:
        self.__data: dict[str, Any] = {}
        self.__group = ""

    def beginGroup(self, name: str) -> None:  # noqa: N802
        self.__group = f"{name}/"

    def endGroup(self) -> None:  # noqa: N802
        self.__group = ""

    def setValue(self, key: str, value: Any) -> None:  # noqa: N802
        self.__data[self.__group + key] = value  # pylint: disable=unsupported-assignment-operation

    def value(self, key: str, default: Any = None, type: Any = None) -> Any:  # noqa: A002, N802
        del type
        return self.__data.get(self.__group + key, default)


@fixture
def settings() -> FakeSettings:
    """A fresh in-memory settings stand-in."""
    return FakeSettings()


# endregion


def test_save_then_load_round_trips_the_mode(settings: FakeSettings) -> None:
    """Saving and reloading reproduces the same mode.

    **Test steps:**

    * set a non-default mode and save
    * load into a fresh instance from the same settings stand-in
    * verify the mode came back unchanged
    """
    theme_settings = ThemeSettings(mode=Qt.ColorScheme.Dark)

    theme_settings.save(settings)  # type: ignore[arg-type]

    restored = ThemeSettings()
    restored.load(settings)  # type: ignore[arg-type]

    assert restored.mode == Qt.ColorScheme.Dark


def test_load_defaults_to_unknown_when_nothing_was_saved(settings: FakeSettings) -> None:
    """Loading from settings that never had a mode saved yields ``Unknown`` (follow system).

    **Test steps:**

    * load into a fresh instance from an empty settings stand-in
    * verify the mode is ``Unknown``
    """
    theme_settings = ThemeSettings()

    theme_settings.load(settings)  # type: ignore[arg-type]

    assert theme_settings.mode == Qt.ColorScheme.Unknown


def test_load_falls_back_to_unknown_for_an_out_of_range_stored_value(settings: FakeSettings) -> None:
    """A stored value that doesn't correspond to any ``Qt.ColorScheme`` member (e.g. from a
    corrupted ``.ini`` or a future, wider enum written by a newer version) falls back to
    ``Unknown`` rather than being kept as-is -- ``Qt.ColorScheme(value)`` doesn't raise for an
    out-of-range int (confirmed empirically), so the fallback can't rely on catching a ``ValueError``.

    **Test steps:**

    * store a value with no matching ``Qt.ColorScheme`` member
    * load into a fresh instance
    * verify the mode falls back to ``Unknown``
    """
    settings.setValue("theme/mode", 99)

    theme_settings = ThemeSettings()
    theme_settings.load(settings)  # type: ignore[arg-type]

    assert theme_settings.mode == Qt.ColorScheme.Unknown
