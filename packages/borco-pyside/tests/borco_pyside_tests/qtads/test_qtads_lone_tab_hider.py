"""Tests for QtAdsLoneTabHider: a dock with title-bar actions floated alone shows no tab, keeps its title bar and
buttons, and has its tab back once it is not alone.
"""

from collections.abc import Iterator
from typing import NamedTuple

import PySide6QtAds as QtAds
from borco_pyside.qtads import QtAdsLoneTabHider
from borco_pyside.qtads.qtads_lone_tab_hider import LoneTabWatcher
from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QAbstractButton, QLabel, QMainWindow
from pytest import fixture
from pytestqt.qtbot import QtBot

WAIT = 10_000
"""How long a ``waitUntil`` here is given: the hider decides a turn of the event loop later, and the first wait
in a Qt test can spend seconds draining earlier tests' deferred deletes."""


class Shell(NamedTuple):
    """A manager with the hider, a Documents dock, and a Root Catalog dock with a Refresh action tabbed beside it."""

    manager: QtAds.CDockManager
    documents: QtAds.CDockWidget
    roots: QtAds.CDockWidget
    refresh: QAction


def make_dock(manager: QtAds.CDockManager, name: str) -> QtAds.CDockWidget:
    """A dock named ``name``, not yet placed.

    :param manager: the manager it belongs to.
    :param name: its object name and title.
    :returns: the dock.
    """
    dock = QtAds.CDockWidget(manager, name)
    dock.setObjectName(name)
    dock.setWidget(QLabel(name))
    return dock


def area_of(dock: QtAds.CDockWidget) -> QtAds.CDockAreaWidget:
    """The area ``dock`` is in, which a placed dock always has.

    :param dock: a placed dock.
    :returns: its area.
    """
    area = dock.dockAreaWidget()
    assert area is not None
    return area


def tab_shown(dock: QtAds.CDockWidget) -> bool:
    """Whether ``dock``'s own tab is shown.

    :param dock: a placed dock.
    :returns: whether its tab is not hidden.
    """
    return not dock.tabWidget().isHidden()


def button_shown(dock: QtAds.CDockWidget, action: QAction) -> bool:
    """Whether ``dock``'s area title bar is shown with a button for ``action``.

    :param dock: a placed dock.
    :param action: one of its title-bar actions.
    :returns: whether the bar is shown and a button carrying it is visible in it.
    """
    title_bar = area_of(dock).titleBar()
    return not title_bar.isHidden() and any(
        action in button.actions() and button.isVisibleTo(title_bar)
        for button in title_bar.findChildren(QAbstractButton)
    )


def watcher_of(dock: QtAds.CDockWidget) -> LoneTabWatcher:
    """The one watcher the hider gave ``dock``.

    :param dock: a dock of a manager with a hider.
    :returns: its watcher.
    """
    watchers = dock.findChildren(LoneTabWatcher)
    assert len(watchers) == 1
    return watchers[0]


def redecide(qtbot: QtBot, dock: QtAds.CDockWidget) -> None:
    """Make ``dock``'s watcher decide again, as a reparenting would, and let the decision run.

    :param qtbot: the bot to wait with.
    :param dock: the dock.
    """
    watcher_of(dock).eventFilter(dock, QEvent(QEvent.Type.ParentChange))
    qtbot.wait(20)


@fixture(name="shell")
def fixture_shell(qtbot: QtBot) -> Iterator[Shell]:
    """A shown window with the hider on its manager, whose Root Catalog dock carries a Refresh action, tabbed
    beside Documents and current.

    A generator fixture so the window lives for the whole test: ``qtbot.addWidget`` keeps only a weakref.
    """
    window = QMainWindow()
    qtbot.addWidget(window)
    window.resize(800, 600)
    window.show()
    manager = QtAds.CDockManager(window)
    QtAdsLoneTabHider(manager)
    documents = make_dock(manager, "Documents")
    manager.addDockWidget(QtAds.CenterDockWidgetArea, documents)
    roots = make_dock(manager, "Root Catalog")
    refresh = QAction("Refresh", window)
    roots.setTitleBarActions([refresh])
    manager.addDockWidget(QtAds.CenterDockWidgetArea, roots, area_of(documents))
    area_of(roots).setCurrentDockWidget(roots)
    yield Shell(manager, documents, roots, refresh)


