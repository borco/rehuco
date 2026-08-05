"""Tests for content-file enumeration -- the set the size scan and the checksums share (#226) -- and
for the size-on-disk sum over it (#223).
"""

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Final

from pytest_mock import MockerFixture
from rehuco_core import (
    EXCLUDED_FILE_PATTERNS,
    INFO_REHU_FILENAME,
    content_size_on_disk,
    enumerate_content_files,
)

DIRECTORY: Final = Path("/fake/resource")
FILE_SCOPED_PATH: Final = DIRECTORY / "foo.rehu"
DIRECTORY_SCOPED_PATH: Final = DIRECTORY / INFO_REHU_FILENAME


class FakeDirEntry:
    """A stand-in for :class:`os.DirEntry`, which cannot be constructed outside a real directory read.

    Only the three members the scanner touches: the entry's name, and whether it is a directory or a
    regular file -- answered from how the test declared it, exactly as a real ``DirEntry`` answers from
    what reading the directory returned.
    """

    def __init__(self, name: str, *, directory: bool = False, regular: bool = True, link: bool = False) -> None:
        self.name: Final = name
        self.__directory: Final = directory
        self.__regular: Final = regular
        self.__link: Final = link

    def is_dir(self, *, follow_symlinks: bool = True) -> bool:
        """Whether the test declared this entry a directory -- through the link only when asked to.

        Mirrors :meth:`os.DirEntry.is_dir`'s contract: a symlink *to* a directory answers ``True`` when
        ``follow_symlinks`` (the default), ``False`` when not -- the distinction the scanner's
        loop guard turns on.
        """
        return self.__directory and (follow_symlinks or not self.__link)

    def is_file(self, *, follow_symlinks: bool = True) -> bool:
        """Whether the test declared this entry a regular file (through the link, per the default)."""
        del follow_symlinks
        return self.__regular


class FakeScandir:
    """What :func:`os.scandir` returns: an iterator that is also a context manager."""

    def __init__(self, entries: list[FakeDirEntry]) -> None:
        self.__entries: Final = entries

    def __enter__(self) -> Iterator[FakeDirEntry]:
        return iter(self.__entries)

    def __exit__(self, *_exception: object) -> None:
        return None


def mock_tree(  # pylint: disable=too-many-arguments
    mocker: MockerFixture,
    filenames: list[str],
    *,
    directories: list[str] | None = None,
    unreadable: list[str] | None = None,
    irregular: list[str] | None = None,
    directory_links: list[str] | None = None,
) -> None:
    """Mock a directory tree under :data:`DIRECTORY`, read one directory at a time via ``os.scandir``.

    Each directory answers with its own entries, because the scan descends rather than flattening -- a
    helper handing back the whole tree at once could not tell a record in one directory from a record in
    another, which is the distinction most of these tests turn on. Directories are declared separately
    from files so an entry's kind comes from the test rather than from guessing at its name.

    :param mocker: pytest-mock fixture.
    :param filenames: fake paths relative to :data:`DIRECTORY`, ``/``-separated, that are regular files.
    :param directories: fake paths relative to :data:`DIRECTORY` that are directories.
    :param unreadable: fake directory paths whose listing should raise ``OSError`` -- an offline branch
        of a mount. They must also appear in ``directories`` to be reached at all.
    :param irregular: fake paths that are neither a directory nor a regular file -- a socket, a fifo, a
        broken symlink. A real listing can hand these back, and they have no bytes to measure or hash.
    :param directory_links: fake paths that are *symlinks to* directories -- ``is_dir()`` answers
        ``True`` through the link and ``False`` with ``follow_symlinks=False``, which is what the
        scanner's loop guard asks. Their target's listing is deliberately not modeled: a test proves the
        walk never descends by the target's contents not appearing.
    """
    offline = {DIRECTORY / name for name in unreadable or []}
    listing: dict[Path, list[FakeDirEntry]] = {DIRECTORY: []}
    for name in directories or []:
        path = DIRECTORY / name
        listing.setdefault(path.parent, []).append(FakeDirEntry(path.name, directory=True))
        listing.setdefault(path, [])
    for name in filenames:
        path = DIRECTORY / name
        listing.setdefault(path.parent, []).append(FakeDirEntry(path.name))
    for name in irregular or []:
        path = DIRECTORY / name
        listing.setdefault(path.parent, []).append(FakeDirEntry(path.name, regular=False))
    for name in directory_links or []:
        path = DIRECTORY / name
        listing.setdefault(path.parent, []).append(FakeDirEntry(path.name, directory=True, regular=False, link=True))

    def scandir(directory: Path) -> FakeScandir:
        if Path(directory) in offline:
            raise PermissionError(directory)
        if Path(directory) not in listing:
            raise FileNotFoundError(directory)
        return FakeScandir(listing[Path(directory)])

    mocker.patch("rehuco_core.rehu_content_files.os.scandir", side_effect=scandir)


