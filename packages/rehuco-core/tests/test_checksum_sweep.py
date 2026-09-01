"""Tests for the catalog-wide checksum sweep (#242).

Unlike `test_checksum_jobs`, the run underneath is **not** mocked: what this module is about is the
interaction between staleness, a record written per resource, and a sweep that has to be resumable from
its own output -- none of which can be asserted against a mocked ``verify_checksums``. So the real
enumeration, the real record and the real digests run over a fake disk that counts reads and writes,
and the claims *a second sweep reads nothing* and *an interrupted sweep continues* are measured rather
than stated.
"""

import json
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final

from fake_directories import FakeDirEntry, FakeScandir
from freezegun.api import FrozenDateTimeFactory
from pytest import fixture, mark, raises
from pytest_mock import MockerFixture
from rehuco_core import (
    CHECKSUM_SWEEP_KIND,
    DEFAULT_TASK_JOB_REGISTRY,
    LEGACY_SCREENSHOT_RULES,
    PROGRESS_UNIT_RESOURCES,
    ContentUnreachableError,
    JobPaused,
    SweepChecksumsJob,
    SweepTally,
    generate_checksums,
    legacy_screenshot_rules_state,
    sweep_summary,
)

ROOT: Final = Path("/fake/library")

SCULPTING: Final = ROOT / "sculpting" / "info.rehu"
PAINTING: Final = ROOT / "painting" / "info.rehu"
PACK: Final = ROOT / "packs" / "brushes.rehu"

RESOURCES: Final = (PACK, PAINTING, SCULPTING)
"""Every resource the fixture's catalog holds, in the order the walk returns them (sorted by path)."""

NOW: Final = "2026-08-05T12:00:00Z"
LATER: Final = "2026-08-09T12:00:00Z"
MUCH_LATER: Final = "2026-11-05T12:00:00Z"
LONG_AGO: Final = "2026-01-01T00:00:00Z"

WEEK: Final = timedelta(days=7)

TIMEOUT: Final = 5.0


# region Fakes


