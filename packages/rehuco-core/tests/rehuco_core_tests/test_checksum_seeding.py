"""Tests for seeding a ``.checksum`` from a legacy ``.sfv``/``.md5``/``.sha*`` manifest (#243).

The run underneath is the **real** verify, not a mocked one: what this module is about is that a seeded
entry is an ordinary entry, so the claims worth testing -- a seeded hash decides a verdict, a missing
file keeps the hash it was recorded with, migration re-keys a seeded entry from one read -- can only be
made by letting #203's verify do its own work over the seed.

The disk is a hand-written fake, `test_rehu_checksums`' near-verbatim, with one addition: it counts
**manifest** reads separately from content reads, because *the legacy file is out of the loop after the
first verify* is the claim that has to be measured rather than stated.
"""

# seeding on the way past a verify and seeding on its own (#256) are one subject, and only read against
# each other: what one establishes is exactly what the other's mode then refuses to establish twice. So
# the module-length cap is lifted here rather than splitting the pair apart.
# pylint: disable=too-many-lines

import json
import logging
from datetime import timedelta
from io import BytesIO
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Any, Final

import pytest
from freezegun.api import FrozenDateTimeFactory
from pytest import fixture, raises
from pytest_mock import MockerFixture
from rehuco_core import (
    CHECKSUM_ALGORITHMS,
    DEFAULT_CHECKSUM_ALGORITHM,
    EXCLUDED_FILE_PATTERNS,
    ChecksumReport,
    ContentUnreachableError,
    RetireLegacyManifestJob,
    VerifyChecksumsJob,
    checksum_report_summary,
    generate_checksums,
    remediate_legacy_manifest,
    seed_checksum_record,
    verify_checksums,
)

from rehuco_core_tests.fake_directories import FakeDirEntry, FakeScandir

DIRECTORY: Final = Path("/fake/library/sculpting")
INFO_PATH: Final = DIRECTORY / "info.rehu"
RECORD_PATH: Final = DIRECTORY / "info.checksum"
SFV_PATH: Final = DIRECTORY / "info.sfv"
MD5_PATH: Final = DIRECTORY / "info.md5"

VIDEO: Final = "lesson1.mp4"
ARCHIVE: Final = "extras/pack.zip"

VIDEO_BYTES: Final = bytes(range(256)) * 12
ARCHIVE_BYTES: Final = bytes(range(255, -1, -1)) * 7

CORRUPTED_VIDEO_BYTES: Final = b"\xff" + VIDEO_BYTES[1:]
"""The video with one byte flipped, and **the same length** -- so nothing but the hash can tell."""

NOW: Final = "2026-08-05T12:00:00Z"


# region Fakes


