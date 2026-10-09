"""Tests for :mod:`rehuco_core.staged_images` -- the name an image taken out of a resource is staged under, and the
staging folder's upkeep (#395)."""

import os
from datetime import timedelta
from pathlib import Path

from pytest import mark
from pytest_mock import MockerFixture
from rehuco_core import StagedImageName, parse_staged_name, prune_staged, stage_image, staged_name, staging_origin
from rehuco_core.staged_images import MAX_NAME_BYTES, SHORTENED_MARK, sanitized_segment

ID: str = "0f8fad5b-d9cb-469f-a165-70867728950e"


# region Names


@mark.parametrize(
    ("relative", "expected"),
    [
        ("a.jpg", f"rehu-{ID}__a.jpg"),
        ("screenshots/a.png", f"rehu-{ID}__screenshots__a.png"),
        ("foo.zip/bar/a.jpg", f"rehu-{ID}__foo.zip__bar__a.jpg"),
    ],
)
def test_a_name_joins_the_origin_and_the_path_segments(relative: str, expected: str) -> None:
    """A loose image, one in a subfolder, and an archive member, the archive a segment of its own.

    **Test steps:**

    * name each path under an id
    * verify the name
    """
    assert staged_name(ID, relative) == expected


@mark.parametrize(
    ("segment", "expected"),
    [
        ('a<b>c:d"e|f?g*h', "a_b_c_d_e_f_g_h"),
        ("a\\b", "a_b"),
        ("tab\there", "tab_here"),
        ("a__b___c", "a_b_c"),
        ("_edge_", "edge"),
        ("trailing. ", "trailing"),
        ("ends_.", "ends"),
        ("", "-"),
        ("___", "-"),
        ("łukasz é", "łukasz é"),
    ],
)
def test_a_segment_is_safe_everywhere_and_never_holds_the_separator(segment: str, expected: str) -> None:
    """What Windows or macOS refuses becomes ``_``, ``_`` never doubles or sits at an edge, nothing ends in a dot.

    **Test steps:**

    * sanitize each segment
    * verify what is left
    """
    assert sanitized_segment(segment) == expected


def test_an_unsafe_path_still_parses_into_its_segments() -> None:
    """A segment that held the separator itself still comes back as one segment.

    **Test steps:**

    * name a path whose folder holds ``__`` and an edge ``_``
    * verify it parses back to the sanitized segments
    """
    name = staged_name(ID, "_my__pack_.zip/sub:dir/a.jpg")

    assert name == f"rehu-{ID}__my_pack_.zip__sub_dir__a.jpg"
    assert parse_staged_name(name) == StagedImageName(ID, "my_pack_.zip/sub_dir/a.jpg")


def test_a_long_name_shortens_the_middle_segments_and_keeps_the_id_and_basename() -> None:
    """The longest middle segment is cut first, and only as far as the name needs.

    **Test steps:**

    * name a path with one very long folder and one short one
    * verify the name fits, the id and basename are whole, the long folder is cut and marked, the short one whole
    """
    name = staged_name(ID, f"{'x' * 300}/short/basename.jpg")
    parsed = parse_staged_name(name)

    assert len(name.encode()) == MAX_NAME_BYTES
    assert parsed is not None
    assert parsed.uuid == ID
    folder, short, basename = parsed.path.split("/")
    assert folder.endswith(SHORTENED_MARK)
    assert short == "short"
    assert basename == "basename.jpg"


def test_the_byte_cap_counts_multi_byte_characters() -> None:
    """APFS counts bytes: a name of two-byte characters fits in bytes, and no character is cut in half.

    **Test steps:**

    * name a path whose folders are all ``ł``
    * verify the name fits in bytes and decodes, with the basename whole
    """
    name = staged_name(ID, f"{'ł' * 100}/{'ł' * 100}/a.jpg")

    assert len(name.encode()) <= MAX_NAME_BYTES
    assert name.encode().decode() == name
    assert name.endswith("__a.jpg")


