"""Tests for the Content Images dock's banner rule (#221)."""

from pathlib import Path
from typing import Final

from pytest import mark
from rehuco_agent.documents.content_images.banners import (
    ContentDisplayFlags,
    archive_relative_path,
    banner_rows,
    banner_text,
    group_of,
    member_folder,
)
from rehuco_core import ContentImageEntry

REHU_DIRECTORY: Final = Path("/fake/refimages")
ZIP1: Final = REHU_DIRECTORY / "dir1" / "zip1.zip"
ZIP2: Final = REHU_DIRECTORY / "zip2.zip"


def entry(archive: Path, name: str) -> ContentImageEntry:
    """A content image with no size or fingerprint to speak of.

    :param archive: the archive.
    :param name: the member path.
    :returns: the entry.
    """
    return ContentImageEntry(archive, name, 0, 0)


TWO_ARCHIVES: Final = [
    entry(ZIP1, "a.jpg"),
    entry(ZIP1, "b.jpg"),
    entry(ZIP1, "path1/path2/c.jpg"),
    entry(ZIP2, "d.jpg"),
    entry(ZIP2, "sub/e.jpg"),
]
"""Two archives, each with a root batch and a subfolder -- the issue's own fixture."""


@mark.parametrize(
    ("flags", "expected"),
    [
        (ContentDisplayFlags(zip_names=False, folder_names=False), None),
        (ContentDisplayFlags(zip_names=True, folder_names=False), "dir1/zip1.zip"),
        (ContentDisplayFlags(zip_names=False, folder_names=True), "/path1/path2"),
        (ContentDisplayFlags(zip_names=True, folder_names=True), "dir1/zip1.zip:/path1/path2"),
    ],
)
def test_the_banner_text_follows_the_issues_table(flags: ContentDisplayFlags, expected: str | None) -> None:
    """The four flag combinations produce the four spellings the issue tabulates -- one combined
    banner, never two stacked.

    **Test steps:**

    * ask for the banner of ``dir1/zip1.zip`` at ``/path1/path2`` under ``flags``
    * verify the expected spelling
    """
    assert banner_text("dir1/zip1.zip", "/path1/path2", flags) == expected


def test_a_root_member_folder_is_a_lone_slash() -> None:
    """Root-level members read as ``/``, so a root batch is never mistaken for the previous group's tail.

    **Test steps:**

    * spell the folder of a root member and of a nested one
    * verify ``/`` and ``/a/b`` with no trailing slash
    """
    assert member_folder("img.jpg") == "/"
    assert member_folder("a/b/img.jpg") == "/a/b"


def test_the_archive_path_is_relative_to_the_rehu_and_slash_separated() -> None:
    """An archive is named relative to the ``.rehu``'s directory with ``/`` on every platform; one
    outside that directory falls back to its bare name.

    **Test steps:**

    * spell a nested archive's path and one outside the directory
    """
    assert archive_relative_path(ZIP1, REHU_DIRECTORY) == "dir1/zip1.zip"
    assert archive_relative_path(Path("/elsewhere/pack.zip"), REHU_DIRECTORY) == "pack.zip"


@mark.parametrize(
    ("flags", "expected"),
    [
        (ContentDisplayFlags(zip_names=False, folder_names=False), []),
        (ContentDisplayFlags(zip_names=True, folder_names=False), [(0, "dir1/zip1.zip"), (3, "zip2.zip")]),
        (
            ContentDisplayFlags(zip_names=False, folder_names=True),
            [(0, "/"), (2, "/path1/path2"), (3, "/"), (4, "/sub")],
        ),
        (
            ContentDisplayFlags(zip_names=True, folder_names=True),
            [
                (0, "dir1/zip1.zip:/"),
                (2, "dir1/zip1.zip:/path1/path2"),
                (3, "zip2.zip:/"),
                (4, "zip2.zip:/sub"),
            ],
        ),
    ],
)
def test_a_banner_goes_wherever_the_displayed_key_changes(
    flags: ContentDisplayFlags, expected: list[tuple[int, str]]
) -> None:
    """Over a two-archive resource with a root batch and a subfolder each, every flag combination puts
    exactly one banner at each change of the displayed key -- and none at all with both boxes off.

    **Test steps:**

    * walk the fixture under ``flags``
    * verify the banner positions and texts
    """
    assert list(banner_rows(TWO_ARCHIVES, REHU_DIRECTORY, flags)) == expected


def test_every_entry_belongs_to_the_banner_above_it() -> None:
    """Each entry's group is the last banner at or before it -- what a collapse hides by -- and none
    at all with both boxes off.

    **Test steps:**

    * group the fixture with zip names on, and again with both boxes off
    """
    assert group_of(TWO_ARCHIVES, REHU_DIRECTORY, ContentDisplayFlags(True, False)) == [
        "dir1/zip1.zip",
        "dir1/zip1.zip",
        "dir1/zip1.zip",
        "zip2.zip",
        "zip2.zip",
    ]
    assert group_of(TWO_ARCHIVES, REHU_DIRECTORY, ContentDisplayFlags(False, False)) == [None] * 5


ZIPS_AND_FOLDERS: Final = ContentDisplayFlags(zip_names=True, folder_names=True, strip_zip_folder=True)
ZIPS_AND_FOLDERS_UNSTRIPPED: Final = ContentDisplayFlags(zip_names=True, folder_names=True, strip_zip_folder=False)

