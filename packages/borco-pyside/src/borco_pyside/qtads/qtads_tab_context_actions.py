"""Extra actions at the top of a dock tab's context menu."""

from collections.abc import Callable, Sequence
from typing import Final

import PySide6QtAds as QtAds
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QAction, QContextMenuEvent
from PySide6.QtWidgets import QMenu


class QtAdsTabContextActions(QObject):
    """Puts a dock's own actions on top of its tab's right-click menu, above QtAds' *Detach* / *Close*
    and set apart from them by a separator.

    QtAds builds that menu inside ``CDockWidgetTab.contextMenuEvent`` and shows it itself, with no hook
    to add to it. So the event is taken at the tab, and the menu is built the way QtAds builds it --
    ``CDockWidgetTab.buildContextMenu`` fills a menu it is handed -- with the actions put in front
    before it is shown (``popup``, not ``exec``: nothing blocks, and the menu deletes itself on
    close). Only the docks passed to :meth:`add` are touched; every other tab keeps QtAds' own menu.

    A dock removed from the manager is forgotten, so nothing keeps it alive.

    A ``QObject``, parented to ``dock_manager``, so the filters it installs go with it.

    :param dock_manager: the manager whose docks may be extended.
    """

    def __init__(self, dock_manager: QtAds.CDockManager) -> None:
        super().__init__(dock_manager)
        self.__docks: Final[dict[QObject, QtAds.CDockWidget]] = {}
        self.__actions: Final[dict[QtAds.CDockWidget, Sequence[QAction]]] = {}
        self.__on_open: Final[dict[QtAds.CDockWidget, Callable[[], None] | None]] = {}
        dock_manager.dockWidgetAboutToBeRemoved.connect(self.__forget)

    def add(
        self, dock: QtAds.CDockWidget, actions: Sequence[QAction], on_open: Callable[[], None] | None = None
    ) -> None:
        """Show ``actions`` at the top of ``dock``'s tab menu.

        :param dock: the dock whose tab menu to extend.
        :param actions: the actions to put first, in order.
        :param on_open: called just before the menu is built, e.g. to make ``dock`` the current one so
            that actions enabled by current-ness read right.
        """
        tab = dock.tabWidget()
        self.__docks[tab] = dock  # pylint: disable=unsupported-assignment-operation
        self.__actions[dock] = actions  # pylint: disable=unsupported-assignment-operation
        self.__on_open[dock] = on_open  # pylint: disable=unsupported-assignment-operation
        tab.installEventFilter(self)

    def __forget(self, dock: QtAds.CDockWidget) -> None:
        """Drop ``dock``, as it leaves the manager.

        :param dock: the dock QtAds is about to remove.
        """
        if self.__actions.pop(dock, None) is None:
            return
        self.__on_open.pop(dock, None)
        tab = dock.tabWidget()
        self.__docks.pop(tab, None)
        tab.removeEventFilter(self)

    def menu_for(self, dock: QtAds.CDockWidget) -> QMenu:
        """``dock``'s tab menu: QtAds' own, with the added actions and a separator in front.

        :param dock: a dock passed to :meth:`add`.
        :returns: a menu parented to the tab, for the caller to show.
        """
        tab = dock.tabWidget()
        menu = QMenu(tab)
        tab.buildContextMenu(menu)
        entries = menu.actions()
        if entries:
            menu.insertActions(entries[0], list(self.__actions[dock]))
            menu.insertSeparator(entries[0])
        else:  # pragma: no cover  (verified empirically: QtAds always fills it)
            menu.addActions(list(self.__actions[dock]))
        return menu

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802  (Qt override)
        """Show the extended menu in place of QtAds' own for a right-click on an added dock's tab.

        :param watched: a tab.
        :param event: the event about to be delivered.
        :returns: ``True`` for a context menu it showed, else ``False``.
        """
        dock = self.__docks.get(watched)
        if dock is None or not isinstance(event, QContextMenuEvent):
            return False
        on_open = self.__on_open[dock]
        if on_open is not None:
            on_open()
        menu = self.menu_for(dock)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.popup(event.globalPos())
        return True
