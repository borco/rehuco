"""Repository-wide pytest configuration: headless Qt platform + platform-conditional test skipping.

CI runs each platform's test set on that platform's runner before building the matching
Briefcase package (§16.8), so a marker/platform mismatch here means "not applicable on this
runner," not a failure.
"""

import os
import sys
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


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip collected tests marked for a platform other than the one currently running.

    :param items: collected test items to filter in place.
    """
    for item in items:
        for marker_name, required_platform in PLATFORM_MARKERS.items():
            if item.get_closest_marker(marker_name) and sys.platform != required_platform:
                item.add_marker(pytest.mark.skip(reason=f"{marker_name}-only test (running on {sys.platform})"))
