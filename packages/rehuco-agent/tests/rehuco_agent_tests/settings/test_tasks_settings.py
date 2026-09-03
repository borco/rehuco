"""Tests for TasksSettings: the three restart-time choices over the saved task queue (#202).

Uses the same hand-rolled in-memory ``QSettings`` stand-in as ``test_main_window_settings.py``.
"""

from typing import Any

from pytest import fixture
from rehuco_agent.settings.tasks_settings import TasksSettings


# region fixtures
# Mirrors test_main_window_settings.py's FakeSettings exactly -- kept as a separate copy rather than a
# shared fixture module since TasksSettings and MainWindowSettings are deliberately separate classes.
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


def test_all_three_default_off(settings: FakeSettings) -> None:
    """Loading from a settings store with nothing written keeps every choice ``False``.

    All three ship off: nothing is swept or restarted unless asked.

    **Test steps:**

    * load a fresh ``TasksSettings`` from an empty store
    * verify all three fields are ``False``
    """
    loaded = TasksSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.clear_done_on_restart is False
    assert loaded.clear_failed_on_restart is False
    assert loaded.resume_on_restart is False


def test_save_then_load_round_trips_all_three(settings: FakeSettings) -> None:
    """Saving and reloading reproduces each choice independently.

    **Test steps:**

    * save a `TasksSettings` with all three ``True``
    * load into a fresh instance from the same store
    * verify every field came back ``True``
    """
    saved = TasksSettings(clear_done_on_restart=True, clear_failed_on_restart=True, resume_on_restart=True)
    saved.save(settings)  # type: ignore[arg-type]

    loaded = TasksSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.clear_done_on_restart is True
    assert loaded.clear_failed_on_restart is True
    assert loaded.resume_on_restart is True


def test_each_choice_is_independent(settings: FakeSettings) -> None:
    """Turning on one choice leaves the other two off.

    **Test steps:**

    * save a `TasksSettings` with only ``clear_failed_on_restart`` set
    * load into a fresh instance
    * verify only that one field came back ``True``
    """
    saved = TasksSettings(clear_failed_on_restart=True)
    saved.save(settings)  # type: ignore[arg-type]

    loaded = TasksSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.clear_done_on_restart is False
    assert loaded.clear_failed_on_restart is True
    assert loaded.resume_on_restart is False
