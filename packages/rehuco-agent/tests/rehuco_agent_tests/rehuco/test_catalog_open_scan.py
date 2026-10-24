"""Tests for what opening a ``.rehuco`` scans (#541, [[data-model#scan-and-staleness]]): every root whose cache row was
never scanned, once, and no root that was.

The catalog is a mock (``catalog``): each test says which roots it reports scanned, and the scans run against the mock
cache (``cache``).
"""

import logging
from pathlib import Path
from typing import Any, Final
from unittest.mock import MagicMock, Mock
from uuid import UUID, uuid4

from pytest import LogCaptureFixture, fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_core import CatalogRoot, RootScanOutcome, TaskQueue
from rehuco_core.access import CatalogUnreadable

from rehuco_agent_tests.mapped_roots import location_at

from .test_catalog_docks import (  # noqa: F401  # pylint: disable=unused-import
    PACKS,
    REHUCO_PATH,
    ROOT_IDS,
    TUTORIALS,
    CatalogDocks,
    GateJob,
    fixture_cache,
    fixture_cached_rows,
    fixture_catalog,
    fixture_dock,
    fixture_held,
    fixture_machine,
    fixture_on_disk,
    fixture_queue,
    fixture_served,
    scan_finding,
    wait_for_jobs,
)

EXTRA: Final = Path.cwd() / "fake" / "extra"
"""A third root's folder, added to the served file."""


@fixture(name="scan_class")
def fixture_scan_class(mocker: MockerFixture) -> MagicMock:
    """Make every root scan find nothing, without touching a disk.

    :param mocker: pytest-mock fixture.
    :returns: the scan class's mock.
    """
    return scan_finding(mocker, {})


def cached_roots(catalog: Mock, *roots: tuple[UUID, str, Path, bool]) -> None:
    """Make the mock catalog report ``roots``, each scanned or never scanned.

    :param catalog: the mock catalog.
    :param roots: ``(id, label, folder, scanned)`` per root, in order.
    """
    listed = tuple(
        CatalogRoot(root_id, label, folder, position, False, None, 1.0 if scanned else None)
        for position, (root_id, label, folder, scanned) in enumerate(roots)
    )
    catalog.roots.side_effect = lambda: listed


def home_roots(catalog: Mock, *, scanned: bool) -> None:
    """Make the mock catalog report the served file's two roots, both scanned or both never scanned.

    :param catalog: the mock catalog.
    :param scanned: whether they were scanned.
    """
    cached_roots(
        catalog,
        (UUID(ROOT_IDS[0]), "tutorials", TUTORIALS, scanned),
        (UUID(ROOT_IDS[1]), "packs", PACKS, scanned),
    )


def scanned_folders(queue: TaskQueue) -> list[Path | None]:
    """The folder each job on the queue is about, in the order they were queued, the held gate left out.

    :param queue: the queue.
    :returns: the folders.
    """
    return [status.source for status in queue.jobs() if status.label != "gate"]


@mark.usefixtures("served", "scan_class")
def test_opening_a_fresh_cache_scans_every_root(
    qtbot: QtBot, dock: CatalogDocks, queue: TaskQueue, catalog: Mock, cache: MagicMock
) -> None:
    """A cache with nothing scanned is filled without a click on Scan.

    **Test steps:**

    * open a two-root catalog whose cache reports neither root scanned
    * verify one scan per root was queued, in root order, and each wrote what it found to the cache
    """
    home_roots(catalog, scanned=False)

    dock.catalog.open_rehuco(REHUCO_PATH)

    assert scanned_folders(queue) == [TUTORIALS, PACKS]
    wait_for_jobs(qtbot, queue)
    assert [call.args[0] for call in cache.apply_root_scan.call_args_list] == [UUID(ROOT_IDS[0]), UUID(ROOT_IDS[1])]


