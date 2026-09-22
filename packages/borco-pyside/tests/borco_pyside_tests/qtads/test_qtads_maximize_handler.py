"""Tests for QtAdsMaximizeHandler: the per-tab maximize toggle beside every tab's close button."""

from collections.abc import Iterator

import PySide6QtAds as QtAds
from borco_pyside.qtads import QtAdsFocusTracker, QtAdsMaximizeHandler, tab_close_button
from borco_pyside.theming import Glyph
from PySide6.QtCore import QByteArray
from PySide6.QtWidgets import QBoxLayout, QMainWindow, QPushButton, QWidget
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot

GLYPH = Glyph("⤢")
MAXIMIZED_GLYPH = Glyph("⤡")
"""Plain-Unicode stand-ins for the two icon-font glyphs, so no font needs loading here."""

WAIT = 10_000
"""How long a ``waitUntil`` here is given -- generous for the reason the suppressor's tests give: the
first wait in a Qt test can spend seconds draining earlier tests' ``deleteLater`` backlog."""


# region fixtures
@fixture
def window(qtbot: QtBot) -> Iterator[QMainWindow]:
    """A real, shown top-level window to host a manager -- shown so splitters have room to divide and
    ``isHidden()`` means what the handler means by it."""
    window = QMainWindow()
    qtbot.addWidget(window)
    window.resize(800, 600)
    window.show()
    yield window


@fixture
def manager(window: QMainWindow) -> QtAds.CDockManager:
    """A manager on the shown window."""
    return QtAds.CDockManager(window)


@fixture
def handler(manager: QtAds.CDockManager) -> QtAdsMaximizeHandler:
    """A handler over the manager, with a plain-Unicode glyph -- the icon font is the app's business."""
    return QtAdsMaximizeHandler(manager, GLYPH, MAXIMIZED_GLYPH)


@fixture
def docks(manager: QtAds.CDockManager, qtbot: QtBot) -> list[QtAds.CDockWidget]:
    """Three docks in three split areas -- left, right, bottom -- laid out and settled."""
    built = [
        add_dock(manager, "left", QtAds.LeftDockWidgetArea),
        add_dock(manager, "right", QtAds.RightDockWidgetArea),
        add_dock(manager, "bottom", QtAds.BottomDockWidgetArea),
    ]
    qtbot.waitUntil(lambda: len(manager.openedDockAreas()) == 3, timeout=WAIT)
    return built


def add_dock(manager: QtAds.CDockManager, name: str, area: QtAds.DockWidgetArea) -> QtAds.CDockWidget:
    """Build a real dock named ``name`` and add it to ``manager`` at ``area``.

    :param manager: the dock manager to add to.
    :param name: the dock's object name and initial title.
    :param area: where to place it.
    :returns: the new dock.
    """
    dock = QtAds.CDockWidget(manager, name)
    dock.setObjectName(name)
    dock.setWidget(QWidget())
    manager.addDockWidget(area, dock)
    return dock


def area_of(dock: QtAds.CDockWidget) -> QtAds.CDockAreaWidget:
    """``dock``'s area, asserted present.

    :param dock: the dock whose area to read.
    :returns: the area.
    """
    area = dock.dockAreaWidget()
    assert area is not None
    return area


def button_of(handler: QtAdsMaximizeHandler, dock: QtAds.CDockWidget, qtbot: QtBot) -> QPushButton:
    """The maximize button on ``dock``'s tab, waited for -- the walk that inserts it is deferred.

    :param handler: the handler that inserts it.
    :param dock: the dock whose tab to read.
    :param qtbot: the bot to wait with.
    :returns: the button.
    """
    qtbot.waitUntil(lambda: handler.button(dock) is not None, timeout=WAIT)
    button = handler.button(dock)
    assert button is not None
    return button


# endregion