# the filesystem faces below are `test_rehu_checksums.FakeDisk`'s, near-verbatim -- kept as a separate
# copy rather than shared, matching this codebase's fake-disk convention: what differs is which walk
# each one serves, and a shared base parameterized on that would hide exactly the distinction these
# tests turn on
# pylint: disable=duplicate-code
class FakeCatalog:
    """A library of several resources, and a record of what was read and written.

    Serves the four ways this code reaches a filesystem from one dictionary, the way
    `test_rehu_checksums`' own fake does -- with one addition: the **catalog** walk and the **content**
    walk are served separately, so a test can take a mount away from one and not the other. That is not
    a contrivance; it is how a mount that goes away mid-sweep looks, since the catalog was listed before
    it went.

    :param files: every file in the library, keyed by path relative to :data:`ROOT`, POSIX-separated.
    """

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files: Final[dict[Path, bytes]] = {ROOT / name: payload for name, payload in files.items()}
        self.reads: list[Path] = []
        """Every content file opened for reading, in order."""
        self.bytes_read = 0
        """How many bytes have been handed to a digest."""
        self.writes: list[Path] = []
        """Every record written, in order."""
        self.offline_directories: Final[set[Path]] = set()
        """Directories the *content* walk and the reader cannot see -- an away mount."""
        self.catalog_offline_directories: Final[set[Path]] = set()
        """Directories the *catalog* walk cannot see."""

    # region Filesystem faces

    def scandir(self, directory: Path | str) -> FakeScandir:
        """List one directory for the content walk.

        :param directory: the directory to read.
        :returns: its entries -- files directly in it, and one entry per immediate subdirectory.
        :raises PermissionError: the directory is offline.
        :raises FileNotFoundError: nothing lives at or under ``directory``.
        """
        return self.__scandir(Path(directory), self.offline_directories)

    def catalog_scandir(self, directory: Path | str) -> FakeScandir:
        """List one directory for the catalog walk.

        :param directory: the directory to read.
        :returns: its entries.
        :raises PermissionError: the directory is offline to the catalog walk.
        :raises FileNotFoundError: nothing lives at or under ``directory``.
        """
        return self.__scandir(Path(directory), self.catalog_offline_directories)

    def open(self, path: Path) -> BytesIO:
        """Serve a content file's bytes, counting the read.

        :param path: the file to open.
        :returns: a fresh reader over its bytes, counting what is taken from it.
        :raises OSError: it sits behind an away mount, or nothing lives there.
        """
        payload = self.__payload(path)
        self.reads.append(Path(path))
        handle = BytesIO(payload)
        original_read = handle.read

        def read(size: int = -1) -> bytes:
            chunk = original_read(size)
            self.bytes_read += len(chunk)
            return chunk

        handle.read = read  # pyright: ignore[reportAttributeAccessIssue]
        return handle

    def stat(self, path: Path) -> SimpleNamespace:
        """Answer a file's size.

        :param path: the file to measure.
        :returns: an object carrying ``st_size``, the one member the size plan reads.
        :raises OSError: nothing lives at ``path``.
        """
        return SimpleNamespace(st_size=len(self.__payload(path)))

    def read_text(self, path: Path) -> str:
        """Read a file as UTF-8 text -- how a record is loaded.

        :param path: the file to read.
        :returns: its decoded contents.
        :raises OSError: nothing lives at ``path``.
        """
        return self.__payload(path).decode("utf-8")

    def write_text(self, path: Path | str, text: str) -> None:
        """Replace a file's contents -- how a record is saved.

        :param path: the file to write.
        :param text: what to write.
        """
        self.writes.append(Path(path))
        self.files[Path(path)] = text.encode("utf-8")

    def is_dir(self, path: Path) -> bool:
        """Whether anything lives under ``path`` -- what a sweep's validation asks.

        :param path: the candidate directory.
        :returns: whether the library holds a file beneath it.
        """
        return any(path in candidate.parents for candidate in self.files)

    # endregion

    # region Test-side conveniences

    def record_of(self, rehu_path: Path) -> dict[str, Any]:
        """One resource's record as it now stands on disk.

        :param rehu_path: the resource's ``.rehu`` file.
        :returns: the parsed record object.
        """
        return json.loads(self.files[rehu_path.with_suffix(".checksum")].decode("utf-8"))

    def entries_of(self, rehu_path: Path) -> dict[str, dict[str, Any]]:
        """One resource's record entries by name.

        :param rehu_path: the resource's ``.rehu`` file.
        :returns: name to entry.
        """
        return {entry["name"]: entry for entry in self.record_of(rehu_path)["files"]}

    def date_entry(self, rehu_path: Path, name: str, verified: str) -> None:
        """Re-date one recorded entry, so a test can make part of a resource stale.

        :param rehu_path: the resource's ``.rehu`` file.
        :param name: the entry to re-date.
        :param verified: the stamp to write.
        """
        record = self.record_of(rehu_path)
        for entry in record["files"]:
            if entry["name"] == name:
                entry["verified"] = verified
        self.files[rehu_path.with_suffix(".checksum")] = json.dumps(record).encode("utf-8")

    def add_entry(self, rehu_path: Path, entry: dict[str, Any]) -> None:
        """Append a raw entry to one resource's record, as an older coverage rule would have left it.

        :param rehu_path: the resource's ``.rehu`` file.
        :param entry: the raw entry to append.
        """
        record = self.record_of(rehu_path)
        record["files"].append(entry)
        self.files[rehu_path.with_suffix(".checksum")] = json.dumps(record).encode("utf-8")

    def forget(self) -> None:
        """Clear the counters, so one run's reads and writes are counted on their own."""
        self.reads = []
        self.bytes_read = 0
        self.writes = []

    # endregion

    def __scandir(self, directory: Path, offline: set[Path]) -> FakeScandir:
        """One directory listing, derived from the current file set.

        :param directory: the directory to read.
        :param offline: the directories this caller cannot see.
        :returns: its entries.
        :raises PermissionError: the directory is offline to this caller.
        :raises FileNotFoundError: nothing lives at or under ``directory``.
        """
        if directory in offline:
            raise PermissionError(str(directory))
        entries: list[FakeDirEntry] = []
        subdirectories: set[str] = set()
        for path in self.files:
            if path.parent == directory:
                entries.append(FakeDirEntry(path.name))
            elif directory in path.parents:
                subdirectories.add(path.relative_to(directory).parts[0])
        if not entries and not subdirectories and directory != ROOT:
            raise FileNotFoundError(str(directory))
        entries.extend(FakeDirEntry(name, directory=True) for name in sorted(subdirectories))
        return FakeScandir(entries)

    def __payload(self, path: Path) -> bytes:
        """One file's bytes.

        :param path: the file.
        :returns: its contents.
        :raises PermissionError: it sits under a directory that would not list.
        :raises FileNotFoundError: nothing lives at ``path``.
        """
        if any(directory in Path(path).parents for directory in self.offline_directories):
            raise PermissionError(str(path))
        payload = self.files.get(Path(path))
        if payload is None:
            raise FileNotFoundError(str(path))
        return payload


