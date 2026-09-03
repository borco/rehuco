"""Tests for current ``.rehu`` screenshot recognition ([[data-model#image-meanings]])."""

from pathlib import Path
from typing import Final

from pytest_mock import MockerFixture
from rehuco_core import scan_rehu_screenshot_files

DIRECTORY: Final = Path("/fake/tutorial")
STEM: Final = "info"


def test_matches_stem_numbered_siblings(mocker: MockerFixture) -> None:
    """Returns the ``<stem>NN`` image siblings, sorted, ignoring everything else.

    **Test steps:**

    * mock the directory to hold matching ``info00``/``info01``/``info02`` (one ``.webp``), plus a
      non-image, a mismatched-stem, and a single-digit sibling
    * scan
    * verify only the three screenshots come back, sorted by name
    """
    siblings = [
        DIRECTORY / "info01.png",
        DIRECTORY / "info00.jpg",
        DIRECTORY / "info02.webp",
        DIRECTORY / "info.rehu",
        DIRECTORY / "info00.txt",
        DIRECTORY / "cover.jpg",
        DIRECTORY / "info0.jpg",
    ]
    mocker.patch.object(Path, "iterdir", return_value=siblings)

    assert scan_rehu_screenshot_files(DIRECTORY, STEM) == [
        DIRECTORY / "info00.jpg",
        DIRECTORY / "info01.png",
        DIRECTORY / "info02.webp",
    ]


def test_matches_stem_and_extension_case_insensitively(mocker: MockerFixture) -> None:
    """The ``<stem>NN`` prefix and the image extension both match case-insensitively.

    **Test steps:**

    * mock the directory to hold ``INFO00.JPG``
    * scan
    * verify it is recognized
    """
    mocker.patch.object(Path, "iterdir", return_value=[DIRECTORY / "INFO00.JPG"])

    assert scan_rehu_screenshot_files(DIRECTORY, STEM) == [DIRECTORY / "INFO00.JPG"]


def test_is_empty_when_nothing_matches(mocker: MockerFixture) -> None:
    """A directory holding no ``<stem>NN`` siblings scans to empty.

    **Test steps:**

    * mock the directory to hold only unrelated files
    * scan
    * verify the result is empty
    """
    mocker.patch.object(Path, "iterdir", return_value=[DIRECTORY / "cover.jpg", DIRECTORY / "info.rehu"])

    assert scan_rehu_screenshot_files(DIRECTORY, STEM) == []


def test_missing_directory_returns_an_empty_list(mocker: MockerFixture) -> None:
    """A missing/unreadable directory (e.g. an offline mount) scans to empty, not a crash.

    **Test steps:**

    * mock ``Path.iterdir`` to raise ``FileNotFoundError``
    * scan
    * verify the result is empty
    """
    mocker.patch.object(Path, "iterdir", side_effect=FileNotFoundError)

    assert scan_rehu_screenshot_files(DIRECTORY, STEM) == []