def mock_siblings(mocker: MockerFixture, filenames: list[str]) -> None:
    """Mock :data:`DIRECTORY` as a flat directory holding ``filenames``, all of them regular files.

    :param mocker: pytest-mock fixture.
    :param filenames: the fake filenames the directory should list.
    """
    mock_tree(mocker, filenames)


def names(paths: list[Path]) -> list[str]:
    """The paths' names, for asserting on a scan's result without repeating :data:`DIRECTORY`.

    :param paths: what a scan returned.
    :returns: each path relative to :data:`DIRECTORY`, ``/``-separated.
    """
    return [path.relative_to(DIRECTORY).as_posix() for path in paths]


# region file-scoped


def test_file_scoped_takes_only_its_own_same_stem_siblings(mocker: MockerFixture) -> None:
    """A whitelist named by the ``.rehu`` itself: another resource's files are out of scope, not excluded.

    **Test steps:**

    * mock the directory to hold ``foo.zip`` plus a whole other resource's ``info.rehu``, ``info00.jpg``,
      ``bar00.jpg`` and ``bar.zip``
    * enumerate ``foo.rehu``'s content files
    * verify only ``foo.zip`` came back
    """
    mock_siblings(mocker, ["foo.zip", "info.rehu", "info00.jpg", "bar00.jpg", "bar.zip"])

    assert names(enumerate_content_files(FILE_SCOPED_PATH)) == ["foo.zip"]


def test_file_scoped_is_unaffected_by_an_empty_pattern_list(mocker: MockerFixture) -> None:
    """No pattern can widen a whitelist of one, so emptying the editable list changes nothing (#226).

    **Test steps:**

    * mock the same directory as the previous test
    * enumerate ``foo.rehu``'s content files with no excluded patterns at all
    * verify the answer is still ``foo.zip`` alone
    """
    mock_siblings(mocker, ["foo.zip", "info.rehu", "info00.jpg", "bar00.jpg", "bar.zip"])

    assert names(enumerate_content_files(FILE_SCOPED_PATH, ())) == ["foo.zip"]


def test_file_scoped_drops_its_own_record_screenshots_and_manifest(mocker: MockerFixture) -> None:
    """The structural tier applies to a file-scoped resource too -- it has bookkeeping of its own.

    **Test steps:**

    * mock the directory to hold ``foo.zip`` beside ``foo.rehu``, ``foo00.jpg``, ``foo01.png`` and
      ``foo.sfv``
    * enumerate ``foo.rehu``'s content files
    * verify only ``foo.zip`` came back
    """
    mock_siblings(mocker, ["foo.rehu", "foo.zip", "foo00.jpg", "foo01.png", "foo.sfv"])

    assert names(enumerate_content_files(FILE_SCOPED_PATH)) == ["foo.zip"]


