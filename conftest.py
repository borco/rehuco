"""Repository-wide pytest configuration: headless Qt platform, per-test deferred deletion, and
platform-conditional test skipping.

CI runs each platform's test set on that platform's runner before building the matching
Briefcase package (§16.8), so a marker/platform mismatch here means "not applicable on this
runner," not a failure.
"""

import os
import sys
from collections.abc import Callable, Iterator
from typing import Any, Final, TypeVar

import pytest

# Qt tests must run headless. Without an active window server -- CI runners, or macOS over SSH --
# the cocoa/xcb platform plugin drives a real native event loop and segfaults during
# QLocalServer/QLocalSocket teardown across tests. The offscreen plugin avoids it. setdefault so a
# developer can still override (QT_QPA_PLATFORM=cocoa) to watch windows during local GUI debugging.
# None of the imports above pull in Qt, and pytest-qt builds the QApplication only later (during a
# test), so setting this here -- before any test module runs -- is early enough.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# (Coverage exclusion of Windows-only code on non-Windows is handled by the coverage_platform
# plugin, not here -- it's runner-independent, unlike an env var set at conftest import time.)

PLATFORM_MARKERS: Final = {
    "windows": "win32",
    "macos": "darwin",
    "linux": "linux",
}
"""Maps a platform marker name to the ``sys.platform`` value it requires."""


@pytest.hookimpl(hookwrapper=True, trylast=True)
def pytest_runtest_teardown() -> Iterator[None]:
    """Delete what the test left to ``deleteLater``, once every teardown -- pytest-qt's included -- ran.

    pytest-qt closes a test's widgets with ``deleteLater`` and then only processes events, which runs
    no deferred deletion outside an event loop. Left alone, the deletions pile up across the suite
    until some later test's first wait drains them all inside its own timeout, and deleting gets
    dearer the more objects are still alive: 17k command-bound actions behind a 120 s drain on WSL.

    Qt is only touched when a test already loaded it, so non-Qt packages never import it here.
    """
    yield
    qt_core = sys.modules.get("PySide6.QtCore")
    if qt_core is not None and qt_core.QCoreApplication.instance() is not None:
        qt_core.QCoreApplication.sendPostedEvents(None, qt_core.QEvent.Type.DeferredDelete)


QObjectT = TypeVar("QObjectT")
"""Whatever `QObject` :func:`delete_at_teardown` is handed, handed back as itself -- unbound, since this module
imports no Qt."""


@pytest.fixture
def delete_at_teardown() -> Iterator[Callable[[QObjectT], QObjectT]]:
    """Hand a test a function that registers a `QObject` to be deleted when the test ends (#529).

    For an object the app would parent and a test builds bare -- a catalog, a model, the file announcements --
    the counterpart of ``qtbot.addWidget`` for a `QObject` that is not a widget. Left alone such an object, once in
    a reference cycle, is destroyed by the cyclic collector on whichever thread allocates next, which can deadlock
    against the GUI thread. The delete is handed to ``deleteLater``, which :func:`pytest_runtest_teardown` drains
    once every teardown ran.

    :returns: the function, which returns the object it was handed.
    """
    registered: list[Any] = []

    def register(qobject: QObjectT) -> QObjectT:
        """Delete ``qobject`` when the test ends.

        :param qobject: the object.
        :returns: ``qobject``.
        """
        registered.append(qobject)
        return qobject

    yield register
    for qobject in registered:
        try:
            qobject.deleteLater()
        except RuntimeError:  # the test deleted it itself, which is what some tests are about
            pass


def pytest_sessionfinish() -> None:
    """Leave the clipboard empty before the process exits, under the offscreen platform.

    A process that exits while the clipboard holds a ``QMimeData`` made in Python segfaults in Qt's teardown, after
    every test passed (measured on all three platforms; exit 139, or ``0xC0000005`` on Windows). Only a serial run
    shows it -- under xdist the crash is a worker's, and goes unreported. A test that copies takes the ``clipboard``
    fixture, but one that copies without it leaves data a later test's fixture then restores as just such an object.

    Not on a real platform, where clearing would lose what the developer had on the clipboard. Qt is only touched
    when a test already loaded it.
    """
    qt_gui = sys.modules.get("PySide6.QtGui")
    if os.environ.get("QT_QPA_PLATFORM") != "offscreen" or qt_gui is None:
        return
    app = qt_gui.QGuiApplication.instance()
    if app is not None:
        qt_gui.QGuiApplication.clipboard().clear()


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip collected tests marked for a platform other than the one currently running.

    :param items: collected test items to filter in place.
    """
    for item in items:
        for marker_name, required_platform in PLATFORM_MARKERS.items():
            if item.get_closest_marker(marker_name) and sys.platform != required_platform:
                item.add_marker(pytest.mark.skip(reason=f"{marker_name}-only test (running on {sys.platform})"))