@mark.usefixtures("scan_class")
def test_reopening_scans_only_the_root_the_cache_never_scanned(
    qtbot: QtBot, dock: CatalogDocks, queue: TaskQueue, catalog: Mock, served: dict[str, Any]
) -> None:
    """Roots already scanned are left to the notifier and verify-on-access.

    **Test steps:**

    * add a third root to the file; make the cache report the first two scanned and the third not
    * open the catalog and verify one scan was queued, of the third root
    """
    extra_id = uuid4()
    served["roots"].append({"id": str(extra_id), "location": location_at(EXTRA), "label": "extra"})
    cached_roots(
        catalog,
        (UUID(ROOT_IDS[0]), "tutorials", TUTORIALS, True),
        (UUID(ROOT_IDS[1]), "packs", PACKS, True),
        (extra_id, "extra", EXTRA, False),
    )

    dock.catalog.open_rehuco(REHUCO_PATH)

    assert scanned_folders(queue) == [EXTRA]
    wait_for_jobs(qtbot, queue)


@mark.usefixtures("served", "scan_class")
def test_opening_when_every_root_is_scanned_queues_nothing(dock: CatalogDocks, queue: TaskQueue, catalog: Mock) -> None:
    """A file whose roots were all scanned leaves the queue as it was.

    **Test steps:**

    * make the cache report both roots scanned, and open the catalog
    * verify no job was queued
    """
    home_roots(catalog, scanned=True)

    dock.catalog.open_rehuco(REHUCO_PATH)

    assert not queue.jobs()


@mark.usefixtures("served", "scan_class")
def test_reopening_the_open_file_while_its_scans_run_queues_nothing_more(
    qtbot: QtBot, dock: CatalogDocks, queue: TaskQueue, held: GateJob, catalog: Mock
) -> None:
    """The asked-twice guard holds for the open-time scans: a re-open from the recents is not a second scan.

    **Test steps:**

    * hold the queue; open a catalog whose roots were never scanned, then open the same file again
    * verify one scan per root waits, not two
    """
    home_roots(catalog, scanned=False)
    dock.catalog.open_rehuco(REHUCO_PATH)

    dock.catalog.open_rehuco(REHUCO_PATH)

    assert scanned_folders(queue) == [TUTORIALS, PACKS]
    held.let_finish()
    wait_for_jobs(qtbot, queue)


@mark.usefixtures("served")
# pylint: disable-next=too-many-arguments,too-many-positional-arguments
def test_a_root_that_cannot_be_reached_is_marked_so_and_is_scanned_again_on_the_next_open(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, queue: TaskQueue, catalog: Mock, cache: MagicMock
) -> None:
    """An offline root's scan is queued and ends as any does, writing only that the root could not be reached -- so it
    stays never scanned, and the next open queues it again.

    **Test steps:**

    * make every scan find its root offline, open a catalog whose roots were never scanned, and let the scans end
    * verify both were queued, each marked its root unreachable and applied no scan
    * open the file again and verify both were queued again
    """
    scan_finding(mocker, {}, RootScanOutcome.OFFLINE)
    home_roots(catalog, scanned=False)
    dock.catalog.open_rehuco(REHUCO_PATH)
    assert scanned_folders(queue) == [TUTORIALS, PACKS]
    wait_for_jobs(qtbot, queue)
    assert [call.args[0] for call in cache.mark_root_unreachable.call_args_list] == [
        UUID(ROOT_IDS[0]),
        UUID(ROOT_IDS[1]),
    ]
    cache.apply_root_scan.assert_not_called()

    dock.catalog.open_rehuco(REHUCO_PATH)

    assert scanned_folders(queue) == [TUTORIALS, PACKS, TUTORIALS, PACKS]
    wait_for_jobs(qtbot, queue)


@mark.usefixtures("served", "scan_class")
def test_a_cache_whose_roots_cannot_be_read_scans_nothing_and_says_why(
    dock: CatalogDocks, queue: TaskQueue, catalog: Mock, caplog: LogCaptureFixture
) -> None:
    """The open still succeeds; the unreadable cache is logged, as every other read of it is.

    **Test steps:**

    * make the catalog's reading of its roots fail and open a catalog
    * verify it opened, nothing was queued and the failure was logged
    """
    catalog.roots.side_effect = CatalogUnreadable("the cache is gone")

    with caplog.at_level(logging.ERROR):
        assert dock.catalog.open_rehuco(REHUCO_PATH)

    assert not queue.jobs()
    assert "the cache is gone" in caplog.text