# region the button
def test_every_tab_gets_a_button_between_its_title_and_its_close_button(
    handler: QtAdsMaximizeHandler, docks: list[QtAds.CDockWidget], qtbot: QtBot
) -> None:
    """Each dock's tab carries the button, named for a stylesheet, checkable, drawn as the glyph's
    text at the close button's size, between the title and the close button with the title's own
    spacing on both sides of it.

    **Test steps:**

    * build three docks under a handler
    * verify each tab's layout reads title, spacing, button, spacing, close button, and the
      button's look
    """
    for dock in docks:
        button = button_of(handler, dock, qtbot)
        layout = dock.tabWidget().layout()
        assert isinstance(layout, QBoxLayout)
        close_button = tab_close_button(dock)
        assert close_button is not None
        assert layout.indexOf(button) == 2
        assert layout.indexOf(close_button) == 4
        assert layout.itemAt(3).sizeHint().width() == layout.itemAt(1).sizeHint().width()  # type: ignore[union-attr]
        assert button.objectName() == QtAdsMaximizeHandler.BUTTON_OBJECT_NAME
        assert button.isCheckable() and not button.isChecked()
        assert button.text() == GLYPH.codepoint
        assert button.width() == button.height() == close_button.height()
        assert button.toolTip() == QtAdsMaximizeHandler.MAXIMIZE_TOOLTIP


def test_beside_a_tracker_the_button_sits_level_with_the_close_button(
    manager: QtAds.CDockManager, qtbot: QtBot
) -> None:
    """With a `QtAdsFocusTracker` on the same manager -- which squares the close button and derives
    the maximize button's margin from its rules -- the two buttons share a top edge and a size.

    **Test steps:**

    * build a tracker and a handler on one manager, add a dock
    * verify the maximize button's geometry is the close button's, shifted left
    """
    QtAdsFocusTracker(manager)
    handler = QtAdsMaximizeHandler(manager, GLYPH, MAXIMIZED_GLYPH)
    dock = add_dock(manager, "levelled", QtAds.LeftDockWidgetArea)
    button = button_of(handler, dock, qtbot)
    close_button = tab_close_button(dock)
    assert close_button is not None

    qtbot.waitUntil(lambda: close_button.width() == close_button.height(), timeout=WAIT)

    assert button.size() == close_button.size()
    assert button.geometry().top() == close_button.geometry().top()
    assert button.geometry().right() < close_button.geometry().left()


def test_a_dock_added_later_gets_a_button_too(
    handler: QtAdsMaximizeHandler, manager: QtAds.CDockManager, qtbot: QtBot
) -> None:
    """A dock added after the handler is hooked is covered by the ``dockWidgetAdded`` walk.

    **Test steps:**

    * hook a handler on an empty manager, then add a dock
    * verify its tab gets a button
    """
    dock = add_dock(manager, "later", QtAds.LeftDockWidgetArea)

    button_of(handler, dock, qtbot)


def test_a_dock_added_hidden_gets_a_button_for_when_it_shows(
    handler: QtAdsMaximizeHandler, manager: QtAds.CDockManager, qtbot: QtBot
) -> None:
    """A closed dock's tab is built all the same, so its button is there once the dock is revealed.

    **Test steps:**

    * add a dock and close it before the walk runs
    * verify it has a button, un-checked
    """
    dock = add_dock(manager, "closed", QtAds.LeftDockWidgetArea)
    dock.toggleView(False)

    button = button_of(handler, dock, qtbot)

    assert not button.isChecked()


# endregion


# region maximize and restore
def test_maximizing_hides_every_sibling_area_and_none_of_the_targets(
    handler: QtAdsMaximizeHandler, manager: QtAds.CDockManager, docks: list[QtAds.CDockWidget], qtbot: QtBot
) -> None:
    """Toggling on leaves the target's area the only open one, closes no dock, fires no dock
    ``viewToggled``, and reports through the button and the signal.

    **Test steps:**

    * watch every dock's ``viewToggled`` and the handler's ``maximized_changed``
    * click the left area's button
    * verify only that area is open, every dock still reads open, nothing toggled, and the button
      is checked with the restore tooltip
    """
    toggled: list[bool] = []
    for dock in docks:
        dock.viewToggled.connect(toggled.append)
    changed: list[bool] = []
    handler.maximized_changed.connect(changed.append)
    button = button_of(handler, docks[0], qtbot)

    button.click()

    assert manager.openedDockAreas() == [area_of(docks[0])]
    assert handler.maximized_dock is docks[0]
    assert not any(dock.isClosed() for dock in docks)
    assert not toggled
    assert changed == [True]
    assert button.isChecked()
    assert button.text() == MAXIMIZED_GLYPH.codepoint
    assert button.toolTip() == QtAdsMaximizeHandler.RESTORE_TOOLTIP


