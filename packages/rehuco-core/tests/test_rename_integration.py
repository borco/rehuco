"""The whole of #241, against a real filesystem: a queue job hashes a real file while the folder is
really renamed underneath it.

Everything mid-read elsewhere in this suite runs over a mocked ``Path.rename``, which proves the
*protocol* -- who waits for whom, who re-opens where -- and proves nothing about the operating system.
The claim this issue stands on is stronger: that once the reader stands aside, **NTFS actually permits
the rename it would otherwise refuse with a live handle beneath the directory**. Only a real disk can
say so, which is what the ``disk`` marker is for; on POSIX the same test passes trivially (the handle
never has to close), so it runs everywhere and asserts the OS-critical half where it exists.

The stack is real end to end: a :class:`~rehuco_core.TaskJobBase` job in a real
:class:`~rehuco_core.TaskQueue` worker thread, reading through
:func:`~rehuco_core.read_content_chunks` over a :class:`~rehuco_core.RenameCoordinator`, with the
coordinator's notification wired to :meth:`~rehuco_core.TaskQueue.resync_sources` exactly as
``MainWindow`` wires it. What is asserted is what a user would see: the digest is byte-identical to an
uninterrupted pass, the files are at the new location, the job finished, and its row names the folder
the work actually ended in.
"""

import hashlib
from pathlib import Path
from threading import Event, Semaphore
from time import monotonic
from typing import Final

from concurrency import SETTLE, running, wait_until
from pytest import mark
from rehuco_core import (
    INFO_REHU_FILENAME,
    JobControl,
    JobState,
    RenameCoordinator,
    TaskJobBase,
    TaskQueue,
    read_content_chunks,
)

PAYLOAD: Final = bytes(range(256)) * 1024
"""256 KiB of real bytes -- large enough for many chunks, small enough to write per test."""

CHUNK: Final = 4096

EXPECTED_DIGEST: Final = hashlib.sha256(PAYLOAD).hexdigest()
"""What the job must produce however many times the folder moves: the digest of an uninterrupted
pass, computed independently of everything under test."""


class HashingJob(TaskJobBase):
    """A real job hashing one content file through the rename-aware reader (#241).

    The shape #203's checksum job will have, reduced to what this test needs: it holds a
    :class:`~rehuco_core.ResourceLocation` rather than paths, answers :attr:`source` from it live --
    which is what :meth:`~rehuco_core.TaskQueue.resync_sources` re-reads, on another thread, while
    ``run`` executes -- and can be parked between chunks so the test can land a rename mid-file
    deterministically rather than by racing.

    :param coordinator: the barrier to read through.
    :param record_path: the resource's ``info.rehu``, tracked so ``source`` follows a rename.
    :param content_path: the file to hash, tracked so the read follows one too.
    """

    def __init__(self, coordinator: RenameCoordinator, record_path: Path, content_path: Path) -> None:
        super().__init__()
        self.label = "Hash content"
        self.__coordinator: Final = coordinator
        self.__record: Final = coordinator.track(record_path)
        self.__content: Final = coordinator.track(content_path)
        self.__permits: Final = Semaphore(0)
        self.parked: Final = Event()
        """Set once the first chunk has been hashed and the job is waiting to be let on."""
        self.digest = ""
        """The finished hash, written by ``run`` on its way out."""

    @property
    def source(self) -> Path | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """Where this job's work is right now -- the tracked record, not a path cached at enqueue."""
        return self.__record.path

    def step(self, chunks: int) -> None:
        """Let the job hash ``chunks`` more chunks.

        :param chunks: how many to allow.
        """
        for _ in range(chunks):
            self.__permits.release()

    def run(self, control: JobControl) -> None:
        """Hash the tracked content file, chunk by chunk, parking after each.

        :param control: the engine's face to this job.
        """
        digest = hashlib.sha256()
        done = 0
        for chunk in read_content_chunks(self.__content, self.__coordinator, CHUNK):
            self.checkpoint()
            digest.update(chunk)
            done += len(chunk)
            control.report(done, len(PAYLOAD))
            self.parked.set()
            # a *timed* acquire, which `with` cannot express: the timeout is what keeps a test that
            # never steps the job from hanging the suite instead of failing
            self.__permits.acquire(timeout=SETTLE)  # pylint: disable=consider-using-with
        self.digest = digest.hexdigest()