def test_file_scoped_takes_every_same_stem_sibling_whatever_its_format(mocker: MockerFixture) -> None:
    """Content is what shares the stem, not a fixed extension list: a single-file tutorial counts too.

    **Test steps:**

    * mock the directory to hold ``foo.mp4`` and ``foo.zip`` beside ``foo.rehu``
    * enumerate ``foo.rehu``'s content files
    * verify both non-bookkeeping siblings came back, sorted by name
    """
    mock_siblings(mocker, ["foo.zip", "foo.rehu", "foo.mp4"])

    assert names(enumerate_content_files(FILE_SCOPED_PATH)) == ["foo.mp4", "foo.zip"]


def test_file_scoped_matches_its_stem_case_insensitively(mocker: MockerFixture) -> None:
    """SMB and macOS hand back casings Windows never wrote, so a sibling must not escape by spelling.

    **Test steps:**

    * mock the directory to hold ``FOO.ZIP``
    * enumerate ``foo.rehu``'s content files
    * verify it was recognized as the resource's own file
    """
    mock_siblings(mocker, ["FOO.ZIP"])

    assert names(enumerate_content_files(FILE_SCOPED_PATH)) == ["FOO.ZIP"]


def test_file_scoped_reports_an_unreadable_directory_as_empty(mocker: MockerFixture) -> None:
    """An offline mount is a document-level condition, not a crash ([[mounts-and-storage#offline-mounts]]).

    **Test steps:**

    * mock ``os.scandir`` to raise ``OSError``
    * enumerate ``foo.rehu``'s content files
    * verify the result is empty and nothing was raised
    """
    mocker.patch("rehuco_core.rehu_content_files.os.scandir", side_effect=OSError)

    assert enumerate_content_files(FILE_SCOPED_PATH) == []


# endregion

# region directory-scoped, structural exclusions


def test_every_rehu_in_the_tree_takes_its_own_bookkeeping_with_it(mocker: MockerFixture) -> None:
    """No ``.rehu``'s files are ever counted -- not the scanner's own, not a nested or neighboring one.

    A record, its screenshots and its manifest can all change at any moment, so counting any of them
    would make a size or a checksum need recomputing after an ordinary metadata edit
    ([[data-model#checksums]]). Their *content* is untouched by this: ``baz.zip`` and ``bar/video.mp4``
    still count, because a nested record is not a boundary ([[data-model#resource-scoping]]).

    **Test steps:**

    * mock a tree holding the scanning ``info.rehu``, a nested ``bar/info.rehu`` and a file-scoped
      ``baz.rehu``, each with its own screenshots and manifests, plus real content beside them
    * enumerate ``info.rehu``'s content files
    * verify only the content came back
    """
    mock_tree(
        mocker,
        [
            "info.rehu",
            "info00.jpg",
            "bar/info.rehu",
            "bar/info00.jpg",
            "bar/video.mp4",
            "baz.rehu",
            "baz00.jpg",
            "baz.sfv",
            "baz.md5",
            "baz.sha256",
            "baz.zip",
        ],
        directories=["bar"],
    )

    assert names(enumerate_content_files(DIRECTORY_SCOPED_PATH)) == ["bar/video.mp4", "baz.zip"]


def test_a_pattern_only_excludes_where_a_matching_record_sits_beside_it(mocker: MockerFixture) -> None:
    """The whole rule on one tree: find the records first, drop what each claims, count what is left.

    A record claims only its own directory, and only names it actually carries. So ``bar/info00.jpg``
    counts -- there is no ``bar/info.rehu``, and the root's does not reach down -- while
    ``baz/info00.jpg`` does not, because ``baz/info.rehu`` sits beside it. ``xxx00.jpg`` and ``yyy.sfv``
    count for the same reason: no ``xxx.rehu``, no ``yyy.rehu``, so they are normal files that merely
    look like bookkeeping.

    **Test steps:**

    * mock a tree with two records at the root, a record-less subdirectory, and a subdirectory carrying
      its own record, plus names shaped like bookkeeping that no record claims
    * enumerate ``info.rehu``'s content files
    * verify exactly the three unclaimed files came back
    """
    mock_tree(
        mocker,
        [
            "info.rehu",
            "info00.jpg",
            "info.sfv",
            "foo.rehu",
            "foo00.jpg",
            "xxx00.jpg",
            "yyy.sfv",
            "bar/info00.jpg",
            "baz/info.rehu",
            "baz/info00.jpg",
        ],
        directories=["bar", "baz"],
    )

    assert names(enumerate_content_files(DIRECTORY_SCOPED_PATH)) == ["bar/info00.jpg", "xxx00.jpg", "yyy.sfv"]


