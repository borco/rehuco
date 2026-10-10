"""Tests for TitleBarActionsUnlessFloatingAlone: a dock with title-bar actions shows no lone tab when floated
alone, and has its actions back everywhere else (#488)."""

from collections.abc import Iterator
from typing import NamedTuple

import PySide6QtAds as QtAds
from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QAbstractButton, QLabel, QMainWindow
from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.main_window import TitleBarActionsUnlessFloatingAlone


class Shell(NamedTuple):
    """A manager with a Documents dock, a Root Catalog dock tabbed beside it, and the one handled."""

    manager: QtAds.CDockManager
    documents: QtAds.CDockWidget
    roots: QtAds.CDockWidget
    refresh: QAction
    handler: TitleBarActionsUnlessFloatingAlone


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


def button_shown(dock: QtAds.CDockWidget, action: QAction) -> bool:
    """Whether ``dock``'s area title bar shows a button for ``action``.

    :param dock: a placed dock.
    :param action: one of its title-bar actions.
    :returns: whether a button carrying it is visible in the bar.
    """
    title_bar = area_of(dock).titleBar()
    return any(
        action in button.actions() and button.isVisibleTo(title_bar)
        for button in title_bar.findChildren(QAbstractButton)
    )


@fixture(name="shell")
def fixture_shell(qtbot: QtBot) -> Iterator[Shell]:
    """A shown window whose Root Catalog dock carries a Refresh action through the handler, tabbed beside
    Documents and current.

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
    handler = TitleBarActionsUnlessFloatingAlone(roots, [refresh])
    manager.addDockWidget(QtAds.CenterDockWidgetArea, roots, area_of(documents))
    area_of(roots).setCurrentDockWidget(roots)
    settle(qtbot)
    yield Shell(manager, documents, roots, refresh, handler)


def test_a_docked_dock_keeps_its_actions(shell: Shell) -> None:
    """Docked in the main window, the dock has its actions and its title bar shows them.

    **Test steps:**

    * build the shell (the dock tabbed beside Documents, current)
    * verify the dock carries its action and the bar shows a button for it
    """
    assert shell.roots.titleBarActions() == [shell.refresh]
    assert button_shown(shell.roots, shell.refresh)


def test_floated_alone_the_dock_loses_its_actions_and_its_title_bar(qtbot: QtBot, shell: Shell) -> None:
    """Alone in a floating window, the dock has no actions, so QtAds hides its title bar -- the tab with it.

    **Test steps:**

    * float the dock on its own
    * verify it has no title-bar actions and its area's title bar is hidden
    """
    shell.roots.setFloating()
    settle(qtbot)

    assert shell.roots.isFloating()
    assert shell.roots.titleBarActions() == []
    assert area_of(shell.roots).titleBar().isHidden()


def test_joined_by_another_dock_the_actions_come_back(qtbot: QtBot, shell: Shell) -> None:
    """A second dock tabbed into the floating window gives the dock its actions back; taken out again, they go.

    **Test steps:**

    * float the dock alone, then tab Documents into its window and make the dock current
    * verify its actions are back and shown
    * float Documents out again
    * verify the dock, alone again, has no actions
    """
    shell.roots.setFloating()
    settle(qtbot)

    shell.manager.addDockWidgetTabToArea(shell.documents, area_of(shell.roots))
    area_of(shell.roots).setCurrentDockWidget(shell.roots)
    settle(qtbot)
    assert shell.roots.titleBarActions() == [shell.refresh]
    assert button_shown(shell.roots, shell.refresh)

    shell.documents.setFloating()
    settle(qtbot)
    assert shell.roots.titleBarActions() == []


def test_docked_back_the_buttons_show_without_a_tab_change(qtbot: QtBot, shell: Shell) -> None:
    """Re-docked into the main window, the dock's buttons are rebuilt at once, not on the next tab change.

    QtAds builds a title bar's action buttons as the current tab changes, so actions handed back to a dock
    already current would show no button until then.

    **Test steps:**

    * float the dock alone, then tab it back beside Documents and make it current
    * verify its actions are back and the bar shows a button for them
    """
    shell.roots.setFloating()
    settle(qtbot)

    shell.manager.addDockWidgetTabToArea(shell.roots, area_of(shell.documents))
    area_of(shell.roots).setCurrentDockWidget(shell.roots)
    settle(qtbot)

    assert not shell.roots.isFloating()
    assert shell.roots.titleBarActions() == [shell.refresh]
    assert button_shown(shell.roots, shell.refresh)


def test_only_the_docks_own_reparenting_redecides(qtbot: QtBot, shell: Shell) -> None:
    """The filter re-decides on the dock's own reparenting and nothing else, and never swallows the event.

    **Test steps:**

    * float the dock alone, then hand it its actions behind the handler's back
    * send a reparenting event of another object through the filter
    * verify the actions are left as they are
    * send one of the dock's own
    * verify the actions are taken off again, and neither event was swallowed
    """
    shell.roots.setFloating()
    settle(qtbot)
    shell.roots.setTitleBarActions([shell.refresh])
    reparented = QEvent(QEvent.Type.ParentChange)

    assert shell.handler.eventFilter(QObject(), reparented) is False
    settle(qtbot)
    assert shell.roots.titleBarActions() == [shell.refresh]

    assert shell.handler.eventFilter(shell.roots, reparented) is False
    settle(qtbot)
    assert shell.roots.titleBarActions() == []


def test_a_dock_in_no_area_keeps_its_actions(qtbot: QtBot, shell: Shell) -> None:
    """A dock taken out of every area is not alone in a floating window, so it has its actions, and there is no
    title bar to update.

    **Test steps:**

    * take the dock out of the manager, then make the handler re-decide
    * verify the dock is in no area and carries its actions
    """
    shell.manager.removeDockWidget(shell.roots)
    shell.handler.eventFilter(shell.roots, QEvent(QEvent.Type.ParentChange))
    settle(qtbot)

    assert shell.roots.dockAreaWidget() is None
    assert shell.roots.titleBarActions() == [shell.refresh]
