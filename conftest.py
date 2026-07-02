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

# rehuco_agent's Windows-only code -- the platforms/windows/ package and __main__'s
# `if sys.platform == "win32":` branches -- can't execute off Windows, so it counts as missed
# there. On non-Windows, omit/exclude it from coverage; consumed by pyproject.toml's coverage
# config (${COV_OMIT_WIN-...} and ${COV_EXCLUDE_WIN-...}). Setting it here (not only in the
# Makefile) makes it apply to a bare `pytest --cov` and the VSCode test runner, which don't go
# through make. This repo-root conftest is loaded before pytest-cov reads the coverage config on a
# rootdir invocation. Left unset on Windows, where the Windows test set measures that code.
if sys.platform != "win32":
    os.environ.setdefault("COV_OMIT_WIN", "*/platforms/windows/*")
    os.environ.setdefault("COV_EXCLUDE_WIN", 'if sys.platform == "win32":')

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