def test_restoring_shows_exactly_the_areas_that_were_hidden(
    handler: QtAdsMaximizeHandler, manager: QtAds.CDockManager, docks: list[QtAds.CDockWidget], qtbot: QtBot
) -> None:
    """Toggling off puts back the hidden areas at their former sizes, and leaves a dock that was
    already closed before the maximize closed.

    **Test steps:**

    * close the bottom dock (its area goes with it), note the remaining splitter sizes
    * maximize the left area, then un-maximize it
    * verify the two areas are back at their sizes and the bottom dock is still closed
    """
    docks[2].toggleView(False)
    qtbot.waitUntil(lambda: len(manager.openedDockAreas()) == 2, timeout=WAIT)
    left = area_of(docks[0])
    sizes = manager.splitterSizes(left)
    assert all(size > 0 for size in sizes)
    button = button_of(handler, docks[0], qtbot)
    button.click()
    assert manager.openedDockAreas() == [left]

    button.click()

    qtbot.waitUntil(lambda: manager.splitterSizes(left) == sizes, timeout=WAIT)
    assert set(manager.openedDockAreas()) == {left, area_of(docks[1])}
    assert docks[2].isClosed()
    assert handler.maximized_dock is None
    assert not button.isChecked()
    assert button.text() == GLYPH.codepoint
    assert button.toolTip() == QtAdsMaximizeHandler.MAXIMIZE_TOOLTIP


def test_maximizing_the_only_area_is_a_no_op_that_still_checks(
    handler: QtAdsMaximizeHandler, manager: QtAds.CDockManager, qtbot: QtBot
) -> None:
    """With nothing to hide, the toggle still reads checked, and toggling off changes nothing either.

    **Test steps:**

    * build one dock alone
    * click its button on, then off
    * verify the area stays open throughout and the button tracked both clicks
    """
    dock = add_dock(manager, "alone", QtAds.LeftDockWidgetArea)
    button = button_of(handler, dock, qtbot)

    button.click()
    assert button.isChecked()
    assert manager.openedDockAreas() == [area_of(dock)]
    assert handler.maximized_dock is dock

    button.click()
    assert not button.isChecked()
    assert manager.openedDockAreas() == [area_of(dock)]
    assert handler.maximized_dock is None


def test_maximizing_another_area_restores_the_first(
    handler: QtAdsMaximizeHandler, manager: QtAds.CDockManager, docks: list[QtAds.CDockWidget], qtbot: QtBot
) -> None:
    """At most one area is maximized per manager: asking for a second restores the first, buttons
    included.

    **Test steps:**

    * maximize the left area through its button, then call ``maximize`` for the right area
    * verify the right area is the only open one and the left button is un-checked
    """
    left_button = button_of(handler, docks[0], qtbot)
    right_button = button_of(handler, docks[1], qtbot)
    left_button.click()

    handler.maximize(docks[1])

    assert manager.openedDockAreas() == [area_of(docks[1])]
    assert not left_button.isChecked()
    assert right_button.isChecked()


def test_maximizing_hides_the_other_tabs_of_its_area_and_restores_them(
    handler: QtAdsMaximizeHandler, manager: QtAds.CDockManager, docks: list[QtAds.CDockWidget], qtbot: QtBot
) -> None:
    """Two tabs in one area: maximizing one hides the other's tab -- without closing its dock -- so
    the maximized dock is the only thing on screen, and restoring shows the tab back.

    **Test steps:**

    * tab a fourth dock into the left area, then maximize the left dock
    * verify the fourth's tab is hidden while its dock still reads open, and the left is current
    * un-maximize and verify the fourth's tab is back
    """
    fourth = QtAds.CDockWidget(manager, "fourth")
    fourth.setObjectName("fourth")
    fourth.setWidget(QWidget())
    manager.addDockWidget(QtAds.CenterDockWidgetArea, fourth, area_of(docks[0]))
    left_button = button_of(handler, docks[0], qtbot)
    qtbot.waitUntil(lambda: fourth.tabWidget().isVisible(), timeout=WAIT)

    left_button.click()

    assert fourth.tabWidget().isHidden()
    assert not fourth.isClosed()
    assert area_of(docks[0]).currentIndex() == area_of(docks[0]).index(docks[0])

    left_button.click()

    assert fourth.tabWidget().isVisible()


