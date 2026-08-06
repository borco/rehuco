"""Tests for the ``.checksum`` record and the generate/verify over it (#203).

The disk is a hand-written fake rather than a real directory: what a read costs is not in question, and
a fake is what lets a test **count reads and bytes**, which several of these turn on -- that a fresh
verify reads nothing at all, and that migrating an entry to another algorithm reads its file once rather
than twice. The enumeration under test is the real one (#226), driven through a fake ``os.scandir``, so
the claim that a record covers exactly what the size scan counts is exercised rather than assumed.
"""

# pylint: disable=too-many-lines  # one cohesive module per subject, see [[appendices.code-conventions]]

import json
import re
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Any, Final

import xxhash
from freezegun.api import FrozenDateTimeFactory
from pytest import fixture, mark, raises
from pytest_mock import MockerFixture
from rehuco_core import (
    CHECKSUM_ALGORITHMS,
    DEFAULT_CHECKSUM_ALGORITHM,
    ChecksumRecordError,
    ChecksumReport,
    ContentUnreachableError,
    checksum_entry_name,
    checksum_record_path,
    content_size_on_disk,
    forget_checksums,
    generate_checksums,
    parse_checksum_entry,
    verify_checksums,
)

DIRECTORY: Final = Path("/fake/library/sculpting")
INFO_PATH: Final = DIRECTORY / "info.rehu"
RECORD_PATH: Final = DIRECTORY / "info.checksum"

VIDEO: Final = "lesson1.mp4"
ARCHIVE: Final = "extras/pack.zip"
RECORD_NAME: Final = "info.checksum"

VIDEO_BYTES: Final = bytes(range(256)) * 12
ARCHIVE_BYTES: Final = bytes(range(255, -1, -1)) * 7

CORRUPTED_VIDEO_BYTES: Final = b"\xff" + VIDEO_BYTES[1:]
"""The video with one byte flipped, and **the same length** -- so nothing but the hash can tell."""

REPACKED_BYTES: Final = b"repacked" + ARCHIVE_BYTES
"""The archive as a legitimate repack would leave it: different bytes, different length."""

NOW: Final = "2026-08-05T12:00:00Z"
LATER: Final = "2026-08-06T12:00:00Z"
MUCH_LATER: Final = "2026-09-05T12:00:00Z"

WEEK: Final = timedelta(days=7)


# region Fakes


class FakeDirEntry:
    """A stand-in for :class:`os.DirEntry`, which cannot be constructed outside a real directory read."""

    def __init__(self, name: str, *, directory: bool = False) -> None:
        self.name: Final = name
        self.__directory: Final = directory

    def is_dir(self, *, follow_symlinks: bool = True) -> bool:
        """Whether the fake declared this entry a directory."""
        del follow_symlinks
        return self.__directory

    def is_file(self, *, follow_symlinks: bool = True) -> bool:
        """Whether the fake declared this entry a regular file."""
        del follow_symlinks
        return not self.__directory


class FakeScandir:
    """What :func:`os.scandir` returns: an iterator that is also a context manager."""

    def __init__(self, entries: list[FakeDirEntry]) -> None:
        self.__entries: Final = entries

    def __enter__(self) -> Any:
        return iter(self.__entries)

    def __exit__(self, *_exception: object) -> None:
        return None


class FakeDisk:
    """Every file under :data:`DIRECTORY`, and a record of what was read and written.

    Serves the four ways this code reaches a filesystem -- the enumeration's ``os.scandir``, the chunked
    reader's :func:`~borco_core.shared_read_open`, the size scan's ``stat``, and the record's
    ``read_text``/:func:`~borco_core.atomic_write_text` -- from one dictionary, so a file added or
    removed between two runs is seen by all of them exactly as it would be on a disk.

    :param files: the resource's files, keyed by name relative to the ``.rehu``, POSIX-separated.
    """

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files: Final[dict[Path, bytes]] = {
            DIRECTORY / PurePosixPath(name): payload for name, payload in files.items()
        }
        self.reads: list[str] = []
        """Every content file opened for reading, in order, by record-relative name."""
        self.bytes_read = 0
        """How many bytes have been handed to a digest."""
        self.writes = 0
        """How many times the record has been written."""
        self.offline_directories: Final[set[Path]] = set()
        """The directories whose listing refuses -- an away mount, or a branch of one
        ([[mounts-and-storage#offline-mounts]]). Their files stay in :attr:`files`, because that is the
        point: they exist, and this run cannot see them (#245)."""
        self.open_errors: Final[dict[Path, OSError]] = {}
        """What opening a given file raises instead of serving it -- a share that refuses, or a file
        that vanished between the enumeration and the read, neither of which a test can arrange by
        editing :attr:`files`."""

    # region Filesystem faces

    def scandir(self, directory: Path | str) -> FakeScandir:
        """List one directory, derived from the current file set.

        :param directory: the directory to read.
        :returns: its entries -- files directly in it, and one entry per immediate subdirectory.
        :raises PermissionError: the directory is in :attr:`offline_directories`.
        :raises FileNotFoundError: nothing lives at or under ``directory``.
        """
        directory = Path(directory)
        if directory in self.offline_directories:
            raise PermissionError(str(directory))
        entries: list[FakeDirEntry] = []
        subdirectories: set[str] = set()
        for path in self.files:
            if path.parent == directory:
                entries.append(FakeDirEntry(path.name))
            elif directory in path.parents:
                subdirectories.add(path.relative_to(directory).parts[0])
        if not entries and not subdirectories and directory != DIRECTORY:
            raise FileNotFoundError(str(directory))
        entries.extend(FakeDirEntry(name, directory=True) for name in sorted(subdirectories))
        return FakeScandir(entries)

    def open(self, path: Path) -> BytesIO:
        """Serve a content file's bytes, counting the read.

        :param path: the file to open.
        :returns: a fresh reader over its bytes, counting what is taken from it.
        :raises OSError: whatever :attr:`open_errors` names for ``path``, or ``FileNotFoundError``
            when nothing lives there.
        """
        error = self.open_errors.get(Path(path))
        if error is not None:
            raise error
        payload = self.__payload(path)
        self.reads.append(self.name_of(path))
        handle = BytesIO(payload)
        original_read = handle.read

        def read(size: int = -1) -> bytes:
            chunk = original_read(size)
            self.bytes_read += len(chunk)
            return chunk

        handle.read = read  # pyright: ignore[reportAttributeAccessIssue]
        return handle

    def stat(self, path: Path) -> SimpleNamespace:
        """Answer a file's size.

        :param path: the file to measure.
        :returns: an object carrying ``st_size``, the one member the size scan reads.
        :raises FileNotFoundError: nothing lives at ``path``.
        """
        return SimpleNamespace(st_size=len(self.__payload(path)))

    def read_text(self, path: Path) -> str:
        """Read a file as UTF-8 text -- how the record is loaded.

        :param path: the file to read.
        :returns: its decoded contents.
        :raises FileNotFoundError: nothing lives at ``path``.
        """
        return self.__payload(path).decode("utf-8")

    def write_text(self, path: Path | str, text: str) -> None:
        """Replace a file's contents -- how the record is saved.

        :param path: the file to write.
        :param text: what to write.
        """
        self.writes += 1
        self.files[Path(path)] = text.encode("utf-8")

    # endregion

    # region Test-side conveniences

    def name_of(self, path: Path) -> str:
        """A path's record-relative, POSIX-separated name.

        :param path: a path under :data:`DIRECTORY`.
        :returns: the name a record entry would carry.
        """
        return path.relative_to(DIRECTORY).as_posix()

    def seed_record(self, entries: list[Any], version: int = 1) -> None:
        """Put a record on the disk without going through a generate.

        :param entries: the raw entries to write.
        :param version: the version to stamp, so a test can seed one from the future.
        """
        self.files[RECORD_PATH] = (json.dumps({"version": version, "files": entries}, indent=2) + "\n").encode("utf-8")

    @property
    def record(self) -> dict[str, Any]:
        """The record as it now stands on disk.

        :returns: the parsed record object.
        """
        return json.loads(self.files[RECORD_PATH].decode("utf-8"))

    @property
    def entries(self) -> dict[str, dict[str, Any]]:
        """The record's entries by name, for a test that does not care about their order.

        :returns: name to entry.
        """
        return {entry["name"]: entry for entry in self.record["files"]}

    def forget(self) -> None:
        """Clear the read counters, so a second run's reads are counted on their own."""
        self.reads = []
        self.bytes_read = 0
        self.writes = 0

    # endregion

    def __payload(self, path: Path) -> bytes:
        """One file's bytes.

        :param path: the file.
        :returns: its contents.
        :raises PermissionError: it sits under a directory that would not list -- a file behind an away
            mount is no more readable than the mount is listable.
        :raises FileNotFoundError: nothing lives at ``path``.
        """
        if any(directory in Path(path).parents for directory in self.offline_directories):
            raise PermissionError(str(path))
        payload = self.files.get(Path(path))
        if payload is None:
            raise FileNotFoundError(str(path))
        return payload


