"""The document docks a session restored and has not read yet ([[plugins#session-restore]], #66)."""

from collections.abc import Callable
from typing import Final

import PySide6QtAds as QtAds
from PySide6.QtCore import QObject


class PendingDocks(QObject):
    """Docks made by a session restore whose document is read the first time it actually reaches the screen (#66).

    Two triggers cover every way there. The dock's own ``visibilityChanged``, watched here, stays silent while the
    window is still hidden, fires once per area's current tab when it first shows, and again on every later tab reveal.
    The programmatic focus routes that bypass real visibility -- a re-open by path, the ``File`` menu, the session's
    remembered focus -- call :meth:`load` themselves. An entry is settled by whichever comes first, or by the dock
    closing unviewed (:meth:`settle`).

    :param read: reads a dock's document.
    :param parent: the Qt parent.
    """

    def __init__(self, read: Callable[[QtAds.CDockWidget], None], parent: QObject) -> None:
        super().__init__(parent)
        self.__read: Final = read
        self.__docks: Final[set[QtAds.CDockWidget]] = set()
        self.restoring = False
        """True only while a restore is (re)creating docks: QtAds shows each tab it adds and makes it current, and while
        a restore adds them, shown is not seen (#574), so nothing is read for it."""

    def __bool__(self) -> bool:
        return bool(self.__docks)

    def add(self, dock: QtAds.CDockWidget) -> None:
        """Wait for a dock to reach the screen.

        :param dock: the dock of a document not read yet.
        """
        self.__docks.add(dock)
        dock.visibilityChanged.connect(self.__on_visibility_changed)

    def settle(self, dock: QtAds.CDockWidget) -> bool:
        """Stop waiting for ``dock``: the funnel every way out of the pending state passes through, so a dock can never
        be settled twice.

        :param dock: the dock to settle.
        :returns: whether it was actually pending -- ``False`` for the overwhelmingly common already-loaded (or
            never-lazy) dock, which callers use to skip their follow-up.
        """
        if dock not in self.__docks:
            return False
        self.__docks.discard(dock)
        dock.visibilityChanged.disconnect(self.__on_visibility_changed)
        return True

    def load(self, dock: QtAds.CDockWidget) -> None:
        """Read ``dock``'s document now, if it is still waiting. Settled first, so nothing re-triggered by the read's
        own signal storm can re-enter it.

        :param dock: the dock whose document to load, if it is pending.
        """
        if self.settle(dock):
            self.__read(dock)

    def __on_visibility_changed(self, visible: bool) -> None:
        """Load a pending dock's document the moment its tab actually reaches the screen; ``sender()`` is the dock,
        since the signal carries only the new visibility.

        :param visible: whether the dock just appeared (``True``) or was covered or hidden.
        """
        dock = self.sender()
        if visible and not self.restoring and isinstance(dock, QtAds.CDockWidget):
            self.load(dock)
