"""Tests for rebalancing a root's buckets from the catalog (#681): the job each root gets, the Roots view's entry, and
that the job takes turns with a library scan.

The catalog is the mock of ``test_catalog_docks``, with the ``.rehuco`` served, its first root given a bucketed layout.
The job itself is core's and tested there; here its run is replaced.
"""

import threading
import time
from collections.abc import Generator
from pathlib import Path
from typing import Any, Final
from unittest.mock import Mock
from uuid import UUID, uuid4

from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.scraping.library_scan_job import LibraryScanJob
from rehuco_agent.settings.excluded_files_settings import ExcludedFilesSettings
from rehuco_core import (
    BUCKET_REBALANCE_KIND,
    FINISHED_JOB_STATES,
    JobControl,
    JobState,
    RebalanceBucketsJob,
    TaskJobBase,
    TaskQueue,
)

from .test_catalog_docks import (  # noqa: F401  # pylint: disable=unused-import
    PACKS,
    REHUCO_PATH,
    ROOT_IDS,
    TUTORIALS,
    CatalogDocks,
    fixture_cache,
    fixture_cached_rows,
    fixture_catalog,
    fixture_dock,
    fixture_machine,
    fixture_no_open_scan,
    fixture_on_disk,
    fixture_queue,
    fixture_served,
    select_root,
)

BUCKETED: Final = {"asset": ["{site}/{buckets}/{site_id}"], "*": ["*"]}
"""A layout with buckets, for one type."""

WAIT_MS: Final = 10_000
"""How long a test waits for a job, in milliseconds -- generous, since it expires only when something is wrong."""


class HeldScan(TaskJobBase):
    """A job on the library scans' chain that runs until it is paused, as a scan waiting between two pages does."""

    def __init__(self) -> None:
        super().__init__()
        self.label = "scan"
        self.chain = LibraryScanJob.chain

    def run(self, control: JobControl) -> None:
        """Wait, checking for a stop, as a scan's wait between two pages does."""
        del control
        while True:
            self.checkpoint()
            time.sleep(0.01)


@fixture(name="bucketed", autouse=True)
def fixture_bucketed(served: dict[str, Any]) -> None:
    """Give the served file's first root a layout with buckets.

    :param served: the served document.
    """
    served["roots"][0]["layouts"] = BUCKETED


@fixture(name="release")
def fixture_release(mocker: MockerFixture) -> Generator[threading.Event]:
    """Replace what a rebalance runs with a wait, so it stays unfinished.

    :param mocker: pytest-mock fixture.
    :yields: the event that lets every rebalance finish; set when the test ends.
    """
    release = threading.Event()
    mocker.patch.object(RebalanceBucketsJob, "run", lambda _job, _control: release.wait(WAIT_MS / 1000))
    yield release
    release.set()


def rebalances(queue: TaskQueue) -> list[Path | None]:
    """The folder each rebalance on the queue is about, in the order they were queued.

    :param queue: the queue.
    :returns: the folders.
    """
    return [status.source for status in queue.jobs() if status.kind == BUCKET_REBALANCE_KIND]


def all_roots(dock: CatalogDocks) -> tuple[UUID, ...]:
    """The ids of the open catalog's roots, in its order.

    :param dock: the docks.
    :returns: the ids.
    """
    return tuple(root.root_id for root in dock.catalog.mapped_roots())


def wait_until_idle(qtbot: QtBot, queue: TaskQueue) -> None:
    """Wait for every job on the queue to finish.

    :param qtbot: pytest-qt fixture.
    :param queue: the queue.
    """
    qtbot.waitUntil(lambda: all(status.state in FINISHED_JOB_STATES for status in queue.jobs()), timeout=WAIT_MS)


def test_a_rebalance_is_queued_for_each_root_asked_for(
    qtbot: QtBot, dock: CatalogDocks, queue: TaskQueue, release: threading.Event, mocker: MockerFixture
) -> None:
    """One job per root, buckets in its layouts or not: a root whose rule is gone may still have folders to join.

    **Test steps:**

    * open a catalog of two roots, one with a bucketed layout, and ask for a rebalance of both and of an unknown one
    * verify one job each, over that root's folder and cache, named after it and its limits, with the Files page's junk
      patterns
    """
    excluded = ExcludedFilesSettings()
    excluded.patterns = ("*.tmp",)
    mocker.patch("rehuco_agent.rehuco.root_catalog.shared_excluded_files_settings", return_value=excluded)
    dock.catalog.open_rehuco(REHUCO_PATH)

    dock.catalog.rebalance((*all_roots(dock), uuid4()), 300, 120)

    assert rebalances(queue) == [TUTORIALS, PACKS]
    status = queue.jobs()[0]
    job = queue.job(status.serial)
    assert isinstance(job, RebalanceBucketsJob)
    assert status.label == "Balance buckets (300/120) - tutorials"
    assert (str(job.root_id), job.cache_path) == (ROOT_IDS[0], dock.catalog.cache_path)
    assert job.limits == (300, 120)
    assert job.excluded_patterns == ("*.tmp",)
    release.set()
    wait_until_idle(qtbot, queue)


