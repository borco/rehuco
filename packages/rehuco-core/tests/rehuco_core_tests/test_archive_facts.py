"""Tests for what a zip's central directory says it holds, and the pack-ordered image listing built on it (#456)."""

import zipfile
from binascii import crc32
from pathlib import Path
from typing import Final

from pytest_mock import MockerFixture
from rehuco_core import (
    CONTENT_IMAGE_EXTENSIONS,
    ArchiveFacts,
    ContentImageEntry,
    RenameCoordinator,
    list_archive_images,
    read_archive_facts,
)

PAYLOAD: Final = b"0123456789" * 200
"""Compressible, so a deflated member is smaller than its stored twin."""


def write_zip(path: Path, members: dict[str, int]) -> Path:
    """Write a zip with the named members, each in the given method.

    :param path: the file.
    :param members: member name to compression method; a name ending in ``/`` is a folder entry.
    :returns: the path.
    """
    with zipfile.ZipFile(path, "w") as archive:
        for name, method in members.items():
            if name.endswith("/"):
                archive.mkdir(name.rstrip("/"))
            else:
                archive.writestr(name, PAYLOAD, compress_type=method)
    return path


def test_a_stored_archive_counts_its_files_and_images_and_both_sizes(tmp_path: Path) -> None:
    """Folders are not files, packed equals unpacked for store, and only recognized images are images.

    **Test steps:**

    * write a stored zip with a folder, two pictures, a note and a dot-file
    * verify the counts, the sizes and the method
    """
    archive = write_zip(
        tmp_path / "a.zip",
        {
            "pics/": zipfile.ZIP_STORED,
            "pics/a.jpg": zipfile.ZIP_STORED,
            "pics/b.PNG": zipfile.ZIP_STORED,
            "note.txt": zipfile.ZIP_STORED,
            "pics/.hidden.jpg": zipfile.ZIP_STORED,
        },
    )

    facts = read_archive_facts(archive, CONTENT_IMAGE_EXTENSIONS)

    assert facts is not None
    assert facts == ArchiveFacts(
        files=4, images=2, unpacked=4 * len(PAYLOAD), packed=4 * len(PAYLOAD), methods={zipfile.ZIP_STORED: 4}
    )
    assert facts.method_text == "Stored"
    assert not facts.slow and not facts.unreadable


def test_a_deflated_archive_packs_smaller_and_says_deflated(tmp_path: Path) -> None:
    """The packed size is what the directory records, not an estimate.

    **Test steps:**

    * write a deflated zip of compressible members
    * verify packed is below unpacked and the method is named
    """
    archive = write_zip(tmp_path / "d.zip", {"a.jpg": zipfile.ZIP_DEFLATED, "b.jpg": zipfile.ZIP_DEFLATED})

    facts = read_archive_facts(archive, CONTENT_IMAGE_EXTENSIONS)

    assert facts is not None
    assert facts.unpacked == 2 * len(PAYLOAD)
    assert 0 < facts.packed < facts.unpacked
    assert facts.method_text == "Deflated"


def test_a_mixed_archive_says_how_many_members_use_each_method(tmp_path: Path) -> None:
    """Neither method names the archive, so the counts do.

    **Test steps:**

    * write a zip with two stored members and one deflated
    * verify the text counts both methods
    """
    archive = write_zip(
        tmp_path / "m.zip",
        {"a.jpg": zipfile.ZIP_STORED, "b.jpg": zipfile.ZIP_STORED, "c.jpg": zipfile.ZIP_DEFLATED},
    )

    facts = read_archive_facts(archive, CONTENT_IMAGE_EXTENSIONS)

    assert facts is not None
    assert facts.method_text == "Mixed (2 stored, 1 deflated)"


def test_bzip2_and_lzma_are_readable_but_slow_and_other_methods_are_unreadable() -> None:
    """The warnings are decided by the method alone.

    **Test steps:**

    * build facts for bzip2, lzma, zstd, deflate64 and an encrypted deflated member
    * verify which are slow and which are unreadable
    """

    def facts(method: int, encrypted: int = 0) -> ArchiveFacts:
        return ArchiveFacts(1, 1, 10, 5, {method: 1}, encrypted)

    assert facts(zipfile.ZIP_BZIP2).slow and not facts(zipfile.ZIP_BZIP2).unreadable
    assert facts(zipfile.ZIP_LZMA).slow and not facts(zipfile.ZIP_LZMA).unreadable
    assert not facts(zipfile.ZIP_ZSTANDARD).slow and not facts(zipfile.ZIP_ZSTANDARD).unreadable
    assert facts(9).unreadable and facts(9).method_text == "Deflate64"
    assert facts(zipfile.ZIP_DEFLATED, encrypted=1).unreadable
    assert ArchiveFacts(0, 0, 0, 0, {}).method_text == ""


