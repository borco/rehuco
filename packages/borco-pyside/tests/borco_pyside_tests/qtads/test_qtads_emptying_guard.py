"""Tests for QtAdsEmptyingGuard: a nested manager emptied under a floating window leaves that window alone."""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Final

import PySide6QtAds as QtAds
import shiboken6
from borco_pyside.qtads import QtAdsEmptyingGuard
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QLabel, QMainWindow
from pytest import fixture
from pytestqt.qtbot import QtBot

CENTER: Final = QtAds.CenterDockWidgetArea
BOTTOM: Final = QtAds.BottomDockWidgetArea


# region fixtures and helpers
@dataclass
class Nest:
    """An outer manager whose floating window holds a sibling dock above a host dock, the host holding a nested
    manager with two docks of its own -- the reported layout of #493."""

    outer: QtAds.CDockManager
    sibling: QtAds.CDockWidget
    host: QtAds.CDockWidget
    inner: QtAds.CDockManager
    subs: list[QtAds.CDockWidget]


def add_dock(manager: QtAds.CDockManager, name: str, area: QtAds.CDockAreaWidget | None = None) -> QtAds.CDockWidget:
    """Add a dock named ``name`` to ``manager``, tabbed into ``area`` if given.

    :param manager: the manager.
    :param name: the dock's title and object name.
    :param area: the area to join.
    :returns: the dock.
    """
    dock = QtAds.CDockWidget(manager, name)
    dock.setObjectName(name)
    dock.setWidget(QLabel(name))
    manager.addDockWidget(CENTER, dock, area)
    return dock


def build_nest(qtbot: QtBot, *, floating: bool, guarded: bool = True) -> tuple[QMainWindow, Nest]:
    """Build a shown window and the nest on it.

    :param qtbot: the test's bot, which closes the window at teardown.
    :param floating: whether sibling and host go into a floating window.
    :param guarded: whether the nested manager gets its guard.
    :returns: the window, held by the caller so the managers live, and the nest.
    """
    main = QMainWindow()
    main.resize(900, 700)
    qtbot.addWidget(main)
    outer = QtAds.CDockManager(main)
    sibling = add_dock(outer, "Sibling")
    host = QtAds.CDockWidget(outer, "Host")
    host.setObjectName("Host")
    inner = QtAds.CDockManager(host)
    host.setWidget(inner)
    if guarded:
        QtAdsEmptyingGuard(inner)
    main.show()
    qtbot.waitExposed(main)
    if floating:
        outer.addDockWidgetFloating(sibling)
    outer.addDockWidget(BOTTOM, host, sibling.dockAreaWidget())
    subs = [add_dock(inner, name) for name in ("A", "B")]
    return main, Nest(outer, sibling, host, inner, subs)


@fixture
def nest(qtbot: QtBot) -> Iterator[Nest]:
    """A guarded nest in a floating window, held for the whole test.

    :param qtbot: the test's bot.
    :returns: the nest.
    """
    main, built = build_nest(qtbot, floating=True)
    yield built
    del main


def remove(manager: QtAds.CDockManager, dock: QtAds.CDockWidget) -> None:
    """Remove ``dock`` from ``manager`` and schedule its deletion, as the app does.

    :param manager: the manager.
    :param dock: the dock.
    """
    manager.removeDockWidget(dock)
    dock.deleteLater()


def settle() -> None:
    """Let every pending deletion run -- a window QtAds retired is gone after this."""
    QCoreApplication.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


def nest_alive(built: Nest) -> bool:
    """Whether both outer docks still exist, in one floating window that is on screen.

    The window is looked up afresh rather than held: a wrapper kept from ``addDockWidgetFloating`` was measured to
    go invalid while the window lives on -- PySide's wrappers of Qt-made objects, as in
    [[appendices.qt-ads#structural-layout]].

    :param built: the nest.
    :returns: whether nothing was deleted.
    """
    if not (shiboken6.isValid(built.sibling) and shiboken6.isValid(built.host)):
        return False
    window = built.sibling.floatingDockContainer()
    return window is not None and window.isVisible() and built.host.floatingDockContainer() is window


# endregion


