"""Tests for legacy screenshot pattern recognition ([[acquisition-tooling#tc-to-rehu]])."""

from pathlib import Path
from typing import Final

from PIL import UnidentifiedImageError
from pytest_mock import MockerFixture
from rehuco_core import ScreenshotRename, scan_tc_screenshots

DIRECTORY: Final = Path("/fake/tutorial")
STEM: Final = "info"


def mock_directory(mocker: MockerFixture, filenames: list[str]) -> None:
    """Mock ``Path.iterdir`` so :data:`DIRECTORY` appears to hold ``filenames``.

    :param mocker: pytest-mock fixture.
    :param filenames: the fake filenames the directory should list.
    """
    mocker.patch.object(Path, "iterdir", return_value=[Path(name) for name in filenames])


def mock_image_sizes(mocker: MockerFixture, sizes: dict[str, tuple[int, int]]) -> None:
    """Mock ``Image.open`` so opening a path named in ``sizes`` yields that ``(width, height)``.

    :param mocker: pytest-mock fixture.
    :param sizes: ``{filename: (width, height)}`` for every file a tie-break will need to open.
    """

    def open_side_effect(path: Path) -> object:
        image = mocker.MagicMock()
        image.__enter__.return_value.size = sizes[Path(path).name]
        return image

    mocker.patch("rehuco_core.tc_screenshots.Image.open", side_effect=open_side_effect)


def test_bare_numeric_pattern(mocker: MockerFixture) -> None:
    """A bare zero-padded index series maps straight through, one slot per file, no ties.

    **Test steps:**

    * mock the directory to hold ``00.jpg``/``01.png``
    * scan
    * verify each maps to its own new name, unchanged extension
    """
    mock_directory(mocker, ["00.jpg", "01.png"])

    renames = scan_tc_screenshots(DIRECTORY, STEM)

    assert renames == [
        ScreenshotRename("info00.jpg", "00.jpg", ("00.jpg",)),
        ScreenshotRename("info01.png", "01.png", ("01.png",)),
    ]


def test_sample_pattern(mocker: MockerFixture) -> None:
    """A ``sample-NN`` series maps straight through, one slot per file, no ties.

    **Test steps:**

    * mock the directory to hold ``sample-00.jpg``/``sample-01.jpg``
    * scan
    * verify each maps to its own new name
    """
    mock_directory(mocker, ["sample-00.jpg", "sample-01.jpg"])

    renames = scan_tc_screenshots(DIRECTORY, STEM)

    assert renames == [
        ScreenshotRename("info00.jpg", "sample-00.jpg", ("sample-00.jpg",)),
        ScreenshotRename("info01.jpg", "sample-01.jpg", ("sample-01.jpg",)),
    ]


def test_file_series_pattern_is_not_treated_as_duplicates(mocker: MockerFixture) -> None:
    """``file``/``file(1)``/``file(2)`` is a genuine series -- each entry is its own slot, not merged
    together as duplicates of one photo (regression case for the user's mid-session correction).

    **Test steps:**

    * mock the directory to hold ``file.jpg``/``file(1).jpg``/``file(2).jpg``
    * scan
    * verify three separate slots come back, each with exactly one recognized filename
    """
    mock_directory(mocker, ["file.jpg", "file(1).jpg", "file(2).jpg"])

    renames = scan_tc_screenshots(DIRECTORY, STEM)

    assert renames == [
        ScreenshotRename("info00.jpg", "file.jpg", ("file.jpg",)),
        ScreenshotRename("info01.jpg", "file(1).jpg", ("file(1).jpg",)),
        ScreenshotRename("info02.jpg", "file(2).jpg", ("file(2).jpg",)),
    ]


