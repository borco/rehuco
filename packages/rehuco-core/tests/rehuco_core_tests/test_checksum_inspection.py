"""Tests for the read-only check of a ``.checksum`` record (#715).

On a real temporary directory, as ``test_checksums_of_no_content.py`` is: what is under test is what is, and is not,
written to a disk.
"""

import json
from pathlib import Path

from pytest import fixture, raises
from rehuco_core import (
    RehuDocument,
    checksum_record_path,
    generate_checksums,
    inspect_checksums,
    verify_checksums,
)


@fixture(name="rehu")
def fixture_rehu(tmp_path: Path) -> Path:
    """A folder record with two checksummed files.

    :param tmp_path: pytest fixture.
    :returns: the record's path.
    """
    folder = tmp_path / "asset"
    folder.mkdir()
    path = folder / "info.rehu"
    document = RehuDocument.new(path, username="tester")
    document.title = "A record"
    document.save()
    (folder / "a.bin").write_bytes(b"alpha")
    (folder / "b.bin").write_bytes(b"bravo")
    generate_checksums(path)
    return path


def test_a_check_says_what_a_verify_says_and_writes_nothing(rehu: Path) -> None:
    """The same verdicts, none recorded: the record keeps the date and status it had.

    **Test steps:**

    * change one file, delete the other and add an unlisted one
    * check the record, and verify a copy of it
    * check both name the same verdicts, and the checked record's bytes are unchanged
    """
    (rehu.parent / "a.bin").write_bytes(b"changed")
    (rehu.parent / "b.bin").unlink()
    (rehu.parent / "c.bin").write_bytes(b"new")
    record = checksum_record_path(rehu)
    before = record.read_bytes()

    inspection = inspect_checksums(rehu, list_without_checksum=True)

    assert record.read_bytes() == before
    assert inspection.report.statuses == {"a.bin": "mismatched", "b.bin": "missing"}
    assert inspection.without_checksum == ("c.bin",)
    assert inspection.findings == ("a.bin", "b.bin")
    verified = verify_checksums(rehu).statuses
    assert {name: status for name, status in verified.items() if name != "c.bin"} == inspection.report.statuses


def test_an_entry_with_no_hash_has_no_checksum(rehu: Path) -> None:
    """Listed without a hash reads as not listed, and an entry this build cannot read is ``malformed``.

    **Test steps:**

    * strip one entry's hash and spoil the other's
    * check the record
    * check the first is listed as without a checksum and the second is malformed
    """
    record = checksum_record_path(rehu)
    data = json.loads(record.read_text(encoding="utf-8"))
    data["files"][0] = {"name": "a.bin"}
    data["files"][1] = {"name": "b.bin", "xxh3": "not hex"}
    record.write_text(json.dumps(data), encoding="utf-8")

    inspection = inspect_checksums(rehu, list_without_checksum=True)

    assert inspection.without_checksum == ("a.bin",)
    assert inspection.report.statuses == {"b.bin": "malformed"}


def test_a_check_without_hashing_only_looks_for_the_files(rehu: Path) -> None:
    """The progress callback is never told, and a changed file is present.

    **Test steps:**

    * change one file and delete the other
    * check the record asking for no hashing, with a progress callback
    * check the verdicts are present and missing, and the callback was not called
    """
    (rehu.parent / "a.bin").write_bytes(b"changed")
    (rehu.parent / "b.bin").unlink()
    told: list[tuple[int, int | None]] = []

    inspection = inspect_checksums(rehu, hash_files=False, progress=lambda done, total: told.append((done, total)))

    assert inspection.report.statuses == {"a.bin": "present", "b.bin": "missing"}
    assert not told


def test_a_check_reports_bytes_and_names_as_it_goes(rehu: Path) -> None:
    """Progress counts bytes against the total planned, and each file is named as its check starts.

    **Test steps:**

    * check the record with a progress callback and a file callback
    * check the names arrive in the record's order and the last progress is every byte
    """
    told: list[tuple[int, int | None]] = []
    named: list[str] = []

    inspect_checksums(rehu, progress=lambda done, total: told.append((done, total)), on_file=named.append)

    assert named == ["a.bin", "b.bin"]
    assert told[0] == (0, 10)
    assert told[-1] == (10, 10)


def test_a_resource_with_no_record_is_refused_and_none_is_made(rehu: Path) -> None:
    """Unlike a verify allowed to create one, a check never starts a record.

    **Test steps:**

    * delete the record and check the resource
    * check it is refused and no record exists afterward
    """
    checksum_record_path(rehu).unlink()

    with raises(FileNotFoundError):
        inspect_checksums(rehu)

    assert not checksum_record_path(rehu).exists()


def test_an_entry_with_no_name_is_counted_and_a_name_listed_twice_is_checked_once(rehu: Path) -> None:
    """What cannot be named is only a count, and the first entry of a name decides.

    **Test steps:**

    * add an entry with no name and a second entry for a listed file, with a wrong hash
    * check the record
    * check one entry is unnamed and malformed, and the file is checked once, against the first entry
    """
    record = checksum_record_path(rehu)
    data = json.loads(record.read_text(encoding="utf-8"))
    data["files"].extend([{"xxh3": "00"}, {"name": "a.bin", "crc32": "00000000"}])
    record.write_text(json.dumps(data), encoding="utf-8")

    inspection = inspect_checksums(rehu)

    assert inspection.report.unnamed_malformed == 1
    assert inspection.report.statuses == {"a.bin": "matched", "b.bin": "matched"}


def test_a_listed_file_that_cannot_be_read_is_reported_unreadable(rehu: Path) -> None:
    """Neither a verdict nor missing: a directory where the file should be refuses the read.

    **Test steps:**

    * replace a listed file with a directory
    * check the record
    * check the name is unreadable, has no verdict and is a finding
    """
    (rehu.parent / "a.bin").unlink()
    (rehu.parent / "a.bin").mkdir()

    inspection = inspect_checksums(rehu)

    assert inspection.report.unreadable == ("a.bin",)
    assert inspection.report.statuses == {"b.bin": "matched"}
    assert inspection.findings == ("a.bin",)
