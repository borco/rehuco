"""Tests for keeping the catalog cache current one record at a time (#373).

The cache and the record reader are each tested on their own (`test_rehudb`, `test_rehudb_scan`); here both are
mocked, along with the stat seams, and what is asserted is the updater's part: which record it reads, under which
hold, and what it asks the cache to do with it.
"""

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final
from unittest.mock import MagicMock
from uuid import uuid4

from pytest import fixture, mark
from pytest_mock import MockerFixture
from rehuco_core import (
    CatalogCache,
    CatalogLocation,
    CatalogRecord,
    CatalogRecordUpdater,
    CatalogRoot,
    RecordKind,
    RecordSignature,
    RenameCoordinator,
)

ROOT: Final = Path("/fake/library")
RECORD: Final = ROOT / "course/info.rehu"
CATALOG_ROOT: Final = CatalogRoot(uuid4(), "library", ROOT, 0, removable=False, reachable=True, scanned_at=1.0)


class Disk:  # pylint: disable=too-few-public-methods  # the seams are the interface
    """The stat seams the updater reads through, set per test.

    :param mocker: pytest-mock fixture.
    """

    def __init__(self, mocker: MockerFixture) -> None:
        self.present = True
        self.root_online = True
        self.mtime_ns = 7
        mocker.patch.object(Path, "stat", autospec=True, side_effect=self.__stat)
        mocker.patch.object(Path, "is_file", autospec=True, side_effect=lambda path: self.present)
        mocker.patch.object(Path, "is_dir", autospec=True, side_effect=lambda path: self.root_online)

    def __stat(self, path: Path, **_kwargs: object) -> SimpleNamespace:
        if not self.present:
            raise FileNotFoundError(path)
        return SimpleNamespace(st_mtime_ns=self.mtime_ns, st_size=3)


@fixture(name="disk")
def fixture_disk(mocker: MockerFixture) -> Disk:
    """The record present, under an online root.

    :param mocker: pytest-mock fixture.
    :returns: the seams.
    """
    return Disk(mocker)


@fixture(name="cache")
def fixture_cache(mocker: MockerFixture) -> MagicMock:
    """A cache that places :data:`RECORD` under :data:`CATALOG_ROOT`, with no row for it yet.

    :param mocker: pytest-mock fixture.
    :returns: the cache.
    """
    cache = mocker.MagicMock(spec=CatalogCache)
    cache.locate.return_value = CatalogLocation(CATALOG_ROOT, "course/info.rehu")
    cache.signature.return_value = None
    return cache


@fixture(name="read")
def fixture_read(mocker: MockerFixture) -> MagicMock:
    """The record reader, answering with a record at the absolute path it was given.

    :param mocker: pytest-mock fixture.
    :returns: the reader's mock.
    """
    return mocker.patch(
        "rehuco_core.rehudb_updates.CatalogRecordReader.read",
        side_effect=lambda path: CatalogRecord(path.as_posix(), RecordKind.REHU, title="Read", mtime_ns=7, size=3),
    )


def updater(cache: MagicMock, coordinator: Any = None) -> CatalogRecordUpdater:
    """An updater over ``cache``, reading through ``coordinator``, or a fresh one of its own."""
    return CatalogRecordUpdater(cache, coordinator=coordinator if coordinator is not None else RenameCoordinator())


# region Upserting


def test_a_saved_record_is_read_under_the_hold_and_written_root_relative(
    disk: Disk, cache: MagicMock, read: MagicMock, mocker: MockerFixture
) -> None:
    """The read is one chunk inside the rename barrier, and the row is written under the path's root."""
    del disk
    coordinator = mocker.MagicMock()

    assert updater(cache, coordinator).upsert(RECORD)

    read.assert_called_once_with(RECORD)
    coordinator.holding.assert_called_once_with()
    (root_id, written), _ = cache.upsert_record.call_args
    assert (root_id, written.path, written.title) == (CATALOG_ROOT.root_id, "course/info.rehu", "Read")


def test_a_record_gone_from_an_online_root_is_removed(disk: Disk, cache: MagicMock, read: MagicMock) -> None:
    """A root that is there makes a missing record a deleted one."""
    disk.present = False

    updater(cache).upsert(RECORD)

    cache.remove.assert_called_once_with(RECORD)
    read.assert_not_called()


def test_a_record_missing_under_an_offline_root_keeps_its_row(disk: Disk, cache: MagicMock, read: MagicMock) -> None:
    """A root that is not there says nothing about what is in it."""
    disk.present = False
    disk.root_online = False

    assert not updater(cache).upsert(RECORD)

    cache.remove.assert_not_called()
    cache.upsert_record.assert_not_called()
    read.assert_not_called()


@mark.parametrize("path", [ROOT / "course/video.mp4", Path("/elsewhere/info.rehu")], ids=["no record", "no root"])
def test_a_path_that_is_no_cached_record_changes_nothing(
    disk: Disk, cache: MagicMock, read: MagicMock, path: Path
) -> None:
    """Not a record's name, or under no root."""
    del disk
    if path.suffix == ".rehu":
        cache.locate.return_value = None

    assert not updater(cache).upsert(path)

    read.assert_not_called()
    cache.upsert_record.assert_not_called()


# endregion

# region Verifying on access


def test_a_record_under_no_root_is_not_verified(disk: Disk, cache: MagicMock, read: MagicMock) -> None:
    """Nothing caches it, so there is nothing to compare."""
    del disk
    cache.locate.return_value = None

    assert not updater(cache).verify(RECORD)

    cache.signature.assert_not_called()
    read.assert_not_called()


def test_a_record_its_row_still_matches_is_not_read(disk: Disk, cache: MagicMock, read: MagicMock) -> None:
    """The same time and size: the hot path costs a stat."""
    del disk
    cache.signature.return_value = RecordSignature("course/info.rehu", 7, 3)

    assert not updater(cache).verify(RECORD)

    cache.signature.assert_called_once_with(CATALOG_ROOT.root_id, "course/info.rehu")
    read.assert_not_called()


@mark.parametrize("signature", [RecordSignature("course/info.rehu", 6, 3), None], ids=["changed", "uncached"])
def test_a_record_changed_out_of_band_is_read_again(
    disk: Disk, cache: MagicMock, read: MagicMock, signature: RecordSignature | None
) -> None:
    """A signature the row was not read at -- or no row at all -- brings the record back in."""
    del disk
    cache.signature.return_value = signature

    assert updater(cache).verify(RECORD)

    read.assert_called_once_with(RECORD)
    cache.upsert_record.assert_called_once()


def test_a_record_found_gone_on_access_is_removed(disk: Disk, cache: MagicMock, read: MagicMock) -> None:
    """Its row was there; the file is not, and the root is."""
    disk.present = False
    cache.signature.return_value = RecordSignature("course/info.rehu", 7, 3)
    cache.remove.return_value = True

    assert updater(cache).verify(RECORD)

    cache.remove.assert_called_once_with(RECORD)
    read.assert_not_called()


# endregion
