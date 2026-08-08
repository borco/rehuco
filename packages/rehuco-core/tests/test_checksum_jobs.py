"""Tests for the two checksum runs as task-queue jobs (#204).

The runs themselves are `test_rehu_checksums`' subject and are mocked away here: what this module is
about is the wrapping -- what the queue reads off a job, what a stop costs, what is written down, and
that the job is registered so a saved queue can rebuild it. One test runs a job through a **real**
:class:`~rehuco_core.TaskQueue`, because "the action enqueues rather than executes" is only worth
asserting against the engine that actually runs it.
"""

from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path
from threading import Event
from typing import Any, Final

from pytest import fixture, mark, raises
from pytest_mock import MockerFixture
from rehuco_core import (
    CHECKSUM_GENERATE_KIND,
    CHECKSUM_VERIFY_KIND,
    DEFAULT_CHECKSUM_ALGORITHM,
    DEFAULT_TASK_JOB_REGISTRY,
    FINISHED_JOB_STATES,
    PROGRESS_UNIT_BYTES,
    PRUNE_REASONS,
    ChecksumJob,
    ChecksumReport,
    CoveringRecord,
    GenerateChecksumsJob,
    JobCancelled,
    JobPaused,
    JobState,
    JobStatus,
    RenameCoordinator,
    TaskJobRegistry,
    TaskQueue,
    VerifyChecksumsJob,
    checksum_report_summary,
)

DIRECTORY: Final = Path("/fake/library/sculpting")
INFO_PATH: Final = DIRECTORY / "info.rehu"
RECORD_PATH: Final = DIRECTORY / "info.checksum"
ARCHIVE_REHU_PATH: Final = DIRECTORY / "pack.rehu"

VIDEO: Final = "lesson1.mp4"
ARCHIVE: Final = "extras/pack.zip"

TIMEOUT: Final = 5.0
"""How long a test waits for the worker thread, in seconds -- generous, because it only ever expires
when something is genuinely wrong."""


# region Fakes


class FakeControl:  # pylint: disable=too-few-public-methods  # the protocol has exactly one method
    """A stand-in for the engine's :class:`~rehuco_core.JobControl`, recording what it was told."""

    def __init__(self) -> None:
        self.reports: list[tuple[int, int | None]] = []

    def report(self, done: int, total: int | None = None) -> None:
        """Record one progress report.

        :param done: bytes hashed so far.
        :param total: bytes expected in all.
        """
        self.reports.append((done, total))


class FinishedListener:
    """Waits for a known number of jobs to reach a state they never leave on their own.

    :attr:`~rehuco_core.TaskQueue.wait_until_idle` answers *nothing is running*, which is vacuously
    true in the instant between an enqueue and the worker picking the job up -- so a test that waits on
    it alone races the very thread it is testing.

    :param expected: how many jobs to wait for.
    """

    def __init__(self, expected: int) -> None:
        self.__expected: Final = expected
        self.__finished: Final[set[int]] = set()
        self.reached: Final = Event()

    def wait(self, timeout: float = TIMEOUT) -> bool:
        """Wait for every expected job to finish.

        :param timeout: how long to wait, in seconds.
        :returns: whether they all did.
        """
        return self.reached.wait(timeout)

    def job_enqueued(self, status: JobStatus, index: int) -> None:
        """See :class:`~rehuco_core.TaskQueueListener`."""
        del index
        self.job_updated(status)

    def job_updated(self, status: JobStatus) -> None:
        """See :class:`~rehuco_core.TaskQueueListener`."""
        if status.state in FINISHED_JOB_STATES:
            self.__finished.add(status.serial)
        if len(self.__finished) >= self.__expected:
            self.reached.set()

    def jobs_reordered(self, serials: Sequence[int]) -> None:
        """See :class:`~rehuco_core.TaskQueueListener`."""
        del serials

    def jobs_removed(self, serials: Sequence[int]) -> None:
        """See :class:`~rehuco_core.TaskQueueListener`."""
        del serials

    def queue_paused_changed(self, paused: bool) -> None:
        """See :class:`~rehuco_core.TaskQueueListener`."""
        del paused


