"""Tests for the catalog cache's queue jobs -- scanning a root and removing one (#372).

The scan and the cache are each tested on their own (`test_rehudb_scan`, `test_rehudb`); here both are mocked,
and what is asserted is the job's part: which of them it calls with what, and how it writes itself down.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Final
from unittest.mock import MagicMock
from uuid import UUID, uuid4

from pytest import fixture, mark, raises
from pytest_mock import MockerFixture
from rehuco_core import (
    DEFAULT_TASK_JOB_REGISTRY,
    PROGRESS_UNIT_RESOURCES,
    REHUDB_REMOVE_ROOT_KIND,
    REHUDB_SCAN_KIND,
    CatalogRecord,
    CatalogRoot,
    HardlinkedRecord,
    RecordKind,
    RemoveCatalogRootJob,
    RenameCoordinator,
    RootScanEffects,
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
    """A root that listed has its rows replaced -- the records read and the ones found unchanged, the rows it touched
    collected (#511) -- and with no rows to go by, the progress is a running count.

    **Test steps:**

    * make the scan find one record read and one unchanged, with no cached rows
    * run the job
    * verify the cache applied both with empty effects to collect touched rows, nothing was marked, and the progress
      counted
    """
    cache.signatures.return_value = {}
    records = (CatalogRecord("info.rehu", RecordKind.REHU),)
    result = RootScanResult(ROOT, RootScanOutcome.SCANNED, records, unchanged=("same.rehu",))
    scan_class = scan_returning(mocker, result)
    control = FakeControl()
    job = scan_job()

    job.run(control)

    cache.apply_root_scan.assert_called_once_with(
        ROOT_ID, records, unchanged=("same.rehu",), identities={}, effects=RootScanEffects()
    )
    cache.mark_root_unreachable.assert_not_called()
    assert control.reports == [(0, None), (1, None)]
    assert job.result is result
    assert scan_class.call_args.kwargs["known"] == {}


def touching(*ids: int) -> Callable[..., bool]:
    """A stand-in for :meth:`~rehuco_core.CatalogCache.apply_root_scan` that reports ``ids`` as the rows it changed.

    :param ids: the rows.
    :returns: the stand-in.
    """

    def apply(*_: object, effects: RootScanEffects, **__: object) -> bool:
        """Report the rows as touched, and answer applied."""
        effects.touched.update(ids)
        return True

    return apply


def test_a_scan_keeps_the_rows_it_changed_until_reset(mocker: MockerFixture, cache: MagicMock) -> None:
    """The ids the cache says a scan changed are the job's ``touched_rows`` once it ran, and a reset drops them with
    the result, so a retry reports its own (#511).

    **Test steps:**

    * make the cache report two rows changed by the scan it applies, and run a scan
    * verify ``touched_rows`` holds them, was empty before the run, and is empty again after a reset
    """
    cache.signatures.return_value = {}
    cache.apply_root_scan.side_effect = touching(7, 9)
    scan_returning(mocker, RootScanResult(ROOT, RootScanOutcome.SCANNED))
    job = scan_job()
    assert job.touched_rows == frozenset()

    job.run(FakeControl())

    assert job.touched_rows == frozenset({7, 9})
    job.reset()
    assert job.touched_rows == frozenset()


def catalog_root(root_id: UUID, path: Path) -> CatalogRoot:
    """A reachable cache row for a root at ``path``.

    :param root_id: the root's id.
    :param path: its folder.
    :returns: the row.
    """
    return CatalogRoot(root_id, path.name, path, 0, False, True, None)


def test_a_scan_fences_off_the_catalogs_other_roots_read_when_it_runs(mocker: MockerFixture, cache: MagicMock) -> None:
    """The other roots are what the cache holds when the job runs, its own root left out -- and a job restored from the
    saved queue, which carries no roots, reads them the same way (#498).

    **Test steps:**

    * make the cache hold the scanned root and two others
    * run a fresh job, and one restored from the first one's saved state
    * verify each scan was handed the two others and not its own root, and the saved state gained no key
    """
    other, another = catalog_root(uuid4(), Path("/fake/other")), catalog_root(uuid4(), Path("/fake/another"))
    cache.roots.return_value = [other, catalog_root(ROOT_ID, ROOT), another]
    cache.signatures.return_value = {}
    scan_class = scan_returning(mocker, RootScanResult(ROOT, RootScanOutcome.SCANNED))
    job = scan_job()
    state = job.capture_state()
    restored = DEFAULT_TASK_JOB_REGISTRY.create(REHUDB_SCAN_KIND, state)
    assert isinstance(restored, ScanCatalogRootJob)

    for each in (job, restored):
        each.run(FakeControl())

        assert scan_class.call_args.kwargs["others"] == [other, another]
    assert set(state) == {"cache", "root_id", "root_label", "path"}


def test_a_scan_reports_the_roots_it_met_and_the_records_it_found_twice_until_reset(
    mocker: MockerFixture, cache: MagicMock
) -> None:
    """``met_roots`` is the last scan's, and ``hardlinked`` every second name dropped -- the scan's own, within the
    root, and the cache's, across roots -- both empty before a run and after a reset (#498).

    **Test steps:**

    * make the scan meet a root and drop one name of its own, with an identity, and the cache drop another across roots
    * check both properties are empty before the run
    * run the job; verify the identities reached the cache, the met root, and both dropped names, the scan's first
    * reset; verify both are empty again
    """
    met = uuid4()
    across = HardlinkedRecord(uuid4(), "elsewhere.rehu", ROOT_ID, "b.rehu")
    result = RootScanResult(
        ROOT,
        RootScanOutcome.SCANNED,
        identities={"a.rehu": "1:2"},
        hardlinked=(("a.rehu", "c.rehu"),),
        met_roots=frozenset({met}),
    )

    def apply(*_: object, effects: RootScanEffects, **__: object) -> bool:
        """Drop one more name across roots, and answer applied."""
        effects.hardlinked.append(across)
        return True

    cache.signatures.return_value = {}
    cache.apply_root_scan.side_effect = apply
    scan_returning(mocker, result)
    job = scan_job()
    assert (job.met_roots, job.hardlinked) == (frozenset(), ())

    job.run(FakeControl())

    assert cache.apply_root_scan.call_args.kwargs["identities"] == {"a.rehu": "1:2"}
    assert job.met_roots == frozenset({met})
    assert job.hardlinked == (HardlinkedRecord(ROOT_ID, "a.rehu", ROOT_ID, "c.rehu"), across)
    job.reset()
    assert (job.met_roots, job.hardlinked) == (frozenset(), ())


def test_a_rescan_compares_against_the_cached_rows_and_reports_against_their_count(
    mocker: MockerFixture, cache: MagicMock
) -> None:
    """The root's rows are what the scan skips by, and how many there were is the total -- raised, not exceeded,
    when more turn up."""
    known = {"a.rehu": mocker.sentinel.a, "b.rehu": mocker.sentinel.b}
    cache.signatures.return_value = known
    scan_class = mocker.patch("rehuco_core.rehudb_jobs.CatalogRootScan")

    def scanning() -> RootScanResult:
        for done in (1, 2, 3):
            scan_class.call_args.kwargs["progress"](done)
        return RootScanResult(ROOT, RootScanOutcome.SCANNED)

    scan_class.return_value.scan.side_effect = scanning
    control = FakeControl()

    scan_job().run(control)

    cache.signatures.assert_called_once_with(ROOT_ID)
    assert scan_class.call_args.kwargs["known"] is known
    assert control.reports == [(0, 2), (1, 2), (2, 2), (3, 3)]


@mark.parametrize("outcome", [RootScanOutcome.OFFLINE, RootScanOutcome.WENT_OFFLINE])
def test_an_offline_root_keeps_its_rows(mocker: MockerFixture, cache: MagicMock, outcome: RootScanOutcome) -> None:
    """Nothing is applied; the root is marked, and the job still finishes, having touched no row -- not even the ones an
    earlier run of it did (#511).

    **Test steps:**

    * run a scan that touches a row, then run the same job again over a root that is offline
    * verify the second run applied nothing, marked the root unreachable, and left ``touched_rows`` empty
    """
    cache.signatures.return_value = {}
    cache.apply_root_scan.side_effect = touching(3)
    scan_class = scan_returning(mocker, RootScanResult(ROOT, RootScanOutcome.SCANNED))
    job = scan_job()
    job.run(FakeControl())
    cache.apply_root_scan.reset_mock()
    scan_class.return_value.scan.side_effect = None
    scan_class.return_value.scan.return_value = RootScanResult(ROOT, outcome)

    job.run(FakeControl())

    cache.apply_root_scan.assert_not_called()
    cache.mark_root_unreachable.assert_called_once_with(ROOT_ID)
    assert job.touched_rows == frozenset()


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


def test_a_retried_scan_reports_its_own_run(mocker: MockerFixture, cache: MagicMock) -> None:
    """Resetting drops the last scan's result along with the stop request."""
    del cache
    scan_returning(mocker, RootScanResult(ROOT, RootScanOutcome.SCANNED))
    job = scan_job()
    job.run(FakeControl())

    job.reset()

    assert job.result is None


def test_a_scan_that_names_nothing_refuses_to_run() -> None:
    """A job built bare and never restored says what it is missing rather than scanning nothing."""
    with raises(ValueError, match="no folder"):
        ScanCatalogRootJob().run(FakeControl())
    with raises(ValueError, match="no root"):
        ScanCatalogRootJob(CACHE, root=ROOT).run(FakeControl())


def test_a_root_removal_with_no_cache_refuses_to_run() -> None:
    """There is no file to remove the root from."""
    with raises(ValueError, match="no cache"):
        RemoveCatalogRootJob(None, ROOT_ID).run(FakeControl())


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