def test_a_floating_area_maximizes_within_its_own_window(
    handler: QtAdsMaximizeHandler, manager: QtAds.CDockManager, docks: list[QtAds.CDockWidget], qtbot: QtBot
) -> None:
    """An area in a floating window hides that window's other areas, not the main window's.

    **Test steps:**

    * float the bottom dock, then split a fourth dock into the floating window beside it
    * maximize the floated bottom area through its button
    * verify the main window's two areas are untouched and the floating window shows one area
    """
    floating = manager.addDockWidgetFloating(docks[2])
    qtbot.waitUntil(lambda: len(manager.openedDockAreas()) == 2, timeout=WAIT)
    fourth = QtAds.CDockWidget(manager, "fourth")
    fourth.setObjectName("fourth")
    fourth.setWidget(QWidget())
    manager.addDockWidget(QtAds.RightDockWidgetArea, fourth, area_of(docks[2]))
    container = floating.dockContainer()
    qtbot.waitUntil(lambda: len(container.openedDockAreas()) == 2, timeout=WAIT)
    button = button_of(handler, docks[2], qtbot)

    button.click()

    assert container.openedDockAreas() == [area_of(docks[2])]
    assert len(manager.openedDockAreas()) == 2


# endregion


# region exit-first
def test_closing_a_dock_in_a_hidden_sibling_restores_but_not_the_emptied_area(
    handler: QtAdsMaximizeHandler, manager: QtAds.CDockManager, docks: list[QtAds.CDockWidget], qtbot: QtBot
) -> None:
    """A dock toggle while maximized exits the maximize; a sibling whose last dock closed while
    hidden is not shown back as an empty area.

    **Test steps:**

    * maximize the left area, then close the right dock (its hidden area's only one)
    * verify the maximize exited, the bottom area came back, and the right area stayed hidden
    """
    button = button_of(handler, docks[0], qtbot)
    button.click()

    docks[1].toggleView(False)

    assert handler.maximized_dock is None
    assert not button.isChecked()
    assert set(manager.openedDockAreas()) == {area_of(docks[0]), area_of(docks[2])}


def test_dragging_a_dock_out_restores(
    handler: QtAdsMaximizeHandler, manager: QtAds.CDockManager, docks: list[QtAds.CDockWidget], qtbot: QtBot
) -> None:
    """An area leaving the container (a dock floated out) exits the maximize first.

    **Test steps:**

    * maximize the left area, then float the right dock
    * verify the maximize exited and the bottom area is open again
    """
    button = button_of(handler, docks[0], qtbot)
    button.click()

    manager.addDockWidgetFloating(docks[1])

    assert handler.maximized_dock is None
    assert not button.isChecked()
    assert set(manager.openedDockAreas()) == {area_of(docks[0]), area_of(docks[2])}


def test_removing_a_dock_restores(
    handler: QtAdsMaximizeHandler, manager: QtAds.CDockManager, docks: list[QtAds.CDockWidget], qtbot: QtBot
) -> None:
    """A dock removed from the manager exits the maximize first.

    **Test steps:**

    * maximize the left area, then remove the bottom dock
    * verify the maximize exited and the right area is open again
    """
    button = button_of(handler, docks[0], qtbot)
    button.click()

    manager.removeDockWidget(docks[2])

    assert handler.maximized_dock is None
    assert not button.isChecked()
    assert set(manager.openedDockAreas()) == {area_of(docks[0]), area_of(docks[1])}


def test_a_layout_restore_ends_unmaximized_with_the_buttons_unchecked(
    handler: QtAdsMaximizeHandler, manager: QtAds.CDockManager, docks: list[QtAds.CDockWidget], qtbot: QtBot
) -> None:
    """``restoreState`` rebuilds every area: the maximize is forgotten, and the tabs' buttons -- the
    same objects, since a restore reparents tabs rather than recreating them -- read un-checked.

    **Test steps:**

    * capture the three-area layout, maximize the left dock
    * restore the capture
    * verify nothing is maximized, three areas are open, and every dock's button is un-checked
    """
    blob = manager.saveState()
    button = button_of(handler, docks[0], qtbot)
    button.click()

    assert manager.restoreState(blob)

    assert handler.maximized_dock is None
    assert len(manager.openedDockAreas()) == 3
    for dock in docks:
        assert handler.button(dock) is not None and not handler.button(dock).isChecked()  # type: ignore[union-attr]


