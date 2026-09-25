"""Tests for the open-archive-handle cache (#221)."""

import threading
import time
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final
from unittest.mock import MagicMock

from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_agent.documents.content_images.archive_cache import HEADER_BYTES, ArchiveCache, ArchiveHandle
from rehuco_core import ContentImageEntry, RenameCoordinator

MODULE: Final = "rehuco_agent.documents.content_images.archive_cache"

ARCHIVE: Final = Path("/fake/pack/pack.zip")
RENAMED_ARCHIVE: Final = Path("/fake/renamed/pack.zip")
OTHER: Final = Path("/fake/other.zip")
THIRD: Final = Path("/fake/third.zip")
MEMBER: Final = ContentImageEntry(ARCHIVE, "img.jpg", 3, 0)
OTHER_MEMBER: Final = ContentImageEntry(OTHER, "img.jpg", 3, 0)
THIRD_MEMBER: Final = ContentImageEntry(THIRD, "img.jpg", 3, 0)
PAYLOAD: Final = b"\xff\xd8\xff"


def mock_zipfile(mocker: MockerFixture, payload: bytes = PAYLOAD) -> list[MagicMock]:
    """Mock the share-delete opener and ``zipfile.ZipFile`` so every archive opens and every member
    reads as ``payload``.

    :param mocker: pytest-mock fixture.
    :param payload: what a member's bytes are.
    :returns: the zip handles handed out so far, in opening order -- appended to as archives open. Each
        carries the file it was opened on as ``.file``, whose ``.path`` is where it was opened.
    """
    handles: list[MagicMock] = []

    def open_file(path: Path) -> MagicMock:
        file = mocker.MagicMock(name=f"file:{path}")
        file.path = path
        return file

    def open_archive(file: MagicMock, *_args: object, **_kwargs: object) -> MagicMock:
        archive = mocker.MagicMock(name=str(file.path))
        archive.file = file
        member = archive.open.return_value.__enter__.return_value
        member.read.side_effect = lambda limit=None: payload if limit is None else payload[:limit]
        handles.append(archive)
        return archive

    mocker.patch(f"{MODULE}.shared_read_open", side_effect=open_file)
    mocker.patch(f"{MODULE}.zipfile.ZipFile", side_effect=open_archive)
    return handles


def planted(cache: ArchiveCache) -> Any:
    """``cache``'s private handle table, for a test planting a handle of its own.

    :param cache: the cache.
    :returns: its ``OrderedDict`` of handles.
    """
    return cache._ArchiveCache__handles  # type: ignore[attr-defined]  # pylint: disable=protected-access


def test_read_returns_the_whole_member(mocker: MockerFixture) -> None:
    """A read inflates the member in full through the archive's handle.

    **Test steps:**

    * read a member
    * verify its bytes came back through one opened archive, asked for the member by name
    """
    handles = mock_zipfile(mocker)

    assert ArchiveCache().read(MEMBER) == PAYLOAD
    assert len(handles) == 1
    handles[0].open.assert_called_once_with(MEMBER.name)


def test_read_head_inflates_only_the_leading_bytes(mocker: MockerFixture) -> None:
    """A header read asks the member for its leading slice -- the default header allowance, or the
    limit given -- not the whole thing.

    **Test steps:**

    * read a member's head with a two-byte limit, then with the default
    * verify each read was bounded accordingly
    """
    handles = mock_zipfile(mocker)
    cache = ArchiveCache()

    assert cache.read_head(MEMBER, 2) == PAYLOAD[:2]
    assert cache.read_head(MEMBER) == PAYLOAD[:HEADER_BYTES]
    member = handles[0].open.return_value.__enter__.return_value
    assert [call.args for call in member.read.call_args_list] == [(2,), (HEADER_BYTES,)]


def test_a_handle_is_reused_across_reads(mocker: MockerFixture) -> None:
    """The archive is opened once and read through repeatedly -- the point of the cache.

    **Test steps:**

    * read two members of the same archive, twice each
    * verify the archive was opened exactly once
    """
    handles = mock_zipfile(mocker)
    cache = ArchiveCache()

    for _ in range(2):
        cache.read(MEMBER)
        cache.read(ContentImageEntry(ARCHIVE, "other.jpg", 3, 0))

    assert len(handles) == 1


