"""Tests for reference-images content-image enumeration ([[data-model#resource-scoping]])."""

import zipfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Final
from unittest.mock import MagicMock

from pytest_mock import MockerFixture
from rehuco_core import (
    INFO_REHU_FILENAME,
    INFO_TC_FILENAME,
    ContentImageEntry,
    RenameCoordinator,
    enumerate_content_images,
    scan_rehu_screenshot_files,
)

from rehuco_core_tests.fake_directories import FakeDirEntry, FakeScandir

DIRECTORY: Final = Path("/fake/refimages")
FILE_SCOPED_PATH: Final = DIRECTORY / "foo.rehu"
DIRECTORY_SCOPED_PATH: Final = DIRECTORY / INFO_REHU_FILENAME


def mock_tree(mocker: MockerFixture, paths: list[Path]) -> MagicMock:
    """Mock the content walk's ``os.scandir`` so :data:`DIRECTORY`'s tree appears to hold ``paths``.

    The scanner asks :func:`~rehuco_core.enumerate_content_files` which files are the resource's (#392),
    so the tree is declared at that walk's own seam, one directory at a time: every folder between
    :data:`DIRECTORY` and a path is a directory entry of its parent.

    :param mocker: pytest-mock fixture.
    :param paths: the fake files, all under :data:`DIRECTORY`.
    :returns: the patched ``os.scandir``.
    """
    listing: dict[Path, list[FakeDirEntry]] = {DIRECTORY: []}
    for path in paths:
        for folder in reversed(path.parents):
            if folder.is_relative_to(DIRECTORY) and folder != DIRECTORY and folder not in listing:
                listing.setdefault(folder.parent, []).append(FakeDirEntry(folder.name, directory=True))
                listing[folder] = []
        listing[path.parent].append(FakeDirEntry(path.name))

    def scandir(directory: Path) -> FakeScandir:
        if Path(directory) not in listing:
            raise FileNotFoundError(directory)
        return FakeScandir(listing[Path(directory)])

    return mocker.patch("rehuco_core.rehu_content_files.os.scandir", side_effect=scandir)


def mock_siblings(mocker: MockerFixture, filenames: list[str]) -> None:
    """Mock :data:`DIRECTORY` as a flat directory holding ``filenames``.

    :param mocker: pytest-mock fixture.
    :param filenames: the fake filenames the directory should list.
    """
    mock_tree(mocker, [DIRECTORY / name for name in filenames])


def mock_stats(mocker: MockerFixture, stats: dict[Path, tuple[int, int]]) -> MagicMock:
    """Mock ``Path.stat`` so each loose image answers its declared size and mtime.

    :param mocker: pytest-mock fixture.
    :param stats: ``{path: (size, mtime_ns)}``; a path left out raises ``FileNotFoundError`` -- a file
        deleted between the walk and the question.
    :returns: the patched ``Path.stat``.
    """

    def stat(path: Path) -> SimpleNamespace:
        if path not in stats:
            raise FileNotFoundError(path)
        size, mtime = stats[path]
        return SimpleNamespace(st_size=size, st_mtime_ns=mtime)

    return mocker.patch.object(Path, "stat", autospec=True, side_effect=stat)


def mock_shared_read_open(mocker: MockerFixture) -> MagicMock:
    """Mock :func:`~borco_core.shared_read_open` so the file it opens *is* its path -- what the mocked
    ``zipfile.ZipFile`` is then handed, so it can still answer per archive (#347).

    :param mocker: pytest-mock fixture.
    :returns: the patched opener, for call-arg assertions.
    """

    def side_effect(path: Path) -> MagicMock:
        file = mocker.MagicMock(name=str(path))
        file.__enter__.return_value = path
        return file

    return mocker.patch("rehuco_core.rehu_content_images.shared_read_open", side_effect=side_effect)


def mock_archives(mocker: MockerFixture, contents: dict[Path, list[zipfile.ZipInfo] | Exception]) -> MagicMock:
    """Mock ``zipfile.ZipFile`` so opening a path named in ``contents`` yields that archive's entries.

    The file under it is opened through a mocked :func:`mock_shared_read_open`, so the zip is handed the
    path back as its "file".

    :param mocker: pytest-mock fixture.
    :param contents: ``{archive_path: entries}``, or ``{archive_path: an_exception_instance}`` for an
        archive that should fail to open/list.
    :returns: the patched ``zipfile.ZipFile`` mock, for call-count/call-arg assertions.
    """

    def side_effect(path: Path, *_args: object, **_kwargs: object) -> MagicMock:
        entry = contents[path]
        if isinstance(entry, Exception):
            raise entry
        opened = mocker.MagicMock()
        opened.__enter__.return_value.infolist.return_value = entry
        return opened

    mock_shared_read_open(mocker)
    return mocker.patch("rehuco_core.rehu_content_images.zipfile.ZipFile", side_effect=side_effect)


