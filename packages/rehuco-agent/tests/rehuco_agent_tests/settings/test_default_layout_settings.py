"""Tests for DefaultLayoutSettings: the saved default document dock layout of each type (#62, #320, #354).

Uses a hand-rolled in-memory stand-in for ``QSettings`` (see ``test_main_window_settings.py`` for the
same rationale) rather than a real one or ``tmp_path``.
"""

from collections.abc import Iterator
from typing import Any

from PySide6.QtCore import QByteArray
from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_agent.settings import default_layout_settings
from rehuco_agent.settings.default_layout_settings import (
    UNTYPED_GROUP,
    DefaultLayoutSettings,
    shared_default_layout_settings,
)

# region fixtures
# Mirrors every other settings test's FakeSettings exactly -- kept as a separate copy rather than a
# shared import, matching this codebase's settings-test convention.
# pylint: disable=duplicate-code


class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/value API.

    Groups nest on a prefix stack, since this section opens one group per type inside its own
    (``default_layout/<type>/state``, #320), and it enumerates and removes those child groups.
    """

    def __init__(self) -> None:
        self.__data: dict[str, Any] = {}
        self.__prefixes: list[str] = []

    @property
    def __prefix(self) -> str:
        return "".join(self.__prefixes)

    def beginGroup(self, name: str) -> None:  # noqa: N802
        self.__prefixes.append(f"{name}/")

    def endGroup(self) -> None:  # noqa: N802
        if self.__prefixes:
            self.__prefixes.pop()

    def setValue(self, key: str, value: Any) -> None:  # noqa: N802
        self.__data[self.__prefix + key] = value  # pylint: disable=unsupported-assignment-operation

    def value(self, key: str, default: Any = None, type: Any = None) -> Any:  # noqa: A002, N802
        del type
        return self.__data.get(self.__prefix + key, default)

    def childGroups(self) -> list[str]:  # noqa: N802
        prefix = self.__prefix
        nested = (key[len(prefix) :] for key in self.__data if key.startswith(prefix))
        return sorted({rest.split("/")[0] for rest in nested if "/" in rest})

    def remove(self, key: str) -> None:
        full = self.__prefix + key
        for stored in list(self.__data):
            if stored == full or stored.startswith(full + "/") or (not key and stored.startswith(full)):
                del self.__data[stored]  # pylint: disable=unsupported-delete-operation

    def keys(self) -> list[str]:
        """Every stored key, for asserting on what a save left behind."""
        return sorted(self.__data)


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
    """No default has ever been saved on a fresh install, for any type.

    **Test steps:**

    * build a `DefaultLayoutSettings` with no stored values
    * verify it holds no state, and asking for a type answers empty
    """
    settings = DefaultLayoutSettings()

    assert not settings.states
    assert settings.state_for("tutorial") == b""


# endregion

# region storage


def test_the_states_round_trip_through_storage(settings: FakeSettings) -> None:
    """Each type's saved default is read back exactly as it was written, under its own group (#320).

    **Test steps:**

    * save a settings object holding two types' states
    * verify each landed at ``default_layout/<type>/state``
    * load a fresh one from the same storage and verify it came back unchanged
    """
    saved = DefaultLayoutSettings(states={"tutorial": b"tutorial blob", "reference_images": b"pack blob"})
    saved.save(settings)  # pyright: ignore[reportArgumentType]

    assert settings.keys() == ["default_layout/reference_images/state", "default_layout/tutorial/state"]

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


def test_saving_drops_a_reset_type_and_the_untyped_blob(settings: FakeSettings) -> None:
    """A type popped from the states leaves storage on the next save, and so does the untyped blob a
    pre-#320 build wrote at ``default_layout/state`` -- dropped, not migrated, since it was written
    against the pre-split dock set (#320).

    **Test steps:**

    * seed storage with the untyped blob and two types, then load
    * verify the untyped blob was ignored
    * pop one type, save, and verify only the other remains in storage
    """
    settings.beginGroup("default_layout")
    settings.setValue("state", QByteArray(b"old untyped blob"))
    settings.endGroup()
    both = DefaultLayoutSettings(states={"tutorial": b"t", "reference_images": b"r"})
    both.save(settings)  # pyright: ignore[reportArgumentType]
    loaded = DefaultLayoutSettings()
    loaded.load(settings)  # pyright: ignore[reportArgumentType]
    assert loaded.states == {"tutorial": b"t", "reference_images": b"r"}

    loaded.states.pop("tutorial")
    loaded.save(settings)  # pyright: ignore[reportArgumentType]

    assert settings.keys() == ["default_layout/reference_images/state"]


def test_the_empty_types_state_round_trips_under_its_own_group(settings: FakeSettings) -> None:
    """The empty type's default is stored under :data:`UNTYPED_GROUP` -- never the malformed
    ``default_layout//state``, nor the legacy untyped ``default_layout/state`` a save drops -- and read
    back keyed by ``""`` (#354).

    **Test steps:**

    * save a settings object holding the empty type's state and a tutorial's
    * verify the empty type landed at ``default_layout/<UNTYPED_GROUP>/state``
    * load a fresh one from the same storage and verify it came back unchanged
    * pop the empty type, save, and verify its group left storage
    """
    saved = DefaultLayoutSettings(states={"": b"untyped blob", "tutorial": b"tutorial blob"})
    saved.save(settings)  # pyright: ignore[reportArgumentType]

    assert settings.keys() == [f"default_layout/{UNTYPED_GROUP}/state", "default_layout/tutorial/state"]

    loaded = DefaultLayoutSettings()
    loaded.load(settings)  # pyright: ignore[reportArgumentType]
    assert loaded == saved

    loaded.states.pop("")
    loaded.save(settings)  # pyright: ignore[reportArgumentType]

    assert settings.keys() == ["default_layout/tutorial/state"]


def test_an_empty_stored_state_reads_as_no_default(settings: FakeSettings) -> None:
    """A type whose stored blob is empty has no default, the same as a type never saved.

    **Test steps:**

    * store an empty blob under a type and load
    * verify the type is absent from the states
    """
    settings.beginGroup("default_layout")
    settings.beginGroup("collection")
    settings.setValue("state", QByteArray())
    settings.endGroup()
    settings.endGroup()

    loaded = DefaultLayoutSettings()
    loaded.load(settings)  # pyright: ignore[reportArgumentType]

    assert not loaded.states


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