def test_the_least_recently_used_handle_is_evicted_and_closed(mocker: MockerFixture) -> None:
    """Past the limit, the handle touched longest ago is closed; touching one keeps it.

    **Test steps:**

    * with a limit of two, read from A, B, then A again, then C
    * verify B's handle was closed and A's kept, so a later read of A opens nothing new and one of B
      reopens it
    """
    handles = mock_zipfile(mocker)
    cache = ArchiveCache(limit=2)

    cache.read(MEMBER)
    cache.read(OTHER_MEMBER)
    cache.read(MEMBER)
    cache.read(THIRD_MEMBER)

    assert len(handles) == 3
    handles[1].close.assert_called_once()
    handles[0].close.assert_not_called()
    cache.read(MEMBER)
    assert len(handles) == 3
    cache.read(OTHER_MEMBER)
    assert len(handles) == 4


def test_losing_the_race_to_open_an_archive_keeps_the_winners_handle(mocker: MockerFixture) -> None:
    """Two threads opening the same archive at once: the second to insert closes its own handle and
    reads through the first's, so an archive is never held open twice.

    **Test steps:**

    * make the open, while it runs, plant a winner's handle in the cache for the same path
    * read, and verify the read went through the planted handle and the loser was closed
    """
    cache = ArchiveCache()
    winner = mocker.MagicMock(name="winner")
    winner.open.return_value.__enter__.return_value.read.return_value = PAYLOAD
    losers: list[MagicMock] = []

    def open_and_lose(file: MagicMock, *_args: object, **_kwargs: object) -> MagicMock:
        planted(cache)[ARCHIVE] = ArchiveHandle(mocker.MagicMock(), winner, False)
        loser = mocker.MagicMock(name="loser")
        loser.file = file
        losers.append(loser)
        return loser

    mocker.patch(f"{MODULE}.shared_read_open")
    mocker.patch(f"{MODULE}.zipfile.ZipFile", side_effect=open_and_lose)

    assert cache.read(MEMBER) == PAYLOAD

    winner.open.assert_called_once_with(MEMBER.name)
    losers[0].close.assert_called_once()
    losers[0].file.close.assert_called_once()
    losers[0].open.assert_not_called()


def test_a_handle_closed_by_an_eviction_under_the_read_is_looked_up_again(mocker: MockerFixture) -> None:
    """A handle found and then closed by an eviction before its lock was taken is not read through:
    the read looks the archive up again -- an eviction is no fact about the member, and the caller
    would record a failure for good. A handle that stays closed however often it is looked up reads as
    ``None``.

    **Test steps:**

    * plant a handle whose file object reads as closed once, then open
    * verify the read succeeded through that handle on its second look
    * plant one that stays closed and verify the read gives up as ``None``
    """
    cache = ArchiveCache()
    handles = planted(cache)
    flaky = mocker.MagicMock(name="flaky")
    type(flaky).fp = mocker.PropertyMock(side_effect=[None, object()])
    flaky.open.return_value.__enter__.return_value.read.return_value = PAYLOAD
    handles[ARCHIVE] = ArchiveHandle(mocker.MagicMock(), flaky, False)

    assert cache.read(MEMBER) == PAYLOAD
    flaky.open.assert_called_once_with(MEMBER.name)

    closed = mocker.MagicMock(name="closed")
    type(closed).fp = mocker.PropertyMock(return_value=None)
    handles[OTHER] = ArchiveHandle(mocker.MagicMock(), closed, False)

    assert cache.read(OTHER_MEMBER) is None
    closed.open.assert_not_called()


def test_an_unopenable_archive_reads_as_nothing(mocker: MockerFixture) -> None:
    """An archive that cannot be opened -- offline, truncated -- reads as ``None``, never raises.

    **Test steps:**

    * make the file fail to open with an ``OSError``, then the zip over it with a ``BadZipFile``
    * verify both reads come back ``None``, and the file under the bad zip was closed
    """
    truncated = mocker.MagicMock(name="truncated")
    mocker.patch(f"{MODULE}.shared_read_open", side_effect=[OSError("offline"), truncated])
    mocker.patch(f"{MODULE}.zipfile.ZipFile", side_effect=zipfile.BadZipFile("truncated"))
    cache = ArchiveCache()

    assert cache.read(MEMBER) is None
    assert cache.read_head(MEMBER) is None
    # the file a zip could not be read off is not left open behind it
    truncated.close.assert_called_once()


