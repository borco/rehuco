"""Tests for the open-archive-handle cache (#221)."""

import threading
import zipfile
from pathlib import Path
from typing import Final
from unittest.mock import MagicMock

from pytest_mock import MockerFixture
from rehuco_agent.documents.content_images.archive_cache import HEADER_BYTES, ArchiveCache
from rehuco_core import ContentImageEntry

ARCHIVE: Final = Path("/fake/pack.zip")
OTHER: Final = Path("/fake/other.zip")
THIRD: Final = Path("/fake/third.zip")
MEMBER: Final = ContentImageEntry(ARCHIVE, "img.jpg", 3, 0)
OTHER_MEMBER: Final = ContentImageEntry(OTHER, "img.jpg", 3, 0)
THIRD_MEMBER: Final = ContentImageEntry(THIRD, "img.jpg", 3, 0)
PAYLOAD: Final = b"\xff\xd8\xff"


def mock_zipfile(mocker: MockerFixture, payload: bytes = PAYLOAD) -> list[MagicMock]:
    """Mock ``zipfile.ZipFile`` so every archive opens and every member reads as ``payload``.

    :param mocker: pytest-mock fixture.
    :param payload: what a member's bytes are.
    :returns: the handles handed out so far, in opening order -- appended to as archives open.
    """
    handles: list[MagicMock] = []

    def open_archive(path: Path, *_args: object, **_kwargs: object) -> MagicMock:
        archive = mocker.MagicMock(name=str(path))
        member = archive.open.return_value.__enter__.return_value
        member.read.side_effect = lambda limit=None: payload if limit is None else payload[:limit]
        handles.append(archive)
        return archive

    mocker.patch("rehuco_agent.documents.content_images.archive_cache.zipfile.ZipFile", side_effect=open_archive)
    return handles


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

    def open_and_lose(path: Path, *_args: object, **_kwargs: object) -> MagicMock:
        handles = cache._ArchiveCache__handles  # type: ignore[attr-defined]  # pylint: disable=protected-access
        handles[path] = (winner, threading.Lock())
        loser = mocker.MagicMock(name="loser")
        losers.append(loser)
        return loser

    mocker.patch("rehuco_agent.documents.content_images.archive_cache.zipfile.ZipFile", side_effect=open_and_lose)

    assert cache.read(MEMBER) == PAYLOAD

    winner.open.assert_called_once_with(MEMBER.name)
    losers[0].close.assert_called_once()
    losers[0].open.assert_not_called()


def test_an_unopenable_archive_reads_as_nothing(mocker: MockerFixture) -> None:
    """An archive that cannot be opened -- offline, truncated -- reads as ``None``, never raises.

    **Test steps:**

    * make the archive fail to open with an ``OSError`` and then a ``BadZipFile``
    * verify both reads come back ``None``
    """
    mocker.patch(
        "rehuco_agent.documents.content_images.archive_cache.zipfile.ZipFile",
        side_effect=[OSError("offline"), zipfile.BadZipFile("truncated")],
    )
    cache = ArchiveCache()

    assert cache.read(MEMBER) is None
    assert cache.read_head(MEMBER) is None


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
    cache.read(MEMBER)
    assert len(handles) == 3
