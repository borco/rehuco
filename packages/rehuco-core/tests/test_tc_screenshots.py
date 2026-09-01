"""Tests for legacy screenshot pattern recognition ([[acquisition-tooling#tc-to-rehu]])."""

from pathlib import Path
from typing import Final

from PIL import UnidentifiedImageError
from pytest import mark, param, raises
from pytest_mock import MockerFixture
from rehuco_core import (
    LEGACY_SCREENSHOT_RULES,
    LegacyScreenshotRule,
    LegacyScreenshotRuleMatcher,
    LegacyScreenshotRules,
    ScreenshotRename,
    is_legacy_screenshot,
    legacy_screenshot_rules_from_state,
    legacy_screenshot_rules_state,
    scan_tc_screenshot_files,
    scan_tc_screenshots,
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
        param("01.jpg", True, id="bare-numeric"),
        param("sample-01.png", True, id="sample-series"),
        param("file.jpg", True, id="file-alone"),
        param("file(2).jpg", True, id="file-duplicate-suffix"),
        param("COVER.JPG", True, id="cover-any-casing"),
        param("file-01.gif", True, id="file-small-series"),
        param("lesson1.jpg", False, id="an-ordinary-image"),
        param("01.mp4", False, id="a-numbered-video"),
        param("info00.jpg", False, id="a-converted-name"),
    ],
)
def test_a_name_is_classified_without_opening_anything(mocker: MockerFixture, filename: str, expected: bool) -> None:
    """Every scheme is recognized from the name alone -- no listing, no image opened (#250).

    What the content walk asks of a name it already has, so that a legacy record's screenshots are
    skipped the way an ``infoNN.jpg`` beside an ``info.rehu`` is. All five schemes answer here, winners
    and losing variants alike, because a conversion backs up all of them: ranking decides which one is
    *installed*, never which ones are screenshots. A numbered *video* is not one, the same distinction
    ``<record>NN`` plus an image extension draws for a converted record.

    **Test steps:**

    * make any attempt to list a directory or open an image raise
    * classify a filename
    * verify the answer, and that nothing on disk was touched
    """
    mocker.patch.object(Path, "iterdir", side_effect=OSError("nothing may be listed"))
    mocker.patch("rehuco_core.tc_screenshots.Image.open", side_effect=OSError("nothing may be opened"))

    assert is_legacy_screenshot(filename) is expected


# endregion

# region The rule language (#53)


@mark.parametrize(
    ("rest", "text", "expected"),
    [
        param("img-#", "0", 0, id="no-padding-zero"),
        param("img-#", "7", 7, id="no-padding-single"),
        param("img-#", "10", 10, id="no-padding-grows"),
        param("img-#", "01", None, id="no-padding-refuses-padded"),
        param("img-##", "00", 0, id="pad-two-zero"),
        param("img-##", "09", 9, id="pad-two-single"),
        param("img-##", "99", 99, id="pad-two-full"),
        param("img-##", "100", 100, id="pad-two-grows-past-its-width"),
        param("img-##", "0", None, id="pad-two-refuses-narrower"),
        param("img-##", "0100", None, id="pad-two-refuses-over-padded"),
        param("img-###", "000", 0, id="pad-three-zero"),
        param("img-###", "1000", 1000, id="pad-three-grows"),
        param("img-###", "00", None, id="pad-three-refuses-narrower"),
    ],
)
def test_a_rest_template_reads_its_number_at_the_written_padding(rest: str, text: str, expected: int | None) -> None:
    """A run of ``#`` is the number's **minimum** zero-padded width, and re-rendering enforces it.

    **Test steps:**

    * compile a rule carrying the template
    * ask it for the number in a stem built from the digits
    * verify the number, or that the template refused it
    """
    matcher = LegacyScreenshotRuleMatcher(LegacyScreenshotRule("cover", rest))

    assert matcher.number(f"img-{text}") == expected


@mark.parametrize(
    ("rule", "reason"),
    [
        param(LegacyScreenshotRule("", "##"), "a blank cover", id="blank-cover"),
        param(LegacyScreenshotRule("#", "##"), "a cover holding the placeholder", id="placeholder-in-cover"),
        param(LegacyScreenshotRule("cover", "no-number"), "a rest with no placeholder", id="no-placeholder"),
        param(LegacyScreenshotRule("cover", "a#b#c"), "a rest with two runs", id="two-placeholder-runs"),
    ],
)
def test_a_malformed_rule_is_refused_rather_than_half_compiled(rule: LegacyScreenshotRule, reason: str) -> None:
    """Compiling states what a rule must be; the set above it is what skips one that isn't.

    **Test steps:**

    * compile a malformed rule
    * verify it raises rather than producing a matcher that matches nothing
    """
    with raises(ValueError):
        LegacyScreenshotRuleMatcher(rule)
    assert reason  # names the case in the parametrization, read in the failure output


def test_a_malformed_rule_is_skipped_and_the_rest_of_the_set_still_applies() -> None:
    """One unusable rule costs itself, not the scan -- the refuse-don't-crash discipline.

    **Test steps:**

    * build a set holding a malformed rule between two good ones
    * classify a name each good rule claims
    * verify both are still recognized
    """
    rules = LegacyScreenshotRules(
        (
            LegacyScreenshotRule("cover", "no-number"),
            LegacyScreenshotRule("00", "##"),
        )
    )

    assert rules.recognizes("01") is True
    assert rules.recognizes("nonsense") is False