@fixture(name="control")
def fixture_control() -> FakeControl:
    """The control a job is handed while it runs.

    :returns: the recording control.
    """
    return FakeControl()


@fixture(name="present")
def fixture_present(mocker: MockerFixture) -> None:
    """A filesystem where every path a job asks about exists -- the uninteresting case.

    :param mocker: pytest-mock fixture.
    """
    mocker.patch.object(Path, "exists", autospec=True, return_value=True)


# endregion


# region What the queue reads


@mark.parametrize(
    ("path", "expected"),
    [
        (INFO_PATH, "Verify checksums - sculpting"),
        (ARCHIVE_REHU_PATH, "Verify checksums - pack.rehu"),
        (DIRECTORY / "info.tc", "Verify checksums - sculpting"),
    ],
)
def test_a_job_names_the_resource_rather_than_its_record(path: Path, expected: str) -> None:
    """A label names the directory for a directory-scoped record and the file otherwise.

    A legacy ``info.tc`` is one of those (#250) -- a verify against the ``.sfv`` beside it is a run this
    build offers (#243), and a queue of fifty of them may not read ``info.tc`` fifty times over.

    **Test steps:**

    * build a verify job over a directory-scoped and a file-scoped resource
    * check each label names the thing a reader would recognize
    """
    assert VerifyChecksumsJob(path).label == expected


def test_an_enqueuer_may_name_the_job_itself() -> None:
    """A caller with a better name for the resource passes one, and it is kept.

    **Test steps:**

    * build a job with an explicit label
    * check the derived one was not used
    """
    assert GenerateChecksumsJob(INFO_PATH, label="Generate checksums - Sculpting Series/").label == (
        "Generate checksums - Sculpting Series/"
    )


def test_a_job_declares_what_stopping_it_costs() -> None:
    """Stopping leaves nothing behind, and resuming starts over.

    **Test steps:**

    * build a job
    * check both declarations the dock reads off a row
    """
    job = VerifyChecksumsJob(INFO_PATH)

    assert job.safely_interruptible
    assert not job.resumes_where_it_stopped


def test_a_run_declares_that_it_counts_bytes() -> None:
    """A checksum run reports bytes, which is what lets a row draw them as bytes (#248).

    **Test steps:**

    * build one of each run
    * check the unit both declare
    """
    assert GenerateChecksumsJob(INFO_PATH).progress_unit == PROGRESS_UNIT_BYTES
    assert VerifyChecksumsJob(INFO_PATH).progress_unit == PROGRESS_UNIT_BYTES


def test_a_job_follows_the_resource_it_moved(mocker: MockerFixture) -> None:
    """A rename during a run leaves ``source`` naming the new path (#241).

    **Test steps:**

    * track the resource in a coordinator and rename its directory through it
    * check the job's source answers the new path
    """
    coordinator = RenameCoordinator()
    job = VerifyChecksumsJob(INFO_PATH, coordinator=coordinator)
    renamer = mocker.MagicMock()
    renamer.execute.return_value = DIRECTORY.parent / "sculpting-2"
    renamer.relocate.side_effect = lambda path: Path(str(path).replace("sculpting", "sculpting-2"))
    mocker.patch("rehuco_core.rename_coordination.RehuRenamer", return_value=renamer)

    coordinator.rename(INFO_PATH, "sculpting-2")

    assert job.source == DIRECTORY.parent / "sculpting-2" / "info.rehu"


# endregion


# region Validation


def test_a_job_over_a_resource_that_is_gone_refuses_to_start(mocker: MockerFixture) -> None:
    """A resource deleted while the job waited fails with a sentence, not an exception out of the run.

    **Test steps:**

    * make the resource absent
    * check validate names it
    """
    mocker.patch.object(Path, "exists", autospec=True, return_value=False)

    assert VerifyChecksumsJob(INFO_PATH).validate() == f"The resource no longer exists: {INFO_PATH}"