def test_too_many_middle_segments_collapse_into_one_mark() -> None:
    """When cutting each folder to its floor is not enough, they all become one mark.

    **Test steps:**

    * name a path forty folders deep
    * verify the name fits and reads ``id``, the mark, the basename
    """
    name = staged_name(ID, "/".join(["folder-name"] * 40 + ["a.jpg"]))

    assert len(name.encode()) <= MAX_NAME_BYTES
    assert name == f"rehu-{ID}__{SHORTENED_MARK}__a.jpg"


def test_a_location_origin_is_cut_but_an_id_never_is() -> None:
    """With the folders gone, a long location is cut next; an id is left whole and the basename's stem gives way.

    **Test steps:**

    * name a long basename under a very long location, and under an id
    * verify the location is cut with the basename whole, and the id whole with the stem cut and the extension kept
    """
    by_location = staged_name("L" * 300, f"{'b' * 100}.jpg")
    by_id = staged_name(ID, f"{'b' * 300}.jpeg")

    assert len(by_location.encode()) <= MAX_NAME_BYTES
    assert by_location.endswith(f"__{'b' * 100}.jpg")
    assert by_location.startswith("rehu-L")
    assert len(by_id.encode()) <= MAX_NAME_BYTES
    assert by_id.startswith(f"rehu-{ID}__b")
    assert by_id.endswith(f"{SHORTENED_MARK}.jpeg")


@mark.parametrize(
    ("document_id", "record", "expected"),
    [
        (ID, Path("/lib/Pack/info.rehu"), ID),
        ("", Path("/lib/Pack/info.rehu"), "Pack"),
        ("", Path("/lib/Pack/info.tc"), "Pack"),
        ("", Path("/lib/Packs/forest.rehu"), "forest"),
        ("", Path("/lib/Packs/forest.tc"), "forest"),
        ("", None, ""),
    ],
)
def test_a_record_without_an_id_is_named_by_its_location(document_id: str, record: Path | None, expected: str) -> None:
    """The id first; else a directory-scoped record's folder, or a file-scoped record's stem.

    **Test steps:**

    * ask for the origin of records with and without an id, of each scope and format
    * verify the answer
    """
    assert staging_origin(document_id, record) == expected


@mark.parametrize(
    ("origin", "relative"),
    [(ID, "a.jpg"), (ID, "foo.zip/bar/a.jpg"), ("Pack", "a.jpg"), ("my pack", "sub/a b.png")],
)
def test_a_name_parses_back_to_its_origin_and_path(origin: str, relative: str) -> None:
    """The inverse: the origin and the path come back, and an id is told from a location by its shape.

    **Test steps:**

    * name each origin and path, then parse the name
    * verify both come back, and the id is reported only for an id
    """
    parsed = parse_staged_name(staged_name(origin, relative))

    assert parsed == StagedImageName(origin, relative)
    assert parsed is not None
    assert parsed.uuid == (origin if origin == ID else None)


@mark.parametrize("name", ["a.jpg", "rehu-", "rehu-only", "rehu-x____a.jpg", f"REHU-{ID}__a.jpg"])
def test_a_foreign_name_does_not_parse(name: str) -> None:
    """Without the prefix, without a separator, or with an empty segment, a name is not a staged one.

    **Test steps:**

    * parse each name
    * verify there is nothing
    """
    assert parse_staged_name(name) is None


# endregion

# region Staging


def test_staging_writes_the_unchanged_bytes(tmp_path: Path) -> None:
    """The copy is byte-identical, in a folder made for it.

    **Test steps:**

    * stage some bytes into a folder that does not exist yet
    * verify the file is at the name and holds exactly those bytes
    """
    folder = tmp_path / "staged"
    data = bytes(range(256)) * 4

    staged = stage_image(folder, "rehu-x__a.jpg", data)

    assert staged == folder / "rehu-x__a.jpg"
    assert staged is not None
    assert staged.read_bytes() == data


