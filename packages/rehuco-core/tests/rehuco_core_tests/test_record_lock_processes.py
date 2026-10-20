"""Two processes writing one record at once (#512, [[sync#lock-file]]): every edit either lands or comes back as a
conflict, none is silently lost, and a progress write never conflicts with a details edit.

Real processes on one ``tmp_path`` folder: the workers are this module's functions, started with ``spawn`` so they
behave the same on every OS. Coverage is not measured in them; every branch they reach is also reached in process
(``test_record_file_lock``).
"""

import json
import time
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from pathlib import Path
from typing import Any, Final

from rehuco_core import (
    RecordConflict,
    RecordLockedError,
    Records,
    RehuDocument,
    ResourceKey,
    checksum_record_path,
    current_block_version,
    forget_checksums,
    generate_checksums,
    lock_path_for,
    record_progress,
    update_checksum_record,
    verify_checksums,
)

WRITERS: Final = 2
"""How many processes race the details."""

ATTEMPTS: Final = 40
"""How many saves each one makes."""

START_DELAY: Final = 3.0
"""How long after submitting the workers they start writing, in seconds: long enough for both to be spawned and to
have imported everything, so they overlap."""

RESULT_TIMEOUT: Final = 120.0
"""How long to wait for a worker, in seconds, before the test fails rather than hangs."""


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


def save_titles(path: str, worker: int, start_at: float) -> dict[str, Any]:
    """Load the record, set its title and save it, :data:`ATTEMPTS` times, starting at ``start_at`` -- a worker.

    A load that lands on another process's replace reads nothing (Windows refuses the open meanwhile) and is not an
    attempt at a save.

    :param path: the record.
    :param worker: which worker this is, to make each title unique.
    :param start_at: when to start, in seconds since the epoch.
    :returns: each landed save's base version and title, and how many conflicted, waited out the lock, or read nothing.
    """
    records = Records()
    key = ResourceKey(Path(path))
    landed: list[tuple[str, str]] = []
    conflicts = locked = unread = 0
    time.sleep(max(0.0, start_at - time.time()))
    for attempt in range(ATTEMPTS):
        loaded = records.load(key, username="alice", unknown_username="ghost")
        if loaded.version is None:
            unread += 1
            continue
        title = f"w{worker}-{attempt}"
        loaded.document.title = title
        try:
            records.save(key, loaded.document, loaded.version, username="alice", overwrite=False)
        except RecordConflict:
            conflicts += 1
        except RecordLockedError:
            locked += 1
        else:
            landed.append((loaded.version.file_hash, title))
    return {"landed": landed, "conflicts": conflicts, "locked": locked, "unread": unread}


def write_progress(path: str, start_at: float) -> int:
    """Record progress on :data:`ATTEMPTS` different files of the record, starting at ``start_at`` -- a worker.

    :param path: the record.
    :param start_at: when to start, in seconds since the epoch.
    :returns: how many were written.
    """
    time.sleep(max(0.0, start_at - time.time()))
    for attempt in range(ATTEMPTS):
        record_progress(Path(path), "bob", f"part{attempt}.mp4", 1.0, 10.0, current_username="bob")
    return ATTEMPTS


def verify_paused(path: str, started: str, proceed: str) -> list[dict[str, Any]]:
    """Verify one file of the record, pausing after its first chunk until told to go on -- a worker.

    :param path: the record.
    :param started: a file to create once the run has read its record and begun hashing.
    :param proceed: a file whose appearance lets the run finish.
    :returns: the entries the run left in the record.
    """
    paused: list[bool] = []

    def gate(done: int, total: int | None) -> None:
        """Pause on the first report, until :data:`proceed` appears.

        :param done: bytes hashed so far.
        :param total: bytes expected.
        """
        del done, total
        if paused:
            return
        paused.append(True)
        Path(started).touch()
        deadline = time.monotonic() + RESULT_TIMEOUT
        while not Path(proceed).exists() and time.monotonic() < deadline:
            time.sleep(0.01)

    verify_checksums(Path(path), only=["lesson.mp4"], progress=gate)
    return json.loads(checksum_record_path(Path(path)).read_text(encoding="utf-8"))["files"]