def digest_of(payload: bytes, algorithm: str = DEFAULT_CHECKSUM_ALGORITHM) -> str:
    """Hash bytes the way the record records them.

    :param payload: the bytes to hash.
    :param algorithm: which algorithm to hash under.
    :returns: the hex digest.
    """
    digest = CHECKSUM_ALGORITHMS[algorithm].new_digest()
    digest.update(payload)
    return digest.hexdigest()


def entry(  # pylint: disable=too-many-arguments
    name: str,
    payload: bytes | None = None,
    *,
    algorithm: str = DEFAULT_CHECKSUM_ALGORITHM,
    digest: str | None = None,
    verified: str | None = NOW,
    status: str = "matched",
    **extra: Any,
) -> dict[str, Any]:
    """Build a record entry, hashing ``payload`` unless a digest is given outright.

    :param name: the file's record-relative name.
    :param payload: the bytes whose hash to record; ``None`` with an explicit ``digest``.
    :param algorithm: the key the hash is recorded under.
    :param digest: the hash to record verbatim -- a corrupted or hand-edited one.
    :param verified: the stamp to record, or ``None`` to leave the entry undated.
    :param status: the verdict to record.
    :param extra: further keys, for a test about what a rewrite carries through.
    :returns: the raw entry.
    """
    built: dict[str, Any] = {"name": name}
    if digest is not None:
        built[algorithm] = digest
    elif payload is not None:
        built[algorithm] = digest_of(payload, algorithm)
    if verified is not None:
        built["verified"] = verified
    built["status"] = status
    built.update(extra)
    return built


@fixture(name="disk")
def fixture_disk(mocker: MockerFixture, freezer: FrozenDateTimeFactory) -> FakeDisk:
    """A resource holding a video, an archive in a subfolder, and its own bookkeeping.

    The bookkeeping is deliberately present -- the ``.rehu``, a screenshot, and (once written) the
    record itself -- so every test implicitly asserts that none of it is ever checksummed.

    :param mocker: pytest-mock fixture.
    :param freezer: the frozen clock, started at :data:`NOW` so a written stamp is predictable.
    :returns: the disk under the code's feet.
    """
    freezer.move_to(NOW)
    disk = FakeDisk(
        {
            "info.rehu": b'{"format_version": 2}',
            "info00.jpg": b"a screenshot",
            VIDEO: VIDEO_BYTES,
            ARCHIVE: ARCHIVE_BYTES,
        }
    )
    mocker.patch("rehuco_core.rehu_content_files.os.scandir", side_effect=disk.scandir)
    mocker.patch("rehuco_core.content_reading.shared_read_open", side_effect=disk.open)
    mocker.patch("rehuco_core.checksum_record.atomic_write_text", side_effect=disk.write_text)
    mocker.patch.object(Path, "stat", autospec=True, side_effect=lambda self, **_kwargs: disk.stat(self))
    mocker.patch.object(Path, "read_text", autospec=True, side_effect=lambda self, **_kwargs: disk.read_text(self))
    return disk


# endregion


# region Round-trip


def test_a_generate_records_the_content_and_nothing_else(disk: FakeDisk) -> None:
    """A first generate writes one entry per content file, hashed under the default algorithm.

    **Test steps:**

    * generate over a resource holding a video, an archive and its own bookkeeping
    * check the record lists exactly the two content files, with matching hashes and a fresh stamp
    """
    report = generate_checksums(INFO_PATH)

    assert set(disk.entries) == {VIDEO, ARCHIVE}
    assert disk.entries[VIDEO] == {
        "name": VIDEO,
        DEFAULT_CHECKSUM_ALGORITHM: digest_of(VIDEO_BYTES),
        "verified": NOW,
        "status": "matched",
    }
    assert report.statuses == {VIDEO: "matched", ARCHIVE: "matched"}


def test_a_generate_leaves_the_bookkeeping_out(disk: FakeDisk) -> None:
    """The record, the ``.rehu`` and the screenshots are in neither the record nor the report (#226).

    **Test steps:**

    * generate twice, so the record exists on disk for the second pass to meet
    * check no bookkeeping name appears in the record or in what either run reported
    """
    first = generate_checksums(INFO_PATH)
    second = generate_checksums(INFO_PATH)

    bookkeeping = {"info.rehu", "info00.jpg", RECORD_NAME}
    assert bookkeeping.isdisjoint(disk.entries)
    assert bookkeeping.isdisjoint(first.statuses)
    assert bookkeeping.isdisjoint(second.statuses)


def test_generate_then_verify_round_trips_clean(disk: FakeDisk) -> None:
    """Nothing has changed, so everything matches.

    **Test steps:**

    * generate, then verify with no staleness window
    * check every file came back matched and nothing was missing or unexpected
    """
    generate_checksums(INFO_PATH)
    report = verify_checksums(INFO_PATH)

    assert report.statuses == {VIDEO: "matched", ARCHIVE: "matched"}
    assert not report.unreadable
    assert set(disk.entries) == {VIDEO, ARCHIVE}


def test_a_modified_byte_is_mismatched(disk: FakeDisk) -> None:
    """A file whose bytes changed under the record comes back mismatched.

    **Test steps:**

    * generate, change one byte of the video, verify
    * check only the video is mismatched, and the record now says so
    """
    generate_checksums(INFO_PATH)
    disk.files[DIRECTORY / VIDEO] = CORRUPTED_VIDEO_BYTES

    report = verify_checksums(INFO_PATH)

    assert report.statuses == {VIDEO: "mismatched", ARCHIVE: "matched"}
    assert disk.entries[VIDEO]["status"] == "mismatched"


def test_a_mismatch_keeps_the_hash_it_failed_against(disk: FakeDisk) -> None:
    """A failed verify never re-baselines: the recorded hash is the one the file no longer has.

    **Test steps:**

    * generate, repack the archive, verify
    * check the record still holds the original hash, under a mismatched status
    """
    generate_checksums(INFO_PATH)
    disk.files[DIRECTORY / ARCHIVE] = REPACKED_BYTES

    verify_checksums(INFO_PATH)

    assert disk.entries[ARCHIVE][DEFAULT_CHECKSUM_ALGORITHM] == digest_of(ARCHIVE_BYTES)


def test_a_deleted_file_is_missing(disk: FakeDisk) -> None:
    """A file the record lists and the disk no longer holds is missing, not mismatched.

    **Test steps:**

    * generate, delete the archive, verify
    * check the archive is missing and its entry says so
    """
    generate_checksums(INFO_PATH)
    del disk.files[DIRECTORY / ARCHIVE]

    report = verify_checksums(INFO_PATH)

    assert report.statuses == {VIDEO: "matched", ARCHIVE: "missing"}
    assert disk.entries[ARCHIVE]["status"] == "missing"


