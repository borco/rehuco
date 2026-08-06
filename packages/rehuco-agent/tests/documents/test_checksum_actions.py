"""Tests for one document's Generate/Verify pair (#204).

The queue is a **real** :class:`~rehuco_core.TaskQueue` and the runs themselves are mocked: what these
tests are about is that a click *enqueues* instead of hashing on the GUI thread, which is only worth
asserting against the engine that would actually have run it. The findings then travel back the way
they do in the app -- off the job, through the queue's listener, marshalled onto the GUI thread -- so
the banner assertions exercise that path rather than a shortcut around it.
"""

import logging
from pathlib import Path
from threading import Event
from typing import Any, Final

from borco_pyside.logging import LogScope
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent import main_rc  # noqa: F401  # pylint: disable=unused-import  # registers :/icons/...
from rehuco_agent.documents.checksum_actions import ChecksumActions
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_core import ChecksumReport, JobState, RehuDocument, TaskQueue

DIRECTORY: Final = Path("/fake/library/sculpting")
INFO_PATH: Final = DIRECTORY / "info.rehu"
RECORD_PATH: Final = DIRECTORY / "info.checksum"

VIDEO: Final = "lesson1.mp4"

TIMEOUT: Final = 5000
"""How long a test waits for the worker thread, in milliseconds."""


class ScopeRecordingHandler(logging.Handler):
    """Keeps the **scope** of every record it is handed, so a test can assert where one was placed.

    Resolved in ``emit`` rather than afterwards, because that is the only place it is correct: a
    handler runs synchronously on the thread that logged, and the scope lives in that thread's context
    ([[appendices.logging#scopes]]) -- which here is the worker's copy of the enqueuer's.

    :param scopes: the list to append each record's scope to.
    """

    def __init__(self, scopes: list[Any]) -> None:
        super().__init__()
        self.__scopes: Final = scopes

    def emit(self, record: logging.LogRecord) -> None:
        """Keep what this record is about.

        :param record: the record handled.
        """
        self.__scopes.append(LogScope.of(record))


# region fixtures


@fixture(name="model")
def fixture_model() -> RehuDocumentModel:
    """A view-model over a directory-scoped resource that is on disk.

    :returns: the model the actions are about.
    """
    document = RehuDocument(
        {"type": "Tutorial", "sources": [{"title": "Sculpting Series", "primary": True}]},
        INFO_PATH,
    )
    return RehuDocumentModel(document)


@fixture(name="queue")
def fixture_queue(qapp: Any) -> Any:
    """A real queue, shut down after the test.

    :param qapp: pytest-qt's application fixture -- every test here builds ``QAction``s, which need
        one to exist before they are constructed.
    :returns: the queue the actions enqueue into.
    """
    del qapp
    queue = TaskQueue()
    yield queue
    queue.shutdown()


@fixture(name="recorded")
def fixture_recorded(mocker: MockerFixture) -> None:
    """A filesystem where the resource and its record both exist.

    :param mocker: pytest-mock fixture.
    """
    mocker.patch.object(Path, "exists", autospec=True, return_value=True)


@fixture(name="actions")
def fixture_actions(qtbot: QtBot, model: RehuDocumentModel, queue: TaskQueue, recorded: None) -> ChecksumActions:
    """The pair under test, over a resource that already has a record.

    :param qtbot: pytest-qt fixture, for waiting on signals.
    :param model: the document the actions are about.
    :param queue: the queue they enqueue into.
    :param recorded: the filesystem where the record exists.
    :returns: the actions.
    """
    del qtbot, recorded
    return ChecksumActions(model, queue)


# endregion


# region What is offered


def test_a_resource_with_no_record_is_offered_generate_and_not_verify(
    mocker: MockerFixture, model: RehuDocumentModel, queue: TaskQueue
) -> None:
    """Verify has nothing to verify against until a record exists ([[data-model#checksums]]).

    **Test steps:**

    * build the actions over a resource whose ``.checksum`` is absent
    * check Generate is offered and Verify is not
    """
    mocker.patch.object(Path, "exists", autospec=True, side_effect=lambda self: self != RECORD_PATH)
    actions = ChecksumActions(model, queue)

    assert actions.generate_action.isEnabled()
    assert not actions.verify_action.isEnabled()


