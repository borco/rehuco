"""Tests for legacy screenshot pattern recognition ([[acquisition-tooling#tc-to-rehu]], #287)."""

from pathlib import Path
from typing import Final

from PIL import UnidentifiedImageError
from pytest import mark, param
from pytest_mock import MockerFixture
from rehuco_core import (
    SCREENSHOT_NAME_PATTERNS,
    ScreenshotNamePattern,
    ScreenshotNamePatterns,
    ScreenshotRename,
    is_legacy_screenshot,
    scan_tc_screenshot_files,
    scan_tc_screenshots,
    screenshot_name_patterns_from_state,
    screenshot_name_patterns_state,
)

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


# region scan_tc_screenshots (the rename plan)


def test_each_recognized_file_takes_the_slot_its_name_carries(mocker: MockerFixture) -> None:
    """With no two files on one slot, a scan is the slot each name carries and nothing more -- whichever
    shipped pattern named it -- keeping the file's own extension.

    **Test steps:**

    * mock the directory to hold one file under each of three shipped patterns
    * scan
    * verify each maps to its own new name, in slot order
    """
    mock_directory(mocker, ["file(2).jpg", "cover.jpg", "sample-01.png"])

    renames = scan_tc_screenshots(DIRECTORY, STEM)

    assert renames == [
        ScreenshotRename("info00.jpg", "cover.jpg", ("cover.jpg",)),
        ScreenshotRename("info01.png", "sample-01.png", ("sample-01.png",)),
        ScreenshotRename("info02.jpg", "file(2).jpg", ("file(2).jpg",)),
    ]


def test_small_variant_ties_with_full_size_and_loses(mocker: MockerFixture) -> None:
    """A thumbnail (``cover``) and a full-size photo (``sample-00``) at the same slot: the larger one
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
    candidates landing on the same slot resolve the same way.

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

    * mock the directory to hold two same-size ``.jpg`` candidates at the same slot
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
    """A filename matching none of the shipped patterns is left out of the scan entirely.

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

    * mock the directory to hold a readable ``cover.jpg`` and a same-slot ``sample-00.png`` whose
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


def test_a_directory_is_scanned_with_the_patterns_it_was_given(mocker: MockerFixture) -> None:
    """The pattern set is the caller's, so a user-added series converts like any shipped one.

    **Test steps:**

    * mock a directory holding a series no shipped pattern recognizes
    * scan it with a pattern set that does
    * verify the rename plan numbers it from its own slots
    """
    mock_directory(mocker, ["shot-1.jpg", "shot-2.jpg"])
    patterns = (ScreenshotNamePattern(r"^shot-(\d+)$"),)

    renames = scan_tc_screenshots(DIRECTORY, STEM, patterns)

    assert renames == [
        ScreenshotRename("info01.jpg", "shot-1.jpg", ("shot-1.jpg",)),
        ScreenshotRename("info02.jpg", "shot-2.jpg", ("shot-2.jpg",)),
    ]


# endregion

# region scan_tc_screenshot_files (the reader view: current winner paths)


def test_screenshot_files_returns_each_slot_winners_path(mocker: MockerFixture) -> None:
    """The reader lists each recognized slot's current (pre-conversion) winner as an absolute path.

    **Test steps:**

    * mock the directory to hold a ``sample-00``/``sample-01`` series (no ties)
    * list the screenshot files
    * verify each winner resolves against :data:`DIRECTORY`, in slot order
    """
    mock_directory(mocker, ["sample-00.jpg", "sample-01.jpg"])

    assert scan_tc_screenshot_files(DIRECTORY, STEM) == [DIRECTORY / "sample-00.jpg", DIRECTORY / "sample-01.jpg"]


def test_screenshot_files_returns_the_winner_on_a_tie(mocker: MockerFixture) -> None:
    """On a slot tie only the winner's path is listed, not the losing variant.

    **Test steps:**

    * mock a small ``cover.jpg`` and a large ``sample-00.png`` on the same slot
    * list the screenshot files
    * verify only the larger winner's path comes back
    """
    mock_directory(mocker, ["cover.jpg", "sample-00.png"])
    mock_image_sizes(mocker, {"cover.jpg": (100, 100), "sample-00.png": (1920, 1080)})

    assert scan_tc_screenshot_files(DIRECTORY, STEM) == [DIRECTORY / "sample-00.png"]


