"""Tests for reverting a conversion and discarding its backups as task-queue jobs (#193).

:func:`~rehuco_core.revert_conversion` and :func:`~rehuco_core.discard_conversion_backups` are
`test_tc_conversion_backups`'s subject and are mocked away here: what this module is about is the
wrapping -- what the queue reads off a job, what is written down, and that both kinds are registered so a
saved queue can rebuild them. One test runs a job through a **real** :class:`~rehuco_core.TaskQueue`, the
same discipline `test_tc_import_job` follows for the same reason.
"""

from collections.abc import Sequence
from pathlib import Path
from threading import Event
from typing import Any, Final

from pytest import fixture, mark, raises
from pytest_mock import MockerFixture
from rehuco_core import (
    DEFAULT_TASK_JOB_REGISTRY,
    FINISHED_JOB_STATES,
    TC_DISCARD_KIND,
    TC_REVERT_KIND,
    ConversionBackups,
    DiscardBackupsJob,
    JobState,
    JobStatus,
    RevertConversionJob,
    TaskJobRegistry,
    TaskQueue,
    TcBackupsJob,
)

DIRECTORY: Final = Path("/fake/library/sculpting")
REHU_PATH: Final = DIRECTORY / "info.rehu"
FILE_SCOPED_REHU_PATH: Final = DIRECTORY / "pack.rehu"

DISCARDED: Final = (DIRECTORY / "cover.jpg.orig", DIRECTORY / "info.tc.orig")

TIMEOUT: Final = 5.0
"""How long a test waits for the worker thread, in seconds -- generous, because it only ever expires
when something is genuinely wrong."""


# region Fakes


# mirrors `test_tc_import_job`'s own FakeControl/FinishedListener/fixtures exactly -- kept as a
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


@fixture(name="inventory")
def fixture_inventory() -> ConversionBackups:
    """What a completed revert reports it put back.

    :returns: a plausible inventory over :data:`REHU_PATH`.
    """
    return ConversionBackups(
        rehu_path=REHU_PATH,
        backups=DISCARDED,
        total_bytes=2000,
        written=(REHU_PATH,),
        obstructions=(),
        legacy_restored=DIRECTORY / "info.tc",
        edited_since=False,
        converted="2023-11-14T22:13:20Z",
    )


# endregion


# region What the queue reads


@mark.parametrize(
    ("job_class", "path", "expected"),
    [
        (RevertConversionJob, REHU_PATH, "Revert conversion - sculpting"),
        (RevertConversionJob, FILE_SCOPED_REHU_PATH, "Revert conversion - pack.rehu"),
        (DiscardBackupsJob, REHU_PATH, "Discard backups - sculpting"),
        (DiscardBackupsJob, FILE_SCOPED_REHU_PATH, "Discard backups - pack.rehu"),
    ],
)
def test_a_job_names_its_verb_and_the_resource_rather_than_the_file(
    job_class: type[TcBackupsJob], path: Path, expected: str
) -> None:
    """A label names the directory for ``info.rehu`` and the file otherwise, after the verb -- so two
    rows over one resource are told apart by what they will do to it.

    **Test steps:**

    * build each job over a directory-scoped and a file-scoped resource
    * check each label names the thing a reader would recognize
    """
    assert job_class(path).label == expected


def test_an_enqueuer_may_name_the_job_itself() -> None:
    """A caller with a better name for the resource passes one, and it is kept.

    **Test steps:**

    * build a job with an explicit label
    * check the derived one was not used
    """
    assert RevertConversionJob(REHU_PATH, label="Revert conversion - Sculpting Series/").label == (
        "Revert conversion - Sculpting Series/"
    )