def zip_info(name: str, size: int = 0, crc: int = 0) -> zipfile.ZipInfo:
    """Build a real :class:`zipfile.ZipInfo` for ``name`` -- a plain data holder, no archive needed.

    :param name: the entry's stored path.
    :param size: the uncompressed size the central directory would record.
    :param crc: the CRC32 the central directory would record.
    :returns: a :class:`zipfile.ZipInfo` naming it.
    """
    info = zipfile.ZipInfo(name)
    info.file_size = size
    info.CRC = crc
    return info


def entry(archive: Path, name: str, size: int = 0, crc: int = 0) -> ContentImageEntry:
    """The :class:`ContentImageEntry` :func:`zip_info`'s counterpart enumerates to.

    :param archive: the archive path.
    :param name: the member path.
    :param size: the uncompressed size.
    :param crc: the CRC32.
    :returns: the expected entry.
    """
    return ContentImageEntry(archive, name, size, crc)


def loose(name: str, size: int = 0, mtime: int = 0) -> ContentImageEntry:
    """The :class:`ContentImageEntry` a loose image under :data:`DIRECTORY` enumerates to.

    :param name: the image's path relative to :data:`DIRECTORY`.
    :param size: its size.
    :param mtime: its modification time in nanoseconds.
    :returns: the expected entry.
    """
    return ContentImageEntry(None, name, size, file=DIRECTORY / name, mtime=mtime)


# region file-scoped


def test_file_scoped_enumerates_only_its_own_sibling_archive(mocker: MockerFixture) -> None:
    """A whitelist of one: unrelated siblings, including another resource's archive, are never opened.

    **Test steps:**

    * mock the directory to hold ``foo.zip``, ``info.rehu``, ``bar00.jpg`` and ``bar.zip``
    * mock only ``foo.zip`` as an openable archive
    * enumerate ``foo.rehu``'s content images
    * verify ``zipfile.ZipFile`` was called exactly once, with ``foo.zip``
    """
    mock_siblings(mocker, ["foo.zip", "info.rehu", "bar00.jpg", "bar.zip"])
    mock_zipfile = mock_archives(mocker, {DIRECTORY / "foo.zip": [zip_info("page01.jpg")]})

    entries = enumerate_content_images(FILE_SCOPED_PATH)

    assert entries == [entry(DIRECTORY / "foo.zip", "page01.jpg")]
    mock_zipfile.assert_called_once_with(DIRECTORY / "foo.zip")


def test_file_scoped_matches_stem_and_extension_case_insensitively(mocker: MockerFixture) -> None:
    """The sibling's stem and archive extension both match case-insensitively.

    **Test steps:**

    * mock the directory to hold ``FOO.ZIP`` only
    * enumerate ``foo.rehu``'s content images
    * verify ``FOO.ZIP`` was opened
    """
    mock_siblings(mocker, ["FOO.ZIP"])
    mock_archives(mocker, {DIRECTORY / "FOO.ZIP": [zip_info("page01.jpg")]})

    entries = enumerate_content_images(FILE_SCOPED_PATH)

    assert entries == [entry(DIRECTORY / "FOO.ZIP", "page01.jpg")]


def test_file_scoped_lists_entries_in_natural_order_ignoring_non_images(mocker: MockerFixture) -> None:
    """Non-image entries are dropped; recognized ones come back in natural order, the archive's root
    images before its folders' (#392), never in the central directory's order
    ([[reference-images#image-identity]]).

    **Test steps:**

    * mock ``foo.zip`` to hold images in a shuffled central-directory order -- ``page10`` before
      ``page9``, a subfolder's member before the root's, a text file in between
    * enumerate
    * verify the root images come back natural-sorted, then the subfolder's, the text file dropped
    """
    mock_siblings(mocker, ["foo.zip"])
    mock_archives(
        mocker,
        {
            DIRECTORY / "foo.zip": [
                zip_info("page10.jpg"),
                zip_info("readme.txt"),
                zip_info("extras/bonus.png"),
                zip_info("page9.jpg"),
                zip_info("page009.jpg"),
            ]
        },
    )

    entries = enumerate_content_images(FILE_SCOPED_PATH)

    assert entries == [
        entry(DIRECTORY / "foo.zip", "page9.jpg"),
        entry(DIRECTORY / "foo.zip", "page009.jpg"),
        entry(DIRECTORY / "foo.zip", "page10.jpg"),
        entry(DIRECTORY / "foo.zip", "extras/bonus.png"),
    ]