def test_a_document_with_no_path_at_all_is_offered_neither(queue: TaskQueue) -> None:
    """A document bound to no path has nothing on disk to hash.

    **Test steps:**

    * build the actions over a path-less document
    * check both actions are disabled, and that triggering one anyway queues nothing
    """
    actions = ChecksumActions(RehuDocumentModel(RehuDocument({"type": "Tutorial"})), queue)

    assert not actions.generate_action.isEnabled()
    assert not actions.verify_action.isEnabled()

    actions.generate()

    assert queue.jobs() == ()


# endregion


# region Enqueuing


def test_verifying_enqueues_rather_than_hashing_on_the_gui_thread(
    qtbot: QtBot, mocker: MockerFixture, actions: ChecksumActions, queue: TaskQueue
) -> None:
    """The click returns at once and the work lands on the worker.

    **Test steps:**

    * trigger Verify with the underlying run mocked
    * check a job was queued, naming the resource, and that it ran there
    """
    verify = mocker.patch("rehuco_core.checksum_jobs.verify_checksums", return_value=ChecksumReport())

    actions.verify_action.trigger()

    (status,) = queue.jobs()
    assert status.label == "Verify checksums - sculpting/"
    assert status.source == INFO_PATH
    qtbot.waitUntil(lambda: queue.jobs()[0].state is JobState.DONE, timeout=TIMEOUT)
    assert verify.call_args.args == (INFO_PATH,)


def test_generating_enqueues_the_other_run(
    qtbot: QtBot, mocker: MockerFixture, actions: ChecksumActions, queue: TaskQueue
) -> None:
    """Generate queues a baseline over the same resource.

    **Test steps:**

    * trigger Generate with the underlying run mocked
    * check the queued row and that the baseline ran
    """
    generate = mocker.patch("rehuco_core.checksum_jobs.generate_checksums", return_value=ChecksumReport())

    actions.generate_action.trigger()

    assert [status.label for status in queue.jobs()] == ["Generate checksums - sculpting/"]
    qtbot.waitUntil(lambda: queue.jobs()[0].state is JobState.DONE, timeout=TIMEOUT)
    assert generate.called


def test_the_run_is_handed_the_excluded_files_the_user_configured(
    qtbot: QtBot, mocker: MockerFixture, actions: ChecksumActions, queue: TaskQueue
) -> None:
    """The exclusion set is resolved by the agent and passed in -- core never reads a setting (#226).

    **Test steps:**

    * configure an exclusion list and trigger Generate
    * check the run was handed it
    """
    settings = mocker.patch("rehuco_agent.documents.checksum_actions.shared_excluded_files_settings")
    settings.return_value.excluded_file_patterns = ("*.tmp",)
    generate = mocker.patch("rehuco_core.checksum_jobs.generate_checksums", return_value=ChecksumReport())

    actions.generate_action.trigger()
    qtbot.waitUntil(lambda: queue.jobs()[0].state is JobState.DONE, timeout=TIMEOUT)

    assert generate.call_args.kwargs["excluded_patterns"] == ("*.tmp",)


def test_asking_twice_does_not_queue_the_same_work_twice(
    mocker: MockerFixture, actions: ChecksumActions, queue: TaskQueue
) -> None:
    """A second click while the first run is still outstanding is a no-op.

    **Test steps:**

    * hold the first run inside its call, then trigger Verify twice
    * check only one job was queued, and that the other action is unaffected
    """
    release = Event()
    mocker.patch(
        "rehuco_core.checksum_jobs.verify_checksums",
        side_effect=lambda *_a, **_k: (release.wait(TIMEOUT / 1000), ChecksumReport())[1],
    )
    mocker.patch("rehuco_core.checksum_jobs.generate_checksums", return_value=ChecksumReport())
    try:
        actions.verify_action.trigger()
        actions.verify_action.trigger()
        actions.generate_action.trigger()
    finally:
        release.set()

    assert [status.label for status in queue.jobs()] == [
        "Verify checksums - sculpting/",
        "Generate checksums - sculpting/",
    ]