def test_cover_and_file_dash_pattern(mocker: MockerFixture) -> None:
    """``cover``/``file-NN`` maps straight through when no full-size counterpart is present.

    **Test steps:**

    * mock the directory to hold ``cover.jpg``/``file-01.jpg``/``file-02.jpg``
    * scan
    * verify ``cover`` claims index 0 and ``file-NN``'s suffix is the index directly (no offset)
    """
    mock_directory(mocker, ["cover.jpg", "file-01.jpg", "file-02.jpg"])

    renames = scan_tc_screenshots(DIRECTORY, STEM)

    assert renames == [
        ScreenshotRename("info00.jpg", "cover.jpg", ("cover.jpg",)),
        ScreenshotRename("info01.jpg", "file-01.jpg", ("file-01.jpg",)),
        ScreenshotRename("info02.jpg", "file-02.jpg", ("file-02.jpg",)),
    ]


def test_small_variant_ties_with_full_size_and_loses(mocker: MockerFixture) -> None:
    """A thumbnail (``cover``) and a full-size photo (``sample-00``) at the same index: the larger one
    by pixel dimensions wins, and both stay recorded as recognized.

    **Test steps:**

    * mock the directory to hold ``cover.jpg`` (small) and ``sample-00.png`` (large)
    * mock their pixel sizes accordingly
    * scan
    * verify the winner is ``sample-00.png``, and ``recognized_filenames`` holds both
    """
    mock_directory(mocker, ["cover.jpg", "sample-00.png"])
    mock_image_sizes(mocker, {"cover.jpg": (100, 100), "sample-00.png": (1920, 1080)})

    renames = scan_tc_screenshots(DIRECTORY, STEM)

    assert renames == [ScreenshotRename("info00.png", "sample-00.png", ("cover.jpg", "sample-00.png"))]


def test_generalized_tie_break_across_unanticipated_patterns(mocker: MockerFixture) -> None:
    """The size tie-break isn't hardcoded to the small-vs-full-size pairing -- any two recognized
    candidates landing on the same index resolve the same way.

    **Test steps:**

    * mock the directory to hold ``00.jpg`` (bare numeric) and ``sample-00.png`` (sample series),
      an unanticipated pairing
    * mock the bare-numeric file as the larger one
    * scan
    * verify the larger file wins even though its pattern was never described as tying with the other
    """
    mock_directory(mocker, ["00.jpg", "sample-00.png"])
    mock_image_sizes(mocker, {"00.jpg": (1920, 1080), "sample-00.png": (100, 100)})

    renames = scan_tc_screenshots(DIRECTORY, STEM)

    assert renames == [ScreenshotRename("info00.jpg", "00.jpg", ("00.jpg", "sample-00.png"))]


def test_exact_dimension_tie_prefers_jpg_over_png(mocker: MockerFixture) -> None:
    """On an exact pixel-dimension tie, a ``.jpg`` candidate wins over a ``.png`` one.

    **Test steps:**

    * mock the directory to hold ``cover.jpg`` and ``sample-00.png`` at identical dimensions
    * scan
    * verify the ``.jpg`` file wins despite tying on size
    """
    mock_directory(mocker, ["cover.jpg", "sample-00.png"])
    mock_image_sizes(mocker, {"cover.jpg": (800, 600), "sample-00.png": (800, 600)})

    renames = scan_tc_screenshots(DIRECTORY, STEM)

    assert renames == [ScreenshotRename("info00.jpg", "cover.jpg", ("cover.jpg", "sample-00.png"))]


def test_full_tie_falls_back_to_filename_sort(mocker: MockerFixture) -> None:
    """When both size and extension tie, the alphabetically first filename wins, deterministically.

    **Test steps:**

    * mock the directory to hold two same-size ``.jpg`` candidates at the same index
    * scan
    * verify the alphabetically earlier filename is the winner regardless of directory-listing order
    """
    mock_directory(mocker, ["sample-00.jpg", "00.jpg"])
    mock_image_sizes(mocker, {"sample-00.jpg": (800, 600), "00.jpg": (800, 600)})

    renames = scan_tc_screenshots(DIRECTORY, STEM)

    assert renames == [ScreenshotRename("info00.jpg", "00.jpg", ("sample-00.jpg", "00.jpg"))]


