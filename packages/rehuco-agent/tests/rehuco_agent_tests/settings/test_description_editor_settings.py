"""Tests for DescriptionEditorSettings: live line-numbers/line-endings/wrap editor settings (#69).

Uses the same hand-rolled in-memory ``QSettings`` stand-in as ``test_markdown_rendering_settings.py``.
"""

from collections.abc import Iterator
from typing import Any

from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_agent.settings import description_editor_settings
from rehuco_agent.settings.description_editor_settings import (
    DescriptionEditorSettings,
    shared_description_editor_settings,
)


# region fixtures
# Mirrors test_markdown_rendering_settings.py's FakeSettings exactly -- kept as a separate copy,
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
    """Clear the ``lru_cache``-backed singleton before and after every test (see
    ``test_markdown_rendering_settings.py`` for the full rationale)."""
    shared_description_editor_settings.cache_clear()
    yield
    shared_description_editor_settings.cache_clear()


# endregion


def test_load_defaults_when_nothing_was_saved(settings: FakeSettings) -> None:
    """Loading from settings that never had anything saved yields the documented defaults:
    everything on, matching what `MarkdownEdit` hard-coded before this setting existed.

    **Test steps:**

    * load into a fresh instance from an empty settings stand-in
    * verify every field holds its default: ``True``
    """
    loaded = DescriptionEditorSettings()

    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.show_line_numbers is True
    assert loaded.show_line_endings is True
    assert loaded.wrap_long_lines is True


def test_save_then_load_round_trips_every_field(settings: FakeSettings) -> None:
    """Saving and reloading reproduces every field's value.

    **Test steps:**

    * set every field off on a fresh instance and save
    * load into a fresh instance from the same settings stand-in
    * verify every field came back off
    """
    original = DescriptionEditorSettings()
    original.show_line_numbers = False
    original.show_line_endings = False
    original.wrap_long_lines = False

    original.save(settings)  # type: ignore[arg-type]

    restored = DescriptionEditorSettings()
    restored.load(settings)  # type: ignore[arg-type]

    assert restored.show_line_numbers is False
    assert restored.show_line_endings is False
    assert restored.wrap_long_lines is False


def test_description_editor_changed_fires_on_every_setting(mocker: MockerFixture) -> None:
    """``description_editor_changed`` fires on each of the three settings changing -- the one
    aggregate signal an open editor follows.

    **Test steps:**

    * connect a spy to ``description_editor_changed`` on a fresh instance
    * flip each of the three settings
    * verify the spy fired once per change
    """
    editor_settings = DescriptionEditorSettings()
    spy = mocker.Mock()
    editor_settings.description_editor_changed.connect(spy)

    editor_settings.show_line_numbers = False
    editor_settings.show_line_endings = False
    editor_settings.wrap_long_lines = False

    assert spy.call_count == 3


def test_description_editor_changed_stays_silent_for_an_unchanged_assignment(mocker: MockerFixture) -> None:
    """Re-assigning a setting its current value leaves ``description_editor_changed`` silent -- the
    `SimpleProperty` no-op, relied on so a settings-page Save that changes nothing restyles nothing.

    **Test steps:**

    * connect a spy on a fresh instance
    * assign every setting its current (default) value
    * verify the spy never fired
    """
    editor_settings = DescriptionEditorSettings()
    spy = mocker.Mock()
    editor_settings.description_editor_changed.connect(spy)

    editor_settings.show_line_numbers = True
    editor_settings.show_line_endings = True
    editor_settings.wrap_long_lines = True

    spy.assert_not_called()


def test_shared_instance_is_the_same_object_across_calls(mocker: MockerFixture) -> None:
    """``shared_description_editor_settings`` returns the identical instance every call.

    **Test steps:**

    * mock ``persistent_settings`` so the first call's ``load`` doesn't touch real storage
    * call the accessor twice
    * verify both calls return the same object
    """
    mocker.patch.object(description_editor_settings, "persistent_settings", return_value=FakeSettings())

    first = shared_description_editor_settings()
    second = shared_description_editor_settings()

    assert first is second


def test_shared_instance_loads_from_persistent_settings_on_first_call(mocker: MockerFixture) -> None:
    """``shared_description_editor_settings`` loads its values from ``persistent_settings()`` the
    first time it's constructed.

    **Test steps:**

    * pre-populate a fake settings store and mock ``persistent_settings`` to return it
    * call the accessor
    * verify the returned instance reflects the pre-populated values
    """
    fake = FakeSettings()
    to_save = DescriptionEditorSettings()
    to_save.wrap_long_lines = False
    to_save.save(fake)  # type: ignore[arg-type]
    mocker.patch.object(description_editor_settings, "persistent_settings", return_value=fake)

    instance = shared_description_editor_settings()

    assert instance.wrap_long_lines is False
    assert instance.show_line_numbers is True
