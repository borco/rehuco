"""Tests for reference-images content-image enumeration ([[data-model#resource-scoping]])."""

import zipfile
from pathlib import Path
from typing import Final
from unittest.mock import MagicMock

from pytest_mock import MockerFixture
from rehuco_core import (
    INFO_REHU_FILENAME,
    INFO_TC_FILENAME,
    ContentImageEntry,
    enumerate_content_images,
    scan_rehu_screenshot_files,
)

DIRECTORY: Final = Path("/fake/refimages")
FILE_SCOPED_PATH: Final = DIRECTORY / "foo.rehu"
DIRECTORY_SCOPED_PATH: Final = DIRECTORY / INFO_REHU_FILENAME


def mock_siblings(mocker: MockerFixture, filenames: list[str]) -> None:
    """Mock ``Path.iterdir`` so :data:`DIRECTORY` appears to hold ``filenames``.

    :param mocker: pytest-mock fixture.
    :param filenames: the fake filenames the directory should list.
    """
    mocker.patch.object(Path, "iterdir", return_value=[DIRECTORY / name for name in filenames])


def mock_tree(mocker: MockerFixture, paths: list[Path]) -> None:
    """Mock ``Path.rglob`` so :data:`DIRECTORY`'s recursive tree appears to hold ``paths``.

    :param mocker: pytest-mock fixture.
    :param paths: the fake paths the recursive walk should yield.
    """
    mocker.patch.object(Path, "rglob", return_value=paths)


def mock_archives(mocker: MockerFixture, contents: dict[Path, list[zipfile.ZipInfo] | Exception]) -> MagicMock:
    """Mock ``zipfile.ZipFile`` so opening a path named in ``contents`` yields that archive's entries.

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

    return mocker.patch("rehuco_core.rehu_content_images.zipfile.ZipFile", side_effect=side_effect)


def zip_info(name: str) -> zipfile.ZipInfo:
    """Build a real :class:`zipfile.ZipInfo` for ``name`` -- a plain data holder, no archive needed.

    :param name: the entry's stored path.
    :returns: a :class:`zipfile.ZipInfo` naming it.
    """
    return zipfile.ZipInfo(name)


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

    assert entries == [ContentImageEntry(DIRECTORY / "foo.zip", "page01.jpg")]
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

    assert entries == [ContentImageEntry(DIRECTORY / "FOO.ZIP", "page01.jpg")]


def test_file_scoped_lists_entries_in_infolist_order_ignoring_non_images(mocker: MockerFixture) -> None:
    """Non-image entries are dropped; recognized ones keep the archive's own central-directory order.

    **Test steps:**

    * mock ``foo.zip`` to hold two images and a text file, image entries out of alphabetical order
    * enumerate
    * verify only the two images come back, in the archive's own order
    """
    mock_siblings(mocker, ["foo.zip"])
    mock_archives(
        mocker,
        {DIRECTORY / "foo.zip": [zip_info("page02.jpg"), zip_info("readme.txt"), zip_info("page01.png")]},
    )

    entries = enumerate_content_images(FILE_SCOPED_PATH)

    assert entries == [
        ContentImageEntry(DIRECTORY / "foo.zip", "page02.jpg"),
        ContentImageEntry(DIRECTORY / "foo.zip", "page01.png"),
    ]


def test_loose_sibling_images_are_never_counted(mocker: MockerFixture) -> None:
    """Loose files beside the ``.rehu`` are never opened as archives, even if named like a screenshot.

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
        ContentImageEntry(root_zip, "page01.jpg"),
        ContentImageEntry(nested_cbz, "page01.jpg"),
    ]


def test_directory_scoped_includes_a_subdirectory_with_its_own_info_rehu(mocker: MockerFixture) -> None:
    """A nested ``info.rehu`` is not a boundary -- its directory's archives still sum into the parent.

    **Test steps:**

    * mock the tree to hold a nested ``info.rehu`` alongside a nested archive
    * enumerate the parent ``info.rehu``'s content images
    * verify the nested archive's entries are included
    """
    nested_archive = DIRECTORY / "child" / "images.zip"
    mock_tree(mocker, [DIRECTORY / "child" / INFO_REHU_FILENAME, nested_archive])
    mock_archives(mocker, {nested_archive: [zip_info("page01.jpg")]})

    entries = enumerate_content_images(DIRECTORY_SCOPED_PATH)

    assert entries == [ContentImageEntry(nested_archive, "page01.jpg")]


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

    assert entries == [ContentImageEntry(root_zip, "page01.jpg"), ContentImageEntry(nested_cbz, "page02.jpg")]


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

    assert entries == [ContentImageEntry(DIRECTORY / "foo.zip", "page/keep.jpg")]


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

    assert entries == [ContentImageEntry(DIRECTORY / "foo.zip", "volume1/chapter2/page03.jpg")]


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

    assert entries == [ContentImageEntry(DIRECTORY / "foo.zip", "page01.jpg")]


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

    assert entries == [ContentImageEntry(DIRECTORY / "foo.zip", "page01.jpg")]
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

    assert default_entries == [ContentImageEntry(DIRECTORY / "foo.zip", "page01.jpg")]
    assert tiff_entries == [ContentImageEntry(DIRECTORY / "foo.zip", "page01.tiff")]


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

    * mock ``Path.iterdir`` to raise ``FileNotFoundError`` (file-scoped)
    * mock ``Path.rglob`` to raise ``FileNotFoundError`` (directory-scoped)
    * enumerate both
    * verify both results are empty
    """
    mocker.patch.object(Path, "iterdir", side_effect=FileNotFoundError)
    mocker.patch.object(Path, "rglob", side_effect=FileNotFoundError)

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
    mock_siblings(mocker, ["foo.rehu", "foo00.jpg", "foo01.png", "foo.zip"])
    mock_archives(mocker, {DIRECTORY / "foo.zip": [zip_info("page01.jpg")]})

    screenshots = scan_rehu_screenshot_files(DIRECTORY, "foo")
    entries = enumerate_content_images(FILE_SCOPED_PATH)

    assert screenshots == [DIRECTORY / "foo00.jpg", DIRECTORY / "foo01.png"]
    assert entries == [ContentImageEntry(DIRECTORY / "foo.zip", "page01.jpg")]


# endregion
