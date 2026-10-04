"""Tests for SessionRestoreSettings: whether a restart restores the previous session (#65).

Uses the same hand-rolled in-memory ``QSettings`` stand-in as ``test_tasks_settings.py``.
"""

from typing import Any

from pytest import fixture
from rehuco_agent.settings.session_restore_settings import GROUP, LEGACY_RESTORE_ON_STARTUP_KEY, SessionRestoreSettings


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
    * verify both choices are ``True``
    """
    loaded = SessionRestoreSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.restore_documents is True
    assert loaded.restore_root_catalog is True


def test_save_then_load_round_trips_the_choice(settings: FakeSettings) -> None:
    """Saving and reloading reproduces the choice.

    **Test steps:**

    * save a `SessionRestoreSettings` with ``restore_documents`` off
    * load into a fresh instance from the same store
    * verify it came back off
    """
    saved = SessionRestoreSettings(restore_documents=False, restore_root_catalog=True)
    saved.save(settings)  # type: ignore[arg-type]

    loaded = SessionRestoreSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.restore_documents is False
    assert loaded.restore_root_catalog is True


def test_the_two_choices_are_independent(settings: FakeSettings) -> None:
    """Root catalog off with documents on survives a round trip (#408).

    **Test steps:**

    * save ``restore_root_catalog`` off, ``restore_documents`` on
    * load into a fresh instance
    * verify each came back as saved
    """
    SessionRestoreSettings(restore_documents=True, restore_root_catalog=False).save(settings)  # type: ignore[arg-type]

    loaded = SessionRestoreSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.restore_documents is True
    assert loaded.restore_root_catalog is False


def test_the_legacy_single_toggle_seeds_both_choices(settings: FakeSettings) -> None:
    """A user who had the old single toggle off keeps both halves off until they choose (#408).

    **Test steps:**

    * write only the legacy ``restore_on_startup`` key, off
    * load a fresh instance
    * verify both choices are off
    """
    settings.beginGroup(GROUP)
    settings.setValue(LEGACY_RESTORE_ON_STARTUP_KEY, False)
    settings.endGroup()

    loaded = SessionRestoreSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.restore_documents is False
    assert loaded.restore_root_catalog is False