def test_screenshots_and_manifests_without_a_record_are_content(mocker: MockerFixture) -> None:
    """Nothing is bookkeeping without a record to claim it -- the exclusion needs a ``.rehu`` to exist.

    A tutorial's own ``lesson01.jpg`` and a pack that ships its own ``.sfv`` must not be mistaken for
    bookkeeping on no evidence but their shape, and dropped from the measurement meant to cover them.

    **Test steps:**

    * mock a tree holding ``lesson01.jpg`` and ``pack.sfv`` with no matching ``.rehu``
    * enumerate ``info.rehu``'s content files
    * verify both counted
    """
    mock_tree(mocker, ["info.rehu", "lesson01.jpg", "pack.sfv"])

    assert names(enumerate_content_files(DIRECTORY_SCOPED_PATH)) == ["lesson01.jpg", "pack.sfv"]


def test_deleting_a_record_turns_its_screenshots_back_into_content(mocker: MockerFixture) -> None:
    """The exclusion follows the record, not the name: remove ``baz.rehu`` and ``baz00.jpg`` counts again.

    The same tree scanned twice, differing only in whether the record is there -- which is the whole
    condition. Nothing is bookkeeping on the strength of its shape alone.

    **Test steps:**

    * mock a tree holding ``baz.rehu``, ``baz00.jpg`` and ``baz.sfv``, and enumerate
    * mock the same tree without ``baz.rehu``, and enumerate again
    * verify the first scan excluded the pair and the second counted it
    """
    mock_tree(mocker, ["info.rehu", "baz.rehu", "baz00.jpg", "baz.sfv"])
    assert names(enumerate_content_files(DIRECTORY_SCOPED_PATH)) == []

    mock_tree(mocker, ["info.rehu", "baz00.jpg", "baz.sfv"])
    assert names(enumerate_content_files(DIRECTORY_SCOPED_PATH)) == ["baz.sfv", "baz00.jpg"]


def test_directory_scoped_drops_the_record_screenshots_and_manifest_by_slug(mocker: MockerFixture) -> None:
    """The three structural exclusions, derived from the record's name, never count.

    **Test steps:**

    * mock the tree to hold ``info.rehu``, ``info00.jpg``, ``info01.png``, ``info.sfv`` and ``video.mp4``
    * enumerate ``info.rehu``'s content files
    * verify only ``video.mp4`` came back
    """
    mock_tree(mocker, ["info.rehu", "info00.jpg", "info01.png", "info.sfv", "video.mp4"])

    assert names(enumerate_content_files(DIRECTORY_SCOPED_PATH)) == ["video.mp4"]


def test_directory_scoped_drops_every_manifest_extension(mocker: MockerFixture) -> None:
    """The written ``.checksum`` and every legacy manifest suffix are bookkeeping alike
    ([[data-model#resource-scoping]], [[data-model#checksums]]).

    The names are spelled out here on purpose -- asserting against the constant they are read from
    would pass however the constant changed, so the second copy *is* the test.

    **Test steps:**

    * mock the tree to hold a record-named file per manifest suffix, plus ``video.mp4``
    * enumerate ``info.rehu``'s content files
    * verify only ``video.mp4`` came back
    """
    manifests = [
        "info.checksum",
        "info.md5",
        "info.sfv",
        "info.sha1",
        "info.sha224",
        "info.sha256",
        "info.sha384",
        "info.sha512",
    ]
    mock_tree(mocker, [*manifests, "video.mp4"])

    assert names(enumerate_content_files(DIRECTORY_SCOPED_PATH)) == ["video.mp4"]


