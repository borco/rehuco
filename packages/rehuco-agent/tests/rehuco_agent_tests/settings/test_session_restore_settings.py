"""Tests for SessionRestoreSettings: whether a restart restores the previous session (#65).

Uses the same hand-rolled in-memory ``QSettings`` stand-in as ``test_tasks_settings.py``.
"""

from typing import Any

from pytest import fixture
from rehuco_agent.settings.session_restore_settings import SessionRestoreSettings


# region fixtures
# Mirrors test_tasks_settings.py's FakeSettings exactly -- kept as a separate copy, matching this
# codebase's settings-test convention.
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


def test_defaults_to_restoring(settings: FakeSettings) -> None:
    """Loading from a settings store with nothing written keeps the shipped default: restore on.

    **Test steps:**

    * load a fresh `SessionRestoreSettings` from an empty store
    * verify ``restore_on_startup`` is ``True``
    """
    loaded = SessionRestoreSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.restore_on_startup is True


def test_save_then_load_round_trips_the_choice(settings: FakeSettings) -> None:
    """Saving and reloading reproduces the choice.

    **Test steps:**

    * save a `SessionRestoreSettings` with ``restore_on_startup`` off
    * load into a fresh instance from the same store
    * verify it came back off
    """
    saved = SessionRestoreSettings(restore_on_startup=False)
    saved.save(settings)  # type: ignore[arg-type]

    loaded = SessionRestoreSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.restore_on_startup is False
