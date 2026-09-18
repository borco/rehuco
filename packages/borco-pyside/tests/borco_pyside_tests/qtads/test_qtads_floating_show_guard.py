"""Tests for QtAdsFloatingShowGuard: floating dock windows held off the screen until released."""

from collections.abc import Iterator
from typing import Final

import PySide6QtAds as QtAds
from borco_pyside.qtads import QtAdsFloatingShowGuard
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot

DONT_SHOW: Final = Qt.WidgetAttribute.WA_DontShowOnScreen


@fixture
def shown_manager(qtbot: QtBot) -> Iterator[QtAds.CDockManager]:
    """A real, **shown** `CDockManager` kept alive for the whole test.

    Shown on purpose, unlike most managers in these tests: QtAds only shows a freshly floated dock's
    container when its manager is already visible (otherwise it parks it in its own
    uninitialised-floating-widgets list), and a container that is never shown is not what this guard
    is about.

    A generator fixture for the reason ``test_qtads_focus_tracker.py`` explains.
    """
    manager = QtAds.CDockManager()
    qtbot.addWidget(manager)
    manager.show()
    qtbot.waitExposed(manager)
    yield manager


def floating_dock(manager: QtAds.CDockManager, name: str) -> QtAds.CDockWidget:
    """Float a new dock on ``manager`` and return it.

    :param manager: the manager to float the dock on.
    :param name: the dock's object name.
    :returns: the dock, in its own floating container.
    """
    dock = QtAds.CDockWidget(manager, name.title())
    dock.setObjectName(name)
    dock.setWidget(QLabel(name))
    manager.addDockWidgetFloating(dock)
    return dock


def test_a_guarded_container_is_kept_off_the_screen(shown_manager: QtAds.CDockManager) -> None:
    """A floating container shown while the guard is armed carries ``WA_DontShowOnScreen``.

    Which is the whole mechanism: ``QWidgetPrivate::show_sys`` -- the step that maps the native window
    -- returns early for a widget carrying that attribute, and Qt delivers ``QEvent.Show`` just before
    calling it. Asserted on the attribute rather than on a paint, because the offscreen plugin these
    tests run under does not present anything either way; what the attribute buys is measured on a
    real plugin instead (:class:`QtAdsFloatingShowGuard`).

    **Test steps:**

    * arm a guard, then float a dock on a manager that is already shown
    * verify the container carries the attribute and is what the guard hands back
    """
    guard = QtAdsFloatingShowGuard()
    dock = floating_dock(shown_manager, "guarded")

    container = dock.floatingDockContainer()
    assert container is not None
    assert container.testAttribute(DONT_SHOW) is True
    assert guard.release() == (container,)


def test_release_clears_the_attribute_so_a_later_show_maps(shown_manager: QtAds.CDockManager) -> None:
    """``release`` hands each container back hidden and ready to be shown for real.

    Both halves are the guard's: the hide (a held container is visible to Qt but unmapped, so a
    ``show()`` on it would be a no-op) and the attribute (which would otherwise silently swallow the
    caller's show once its window is up).

    **Test steps:**

    * arm a guard and float a dock on a shown manager
    * release the guard
    * verify the container is hidden with the attribute gone, and an ordinary ``show`` maps it again
    """
    guard = QtAdsFloatingShowGuard()
    dock = floating_dock(shown_manager, "guarded")
    container = dock.floatingDockContainer()
    assert container is not None

    guard.release()

    assert container.isVisible() is False
    assert container.testAttribute(DONT_SHOW) is False
    container.show()
    assert container.isVisible() is True


def test_a_container_shown_after_the_release_is_left_alone(shown_manager: QtAds.CDockManager) -> None:
    """The guard stops guarding once released -- it covers construction, not the session.

    **Test steps:**

    * arm a guard and release it immediately
    * float a dock afterwards
    * verify its container carries no attribute, and a second release hands back nothing
    """
    guard = QtAdsFloatingShowGuard()
    assert not guard.release()

    dock = floating_dock(shown_manager, "unguarded")

    container = dock.floatingDockContainer()
    assert container is not None
    assert container.testAttribute(DONT_SHOW) is False
    assert not guard.release()


def test_a_container_hidden_before_the_release_is_not_hidden_again(
    shown_manager: QtAds.CDockManager, mocker: MockerFixture
) -> None:
    """``release`` hides a held container only while it is still visible -- a second ``hide()`` on one
    already hidden was seen to crash the process, so the release checks rather than hides blindly.

    **Test steps:**

    * arm a guard, float a dock on a shown manager, and hide its container by hand
    * release the guard with ``hide`` spied on
    * verify the container was not hidden again, and still comes back with the attribute cleared
    """
    guard = QtAdsFloatingShowGuard()
    dock = floating_dock(shown_manager, "guarded")
    container = dock.floatingDockContainer()
    assert container is not None
    container.hide()
    hide = mocker.spy(container, "hide")

    assert guard.release() == (container,)

    hide.assert_not_called()
    assert container.testAttribute(DONT_SHOW) is False


def test_without_an_application_the_guard_is_inert(mocker: MockerFixture) -> None:
    """A guard built while ``QApplication.instance()`` is ``None`` installs nothing and releases nothing.

    Reached only when a guard is constructed before the application exists; the filter is
    application-wide, so with no application there is nothing to arm -- and nothing to disarm either.

    **Test steps:**

    * make ``QApplication.instance`` report no application, and watch the filter API
    * build and release a guard
    * verify no filter was installed or removed, and the release hands back nothing
    """
    mocker.patch.object(QApplication, "instance", return_value=None)
    install = mocker.patch.object(QApplication, "installEventFilter")
    remove = mocker.patch.object(QApplication, "removeEventFilter")

    guard = QtAdsFloatingShowGuard()

    assert not guard.release()
    install.assert_not_called()
    remove.assert_not_called()