def test_a_missing_member_reads_as_nothing(mocker: MockerFixture) -> None:
    """A member the archive no longer holds -- a re-pack under the browse -- reads as ``None``.

    **Test steps:**

    * open the archive once, then make it raise ``KeyError`` on opening the member
    * verify the read comes back ``None``
    """
    handles = mock_zipfile(mocker)
    cache = ArchiveCache()
    cache.read(MEMBER)
    handles[0].open.side_effect = KeyError("gone")

    assert cache.read(MEMBER) is None


def test_close_closes_every_handle(mocker: MockerFixture) -> None:
    """Closing the cache closes each open handle and forgets it.

    **Test steps:**

    * read from two archives, then close the cache
    * verify both handles were closed and a later read reopens
    """
    handles = mock_zipfile(mocker)
    cache = ArchiveCache()
    cache.read(MEMBER)
    cache.read(OTHER_MEMBER)

    cache.close()

    for handle in handles[:2]:
        handle.close.assert_called_once()
        handle.file.close.assert_called_once()
    cache.read(MEMBER)
    assert len(handles) == 3


# region rename barrier (#347)
SETTLE: Final = 5.0
"""How long a test waits for another thread to reach the state it checks, in seconds."""

BRIEF: Final = 0.05
"""A wait a test *expects* to run out, in seconds."""


@fixture(name="coordinator")
def fixture_coordinator() -> RenameCoordinator:
    """A fresh coordinator per test, never the app's shared one.

    :returns: the coordinator the cache under test takes part in.
    """
    return RenameCoordinator()


@fixture(name="renamer")
def fixture_renamer(mocker: MockerFixture) -> MagicMock:
    """Mock the rename a coordinator runs: it moves :data:`ARCHIVE` to :data:`RENAMED_ARCHIVE` and
    touches no disk.

    :param mocker: pytest-mock fixture.
    :returns: the renamer instance, so a test can gate or inspect its ``rename``.
    """
    renamer = mocker.patch("rehuco_core.rename_coordination.RehuRenamer").return_value
    renamer.relocate.side_effect = lambda path: RENAMED_ARCHIVE if path == ARCHIVE else path
    return renamer


@fixture(name="must_close")
def fixture_must_close(mocker: MockerFixture) -> MagicMock:
    """Make the storage one whose readers must let go for a directory rename -- Windows' answer,
    whatever platform the suite runs on.

    :param mocker: pytest-mock fixture.
    :returns: the patched trait, so a test can answer ``False`` instead.
    """
    return mocker.patch(f"{MODULE}.readers_must_yield_for_directory_rename", return_value=True)


def rename(coordinator: RenameCoordinator) -> None:
    """Rename through ``coordinator``, the way the location editor does.

    :param coordinator: the coordinator.
    """
    coordinator.rename(ARCHIVE.parent / "info.rehu", RENAMED_ARCHIVE.parent.name)


def start(target: Callable[[], object]) -> threading.Thread:
    """Run ``target`` on a daemon thread, so a failing test cannot hang the suite behind it.

    :param target: what to run.
    :returns: the started thread.
    """
    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread


def wait_until(predicate: Callable[[], bool]) -> bool:
    """Poll ``predicate`` until it holds or :data:`SETTLE` runs out.

    :param predicate: what to wait for.
    :returns: whether it came true in time.
    """
    deadline = time.monotonic() + SETTLE
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.001)
    return predicate()