def test_a_run_s_records_land_on_the_resource_s_own_log(
    qtbot: QtBot, mocker: MockerFixture, actions: ChecksumActions, queue: TaskQueue
) -> None:
    """The enqueue opens the document's log scope, so the worker's records are placed under it (#200).

    **Test steps:**

    * trigger Verify and let the job log from the worker thread
    * check the record carried this resource's path as its scope
    """
    mocker.patch(
        "rehuco_core.checksum_jobs.verify_checksums",
        return_value=ChecksumReport(statuses={VIDEO: "matched"}),
    )
    scopes: list[Any] = []
    handler = ScopeRecordingHandler(scopes)
    logger = logging.getLogger("rehuco_core.checksum_jobs")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        actions.verify_action.trigger()
        qtbot.waitUntil(lambda: queue.jobs()[0].state is JobState.DONE, timeout=TIMEOUT)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(logging.NOTSET)

    assert scopes == [INFO_PATH]


# endregion


# region What comes back


def test_a_clean_verify_says_so(
    qtbot: QtBot, mocker: MockerFixture, actions: ChecksumActions, queue: TaskQueue
) -> None:
    """A run that found nothing wrong still reports, and reports as clean.

    **Test steps:**

    * run a verify whose every verdict is ``matched``
    * check the finding names the count and reads as clean
    """
    mocker.patch(
        "rehuco_core.checksum_jobs.verify_checksums",
        return_value=ChecksumReport(statuses={VIDEO: "matched"}),
    )

    with qtbot.waitSignal(actions.finding_changed, timeout=TIMEOUT):
        actions.verify_action.trigger()

    assert actions.finding == "Checksums verified: 1 matched."
    assert actions.finding_clean
    assert queue.jobs()[0].state is JobState.DONE


def test_a_verify_with_mismatches_surfaces_them(qtbot: QtBot, mocker: MockerFixture, actions: ChecksumActions) -> None:
    """A mismatch is a finding about the files, not an error -- so it reads as one, and is not clean.

    **Test steps:**

    * run a verify reporting a mismatch and a missing file
    * check the finding counts them and does not read as clean
    """
    mocker.patch(
        "rehuco_core.checksum_jobs.verify_checksums",
        return_value=ChecksumReport(statuses={VIDEO: "mismatched", "extras/pack.zip": "missing"}),
    )

    with qtbot.waitSignal(actions.finding_changed, timeout=TIMEOUT):
        actions.verify_action.trigger()

    assert actions.finding == "Checksums verified: 1 mismatched, 1 missing."
    assert not actions.finding_clean


def test_a_second_run_replaces_the_first_s_finding(
    qtbot: QtBot, mocker: MockerFixture, actions: ChecksumActions
) -> None:
    """The strip describes the most recent answer rather than accumulating a history.

    **Test steps:**

    * run a verify that reports a mismatch, then one that comes back clean
    * check only the second is left
    """
    mocker.patch(
        "rehuco_core.checksum_jobs.verify_checksums",
        return_value=ChecksumReport(statuses={VIDEO: "mismatched"}),
    )
    with qtbot.waitSignal(actions.finding_changed, timeout=TIMEOUT):
        actions.verify_action.trigger()

    mocker.patch(
        "rehuco_core.checksum_jobs.verify_checksums",
        return_value=ChecksumReport(statuses={VIDEO: "matched"}),
    )
    with qtbot.waitSignal(actions.finding_changed, timeout=TIMEOUT):
        actions.verify_action.trigger()

    assert actions.finding == "Checksums verified: 1 matched."
    assert actions.finding_clean