def make_resource(root: Path, name: str) -> tuple[Path, Path]:
    """Write a real directory-scoped resource under ``root``.

    :param root: where to create it.
    :param name: the folder's name.
    :returns: the ``info.rehu`` path and the content file's path.
    """
    folder = root / name
    folder.mkdir()
    record = folder / INFO_REHU_FILENAME
    record.write_text("{}", encoding="utf-8")
    content = folder / "content.zip"
    content.write_bytes(PAYLOAD)
    return record, content


def rename_parked(job: HashingJob, coordinator: RenameCoordinator, record: Path, new_name: str) -> float:
    """Rename ``record`` while ``job`` is parked mid-file, and say how long the standing-aside took.

    The same arrangement ``test_content_reading.rename_while_parked`` uses, against a real disk: the
    rename runs on a background thread because it *must* wait for the reader's next boundary, and a
    parked job only reaches one when stepped -- calling it synchronously here would deadlock the test
    with itself, which is precisely what an unparked, continuously-hashing job never does.

    :param job: the parked job.
    :param coordinator: the barrier both are using.
    :param record: the resource's current ``info.rehu``.
    :param new_name: what to rename it to.
    :returns: the seconds from the reader being let take its step to the rename landing -- the honest
        measure of "a rename waits one chunk", with the test's own deliberate parking excluded.
    """
    landed = Event()
    with running(lambda: (coordinator.rename(record, new_name), landed.set())):
        assert wait_until(lambda: coordinator.yield_wanted)
        started = monotonic()
        job.step(1)
        assert landed.wait(SETTLE)
        return monotonic() - started


