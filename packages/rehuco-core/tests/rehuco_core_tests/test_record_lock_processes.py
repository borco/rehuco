"""Two processes writing one record at once (#512, [[sync#lock-file]]): an edit made on a stale version comes back as
a conflict rather than writing over another, and a progress write never conflicts with a details edit.

Real processes on one ``tmp_path`` folder: the workers are this module's functions, started with ``spawn`` so they
behave the same on every OS. Every test fixes the order the two processes act in (#547): a worker pauses at a named
point until a flag file tells it to go on, never left to the scheduler. Coverage is not measured in them; every
branch they reach is also reached in process (``test_record_file_lock``).
"""

import json
import time
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from pathlib import Path
from typing import Any, Final
from unittest.mock import patch

from pytest import raises
from pytest_mock import MockerFixture
from rehuco_core import (
    RecordConflict,
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


def wait_for(flag: Path) -> None:
    """Wait until ``flag`` exists, for at most :data:`RESULT_TIMEOUT` seconds.

    :param flag: the file another process creates to say it reached a point.
    """
    deadline = time.monotonic() + RESULT_TIMEOUT
    while not flag.exists() and time.monotonic() < deadline:
        time.sleep(0.01)


def save_holding_the_lock(path: str, holding: str, proceed: str) -> str:
    """Retitle the record and save it, pausing inside the save -- the lock taken, the file not yet written -- until
    told to go on: a worker.

    :param path: the record.
    :param holding: a file to create once the save holds the lock.
    :param proceed: a file whose appearance lets the save write.
    :returns: the title saved.
    """
    records = Records()
    key = ResourceKey(Path(path))
    loaded = records.load(key, username="alice", unknown_username="ghost")
    loaded.document.title = "worker"
    write = RehuDocument.save

    def write_when_told(document: RehuDocument, *args: Any, **kwargs: Any) -> None:
        """Say the lock is held, wait to be told, then write.

        :param document: the record being saved.
        :param args: the save's own arguments.
        :param kwargs: the save's own keyword arguments.
        """
        Path(holding).touch()
        wait_for(Path(proceed))
        write(document, *args, **kwargs)

    assert loaded.version is not None
    with patch.object(RehuDocument, "save", write_when_told):
        records.save(key, loaded.document, loaded.version, username="alice", overwrite=False)
    return loaded.document.title


def load_then_save(path: str, loaded_flag: str, proceed: str) -> bool:
    """Load the record, say so, wait to be told, then retitle and save it: a worker.

    :param path: the record.
    :param loaded_flag: a file to create once the record is loaded.
    :param proceed: a file whose appearance lets the save run.
    :returns: whether the save landed rather than conflicting.
    """
    records = Records()
    key = ResourceKey(Path(path))
    loaded = records.load(key, username="alice", unknown_username="ghost")
    assert loaded.version is not None
    Path(loaded_flag).touch()
    wait_for(Path(proceed))
    loaded.document.title = "worker"
    try:
        records.save(key, loaded.document, loaded.version, username="alice", overwrite=False)
    except RecordConflict:
        return False
    return True


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
        wait_for(Path(proceed))

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
        wait_for(started)
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


def test_a_save_waiting_on_the_lock_is_refused_once_the_holder_wrote_over_its_version(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    """A save that meets another process's lock waits for it, and is then judged against what that process wrote: its
    edit was made on the version before, so it comes back as a conflict rather than writing over the other's.

    **Test steps:**

    * write a record and load it here
    * start a process that retitles and saves it, paused inside the save while it holds the lock
    * retitle and save here: the save backs off on the held lock, and the first back-off lets the process write
    * verify the save here was refused as a conflict after backing off, the file holds the process's title, and no lock
      is left
    """
    path = tmp_path / "info.rehu"
    write_tutorial(path)
    holding = tmp_path / "holding.flag"
    proceed = tmp_path / "proceed.flag"
    records = Records()
    key = ResourceKey(path)
    loaded = records.load(key, username="alice", unknown_username="ghost")
    assert loaded.version is not None
    sleep = time.sleep

    def let_the_holder_write(seconds: float) -> None:
        """Back off as the lock does, having told the holder to go on.

        :param seconds: how long.
        """
        proceed.touch()
        sleep(seconds)

    with ProcessPoolExecutor(max_workers=1, mp_context=get_context("spawn")) as pool:
        holder = pool.submit(save_holding_the_lock, str(path), str(holding), str(proceed))
        wait_for(holding)
        assert holding.exists()
        back_off = mocker.patch.object(time, "sleep", side_effect=let_the_holder_write)
        loaded.document.title = "here"
        try:
            with raises(RecordConflict):
                records.save(key, loaded.document, loaded.version, username="alice", overwrite=False)
        finally:
            # a save that never met the lock never told the holder to go on: release it, so a failure is reported
            # at once rather than after the holder's wait runs out
            proceed.touch()
        mocker.stopall()
        written = holder.result(timeout=RESULT_TIMEOUT)

    assert back_off.call_count >= 1
    assert RehuDocument.load(path).title == written == "worker"
    assert not lock_path_for(path).exists()


def test_a_progress_write_never_conflicts_with_a_details_edit(tmp_path: Path) -> None:
    """Progress recorded by another process between a details edit's load and its save is merged into that save
    rather than conflicting with it, and kept.

    **Test steps:**

    * write a record, and start a process that loads it and waits
    * record progress here, then let the process retitle and save
    * verify its save landed, and the file holds both the title and the progress
    """
    path = tmp_path / "info.rehu"
    write_tutorial(path)
    loaded = tmp_path / "loaded.flag"
    proceed = tmp_path / "proceed.flag"

    with ProcessPoolExecutor(max_workers=1, mp_context=get_context("spawn")) as pool:
        saver = pool.submit(load_then_save, str(path), str(loaded), str(proceed))
        wait_for(loaded)
        assert loaded.exists()
        record_progress(path, "bob", "part.mp4", 1.0, 10.0, current_username="bob")
        proceed.touch()
        landed = saver.result(timeout=RESULT_TIMEOUT)

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert landed
    assert RehuDocument.load(path).title == "worker"
    assert set(saved["tutorial"]["users"]["bob"]["progress"]) == {"part.mp4"}
    assert not lock_path_for(path).exists()
