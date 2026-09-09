"""Tests for legacy screenshot pattern recognition ([[acquisition-tooling#tc-to-rehu]], #287)."""

from pathlib import Path
from typing import Final

from PIL import UnidentifiedImageError
from pytest import mark, param, raises
from pytest_mock import MockerFixture
from rehuco_core import (
    SCREENSHOT_NAME_PATTERNS,
    ScreenshotNamePattern,
    ScreenshotNamePatterns,
    ScreenshotRename,
    ScreenshotSkipReason,
    UnconvertedScreenshot,
    convert_screenshot,
    is_legacy_screenshot,
    scan_tc_screenshot_files,
    scan_tc_screenshots,
    scan_unconverted_screenshots,
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
    :param sizes: ``{filename: (width, height)}`` for every same-stem variant the scan will open.
    """

    def open_side_effect(path: Path) -> object:
        image = mocker.MagicMock()
        image.__enter__.return_value.size = sizes[Path(path).name]
        return image

    mocker.patch("rehuco_core.tc_screenshots.Image.open", side_effect=open_side_effect)


def mock_existing(mocker: MockerFixture, present: set[str]) -> None:
    """Mock ``Path.exists`` so only the names in ``present`` appear to exist.

    :param mocker: pytest-mock fixture.
    :param present: the filenames that should report as existing.
    """
    mocker.patch.object(Path, "exists", autospec=True, side_effect=lambda self: self.name in present)


# region scan_tc_screenshots (the rename plan)


def test_each_recognized_file_takes_the_number_its_name_carries(mocker: MockerFixture) -> None:
    """With no two files on one slot, a scan is the number each name carries and nothing more --
    whichever shipped pattern named it -- keeping the file's own extension.

    **Test steps:**

    * mock the directory to hold one file under each of three shipped patterns
    * scan
    * verify each maps to its own new name, in slot order, and nothing is left unconverted
    """
    mock_directory(mocker, ["file(2).jpg", "cover.jpg", "sample-01.png"])

    plan = scan_tc_screenshots(DIRECTORY, STEM)

    assert plan.renames == (
        ScreenshotRename("info00.jpg", "cover.jpg"),
        ScreenshotRename("info01.png", "sample-01.png"),
        ScreenshotRename("info02.jpg", "file(2).jpg"),
    )
    assert not plan.unconverted


def test_renames_come_out_in_slot_order_whatever_the_pattern_order(mocker: MockerFixture) -> None:
    """The plan is in slot order even where the pattern that claims a name sits later in the list than
    the one claiming a higher number -- the lightbox reads this order for an unconverted ``.tc``.

    **Test steps:**

    * mock a bare ``05`` (an earlier shipped pattern) beside a ``sample-01`` (a later one)
    * scan
    * verify slot 1 comes before slot 5
    """
    mock_directory(mocker, ["05.jpg", "sample-01.png"])

    plan = scan_tc_screenshots(DIRECTORY, STEM)

    assert plan.renames == (
        ScreenshotRename("info01.png", "sample-01.png"),
        ScreenshotRename("info05.jpg", "05.jpg"),
    )
    assert scan_tc_screenshot_files(DIRECTORY, STEM) == [DIRECTORY / "sample-01.png", DIRECTORY / "05.jpg"]


def test_a_taken_slot_leaves_the_later_file_exactly_as_it_was(mocker: MockerFixture) -> None:
    """Two names wanting one number is the case nothing here decides: the earlier pattern's file takes
    the slot and the other keeps its own name, reported as a collision for the images dock (#270).

    **Test steps:**

    * mock the directory to hold ``cover.jpg`` and ``sample-00.png``, both slot 0
    * scan
    * verify ``cover`` (the earlier pattern) is renamed and ``sample-00.png`` is untouched
    """
    mock_directory(mocker, ["sample-00.png", "cover.jpg"])

    plan = scan_tc_screenshots(DIRECTORY, STEM)

    assert plan.renames == (ScreenshotRename("info00.jpg", "cover.jpg"),)
    assert plan.unconverted == (UnconvertedScreenshot("sample-00.png", ScreenshotSkipReason.COLLISION),)
    assert plan.collision is True


def test_the_pattern_order_decides_which_file_takes_a_contested_slot(mocker: MockerFixture) -> None:
    """The list's order is what settles a collision, so moving a pattern moves the winner with it --
    the same order that decides which pattern claims a name two of them match (#287).

    **Test steps:**

    * scan one directory twice, with the two patterns in either order
    * verify the earlier pattern's file takes the slot both times
    """
    mock_directory(mocker, ["sample-00.png", "cover.jpg"])
    cover_first = (ScreenshotNamePattern(r"^cover$"), ScreenshotNamePattern(r"^sample-(\d+)$"))
    sample_first = (ScreenshotNamePattern(r"^sample-(\d+)$"), ScreenshotNamePattern(r"^cover$"))

    assert scan_tc_screenshots(DIRECTORY, STEM, cover_first).renames == (ScreenshotRename("info00.jpg", "cover.jpg"),)
    assert scan_tc_screenshots(DIRECTORY, STEM, sample_first).renames == (
        ScreenshotRename("info00.png", "sample-00.png"),
    )


def test_names_under_one_pattern_are_ordered_naturally(mocker: MockerFixture) -> None:
    """Within a single pattern, two spellings of one number are ordered naturally rather than as text,
    so which of them takes the slot does not depend on zero-padding sorting before digits.

    **Test steps:**

    * mock the directory to hold ``file-2``, ``file-10`` and a padded ``file-02``
    * scan
    * verify the distinct numbers convert, and the padded duplicate of slot 2 is left alone
    """
    mock_directory(mocker, ["file-10.jpg", "file-02.jpg", "file-2.jpg"])

    plan = scan_tc_screenshots(DIRECTORY, STEM)

    assert plan.renames == (
        ScreenshotRename("info02.jpg", "file-02.jpg"),
        ScreenshotRename("info10.jpg", "file-10.jpg"),
    )
    assert plan.unconverted == (UnconvertedScreenshot("file-2.jpg", ScreenshotSkipReason.COLLISION),)


def test_a_preexisting_numbered_file_owns_its_slot(mocker: MockerFixture) -> None:
    """A ``<stem>NN`` file already on disk is where the reader looks, so it keeps its number and a
    legacy name wanting it is left alone -- the conversion overwrites nothing.

    **Test steps:**

    * mock the directory to hold ``info00.jpg`` beside ``cover.jpg``
    * scan
    * verify nothing is renamed onto ``info00.jpg`` and ``cover.jpg`` keeps its name
    """
    mock_directory(mocker, ["info00.jpg", "cover.jpg"])

    plan = scan_tc_screenshots(DIRECTORY, STEM)

    assert not plan.renames
    assert plan.unconverted == (UnconvertedScreenshot("cover.jpg", ScreenshotSkipReason.COLLISION),)


def test_a_second_run_over_a_converted_directory_renames_nothing(mocker: MockerFixture) -> None:
    """Conversion is idempotent: every name it produced is a ``<stem>NN``, which is not a candidate, so
    running it again against an already-converted resource is a no-op.

    **Test steps:**

    * mock the directory as it looks after a conversion of the three-pattern case above
    * scan
    * verify the plan is empty on both sides
    """
    mock_directory(mocker, ["info00.jpg", "info01.png", "info02.jpg"])

    plan = scan_tc_screenshots(DIRECTORY, STEM)

    assert not plan.renames
    assert not plan.unconverted


def test_one_stem_under_several_extensions_keeps_the_larger_picture(mocker: MockerFixture) -> None:
    """One name stored twice is one picture: the larger by pixel area takes the number and the other
    keeps its own name, which is the only place a conversion opens an image at all.

    **Test steps:**

    * mock ``cover.jpg`` (small) beside ``cover.png`` (large)
    * scan
    * verify the ``.png`` takes slot 0 and the ``.jpg`` is left alone
    """
    mock_directory(mocker, ["cover.jpg", "cover.png"])
    mock_image_sizes(mocker, {"cover.jpg": (100, 100), "cover.png": (1920, 1080)})

    plan = scan_tc_screenshots(DIRECTORY, STEM)

    assert plan.renames == (ScreenshotRename("info00.png", "cover.png"),)
    assert plan.unconverted == (UnconvertedScreenshot("cover.jpg", ScreenshotSkipReason.COLLISION),)


def test_an_exact_area_tie_between_extensions_follows_the_image_extension_order(mocker: MockerFixture) -> None:
    """Two copies of one name at identical dimensions resolve by the app's own extension order, so the
    outcome never depends on which the directory listed first.

    **Test steps:**

    * mock ``cover.png`` and ``cover.jpg`` at the same dimensions, the ``.png`` listed first
    * scan
    * verify the ``.jpg`` wins, being earlier in ``IMAGE_EXTENSIONS``
    """
    mock_directory(mocker, ["cover.png", "cover.jpg"])
    mock_image_sizes(mocker, {"cover.png": (800, 600), "cover.jpg": (800, 600)})

    plan = scan_tc_screenshots(DIRECTORY, STEM)

    assert plan.renames == (ScreenshotRename("info00.jpg", "cover.jpg"),)


def test_a_corrupt_variant_loses_the_area_comparison(mocker: MockerFixture) -> None:
    """A variant whose bytes ``PIL`` can't decode ranks last rather than aborting the conversion -- this
    runs before any disk mutation, so an unreadable image is strictly safer treated as area ``0``.

    **Test steps:**

    * mock ``cover.jpg`` as readable and same-stem ``cover.png`` as raising ``UnidentifiedImageError``
    * scan
    * verify the readable file wins despite its modest pixel size
    """
    mock_directory(mocker, ["cover.jpg", "cover.png"])

    def open_side_effect(path: Path) -> object:
        if Path(path).name == "cover.png":
            raise UnidentifiedImageError
        image = mocker.MagicMock()
        image.__enter__.return_value.size = (100, 100)
        return image

    mocker.patch("rehuco_core.tc_screenshots.Image.open", side_effect=open_side_effect)

    plan = scan_tc_screenshots(DIRECTORY, STEM)

    assert plan.renames == (ScreenshotRename("info00.jpg", "cover.jpg"),)


def test_a_three_digit_number_is_left_unconverted(mocker: MockerFixture) -> None:
    """A legacy number at or above :data:`~rehuco_core.MAX_SCREENSHOT_SLOT` is someone else's
    convention: the file keeps its name rather than being given a ``<stem>NNN`` no reader recognizes.

    **Test steps:**

    * mock ``sample-100.jpg`` beside an ordinary ``sample-01.jpg``
    * scan
    * verify only the two-digit one converts, and the other is reported as out of range rather than as
      a collision -- nothing was contested
    """
    mock_directory(mocker, ["sample-100.jpg", "sample-01.jpg"])

    plan = scan_tc_screenshots(DIRECTORY, STEM)

    assert plan.renames == (ScreenshotRename("info01.jpg", "sample-01.jpg"),)
    assert plan.unconverted == (UnconvertedScreenshot("sample-100.jpg", ScreenshotSkipReason.OUT_OF_RANGE),)
    assert plan.collision is False


def test_unrecognized_filenames_are_ignored(mocker: MockerFixture) -> None:
    """A filename matching none of the shipped patterns is left out of the scan entirely -- it is not a
    screenshot at all, so it is neither renamed nor reported as one left alone.

    **Test steps:**

    * mock the directory to hold one recognized file and one unrelated one
    * scan
    * verify only the recognized file appears in the result
    """
    mock_directory(mocker, ["sample-00.jpg", "random_screenshot.jpg"])

    plan = scan_tc_screenshots(DIRECTORY, STEM)

    assert plan.renames == (ScreenshotRename("info00.jpg", "sample-00.jpg"),)
    assert not plan.unconverted


def test_non_image_extensions_are_ignored(mocker: MockerFixture) -> None:
    """A same-named file with an unrecognized extension is left out of the scan.

    **Test steps:**

    * mock the directory to hold ``sample-00.jpg`` and a same-stem ``sample-00.txt``
    * scan
    * verify only the image file is recognized
    """
    mock_directory(mocker, ["sample-00.jpg", "sample-00.txt"])

    plan = scan_tc_screenshots(DIRECTORY, STEM)

    assert plan.renames == (ScreenshotRename("info00.jpg", "sample-00.jpg"),)


def test_missing_directory_returns_an_empty_plan(mocker: MockerFixture) -> None:
    """A missing/unreadable directory (e.g. an offline mount) scans to an empty plan, not a crash.

    **Test steps:**

    * mock ``Path.iterdir`` to raise ``OSError``
    * scan
    * verify both halves of the plan are empty
    """
    mocker.patch.object(Path, "iterdir", side_effect=OSError)

    plan = scan_tc_screenshots(DIRECTORY, STEM)

    assert not plan.renames
    assert not plan.unconverted


def test_a_directory_is_scanned_with_the_patterns_it_was_given(mocker: MockerFixture) -> None:
    """The pattern set is the caller's, so a user-added series converts like any shipped one.

    **Test steps:**

    * mock a directory holding a series no shipped pattern recognizes
    * scan it with a pattern set that does
    * verify the rename plan numbers it from its own slots
    """
    mock_directory(mocker, ["shot-1.jpg", "shot-2.jpg"])
    patterns = (ScreenshotNamePattern(r"^shot-(\d+)$"),)

    plan = scan_tc_screenshots(DIRECTORY, STEM, patterns)

    assert plan.renames == (
        ScreenshotRename("info01.jpg", "shot-1.jpg"),
        ScreenshotRename("info02.jpg", "shot-2.jpg"),
    )


# endregion

# region scan_tc_screenshot_files (the reader view: the numbered files' current paths)


def test_screenshot_files_returns_each_numbered_files_current_path(mocker: MockerFixture) -> None:
    """The reader lists the current (pre-conversion) path of every file the conversion would number.

    **Test steps:**

    * mock the directory to hold a ``sample-00``/``sample-01`` series (no collisions)
    * list the screenshot files
    * verify each resolves against :data:`DIRECTORY`, in slot order
    """
    mock_directory(mocker, ["sample-00.jpg", "sample-01.jpg"])

    assert scan_tc_screenshot_files(DIRECTORY, STEM) == [DIRECTORY / "sample-00.jpg", DIRECTORY / "sample-01.jpg"]


def test_screenshot_files_leaves_out_a_file_no_slot_is_free_for(mocker: MockerFixture) -> None:
    """Only the files that would end up in a slot are listed: one left under its own name has no
    position in the numbered set to be shown at.

    **Test steps:**

    * mock ``cover.jpg`` and ``sample-00.png`` on the same slot
    * list the screenshot files
    * verify only the slot winner's path comes back
    """
    mock_directory(mocker, ["cover.jpg", "sample-00.png"])

    assert scan_tc_screenshot_files(DIRECTORY, STEM) == [DIRECTORY / "cover.jpg"]


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

# region scan_unconverted_screenshots (the images dock's second row, #265)


def test_pattern_matched_images_not_yet_numbered_are_listed(mocker: MockerFixture) -> None:
    """A pattern-matched image with no ``<stem>NN`` slot yet is the whole point of this scan.

    **Test steps:**

    * mock the directory to hold two un-numbered, pattern-matched images
    * scan
    * verify both come back, resolved against the directory
    """
    mock_directory(mocker, ["cover.jpg", "sample-01.png"])

    assert scan_unconverted_screenshots(DIRECTORY, STEM) == [DIRECTORY / "cover.jpg", DIRECTORY / "sample-01.png"]


def test_already_numbered_files_are_left_out(mocker: MockerFixture) -> None:
    """A file already sitting in a ``<stem>NN`` slot is not un-converted -- it has nothing to convert.

    **Test steps:**

    * mock the directory to hold a numbered file beside an un-numbered one
    * scan
    * verify only the un-numbered file is listed
    """
    mock_directory(mocker, ["info00.jpg", "sample-01.png"])

    assert scan_unconverted_screenshots(DIRECTORY, STEM) == [DIRECTORY / "sample-01.png"]


def test_unrecognized_and_non_image_files_are_left_out(mocker: MockerFixture) -> None:
    """A name no pattern claims, or a non-image extension, is not a screenshot at all.

    **Test steps:**

    * mock the directory to hold one recognized image beside an unrelated file and a non-image extension
    * scan
    * verify only the recognized image is listed
    """
    mock_directory(mocker, ["sample-00.jpg", "random.jpg", "sample-00.txt"])

    assert scan_unconverted_screenshots(DIRECTORY, STEM) == [DIRECTORY / "sample-00.jpg"]


def test_results_come_back_in_natural_sort_order(mocker: MockerFixture) -> None:
    """The listing is naturally sorted, so ``file-2`` comes before ``file-10``.

    **Test steps:**

    * mock the directory to hold the two out of natural-sort listing order
    * scan
    * verify the natural order rather than the listing order
    """
    mock_directory(mocker, ["file-10.jpg", "file-2.jpg"])

    assert scan_unconverted_screenshots(DIRECTORY, STEM) == [DIRECTORY / "file-2.jpg", DIRECTORY / "file-10.jpg"]


def test_missing_directory_lists_nothing(mocker: MockerFixture) -> None:
    """A missing/unreadable directory scans to an empty list, not a crash.

    **Test steps:**

    * mock ``Path.iterdir`` to raise ``OSError``
    * scan
    * verify the result is empty
    """
    mocker.patch.object(Path, "iterdir", side_effect=OSError)

    assert not scan_unconverted_screenshots(DIRECTORY, STEM)


# endregion

# region convert_screenshot (single-file conversion, #265)


def test_convert_takes_its_own_legacy_number_when_the_slot_is_free(mocker: MockerFixture) -> None:
    """With no ``<stem>NN`` file already on that slot, conversion writes the number the legacy name
    carries -- the ordinary case.

    **Test steps:**

    * mock a directory holding only the un-converted candidate
    * convert it
    * verify it is renamed onto the slot its own name carries
    """
    mock_directory(mocker, ["sample-01.png"])
    mock_existing(mocker, set())
    rename = mocker.patch.object(Path, "rename", autospec=True)

    result = convert_screenshot(DIRECTORY / "sample-01.png", STEM)

    assert result == DIRECTORY / "info01.png"
    rename.assert_called_once_with(DIRECTORY / "sample-01.png", DIRECTORY / "info01.png")


def test_convert_appends_past_the_end_when_its_own_slot_is_taken(mocker: MockerFixture) -> None:
    """The two-click thumbnail fix: with ``info00`` already on disk, converting ``sample-00`` cannot
    reuse slot 0, so it lands one past the current highest instead of being refused.

    **Test steps:**

    * mock a directory holding ``info00.jpg`` (slot 0 taken) beside ``sample-00.png``
    * convert the un-converted file
    * verify it lands on slot 1, not slot 0
    """
    mock_directory(mocker, ["info00.jpg", "sample-00.png"])
    mock_existing(mocker, {"info00.jpg"})
    rename = mocker.patch.object(Path, "rename", autospec=True)

    result = convert_screenshot(DIRECTORY / "sample-00.png", STEM)

    assert result == DIRECTORY / "info01.png"
    rename.assert_called_once_with(DIRECTORY / "sample-00.png", DIRECTORY / "info01.png")


def test_convert_lands_on_a_slot_a_delete_just_freed(mocker: MockerFixture) -> None:
    """Deleting ``info00`` first and then converting ``sample-00`` lands it right back on slot 0 -- the
    freed slot is free, not merely `not yet seen`.

    **Test steps:**

    * mock a directory holding only ``sample-00.png`` (``info00`` already gone)
    * convert it
    * verify it takes slot 0
    """
    mock_directory(mocker, ["sample-00.png"])
    mock_existing(mocker, set())
    rename = mocker.patch.object(Path, "rename", autospec=True)

    result = convert_screenshot(DIRECTORY / "sample-00.png", STEM)

    assert result == DIRECTORY / "info00.png"
    rename.assert_called_once_with(DIRECTORY / "sample-00.png", DIRECTORY / "info00.png")


def test_convert_appends_a_legacy_number_that_is_out_of_range(mocker: MockerFixture) -> None:
    """A three-digit legacy number is the file the whole-directory conversion left for hand correction
    ([[acquisition-tooling#tc-to-rehu]]): it is not a free slot, so Convert appends rather than writing
    an ``info100`` that no reader -- numbered or pattern-matched -- would list again.

    **Test steps:**

    * mock ``info00.jpg`` beside ``sample-100.jpg``
    * convert the three-digit file
    * verify it lands one past the end, not on ``info100``
    """
    mock_directory(mocker, ["info00.jpg", "sample-100.jpg"])
    mock_existing(mocker, {"info00.jpg"})
    rename = mocker.patch.object(Path, "rename", autospec=True)

    result = convert_screenshot(DIRECTORY / "sample-100.jpg", STEM)

    assert result == DIRECTORY / "info01.jpg"
    rename.assert_called_once_with(DIRECTORY / "sample-100.jpg", DIRECTORY / "info01.jpg")


def test_convert_refuses_when_the_numbered_set_is_full(mocker: MockerFixture) -> None:
    """Appending past ``info99`` would need a three-digit name, so it is refused instead of written.

    **Test steps:**

    * mock ``info99.jpg`` beside a ``sample-99.png`` whose own slot it takes
    * attempt to convert
    * verify it is refused and nothing is renamed
    """
    mock_directory(mocker, ["info99.jpg", "sample-99.png"])
    mock_existing(mocker, {"info99.jpg"})
    rename = mocker.patch.object(Path, "rename", autospec=True)

    with raises(ValueError, match="full"):
        convert_screenshot(DIRECTORY / "sample-99.png", STEM)
    rename.assert_not_called()


def test_convert_refuses_while_the_resource_is_still_a_tc(mocker: MockerFixture) -> None:
    """A single screenshot is not converted ahead of the resource it belongs to.

    **Test steps:**

    * mock the directory-scoped ``.tc`` record as present
    * attempt to convert
    * verify it is refused and nothing is renamed
    """
    mock_directory(mocker, ["sample-01.png"])
    mock_existing(mocker, {"info.tc"})
    rename = mocker.patch.object(Path, "rename", autospec=True)

    with raises(PermissionError):
        convert_screenshot(DIRECTORY / "sample-01.png", STEM)
    rename.assert_not_called()


def test_convert_refuses_a_name_no_pattern_recognizes(mocker: MockerFixture) -> None:
    """A name none of the patterns claim has no legacy number to preserve.

    **Test steps:**

    * mock a directory holding an unrecognized name
    * attempt to convert it
    * verify it is refused and nothing is renamed
    """
    mock_directory(mocker, ["random.jpg"])
    mock_existing(mocker, set())
    rename = mocker.patch.object(Path, "rename", autospec=True)

    with raises(LookupError):
        convert_screenshot(DIRECTORY / "random.jpg", STEM)
    rename.assert_not_called()


def test_convert_refuses_a_target_already_on_disk(mocker: MockerFixture) -> None:
    """A ``<stem>NN`` name already on disk is never overwritten, even when nothing upstream expected
    the collision.

    **Test steps:**

    * mock the chosen destination as already present, despite an empty numbered set
    * attempt to convert
    * verify it is refused and nothing is renamed
    """
    mock_directory(mocker, ["sample-01.png"])
    mock_existing(mocker, {"info01.png"})
    rename = mocker.patch.object(Path, "rename", autospec=True)

    with raises(FileExistsError):
        convert_screenshot(DIRECTORY / "sample-01.png", STEM)
    rename.assert_not_called()


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
