"""Tests for remove_dock_widget: taking a dock out of its manager under the name it was registered by."""

from collections.abc import Iterator

import PySide6QtAds as QtAds
from borco_pyside.qtads import QtAdsMaximizeHandler, remove_dock_widget
from borco_pyside.theming import Glyph
from PySide6.QtWidgets import QMainWindow, QWidget
from pytest import fixture
from pytestqt.qtbot import QtBot

WAIT = 10_000
"""How long a ``waitUntil`` here is given -- generous for the reason the maximize handler's tests give:
the first wait in a Qt test can spend seconds draining earlier tests' ``deleteLater`` backlog."""


# region fixtures
@fixture
def manager(qtbot: QtBot) -> Iterator[QtAds.CDockManager]:
    """A manager on a real window.

    A generator fixture so the window, which owns the manager, stays alive for the whole test.
    """
    window = QMainWindow()
    qtbot.addWidget(window)
    yield QtAds.CDockManager(window)


def add_dock(manager: QtAds.CDockManager, name: str) -> QtAds.CDockWidget:
    """Build a real dock named ``name`` and add it to ``manager``, which registers it under that name.

    :param manager: the dock manager to add to.
    :param name: the dock's object name and title.
    :returns: the new dock.
    """
    dock = QtAds.CDockWidget(manager, name)
    dock.setObjectName(name)
    dock.setWidget(QWidget())
    manager.addDockWidget(QtAds.CenterDockWidgetArea, dock)
    return dock


def delete_removed(dock: QtAds.CDockWidget, qtbot: QtBot) -> None:
    """Delete a dock taken out of its manager the way the app does, deferred, and wait for it to go.

    Left to Python instead, a removed dock -- parentless and Python-owned -- is freed on the spot as the
    test returns, ahead of the events its removal posted, and the next ``processEvents`` crashes or hangs
    (measured).

    :param dock: the removed dock.
    :param qtbot: the bot to wait with.
    """
    with qtbot.waitSignal(dock.destroyed, timeout=WAIT):
        dock.deleteLater()


# endregion


# region remove_dock_widget tests
def test_the_registry_keeps_a_renamed_dock_under_the_name_it_was_added_by(manager: QtAds.CDockManager) -> None:
    """QtAds never re-keys its dock registry, so a dock renamed after it was added is found under the old
    name and not the new one -- the behaviour :func:`remove_dock_widget` exists for. Pinned so a QtAds that
    starts re-keying shows up here.

    **Test steps:**

    * add a dock and rename it
    * verify the registry maps the name it was added under to it, and the new name to nothing
    """
    dock = add_dock(manager, "added-as")

    dock.setObjectName("renamed")

    assert manager.dockWidgetsMap() == {"added-as": dock}
    assert manager.findDockWidget("renamed") is None


def test_a_renamed_dock_leaves_the_registry(manager: QtAds.CDockManager, qtbot: QtBot) -> None:
    """A dock renamed after it was added is removed from the registry under the name it was added by, is
    taken off its area, and comes out carrying its current name.

    **Test steps:**

    * add a dock, rename it, and remove it with ``remove_dock_widget``
    * verify the registry is empty, the dock has no area, and its name is the renamed one
    """
    dock = add_dock(manager, "added-as")
    dock.setObjectName("renamed")

    remove_dock_widget(manager, dock)

    assert manager.dockWidgetsMap() == {}
    assert dock.dockAreaWidget() is None
    assert dock.objectName() == "renamed"
    delete_removed(dock, qtbot)


def test_a_dock_never_renamed_is_removed_as_removedockwidget_would(manager: QtAds.CDockManager, qtbot: QtBot) -> None:
    """A dock still carrying the name it was added under is removed like ``removeDockWidget`` removes it,
    and other docks stay registered.

    **Test steps:**

    * add two docks and remove one with ``remove_dock_widget``
    * verify only the other is still registered, and the removed one kept its name
    """
    dock = add_dock(manager, "gone")
    other = add_dock(manager, "kept")

    remove_dock_widget(manager, dock)

    assert manager.dockWidgetsMap() == {"kept": other}
    assert dock.objectName() == "gone"
    delete_removed(dock, qtbot)


def test_a_dock_renamed_onto_another_docks_name_leaves_that_one_registered(
    manager: QtAds.CDockManager, qtbot: QtBot
) -> None:
    """A dock renamed to the name another dock is registered under takes only its own entry with it -- a
    plain ``removeDockWidget`` would drop the other dock's.

    **Test steps:**

    * add two docks, rename the first to the second's name, and remove the first
    * verify the second is still registered under its name
    """
    dock = add_dock(manager, "first")
    other = add_dock(manager, "second")
    dock.setObjectName("second")

    remove_dock_widget(manager, dock)

    assert manager.dockWidgetsMap() == {"second": other}
    delete_removed(dock, qtbot)


def test_a_renamed_and_deleted_dock_leaves_nothing_for_the_maximize_walk(
    manager: QtAds.CDockManager, qtbot: QtBot
) -> None:
    """The crash this fixes (#364): a dock renamed, removed and deleted, then another added. The maximize
    handler's deferred walk reads the registry on the add, and a stale entry left behind by the removal
    would be a freed dock by then -- here the walk finds only the live one and dresses it.

    **Test steps:**

    * put a maximize handler on the manager, add a dock and rename it
    * remove it with ``remove_dock_widget`` and wait for it to be deleted
    * add another dock
    * verify the new dock gets its button and the registry holds it alone
    """
    handler = QtAdsMaximizeHandler(manager, Glyph("⤢"))
    renamed = add_dock(manager, "added-as")
    renamed.setObjectName("renamed")

    remove_dock_widget(manager, renamed)
    delete_removed(renamed, qtbot)
    added = add_dock(manager, "added-after")

    qtbot.waitUntil(lambda: handler.button(added) is not None, timeout=WAIT)
    assert list(manager.dockWidgetsMap()) == ["added-after"]


# endregion