STRIP_TABLE: Final = [
    ("foo.zip", ["foo/a.jpg", "foo/b.jpg"], "foo.zip:/", "foo.zip:/foo"),
    ("foo.zip", ["foo/bar/a.jpg"], "foo.zip:/bar", "foo.zip:/foo/bar"),
    ("Foo.zip", ["foo/a.jpg"], "Foo.zip:/", "Foo.zip:/foo"),
    ("foo.cbz", ["FOO/a.jpg"], "foo.cbz:/", "foo.cbz:/FOO"),
    ("baz.zip", ["baz.jpg", "baz/a.jpg"], "baz.zip:/", "baz.zip:/"),
    ("baz.zip", ["baz/a.jpg", "other/b.jpg"], "baz.zip:/baz", "baz.zip:/baz"),
    ("qux.zip", ["quux/a.jpg"], "qux.zip:/quux", "qux.zip:/quux"),
]
"""The issue's table, plus a ``.cbz`` with its case flipped: archive, members, the first banner with the
top folder stripped, and the same banner with it kept. The ``baz`` rows open with their root member's
``/``, so their stripped and kept first banners agree -- the prefix they keep shows on the next group."""


@mark.parametrize(("archive", "members", "stripped", "kept"), STRIP_TABLE)
def test_a_top_folder_named_like_its_archive_is_dropped_from_the_banner(
    archive: str, members: list[str], stripped: str, kept: str
) -> None:
    """With both banner boxes on, a top folder that repeats its archive's stem and holds every content
    image is left out of the banner; a loose root image, a sibling top folder, or another name keeps it
    -- and with the box off, nothing changes (#367).

    **Test steps:**

    * banner one archive's members with the box on, and again with it off
    * verify the first banner of each, and that the box off matches the unstripped spelling
    """
    entries = [entry(REHU_DIRECTORY / archive, name) for name in members]

    assert next(banner_rows(entries, REHU_DIRECTORY, ZIPS_AND_FOLDERS))[1] == stripped
    assert next(banner_rows(entries, REHU_DIRECTORY, ZIPS_AND_FOLDERS_UNSTRIPPED))[1] == kept


def test_a_top_folder_beside_a_loose_root_image_keeps_its_banner() -> None:
    """``baz.zip`` holding ``baz/*.jpg`` and a root ``baz.jpg`` banners the folder as ``baz.zip:/baz``, so
    it never merges with the real root group ``baz.zip:/`` (#367).

    **Test steps:**

    * banner the archive with the box on
    * verify both groups keep their own key
    """
    entries = [entry(REHU_DIRECTORY / "baz.zip", "baz.jpg"), entry(REHU_DIRECTORY / "baz.zip", "baz/a.jpg")]

    assert list(banner_rows(entries, REHU_DIRECTORY, ZIPS_AND_FOLDERS)) == [(0, "baz.zip:/"), (1, "baz.zip:/baz")]


DIRECTORY_SCOPED: Final = [
    entry(REHU_DIRECTORY / "pack1.zip", "pack1/a.jpg"),
    entry(REHU_DIRECTORY / "pack1.zip", "pack1/poses/b.jpg"),
    entry(REHU_DIRECTORY / "pack2.zip", "extras/c.jpg"),
    entry(REHU_DIRECTORY / "pack2.zip", "extras/d.jpg"),
]
"""A directory-scoped resource with two archives, only the first zipped with its own name inside."""


def test_only_the_archive_that_qualifies_is_stripped() -> None:
    """Redundancy is judged per archive: in a directory-scoped resource, the pack whose top folder
    repeats its name loses it, the neighbour whose folder does not keeps its own (#367).

    **Test steps:**

    * banner both archives with the box on
    * verify the first pack's folders are stripped and the second's are not
    """
    assert list(banner_rows(DIRECTORY_SCOPED, REHU_DIRECTORY, ZIPS_AND_FOLDERS)) == [
        (0, "pack1.zip:/"),
        (1, "pack1.zip:/poses"),
        (2, "pack2.zip:/extras"),
    ]


@mark.parametrize(
    ("flags", "expected"),
    [
        (
            ContentDisplayFlags(zip_names=False, folder_names=True, strip_zip_folder=True),
            [(0, "/pack1"), (1, "/pack1/poses"), (2, "/extras")],
        ),
        (
            ContentDisplayFlags(zip_names=True, folder_names=False, strip_zip_folder=True),
            [(0, "pack1.zip"), (2, "pack2.zip")],
        ),
    ],
)
def test_the_top_folder_stays_unless_both_banner_boxes_are_on(
    flags: ContentDisplayFlags, expected: list[tuple[int, str]]
) -> None:
    """Folders-only mode keeps the prefix -- with no zip name shown, the top folder is the only hint of
    which pack a group belongs to -- and zip-only mode shows no folder to strip (#367).

    **Test steps:**

    * banner the directory-scoped fixture with the box on but one banner box off
    * verify the unstripped banners
    """
    assert list(banner_rows(DIRECTORY_SCOPED, REHU_DIRECTORY, flags)) == expected


def test_the_group_keys_follow_the_stripped_banners() -> None:
    """Each entry's collapse key is the stripped banner above it, so a collapse still hides by the text
    the user sees (#367).

    **Test steps:**

    * group the directory-scoped fixture with the box on
    """
    assert group_of(DIRECTORY_SCOPED, REHU_DIRECTORY, ZIPS_AND_FOLDERS) == [
        "pack1.zip:/",
        "pack1.zip:/poses",
        "pack2.zip:/extras",
        "pack2.zip:/extras",
    ]
