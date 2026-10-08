"""Tests for a new file-scoped record taking its checksums from the record enclosing it (#467).

On a real temporary directory rather than a fake disk: nothing here counts bytes, and what is under test is
which record ends up holding which entry -- a question about two files on disk, best asked of two files.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_core import (
    CHECKSUM_ALGORITHMS,
    DEFAULT_CHECKSUM_ALGORITHM,
    CoveringRecord,
    RenameCoordinator,
    is_checksum_fresh,
    parse_checksum_entry,
    save_checksum_record,
    take_enclosing_claims,
    verify_checksums,
)

ZIP_BYTES = b"the pack as it was downloaded"
VIDEO_BYTES = b"a lesson"
VERIFIED = "2026-08-05T12:00:00Z"


def digest_of(payload: bytes) -> str:
    """Hash bytes the way a record records them.

    :param payload: the bytes.
    :returns: the hex digest under the default algorithm.
    """
    digest = CHECKSUM_ALGORITHMS[DEFAULT_CHECKSUM_ALGORITHM].new_digest()
    digest.update(payload)
    return digest.hexdigest()


def entry(name: str, payload: bytes) -> dict[str, Any]:
    """A checked entry, as a verify writes one.

    :param name: the record-relative name.
    :param payload: the bytes whose hash to record.
    :returns: the raw entry.
    """
    return {"name": name, DEFAULT_CHECKSUM_ALGORITHM: digest_of(payload), "verified": VERIFIED, "status": "matched"}


def write_record(path: Path, entries: list[Any]) -> None:
    """Put a ``.checksum`` on disk.

    :param path: where.
    :param entries: its raw entries.
    """
    path.write_text(json.dumps({"version": 1, "files": entries}, indent=2) + "\n", encoding="utf-8")


def entries_of(path: Path) -> dict[str, dict[str, Any]]:
    """A ``.checksum``'s entries by name.

    :param path: the record.
    :returns: name to entry.
    """
    return {raw["name"]: raw for raw in json.loads(path.read_text(encoding="utf-8"))["files"]}


@fixture(name="folder")
def fixture_folder(tmp_path: Path) -> Path:
    """A directory-scoped resource whose ``info.checksum`` lists a pack, its screenshot-shaped image and a video.

    :param tmp_path: pytest's temporary directory.
    :returns: the resource's directory, with no ``foo.rehu`` in it yet.
    """
    (tmp_path / "info.rehu").write_text("{}", encoding="utf-8")
    (tmp_path / "foo.zip").write_bytes(ZIP_BYTES)
    (tmp_path / "foo00.jpg").write_bytes(b"a picture")
    (tmp_path / "lesson.mp4").write_bytes(VIDEO_BYTES)
    write_record(
        tmp_path / "info.checksum",
        [entry("foo.zip", ZIP_BYTES), entry("foo00.jpg", b"a picture"), entry("lesson.mp4", VIDEO_BYTES)],
    )
    return tmp_path


def create(folder: Path, name: str = "foo.rehu") -> Path:
    """Write a new record, as its first save does.

    :param folder: where.
    :param name: the record's file name.
    :returns: its path.
    """
    path = folder / name
    path.write_text("{}", encoding="utf-8")
    return path


def test_creating_a_record_moves_its_entries_out_of_the_enclosing_record(folder: Path) -> None:
    """``foo.zip``'s entry moves to ``foo.checksum`` at once, carrying its hash and nothing else (#467).

    **Test steps:**

    * create ``foo.rehu`` beside a ``foo.zip`` that ``info.checksum`` lists, and take its claims
    * check the entry is in ``foo.checksum`` with its digest and algorithm and no date or status
    * check it left ``info.checksum``, whose other entries are untouched, and the report says so
    """
    record = create(folder)
    before = entries_of(folder / "info.checksum")

    taken = take_enclosing_claims(record)

    assert entries_of(folder / "foo.checksum") == {
        "foo.zip": {"name": "foo.zip", DEFAULT_CHECKSUM_ALGORITHM: digest_of(ZIP_BYTES)}
    }
    after = entries_of(folder / "info.checksum")
    assert "foo.zip" not in after
    assert after["lesson.mp4"] == before["lesson.mp4"]
    assert taken is not None
    assert taken.source == folder / "info.checksum"
    assert taken.moved == {"foo.zip": CoveringRecord(record, "foo.zip")}
    assert taken.pruned


def test_a_screenshot_of_the_new_record_is_not_moved(folder: Path) -> None:
    """``foo00.jpg`` is the new record's bookkeeping, not its content, so its entry stays where it is.

    **Test steps:**

    * create ``foo.rehu`` and take its claims
    * check ``foo00.jpg``'s entry is still in ``info.checksum`` and not in ``foo.checksum``
    """
    take_enclosing_claims(create(folder))

    assert "foo00.jpg" in entries_of(folder / "info.checksum")
    assert "foo00.jpg" not in entries_of(folder / "foo.checksum")


def test_a_moved_file_needs_a_recheck_which_its_next_verify_makes(folder: Path) -> None:
    """The moved entry is never fresh, so the new record's next verify reads the file and dates it (#467).

    **Test steps:**

    * create ``foo.rehu`` and take its claims
    * check the moved entry is not fresh under any window
    * verify ``foo.rehu`` with a long window
    * check the file was checked -- matched, dated -- under the hash it arrived with
    """
    record = create(folder)
    take_enclosing_claims(record)
    moved = parse_checksum_entry(entries_of(folder / "foo.checksum")["foo.zip"])
    assert moved is not None
    assert moved.verified is None
    assert not is_checksum_fresh(moved, timedelta(days=3650), datetime.now(UTC))

    report = verify_checksums(record, stale_after=timedelta(days=3650))

    assert report.statuses == {"foo.zip": "matched"}
    checked = entries_of(folder / "foo.checksum")["foo.zip"]
    assert checked[DEFAULT_CHECKSUM_ALGORITHM] == digest_of(ZIP_BYTES)
    assert checked["status"] == "matched"
    assert "verified" in checked


def test_a_record_under_a_deeper_folder_takes_from_the_nearest_enclosing_record(folder: Path) -> None:
    """The enclosing record may sit any number of folders up, and spells the file with its folder (#467).

    **Test steps:**

    * list ``sub/bar.zip`` in the top ``info.checksum``, then create ``sub/bar.rehu``
    * check the entry moved, and ``sub/bar.checksum`` spells it ``bar.zip``
    """
    sub = folder / "sub"
    sub.mkdir()
    (sub / "bar.zip").write_bytes(ZIP_BYTES)
    write_record(folder / "info.checksum", [entry("sub/bar.zip", ZIP_BYTES), entry("lesson.mp4", VIDEO_BYTES)])

    take_enclosing_claims(create(sub, "bar.rehu"))

    assert set(entries_of(sub / "bar.checksum")) == {"bar.zip"}
    assert set(entries_of(folder / "info.checksum")) == {"lesson.mp4"}


def test_a_failure_writing_the_new_record_leaves_the_entry_where_it_was(folder: Path, mocker: MockerFixture) -> None:
    """A destination that cannot be written keeps its claims in the enclosing record (#467).

    **Test steps:**

    * make writing ``foo.checksum`` fail, create ``foo.rehu`` and take its claims
    * check nothing moved and ``info.checksum`` still lists ``foo.zip`` unchanged
    """
    before = (folder / "info.checksum").read_text(encoding="utf-8")
    mocker.patch(
        "rehuco_core.checksum_claim_moves.save_checksum_record",
        side_effect=PermissionError("read-only share"),
    )

    taken = take_enclosing_claims(create(folder))

    assert taken is None
    assert not (folder / "foo.checksum").exists()
    assert (folder / "info.checksum").read_text(encoding="utf-8") == before


def test_a_failure_pruning_the_enclosing_record_leaves_the_claim_in_both_until_its_next_verify(
    folder: Path, mocker: MockerFixture
) -> None:
    """The new record is written first, so a failed prune duplicates the claim rather than losing it (#467).

    **Test steps:**

    * make writing ``info.checksum`` fail, create ``foo.rehu`` and take its claims
    * check ``foo.zip`` is in both records and the report says the prune failed
    * verify ``info.rehu``
    * check the entry is now in ``foo.checksum`` only
    """

    def save(path: Path, record: dict[str, Any]) -> None:
        if path.name == "info.checksum":
            raise PermissionError("read-only share")
        save_checksum_record(path, record)

    mocker.patch("rehuco_core.checksum_claim_moves.save_checksum_record", side_effect=save)
    record = create(folder)

    taken = take_enclosing_claims(record)

    assert taken is not None
    assert not taken.pruned
    assert "foo.zip" in entries_of(folder / "foo.checksum")
    assert "foo.zip" in entries_of(folder / "info.checksum")

    mocker.stopall()
    verify_checksums(folder / "info.rehu")

    assert "foo.zip" not in entries_of(folder / "info.checksum")
    assert "foo.zip" in entries_of(folder / "foo.checksum")


def test_an_enclosing_checksum_this_build_cannot_read_moves_nothing(folder: Path, caplog: Any) -> None:
    """A record that is not JSON is left alone and said so, and the save it follows still stands (#467).

    **Test steps:**

    * make ``info.checksum`` unreadable, create ``foo.rehu`` and take its claims
    * check nothing moved, the file is untouched and the log names it
    """
    (folder / "info.checksum").write_text("not json", encoding="utf-8")

    with caplog.at_level("WARNING", logger="rehuco_core.checksum_claim_moves"):
        assert take_enclosing_claims(create(folder)) is None

    assert (folder / "info.checksum").read_text(encoding="utf-8") == "not json"
    assert "info.checksum could not be read" in caplog.text


def test_an_entry_for_the_new_records_own_bookkeeping_moves_nothing(folder: Path) -> None:
    """A same-stem name the new record never covers -- its own record file -- has no claim to move.

    Unnamed and duplicate entries are passed over on the way, as every reader of a record passes them over.

    **Test steps:**

    * list an unnamed entry, ``foo.rehu`` itself twice, and the video in ``info.checksum``; create ``foo.rehu``
    * check nothing moved and ``info.checksum`` is byte-for-byte what it was
    """
    write_record(
        folder / "info.checksum",
        [
            {"xxh3": digest_of(b"x")},
            entry("foo.rehu", b"{}"),
            entry("foo.rehu", b"{}"),
            entry("lesson.mp4", VIDEO_BYTES),
        ],
    )
    before = (folder / "info.checksum").read_text(encoding="utf-8")

    assert take_enclosing_claims(create(folder)) is None
    assert (folder / "info.checksum").read_text(encoding="utf-8") == before


def test_no_enclosing_checksum_moves_nothing(folder: Path) -> None:
    """A folder whose record has no ``.checksum`` has nothing to give (#467).

    **Test steps:**

    * remove ``info.checksum``, create ``foo.rehu`` and take its claims
    * check nothing moved and no ``foo.checksum`` was written
    """
    (folder / "info.checksum").unlink()

    assert take_enclosing_claims(create(folder)) is None
    assert not (folder / "foo.checksum").exists()


def test_no_enclosing_record_moves_nothing(tmp_path: Path) -> None:
    """A file-scoped record with no directory-scoped record above it takes nothing.

    **Test steps:**

    * create ``foo.rehu`` in a folder no ``info.rehu`` covers, beside a stray ``info.checksum``
    * check nothing moved
    """
    (tmp_path / "foo.zip").write_bytes(ZIP_BYTES)
    write_record(tmp_path / "info.checksum", [entry("foo.zip", ZIP_BYTES)])

    assert take_enclosing_claims(create(tmp_path)) is None
    assert "foo.zip" in entries_of(tmp_path / "info.checksum")


def test_an_enclosing_record_that_does_not_list_the_file_moves_nothing(folder: Path) -> None:
    """Only listed files have claims to move (#467).

    **Test steps:**

    * create ``bar.rehu`` beside a ``bar.zip`` ``info.checksum`` does not list, and take its claims
    * check nothing moved and ``info.checksum`` is byte-for-byte what it was
    """
    (folder / "bar.zip").write_bytes(ZIP_BYTES)
    before = (folder / "info.checksum").read_text(encoding="utf-8")

    assert take_enclosing_claims(create(folder, "bar.rehu")) is None
    assert not (folder / "bar.checksum").exists()
    assert (folder / "info.checksum").read_text(encoding="utf-8") == before


def test_a_legacy_manifest_not_yet_seeded_keeps_the_claims_where_they_are(folder: Path) -> None:
    """A new record with a ``foo.sfv`` beside it and no ``foo.checksum`` is owed its seed first (#243, #467).

    **Test steps:**

    * put ``foo.sfv`` beside ``foo.zip``, create ``foo.rehu`` and take its claims
    * check nothing moved, no ``foo.checksum`` was written and ``info.checksum`` still lists ``foo.zip``
    """
    (folder / "foo.sfv").write_text("foo.zip 12345678\n", encoding="utf-8")

    assert take_enclosing_claims(create(folder)) is None
    assert not (folder / "foo.checksum").exists()
    assert "foo.zip" in entries_of(folder / "info.checksum")


def test_a_directory_scoped_record_takes_nothing_here(folder: Path) -> None:
    """Only a file-scoped record takes its claims at creation; a nested ``info.rehu`` waits for a verify.

    **Test steps:**

    * list ``sub/bar.zip`` in the top ``info.checksum`` and create ``sub/info.rehu``
    * check nothing moved
    """
    sub = folder / "sub"
    sub.mkdir()
    (sub / "bar.zip").write_bytes(ZIP_BYTES)
    write_record(folder / "info.checksum", [entry("sub/bar.zip", ZIP_BYTES)])

    assert take_enclosing_claims(create(sub, "info.rehu")) is None
    assert "sub/bar.zip" in entries_of(folder / "info.checksum")


def test_a_rename_waits_only_for_the_two_writes(folder: Path, mocker: MockerFixture) -> None:
    """The listing and the reads happen outside the rename barrier; only the two writes hold it (#241, #467).

    **Test steps:**

    * take a new record's claims through a coordinator whose hold is counted
    * check the barrier was held exactly twice -- once per record written
    """
    coordinator = RenameCoordinator()
    holding = mocker.spy(coordinator, "holding")

    take_enclosing_claims(create(folder), coordinator=coordinator)

    assert holding.call_count == 2