def test_an_empty_archive_has_nothing_in_it(tmp_path: Path) -> None:
    """No member, no method.

    **Test steps:**

    * write an empty zip
    * verify zero counts and an empty method text
    """
    path = tmp_path / "empty.zip"
    with zipfile.ZipFile(path, "w"):
        pass

    facts = read_archive_facts(path, CONTENT_IMAGE_EXTENSIONS)

    assert facts is not None
    assert facts == ArchiveFacts(0, 0, 0, 0, {})
    assert facts.method_text == ""


def test_a_file_that_is_no_zip_or_is_gone_has_no_facts(tmp_path: Path) -> None:
    """Reported as ``None``, never raised.

    **Test steps:**

    * read a text file named ``.zip``, a truncated zip and a missing path
    * verify each answers ``None``
    """
    text = tmp_path / "text.zip"
    text.write_bytes(b"not a zip")
    whole = write_zip(tmp_path / "whole.zip", {"a.jpg": zipfile.ZIP_STORED})
    truncated = tmp_path / "cut.zip"
    truncated.write_bytes(whole.read_bytes()[:-30])

    assert read_archive_facts(text, CONTENT_IMAGE_EXTENSIONS) is None
    assert read_archive_facts(truncated, CONTENT_IMAGE_EXTENSIONS) is None
    assert read_archive_facts(tmp_path / "gone.zip", CONTENT_IMAGE_EXTENSIONS) is None


def test_no_member_is_opened_and_the_read_is_one_hold(tmp_path: Path, mocker: MockerFixture) -> None:
    """The directory alone answers, inside a single hold of the rename coordinator.

    **Test steps:**

    * make ``ZipFile.open`` raise, and spy on the coordinator's ``holding``
    * read a zip's facts and list its images
    * verify both answered, with one hold each
    """
    archive = write_zip(tmp_path / "a.zip", {"a.jpg": zipfile.ZIP_DEFLATED, "b.jpg": zipfile.ZIP_STORED})
    mocker.patch.object(zipfile.ZipFile, "open", side_effect=AssertionError("a member was opened"))
    coordinator = RenameCoordinator()
    holding = mocker.spy(coordinator, "holding")

    facts = read_archive_facts(archive, CONTENT_IMAGE_EXTENSIONS, coordinator)
    entries = list_archive_images(archive, CONTENT_IMAGE_EXTENSIONS, coordinator)

    assert facts is not None and facts.files == 2
    assert [entry.name for entry in entries] == ["a.jpg", "b.jpg"]
    assert holding.call_count == 2


def test_the_images_are_listed_in_pack_order_not_directory_order(tmp_path: Path) -> None:
    """The root's images come before a folder's, each folder's before its subfolders', names in natural order.

    **Test steps:**

    * write a zip whose directory lists ``b10``, ``b2``, a folder image and the root's ``z`` image, with upper-case
      extensions among them
    * verify the order, the archive and the CRC each entry carries, and that junk is left out
    """
    archive = write_zip(
        tmp_path / "p.zip",
        {
            "sub/x.jpg": zipfile.ZIP_STORED,
            "b10.jpg": zipfile.ZIP_STORED,
            "__MACOSX/b2.jpg": zipfile.ZIP_STORED,
            "b2.JPG": zipfile.ZIP_STORED,
            "z.png": zipfile.ZIP_STORED,
            "readme.txt": zipfile.ZIP_STORED,
        },
    )

    entries = list_archive_images(archive, (".jpg", ".png"))

    assert [entry.name for entry in entries] == ["b2.JPG", "b10.jpg", "z.png", "sub/x.jpg"]
    assert all(isinstance(entry, ContentImageEntry) and entry.archive == archive for entry in entries)
    assert all(entry.crc == crc32(PAYLOAD) and entry.size == len(PAYLOAD) for entry in entries)


def test_listing_an_unreadable_archive_gives_nothing(tmp_path: Path) -> None:
    """Absent, not a zip: empty, as the scanner has always reported them.

    **Test steps:**

    * list a missing path and a text file
    * verify both are empty
    """
    text = tmp_path / "text.zip"
    text.write_bytes(b"nope")

    assert list_archive_images(tmp_path / "gone.zip", CONTENT_IMAGE_EXTENSIONS) == []
    assert list_archive_images(text, CONTENT_IMAGE_EXTENSIONS) == []
