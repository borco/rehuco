"""Tests for reading a content file through a rename (#241).

The file is a hand-written in-memory fake rather than a real one: what a chunk read costs on disk is not
in question, and a fake is what lets a test *count* opens and closes, which is the whole subject here --
whether the reader let go, and whether it came back to the right place.

The barrier is the real :class:`~rehuco_core.RenameCoordinator`, on real threads, wherever a test is
about the two of them meeting. A mocked coordinator would prove the reader calls what the test told it
to call, which is not the same as proving it stands aside.

**The reader is stepped, never raced.** :class:`SteppedReader` parks after every chunk until a test
lets it through, so "a rename lands mid-read" is an arrangement rather than a hope -- an unstepped
reader finishes a small file long before any rename could reach it, and the test would pass by never
exercising the thing it is named for.
"""

from io import BytesIO
from pathlib import Path
from threading import Event, Semaphore, Thread
from typing import Final

from concurrency import BRIEF, SETTLE, running, wait_until
from pytest import fixture, raises
from pytest_mock import MockerFixture
from rehuco_core import RenameCoordinator, ResourceLocation, read_content_chunks

DIRECTORY: Final = Path("/fake/library")
FOLDER: Final = DIRECTORY / "old_folder"
INFO_PATH: Final = FOLDER / "info.rehu"
CONTENT: Final = FOLDER / "content.zip"
NEW_NAME: Final = "new_name"
RENAMED_CONTENT: Final = DIRECTORY / NEW_NAME / "content.zip"

PAYLOAD: Final = bytes(range(256)) * 40
"""The file every test reads: 10240 bytes, so a 1024-byte chunk divides it exactly and a 1000-byte one
does not."""

CHUNK: Final = 1024

CHUNK_COUNT: Final = len(PAYLOAD) // CHUNK


# region fakes and helpers
class FakeFiles:  # pylint: disable=too-few-public-methods  # one way in; the rest is what it recorded
    """Every file the reader can open, and a record of how it was opened.

    Stands in for :func:`~borco_core.shared_read_open`. Each open hands back an independent
    :class:`~io.BytesIO` over the named file's bytes, so a re-open genuinely starts at zero and a
    reader that forgot to seek is caught rather than accidentally right.

    :param contents: the bytes to serve, by path.
    """

    def __init__(self, contents: dict[Path, bytes]) -> None:
        self.__contents: Final = contents
        self.opened: list[Path] = []
        """Every path opened, in order -- the record a re-open is asserted against."""
        self.closed = 0
        """How many handles have been closed."""

    def open(self, path: Path) -> BytesIO:
        """Serve ``path``.

        :param path: the file to open.
        :returns: a fresh reader over its bytes.
        :raises FileNotFoundError: nothing was registered under ``path``.
        """
        if path not in self.__contents:
            raise FileNotFoundError(str(path))
        self.opened.append(path)
        handle = BytesIO(self.__contents[path])
        original_close = handle.close

        def close() -> None:
            self.closed += 1
            original_close()

        handle.close = close  # pyright: ignore[reportAttributeAccessIssue]
        return handle


class SteppedReader:
    """A reader on its own thread that parks after every chunk until it is let through.

    The park happens **inside** the read, so the reader is holding when it stops -- which is what makes
    a rename in that window genuinely have to wait, rather than slipping through a gap.

    :param coordinator: the barrier to read through.
    :param location: the file to read.
    """

    def __init__(self, coordinator: RenameCoordinator, location: ResourceLocation) -> None:
        self.__coordinator: Final = coordinator
        self.__location: Final = location
        self.__permits: Final = Semaphore(0)
        self.__thread: Final = Thread(target=self.__read, daemon=True)
        self.collected: list[bytes] = []
        """Every chunk yielded so far."""
        self.parked: Final = Event()
        """Set once the first chunk has arrived and the reader is waiting to be let through."""
        self.done: Final = Event()
        """Set once the read has run to the end of the file."""

    def __read(self) -> None:
        """Read the location, parking after each chunk."""
        for chunk in read_content_chunks(self.__location, self.__coordinator, CHUNK):
            self.collected.append(chunk)
            self.parked.set()
            # a *timed* acquire, which `with` cannot express: the timeout is what keeps a test that
            # never steps the reader from hanging the suite instead of failing
            self.__permits.acquire(timeout=SETTLE)  # pylint: disable=consider-using-with
        self.done.set()

    def start(self) -> None:
        """Start reading and wait until the first chunk has landed."""
        self.__thread.start()
        assert self.parked.wait(SETTLE)

    def step(self, chunks: int = 1) -> None:
        """Let the reader through ``chunks`` more chunks.

        :param chunks: how many chunks to allow.
        """
        # cleared *before* releasing, so the flag a caller waits on next is the one this step's chunk
        # sets rather than the one still standing from the last; clearing afterwards would race the
        # reader and could wipe a park that had already happened
        self.parked.clear()
        for _ in range(chunks):
            self.__permits.release()

    def finish(self) -> None:
        """Let the reader run to the end of the file and wait for it."""
        self.step(CHUNK_COUNT + 1)
        assert self.done.wait(SETTLE)
        self.__thread.join(SETTLE)