def test_a_root_not_asked_for_gets_none(
    qtbot: QtBot, dock: CatalogDocks, queue: TaskQueue, release: threading.Event
) -> None:
    """Only the roots checked are balanced.

    **Test steps:**

    * open the catalog and ask for a rebalance of its first root
    * verify that root's job alone
    """
    dock.catalog.open_rehuco(REHUCO_PATH)

    dock.catalog.rebalance(all_roots(dock)[:1], 300, 120)

    assert rebalances(queue) == [TUTORIALS]
    release.set()
    wait_until_idle(qtbot, queue)


def test_a_rebalance_waiting_with_the_same_limits_is_not_queued_again(
    qtbot: QtBot, dock: CatalogDocks, queue: TaskQueue, release: threading.Event
) -> None:
    """One unfinished with the same limits stands for another; other limits are another job, behind it, and a finished
    one stands for none.

    **Test steps:**

    * open the catalog and ask for a rebalance twice, then with other limits
    * verify two jobs; let them finish, ask once more, and verify a third
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    roots = all_roots(dock)[:1]

    dock.catalog.rebalance(roots, 300, 120)
    dock.catalog.rebalance(roots, 300, 120)
    assert rebalances(queue) == [TUTORIALS]
    dock.catalog.rebalance(roots, 50, 20)
    assert rebalances(queue) == [TUTORIALS, TUTORIALS]

    release.set()
    wait_until_idle(qtbot, queue)
    dock.catalog.rebalance(roots, 300, 120)
    assert rebalances(queue) == [TUTORIALS] * 3
    wait_until_idle(qtbot, queue)


def test_nothing_is_queued_with_no_catalog_open(dock: CatalogDocks, queue: TaskQueue) -> None:
    """A root's bucketed folders are found by the records its cache holds, so with none open there is nothing to do.

    **Test steps:**

    * ask for a rebalance with no catalog open
    * verify the queue is empty
    """
    dock.catalog.rebalance((uuid4(),), 300, 120)

    assert not queue.jobs()


def test_the_roots_view_asks_for_the_root_it_is_on(dock: CatalogDocks, qtbot: QtBot, queue: TaskQueue) -> None:
    """**Balance Buckets** is under Scan root on every root this machine maps, and asks the window for that root; the
    action the Root Catalog menu shares is off with none selected.

    **Test steps:**

    * open a catalog and ask for the actions of a root with buckets and one without
    * read the action with no root selected; select one, and trigger it
    * verify where it is, that it names that root, and that it queued nothing itself
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    roots, model = dock.roots, dock.roots.roots_model

    for row in (0, 1):
        actions = roots.roots_context_actions(model.index(row, 0))
        assert actions[2:5] == [roots.scan_root_action, roots.rebalance_root_action, roots.refresh_roots_action]
    assert not roots.rebalance_root_action.isEnabled()

    select_root(dock, 1)
    assert roots.rebalance_root_action.isEnabled()
    with qtbot.waitSignal(roots.rebalance_requested, timeout=1000) as asked:
        roots.rebalance_root_action.trigger()

    assert asked.args == [all_roots(dock)[1]]
    assert not queue.jobs()


def test_the_action_asked_on_no_root_does_nothing(dock: CatalogDocks, qtbot: QtBot) -> None:
    """With no root selected the action's slot asks for nothing.

    **Test steps:**

    * open a catalog with no row selected, and run the action's slot all the same
    * verify nothing was asked for
    """
    dock.catalog.open_rehuco(REHUCO_PATH)

    with qtbot.assertNotEmitted(dock.roots.rebalance_requested):
        dock.roots._RootsPanel__on_rebalance_root()  # type: ignore[attr-defined]  # pylint: disable=protected-access


@mark.usefixtures("catalog")
def test_a_rebalance_waits_for_a_library_scan_and_runs_once_it_is_paused(
    qtbot: QtBot, dock: CatalogDocks, queue: TaskQueue, release: threading.Event
) -> None:
    """The two share a chain: a rebalance asked for during a scan waits, and pausing the scan lets it run.

    **Test steps:**

    * run a job on the library scans' chain, and ask for a rebalance
    * verify it is queued while the scan runs; pause the scan
    * verify the rebalance runs to its end, the scan still paused
    """
    release.set()
    scan = queue.enqueue(HeldScan())
    qtbot.waitUntil(lambda: queue.jobs()[0].state is JobState.RUNNING, timeout=WAIT_MS)
    dock.catalog.open_rehuco(REHUCO_PATH)

    dock.catalog.rebalance(all_roots(dock)[:1], 300, 120)
    assert queue.jobs()[1].state is JobState.QUEUED

    queue.pause_job(scan)
    qtbot.waitUntil(lambda: queue.jobs()[1].state is JobState.DONE, timeout=WAIT_MS)
    assert queue.jobs()[0].state is JobState.PAUSED


def test_every_library_scan_is_on_one_chain() -> None:
    """Scans of two stores take turns too, so a rebalance waits for either.

    **Test steps:**

    * build two scans and a rebalance
    * verify one chain
    """
    assert LibraryScanJob(Mock()).chain == LibraryScanJob(Mock()).chain == RebalanceBucketsJob().chain
