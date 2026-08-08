"""Tests for content-file enumeration -- the set the size scan and the checksums share (#226) -- and
for the size-on-disk sum over it (#223).
"""

# one walk answers for two features, two scopes, two exclusion tiers, both record formats and every way
# a directory can refuse to list; splitting that along any of those axes would separate cases that only
# make sense read against each other, so the module-length cap is lifted here instead.
# pylint: disable=too-many-lines

import re
from pathlib import Path
from types import SimpleNamespace
from typing import Final
from unittest.mock import MagicMock

from fake_directories import FakeDirEntry, FakeScandir
from pytest import mark, raises
from pytest_mock import MockerFixture
from rehuco_core import (
    EXCLUDED_FILE_PATTERNS,
    INFO_REHU_FILENAME,
    INFO_TC_FILENAME,
    ContentUnreachableError,
    CoveringRecord,
    content_size_on_disk,
    covering_content_records,
    enumerate_content_files,
    excluded_content_names,
)
from rehuco_core.rehu_content_files import MAX_NAMED_UNREADABLE

DIRECTORY: Final = Path("/fake/resource")
FILE_SCOPED_PATH: Final = DIRECTORY / "foo.rehu"
DIRECTORY_SCOPED_PATH: Final = DIRECTORY / INFO_REHU_FILENAME
LEGACY_DIRECTORY_SCOPED_PATH: Final = DIRECTORY / INFO_TC_FILENAME


def mock_tree(  # pylint: disable=too-many-arguments
    mocker: MockerFixture,
    filenames: list[str],
    *,
    directories: list[str] | None = None,
    unreadable: list[str] | None = None,
    irregular: list[str] | None = None,
    directory_links: list[str] | None = None,
) -> MagicMock:
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
    :returns: the patched ``os.scandir``, for the tests that count how many directories were listed.
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

    return mocker.patch("rehuco_core.rehu_content_files.os.scandir", side_effect=scandir)


def mock_siblings(mocker: MockerFixture, filenames: list[str]) -> None:
    """Mock :data:`DIRECTORY` as a flat directory holding ``filenames``, all of them regular files.

    :param mocker: pytest-mock fixture.
    :param filenames: the fake filenames the directory should list.
    """
    mock_tree(mocker, filenames)


def content_files(rehu_path: Path, excluded_patterns: tuple[str, ...] = EXCLUDED_FILE_PATTERNS) -> list[Path]:
    """The walk's files alone, for the tests that are about the two exclusion tiers.

    What a walk could not read is its own group of tests below (#245); everywhere else the files are the
    subject, and going through the enumeration's other member each time would say nothing.

    :param rehu_path: the resource's ``.rehu`` file.
    :param excluded_patterns: the junk globs, defaulting the way the real call does.
    :returns: the content file paths.
    """
    return enumerate_content_files(rehu_path, excluded_patterns).files


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

    assert names(content_files(FILE_SCOPED_PATH)) == ["foo.zip"]


def test_file_scoped_is_unaffected_by_an_empty_pattern_list(mocker: MockerFixture) -> None:
    """No pattern can widen a whitelist of one, so emptying the editable list changes nothing (#226).

    **Test steps:**

    * mock the same directory as the previous test
    * enumerate ``foo.rehu``'s content files with no excluded patterns at all
    * verify the answer is still ``foo.zip`` alone
    """
    mock_siblings(mocker, ["foo.zip", "info.rehu", "info00.jpg", "bar00.jpg", "bar.zip"])

    assert names(content_files(FILE_SCOPED_PATH, ())) == ["foo.zip"]


def test_file_scoped_drops_its_own_record_screenshots_and_manifest(mocker: MockerFixture) -> None:
    """The structural tier applies to a file-scoped resource too -- it has bookkeeping of its own.

    **Test steps:**

    * mock the directory to hold ``foo.zip`` beside ``foo.rehu``, ``foo00.jpg``, ``foo01.png`` and
      ``foo.sfv``
    * enumerate ``foo.rehu``'s content files
    * verify only ``foo.zip`` came back
    """
    mock_siblings(mocker, ["foo.rehu", "foo.zip", "foo00.jpg", "foo01.png", "foo.sfv"])

    assert names(content_files(FILE_SCOPED_PATH)) == ["foo.zip"]


def test_file_scoped_takes_every_same_stem_sibling_whatever_its_format(mocker: MockerFixture) -> None:
    """Content is what shares the stem, not a fixed extension list: a single-file tutorial counts too.

    **Test steps:**

    * mock the directory to hold ``foo.mp4`` and ``foo.zip`` beside ``foo.rehu``
    * enumerate ``foo.rehu``'s content files
    * verify both non-bookkeeping siblings came back, sorted by name
    """
    mock_siblings(mocker, ["foo.zip", "foo.rehu", "foo.mp4"])

    assert names(content_files(FILE_SCOPED_PATH)) == ["foo.mp4", "foo.zip"]


def test_file_scoped_matches_its_stem_case_insensitively(mocker: MockerFixture) -> None:
    """SMB and macOS hand back casings Windows never wrote, so a sibling must not escape by spelling.

    **Test steps:**

    * mock the directory to hold ``FOO.ZIP``
    * enumerate ``foo.rehu``'s content files
    * verify it was recognized as the resource's own file
    """
    mock_siblings(mocker, ["FOO.ZIP"])

    assert names(content_files(FILE_SCOPED_PATH)) == ["FOO.ZIP"]


def test_file_scoped_reports_an_unreadable_directory_as_empty(mocker: MockerFixture) -> None:
    """An offline mount is a document-level condition, not a crash ([[mounts-and-storage#offline-mounts]]).

    **Test steps:**

    * mock ``os.scandir`` to raise ``OSError``
    * enumerate ``foo.rehu``'s content files
    * verify the result is empty and nothing was raised
    """
    mocker.patch("rehuco_core.rehu_content_files.os.scandir", side_effect=OSError)

    assert not content_files(FILE_SCOPED_PATH)


# endregion

# region directory-scoped, structural exclusions