def test_entries_carry_the_central_directory_size_and_crc(mocker: MockerFixture) -> None:
    """Each entry carries the member's uncompressed size and CRC32 off the central directory, and keys
    itself by them ([[reference-images#image-identity]]) -- without a byte inflated.

    **Test steps:**

    * mock ``foo.zip`` to hold one image with a known size and CRC
    * enumerate
    * verify the entry carries both and its key is ``("zip", name, size, crc)``
    """
    mock_siblings(mocker, ["foo.zip"])
    mock_archives(mocker, {DIRECTORY / "foo.zip": [zip_info("page01.jpg", 123_456, 0xDEADBEEF)]})

    entries = enumerate_content_images(FILE_SCOPED_PATH)

    assert entries == [entry(DIRECTORY / "foo.zip", "page01.jpg", 123_456, 0xDEADBEEF)]
    assert entries[0].key == ("zip", "page01.jpg", 123_456, 0xDEADBEEF)


def test_a_file_scoped_records_screenshots_are_never_content(mocker: MockerFixture) -> None:
    """``foo00.jpg`` beside ``foo.rehu`` is that record's screenshot, never a content image, and no loose
    file is opened as an archive.

    **Test steps:**

    * mock the directory to hold only ``foo00.jpg`` and ``foo01.png``, no archive
    * enumerate
    * verify the result is empty and ``zipfile.ZipFile`` is never called
    """
    mock_siblings(mocker, ["foo00.jpg", "foo01.png"])
    mock_zipfile = mocker.patch("rehuco_core.rehu_content_images.zipfile.ZipFile")

    entries = enumerate_content_images(FILE_SCOPED_PATH)

    assert not entries
    mock_zipfile.assert_not_called()


# endregion

# region directory-scoped


def test_directory_scoped_sums_every_archive_recursively(mocker: MockerFixture) -> None:
    """The result sums over every ``.zip``/``.cbz`` found anywhere under the directory tree.

    **Test steps:**

    * mock the tree to hold a root ``.zip``, a nested ``.cbz``, and an unrelated text file
    * mock each archive's entries, one sharing a filename across both archives
    * enumerate ``info.rehu``'s content images
    * verify all entries from both archives come back, archives in path order
    """
    root_zip = DIRECTORY / "a.zip"
    nested_cbz = DIRECTORY / "sub" / "b.cbz"
    mock_tree(mocker, [root_zip, nested_cbz, DIRECTORY / "notes.txt"])
    mock_archives(
        mocker,
        {
            root_zip: [zip_info("page01.jpg")],
            nested_cbz: [zip_info("page01.jpg")],
        },
    )

    entries = enumerate_content_images(DIRECTORY_SCOPED_PATH)

    assert entries == [
        entry(root_zip, "page01.jpg"),
        entry(nested_cbz, "page01.jpg"),
    ]


def test_directory_scoped_orders_archives_naturally_by_path(mocker: MockerFixture) -> None:
    """Archives come in natural order of their paths: ``pack2`` before ``pack10``, a folder's packs where
    the folder sorts -- not ``str`` order, which puts ``pack10`` first.

    **Test steps:**

    * mock the tree to yield ``pack10.zip``, ``pack2.zip`` and ``vol1/pack1.zip`` in that order
    * mock one image per archive
    * enumerate
    * verify the entries come archive by archive, ``pack2``, ``pack10``, then ``vol1/pack1``
    """
    pack10 = DIRECTORY / "pack10.zip"
    pack2 = DIRECTORY / "pack2.zip"
    nested = DIRECTORY / "vol1" / "pack1.zip"
    mock_tree(mocker, [pack10, pack2, nested])
    mock_archives(mocker, {pack10: [zip_info("a.jpg")], pack2: [zip_info("a.jpg")], nested: [zip_info("a.jpg")]})

    entries = enumerate_content_images(DIRECTORY_SCOPED_PATH)

    assert entries == [entry(pack2, "a.jpg"), entry(pack10, "a.jpg"), entry(nested, "a.jpg")]


def test_directory_scoped_excludes_a_subdirectory_with_its_own_info_rehu(mocker: MockerFixture) -> None:
    """A nested ``info.rehu`` covers its own directory, so its archives are not the parent's (#254).

    The same rule the size scan and the checksums apply: adding up what each record counts has to
    answer a library's total, which it cannot while a nested pack is counted once for itself and again
    for every ancestor above it.

    **Test steps:**

    * mock the tree to hold a nested ``info.rehu`` alongside a nested archive, and one archive at the
      root the parent still owns
    * enumerate the parent ``info.rehu``'s content images
    * verify only the root archive's entries came back
    """
    nested_archive = DIRECTORY / "child" / "images.zip"
    own_archive = DIRECTORY / "own.zip"
    mock_tree(mocker, [DIRECTORY / "child" / INFO_REHU_FILENAME, nested_archive, own_archive])
    mock_archives(mocker, {nested_archive: [zip_info("page01.jpg")], own_archive: [zip_info("cover.jpg")]})

    entries = enumerate_content_images(DIRECTORY_SCOPED_PATH)

    assert entries == [entry(own_archive, "cover.jpg")]


