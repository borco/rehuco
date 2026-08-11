"""Tests for TraySettings: whether tray mode is on (#205)."""

from typing import Any

from pytest import fixture
from rehuco_agent.settings.tray_settings import TraySettings


# region fixtures
# Mirrors test_tasks_settings.py's FakeSettings exactly -- kept as a separate copy rather than a
# shared fixture module, matching this codebase's settings-test convention.
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


# endregion


def test_defaults_off(settings: FakeSettings) -> None:
    """Loading from a settings store with nothing written keeps ``enabled`` ``False`` (#205): closing
    the window is a decision to quit until tray mode is turned on.

    **Test steps:**

    * load a fresh ``TraySettings`` from an empty store
    * verify ``enabled`` is ``False``
    """
    loaded = TraySettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.enabled is False


def test_save_then_load_round_trips(settings: FakeSettings) -> None:
    """Saving and reloading reproduces the choice.

    **Test steps:**

    * save a `TraySettings` with ``enabled`` set
    * load into a fresh instance from the same store
    * verify it came back ``True``
    """
    saved = TraySettings()
    saved.enabled = True
    saved.save(settings)  # type: ignore[arg-type]

    loaded = TraySettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.enabled is True
