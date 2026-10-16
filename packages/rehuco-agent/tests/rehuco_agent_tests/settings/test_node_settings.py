"""Tests for NodeSettings: whether the local node runs beside the agent (#506)."""

from typing import Any

from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_agent.settings import node_settings
from rehuco_agent.settings.node_settings import NodeSettings, shared_node_settings


# region fixtures
# Mirrors test_tray_settings.py's FakeSettings exactly -- kept as a separate copy rather than a
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


# pylint: enable=duplicate-code


@fixture
def settings() -> FakeSettings:
    """A fresh in-memory settings stand-in."""
    return FakeSettings()


# endregion


def test_defaults_on(settings: FakeSettings) -> None:
    """Loading from a store with nothing written keeps ``enabled`` ``True``: the node runs unless turned off.

    **Test steps:**

    * load a fresh ``NodeSettings`` from an empty store
    * verify ``enabled`` is ``True``
    """
    loaded = NodeSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.enabled is True


def test_save_then_load_round_trips(settings: FakeSettings) -> None:
    """Saving ``False`` and reloading reproduces the choice.

    **Test steps:**

    * save a ``NodeSettings`` with the node off, load a fresh one from the same store
    * verify ``enabled`` is ``False``
    """
    saved = NodeSettings()
    saved.enabled = False
    saved.save(settings)  # type: ignore[arg-type]

    loaded = NodeSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.enabled is False


def test_enabled_changed_fires_on_a_real_change_only() -> None:
    """The reactive field emits once per value change, never for an assignment of the same value.

    **Test steps:**

    * connect a counter, assign ``True`` (the default) then ``False`` then ``False``
    * verify one emission, carrying ``False``
    """
    node = NodeSettings()
    seen: list[bool] = []
    node.enabled_changed.connect(seen.append)  # type: ignore[attr-defined]

    node.enabled = True
    node.enabled = False
    node.enabled = False

    assert seen == [False]


def test_shared_instance_loads_once_from_persistent_storage(mocker: MockerFixture, settings: FakeSettings) -> None:
    """The shared accessor reads the store on first call and hands back the same object after.

    **Test steps:**

    * store the node off, patch ``persistent_settings`` to the store
    * call the accessor twice
    * verify both calls return one object, loaded as off
    """
    shared_node_settings.cache_clear()
    stored = NodeSettings()
    stored.enabled = False
    stored.save(settings)  # type: ignore[arg-type]
    mocker.patch.object(node_settings, "persistent_settings", return_value=settings)

    first = shared_node_settings()
    second = shared_node_settings()

    assert first is second
    assert first.enabled is False
