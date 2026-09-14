"""Tests for QtAdsAutoHideButtonSuppressor: keeping one manager's areas free of the pin button."""

from collections.abc import Iterator

import PySide6QtAds as QtAds
from borco_pyside.qtads.qtads_auto_hide_button_suppressor import QtAdsAutoHideButtonSuppressor
from PySide6.QtWidgets import QMainWindow, QWidget
from pytest import fixture
from pytestqt.qtbot import QtBot

WAIT = 10_000
"""How long a ``waitUntil`` here is given. Generous on purpose: the first wait in a Qt test can spend
seconds draining a backlog of ``deleteLater`` calls left by earlier tests, so a gate has to outlast
that rather than the work it is actually waiting for."""


@fixture(autouse=True)
def auto_hide_flags() -> Iterator[None]:
    """Turn QtAds' pinning on for the duration of one test, and put the flags back afterwards.

    The flags are a `CDockManager` **static**, shared by every manager in the process -- which is the
    whole reason the suppressor exists -- so a test that left them on would decide the behaviour of
    every later test in the same session. New areas honour a flag set after the first manager was
    built (verified), so this needs no session-wide ordering.
    """
    previous = QtAds.CDockManager.autoHideConfigFlags()
    QtAds.CDockManager.setAutoHideConfigFlags(QtAds.CDockManager.eAutoHideFlag.DefaultAutoHideConfig)
    yield
    QtAds.CDockManager.setAutoHideConfigFlags(previous)


@fixture
def window(qtbot: QtBot) -> Iterator[QMainWindow]:
    """A real, shown top-level window to host a manager.

    Shown rather than merely built: ``isHidden()`` distinguishes an explicitly hidden widget from one
    that merely has no visible ancestor, but a pin button QtAds never got round to showing would read
    as hidden too -- so the control assertion (a suppressed manager's sibling keeps its button) needs
    a window that genuinely paints.
    """
    window = QMainWindow()
    qtbot.addWidget(window)
    window.resize(800, 600)
    window.show()
    yield window


def add_dock(
    manager: QtAds.CDockManager,
    name: str,
    area: QtAds.DockWidgetArea = QtAds.CenterDockWidgetArea,
) -> QtAds.CDockWidget:
    """Build a real dock named ``name`` and add it to ``manager`` at ``area``.

    :param manager: the dock manager to add to.
    :param name: the dock's object name and initial title.
    :param area: where to place it (defaults to a center tab).
    :returns: the new dock.
    """
    dock = QtAds.CDockWidget(manager, name)
    dock.setObjectName(name)
    dock.setWidget(QWidget())
    manager.addDockWidget(area, dock)
    return dock


def pin_button(dock: QtAds.CDockWidget) -> QtAds.CTitleBarButton:
    """The pin (auto-hide) button on ``dock``'s containing area's title bar.

    :param dock: the dock whose area to read.
    :returns: the area's auto-hide button.
    """
    area = dock.dockAreaWidget()
    assert area is not None
    return area.titleBarButton(QtAds.TitleBarButtonAutoHide)


def test_an_unsuppressed_manager_keeps_its_pin_button(window: QMainWindow, qtbot: QtBot) -> None:
    """Without a suppressor, QtAds' own flag puts a pin button on the area -- the control case.

    **Test steps:**

    * build a manager with one dock and no suppressor
    * verify the area's auto-hide button is shown
    """
    manager = QtAds.CDockManager(window)
    dock = add_dock(manager, "plain")

    qtbot.waitUntil(lambda: pin_button(dock).isVisible(), timeout=WAIT)


def test_an_area_built_before_the_suppressor_loses_its_pin_button(window: QMainWindow, qtbot: QtBot) -> None:
    """The initial pass covers areas that already exist when the suppressor is constructed.

    **Test steps:**

    * build a manager with one dock
    * construct a suppressor on it afterwards
    * verify the area's auto-hide button ends up hidden
    """
    manager = QtAds.CDockManager(window)
    dock = add_dock(manager, "first")

    QtAdsAutoHideButtonSuppressor(manager)

    qtbot.waitUntil(lambda: pin_button(dock).isHidden(), timeout=WAIT)


def test_an_area_created_later_loses_its_pin_button(window: QMainWindow, qtbot: QtBot) -> None:
    """A dock added after the suppressor is hooked is covered too.

    **Test steps:**

    * build a manager and suppress it while it is still empty
    * add a dock
    * verify its area's auto-hide button ends up hidden
    """
    manager = QtAds.CDockManager(window)
    QtAdsAutoHideButtonSuppressor(manager)

    dock = add_dock(manager, "later")

    qtbot.waitUntil(lambda: pin_button(dock).isHidden(), timeout=WAIT)


def test_a_revealed_dock_does_not_bring_the_pin_button_back(window: QMainWindow, qtbot: QtBot) -> None:
    """Showing a hidden dock re-shows the area's title-bar buttons; the suppressor re-hides them.

    The regression the ``dockAreaViewToggled`` hook exists for -- a shell whose sub-docks start
    hidden is exactly the shape this is used on, and a suppressor watching only adds and removals
    was measured to let the button back on the first reveal.

    **Test steps:**

    * build a suppressed manager with a dock, and hide the dock
    * reveal it again
    * verify its area's auto-hide button is hidden once more
    """
    manager = QtAds.CDockManager(window)
    QtAdsAutoHideButtonSuppressor(manager)
    dock = add_dock(manager, "revealed")
    dock.toggleView(False)

    dock.toggleView(True)

    qtbot.waitUntil(lambda: pin_button(dock).isHidden(), timeout=WAIT)


def test_removing_a_dock_leaves_the_survivors_pin_button_hidden(window: QMainWindow, qtbot: QtBot) -> None:
    """A removal flips the container's visible-area count through one, which re-shows the buttons.

    The second half of the reason the hide is deferred and re-applied rather than made once: QtAds
    forces title-bar buttons back on that transition regardless of any flag.

    **Test steps:**

    * build a suppressed manager with two docks in split areas
    * remove one of them
    * verify the survivor's auto-hide button is still hidden
    """
    manager = QtAds.CDockManager(window)
    QtAdsAutoHideButtonSuppressor(manager)
    survivor = add_dock(manager, "survivor")
    doomed = add_dock(manager, "doomed", QtAds.BottomDockWidgetArea)
    qtbot.waitUntil(lambda: pin_button(survivor).isHidden(), timeout=WAIT)

    manager.removeDockWidget(doomed)

    qtbot.waitUntil(lambda: pin_button(survivor).isHidden(), timeout=WAIT)
