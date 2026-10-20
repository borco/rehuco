"""Tests for who takes a record's lock file and who leaves it out (#512, [[sync#lock-file]]): every writer holds it
across its write, and scans, listings, the notifier and renames treat it as no one's content."""

import importlib
import json
import os
import socket
import threading
import time
import zlib
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

from pytest import LogCaptureFixture, mark, raises
from pytest_mock import MockerFixture
from rehuco_core import (
    DEFAULT_DELETER,
    EXCLUDED_FILE_PATTERNS,
    SCREENSHOT_NAME_PATTERNS,
    Changed,
    CoveringRecord,
    DirectoryClassifier,
    FileKind,
    LockHolder,
    RecordFileLock,
    RecordLockedError,
    Records,
    RehucoFile,
    RehuDocument,
    RenameCoordinator,
    ResourceKey,
    checksum_record_path,
    current_block_version,
    enumerate_content_files,
    forget_checksums,
    generate_checksums,
    lock_path_for,
    merge_write,
    remediate_legacy_manifest,
    rename_rehu_resource,
    seed_checksum_record,
    seed_from_legacy_manifest,
    verify_checksums,
)
from rehuco_core.checksum_claim_moves import prune_claims
from rehuco_core.notify import ChangeCoalescer, RawChange, RawChangeKind

from rehuco_core_tests.test_tc_conversion import TC_YAML


def fresh_other() -> LockHolder:
    """Another machine's process holding a lock it took just now -- fresh for the test's length, whenever the suite
    reaches it; to the second, so it reads back from the lock's text unchanged.

    :returns: the holder.
    """
    return LockHolder("bob", "elsewhere", 4242, "rehuco-agent", datetime.now(UTC).replace(microsecond=0))


def write_tutorial(path: Path) -> None:
    """Write a minimal tutorial record.

    :param path: where.
    """
    data = {
        "format_version": 2,
        "core": {"type": "tutorial", "id": "550e8400-e29b-41d4-a716-446655440000"},
        "tutorial": {"format_version": current_block_version("tutorial")},
    }
    path.write_text(json.dumps(data), encoding="utf-8")


def watching_writes(mocker: MockerFixture, module: str) -> list[bool]:
    """Pass ``module``'s atomic writes through, noting whether each found its target's lock there.

    :param mocker: pytest-mock fixture.
    :param module: the module whose ``atomic_write_text`` to watch.
    :returns: one entry per write, filled as they happen.
    """
    seen: list[bool] = []
    real = importlib.import_module(module).atomic_write_text

    def write(path: Path, text: str) -> None:
        """Note the lock, then write.

        :param path: the target.
        :param text: what to write.
        """
        seen.append(lock_path_for(Path(path)).exists())
        real(path, text)

    mocker.patch(f"{module}.atomic_write_text", side_effect=write)
    return seen


def no_lock_left(folder: Path) -> bool:
    """Whether ``folder`` holds no lock file.

    :param folder: where to look.
    :returns: whether none is there.
    """
    return not [entry for entry in folder.iterdir() if entry.name.endswith(".lock")]


# region Writers


def test_a_record_save_holds_the_lock_across_its_write(tmp_path: Path, mocker: MockerFixture) -> None:
    """``Records.save`` writes under the record's lock file, and leaves none.

    **Test steps:**

    * load a record, edit it and save it, watching the write
    * verify the lock was there for the write and is gone after
    """
    path = tmp_path / "info.rehu"
    write_tutorial(path)
    records = Records()
    key = ResourceKey(path)
    loaded = records.load(key, username="alice", unknown_username="ghost")
    loaded.document.title = "edited"
    seen = watching_writes(mocker, "rehuco_core.rehu_document")

    records.save(key, loaded.document, loaded.version, username="alice", overwrite=False)

    assert seen == [True]
    assert no_lock_left(tmp_path)


def test_a_record_save_is_refused_while_another_process_holds_the_lock(tmp_path: Path, mocker: MockerFixture) -> None:
    """A save that cannot take the lock in its time fails naming the holder, and writes nothing.

    **Test steps:**

    * hold the record's lock as another machine's process, and shorten the wait
    * save an edit
    * verify a ``RecordLockedError`` naming the holder, the file unchanged and the other lock kept
    """
    path = tmp_path / "info.rehu"
    write_tutorial(path)
    before = path.read_bytes()
    lock = lock_path_for(path)
    other = fresh_other()
    lock.write_text(other.text(), encoding="utf-8")
    mocker.patch("rehuco_core.record_file_lock.RecordFileLock", partial(RecordFileLock, timeout=0.05))
    records = Records()
    key = ResourceKey(path)
    loaded = records.load(key, username="alice", unknown_username="ghost")
    loaded.document.title = "edited"

    with raises(RecordLockedError) as refused:
        records.save(key, loaded.document, loaded.version, username="alice", overwrite=False)

    assert refused.value.holder == other
    assert path.read_bytes() == before
    assert lock.exists()