# pylint: enable=duplicate-code


class FakeControl:  # pylint: disable=too-few-public-methods  # the protocol has exactly one method
    """A stand-in for the engine's :class:`~rehuco_core.JobControl`, recording what it was told.

    :param on_report: called after each report, so a test can stop the job part-way through.
    """

    def __init__(self, on_report: Any = None) -> None:
        self.reports: list[tuple[int, int | None]] = []
        self.__on_report: Final = on_report

    def report(self, done: int, total: int | None = None) -> None:
        """Record one progress report.

        :param done: resources finished so far.
        :param total: resources in all.
        """
        self.reports.append((done, total))
        if self.__on_report is not None:
            self.__on_report(done)


@fixture(name="catalog")
def fixture_catalog(mocker: MockerFixture, freezer: FrozenDateTimeFactory) -> FakeCatalog:
    """A library of three resources, each already carrying a record dated :data:`NOW`.

    Two directory-scoped and one file-scoped, so the sweep is exercised over both scoping rules; the
    records are seeded through the real generate, so the digests a verify checks against are the ones
    the code itself would have written.

    :param mocker: pytest-mock fixture.
    :param freezer: the frozen clock, started at :data:`NOW`.
    :returns: the disk under the code's feet.
    """
    freezer.move_to(NOW)
    catalog = FakeCatalog(
        {
            "sculpting/info.rehu": b'{"format_version": 2}',
            "sculpting/info00.jpg": b"a screenshot",
            "sculpting/lesson1.mp4": bytes(range(256)) * 4,
            "sculpting/extras/pack.zip": bytes(range(255, -1, -1)) * 3,
            "painting/info.rehu": b'{"format_version": 2}',
            "painting/lesson1.mp4": bytes(range(128)) * 5,
            "packs/brushes.rehu": b'{"format_version": 2}',
            "packs/brushes.zip": bytes(range(64)) * 9,
        }
    )
    mocker.patch("rehuco_core.rehu_content_files.os.scandir", side_effect=catalog.scandir)
    mocker.patch("rehuco_core.rehu_catalog.os.scandir", side_effect=catalog.catalog_scandir)
    mocker.patch("rehuco_core.content_reading.shared_read_open", side_effect=catalog.open)
    mocker.patch("rehuco_core.checksum_record.atomic_write_text", side_effect=catalog.write_text)
    mocker.patch.object(Path, "stat", autospec=True, side_effect=lambda self, **_kwargs: catalog.stat(self))
    mocker.patch.object(Path, "read_text", autospec=True, side_effect=lambda self, **_kwargs: catalog.read_text(self))
    mocker.patch.object(Path, "is_dir", autospec=True, side_effect=catalog.is_dir)
    for rehu_path in RESOURCES:
        generate_checksums(rehu_path)
    catalog.forget()
    return catalog


def sweep(**kwargs: Any) -> SweepChecksumsJob:
    """Build a sweep over the fixture's library.

    :param kwargs: whatever the test wants to override.
    :returns: the job.
    """
    return SweepChecksumsJob(ROOT, **kwargs)