def test_a_docked_dock_shows_its_tab(shell: Shell) -> None:
    """Docked in the main window, the dock shows its tab and its buttons.

    **Test steps:**

    * build the shell (the dock tabbed beside Documents, current)
    * verify its tab and its Refresh button are shown
    """
    assert tab_shown(shell.roots)
    assert button_shown(shell.roots, shell.refresh)


def test_floated_alone_the_dock_hides_its_tab_and_keeps_its_buttons(qtbot: QtBot, shell: Shell) -> None:
    """Alone in a floating window, the dock's tab is hidden while its title bar and buttons stay.

    **Test steps:**

    * float the dock on its own
    * verify its tab is hidden and its Refresh button still shown
    """
    shell.roots.setFloating()

    qtbot.waitUntil(lambda: not tab_shown(shell.roots), timeout=WAIT)
    assert shell.roots.isFloating()
    assert button_shown(shell.roots, shell.refresh)


def test_joined_by_another_dock_the_tab_comes_back(qtbot: QtBot, shell: Shell) -> None:
    """A second dock tabbed into the floating window brings the dock's tab back; taken out again, it goes.

    **Test steps:**

    * float the dock alone, then tab Documents into its window
    * verify both tabs are shown
    * float Documents out again
    * verify the dock, alone again, hides its tab
    """
    shell.roots.setFloating()
    qtbot.waitUntil(lambda: not tab_shown(shell.roots), timeout=WAIT)

    shell.manager.addDockWidgetTabToArea(shell.documents, area_of(shell.roots))
    qtbot.waitUntil(lambda: tab_shown(shell.roots), timeout=WAIT)
    assert tab_shown(shell.documents)

    shell.documents.setFloating()
    qtbot.waitUntil(lambda: not tab_shown(shell.roots), timeout=WAIT)


def test_docked_back_the_tab_comes_back(qtbot: QtBot, shell: Shell) -> None:
    """Re-docked into the main window, the dock shows its tab and its buttons again.

    **Test steps:**

    * float the dock alone, then tab it back beside Documents and make it current
    * verify its tab and its Refresh button are shown
    """
    shell.roots.setFloating()
    qtbot.waitUntil(lambda: not tab_shown(shell.roots), timeout=WAIT)

    shell.manager.addDockWidgetTabToArea(shell.roots, area_of(shell.documents))
    area_of(shell.roots).setCurrentDockWidget(shell.roots)

    qtbot.waitUntil(lambda: tab_shown(shell.roots), timeout=WAIT)
    assert not shell.roots.isFloating()
    # QtAds rebuilds the bar's action buttons a moment after the tab is back
    qtbot.waitUntil(lambda: button_shown(shell.roots, shell.refresh), timeout=WAIT)


def test_a_dock_without_actions_keeps_its_tab(qtbot: QtBot, shell: Shell) -> None:
    """A dock with no title-bar actions is left to QtAds, which hides its whole title bar when it floats alone.

    **Test steps:**

    * float Documents, which has no actions, on its own
    * verify its tab is not hidden by the hider, the bar being hidden as a whole
    """
    shell.documents.setFloating()
    redecide(qtbot, shell.documents)

    assert shell.documents.isFloating()
    assert tab_shown(shell.documents)
    assert area_of(shell.documents).titleBar().isHidden()


def test_a_dock_added_later_is_watched(qtbot: QtBot, shell: Shell) -> None:
    """A dock the manager adds after the hider was built is watched like the rest.

    **Test steps:**

    * add a third dock with an action, then float it alone
    * verify its tab is hidden
    """
    log = make_dock(shell.manager, "Log")
    log.setTitleBarActions([QAction("Clear", log)])
    shell.manager.addDockWidget(QtAds.CenterDockWidgetArea, log, area_of(shell.documents))

    log.setFloating()

    qtbot.waitUntil(lambda: not tab_shown(log), timeout=WAIT)


