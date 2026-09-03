"""Qt waits shared across the agent's tests."""

from collections.abc import Generator
from contextlib import contextmanager

from PySide6.QtCore import QObject
from pytestqt.qtbot import QtBot


@contextmanager
def wait_destroyed(qtbot: QtBot, obj: QObject) -> Generator[None]:
    """Run the block, then wait until ``obj`` has actually been destroyed.

    Used instead of ``qtbot.waitSignal(obj.destroyed)``: pytest-qt disconnects its own slot once the
    wait finishes, and by then the sender's C++ object is gone, which PySide reports as a
    ``RuntimeWarning: libpyside: Failed to disconnect``. Recording the destruction in a plain closure
    that is never disconnected leaves no such teardown to go wrong, while asserting the same thing --
    ``waitUntil`` raises if the object is still alive when the timeout runs out.

    Deferred deletion is covered: ``waitUntil`` polls through ``QTest.qWait``, which flushes pending
    ``DeferredDelete`` events, so a ``deleteLater``-d (or ``WA_DeleteOnClose``) object is collected
    inside the wait rather than left for whatever runs next.

    :param qtbot: pytest-qt fixture driving the wait.
    :param obj: the object expected to be destroyed by the block.
    """
    destroyed: list[bool] = []
    obj.destroyed.connect(lambda: destroyed.append(True))
    yield
    qtbot.waitUntil(lambda: bool(destroyed))