# endregion


# region unmaximized captures
def test_a_capture_inside_unmaximized_records_the_real_sizes(
    handler: QtAdsMaximizeHandler, manager: QtAds.CDockManager, docks: list[QtAds.CDockWidget], qtbot: QtBot
) -> None:
    """A ``saveState`` taken inside :meth:`unmaximized` restores to the pre-maximize sizes, and the
    maximize is exactly as it was afterwards.

    **Test steps:**

    * note the sizes, maximize the left area, capture inside ``unmaximized()``
    * verify the layout is maximized again and the button still checked right after the block
    * un-maximize, restore the capture, verify the sizes are the noted ones
    """
    left = area_of(docks[0])
    sizes = manager.splitterSizes(left)
    button = button_of(handler, docks[0], qtbot)
    button.click()

    with handler.unmaximized():
        assert len(manager.openedDockAreas()) == 3
        blob = manager.saveState()

    assert manager.openedDockAreas() == [left]
    assert button.isChecked()
    assert handler.maximized_dock is docks[0]
    button.click()
    assert manager.restoreState(QByteArray(blob))
    qtbot.waitUntil(lambda: manager.splitterSizes(area_of(docks[0])) == sizes, timeout=WAIT)


def test_unmaximized_is_a_pass_through_while_nothing_is_maximized(
    handler: QtAdsMaximizeHandler, manager: QtAds.CDockManager, docks: list[QtAds.CDockWidget]
) -> None:
    """With no maximize standing the block changes nothing, before, during or after.

    **Test steps:**

    * enter the block on an un-maximized manager
    * verify three areas are open throughout
    """
    del docks
    with handler.unmaximized():
        assert len(manager.openedDockAreas()) == 3
    assert len(manager.openedDockAreas()) == 3


# endregion


# region full coverage of the defensive paths


def test_a_handler_built_over_existing_docks_hooks_their_toggle_too(
    manager: QtAds.CDockManager, docks: list[QtAds.CDockWidget]
) -> None:
    """Docks already on the manager when the handler is constructed are wired to exit-first the
    same as ones added afterwards, not only walked for a button.

    **Test steps:**

    * build three docks, then construct a handler over the already-populated manager
    * maximize the first, then toggle a *pre-existing* dock's own view
    * verify the maximize exited -- proof the toggle was connected at construction, not only later
    """
    handler = QtAdsMaximizeHandler(manager, GLYPH, MAXIMIZED_GLYPH)
    handler.maximize(docks[0])

    docks[1].toggleView(False)

    assert handler.maximized_dock is None


def test_maximizing_an_arealess_dock_is_a_no_op(handler: QtAdsMaximizeHandler, manager: QtAds.CDockManager) -> None:
    """A dock not yet placed into any area (built but never ``addDockWidget``-ed) has nothing to
    grow into, so maximizing it changes nothing and does not raise -- it also has no button yet, so
    the no-op sync is itself a no-op.

    **Test steps:**

    * build a dock and call ``maximize`` on it directly, without adding it to the manager
    * verify nothing is maximized
    """
    orphan = QtAds.CDockWidget(manager, "orphan")
    orphan.setWidget(QWidget())

    handler.maximize(orphan)

    assert handler.maximized_dock is None


def test_maximizing_the_already_maximized_dock_is_a_no_op(
    handler: QtAdsMaximizeHandler, docks: list[QtAds.CDockWidget]
) -> None:
    """Calling ``maximize`` again for the dock that is already maximized changes nothing -- the
    button's own ``toggled`` never re-fires it (checking an already-checked button is a no-op), but
    the method itself must still be idempotent for a caller that holds the dock directly.

    **Test steps:**

    * maximize a dock, then call ``maximize`` on it again directly
    * verify it is still the maximized one, alone
    """
    handler.maximize(docks[0])

    handler.maximize(docks[0])

    assert handler.maximized_dock is docks[0]


def test_a_glyph_with_a_family_is_applied_to_the_buttons_font(manager: QtAds.CDockManager, qtbot: QtBot) -> None:
    """A glyph naming a font family (an icon font, in the app) is set on the button's font, not left
    at the tab's inherited one -- the plain-Unicode stand-in the other tests use has none.

    **Test steps:**

    * build a handler with a glyph that names a family, and a dock
    * verify the button's font carries that family
    """
    handler = QtAdsMaximizeHandler(manager, Glyph("x", "Courier New"))
    dock = add_dock(manager, "with-family", QtAds.LeftDockWidgetArea)

    button = button_of(handler, dock, qtbot)

    assert button.font().family() == "Courier New"