def test_directory_scoped_excludes_an_archive_a_file_scoped_record_claims(mocker: MockerFixture) -> None:
    """An archive beside a same-stem ``foo.rehu`` is that record's content, not the directory's (#254).

    **Test steps:**

    * mock the tree to hold ``foo.rehu`` beside ``foo.zip``, and an unclaimed archive
    * enumerate the parent ``info.rehu``'s content images
    * verify only the unclaimed archive's entries came back
    """
    claimed = DIRECTORY / "foo.zip"
    unclaimed = DIRECTORY / "bar.zip"
    mock_tree(mocker, [DIRECTORY / "foo.rehu", claimed, unclaimed])
    mock_archives(mocker, {claimed: [zip_info("page01.jpg")], unclaimed: [zip_info("page02.jpg")]})

    entries = enumerate_content_images(DIRECTORY_SCOPED_PATH)

    assert entries == [entry(unclaimed, "page02.jpg")]


def test_a_legacy_info_tc_is_directory_scoped_too(mocker: MockerFixture) -> None:
    """An unconverted ``info.tc`` counts the archives its directory holds (#250).

    The scope comes from :func:`~rehuco_core.is_directory_scoped`, so this walk and the content-file
    walk cannot disagree about the same record. Taking the file-scoped branch would have looked for an
    ``info.zip`` that a tc4 catalog never had.

    **Test steps:**

    * mock the tree to hold a root archive and a nested one
    * enumerate ``info.tc``'s content images
    * verify both archives' entries came back
    """
    root_zip = DIRECTORY / "a.zip"
    nested_cbz = DIRECTORY / "sub" / "b.cbz"
    mock_tree(mocker, [root_zip, nested_cbz])
    mock_archives(mocker, {root_zip: [zip_info("page01.jpg")], nested_cbz: [zip_info("page02.jpg")]})

    entries = enumerate_content_images(DIRECTORY / INFO_TC_FILENAME)

    assert entries == [entry(root_zip, "page01.jpg"), entry(nested_cbz, "page02.jpg")]


# endregion

# region archive contents


def test_directory_entries_dot_files_and_macosx_are_excluded(mocker: MockerFixture) -> None:
    """Directory entries, dot-files, and ``__MACOSX/`` metadata never count, even with a matching suffix.

    **Test steps:**

    * mock an archive holding a directory entry named like an image, a top-level dot-file, a nested
      dot-file, a dot-prefixed and a plainly-named ``__MACOSX/`` sidecar, and one genuine image
    * enumerate
    * verify only the genuine image comes back
    """
    mock_siblings(mocker, ["foo.zip"])
    mock_archives(
        mocker,
        {
            DIRECTORY / "foo.zip": [
                zip_info("images.jpg/"),
                zip_info(".hidden.jpg"),
                zip_info("page/.hidden2.png"),
                zip_info("__MACOSX/._page01.jpg"),
                zip_info("__MACOSX/page02.jpg"),
                zip_info("page/keep.jpg"),
            ]
        },
    )

    entries = enumerate_content_images(FILE_SCOPED_PATH)

    assert entries == [entry(DIRECTORY / "foo.zip", "page/keep.jpg")]


def test_nested_entries_count(mocker: MockerFixture) -> None:
    """An entry nested in a subdirectory inside the zip counts like a top-level one.

    **Test steps:**

    * mock an archive holding only a deeply-nested image
    * enumerate
    * verify it counts
    """
    mock_siblings(mocker, ["foo.zip"])
    mock_archives(mocker, {DIRECTORY / "foo.zip": [zip_info("volume1/chapter2/page03.jpg")]})

    entries = enumerate_content_images(FILE_SCOPED_PATH)

    assert entries == [entry(DIRECTORY / "foo.zip", "volume1/chapter2/page03.jpg")]


def test_encrypted_entries_still_enumerate(mocker: MockerFixture) -> None:
    """Listing never decodes an entry, so an encrypted one is still recognized and counted.

    **Test steps:**

    * mock an archive holding one entry with its encryption flag bit set
    * enumerate
    * verify it counts, proving no decode/decrypt was attempted
    """
    mock_siblings(mocker, ["foo.zip"])
    encrypted = zip_info("page01.jpg")
    encrypted.flag_bits |= 0x1
    mock_archives(mocker, {DIRECTORY / "foo.zip": [encrypted]})

    entries = enumerate_content_images(FILE_SCOPED_PATH)

    assert entries == [entry(DIRECTORY / "foo.zip", "page01.jpg")]