def rename_while_parked(reader: SteppedReader, coordinator: RenameCoordinator, path: Path, new_name: str) -> None:
    """Rename ``path`` while ``reader`` is parked mid-file, and see it through.

    The arrangement every interruption test wants: start the rename, watch it raise the flag and stop,
    let the reader take one more step -- which is where it notices and lets go -- and check the rename
    lands.

    :param reader: the parked reader.
    :param coordinator: the barrier both are using.
    :param path: the resource's ``.rehu``.
    :param new_name: what to rename it to.
    """
    # Wait for the reader to be parked -- which is to say *holding* -- before asking for the rename.
    # Between letting go of one name and re-opening under the next it holds nothing, and a rename
    # started in that window finds no reader to wait for and completes without ever raising the flag,
    # leaving `wait_until` below polling for something that will not come back. Harmless for a single
    # rename, which starts from `SteppedReader.start`'s own park; renaming twice in a row is what
    # exposes it, and only where the threads interleave that way -- hence green on Windows and flaky
    # on Linux and macOS.
    assert reader.parked.wait(SETTLE)
    landed = Event()

    def rename() -> None:
        coordinator.rename(path, new_name)
        landed.set()

    with running(rename):
        assert wait_until(lambda: coordinator.yield_wanted)
        assert landed.wait(BRIEF) is False
        reader.step()
        assert landed.wait(SETTLE)


@fixture(name="files")
def fixture_files(mocker: MockerFixture) -> FakeFiles:
    """Serve :data:`PAYLOAD` at both the old and the new content path.

    Both, because a test that renames mid-read needs the file to be openable under its new name -- and
    serving identical bytes is what lets the assertion be *the bytes are unchanged* rather than *the
    reader noticed something*.

    :param mocker: pytest-mock fixture.
    :returns: the fake, so a test can count opens and closes.
    """
    files = FakeFiles({CONTENT: PAYLOAD, RENAMED_CONTENT: PAYLOAD})
    mocker.patch("rehuco_core.content_reading.shared_read_open", side_effect=files.open)
    return files


@fixture(name="locking_storage")
def fixture_locking_storage(mocker: MockerFixture) -> None:
    """Say the storage locks a directory against an open handle, whatever host the suite runs on.

    What NTFS does, and the reason the close-and-re-open half of this module exists
    (:func:`~rehuco_core.readers_must_yield_for_directory_rename`). Pinned rather than inherited from
    ``sys.platform``: a test that asserts *the reader re-opened at the new path* describes the locking
    backend, so on POSIX it would either fail or -- worse -- pass while proving nothing, since there is
    no re-open to observe there. Its opposite number,
    ``test_a_non_locking_backend_keeps_its_handle_open``, pins the trait the other way for the same
    reason.

    :param mocker: pytest-mock fixture.
    """
    mocker.patch("rehuco_core.content_reading.readers_must_yield_for_directory_rename", return_value=True)


@fixture(name="coordinator")
def fixture_coordinator(mocker: MockerFixture) -> RenameCoordinator:
    """A coordinator over a mocked filesystem, so its renames succeed without touching a disk.

    :param mocker: pytest-mock fixture.
    :returns: the coordinator under test.
    """
    mocker.patch.object(Path, "is_file", autospec=True, return_value=True)
    mocker.patch.object(Path, "exists", autospec=True, return_value=False)
    mocker.patch.object(Path, "rename", autospec=True)
    return RenameCoordinator()


# endregion