def test_structural_exclusions_survive_an_empty_pattern_list(mocker: MockerFixture) -> None:
    """They are not the user's to remove: emptying the editable list leaves all three excluded (#226).

    **Test steps:**

    * mock the tree to hold the three structural files and ``video.mp4``
    * enumerate with no excluded patterns at all
    * verify only ``video.mp4`` came back
    """
    mock_tree(mocker, ["info.rehu", "info00.jpg", "info.sfv", "video.mp4"])

    assert names(enumerate_content_files(DIRECTORY_SCOPED_PATH, ())) == ["video.mp4"]


def test_a_numbered_sibling_that_is_not_an_image_is_content(mocker: MockerFixture) -> None:
    """A screenshot is ``<slug>NN`` *plus an image suffix*, so ``info01.mp4`` is a video and counts.

    **Test steps:**

    * mock the tree to hold ``info00.jpg`` and ``info01.mp4``
    * enumerate ``info.rehu``'s content files
    * verify the screenshot was dropped and the video kept
    """
    mock_tree(mocker, ["info00.jpg", "info01.mp4"])

    assert names(enumerate_content_files(DIRECTORY_SCOPED_PATH)) == ["info01.mp4"]


def test_a_differently_shaped_numbered_name_is_content(mocker: MockerFixture) -> None:
    """Only a two-digit index off the slug is a screenshot: ``info1.jpg`` and ``lesson01.jpg`` are not.

    **Test steps:**

    * mock the tree to hold ``info1.jpg``, ``info001.jpg``, ``lesson01.jpg`` and ``info00.jpg``
    * enumerate ``info.rehu``'s content files
    * verify only the true screenshot was dropped
    """
    mock_tree(mocker, ["info1.jpg", "info001.jpg", "lesson01.jpg", "info00.jpg"])

    assert names(enumerate_content_files(DIRECTORY_SCOPED_PATH)) == ["info001.jpg", "info1.jpg", "lesson01.jpg"]


def test_structural_exclusions_apply_at_every_depth(mocker: MockerFixture) -> None:
    """A nested resource's record and screenshots are somebody else's editable files, and are dropped too.

    **Test steps:**

    * mock the tree to hold a nested ``part1/info.rehu``, ``part1/info00.jpg`` and ``part1/video.mp4``
    * enumerate the parent ``info.rehu``'s content files
    * verify only the nested video came back
    """
    mock_tree(mocker, ["part1/info.rehu", "part1/info00.jpg", "part1/video.mp4"], directories=["part1"])

    assert names(enumerate_content_files(DIRECTORY_SCOPED_PATH)) == ["part1/video.mp4"]


def test_directory_scoped_skips_anything_that_is_not_a_regular_file(mocker: MockerFixture) -> None:
    """A socket, a fifo or a broken symlink has no bytes to sum or hash, so it is not content.

    **Test steps:**

    * mock the tree to hold a regular ``video.mp4`` beside an entry that is neither file nor directory
    * enumerate ``info.rehu``'s content files
    * verify only the regular file came back
    """
    mock_tree(mocker, ["info.rehu", "video.mp4"], irregular=["dangling.mp4"])

    assert names(enumerate_content_files(DIRECTORY_SCOPED_PATH)) == ["video.mp4"]


def test_directory_scoped_skips_directories(mocker: MockerFixture) -> None:
    """Only regular files are content -- a directory has no size to sum and no bytes to hash.

    **Test steps:**

    * mock the tree to hold a ``part1`` directory and one file inside it
    * enumerate ``info.rehu``'s content files
    * verify the directory itself is not in the result
    """
    mock_tree(mocker, ["part1/video.mp4"], directories=["part1"])

    assert names(enumerate_content_files(DIRECTORY_SCOPED_PATH)) == ["part1/video.mp4"]


# endregion

# region directory-scoped, junk patterns