def run(job: SweepChecksumsJob, control: FakeControl | None = None) -> FakeControl:
    """Run a sweep with a control, returning it for inspection.

    :param job: the sweep to run.
    :param control: the control to use, or ``None`` for a fresh recording one.
    :returns: the control the run reported to.
    """
    used = control if control is not None else FakeControl()
    job.run(used)  # pyright: ignore[reportArgumentType]
    return used


# endregion


# region Skipping what was checked recently


def test_a_second_sweep_inside_the_window_opens_no_file_at_all(catalog: FakeCatalog) -> None:
    """The point of the whole feature: a catalog checked last week is not re-hashed this week (#242).

    **Test steps:**

    * sweep the library whose records were just written, with a week-long window
    * check nothing was opened, no byte was read and no record was rewritten
    """
    job = sweep(stale_after=WEEK)

    run(job)

    assert catalog.reads == []
    assert catalog.bytes_read == 0
    assert catalog.writes == []


def test_the_same_sweep_with_no_window_re_reads_everything(catalog: FakeCatalog) -> None:
    """``timedelta(0)`` leaves nothing fresh, which is what the settings page's *0 days* means.

    **Test steps:**

    * sweep the same library with the window at zero
    * check every content file was read
    """
    run(sweep(stale_after=timedelta(0)))

    assert sorted(catalog.reads) == [
        ROOT / "packs/brushes.zip",
        ROOT / "painting/lesson1.mp4",
        ROOT / "sculpting/extras/pack.zip",
        ROOT / "sculpting/lesson1.mp4",
    ]


def test_a_resource_half_fresh_reads_exactly_the_stale_half(
    catalog: FakeCatalog, freezer: FrozenDateTimeFactory
) -> None:
    """Staleness is per file, not per resource, so a partly-checked resource costs only its remainder.

    **Test steps:**

    * age one of the sculpting resource's two entries out of the window
    * sweep with a week-long window
    * check exactly that one file was read
    """
    catalog.date_entry(SCULPTING, "lesson1.mp4", LONG_AGO)
    freezer.move_to(LATER)

    run(sweep(stale_after=WEEK))

    assert catalog.reads == [ROOT / "sculpting/lesson1.mp4"]


# endregion


# region Resuming from its own output


def test_an_interrupted_sweep_continues_from_the_resources_it_had_not_written(
    catalog: FakeCatalog, freezer: FrozenDateTimeFactory
) -> None:
    """The records already written *are* the cursor ([[appendices.task-queue#cursor]], #242).

    **Test steps:**

    * age the whole library out of the window and pause the sweep after its first resource
    * check exactly one record was written
    * re-enter the run and check the first resource was not read again while the rest were
    """
    freezer.move_to(MUCH_LATER)
    job = sweep(stale_after=WEEK)
    control = FakeControl(on_report=lambda done: job.pause() if done == 1 else None)

    with raises(JobPaused):
        run(job, control)

    assert catalog.writes == [PACK.with_suffix(".checksum")]
    catalog.forget()
    job.resume()

    run(job)

    assert ROOT / "packs/brushes.zip" not in catalog.reads
    assert sorted(catalog.writes) == [
        PAINTING.with_suffix(".checksum"),
        SCULPTING.with_suffix(".checksum"),
    ]


def test_a_sweep_with_a_window_says_pausing_keeps_its_work(catalog: FakeCatalog) -> None:
    """The one bit that crosses the job's boundary, and it has to be true at the setting in force.

    **Test steps:**

    * build a sweep with a window and one with the window at zero
    * check only the first claims to resume where it stopped
    """
    del catalog

    assert sweep(stale_after=WEEK).resumes_where_it_stopped
    assert not sweep(stale_after=timedelta(0)).resumes_where_it_stopped
    assert not sweep().resumes_where_it_stopped


# endregion


# region One bad resource costs itself


