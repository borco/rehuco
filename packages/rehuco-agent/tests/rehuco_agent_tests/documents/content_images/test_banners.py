"""Tests for the Content Images dock's banner rule (#221, #392)."""

from pathlib import Path
from typing import Final

from pytest import mark
from rehuco_agent.documents.content_images.banners import (
    ContentDisplayFlags,
    archive_relative_path,
    banner_rows,
    group_name,
    group_of,
    redundant_top_folders,
)
from rehuco_core import ContentImageEntry

REHU_DIRECTORY: Final = Path("/fake/refimages")
ZIP1: Final = REHU_DIRECTORY / "dir1" / "zip1.zip"
ZIP2: Final = REHU_DIRECTORY / "zip2.zip"

BANNERS: Final = ContentDisplayFlags(banners=True, strip_zip_folder=True)
BANNERS_UNSTRIPPED: Final = ContentDisplayFlags(banners=True, strip_zip_folder=False)
NO_BANNERS: Final = ContentDisplayFlags(banners=False)


def entry(archive: Path, name: str) -> ContentImageEntry:
    """An archive member with no size or fingerprint to speak of.

    :param archive: the archive.
    :param name: the member path.
    :returns: the entry.
    """
    return ContentImageEntry(archive, name, 0, 0)


def loose(name: str) -> ContentImageEntry:
    """A loose image under :data:`REHU_DIRECTORY` (#392).

    :param name: its path relative to the ``.rehu``'s directory.
    :returns: the entry.
    """
    return ContentImageEntry(None, name, 0, file=REHU_DIRECTORY / name)


# region group names


@mark.parametrize(
    ("image", "expected"),
    [
        (loose("a.jpg"), "/"),
        (loose("foo/a.jpg"), "foo/"),
        (loose("foo/sub/a.jpg"), "foo/sub/"),
        (entry(REHU_DIRECTORY / "foo.zip", "a.jpg"), "foo.zip/"),
        (entry(REHU_DIRECTORY / "foo.zip", "bar/a.jpg"), "foo.zip/bar/"),
        (entry(REHU_DIRECTORY / "baz" / "foo.zip", "bar/a.jpg"), "baz/foo.zip/bar/"),
        (entry(REHU_DIRECTORY / "baz" / "foo.zip", "a.jpg"), "baz/foo.zip/"),
    ],
)
def test_a_group_is_named_by_its_folders_path_under_the_rehu(image: ContentImageEntry, expected: str) -> None:
    """One spelling for every group (#392): the folder's path relative to the ``.rehu``, an archive
    counting as one more level, with a trailing ``/`` -- and the root alone a lone ``/``.

    **Test steps:**

    * name the group of a loose image or member
    * verify the spelling
    """
    assert group_name(image, REHU_DIRECTORY) == expected


def test_the_archive_path_is_relative_to_the_rehu_and_slash_separated() -> None:
    """An archive is named relative to the ``.rehu``'s directory with ``/`` on every platform; one
    outside that directory falls back to its bare name.

    **Test steps:**

    * spell a nested archive's path and one outside the directory
    """
    assert archive_relative_path(ZIP1, REHU_DIRECTORY) == "dir1/zip1.zip"
    assert archive_relative_path(Path("/elsewhere/pack.zip"), REHU_DIRECTORY) == "pack.zip"
    assert group_name(entry(Path("/elsewhere/pack.zip"), "a.jpg"), REHU_DIRECTORY) == "pack.zip/"


# endregion

# region banner rows

MIXED: Final = [
    loose("a.jpg"),
    loose("b.jpg"),
    entry(ZIP1, "c.jpg"),
    entry(ZIP1, "path1/path2/d.jpg"),
    loose("foo/e.jpg"),
    entry(ZIP2, "f.jpg"),
    entry(ZIP2, "sub/g.jpg"),
]
"""Root images, a nested archive with a root image and a deep folder, a loose folder, and a second
archive with a root image and a subfolder -- in the order the enumeration hands them over."""


def test_a_banner_starts_every_group() -> None:
    """With banners on, every change of group gets one banner naming it, loose folders and archive
    folders alike.

    **Test steps:**

    * banner the mixed fixture
    * verify the banner positions and texts
    """
    assert list(banner_rows(MIXED, REHU_DIRECTORY, BANNERS)) == [
        (0, "/"),
        (2, "dir1/zip1.zip/"),
        (3, "dir1/zip1.zip/path1/path2/"),
        (4, "foo/"),
        (5, "zip2.zip/"),
        (6, "zip2.zip/sub/"),
    ]


def test_with_banners_off_there_are_none() -> None:
    """Banners off is one continuous grid: no banner, and no group to collapse.

    **Test steps:**

    * banner and group the mixed fixture with banners off
    """
    assert not list(banner_rows(MIXED, REHU_DIRECTORY, NO_BANNERS))
    assert group_of(MIXED, REHU_DIRECTORY, NO_BANNERS) == [None] * len(MIXED)


