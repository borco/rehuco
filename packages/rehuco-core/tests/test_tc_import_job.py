"""Tests for one `.tc` conversion as a task-queue job (#192).

:func:`~rehuco_core.convert_tc` itself is `test_tc_conversion`'s subject and is mocked away here: what
this module is about is the wrapping -- what the queue reads off a job, what is written down, and that
the job is registered so a saved queue can rebuild it. One test runs a job through a **real**
:class:`~rehuco_core.TaskQueue`, the same discipline `test_checksum_jobs` follows for the same reason.
"""

import logging
from collections.abc import Sequence
from pathlib import Path
from threading import Event
from typing import Any, Final

import pytest
from pytest import fixture, mark, raises
from pytest_mock import MockerFixture
from rehuco_core import (
    DEFAULT_TASK_JOB_REGISTRY,
    EXCLUDED_FILE_PATTERNS,
    FINISHED_JOB_STATES,
    TC_IMPORT_KIND,
    JobState,
    JobStatus,
    LegacyDrop,
    LegacySeed,
    RehuDocument,
    TaskJobRegistry,
    TaskQueue,
    TcImportJob,
)

DIRECTORY: Final = Path("/fake/library/sculpting")
TC_PATH: Final = DIRECTORY / "info.tc"
FILE_SCOPED_TC_PATH: Final = DIRECTORY / "pack.tc"

TIMEOUT: Final = 5.0
"""How long a test waits for the worker thread, in seconds -- generous, because it only ever expires
when something is genuinely wrong."""


# region Fakes


# mirrors `test_checksum_jobs`'s own FakeControl/FinishedListener/fixtures exactly -- kept as a
# separate copy rather than shared, this codebase's job-test convention
# pylint: disable=duplicate-code
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