@mark.parametrize(
    ("filenames", "expected"),
    [
        param(
            ["image-00.jpg", "image-01.jpg", "image-02.jpg"],
            {0: ["image-00.jpg"], 1: ["image-01.jpg"], 2: ["image-02.jpg"]},
            id="image-00-first",
        ),
        param(
            ["image-01.jpg", "image-02.jpg", "image-03.jpg"],
            {0: ["image-01.jpg"], 1: ["image-02.jpg"], 2: ["image-03.jpg"]},
            id="image-01-first",
        ),
        param(
            ["file.jpg", "file(2).jpg", "file(3).jpg"],
            {0: ["file.jpg"], 1: ["file(2).jpg"], 2: ["file(3).jpg"]},
            id="windows-duplicate-series",
        ),
        param(
            ["cover.jpg", "file-01.jpg", "file-02.jpg"],
            {0: ["cover.jpg"], 1: ["file-01.jpg"], 2: ["file-02.jpg"]},
            id="cover-then-file-nn",
        ),
    ],
)
def test_each_shipped_rule_numbers_its_series_from_its_own_cover(
    filenames: list[str], expected: dict[int, list[str]]
) -> None:
    """The four series the rules were written from, each starting at slot 0 with its own cover.

    The ``image-01``-first case is the one no filename can answer: ``image-01`` is slot 1 under the rule
    above it and slot 0 under its own, and the only evidence is that ``image-00`` is absent.

    **Test steps:**

    * group a directory's filenames under the shipped rules
    * verify each file's slot
    """
    assert LegacyScreenshotRules(LEGACY_SCREENSHOT_RULES).group_by_slot(filenames) == expected


def test_the_numbers_order_the_files_rather_than_naming_their_slots() -> None:
    """A gap in the numbering closes: slots are ordinal, because a rule carries no start value.

    **Test steps:**

    * group a series numbered 00, 01, 05
    * verify the third file is slot 2 rather than slot 5
    """
    assert LegacyScreenshotRules(LEGACY_SCREENSHOT_RULES).group_by_slot(["00.jpg", "01.jpg", "05.jpg"]) == {
        0: ["00.jpg"],
        1: ["01.jpg"],
        2: ["05.jpg"],
    }


def test_a_file_the_winning_rule_misses_folds_in_as_a_variant_of_the_same_slot() -> None:
    """The winner assigns the slots; another rule's files join them rather than being dropped.

    That is what keeps a thumbnail ``cover.jpg`` paired with the full-size ``sample-00.jpg`` it
    duplicates, so the tie-break still gets to pick between them.

    **Test steps:**

    * group a directory holding both a `sample-` series and a `cover`
    * verify both land on slot 0
    """
    grouped = LegacyScreenshotRules(LEGACY_SCREENSHOT_RULES).group_by_slot(
        ["cover.jpg", "sample-00.jpg", "sample-01.jpg"]
    )

    assert grouped == {0: ["cover.jpg", "sample-00.jpg"], 1: ["sample-01.jpg"]}


def test_the_first_rule_whose_cover_is_present_claims_the_directory() -> None:
    """Rule order is the control, and only a *present* cover puts a rule in charge.

    **Test steps:**

    * group a `file-NN` series whose `cover` is absent
    * verify it is numbered from its own first file rather than left without a slot 0
    """
    grouped = LegacyScreenshotRules(LEGACY_SCREENSHOT_RULES).group_by_slot(["file-01.jpg", "file-02.jpg"])

    assert grouped == {1: ["file-01.jpg"], 2: ["file-02.jpg"]}


def test_a_directory_the_rules_reach_differently_is_scanned_with_the_rules_it_was_given(
    mocker: MockerFixture,
) -> None:
    """The rule set is the caller's, so a user-added series converts like any shipped one.

    **Test steps:**

    * mock a directory holding a series no shipped rule recognizes
    * scan it with a rule set that does
    * verify the rename plan numbers it from its cover
    """
    mock_directory(mocker, ["shot-1.jpg", "shot-2.jpg"])
    rules = (LegacyScreenshotRule("shot-1", "shot-#"),)

    renames = scan_tc_screenshots(DIRECTORY, STEM, rules)

    assert renames == [
        ScreenshotRename("info00.jpg", "shot-1.jpg", ("shot-1.jpg",)),
        ScreenshotRename("info01.jpg", "shot-2.jpg", ("shot-2.jpg",)),
    ]


def test_recognition_follows_the_rules_it_is_given(mocker: MockerFixture) -> None:
    """The name-only question the content walk asks is answered by the caller's rules too, which is what
    keeps the set the walk skips identical to the set a conversion renames aside.

    **Test steps:**

    * make any disk access raise
    * classify a name under a rule set that claims it and one that does not
    * verify the two answers differ
    """
    mocker.patch.object(Path, "iterdir", side_effect=OSError("nothing may be listed"))
    rules = (LegacyScreenshotRule("shot-1", "shot-#"),)

    assert is_legacy_screenshot("shot-2.jpg", rules) is True
    assert is_legacy_screenshot("shot-2.jpg") is False


def test_a_rule_set_round_trips_through_a_saved_jobs_state() -> None:
    """A queued conversion carries its rules, so a restored job converts the way it was queued to.

    **Test steps:**

    * write a rule set down and read it back
    * verify it is unchanged, and that malformed state falls back rather than half-reading
    """
    assert legacy_screenshot_rules_from_state(legacy_screenshot_rules_state(LEGACY_SCREENSHOT_RULES)) == (
        LEGACY_SCREENSHOT_RULES
    )
    assert legacy_screenshot_rules_from_state(None) is None
    assert legacy_screenshot_rules_from_state([["only-one-field"]]) is None


# endregion