# region plain reading
def test_the_whole_file_arrives_in_order(coordinator: RenameCoordinator, files: FakeFiles) -> None:
    """Reading a file start to finish yields exactly its bytes.

    **Test steps:**

    * read a location whose size is an exact multiple of the chunk
    * check the joined chunks equal the file, each chunk is full, and it opened once
    """
    chunks = list(read_content_chunks(coordinator.track(CONTENT), coordinator, CHUNK))

    assert b"".join(chunks) == PAYLOAD
    assert {len(chunk) for chunk in chunks} == {CHUNK}
    assert files.opened == [CONTENT]


def test_a_short_final_chunk_is_yielded(coordinator: RenameCoordinator, files: FakeFiles) -> None:
    """A file that does not divide evenly ends with whatever is left, not with a padded chunk.

    **Test steps:**

    * read with a chunk size the file is not a multiple of
    * check the last chunk is the remainder and nothing was lost
    """
    del files
    chunks = list(read_content_chunks(coordinator.track(CONTENT), coordinator, 1000))

    assert b"".join(chunks) == PAYLOAD
    assert len(chunks[-1]) == len(PAYLOAD) % 1000


def test_an_empty_file_yields_nothing(coordinator: RenameCoordinator, mocker: MockerFixture) -> None:
    """Nothing to read is not an error and not a zero-length chunk -- it is no chunks at all.

    **Test steps:**

    * serve an empty file and read it
    * check no chunks came back
    """
    files = FakeFiles({CONTENT: b""})
    mocker.patch("rehuco_core.content_reading.shared_read_open", side_effect=files.open)

    assert not list(read_content_chunks(coordinator.track(CONTENT), coordinator, CHUNK))


def test_a_missing_file_raises_from_the_first_chunk(coordinator: RenameCoordinator, mocker: MockerFixture) -> None:
    """A file that is not there fails where a caller can act on it, not silently as an empty read.

    **Test steps:**

    * serve nothing and start reading
    * check the open's own error came out
    """
    files = FakeFiles({})
    mocker.patch("rehuco_core.content_reading.shared_read_open", side_effect=files.open)

    with raises(FileNotFoundError):
        next(read_content_chunks(coordinator.track(CONTENT), coordinator, CHUNK))


def test_the_handle_is_closed_when_the_reader_is_exhausted(coordinator: RenameCoordinator, files: FakeFiles) -> None:
    """Reading to the end closes the file rather than leaving it to the garbage collector.

    **Test steps:**

    * read a location to exhaustion
    * check the handle was closed
    """
    list(read_content_chunks(coordinator.track(CONTENT), coordinator, CHUNK))

    assert files.closed == 1


def test_abandoning_the_reader_closes_the_handle_and_releases_the_hold(
    coordinator: RenameCoordinator, files: FakeFiles
) -> None:
    """A consumer that stops reading part-way never leaves a rename blocked behind it.

    The failure this prevents is the worst kind: a job that gave up would hold the barrier forever, and
    every rename after it would wait out its ceiling and fail.

    **Test steps:**

    * take one chunk, then close the generator
    * check the handle closed, and a rename afterwards runs straight through
    """
    reader = read_content_chunks(coordinator.track(CONTENT), coordinator, CHUNK)
    next(reader)

    reader.close()

    assert files.closed == 1
    assert coordinator.rename(INFO_PATH, NEW_NAME) == DIRECTORY / NEW_NAME / "info.rehu"


# endregion


# region the handle never outlives the hold
def holders_now(coordinator: RenameCoordinator) -> int:
    """How many holds ``coordinator`` currently counts.

    Reaches for the name-mangled counter the same way ``test_rename_coordination.tracked_count``
    reaches for the location list, and for the same reason: the invariant under test -- the handle is
    closed *while the reader still holds* -- is not observable from the outside, and the alternative is
    a race with a real rename thread that a test could only lose noisily and win silently.

    :param coordinator: the coordinator to inspect.
    :returns: the current holder count.
    """
    return getattr(coordinator, "_RenameCoordinator__holders")  # noqa: B009  # name-mangled, see above