def test_enumerating_never_reads_or_extracts_entry_contents(mocker: MockerFixture) -> None:
    """Enumeration reads only the central directory -- no per-entry decode cost, however large the archive.

    **Test steps:**

    * mock an archive holding several images
    * enumerate
    * verify neither ``read`` nor ``open`` (the extraction/decode APIs) was ever called
    """
    mock_siblings(mocker, ["foo.zip"])
    entries = [zip_info(f"page{index:02d}.jpg") for index in range(50)]
    mock_zipfile = mock_archives(mocker, {DIRECTORY / "foo.zip": entries})

    enumerate_content_images(FILE_SCOPED_PATH)

    opened = mock_zipfile.return_value.__enter__.return_value
    opened.read.assert_not_called()
    opened.open.assert_not_called()


def test_zips_inside_zips_are_not_descended_into(mocker: MockerFixture) -> None:
    """An archive entry that is itself a zip is neither counted nor opened.

    **Test steps:**

    * mock ``foo.zip`` to hold an inner ``.zip`` entry and one genuine image
    * enumerate
    * verify only the image comes back, and ``zipfile.ZipFile`` opened just the one on-disk archive
    """
    mock_siblings(mocker, ["foo.zip"])
    mock_zipfile = mock_archives(mocker, {DIRECTORY / "foo.zip": [zip_info("inner.zip"), zip_info("page01.jpg")]})

    entries = enumerate_content_images(FILE_SCOPED_PATH)

    assert entries == [entry(DIRECTORY / "foo.zip", "page01.jpg")]
    mock_zipfile.assert_called_once_with(DIRECTORY / "foo.zip")


def test_custom_extension_set_changes_what_is_counted(mocker: MockerFixture) -> None:
    """The recognized extension set is an argument, not a baked-in constant.

    **Test steps:**

    * mock an archive holding a ``.jpg`` (the default set) and a ``.tiff`` (outside it)
    * enumerate once with the default set and once naming only ``.tiff``
    * verify each call recognizes only the extension it was given
    """
    mock_siblings(mocker, ["foo.zip"])
    mock_archives(mocker, {DIRECTORY / "foo.zip": [zip_info("page01.jpg"), zip_info("page01.tiff")]})

    default_entries = enumerate_content_images(FILE_SCOPED_PATH)
    tiff_entries = enumerate_content_images(FILE_SCOPED_PATH, extensions=(".tiff",))

    assert default_entries == [entry(DIRECTORY / "foo.zip", "page01.jpg")]
    assert tiff_entries == [entry(DIRECTORY / "foo.zip", "page01.tiff")]


# endregion

# region loose images


def test_loose_images_enumerate_beside_the_archives(mocker: MockerFixture) -> None:
    """A loose image is a content image too (#392), keyed by its size and mtime under the ``file`` kind
    ([[reference-images#image-identity]]), with its path relative to the ``.rehu``'s directory.

    **Test steps:**

    * mock a tree holding a root image, one in a subfolder, an archive, and a non-image
    * enumerate ``info.rehu``'s content images
    * verify both loose images and the member came back, each loose one keyed ``("file", ...)``
    """
    archive = DIRECTORY / "pack.zip"
    mock_tree(mocker, [DIRECTORY / "a.jpg", DIRECTORY / "foo" / "b.png", archive, DIRECTORY / "notes.txt"])
    mock_archives(mocker, {archive: [zip_info("page01.jpg", 7, 0xBEEF)]})
    mock_stats(mocker, {DIRECTORY / "a.jpg": (11, 1_000), DIRECTORY / "foo" / "b.png": (22, 2_000)})

    entries = enumerate_content_images(DIRECTORY_SCOPED_PATH)

    assert entries == [
        loose("a.jpg", 11, 1_000),
        loose("foo/b.png", 22, 2_000),
        entry(archive, "page01.jpg", 7, 0xBEEF),
    ]
    assert entries[0].key == ("file", "a.jpg", 11, 1_000)
    assert entries[2].key == ("zip", "page01.jpg", 7, 0xBEEF)


def test_a_folders_own_images_come_before_its_subfolders_inside_an_archive(mocker: MockerFixture) -> None:
    """Inside an archive, each folder's images come before its subfolders' -- the root's first -- so a
    folder's images are contiguous whatever their names (#392): ``z.jpg`` at the root is not split from
    ``a.jpg`` by a ``bar/`` folder sorting between them.

    **Test steps:**

    * mock ``foo.zip`` to hold ``z.jpg``, ``bar/sub/c.jpg``, ``bar/b.jpg`` and ``a.jpg``
    * enumerate
    * verify the root images, then ``bar``'s, then ``bar/sub``'s
    """
    mock_siblings(mocker, ["foo.zip"])
    mock_archives(
        mocker,
        {
            DIRECTORY / "foo.zip": [
                zip_info("z.jpg"),
                zip_info("bar/sub/c.jpg"),
                zip_info("bar/b.jpg"),
                zip_info("a.jpg"),
            ]
        },
    )

    assert [found.name for found in enumerate_content_images(FILE_SCOPED_PATH)] == [
        "a.jpg",
        "z.jpg",
        "bar/b.jpg",
        "bar/sub/c.jpg",
    ]