def test_every_entry_belongs_to_the_banner_above_it() -> None:
    """Each entry's group is the last banner at or before it -- what a collapse hides by.

    **Test steps:**

    * group the mixed fixture with banners on
    """
    assert group_of(MIXED, REHU_DIRECTORY, BANNERS) == [
        "/",
        "/",
        "dir1/zip1.zip/",
        "dir1/zip1.zip/path1/path2/",
        "foo/",
        "zip2.zip/",
        "zip2.zip/sub/",
    ]


# endregion

# region top folder named like its zip (#367)

STRIP_TABLE: Final = [
    ("foo.zip", ["foo/a.jpg", "foo/b.jpg"], "foo.zip/", "foo.zip/foo/"),
    ("foo.zip", ["foo/bar/a.jpg"], "foo.zip/bar/", "foo.zip/foo/bar/"),
    ("Foo.zip", ["foo/a.jpg"], "Foo.zip/", "Foo.zip/foo/"),
    ("foo.cbz", ["FOO/a.jpg"], "foo.cbz/", "foo.cbz/FOO/"),
    ("baz.zip", ["baz.jpg", "baz/a.jpg"], "baz.zip/", "baz.zip/"),
    ("baz.zip", ["baz/a.jpg", "other/b.jpg"], "baz.zip/baz/", "baz.zip/baz/"),
    ("qux.zip", ["quux/a.jpg"], "qux.zip/quux/", "qux.zip/quux/"),
]
"""The #367 table, plus a ``.cbz`` with its case flipped: archive, members, the first banner with the top
folder stripped, and the same banner with it kept. The ``baz`` rows open with their root member's
``baz.zip/``, so their stripped and kept first banners agree -- the prefix they keep shows on the next
group."""


@mark.parametrize(("archive", "members", "stripped", "kept"), STRIP_TABLE)
def test_a_top_folder_named_like_its_archive_is_dropped_from_the_banner(
    archive: str, members: list[str], stripped: str, kept: str
) -> None:
    """With the box on, a top folder that repeats its archive's stem and holds every content image is
    left out of the banner; a root image, a sibling top folder, or another name keeps it -- and with
    the box off, nothing changes (#367).

    **Test steps:**

    * banner one archive's members with the box on, and again with it off
    * verify the first banner of each
    """
    entries = [entry(REHU_DIRECTORY / archive, name) for name in members]

    assert next(banner_rows(entries, REHU_DIRECTORY, BANNERS))[1] == stripped
    assert next(banner_rows(entries, REHU_DIRECTORY, BANNERS_UNSTRIPPED))[1] == kept


def test_a_top_folder_beside_a_root_image_keeps_its_banner() -> None:
    """``baz.zip`` holding ``baz/*.jpg`` and a root ``baz.jpg`` banners the folder as ``baz.zip/baz/``,
    so it never merges with the archive's real root group ``baz.zip/`` (#367).

    **Test steps:**

    * banner the archive with the box on
    * verify both groups keep their own key
    """
    entries = [entry(REHU_DIRECTORY / "baz.zip", "baz.jpg"), entry(REHU_DIRECTORY / "baz.zip", "baz/a.jpg")]

    assert list(banner_rows(entries, REHU_DIRECTORY, BANNERS)) == [(0, "baz.zip/"), (1, "baz.zip/baz/")]


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
    assert list(banner_rows(DIRECTORY_SCOPED, REHU_DIRECTORY, BANNERS)) == [
        (0, "pack1.zip/"),
        (1, "pack1.zip/poses/"),
        (2, "pack2.zip/extras/"),
    ]


def test_the_group_keys_follow_the_stripped_banners() -> None:
    """Each entry's collapse key is the stripped banner above it, so a collapse still hides by the text
    the user sees (#367).

    **Test steps:**

    * group the directory-scoped fixture with the box on
    """
    assert group_of(DIRECTORY_SCOPED, REHU_DIRECTORY, BANNERS) == [
        "pack1.zip/",
        "pack1.zip/poses/",
        "pack2.zip/extras/",
        "pack2.zip/extras/",
    ]


def test_a_loose_image_is_never_a_stripped_archive() -> None:
    """Stripping concerns archives only: a loose ``foo/`` folder beside ``foo.zip`` is not one, and the
    archive still strips (#392).

    **Test steps:**

    * collect the redundant top folders of a loose ``foo/a.jpg`` and a ``foo.zip`` holding ``foo/b.jpg``
    * verify only the archive qualified, and the loose image kept its ``foo/`` banner
    """
    archive = REHU_DIRECTORY / "foo.zip"
    entries = [loose("foo/a.jpg"), entry(archive, "foo/b.jpg")]

    assert redundant_top_folders(entries) == {archive}
    assert list(banner_rows(entries, REHU_DIRECTORY, BANNERS)) == [(0, "foo/"), (1, "foo.zip/")]


# endregion