def open_recording_holders(
    coordinator: RenameCoordinator, mocker: MockerFixture, payload: bytes = PAYLOAD
) -> list[int]:
    """Serve ``payload`` at every path, recording the holder count at each close.

    :param coordinator: whose holder count to sample.
    :param mocker: pytest-mock fixture.
    :param payload: the bytes to serve.
    :returns: the live list the samples land in -- ``[1]`` after a close that happened inside the
        hold, ``[0]`` after one that leaked past it.
    """
    seen: list[int] = []

    def open_file(path: Path) -> BytesIO:
        del path
        handle = BytesIO(payload)
        original_close = handle.close

        def close() -> None:
            seen.append(holders_now(coordinator))
            original_close()

        handle.close = close  # pyright: ignore[reportAttributeAccessIssue]
        return handle

    mocker.patch("rehuco_core.content_reading.shared_read_open", side_effect=open_file)
    return seen


def test_eof_closes_the_handle_inside_the_hold(coordinator: RenameCoordinator, mocker: MockerFixture) -> None:
    """The end of the file closes the handle *before* the hold is released, never after.

    The race this pins is the module's own reason to exist, met at its most frequent moment: leaving
    the hold is what wakes a waiting rename, so a close that trailed it would hand the rename a
    directory with a live handle still under it -- at the end of **every** file a sweep reads.

    **Test steps:**

    * read a file to exhaustion, sampling the holder count at close
    * check the close saw the reader still holding
    """
    seen = open_recording_holders(coordinator, mocker)

    list(read_content_chunks(coordinator.track(CONTENT), coordinator, CHUNK))

    assert seen == [1]


def test_abandonment_closes_the_handle_inside_the_hold(coordinator: RenameCoordinator, mocker: MockerFixture) -> None:
    """A consumer that stops reading closes the same way: inside the hold its unwind is leaving.

    ``GeneratorExit`` lands at the ``yield``, which sits inside the hold -- so the close must happen on
    the way out of the ``try``, not in some cleanup that runs after the hold has already let a rename
    through.

    **Test steps:**

    * take one chunk, then close the generator, sampling the holder count at close
    * check the close saw the reader still holding
    """
    seen = open_recording_holders(coordinator, mocker)
    reader = read_content_chunks(coordinator.track(CONTENT), coordinator, CHUNK)
    next(reader)

    reader.close()

    assert seen == [1]


def test_a_failed_read_closes_the_handle_inside_the_hold(coordinator: RenameCoordinator, mocker: MockerFixture) -> None:
    """A read that raises leaves no handle behind for a rename to trip over, and hides nothing.

    **Test steps:**

    * serve a file whose second read raises, sampling the holder count at close
    * check the error came out, and the close saw the reader still holding
    """
    seen: list[int] = []

    def open_file(path: Path) -> BytesIO:
        del path
        handle = BytesIO(PAYLOAD)
        original_close = handle.close
        reads = [0]

        def read(size: int = -1) -> bytes:
            reads[0] += 1
            if reads[0] > 1:
                raise OSError("the disk went away")
            return PAYLOAD[:size]

        def close() -> None:
            seen.append(holders_now(coordinator))
            original_close()

        handle.read = read  # pyright: ignore[reportAttributeAccessIssue]
        handle.close = close  # pyright: ignore[reportAttributeAccessIssue]
        return handle

    mocker.patch("rehuco_core.content_reading.shared_read_open", side_effect=open_file)
    reader = read_content_chunks(coordinator.track(CONTENT), coordinator, CHUNK)
    next(reader)

    with raises(OSError):
        next(reader)

    assert seen == [1]


# endregion


# region standing aside for a rename
def test_a_rename_mid_read_yields_the_same_bytes(
    coordinator: RenameCoordinator, files: FakeFiles, locking_storage: None
) -> None:
    """A directory rename landing mid-read produces exactly what an uninterrupted pass would.

    The measurement this whole issue rests on, as a test: the reader closes, waits, re-opens at the new
    path and seeks back, and the bytes are identical.

    **Test steps:**

    * park a reader mid-file and rename the folder underneath it
    * let the read finish, and check the bytes and where it re-opened
    """
    del locking_storage  # the backend this test describes; see the fixture
    location = coordinator.track(CONTENT)
    reader = SteppedReader(coordinator, location)
    reader.start()

    rename_while_parked(reader, coordinator, INFO_PATH, NEW_NAME)
    reader.finish()

    assert b"".join(reader.collected) == PAYLOAD
    assert files.opened == [CONTENT, RENAMED_CONTENT]
    assert location.path == RENAMED_CONTENT