def test_a_verify_with_no_record_refuses_before_reading_anything(mocker: MockerFixture) -> None:
    """A verify says the record is missing rather than raising ``FileNotFoundError`` from inside.

    **Test steps:**

    * make the ``.rehu`` present and the ``.checksum`` absent
    * check the verify refuses and the generate does not
    """
    mocker.patch.object(Path, "exists", autospec=True, side_effect=lambda self: self != RECORD_PATH)

    assert VerifyChecksumsJob(INFO_PATH).validate() == f"This resource has no checksum record yet: {RECORD_PATH}"
    assert GenerateChecksumsJob(INFO_PATH).validate() is None


def test_a_verify_that_may_create_the_record_does_not_refuse_a_missing_one(mocker: MockerFixture) -> None:
    """With *Create missing checksum on verify* set, no record is the starting state, not a fault (#242).

    **Test steps:**

    * make the ``.rehu`` present and the ``.checksum`` absent
    * check a verify allowed to create the record validates
    """
    mocker.patch.object(Path, "exists", autospec=True, side_effect=lambda self: self != RECORD_PATH)

    assert VerifyChecksumsJob(INFO_PATH, create_if_missing=True).validate() is None


def test_a_job_with_no_resource_at_all_refuses() -> None:
    """The path-less job the registry builds before a state arrives is not runnable.

    **Test steps:**

    * build a job with no path -- what the registry's factory does
    * check it refuses to validate and to run
    """
    job = GenerateChecksumsJob()

    assert job.validate() == "This task has no resource."
    with raises(ValueError):
        job.resource_path()


def test_the_base_is_not_a_job_on_its_own(control: FakeControl) -> None:
    """:class:`ChecksumJob` holds everything around a run and none of the run; it refuses to be one.

    **Test steps:**

    * run the base class directly
    * check it refuses
    """
    with raises(NotImplementedError):
        ChecksumJob(INFO_PATH).perform(control)  # pyright: ignore[reportArgumentType]


# endregion


# region Running


def test_a_run_hands_its_progress_and_its_checkpoint_to_the_run(
    mocker: MockerFixture, control: FakeControl, present: None
) -> None:
    """The engine's report and the job's checkpoint are what #203's callable is given.

    **Test steps:**

    * run a generate job with the underlying callable mocked
    * check the resource, the selection and both callbacks arrived
    """
    del present
    generate = mocker.patch("rehuco_core.checksum_jobs.generate_checksums", return_value=ChecksumReport())
    job = GenerateChecksumsJob(INFO_PATH, only=[VIDEO], excluded_patterns=("Thumbs.db",))

    job.run(control)  # pyright: ignore[reportArgumentType]

    generate.assert_called_once()
    assert generate.call_args.args == (INFO_PATH,)
    assert generate.call_args.kwargs["only"] == (VIDEO,)
    assert generate.call_args.kwargs["excluded_patterns"] == ("Thumbs.db",)
    # comparing the bound methods themselves: which callable arrived is the assertion, and a bound
    # method is a fresh object per attribute access, so equality is the only way to ask
    # pylint: disable=comparison-with-callable
    assert generate.call_args.kwargs["progress"] == control.report
    assert generate.call_args.kwargs["checkpoint"] == job.checkpoint


def test_a_verify_run_never_creates_the_record_it_is_checking_against(
    mocker: MockerFixture, control: FakeControl, present: None
) -> None:
    """A verify creates no record unless the caller says so, so adopting stays a deliberate act (#242).

    **Test steps:**

    * run a verify job nobody handed a creation choice, with the underlying callable mocked
    * check it was asked not to create a record
    """
    del present
    verify = mocker.patch("rehuco_core.checksum_jobs.verify_checksums", return_value=ChecksumReport())

    VerifyChecksumsJob(INFO_PATH).run(control)  # pyright: ignore[reportArgumentType]

    assert verify.call_args.kwargs["create_if_missing"] is False


