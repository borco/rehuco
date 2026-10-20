"""Tests for what opening a ``.rehuco`` scans (#541, [[data-model#scan-and-staleness]]): every root whose cache row was
never scanned, once, and no root that was.
"""

import logging
from pathlib import Path
from typing import Any, Final
from unittest.mock import MagicMock
from uuid import uuid4

from pytest import LogCaptureFixture, fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_core import RootScanOutcome, TaskQueue
from rehuco_core.access import Catalog, CatalogUnreadable

from .test_catalog_docks import (  # noqa: F401  # pylint: disable=unused-import
    PACKS,
    REHUCO_PATH,
    TUTORIALS,
    CatalogDocks,
    GateJob,
    MemoryDatabase,
    fixture_database,
    fixture_dock,
    fixture_held,
    fixture_queue,
    fixture_served,
    scan_finding,
    wait_for_jobs,
)

EXTRA: Final = Path.cwd() / "fake" / "extra"
"""A third root's folder, added to the served file after a first open."""


@fixture(name="scan_class")
def fixture_scan_class(mocker: MockerFixture) -> MagicMock:
    """Make every root scan find nothing, without touching a disk.

    :param mocker: pytest-mock fixture.
    :returns: the scan class's mock.
    """
    return scan_finding(mocker, {})


def scanned_folders(queue: TaskQueue) -> list[Path | None]:
    """The folder each job on the queue is about, in the order they were queued, the held gate left out.

    :param queue: the queue.
    :returns: the folders.
    """
    return [status.source for status in queue.jobs() if status.label != "gate"]


@mark.usefixtures("served", "scan_class")
def test_opening_a_fresh_cache_scans_every_root(
    qtbot: QtBot, dock: CatalogDocks, queue: TaskQueue, database: MemoryDatabase
) -> None:
    """A cache with nothing in it is filled without a click on Scan.

    **Test steps:**

    * open a two-root catalog whose cache is new
    * verify one scan per root was queued, in root order, and that both roots end scanned
    """
    dock.catalog.open_rehuco(REHUCO_PATH)

    assert scanned_folders(queue) == [TUTORIALS, PACKS]
    wait_for_jobs(qtbot, queue)
    assert database.scalar("SELECT COUNT(*) FROM roots WHERE scanned_at IS NOT NULL") == 2


@mark.usefixtures("scan_class")
def test_reopening_scans_only_the_root_the_cache_never_scanned(
    qtbot: QtBot, dock: CatalogDocks, queue: TaskQueue, served: dict[str, Any]
) -> None:
    """Roots already scanned are left to the notifier and verify-on-access.

    **Test steps:**

    * open a two-root catalog and let its scans end
    * add a third root to the file and open it again
    * verify the second open queued one scan, of the third root
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    wait_for_jobs(qtbot, queue)
    first_open = len(queue.jobs())
    served["roots"].append({"id": str(uuid4()), "path": str(EXTRA), "label": "extra"})

    dock.catalog.open_rehuco(REHUCO_PATH)

    assert [status.source for status in queue.jobs()[first_open:]] == [EXTRA]
    wait_for_jobs(qtbot, queue)


@mark.usefixtures("served", "scan_class")
def test_reopening_when_every_root_is_scanned_queues_nothing(
    qtbot: QtBot, dock: CatalogDocks, queue: TaskQueue
) -> None:
    """Re-opening a file whose roots were all scanned leaves the queue as it was.

    **Test steps:**

    * open a catalog, let its scans end, open it again
    * verify no job was added
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    wait_for_jobs(qtbot, queue)
    jobs = len(queue.jobs())

    dock.catalog.open_rehuco(REHUCO_PATH)

    assert len(queue.jobs()) == jobs


@mark.usefixtures("served", "scan_class")
def test_reopening_the_open_file_while_its_scans_run_queues_nothing_more(
    qtbot: QtBot, dock: CatalogDocks, queue: TaskQueue, held: GateJob
) -> None:
    """The asked-twice guard holds for the open-time scans: a re-open from the recents is not a second scan.

    **Test steps:**

    * hold the queue, open a catalog, open the same file again
    * verify one scan per root waits, not two
    """
    dock.catalog.open_rehuco(REHUCO_PATH)

    dock.catalog.open_rehuco(REHUCO_PATH)

    assert scanned_folders(queue) == [TUTORIALS, PACKS]
    held.let_finish()
    wait_for_jobs(qtbot, queue)


@mark.usefixtures("served")
def test_a_root_that_cannot_be_reached_is_scanned_and_is_scanned_again_on_the_next_open(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, queue: TaskQueue, database: MemoryDatabase
) -> None:
    """An offline root's scan is queued and ends as any does, leaving the root never scanned.

    **Test steps:**

    * make every scan find its root offline, open a catalog and let the scans end
    * verify both were queued and neither root has a scan time
    * open the file again and verify both were queued again
    """
    scan_finding(mocker, {}, RootScanOutcome.OFFLINE)
    dock.catalog.open_rehuco(REHUCO_PATH)
    assert scanned_folders(queue) == [TUTORIALS, PACKS]
    wait_for_jobs(qtbot, queue)
    assert database.scalar("SELECT COUNT(*) FROM roots WHERE scanned_at IS NULL") == 2

    dock.catalog.open_rehuco(REHUCO_PATH)

    assert scanned_folders(queue) == [TUTORIALS, PACKS, TUTORIALS, PACKS]
    wait_for_jobs(qtbot, queue)


@mark.usefixtures("served", "scan_class")
def test_a_cache_whose_roots_cannot_be_read_scans_nothing_and_says_why(
    mocker: MockerFixture, dock: CatalogDocks, queue: TaskQueue, caplog: LogCaptureFixture
) -> None:
    """The open still succeeds; the unreadable cache is logged, as every other read of it is.

    **Test steps:**

    * make the catalog's reading of its roots fail and open a catalog
    * verify it opened, nothing was queued and the failure was logged
    """
    mocker.patch.object(Catalog, "roots", side_effect=CatalogUnreadable("the cache is gone"))

    with caplog.at_level(logging.ERROR):
        assert dock.catalog.open_rehuco(REHUCO_PATH)

    assert not queue.jobs()
    assert "the cache is gone" in caplog.text
