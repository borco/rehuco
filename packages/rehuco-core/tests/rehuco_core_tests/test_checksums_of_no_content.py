"""Tests for the checksum record of a resource that has no content: a store item that is metadata alone still gets a
record, an empty one, so a later verify -- and the move that runs it -- finds it checked (#685).

On a real temporary directory rather than a fake disk, as ``test_checksum_claims_at_creation.py`` is: what is under
test is whether a file ends up on disk.
"""

import json
from pathlib import Path

from pytest import fixture, raises
from pytest_mock import MockerFixture
from rehuco_core import RehuDocument, checksum_record_path, generate_checksums, rehu_checksums, verify_checksums

CONTENT_NAME = "model.fbx"


@fixture(name="rehu")
def fixture_rehu(tmp_path: Path) -> Path:
    """A record alone in its folder: no content beside it.

    :param tmp_path: pytest fixture.
    :returns: the record's path.
    """
    folder = tmp_path / "asset"
    folder.mkdir()
    path = folder / "info.rehu"
    document = RehuDocument.new(path, username="tester")
    document.title = "An item whose files have not arrived"
    document.save()
    return path


def recorded(rehu: Path) -> list[object]:
    """The entries of a record's checksum file.

    :param rehu: the record.
    :returns: the entries.
    """
    return json.loads(checksum_record_path(rehu).read_text(encoding="utf-8"))["files"]


def test_generating_for_a_record_with_no_content_writes_an_empty_record(rehu: Path) -> None:
    """Nothing to hash is still something to record: the file says the resource was checked and holds nothing.

    **Test steps:**

    * generate checksums for a record with no content
    * verify nothing was reported
    * verify the checksum file exists and lists no entry
    """
    report = generate_checksums(rehu)

    assert not report.statuses
    assert recorded(rehu) == []


def test_a_record_with_no_content_verifies_once_generated(rehu: Path) -> None:
    """The verify a move runs finds the empty record and has nothing against it.

    **Test steps:**

    * verify a record with no content and no checksum file, and check it is refused as having none
    * generate its checksums
    * verify again, creating nothing, and check the run is clean
    """
    with raises(FileNotFoundError):
        verify_checksums(rehu)
    generate_checksums(rehu)

    report = verify_checksums(rehu)

    assert not report.statuses
    assert not report.unreadable


def test_a_verify_told_to_start_from_nothing_writes_the_empty_record(rehu: Path) -> None:
    """A verify allowed to create the record creates it for a resource with no content too.

    **Test steps:**

    * verify a record with no content, allowing the record to be created
    * verify the checksum file exists and lists no entry
    """
    verify_checksums(rehu, create_if_missing=True)

    assert recorded(rehu) == []


def test_an_empty_record_is_written_once(mocker: MockerFixture, rehu: Path) -> None:
    """A run that finds the empty record, and still nothing to hash, leaves the file alone.

    **Test steps:**

    * generate checksums for a record with no content
    * watch the record's writer, then generate and verify again
    * verify neither run wrote
    """
    generate_checksums(rehu)
    write = mocker.spy(rehu_checksums, "update_checksum_record")

    generate_checksums(rehu)
    verify_checksums(rehu)

    write.assert_not_called()


def test_a_name_that_is_not_there_starts_no_record(rehu: Path) -> None:
    """A run over a selection of names is not a run over the resource: a typo does not leave a record behind.

    **Test steps:**

    * generate checksums of one name for a record with no content
    * verify the name is reported missing
    * verify no checksum file was written
    """
    report = generate_checksums(rehu, only=[CONTENT_NAME])

    assert report.statuses == {CONTENT_NAME: "missing"}
    assert not checksum_record_path(rehu).exists()


def test_content_that_could_not_be_read_starts_no_record(mocker: MockerFixture, rehu: Path) -> None:
    """A resource whose content could not be read is not one with none, so it gets no empty record saying it was
    checked.

    **Test steps:**

    * put a content file beside the record, and make every read of content fail
    * generate checksums
    * verify the file is reported unreadable
    * verify no checksum file was written
    """
    (rehu.parent / CONTENT_NAME).write_bytes(b"a model")
    mocker.patch("rehuco_core.content_reading.shared_read_open", side_effect=PermissionError("refused"))

    report = generate_checksums(rehu)

    assert report.unreadable == (CONTENT_NAME,)
    assert not checksum_record_path(rehu).exists()