class FinishedListener:
    """Waits for a known number of jobs to reach a state they never leave on their own.

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


# pylint: enable=duplicate-code

# endregion


# region What the queue reads


@mark.parametrize(
    ("path", "expected"),
    [
        (TC_PATH, "Import legacy catalog - sculpting"),
        (FILE_SCOPED_TC_PATH, "Import legacy catalog - pack.tc"),
    ],
)
def test_a_job_names_the_resource_rather_than_its_tc_file(path: Path, expected: str) -> None:
    """A label names the directory for ``info.tc`` and the file otherwise.

    **Test steps:**

    * build a job over a directory-scoped and a file-scoped `.tc`
    * check each label names the thing a reader would recognize
    """
    assert TcImportJob(path).label == expected


def test_an_enqueuer_may_name_the_job_itself() -> None:
    """A caller with a better name for the resource passes one, and it is kept.

    **Test steps:**

    * build a job with an explicit label
    * check the derived one was not used
    """
    assert TcImportJob(TC_PATH, label="Import legacy catalog - Sculpting Series/").label == (
        "Import legacy catalog - Sculpting Series/"
    )


def test_a_job_declares_what_stopping_it_costs() -> None:
    """A conversion has touched the directory once it has started, so stopping it part-way is never
    safe, and it never resumes from a cursor -- a retry starts the one call over.

    **Test steps:**

    * build a job
    * check both declarations the dock reads off a row
    """
    job = TcImportJob(TC_PATH)

    assert not job.safely_interruptible
    assert not job.resumes_where_it_stopped


# endregion


# region Validation


def test_a_job_over_a_resource_that_is_gone_refuses_to_start(mocker: MockerFixture) -> None:
    """A `.tc` deleted while the job waited fails with a sentence, not an exception out of the run.

    **Test steps:**

    * make the resource absent
    * check validate names it
    """
    mocker.patch.object(Path, "exists", autospec=True, return_value=False)

    assert TcImportJob(TC_PATH).validate() == f"The .tc file no longer exists: {TC_PATH}"


def test_a_job_with_no_resource_at_all_refuses() -> None:
    """The path-less job the registry builds before a state arrives is not runnable.

    **Test steps:**

    * build a job with no path -- what the registry's factory does
    * check it refuses to validate and to convert
    """
    job = TcImportJob()

    assert job.validate() == "This task has no resource."
    with raises(ValueError):
        job.resource_path()


# endregion


# region Running


def test_a_run_hands_its_parameters_to_the_conversion(
    mocker: MockerFixture, control: FakeControl, present: None
) -> None:
    """The path, the overwrite opt-in, the keep-backups default and the identity are what
    :func:`~rehuco_core.convert_tc` is given.

    **Test steps:**

    * run a job with overwrite on and an explicit username, with the underlying callable mocked
    * check every argument arrived
    """
    del present
    document = mocker.MagicMock(spec=RehuDocument)
    convert = mocker.patch("rehuco_core.tc_import_job.convert_tc", return_value=document)
    job = TcImportJob(TC_PATH, overwrite=True, username="alice", excluded_patterns=("*.tmp",))

    job.run(control)  # pyright: ignore[reportArgumentType]

    convert.assert_called_once_with(
        TC_PATH, keep_backups=True, overwrite=True, username="alice", excluded_patterns=("*.tmp",)
    )


def test_a_run_reports_only_start_and_finish(mocker: MockerFixture, control: FakeControl, present: None) -> None:
    """One call divides no further, so there is nothing between *not started* and *done*.

    **Test steps:**

    * run a job with the underlying callable mocked
    * check the control saw exactly two reports
    """
    del present
    mocker.patch("rehuco_core.tc_import_job.convert_tc", return_value=mocker.MagicMock(spec=RehuDocument))

    TcImportJob(TC_PATH).run(control)  # pyright: ignore[reportArgumentType]

    assert control.reports == [(0, 1), (1, 1)]


def test_a_finished_run_holds_its_document_for_whoever_enqueued_it(
    mocker: MockerFixture, control: FakeControl, present: None
) -> None:
    """The converted document is readable off the job once it has finished, since the engine carries no
    payload.

    **Test steps:**

    * run a job whose conversion produces a document
    * check the job answers that document, and that a retry drops it again
    """
    del present
    document = mocker.MagicMock(spec=RehuDocument)
    mocker.patch("rehuco_core.tc_import_job.convert_tc", return_value=document)
    job = TcImportJob(TC_PATH)

    assert job.document is None
    job.run(control)  # pyright: ignore[reportArgumentType]
    assert job.document is document

    job.reset()

    assert job.document is None


def test_a_conversion_failure_escapes_the_run(mocker: MockerFixture, control: FakeControl, present: None) -> None:
    """`convert_tc`'s own refusals (an existing target, a stale backup) are not caught here -- the
    engine turns them into a failed status with the message.

    **Test steps:**

    * make the underlying call raise
    * check the run does not swallow it
    """
    del present
    mocker.patch("rehuco_core.tc_import_job.convert_tc", side_effect=FileExistsError(DIRECTORY / "info.rehu"))

    with raises(FileExistsError):
        TcImportJob(TC_PATH).run(control)  # pyright: ignore[reportArgumentType]


def test_a_run_carries_the_legacy_manifest_into_the_new_record(
    mocker: MockerFixture, control: FakeControl, present: None
) -> None:
    """Converting a resource converts its checksums too (#256), over the `.rehu` the conversion wrote.

    **Test steps:**

    * run a job with both the conversion and the seed mocked
    * check both carriers were asked about the target `.rehu`, with the job's own exclusion set
    """
    del present
    mocker.patch("rehuco_core.tc_import_job.convert_tc", return_value=mocker.MagicMock(spec=RehuDocument))
    seed = mocker.patch("rehuco_core.tc_import_job.seed_checksum_record", return_value=None)
    remediate = mocker.patch("rehuco_core.tc_import_job.remediate_legacy_manifest", return_value=None)

    TcImportJob(TC_PATH, excluded_patterns=("*.tmp",)).run(control)  # pyright: ignore[reportArgumentType]

    seed.assert_called_once_with(DIRECTORY / "info.rehu", excluded_patterns=("*.tmp",))
    remediate.assert_called_once_with(DIRECTORY / "info.rehu", excluded_patterns=("*.tmp",))


def test_a_conversion_over_an_existing_record_merges_rather_than_leaving_the_manifest(
    mocker: MockerFixture, control: FakeControl, present: None, caplog: pytest.LogCaptureFixture
) -> None:
    """A converted resource never keeps a live manifest, whichever of the two paths carried it (#259).

    **Test steps:**

    * run a job whose seed declines (a record is already there) and whose remediation answers a seed
    * check the run reported what the merge carried, and which file it retired
    """
    del present
    mocker.patch("rehuco_core.tc_import_job.convert_tc", return_value=mocker.MagicMock(spec=RehuDocument))
    mocker.patch("rehuco_core.tc_import_job.seed_checksum_record", return_value=None)
    mocker.patch(
        "rehuco_core.tc_import_job.remediate_legacy_manifest",
        return_value=LegacySeed(
            DIRECTORY / "info.sfv",
            entries=({"name": "lesson1.mp4", "crc32": "deadbeef"},),
            retired=(DIRECTORY / "info.sfv",),
        ),
    )
    caplog.set_level(logging.INFO, logger="rehuco_core")

    TcImportJob(TC_PATH).run(control)  # pyright: ignore[reportArgumentType]

    assert "Seeded 1 checksum entry from info.sfv." in caplog.text
    assert "was retired to info.sfv.orig" in caplog.text


def test_a_seed_says_what_it_carried_and_what_it_dropped(
    mocker: MockerFixture, control: FakeControl, present: None, caplog: pytest.LogCaptureFixture
) -> None:
    """A seed happens once in a resource's life, so which manifest it came from is what a reader wants
    back later -- and the lines it could not use are on the resource's own log beside it.

    **Test steps:**

    * run a job whose seed carries one entry and drops one line
    * check the log names the manifest, the count, and the dropped line's reason
    """
    del present
    mocker.patch("rehuco_core.tc_import_job.convert_tc", return_value=mocker.MagicMock(spec=RehuDocument))
    mocker.patch(
        "rehuco_core.tc_import_job.seed_checksum_record",
        return_value=LegacySeed(
            DIRECTORY / "info.sfv",
            entries=({"name": "lesson1.mp4", "crc32": "deadbeef"},),
            dropped=(LegacyDrop("nonsense", "not this manifest's line shape"),),
        ),
    )
    caplog.set_level(logging.INFO, logger="rehuco_core")

    TcImportJob(TC_PATH).run(control)  # pyright: ignore[reportArgumentType]

    assert "Seeded 1 checksum entry from info.sfv." in caplog.text
    assert "dropped 'nonsense' -- not this manifest's line shape." in caplog.text


def test_a_seed_that_fails_costs_itself_rather_than_the_conversion(
    mocker: MockerFixture, control: FakeControl, present: None
) -> None:
    """The conversion has already landed and is not rolled back for this; a later verify seeds instead.

    **Test steps:**

    * make the seed raise, with the conversion succeeding
    * check the run finished and still answers the converted document
    """
    del present
    document = mocker.MagicMock(spec=RehuDocument)
    mocker.patch("rehuco_core.tc_import_job.convert_tc", return_value=document)
    mocker.patch("rehuco_core.tc_import_job.seed_checksum_record", side_effect=PermissionError("read-only share"))
    job = TcImportJob(TC_PATH)

    job.run(control)  # pyright: ignore[reportArgumentType]

    assert job.document is document


# endregion


# region Being written down


def test_a_job_writes_down_what_it_needs_to_be_itself_again() -> None:
    """The state is JSON primitives, and holds the run's parameters.

    **Test steps:**

    * capture a job built with overwrite on and an explicit username
    * check every value is a JSON primitive
    """
    job = TcImportJob(TC_PATH, overwrite=True, username="alice", excluded_patterns=("*.tmp",))

    assert job.capture_state() == {
        "path": str(TC_PATH),
        "overwrite": True,
        "keep_backups": True,
        "username": "alice",
        "excluded_patterns": ["*.tmp"],
    }


def test_a_restored_job_is_the_job_that_was_queued() -> None:
    """A capture/restore round trip preserves the resource and the run's parameters.

    **Test steps:**

    * restore a fresh job from another's captured state
    * check what it will run over
    """
    captured = TcImportJob(
        TC_PATH, overwrite=True, keep_backups=False, username="alice", excluded_patterns=("*.tmp",)
    ).capture_state()
    restored = TcImportJob()

    restored.restore_state(captured)

    assert restored.source == TC_PATH
    assert restored.overwrite is True
    assert restored.keep_backups is False
    assert restored.username == "alice"
    assert restored.excluded_patterns == ("*.tmp",)
    assert restored.label == "Import legacy catalog - sculpting"


def test_a_state_written_before_keep_backups_was_optional_restores_true() -> None:
    """A queue saved by a build that predates this key must come back keeping backups -- the wizard's
    only mode, and the safe one to assume for a saved item that never named it.

    **Test steps:**

    * restore from a state carrying only a path
    * check backups default to kept
    """
    job = TcImportJob()

    job.restore_state({"path": str(TC_PATH)})

    assert job.keep_backups is True
    assert job.overwrite is False


def test_a_state_written_before_excluded_patterns_was_optional_restores_the_default() -> None:
    """A queue saved by a build that predates this key must come back with the built-in exclusion
    set, matching :class:`~rehuco_core.ChecksumJob`'s own tolerant restore.

    **Test steps:**

    * restore from a state carrying only a path
    * check the exclusion set falls back to the default
    """
    job = TcImportJob()

    job.restore_state({"path": str(TC_PATH)})

    assert job.excluded_patterns == EXCLUDED_FILE_PATTERNS


@mark.parametrize(
    "state",
    [{}, {"path": ""}, {"path": str(TC_PATH), "username": 5}],
    ids=["no path", "empty path", "username is not a string"],
)
def test_a_state_that_does_not_describe_a_runnable_job_is_refused(state: dict[str, Any]) -> None:
    """A hand-edited file costs its own item rather than the app's start.

    **Test steps:**

    * restore from each unusable state
    * check it raises, which is what makes the registry drop the item
    """
    with raises(ValueError):
        TcImportJob().restore_state(state)


def test_the_kind_is_registered_so_a_saved_queue_can_rebuild_it() -> None:
    """The kind names this class in the registry a restore reads.

    **Test steps:**

    * create from the app-wide registry
    * check the class and the restored resource
    """
    job = DEFAULT_TASK_JOB_REGISTRY.create(TC_IMPORT_KIND, {"path": str(TC_PATH)})

    assert isinstance(job, TcImportJob)
    assert job.source == TC_PATH


def test_a_kind_is_claimed_once() -> None:
    """Two classes claiming one kind is a programming error, and the registry says so.

    **Test steps:**

    * register the kind into a fresh registry, then register it again
    * check the second registration is refused
    """
    registry = TaskJobRegistry()
    registry.register(TC_IMPORT_KIND, TcImportJob)

    with raises(ValueError):
        registry.register(TC_IMPORT_KIND, TcImportJob)


# endregion


# region On the queue


def test_a_job_runs_on_the_queue_rather_than_the_caller_s_thread(mocker: MockerFixture, present: None) -> None:
    """Enqueuing returns at once and the work lands on the worker.

    **Test steps:**

    * enqueue a job, wait for the queue to settle
    * check the job finished and is reported not safely interruptible and persistable
    """
    del present
    mocker.patch("rehuco_core.tc_import_job.convert_tc", return_value=mocker.MagicMock(spec=RehuDocument))
    queue = TaskQueue()
    settled = FinishedListener(1)
    queue.add_listener(settled)
    try:
        queue.enqueue(TcImportJob(TC_PATH))
        assert settled.wait()
        (status,) = queue.jobs()
    finally:
        queue.shutdown()

    assert status.state is JobState.DONE
    assert status.persistable
    assert status.safely_interruptible is False
    assert status.source == TC_PATH


def test_a_queued_job_is_cancelled_outright_rather_than_started(mocker: MockerFixture, present: None) -> None:
    """Cancelling a job still waiting its turn drops it without ever calling `convert_tc` -- the whole
    of #192's "cancel stops after the current resource": nothing asks a running conversion to stop
    mid-file, only the ones still queued.

    **Test steps:**

    * hold a first job inside its conversion, enqueue a second behind it and cancel that one
    * release the first and check only it converted, with the second reported cancelled
    """
    del present
    # Holding the first job is what leaves the second demonstrably *waiting its turn* when it is
    # cancelled. `queue.pause()` cannot arrange it and used to be asked to: pausing is `pause_job`
    # applied to the jobs already enqueued ([[appendices.task-queue#pause-concept]]), never a gate a
    # later enqueue passes through, so the lone job raced the cancel and a fast runner converted it
    # first -- green here, red on Windows.
    running = Event()
    release = Event()

    def hold_the_worker(*_args: Any, **_kwargs: Any) -> None:
        """Park the worker inside the first conversion until the test has cancelled the second."""
        running.set()
        assert release.wait(TIMEOUT)

    convert = mocker.patch("rehuco_core.tc_import_job.convert_tc", side_effect=hold_the_worker)
    queue = TaskQueue()
    settled = FinishedListener(2)
    queue.add_listener(settled)
    try:
        queue.enqueue(TcImportJob(FILE_SCOPED_TC_PATH))
        assert running.wait(TIMEOUT)
        serial = queue.enqueue(TcImportJob(TC_PATH))
        queue.cancel(serial)
        release.set()
        assert settled.wait()
        (status,) = (job for job in queue.jobs() if job.serial == serial)
    finally:
        queue.shutdown()

    assert status.state is JobState.CANCELLED
    # the held job converted; the cancelled one never reached `convert_tc` at all
    convert.assert_called_once()
    assert convert.call_args.args == (FILE_SCOPED_TC_PATH,)


# endregion
