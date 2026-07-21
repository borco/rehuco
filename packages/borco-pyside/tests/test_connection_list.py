"""Tests for ConnectionList: grouped disconnection and lifetime-scoping of signal connections."""

from borco_pyside.core import ConnectionList
from PySide6.QtCore import QObject, Signal
from pytestqt.qtbot import QtBot


class Emitter(QObject):
    """A minimal signal source for the tests."""

    fired = Signal()


def test_clear_disconnects_tracked_connections() -> None:
    """``clear`` disconnects every tracked connection, so the slot stops firing.

    **Test steps:**

    * track a lambda connection to a signal, then emit and confirm it fired
    * clear the list, emit again, and verify the slot is no longer called
    """
    emitter = Emitter()
    calls: list[None] = []
    connections = ConnectionList()
    connections.connect(emitter.fired, lambda: calls.append(None))

    emitter.fired.emit()
    assert len(calls) == 1

    connections.clear()
    emitter.fired.emit()
    assert len(calls) == 1


def test_clear_is_idempotent() -> None:
    """Clearing an already-cleared list does nothing (no error).

    **Test steps:**

    * track one connection, clear twice
    * verify the second clear is harmless
    """
    emitter = Emitter()
    connections = ConnectionList()
    connections.connect(emitter.fired, lambda: None)

    connections.clear()
    connections.clear()  # must not raise


def test_append_tracks_a_connection_made_separately() -> None:
    """``append`` tracks a connection handle produced by a separate ``connect`` call.

    **Test steps:**

    * connect a signal, then ``append`` the returned handle
    * clear the list and verify the slot no longer fires
    """
    emitter = Emitter()
    calls: list[None] = []
    connections = ConnectionList()
    connections.append(emitter.fired.connect(lambda: calls.append(None)))

    connections.clear()
    emitter.fired.emit()

    assert not calls


def test_setup_replaces_previously_tracked_connections() -> None:
    """``setup`` disconnects what was held before adopting the new connections.

    **Test steps:**

    * track a first connection, then ``setup`` a second in its place
    * emit, and verify only the second slot fires
    """
    emitter = Emitter()
    first: list[None] = []
    second: list[None] = []
    connections = ConnectionList()
    connections.connect(emitter.fired, lambda: first.append(None))

    connections.setup(emitter.fired.connect(lambda: second.append(None)))

    emitter.fired.emit()
    assert not first
    assert len(second) == 1


def test_clear_on_destroyed_severs_connections_when_the_guard_dies(qtbot: QtBot) -> None:
    """``clear_on_destroyed`` scopes the tracked connections to a guard's lifetime -- once the guard is
    destroyed, the connections are gone.

    **Test steps:**

    * track a connection and scope it to a guard `QObject`
    * delete the guard and let its ``destroyed`` fire
    * emit, and verify the slot no longer fires
    """
    emitter = Emitter()
    guard = QObject()
    calls: list[None] = []
    connections = ConnectionList()
    connections.connect(emitter.fired, lambda: calls.append(None))
    connections.clear_on_destroyed(guard)

    guard.deleteLater()
    qtbot.wait(1)

    emitter.fired.emit()
    assert not calls