def test_the_default_patterns_drop_the_os_residue(mocker: MockerFixture) -> None:
    """Every shipped default matches what it was added for, and content around it survives (#226).

    **Test steps:**

    * mock the tree to hold each default's target beside ``video.mp4``
    * enumerate ``info.rehu``'s content files
    * verify only ``video.mp4`` came back
    """
    mock_tree(mocker, ["Thumbs.db", "ehthumbs.db", "desktop.ini", ".DS_Store", "._video.mp4", "video.mp4"])

    assert names(enumerate_content_files(DIRECTORY_SCOPED_PATH)) == ["video.mp4"]


def test_patterns_match_case_insensitively(mocker: MockerFixture) -> None:
    """One ``Thumbs.db`` pattern catches every casing an SMB share can hand back (#226).

    **Test steps:**

    * mock the tree to hold ``Thumbs.db``, ``THUMBS.DB`` and ``thumbs.db``
    * enumerate ``info.rehu``'s content files
    * verify none of the three survived
    """
    mock_tree(mocker, ["Thumbs.db", "THUMBS.DB", "thumbs.db"])

    assert enumerate_content_files(DIRECTORY_SCOPED_PATH) == []


def test_a_glob_pattern_matches_a_prefix(mocker: MockerFixture) -> None:
    """``._*`` is a glob, not a literal: it catches the AppleDouble sidecar and leaves the file alone.

    **Test steps:**

    * mock the tree to hold ``._foo.mp4`` and ``foo.mp4``
    * enumerate ``info.rehu``'s content files
    * verify the sidecar was dropped and the file kept
    """
    mock_tree(mocker, ["._foo.mp4", "foo.mp4"])

    assert names(enumerate_content_files(DIRECTORY_SCOPED_PATH)) == ["foo.mp4"]


def test_patterns_match_the_file_name_not_the_path(mocker: MockerFixture) -> None:
    """A pattern can never take out a whole subtree, only the files inside it that match by name.

    **Test steps:**

    * mock the tree to hold a directory *named* ``thumbs.db``, holding both ``video.mp4`` and a real
      ``Thumbs.db`` file
    * enumerate ``info.rehu``'s content files with the default patterns
    * verify the directory's own name excluded nothing, while the file inside it was excluded
    """
    mock_tree(mocker, ["thumbs.db/video.mp4", "thumbs.db/Thumbs.db"], directories=["thumbs.db"])

    assert names(enumerate_content_files(DIRECTORY_SCOPED_PATH)) == ["thumbs.db/video.mp4"]


def test_the_measured_set_changes_with_the_pattern_list(mocker: MockerFixture) -> None:
    """The set really is injected: a caller-supplied pattern changes what a scan sees (#226).

    **Test steps:**

    * mock the tree to hold ``notes.txt`` and ``video.mp4``
    * enumerate once with the shipped defaults and once with ``*.txt`` added
    * verify the second call dropped ``notes.txt`` the first one counted
    """
    mock_tree(mocker, ["notes.txt", "video.mp4"])

    assert names(enumerate_content_files(DIRECTORY_SCOPED_PATH)) == ["notes.txt", "video.mp4"]
    assert names(enumerate_content_files(DIRECTORY_SCOPED_PATH, (*EXCLUDED_FILE_PATTERNS, "*.txt"))) == ["video.mp4"]


def test_a_directory_symlink_is_never_descended(mocker: MockerFixture) -> None:
    """A symlink to a directory is skipped, not walked -- one at an ancestor would loop the scan forever.

    The walk asks ``is_dir(follow_symlinks=False)``, so a linked-in tree contributes nothing and a
    self-referential link cannot recurse. The fake models the link but not its target's listing: if the
    scanner *did* descend, it would raise on the unknown directory rather than pass.

    **Test steps:**

    * mock a tree holding real content beside a symlink to a directory
    * enumerate ``info.rehu``'s content files
    * verify only the real content came back, with no attempt to read through the link
    """
    mock_tree(mocker, ["info.rehu", "video.mp4"], directory_links=["loop"])

    assert names(enumerate_content_files(DIRECTORY_SCOPED_PATH)) == ["video.mp4"]