def test_pixel_size_ranking_can_pick_the_non_preferred_extension(mocker: MockerFixture) -> None:
    """A bigger ``.png`` still beats a smaller ``.jpg`` -- the extension preference only breaks an
    exact dimension tie, it never overrides a real size difference.

    **Test steps:**

    * mock the directory to hold a large ``cover.png`` and a small ``sample-00.jpg``
    * scan
    * verify the ``.png`` wins and the new name keeps its extension
    """
    mock_directory(mocker, ["cover.png", "sample-00.jpg"])
    mock_image_sizes(mocker, {"cover.png": (1920, 1080), "sample-00.jpg": (100, 100)})

    renames = scan_tc_screenshots(DIRECTORY, STEM)

    assert renames == [ScreenshotRename("info00.png", "cover.png", ("cover.png", "sample-00.jpg"))]


def test_unrecognized_filenames_are_ignored(mocker: MockerFixture) -> None:
    """A filename matching none of the five patterns is left out of the scan entirely.

    **Test steps:**

    * mock the directory to hold one recognized file and one unrelated one
    * scan
    * verify only the recognized file appears in the result
    """
    mock_directory(mocker, ["sample-00.jpg", "random_screenshot.jpg"])

    renames = scan_tc_screenshots(DIRECTORY, STEM)

    assert renames == [ScreenshotRename("info00.jpg", "sample-00.jpg", ("sample-00.jpg",))]


def test_non_image_extensions_are_ignored(mocker: MockerFixture) -> None:
    """A same-named file with an unrecognized extension is left out of the scan.

    **Test steps:**

    * mock the directory to hold ``sample-00.jpg`` and a same-stem ``sample-00.txt``
    * scan
    * verify only the image file is recognized
    """
    mock_directory(mocker, ["sample-00.jpg", "sample-00.txt"])

    renames = scan_tc_screenshots(DIRECTORY, STEM)

    assert renames == [ScreenshotRename("info00.jpg", "sample-00.jpg", ("sample-00.jpg",))]


def test_corrupt_candidate_loses_the_pixel_ranking(mocker: MockerFixture) -> None:
    """A candidate whose bytes ``PIL`` can't decode ranks last, rather than aborting the conversion --
    this runs during `.tc` conversion's plan phase, before any disk mutation, so an unreadable image is
    strictly safer treated as area ``0`` than left to raise.

    **Test steps:**

    * mock the directory to hold a readable ``cover.jpg`` and a same-index ``sample-00.png`` whose
      ``Image.open`` raises ``UnidentifiedImageError``
    * scan
    * verify the readable file wins despite its modest pixel size
    """
    mock_directory(mocker, ["cover.jpg", "sample-00.png"])

    def open_side_effect(path: Path) -> object:
        if Path(path).name == "sample-00.png":
            raise UnidentifiedImageError
        image = mocker.MagicMock()
        image.__enter__.return_value.size = (100, 100)
        return image

    mocker.patch("rehuco_core.tc_screenshots.Image.open", side_effect=open_side_effect)

    renames = scan_tc_screenshots(DIRECTORY, STEM)

    assert renames == [ScreenshotRename("info00.jpg", "cover.jpg", ("cover.jpg", "sample-00.png"))]


def test_missing_directory_returns_an_empty_list(mocker: MockerFixture) -> None:
    """A missing/unreadable directory (e.g. an offline mount) scans to an empty list, not a crash.

    **Test steps:**

    * mock ``Path.iterdir`` to raise ``OSError``
    * scan
    * verify the result is an empty list
    """
    mocker.patch.object(Path, "iterdir", side_effect=OSError)

    assert not scan_tc_screenshots(DIRECTORY, STEM)
