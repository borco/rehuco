"""Tests for QtAdsPinSideHandler: remembering which sidebar a dock was last pinned to."""

from collections.abc import Iterator
from typing import Any

import PySide6QtAds as QtAds
from borco_pyside.qtads.qtads_pin_side_handler import (
    DEFAULT_PIN_SIDE,
    PIN_SIDE_KEY,
    PIN_SIDE_NAMES,
    QtAdsPinSideHandler,
)
from PySide6.QtWidgets import QMainWindow, QWidget
from pytest import fixture
from pytestqt.qtbot import QtBot

GROUP = "dock_pin_sides/probe"
"""Settings group these tests hand their handler -- one per dock in real use."""


# region fixtures
# Mirrors the settings tests' own FakeSettings, minus the parts this one never calls -- kept as a
# separate copy rather than a shared import, matching this codebase's convention.
#
# unsupported-assignment-operation is a false positive from importing PySide6QtAds (which every test
# here needs for SideBarLocation): astroid then loses the plain dict annotation on __data and reads
# the subscript assignments below as unsupported. Confirmed by dropping that one import, which
# silences it -- so the disable is scoped to this class, and the tests seed storage through
# :meth:`seed` rather than subscripting from outside it.
# pylint: disable=duplicate-code
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin,unsupported-assignment-operation
    """A minimal in-memory stand-in for the ``QSettings`` group/value API, plus ``remove``.

    Method names and the ``type=`` parameter deliberately mirror ``QSettings``'s own C++-derived API,
    since :meth:`QtAdsPinSideHandler.load`/:meth:`~QtAdsPinSideHandler.save` call them by name.
    """

    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.__group = ""

    def seed(self, key: str, value: Any) -> None:
        """Put ``value`` at the ungrouped ``key``, as an earlier session would have left it."""
        self.data[key] = value

    def beginGroup(self, name: str) -> None:  # noqa: N802
        self.__group = f"{name}/"

    def endGroup(self) -> None:  # noqa: N802
        self.__group = ""

    def setValue(self, key: str, value: Any) -> None:  # noqa: N802
        self.data[self.__group + key] = value

    def remove(self, key: str) -> None:
        self.data.pop(self.__group + key, None)

    def value(self, key: str, default: Any = None, type: Any = None) -> Any:  # noqa: A002, N802
        del type
        return self.data.get(self.__group + key, default)


# pylint: enable=duplicate-code


@fixture(autouse=True)
def auto_hide_flags() -> Iterator[None]:
    """Turn QtAds' pinning on for the duration of one test, and put the flags back afterwards.

    The flags are a `CDockManager` **static**, shared by every manager in the process, so a test that
    left them on would decide the behaviour of every later test in the session.
    """
    previous = QtAds.CDockManager.autoHideConfigFlags()
    QtAds.CDockManager.setAutoHideConfigFlags(QtAds.CDockManager.eAutoHideFlag.DefaultAutoHideConfig)
    yield
    QtAds.CDockManager.setAutoHideConfigFlags(previous)


@fixture
def manager(qtbot: QtBot) -> Iterator[QtAds.CDockManager]:
    """A real `CDockManager` on a shown window, kept alive for the whole test.

    Shown because pinning builds real chrome; a generator fixture because ``qtbot.addWidget`` keeps
    only a weakref -- see ``test_qtads_widgets`` for the full reasoning.
    """
    window = QMainWindow()
    qtbot.addWidget(window)
    window.resize(800, 600)
    window.show()
    yield QtAds.CDockManager(window)


@fixture
def settings() -> FakeSettings:
    """In-memory storage for one test.

    :returns: the stand-in storage.
    """
    return FakeSettings()


def add_dock(manager: QtAds.CDockManager, name: str) -> QtAds.CDockWidget:
    """Build a real pinnable dock named ``name`` and add it to ``manager``.

    :param manager: the dock manager to add to.
    :param name: the dock's object name and initial title.
    :returns: the new dock.
    """
    dock = QtAds.CDockWidget(manager, name)
    dock.setObjectName(name)
    features = QtAds.CDockWidget.DockWidgetFeature
    dock.setFeatures(features.DockWidgetClosable | features.DockWidgetMovable | features.DockWidgetPinnable)
    dock.setWidget(QWidget())
    manager.addDockWidget(QtAds.CenterDockWidgetArea, dock)
    return dock


# endregion


# region the remembered side


def test_a_dock_starts_on_the_default_side(manager: QtAds.CDockManager) -> None:
    """Before anything is pinned, the default decides where the pin button sends the dock.

    **Test steps:**

    * build a handler over a fresh dock
    * assert the dock's preferred sidebar is the default, and it reads as never pinned
    """
    dock = add_dock(manager, "fresh")

    handler = QtAdsPinSideHandler(dock, GROUP)

    assert dock.preferredAutoHideSideBarLocation() == DEFAULT_PIN_SIDE
    assert handler.pinned is False
    assert handler.side == DEFAULT_PIN_SIDE


def test_pinning_to_a_named_side_is_remembered(manager: QtAds.CDockManager) -> None:
    """A dock dropped on one border pins back to that border, not to the default.

    The defect this class exists for: QtAds' drop path sets where the dock *is* and leaves the
    preferred side -- the only thing the pin button reads -- untouched.

    **Test steps:**

    * pin a handled dock into the right-hand sidebar by name
    * unpin it and pin it again the way the title-bar button does
    * assert it landed on the right both times
    """
    dock = add_dock(manager, "dropped")
    handler = QtAdsPinSideHandler(dock, GROUP)

    manager.addAutoHideDockWidget(QtAds.SideBarRight, dock)
    dock.setAutoHide(False)
    dock.setAutoHide(True)

    assert dock.autoHideLocation() == QtAds.SideBarRight
    assert handler.side == QtAds.SideBarRight
    assert handler.pinned is True