@mark.disk
def test_a_real_rename_lands_mid_hash_and_the_job_survives_it(tmp_path: Path) -> None:
    """A directory really renames on disk while a queued job is really hashing a file inside it, and
    everything a user would look at afterwards is right (#241).

    **Test steps:**

    * write a real resource and enqueue a real hashing job over it, wired the way the app wires it
    * park the job mid-file and land a rename, timing the standing-aside
    * let the job finish; check the digest, the disk, the job's outcome, its ``source``, and that the
      rename cost one chunk's worth of waiting rather than the job's
    """
    record, content = make_resource(tmp_path, "old_folder")
    coordinator = RenameCoordinator()
    queue = TaskQueue()
    coordinator.add_rename_listener(queue.resync_sources)  # exactly MainWindow's wiring
    job = HashingJob(coordinator, record, content)
    try:
        serial = queue.enqueue(job)
        assert queue.jobs()[0].source == record
        assert job.parked.wait(SETTLE)

        rename_cost = rename_parked(job, coordinator, record, "new_name")
        renamed = tmp_path / "new_name" / INFO_REHU_FILENAME
        job.step(len(PAYLOAD) // CHUNK + 1)
        assert wait_until(lambda: queue.jobs()[0].state is JobState.DONE)

        assert job.digest == EXPECTED_DIGEST
        assert renamed.is_file()
        assert (tmp_path / "new_name" / "content.zip").read_bytes() == PAYLOAD
        assert not (tmp_path / "old_folder").exists()
        status = queue.jobs()[0]
        assert status.serial == serial
        assert status.source == renamed
        # the promise made to the rename: it waits one chunk, not one job. A second is two orders of
        # magnitude above the ~7 ms measured, and far below what waiting for the file would cost.
        assert rename_cost < 1.0
    finally:
        job.step(len(PAYLOAD) // CHUNK + 2)  # a failed assertion must not strand the worker parked
        queue.shutdown()


@mark.disk
def test_three_real_renames_during_one_hash_still_yield_the_right_digest(tmp_path: Path) -> None:
    """The folder moves three times during one job and the bytes still come out exactly right.

    A rename is not a once-per-job event -- a user reorganizing a catalog mid-sweep may move the same
    resource repeatedly, and each move must cost one chunk and corrupt nothing.

    **Test steps:**

    * park a real hashing job mid-file and rename the real folder three times, stepping between
    * let it finish; check the digest and that the files ended under the last name
    """
    record, content = make_resource(tmp_path, "old_folder")
    coordinator = RenameCoordinator()
    queue = TaskQueue()
    coordinator.add_rename_listener(queue.resync_sources)
    job = HashingJob(coordinator, record, content)
    try:
        queue.enqueue(job)
        assert job.parked.wait(SETTLE)

        moved = record
        for name in ("first", "second", "third"):
            rename_parked(job, coordinator, moved, name)
            moved = tmp_path / name / INFO_REHU_FILENAME
        job.step(len(PAYLOAD) // CHUNK + 1)
        assert wait_until(lambda: queue.jobs()[0].state is JobState.DONE)

        assert job.digest == EXPECTED_DIGEST
        assert (tmp_path / "third" / "content.zip").read_bytes() == PAYLOAD
        assert queue.jobs()[0].source == tmp_path / "third" / INFO_REHU_FILENAME
    finally:
        job.step(len(PAYLOAD) // CHUNK + 2)
        queue.shutdown()


@mark.disk
@mark.windows
def test_the_reader_really_is_what_lets_the_rename_through(tmp_path: Path) -> None:
    """On Windows, the same rename that succeeds after the reader stands aside is genuinely refused
    while a plain handle is open -- so the barrier is doing real work, not decorating a rename that
    would have succeeded anyway.

    The control half of the tests above. Without it, a regression that quietly stopped the reader
    closing its handle would still pass them on a filesystem that never refuses.

    **Test steps:**

    * hold a plain ``open`` on the content file and check the directory rename is refused
    * release it, and check the same rename through a coordinator with no readers succeeds
    """
    record, content = make_resource(tmp_path, "old_folder")
    coordinator = RenameCoordinator()

    with content.open("rb"):
        refused = False
        try:
            (tmp_path / "old_folder").rename(tmp_path / "new_name")
        except OSError:
            refused = True
        assert refused

    assert coordinator.rename(record, "new_name") == tmp_path / "new_name" / INFO_REHU_FILENAME
    assert (tmp_path / "new_name" / "content.zip").read_bytes() == PAYLOAD


@mark.disk
def test_a_rename_started_mid_park_waits_for_the_standing_aside(tmp_path: Path) -> None:
    """Started while the job holds a real handle, the rename blocks until the next chunk boundary and
    then really lands -- the wait is the reader's one step, observed against the real disk.

    **Test steps:**

    * park a real job mid-file, start the rename on another thread, and see it has not landed
    * step the job once; check the rename completes and the folder really moved
    """
    record, content = make_resource(tmp_path, "old_folder")
    coordinator = RenameCoordinator()
    queue = TaskQueue()
    coordinator.add_rename_listener(queue.resync_sources)
    job = HashingJob(coordinator, record, content)
    landed = Event()
    try:
        queue.enqueue(job)
        assert job.parked.wait(SETTLE)

        with running(lambda: (coordinator.rename(record, "new_name"), landed.set())):
            assert wait_until(lambda: coordinator.yield_wanted)
            assert landed.wait(0.05) is False
            assert (tmp_path / "old_folder").exists()

            job.step(1)

            assert landed.wait(SETTLE)
            assert (tmp_path / "new_name").is_dir()
        job.step(len(PAYLOAD) // CHUNK + 1)
        assert wait_until(lambda: queue.jobs()[0].state is JobState.DONE)
        assert job.digest == EXPECTED_DIGEST
    finally:
        job.step(len(PAYLOAD) // CHUNK + 2)
        queue.shutdown()
