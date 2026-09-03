"""Tests for DefaultLayoutSettings: the saved default document dock layout (#62).

Uses a hand-rolled in-memory stand-in for ``QSettings`` (see ``test_main_window_settings.py`` for the
same rationale) rather than a real one or ``tmp_path``.
"""

from collections.abc import Iterator
from typing import Any

from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_agent.settings import default_layout_settings
from rehuco_agent.settings.default_layout_settings import DefaultLayoutSettings, shared_default_layout_settings

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
    shared_default_layout_settings.cache_clear()
    yield
    shared_default_layout_settings.cache_clear()


# endregion

# region defaults


def test_a_fresh_install_has_no_saved_default() -> None:
    """No default has ever been saved on a fresh install.

    **Test steps:**

    * build a `DefaultLayoutSettings` with no stored values
    * verify its state is empty
    """
    assert DefaultLayoutSettings().state == b""


# endregion

# region storage


def test_the_state_round_trips_through_storage(settings: FakeSettings) -> None:
    """A saved default is read back exactly as it was written.

    **Test steps:**

    * save a settings object holding a non-empty state
    * load a fresh one from the same storage
    * verify the state came back unchanged
    """
    saved = DefaultLayoutSettings(state=b"some cbor2 blob")
    saved.save(settings)  # pyright: ignore[reportArgumentType]

    loaded = DefaultLayoutSettings()
    loaded.load(settings)  # pyright: ignore[reportArgumentType]

    assert loaded == saved


def test_loading_from_empty_storage_yields_no_default(settings: FakeSettings) -> None:
    """A first run has no stored group at all, and must not read as a real saved default.

    **Test steps:**

    * load from storage nothing was ever saved to
    * verify the result equals a default-constructed settings object
    """
    loaded = DefaultLayoutSettings()
    loaded.load(settings)  # pyright: ignore[reportArgumentType]

    assert loaded == DefaultLayoutSettings()


def test_the_shared_instance_is_the_same_object_every_time(mocker: MockerFixture) -> None:
    """A document's Save must be what the next opened document reads, not a disconnected copy (#62).

    **Test steps:**

    * mock persistent storage and ask for the shared instance twice
    * verify both calls answered the same object, loaded once
    """
    stored = FakeSettings()
    mocker.patch.object(default_layout_settings, "persistent_settings", return_value=stored)

    assert shared_default_layout_settings() is shared_default_layout_settings()


# endregion