@mark.parametrize("job_class", [RevertConversionJob, DiscardBackupsJob])
def test_a_job_declares_what_stopping_it_costs(job_class: type[TcBackupsJob]) -> None:
    """Both operations have touched the directory once they have started, so stopping one part-way is
    never safe, and neither resumes from a cursor -- a retry starts the one call over.

    **Test steps:**

    * build each job
    * check both declarations the dock reads off a row
    """
    job = job_class(REHU_PATH)

    assert not job.safely_interruptible
    assert not job.resumes_where_it_stopped


# endregion


# region Validation


def test_a_job_over_a_folder_that_is_gone_refuses_to_start(mocker: MockerFixture) -> None:
    """A resource folder deleted while the job waited fails with a sentence, not an exception out of the
    run.

    **Test steps:**

    * make the resource folder absent
    * check validate names it
    """
    mocker.patch.object(Path, "exists", autospec=True, return_value=False)

    assert RevertConversionJob(REHU_PATH).validate() == f"The resource folder no longer exists: {DIRECTORY}"


def test_a_missing_rehu_does_not_stop_the_job(present: None) -> None:
    """The ``.rehu`` is what a revert *deletes*, not what it needs: a resource whose record was removed
    by hand still has originals to put back, and a discard is about the ``.orig`` siblings alone.

    **Test steps:**

    * validate a job whose folder is there
    * check nothing is wrong with it
    """
    del present

    assert RevertConversionJob(REHU_PATH).validate() is None


def test_the_base_is_not_a_job_on_its_own() -> None:
    """:meth:`~rehuco_core.TcBackupsJob.perform` is the one thing a subclass adds, so the base refuses
    rather than quietly doing nothing -- which would report a resource as handled without touching it.

    **Test steps:**

    * run the base's own perform
    * verify it raises
    """
    with raises(NotImplementedError):
        TcBackupsJob(REHU_PATH).perform(REHU_PATH)


@mark.parametrize("job_class", [RevertConversionJob, DiscardBackupsJob])
def test_a_job_with_no_resource_at_all_refuses(job_class: type[TcBackupsJob]) -> None:
    """The path-less job the registry builds before a state arrives is not runnable.

    **Test steps:**

    * build a job with no path -- what the registry's factory does
    * check it refuses to validate and to name a resource
    """
    job = job_class()

    assert job.validate() == "This task has no resource."
    with raises(ValueError):
        job.resource_path()


# endregion


# region Running


def test_a_revert_hands_its_resource_to_the_operation(
    mocker: MockerFixture, control: FakeControl, present: None, inventory: ConversionBackups
) -> None:
    """The path is the whole of what :func:`~rehuco_core.revert_conversion` is given -- there is no
    choice for this job to carry.

    **Test steps:**

    * run a revert with the underlying callable mocked
    * check the path arrived and only start and finish were reported
    """
    del present
    revert = mocker.patch("rehuco_core.tc_backups_jobs.revert_conversion", return_value=inventory)

    RevertConversionJob(REHU_PATH).run(control)  # pyright: ignore[reportArgumentType]

    revert.assert_called_once_with(REHU_PATH)
    assert control.reports == [(0, 1), (1, 1)]


def test_a_discard_hands_its_resource_to_the_operation(
    mocker: MockerFixture, control: FakeControl, present: None
) -> None:
    """The same shape as the revert, one call over: what differs between the two is entirely inside the
    callable.

    **Test steps:**

    * run a discard with the underlying callable mocked
    * check the path arrived and only start and finish were reported
    """
    del present
    discard = mocker.patch("rehuco_core.tc_backups_jobs.discard_conversion_backups", return_value=DISCARDED)

    DiscardBackupsJob(REHU_PATH).run(control)  # pyright: ignore[reportArgumentType]

    discard.assert_called_once_with(REHU_PATH)
    assert control.reports == [(0, 1), (1, 1)]