def test_an_added_file_is_unexpected_and_adopted(disk: FakeDisk) -> None:
    """A content file the record does not cover is reported unexpected and recorded matched.

    ``unexpected`` is a report state, never a resting one ([[data-model#checksums]]): the sweep adopts
    the file so the next verify has something to check it against.

    **Test steps:**

    * generate, drop a new archive into the tree, verify
    * check it is reported unexpected but recorded matched under a fresh hash
    * verify again and check it now simply matches
    """
    generate_checksums(INFO_PATH)
    disk.files[DIRECTORY / "extras" / "bonus.zip"] = b"a bonus pack"

    report = verify_checksums(INFO_PATH)

    assert report.statuses["extras/bonus.zip"] == "unexpected"
    assert disk.entries["extras/bonus.zip"] == {
        "name": "extras/bonus.zip",
        DEFAULT_CHECKSUM_ALGORITHM: digest_of(b"a bonus pack"),
        "verified": NOW,
        "status": "matched",
    }
    assert verify_checksums(INFO_PATH).statuses["extras/bonus.zip"] == "matched"


def test_editing_the_bookkeeping_leaves_a_verify_clean(disk: FakeDisk) -> None:
    """A rewritten record, an edited screenshot and a new one do not disturb a verify (#226).

    **Test steps:**

    * generate, then edit the ``.rehu``, edit a screenshot and add another
    * check the verify still reports only the two content files, both matched
    """
    generate_checksums(INFO_PATH)
    disk.files[INFO_PATH] = b'{"format_version": 2, "core": {"title": "edited"}}'
    disk.files[DIRECTORY / "info00.jpg"] = b"a re-cropped screenshot"
    disk.files[DIRECTORY / "info01.png"] = b"a new screenshot"

    report = verify_checksums(INFO_PATH)

    assert report.statuses == {VIDEO: "matched", ARCHIVE: "matched"}


def test_a_thumbs_db_appearing_leaves_a_verify_clean(disk: FakeDisk) -> None:
    """Junk a Windows browse drops into the directory is never reported unexpected (#226).

    **Test steps:**

    * generate, then let a ``Thumbs.db`` appear in the root and in the subfolder
    * check the verify reports neither
    """
    generate_checksums(INFO_PATH)
    disk.files[DIRECTORY / "Thumbs.db"] = b"a thumbnail cache"
    disk.files[DIRECTORY / "extras" / "thumbs.db"] = b"a lower-cased one, from a share"

    report = verify_checksums(INFO_PATH)

    assert report.statuses == {VIDEO: "matched", ARCHIVE: "matched"}


# endregion


# region Staleness and force


def test_a_second_verify_inside_the_window_reads_nothing(disk: FakeDisk, freezer: FrozenDateTimeFactory) -> None:
    """Everything checked yesterday is skipped today, at the cost of zero bytes.

    **Test steps:**

    * generate, move the clock on by a day, verify with a week's window
    * check every file was skipped, nothing was read, and the record was not rewritten
    """
    generate_checksums(INFO_PATH)
    freezer.move_to(LATER)
    disk.forget()

    report = verify_checksums(INFO_PATH, stale_after=WEEK)

    assert set(report.skipped) == {VIDEO, ARCHIVE}
    assert not report.statuses
    assert disk.reads == []
    assert disk.bytes_read == 0
    assert disk.writes == 0


def test_a_verify_past_the_window_reads_everything_again(disk: FakeDisk, freezer: FrozenDateTimeFactory) -> None:
    """Once the window has passed, the same call re-reads.

    **Test steps:**

    * generate, move the clock on by a month, verify with a week's window
    * check nothing was skipped and both files were read
    """
    generate_checksums(INFO_PATH)
    freezer.move_to(MUCH_LATER)
    disk.forget()

    report = verify_checksums(INFO_PATH, stale_after=WEEK)

    assert not report.skipped
    assert sorted(disk.reads) == sorted([VIDEO, ARCHIVE])
    assert disk.entries[VIDEO]["verified"] == MUCH_LATER


def test_no_window_is_how_force_is_expressed(disk: FakeDisk, freezer: FrozenDateTimeFactory) -> None:
    """``stale_after=None`` re-reads what a window would have skipped -- there is no separate force flag.

    **Test steps:**

    * generate, move the clock on by a day, verify with no window at all
    * check nothing was skipped and every byte was read again
    """
    generate_checksums(INFO_PATH)
    freezer.move_to(LATER)
    disk.forget()

    report = verify_checksums(INFO_PATH, stale_after=None)

    assert not report.skipped
    assert disk.bytes_read == len(VIDEO_BYTES) + len(ARCHIVE_BYTES)


def test_a_generate_inside_the_window_skips_what_was_hashed_recently(
    disk: FakeDisk, freezer: FrozenDateTimeFactory
) -> None:
    """The window means the same thing in both halves: a fresh entry is not re-hashed by a generate.

    **Test steps:**

    * generate, move the clock on by a day, generate again with a week's window
    * check both files were skipped and nothing was read
    """
    generate_checksums(INFO_PATH)
    freezer.move_to(LATER)
    disk.forget()

    report = generate_checksums(INFO_PATH, stale_after=WEEK)

    assert set(report.skipped) == {VIDEO, ARCHIVE}
    assert disk.reads == []
    assert disk.entries[VIDEO]["verified"] == NOW


def test_a_targeted_generate_inside_the_window_skips_too(disk: FakeDisk, freezer: FrozenDateTimeFactory) -> None:
    """A named entry that was hashed recently is left alone as readily as an unnamed one.

    **Test steps:**

    * generate, move the clock on by a day, generate naming the video with a week's window
    * check it was skipped rather than re-hashed
    """
    generate_checksums(INFO_PATH)
    freezer.move_to(LATER)
    disk.forget()

    report = generate_checksums(INFO_PATH, only=[VIDEO], stale_after=WEEK)

    assert report.skipped == (VIDEO,)
    assert disk.reads == []


def test_an_unreadable_date_reads_as_never_verified(disk: FakeDisk) -> None:
    """A stamp this build cannot parse costs a re-check, never the entry's hash.

    **Test steps:**

    * seed an entry whose ``verified`` is nonsense, verify inside a wide window
    * check it was read rather than skipped, and came back matched
    """
    disk.seed_record([entry(VIDEO, VIDEO_BYTES, verified="last Tuesday")])

    report = verify_checksums(INFO_PATH, only=[VIDEO], stale_after=WEEK)

    assert not report.skipped
    assert report.statuses == {VIDEO: "matched"}


# endregion


# region Migration


def test_migrating_a_matched_entry_replaces_its_algorithm(disk: FakeDisk) -> None:
    """A crc32 entry verified with ``migrate_to="xxh3"`` comes back holding only an xxh3 key.

    **Test steps:**

    * seed a crc32 entry over an untouched file, verify migrating to xxh3
    * check the entry matched, now holds the xxh3 hash, and no longer holds a crc32 one
    """
    disk.seed_record([entry(VIDEO, VIDEO_BYTES, algorithm="crc32")])

    report = verify_checksums(INFO_PATH, only=[VIDEO], migrate_to="xxh3")

    assert report.statuses == {VIDEO: "matched"}
    assert disk.entries[VIDEO] == {
        "name": VIDEO,
        "xxh3": digest_of(VIDEO_BYTES, "xxh3"),
        "verified": NOW,
        "status": "matched",
    }


def test_migrating_reads_the_file_once(disk: FakeDisk) -> None:
    """Both digests are fed from one pass, so migration costs no extra read (#203).

    **Test steps:**

    * seed a crc32 entry, verify migrating to xxh3
    * check the file was opened once and exactly its own length was read
    """
    disk.seed_record([entry(VIDEO, VIDEO_BYTES, algorithm="crc32")])

    verify_checksums(INFO_PATH, only=[VIDEO], migrate_to="xxh3")

    assert disk.reads == [VIDEO]
    assert disk.bytes_read == len(VIDEO_BYTES)