def test_groups_sort_case_insensitively_folders_and_archives_together(mocker: MockerFixture) -> None:
    """The root's loose images come first, then every folder and archive in one natural,
    case-insensitive order of their paths -- ``Bar.zip`` before ``foo``, ``foo`` before ``xxx/xyz.zip``
    -- and each group's images in natural order (#392).

    **Test steps:**

    * mock a tree holding root images, a ``foo`` folder's images, ``Bar.zip`` and ``xxx/xyz.zip``,
      listed out of order
    * enumerate
    * verify the groups come ``/``, ``Bar.zip``, ``foo``, ``xxx/xyz.zip``, images natural within each
    """
    bar_zip = DIRECTORY / "Bar.zip"
    xyz_zip = DIRECTORY / "xxx" / "xyz.zip"
    images = [DIRECTORY / "foo" / "b10.jpg", DIRECTORY / "foo" / "b2.jpg", DIRECTORY / "a.jpg"]
    mock_tree(mocker, [xyz_zip, *images, bar_zip])
    mock_archives(mocker, {bar_zip: [zip_info("x.jpg")], xyz_zip: [zip_info("y.jpg")]})
    mock_stats(mocker, dict.fromkeys(images, (0, 0)))

    entries = enumerate_content_images(DIRECTORY_SCOPED_PATH)

    assert entries == [
        loose("a.jpg"),
        entry(bar_zip, "x.jpg"),
        loose("foo/b2.jpg"),
        loose("foo/b10.jpg"),
        entry(xyz_zip, "y.jpg"),
    ]


def test_loose_dot_files_macosx_and_other_extensions_are_excluded(mocker: MockerFixture) -> None:
    """A loose file is filtered the way an archive member is: no dot-files, nothing under a
    ``__MACOSX`` folder, only the recognized extensions -- and the given set decides those.

    **Test steps:**

    * mock a tree holding a dot-file image, an image under ``__MACOSX``, a ``.TIFF`` and a ``.jpg``
    * enumerate once with the default set and once naming only ``.tiff``
    * verify each run kept only its own extension, and neither kept the dot-file or the sidecar
    """
    tiff = DIRECTORY / "scan.TIFF"
    jpg = DIRECTORY / "keep.jpg"
    mock_tree(mocker, [DIRECTORY / ".hidden.jpg", DIRECTORY / "__MACOSX" / "keep.jpg", tiff, jpg])
    mock_stats(mocker, {tiff: (0, 0), jpg: (0, 0)})

    assert enumerate_content_images(DIRECTORY_SCOPED_PATH) == [loose("keep.jpg")]
    assert enumerate_content_images(DIRECTORY_SCOPED_PATH, extensions=(".tiff",)) == [loose("scan.TIFF")]


def test_the_junk_globs_reach_the_walk(mocker: MockerFixture) -> None:
    """The caller's excluded-files globs leave an image out here exactly as they do for the checksums
    (#226, #392): what the one set skips, the other never shows.

    **Test steps:**

    * mock a tree holding ``a_thumb.jpg`` and ``a.jpg``
    * enumerate with a ``*_thumb.jpg`` glob
    * verify only ``a.jpg`` came back
    """
    mock_tree(mocker, [DIRECTORY / "a_thumb.jpg", DIRECTORY / "a.jpg"])
    mock_stats(mocker, {DIRECTORY / "a_thumb.jpg": (0, 0), DIRECTORY / "a.jpg": (0, 0)})

    entries = enumerate_content_images(DIRECTORY_SCOPED_PATH, excluded_patterns=("*_thumb.jpg",))

    assert entries == [loose("a.jpg")]


def test_a_loose_image_that_cannot_be_measured_is_skipped(mocker: MockerFixture) -> None:
    """A file gone between the walk and its ``stat`` contributes nothing rather than raising.

    **Test steps:**

    * mock a tree holding two images, only one of which answers ``stat``
    * enumerate
    * verify only the measurable one came back
    """
    mock_tree(mocker, [DIRECTORY / "gone.jpg", DIRECTORY / "here.jpg"])
    mock_stats(mocker, {DIRECTORY / "here.jpg": (5, 6)})

    assert enumerate_content_images(DIRECTORY_SCOPED_PATH) == [loose("here.jpg", 5, 6)]


def test_a_file_scoped_record_owns_its_own_stem_and_nothing_else(mocker: MockerFixture) -> None:
    """``foo.rehu`` owns ``foo.*`` beside it: ``foo.jpg`` is its content image, ``foo00.jpg`` its
    screenshot, and ``bar.jpg`` belongs to no record here.

    **Test steps:**

    * mock a flat directory holding ``foo.rehu``, ``foo.jpg``, ``foo00.jpg`` and ``bar.jpg``
    * enumerate ``foo.rehu``'s content images
    * verify only ``foo.jpg`` came back
    """
    mock_siblings(mocker, ["foo.rehu", "foo.jpg", "foo00.jpg", "bar.jpg"])
    mock_stats(mocker, {DIRECTORY / "foo.jpg": (1, 2)})

    assert enumerate_content_images(FILE_SCOPED_PATH) == [loose("foo.jpg", 1, 2)]