def test_a_resource_that_cannot_be_read_is_counted_and_the_sweep_carries_on(
    catalog: FakeCatalog, freezer: FrozenDateTimeFactory
) -> None:
    """A catalog-wide run that died on its first offline mount would be useless (#245).

    **Test steps:**

    * take one resource's directory away after the catalog was listed
    * sweep the library
    * check that resource is counted as failed and the others were still verified
    """
    freezer.move_to(MUCH_LATER)
    catalog.offline_directories.add(PAINTING.parent)

    job = sweep(stale_after=WEEK)
    run(job)

    assert job.tally is not None
    assert job.tally.failed == 1
    assert job.tally.verified == 2


def test_a_resource_with_no_record_is_counted_rather_than_failed(
    catalog: FakeCatalog, freezer: FrozenDateTimeFactory
) -> None:
    """*No record yet* is an expected state, and the count is what makes the setting discoverable.

    **Test steps:**

    * delete one resource's record and sweep
    * check it was counted as having none, and the others were verified
    """
    freezer.move_to(MUCH_LATER)
    del catalog.files[PAINTING.with_suffix(".checksum")]

    job = sweep(stale_after=WEEK)
    run(job)

    assert job.tally is not None
    assert job.tally.without_record == 1
    assert job.tally.failed == 0
    assert job.tally.verified == 2


def test_a_sweep_counts_the_entries_it_pruned_across_the_catalog(
    catalog: FakeCatalog, freezer: FrozenDateTimeFactory
) -> None:
    """A catalog swept for the first time under exclusive coverage cleans up as it goes (#254).

    This is the state a bulk import leaves a whole library in: every converted resource's own
    ``info.tc.orig`` adopted into its baseline, and every one of them dropped by the next sweep.

    **Test steps:**

    * put a retained backup in two resources and add an entry for each to their records
    * sweep with everything already stale
    * check both were dropped from their records and counted once in the tally
    """
    freezer.move_to(MUCH_LATER)
    for rehu_path in (SCULPTING, PAINTING):
        catalog.files[rehu_path.parent / "info.tc.orig"] = b"the record as tc4 wrote it"
        catalog.add_entry(rehu_path, {"name": "info.tc.orig", "xxh3": "0" * 16, "verified": NOW, "status": "matched"})

    job = sweep(stale_after=WEEK)
    run(job)

    assert job.tally is not None
    assert job.tally.pruned == 2
    assert "info.tc.orig" not in catalog.entries_of(SCULPTING)
    assert "info.tc.orig" not in catalog.entries_of(PAINTING)


def test_a_sweep_moves_a_claim_to_the_record_that_covers_it_now(
    catalog: FakeCatalog, freezer: FrozenDateTimeFactory
) -> None:
    """The other half of catching up with exclusive coverage, over a whole catalog (#257).

    A nested record appearing under a resource that was already checksummed is the common shape: the
    archive's claim exists only in the record above it, and the sweep hands it down. **Which order the
    two resources are swept in does not matter** -- the nested one is walked first here, so the claim
    arrives after its own verify has run and is checked on the next sweep, which is exactly what a
    dateless entry is for.

    **Test steps:**

    * drop a nested ``info.rehu`` beside a resource's archive, after both records were written
    * sweep with everything already stale
    * check the entry left the enclosing record, arrived in the nested one, and was counted once
    """
    freezer.move_to(MUCH_LATER)
    nested = ROOT / "sculpting" / "extras" / "info.rehu"
    catalog.files[nested] = b'{"format_version": 2}'

    job = sweep(stale_after=WEEK)
    run(job)

    assert job.tally is not None
    assert job.tally.moved == 1
    assert "extras/pack.zip" not in catalog.entries_of(SCULPTING)
    assert "pack.zip" in catalog.entries_of(nested)


def test_a_sweep_allowed_to_create_records_baselines_the_resource_that_had_none(
    catalog: FakeCatalog, freezer: FrozenDateTimeFactory
) -> None:
    """*Create missing checksum on verify* is what turns a sweep into the thing that adopts (#242).

    **Test steps:**

    * delete one resource's record and sweep with creation allowed
    * check the record came back holding its content file
    """
    freezer.move_to(MUCH_LATER)
    del catalog.files[PAINTING.with_suffix(".checksum")]

    job = sweep(stale_after=WEEK, create_if_missing=True)
    run(job)

    assert job.tally is not None
    assert job.tally.without_record == 0
    assert list(catalog.entries_of(PAINTING)) == ["lesson1.mp4"]