# the filesystem faces below are `test_rehu_checksums.FakeDisk`'s, near-verbatim -- kept as a separate
# copy rather than shared, matching this codebase's fake-disk convention
# pylint: disable=duplicate-code
class FakeDisk:
    """Every file under :data:`DIRECTORY`, and a record of what was read and written.

    :param files: the resource's files, keyed by name relative to the ``.rehu``, POSIX-separated.
    """

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files: Final[dict[Path, bytes]] = {
            DIRECTORY / PurePosixPath(name): payload for name, payload in files.items()
        }
        self.reads: list[str] = []
        """Every content file opened for reading, in order, by record-relative name."""
        self.manifest_reads: list[Path] = []
        """Every file read whole as bytes -- which is only ever a legacy manifest (#243)."""
        self.writes = 0
        """How many times the record has been written."""
        self.renames: list[tuple[Path, Path]] = []
        """Every rename, in order -- which is only ever a manifest being retired (#259)."""
        self.offline_directories: Final[set[Path]] = set()
        """The directories whose listing refuses -- an away mount, or a branch of one
        ([[mounts-and-storage#offline-mounts]]). Their files stay in :attr:`files`, because that is the
        point: they exist, and this run cannot see them (#245)."""
        self.refused: Final[set[Path]] = set()
        """The paths that answer neither *is it there* nor *what is in it* -- a share that says no,
        which is the one condition a test cannot arrange by editing :attr:`files`."""

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
        :returns: a fresh reader over its bytes.
        :raises FileNotFoundError: nothing lives there.
        """
        payload = self.__payload(path)
        self.reads.append(self.name_of(path))
        return BytesIO(payload)

    def stat(self, path: Path) -> SimpleNamespace:
        """Answer a file's size.

        :param path: the file to measure.
        :returns: an object carrying ``st_size``.
        :raises FileNotFoundError: nothing lives at ``path``.
        """
        return SimpleNamespace(st_size=len(self.__payload(path)))

    def exists(self, path: Path) -> bool:
        """Whether anything lives at ``path`` -- what a job's validation asks.

        :param path: the candidate.
        :returns: whether the disk holds it.
        :raises PermissionError: the path is refused.
        """
        if Path(path) in self.refused:
            raise PermissionError(str(path))
        return Path(path) in self.files

    def read_text(self, path: Path) -> str:
        """Read a file as UTF-8 text -- how the record is loaded.

        :param path: the file to read.
        :returns: its decoded contents.
        :raises FileNotFoundError: nothing lives at ``path``.
        """
        return self.__payload(path).decode("utf-8")

    def read_bytes(self, path: Path) -> bytes:
        """Read a file whole, counting it -- how a legacy manifest is read.

        :param path: the file to read.
        :returns: its bytes.
        :raises PermissionError: the path is refused.
        :raises FileNotFoundError: nothing lives at ``path``.
        """
        if Path(path) in self.refused:
            raise PermissionError(str(path))
        payload = self.__payload(path)
        self.manifest_reads.append(Path(path))
        return payload

    def write_text(self, path: Path | str, text: str) -> None:
        """Replace a file's contents -- how the record is saved.

        :param path: the file to write.
        :param text: what to write.
        """
        self.writes += 1
        self.files[Path(path)] = text.encode("utf-8")

    def rename(self, path: Path, target: Path) -> None:
        """Move one file to another name -- how a manifest is retired (#259).

        :param path: the file to move.
        :param target: where it lands.
        :raises PermissionError: the path is refused.
        :raises FileNotFoundError: nothing lives at ``path``.
        """
        if Path(path) in self.refused:
            raise PermissionError(str(path))
        payload = self.__payload(path)
        self.renames.append((Path(path), Path(target)))
        self.files[Path(target)] = payload
        del self.files[Path(path)]

    # endregion

    # region Test-side conveniences

    def name_of(self, path: Path) -> str:
        """A path's record-relative, POSIX-separated name.

        :param path: a path under :data:`DIRECTORY`.
        :returns: the name a record entry would carry.
        """
        return path.relative_to(DIRECTORY).as_posix()

    def put(self, name: str, payload: bytes) -> None:
        """Add or replace one file.

        :param name: its name relative to the ``.rehu``, POSIX-separated.
        :param payload: its bytes.
        """
        self.files[DIRECTORY / PurePosixPath(name)] = payload

    def remove(self, name: str) -> None:
        """Delete one file.

        :param name: its name relative to the ``.rehu``, POSIX-separated.
        """
        del self.files[DIRECTORY / PurePosixPath(name)]

    @property
    def record(self) -> dict[str, Any]:
        """The record as it now stands on disk.

        :returns: the parsed record object.
        """
        return json.loads(self.files[RECORD_PATH].decode("utf-8"))

    @property
    def entries(self) -> dict[str, dict[str, Any]]:
        """The record's entries by name.

        :returns: name to entry.
        """
        return {entry["name"]: entry for entry in self.record["files"]}

    def forget(self) -> None:
        """Clear the counters, so a second run's reads are counted on their own."""
        self.reads = []
        self.manifest_reads = []
        self.renames = []
        self.writes = 0

    # endregion

    def __payload(self, path: Path) -> bytes:
        """One file's bytes.

        :param path: the file.
        :returns: its contents.
        :raises FileNotFoundError: nothing lives at ``path``.
        """
        payload = self.files.get(Path(path))
        if payload is None:
            raise FileNotFoundError(str(path))
        return payload


# pylint: enable=duplicate-code


class FakeControl:  # pylint: disable=too-few-public-methods  # the protocol has exactly one method
    """A stand-in for the engine's :class:`~rehuco_core.JobControl`, recording what it was told."""

    def __init__(self) -> None:
        self.reports: list[tuple[int, int | None]] = []

    def report(self, done: int, total: int | None = None) -> None:
        """Record one progress report.

        :param done: bytes hashed so far.
        :param total: bytes expected in all.
        """
        self.reports.append((done, total))


def digest_of(payload: bytes, algorithm: str = DEFAULT_CHECKSUM_ALGORITHM) -> str:
    """Hash bytes the way the record records them.

    :param payload: the bytes to hash.
    :param algorithm: which algorithm to hash under.
    :returns: the hex digest.
    """
    digest = CHECKSUM_ALGORITHMS[algorithm].new_digest()
    digest.update(payload)
    return digest.hexdigest()


VIDEO_CRC: Final = digest_of(VIDEO_BYTES, "crc32").upper()
"""The video's CRC-32 in the uppercase hex a ``.sfv`` is written in -- which the comparison has to
tolerate, since a recorded hash is compared case-insensitively (#203)."""

ARCHIVE_CRC: Final = digest_of(ARCHIVE_BYTES, "crc32").upper()


@fixture(name="disk")
def fixture_disk(mocker: MockerFixture, freezer: FrozenDateTimeFactory) -> FakeDisk:
    """A resource holding a video, an archive in a subfolder, and its own bookkeeping.

    No ``.checksum`` -- every test here is about the run that has to find one somewhere else.

    :param mocker: pytest-mock fixture.
    :param freezer: the frozen clock, started at :data:`NOW` so a written stamp is predictable.
    :returns: the disk under the code's feet.
    """
    freezer.move_to(NOW)
    disk = FakeDisk(
        {
            "info.rehu": b'{"format_version": 2}',
            "info00.jpg": b"a screenshot",
            "Thumbs.db": b"a thumbnail cache",
            VIDEO: VIDEO_BYTES,
            ARCHIVE: ARCHIVE_BYTES,
        }
    )
    mocker.patch("rehuco_core.rehu_content_files.os.scandir", side_effect=disk.scandir)
    mocker.patch("rehuco_core.checksum_seeding.os.scandir", side_effect=disk.scandir)
    mocker.patch("rehuco_core.content_reading.shared_read_open", side_effect=disk.open)
    mocker.patch("rehuco_core.checksum_record.atomic_write_text", side_effect=disk.write_text)
    mocker.patch.object(Path, "stat", autospec=True, side_effect=lambda self, **_kwargs: disk.stat(self))
    mocker.patch.object(Path, "exists", autospec=True, side_effect=disk.exists)
    mocker.patch.object(Path, "read_text", autospec=True, side_effect=lambda self, **_kwargs: disk.read_text(self))
    mocker.patch.object(Path, "read_bytes", autospec=True, side_effect=disk.read_bytes)
    mocker.patch.object(Path, "rename", autospec=True, side_effect=disk.rename)
    return disk


def put_sfv(disk: FakeDisk, *lines: str, name: str = "info.sfv") -> None:
    """Write a ``.sfv``-shaped manifest beside the record.

    :param disk: the disk to write it to.
    :param lines: its lines, without terminators.
    :param name: the manifest's filename.
    """
    disk.put(name, ("\r\n".join(lines) + "\r\n").encode("utf-8"))


# endregion


# region Seeding a verify


def test_a_sfv_seeds_the_first_verify(disk: FakeDisk) -> None:
    """A resource with no record verifies against the ``.sfv`` beside it, and writes a record.

    **Test steps:**

    * put a ``.sfv`` naming both content files, mixing ``\\`` and ``/`` in the same file
    * verify
    * check both came back matched, the written names are POSIX, and the seed names the manifest
    """
    put_sfv(disk, f"{VIDEO} {VIDEO_CRC}", f"extras\\pack.zip {ARCHIVE_CRC}")

    report = verify_checksums(INFO_PATH)

    assert report.statuses == {VIDEO: "matched", ARCHIVE: "matched"}
    assert set(disk.entries) == {VIDEO, ARCHIVE}
    assert report.seed is not None
    assert report.seed.manifest == SFV_PATH
    assert not report.seed.dropped


def test_a_seeded_entry_is_recorded_under_the_suffix_algorithm(disk: FakeDisk) -> None:
    """The manifest's suffix decides the algorithm, not the configured default.

    **Test steps:**

    * verify against a ``.sfv``, with the default algorithm left at XXH3
    * check the written entry holds a ``crc32`` hash and carries this run's stamp
    """
    put_sfv(disk, f"{VIDEO} {VIDEO_CRC}", f"extras/pack.zip {ARCHIVE_CRC}")

    verify_checksums(INFO_PATH)

    assert disk.entries[VIDEO] == {
        "name": VIDEO,
        "crc32": VIDEO_CRC,
        "verified": NOW,
        "status": "matched",
    }


def test_a_seeded_entry_over_changed_bytes_is_mismatched(disk: FakeDisk) -> None:
    """The old claim is *checked*, which is the whole point: changed bytes fail it.

    **Test steps:**

    * put a ``.sfv`` recorded when the files were good, then corrupt the video
    * verify
    * check the video is mismatched and still holds the hash it failed against
    """
    put_sfv(disk, f"{VIDEO} {VIDEO_CRC}", f"extras/pack.zip {ARCHIVE_CRC}")
    disk.put(VIDEO, CORRUPTED_VIDEO_BYTES)

    report = verify_checksums(INFO_PATH)

    assert report.statuses[VIDEO] == "mismatched"
    assert disk.entries[VIDEO]["crc32"] == VIDEO_CRC


def test_a_seeded_entry_for_a_deleted_file_keeps_its_hash(disk: FakeDisk) -> None:
    """A file that is gone is ``missing`` and keeps its hash, so the claim survives its return.

    **Test steps:**

    * put a ``.sfv`` naming both files, then delete the archive
    * verify
    * check the archive is missing and its recorded hash is still there
    """
    put_sfv(disk, f"{VIDEO} {VIDEO_CRC}", f"extras/pack.zip {ARCHIVE_CRC}")
    disk.remove(ARCHIVE)

    report = verify_checksums(INFO_PATH)

    assert report.statuses[ARCHIVE] == "missing"
    assert disk.entries[ARCHIVE]["crc32"] == ARCHIVE_CRC


def test_content_the_manifest_never_listed_is_adopted(disk: FakeDisk) -> None:
    """A file the old manifest does not name is adopted in the same run, as any unlisted file is.

    **Test steps:**

    * put a ``.sfv`` naming only the video
    * verify
    * check the archive was reported unexpected and recorded matched under the default algorithm
    """
    put_sfv(disk, f"{VIDEO} {VIDEO_CRC}")

    report = verify_checksums(INFO_PATH)

    assert report.statuses == {VIDEO: "matched", ARCHIVE: "unexpected"}
    assert disk.entries[ARCHIVE][DEFAULT_CHECKSUM_ALGORITHM] == digest_of(ARCHIVE_BYTES)
    assert disk.entries[ARCHIVE]["status"] == "matched"


def test_the_second_verify_never_opens_the_manifest(disk: FakeDisk) -> None:
    """Seeding is one-way: the record it writes is what every later verify reads.

    **Test steps:**

    * verify against a ``.sfv``, then forget the counters and verify again
    * check the second run read no manifest at all, and the ``.sfv`` is retired rather than gone (#259)
    """
    put_sfv(disk, f"{VIDEO} {VIDEO_CRC}", f"extras/pack.zip {ARCHIVE_CRC}")
    verify_checksums(INFO_PATH)
    disk.forget()

    report = verify_checksums(INFO_PATH)

    assert disk.manifest_reads == []
    assert report.seed is None
    assert SFV_PATH not in disk.files
    assert SFV_PATH.with_name("info.sfv.orig") in disk.files


def test_seeding_happens_even_when_a_run_may_not_create_a_record(disk: FakeDisk) -> None:
    """Finding a record is not creating one, so ``create_if_missing`` does not gate a seed.

    **Test steps:**

    * verify with ``create_if_missing`` off, against a resource holding only a ``.sfv``
    * check it ran rather than raising
    """
    put_sfv(disk, f"{VIDEO} {VIDEO_CRC}")

    report = verify_checksums(INFO_PATH, create_if_missing=False)

    assert report.statuses[VIDEO] == "matched"


def test_a_verify_with_nothing_to_seed_from_still_refuses(disk: FakeDisk) -> None:
    """No record and no manifest is the case ``create_if_missing`` was always about.

    **Test steps:**

    * verify a resource with neither, with ``create_if_missing`` off
    * check it raises
    """
    with raises(FileNotFoundError):
        verify_checksums(INFO_PATH, create_if_missing=False)

    assert RECORD_PATH not in disk.files


def test_a_generate_never_seeds(disk: FakeDisk) -> None:
    """A generate re-baselines what it is handed, so a seed would buy it nothing and cost the claim.

    **Test steps:**

    * put a ``.sfv`` whose hash for the video is wrong, then generate
    * check the record was baselined under the default algorithm and reported nothing seeded
    """
    put_sfv(disk, f"{VIDEO} {'0' * 8}")

    report = generate_checksums(INFO_PATH)

    assert report.seed is None
    assert disk.entries[VIDEO][DEFAULT_CHECKSUM_ALGORITHM] == digest_of(VIDEO_BYTES)


def test_a_seeded_entry_migrates_from_one_read(disk: FakeDisk) -> None:
    """*Update checksums on verify* composes with a seed, at no extra read.

    **Test steps:**

    * verify against a ``.sfv`` with ``migrate_to`` set to the default algorithm
    * check the entry ends holding only the new hash, and its file was read once
    """
    put_sfv(disk, f"{VIDEO} {VIDEO_CRC}", f"extras/pack.zip {ARCHIVE_CRC}")

    report = verify_checksums(INFO_PATH, migrate_to=DEFAULT_CHECKSUM_ALGORITHM)

    assert report.statuses[VIDEO] == "matched"
    assert disk.entries[VIDEO][DEFAULT_CHECKSUM_ALGORITHM] == digest_of(VIDEO_BYTES)
    assert "crc32" not in disk.entries[VIDEO]
    assert disk.reads.count(VIDEO) == 1


# endregion


# region What a seed refuses to carry


def test_a_name_outside_the_resource_is_dropped(disk: FakeDisk) -> None:
    """Nothing outside the resource is ever hashed on the strength of a line in a legacy file.

    **Test steps:**

    * put a ``.sfv`` naming an escaping relative path, an absolute path and a drive letter
    * verify
    * check only the one legitimate file was read, and the three were reported dropped
    """
    put_sfv(
        disk,
        f"{VIDEO} {VIDEO_CRC}",
        f"..\\..\\elsewhere\\secrets.zip {VIDEO_CRC}",
        f"/etc/passwd {VIDEO_CRC}",
        f"C:\\Windows\\system32\\cmd.exe {VIDEO_CRC}",
    )

    report = verify_checksums(INFO_PATH)

    assert report.seed is not None
    assert len(report.seed.dropped) == 3
    assert set(disk.entries) == {VIDEO, ARCHIVE}
    assert set(disk.reads) == {VIDEO, ARCHIVE}


def test_a_name_that_is_not_content_is_dropped(disk: FakeDisk) -> None:
    """A predecessor was free to checksum files this app deliberately does not.

    **Test steps:**

    * put a ``.sfv`` naming a screenshot and a ``Thumbs.db`` alongside the video
    * verify
    * check neither was seeded, so no screenshot edit can ever make this record dirty
    """
    put_sfv(disk, f"{VIDEO} {VIDEO_CRC}", f"info00.jpg {VIDEO_CRC}", f"Thumbs.db {VIDEO_CRC}")

    report = verify_checksums(INFO_PATH)

    assert report.seed is not None
    assert {drop.line.split(" ")[0] for drop in report.seed.dropped} == {"info00.jpg", "Thumbs.db"}
    assert set(disk.entries) == {VIDEO, ARCHIVE}


def test_a_line_this_build_cannot_read_costs_itself(disk: FakeDisk) -> None:
    """A malformed line is reported, and the rest of the file still seeds.

    **Test steps:**

    * put a ``.sfv`` with a comment, a blank line, a hash of the wrong length and a shapeless line
    * verify
    * check the two good lines seeded and the two bad ones were reported
    """
    put_sfv(
        disk,
        "; generated by some checker, 2019",
        "",
        f"{VIDEO} {VIDEO_CRC}",
        "extras/pack.zip NOTAHASH",
        "a line with no hash at all",
        f"extras/pack.zip {ARCHIVE_CRC}",
    )

    report = verify_checksums(INFO_PATH)

    assert report.statuses == {VIDEO: "matched", ARCHIVE: "matched"}
    assert report.seed is not None
    assert [drop.line for drop in report.seed.dropped] == ["extras/pack.zip NOTAHASH", "a line with no hash at all"]


def test_a_name_listed_twice_is_seeded_once(disk: FakeDisk) -> None:
    """Two claims about one file cannot both be the record's, so the first wins and the second is said.

    **Test steps:**

    * put a ``.sfv`` naming the video twice, the second time with a hash that would fail
    * verify
    * check the video matched and the duplicate was reported
    """
    put_sfv(disk, f"{VIDEO} {VIDEO_CRC}", f"{VIDEO} {'0' * 8}")

    report = verify_checksums(INFO_PATH)

    assert report.statuses[VIDEO] == "matched"
    assert report.seed is not None
    assert [drop.line for drop in report.seed.dropped] == [f"{VIDEO} {'0' * 8}"]


def test_a_line_no_codec_reads_is_one_dropped_entry(disk: FakeDisk) -> None:
    """A name that survives neither codec costs itself, not the seed.

    **Test steps:**

    * put a ``.sfv`` whose second line carries bytes cp1252 has no character for
    * verify
    * check the first line still seeded and the second was reported
    """
    disk.put("info.sfv", f"{VIDEO} {VIDEO_CRC}\r\n".encode() + b"\x81\x8d.mp4 " + VIDEO_CRC.encode() + b"\r\n")

    report = verify_checksums(INFO_PATH)

    assert report.statuses[VIDEO] == "matched"
    assert report.seed is not None
    assert [drop.reason for drop in report.seed.dropped] == ["neither UTF-8 nor cp1252"]


def test_a_name_whose_existence_cannot_be_answered_is_carried(disk: FakeDisk) -> None:
    """A refusal is not an answer, so the claim is kept and the file reported missing.

    **Test steps:**

    * put a ``.sfv`` naming a file the disk refuses to answer for at all
    * verify
    * check the entry was seeded, came back missing, and still holds its hash
    """
    put_sfv(disk, f"{VIDEO} {VIDEO_CRC}", f"gone.mp4 {VIDEO_CRC}")
    disk.refused.add(DIRECTORY / "gone.mp4")

    report = verify_checksums(INFO_PATH)

    assert report.statuses["gone.mp4"] == "missing"
    assert disk.entries["gone.mp4"]["crc32"] == VIDEO_CRC


def test_a_manifest_that_will_not_read_leaves_the_run_where_it_was(disk: FakeDisk) -> None:
    """Finding a manifest is not reading one; a refusal is the same as having none.

    **Test steps:**

    * put a ``.sfv`` and make the disk refuse to open it
    * verify with ``create_if_missing`` off
    * check it refused the way a resource with no manifest does
    """
    put_sfv(disk, f"{VIDEO} {VIDEO_CRC}")
    disk.refused.add(SFV_PATH)

    with raises(FileNotFoundError):
        verify_checksums(INFO_PATH, create_if_missing=False)


def test_a_cp1252_name_survives(disk: FakeDisk) -> None:
    """These files were written by Windows tools years ago; a non-ASCII name is cp1252, not garbage.

    **Test steps:**

    * add a file whose name carries a ``é``, and a ``.sfv`` naming it in cp1252 bytes
    * verify
    * check the name was read and the file matched
    """
    name = "resumé.mp4"
    disk.put(name, VIDEO_BYTES)
    disk.put("info.sfv", f"{name} {VIDEO_CRC}\r\n".encode("cp1252"))

    report = verify_checksums(INFO_PATH)

    assert report.statuses[name] == "matched"


# endregion


# region Which manifest is read


def test_a_coreutils_manifest_seeds_the_same_names_either_way(disk: FakeDisk) -> None:
    """The binary marker and the second separator space are noise; the names are what matter.

    **Test steps:**

    * seed once from a ``.sha256`` written with two spaces and a ``*``, and once without either
    * check both produced the same record entries
    """
    sha_video = digest_of(VIDEO_BYTES, "sha256")
    sha_archive = digest_of(ARCHIVE_BYTES, "sha256")
    disk.put("info.sha256", f"{sha_video}  *{VIDEO}\n{sha_archive}  *extras/pack.zip\n".encode())
    verify_checksums(INFO_PATH)
    marked = disk.entries
    disk.files.pop(RECORD_PATH)
    disk.put("info.sha256", f"{sha_video} {VIDEO}\n{sha_archive} extras/pack.zip\n".encode())

    verify_checksums(INFO_PATH)

    assert disk.entries == marked
    assert disk.entries[VIDEO]["sha256"] == sha_video


def test_the_stronger_manifest_wins_and_the_other_is_reported(disk: FakeDisk) -> None:
    """One manifest is read, by a fixed precedence, and the rest are said out loud.

    **Test steps:**

    * put both a ``.sfv`` and a ``.md5`` beside the record
    * verify
    * check the ``.md5`` seeded the entries and the ``.sfv`` was reported ignored and never read
    """
    put_sfv(disk, f"{VIDEO} {VIDEO_CRC}")
    disk.put("info.md5", f"{digest_of(VIDEO_BYTES, 'md5')} *{VIDEO}\n".encode())

    report = verify_checksums(INFO_PATH)

    assert report.seed is not None
    assert report.seed.manifest == MD5_PATH
    assert report.seed.ignored == (SFV_PATH,)
    assert disk.manifest_reads == [MD5_PATH]
    assert "md5" in disk.entries[VIDEO]


def test_a_manifest_this_build_cannot_hash_is_not_seeded_from(disk: FakeDisk) -> None:
    """A ``.sha1`` names an algorithm this build dropped, so it is passed over rather than failed.

    **Test steps:**

    * put a ``.sha1`` beside the record and verify with ``create_if_missing`` off
    * check it refused the way a resource with no manifest at all does
    """
    disk.put("info.sha1", f"{'a' * 40} *{VIDEO}\n".encode())

    with raises(FileNotFoundError):
        verify_checksums(INFO_PATH, create_if_missing=False)


def test_an_unrelated_manifest_is_not_this_record_s(disk: FakeDisk) -> None:
    """Same-stem is what makes a manifest this record's; anything else is an ordinary file.

    **Test steps:**

    * put a ``random.sfv`` naming the video, with no ``random.rehu`` anywhere
    * verify with ``create_if_missing`` off
    * check it refused, since nothing was this record's manifest
    """
    put_sfv(disk, f"{VIDEO} {VIDEO_CRC}", name="random.sfv")

    with raises(FileNotFoundError):
        verify_checksums(INFO_PATH, create_if_missing=False)


# endregion


# region Around the run


def test_a_verify_job_accepts_a_resource_that_has_only_a_manifest(disk: FakeDisk) -> None:
    """Refusing here would send the reader at a Generate, throwing the old claim away.

    **Test steps:**

    * validate a verify job over a resource with a ``.sfv`` and no ``.checksum``
    * check it passes, and that removing the manifest makes it refuse again
    """
    put_sfv(disk, f"{VIDEO} {VIDEO_CRC}")
    job = VerifyChecksumsJob(INFO_PATH)

    assert job.validate() is None

    disk.remove("info.sfv")

    assert job.validate() == f"This resource has no checksum record yet: {RECORD_PATH}"


def test_the_summary_names_the_manifest_a_run_was_seeded_from(disk: FakeDisk) -> None:
    """A seed happens once in a resource's life, so which file it came from is what a reader wants.

    **Test steps:**

    * verify against a ``.md5`` holding one good line and one unusable one, with a ``.sfv`` beside it
    * check the summary line names the manifest, counts what it dropped and ignored, and names both
      files it retired (#259)
    """
    disk.put("info.md5", f"{digest_of(VIDEO_BYTES, 'md5')} *{VIDEO}\nNOTAHASH *extras/pack.zip\n".encode())
    put_sfv(disk, f"{VIDEO} {VIDEO_CRC}")

    report = verify_checksums(INFO_PATH)

    assert checksum_report_summary(report) == (
        "1 matched, 1 unexpected, seeded 1 from info.md5, 1 seed line dropped, 1 manifest ignored, "
        "retired info.md5, info.sfv"
    )


def test_a_clean_seed_says_only_what_it_seeded(disk: FakeDisk) -> None:
    """With nothing dropped and nothing ignored, the summary carries one clause, not three.

    **Test steps:**

    * verify against a ``.sfv`` naming both content files, cleanly
    * check the summary names the manifest and says no more
    """
    put_sfv(disk, f"{VIDEO} {VIDEO_CRC}", f"extras/pack.zip {ARCHIVE_CRC}")

    report = verify_checksums(INFO_PATH)

    assert checksum_report_summary(report) == "2 matched, seeded 2 from info.sfv, retired info.sfv"


def test_a_seed_whose_retirement_refused_claims_none(disk: FakeDisk) -> None:
    """The claim landed but the file is still the authority on disk, so the line must not say retired --
    a reader who came back later would go looking for a backup nothing ever wrote (#259).

    **Test steps:**

    * verify against a clean ``.sfv`` whose ``.orig`` name is already taken, so retiring it refuses
    * check the summary names what it seeded and stops there
    """
    put_sfv(disk, f"{VIDEO} {VIDEO_CRC}", f"extras/pack.zip {ARCHIVE_CRC}")
    disk.put("info.sfv.orig", b"an older backup")

    report = verify_checksums(INFO_PATH)

    assert checksum_report_summary(report) == "2 matched, seeded 2 from info.sfv"


def test_a_verify_job_logs_what_the_manifest_did_not_contribute(
    disk: FakeDisk, caplog: pytest.LogCaptureFixture
) -> None:
    """The summary carries the counts; the resource's own log is where *which* and *why* land.

    **Test steps:**

    * run a verify job over a resource with a ``.md5`` holding one unusable line and a ``.sfv`` beside it
    * check the log names the ignored manifest and the dropped line's reason
    """
    disk.put("info.md5", f"{digest_of(VIDEO_BYTES, 'md5')} *{VIDEO}\nabcdef *extras/pack.zip\n".encode())
    put_sfv(disk, f"{VIDEO} {VIDEO_CRC}")
    # the seed's own detail is `rehuco_core.checksum_seeding`'s, shared with the import that seeds
    # without verifying (#256); the summary beside it is the job's
    caplog.set_level(logging.INFO, logger="rehuco_core")

    VerifyChecksumsJob(INFO_PATH).run(FakeControl())

    assert f"{SFV_PATH} was not read: info.md5 is the manifest this record was seeded from." in caplog.text
    assert "dropped 'abcdef *extras/pack.zip' -- not a MD5 hash." in caplog.text


def test_a_report_carries_no_seed_by_default() -> None:
    """Every run that did not seed says so by carrying nothing, so a surface can read the field plainly.

    **Test steps:**

    * build an empty report
    * check its seed is absent
    """
    assert ChecksumReport().seed is None


# endregion


# region Seeding without verifying (#256)


def test_a_seed_only_call_writes_the_record_and_reads_no_content(disk: FakeDisk) -> None:
    """The whole of a bulk import's default path: the claim is carried, and no byte is hashed.

    **Test steps:**

    * seed a resource holding a ``.sfv`` for both its files
    * check the record carries both claims and that nothing was opened for reading
    """
    put_sfv(disk, f"{VIDEO} {VIDEO_CRC}", f"{ARCHIVE} {ARCHIVE_CRC}")

    seed = seed_checksum_record(INFO_PATH)

    assert seed is not None
    assert seed.manifest == SFV_PATH
    assert disk.entries[VIDEO]["crc32"] == VIDEO_CRC
    assert disk.entries[ARCHIVE]["crc32"] == ARCHIVE_CRC
    assert disk.reads == []


def test_a_seeded_entry_lands_dateless_so_a_later_verify_checks_it(disk: FakeDisk) -> None:
    """No date is what makes the import self-healing: nothing is fresh, so the next sweep reads it.

    **Test steps:**

    * seed the record, then verify it with a staleness window wide enough to skip anything dated
    * check the seeded entry carried no date, and that the verify checked it anyway
    """
    put_sfv(disk, f"{VIDEO} {VIDEO_CRC}")
    seed_checksum_record(INFO_PATH)

    assert "verified" not in disk.entries[VIDEO]

    report = verify_checksums(INFO_PATH, stale_after=timedelta(days=365))

    assert report.statuses[VIDEO] == "matched"
    assert not report.skipped


def test_a_seed_only_call_leaves_an_existing_record_alone(disk: FakeDisk) -> None:
    """Seeding is one-way: the record supersedes the manifest, and re-seeding would undo that.

    **Test steps:**

    * verify a resource into a dated record, then put a manifest claiming something else and seed
    * check nothing was written and the recorded hash is the one the verify established
    """
    verify_checksums(INFO_PATH, create_if_missing=True)
    put_sfv(disk, f"{VIDEO} {'0' * 8}")
    disk.forget()

    assert seed_checksum_record(INFO_PATH) is None
    assert disk.writes == 0
    assert disk.entries[VIDEO][DEFAULT_CHECKSUM_ALGORITHM] == digest_of(VIDEO_BYTES)


def test_a_seed_only_call_with_no_manifest_writes_nothing(disk: FakeDisk) -> None:
    """No ``.sfv`` and no check asked for means no record: inventing a baseline is a generate's job.

    **Test steps:**

    * seed a resource with no manifest beside it
    * check nothing came back and no record was written
    """
    assert seed_checksum_record(INFO_PATH) is None
    assert RECORD_PATH not in disk.files


def test_a_seed_only_call_over_an_away_mount_refuses(disk: FakeDisk) -> None:
    """An unreachable resource is not an empty one (#245): every claim would read as a gone file.

    **Test steps:**

    * make the resource's own directory refuse to list, then seed
    * check it raises rather than writing a record
    """
    put_sfv(disk, f"{VIDEO} {VIDEO_CRC}")
    disk.offline_directories.add(DIRECTORY)

    with raises(ContentUnreachableError):
        seed_checksum_record(INFO_PATH)

    assert RECORD_PATH not in disk.files


def test_a_seed_only_call_carries_only_content(disk: FakeDisk) -> None:
    """The same rule a verify's seed is under: a name today's enumeration leaves out is dropped.

    **Test steps:**

    * seed from a manifest also claiming the screenshot and the ``Thumbs.db`` beside the record
    * check the record holds the video alone, and both other lines were reported dropped
    """
    put_sfv(disk, f"{VIDEO} {VIDEO_CRC}", f"info00.jpg {'a' * 8}", f"Thumbs.db {'b' * 8}")

    seed = seed_checksum_record(INFO_PATH)

    assert seed is not None
    assert list(disk.entries) == [VIDEO]
    assert [drop.reason for drop in seed.dropped] == ["a file this resource's content excludes"] * 2


def test_a_verify_that_does_not_seed_checks_what_was_recorded(disk: FakeDisk) -> None:
    """The import's second job: the claim is already in the record, and the manifest is not read again.

    **Test steps:**

    * seed the record, forget the counters, then verify with ``seed_legacy`` off
    * check the verify made its verdict and opened no manifest
    """
    put_sfv(disk, f"{VIDEO} {VIDEO_CRC}")
    seed_checksum_record(INFO_PATH)
    disk.forget()

    report = verify_checksums(INFO_PATH, seed_legacy=False)

    assert report.statuses[VIDEO] == "matched"
    assert report.seed is None
    assert disk.manifest_reads == []


def test_a_verify_that_does_not_seed_refuses_where_there_is_no_record(disk: FakeDisk) -> None:
    """A check that arrives before its own conversion costs a ``stat``, not a walk.

    **Test steps:**

    * verify with ``seed_legacy`` off over a resource holding only a ``.sfv``
    * check it raises and read neither the manifest nor any content
    """
    put_sfv(disk, f"{VIDEO} {VIDEO_CRC}")

    with raises(FileNotFoundError):
        verify_checksums(INFO_PATH, seed_legacy=False)

    assert disk.manifest_reads == []
    assert disk.reads == []


def test_a_verify_may_not_create_a_record_while_ignoring_the_manifest(disk: FakeDisk) -> None:
    """The fourth combination adopts today's bytes with a good claim sitting unread beside them.

    **Test steps:**

    * ask for a verify that creates a missing record and does not seed
    * check it refuses, and wrote nothing
    """
    put_sfv(disk, f"{VIDEO} {VIDEO_CRC}")

    with raises(ValueError):
        verify_checksums(INFO_PATH, create_if_missing=True, seed_legacy=False)

    assert RECORD_PATH not in disk.files


def test_a_verify_job_that_does_not_seed_refuses_a_resource_with_only_a_manifest(disk: FakeDisk) -> None:
    """The manifest is not this job's to read, so *no record yet* is the honest answer -- and retryable.

    **Test steps:**

    * validate a non-seeding verify job over a resource with a ``.sfv`` and no ``.checksum``
    * check it refuses, and that it accepts once the record has been seeded
    """
    put_sfv(disk, f"{VIDEO} {VIDEO_CRC}")
    job = VerifyChecksumsJob(INFO_PATH, seed_legacy=False)

    assert job.validate() == f"This resource has no checksum record yet: {RECORD_PATH}"

    seed_checksum_record(INFO_PATH)

    assert job.validate() is None


def test_a_verify_job_refuses_the_combination_core_refuses(disk: FakeDisk) -> None:
    """A hand-edited queue item fails as a row rather than as an exception out of the run.

    **Test steps:**

    * validate a verify job that would create a record without seeding
    * check it answers with a sentence
    """
    del disk

    job = VerifyChecksumsJob(INFO_PATH, create_if_missing=True, seed_legacy=False)

    assert job.validate() == "A verify that creates a missing record may not ignore the legacy manifest beside it."


def test_a_job_writes_down_whether_it_seeds(disk: FakeDisk) -> None:
    """A restored check is the check that was queued, and one written before the key defaults to on.

    **Test steps:**

    * round-trip a non-seeding job's state, then restore one from a state that never carried the key
    * check the first came back non-seeding and the second seeding
    """
    del disk
    state = VerifyChecksumsJob(INFO_PATH, seed_legacy=False).capture_state()

    restored = VerifyChecksumsJob()
    restored.restore_state(state)

    assert restored.seed_legacy is False

    older = VerifyChecksumsJob()
    older.restore_state({key: value for key, value in state.items() if key != "seed_legacy"})

    assert older.seed_legacy is True


# endregion


# region Retiring the manifest (#259)

ORIG_SFV: Final = DIRECTORY / "info.sfv.orig"
ORIG_MD5: Final = DIRECTORY / "info.md5.orig"


def test_a_seed_only_call_retires_the_manifest_it_read(disk: FakeDisk) -> None:
    """The claim is in the record, so the file it came from stops being one.

    **Test steps:**

    * seed a record from a ``.sfv``, hashing nothing
    * check the manifest now sits under ``.orig`` and the seed says so
    """
    put_sfv(disk, f"{VIDEO} {VIDEO_CRC}")

    seed = seed_checksum_record(INFO_PATH)

    assert seed is not None
    assert seed.retired == (SFV_PATH,)
    assert SFV_PATH not in disk.files
    assert ORIG_SFV in disk.files


def test_the_record_is_written_before_the_manifest_is_retired(disk: FakeDisk, mocker: MockerFixture) -> None:
    """Nothing is renamed until the claim is safely somewhere else.

    **Test steps:**

    * seed with the record write refusing
    * check the write raised and the manifest is exactly where it was
    """
    put_sfv(disk, f"{VIDEO} {VIDEO_CRC}")
    mocker.patch("rehuco_core.checksum_record.atomic_write_text", side_effect=PermissionError(str(RECORD_PATH)))

    with raises(PermissionError):
        seed_checksum_record(INFO_PATH)

    assert disk.renames == []
    assert SFV_PATH in disk.files


def test_a_passed_over_manifest_is_retired_with_the_one_that_seeded(disk: FakeDisk) -> None:
    """A file the precedence declined must not stay live to be absorbed by some later run.

    **Test steps:**

    * seed a resource carrying both a ``.md5`` (which wins) and a ``.sfv``
    * check both are retired, strongest first
    """
    disk.put("info.md5", f"{digest_of(VIDEO_BYTES, 'md5')} *{VIDEO}\n".encode())
    put_sfv(disk, f"{VIDEO} {VIDEO_CRC}")

    seed = seed_checksum_record(INFO_PATH)

    assert seed is not None
    assert seed.retired == (MD5_PATH, SFV_PATH)
    assert {ORIG_MD5, ORIG_SFV} <= set(disk.files)


def test_a_manifest_this_build_cannot_hash_is_left_alone(disk: FakeDisk) -> None:
    """Nothing considered it, so nothing has absorbed its claim and nothing may retire it.

    **Test steps:**

    * seed a resource whose ``.sha1`` (unshipped) sits beside a readable ``.sfv``
    * check only the ``.sfv`` was retired
    """
    disk.put("info.sha1", b"0" * 40 + f" *{VIDEO}\n".encode())
    put_sfv(disk, f"{VIDEO} {VIDEO_CRC}")

    seed = seed_checksum_record(INFO_PATH)

    assert seed is not None
    assert seed.retired == (SFV_PATH,)
    assert DIRECTORY / "info.sha1" in disk.files


def test_a_manifest_whose_orig_name_is_taken_stays_where_it_is(disk: FakeDisk) -> None:
    """Never overwrite -- the same contract a conversion's backups are under.

    **Test steps:**

    * seed a resource that already carries an ``info.sfv.orig``
    * check the record was still written and the manifest was not renamed over it
    """
    put_sfv(disk, f"{VIDEO} {VIDEO_CRC}")
    disk.put("info.sfv.orig", b"an older backup")

    seed = seed_checksum_record(INFO_PATH)

    assert seed is not None
    assert seed.retired == ()
    assert disk.files[ORIG_SFV] == b"an older backup"
    assert SFV_PATH in disk.files
    assert RECORD_PATH in disk.files


def test_a_rename_that_refuses_costs_itself_rather_than_the_seed(disk: FakeDisk, mocker: MockerFixture) -> None:
    """The claim is already recorded; failing here would put an error against work that happened.

    **Test steps:**

    * seed with the manifest's rename refusing
    * check the record was still written and the seed reports nothing retired
    """
    put_sfv(disk, f"{VIDEO} {VIDEO_CRC}")
    mocker.patch.object(Path, "rename", side_effect=PermissionError("read-only share"))

    seed = seed_checksum_record(INFO_PATH)

    assert seed is not None
    assert seed.retired == ()
    assert RECORD_PATH in disk.files


def test_a_verify_that_read_a_record_retires_nothing(disk: FakeDisk) -> None:
    """Only a run that absorbed a claim retires the file it came from.

    **Test steps:**

    * write a record by seeding, put a fresh manifest back beside it, and verify again
    * check the second run renamed nothing
    """
    put_sfv(disk, f"{VIDEO} {VIDEO_CRC}")
    seed_checksum_record(INFO_PATH)
    put_sfv(disk, f"{VIDEO} {VIDEO_CRC}")
    disk.forget()

    report = verify_checksums(INFO_PATH)

    assert report.seed is None
    assert disk.renames == []
    assert SFV_PATH in disk.files


# endregion


# region Remediating a record written without its manifest (#259)


def seed_and_strand(disk: FakeDisk, *lines: str) -> None:
    """Put a resource into the state hand-conversion left behind: a record, and a live manifest.

    :param disk: the disk to arrange.
    :param lines: the manifest's lines, written after the record so nothing absorbed them.
    """
    generate_checksums(INFO_PATH)
    put_sfv(disk, *lines)
    disk.forget()


def test_a_stranded_claim_replaces_the_digest_and_clears_the_date(disk: FakeDisk) -> None:
    """The manifest is the older and truer claim about what it names.

    **Test steps:**

    * baseline a record from disk, then drop a ``.sfv`` naming the video beside it
    * remediate, and check the entry now carries the legacy crc32 with no date and no status
    """
    seed_and_strand(disk, f"{VIDEO} {VIDEO_CRC}")

    seed = remediate_legacy_manifest(INFO_PATH)

    assert seed is not None
    entry = disk.entries[VIDEO]
    assert entry["crc32"] == VIDEO_CRC
    assert DEFAULT_CHECKSUM_ALGORITHM not in entry
    assert "verified" not in entry
    assert "status" not in entry
    assert disk.reads == []


def test_an_entry_the_manifest_does_not_name_is_untouched(disk: FakeDisk) -> None:
    """A file added after the manifest was written keeps its baseline and its timestamp.

    **Test steps:**

    * baseline a record covering the video and the archive, then strand a ``.sfv`` naming only the video
    * check the archive's entry came through byte-for-byte
    """
    generate_checksums(INFO_PATH)
    before = disk.entries[ARCHIVE]
    put_sfv(disk, f"{VIDEO} {VIDEO_CRC}")

    remediate_legacy_manifest(INFO_PATH)

    assert disk.entries[ARCHIVE] == before


def test_a_missing_entry_the_manifest_never_mentioned_keeps_its_claim(disk: FakeDisk) -> None:
    """The claim about a file that has gone is not the manifest's to overwrite.

    **Test steps:**

    * baseline, delete the archive, strand a ``.sfv`` naming only the video, and remediate
    * check the archive's entry still carries the hash it was baselined with
    """
    generate_checksums(INFO_PATH)
    archive_hash = disk.entries[ARCHIVE][DEFAULT_CHECKSUM_ALGORITHM]
    disk.remove(ARCHIVE)
    put_sfv(disk, f"{VIDEO} {VIDEO_CRC}")

    remediate_legacy_manifest(INFO_PATH)

    assert disk.entries[ARCHIVE][DEFAULT_CHECKSUM_ALGORITHM] == archive_hash


def test_a_claim_the_record_never_held_becomes_an_entry(disk: FakeDisk) -> None:
    """It is held nowhere else, which is exactly what seeding a claim is for.

    **Test steps:**

    * baseline before the archive exists, then strand a ``.sfv`` naming both files
    * check the archive arrived as a dateless entry under the manifest's algorithm
    """
    disk.remove(ARCHIVE)
    generate_checksums(INFO_PATH)
    disk.put(ARCHIVE, ARCHIVE_BYTES)
    put_sfv(disk, f"{VIDEO} {VIDEO_CRC}", f"{ARCHIVE} {ARCHIVE_CRC}")

    remediate_legacy_manifest(INFO_PATH)

    assert disk.entries[ARCHIVE] == {"name": ARCHIVE, "crc32": ARCHIVE_CRC}


def test_a_stranded_line_naming_something_excluded_clears_nothing(disk: FakeDisk) -> None:
    """The exclusion half is inherited: such a line never becomes an entry, so it cannot reset one.

    **Test steps:**

    * baseline, strand a ``.sfv`` naming the video and a ``Thumbs.db`` the walk leaves out
    * check the record gained no entry for it and the seed reported the drop
    """
    seed_and_strand(disk, f"{VIDEO} {VIDEO_CRC}", f"Thumbs.db {VIDEO_CRC}")

    seed = remediate_legacy_manifest(INFO_PATH)

    assert seed is not None
    assert [drop.reason for drop in seed.dropped] == ["a file this resource's content excludes"]
    assert "Thumbs.db" not in disk.entries


def test_a_name_the_record_holds_twice_ends_holding_one_entry(disk: FakeDisk) -> None:
    """A survivor beside a stale hash the merge just declared wrong would fail every verify after it.

    **Test steps:**

    * hand-write a record listing the video twice, then strand a ``.sfv`` naming it
    * check the merged record holds exactly one entry for it, carrying the legacy claim
    """
    generate_checksums(INFO_PATH)
    record = disk.record
    record["files"] = [*record["files"], {"name": VIDEO, "crc32": "deadbeef"}]
    disk.put("info.checksum", (json.dumps(record) + "\n").encode())
    put_sfv(disk, f"{VIDEO} {VIDEO_CRC}")

    remediate_legacy_manifest(INFO_PATH)

    video_entries = [entry for entry in disk.record["files"] if entry["name"] == VIDEO]
    assert video_entries == [{"name": VIDEO, "crc32": VIDEO_CRC}]


def test_remediating_retires_the_manifest_afterwards(disk: FakeDisk) -> None:
    """The whole point: the state cannot be reached again from here.

    **Test steps:**

    * remediate a stranded resource
    * check the ``.sfv`` moved to ``.orig``, after the record was written
    """
    seed_and_strand(disk, f"{VIDEO} {VIDEO_CRC}")

    seed = remediate_legacy_manifest(INFO_PATH)

    assert seed is not None
    assert seed.retired == (SFV_PATH,)
    assert disk.writes == 1
    assert ORIG_SFV in disk.files


def test_remediating_a_resource_with_no_record_does_nothing(disk: FakeDisk) -> None:
    """Writing one is the seed's job, and it is the job that carries the *one-way* rule.

    **Test steps:**

    * remediate a resource that has a ``.sfv`` and no ``.checksum``
    * check nothing was written and nothing was renamed
    """
    put_sfv(disk, f"{VIDEO} {VIDEO_CRC}")

    assert remediate_legacy_manifest(INFO_PATH) is None
    assert RECORD_PATH not in disk.files
    assert disk.renames == []


def test_remediating_a_resource_with_no_manifest_does_nothing(disk: FakeDisk) -> None:
    """There is nothing stranded, which is every already-converted resource.

    **Test steps:**

    * remediate a resource carrying only a baselined record
    * check nothing was written on top of it
    """
    generate_checksums(INFO_PATH)
    disk.forget()

    assert remediate_legacy_manifest(INFO_PATH) is None
    assert disk.writes == 0


def test_remediating_over_an_away_mount_refuses(disk: FakeDisk) -> None:
    """*The mount is away* outranks every answer this could otherwise give (#245).

    **Test steps:**

    * strand a resource, take its directory offline, and remediate
    * check it raised rather than merging over a record it could not check the content of
    """
    seed_and_strand(disk, f"{VIDEO} {VIDEO_CRC}")
    disk.offline_directories.add(DIRECTORY)

    with raises(ContentUnreachableError):
        remediate_legacy_manifest(INFO_PATH)


def test_remediating_with_no_record_over_an_away_mount_still_refuses(disk: FakeDisk) -> None:
    """*No record to merge into* is only honest where the directory can be seen at all (#245).

    The record lives on the mount, so an away mount surfaces as the record failing to load -- and
    answering *nothing to do* there would report a mount outage as a settled resource.

    **Test steps:**

    * take a stranded resource's directory offline with no record on disk, and remediate
    * check it raised rather than answering ``None``
    """
    put_sfv(disk, f"{VIDEO} {VIDEO_CRC}")
    disk.offline_directories.add(DIRECTORY)

    with raises(ContentUnreachableError):
        remediate_legacy_manifest(INFO_PATH)


def test_a_retirement_job_merges_and_retires(disk: FakeDisk) -> None:
    """The wizard's row, end to end, over the real callable.

    **Test steps:**

    * run a :class:`~rehuco_core.RetireLegacyManifestJob` over a stranded resource
    * check it validates, the claim landed, the manifest is retired, and the job kept what it did
    """
    seed_and_strand(disk, f"{VIDEO} {VIDEO_CRC}")
    job = RetireLegacyManifestJob(INFO_PATH)
    assert job.validate() is None

    job.run(FakeControl())

    assert job.seed is not None
    assert job.seed.retired == (SFV_PATH,)
    assert disk.entries[VIDEO]["crc32"] == VIDEO_CRC
    assert disk.reads == []


def test_a_retirement_job_with_nothing_to_do_succeeds(disk: FakeDisk) -> None:
    """The scan read a listing, not the record, so *already settled* is an outcome rather than a fault.

    **Test steps:**

    * run the job over a resource whose manifest has already been retired
    * check it completed and reports no seed
    """
    del disk
    generate_checksums(INFO_PATH)
    job = RetireLegacyManifestJob(INFO_PATH)

    job.run(FakeControl())

    assert job.seed is None


def test_a_retirement_job_refuses_a_resource_that_is_gone(disk: FakeDisk) -> None:
    """A stat, not a walk -- the same validation every job about one resource does.

    **Test steps:**

    * validate a job naming a ``.rehu`` that is not there
    * check it answers with a sentence
    """
    del disk
    missing = DIRECTORY / "gone.rehu"

    assert RetireLegacyManifestJob(missing).validate() == f"The resource no longer exists: {missing}"


def test_a_retirement_job_is_the_job_that_was_queued_after_a_restart(disk: FakeDisk) -> None:
    """A restored item is the run it described ([[appendices.task-queue#lifetime]]).

    **Test steps:**

    * round-trip a job's state through capture and restore
    * check the path and the exclusion set came back
    """
    del disk
    state = RetireLegacyManifestJob(INFO_PATH, excluded_patterns=("*.tmp",)).capture_state()

    restored = RetireLegacyManifestJob()
    restored.restore_state(state)

    assert restored.source == INFO_PATH
    assert restored.excluded_patterns == ("*.tmp",)
    assert restored.label == "Retire legacy manifest - sculpting"


def test_a_retirement_job_with_no_resource_at_all_refuses(disk: FakeDisk) -> None:
    """The registry builds one empty and hands it a state; one that never got a state cannot run.

    **Test steps:**

    * validate a job built with no path, ask it for its resource, and read its label
    * check all three answer without a path to work from
    """
    del disk
    job = RetireLegacyManifestJob()

    assert job.validate() == "This task has no resource."
    assert job.label == "Retire legacy manifest"
    with raises(ValueError, match="no resource"):
        job.resource_path()


def test_a_retirement_job_forgets_its_last_run_on_reset(disk: FakeDisk) -> None:
    """A retry reports its own run, not the one before it.

    **Test steps:**

    * run a job over a stranded resource, then reset it
    * check it no longer answers the seed it carried
    """
    seed_and_strand(disk, f"{VIDEO} {VIDEO_CRC}")
    job = RetireLegacyManifestJob(INFO_PATH)
    job.run(FakeControl())
    assert job.seed is not None

    job.reset()

    assert job.seed is None


def test_a_saved_retirement_task_that_names_no_resource_is_refused(disk: FakeDisk) -> None:
    """A hand-edited queue file costs its own item, not the build coming up broken.

    **Test steps:**

    * restore from a state with an empty path, and from one whose exclusion set is not a list of names
    * check the first raises and the second keeps this build's own default
    """
    del disk
    job = RetireLegacyManifestJob()
    with raises(ValueError, match="names no resource"):
        job.restore_state({"path": ""})

    job.restore_state({"path": str(INFO_PATH), "excluded_patterns": "*.tmp"})

    assert job.excluded_patterns == EXCLUDED_FILE_PATTERNS


# endregion