def test_migrating_a_corrupted_file_discards_the_new_hash(disk: FakeDisk) -> None:
    """A file that fails its recorded algorithm keeps that algorithm and gains no new hash.

    Blessing bad bytes under a new name would launder corruption into a record that then looks clean
    forever ([[data-model#checksums]], #203).

    **Test steps:**

    * seed a crc32 entry whose file has since changed, verify migrating to xxh3
    * check the entry is mismatched, still crc32, still holding the hash it failed against, and that
      no xxh3 key was written
    """
    stale = digest_of(ARCHIVE_BYTES, "crc32")
    disk.seed_record([entry(ARCHIVE, algorithm="crc32", digest=stale)])
    disk.files[DIRECTORY / ARCHIVE] = REPACKED_BYTES

    report = verify_checksums(INFO_PATH, only=[ARCHIVE], migrate_to="xxh3")

    assert report.statuses == {ARCHIVE: "mismatched"}
    assert disk.entries[ARCHIVE] == {
        "name": ARCHIVE,
        "crc32": stale,
        "verified": NOW,
        "status": "mismatched",
    }


def test_an_entry_already_on_the_target_algorithm_is_left_alone(disk: FakeDisk) -> None:
    """Migrating to the algorithm an entry already carries is a plain verify.

    **Test steps:**

    * seed an xxh3 entry, verify migrating to xxh3
    * check it matched under the same key, having been read once
    """
    disk.seed_record([entry(VIDEO, VIDEO_BYTES, algorithm="xxh3")])

    report = verify_checksums(INFO_PATH, only=[VIDEO], migrate_to="xxh3")

    assert report.statuses == {VIDEO: "matched"}
    assert disk.entries[VIDEO]["xxh3"] == digest_of(VIDEO_BYTES, "xxh3")
    assert disk.reads == [VIDEO]


def test_entries_on_different_algorithms_verify_side_by_side(disk: FakeDisk) -> None:
    """The algorithm is genuinely per entry, so a mixed record needs no migration to be checked.

    **Test steps:**

    * seed one crc32 entry and one xxh3 entry, verify without migrating
    * check both matched and both kept their own key
    """
    disk.seed_record(
        [
            entry(VIDEO, VIDEO_BYTES, algorithm="crc32"),
            entry(ARCHIVE, ARCHIVE_BYTES, algorithm="xxh3"),
        ]
    )

    report = verify_checksums(INFO_PATH)

    assert report.statuses == {VIDEO: "matched", ARCHIVE: "matched"}
    assert "crc32" in disk.entries[VIDEO]
    assert "xxh3" in disk.entries[ARCHIVE]


# endregion


# region Accepting a change


def test_a_targeted_generate_re_baselines_only_what_it_names(disk: FakeDisk, freezer: FrozenDateTimeFactory) -> None:
    """The accept-a-change loop: verify, then re-baseline just the file whose change was genuine.

    **Test steps:**

    * generate, repack the archive and corrupt the video, verify -- both come back mismatched
    * generate naming only the archive
    * check the archive is freshly hashed and dated, and the video's entry is untouched, mismatch and
      original hash included
    * check the archive was the only file read
    """
    generate_checksums(INFO_PATH)
    disk.files[DIRECTORY / ARCHIVE] = REPACKED_BYTES
    disk.files[DIRECTORY / VIDEO] = CORRUPTED_VIDEO_BYTES
    assert verify_checksums(INFO_PATH).statuses == {VIDEO: "mismatched", ARCHIVE: "mismatched"}
    freezer.move_to(LATER)
    disk.forget()

    report = generate_checksums(INFO_PATH, only=[ARCHIVE])

    assert report.statuses == {ARCHIVE: "matched"}
    assert disk.entries[ARCHIVE] == {
        "name": ARCHIVE,
        DEFAULT_CHECKSUM_ALGORITHM: digest_of(REPACKED_BYTES),
        "verified": LATER,
        "status": "matched",
    }
    assert disk.entries[VIDEO] == {
        "name": VIDEO,
        DEFAULT_CHECKSUM_ALGORITHM: digest_of(VIDEO_BYTES),
        "verified": NOW,
        "status": "mismatched",
    }
    assert disk.reads == [ARCHIVE]


def test_a_targeted_generate_re_baselines_under_the_configured_algorithm(disk: FakeDisk) -> None:
    """Whatever an entry carried before, a re-baseline records it the way this run was told to.

    **Test steps:**

    * seed a crc32 entry, generate naming it with xxh3 configured
    * check it now holds only an xxh3 hash
    """
    disk.seed_record([entry(VIDEO, VIDEO_BYTES, algorithm="crc32")])

    generate_checksums(INFO_PATH, only=[VIDEO], algorithm="xxh3")

    assert disk.entries[VIDEO] == {
        "name": VIDEO,
        "xxh3": digest_of(VIDEO_BYTES, "xxh3"),
        "verified": NOW,
        "status": "matched",
    }


def test_a_targeted_generate_names_a_file_that_is_not_there(disk: FakeDisk) -> None:
    """Naming something the disk does not hold answers missing rather than doing nothing.

    **Test steps:**

    * generate, then generate naming a file that does not exist
    * check it is reported missing and gained no entry
    """
    generate_checksums(INFO_PATH)

    report = generate_checksums(INFO_PATH, only=["extras/ghost.zip"])

    assert report.statuses == {"extras/ghost.zip": "missing"}
    assert "extras/ghost.zip" not in disk.entries


def test_a_targeted_generate_adopts_a_file_the_record_never_held(disk: FakeDisk) -> None:
    """Naming a content file the record does not cover records it, rather than refusing.

    **Test steps:**

    * generate, drop a new archive into the tree, generate naming only it
    * check it gained an entry and the files already recorded were not read again
    """
    generate_checksums(INFO_PATH)
    disk.files[DIRECTORY / "extras" / "bonus.zip"] = b"a bonus pack"
    disk.forget()

    report = generate_checksums(INFO_PATH, only=["extras/bonus.zip"])

    assert report.statuses == {"extras/bonus.zip": "matched"}
    assert disk.entries["extras/bonus.zip"][DEFAULT_CHECKSUM_ALGORITHM] == digest_of(b"a bonus pack")
    assert disk.reads == ["extras/bonus.zip"]


def test_a_first_baseline_carries_on_past_a_file_it_cannot_read(disk: FakeDisk) -> None:
    """One unreadable file costs its own entry, never the rest of the baseline.

    **Test steps:**

    * generate from nothing, with the first file in the walk refusing to open
    * check it is reported unreadable, gained no entry, and the other file was still recorded
    """
    disk.open_errors[DIRECTORY / ARCHIVE] = PermissionError(ARCHIVE)

    report = generate_checksums(INFO_PATH)

    assert report.unreadable == (ARCHIVE,)
    assert set(disk.entries) == {VIDEO}


def test_a_full_generate_drops_what_is_gone(disk: FakeDisk) -> None:
    """A baseline describes what *is*, so a deleted file's entry does not survive it.

    **Test steps:**

    * generate, delete the archive, generate again
    * check the record now lists the video alone
    """
    generate_checksums(INFO_PATH)
    del disk.files[DIRECTORY / ARCHIVE]

    generate_checksums(INFO_PATH)

    assert set(disk.entries) == {VIDEO}


def test_a_verify_naming_one_file_leaves_the_rest_alone(disk: FakeDisk, freezer: FrozenDateTimeFactory) -> None:
    """The selection means the same thing in both halves: named entries are checked, others untouched.

    **Test steps:**

    * generate, move the clock on, verify naming only the video
    * check only the video was read and only its entry was re-dated
    """
    generate_checksums(INFO_PATH)
    freezer.move_to(LATER)
    disk.forget()

    report = verify_checksums(INFO_PATH, only=[VIDEO])

    assert report.statuses == {VIDEO: "matched"}
    assert disk.reads == [VIDEO]
    assert disk.entries[VIDEO]["verified"] == LATER
    assert disk.entries[ARCHIVE]["verified"] == NOW


# endregion


# region Malformed entries