def test_an_idle_handle_closes_before_the_rename_runs(
    mocker: MockerFixture, coordinator: RenameCoordinator, renamer: MagicMock, must_close: MagicMock
) -> None:
    """A handle nobody is reading is closed by the yield listener before the rename touches disk --
    the refusal #347 was filed for.

    **Test steps:**

    * read a member, leaving its archive open in the cache
    * rename, recording whether the handle and its file were closed when the rename ran
    * verify they were, and a later read reopens at the renamed path
    """
    del must_close
    handles = mock_zipfile(mocker)
    cache = ArchiveCache(coordinator)
    cache.read(MEMBER)
    closed_when_renamed: list[bool] = []
    renamer.rename.side_effect = lambda: closed_when_renamed.append(
        handles[0].close.called and handles[0].file.close.called
    )

    rename(coordinator)

    assert closed_when_renamed == [True]
    assert cache.read(MEMBER) == PAYLOAD
    assert handles[1].file.path == RENAMED_ARCHIVE


def test_a_handle_mid_read_is_closed_by_its_reader_before_the_rename(
    mocker: MockerFixture, coordinator: RenameCoordinator, renamer: MagicMock, must_close: MagicMock
) -> None:
    """A handle a reader is on is not waited for by the listener: the reader finishes its member and
    closes the handle before leaving the hold, and only then does the rename run.

    **Test steps:**

    * open the archive, then make the next member read block until released
    * start that read, then a rename, and check the rename waits with the handle still open
    * release the read, and check it returned its bytes, the handle closed, then the rename ran
    """
    del must_close
    handles = mock_zipfile(mocker)
    cache = ArchiveCache(coordinator)
    cache.read(MEMBER)
    reading = threading.Event()
    release = threading.Event()
    events: list[str] = []

    def blocking_read(limit: int | None = None) -> bytes:
        del limit
        reading.set()
        release.wait(SETTLE)
        return PAYLOAD

    handles[0].open.return_value.__enter__.return_value.read.side_effect = blocking_read
    handles[0].close.side_effect = lambda: events.append("close")
    renamer.rename.side_effect = lambda: events.append("rename")
    result: list[bytes | None] = []

    reader = start(lambda: result.append(cache.read(MEMBER)))
    assert reading.wait(SETTLE)
    renaming = start(lambda: rename(coordinator))
    assert wait_until(lambda: coordinator.yield_wanted)
    renaming.join(BRIEF)
    assert not events

    release.set()
    reader.join(SETTLE)
    renaming.join(SETTLE)

    assert result == [PAYLOAD]
    assert events == ["close", "rename"]


def test_a_read_during_the_rename_waits_and_opens_at_the_new_path(
    mocker: MockerFixture, coordinator: RenameCoordinator, renamer: MagicMock, must_close: MagicMock
) -> None:
    """A read asked for while the rename runs opens nothing until it is done, then reads the archive
    where it went -- never a failure recorded against the member.

    **Test steps:**

    * read once, then make the rename block until released
    * start the rename, then a read, and check the read has opened nothing new
    * release the rename, and check the read returned its bytes off the renamed archive
    """
    del must_close
    handles = mock_zipfile(mocker)
    cache = ArchiveCache(coordinator)
    cache.read(MEMBER)
    release = threading.Event()
    renamer.rename.side_effect = lambda: release.wait(SETTLE)
    result: list[bytes | None] = []

    renaming = start(lambda: rename(coordinator))
    assert wait_until(lambda: coordinator.yield_wanted)
    reader = start(lambda: result.append(cache.read(MEMBER)))
    reader.join(BRIEF)
    assert not result
    assert len(handles) == 1

    release.set()
    renaming.join(SETTLE)
    reader.join(SETTLE)

    assert result == [PAYLOAD]
    assert handles[-1].file.path == RENAMED_ARCHIVE


def test_storage_that_does_not_lock_keeps_its_handles(
    mocker: MockerFixture, coordinator: RenameCoordinator, renamer: MagicMock, must_close: MagicMock
) -> None:
    """Where a reader need not let go -- POSIX -- a rename closes nothing, and the handle keeps reading.

    **Test steps:**

    * answer the storage trait ``False``, read, rename
    * verify the handle was never closed and a later read opens nothing new
    """
    del renamer
    must_close.return_value = False
    handles = mock_zipfile(mocker)
    cache = ArchiveCache(coordinator)
    cache.read(MEMBER)

    rename(coordinator)

    handles[0].close.assert_not_called()
    assert cache.read(MEMBER) == PAYLOAD
    assert len(handles) == 1