def test_directory_scoped_reports_an_unreadable_directory_as_empty(mocker: MockerFixture) -> None:
    """An offline mount reports as empty here too, rather than raising out of the walk.

    **Test steps:**

    * mock ``os.scandir`` to raise ``OSError``
    * enumerate ``info.rehu``'s content files
    * verify the result is empty and nothing was raised
    """
    mocker.patch("rehuco_core.rehu_content_files.os.scandir", side_effect=OSError)

    assert enumerate_content_files(DIRECTORY_SCOPED_PATH) == []


def test_an_unreadable_subdirectory_costs_only_its_own_contents(mocker: MockerFixture) -> None:
    """One offline branch of a mount does not take the whole measurement down with it.

    The scan descends directory by directory, so a subdirectory it cannot read is skipped where a single
    flattened walk would have had to abandon everything.

    **Test steps:**

    * mock a tree with a readable root and a subdirectory whose listing raises ``OSError``
    * enumerate ``info.rehu``'s content files
    * verify the root's content came back and nothing was raised
    """
    mock_tree(
        mocker,
        ["info.rehu", "video.mp4", "offline/hidden.mp4"],
        directories=["offline"],
        unreadable=["offline"],
    )

    assert names(enumerate_content_files(DIRECTORY_SCOPED_PATH)) == ["video.mp4"]


# endregion


# region size on disk


def mock_sizes(mocker: MockerFixture, sizes: dict[str, int], *, unreadable: list[str] | None = None) -> None:
    """Mock ``Path.stat`` so each fake path reports the size the test gave it.

    :param mocker: pytest-mock fixture.
    :param sizes: fake paths relative to :data:`DIRECTORY`, ``/``-separated, mapped to their byte size.
    :param unreadable: fake paths whose ``stat`` should raise ``OSError`` -- a file listed a moment ago
        and gone now, which the sum must survive.
    """
    gone = {DIRECTORY / name for name in unreadable or []}
    sized = {DIRECTORY / name: size for name, size in sizes.items()}

    def stat(path: Path, **_kwargs: object) -> SimpleNamespace:
        if path in gone:
            raise PermissionError(path)
        return SimpleNamespace(st_size=sized[path])

    mocker.patch.object(Path, "stat", autospec=True, side_effect=stat)


def test_the_size_is_the_sum_of_every_content_file(mocker: MockerFixture) -> None:
    """The footprint is what the content weighs, summed over the same set the checksums will cover (#226).

    **Test steps:**

    * mock a tree holding two videos, one of them nested, and give each a size
    * measure ``info.rehu``'s size on disk
    * verify the total is both files' bytes
    """
    mock_tree(mocker, ["info.rehu", "intro.mp4", "part1/lesson.mp4"], directories=["part1"])
    mock_sizes(mocker, {"intro.mp4": 1024, "part1/lesson.mp4": 2048})

    assert content_size_on_disk(DIRECTORY_SCOPED_PATH) == 3072


def test_the_resources_own_bookkeeping_weighs_nothing(mocker: MockerFixture) -> None:
    """The record, its screenshots and its manifest are excluded structurally, so editing a description
    or adding a screenshot never changes the measured size ([[data-model#checksums]]).

    **Test steps:**

    * mock a tree holding one video beside the record, a screenshot and a checksum manifest
    * measure ``info.rehu``'s size on disk
    * verify only the video counted
    """
    mock_tree(mocker, ["info.rehu", "info00.jpg", "info.sfv", "video.mp4"])
    mock_sizes(mocker, {"video.mp4": 4096})

    assert content_size_on_disk(DIRECTORY_SCOPED_PATH) == 4096


def test_junk_files_weigh_nothing_whatever_their_casing(mocker: MockerFixture) -> None:
    """A share's ``Thumbs.db`` is not content, and must not survive the scan by spelling -- SMB and
    macOS both hand back casings Windows never wrote (#226).

    **Test steps:**

    * mock a tree holding a video beside ``THUMBS.DB`` and a macOS AppleDouble file
    * measure ``info.rehu``'s size on disk
    * verify only the video counted
    """
    mock_tree(mocker, ["info.rehu", "video.mp4", "THUMBS.DB", "._video.mp4"])
    mock_sizes(mocker, {"video.mp4": 512})

    assert content_size_on_disk(DIRECTORY_SCOPED_PATH) == 512


