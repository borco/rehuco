"""Tests for DocksSettings: which border a pinned main dock collapses into (#279).

Uses a hand-rolled in-memory stand-in for ``QSettings`` (see ``test_main_window_settings.py`` for
the same rationale) rather than a real one or ``tmp_path``.
"""

from typing import Any

import PySide6QtAds as QtAds
from pytest import fixture, mark
from pytest_mock import MockerFixture
from rehuco_agent.settings import docks_settings
from rehuco_agent.settings.docks_settings import (
    DEFAULT_PIN_SIDE,
    GROUP,
    PIN_SIDE_KEY,
    SIDE_BAR_LOCATIONS,
    SIDE_LABELS,
    DockPinSide,
    DocksSettings,
    shared_docks_settings,
)


# region fixtures
# Mirrors every other settings test's FakeSettings exactly -- kept as a separate copy rather than a
# shared import, matching this codebase's settings-test convention.
#
# unsupported-assignment-operation is a false positive unique to this copy: importing PySide6QtAds
# (for the sidebar-location assertions below) makes astroid lose track of the plain dict annotation
# on __data and read the subscript assignment as unsupported. Confirmed by removing that one import,
# which silences it -- so the disable is scoped to this class rather than the module.
# pylint: disable=duplicate-code
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin,unsupported-assignment-operation
    """A minimal in-memory stand-in for the ``QSettings`` group/value API.

    Method names and the ``type=`` parameter deliberately mirror ``QSettings``'s own C++-derived
    API, since :meth:`DocksSettings.load`/:meth:`~DocksSettings.save` call them by name.
    """

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
    """In-memory storage for one test.

    :returns: the stand-in storage.
    """
    return FakeSettings()


# endregion


# region the sides themselves


def test_every_side_has_a_qtads_location() -> None:
    """A side the page can offer but nothing can apply would be a choice with nothing behind it.

    **Test steps:**

    * Assert every `DockPinSide` member appears in `SIDE_BAR_LOCATIONS`.
    """
    assert set(SIDE_BAR_LOCATIONS) == set(DockPinSide)


def test_every_side_has_a_label() -> None:
    """The combo box is built from the labels, so a missing one would hide a side outright.

    **Test steps:**

    * Assert every `DockPinSide` member appears in `SIDE_LABELS`.
    """
    assert set(SIDE_LABELS) == set(DockPinSide)


def test_left_maps_to_qtads_left_side_bar() -> None:
    """The one mapping worth pinning down by name -- it is also the default.

    **Test steps:**

    * Assert `DockPinSide.LEFT` maps to QtAds' left sidebar.
    """
    assert SIDE_BAR_LOCATIONS[DockPinSide.LEFT] == QtAds.SideBarLeft


# endregion


# region loading and saving


def test_defaults_to_the_left_side_with_nothing_stored(settings: FakeSettings) -> None:
    """A fresh install pins to the left.

    **Test steps:**

    * Load from empty storage.
    * Assert the side is the default.
    """
    docks = DocksSettings()

    docks.load(settings)  # type: ignore[arg-type]

    assert docks.pin_side == DEFAULT_PIN_SIDE


@mark.parametrize("side", list(DockPinSide))
def test_each_side_round_trips(settings: FakeSettings, side: DockPinSide) -> None:
    """What was saved is what comes back, for every side the page can offer.

    **Test steps:**

    * Save a settings object holding ``side``.
    * Load a fresh one from the same storage.
    * Assert it holds ``side``.
    """
    saved = DocksSettings()
    saved.pin_side = side
    saved.save(settings)  # type: ignore[arg-type]

    loaded = DocksSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.pin_side == side


def test_the_stored_value_is_the_readable_word(settings: FakeSettings) -> None:
    """The ``.ini`` says "right", not QtAds' enum number -- the whole point of the `StrEnum`.

    **Test steps:**

    * Save a settings object holding the right-hand side.
    * Assert the stored value is that side's own word.
    """
    docks = DocksSettings()
    docks.pin_side = DockPinSide.RIGHT

    docks.save(settings)  # type: ignore[arg-type]

    assert settings.value(f"{GROUP}/{PIN_SIDE_KEY}") == "right"


def test_an_unrecognized_side_falls_back_to_the_default(settings: FakeSettings) -> None:
    """An ``.ini`` from a build offering a fifth side must not stop the window building its docks.

    **Test steps:**

    * Store a side name this build does not know.
    * Load it.
    * Assert the side is the default.
    """
    settings.beginGroup(GROUP)
    settings.setValue(PIN_SIDE_KEY, "diagonal")
    settings.endGroup()
    docks = DocksSettings()

    docks.load(settings)  # type: ignore[arg-type]

    assert docks.pin_side == DEFAULT_PIN_SIDE


def test_changing_the_side_notifies(settings: FakeSettings) -> None:
    """The window re-points its docks off this signal, which is why the object is reactive at all.

    **Test steps:**

    * Load a settings object and record its change notifications.
    * Set a different side.
    * Assert one notification arrived.
    """
    docks = DocksSettings()
    docks.load(settings)  # type: ignore[arg-type]
    seen: list[DockPinSide] = []
    docks.pin_side_changed.connect(lambda: seen.append(docks.pin_side))  # type: ignore[attr-defined]

    docks.pin_side = DockPinSide.BOTTOM

    assert seen == [DockPinSide.BOTTOM]


# endregion


# region the shared instance


def test_the_shared_instance_is_loaded_once(mocker: MockerFixture) -> None:
    """Every reader has to see the same object, or the settings page's Save would reach nobody.

    **Test steps:**

    * Point the module's storage at a stand-in holding a non-default side.
    * Ask for the shared instance twice.
    * Assert both calls return the same object, carrying the stored side.
    """
    settings = FakeSettings()
    settings.beginGroup(GROUP)
    settings.setValue(PIN_SIDE_KEY, DockPinSide.TOP.value)
    settings.endGroup()
    mocker.patch.object(docks_settings, "persistent_settings", return_value=settings)
    shared_docks_settings.cache_clear()

    first = shared_docks_settings()
    second = shared_docks_settings()

    assert first is second
    assert first.pin_side == DockPinSide.TOP


# endregion