@mark.parametrize(
    ("broken", "reason"),
    [
        ({"name": VIDEO, "xxh3": "not hex at all!"}, "a hash that is not hex"),
        ({"name": VIDEO, "xxh3": "abc"}, "a hash of the wrong length"),
        ({"name": VIDEO, "xxh3": "z" * 16}, "the right length, but not hex"),
        ({"name": VIDEO, "xxh3": digest_of(VIDEO_BYTES), "crc32": "42342424"}, "two hash keys at once"),
        ({"name": VIDEO, "blake3": "42342424"}, "an algorithm this build does not know"),
        ({"name": VIDEO, "sha1": "a" * 40}, "an algorithm this build used to ship"),
        ({"name": VIDEO, "xxh3": 42}, "a hash that is not a string"),
    ],
)
def test_an_unreadable_entry_is_reported_not_crashed_on(disk: FakeDisk, broken: dict[str, Any], reason: str) -> None:
    """An entry this build cannot read costs itself and its neighbours still verify (#203).

    **Test steps:**

    * seed a record holding one broken entry beside one good one, and verify
    * check the broken entry is reported malformed and carried through byte-for-byte
    * check its neighbour was still checked
    """
    del reason  # named in the parametrization so a failure says which shape broke
    disk.seed_record([broken, entry(ARCHIVE, ARCHIVE_BYTES)])

    report = verify_checksums(INFO_PATH)

    assert report.statuses[VIDEO] == "malformed"
    assert report.statuses[ARCHIVE] == "matched"
    assert disk.entries[VIDEO] == broken


def test_an_entry_with_no_readable_name_is_counted(disk: FakeDisk) -> None:
    """An entry that cannot even be named is reportable only as a count.

    **Test steps:**

    * seed entries with a missing, an empty, an escaping and a Windows-shaped name, beside a good one
    * check all four are counted and survive the write, and the good one still verified
    * check the video the nameless entry meant to cover is adopted -- an entry nobody can read is an
      entry that claims no file, so the file it was about is simply uncovered
    """
    broken: list[Any] = [
        {"xxh3": digest_of(VIDEO_BYTES)},
        {"name": ""},
        {"name": "../../elsewhere/secrets.zip"},
        {"name": "extras\\pack.zip"},
    ]
    disk.seed_record([*broken, entry(ARCHIVE, ARCHIVE_BYTES)])

    report = verify_checksums(INFO_PATH)

    assert report.unnamed_malformed == 4
    assert report.statuses == {ARCHIVE: "matched", VIDEO: "unexpected"}
    assert disk.record["files"][:4] == broken


def test_a_targeted_generate_repairs_an_unreadable_entry(disk: FakeDisk) -> None:
    """A broken entry with a readable name is still selectable, which is how it gets fixed.

    **Test steps:**

    * seed a record whose video entry holds a corrupted hash, generate naming that file
    * check the entry is now a well-formed fresh baseline
    """
    disk.seed_record([{"name": VIDEO, "xxh3": "not hex at all!"}, entry(ARCHIVE, ARCHIVE_BYTES)])

    generate_checksums(INFO_PATH, only=[VIDEO])

    assert disk.entries[VIDEO] == {
        "name": VIDEO,
        DEFAULT_CHECKSUM_ALGORITHM: digest_of(VIDEO_BYTES),
        "verified": NOW,
        "status": "matched",
    }


def test_a_rewrite_carries_keys_it_does_not_understand(disk: FakeDisk) -> None:
    """An annotation another build left on an entry survives this one's verify.

    **Test steps:**

    * seed an entry carrying an extra key, verify
    * check the key is still there, beside a freshly written verdict
    """
    disk.seed_record([entry(VIDEO, VIDEO_BYTES, note="checked on the node")])

    verify_checksums(INFO_PATH, only=[VIDEO])

    assert disk.entries[VIDEO]["note"] == "checked on the node"
    assert disk.entries[VIDEO]["status"] == "matched"


# endregion


# region Files that cannot be read


def test_a_file_that_cannot_be_read_is_not_a_verdict(disk: FakeDisk) -> None:
    """A share that refuses a file says nothing about its bytes, so its entry is left alone.

    Deliberately not ``missing``: the file is there, and recording a verdict about bytes nobody read
    is what an I/O failure must never produce ([[mounts-and-storage#offline-mounts]]).

    **Test steps:**

    * generate, then make the video refuse to open, and verify
    * check it is reported unreadable rather than given a status, and its entry still says matched
    """
    generate_checksums(INFO_PATH)
    disk.open_errors[DIRECTORY / VIDEO] = PermissionError(VIDEO)

    report = verify_checksums(INFO_PATH)

    assert report.unreadable == (VIDEO,)
    assert report.statuses == {ARCHIVE: "matched"}
    assert disk.entries[VIDEO]["verified"] == NOW


def test_a_file_that_cannot_be_read_keeps_its_entry_through_a_generate(disk: FakeDisk) -> None:
    """A re-baseline cannot baseline what it cannot read, so it leaves the old entry standing.

    **Test steps:**

    * generate, then make the video refuse to open, and generate again
    * check it is reported unreadable and its original entry survived
    """
    generate_checksums(INFO_PATH)
    disk.open_errors[DIRECTORY / VIDEO] = PermissionError(VIDEO)

    report = generate_checksums(INFO_PATH)

    assert report.unreadable == (VIDEO,)
    assert disk.entries[VIDEO][DEFAULT_CHECKSUM_ALGORITHM] == digest_of(VIDEO_BYTES)


def test_a_listed_but_unhashed_file_that_is_gone_is_missing(disk: FakeDisk) -> None:
    """A resting ``unexpected`` whose file has since gone is missing, and gains no hash.

    **Test steps:**

    * seed an entry with a name, no hash and no file behind it, and verify
    * check it is missing and its entry still carries no hash
    """
    disk.seed_record([{"name": "extras/ghost.zip", "status": "unexpected"}])

    report = verify_checksums(INFO_PATH, only=["extras/ghost.zip"])

    assert report.statuses == {"extras/ghost.zip": "missing"}
    assert disk.entries["extras/ghost.zip"] == {
        "name": "extras/ghost.zip",
        "verified": NOW,
        "status": "missing",
    }


def test_a_listed_but_unhashed_file_that_cannot_be_read_is_left_alone(disk: FakeDisk) -> None:
    """The same entry over a file that refuses to open is carried through untouched.

    **Test steps:**

    * seed a hash-less entry over a file that refuses to open, and verify
    * check it is reported unreadable and the entry is exactly as it was
    """
    resting = {"name": VIDEO, "status": "unexpected"}
    disk.seed_record([resting])
    disk.open_errors[DIRECTORY / VIDEO] = PermissionError(VIDEO)

    report = verify_checksums(INFO_PATH, only=[VIDEO])

    assert report.unreadable == (VIDEO,)
    assert disk.entries[VIDEO] == resting


def test_a_file_that_vanishes_before_it_is_read_is_not_adopted(disk: FakeDisk) -> None:
    """A file listed by the scan and gone by the read is nothing at all, not an unexpected one.

    **Test steps:**

    * verify from nothing, with the video vanishing between the enumeration and the read
    * check it is neither reported nor recorded, and the archive still was
    """
    disk.open_errors[DIRECTORY / VIDEO] = FileNotFoundError(VIDEO)

    report = verify_checksums(INFO_PATH, create_if_missing=True)

    assert report.statuses == {ARCHIVE: "unexpected"}
    assert set(disk.entries) == {ARCHIVE}


def test_an_adopted_file_that_cannot_be_read_rests_unexpected(disk: FakeDisk) -> None:
    """An unlisted file that refuses to open is recorded by name alone, to be hashed another day.

    **Test steps:**

    * verify from nothing, with the video refusing to open
    * check it is reported unexpected and recorded with a name, a status and no hash
    """
    disk.open_errors[DIRECTORY / VIDEO] = PermissionError(VIDEO)

    report = verify_checksums(INFO_PATH, create_if_missing=True)

    assert report.statuses[VIDEO] == "unexpected"
    assert disk.entries[VIDEO] == {"name": VIDEO, "status": "unexpected"}


# endregion


# region Resources that cannot be reached