def test_a_root_that_will_not_list_fails_the_sweep(catalog: FakeCatalog) -> None:
    """A folder that would not list means the run has nothing to say, which is not a clean sweep (#245).

    **Test steps:**

    * take the library root away and run the sweep
    * check it refuses rather than reporting an empty catalog
    """
    catalog.catalog_offline_directories.add(ROOT)

    with raises(ContentUnreachableError):
        run(sweep(stale_after=WEEK))


def test_an_offline_branch_costs_its_resources_and_is_counted(catalog: FakeCatalog) -> None:
    """A branch the walk could not list has no resources to verify, and that has to be said out loud.

    **Test steps:**

    * take one branch away from the catalog walk and sweep
    * check the branch was counted and the remaining resources were still found
    """
    catalog.catalog_offline_directories.add(PAINTING.parent)

    job = sweep(stale_after=WEEK)
    run(job)

    assert job.tally is not None
    assert job.tally.resources == 2
    assert job.tally.unreadable_branches == 1


# endregion


# region What the queue reads


def test_progress_counts_resources_and_names_the_total_before_the_first_read(catalog: FakeCatalog) -> None:
    """The walk runs first, so the bar has its denominator before the slow part starts (#242).

    **Test steps:**

    * sweep the library
    * check the first report named the total and the rest counted up to it
    """
    del catalog
    control = run(sweep(stale_after=WEEK))

    assert control.reports == [(0, 3), (1, 3), (2, 3), (3, 3)]


def test_a_sweep_declares_that_it_counts_resources(catalog: FakeCatalog) -> None:
    """The numbers above are resources where a verify's are bytes, and the declaration is what makes
    the two tellable apart downstream (#248).

    **Test steps:**

    * build a sweep
    * check the unit it declares
    """
    del catalog

    assert sweep(stale_after=WEEK).progress_unit == PROGRESS_UNIT_RESOURCES


def test_a_sweep_names_the_folder_it_is_over(catalog: FakeCatalog) -> None:
    """A queue of sweeps must not be a queue of identical rows.

    **Test steps:**

    * build a sweep with no label of its own
    * check it named itself after the folder
    """
    del catalog

    assert sweep(stale_after=WEEK).label == "Sweep checksums - library"


def test_a_sweep_over_a_folder_that_is_not_there_refuses_to_start(catalog: FakeCatalog) -> None:
    """A folder deleted while the sweep sat in the queue fails with a sentence, not an exception.

    **Test steps:**

    * validate a sweep over a folder holding nothing, and one with no folder at all
    * check each refused with its own sentence
    """
    del catalog
    missing = ROOT / "nowhere"

    assert SweepChecksumsJob(missing).validate() == f"The folder to sweep is not there: {missing}"
    assert SweepChecksumsJob().validate() == "This task has no folder to sweep."
    with raises(ValueError):
        SweepChecksumsJob().root_path()


def test_a_sweep_that_can_still_run_validates(catalog: FakeCatalog) -> None:
    """The ordinary case, so the refusals above are not vacuous.

    **Test steps:**

    * validate a sweep over the library
    * check it may start
    """
    del catalog

    assert sweep().validate() is None


# endregion


# region Being written down


def test_a_sweep_writes_down_what_it_needs_to_be_itself_again(catalog: FakeCatalog) -> None:
    """The state is JSON primitives, which is why the window is written as whole days.

    **Test steps:**

    * capture a fully configured sweep
    * check every value is a JSON primitive
    """
    del catalog

    captured = sweep(
        stale_after=WEEK, create_if_missing=True, migrate_to="crc32", excluded_patterns=("*.tmp",)
    ).capture_state()

    assert captured == {
        "path": str(ROOT),
        "algorithm": "xxh3",
        "stale_days": 7,
        "create_if_missing": True,
        "migrate_to": "crc32",
        "excluded_patterns": ["*.tmp"],
        "legacy_screenshot_rules": legacy_screenshot_rules_state(LEGACY_SCREENSHOT_RULES),
    }