def test_a_run_that_was_stopped_part_way_says_nothing(
    qtbot: QtBot, mocker: MockerFixture, actions: ChecksumActions, queue: TaskQueue
) -> None:
    """A cancelled run established nothing, so there is nothing to report ([[data-model#checksums]]).

    **Test steps:**

    * run a verify that raises out of its checkpoint after being cancelled
    * check the job is cancelled and no finding was raised
    """
    mocker.patch(
        "rehuco_core.checksum_jobs.verify_checksums",
        side_effect=lambda *_args, **kwargs: kwargs["checkpoint"](),
    )
    actions.verify_action.trigger()
    queue.cancel(queue.jobs()[0].serial)

    qtbot.waitUntil(lambda: queue.jobs()[0].state in {JobState.CANCELLED, JobState.DONE}, timeout=TIMEOUT)

    assert actions.finding == ""


def test_a_first_generate_turns_verify_on(
    qtbot: QtBot, mocker: MockerFixture, model: RehuDocumentModel, queue: TaskQueue
) -> None:
    """Once a record exists, Verify becomes offerable without reopening the document.

    **Test steps:**

    * generate over a resource with no record, with the record appearing as the run finishes
    * check Verify is enabled afterwards
    """
    record_exists = False
    mocker.patch.object(Path, "exists", autospec=True, side_effect=lambda self: self != RECORD_PATH or record_exists)
    actions = ChecksumActions(model, queue)
    assert not actions.verify_action.isEnabled()

    def generate(*_args: Any, **_kwargs: Any) -> ChecksumReport:
        nonlocal record_exists
        record_exists = True
        return ChecksumReport(statuses={VIDEO: "matched"})

    mocker.patch("rehuco_core.checksum_jobs.generate_checksums", side_effect=generate)

    with qtbot.waitSignal(actions.finding_changed, timeout=TIMEOUT):
        actions.generate_action.trigger()

    assert actions.verify_action.isEnabled()
    assert actions.finding == "Checksums recorded: 1 matched."


def test_a_reorder_or_a_removal_elsewhere_in_the_queue_says_nothing(actions: ChecksumActions) -> None:
    """Only a job *moving state* can carry a finding, so the other three notifications are no-ops.

    **Test steps:**

    * hand the actions a reorder, a removal and a queue-pause notification
    * check nothing was reported
    """
    actions.jobs_reordered([1, 2])
    actions.jobs_removed([1])
    actions.queue_paused_changed(True)

    assert actions.finding == ""


def test_a_resource_whose_record_cannot_be_read_is_offered_generate(
    mocker: MockerFixture, model: RehuDocumentModel, queue: TaskQueue
) -> None:
    """A mount that refuses the ``stat`` answers *no record*, which offers the safe half (#245).

    **Test steps:**

    * make the record's ``exists`` raise, as an unreachable mount can
    * check Verify is not offered and nothing was raised out of the construction
    """
    mocker.patch.object(Path, "exists", autospec=True, side_effect=PermissionError("the mount is away"))

    actions = ChecksumActions(model, queue)

    assert not actions.verify_action.isEnabled()


# endregion


# region Teardown


def test_a_closed_document_stops_listening_without_stopping_its_work(
    qtbot: QtBot, mocker: MockerFixture, actions: ChecksumActions, queue: TaskQueue
) -> None:
    """Detaching drops the listener; the job already asked for still runs.

    **Test steps:**

    * enqueue a verify, detach, and let the queue settle
    * check the job finished and nothing was reported to the detached surface
    """
    mocker.patch(
        "rehuco_core.checksum_jobs.verify_checksums",
        return_value=ChecksumReport(statuses={VIDEO: "matched"}),
    )
    actions.verify_action.trigger()

    actions.detach()
    qtbot.waitUntil(lambda: queue.jobs()[0].state is JobState.DONE, timeout=TIMEOUT)

    assert actions.finding == ""


# endregion
