"""pytest fixtures for borco-pyside."""

from collections.abc import Callable, Iterator
from typing import Any

from borco_pyside.core import ApplicationSingleton
from PySide6.QtCore import QCoreApplication, QEvent
from pytest import fixture
from pytestqt.qtbot import QtBot


@fixture
def make_singleton(qtbot: QtBot) -> Iterator[Callable[..., ApplicationSingleton]]:
    """Provide a factory for :class:`ApplicationSingleton` that tears each one down cleanly.

    Created instances are shut down and their pending Qt events drained before the Python
    objects are garbage-collected, so no queued signal fires on a freed object in a later test.

    :param qtbot: pytest-qt bot, ensuring a QApplication exists and draining events on teardown.
    :returns: a factory that builds and registers an :class:`ApplicationSingleton`.
    """
    created: list[ApplicationSingleton] = []

    def factory(**kwargs: Any) -> ApplicationSingleton:
        singleton = ApplicationSingleton(**kwargs)
        created.append(singleton)
        return singleton

    yield factory

    for singleton in created:
        singleton.shutdown()
    # shutdown() schedules each QLocalServer and its accepted QLocalSockets for destruction via
    # deleteLater(). qtbot.wait() runs a nested event loop, but DeferredDelete events posted at a
    # different loop level are not reliably reaped there; on Linux's glib dispatcher they instead
    # pile up across tests and later segfault when a server is finally destroyed after a child
    # socket was already freed. Flush them explicitly so each test disposes of its own Qt objects
    # (QT_QPA_PLATFORM=offscreen alone is not enough on Linux — see docs testing.md §A04.2).
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    qtbot.wait(10)
