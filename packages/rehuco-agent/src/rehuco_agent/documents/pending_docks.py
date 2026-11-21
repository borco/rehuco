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

    **A held dock is not read by either** (#698): its file is on storage that has not answered, and reading it would
    hold a thread for as long as a switched-off server takes to time out. Each time it would have been read -- its tab
    shown, a focus route -- ``ask`` is called instead, to have the storage asked again, and :meth:`release` lets it be
    read once the storage has answered.

    :param read: reads a dock's document.
    :param ask: asks the storage of a held dock's document again.
    :param parent: the Qt parent.
    """

    def __init__(
        self, read: Callable[[QtAds.CDockWidget], None], ask: Callable[[QtAds.CDockWidget], None], parent: QObject
    ) -> None:
        super().__init__(parent)
        self.__read: Final = read
        self.__ask: Final = ask
        self.__docks: Final[set[QtAds.CDockWidget]] = set()
        self.__held: Final[set[QtAds.CDockWidget]] = set()
        """The pending docks whose storage has not answered."""
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

    def hold(self, dock: QtAds.CDockWidget) -> None:
        """Keep a pending dock from being read until its storage answers (:meth:`release`).

        :param dock: a dock that was added.
        """
        if dock in self.__docks:
            self.__held.add(dock)

    def is_held(self, dock: QtAds.CDockWidget) -> bool:
        """Whether a dock waits for its storage.

        :param dock: the dock.
        :returns: the answer.
        """
        return dock in self.__held

    def release(self, dock: QtAds.CDockWidget, *, load: bool = False) -> None:
        """Let a held dock be read: its storage answered. It is read now if it is on screen, else when it gets there.

        :param dock: a held dock.
        :param load: read it now wherever it is -- something of it covers more than its own tab.
        """
        self.__held.discard(dock)
        if load or (dock.isVisible() and not self.restoring):
            self.load(dock)

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
        self.__held.discard(dock)
        dock.visibilityChanged.disconnect(self.__on_visibility_changed)
        return True

    def load(self, dock: QtAds.CDockWidget) -> None:
        """Read ``dock``'s document now, if it is still waiting. Settled first, so nothing re-triggered by the read's
        own signal storm can re-enter it. A held dock is not read: its storage is asked again.

        :param dock: the dock whose document to load, if it is pending.
        """
        if dock in self.__held:
            self.__ask(dock)
        elif self.settle(dock):
            self.__read(dock)

    def __on_visibility_changed(self, visible: bool) -> None:
        """Load a pending dock's document the moment its tab actually reaches the screen; ``sender()`` is the dock,
        since the signal carries only the new visibility.

        :param visible: whether the dock just appeared (``True``) or was covered or hidden.
        """
        dock = self.sender()
        if visible and not self.restoring and isinstance(dock, QtAds.CDockWidget):
            self.load(dock)