def test_every_rehu_in_the_tree_takes_its_own_bookkeeping_with_it(mocker: MockerFixture) -> None:
    """No ``.rehu``'s files are ever counted -- not the scanner's own, not a nested or neighboring one.

    A record, its screenshots and its manifest can all change at any moment, so counting any of them
    would make a size or a checksum need recomputing after an ordinary metadata edit
    ([[data-model#checksums]]). Their *content* leaves too, but under the coverage rule rather than this
    one (#254): ``bar/video.mp4`` is the nested record's and ``baz.zip`` is ``baz.rehu``'s, so the root
    is left with the one file nothing else claims.

    **Test steps:**

    * mock a tree holding the scanning ``info.rehu``, a nested ``bar/info.rehu`` and a file-scoped
      ``baz.rehu``, each with its own screenshots and manifests, plus a video only the root can claim
    * enumerate ``info.rehu``'s content files
    * verify only that video came back
    """
    mock_tree(
        mocker,
        [
            "info.rehu",
            "info00.jpg",
            "video.mp4",
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

    assert names(content_files(DIRECTORY_SCOPED_PATH)) == ["video.mp4"]


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

    assert names(content_files(DIRECTORY_SCOPED_PATH)) == ["bar/info00.jpg", "xxx00.jpg", "yyy.sfv"]


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

    assert names(content_files(DIRECTORY_SCOPED_PATH)) == ["lesson01.jpg", "pack.sfv"]


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
    assert names(content_files(DIRECTORY_SCOPED_PATH)) == []

    mock_tree(mocker, ["info.rehu", "baz00.jpg", "baz.sfv"])
    assert names(content_files(DIRECTORY_SCOPED_PATH)) == ["baz.sfv", "baz00.jpg"]


def test_directory_scoped_drops_the_record_screenshots_and_manifest_by_slug(mocker: MockerFixture) -> None:
    """The three record-derived structural exclusions never count.

    **Test steps:**

    * mock the tree to hold ``info.rehu``, ``info00.jpg``, ``info01.png``, ``info.sfv`` and ``video.mp4``
    * enumerate ``info.rehu``'s content files
    * verify only ``video.mp4`` came back
    """
    mock_tree(mocker, ["info.rehu", "info00.jpg", "info01.png", "info.sfv", "video.mp4"])

    assert names(content_files(DIRECTORY_SCOPED_PATH)) == ["video.mp4"]


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

    assert names(content_files(DIRECTORY_SCOPED_PATH)) == ["video.mp4"]


def test_structural_exclusions_survive_an_empty_pattern_list(mocker: MockerFixture) -> None:
    """They are not the user's to remove: emptying the editable list leaves all three excluded (#226).

    **Test steps:**

    * mock the tree to hold the three record-derived structural files and ``video.mp4``
    * enumerate with no excluded patterns at all
    * verify only ``video.mp4`` came back
    """
    mock_tree(mocker, ["info.rehu", "info00.jpg", "info.sfv", "video.mp4"])

    assert names(content_files(DIRECTORY_SCOPED_PATH, ())) == ["video.mp4"]


def test_a_numbered_sibling_that_is_not_an_image_is_content(mocker: MockerFixture) -> None:
    """A screenshot is ``<slug>NN`` *plus an image suffix*, so ``info01.mp4`` is a video and counts.

    **Test steps:**

    * mock the tree to hold ``info00.jpg`` and ``info01.mp4``
    * enumerate ``info.rehu``'s content files
    * verify the screenshot was dropped and the video kept
    """
    mock_tree(mocker, ["info00.jpg", "info01.mp4"])

    assert names(content_files(DIRECTORY_SCOPED_PATH)) == ["info01.mp4"]


def test_a_differently_shaped_numbered_name_is_content(mocker: MockerFixture) -> None:
    """Only a two-digit index off the slug is a screenshot: ``info1.jpg`` and ``lesson01.jpg`` are not.

    **Test steps:**

    * mock the tree to hold ``info1.jpg``, ``info001.jpg``, ``lesson01.jpg`` and ``info00.jpg``
    * enumerate ``info.rehu``'s content files
    * verify only the true screenshot was dropped
    """
    mock_tree(mocker, ["info1.jpg", "info001.jpg", "lesson01.jpg", "info00.jpg"])

    assert names(content_files(DIRECTORY_SCOPED_PATH)) == ["info001.jpg", "info1.jpg", "lesson01.jpg"]


def test_a_record_less_subdirectory_is_the_enclosing_resources_at_every_depth(mocker: MockerFixture) -> None:
    """A subdirectory carrying no record of its own is still the enclosing resource's, at any depth.

    The coverage rule turns on a record, not on a level: ``part1`` has none, so everything in it that
    the root's own bookkeeping rules do not claim is the root's -- while ``part1/deep/info00.jpg`` is
    still a normal file, because the root's record does not reach down to name it.

    **Test steps:**

    * mock the tree to hold a record-less ``part1`` two levels deep, holding a video and a name shaped
      like a screenshot that no record beside it claims
    * enumerate the parent ``info.rehu``'s content files
    * verify both came back
    """
    mock_tree(
        mocker,
        ["info.rehu", "part1/video.mp4", "part1/deep/info00.jpg"],
        directories=["part1", "part1/deep"],
    )

    assert names(content_files(DIRECTORY_SCOPED_PATH)) == ["part1/deep/info00.jpg", "part1/video.mp4"]


def test_a_nested_record_takes_its_whole_directory_out(mocker: MockerFixture) -> None:
    """A subdirectory holding an ``info.rehu`` is that record's, wholesale -- files, subtree and all
    (#254).

    Not just its bookkeeping: the ancestor stops at the directory rather than descending and dropping
    the record's own files, which is what makes summing every record's size answer a library's instead
    of counting every nested resource once more for each ancestor above it.

    **Test steps:**

    * mock the tree to hold a nested ``part1/info.rehu`` over a video and a deeper subdirectory of its
      own, beside a video the root still owns
    * enumerate the parent ``info.rehu``'s content files
    * verify only the root's video came back
    """
    mock_tree(
        mocker,
        ["info.rehu", "video.mp4", "part1/info.rehu", "part1/info00.jpg", "part1/lesson.mp4", "part1/deep/extra.mp4"],
        directories=["part1", "part1/deep"],
    )

    assert names(content_files(DIRECTORY_SCOPED_PATH)) == ["video.mp4"]


def test_a_nested_legacy_record_takes_its_whole_directory_out(mocker: MockerFixture) -> None:
    """An unconverted ``info.tc`` is a directory-scoped record, so it draws the same boundary (#250, #254).

    Without that, converting the nested resource would move its files from the parent's content into
    its own for a reason that has nothing to do with what either of them holds -- and a claim seeded
    from the old ``.sfv`` (#243) would describe a resource that had changed underneath it.

    **Test steps:**

    * mock the tree to hold a nested ``part1/info.tc`` over its own manifest and video, beside a video
      the root still owns
    * enumerate the parent ``info.rehu``'s content files
    * verify only the root's video came back
    """
    mock_tree(
        mocker,
        ["info.rehu", "video.mp4", "part1/info.tc", "part1/info.sfv", "part1/lesson.mp4"],
        directories=["part1"],
    )

    assert names(content_files(DIRECTORY_SCOPED_PATH)) == ["video.mp4"]


def test_a_file_scoped_neighbour_takes_its_same_stem_siblings_out(mocker: MockerFixture) -> None:
    """A named ``foo.rehu`` describes its same-stem siblings, so they are its and not the directory's
    (#254).

    Every ``foo.*`` goes, not only the archive: a file-scoped record's content is the whole same-stem
    set, and both walks have to draw that set the same way or a file lands in neither record or in
    both. The stem is compared whole, so ``foo.part2.zip`` -- stem ``foo.part2`` -- is not ``foo.rehu``'s
    and stays where it was.

    **Test steps:**

    * mock the directory to hold ``info.rehu`` beside a file-scoped ``foo.rehu`` with two same-stem
      files, a third that only shares a prefix, and one file sharing nothing
    * enumerate ``info.rehu``'s content files
    * verify only the unclaimed file came back
    """
    mock_tree(mocker, ["info.rehu", "foo.rehu", "foo.zip", "foo.pdf", "foo.part2.zip", "readme.txt"])

    assert names(content_files(DIRECTORY_SCOPED_PATH)) == ["foo.part2.zip", "readme.txt"]


def test_a_conversions_retained_backups_are_not_the_resources_content(mocker: MockerFixture) -> None:
    """A backup is bookkeeping in the same sense the record it backs up is (#253).

    A bulk import retains every ``.orig`` ([[acquisition-tooling#convert-mechanics]]), so counting them
    would bake each converted resource's own backups into its first checksum baseline -- and discarding
    them afterwards would report a missing file for every resource in the catalog.

    **Test steps:**

    * mock a converted tree: the written record and screenshot, the backed-up ``.tc`` and legacy
      screenshots, and a second converted resource file-scoped beside it, all around one real video
    * enumerate ``info.rehu``'s content files
    * verify only the video came back
    """
    mock_tree(
        mocker,
        [
            "info.rehu",
            "info00.jpg",
            "info.tc.orig",
            "cover.jpg.orig",
            "video.mp4",
            "pack.rehu",
            "pack.tc.orig",
            "pack.zip",
        ],
    )

    assert names(content_files(DIRECTORY_SCOPED_PATH)) == ["video.mp4"]


def test_any_orig_sibling_is_a_backup_whatever_it_backs_up(mocker: MockerFixture) -> None:
    """One definition of a backup, and it is the backups module's: **any** ``.orig`` sibling, matched on
    no record and no stem (#253).

    A legacy screenshot is named ``cover.jpg`` or ``sample-01.jpg`` and carries nothing tying it to the
    resource it belongs to, which is why a revert enumerates a directory rather than a stem. Following a
    narrower rule here would count files a revert is holding -- and would drop them again the moment the
    backups were discarded.

    **Test steps:**

    * mock a tree holding a ``.orig`` no conversion would have written, beside a name that only looks
      like one
    * enumerate ``info.rehu``'s content files
    * verify the ``.orig`` was skipped and the look-alike counted
    """
    mock_tree(mocker, ["info.rehu", "render.blend.orig", "notes.orig.txt"])

    assert names(content_files(DIRECTORY_SCOPED_PATH)) == ["notes.orig.txt"]


def test_backups_are_excluded_whatever_the_pattern_list_says(mocker: MockerFixture) -> None:
    """Structural, not junk: emptying the editable list leaves the backups excluded (#253).

    **Test steps:**

    * mock a converted tree
    * enumerate with no excluded patterns at all
    * verify only the content came back
    """
    mock_tree(mocker, ["info.rehu", "info.tc.orig", "cover.jpg.orig", "video.mp4"])

    assert names(content_files(DIRECTORY_SCOPED_PATH, ())) == ["video.mp4"]


def test_a_file_scoped_resource_skips_its_own_backups_too(mocker: MockerFixture) -> None:
    """The structural tier reaches the whitelist as well: a same-stem ``.orig`` is still a backup (#253).

    **Test steps:**

    * mock the directory to hold ``foo.zip`` beside ``foo.rehu`` and a ``foo.orig`` backup
    * enumerate ``foo.rehu``'s content files
    * verify only ``foo.zip`` came back
    """
    mock_siblings(mocker, ["foo.rehu", "foo.zip", "foo.orig"])

    assert names(content_files(FILE_SCOPED_PATH)) == ["foo.zip"]


def test_directory_scoped_skips_anything_that_is_not_a_regular_file(mocker: MockerFixture) -> None:
    """A socket, a fifo or a broken symlink has no bytes to sum or hash, so it is not content.

    **Test steps:**

    * mock the tree to hold a regular ``video.mp4`` beside an entry that is neither file nor directory
    * enumerate ``info.rehu``'s content files
    * verify only the regular file came back
    """
    mock_tree(mocker, ["info.rehu", "video.mp4"], irregular=["dangling.mp4"])

    assert names(content_files(DIRECTORY_SCOPED_PATH)) == ["video.mp4"]


def test_directory_scoped_skips_directories(mocker: MockerFixture) -> None:
    """Only regular files are content -- a directory has no size to sum and no bytes to hash.

    **Test steps:**

    * mock the tree to hold a ``part1`` directory and one file inside it
    * enumerate ``info.rehu``'s content files
    * verify the directory itself is not in the result
    """
    mock_tree(mocker, ["part1/video.mp4"], directories=["part1"])

    assert names(content_files(DIRECTORY_SCOPED_PATH)) == ["part1/video.mp4"]


# endregion

# region legacy .tc records


def test_an_info_tc_is_walked_as_the_directory_it_describes(mocker: MockerFixture) -> None:
    """``info.tc`` is directory-scoped in exactly the sense ``info.rehu`` is (#250).

    tc4 wrote one per resource directory, so taking the file-scoped branch collapsed a whole tutorial's
    content to the ``.tc`` file itself -- which is what made ``Verify checksums`` on an unconverted
    resource write a record whose baseline was one small YAML file.

    **Test steps:**

    * mock a tree holding ``info.tc`` over real content in the root and a subdirectory
    * enumerate ``info.tc``'s content files
    * verify the tree's content came back, the ``.tc`` itself excluded
    """
    mock_tree(mocker, ["info.tc", "video.mp4", "part1/video.mp4"], directories=["part1"])

    assert names(content_files(LEGACY_DIRECTORY_SCOPED_PATH)) == ["part1/video.mp4", "video.mp4"]


def test_a_legacy_record_claims_the_same_bookkeeping_its_conversion_will(mocker: MockerFixture) -> None:
    """An ``info.tc`` claims the ``info.*`` siblings beside it, as the ``info.rehu`` replacing it will.

    This is what makes a resource's content set survive its own conversion: measure the directory
    before, convert it, measure it again, and the answer is the same set for a directory whose content
    nobody touched.

    **Test steps:**

    * mock a tree holding ``info.tc`` beside its ``info.sfv``, ``info.checksum`` and ``info00.jpg``,
      plus the ``video.mp4`` that is the actual content
    * enumerate ``info.tc``'s content files
    * verify only the content came back
    """
    mock_tree(mocker, ["info.tc", "info.sfv", "info.checksum", "info00.jpg", "video.mp4"])

    assert names(content_files(LEGACY_DIRECTORY_SCOPED_PATH)) == ["video.mp4"]


def test_a_nested_legacy_record_is_bookkeeping_to_the_resource_above_it(mocker: MockerFixture) -> None:
    """A ``.tc`` found in the tree is a record, wherever it sits -- never the enclosing resource's content.

    The same rule every ``.rehu`` in the tree is under, and for the same reason: without it, converting
    the nested resource would change its parent's content set for a reason that has nothing to do with
    what the parent holds. Its real content leaves with it under the coverage rule (#254): a
    directory-scoped ``bar/info.tc`` claims ``bar`` and a file-scoped ``baz.tc`` claims ``baz.zip``.

    **Test steps:**

    * mock a tree holding a nested ``bar/info.tc`` with its own manifest and content, and a file-scoped
      ``baz.tc`` at the root beside the archive it describes, around one video the root still owns
    * enumerate the root ``info.rehu``'s content files
    * verify only that video came back
    """
    mock_tree(
        mocker,
        ["info.rehu", "video.mp4", "bar/info.tc", "bar/info.sfv", "bar/lesson.mp4", "baz.tc", "baz.sfv", "baz.zip"],
        directories=["bar"],
    )

    assert names(content_files(DIRECTORY_SCOPED_PATH)) == ["video.mp4"]


def test_a_legacy_record_claims_its_screenshots_by_scheme(mocker: MockerFixture) -> None:
    """tc4's screenshot names are bookkeeping too -- they are what a conversion renames aside (#250).

    None of them carries the record's name (``01.jpg``, ``cover.jpg``, ``sample-01.jpg``,
    ``file(2).jpg``, ``file-01.jpg``), so the ``<record>NN`` rule cannot see them. Counting them would
    make the same directory measure differently the moment it was converted, since a conversion backs up
    every recognized image -- winners and losing variants alike -- and installs the winners under names
    this walk already excludes.

    **Test steps:**

    * mock a tree holding ``info.tc`` over one file of every recognized scheme, plus real content
    * enumerate ``info.tc``'s content files
    * verify only the content came back
    """
    mock_tree(
        mocker,
        ["info.tc", "01.jpg", "cover.jpg", "sample-01.jpg", "file(2).jpg", "file-01.jpg", "video.mp4"],
    )

    assert names(content_files(LEGACY_DIRECTORY_SCOPED_PATH)) == ["video.mp4"]


def test_a_legacy_screenshot_name_is_content_where_no_legacy_record_sits(mocker: MockerFixture) -> None:
    """The scheme alone proves nothing -- a live tutorial's own ``01.jpg`` is content, and stays counted.

    The same condition every other structural exclusion is under: a name is bookkeeping *because a
    record claims it*. Legacy screenshots are claimed by the directory rather than by a stem, for the
    reason :mod:`rehuco_core.tc_conversion_backups` gives about the backups, so the claim needs a ``.tc``
    in that directory -- and a converted resource, whose ``.tc`` is now an ``.orig``, makes no claim at
    all.

    **Test steps:**

    * mock a tree whose root holds ``info.rehu`` over legacy-shaped image names, and a record-less
      subdirectory holding the same names
    * enumerate ``info.rehu``'s content files
    * verify every one of them counted
    """
    mock_tree(
        mocker,
        ["info.rehu", "01.jpg", "cover.jpg", "bar/01.jpg", "bar/cover.jpg", "bar/video.mp4"],
        directories=["bar"],
    )

    assert names(content_files(DIRECTORY_SCOPED_PATH)) == [
        "01.jpg",
        "bar/01.jpg",
        "bar/cover.jpg",
        "bar/video.mp4",
        "cover.jpg",
    ]


def test_a_named_legacy_record_stays_file_scoped(mocker: MockerFixture) -> None:
    """A named ``foo.tc`` behaves as ``foo.rehu`` does: its same-stem siblings, and not itself.

    The rule is about the one filename that means *this record describes its directory*, not about the
    extension -- so nothing here changes for a legacy record that was never directory-scoped.

    **Test steps:**

    * mock the directory to hold ``foo.tc`` beside its ``foo.zip`` and ``foo.sfv``, plus another
      resource's files
    * enumerate ``foo.tc``'s content files
    * verify only ``foo.zip`` came back
    """
    mock_siblings(mocker, ["foo.tc", "foo.zip", "foo.sfv", "bar.tc", "bar.zip"])

    assert names(content_files(DIRECTORY / "foo.tc")) == ["foo.zip"]


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

    assert names(content_files(DIRECTORY_SCOPED_PATH)) == ["video.mp4"]


def test_patterns_match_case_insensitively(mocker: MockerFixture) -> None:
    """One ``Thumbs.db`` pattern catches every casing an SMB share can hand back (#226).

    **Test steps:**

    * mock the tree to hold ``Thumbs.db``, ``THUMBS.DB`` and ``thumbs.db``
    * enumerate ``info.rehu``'s content files
    * verify none of the three survived
    """
    mock_tree(mocker, ["Thumbs.db", "THUMBS.DB", "thumbs.db"])

    assert not content_files(DIRECTORY_SCOPED_PATH)


def test_a_glob_pattern_matches_a_prefix(mocker: MockerFixture) -> None:
    """``._*`` is a glob, not a literal: it catches the AppleDouble sidecar and leaves the file alone.

    **Test steps:**

    * mock the tree to hold ``._foo.mp4`` and ``foo.mp4``
    * enumerate ``info.rehu``'s content files
    * verify the sidecar was dropped and the file kept
    """
    mock_tree(mocker, ["._foo.mp4", "foo.mp4"])

    assert names(content_files(DIRECTORY_SCOPED_PATH)) == ["foo.mp4"]


def test_patterns_match_the_file_name_not_the_path(mocker: MockerFixture) -> None:
    """A pattern can never take out a whole subtree, only the files inside it that match by name.

    **Test steps:**

    * mock the tree to hold a directory *named* ``thumbs.db``, holding both ``video.mp4`` and a real
      ``Thumbs.db`` file
    * enumerate ``info.rehu``'s content files with the default patterns
    * verify the directory's own name excluded nothing, while the file inside it was excluded
    """
    mock_tree(mocker, ["thumbs.db/video.mp4", "thumbs.db/Thumbs.db"], directories=["thumbs.db"])

    assert names(content_files(DIRECTORY_SCOPED_PATH)) == ["thumbs.db/video.mp4"]


def test_the_measured_set_changes_with_the_pattern_list(mocker: MockerFixture) -> None:
    """The set really is injected: a caller-supplied pattern changes what a scan sees (#226).

    **Test steps:**

    * mock the tree to hold ``notes.txt`` and ``video.mp4``
    * enumerate once with the shipped defaults and once with ``*.txt`` added
    * verify the second call dropped ``notes.txt`` the first one counted
    """
    mock_tree(mocker, ["notes.txt", "video.mp4"])

    assert names(content_files(DIRECTORY_SCOPED_PATH)) == ["notes.txt", "video.mp4"]
    assert names(content_files(DIRECTORY_SCOPED_PATH, (*EXCLUDED_FILE_PATTERNS, "*.txt"))) == ["video.mp4"]


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

    assert names(content_files(DIRECTORY_SCOPED_PATH)) == ["video.mp4"]


def test_directory_scoped_reports_an_unreadable_directory_as_empty(mocker: MockerFixture) -> None:
    """An offline mount answers with no files rather than raising out of the walk -- what it *says* about
    the directory is the next region's subject (#245); here it is only that nothing escapes.

    **Test steps:**

    * mock ``os.scandir`` to raise ``OSError``
    * enumerate ``info.rehu``'s content files
    * verify the result is empty and nothing was raised
    """
    mocker.patch("rehuco_core.rehu_content_files.os.scandir", side_effect=OSError)

    assert not content_files(DIRECTORY_SCOPED_PATH)


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

    assert names(content_files(DIRECTORY_SCOPED_PATH)) == ["video.mp4"]


# endregion


# region what the walk could not read


def test_a_walk_over_a_readable_tree_reports_nothing_unreadable(mocker: MockerFixture) -> None:
    """The ordinary case, pinned so *complete* means something: a tree that listed is reachable, complete,
    and names no branch (#245).

    **Test steps:**

    * mock a readable tree with a subdirectory
    * enumerate ``info.rehu``'s content
    * verify it is reachable and complete, with an empty unreadable list
    """
    mock_tree(mocker, ["info.rehu", "video.mp4", "part1/lesson.mp4"], directories=["part1"])

    enumeration = enumerate_content_files(DIRECTORY_SCOPED_PATH)

    assert enumeration.reachable
    assert enumeration.complete
    assert not enumeration.unreadable
    enumeration.require_complete()


def test_a_resource_whose_own_directory_will_not_list_is_unreachable(mocker: MockerFixture) -> None:
    """*Away* is not *empty* (#245): the walk still answers rather than raising, but it says which it is,
    and the resource's own directory is named as the one that would not list.

    **Test steps:**

    * mock ``os.scandir`` to raise
    * enumerate ``info.rehu``'s content
    * verify it came back empty and unreachable, and that both guards refuse
    """
    mocker.patch("rehuco_core.rehu_content_files.os.scandir", side_effect=OSError)

    enumeration = enumerate_content_files(DIRECTORY_SCOPED_PATH)

    assert not enumeration.files
    assert not enumeration.reachable
    assert enumeration.unreadable == (DIRECTORY,)
    with raises(ContentUnreachableError, match=re.escape(str(DIRECTORY))):
        enumeration.require_reachable()
    with raises(ContentUnreachableError, match=re.escape(str(DIRECTORY))):
        enumeration.require_complete()


def test_a_file_scoped_resource_whose_directory_will_not_list_is_unreachable(mocker: MockerFixture) -> None:
    """The whitelist of one is still read from a directory, so it is unreachable for the same reason.

    **Test steps:**

    * mock ``os.scandir`` to raise
    * enumerate ``foo.rehu``'s content
    * verify the directory is reported unreadable rather than the resource reading as empty
    """
    mocker.patch("rehuco_core.rehu_content_files.os.scandir", side_effect=OSError)

    enumeration = enumerate_content_files(FILE_SCOPED_PATH)

    assert not enumeration.files
    assert enumeration.unreadable == (DIRECTORY,)


def test_an_offline_branch_is_reachable_but_incomplete(mocker: MockerFixture) -> None:
    """The distinction the two guards exist for: a verify carries on over a branch it cannot see, while a
    measurement over the whole resource must not (#245).

    **Test steps:**

    * mock a tree with a readable root and a branch whose listing raises
    * enumerate ``info.rehu``'s content
    * verify the root's file came back, the resource is reachable, and only completeness is refused
    """
    mock_tree(
        mocker,
        ["info.rehu", "video.mp4", "offline/hidden.mp4"],
        directories=["offline"],
        unreadable=["offline"],
    )

    enumeration = enumerate_content_files(DIRECTORY_SCOPED_PATH)

    assert names(enumeration.files) == ["video.mp4"]
    assert enumeration.reachable
    assert not enumeration.complete
    assert enumeration.unreadable == (DIRECTORY / "offline",)
    enumeration.require_reachable()
    with raises(ContentUnreachableError, match="offline"):
        enumeration.require_complete()


def test_the_refusal_names_a_few_branches_and_counts_the_rest(mocker: MockerFixture) -> None:
    """A tree that went away wholesale has one unreadable directory per branch, and a sentence listing
    forty says less than one listing three.

    **Test steps:**

    * mock a tree whose four subdirectories all refuse to list
    * enumerate ``info.rehu``'s content
    * verify the text names three of them and counts the fourth
    """
    branches = ["a", "b", "c", "d"]
    mock_tree(mocker, ["info.rehu"], directories=branches, unreadable=branches)

    text = enumerate_content_files(DIRECTORY_SCOPED_PATH).unreadable_text()

    assert text.count(str(DIRECTORY)) == MAX_NAMED_UNREADABLE
    assert text.endswith("(and 1 more)")


# endregion


# region names that were never content


def test_excluded_names_reports_each_structural_kind(mocker: MockerFixture) -> None:
    """The structural tier, asked from names rather than from a walk (#254).

    Every kind a record claims: the record itself, its screenshots, its manifest, and a retained
    conversion backup -- the four an older coverage rule adopted into records that still hold them.

    **Test steps:**

    * mock a tree holding all four beside real content
    * ask which of their names were never content
    * verify all four came back structural and the content did not come back at all
    """
    mock_tree(mocker, ["info.rehu", "info00.jpg", "info.sfv", "info.tc.orig", "video.mp4"])

    excluded = excluded_content_names(
        DIRECTORY_SCOPED_PATH, ["info.rehu", "info00.jpg", "info.sfv", "info.tc.orig", "video.mp4"]
    )

    assert excluded == {
        "info.rehu": "structural",
        "info00.jpg": "structural",
        "info.sfv": "structural",
        "info.tc.orig": "structural",
    }


def test_excluded_names_reports_a_junk_glob_under_its_own_tier(mocker: MockerFixture) -> None:
    """The two tiers are told apart, because one of them is the user's and the other is not (#226).

    **Test steps:**

    * mock a tree holding a ``Thumbs.db``
    * ask about it
    * verify it came back under the junk tier
    """
    mock_tree(mocker, ["info.rehu", "Thumbs.db"])

    assert excluded_content_names(DIRECTORY_SCOPED_PATH, ["Thumbs.db"]) == {"Thumbs.db": "junk"}


def test_excluded_names_decides_on_the_name_not_on_the_file_being_there(mocker: MockerFixture) -> None:
    """A deleted file and an excluded one look identical to a walk, so absence decides nothing (#254).

    A record's entry for a file that is merely gone must stay ``missing`` and keep its hash, while one
    for a backup that has since been discarded is still a backup and still goes.

    **Test steps:**

    * mock a tree holding neither name
    * ask about a deleted video and a discarded backup
    * verify only the backup came back
    """
    mock_tree(mocker, ["info.rehu"])

    assert excluded_content_names(DIRECTORY_SCOPED_PATH, ["gone.mp4", "info.tc.orig"]) == {"info.tc.orig": "structural"}


def test_excluded_names_leaves_out_a_name_another_record_now_covers(mocker: MockerFixture) -> None:
    """Content that moved to another record is not *excluded* -- it is somebody's, and its claim moves
    with it (#257).

    Both halves of the coverage rule: a nested directory-scoped record, and a file-scoped record's
    same-stem sibling. Neither name comes back, so a verify keeps both entries.

    **Test steps:**

    * mock a tree with a nested ``bar/info.rehu`` and a file-scoped ``baz.rehu``, each over its content
    * ask about both contents, and about the nested record's own screenshot
    * verify only the screenshot came back, since it was never anybody's content
    """
    mock_tree(
        mocker,
        ["info.rehu", "bar/info.rehu", "bar/info00.jpg", "bar/video.mp4", "baz.rehu", "baz.zip"],
        directories=["bar"],
    )

    excluded = excluded_content_names(DIRECTORY_SCOPED_PATH, ["bar/video.mp4", "baz.zip", "bar/info00.jpg"])

    assert excluded == {"bar/info00.jpg": "structural"}


def test_excluded_names_reads_each_directory_once(mocker: MockerFixture) -> None:
    """A record naming two hundred files in three directories costs three listings, not two hundred.

    **Test steps:**

    * mock a tree of two subdirectories, and count the listings
    * ask about four names spread over the root and both of them
    * verify one listing per distinct directory
    """
    scandir = mock_tree(mocker, ["info.rehu", "a/one.mp4", "a/two.mp4", "b/three.mp4"], directories=["a", "b"])

    excluded_content_names(DIRECTORY_SCOPED_PATH, ["info.tc.orig", "a/one.mp4", "a/two.mp4", "b/three.mp4"])

    assert scandir.call_count == 3


def test_a_file_scoped_resources_entries_are_never_junk_pruned(mocker: MockerFixture) -> None:
    """A file-scoped record's content is a whitelist no pattern reaches, in both directions (#226).

    ``foo.tmp`` beside ``foo.rehu`` is that resource's content however the junk list is spelled, so a
    verify may not drop its entry on a glob the walk never applies.

    **Test steps:**

    * mock the directory to hold ``foo.tmp`` beside ``foo.rehu``
    * ask about it with a pattern that matches its name
    * verify nothing came back
    """
    mock_siblings(mocker, ["foo.rehu", "foo.tmp"])

    assert not excluded_content_names(FILE_SCOPED_PATH, ["foo.tmp"], ("*.tmp",))


def test_excluded_names_over_an_unreadable_directory_keeps_what_it_cannot_judge(mocker: MockerFixture) -> None:
    """A branch that will not list claims nothing, so only the name-only rules can still fire.

    A ``.orig`` is a backup by its name alone and still goes; a ``bar/info00.jpg`` needs a record beside
    it to be a screenshot, and with no listing there is no such evidence -- so the entry stays.

    **Test steps:**

    * mock a tree whose ``bar`` refuses to list
    * ask about a backup and a screenshot-shaped name inside it
    * verify only the backup came back
    """
    mock_tree(mocker, ["info.rehu"], directories=["bar"], unreadable=["bar"])

    excluded = excluded_content_names(DIRECTORY_SCOPED_PATH, ["bar/info.tc.orig", "bar/info00.jpg"])

    assert excluded == {"bar/info.tc.orig": "structural"}


# endregion


# region which record covers a name now


def test_a_nested_record_covers_a_name_under_it_and_respells_it(mocker: MockerFixture) -> None:
    """The directory-level half of the rule, answered for a name the enclosing record still lists (#257).

    The name has to come back as the *covering* record spells it, since that is what an entry moving
    there will be keyed under: relative to ``bar/``, not to the resource above it.

    **Test steps:**

    * mock a tree with a nested ``bar/info.rehu`` over a video two levels down
    * ask who covers the enclosing record's name for it
    * verify the nested record came back, with the name rebased onto its own directory
    """
    mock_tree(mocker, ["info.rehu", "bar/info.rehu", "bar/sub/video.mp4"], directories=["bar", "bar/sub"])

    covering = covering_content_records(DIRECTORY_SCOPED_PATH, ["bar/sub/video.mp4"])

    assert covering == {"bar/sub/video.mp4": CoveringRecord(DIRECTORY / "bar" / INFO_REHU_FILENAME, "sub/video.mp4")}


def test_the_deepest_record_along_the_path_is_the_one_that_covers(mocker: MockerFixture) -> None:
    """Coverage is exclusive, so a record nested inside a nested one takes the file from both.

    **Test steps:**

    * mock a tree with an ``info.rehu`` at every level down to the file
    * ask who covers the outermost record's name for it
    * verify the innermost record came back
    """
    mock_tree(
        mocker,
        ["info.rehu", "bar/info.rehu", "bar/sub/info.rehu", "bar/sub/video.mp4"],
        directories=["bar", "bar/sub"],
    )

    covering = covering_content_records(DIRECTORY_SCOPED_PATH, ["bar/sub/video.mp4"])

    assert covering == {
        "bar/sub/video.mp4": CoveringRecord(DIRECTORY / "bar" / "sub" / INFO_REHU_FILENAME, "video.mp4")
    }


def test_a_file_scoped_neighbour_covers_its_same_stem_sibling(mocker: MockerFixture) -> None:
    """The file-level half: a ``foo.rehu`` beside the file takes it, and spells it as it already is.

    Narrower than the directory-scoped record in the same directory, which is why it wins over one.

    **Test steps:**

    * mock a directory holding ``baz.rehu`` beside ``baz.zip``, under the resource's own ``info.rehu``
    * ask who covers ``baz.zip``
    * verify the file-scoped record came back, under the same name
    """
    mock_siblings(mocker, ["info.rehu", "baz.rehu", "baz.zip"])

    covering = covering_content_records(DIRECTORY_SCOPED_PATH, ["baz.zip"])

    assert covering == {"baz.zip": CoveringRecord(DIRECTORY / "baz.rehu", "baz.zip")}


def test_a_legacy_record_covers_what_it_will_cover_once_converted(mocker: MockerFixture) -> None:
    """An ``info.tc`` is a record and covers its directory (#250), so a claim can move to it as well.

    A catalog mid-conversion is the normal case rather than the exotic one, and refusing to move a claim
    into an unconverted resource would strand it in the record above until somebody converted that one.

    **Test steps:**

    * mock a tree with a nested ``bar/info.tc`` over a video
    * ask who covers the enclosing record's name for it
    * verify the legacy record came back
    """
    mock_tree(mocker, ["info.rehu", "bar/info.tc", "bar/video.mp4"], directories=["bar"])

    covering = covering_content_records(DIRECTORY_SCOPED_PATH, ["bar/video.mp4"])

    assert covering == {"bar/video.mp4": CoveringRecord(DIRECTORY / "bar" / INFO_TC_FILENAME, "video.mp4")}


def test_a_converted_record_wins_over_the_legacy_one_beside_it(mocker: MockerFixture) -> None:
    """Both formats in one directory is a transient state, and the live record is the one to write to.

    They share a ``.checksum`` either way, so this decides which path the move is *reported* under.

    **Test steps:**

    * mock a nested directory holding both an ``info.rehu`` and an ``info.tc``
    * ask who covers a video in it
    * verify the ``.rehu`` came back
    """
    mock_tree(mocker, ["info.rehu", "bar/info.rehu", "bar/info.tc", "bar/video.mp4"], directories=["bar"])

    covering = covering_content_records(DIRECTORY_SCOPED_PATH, ["bar/video.mp4"])

    assert covering == {"bar/video.mp4": CoveringRecord(DIRECTORY / "bar" / INFO_REHU_FILENAME, "video.mp4")}


@mark.parametrize(
    "listing",
    [["baz.rehu", "baz.tc"], ["baz.tc", "baz.rehu"]],
    ids=["converted first", "legacy first"],
)
def test_a_file_scoped_claimant_is_the_live_record_whichever_order_the_listing_gives(
    mocker: MockerFixture, listing: list[str]
) -> None:
    """A half-converted stem answers the ``.rehu``, and a listing's order is nobody's guarantee.

    SMB and macOS both hand entries back in orders Windows never wrote, so a rule that took the first
    record it met would move a claim into the converted resource or the legacy one at random.

    **Test steps:**

    * mock a directory holding ``baz.rehu`` and ``baz.tc`` beside ``baz.zip``, in each order
    * ask who covers the archive
    * verify the ``.rehu`` came back both times
    """
    mock_siblings(mocker, ["info.rehu", *listing, "baz.zip"])

    covering = covering_content_records(DIRECTORY_SCOPED_PATH, ["baz.zip"])

    assert covering == {"baz.zip": CoveringRecord(DIRECTORY / "baz.rehu", "baz.zip")}


def test_a_name_this_record_still_covers_is_covered_by_nobody_else(mocker: MockerFixture) -> None:
    """Silence is the answer for content, so an ordinary record's entries never move (#257).

    A directory-scoped record's own directory is not searched: itself is not somebody else, and its
    ``.checksum`` is the one this run is already writing.

    **Test steps:**

    * mock a tree holding a record-less subdirectory and a video in it
    * ask about that video and about one in the root
    * verify nothing came back
    """
    mock_tree(mocker, ["info.rehu", "video.mp4", "bar/deeper.mp4"], directories=["bar"])

    assert not covering_content_records(DIRECTORY_SCOPED_PATH, ["video.mp4", "bar/deeper.mp4"])


def test_a_name_that_was_never_content_is_covered_by_nobody(mocker: MockerFixture) -> None:
    """Bookkeeping and junk have no claim to hand on -- they are the exclusion answer's to drop (#254).

    Moving them would only relocate the problem: the covering record's own next verify would prune what
    it had just been given.

    **Test steps:**

    * mock a nested resource holding its own screenshot, its manifest and a ``Thumbs.db``
    * ask who covers all three
    * verify nothing came back
    """
    mock_tree(
        mocker,
        ["info.rehu", "bar/info.rehu", "bar/info00.jpg", "bar/info.sfv", "bar/Thumbs.db"],
        directories=["bar"],
    )

    names_asked = ["bar/info00.jpg", "bar/info.sfv", "bar/Thumbs.db"]

    assert not covering_content_records(DIRECTORY_SCOPED_PATH, names_asked)


def test_a_file_scoped_resources_own_name_is_covered_by_nobody(mocker: MockerFixture) -> None:
    """A record is not somebody else, so an entry for its own deleted file stays where it is.

    The file-scoped claimant is looked up before the enclosing directory-scoped record, and finding
    *itself* has to answer *nobody* rather than falling through to the ``info.rehu`` beside it -- which
    would hand that record a claim over a file it does not cover.

    **Test steps:**

    * mock a directory holding ``foo.rehu`` and an ``info.rehu``, with ``foo.zip`` deleted
    * ask who covers ``foo.zip``, from the file-scoped record's point of view
    * verify nothing came back
    """
    mock_siblings(mocker, ["foo.rehu", "info.rehu"])

    assert not covering_content_records(FILE_SCOPED_PATH, ["foo.zip"])


def test_a_file_scoped_record_hands_what_its_whitelist_does_not_name_to_the_directory(
    mocker: MockerFixture,
) -> None:
    """A file-scoped record searches its own directory, because the ``info.rehu`` there is not itself.

    Its content is a whitelist of same-stem siblings, so an entry for anything else was never its own --
    and the record covering that file is the directory-scoped one sitting beside it.

    **Test steps:**

    * mock a directory holding ``foo.rehu``, an ``info.rehu`` and an unrelated video
    * ask who covers the video, from the file-scoped record's point of view
    * verify the directory-scoped record came back, under the same name
    """
    mock_siblings(mocker, ["foo.rehu", "foo.zip", "info.rehu", "video.mp4"])

    covering = covering_content_records(FILE_SCOPED_PATH, ["video.mp4"])

    assert covering == {"video.mp4": CoveringRecord(DIRECTORY_SCOPED_PATH, "video.mp4")}


def test_a_file_scoped_records_junk_entry_is_covered_by_nobody(mocker: MockerFixture) -> None:
    """A junk glob is a rule about the *covering* record's content, so it stops the move as well (#226).

    The tier that would drop such an entry never fires for a file-scoped record (its content is a
    whitelist), so without this the entry would be handed to the ``info.rehu`` beside it purely to be
    pruned there.

    **Test steps:**

    * mock a directory holding ``foo.rehu``, an ``info.rehu`` and a ``Thumbs.db``
    * ask who covers the ``Thumbs.db``
    * verify nothing came back
    """
    mock_siblings(mocker, ["foo.rehu", "foo.zip", "info.rehu", "Thumbs.db"])

    assert not covering_content_records(FILE_SCOPED_PATH, ["Thumbs.db"])


def test_a_branch_that_will_not_list_covers_nothing(mocker: MockerFixture) -> None:
    """A directory claiming nothing is the same answer the exclusion side gives (#245).

    An away mount must not make a claim look homeless -- the entry stays where it is, and the next run
    over a readable tree moves it.

    **Test steps:**

    * mock a tree whose ``bar`` refuses to list
    * ask who covers a video inside it
    * verify nothing came back
    """
    mock_tree(mocker, ["info.rehu"], directories=["bar"], unreadable=["bar"])

    assert not covering_content_records(DIRECTORY_SCOPED_PATH, ["bar/video.mp4"])


def test_covering_records_reads_each_directory_once(mocker: MockerFixture) -> None:
    """Two hundred names in two directories cost two listings, as the exclusion answer does.

    A directory-scoped resource's own directory is not read at all unless a name sits directly in it: it
    covers itself, so there is nothing to ask about it.

    **Test steps:**

    * mock a tree of two subdirectories, each with its own record, and count the listings
    * ask about three names spread across both
    * verify one listing per distinct directory a name actually sits in
    """
    scandir = mock_tree(
        mocker,
        ["info.rehu", "a/info.rehu", "a/one.mp4", "a/two.mp4", "b/info.rehu", "b/three.mp4"],
        directories=["a", "b"],
    )

    covering_content_records(DIRECTORY_SCOPED_PATH, ["a/one.mp4", "a/two.mp4", "b/three.mp4"])

    assert scandir.call_count == 2


# endregion


# region size on disk


def mock_sizes(
    mocker: MockerFixture,
    sizes: dict[str, int],
    *,
    unreadable: list[str] | None = None,
    missing: list[str] | None = None,
) -> None:
    """Mock ``Path.stat`` so each fake path reports the size the test gave it.

    :param mocker: pytest-mock fixture.
    :param sizes: fake paths relative to :data:`DIRECTORY`, ``/``-separated, mapped to their byte size.
    :param unreadable: fake paths whose ``stat`` should refuse -- a share that will not answer for a
        file it listed, which says nothing about the file's size and so takes the total down (#245).
    :param missing: fake paths whose ``stat`` should raise ``FileNotFoundError`` -- deleted between the
        listing and the measurement, which is a positive answer: it weighs nothing.
    """
    refusing = {DIRECTORY / name for name in unreadable or []}
    gone = {DIRECTORY / name for name in missing or []}
    sized = {DIRECTORY / name: size for name, size in sizes.items()}

    def stat(path: Path, **_kwargs: object) -> SimpleNamespace:
        if path in refusing:
            raise PermissionError(path)
        if path in gone:
            raise FileNotFoundError(path)
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


def test_retained_conversion_backups_weigh_nothing(mocker: MockerFixture) -> None:
    """A converted resource measures the same whether its backups are still there or already discarded
    (#253) -- otherwise every size in the catalog shrinks the day the manager is used.

    **Test steps:**

    * give every file a size, mock a converted tree holding the backups, and measure
    * mock the same tree with the backups discarded, and measure again
    * verify both answers are the video's bytes alone
    """
    mock_sizes(mocker, {"info.tc.orig": 2048, "cover.jpg.orig": 1024, "video.mp4": 4096})

    mock_tree(mocker, ["info.rehu", "info.tc.orig", "cover.jpg.orig", "video.mp4"])
    assert content_size_on_disk(DIRECTORY_SCOPED_PATH) == 4096

    mock_tree(mocker, ["info.rehu", "video.mp4"])
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


def test_an_unreadable_resource_is_refused_rather_than_measured_as_empty(mocker: MockerFixture) -> None:
    """An away mount and an empty resource used to be the same answer, ``0`` (#245): the sum now says it
    could not read the resource instead of quoting a size nothing supports.

    **Test steps:**

    * mock ``os.scandir`` to raise
    * measure ``info.rehu``'s size on disk
    * verify it refused, naming the directory
    """
    mocker.patch("rehuco_core.rehu_content_files.os.scandir", side_effect=OSError)

    with raises(ContentUnreachableError, match=re.escape(str(DIRECTORY))):
        content_size_on_disk(DIRECTORY_SCOPED_PATH)


def test_a_size_over_a_partly_unreadable_tree_is_refused_rather_than_reported_low(
    mocker: MockerFixture,
) -> None:
    """A total summed over the branches that happened to answer is not the resource's size, and a number
    that reads as authority is worse than no number (#245).

    **Test steps:**

    * mock a tree of two branches, one of which will not list, each holding a sized video
    * measure ``info.rehu``'s size on disk
    * verify it refused, naming the branch it could not read rather than returning the other's bytes
    """
    mock_tree(
        mocker,
        ["info.rehu", "a/here.mp4", "b/away.mp4"],
        directories=["a", "b"],
        unreadable=["b"],
    )
    mock_sizes(mocker, {"a/here.mp4": 64})

    with raises(ContentUnreachableError, match="b"):
        content_size_on_disk(DIRECTORY_SCOPED_PATH)


def test_a_file_that_vanishes_mid_scan_costs_only_its_own_bytes(mocker: MockerFixture) -> None:
    """A file listed a moment ago and gone now weighs nothing: absent bytes are a positive answer about
    the file, unlike a refusal, which says nothing about it at all.

    **Test steps:**

    * mock a tree of two videos, one of which raises ``FileNotFoundError`` on ``stat``
    * measure ``info.rehu``'s size on disk
    * verify the readable one's bytes came back and nothing was raised
    """
    mock_tree(mocker, ["info.rehu", "here.mp4", "gone.mp4"])
    mock_sizes(mocker, {"here.mp4": 64, "gone.mp4": 1024}, missing=["gone.mp4"])

    assert content_size_on_disk(DIRECTORY_SCOPED_PATH) == 64


def test_a_file_that_refuses_to_be_measured_takes_the_measurement_down(mocker: MockerFixture) -> None:
    """A share that refuses one file mid-scan makes the total wrong by that file's unknown size, so it is
    refused rather than quoted short (#245).

    **Test steps:**

    * mock a tree of two videos, one of which raises ``PermissionError`` on ``stat``
    * measure ``info.rehu``'s size on disk
    * verify it refused, naming the file
    """
    mock_tree(mocker, ["info.rehu", "here.mp4", "locked.mp4"])
    mock_sizes(mocker, {"here.mp4": 64, "locked.mp4": 1024}, unreadable=["locked.mp4"])

    with raises(ContentUnreachableError, match="locked.mp4"):
        content_size_on_disk(DIRECTORY_SCOPED_PATH)


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
