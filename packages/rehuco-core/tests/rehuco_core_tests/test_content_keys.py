"""Tests for how a record keys its own content files ([[field-schema#watch-progress]], #410)."""

from pathlib import Path
from typing import Final

from pytest import mark, param, raises
from rehuco_core import INFO_REHU_FILENAME, content_key, content_path, is_valid_content_key

DIRECTORY: Final = Path("/fake/tutorial")
INFO_REHU: Final = DIRECTORY / INFO_REHU_FILENAME
STANDALONE: Final = DIRECTORY / "Lesson.rehu"


# region content_key
def test_a_directory_records_key_is_the_posix_path_under_its_folder() -> None:
    """A directory-scoped ``info.rehu`` keys a file by its path under the record's folder, ``/``-separated
    on every OS, so moving the resource as a whole keeps every key.

    **Test steps:**

    * key a top-level and a nested file
    * verify each is its relative POSIX path
    """
    assert content_key(INFO_REHU, DIRECTORY / "intro.mp4") == "intro.mp4"
    assert content_key(INFO_REHU, DIRECTORY / "01 Basics" / "03 Brushes.mp4") == "01 Basics/03 Brushes.mp4"


@mark.parametrize(
    ("filename", "expected"),
    [
        param("Lesson.mp4", ".mp4", id="same-spelling"),
        param("lesson.MP4", ".MP4", id="stem-matched-case-insensitively-remainder-kept"),
    ],
)
def test_a_standalone_records_key_is_its_file_name_without_the_stem(filename: str, expected: str) -> None:
    """A standalone ``<stem>.rehu`` describes one media file and keys it with the stem removed, so renaming
    the stem keeps the key; the stem matches as the content walk matches it, ignoring case.

    **Test steps:**

    * key the record's media file
    * verify the key is the remainder after the stem, spelled as on disk
    """
    assert content_key(STANDALONE, DIRECTORY / filename) == expected


@mark.parametrize(
    "file_path",
    [
        param(DIRECTORY / "Other.mp4", id="another-stem"),
        param(DIRECTORY / "Lesson-part2.mp4", id="stem-is-only-a-prefix"),
        param(DIRECTORY / "Lesson.tar.gz", id="stem-plus-a-second-extension"),
        param(DIRECTORY / "Lesson" / "a.mp4", id="inside-a-folder"),
        param(DIRECTORY / "Lesson", id="nothing-after-the-stem"),
    ],
)
def test_a_file_that_is_not_a_standalone_records_content_has_no_key(file_path: Path) -> None:
    """Only the record's own same-stem sibling has a key -- the stem compared whole, as the content walk compares
    it ([[data-model#resource-scoping]]); anything else is a caller's mistake.

    **Test steps:**

    * key a file that is not the record's sibling
    * verify it raises
    """
    with raises(ValueError, match="is not content of"):
        content_key(STANDALONE, file_path)


# endregion


# region content_path
def test_a_key_resolves_back_to_its_file() -> None:
    """``content_path`` is ``content_key``'s inverse, and a standalone key follows the record's stem as it
    is spelled now -- the point of removing it.

    **Test steps:**

    * resolve a nested directory key and a standalone key, the latter on a renamed record
    * verify each names the file
    """
    assert content_path(INFO_REHU, "01 Basics/03 Brushes.mp4") == DIRECTORY / "01 Basics" / "03 Brushes.mp4"
    assert content_path(DIRECTORY / "Renamed.rehu", ".mp4") == DIRECTORY / "Renamed.mp4"


@mark.parametrize(
    ("record", "key"),
    [
        param(INFO_REHU, "", id="empty"),
        param(INFO_REHU, "../outside.mp4", id="escaping"),
        param(INFO_REHU, "/abs.mp4", id="absolute"),
        param(INFO_REHU, "a//b.mp4", id="empty-segment"),
        param(INFO_REHU, "a\\b.mp4", id="backslash"),
        param(INFO_REHU, "C:/a.mp4", id="drive"),
        param(STANDALONE, "/x.mp4", id="standalone-with-a-folder"),
        param(STANDALONE, ":x", id="standalone-with-a-colon"),
        param(STANDALONE, "-part2.mp4", id="standalone-not-an-extension"),
        param(STANDALONE, ".tar.gz", id="standalone-two-extensions"),
    ],
)
def test_a_key_that_could_reach_outside_the_resource_is_refused(record: Path, key: str) -> None:
    """A key comes off disk -- another build, another node, a hand edit -- so one that could name a file
    outside the resource is refused rather than resolved, the rule a checksum entry's name is held to.

    **Test steps:**

    * validate and resolve a malformed key
    * verify it is invalid and resolving raises
    """
    assert is_valid_content_key(record, key) is False
    with raises(ValueError, match="Not a content key"):
        content_path(record, key)


def test_a_key_that_is_not_a_string_is_invalid() -> None:
    """A stored key of the wrong type is invalid, never an error.

    **Test steps:**

    * validate a non-string key
    * verify it is invalid
    """
    assert is_valid_content_key(INFO_REHU, 3) is False


# endregion