def test_released_handles_reopen_where_the_archive_went(
    mocker: MockerFixture, coordinator: RenameCoordinator, renamer: MagicMock, must_close: MagicMock
) -> None:
    """Releasing the handles -- a path change -- keeps following every archive seen, so a read queued
    for an entry named before the change still finds it.

    **Test steps:**

    * read, release the handles, rename
    * verify the handle was closed, and a read by the old entry opens at the renamed path
    """
    del renamer, must_close
    handles = mock_zipfile(mocker)
    cache = ArchiveCache(coordinator)
    cache.read(MEMBER)

    cache.release_handles()
    handles[0].close.assert_called_once()
    rename(coordinator)

    assert cache.read(MEMBER) == PAYLOAD
    assert handles[1].file.path == RENAMED_ARCHIVE


def test_closing_the_cache_leaves_the_barrier(
    mocker: MockerFixture, coordinator: RenameCoordinator, renamer: MagicMock, must_close: MagicMock
) -> None:
    """A closed cache stops listening: the coordinator outlives every document, and would otherwise
    keep each one's cache alive and called.

    **Test steps:**

    * read, close the cache, and spy on its listener's removal
    * rename, and verify the handle was closed once -- by the close, not again by the rename
    """
    del renamer, must_close
    handles = mock_zipfile(mocker)
    remove = mocker.spy(coordinator, "remove_yield_listener")
    cache = ArchiveCache(coordinator)
    cache.read(MEMBER)

    cache.close()
    rename(coordinator)

    remove.assert_called_once()
    handles[0].close.assert_called_once()


def test_a_reader_closes_its_handle_even_once_it_has_left_the_cache(
    mocker: MockerFixture, coordinator: RenameCoordinator, renamer: MagicMock, must_close: MagicMock
) -> None:
    """A handle dropped from the cache while a reader was on it -- an eviction mid-read -- is still
    closed by that reader when a rename is waiting, and nothing else is dropped in its place.

    **Test steps:**

    * open the archive, then make the next read drop the handle from the cache and block until released
    * start that read and a rename, release the read
    * verify the handle closed before the rename ran
    """
    del must_close
    handles = mock_zipfile(mocker)
    cache = ArchiveCache(coordinator)
    cache.read(MEMBER)
    reading = threading.Event()
    release = threading.Event()
    events: list[str] = []

    def evicted_read(limit: int | None = None) -> bytes:
        del limit
        planted(cache).clear()
        reading.set()
        release.wait(SETTLE)
        return PAYLOAD

    handles[0].open.return_value.__enter__.return_value.read.side_effect = evicted_read
    handles[0].close.side_effect = lambda: events.append("close")
    renamer.rename.side_effect = lambda: events.append("rename")

    reader = start(lambda: cache.read(MEMBER))
    assert reading.wait(SETTLE)
    renaming = start(lambda: rename(coordinator))
    assert wait_until(lambda: coordinator.yield_wanted)
    release.set()
    reader.join(SETTLE)
    renaming.join(SETTLE)

    assert events == ["close", "rename"]


def test_the_listener_leaves_a_handle_someone_else_already_dropped(
    mocker: MockerFixture, coordinator: RenameCoordinator, renamer: MagicMock, must_close: MagicMock
) -> None:
    """An idle handle that leaves the cache while the listener is closing it is not dropped a second
    time -- the entry by then may be another handle's.

    **Test steps:**

    * open two archives, and make the first one's close plant a stand-in under its path
    * rename
    * verify both handles closed and the stand-in is still in the cache
    """
    del renamer, must_close
    handles = mock_zipfile(mocker)
    cache = ArchiveCache(coordinator)
    cache.read(MEMBER)
    cache.read(OTHER_MEMBER)
    stand_in = ArchiveHandle(mocker.MagicMock(), mocker.MagicMock(), False)
    handles[0].close.side_effect = lambda: planted(cache).__setitem__(ARCHIVE, stand_in)

    rename(coordinator)

    handles[0].close.assert_called_once()
    handles[1].close.assert_called_once()
    assert planted(cache) == {ARCHIVE: stand_in}


# endregion
