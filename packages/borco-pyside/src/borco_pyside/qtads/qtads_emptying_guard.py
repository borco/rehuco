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

    **How.** As the manager's last dock is about to be removed (``dockWidgetAboutToBeRemoved``, emitted before
    the area goes) under a floating window, a **ballast** dock is parked in an area of its own, closed, so the
    count stays at one. The next dock added unparks it. The ballast is added through the container's own
    ``addDockWidget`` rather than the manager's, so it never enters ``dockWidgetsMap()`` -- a layout save, the
    tab walks and the app's own dock lists never see it -- and its closed area is hidden, taking no room.

    A ``QObject``, parented to ``dock_manager`` -- ``QtAdsEmptyingGuard(dock_manager)`` alone is enough, as for
    ``QtAdsPinGuard``.

    :param dock_manager: the nested manager to keep from emptying.
    """

    def __init__(self, dock_manager: QtAds.CDockManager) -> None:
        super().__init__(dock_manager)
        self.__dock_manager: Final = dock_manager
        self.__ballast: QtAds.CDockWidget | None = None
        dock_manager.dockWidgetAboutToBeRemoved.connect(self.__on_about_to_be_removed)
        dock_manager.dockWidgetAdded.connect(self.__on_added)

    def __on_about_to_be_removed(self, dock: QtAds.CDockWidget) -> None:
        """Park the ballast if removing ``dock`` would leave the manager with no area under a floating window.

        :param dock: the dock about to be removed.
        """
        if self.__ballast is not None or not self.__empties(dock) or self.__dock_manager.floatingWidget() is None:
            return
        ballast = QtAds.CDockWidget(self.__dock_manager, "")
        ballast.setObjectName(BALLAST_NAME)
        QtAds.CDockContainerWidget.addDockWidget(self.__dock_manager, QtAds.CenterDockWidgetArea, ballast)
        ballast.toggleView(False)
        self.__ballast = ballast

    def __empties(self, dock: QtAds.CDockWidget) -> bool:
        """Whether ``dock`` is all the manager's own container holds.

        :param dock: one of the manager's docks.
        :returns: whether removing it would leave the container with no area.
        """
        area = dock.dockAreaWidget()
        return (
            area is not None
            and not dock.isAutoHide()
            and area.dockContainer() is self.__dock_manager
            and self.__dock_manager.dockAreaCount() == 1
            and area.dockWidgetsCount() == 1
        )

    def __on_added(self, dock: QtAds.CDockWidget) -> None:
        """Unpark the ballast once a dock has joined the manager -- in an area of its own, or the ballast's.

        :param dock: the dock just added.
        """
        ballast = self.__ballast
        if ballast is None or dock is ballast or self.__empties(ballast):
            return
        self.__ballast = None
        QtAds.CDockContainerWidget.removeDockWidget(self.__dock_manager, ballast)
        ballast.deleteLater()