def test_the_measured_size_follows_the_exclusion_list_it_is_handed(mocker: MockerFixture) -> None:
    """The set is injected, not read from a setting: the same tree measures differently under a
    different list, which is what lets the size scan and the checksums be handed one answer (#226).

    **Test steps:**

    * mock a tree holding a video beside a ``.tmp`` file
    * measure with the shipped defaults, and again with a list that excludes ``*.tmp``
    * verify the second measurement is smaller by the temporary file's bytes
    """
    mock_tree(mocker, ["info.rehu", "video.mp4", "scratch.tmp"])
    mock_sizes(mocker, {"video.mp4": 512, "scratch.tmp": 8})

    assert content_size_on_disk(DIRECTORY_SCOPED_PATH, EXCLUDED_FILE_PATTERNS) == 520
    assert content_size_on_disk(DIRECTORY_SCOPED_PATH, ("*.tmp",)) == 512


def test_a_file_scoped_resource_weighs_its_own_archive_alone(mocker: MockerFixture) -> None:
    """A file-scoped ``foo.rehu`` measures ``foo.zip`` and nothing else -- its neighbours are out of
    scope before any exclusion is consulted, so emptying the pattern list cannot reach them (#226).

    **Test steps:**

    * mock a directory holding ``foo.zip`` beside a whole other resource's files
    * measure ``foo.rehu``'s size on disk with the defaults, and again with no exclusions at all
    * verify both are ``foo.zip``'s bytes alone
    """
    mock_siblings(mocker, ["foo.zip", "info.rehu", "info00.jpg", "bar00.jpg", "bar.zip"])
    mock_sizes(mocker, {"foo.zip": 256})

    assert content_size_on_disk(FILE_SCOPED_PATH) == 256
    assert content_size_on_disk(FILE_SCOPED_PATH, ()) == 256


def test_an_unreadable_directory_measures_zero_without_raising(mocker: MockerFixture) -> None:
    """An offline mount is a document-level condition, not a crash: the enumeration already reports it as
    *nothing found* ([[mounts-and-storage#offline-mounts]]), and the sum has nothing to add.

    **Test steps:**

    * mock ``os.scandir`` to raise
    * measure ``info.rehu``'s size on disk
    * verify it is ``0`` and nothing was raised
    """
    mocker.patch("rehuco_core.rehu_content_files.os.scandir", side_effect=OSError)

    assert content_size_on_disk(DIRECTORY_SCOPED_PATH) == 0


def test_a_file_that_vanishes_mid_scan_costs_only_its_own_bytes(mocker: MockerFixture) -> None:
    """A file listed a moment ago and unreadable now -- deleted mid-scan, or a mount that went away --
    drops out of the total rather than taking the whole measurement down.

    **Test steps:**

    * mock a tree of two videos, one of which raises on ``stat``
    * measure ``info.rehu``'s size on disk
    * verify the readable one's bytes came back and nothing was raised
    """
    mock_tree(mocker, ["info.rehu", "here.mp4", "gone.mp4"])
    mock_sizes(mocker, {"here.mp4": 64, "gone.mp4": 1024}, unreadable=["gone.mp4"])

    assert content_size_on_disk(DIRECTORY_SCOPED_PATH) == 64


def test_a_resource_with_no_content_weighs_zero(mocker: MockerFixture) -> None:
    """A directory holding only the resource's own bookkeeping measures ``0`` -- there is content and
    there is none of it, which is a different answer from an unreadable mount only in how it got here.

    **Test steps:**

    * mock a tree holding just the record and its screenshot
    * measure ``info.rehu``'s size on disk
    * verify it is ``0``
    """
    mock_tree(mocker, ["info.rehu", "info00.jpg"])
    mock_sizes(mocker, {})

    assert content_size_on_disk(DIRECTORY_SCOPED_PATH) == 0


# endregion