def test_screenshot_files_is_empty_for_a_missing_directory(mocker: MockerFixture) -> None:
    """A missing/unreadable directory lists no screenshot files, rather than crashing.

    **Test steps:**

    * mock ``Path.iterdir`` to raise ``OSError``
    * list the screenshot files
    * verify the result is empty
    """
    mocker.patch.object(Path, "iterdir", side_effect=OSError)

    assert not scan_tc_screenshot_files(DIRECTORY, STEM)


# endregion

# region is_legacy_screenshot (the name-only view the content walk asks)


@mark.parametrize(
    ("filename", "expected"),
    [
        param("COVER.JPG", True, id="any-casing-of-stem-and-extension"),
        param("lesson1.jpg", False, id="an-ordinary-image"),
        param("01.mp4", False, id="a-numbered-video"),
        param("info00.jpg", False, id="a-converted-name"),
    ],
)
def test_a_name_is_classified_without_opening_anything(mocker: MockerFixture, filename: str, expected: bool) -> None:
    """A name is classified from the name alone -- no listing, no image opened (#250).

    What the content walk asks of a name it already has, so that a legacy record's screenshots are
    skipped the way an ``infoNN.jpg`` beside an ``info.rehu`` is. Which stems the patterns claim is the
    slot tests' business below; what is asked here is the wrapper's own two rules: the stem is matched
    whatever its casing, and only under an image extension -- a numbered *video* is not a screenshot,
    the same distinction ``<record>NN`` plus an image extension draws for a converted record.

    **Test steps:**

    * make any attempt to list a directory or open an image raise
    * classify a filename
    * verify the answer, and that nothing on disk was touched
    """
    mocker.patch.object(Path, "iterdir", side_effect=OSError("nothing may be listed"))
    mocker.patch("rehuco_core.tc_screenshots.Image.open", side_effect=OSError("nothing may be opened"))

    assert is_legacy_screenshot(filename) is expected


def test_recognition_follows_the_patterns_it_is_given(mocker: MockerFixture) -> None:
    """The name-only question the content walk asks is answered by the caller's patterns too, which is
    what keeps the set the walk skips identical to the set a conversion renames aside.

    **Test steps:**

    * make any disk access raise
    * classify a name under a pattern set that claims it and one that does not
    * verify the two answers differ
    """
    mocker.patch.object(Path, "iterdir", side_effect=OSError("nothing may be listed"))
    patterns = (ScreenshotNamePattern(r"^shot-(\d+)$"),)

    assert is_legacy_screenshot("shot-2.jpg", patterns) is True
    assert is_legacy_screenshot("shot-2.jpg") is False


# endregion

# region ScreenshotNamePatterns (#287)


@mark.parametrize(
    ("stem", "expected"),
    [
        param("cover", 0, id="cover"),
        param("file", 0, id="file"),
        param("03", 3, id="bare-number"),
        param("sample-03", 3, id="sample-series"),
        param("image-07", 7, id="image-series"),
        param("file-2", 2, id="file-dash-series"),
        param("file(3)", 3, id="file-paren-series"),
        param("lesson1", None, id="unmatched"),
    ],
)
def test_slot_extraction_for_each_shipped_pattern(stem: str, expected: int | None) -> None:
    """Each of the seven shipped patterns yields the slot the design doc's table says
    ([[acquisition-tooling#screenshot-schemes]]).

    **Test steps:**

    * ask the compiled shipped patterns for ``stem``'s slot
    * verify the number, or that nothing matched
    """
    patterns = ScreenshotNamePatterns(SCREENSHOT_NAME_PATTERNS)

    assert patterns.slot(stem) == expected


def test_a_pattern_with_no_capture_group_means_slot_zero() -> None:
    """A pattern without a capture group always assigns slot 0 -- the convention, not a property of the
    shipped ``^cover$``.

    **Test steps:**

    * compile a single no-group pattern
    * ask it for a matching stem's slot
    * verify it is 0
    """
    patterns = ScreenshotNamePatterns((ScreenshotNamePattern(r"^titlecard$"),))

    assert patterns.slot("titlecard") == 0


@mark.parametrize(
    ("stem", "expected"),
    [
        param("file-1", 1, id="unpadded"),
        param("file-01", 1, id="padded"),
    ],
)
def test_padding_is_ignored(stem: str, expected: int) -> None:
    """Unlike the retired cover/rest templates, a pattern's slot is a plain ``int()`` -- padding never
    changes which slot a number names.

    **Test steps:**

    * ask the shipped ``file-(\\d+)`` pattern for an unpadded and a zero-padded stem's slot
    * verify both read as the same number
    """
    patterns = ScreenshotNamePatterns(SCREENSHOT_NAME_PATTERNS)

    assert patterns.slot(stem) == expected