def test_a_verify_carries_the_two_choices_the_settings_page_owns(
    mocker: MockerFixture, control: FakeControl, present: None
) -> None:
    """The migration target and the creation choice are resolved by the caller and passed in (#242).

    **Test steps:**

    * run a verify built with both choices, with the underlying callable mocked
    * check both reached the run
    """
    del present
    verify = mocker.patch("rehuco_core.checksum_jobs.verify_checksums", return_value=ChecksumReport())

    job = VerifyChecksumsJob(INFO_PATH, create_if_missing=True, migrate_to="crc32")

    job.run(control)  # pyright: ignore[reportArgumentType]

    assert verify.call_args.kwargs["create_if_missing"] is True
    assert verify.call_args.kwargs["migrate_to"] == "crc32"


def test_a_generate_creates_the_record_it_is_for_and_migrates_nothing(
    mocker: MockerFixture, control: FakeControl, present: None
) -> None:
    """Creating the record is a first generate's purpose, and it re-baselines rather than migrates.

    **Test steps:**

    * run a generate job with the underlying callable mocked
    * check it was asked to create the record, and was never handed a migration target
    """
    del present
    generate = mocker.patch("rehuco_core.checksum_jobs.generate_checksums", return_value=ChecksumReport())

    GenerateChecksumsJob(INFO_PATH).run(control)  # pyright: ignore[reportArgumentType]

    assert generate.call_args.kwargs["create_if_missing"] is True
    assert "migrate_to" not in generate.call_args.kwargs


def test_a_finished_run_holds_its_findings_for_whoever_enqueued_it(
    mocker: MockerFixture, control: FakeControl, present: None
) -> None:
    """The report is readable off the job once it has finished, since the engine carries no payload.

    **Test steps:**

    * run a verify whose report holds one mismatch
    * check the job answers that report, and that a retry drops it again
    """
    del present
    report = ChecksumReport(statuses={VIDEO: "mismatched"})
    mocker.patch("rehuco_core.checksum_jobs.verify_checksums", return_value=report)
    job = VerifyChecksumsJob(INFO_PATH)

    assert job.report is None
    job.run(control)  # pyright: ignore[reportArgumentType]
    assert job.report is report

    job.reset()

    assert job.report is None


def test_a_summary_is_logged_under_the_scope_the_job_was_enqueued_in(
    mocker: MockerFixture, control: FakeControl, present: None, caplog: Any
) -> None:
    """What a run established is said once, in a line a reader can act on.

    **Test steps:**

    * run a verify reporting a mixture of verdicts
    * check the summary counts them
    """
    del present
    mocker.patch(
        "rehuco_core.checksum_jobs.verify_checksums",
        return_value=ChecksumReport(statuses={VIDEO: "matched", ARCHIVE: "mismatched"}),
    )

    with caplog.at_level("INFO", logger="rehuco_core.checksum_jobs"):
        VerifyChecksumsJob(INFO_PATH).run(control)  # pyright: ignore[reportArgumentType]

    assert "1 matched, 1 mismatched" in caplog.text


def test_every_pruned_entry_is_named_in_the_log_with_its_reason(
    mocker: MockerFixture, control: FakeControl, present: None, caplog: Any
) -> None:
    """The summary counts what was dropped; the log says which entry and why (#254).

    Entries vanishing silently is the failure mode the reporting is written against, and a count alone
    would not let anyone find out what left.

    **Test steps:**

    * run a verify reporting one entry pruned under each tier
    * check both names and both reasons reached the resource's log
    """
    del present
    mocker.patch(
        "rehuco_core.checksum_jobs.verify_checksums",
        return_value=ChecksumReport(pruned={"info.tc.orig": "structural", "Thumbs.db": "junk"}),
    )

    with caplog.at_level("INFO", logger="rehuco_core.checksum_jobs"):
        VerifyChecksumsJob(INFO_PATH).run(control)  # pyright: ignore[reportArgumentType]

    assert "'info.tc.orig'" in caplog.text
    assert PRUNE_REASONS["structural"] in caplog.text
    assert "'Thumbs.db'" in caplog.text
    assert PRUNE_REASONS["junk"] in caplog.text
    assert "2 pruned" in caplog.text


