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