def test_a_verify_keeps_what_another_writer_put_in_the_record_while_it_hashed(tmp_path: Path) -> None:
    """A verify reads its ``.checksum`` when it starts and writes it when it ends; what another process wrote there
    in between -- an entry forgotten, a claim moved in -- survives, beside the verify's own new verdict.

    **Test steps:**

    * generate checksums for a lesson and a note, then start a process verifying the lesson, paused mid-hash
    * meanwhile, forget the note's entry and move a claim for ``pack.zip`` into the record
    * let the verify finish
    * verify the record holds the lesson re-checked, the claim, and no note; and no lock is left
    """
    record = tmp_path / "info.rehu"
    write_tutorial(record)
    (tmp_path / "lesson.mp4").write_bytes(b"a lesson" * 1000)
    (tmp_path / "notes.txt").write_bytes(b"a note")
    generate_checksums(record)
    started = tmp_path / "started.flag"
    proceed = tmp_path / "proceed.flag"
    claim = {"name": "pack.zip", "crc32": "0123abcd"}

    with ProcessPoolExecutor(max_workers=1, mp_context=get_context("spawn")) as pool:
        verify = pool.submit(verify_paused, str(record), str(started), str(proceed))
        deadline = time.monotonic() + RESULT_TIMEOUT
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert started.exists()
        assert forget_checksums(record, only=["notes.txt"]) == ("notes.txt",)

        def claim_moved_in(current: dict[str, Any] | None) -> dict[str, Any]:
            """The record with the claim added, as a hand-over writes it.

            :param current: the record now.
            :returns: what to write.
            """
            assert current is not None
            return {**current, "files": [*current["files"], claim]}

        update_checksum_record(checksum_record_path(record), claim_moved_in)
        proceed.touch()
        entries = verify.result(timeout=RESULT_TIMEOUT)

    by_name = {entry["name"]: entry for entry in entries}
    assert set(by_name) == {"lesson.mp4", "pack.zip"}
    assert by_name["lesson.mp4"]["status"] == "matched"
    assert by_name["pack.zip"] == claim
    assert not lock_path_for(checksum_record_path(record)).exists()


def test_racing_saves_each_land_or_conflict_and_none_is_lost(tmp_path: Path) -> None:
    """Two processes saving one record's details at once: each save either lands on the file as it was read, or is
    refused as a conflict -- never two saves landing on the same version, which is one silently writing the other's
    edit away.

    **Test steps:**

    * write a record, and start two processes that each load, retitle and save it 40 times at once
    * verify every attempt is a landed save, a conflict or a load that read nothing, and none waited out the lock
    * verify no two landed saves were based on the same version, the file holds the title one of them wrote, and no
      lock is left
    """
    path = tmp_path / "info.rehu"
    write_tutorial(path)
    start_at = time.time() + START_DELAY

    with ProcessPoolExecutor(max_workers=WRITERS, mp_context=get_context("spawn")) as pool:
        futures = [pool.submit(save_titles, str(path), worker, start_at) for worker in range(WRITERS)]
        results = [future.result(timeout=RESULT_TIMEOUT) for future in futures]

    landed = [entry for result in results for entry in result["landed"]]
    bases = [base for base, _ in landed]
    outcomes = sum(len(result["landed"]) + result["conflicts"] + result["unread"] for result in results)
    assert outcomes == WRITERS * ATTEMPTS
    assert sum(result["locked"] for result in results) == 0
    assert len(bases) == len(set(bases))
    assert RehuDocument.load(path).title in {title for _, title in landed}
    assert not lock_path_for(path).exists()


def test_a_progress_write_never_conflicts_with_a_details_edit(tmp_path: Path) -> None:
    """A process recording progress while another edits the record's details: the details saves merge the progress
    in rather than conflicting, and every progress entry is on disk at the end.

    **Test steps:**

    * write a record, and start one process saving its title 40 times and one recording progress on 40 files
    * verify no save conflicted, and all 40 progress entries are on disk with the last title landed
    """
    path = tmp_path / "info.rehu"
    write_tutorial(path)
    start_at = time.time() + START_DELAY

    with ProcessPoolExecutor(max_workers=2, mp_context=get_context("spawn")) as pool:
        saves = pool.submit(save_titles, str(path), 0, start_at)
        progress = pool.submit(write_progress, str(path), start_at)
        result = saves.result(timeout=RESULT_TIMEOUT)
        written = progress.result(timeout=RESULT_TIMEOUT)

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert result["conflicts"] == 0
    assert result["locked"] == 0
    assert len(saved["tutorial"]["users"]["bob"]["progress"]) == written
    assert RehuDocument.load(path).title == result["landed"][-1][1]
