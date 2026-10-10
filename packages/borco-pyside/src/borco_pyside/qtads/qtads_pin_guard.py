"""Undoes a pin QtAds makes against a `CDockManager`'s will, the moment it is made."""

from functools import partial
from typing import Final

import PySide6QtAds as QtAds
from PySide6.QtCore import QObject, QTimer


class QtAdsPinGuard(QObject):
    """Keeps one `CDockManager`'s sidebars to its own docks -- and, for a manager that never pins, empty.

    **Two pins nothing else stops** (#491):

    - **A nested manager's dock stolen by a drop.** Dropping a floating window onto a sidebar pins every dock
      the window holds, and QtAds finds them by searching the window's dock areas *recursively* -- into a
      nested manager inside one of its docks. Each sub-dock found is pinned into the sidebar and re-homed to
      the manager owning it, while the nested manager still lists it as its own. This guard sends a dock its
      manager never registered back to the nested manager that did.
    - **A pin into a manager that never pins.** Its pin button is hidden (`QtAdsAutoHideButtonSuppressor`), but
      a drop onto one of its borders still pins, and ``DockWidgetPinnable`` gates neither
      ([[appendices.qt-ads#pinnable-is-not-a-lever]]). With ``pins=False`` this guard unpins any dock of its
      own pinned there, back into its container, so the manager never grows a sidebar.

    Both run off ``CDockManager.autoHideWidgetCreated``, which fires on every pin into the manager's sidebars,
    a stolen dock's included (measured). Both are deferred a turn of the event loop, **with this object as the
    context**: the signal is emitted from inside QtAds' drop, which is still walking the dropped window's docks,
    and Qt drops a context-bound call if the manager is torn down first.

    A ``QObject``, parented to ``dock_manager`` -- ``QtAdsPinGuard(dock_manager)`` alone is enough, with nothing
    to hold onto: Qt destroys it along with ``dock_manager``.

    :param dock_manager: the manager whose sidebars to guard.
    :param pins: whether the manager pins its own docks; ``False`` for a nested manager.
    """

    def __init__(self, dock_manager: QtAds.CDockManager, *, pins: bool = True) -> None:
        super().__init__(dock_manager)
        self.__dock_manager: Final = dock_manager
        self.__pins: Final = pins
        dock_manager.autoHideWidgetCreated.connect(self.__on_auto_hide_widget_created)

    def __on_auto_hide_widget_created(self, container: QtAds.CAutoHideDockContainer) -> None:
        """Schedule the undoing of a pin this manager must not hold.

        A foreign dock whose registering manager cannot be found is left pinned: there is no home to send it
        to, and unpinning it would only move it into this manager's container instead.

        :param container: the slide-out panel just created for the pinned dock.
        """
        dock = container.dockWidget()
        if self.__registers(self.__dock_manager, dock):
            if not self.__pins:
                QTimer.singleShot(0, self, partial(self.__unpin, dock))
            return
        home = next(
            (
                manager
                for manager in self.__dock_manager.findChildren(QtAds.CDockManager)
                if self.__registers(manager, dock)
            ),
            None,
        )
        if home is not None:
            QTimer.singleShot(0, self, partial(self.__send_home, dock, home))

    @staticmethod
    def __registers(manager: QtAds.CDockManager, dock: QtAds.CDockWidget) -> bool:
        """Whether ``manager``'s registry holds ``dock`` -- by identity, since two managers may each hold a dock
        of the same name.

        :param manager: the manager.
        :param dock: the dock.
        :returns: whether ``dock`` is one of ``manager``'s own.
        """
        return any(entry is dock for entry in manager.dockWidgetsMap().values())

    @staticmethod
    def __unpin(dock: QtAds.CDockWidget) -> None:
        """Unpin ``dock`` back into its manager's container, unless something already did.

        :param dock: the dock.
        """
        if dock.isAutoHide():
            dock.setAutoHide(False)

    @staticmethod
    def __send_home(dock: QtAds.CDockWidget, home: QtAds.CDockManager) -> None:
        """Move ``dock`` out of this manager's sidebar and back into ``home``, tabbed into its first open area.

        Unpinned first, which drops it into this manager's container, then ``addDockWidget`` -- the call that
        re-homes it, handing the dock back to ``home`` as its manager (measured, #491).

        :param dock: the stolen dock.
        :param home: the manager that registered it.
        """
        if dock.isAutoHide():
            dock.setAutoHide(False)
        home.addDockWidget(QtAds.CenterDockWidgetArea, dock, next(iter(home.openedDockAreas()), None))
