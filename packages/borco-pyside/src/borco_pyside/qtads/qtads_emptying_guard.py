"""Keeps a nested `CDockManager` from emptying, which would delete the floating window above it."""

from typing import Final

import PySide6QtAds as QtAds
from PySide6.QtCore import QObject

BALLAST_NAME: Final = "qtads-emptying-guard-ballast"
"""The ballast dock's object name -- never registered, but named so nothing mistakes it for a dock of the app's."""


class QtAdsEmptyingGuard(QObject):
    """Never lets a nested manager's last area go while a floating window is above it (#493).

    **What it stops.** When an area loses its last dock and its container is left with no area, QtAds retires
    the container's floating window -- ``finishDropOperation()``: hidden, its areas let go, deleted. It finds
    that window with ``floatingWidget()``, which answers the nearest floating window *above* a container, so a
    nested manager emptied inside a dock of an outer floating window deletes the **outer** window, every dock
    in it included ([[appendices.qt-ads#nested-emptied-float]]). Nothing undoes that afterwards.

    **How.** The moment the container is left with no area -- ``dockAreasRemoved``, which QtAds emits as the area
    goes and *before* it tests the count -- a **ballast** dock is parked in an area of its own, closed, so the count
    is one again by the time QtAds looks. That signal sits inside every removal path: a dock removed from the
    manager, closed with ``DockWidgetDeleteOnClose``, or dragged off its area by a drop (``dropWidget`` and the
    drag-preview drops call the area's own ``removeDockWidget``, which the manager's removal signals never hear;
    measured). The next dock added unparks it -- through the manager (``dockWidgetAdded``) or by a drop
    (``dockAreasAdded``). Both run synchronously, so a layout restore reading the areas right after an add finds
    the ballast gone. The ballast is added through the container's own ``addDockWidget`` rather than the
    manager's, so it never enters ``dockWidgetsMap()`` -- a layout save, the tab walks and the app's own dock lists
    never see it -- and its closed area is hidden, taking no room.

    A ``QObject``, parented to ``dock_manager`` -- ``QtAdsEmptyingGuard(dock_manager)`` alone is enough, as for
    ``QtAdsPinGuard``.

    :param dock_manager: the nested manager to keep from emptying.
    """

    def __init__(self, dock_manager: QtAds.CDockManager) -> None:
        super().__init__(dock_manager)
        self.__dock_manager: Final = dock_manager
        self.__ballast: QtAds.CDockWidget | None = None
        dock_manager.dockAreasRemoved.connect(self.__on_areas_removed)
        dock_manager.dockWidgetAdded.connect(self.__unpark)
        dock_manager.dockAreasAdded.connect(self.__unpark)

    def __on_areas_removed(self) -> None:
        """Park the ballast if the manager was just left with no area under a floating window."""
        if (
            self.__ballast is not None
            or self.__dock_manager.dockAreaCount()
            or self.__dock_manager.floatingWidget() is None
        ):
            return
        ballast = QtAds.CDockWidget(self.__dock_manager, "")
        ballast.setObjectName(BALLAST_NAME)
        QtAds.CDockContainerWidget.addDockWidget(self.__dock_manager, QtAds.CenterDockWidgetArea, ballast)
        ballast.toggleView(False)
        self.__ballast = ballast

    def __unpark(self) -> None:
        """Take the ballast out once a dock has joined the manager -- in an area of its own, or the ballast's. A dock
        that joined none of the main container's areas (floated out of the manager) leaves the ballast alone there;
        taking it out empties the container, and the removal parks a fresh one before QtAds looks."""
        ballast = self.__ballast
        if ballast is None:
            return
        self.__ballast = None
        QtAds.CDockContainerWidget.removeDockWidget(self.__dock_manager, ballast)
        ballast.deleteLater()
