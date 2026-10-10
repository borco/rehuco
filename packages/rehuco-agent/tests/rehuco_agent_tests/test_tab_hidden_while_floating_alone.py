"""Tests for TabHiddenWhileFloatingAlone: a dock with title-bar actions floated alone shows no tab, keeps its
title bar and buttons, and has its tab back once it is not alone (#488)."""

from collections.abc import Iterator
from typing import NamedTuple

import PySide6QtAds as QtAds
from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QAbstractButton, QLabel, QMainWindow
from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.main_window import TabHiddenWhileFloatingAlone


class Shell(NamedTuple):
    """A manager with a Documents dock, a Root Catalog dock tabbed beside it, and the one handled."""

    manager: QtAds.CDockManager
    documents: QtAds.CDockWidget
    roots: QtAds.CDockWidget
    refresh: QAction
    handler: TabHiddenWhileFloatingAlone


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


def settle(qtbot: QtBot) -> None:
    """Let the handler's decision run: it is queued for the next turn of the event loop."""
    qtbot.wait(20)


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


@fixture(name="shell")
def fixture_shell(qtbot: QtBot) -> Iterator[Shell]:
    """A shown window whose Root Catalog dock carries a Refresh action and the handler, tabbed beside Documents
    and current.

    A generator fixture so the window lives for the whole test: ``qtbot.addWidget`` keeps only a weakref.
    """
    window = QMainWindow()
    qtbot.addWidget(window)
    window.resize(800, 600)
    window.show()
    manager = QtAds.CDockManager(window)
    documents = make_dock(manager, "Documents")
    manager.addDockWidget(QtAds.CenterDockWidgetArea, documents)
    roots = make_dock(manager, "Root Catalog")
    refresh = QAction("Refresh", window)
    roots.setTitleBarActions([refresh])
    handler = TabHiddenWhileFloatingAlone(roots)
    manager.addDockWidget(QtAds.CenterDockWidgetArea, roots, area_of(documents))
    area_of(roots).setCurrentDockWidget(roots)
    settle(qtbot)
    yield Shell(manager, documents, roots, refresh, handler)


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
    settle(qtbot)

    assert shell.roots.isFloating()
    assert not tab_shown(shell.roots)
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
    settle(qtbot)

    shell.manager.addDockWidgetTabToArea(shell.documents, area_of(shell.roots))
    settle(qtbot)
    assert tab_shown(shell.roots)
    assert tab_shown(shell.documents)

    shell.documents.setFloating()
    settle(qtbot)
    assert not tab_shown(shell.roots)


def test_docked_back_the_tab_comes_back(qtbot: QtBot, shell: Shell) -> None:
    """Re-docked into the main window, the dock shows its tab and its buttons again.

    **Test steps:**

    * float the dock alone, then tab it back beside Documents and make it current
    * verify its tab and its Refresh button are shown
    """
    shell.roots.setFloating()
    settle(qtbot)

    shell.manager.addDockWidgetTabToArea(shell.roots, area_of(shell.documents))
    area_of(shell.roots).setCurrentDockWidget(shell.roots)
    settle(qtbot)

    assert not shell.roots.isFloating()
    assert tab_shown(shell.roots)
    assert button_shown(shell.roots, shell.refresh)


def test_a_tab_hidden_by_someone_else_stays_hidden(qtbot: QtBot, shell: Shell) -> None:
    """A tab the handler did not hide is never shown by it -- as a maximize hides its neighbours' tabs.

    **Test steps:**

    * hide the docked dock's tab from outside, then make the handler re-decide
    * verify the tab stays hidden
    """
    shell.roots.tabWidget().setVisible(False)
    shell.handler.eventFilter(shell.roots, QEvent(QEvent.Type.ParentChange))
    settle(qtbot)

    assert not tab_shown(shell.roots)


def test_a_closed_dock_does_not_get_its_tab_back(qtbot: QtBot, shell: Shell) -> None:
    """A dock closed after its tab was hidden is not given it back: QtAds hides a closed dock's tab itself.

    **Test steps:**

    * float the dock alone, tab Documents into its window, then close the dock and make the handler re-decide
    * verify its tab is hidden
    """
    shell.roots.setFloating()
    settle(qtbot)
    shell.manager.addDockWidgetTabToArea(shell.documents, area_of(shell.roots))
    shell.roots.toggleView(False)
    shell.handler.eventFilter(shell.roots, QEvent(QEvent.Type.ParentChange))
    settle(qtbot)

    assert shell.roots.isClosed()
    assert not tab_shown(shell.roots)


def test_only_the_docks_own_reparenting_redecides(qtbot: QtBot, shell: Shell) -> None:
    """The filter re-decides on the dock's own reparenting and nothing else, and never swallows the event.

    **Test steps:**

    * float the dock alone, then show its tab behind the handler's back
    * send a reparenting event of another object through the filter
    * verify the tab is left shown
    * send one of the dock's own
    * verify the tab is hidden again, and neither event was swallowed
    """
    shell.roots.setFloating()
    settle(qtbot)
    shell.roots.tabWidget().setVisible(True)
    reparented = QEvent(QEvent.Type.ParentChange)

    assert shell.handler.eventFilter(QObject(), reparented) is False
    settle(qtbot)
    assert tab_shown(shell.roots)

    assert shell.handler.eventFilter(shell.roots, reparented) is False
    settle(qtbot)
    assert not tab_shown(shell.roots)