def test_a_verify_over_an_unreachable_resource_refuses_rather_than_reporting_clean(disk: FakeDisk) -> None:
    """An away mount used to verify clean: nothing read, nothing reported, indistinguishable from a
    resource whose every file was checked a moment ago (#245).

    **Test steps:**

    * generate a record, then take the resource's own directory offline
    * verify with ``create_if_missing`` off, and again with it on
    * check both refuse, naming the directory rather than the record
    """
    generate_checksums(INFO_PATH)
    disk.offline_directories.add(DIRECTORY)

    for create_if_missing in (False, True):
        with raises(ContentUnreachableError, match=re.escape(str(DIRECTORY))):
            verify_checksums(INFO_PATH, create_if_missing=create_if_missing)


def test_a_generate_over_an_unreachable_resource_refuses_rather_than_baselining_nothing(
    disk: FakeDisk,
) -> None:
    """The other half of the same answer: a baseline over a resource nobody can list is not an empty
    baseline (#245).

    **Test steps:**

    * take the resource's own directory offline
    * generate
    * check it refused, and wrote no record
    """
    disk.offline_directories.add(DIRECTORY)

    with raises(ContentUnreachableError, match=re.escape(str(DIRECTORY))):
        generate_checksums(INFO_PATH)

    assert RECORD_PATH not in disk.files


def test_an_unreachable_resource_is_refused_before_the_record_is_looked_for(disk: FakeDisk) -> None:
    """*The mount is away* outranks *this resource has no checksums*, which is what a
    ``FileNotFoundError`` naming ``info.checksum`` said about a resource that may well have one (#245).

    **Test steps:**

    * take the directory offline, with no record ever written
    * verify with ``create_if_missing`` off, which is the call that used to raise ``FileNotFoundError``
    * check what came back is the unreachable-resource refusal, and names no record
    """
    disk.offline_directories.add(DIRECTORY)

    with raises(ContentUnreachableError) as refusal:
        verify_checksums(INFO_PATH)

    assert RECORD_NAME not in str(refusal.value)


def test_a_full_generate_keeps_the_entries_under_a_branch_it_could_not_list(disk: FakeDisk) -> None:
    """The data loss this issue is about: a full baseline used to drop ``extras/pack.zip`` -- the only
    description of what that file was supposed to be -- because a directory would not list (#245).

    **Test steps:**

    * generate over both files, then take the archive's branch offline
    * generate again, over everything
    * check the video was re-baselined, the archive's entry survived untouched, and both the branch and
      the entry under it were reported
    """
    generate_checksums(INFO_PATH)
    recorded = disk.entries[ARCHIVE]
    disk.offline_directories.add(DIRECTORY / "extras")

    report = generate_checksums(INFO_PATH)

    assert disk.entries[ARCHIVE] == recorded
    assert report.statuses == {VIDEO: "matched"}
    assert report.unreadable == (ARCHIVE,)
    assert report.unreadable_directories == ("extras",)


def test_a_generate_over_a_partly_unreadable_tree_says_so_with_nothing_recorded_under_it(
    disk: FakeDisk,
) -> None:
    """A branch with no entries under it has nothing to carry, and still must not read as a clean run:
    the files behind it are simply not in the baseline anybody reads afterwards (#245).

    **Test steps:**

    * take the archive's branch offline before any record exists
    * generate
    * check the video was baselined, nothing was recorded for the branch, and the branch was reported
    """
    disk.offline_directories.add(DIRECTORY / "extras")

    report = generate_checksums(INFO_PATH)

    assert set(disk.entries) == {VIDEO}
    assert not report.unreadable
    assert report.unreadable_directories == ("extras",)


def test_a_verify_still_checks_what_the_record_lists_under_an_offline_branch(disk: FakeDisk) -> None:
    """Verify's saving property, kept: it checks what the record lists rather than what a walk finds, so
    an offline branch costs a verdict rather than an entry ([[data-model#checksums]]).

    **Test steps:**

    * generate over both files, then take the archive's branch offline
    * verify
    * check the video matched, the archive is unreadable rather than missing, and its entry stands
    """
    generate_checksums(INFO_PATH)
    recorded = disk.entries[ARCHIVE]
    disk.offline_directories.add(DIRECTORY / "extras")

    report = verify_checksums(INFO_PATH)

    assert report.statuses == {VIDEO: "matched"}
    assert report.unreadable == (ARCHIVE,)
    assert report.unreadable_directories == ("extras",)
    assert disk.entries[ARCHIVE] == recorded


def test_a_run_over_a_readable_tree_reports_no_unreadable_directories(disk: FakeDisk) -> None:
    """The resting state of the new report member, so *nothing unread* keeps meaning something.

    **Test steps:**

    * generate, then verify, over an entirely readable resource
    * check neither run named an unreadable directory
    """
    assert not generate_checksums(INFO_PATH).unreadable_directories
    assert not verify_checksums(INFO_PATH).unreadable_directories
    assert set(disk.entries) == {VIDEO, ARCHIVE}


def test_the_size_scan_refuses_the_same_tree_the_checksums_carry_entries_over(disk: FakeDisk) -> None:
    """The two callers of the one enumeration (#226) must not drift: over the same offline branch a
    checksum run carries and reports, while a size refuses outright, and both answers are deliberate --
    a record entry is a description that survives, a size is a number that would simply be wrong (#245).

    **Test steps:**

    * take the archive's branch offline
    * measure the size on disk, and generate
    * check the size refused naming the branch, and the generate reported the same branch
    """
    disk.offline_directories.add(DIRECTORY / "extras")

    with raises(ContentUnreachableError, match="extras"):
        content_size_on_disk(INFO_PATH)

    assert generate_checksums(INFO_PATH).unreadable_directories == ("extras",)


# endregion


# region Cancellation and progress


def test_a_cancelled_verify_writes_nothing(disk: FakeDisk) -> None:
    """A stop leaves through the checkpoint with the previous record intact (#203).

    **Test steps:**

    * corrupt the video, then verify with a checkpoint that raises on its third call
    * check the exception travelled out untouched and the record was never rewritten
    """

    class Stop(Exception):
        """What the caller's checkpoint raises -- a stand-in for ``JobCancelled``."""

    calls = 0

    def checkpoint() -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise Stop

    generate_checksums(INFO_PATH)
    disk.files[DIRECTORY / VIDEO] = CORRUPTED_VIDEO_BYTES
    before = disk.record
    disk.forget()

    with raises(Stop):
        verify_checksums(INFO_PATH, checkpoint=checkpoint)

    assert disk.writes == 0
    assert disk.record == before


def test_a_cancelled_verify_reports_no_verdict_it_did_not_establish(disk: FakeDisk) -> None:
    """A stop part-way can never manufacture a mismatch: no verdict exists until a whole file is hashed.

    **Test steps:**

    * verify with a checkpoint that raises immediately
    * check nothing was read to the end and the record still holds the verdicts the generate wrote
    """

    class Stop(Exception):
        """What the caller's checkpoint raises."""

    generate_checksums(INFO_PATH)
    disk.forget()

    with raises(Stop):
        verify_checksums(INFO_PATH, checkpoint=lambda: (_ for _ in ()).throw(Stop()))

    assert disk.bytes_read == 0
    assert {name: found["status"] for name, found in disk.entries.items()} == {
        VIDEO: "matched",
        ARCHIVE: "matched",
    }


def test_progress_counts_bytes_not_files(disk: FakeDisk) -> None:
    """A bar over three eight-gigabyte videos has to say more than *one of three*.

    **Test steps:**

    * generate with a progress callback
    * check the total is the content's size in bytes, reported before the first slow read
    * check the intermediate figure is the first file's **length**, not a file count
    """
    del disk
    reports: list[tuple[int, int | None]] = []

    generate_checksums(INFO_PATH, progress=lambda done, total: reports.append((done, total)))

    content = len(VIDEO_BYTES) + len(ARCHIVE_BYTES)
    assert [total for _, total in reports] == [content] * len(reports)
    assert [done for done, _ in reports] == [0, len(ARCHIVE_BYTES), content]