def test_a_save_waits_for_another_process_s_lock_to_go_and_then_lands(tmp_path: Path) -> None:
    """A save finding another process's fresh lock waits for it, and lands once it is released -- the lock makes a
    writer wait, not only fail.

    **Test steps:**

    * hold the record's lock as another process, released by a thread after a moment
    * save an edit, timing it
    * verify it landed, took at least as long as the hold, and left no lock
    """
    path = tmp_path / "info.rehu"
    write_tutorial(path)
    lock = lock_path_for(path)
    lock.write_text(fresh_other().text(), encoding="utf-8")
    hold = 0.3
    releaser = threading.Timer(hold, lock.unlink)
    records = Records()
    key = ResourceKey(path)
    loaded = records.load(key, username="alice", unknown_username="ghost")
    loaded.document.title = "edited"
    begun = time.monotonic()
    releaser.start()
    try:
        records.save(key, loaded.document, loaded.version, username="alice", overwrite=False)
    finally:
        releaser.join(5)

    assert time.monotonic() - begun >= hold
    assert RehuDocument.load(path).title == "edited"
    assert no_lock_left(tmp_path)


def test_a_merge_write_holds_the_lock_and_leaves_none_when_its_change_fails(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    """A read-merge-write writes under the lock, and a change that refuses leaves no lock behind.

    **Test steps:**

    * merge one per-user field, watching the write
    * verify the lock was there for it and is gone after
    * merge a change that raises, and verify the error comes out and no lock is left
    """
    path = tmp_path / "info.rehu"
    write_tutorial(path)
    seen = watching_writes(mocker, "rehuco_core.rehu_document")

    merge_write(path, lambda doc: doc.set_user_field("bob", "viewed", True), username="alice", touch_updated=False)

    assert seen == [True]
    assert no_lock_left(tmp_path)

    def refuse(_: object) -> None:
        """Refuse the change.

        :raises ValueError: always.
        """
        raise ValueError("refused")

    with raises(ValueError, match="refused"):
        merge_write(path, refuse, username="alice", touch_updated=False)

    assert no_lock_left(tmp_path)


def test_a_conversion_writes_the_new_record_under_its_lock(tmp_path: Path, mocker: MockerFixture) -> None:
    """A ``.tc`` conversion is a writer like any other: the new ``.rehu`` is written under its lock.

    **Test steps:**

    * convert a ``.tc``, watching the record's write
    * verify the lock was there for it and is gone after
    """
    tc_path = tmp_path / "info.tc"
    tc_path.write_text(TC_YAML, encoding="utf-8")
    seen = watching_writes(mocker, "rehuco_core.rehu_document")

    Records().convert(
        ResourceKey(tc_path),
        keep_backups=False,
        overwrite=False,
        username="alice",
        excluded_patterns=EXCLUDED_FILE_PATTERNS,
        screenshot_name_patterns=SCREENSHOT_NAME_PATTERNS,
        deleter=DEFAULT_DELETER,
    )

    assert seen == [True]
    assert no_lock_left(tmp_path)


def test_every_checksum_write_holds_the_checksum_record_s_lock(tmp_path: Path, mocker: MockerFixture) -> None:
    """A generate, a verify and a forget each write the ``.checksum`` under ``info.checksum.lock``, and leave none.

    **Test steps:**

    * put a record and a video in a folder, watching the checksum record's writes
    * generate, verify after changing the video's bytes, and forget the video's entry
    * verify each write found the lock there, and no lock is left
    """
    record = tmp_path / "info.rehu"
    write_tutorial(record)
    (tmp_path / "lesson.mp4").write_bytes(b"a lesson")
    seen = watching_writes(mocker, "rehuco_core.checksum_record")

    generate_checksums(record)
    (tmp_path / "lesson.mp4").write_bytes(b"a lesson, rotted")
    verify_checksums(record)
    forget_checksums(record, only=["lesson.mp4"])

    assert seen == [True, True, True]
    assert no_lock_left(tmp_path)


def test_a_checksum_write_is_refused_while_another_process_holds_its_lock(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    """A forget that cannot take the checksum record's lock in its time fails naming the holder, and writes nothing.

    **Test steps:**

    * generate a record's checksums, then hold ``info.checksum.lock`` as another machine, and shorten the wait
    * forget an entry
    * verify a ``RecordLockedError`` naming the holder, and the record unchanged
    """
    record = tmp_path / "info.rehu"
    write_tutorial(record)
    (tmp_path / "lesson.mp4").write_bytes(b"a lesson")
    generate_checksums(record)
    checksums = checksum_record_path(record)
    before = checksums.read_bytes()
    other = fresh_other()
    lock_path_for(checksums).write_text(other.text(), encoding="utf-8")
    mocker.patch("rehuco_core.record_file_lock.RecordFileLock", partial(RecordFileLock, timeout=0.05))

    with raises(RecordLockedError) as refused:
        forget_checksums(record, only=["lesson.mp4"])

    assert refused.value.holder == other
    assert checksums.read_bytes() == before


def legacy_resource(folder: Path) -> Path:
    """A record, a video and an ``info.sfv`` claiming the video's CRC-32, in ``folder``.

    :param folder: where.
    :returns: the record.
    """
    record = folder / "info.rehu"
    write_tutorial(record)
    video = b"a lesson"
    (folder / "lesson.mp4").write_bytes(video)
    (folder / "info.sfv").write_text(f"lesson.mp4 {zlib.crc32(video):08X}\n", encoding="utf-8")
    return record


def test_a_seed_meeting_a_record_written_meanwhile_leaves_it_alone(tmp_path: Path, mocker: MockerFixture) -> None:
    """A record another writer created after the seed looked and before it wrote is the record now: the seed writes
    nothing and retires no manifest.

    **Test steps:**

    * put a record, a video and an ``info.sfv``; have a ``.checksum`` appear while the manifest is read
    * seed
    * verify nothing was seeded, the other writer's record is as written, and the manifest is still live
    """
    record = legacy_resource(tmp_path)
    checksums = checksum_record_path(record)
    theirs = '{"version": 1, "files": []}\n'
    real_seed = seed_from_legacy_manifest

    def seed_then_someone_writes(*args: Any) -> Any:
        """Read the manifest, then let another writer create the record.

        :param args: the seed's.
        :returns: the seed.
        """
        seed = real_seed(*args)
        checksums.write_text(theirs, encoding="utf-8")
        return seed

    mocker.patch("rehuco_core.checksum_seeding.seed_from_legacy_manifest", side_effect=seed_then_someone_writes)

    assert seed_checksum_record(record) is None
    assert checksums.read_text(encoding="utf-8") == theirs
    assert (tmp_path / "info.sfv").exists()


def test_a_remediation_whose_record_vanished_writes_nothing(tmp_path: Path, mocker: MockerFixture) -> None:
    """A record deleted after the remediation found it is not re-created from the manifest's claims alone.

    **Test steps:**

    * put a record with a ``.checksum``, a video and an ``info.sfv``; have the ``.checksum`` deleted while the
      manifest is read
    * remediate
    * verify nothing was done: no record, and the manifest is still live
    """
    record = legacy_resource(tmp_path)
    checksums = checksum_record_path(record)
    checksums.write_text('{"version": 1, "files": []}\n', encoding="utf-8")
    real_seed = seed_from_legacy_manifest

    def seed_then_someone_deletes(*args: Any) -> Any:
        """Read the manifest, then let another writer delete the record.

        :param args: the seed's.
        :returns: the seed.
        """
        seed = real_seed(*args)
        checksums.unlink()
        return seed

    mocker.patch("rehuco_core.checksum_seeding.seed_from_legacy_manifest", side_effect=seed_then_someone_deletes)

    assert remediate_legacy_manifest(record) is None
    assert not checksums.exists()
    assert (tmp_path / "info.sfv").exists()


def test_a_prune_of_a_record_that_is_gone_says_so(tmp_path: Path, caplog: LogCaptureFixture) -> None:
    """Claims moved out of a record deleted meanwhile have nowhere to be pruned from: the prune fails, and says so.

    **Test steps:**

    * prune a claim from a ``.checksum`` that is not there
    * verify it reports no prune, with a warning
    """
    source = tmp_path / "info.checksum"
    moved = {"pack.zip": CoveringRecord(tmp_path / "pack.rehu", "pack.zip")}

    assert not prune_claims(source, moved, RenameCoordinator())
    assert any("still lists the checksums that moved out of it" in message for message in caplog.messages)


def test_a_rehuco_save_holds_its_lock(tmp_path: Path, mocker: MockerFixture) -> None:
    """A ``.rehuco`` is saved under its own lock file, like a record ([[mounts-and-storage#rehuco-scope]]).

    **Test steps:**

    * save a new ``.rehuco``, watching the write
    * verify ``home.rehuco.lock`` was there for it and is gone after
    """
    seen = watching_writes(mocker, "rehuco_core.rehuco_file")

    RehucoFile.new().save(tmp_path / "home.rehuco")

    assert seen == [True]
    assert no_lock_left(tmp_path)


# endregion

# region Left out


def test_a_lock_is_no_content_but_a_tutorial_s_own_lock_file_is(tmp_path: Path) -> None:
    """The content walk -- sizes, checksums, videos -- leaves a record's lock out and keeps every other ``.lock``.

    **Test steps:**

    * put a record, its lock and its checksum record's, a ``yarn.lock`` and a video in a folder
    * verify the walk finds the video and the ``yarn.lock`` only
    """
    record = tmp_path / "info.rehu"
    write_tutorial(record)
    for name in ("info.rehu.lock", "info.checksum.lock", "yarn.lock", "lesson.mp4"):
        (tmp_path / name).write_bytes(b"x")

    found = enumerate_content_files(record).files

    assert sorted(path.name for path in found) == ["lesson.mp4", "yarn.lock"]


def test_a_listing_never_shows_a_lock(tmp_path: Path) -> None:
    """The Files listing and the Roots view leave a record's lock out altogether; a ``yarn.lock`` is content.

    **Test steps:**

    * put a record, its lock and a ``yarn.lock`` in a folder
    * classify the folder from the record
    * verify the record and the ``yarn.lock`` are listed, and the lock is not
    """
    record = tmp_path / "info.rehu"
    write_tutorial(record)
    (tmp_path / "info.rehu.lock").write_bytes(b"")
    (tmp_path / "yarn.lock").write_bytes(b"")

    listing = DirectoryClassifier(record).classify(tmp_path)

    assert {entry.name: entry.kind for entry in listing.entries} == {
        "info.rehu": FileKind.OWN_RECORD,
        "yarn.lock": FileKind.CONTENT,
    }


def test_the_notifier_says_nothing_of_a_lock(tmp_path: Path) -> None:
    """A lock taken and removed by a save is no one's business; the save itself still is.

    **Test steps:**

    * coalesce a lock's creation, write and removal around an atomic save of the record
    * verify what is published is exactly what the save alone publishes: the record changed
    """
    record = tmp_path / "info.rehu"
    lock = lock_path_for(record)
    temporary = tmp_path / "info.rehu.abcd1234.tmp"
    save = [RawChange(RawChangeKind.CREATED, temporary), RawChange(RawChangeKind.MOVED, temporary, record)]
    batch = [
        RawChange(RawChangeKind.CREATED, lock),
        RawChange(RawChangeKind.MODIFIED, lock),
        *save,
        RawChange(RawChangeKind.DELETED, lock),
    ]

    events = ChangeCoalescer.events_of(batch, tmp_path, None)

    assert events == ChangeCoalescer.events_of(save, tmp_path, None)
    assert Changed((ResourceKey(record),)) in events


def test_a_rename_leaves_this_process_s_lock_behind(tmp_path: Path) -> None:
    """A lock is no part of the record's file set: a file-scoped rename moves the record and its content, and a lock
    beside it stays under the old name.

    **Test steps:**

    * put ``lesson.rehu``, ``lesson.mp4`` and a lock this process holds in a folder
    * rename the record to ``intro``
    * verify the record and its video moved, and the lock did not
    """
    record = tmp_path / "lesson.rehu"
    write_tutorial(record)
    (tmp_path / "lesson.mp4").write_bytes(b"x")
    own = LockHolder("alice", socket.gethostname(), os.getpid(), "rehuco-agent", datetime.now(UTC))
    lock_path_for(record).write_text(own.text(), encoding="utf-8")

    renamed = rename_rehu_resource(record, "intro")

    assert renamed == tmp_path / "intro.rehu"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["intro.mp4", "intro.rehu", "lesson.rehu.lock"]


@mark.parametrize("locked", ["lesson.rehu", "lesson.checksum"])
def test_a_rename_is_refused_while_another_process_holds_the_lock(tmp_path: Path, locked: str) -> None:
    """A save elsewhere -- of the record, or of its checksum record -- is between its re-read and its write: the rename
    refuses, naming the holder, and moves nothing.

    **Test steps:**

    * put a record and a fresh lock another machine holds on ``locked`` in a folder
    * rename the record
    * verify a ``RecordLockedError`` naming the holder, and every file where it was
    """
    record = tmp_path / "lesson.rehu"
    write_tutorial(record)
    lock_path_for(tmp_path / locked).write_text(fresh_other().text(), encoding="utf-8")

    with raises(RecordLockedError, match="bob@elsewhere"):
        rename_rehu_resource(record, "intro")

    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(["lesson.rehu", f"{locked}.lock"])


# endregion