# region QtAdsEmptyingGuard tests
def test_emptying_a_nested_manager_keeps_the_floating_window_above_it(nest: Nest) -> None:
    """Removing the nested manager's last dock leaves the outer floating window, its sibling dock and the host --
    the window QtAds would otherwise retire as the nested container's own ([[appendices.qt-ads#nested-emptied-float]]).

    **Test steps:**

    * remove both of the nested manager's docks
    * verify the window, the sibling and the host survive the pending deletions, still showing
    * verify the nested manager keeps one area and registers no dock -- the ballast is never in its registry
    """
    for dock in nest.subs:
        remove(nest.inner, dock)
    settle()

    assert nest_alive(nest)
    assert nest.inner.dockAreaCount() == 1
    assert not nest.inner.dockWidgetsMap()


def test_without_the_guard_the_floating_window_is_deleted(qtbot: QtBot) -> None:
    """The defect the guard stands against, kept as a canary: should a QtAds update stop retiring the outer
    window, this fails and the guard can go.

    **Test steps:**

    * build the same nest without a guard and remove both nested docks
    * verify both docks in the floating window are gone with it
    """
    main, built = build_nest(qtbot, floating=True, guarded=False)

    for dock in built.subs:
        remove(built.inner, dock)
    settle()

    assert not shiboken6.isValid(built.sibling)
    assert not shiboken6.isValid(built.host)
    del main


def test_a_dock_added_after_emptying_unparks_the_ballast(nest: Nest) -> None:
    """The next dock the nested manager gets takes the ballast's place: one area, holding only that dock, on
    screen.

    **Test steps:**

    * empty the nested manager, then add a dock
    * verify the manager has one area, holding just the new dock, visible
    """
    for dock in nest.subs:
        remove(nest.inner, dock)
    added = add_dock(nest.inner, "C")
    settle()

    area = added.dockAreaWidget()
    assert nest.inner.dockAreaCount() == 1
    assert area is not None and area.dockWidgets() == [added]
    assert area.isVisible()
    assert nest_alive(nest)


def test_a_dock_tabbed_into_the_ballasts_area_keeps_it(nest: Nest) -> None:
    """A dock placed into the area the ballast holds -- the first area a layout restore finds -- stays there when
    the ballast leaves, open and on screen.

    **Test steps:**

    * empty the nested manager and add a dock into its one remaining area
    * verify that area holds just the new dock, visible
    """
    for dock in nest.subs:
        remove(nest.inner, dock)
    (ballast_area,) = nest.inner.findChildren(QtAds.CDockAreaWidget)
    added = add_dock(nest.inner, "C", ballast_area)
    settle()

    assert added.dockAreaWidget() is ballast_area
    assert ballast_area.dockWidgets() == [added]
    assert ballast_area.isVisible()


def test_a_manager_emptied_twice_parks_one_ballast_at_a_time(nest: Nest) -> None:
    """Emptying, refilling and emptying again parks a fresh ballast each time, never two.

    **Test steps:**

    * empty the nested manager, add a dock, then remove it
    * verify the window survives and the manager holds one area
    """
    for dock in nest.subs:
        remove(nest.inner, dock)
    added = add_dock(nest.inner, "C")
    remove(nest.inner, added)
    settle()

    assert nest_alive(nest)
    assert nest.inner.dockAreaCount() == 1


def test_a_removal_that_leaves_a_dock_parks_nothing(nest: Nest) -> None:
    """Only the last dock's removal parks: with a dock left, the manager keeps its own area.

    **Test steps:**

    * remove one of the two nested docks
    * verify the other one's area is the manager's only area
    """
    first, second = nest.subs

    remove(nest.inner, first)
    settle()

    assert nest.inner.dockAreaCount() == 1
    assert nest.inner.findChildren(QtAds.CDockAreaWidget) == [second.dockAreaWidget()]


def test_a_docked_nest_parks_nothing(qtbot: QtBot) -> None:
    """With no floating window above it, an emptied nested manager is left empty, as QtAds leaves it -- there is no
    window to lose.

    **Test steps:**

    * build the nest docked in the main window and remove both nested docks
    * verify the manager holds no area, and the host survives
    """
    main, built = build_nest(qtbot, floating=False)

    for dock in built.subs:
        remove(built.inner, dock)
    settle()

    assert built.inner.dockAreaCount() == 0
    assert shiboken6.isValid(built.host)
    del main


# endregion