def test_every_moved_claim_is_named_in_the_log_with_where_it_went(
    mocker: MockerFixture, control: FakeControl, present: None, caplog: Any
) -> None:
    """An entry leaving a record is only safe because it arrived somewhere else, so say where (#257).

    The count in the summary cannot name the record that took it, and that record is exactly what
    someone reading the log later needs.

    **Test steps:**

    * run a verify reporting one entry handed to a nested record
    * check the name, the record it went to and the name it goes by there all reached the resource's log
    """
    del present
    covering = CoveringRecord(DIRECTORY / "extras" / "info.rehu", "pack.zip")
    mocker.patch("rehuco_core.checksum_jobs.verify_checksums", return_value=ChecksumReport(moved={ARCHIVE: covering}))

    with caplog.at_level("INFO", logger="rehuco_core.checksum_jobs"):
        VerifyChecksumsJob(INFO_PATH).run(control)  # pyright: ignore[reportArgumentType]

    assert f"'{ARCHIVE}'" in caplog.text
    assert str(covering.record) in caplog.text
    assert "'pack.zip'" in caplog.text
    assert "1 moved" in caplog.text


@mark.parametrize("request_stop", ["pause", "cancel"])
def test_a_stop_travels_out_of_the_run_untouched(
    mocker: MockerFixture, control: FakeControl, present: None, request_stop: str
) -> None:
    """A pause or a cancel raised by the checkpoint leaves through ``run``, never caught here.

    **Test steps:**

    * make the mocked run call the checkpoint, having asked the job to stop
    * check the matching exception reaches the caller
    """
    del present
    job = VerifyChecksumsJob(INFO_PATH)
    getattr(job, request_stop)()
    mocker.patch(
        "rehuco_core.checksum_jobs.verify_checksums",
        side_effect=lambda *_args, **kwargs: kwargs["checkpoint"](),
    )

    with raises(JobPaused if request_stop == "pause" else JobCancelled):
        job.run(control)  # pyright: ignore[reportArgumentType]


# endregion


# region Being written down


def test_a_job_writes_down_what_it_needs_to_be_itself_again() -> None:
    """The state is JSON primitives, and holds the selection the enqueuer asked for.

    **Test steps:**

    * capture a job built with a selection and an exclusion set
    * check every value is a JSON primitive
    """
    job = GenerateChecksumsJob(INFO_PATH, only=[VIDEO, ARCHIVE], excluded_patterns=("Thumbs.db",))

    assert job.capture_state() == {
        "path": str(INFO_PATH),
        "algorithm": DEFAULT_CHECKSUM_ALGORITHM,
        "only": [VIDEO, ARCHIVE],
        "excluded_patterns": ["Thumbs.db"],
        "create_if_missing": True,
        "stale_days": None,
        "migrate_to": None,
        "seed_legacy": True,
    }


def test_a_restored_job_is_the_job_that_was_queued() -> None:
    """A capture/restore round trip preserves the resource, the algorithm and the selection.

    **Test steps:**

    * restore a fresh job from another's captured state
    * check what it will run over
    """
    captured = VerifyChecksumsJob(
        INFO_PATH, only=[ARCHIVE], excluded_patterns=("*.tmp",), create_if_missing=True, migrate_to="crc32"
    ).capture_state()
    restored = VerifyChecksumsJob()

    restored.restore_state(captured)

    assert restored.source == INFO_PATH
    assert restored.only == (ARCHIVE,)
    assert restored.excluded_patterns == ("*.tmp",)
    assert restored.create_if_missing
    assert restored.migrate_to == "crc32"
    assert restored.label == "Verify checksums - sculpting"


@mark.parametrize(
    ("job_class", "creates"),
    [(GenerateChecksumsJob, True), (VerifyChecksumsJob, False)],
    ids=["generate", "verify"],
)
def test_a_state_written_before_the_two_choices_existed_restores_the_run_it_described(
    job_class: type[ChecksumJob], creates: bool
) -> None:
    """A queue saved by a build that predates #242 must come back as exactly the run it was.

    **Test steps:**

    * restore each kind from a state carrying neither new key
    * check each kept its own creation behaviour and migrates nothing
    """
    job = job_class()

    job.restore_state({"path": str(INFO_PATH)})

    assert job.create_if_missing is creates
    assert job.migrate_to is None


