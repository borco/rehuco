"""A small manager for a list of signal connections, so they can be disconnected together."""

from collections.abc import Callable
from typing import Any, Final

from PySide6.QtCore import QMetaObject, QObject, SignalInstance


class ConnectionList:
    """Tracks :class:`QMetaObject.Connection` handles so they can be disconnected as a group.

    The use case is lifetime-scoping a connection whose slot is **not** a bound method of a `QObject` --
    a lambda or a method of a plain Python object -- which Qt therefore does not auto-disconnect when the
    captured widget is destroyed. Collect such a connection here and :meth:`clear` it -- most naturally
    via :meth:`clear_on_destroyed`, wired to a widget's ``destroyed`` signal -- so the slot never fires
    into a deleted object. A slot that *is* a bound method of a `QObject` needs none of this -- Qt drops
    it automatically -- so reach for this only for the cases that aren't covered for free.
    """

    def __init__(self) -> None:
        self.__connections: Final[list[QMetaObject.Connection]] = []

    def clear(self) -> None:
        """Disconnect every tracked connection and forget them.

        Idempotent: a second call finds the list already empty and does nothing.
        """
        for connection in self.__connections:
            QObject.disconnect(connection)
        self.__connections.clear()

    def setup(self, *connections: QMetaObject.Connection) -> None:
        """Replace the tracked connections with ``connections``, disconnecting any held before.

        :param connections: the connections to track from now on.
        """
        self.clear()
        self.__connections.extend(connections)

    def append(self, connection: QMetaObject.Connection) -> None:
        """Track one more connection.

        :param connection: the connection handle returned by a ``signal.connect(...)`` call.
        """
        self.__connections.append(connection)

    def connect(self, signal: SignalInstance, slot: Callable[..., Any]) -> None:
        """Connect ``signal`` to ``slot`` and track the resulting connection in one step.

        The common case, saving the ``list.append(signal.connect(slot))`` dance.

        :param signal: the signal to connect.
        :param slot: the slot to connect it to (typically the lambda/plain-object method that makes
            tracking necessary in the first place).
        """
        self.__connections.append(signal.connect(slot))

    def clear_on_destroyed(self, guard: QObject) -> None:
        """Arrange for :meth:`clear` to run when ``guard`` is destroyed, scoping the tracked connections
        to its lifetime.

        The connection to ``guard.destroyed`` is itself auto-dropped by Qt when ``guard`` dies (``guard``
        is its sender), so this adds no lingering connection of its own. Wiring more than one guard is
        fine -- :meth:`clear` is idempotent, so whichever is destroyed first severs the connections.

        :param guard: the object whose destruction should disconnect the tracked connections.
        """
        guard.destroyed.connect(self.clear)