def test_docks_there_before_the_hider_are_watched(qtbot: QtBot) -> None:
    """A hider built after the docks watches those too.

    **Test steps:**

    * build a manager with a dock that has an action, then the hider
    * verify the dock has a watcher, and floating it alone hides its tab
    """
    window = QMainWindow()
    qtbot.addWidget(window)
    window.resize(800, 600)
    window.show()
    manager = QtAds.CDockManager(window)
    documents = make_dock(manager, "Documents")
    manager.addDockWidget(QtAds.CenterDockWidgetArea, documents)
    roots = make_dock(manager, "Root Catalog")
    roots.setTitleBarActions([QAction("Refresh", window)])
    manager.addDockWidget(QtAds.CenterDockWidgetArea, roots, area_of(documents))

    QtAdsLoneTabHider(manager)
    watcher_of(roots)
    roots.setFloating()

    qtbot.waitUntil(lambda: not tab_shown(roots), timeout=WAIT)


def test_a_dock_added_back_is_not_watched_twice(shell: Shell) -> None:
    """A dock taken out of the manager and added back keeps its one watcher.

    **Test steps:**

    * remove the dock and add it back
    * verify it has exactly one watcher
    """
    shell.manager.removeDockWidget(shell.roots)
    shell.manager.addDockWidget(QtAds.CenterDockWidgetArea, shell.roots, area_of(shell.documents))

    watcher_of(shell.roots)


def test_a_tab_hidden_by_someone_else_is_not_claimed(qtbot: QtBot) -> None:
    """A tab already hidden by another party when the hider first decides is never shown by it.

    Proved with the tab hidden before the hider is built, since QtAds shows a dock's tab itself on every move
    into an area -- a float included -- and another dock joining the window is the one path that leaves it alone.

    **Test steps:**

    * float a dock with an action alone and hide its tab from outside, then build the hider and let it decide
    * tab Documents into the window and let it decide again
    * verify the tab stays hidden throughout
    """
    window = QMainWindow()
    qtbot.addWidget(window)
    window.resize(800, 600)
    window.show()
    manager = QtAds.CDockManager(window)
    documents = make_dock(manager, "Documents")
    manager.addDockWidget(QtAds.CenterDockWidgetArea, documents)
    roots = make_dock(manager, "Root Catalog")
    roots.setTitleBarActions([QAction("Refresh", window)])
    manager.addDockWidget(QtAds.CenterDockWidgetArea, roots, area_of(documents))
    roots.setFloating()
    roots.tabWidget().setVisible(False)

    QtAdsLoneTabHider(manager)
    redecide(qtbot, roots)
    assert not tab_shown(roots)

    manager.addDockWidgetTabToArea(documents, area_of(roots))
    redecide(qtbot, roots)

    assert tab_shown(documents)
    assert not tab_shown(roots)


def test_a_closed_dock_does_not_get_its_tab_back(qtbot: QtBot, shell: Shell) -> None:
    """A dock closed after its tab was hidden is not given it back: QtAds hides a closed dock's tab itself.

    **Test steps:**

    * float the dock alone, tab Documents into its window, then close the dock and make the watcher re-decide
    * verify its tab is hidden
    """
    shell.roots.setFloating()
    qtbot.waitUntil(lambda: not tab_shown(shell.roots), timeout=WAIT)
    shell.manager.addDockWidgetTabToArea(shell.documents, area_of(shell.roots))
    shell.roots.toggleView(False)
    redecide(qtbot, shell.roots)

    assert shell.roots.isClosed()
    assert not tab_shown(shell.roots)


def test_only_the_docks_own_reparenting_redecides(qtbot: QtBot, shell: Shell) -> None:
    """The filter re-decides on the dock's own reparenting and nothing else, and never swallows the event.

    **Test steps:**

    * float the dock alone, then show its tab behind the watcher's back
    * send a reparenting event of another object through the filter
    * verify the tab is left shown
    * send one of the dock's own
    * verify the tab is hidden again, and neither event was swallowed
    """
    shell.roots.setFloating()
    qtbot.waitUntil(lambda: not tab_shown(shell.roots), timeout=WAIT)
    shell.roots.tabWidget().setVisible(True)
    reparented = QEvent(QEvent.Type.ParentChange)

    assert watcher_of(shell.roots).eventFilter(QObject(), reparented) is False
    qtbot.wait(20)
    assert tab_shown(shell.roots)

    assert watcher_of(shell.roots).eventFilter(shell.roots, reparented) is False
    qtbot.waitUntil(lambda: not tab_shown(shell.roots), timeout=WAIT)