# endregion


# region The record itself


def test_a_verify_without_a_record_refuses_by_default(disk: FakeDisk) -> None:
    """Verifying against a record that does not exist is a mistake worth hearing about.

    **Test steps:**

    * verify a resource that has never been generated
    * check it raises rather than reporting every file as unexpected
    """
    del disk
    with raises(FileNotFoundError):
        verify_checksums(INFO_PATH)


def test_a_verify_may_be_told_to_start_from_nothing(disk: FakeDisk) -> None:
    """``create_if_missing`` is how a sweep says *adopt everything here*.

    **Test steps:**

    * verify a resource that has never been generated, allowing the record to be created
    * check every content file was reported unexpected and recorded matched
    """
    report = verify_checksums(INFO_PATH, create_if_missing=True)

    assert report.statuses == {VIDEO: "unexpected", ARCHIVE: "unexpected"}
    assert set(disk.entries) == {VIDEO, ARCHIVE}


def test_a_record_this_build_cannot_read_is_refused_whole(disk: FakeDisk) -> None:
    """A file that is not a record at all is reported as one thing, never half-trusted.

    **Test steps:**

    * put text that is not JSON where the record belongs, and verify
    * check it is refused
    """
    disk.files[RECORD_PATH] = b"not a record at all"

    with raises(ChecksumRecordError):
        verify_checksums(INFO_PATH)


@mark.parametrize(
    ("content", "shape"),
    [
        (b"\xff\xfe not text at all", "not text"),
        (b"[]", "JSON, but not an object"),
        (b'{"version": 1, "files": {"lesson1.mp4": "42342424"}}', "an object where the entries belong"),
    ],
)
def test_a_record_of_the_wrong_shape_is_refused_whole(disk: FakeDisk, content: bytes, shape: str) -> None:
    """A file that is not a record is reported as one thing, never half-trusted.

    **Test steps:**

    * put each wrong shape where the record belongs, and verify
    """
    del shape  # named in the parametrization so a failure says which shape got through
    disk.files[RECORD_PATH] = content

    with raises(ChecksumRecordError):
        verify_checksums(INFO_PATH)


def test_a_duplicate_name_is_baselined_once(disk: FakeDisk) -> None:
    """A record listing the same file twice becomes a record listing it once.

    **Test steps:**

    * seed a record holding two entries for the video, and generate
    * check the new baseline holds one entry per file
    """
    disk.seed_record([entry(VIDEO, VIDEO_BYTES), entry(VIDEO, VIDEO_BYTES, status="mismatched")])

    generate_checksums(INFO_PATH)

    assert [found["name"] for found in disk.record["files"]] == [ARCHIVE, VIDEO]


def test_a_targeted_generate_collapses_a_duplicated_name(disk: FakeDisk) -> None:
    """Re-baselining a name leaves exactly one entry for it, however many a hand-edit left.

    The dropped duplicate would otherwise carry a stale hash the re-baseline just declared wrong, and
    fail every verify after it.

    **Test steps:**

    * seed two entries for the video -- both wrong -- and generate naming it
    * check the record holds one fresh entry for the video, beside the untouched archive entry
    """
    disk.seed_record(
        [
            entry(VIDEO, algorithm="xxh3", digest="0" * 16, status="mismatched"),
            entry(VIDEO, algorithm="crc32", digest="1" * 8, status="mismatched"),
            entry(ARCHIVE, ARCHIVE_BYTES),
        ]
    )

    generate_checksums(INFO_PATH, only=[VIDEO])

    assert [found["name"] for found in disk.record["files"]] == [VIDEO, ARCHIVE]
    assert disk.entries[VIDEO] == {
        "name": VIDEO,
        DEFAULT_CHECKSUM_ALGORITHM: digest_of(VIDEO_BYTES),
        "verified": NOW,
        "status": "matched",
    }


def test_a_rewrite_carries_record_keys_it_does_not_understand(disk: FakeDisk) -> None:
    """A top-level key another build left on the record survives this one's rewrite.

    The same round-trip discipline the entries get, one level up -- and the canonical layout holds:
    the stamp leads, the carried key keeps its place, the entry list trails.

    **Test steps:**

    * write a record carrying an unknown top-level key, then verify with the video corrupted -- so the
      record is genuinely rewritten
    * check the key survived, and the layout is version, the carried key, files
    """
    record = {"version": 1, "note": "left by another build", "files": [entry(VIDEO, VIDEO_BYTES)]}
    disk.files[RECORD_PATH] = (json.dumps(record) + "\n").encode("utf-8")
    disk.files[DIRECTORY / VIDEO] = CORRUPTED_VIDEO_BYTES

    verify_checksums(INFO_PATH, only=[VIDEO])

    assert disk.record["note"] == "left by another build"
    assert list(disk.record) == ["version", "note", "files"]
    assert disk.entries[VIDEO]["status"] == "mismatched"


def test_a_verify_naming_something_the_record_never_held(disk: FakeDisk) -> None:
    """A name in neither the record nor the directory answers missing rather than silently nothing.

    **Test steps:**

    * generate, then verify naming a file that does not exist
    * check it is reported missing and nothing was read
    """
    generate_checksums(INFO_PATH)
    disk.forget()

    report = verify_checksums(INFO_PATH, only=["extras/ghost.zip"])

    assert report.statuses == {"extras/ghost.zip": "missing"}
    assert disk.reads == []


def test_a_record_from_the_future_is_refused(disk: FakeDisk) -> None:
    """A record a later build wrote is refused rather than read through this build's assumptions.

    **Test steps:**

    * seed a record stamped one version above what this build understands, and verify
    * check it is refused
    """
    disk.seed_record([entry(VIDEO, VIDEO_BYTES)], version=99)

    with raises(ChecksumRecordError):
        verify_checksums(INFO_PATH)


def test_an_unstamped_record_reads_as_version_one(disk: FakeDisk) -> None:
    """Version 1 is the first shape there has ever been, so a missing stamp is read as one.

    **Test steps:**

    * write a record with no ``version`` key and an undated entry, and verify
    * check it was read, and is stamped on the way back out
    """
    unstamped = {"files": [entry(VIDEO, VIDEO_BYTES, verified=None)]}
    disk.files[RECORD_PATH] = (json.dumps(unstamped) + "\n").encode("utf-8")

    report = verify_checksums(INFO_PATH, only=[VIDEO])

    assert report.statuses == {VIDEO: "matched"}
    assert disk.record["version"] == 1


def test_a_run_that_changes_nothing_leaves_the_file_alone(disk: FakeDisk) -> None:
    """A verify whose every entry comes back identical does not rewrite the record.

    A run that established nothing new has nothing to say, and this catalog lives on an SMB mount
    ([[packaging-deployment#ts230-as-nas]]) where a write is a real round trip. The consequence worth
    knowing: a record whose *shape* was brought up to date on load and whose entries then came back
    identical stays on disk in the shape it was read in, until something genuine changes it.

    **Test steps:**

    * seed a record whose entries are exactly what a verify would write, and verify
    * check every file was still read, and the record was not written
    """
    disk.seed_record([entry(VIDEO, VIDEO_BYTES), entry(ARCHIVE, ARCHIVE_BYTES)])
    disk.forget()

    report = verify_checksums(INFO_PATH)

    assert report.statuses == {VIDEO: "matched", ARCHIVE: "matched"}
    assert sorted(disk.reads) == sorted([VIDEO, ARCHIVE])
    assert disk.writes == 0


def test_the_record_sits_beside_the_rehu(disk: FakeDisk) -> None:
    """``info.rehu`` -> ``info.checksum``, ``foo.rehu`` -> ``foo.checksum``.

    **Test steps:**

    * ask where two resources' records live
    """
    del disk
    assert checksum_record_path(INFO_PATH) == RECORD_PATH
    assert checksum_record_path(DIRECTORY / "foo.rehu") == DIRECTORY / "foo.checksum"