def test_a_finished_revert_holds_its_inventory_for_whoever_enqueued_it(
    mocker: MockerFixture, control: FakeControl, present: None, inventory: ConversionBackups
) -> None:
    """What was put back is readable off the job once it has finished, since the engine carries no
    payload.

    **Test steps:**

    * run a revert whose operation reports an inventory
    * check the job answers it, and that a retry drops it again
    """
    del present
    mocker.patch("rehuco_core.tc_backups_jobs.revert_conversion", return_value=inventory)
    job = RevertConversionJob(REHU_PATH)

    assert job.reverted is None
    job.run(control)  # pyright: ignore[reportArgumentType]
    assert job.reverted is inventory

    job.reset()

    assert job.reverted is None


def test_a_finished_discard_holds_what_it_deleted(mocker: MockerFixture, control: FakeControl, present: None) -> None:
    """The deleted backups are readable off the job for the same reason a revert's inventory is.

    **Test steps:**

    * run a discard whose operation reports two deleted backups
    * check the job answers them, and that a retry drops them again
    """
    del present
    mocker.patch("rehuco_core.tc_backups_jobs.discard_conversion_backups", return_value=DISCARDED)
    job = DiscardBackupsJob(REHU_PATH)

    assert job.discarded is None
    job.run(control)  # pyright: ignore[reportArgumentType]
    assert job.discarded == DISCARDED

    job.reset()

    assert job.discarded is None


@mark.parametrize(
    "error",
    [FileNotFoundError(DIRECTORY / "info.tc.orig"), FileExistsError(DIRECTORY / "info.tc")],
    ids=["no backed-up .tc", "occupied restore target"],
)
def test_a_reverts_refusal_escapes_the_run(
    mocker: MockerFixture, control: FakeControl, present: None, error: OSError
) -> None:
    """:func:`~rehuco_core.revert_conversion` refuses rather than half-reverts, and those refusals are
    not caught here -- the engine turns them into a failed status with the message.

    **Test steps:**

    * make the underlying call raise each refusal
    * check the run does not swallow it
    """
    del present
    mocker.patch("rehuco_core.tc_backups_jobs.revert_conversion", side_effect=error)

    with raises(type(error)):
        RevertConversionJob(REHU_PATH).run(control)  # pyright: ignore[reportArgumentType]


# endregion


# region Being written down


@mark.parametrize("job_class", [RevertConversionJob, DiscardBackupsJob])
def test_a_job_writes_down_only_its_resource(job_class: type[TcBackupsJob]) -> None:
    """Neither operation carries a choice, so the path is the whole state.

    **Test steps:**

    * capture each job
    * check the state is the path, as text
    """
    assert job_class(REHU_PATH).capture_state() == {"path": str(REHU_PATH)}


@mark.parametrize(
    ("job_class", "expected_label"),
    [(RevertConversionJob, "Revert conversion - sculpting"), (DiscardBackupsJob, "Discard backups - sculpting")],
)
def test_a_restored_job_is_the_job_that_was_queued(job_class: type[TcBackupsJob], expected_label: str) -> None:
    """A capture/restore round trip preserves the resource, and the label is re-derived from it.

    **Test steps:**

    * restore a fresh job from another's captured state
    * check what it will run over, and what it is called
    """
    captured = job_class(REHU_PATH).capture_state()
    restored = job_class()

    restored.restore_state(captured)

    assert restored.source == REHU_PATH
    assert restored.label == expected_label


@mark.parametrize("state", [{}, {"path": ""}, {"path": 5}], ids=["no path", "empty path", "path is not a string"])
def test_a_state_that_does_not_describe_a_runnable_job_is_refused(state: dict[str, Any]) -> None:
    """A hand-edited file costs its own item rather than the app's start.

    **Test steps:**

    * restore from each unusable state
    * check it raises, which is what makes the registry drop the item
    """
    with raises(ValueError):
        RevertConversionJob().restore_state(state)