def test_ownership_is_the_content_walks(mocker: MockerFixture) -> None:
    """The images an ``info.rehu`` shows are the content its checksums cover (#392, #393): its own
    screenshots and a neighbour's ``foo.*`` are not, a ``bar/foo01.jpg`` is -- a record claims only its
    own directory -- and a nested resource's images are that resource's.

    **Test steps:**

    * mock a tree with ``info00.jpg``, a file-scoped ``foo.rehu`` with ``foo.jpg``/``foo00.jpg``, a
      ``bar/foo01.jpg``, a legacy-named ``001.jpg``, and a nested ``child/info.rehu`` with an image
    * enumerate the root ``info.rehu``'s content images
    * verify only ``001.jpg`` and ``bar/foo01.jpg`` came back
    """
    mock_tree(
        mocker,
        [
            DIRECTORY / INFO_REHU_FILENAME,
            DIRECTORY / "info00.jpg",
            DIRECTORY / "foo.rehu",
            DIRECTORY / "foo.jpg",
            DIRECTORY / "foo00.jpg",
            DIRECTORY / "001.jpg",
            DIRECTORY / "bar" / "foo01.jpg",
            DIRECTORY / "child" / INFO_REHU_FILENAME,
            DIRECTORY / "child" / "page.jpg",
        ],
    )
    mock_stats(mocker, {DIRECTORY / "001.jpg": (0, 0), DIRECTORY / "bar" / "foo01.jpg": (0, 0)})

    assert enumerate_content_images(DIRECTORY_SCOPED_PATH) == [loose("001.jpg"), loose("bar/foo01.jpg")]


def test_each_loose_image_is_measured_inside_a_hold(mocker: MockerFixture) -> None:
    """With a coordinator, a loose image's ``stat`` runs inside a
    :meth:`~rehuco_core.RenameCoordinator.holding` of its own, as an archive's read does (#347).

    **Test steps:**

    * mock one loose image, and a coordinator whose hold records how deep the scan is
    * enumerate with it, recording the depth at the ``stat``
    * verify the ``stat`` ran inside exactly one hold
    """
    depth = [0]
    seen: list[int] = []

    @contextmanager
    def holding() -> Generator[None]:
        depth[0] += 1
        try:
            yield
        finally:
            depth[0] -= 1

    coordinator = mocker.MagicMock(spec=RenameCoordinator)
    coordinator.holding.side_effect = holding
    mock_tree(mocker, [DIRECTORY / "a.jpg"])

    def stat(_path: Path) -> SimpleNamespace:
        seen.append(depth[0])
        return SimpleNamespace(st_size=0, st_mtime_ns=0)

    mocker.patch.object(Path, "stat", autospec=True, side_effect=stat)

    assert enumerate_content_images(DIRECTORY_SCOPED_PATH, coordinator=coordinator) == [loose("a.jpg")]
    assert seen == [1]


# endregion

# region archive failures


def test_absent_archive_reports_empty_without_raising(mocker: MockerFixture) -> None:
    """A missing archive contributes no entries -- a document-level condition, not a crash.

    **Test steps:**

    * mock ``zipfile.ZipFile`` to raise ``FileNotFoundError``
    * enumerate
    * verify the result is empty, no exception propagates
    """
    mock_siblings(mocker, ["foo.zip"])
    mock_archives(mocker, {DIRECTORY / "foo.zip": FileNotFoundError()})

    assert not enumerate_content_images(FILE_SCOPED_PATH)


def test_not_a_zip_or_truncated_archive_reports_empty_without_raising(mocker: MockerFixture) -> None:
    """A file that isn't a valid zip (or a truncated one) contributes no entries, not a crash.

    **Test steps:**

    * mock ``zipfile.ZipFile`` to raise ``BadZipFile``
    * enumerate
    * verify the result is empty, no exception propagates
    """
    mock_siblings(mocker, ["foo.zip"])
    mock_archives(mocker, {DIRECTORY / "foo.zip": zipfile.BadZipFile()})

    assert not enumerate_content_images(FILE_SCOPED_PATH)


def test_zero_image_archive_reports_empty_without_raising(mocker: MockerFixture) -> None:
    """An archive holding no recognized image contributes no entries -- not treated as a failure.

    **Test steps:**

    * mock ``foo.zip`` to hold only a non-image entry
    * enumerate
    * verify the result is empty
    """
    mock_siblings(mocker, ["foo.zip"])
    mock_archives(mocker, {DIRECTORY / "foo.zip": [zip_info("readme.txt")]})

    assert not enumerate_content_images(FILE_SCOPED_PATH)