def test_moving_between_sidebars_is_remembered(manager: QtAds.CDockManager) -> None:
    """Dragging an already-pinned dock from one sidebar to another updates the memory too.

    A second pin with no unpin in between, which QtAds answers with a second container -- so the same
    signal carries it.

    **Test steps:**

    * pin a handled dock left, then straight over to the bottom
    * assert the remembered side followed to the bottom
    """
    dock = add_dock(manager, "moved")
    handler = QtAdsPinSideHandler(dock, GROUP)
    manager.addAutoHideDockWidget(QtAds.SideBarLeft, dock)

    manager.addAutoHideDockWidget(QtAds.SideBarBottom, dock)

    assert handler.side == QtAds.SideBarBottom


def test_another_docks_pin_is_ignored(manager: QtAds.CDockManager) -> None:
    """Every handler on a manager sees every pin, so each must answer only for its own dock.

    **Test steps:**

    * build a handler over one dock and pin a *different* dock to the right
    * assert the handled dock is untouched and still reads as never pinned
    """
    handled = add_dock(manager, "handled")
    other = add_dock(manager, "other")
    handler = QtAdsPinSideHandler(handled, GROUP)

    manager.addAutoHideDockWidget(QtAds.SideBarRight, other)

    assert handler.side == DEFAULT_PIN_SIDE
    assert handler.pinned is False


# endregion


# region persistence


def test_the_side_round_trips(manager: QtAds.CDockManager, settings: FakeSettings) -> None:
    """What one session saved is what the next session's handler applies.

    Two docks rather than one reused: a restart builds the dock afresh, and what has to survive is the
    stored word, not any state left on the object that wrote it.

    **Test steps:**

    * pin one handled dock to the top and save
    * build a second handler, over a second dock, against the same storage and load
    * assert the second dock's preferred sidebar is the top
    """
    saved_dock = add_dock(manager, "saved")
    saved = QtAdsPinSideHandler(saved_dock, GROUP)
    manager.addAutoHideDockWidget(QtAds.SideBarTop, saved_dock)
    saved.save(settings)  # type: ignore[arg-type]

    loaded = QtAdsPinSideHandler(add_dock(manager, "loaded"), GROUP)
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.side == QtAds.SideBarTop
    assert loaded.pinned is True


def test_the_stored_value_is_the_readable_word(manager: QtAds.CDockManager, settings: FakeSettings) -> None:
    """The ``.ini`` says "right", not QtAds' enum number -- the point of :data:`PIN_SIDE_NAMES`.

    **Test steps:**

    * pin a handled dock to the right and save
    * assert the stored value is that side's own word
    """
    dock = add_dock(manager, "worded")
    handler = QtAdsPinSideHandler(dock, GROUP)
    manager.addAutoHideDockWidget(QtAds.SideBarRight, dock)

    handler.save(settings)  # type: ignore[arg-type]

    assert settings.data[f"{GROUP}/{PIN_SIDE_KEY}"] == PIN_SIDE_NAMES[QtAds.SideBarRight]


def test_a_dock_nobody_pinned_writes_no_key(manager: QtAds.CDockManager, settings: FakeSettings) -> None:
    """Never pinned means nothing stored -- not today's default written as though it were a choice.

    What keeps :data:`DEFAULT_PIN_SIDE` the authority for such a dock: a later change to that constant
    must move it, rather than being overruled by a side an earlier build wrote on its behalf.

    **Test steps:**

    * save a handler whose dock has never been pinned, over storage holding a stale side
    * assert the key is gone rather than rewritten
    """
    settings.seed(f"{GROUP}/{PIN_SIDE_KEY}", "bottom")
    handler = QtAdsPinSideHandler(add_dock(manager, "untouched"), GROUP)

    handler.save(settings)  # type: ignore[arg-type]

    assert f"{GROUP}/{PIN_SIDE_KEY}" not in settings.data


def test_nothing_stored_leaves_the_default(manager: QtAds.CDockManager, settings: FakeSettings) -> None:
    """A first run, and every dock in it, loads onto the default.

    **Test steps:**

    * load a handler from empty storage
    * assert its dock is on the default side and still reads as never pinned
    """
    handler = QtAdsPinSideHandler(add_dock(manager, "first_run"), GROUP)

    handler.load(settings)  # type: ignore[arg-type]

    assert handler.side == DEFAULT_PIN_SIDE
    assert handler.pinned is False


def test_an_unrecognized_stored_side_falls_back_to_the_default(
    manager: QtAds.CDockManager, settings: FakeSettings
) -> None:
    """An ``.ini`` naming a sidebar this build has no idea about must not strand the dock.

    **Test steps:**

    * store a side name this build does not know, and load
    * assert the dock is on the default side and reads as never pinned
    """
    settings.seed(f"{GROUP}/{PIN_SIDE_KEY}", "diagonal")
    handler = QtAdsPinSideHandler(add_dock(manager, "strange"), GROUP)

    handler.load(settings)  # type: ignore[arg-type]

    assert handler.side == DEFAULT_PIN_SIDE
    assert handler.pinned is False


# endregion
