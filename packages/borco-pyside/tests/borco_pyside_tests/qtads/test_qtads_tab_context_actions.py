"""Tests for QtAdsTabContextActions: a dock's own actions on top of its tab's right-click menu."""

from collections.abc import Iterator
from unittest.mock import MagicMock

import PySide6QtAds as QtAds
from borco_pyside.qtads import QtAdsTabContextActions
from PySide6.QtCore import QPoint
from PySide6.QtGui import QAction, QContextMenuEvent
from PySide6.QtWidgets import QApplication, QMainWindow, QMenu, QWidget
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot


# region fixtures
@fixture
def manager(qtbot: QtBot) -> Iterator[QtAds.CDockManager]:
    """A manager on a shown window."""
    window = QMainWindow()
    qtbot.addWidget(window)
    window.resize(800, 600)
    window.show()
    yield QtAds.CDockManager(window)


def add_dock(manager: QtAds.CDockManager, name: str) -> QtAds.CDockWidget:
    """A dock named ``name``, added to the centre.

    :param manager: the manager to add to.
    :param name: its object name and title.
    :returns: the dock.
    """
    dock = QtAds.CDockWidget(manager, name)
    dock.setObjectName(name)
    dock.setWidget(QWidget())
    manager.addDockWidget(QtAds.CenterDockWidgetArea, dock)
    return dock


@fixture
def action(manager: QtAds.CDockManager) -> QAction:
    """The extra action."""
    return QAction("Rename", manager)


@fixture
def extended(manager: QtAds.CDockManager) -> QtAds.CDockWidget:
    """A dock registered with the helper."""
    return add_dock(manager, "extended")


@fixture
def helper(manager: QtAds.CDockManager, extended: QtAds.CDockWidget, action: QAction) -> QtAdsTabContextActions:
    """A helper with ``action`` on ``extended``."""
    helper = QtAdsTabContextActions(manager)
    helper.add(extended, [action])
    return helper


# endregion


def right_click(dock: QtAds.CDockWidget) -> None:
    """Deliver a context-menu event to ``dock``'s tab.

    :param dock: the dock whose tab to right-click.
    """
    tab = dock.tabWidget()
    point = QPoint(5, 5)
    QApplication.sendEvent(tab, QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point, tab.mapToGlobal(point)))


def test_the_action_comes_first_then_a_separator_then_qtads_own_entries(
    helper: QtAdsTabContextActions, extended: QtAds.CDockWidget, action: QAction
) -> None:
    """The menu reads: the added action, a separator, then QtAds' own entries starting with Detach.

    **Test steps:**

    * build the menu for the extended dock
    * verify the first entry is the action, the second a separator and the third QtAds' *Detach*
    """
    entries = helper.menu_for(extended).actions()

    assert entries[0] is action
    assert entries[1].isSeparator()
    assert entries[2].text() == "Detach"


def test_a_right_click_shows_the_extended_menu_after_calling_on_open(
    mocker: MockerFixture, manager: QtAds.CDockManager, action: QAction
) -> None:
    """A right-click on an added tab runs ``on_open`` and then shows the extended menu.

    **Test steps:**

    * add a dock with an ``on_open`` callback, and capture ``QMenu.popup``
    * right-click its tab
    * verify the callback ran once and the shown menu starts with the action
    """
    dock = add_dock(manager, "with-callback")
    on_open = MagicMock()
    QtAdsTabContextActions(manager).add(dock, [action], on_open)
    popup = mocker.patch.object(QMenu, "popup")

    right_click(dock)

    on_open.assert_called_once_with()
    popup.assert_called_once()
    assert dock.tabWidget().findChildren(QMenu)[0].actions()[0] is action


def test_another_docks_tab_keeps_qtads_own_menu(manager: QtAds.CDockManager, helper: QtAdsTabContextActions) -> None:
    """A tab never passed to ``add`` is left alone: the helper does not show a menu for it.

    **Test steps:**

    * add a second dock that is not registered
    * verify the helper's filter does not consume a context-menu event sent to that tab
    """
    other = add_dock(manager, "other")
    event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(5, 5), QPoint(5, 5))

    assert helper.eventFilter(other.tabWidget(), event) is False


def test_a_removed_dock_is_forgotten(
    manager: QtAds.CDockManager, helper: QtAdsTabContextActions, extended: QtAds.CDockWidget
) -> None:
    """Once its dock leaves the manager, the helper holds nothing for it and its tab is no longer filtered.

    **Test steps:**

    * remove the registered dock from the manager
    * verify the helper no longer consumes a context-menu event sent to the tab it had
    """
    tab = extended.tabWidget()
    manager.removeDockWidget(extended)
    event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(5, 5), QPoint(5, 5))

    assert helper.eventFilter(tab, event) is False