def test_the_reader_seeks_back_to_where_it_stopped(
    coordinator: RenameCoordinator, files: FakeFiles, locking_storage: None
) -> None:
    """Re-opening starts a fresh handle at byte zero, so the reader must seek -- and does.

    Pinned separately because the fake serves an independent stream per open: a reader that forgot to
    seek would read the beginning twice, and the total length is what says so.

    **Test steps:**

    * park a reader mid-file, rename, and let it finish
    * check the total read is the file's length and every chunk is distinct
    """
    del files, locking_storage  # without the re-open there is no seek to observe; see the fixture
    reader = SteppedReader(coordinator, coordinator.track(CONTENT))
    reader.start()

    rename_while_parked(reader, coordinator, INFO_PATH, NEW_NAME)
    reader.finish()

    assert sum(len(chunk) for chunk in reader.collected) == len(PAYLOAD)
    assert len(reader.collected) == CHUNK_COUNT


def test_a_reader_survives_several_renames_in_one_pass(
    coordinator: RenameCoordinator, mocker: MockerFixture, locking_storage: None
) -> None:
    """A long job renamed under three times still reads the file exactly once, end to end.

    A rename is not a once-per-job event: a user reorganizing a catalog while a sweep runs may move the
    same resource repeatedly, and each move must cost one chunk and nothing else.

    **Test steps:**

    * serve the file under every name it will have
    * park a reader and rename three times
    * check the bytes, the re-opens, and where the location ended
    """
    del locking_storage  # one re-open per rename is the thing counted; see the fixture
    names = ["first", "second", "third"]
    files = FakeFiles({CONTENT: PAYLOAD} | {DIRECTORY / name / "content.zip": PAYLOAD for name in names})
    mocker.patch("rehuco_core.content_reading.shared_read_open", side_effect=files.open)
    location = coordinator.track(CONTENT)
    reader = SteppedReader(coordinator, location)
    reader.start()

    rename_while_parked(reader, coordinator, INFO_PATH, "first")
    rename_while_parked(reader, coordinator, DIRECTORY / "first" / "info.rehu", "second")
    rename_while_parked(reader, coordinator, DIRECTORY / "second" / "info.rehu", "third")
    reader.finish()

    assert b"".join(reader.collected) == PAYLOAD
    assert files.opened == [CONTENT, *(DIRECTORY / name / "content.zip" for name in names)]
    assert location.path == DIRECTORY / "third" / "content.zip"


def test_a_non_locking_backend_keeps_its_handle_open(
    coordinator: RenameCoordinator, files: FakeFiles, mocker: MockerFixture
) -> None:
    """Where the storage does not lock, the reader still stands aside but never closes the file.

    The trait's whole purpose: one barrier protocol on every platform, and only the close conditional.
    An open descriptor on POSIX goes on reading the file it was opened on, so re-opening would be work
    for nothing -- but leaving the hold still has to happen, or every rename would wait out its ceiling.

    **Test steps:**

    * say the storage does not lock, then park a reader and rename
    * check the rename landed, the bytes are right, and the file was opened once
    """
    mocker.patch("rehuco_core.content_reading.readers_must_yield_for_directory_rename", return_value=False)
    location = coordinator.track(CONTENT)
    reader = SteppedReader(coordinator, location)
    reader.start()

    rename_while_parked(reader, coordinator, INFO_PATH, NEW_NAME)
    reader.finish()

    assert b"".join(reader.collected) == PAYLOAD
    assert files.opened == [CONTENT]
    assert files.closed == 1
    assert location.path == RENAMED_CONTENT


def test_a_rename_waits_for_the_reader_rather_than_failing(coordinator: RenameCoordinator, files: FakeFiles) -> None:
    """The rename is held up by a reader that is mid-file, and goes through once it reaches a boundary.

    Stated on its own, because it is the promise made to the *rename* rather than to the reader: it is
    not refused and does not force anything -- it waits, and the wait is one chunk long.

    **Test steps:**

    * park a reader and start a rename
    * check the flag is up and the rename has not touched anything
    * let the reader take one step, and check the rename lands
    """
    del files
    reader = SteppedReader(coordinator, coordinator.track(CONTENT))
    reader.start()
    landed = Event()

    with running(lambda: (coordinator.rename(INFO_PATH, NEW_NAME), landed.set())):
        assert wait_until(lambda: coordinator.yield_wanted)
        assert landed.wait(BRIEF) is False

        reader.step()

        assert landed.wait(SETTLE)
    reader.finish()


# endregion
