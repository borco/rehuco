"""Repository-wide pytest configuration: headless Qt platform, per-test deferred deletion, and
platform-conditional test skipping.

CI runs each platform's test set on that platform's runner before building the matching
Briefcase package (§16.8), so a marker/platform mismatch here means "not applicable on this
runner," not a failure.
"""

import os
import sys
from collections.abc import Iterator
from typing import Final

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


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip collected tests marked for a platform other than the one currently running.

    :param items: collected test items to filter in place.
    """
    for item in items:
        for marker_name, required_platform in PLATFORM_MARKERS.items():
            if item.get_closest_marker(marker_name) and sys.platform != required_platform:
                item.add_marker(pytest.mark.skip(reason=f"{marker_name}-only test (running on {sys.platform})"))
