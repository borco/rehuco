"""Tests for the catalog cache's queue jobs -- scanning a root and removing one (#372).

The scan and the cache are each tested on their own (`test_rehudb_scan`, `test_rehudb`); here both are mocked,
and what is asserted is the job's part: which of them it calls with what, and how it writes itself down.
"""

from pathlib import Path
from typing import Final
from unittest.mock import MagicMock
from uuid import uuid4

from pytest import fixture, mark
from pytest_mock import MockerFixture
from rehuco_core import (
    DEFAULT_TASK_JOB_REGISTRY,
    PROGRESS_UNIT_RESOURCES,
    REHUDB_REMOVE_ROOT_KIND,
    REHUDB_SCAN_KIND,
    CatalogRecord,
    RecordKind,
    RemoveCatalogRootJob,
    RenameCoordinator,
    RootScanOutcome,
    RootScanResult,
    ScanCatalogRootJob,
)

CACHE: Final = Path("/fake/cache/rehuco.rehudb")
ROOT: Final = Path("/fake/library")
ROOT_ID: Final = uuid4()


# pylint: disable=duplicate-code  # the job-test convention: each module keeps its own FakeControl
class FakeControl:  # pylint: disable=too-few-public-methods  # the protocol has exactly one method
    """A stand-in for the engine's :class:`~rehuco_core.JobControl`, recording what it was told."""

    def __init__(self) -> None:
        self.reports: list[tuple[int, int | None]] = []

    def report(self, done: int, total: int | None = None) -> None:
        """Record one progress report.

        :param done: units finished so far.
        :param total: units expected in all.
        """
        self.reports.append((done, total))


@fixture(name="cache")
def fixture_cache(mocker: MockerFixture) -> MagicMock:
    """Replace the cache every job opens with a mock, entered and left like the real one.

    :param mocker: pytest-mock fixture.
    :returns: the cache a ``with`` block hands the job.
    """
    opened = mocker.patch("rehuco_core.rehudb_jobs.CatalogCache.open")
    return opened.return_value.__enter__.return_value


def scan_returning(mocker: MockerFixture, result: RootScanResult) -> MagicMock:
    """Make every root scan answer ``result``, reporting one record of progress first.

    :returns: the scan class's mock, to check how it was built.
    """
    scan_class = mocker.patch("rehuco_core.rehudb_jobs.CatalogRootScan")

    def scanning() -> RootScanResult:
        scan_class.call_args.kwargs["progress"](1)
        return result

    scan_class.return_value.scan.side_effect = scanning
    return scan_class


def scan_job() -> ScanCatalogRootJob:
    """A scan of :data:`ROOT` into :data:`CACHE`, over its own coordinator."""
    return ScanCatalogRootJob(CACHE, ROOT_ID, ROOT, root_label="library", coordinator=RenameCoordinator())


# region Scanning


def test_a_scan_applies_what_it_found(mocker: MockerFixture, cache: MagicMock) -> None:
    """A root that listed has its rows replaced, and the progress is a running count."""
    records = (CatalogRecord("info.rehu", RecordKind.REHU),)
    result = RootScanResult(ROOT, RootScanOutcome.SCANNED, records)
    scan_returning(mocker, result)
    control = FakeControl()
    job = scan_job()

    job.run(control)

    cache.apply_root_scan.assert_called_once_with(ROOT_ID, records)
    cache.mark_root_unreachable.assert_not_called()
    assert control.reports == [(0, None), (1, None)]
    assert job.result is result


@mark.parametrize("outcome", [RootScanOutcome.OFFLINE, RootScanOutcome.WENT_OFFLINE])
def test_an_offline_root_keeps_its_rows(mocker: MockerFixture, cache: MagicMock, outcome: RootScanOutcome) -> None:
    """Nothing is applied; the root is marked, and the job still finishes."""
    scan_returning(mocker, RootScanResult(ROOT, outcome))

    scan_job().run(FakeControl())

    cache.apply_root_scan.assert_not_called()
    cache.mark_root_unreachable.assert_called_once_with(ROOT_ID)


def test_a_scan_reads_through_its_coordinator_and_checkpoint(mocker: MockerFixture, cache: MagicMock) -> None:
    """The job's own stop protocol reaches every listing and every read."""
    del cache
    scan_class = scan_returning(mocker, RootScanResult(ROOT, RootScanOutcome.SCANNED))
    coordinator = RenameCoordinator()
    job = ScanCatalogRootJob(CACHE, ROOT_ID, ROOT, coordinator=coordinator)

    job.run(FakeControl())

    assert scan_class.call_args.args == (ROOT,)
    assert scan_class.call_args.kwargs["coordinator"] is coordinator
    checkpoint = scan_class.call_args.kwargs["checkpoint"]
    assert (checkpoint.__self__, checkpoint.__name__) == (job, "checkpoint")


def test_a_scan_counts_resources_and_is_named_for_its_root() -> None:
    """What the queue reads off it."""
    job = scan_job()

    assert job.kind == REHUDB_SCAN_KIND
    assert job.progress_unit == PROGRESS_UNIT_RESOURCES
    assert job.label == "Scan - library"
    assert job.source == ROOT
    assert job.safely_interruptible
    assert job.validate() is None


def test_a_scan_with_nothing_to_scan_says_so() -> None:
    """A job built bare, and never restored, cannot start."""
    assert ScanCatalogRootJob().validate() == "This task names no catalog root."
    assert ScanCatalogRootJob(CACHE, ROOT_ID).validate() == "This task names no folder to scan."


def test_a_scan_survives_the_saved_queue() -> None:
    """Paths and ids, written down and read back."""
    restored = DEFAULT_TASK_JOB_REGISTRY.create(REHUDB_SCAN_KIND, scan_job().capture_state())

    assert isinstance(restored, ScanCatalogRootJob)
    assert (restored.cache_path, restored.root_id, restored.source) == (CACHE, ROOT_ID, ROOT)
    assert restored.label == "Scan - library"


@mark.parametrize(
    "state",
    [
        {"cache": "", "root_id": str(ROOT_ID), "path": str(ROOT)},
        {"cache": str(CACHE), "root_id": "not a uuid", "path": str(ROOT)},
        {"cache": str(CACHE), "path": str(ROOT)},
        {"cache": str(CACHE), "root_id": str(ROOT_ID)},
    ],
)
def test_a_malformed_saved_scan_is_dropped(state: dict[str, str]) -> None:
    """The registry logs and drops a state that does not describe a runnable job."""
    assert DEFAULT_TASK_JOB_REGISTRY.create(REHUDB_SCAN_KIND, state) is None


# endregion

# region Removing a root


def test_removing_a_root_removes_it_from_the_cache(cache: MagicMock) -> None:
    """One step, one call."""
    control = FakeControl()

    RemoveCatalogRootJob(CACHE, ROOT_ID, root_label="library").run(control)

    cache.remove_root.assert_called_once_with(ROOT_ID)
    assert control.reports == [(0, 1), (1, 1)]


def test_a_root_removal_survives_the_saved_queue() -> None:
    """Restored by kind, named as it was."""
    job = RemoveCatalogRootJob(CACHE, ROOT_ID, root_label="library")

    restored = DEFAULT_TASK_JOB_REGISTRY.create(REHUDB_REMOVE_ROOT_KIND, job.capture_state())

    assert isinstance(restored, RemoveCatalogRootJob)
    assert (restored.cache_path, restored.root_id, restored.label) == (CACHE, ROOT_ID, "Remove root - library")
    assert not restored.safely_interruptible


# endregion
