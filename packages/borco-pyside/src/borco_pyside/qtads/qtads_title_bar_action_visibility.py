"""Title-bar buttons that show and hide with their actions."""

from typing import Final

import PySide6QtAds as QtAds
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QToolButton


class QtAdsTitleBarActionVisibility(QObject):
    """Keeps a dock's title-bar buttons as visible as the actions they carry.

    QtAds builds one ``QToolButton`` per title-bar action, and a tool button copies its action's text, icon, tooltip
    and enabled state but **not** its visibility: an action hidden because it does not apply to the selected row
    still shows its button. QtAds also builds those buttons again each time the dock becomes its area's current one,
    visible whatever the action says. So every change of an action is answered by setting its button's visibility,
    and so is the dock becoming visible, which is when the buttons are new.

    A ``QObject``, parented to the dock, so it goes with it.

    :param dock: the dock whose title-bar actions were already set.
    """

    def __init__(self, dock: QtAds.CDockWidget) -> None:
        super().__init__(dock)
        self.__dock: Final = dock
        self.__actions: Final = tuple(dock.titleBarActions())
        for action in self.__actions:
            action.changed.connect(self.sync)
        dock.visibilityChanged.connect(self.sync)
        self.sync()

    def sync(self, *_args: object) -> None:
        """Show each button as its action is shown.

        :param _args: whatever the triggering signal carried; unused.
        """
        area = self.__dock.dockAreaWidget()
        if area is None:
            return
        for button in area.titleBar().findChildren(QToolButton):
            action = button.defaultAction()
            if action in self.__actions:
                button.setVisible(action.isVisible())
