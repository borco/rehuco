"""Tests for discarding a conversion's backups as a task-queue job (#193, #290).

:func:`~rehuco_core.discard_conversion_backups` is `test_tc_conversion_backups`'s subject and is mocked
away here: what this module is about is the wrapping -- what the queue reads off a job, what is written
down, and that the kind is registered so a saved queue can rebuild it. One test runs a job through a
**real** :class:`~rehuco_core.TaskQueue`, the same discipline `test_tc_import_job` follows for the same
reason.
"""

from collections.abc import Sequence
from pathlib import Path
from threading import Event
from typing import Any, Final

from pytest import fixture, mark, raises
from pytest_mock import MockerFixture
from rehuco_core import (
    DEFAULT_DELETER,
    DEFAULT_DELETER_PROVIDER,
    DEFAULT_TASK_JOB_REGISTRY,
    FINISHED_JOB_STATES,
    TC_DISCARD_KIND,
    DiscardBackupsJob,
    JobState,
    JobStatus,
    NoTrashBinError,
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


# endregion


# region What the queue reads


@mark.parametrize(
    ("path", "expected"),
    [
        (REHU_PATH, "Discard backups - sculpting"),
        (FILE_SCOPED_REHU_PATH, "Discard backups - pack.rehu"),
    ],
)
def test_a_job_names_its_verb_and_the_resource_rather_than_the_file(path: Path, expected: str) -> None:
    """A label names the directory for ``info.rehu`` and the file otherwise, after the verb -- so a row
    is told apart by what it will do, and to what.

    **Test steps:**

    * build a job over a directory-scoped and a file-scoped resource
    * check each label names the thing a reader would recognize
    """
    assert DiscardBackupsJob(path).label == expected


def test_an_enqueuer_may_name_the_job_itself() -> None:
    """A caller with a better name for the resource passes one, and it is kept.

    **Test steps:**

    * build a job with an explicit label
    * check the derived one was not used
    """
    assert DiscardBackupsJob(REHU_PATH, label="Discard backups - Sculpting Series/").label == (
        "Discard backups - Sculpting Series/"
    )


def test_a_job_declares_what_stopping_it_costs() -> None:
    """The operation has touched the directory once it has started, so stopping it part-way is never
    safe, and it does not resume from a cursor -- a retry starts the one call over.

    **Test steps:**

    * build the job
    * check both declarations the dock reads off a row
    """
    job = DiscardBackupsJob(REHU_PATH)

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

    assert DiscardBackupsJob(REHU_PATH).validate() == f"The resource folder no longer exists: {DIRECTORY}"


def test_a_missing_rehu_does_not_stop_the_job(present: None) -> None:
    """The ``.rehu`` is not what a discard needs: it is about the ``.orig`` siblings alone, whether or
    not the record beside them is still there.

    **Test steps:**

    * validate a job whose folder is there
    * check nothing is wrong with it
    """
    del present

    assert DiscardBackupsJob(REHU_PATH).validate() is None


def test_the_base_is_not_a_job_on_its_own() -> None:
    """:meth:`~rehuco_core.TcBackupsJob.perform` is the one thing a subclass adds, so the base refuses
    rather than quietly doing nothing -- which would report a resource as handled without touching it.

    **Test steps:**

    * run the base's own perform
    * verify it raises
    """
    with raises(NotImplementedError):
        TcBackupsJob(REHU_PATH).perform(REHU_PATH)


def test_a_job_with_no_resource_at_all_refuses() -> None:
    """The path-less job the registry builds before a state arrives is not runnable.

    **Test steps:**

    * build a job with no path -- what the registry's factory does
    * check it refuses to validate and to name a resource
    """
    job = DiscardBackupsJob()

    assert job.validate() == "This task has no resource."
    with raises(ValueError):
        job.resource_path()


# endregion


# region Running


def test_a_discard_hands_its_resource_to_the_operation(
    mocker: MockerFixture, control: FakeControl, present: None
) -> None:
    """The path is the whole of what :func:`~rehuco_core.discard_conversion_backups` is given -- there is
    no choice for this job to carry.

    **Test steps:**

    * run a discard with the underlying callable mocked
    * check the path arrived and only start and finish were reported
    """
    del present
    discard = mocker.patch("rehuco_core.tc_backups_jobs.discard_conversion_backups", return_value=DISCARDED)

    DiscardBackupsJob(REHU_PATH).run(control)  # pyright: ignore[reportArgumentType]

    discard.assert_called_once_with(REHU_PATH, deleter=DEFAULT_DELETER)
    assert control.reports == [(0, 1), (1, 1)]


def test_a_discard_resolves_its_deleter_from_the_provider_when_it_runs(
    mocker: MockerFixture, control: FakeControl, present: None
) -> None:
    """The deleter is not the job's own: it is asked of the process-wide provider at run time, which is
    what lets an app install its Recycle Bin choice once for every discard, enqueued or restored (#298).

    **Test steps:**

    * install a provider answering a recording deleter, then run a discard built with only its path
    * check the operation was handed the provider's deleter
    """
    del present
    deleter = mocker.Mock()
    mocker.patch.object(DEFAULT_DELETER_PROVIDER, "resolve", return_value=deleter)
    discard = mocker.patch("rehuco_core.tc_backups_jobs.discard_conversion_backups", return_value=DISCARDED)

    DiscardBackupsJob(REHU_PATH).run(control)  # pyright: ignore[reportArgumentType]

    discard.assert_called_once_with(REHU_PATH, deleter=deleter)


def test_the_provider_resets_to_the_plain_unlink(mocker: MockerFixture) -> None:
    """``reset`` is what a test that installed a provider -- or built a window that did -- puts back,
    so the next test is not handed its choice (#298).

    **Test steps:**

    * install a provider answering a recording deleter, then reset
    * check the provider answers core's `DEFAULT_DELETER` again
    """
    DEFAULT_DELETER_PROVIDER.install(mocker.Mock)

    DEFAULT_DELETER_PROVIDER.reset()

    assert DEFAULT_DELETER_PROVIDER.resolve() is DEFAULT_DELETER


def test_a_restored_discard_resolves_the_same_deleter_as_a_fresh_one(
    mocker: MockerFixture, control: FakeControl, present: None
) -> None:
    """A job the registry rebuilt from a saved queue has no window to be handed a deleter through, and
    coming back to a plain unlink would be no restore -- so it reads the very same provider (#298).

    **Test steps:**

    * install a provider, then rebuild a discard from its saved state through the app-wide registry
    * run it and check the operation was handed the provider's deleter, not the core default
    """
    del present
    deleter = mocker.Mock()
    mocker.patch.object(DEFAULT_DELETER_PROVIDER, "resolve", return_value=deleter)
    discard = mocker.patch("rehuco_core.tc_backups_jobs.discard_conversion_backups", return_value=DISCARDED)
    restored = DEFAULT_TASK_JOB_REGISTRY.create(TC_DISCARD_KIND, DiscardBackupsJob(REHU_PATH).capture_state())
    assert restored is not None

    restored.run(control)  # pyright: ignore[reportArgumentType]

    discard.assert_called_once_with(REHU_PATH, deleter=deleter)


def test_a_discard_that_cannot_reach_a_bin_fails_and_leaves_the_backups(
    mocker: MockerFixture, control: FakeControl, present: None
) -> None:
    """No window means no fallback to offer -- the failure is the whole of what a `NoTrashBinError`
    does here (#298).

    **Test steps:**

    * run a discard whose operation refuses with `NoTrashBinError`
    * check it propagates, and nothing was recorded as deleted
    """
    del present
    mocker.patch(
        "rehuco_core.tc_backups_jobs.discard_conversion_backups",
        side_effect=NoTrashBinError("No Recycle Bin is available"),
    )
    job = DiscardBackupsJob(REHU_PATH)

    with raises(NoTrashBinError):
        job.run(control)  # pyright: ignore[reportArgumentType]

    assert job.discarded is None


def test_a_finished_discard_holds_what_it_deleted(mocker: MockerFixture, control: FakeControl, present: None) -> None:
    """What was deleted is readable off the job once it has finished, since the engine carries no
    payload.

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


# endregion


# region Being written down


def test_a_job_writes_down_only_its_resource() -> None:
    """The operation carries no choice, so the path is the whole state.

    **Test steps:**

    * capture the job
    * check the state is the path, as text
    """
    assert DiscardBackupsJob(REHU_PATH).capture_state() == {"path": str(REHU_PATH)}


def test_a_restored_job_is_the_job_that_was_queued() -> None:
    """A capture/restore round trip preserves the resource, and the label is re-derived from it.

    **Test steps:**

    * restore a fresh job from another's captured state
    * check what it will run over, and what it is called
    """
    captured = DiscardBackupsJob(REHU_PATH).capture_state()
    restored = DiscardBackupsJob()

    restored.restore_state(captured)

    assert restored.source == REHU_PATH
    assert restored.label == "Discard backups - sculpting"


@mark.parametrize("state", [{}, {"path": ""}, {"path": 5}], ids=["no path", "empty path", "path is not a string"])
def test_a_state_that_does_not_describe_a_runnable_job_is_refused(state: dict[str, Any]) -> None:
    """A hand-edited file costs its own item rather than the app's start.

    **Test steps:**

    * restore from the unusable state
    * check it raises, which is what makes the registry drop the item
    """
    with raises(ValueError):
        DiscardBackupsJob().restore_state(state)


def test_the_kind_is_registered_so_a_saved_queue_can_rebuild_it() -> None:
    """The kind names this class in the registry a restore reads.

    **Test steps:**

    * create one from the app-wide registry
    * check the class and the restored resource
    """
    job = DEFAULT_TASK_JOB_REGISTRY.create(TC_DISCARD_KIND, {"path": str(REHU_PATH)})

    assert isinstance(job, DiscardBackupsJob)
    assert job.source == REHU_PATH


def test_a_kind_is_claimed_once() -> None:
    """Two classes claiming one kind is a programming error, and the registry says so.

    **Test steps:**

    * register the kind into a fresh registry, then register it again
    * check the second registration is refused
    """
    registry = TaskJobRegistry()
    registry.register(TC_DISCARD_KIND, DiscardBackupsJob)

    with raises(ValueError):
        registry.register(TC_DISCARD_KIND, DiscardBackupsJob)


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
    "cancel stops after the current resource" #192's import runs under, since a bulk discard is enqueued
    the same way.

    **Test steps:**

    * hold a first discard inside the operation, enqueue a second behind it and cancel that one
    * release the first and check only it ran, with the second reported cancelled
    """
    del present
    # Holding the first job is what leaves the second demonstrably *waiting its turn* when it is
    # cancelled. `queue.pause()` cannot arrange it and used to be asked to: pausing is `pause_job`
    # applied to the jobs already enqueued ([[appendices.task-queue#pause-concept]]), never a gate a
    # later enqueue passes through, so the lone job raced the cancel and a fast runner discarded it
    # first -- the same latent flake `test_tc_import_job`'s copy of this test turned red on Windows.
    running = Event()
    release = Event()

    def hold_the_worker(*_args: Any, **_kwargs: Any) -> None:
        """Park the worker inside the first discard until the test has cancelled the second."""
        running.set()
        assert release.wait(TIMEOUT)

    discard = mocker.patch("rehuco_core.tc_backups_jobs.discard_conversion_backups", side_effect=hold_the_worker)
    queue = TaskQueue()
    settled = FinishedListener(2)
    queue.add_listener(settled)
    try:
        queue.enqueue(DiscardBackupsJob(FILE_SCOPED_REHU_PATH))
        assert running.wait(TIMEOUT)
        serial = queue.enqueue(DiscardBackupsJob(REHU_PATH))
        queue.cancel(serial)
        release.set()
        assert settled.wait()
        (status,) = (job for job in queue.jobs() if job.serial == serial)
    finally:
        queue.shutdown()

    assert status.state is JobState.CANCELLED
    # the held job discarded; the cancelled one never reached `discard_conversion_backups` at all
    discard.assert_called_once()
    assert discard.call_args.args == (FILE_SCOPED_REHU_PATH,)


# endregion
