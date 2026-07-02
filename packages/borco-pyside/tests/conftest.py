"""pytest fixtures for borco-pyside."""

from collections.abc import Callable, Iterator
from typing import Any

from borco_pyside.core import ApplicationSingleton
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
    qtbot.wait(10)