@mark.parametrize(
    "state",
    [
        {},
        {"path": ""},
        {"path": str(INFO_PATH), "algorithm": "rot13"},
        {"path": str(INFO_PATH), "only": "lesson1.mp4"},
        {"path": str(INFO_PATH), "migrate_to": "rot13"},
    ],
    ids=["no path", "empty path", "unknown algorithm", "selection is not a list", "unknown migration target"],
)
def test_a_state_that_does_not_describe_a_runnable_job_is_refused(state: dict[str, Any]) -> None:
    """A hand-edited file costs its own item rather than the app's start.

    **Test steps:**

    * restore from each unusable state
    * check it raises, which is what makes the registry drop the item
    """
    with raises(ValueError):
        GenerateChecksumsJob().restore_state(state)


def test_a_restored_job_reads_through_the_coordinator_the_app_renames_through() -> None:
    """A job the registry rebuilt is rename-aware, which is the whole reason there is a shared one.

    **Test steps:**

    * rebuild a job through the default registry, the way a saved queue does
    * check it tracks in the process-wide coordinator rather than one of its own
    """
    job = DEFAULT_TASK_JOB_REGISTRY.create(CHECKSUM_VERIFY_KIND, {"path": str(INFO_PATH)})

    assert isinstance(job, VerifyChecksumsJob)
    assert job.coordinator is ChecksumJob().coordinator


@mark.parametrize(
    ("kind", "expected"),
    [(CHECKSUM_GENERATE_KIND, GenerateChecksumsJob), (CHECKSUM_VERIFY_KIND, VerifyChecksumsJob)],
)
def test_both_kinds_are_registered_so_a_saved_queue_can_rebuild_them(kind: str, expected: type) -> None:
    """Each kind names its class in the registry a restore reads.

    **Test steps:**

    * create each kind from the app-wide registry
    * check the class and the restored resource
    """
    job = DEFAULT_TASK_JOB_REGISTRY.create(kind, {"path": str(INFO_PATH)})

    assert isinstance(job, ChecksumJob)
    assert isinstance(job, expected)
    assert job.source == INFO_PATH


def test_a_kind_is_claimed_once() -> None:
    """Two classes claiming one kind is a programming error, and the registry says so.

    **Test steps:**

    * register both kinds into a fresh registry, then register one again
    * check the second registration is refused
    """
    registry = TaskJobRegistry()
    registry.register(CHECKSUM_VERIFY_KIND, VerifyChecksumsJob)

    with raises(ValueError):
        registry.register(CHECKSUM_VERIFY_KIND, VerifyChecksumsJob)


# endregion


# region On the queue


def test_a_job_runs_on_the_queue_rather_than_the_caller_s_thread(mocker: MockerFixture, present: None) -> None:
    """Enqueuing returns at once and the work lands on the worker, reporting bytes as it goes.

    **Test steps:**

    * enqueue a verify whose run reports progress, and wait for the queue to settle
    * check the job finished and the progress reached the row
    """
    del present
    mocker.patch(
        "rehuco_core.checksum_jobs.verify_checksums",
        side_effect=lambda *_args, **kwargs: (kwargs["progress"](512, 1024), ChecksumReport())[1],
    )
    queue = TaskQueue()
    settled = FinishedListener(1)
    queue.add_listener(settled)
    try:
        queue.enqueue(VerifyChecksumsJob(INFO_PATH))
        assert settled.wait()
        (status,) = queue.jobs()
    finally:
        queue.shutdown()

    assert status.state is JobState.DONE
    assert (status.done, status.total) == (512, 1024)
    assert status.persistable
    assert status.source == INFO_PATH


