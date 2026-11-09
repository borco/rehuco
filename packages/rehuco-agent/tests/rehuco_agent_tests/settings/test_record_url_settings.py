"""Tests for RecordUrlSettings: where a record's URL is shown, live (#620)."""

from collections.abc import Iterator
from typing import Any

from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_agent.settings import record_url_settings
from rehuco_agent.settings.record_url_settings import RecordUrlSettings, shared_record_url_settings


# region fixtures
# Mirrors test_description_editor_settings.py's FakeSettings exactly -- kept as a separate copy,
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


@fixture
def settings() -> FakeSettings:
    """A fresh in-memory settings stand-in."""
    return FakeSettings()


# pylint: enable=duplicate-code


@fixture(autouse=True)
def clear_shared_instance_cache() -> Iterator[None]:
    """Clear the ``lru_cache``-backed singleton before and after every test."""
    shared_record_url_settings.cache_clear()
    yield
    shared_record_url_settings.cache_clear()


# endregion


def test_load_defaults_when_nothing_was_saved(settings: FakeSettings) -> None:
    """Loading from settings that never had anything saved shows the URL on both views.

    **Test steps:**

    * load into a fresh instance from an empty settings stand-in
    * verify both choices hold their default: ``True``
    """
    loaded = RecordUrlSettings()

    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.show_on_main_view is True
    assert loaded.show_on_description_view is True


def test_save_then_load_round_trips_both_choices(settings: FakeSettings) -> None:
    """Saving and reloading reproduces each choice, independently.

    **Test steps:**

    * turn only the Main View off on a fresh instance and save
    * load into a fresh instance from the same settings stand-in
    * verify the Main View came back off and the Description View still on
    * do the same the other way round
    """
    original = RecordUrlSettings()
    original.show_on_main_view = False
    original.save(settings)  # type: ignore[arg-type]
    restored = RecordUrlSettings()
    restored.load(settings)  # type: ignore[arg-type]

    assert restored.show_on_main_view is False
    assert restored.show_on_description_view is True

    original.show_on_main_view = True
    original.show_on_description_view = False
    original.save(settings)  # type: ignore[arg-type]
    restored.load(settings)  # type: ignore[arg-type]

    assert restored.show_on_main_view is True
    assert restored.show_on_description_view is False


def test_each_choice_fires_its_own_changed_signal(mocker: MockerFixture) -> None:
    """Each choice has its own ``*_changed`` signal, which the fields follow live.

    **Test steps:**

    * connect a slot to each signal
    * flip each choice
    * verify only its own slot heard it, with the new value
    """
    settings = RecordUrlSettings()
    on_main = mocker.Mock()
    on_description = mocker.Mock()
    settings.show_on_main_view_changed.connect(on_main)  # type: ignore[attr-defined]
    settings.show_on_description_view_changed.connect(on_description)  # type: ignore[attr-defined]

    settings.show_on_main_view = False

    on_main.assert_called_once_with(False)
    on_description.assert_not_called()

    settings.show_on_description_view = False

    on_description.assert_called_once_with(False)
    on_main.assert_called_once_with(False)


def test_shared_instance_loads_from_persistent_storage_once(mocker: MockerFixture, settings: FakeSettings) -> None:
    """The shared instance loads what was persisted, and is the same object on every call.

    **Test steps:**

    * persist the Description View off
    * patch ``persistent_settings`` to return that storage
    * verify the shared instance has it off, and that a second call returns the same instance
    """
    stored = RecordUrlSettings()
    stored.show_on_description_view = False
    stored.save(settings)  # type: ignore[arg-type]
    mocker.patch.object(record_url_settings, "persistent_settings", return_value=settings)

    shared = shared_record_url_settings()

    assert shared.show_on_description_view is False
    assert shared_record_url_settings() is shared