def test_missing_directory_reports_empty_without_raising(mocker: MockerFixture) -> None:
    """A missing/unreadable directory (e.g. an offline mount) scans to empty, not a crash.

    **Test steps:**

    * mock the walk's ``os.scandir`` to raise ``FileNotFoundError``
    * enumerate a file-scoped and a directory-scoped record
    * verify both results are empty
    """
    mocker.patch("rehuco_core.rehu_content_files.os.scandir", side_effect=FileNotFoundError)

    assert not enumerate_content_images(FILE_SCOPED_PATH)
    assert not enumerate_content_images(DIRECTORY_SCOPED_PATH)


# endregion

# region screenshot separation


def test_content_images_and_screenshots_stay_disjoint(mocker: MockerFixture) -> None:
    """Content images never appear in the screenshot scan, and screenshots never in the enumeration
    ([[data-model#image-meanings]]) -- ``hidden_images`` filtering applies to screenshots downstream and
    structurally cannot affect content images, since the enumeration takes no document state at all.

    **Test steps:**

    * mock the directory to hold ``foo.rehu``, its screenshots ``foo00.jpg``/``foo01.png``, and ``foo.zip``
    * mock ``foo.zip`` to hold one image entry
    * run the screenshot scan and the content enumeration over the same directory
    * verify the screenshot scan returns only the loose screenshots and the enumeration only the zip entry
    """
    filenames = ["foo.rehu", "foo00.jpg", "foo01.png", "foo.zip"]
    mock_siblings(mocker, filenames)
    mocker.patch.object(Path, "iterdir", return_value=[DIRECTORY / name for name in filenames])
    mock_archives(mocker, {DIRECTORY / "foo.zip": [zip_info("page01.jpg")]})

    screenshots = scan_rehu_screenshot_files(DIRECTORY, "foo")
    entries = enumerate_content_images(FILE_SCOPED_PATH)

    assert screenshots == [DIRECTORY / "foo00.jpg", DIRECTORY / "foo01.png"]
    assert entries == [entry(DIRECTORY / "foo.zip", "page01.jpg")]


# endregion


# region rename barrier


def test_archives_open_through_the_share_delete_reader(mocker: MockerFixture) -> None:
    """Every archive is opened through :func:`~borco_core.shared_read_open`, so a file-scoped rename is
    never refused by the scan's own handle (#347).

    **Test steps:**

    * mock one sibling archive and enumerate
    * verify the opener was asked for it, and the file it returned was closed again
    """
    mock_siblings(mocker, ["foo.zip"])
    mock_archives(mocker, {DIRECTORY / "foo.zip": [zip_info("page01.jpg")]})
    opener = mocker.patch("rehuco_core.rehu_content_images.shared_read_open", wraps=None)
    opener.return_value.__enter__.return_value = DIRECTORY / "foo.zip"

    enumerate_content_images(FILE_SCOPED_PATH)

    opener.assert_called_once_with(DIRECTORY / "foo.zip")
    opener.return_value.__exit__.assert_called_once()


def test_each_archive_is_read_inside_its_own_hold(mocker: MockerFixture) -> None:
    """With a coordinator, each archive is opened inside a
    :meth:`~rehuco_core.RenameCoordinator.holding` of its own, never one hold for the whole walk (#347).

    **Test steps:**

    * mock a directory holding two archives, and a coordinator whose hold records entry and exit
    * enumerate with it, recording at each open how deep in holds the scan is
    * verify both opens ran inside exactly one hold, and the holds were entered and left once per archive
    """
    depth = [0]
    events: list[str] = []

    @contextmanager
    def holding() -> Generator[None]:
        depth[0] += 1
        events.append("enter")
        try:
            yield
        finally:
            depth[0] -= 1
            events.append("exit")

    coordinator = mocker.MagicMock(spec=RenameCoordinator)
    coordinator.holding.side_effect = holding
    mock_tree(mocker, [DIRECTORY / "a.zip", DIRECTORY / "b.zip"])
    mock_archives(mocker, {DIRECTORY / "a.zip": [zip_info("a.jpg")], DIRECTORY / "b.zip": [zip_info("b.jpg")]})
    opener = mock_shared_read_open(mocker)
    open_file = opener.side_effect

    def recording_open(path: Path) -> MagicMock:
        events.append(f"open@{depth[0]}")
        return open_file(path)

    opener.side_effect = recording_open

    entries = enumerate_content_images(DIRECTORY_SCOPED_PATH, coordinator=coordinator)

    assert entries == [entry(DIRECTORY / "a.zip", "a.jpg"), entry(DIRECTORY / "b.zip", "b.jpg")]
    assert events == ["enter", "open@1", "exit", "enter", "open@1", "exit"]


# endregion
