"""Tests for QtAdsPinGuard: a pin QtAds makes against a manager's will is undone as it happens."""

from collections.abc import Iterator
from typing import Final

import PySide6QtAds as QtAds
from borco_pyside.qtads import QtAdsPinGuard
from PySide6.QtWidgets import QLabel, QMainWindow
from pytest import fixture
from pytestqt.qtbot import QtBot

CENTER: Final = QtAds.CenterDockWidgetArea
LEFT: Final = QtAds.SideBarLeft


# region fixtures and helpers
@fixture(autouse=True)
def auto_hide_flags() -> Iterator[None]:
    """Turn QtAds' pinning on for one test, and put the process-wide flags back afterwards -- the reason
    ``test_qtads_auto_hide_button_suppressor.py`` gives."""
    previous = QtAds.CDockManager.autoHideConfigFlags()
    QtAds.CDockManager.setAutoHideConfigFlags(QtAds.CDockManager.eAutoHideFlag.DefaultAutoHideConfig)
    yield
    QtAds.CDockManager.setAutoHideConfigFlags(previous)


def make_window(qtbot: QtBot) -> QMainWindow:
    """A shown window for a manager to sit on -- a sidebar pin needs a laid-out container.

    :param qtbot: the test's bot, which closes the window at teardown.
    :returns: the window.
    """
    window = QMainWindow()
    window.resize(1000, 800)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    return window


def add_dock(manager: QtAds.CDockManager, name: str) -> QtAds.CDockWidget:
    """Add a dock named ``name`` to ``manager``'s main container.

    :param manager: the manager.
    :param name: the dock's title and object name.
    :returns: the dock.
    """
    dock = QtAds.CDockWidget(manager, name)
    dock.setObjectName(name)
    dock.setWidget(QLabel(name))
    manager.addDockWidget(CENTER, dock)
    return dock


type Nested = tuple[QtAds.CDockManager, QtAds.CDockWidget, QtAds.CDockManager, QtAds.CDockWidget]
"""The outer manager, the host dock, the nested manager and its dock."""


@fixture
def nested(qtbot: QtBot) -> Iterator[Nested]:
    """An outer manager that pins, with a host dock holding a nested manager that never pins -- each guarded, as
    the app guards its own -- and one dock in the nested manager.

    A generator fixture so the window, which owns both managers, stays alive for the whole test.

    :param qtbot: the test's bot.
    :returns: the outer manager, the host dock, the nested manager and its dock.
    """
    window = make_window(qtbot)
    outer = QtAds.CDockManager(window)
    QtAdsPinGuard(outer)
    host = QtAds.CDockWidget(outer, "Host")
    host.setObjectName("Host")
    inner = QtAds.CDockManager(host)
    host.setWidget(inner)
    outer.addDockWidget(CENTER, host)
    QtAdsPinGuard(inner, pins=False)
    sub = add_dock(inner, "Sub")
    qtbot.wait(10)
    yield outer, host, inner, sub
    del window


def is_home(dock: QtAds.CDockWidget, manager: QtAds.CDockManager) -> bool:
    """Whether ``dock`` sits unpinned in ``manager``'s own container, owned by it.

    :param dock: the dock.
    :param manager: its manager.
    :returns: whether it is home.
    """
    area = dock.dockAreaWidget()
    return (
        not dock.isAutoHide() and dock.dockManager() is manager and area is not None and area.dockContainer() is manager
    )


# endregion


# region QtAdsPinGuard tests
def test_a_nested_dock_stolen_into_an_outer_sidebar_is_sent_home(nested: Nested, qtbot: QtBot) -> None:
    """A dock QtAds pins into an outer manager's sidebar -- the recursive sidebar drop
    ([[appendices.qt-ads#recursive-sidebar-drop]]) -- goes back to the nested manager that registered it, a turn
    later rather than inside QtAds' drop.

    **Test steps:**

    * pin the nested manager's dock into the outer sidebar, as the drop does
    * verify it is still pinned there right away
    * verify it ends unpinned in the nested manager's container, owned by it
    """
    outer, _, inner, sub = nested

    outer.createAndSetupAutoHideContainer(LEFT, sub, -1)

    assert sub.isAutoHide()
    assert sub.dockManager() is outer
    qtbot.waitUntil(lambda: is_home(sub, inner))


def test_a_manager_that_pins_keeps_a_pin_of_its_own(nested: Nested, qtbot: QtBot) -> None:
    """The outer manager's own docks pin as usual: only a dock it never registered is sent away.

    **Test steps:**

    * pin the host dock into the outer sidebar
    * verify it is still pinned there a while later
    """
    outer, host, _, _ = nested

    host.setAutoHide(True, LEFT)
    qtbot.wait(10)

    assert host.isAutoHide()
    assert host.dockManager() is outer


def test_a_manager_that_never_pins_unpins_its_own_dock(nested: Nested, qtbot: QtBot) -> None:
    """A pin into a manager that never pins -- a drop onto one of its borders, which neither its hidden pin button
    nor ``DockWidgetPinnable`` stops -- is undone, so the manager never grows a sidebar.

    **Test steps:**

    * pin the nested manager's dock into its own sidebar
    * verify it ends unpinned in that manager's container
    """
    _, _, inner, sub = nested

    sub.setAutoHide(True, LEFT)

    assert sub.isAutoHide()
    qtbot.waitUntil(lambda: is_home(sub, inner))


def test_a_dock_unpinned_before_the_guard_runs_is_left_where_it_is(nested: Nested, qtbot: QtBot) -> None:
    """The deferred unpin checks the dock first: one something else already unpinned is not touched.

    **Test steps:**

    * pin the nested manager's dock into its own sidebar, and unpin it at once
    * verify it is still home after the guard's turn
    """
    _, _, inner, sub = nested

    sub.setAutoHide(True, LEFT)
    sub.setAutoHide(False)
    qtbot.wait(10)

    assert is_home(sub, inner)


def test_a_stolen_dock_unpinned_before_the_guard_runs_still_goes_home(nested: Nested, qtbot: QtBot) -> None:
    """A stolen dock someone unpins before the guard's turn lands in the outer container -- and is still sent
    home from there.

    **Test steps:**

    * pin the nested manager's dock into the outer sidebar, and unpin it at once
    * verify it ends in the nested manager's container, owned by it
    """
    outer, _, inner, sub = nested

    outer.createAndSetupAutoHideContainer(LEFT, sub, -1)
    sub.setAutoHide(False)

    qtbot.waitUntil(lambda: is_home(sub, inner))


def test_a_foreign_dock_with_no_home_below_the_manager_stays_pinned(qtbot: QtBot) -> None:
    """A dock whose registering manager is not among this manager's descendants has no home to go to; unpinning
    it would only move it into this manager's container, so it is left pinned.

    **Test steps:**

    * pin a dock of one window's manager into another window's manager's sidebar
    * verify it is still pinned there a while later
    """
    # both windows held: each owns its manager, and an unheld one is destroyed with its Python wrapper
    guarded_window = make_window(qtbot)
    stranger_window = make_window(qtbot)
    guarded = QtAds.CDockManager(guarded_window)
    QtAdsPinGuard(guarded)
    add_dock(guarded, "Own")
    stranger = add_dock(QtAds.CDockManager(stranger_window), "Stranger")
    qtbot.wait(10)

    guarded.createAndSetupAutoHideContainer(LEFT, stranger, -1)
    qtbot.wait(10)

    assert stranger.isAutoHide()
    assert stranger.dockManager() is guarded


# endregion