def test_staging_the_same_bytes_again_reuses_the_copy_and_bumps_its_time(tmp_path: Path, mocker: MockerFixture) -> None:
    """An image exported twice is one file, its age counted from the last use.

    **Test steps:**

    * stage some bytes, then age the file
    * stage the same bytes again with the writer watched
    * verify nothing was rewritten and the time is fresh
    """
    staged = stage_image(tmp_path, "rehu-x__a.jpg", b"same")
    assert staged is not None
    os.utime(staged, (0, 0))
    writer = mocker.patch("rehuco_core.staged_images.atomic_write_bytes")

    assert stage_image(tmp_path, "rehu-x__a.jpg", b"same") == staged

    writer.assert_not_called()
    assert staged.stat().st_mtime > 0


@mark.parametrize("other", [b"different", b"diff"])
def test_staging_other_bytes_replaces_the_copy(tmp_path: Path, other: bytes) -> None:
    """A pack that changed since replaces what was staged under its name, whether or not the size changed.

    **Test steps:**

    * stage some bytes, then other bytes under the same name
    * verify the file holds the new ones
    """
    stage_image(tmp_path, "rehu-x__a.jpg", b"original")

    staged = stage_image(tmp_path, "rehu-x__a.jpg", other)

    assert staged is not None
    assert staged.read_bytes() == other


def test_staging_that_fails_reports_nothing_staged(tmp_path: Path, mocker: MockerFixture) -> None:
    """A write that fails is logged and answered with no file, never raised.

    **Test steps:**

    * make the write fail
    * verify staging answers ``None``
    """
    mocker.patch("rehuco_core.staged_images.atomic_write_bytes", side_effect=OSError("disk full"))

    assert stage_image(tmp_path, "rehu-x__a.jpg", b"data") is None


# endregion

# region Pruning


def test_pruning_deletes_only_what_was_not_used_for_the_age(tmp_path: Path) -> None:
    """A file older than the age goes, a newer one stays, and a folder inside is left alone.

    **Test steps:**

    * stage an old file, a new one and a subfolder
    * prune with a seven-day age
    * verify only the old file went
    """
    now = 1_000_000_000.0
    old = tmp_path / "old.jpg"
    new = tmp_path / "new.jpg"
    for file, age_days in ((old, 8), (new, 6)):
        file.write_bytes(b"x")
        stamp = now - timedelta(days=age_days).total_seconds()
        os.utime(file, (stamp, stamp))
    (tmp_path / "folder").mkdir()

    prune_staged(tmp_path, timedelta(days=7), now)

    assert sorted(entry.name for entry in tmp_path.iterdir()) == ["folder", "new.jpg"]


def test_pruning_a_missing_folder_does_nothing(tmp_path: Path) -> None:
    """Nothing staged yet: nothing to prune, and nothing raised.

    **Test steps:**

    * prune a folder that does not exist
    * verify it still does not
    """
    prune_staged(tmp_path / "missing", timedelta(days=7), 0.0)

    assert not (tmp_path / "missing").exists()


def test_a_file_that_cannot_be_pruned_is_skipped(tmp_path: Path, mocker: MockerFixture) -> None:
    """A file held open elsewhere is logged and left; the rest are still pruned.

    **Test steps:**

    * stage two old files and make deleting the first fail
    * verify the second still went
    """
    first = tmp_path / "a.jpg"
    second = tmp_path / "b.jpg"
    for file in (first, second):
        file.write_bytes(b"x")
        os.utime(file, (0, 0))
    real_unlink = Path.unlink

    def unlink(path: Path, missing_ok: bool = False) -> None:
        if path == first:
            raise PermissionError("in use")
        real_unlink(path, missing_ok)

    mocker.patch.object(Path, "unlink", unlink)

    prune_staged(tmp_path, timedelta(days=7), 1_000_000_000.0)

    assert first.exists()
    assert not second.exists()


# endregion


def test_a_long_basename_with_no_extension_is_cut_whole() -> None:
    """With no dot to keep, the whole basename is what gives way, the id and the mark still there.

    **Test steps:**

    * name a path whose only segment is very long and has no extension
    * verify the name fits, keeps the id, and ends in the mark
    """
    name = staged_name(ID, "b" * 300)

    assert len(name.encode()) <= MAX_NAME_BYTES
    assert name.startswith(f"rehu-{ID}__b")
    assert name.endswith(SHORTENED_MARK)