@mark.parametrize(("kind", "job_class"), [(TC_REVERT_KIND, RevertConversionJob), (TC_DISCARD_KIND, DiscardBackupsJob)])
def test_each_kind_is_registered_so_a_saved_queue_can_rebuild_it(kind: str, job_class: type[TcBackupsJob]) -> None:
    """The kinds name these classes in the registry a restore reads, and they are distinct -- a saved
    revert must never come back as a discard.

    **Test steps:**

    * create each from the app-wide registry
    * check the class and the restored resource
    """
    job = DEFAULT_TASK_JOB_REGISTRY.create(kind, {"path": str(REHU_PATH)})

    assert isinstance(job, job_class)
    assert job.source == REHU_PATH


def test_a_kind_is_claimed_once() -> None:
    """Two classes claiming one kind is a programming error, and the registry says so.

    **Test steps:**

    * register the kind into a fresh registry, then register it again
    * check the second registration is refused
    """
    registry = TaskJobRegistry()
    registry.register(TC_REVERT_KIND, RevertConversionJob)

    with raises(ValueError):
        registry.register(TC_REVERT_KIND, DiscardBackupsJob)


# endregion


# region On the queue


def test_a_job_runs_on_the_queue_rather_than_the_caller_s_thread(mocker: MockerFixture, present: None) -> None:
    """Enqueuing returns at once and the work lands on the worker.

    **Test steps:**

    * enqueue a discard, wait for the queue to settle
    * check the job finished and is reported not safely interruptible and persistable
    """
    del present
    mocker.patch("rehuco_core.tc_backups_jobs.discard_conversion_backups", return_value=DISCARDED)
    queue = TaskQueue()
    settled = FinishedListener(1)
    queue.add_listener(settled)
    try:
        queue.enqueue(DiscardBackupsJob(REHU_PATH))
        assert settled.wait()
        (status,) = queue.jobs()
    finally:
        queue.shutdown()

    assert status.state is JobState.DONE
    assert status.persistable
    assert status.safely_interruptible is False
    assert status.source == REHU_PATH


def test_a_queued_job_is_cancelled_outright_rather_than_started(mocker: MockerFixture, present: None) -> None:
    """Cancelling a job still waiting its turn drops it without ever touching the directory -- the same
    "cancel stops after the current resource" #192's import runs under, since a bulk discard or revert
    is enqueued the same way.

    **Test steps:**

    * hold a first revert inside the operation, enqueue a second behind it and cancel that one
    * release the first and check only it ran, with the second reported cancelled
    """
    del present
    # Holding the first job is what leaves the second demonstrably *waiting its turn* when it is
    # cancelled. `queue.pause()` cannot arrange it and used to be asked to: pausing is `pause_job`
    # applied to the jobs already enqueued ([[appendices.task-queue#pause-concept]]), never a gate a
    # later enqueue passes through, so the lone job raced the cancel and a fast runner reverted it
    # first -- the same latent flake `test_tc_import_job`'s copy of this test turned red on Windows.
    running = Event()
    release = Event()

    def hold_the_worker(*_args: Any, **_kwargs: Any) -> None:
        """Park the worker inside the first revert until the test has cancelled the second."""
        running.set()
        assert release.wait(TIMEOUT)

    revert = mocker.patch("rehuco_core.tc_backups_jobs.revert_conversion", side_effect=hold_the_worker)
    queue = TaskQueue()
    settled = FinishedListener(2)
    queue.add_listener(settled)
    try:
        queue.enqueue(RevertConversionJob(FILE_SCOPED_REHU_PATH))
        assert running.wait(TIMEOUT)
        serial = queue.enqueue(RevertConversionJob(REHU_PATH))
        queue.cancel(serial)
        release.set()
        assert settled.wait()
        (status,) = (job for job in queue.jobs() if job.serial == serial)
    finally:
        queue.shutdown()

    assert status.state is JobState.CANCELLED
    # the held job reverted; the cancelled one never reached `revert_conversion` at all
    revert.assert_called_once()
    assert revert.call_args.args == (FILE_SCOPED_REHU_PATH,)


# endregion