def test_a_restored_sweep_is_the_sweep_that_was_queued(catalog: FakeCatalog) -> None:
    """A capture/restore round trip preserves the folder and every choice made about the run.

    **Test steps:**

    * restore a fresh sweep from another's captured state
    * check what it will run over
    """
    del catalog
    captured = sweep(stale_after=WEEK, create_if_missing=True, migrate_to="crc32").capture_state()
    restored = SweepChecksumsJob()

    restored.restore_state(captured)

    assert restored.source == ROOT
    assert restored.stale_after == WEEK
    assert restored.create_if_missing
    assert restored.migrate_to == "crc32"
    assert restored.label == "Sweep checksums - library"


def test_a_sweep_with_no_window_round_trips_as_one(catalog: FakeCatalog) -> None:
    """``None`` is *force*, and a restore that turned it into a window would quietly skip work.

    **Test steps:**

    * capture and restore a sweep with no window
    * check it still has none
    """
    del catalog
    restored = SweepChecksumsJob()

    restored.restore_state(sweep().capture_state())

    assert restored.stale_after is None


@mark.parametrize(
    "state",
    [
        {},
        {"path": ""},
        {"path": str(ROOT), "algorithm": "rot13"},
        {"path": str(ROOT), "migrate_to": "rot13"},
        {"path": str(ROOT), "stale_days": "a week"},
    ],
    ids=["no path", "empty path", "unknown algorithm", "unknown migration target", "window is not a number"],
)
def test_a_state_that_does_not_describe_a_runnable_sweep_is_refused(state: dict[str, Any]) -> None:
    """A hand-edited file costs its own item rather than the app's start.

    **Test steps:**

    * restore from each unusable state
    * check it raises, which is what makes the registry drop the item
    """
    with raises(ValueError):
        SweepChecksumsJob().restore_state(state)


def test_the_sweep_kind_is_registered_so_a_saved_queue_can_rebuild_it() -> None:
    """A sweep outlives the session it was queued in ([[appendices.task-queue#lifetime]]).

    **Test steps:**

    * create the sweep kind from the app-wide registry
    * check the class and the restored folder
    """
    job = DEFAULT_TASK_JOB_REGISTRY.create(CHECKSUM_SWEEP_KIND, {"path": str(ROOT)})

    assert isinstance(job, SweepChecksumsJob)
    assert job.source == ROOT


def test_a_retry_drops_the_last_sweep_s_findings(catalog: FakeCatalog) -> None:
    """A retried run reports its own answer rather than the one before it.

    **Test steps:**

    * run a sweep, then reset it the way Retry does
    * check the tally is gone
    """
    del catalog
    job = sweep(stale_after=WEEK)
    run(job)

    job.reset()

    assert job.tally is None


# endregion


# region Summaries


@mark.parametrize(
    ("tally", "expected"),
    [
        (SweepTally(resources=1), "1 resource"),
        (SweepTally(resources=3, statuses={"matched": 210, "mismatched": 2}), "3 resources, 210 matched, 2 mismatched"),
        (SweepTally(resources=2, without_record=1, failed=1), "2 resources, 1 without a record, 1 failed"),
        (SweepTally(resources=0, unreadable_branches=2), "0 resources, 2 unreadable directories"),
        (SweepTally(resources=0, unreadable_branches=1), "0 resources, 1 unreadable directory"),
        (SweepTally(resources=2, statuses={"matched": 4}, pruned=3), "2 resources, 4 matched, 3 pruned"),
        (SweepTally(resources=2, statuses={"matched": 4}, moved=1), "2 resources, 4 matched, 1 moved"),
    ],
    ids=["one resource", "verdicts", "not checked", "branches", "one branch", "pruned", "moved"],
)
def test_a_summary_says_what_a_sweep_established(tally: SweepTally, expected: str) -> None:
    """One line, in :func:`~rehuco_core.checksum_report_summary`'s voice.

    **Test steps:**

    * summarize each tally
    * check the sentence
    """
    assert sweep_summary(tally) == expected


# endregion