def test_an_invalid_regex_syntax_is_skipped_and_flagged() -> None:
    """A pattern that fails to compile never matches, and is reported in :attr:`invalid`.

    **Test steps:**

    * compile a pattern set holding one syntactically broken regex
    * verify it never matches anything and is named in ``invalid``
    """
    broken = "["
    patterns = ScreenshotNamePatterns((ScreenshotNamePattern(broken),))

    assert patterns.slot("[") is None
    assert patterns.invalid == (broken,)


def test_a_pattern_with_two_capture_groups_is_skipped_and_flagged() -> None:
    """A pattern carrying more than one capture group never matches, and is reported in :attr:`invalid`.

    **Test steps:**

    * compile a pattern set holding one two-group regex
    * verify it never matches anything and is named in ``invalid``
    """
    two_groups = r"^(\d+)-(\d+)$"
    patterns = ScreenshotNamePatterns((ScreenshotNamePattern(two_groups),))

    assert patterns.slot("01-02") is None
    assert patterns.invalid == (two_groups,)


def test_an_invalid_pattern_is_skipped_and_the_rest_of_the_set_still_applies() -> None:
    """One unusable pattern costs itself, not the scan -- the refuse-don't-crash discipline.

    **Test steps:**

    * build a set holding a malformed pattern between two good ones
    * classify a name each good pattern claims
    * verify both are still recognized and the malformed one is flagged
    """
    broken = "("
    patterns = ScreenshotNamePatterns(
        (
            ScreenshotNamePattern(r"^cover$"),
            ScreenshotNamePattern(broken),
            ScreenshotNamePattern(r"^(\d+)$"),
        )
    )

    assert patterns.recognizes("cover") is True
    assert patterns.recognizes("01") is True
    assert patterns.invalid == (broken,)


@mark.parametrize(
    ("pattern", "stem"),
    [
        param(r"^shot-(\w+)$", "shot-a", id="non-numeric-group"),
        param(r"^(.)$", "a", id="half-typed-any-character"),
        param(r"^cover(\d+)?$", "cover", id="optional-group-that-captured-nothing"),
    ],
)
def test_a_group_that_names_no_number_decides_nothing(pattern: str, stem: str) -> None:
    """A pattern that compiles and matches but whose group is not a number is not invalid -- it just
    cannot decide that stem, so the next pattern is tried rather than the scan crashing on ``int()``.
    Reachable from the try-it table on every keystroke, so this is the never-fatal rule at match time.

    **Test steps:**

    * ask the pattern alone for the stem's slot, and again with a deciding pattern after it
    * verify neither raises, the pattern is not flagged, and the later pattern gets its turn
    """
    alone = ScreenshotNamePatterns((ScreenshotNamePattern(pattern),))
    followed = ScreenshotNamePatterns((ScreenshotNamePattern(pattern), ScreenshotNamePattern(f"^{stem}$")))

    assert alone.slot(stem) is None
    assert not alone.invalid
    assert followed.slot(stem) == 0


def test_first_match_wins_in_list_order() -> None:
    """When more than one pattern could match a stem, the first in the list decides its slot.

    **Test steps:**

    * compile two patterns that both match ``"01"`` but disagree on its slot -- one names it literally
      as slot 0, the other reads it as slot 1 through a capture group
    * verify the order they are given in decides which answer wins
    """
    literal_first = ScreenshotNamePatterns((ScreenshotNamePattern(r"^01$"), ScreenshotNamePattern(r"^(\d+)$")))
    numeric_first = ScreenshotNamePatterns((ScreenshotNamePattern(r"^(\d+)$"), ScreenshotNamePattern(r"^01$")))

    assert literal_first.slot("01") == 0
    assert numeric_first.slot("01") == 1


def test_a_pattern_set_round_trips_through_a_saved_jobs_state() -> None:
    """A queued conversion carries its patterns, so a restored job converts the way it was queued to.

    **Test steps:**

    * write a pattern set down and read it back
    * verify it is unchanged, and that malformed state falls back rather than half-reading
    """
    assert screenshot_name_patterns_from_state(screenshot_name_patterns_state(SCREENSHOT_NAME_PATTERNS)) == (
        SCREENSHOT_NAME_PATTERNS
    )
    assert screenshot_name_patterns_from_state(None) is None
    assert screenshot_name_patterns_from_state([1, 2]) is None


# endregion