def test_several_resources_enqueue_several_jobs_and_run_one_at_a_time(mocker: MockerFixture, present: None) -> None:
    """Multi-selecting serializes the work rather than running it all at once.

    **Test steps:**

    * enqueue three verifies, each recording when it started and finished
    * check no two runs overlapped
    """
    del present
    entered: Final = Event()
    release: Final = Event()
    started: list[str] = []

    def verify(path: Path, **_kwargs: Any) -> ChecksumReport:
        started.append(path.parent.name)
        entered.set()
        assert release.wait(TIMEOUT)
        return ChecksumReport()

    mocker.patch("rehuco_core.checksum_jobs.verify_checksums", side_effect=verify)
    paths = [DIRECTORY.parent / name / "info.rehu" for name in ("one", "two", "three")]
    queue = TaskQueue()
    settled = FinishedListener(len(paths))
    queue.add_listener(settled)
    try:
        for path in paths:
            queue.enqueue(VerifyChecksumsJob(path))
        assert entered.wait(TIMEOUT)
        held = [status.state for status in queue.jobs()]
        release.set()
        assert settled.wait()
        states = [status.state for status in queue.jobs()]
    finally:
        release.set()
        queue.shutdown()

    assert held == [JobState.RUNNING, JobState.QUEUED, JobState.QUEUED]
    assert states == [JobState.DONE] * 3
    assert started == ["one", "two", "three"]


# endregion


# region Summaries


@mark.parametrize(
    ("report", "expected"),
    [
        (ChecksumReport(), "nothing to check"),
        (ChecksumReport(statuses={VIDEO: "matched", ARCHIVE: "matched"}), "2 matched"),
        (
            ChecksumReport(statuses={VIDEO: "mismatched", ARCHIVE: "missing"}),
            "1 mismatched, 1 missing",
        ),
        (ChecksumReport(skipped=(VIDEO,), unreadable=(ARCHIVE,)), "1 skipped, 1 unreadable"),
        (ChecksumReport(unnamed_malformed=2), "2 unnamed malformed"),
        (ChecksumReport(unreadable_directories=("extras",)), "1 unreadable directory"),
        (
            ChecksumReport(statuses={VIDEO: "matched"}, pruned={"info.tc.orig": "structural"}),
            "1 matched, 1 pruned",
        ),
        (
            ChecksumReport(statuses={VIDEO: "matched"}, moved={ARCHIVE: CoveringRecord(INFO_PATH, "pack.zip")}),
            "1 matched, 1 moved",
        ),
        (
            ChecksumReport(statuses={VIDEO: "matched"}, unreadable_directories=("extras", "raw")),
            "1 matched, 2 unreadable directories",
        ),
    ],
    ids=[
        "nothing",
        "all matched",
        "verdicts",
        "skipped and unreadable",
        "unnamed",
        "one unreadable directory",
        "pruned",
        "moved",
        "several unreadable directories",
    ],
)
def test_a_summary_counts_what_a_run_established(report: ChecksumReport, expected: str) -> None:
    """The line a log record and a banner both carry says how many of what.

    **Test steps:**

    * summarize each report
    * check the counts
    """
    assert checksum_report_summary(report) == expected


# endregion


def test_a_saved_job_whose_window_is_not_a_number_is_dropped() -> None:
    """A hand-edited queue file should cost its own item, not come up as a run nobody described.

    **Test steps:**

    * restore a job from a state whose staleness window is text
    * check it raises, which is what makes the registry drop the item
    """
    state = VerifyChecksumsJob(INFO_PATH).capture_state() | {"stale_days": "ninety"}

    with raises(ValueError, match="staleness window"):
        VerifyChecksumsJob().restore_state(state)


def test_a_restored_job_keeps_the_window_it_was_queued_with() -> None:
    """*Verify Old* survives a restart as the run it was, window included (#242, #244).

    **Test steps:**

    * capture a verify carrying a window and restore another job from it
    * check the window came back
    """
    captured = VerifyChecksumsJob(INFO_PATH, stale_after=timedelta(days=90)).capture_state()

    restored = VerifyChecksumsJob()
    restored.restore_state(captured)

    assert restored.stale_after == timedelta(days=90)


def test_a_verify_runs_with_the_window_it_carries() -> None:
    """The window reaches the run rather than being decoration on the row (#244).

    **Test steps:**

    * run a verify job carrying a window over a resource with a record
    * check the window was what the run was given
    """
    job = VerifyChecksumsJob(INFO_PATH, stale_after=timedelta(days=7))

    assert job.stale_after == timedelta(days=7)
    assert job.capture_state()["stale_days"] == 7