def test_a_dock_gone_mid_teardown_is_skipped_hiding_its_tab(
    handler: QtAdsMaximizeHandler,
    manager: QtAds.CDockManager,
    docks: list[QtAds.CDockWidget],
    mocker: MockerFixture,
    qtbot: QtBot,
) -> None:
    """A dock whose tab Shiboken already flags deleted while its neighbour is being maximized is
    skipped rather than raising (an exit hook can run mid-teardown).

    Patches the *tab widget's* own ``setVisible`` rather than ``CDockWidget.tabWidget()`` itself:
    the latter is also read by QtAds' own internals on every event, and a raising stand-in there
    cascades into unrelated ``eventFilter`` calls instead of the one path under test.

    **Test steps:**

    * tab a fourth dock into the left area, and make its tab's ``setVisible`` raise
    * maximize the left dock
    * verify it still maximized, and the stand-in was asked to hide the fourth's tab
    """
    fourth = QtAds.CDockWidget(manager, "fourth")
    fourth.setObjectName("fourth")
    fourth.setWidget(QWidget())
    manager.addDockWidget(QtAds.CenterDockWidgetArea, fourth, area_of(docks[0]))
    button = button_of(handler, docks[0], qtbot)
    set_visible = mocker.patch.object(fourth.tabWidget(), "setVisible", side_effect=RuntimeError("already deleted"))

    button.click()

    assert handler.maximized_dock is docks[0]
    set_visible.assert_called_once_with(False)


def test_an_area_gone_mid_teardown_is_skipped_showing_it_back(
    handler: QtAdsMaximizeHandler, docks: list[QtAds.CDockWidget], mocker: MockerFixture
) -> None:
    """A sibling area Shiboken already flags deleted when restoring is skipped rather than raising.

    **Test steps:**

    * maximize the left dock, then make the right area's ``openDockWidgetsCount`` raise
    * restore
    * verify nothing is maximized and the stand-in was consulted
    """
    handler.maximize(docks[0])
    right_area = area_of(docks[1])
    counter = mocker.patch.object(right_area, "openDockWidgetsCount", side_effect=RuntimeError("already deleted"))

    handler.restore()

    assert handler.maximized_dock is None
    counter.assert_called()


def test_a_hidden_area_gone_mid_capture_is_skipped_re_hiding_it(
    handler: QtAdsMaximizeHandler, docks: list[QtAds.CDockWidget], mocker: MockerFixture
) -> None:
    """Inside :meth:`~QtAdsMaximizeHandler.unmaximized`, a hidden area Shiboken already flags deleted
    by the time the block re-hides it is skipped rather than raising.

    **Test steps:**

    * maximize the left dock, and make the right area's second ``setVisible`` call raise
    * run an ``unmaximized`` block
    * verify the maximize still stands afterwards, and ``setVisible`` was asked to hide it
    """
    handler.maximize(docks[0])
    right_area = area_of(docks[1])
    set_visible = mocker.patch.object(right_area, "setVisible", side_effect=[None, RuntimeError("already deleted")])

    with handler.unmaximized():
        pass

    assert handler.maximized_dock is docks[0]
    set_visible.assert_called_with(False)


def test_a_dock_with_no_close_button_still_gets_a_squared_button(
    manager: QtAds.CDockManager, mocker: MockerFixture, qtbot: QtBot
) -> None:
    """A tab whose close-button config flag is off (``tab_close_button`` reports none) still gets a
    maximize button, sized off the tab itself rather than a close button that isn't there.

    **Test steps:**

    * make ``tab_close_button`` report ``None``, then build a handler and a dock
    * verify the button exists and is square
    """
    mocker.patch("borco_pyside.qtads.qtads_maximize_handler.tab_close_button", return_value=None)
    handler = QtAdsMaximizeHandler(manager, GLYPH, MAXIMIZED_GLYPH)
    dock = add_dock(manager, "no-close", QtAds.LeftDockWidgetArea)

    button = button_of(handler, dock, qtbot)

    assert button.width() == button.height() > 0


# endregion