def test_an_unknown_algorithm_is_refused_before_anything_is_read(disk: FakeDisk) -> None:
    """A run is told what it cannot do before it costs a single byte.

    **Test steps:**

    * generate under an algorithm this build does not ship
    * check it raises and nothing was read
    """
    with raises(ValueError):
        generate_checksums(INFO_PATH, algorithm="blake3")

    assert disk.reads == []


# endregion


# region Entry parsing


@mark.parametrize(
    "name",
    ["", "..", "../secrets.zip", "extras/../../secrets.zip", "/absolute/secrets.zip", "C:/secrets.zip", "a\\b.zip"],
)
def test_a_name_that_could_reach_outside_the_resource_is_refused(name: str) -> None:
    """A record entry names a file *inside* the resource, and anything else is refused outright.

    **Test steps:**

    * read the name of an entry spelling an escape, an absolute path or a Windows separator
    """
    assert checksum_entry_name({"name": name}) is None


def test_a_plain_relative_name_is_accepted() -> None:
    """The names a record legitimately holds.

    **Test steps:**

    * read a root-level name and a nested one
    """
    assert checksum_entry_name({"name": "bar2.zip"}) == "bar2.zip"
    assert checksum_entry_name({"name": "foo1/bar1.zip"}) == "foo1/bar1.zip"


def test_a_parsed_entry_carries_its_algorithm_and_date() -> None:
    """What generate and verify reason over, read off one raw entry.

    **Test steps:**

    * parse an entry holding a crc32 hash and a stamp
    """
    parsed = parse_checksum_entry({"name": VIDEO, "crc32": "42342424", "verified": NOW, "status": "matched"})

    assert parsed is not None
    assert parsed.algorithm == "crc32"
    assert parsed.digest == "42342424"
    assert parsed.verified == datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
    assert parsed.status == "matched"


def test_a_hash_recorded_in_upper_case_still_compares(disk: FakeDisk) -> None:
    """A value seeded from a legacy ``.sfv`` is hex in the other case, and matches all the same.

    **Test steps:**

    * seed a crc32 entry whose hash is upper-cased, and verify
    """
    disk.seed_record([entry(VIDEO, algorithm="crc32", digest=digest_of(VIDEO_BYTES, "crc32").upper())])

    assert verify_checksums(INFO_PATH, only=[VIDEO]).statuses == {VIDEO: "matched"}


def test_an_entry_with_no_hash_yet_parses(disk: FakeDisk) -> None:
    """A resting ``unexpected`` -- listed, never hashed -- is a shape the format defines.

    **Test steps:**

    * seed an entry holding only a name and a status, and verify
    * check it was hashed, dated and recorded matched
    """
    disk.seed_record([{"name": VIDEO, "status": "unexpected"}])

    report = verify_checksums(INFO_PATH, only=[VIDEO])

    assert report.statuses == {VIDEO: "matched"}
    assert disk.entries[VIDEO][DEFAULT_CHECKSUM_ALGORITHM] == digest_of(VIDEO_BYTES)


def test_an_empty_report_is_the_default(disk: FakeDisk) -> None:
    """A report says nothing until a run establishes something.

    **Test steps:**

    * build a bare report
    """
    del disk
    report = ChecksumReport()

    assert not report.statuses
    assert not report.skipped
    assert not report.unreadable
    assert report.unnamed_malformed == 0


def test_the_default_algorithm_is_the_measured_one() -> None:
    """XXH3 is what a record is written under unless a setting says otherwise (#203).

    **Test steps:**

    * check the default names xxh3, and that it hashes as the library does
    """
    assert DEFAULT_CHECKSUM_ALGORITHM == "xxh3"
    assert digest_of(VIDEO_BYTES) == xxhash.xxh3_64(VIDEO_BYTES).hexdigest()


# endregion


# region Forgetting entries


def test_forgetting_drops_exactly_the_named_entries(disk: FakeDisk) -> None:
    """The named entries go and every other one stays (#244).

    **Test steps:**

    * generate a record over both content files, then forget one of them
    * check the other is untouched and the dropped name came back
    """
    generate_checksums(INFO_PATH)
    before = disk.entries[ARCHIVE]

    dropped = forget_checksums(INFO_PATH, only=[VIDEO])

    assert dropped == (VIDEO,)
    assert set(disk.entries) == {ARCHIVE}
    assert disk.entries[ARCHIVE] == before


def test_forgetting_carries_every_unknown_key_byte_for_byte(disk: FakeDisk) -> None:
    """A record's own top-level keys, and another build's entry keys, survive a forget (#244).

    **Test steps:**

    * seed a record carrying an unknown top-level key and an entry with an unknown key
    * forget an unrelated entry
    * check both are still there exactly as written
    """
    disk.files[RECORD_PATH] = (
        json.dumps(
            {
                "version": 1,
                "annotations": {"by": "another build"},
                "files": [entry(VIDEO, VIDEO_BYTES), entry(ARCHIVE, ARCHIVE_BYTES, note="kept")],
            },
            indent=2,
        )
        + "\n"
    ).encode("utf-8")

    forget_checksums(INFO_PATH, only=[VIDEO])

    assert disk.record["annotations"] == {"by": "another build"}
    assert disk.entries[ARCHIVE]["note"] == "kept"


def test_forgetting_a_name_the_record_never_held_writes_nothing(disk: FakeDisk) -> None:
    """A name that is already forgotten is not an error, and not a write either (#244).

    **Test steps:**

    * generate, forget the counters, then forget a name the record does not hold
    * check nothing came back and the record was not rewritten
    """
    generate_checksums(INFO_PATH)
    disk.forget()

    dropped = forget_checksums(INFO_PATH, only=["nowhere/at/all.mp4"])

    assert not dropped
    assert disk.writes == 0


def test_forgetting_never_drops_an_entry_it_cannot_name(disk: FakeDisk) -> None:
    """An entry with no readable name cannot be selected, so it is carried (#244).

    **Test steps:**

    * seed a record holding an unnamed entry beside a named one
    * forget the named one
    * check the unnamed entry is still there
    """
    disk.seed_record([{"crc32": "deadbeef"}, entry(VIDEO, VIDEO_BYTES)])

    forget_checksums(INFO_PATH, only=[VIDEO])

    assert disk.record["files"] == [{"crc32": "deadbeef"}]


def test_forgetting_over_a_resource_with_no_record_refuses(disk: FakeDisk) -> None:
    """There is nothing to forget from, and saying so beats inventing an empty record (#244).

    **Test steps:**

    * forget over a resource that has never been checksummed
    * check it raises and wrote nothing
    """
    with raises(FileNotFoundError):
        forget_checksums(INFO_PATH, only=[VIDEO])

    assert RECORD_PATH not in disk.files


def test_a_forgotten_entry_is_adopted_again_by_the_next_verify(disk: FakeDisk) -> None:
    """Forgetting the entry of a file that is still there achieves nothing, which is why the surface
    that offers it is scoped to ``missing`` rows ([[data-model#checksums]], #244).

    **Test steps:**

    * generate, forget one entry whose file is still on disk, then verify
    * check the file came straight back, recorded matched
    """
    generate_checksums(INFO_PATH)
    forget_checksums(INFO_PATH, only=[VIDEO])

    report = verify_checksums(INFO_PATH)

    assert report.statuses[VIDEO] == "unexpected"
    assert disk.entries[VIDEO]["status"] == "matched"


# endregion


def test_forgetting_a_duplicated_name_reports_it_once(disk: FakeDisk) -> None:
    """A hand-edited record can hold one name twice; both entries go and the name is said once (#244).

    **Test steps:**

    * seed a record listing the video twice
    * forget it
    * check both entries went and the name came back a single time
    """
    disk.seed_record([entry(VIDEO, VIDEO_BYTES), entry(VIDEO, VIDEO_BYTES), entry(ARCHIVE, ARCHIVE_BYTES)])

    dropped = forget_checksums(INFO_PATH, only=[VIDEO])

    assert dropped == (VIDEO,)
    assert set(disk.entries) == {ARCHIVE}
