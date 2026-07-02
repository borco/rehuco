"""Repository-wide pytest configuration: platform-conditional test skipping.

CI runs each platform's test set on that platform's runner before building the matching
Briefcase package (§16.8), so a marker/platform mismatch here means "not applicable on this
runner," not a failure.
"""

import sys
from typing import Final

import pytest

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
