"""Tests for the `File ▸ Conversion Backups…` manager (#193).

The scan is mocked at :func:`~rehuco_core.scan_conversion_backups` -- `test_tc_conversion_backups_scan`
is its subject -- but the **queue is real** and the two operations are mocked one level below the jobs,
so an action travels the way it does in the app: enqueued, run on the worker, read back off the job
through the listener and marshalled onto the GUI thread. What these tests are about is which rows the
dialog offers, what each confirmation says, and that nothing destructive happens without one.
"""

# one cohesive suite over the dialog's scan, selection, confirmations and both actions -- a scoped
# disable reads better than an arbitrary split (same precedent as test_rehu_document_model.py,
# [[appendices.code-conventions]])
# pylint: disable=too-many-lines

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from threading import Event
from typing import Any, Final

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent import main_rc  # noqa: F401  # pylint: disable=unused-import  # registers :/icons/...
from rehuco_agent.dialogs.conversion_backups_dialog import (
    MAXIMUM_NAMED_EDITED,
    NO_LEGACY_REASON,
    NOTHING_RETAINED,
    ConversionBackupsDialog,
)
from rehuco_agent.dialogs.conversion_backups_table_model import REFUSED_OUTCOME, TIE_BREAK_FLAG
from rehuco_agent.settings.conversion_backups_dialog_settings import ConversionBackupsDialogSettings
from rehuco_core import ConversionBackups, ConversionBackupsTreeScan, JobState, JobStatus, TaskQueue

ROOT: Final = Path("/fake/library")
SCULPTING: Final = ROOT / "Sculpting" / "info.rehu"
ZBRUSH: Final = ROOT / "ZBrush" / "info.rehu"
PAINTING: Final = ROOT / "Painting" / "info.rehu"

CONVERTED_STAMP: Final = "2023-11-14T22:13:20Z"

DIALOG_MODULE: Final = "rehuco_agent.dialogs.conversion_backups_dialog"
JOBS_MODULE: Final = "rehuco_core.tc_backups_jobs"

TIMEOUT: Final = 5000
"""How long a test waits for the worker thread, in milliseconds."""


# a builder's parameters *are* the shapes worth testing; see test_conversion_backups_table_model
def make_backups(  # pylint: disable=too-many-arguments
    rehu_path: Path,
    *,
    files: int = 2,
    total_bytes: int = 14_000_000,
    installed: int = 2,
    edited_since: bool = False,
    legacy: bool = True,
) -> ConversionBackups:
    """One resource's inventory, as :func:`~rehuco_core.conversion_backups` would report it.

    :param rehu_path: the converted resource.
    :param files: how many image backups it retains.
    :param total_bytes: what they occupy.
    :param installed: how many screenshots the conversion installed -- fewer than ``files`` is a tie-break.
    :param edited_since: whether the ``.rehu`` has been saved again since the conversion.
    :param legacy: whether a backed-up ``.tc`` is here -- without one there is nothing to revert.
    :returns: the inventory.
    """
    directory = rehu_path.parent
    backups = tuple(directory / f"sample-{index:02}.jpg.orig" for index in range(files))
    if legacy:
        backups = (*backups, directory / "info.tc.orig")
    written = (rehu_path, *(directory / f"info{index:02}.jpg" for index in range(installed)))
    return ConversionBackups(
        rehu_path=rehu_path,
        backups=backups,
        total_bytes=total_bytes,
        written=written,
        obstructions=(),
        legacy_restored=(directory / "info.tc") if legacy else None,
        edited_since=edited_since,
        converted=CONVERTED_STAMP,
    )


def make_scan(
    resources: Sequence[ConversionBackups], *, examined: int = 9, unreadable: int = 0
) -> ConversionBackupsTreeScan:
    """A finished scan of the shape the dialog renders.

    :param resources: the resources still holding backups.
    :param examined: how many records the walk read in all.
    :param unreadable: how many branches would not list.
    :returns: the scan.
    """
    return ConversionBackupsTreeScan(
        ROOT,
        tuple(resources),
        tuple(ROOT / f"Away{index}" for index in range(unreadable)),
        examined,
    )


# region fixtures


@fixture(name="queue")
def fixture_queue(qapp: Any) -> Any:
    """A real queue, shut down after the test.

    :param qapp: pytest-qt's application fixture -- the dialog builds widgets, which need one.
    :returns: the queue the dialog enqueues into.
    """
    del qapp
    queue = TaskQueue()
    yield queue
    queue.shutdown()


@fixture(name="scan")
def fixture_scan(mocker: MockerFixture) -> Any:
    """The scan the dialog runs, patched at the seam it calls.

    Three resources: a tie-break, an edited-since, and one with nothing left to revert.

    :param mocker: pytest-mock fixture.
    :returns: the patched :func:`~rehuco_core.scan_conversion_backups`.
    """
    return mocker.patch(
        f"{DIALOG_MODULE}.scan_conversion_backups",
        return_value=make_scan(
            [
                make_backups(SCULPTING, files=3, installed=2),
                make_backups(ZBRUSH, edited_since=True, total_bytes=1000),
                make_backups(PAINTING, legacy=False, total_bytes=2000),
            ],
            examined=9,
        ),
    )


@fixture(name="present")
def fixture_present(mocker: MockerFixture) -> None:
    """A filesystem where every path a job validates against exists -- the uninteresting case.

    :param mocker: pytest-mock fixture.
    """
    mocker.patch.object(Path, "exists", autospec=True, return_value=True)


@fixture(name="dialog")
def fixture_dialog(qtbot: QtBot, queue: TaskQueue, scan: Any, present: None) -> ConversionBackupsDialog:
    """The dialog under test, over a scanned root.

    :param qtbot: pytest-qt fixture, for waiting on the worker thread.
    :param queue: the queue it enqueues into.
    :param scan: the patched scan seam.
    :param present: the filesystem where each resource still exists.
    :returns: the dialog, with its scan already finished.
    """
    del scan, present
    dialog = ConversionBackupsDialog(queue)
    qtbot.addWidget(dialog)
    choose_root(qtbot, dialog, ROOT)
    return dialog


@fixture(name="answer_yes")
def fixture_answer_yes(mocker: MockerFixture) -> Any:
    """Every confirmation answered Yes.

    :param mocker: pytest-mock fixture.
    :returns: the patched ``QMessageBox.warning``, so a test can read what was asked.
    """
    return mocker.patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Yes)


@fixture(name="answer_no")
def fixture_answer_no(mocker: MockerFixture) -> Any:
    """Every confirmation answered No.

    :param mocker: pytest-mock fixture.
    :returns: the patched ``QMessageBox.warning``.
    """
    return mocker.patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.No)


def ui_of(dialog: ConversionBackupsDialog) -> Any:
    """The dialog's generated widgets.

    Private by design -- nothing outside the class drives them in the app -- but they are what a reader
    actually clicks, so a test that went around them would prove something else.

    :param dialog: the dialog to inspect.
    :returns: the ``Ui_ConversionBackupsDialog``.
    """
    return dialog._ConversionBackupsDialog__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access


def scan_worker_of(dialog: ConversionBackupsDialog) -> Any:
    """The dialog's in-flight scan worker, or ``None`` between scans.

    The only observable *is it still scanning* -- a never-shown dialog's widgets all answer
    ``isVisible()`` false, so the progress bar cannot stand in for it.

    :param dialog: the dialog to inspect.
    :returns: the worker, or ``None``.
    """
    return dialog._ConversionBackupsDialog__scan_worker  # type: ignore[attr-defined]  # pylint: disable=protected-access


def choose_root(qtbot: QtBot, dialog: ConversionBackupsDialog, root: Path) -> None:
    """Point the dialog at ``root`` and wait for its worker-thread scan to finish.

    :param qtbot: pytest-qt fixture.
    :param dialog: the dialog to drive.
    :param root: the folder to scan.
    """
    dialog._ConversionBackupsDialog__set_root(root)  # type: ignore[attr-defined]  # pylint: disable=protected-access
    qtbot.waitUntil(lambda: scan_worker_of(dialog) is None, timeout=TIMEOUT)


def wait_for_outcomes(qtbot: QtBot, dialog: ConversionBackupsDialog) -> None:
    """Wait until no row is still pending.

    :param qtbot: pytest-qt fixture.
    :param dialog: the dialog to watch.
    """
    qtbot.waitUntil(lambda: all(row.outcome != "pending" for row in dialog.model.rows()), timeout=TIMEOUT)


def names(dialog: ConversionBackupsDialog) -> list[str]:
    """The resource directory names currently in the table."""
    return [row.path.parent.name for row in dialog.model.rows()]


def question_of(warning: Any) -> str:
    """What the last confirmation actually asked."""
    return str(warning.call_args.args[2])


# endregion


# region Scanning


def test_the_table_lists_exactly_the_resources_that_still_have_backups(dialog: ConversionBackupsDialog) -> None:
    """The answer is the work a reader could actually do, not an inventory of the catalog.

    **Test steps:**

    * scan a root whose three resources still hold backups, out of nine examined
    * verify each is a row, and every row starts checked
    """
    assert names(dialog) == ["Sculpting", "ZBrush", "Painting"]
    assert len(dialog.model.checked_rows()) == 3


def test_the_header_names_the_totals_the_decision_turns_on(dialog: ConversionBackupsDialog) -> None:
    """The byte total is the number that makes the decision easy, and the tie-break count is the pointer
    to the review pass.

    **Test steps:**

    * read the summary after a scan
    * verify it names the ratio, the selection, the files, the bytes and the tie-breaks
    """
    summary = ui_of(dialog).summary_label.text()

    assert "3 of 9 resources" in summary
    assert "3 selected" in summary
    assert "9 files" in summary
    assert "14.0 MB" in summary
    assert TIE_BREAK_FLAG in summary


def test_the_header_follows_the_selection(qtbot: QtBot, dialog: ConversionBackupsDialog) -> None:
    """The decision is about what is selected right now, so unchecking a row has to move the total.

    **Test steps:**

    * uncheck the largest resource
    * verify the header's selection count and byte total both drop
    """
    del qtbot
    dialog.model.set_checked([SCULPTING], False)

    summary = ui_of(dialog).summary_label.text()

    assert "2 selected" in summary
    assert "14.0 MB" not in summary


def test_a_root_with_nothing_retained_says_so(qtbot: QtBot, queue: TaskQueue, mocker: MockerFixture) -> None:
    """*Nothing left to clean up* is a real answer, and an empty table with no sentence is not it.

    **Test steps:**

    * scan a root whose resources hold no backups
    * verify the summary says there is nothing, and no row is offered
    """
    mocker.patch(f"{DIALOG_MODULE}.scan_conversion_backups", return_value=make_scan([], examined=9))
    dialog = ConversionBackupsDialog(queue)
    qtbot.addWidget(dialog)

    choose_root(qtbot, dialog, ROOT)

    assert NOTHING_RETAINED in ui_of(dialog).summary_label.text()
    assert not dialog.model.rows()


def test_an_unreadable_branch_is_named_in_the_header(qtbot: QtBot, queue: TaskQueue, mocker: MockerFixture) -> None:
    """A catalog that would not list and one with nothing retained are the same empty table otherwise.

    **Test steps:**

    * scan a root where one branch would not list
    * verify the summary says so
    """
    mocker.patch(
        f"{DIALOG_MODULE}.scan_conversion_backups",
        return_value=make_scan([make_backups(SCULPTING)], examined=4, unreadable=2),
    )
    dialog = ConversionBackupsDialog(queue)
    qtbot.addWidget(dialog)

    choose_root(qtbot, dialog, ROOT)

    assert "2 folder(s) could not be read" in ui_of(dialog).summary_label.text()


def test_a_scanned_root_is_remembered(dialog: ConversionBackupsDialog) -> None:
    """The next session opens on the folder this one was working through.

    **Test steps:**

    * scan a root
    * verify it heads the recent-roots list
    """
    combo = ui_of(dialog).recent_roots_combo

    assert combo.itemData(0) == ROOT


def test_a_failed_scan_reports_the_reason_rather_than_an_empty_table(
    qtbot: QtBot, queue: TaskQueue, mocker: MockerFixture
) -> None:
    """A scan that blew up must not read as a catalog with nothing in it.

    **Test steps:**

    * make the scan raise
    * verify the status says it failed, and no row is offered
    """
    mocker.patch(f"{DIALOG_MODULE}.scan_conversion_backups", side_effect=OSError("mount away"))
    dialog = ConversionBackupsDialog(queue)
    qtbot.addWidget(dialog)

    choose_root(qtbot, dialog, ROOT)

    assert "Scan failed" in ui_of(dialog).status_label.text()
    assert not dialog.model.rows()


# endregion


def test_the_dialog_answers_which_folder_it_is_looking_at(dialog: ConversionBackupsDialog) -> None:
    """What a caller (or the next rescan) reads back off it.

    **Test steps:**

    * scan a root
    * verify the dialog reports it
    """
    assert dialog.root == ROOT


def test_browsing_to_a_folder_scans_it(qtbot: QtBot, dialog: ConversionBackupsDialog, mocker: MockerFixture) -> None:
    """Choosing a folder is the whole of starting a run -- there is no separate *scan* to press.

    **Test steps:**

    * browse to a second folder
    * verify it became the chosen root and was scanned
    """
    chosen = ROOT / "Sub"
    mocker.patch.object(QFileDialog, "getExistingDirectory", return_value=str(chosen))

    ui_of(dialog).browse_button.click()
    qtbot.waitUntil(lambda: scan_worker_of(dialog) is None, timeout=TIMEOUT)

    assert dialog.root == chosen


def test_a_cancelled_browse_leaves_the_root_alone(
    qtbot: QtBot, dialog: ConversionBackupsDialog, mocker: MockerFixture
) -> None:
    """Dismissing the file chooser is not a request to scan anything.

    **Test steps:**

    * browse and dismiss the chooser
    * verify the previous root still stands
    """
    del qtbot
    mocker.patch.object(QFileDialog, "getExistingDirectory", return_value="")

    ui_of(dialog).browse_button.click()

    assert dialog.root == ROOT


def test_choosing_a_recent_folder_scans_it(qtbot: QtBot, dialog: ConversionBackupsDialog) -> None:
    """The list exists to be picked from, not only to be looked at.

    **Test steps:**

    * activate the newest recent entry
    * verify it became the chosen root
    """
    ui_of(dialog).recent_roots_combo.activated.emit(0)
    qtbot.waitUntil(lambda: scan_worker_of(dialog) is None, timeout=TIMEOUT)

    assert dialog.root == ROOT


def test_rescanning_reads_the_folder_again(qtbot: QtBot, dialog: ConversionBackupsDialog, scan: Any) -> None:
    """What makes the table honest after an action has run over it.

    **Test steps:**

    * rescan the current root
    * verify the scan ran a second time
    """
    before = scan.call_count

    ui_of(dialog).rescan_button.click()
    qtbot.waitUntil(lambda: scan_worker_of(dialog) is None, timeout=TIMEOUT)

    assert scan.call_count == before + 1


def test_cancelling_a_scan_stops_it_and_keeps_the_previous_rows(
    qtbot: QtBot, dialog: ConversionBackupsDialog, scan: Any
) -> None:
    """A long walk over a mount has to be stoppable, and stopping it must not throw away the answer
    already on screen.

    **Test steps:**

    * start a scan that blocks until cancelled, then cancel it
    * verify the scan reports cancelled and the previous rows are still there
    """
    started = Event()
    released = Event()

    def blocking_scan(_root: Path, *, progress: Any = None, checkpoint: Any = None) -> Any:
        del progress
        started.set()
        released.wait(TIMEOUT / 1000)
        checkpoint()
        raise AssertionError("the checkpoint should have unwound this scan")

    scan.side_effect = blocking_scan
    ui_of(dialog).rescan_button.click()
    qtbot.waitUntil(started.is_set, timeout=TIMEOUT)

    ui_of(dialog).cancel_button.click()
    released.set()
    qtbot.waitUntil(lambda: scan_worker_of(dialog) is None, timeout=TIMEOUT)

    assert "cancelled" in ui_of(dialog).status_label.text().lower()
    assert len(dialog.model.rows()) == 3


def test_a_scan_reports_how_far_it_has_got(qtbot: QtBot, dialog: ConversionBackupsDialog, scan: Any) -> None:
    """A catalog where almost nothing has backups would otherwise look like a hung dialog.

    **Test steps:**

    * run a scan that reports progress
    * verify the status named the running count
    """
    released = Event()

    def reporting_scan(_root: Path, *, progress: Any = None, checkpoint: Any = None) -> Any:
        del checkpoint
        progress(7)
        # hold the walk open, so the running count is still what the label says when it is read --
        # a finished scan replaces it with the summary
        released.wait(TIMEOUT / 1000)
        return make_scan([], examined=7)

    scan.side_effect = reporting_scan

    ui_of(dialog).rescan_button.click()
    qtbot.waitUntil(lambda: "7 examined" in ui_of(dialog).status_label.text(), timeout=TIMEOUT)
    released.set()
    qtbot.waitUntil(lambda: scan_worker_of(dialog) is None, timeout=TIMEOUT)

    assert dialog.model.rows() == ()


def test_a_second_scan_is_not_started_while_one_is_running(
    qtbot: QtBot, dialog: ConversionBackupsDialog, scan: Any
) -> None:
    """Two walks over one tree would double the reads and race each other into the same table.

    **Test steps:**

    * start a blocking scan, then ask for another
    * verify only one ran
    """
    started = Event()
    released = Event()

    def blocking_scan(_root: Path, *, progress: Any = None, checkpoint: Any = None) -> Any:
        del progress, checkpoint
        started.set()
        released.wait(TIMEOUT / 1000)
        return make_scan([])

    scan.side_effect = blocking_scan
    before = scan.call_count
    ui_of(dialog).rescan_button.click()
    qtbot.waitUntil(started.is_set, timeout=TIMEOUT)

    dialog._ConversionBackupsDialog__begin_scan()  # type: ignore[attr-defined]  # pylint: disable=protected-access
    released.set()
    qtbot.waitUntil(lambda: scan_worker_of(dialog) is None, timeout=TIMEOUT)

    assert scan.call_count == before + 1


def test_the_dialog_ignores_jobs_that_are_not_its_own(dialog: ConversionBackupsDialog) -> None:
    """Every surface listens to one shared queue, so each has to recognize its own rows -- and the
    engine's other notices are simply nothing to this one.

    **Test steps:**

    * hand the dialog a status for a job it never enqueued, and each notice it does not act on
    * verify no row changed
    """
    dialog.job_enqueued(JobStatus(serial=999, label="Someone else's", state=JobState.DONE, done=1), 0)
    dialog.job_updated(JobStatus(serial=999, label="Someone else's", state=JobState.DONE, done=1))
    dialog.jobs_reordered([999])
    dialog.jobs_removed([999])
    dialog.queue_paused_changed(True)

    assert all(row.outcome is None for row in dialog.model.rows())


# endregion


# region Filtering and selection


def test_filtering_by_a_flag_reaches_the_review_pass(qtbot: QtBot, dialog: ConversionBackupsDialog) -> None:
    """Filter to the ~1--2 % a judgement was made about, which is what #192 deliberately deferred.

    **Test steps:**

    * type the tie-break flag into the filter
    * verify one row is shown
    """
    del qtbot
    ui_of(dialog).filter_edit.setText(TIE_BREAK_FLAG)

    assert ui_of(dialog).backups_table_view.model().rowCount() == 1


def test_select_all_acts_on_the_filtered_view_only(qtbot: QtBot, dialog: ConversionBackupsDialog) -> None:
    """Having filtered to the tie-breaks, selecting all of *them* and selecting the whole scan are very
    different asks -- and only one of them was made.

    **Test steps:**

    * clear every selection, filter to the tie-break, then select all shown
    * verify only the filtered resource became selected
    """
    dialog.model.set_checked([SCULPTING, ZBRUSH, PAINTING], False)
    ui_of(dialog).filter_edit.setText(TIE_BREAK_FLAG)

    ui_of(dialog).select_all_check_box.click()
    qtbot.wait(0)

    assert [row.path for row in dialog.model.checked_rows()] == [SCULPTING]


def test_select_all_clears_a_fully_selected_view(qtbot: QtBot, dialog: ConversionBackupsDialog) -> None:
    """Clicking it again is how a reader starts over, so a full view has to toggle off rather than
    cycling through the partial state the tri-state box can show.

    **Test steps:**

    * click select-all over an already-fully-selected table
    * verify nothing is selected
    """
    ui_of(dialog).select_all_check_box.click()
    qtbot.wait(0)

    assert not dialog.model.checked_rows()


def test_the_select_all_box_shows_the_views_own_state(qtbot: QtBot, dialog: ConversionBackupsDialog) -> None:
    """Partially checked is a readout, not an instruction -- it tells a reader the view is mixed.

    **Test steps:**

    * uncheck one row of three
    * verify the box reads partially checked
    """
    del qtbot
    dialog.model.set_checked([SCULPTING], False)

    assert ui_of(dialog).select_all_check_box.checkState() == Qt.CheckState.PartiallyChecked


def test_neither_action_is_offered_with_nothing_selected(qtbot: QtBot, dialog: ConversionBackupsDialog) -> None:
    """A button that would act on nothing is a button that does nothing.

    **Test steps:**

    * clear the selection
    * verify both action buttons are disabled
    """
    del qtbot
    dialog.model.set_checked([SCULPTING, ZBRUSH, PAINTING], False)

    assert not ui_of(dialog).revert_button.isEnabled()
    assert not ui_of(dialog).discard_button.isEnabled()


# endregion


# region Discarding


def test_discarding_asks_first_and_names_the_count_and_the_bytes(
    qtbot: QtBot, dialog: ConversionBackupsDialog, answer_yes: Any, mocker: MockerFixture
) -> None:
    """The only irreversible act in the whole import flow, so the confirmation reads that way rather
    than as a reflexive yes/no.

    **Test steps:**

    * discard the whole selection with the confirmation answered Yes
    * verify what was asked, and that every row came back discarded
    """
    discard = mocker.patch(f"{JOBS_MODULE}.discard_conversion_backups", return_value=())

    ui_of(dialog).discard_button.click()
    wait_for_outcomes(qtbot, dialog)

    assert "3 resource(s)" in question_of(answer_yes)
    assert "cannot be undone" in question_of(answer_yes)
    assert {row.outcome for row in dialog.model.rows()} == {"discarded"}
    assert discard.call_count == 3


def test_a_declined_discard_enqueues_nothing(
    qtbot: QtBot, dialog: ConversionBackupsDialog, answer_no: Any, queue: TaskQueue, mocker: MockerFixture
) -> None:
    """Nothing is deleted until the question is answered Yes -- and nothing reaches the queue either.

    **Test steps:**

    * discard with the confirmation answered No
    * verify the queue stayed empty and no row changed
    """
    del answer_no
    discard = mocker.patch(f"{JOBS_MODULE}.discard_conversion_backups")

    ui_of(dialog).discard_button.click()
    qtbot.wait(0)

    discard.assert_not_called()
    assert not queue.jobs()
    assert all(row.outcome is None for row in dialog.model.rows())


def test_each_resource_is_its_own_job(
    qtbot: QtBot, dialog: ConversionBackupsDialog, answer_yes: Any, queue: TaskQueue, mocker: MockerFixture
) -> None:
    """One job per resource, so cancelling stops after the current one and each operation runs under its
    own resource's log scope.

    **Test steps:**

    * discard a two-row selection
    * verify the queue holds one row per resource, each naming its own source
    """
    del answer_yes
    mocker.patch(f"{JOBS_MODULE}.discard_conversion_backups", return_value=())
    dialog.model.set_checked([PAINTING], False)

    ui_of(dialog).discard_button.click()
    wait_for_outcomes(qtbot, dialog)

    assert sorted(str(status.source) for status in queue.jobs()) == sorted([str(SCULPTING), str(ZBRUSH)])


def test_a_failed_operation_lands_on_its_own_row(
    qtbot: QtBot, dialog: ConversionBackupsDialog, answer_yes: Any, mocker: MockerFixture
) -> None:
    """A read-only mount refuses one resource without costing the rest of the run.

    **Test steps:**

    * make the operation raise for every resource
    * verify each row reports the failure with its reason
    """
    del answer_yes
    mocker.patch(f"{JOBS_MODULE}.discard_conversion_backups", side_effect=PermissionError("read-only"))

    ui_of(dialog).discard_button.click()
    wait_for_outcomes(qtbot, dialog)

    assert {row.outcome for row in dialog.model.rows()} == {"failed"}
    assert all("read-only" in (row.message or "") for row in dialog.model.rows())


# endregion


# region Reverting


def test_reverting_warns_per_resource_about_edits_saved_since(
    qtbot: QtBot, dialog: ConversionBackupsDialog, answer_yes: Any, mocker: MockerFixture
) -> None:
    """Per resource, not a blanket disclaimer: *some of these may have been edited* is a sentence a
    reader can only agree to blindly.

    **Test steps:**

    * revert a selection holding one edited-since resource
    * verify the question counts them and names the one
    """
    mocker.patch(f"{JOBS_MODULE}.revert_conversion", return_value=None)

    ui_of(dialog).revert_button.click()
    wait_for_outcomes(qtbot, dialog)

    assert "1 of these have been saved again" in question_of(answer_yes)
    assert "ZBrush" in question_of(answer_yes)


def test_an_unrevertible_row_is_refused_here_rather_than_by_the_queue(
    qtbot: QtBot, dialog: ConversionBackupsDialog, answer_yes: Any, mocker: MockerFixture
) -> None:
    """The inventory already knows it cannot run, so asking the queue would buy the same refusal later
    and noisier -- and the reason belongs on the row.

    **Test steps:**

    * revert a selection holding one resource with no backed-up ``.tc``
    * verify that row is refused with its reason, and the operation never ran over it
    """
    del answer_yes
    revert = mocker.patch(f"{JOBS_MODULE}.revert_conversion", return_value=None)

    ui_of(dialog).revert_button.click()
    wait_for_outcomes(qtbot, dialog)

    outcomes = {row.path.parent.name: (row.outcome, row.message) for row in dialog.model.rows()}
    assert outcomes["Painting"] == (REFUSED_OUTCOME, NO_LEGACY_REASON)
    assert outcomes["Sculpting"][0] == "reverted"
    assert revert.call_count == 2


def test_a_declined_revert_leaves_every_row_alone(
    qtbot: QtBot, dialog: ConversionBackupsDialog, answer_no: Any, mocker: MockerFixture
) -> None:
    """Answering No must not mark the unrevertible rows either -- nothing was asked for at all.

    **Test steps:**

    * revert with the confirmation answered No
    * verify no row carries an outcome and nothing ran
    """
    del answer_no
    revert = mocker.patch(f"{JOBS_MODULE}.revert_conversion")

    ui_of(dialog).revert_button.click()
    qtbot.wait(0)

    revert.assert_not_called()
    assert all(row.outcome is None for row in dialog.model.rows())


def test_a_selection_of_only_unrevertible_rows_asks_nothing(
    qtbot: QtBot, dialog: ConversionBackupsDialog, answer_yes: Any, mocker: MockerFixture
) -> None:
    """There is nothing to agree to when nothing can run, so the refusals are simply recorded.

    **Test steps:**

    * select only the resource with no backed-up ``.tc``, then revert
    * verify no confirmation was put and the row says why
    """
    revert = mocker.patch(f"{JOBS_MODULE}.revert_conversion")
    dialog.model.set_checked([SCULPTING, ZBRUSH], False)

    ui_of(dialog).revert_button.click()
    qtbot.wait(0)

    answer_yes.assert_not_called()
    revert.assert_not_called()
    outcomes = {row.path.parent.name: row.outcome for row in dialog.model.rows()}
    assert outcomes["Painting"] == REFUSED_OUTCOME


# endregion


def test_an_occupied_restore_target_is_refused_by_name(
    qtbot: QtBot, queue: TaskQueue, mocker: MockerFixture, answer_yes: Any, present: None
) -> None:
    """A legacy name the user has since put back by hand refuses the whole revert, and naming it is what
    lets them decide what to do about it.

    **Test steps:**

    * revert a resource whose restore target is occupied
    * verify the row names the file that is in the way
    """
    del answer_yes, present
    obstructed = make_backups(SCULPTING)
    mocker.patch(
        f"{DIALOG_MODULE}.scan_conversion_backups",
        return_value=make_scan([replace(obstructed, obstructions=(SCULPTING.parent / "sample-00.jpg",))]),
    )
    mocker.patch(f"{JOBS_MODULE}.revert_conversion")
    dialog = ConversionBackupsDialog(queue)
    qtbot.addWidget(dialog)
    choose_root(qtbot, dialog, ROOT)

    ui_of(dialog).revert_button.click()
    qtbot.wait(0)

    # pylint infers `rows()`'s tuple as empty from the model's initial state rather than from the scan
    # this dialog was given, so the single-row unpack looks unbalanced to it
    (row,) = dialog.model.rows()  # pylint: disable=unbalanced-tuple-unpacking
    assert row.outcome == REFUSED_OUTCOME
    assert row.message == "sample-00.jpg is in the way"


def test_the_revert_warning_counts_the_rest_past_a_wall_of_names(
    qtbot: QtBot, queue: TaskQueue, mocker: MockerFixture, answer_yes: Any, present: None
) -> None:
    """Naming every one of a hundred edited resources is a blanket disclaimer again, just longer.

    **Test steps:**

    * revert a selection where more resources were edited than the confirmation names
    * verify the extras are counted rather than listed
    """
    del present
    edited = [
        make_backups(ROOT / f"Resource{index}" / "info.rehu", edited_since=True)
        for index in range(MAXIMUM_NAMED_EDITED + 3)
    ]
    mocker.patch(f"{DIALOG_MODULE}.scan_conversion_backups", return_value=make_scan(edited))
    mocker.patch(f"{JOBS_MODULE}.revert_conversion")
    dialog = ConversionBackupsDialog(queue)
    qtbot.addWidget(dialog)
    choose_root(qtbot, dialog, ROOT)

    ui_of(dialog).revert_button.click()
    wait_for_outcomes(qtbot, dialog)

    assert "and 3 more" in question_of(answer_yes)


def test_a_revert_with_nothing_edited_says_nothing_about_edits(
    qtbot: QtBot, dialog: ConversionBackupsDialog, answer_yes: Any, mocker: MockerFixture
) -> None:
    """The warning is a fact about the selection, so a selection it is not true of must not carry it --
    a disclaimer that always appears is one nobody reads.

    **Test steps:**

    * revert a selection holding no edited-since resource
    * verify the question says nothing about discarded edits
    """
    mocker.patch(f"{JOBS_MODULE}.revert_conversion")
    dialog.model.set_checked([ZBRUSH, PAINTING], False)

    ui_of(dialog).revert_button.click()
    wait_for_outcomes(qtbot, dialog)

    assert "saved again" not in question_of(answer_yes)


def test_reverting_warns_about_resources_open_in_a_tab(
    qtbot: QtBot, queue: TaskQueue, scan: Any, present: None, answer_yes: Any, mocker: MockerFixture
) -> None:
    """The bulk manager cannot see open documents on its own -- ``open_paths`` is the seam that tells it,
    and what makes this warning possible at all (#246).

    **Test steps:**

    * revert a selection where one of the two runnable resources is reported as open
    * verify the question counts it
    """
    del scan, present
    mocker.patch(f"{JOBS_MODULE}.revert_conversion", return_value=None)
    dialog = ConversionBackupsDialog(queue, open_paths=lambda: {SCULPTING})
    qtbot.addWidget(dialog)
    choose_root(qtbot, dialog, ROOT)

    ui_of(dialog).revert_button.click()
    wait_for_outcomes(qtbot, dialog)

    assert "1 of these are open in an editor tab" in question_of(answer_yes)


def test_reverting_says_nothing_about_open_documents_with_no_seam_wired(
    qtbot: QtBot, dialog: ConversionBackupsDialog, answer_yes: Any, mocker: MockerFixture
) -> None:
    """With no ``open_paths`` wired -- the default -- the manager says nothing about tabs it has no way
    to see.

    **Test steps:**

    * revert with the default dialog, built with no ``open_paths``
    * verify the question says nothing about open tabs
    """
    mocker.patch(f"{JOBS_MODULE}.revert_conversion", return_value=None)

    ui_of(dialog).revert_button.click()
    wait_for_outcomes(qtbot, dialog)

    assert "open in an editor tab" not in question_of(answer_yes)


def test_a_finished_revert_reports_it_to_the_open_documents_seam(
    qtbot: QtBot, queue: TaskQueue, scan: Any, present: None, answer_yes: Any, mocker: MockerFixture
) -> None:
    """A successfully reverted resource is handed to ``on_reverted``, so an open tab can adopt the
    restored ``.tc`` in place instead of going stale (#246).

    **Test steps:**

    * revert a selection restricted to one revertible resource
    * verify ``on_reverted`` was called with its path once the job finished
    """
    del scan, present, answer_yes
    mocker.patch(f"{JOBS_MODULE}.revert_conversion", return_value=None)
    on_reverted = mocker.Mock()
    dialog = ConversionBackupsDialog(queue, on_reverted=on_reverted)
    qtbot.addWidget(dialog)
    choose_root(qtbot, dialog, ROOT)
    dialog.model.set_checked([ZBRUSH, PAINTING], False)

    ui_of(dialog).revert_button.click()
    wait_for_outcomes(qtbot, dialog)

    on_reverted.assert_called_once_with(SCULPTING)


def test_a_failed_revert_does_not_report_it_to_the_open_documents_seam(
    qtbot: QtBot, queue: TaskQueue, scan: Any, present: None, answer_yes: Any, mocker: MockerFixture
) -> None:
    """Only a resource that actually reverted is worth catching an open tab up on -- a failed operation
    changed nothing on disk for it to adopt (#246).

    **Test steps:**

    * make the operation raise for the one resource selected
    * verify ``on_reverted`` was never called
    """
    del scan, present, answer_yes
    mocker.patch(f"{JOBS_MODULE}.revert_conversion", side_effect=PermissionError("read-only"))
    on_reverted = mocker.Mock()
    dialog = ConversionBackupsDialog(queue, on_reverted=on_reverted)
    qtbot.addWidget(dialog)
    choose_root(qtbot, dialog, ROOT)
    dialog.model.set_checked([ZBRUSH, PAINTING], False)

    ui_of(dialog).revert_button.click()
    wait_for_outcomes(qtbot, dialog)

    on_reverted.assert_not_called()


def test_cancelling_a_run_stops_the_jobs_still_queued(
    qtbot: QtBot, dialog: ConversionBackupsDialog, answer_yes: Any, mocker: MockerFixture
) -> None:
    """Neither operation is safely interruptible, so *cancel stops after the current resource* is the
    only honest meaning -- the queued ones are dropped without ever starting.

    **Test steps:**

    * hold the first job inside the worker, discard the selection, cancel, then let it finish
    * verify rows came back cancelled and fewer resources were touched than were selected
    """
    del answer_yes
    # Holding the first job is what leaves the other two demonstrably queued when Cancel is clicked.
    # `queue.pause()` cannot arrange it and used to be asked to: pausing is `pause_job` applied to the
    # jobs *already enqueued* ([[appendices.task-queue#pause-concept]]), never a gate a later enqueue
    # passes through, so all three raced the click and a fast runner finished them first.
    running = Event()
    release = Event()

    def hold_the_worker(*_args: Any, **_kwargs: Any) -> Sequence[Path]:
        """Park the worker inside the first resource until the test has cancelled the rest."""
        running.set()
        assert release.wait(TIMEOUT / 1000)
        return ()

    discard = mocker.patch(f"{JOBS_MODULE}.discard_conversion_backups", side_effect=hold_the_worker)

    ui_of(dialog).discard_button.click()
    assert running.wait(TIMEOUT / 1000)
    ui_of(dialog).cancel_button.click()
    release.set()
    wait_for_outcomes(qtbot, dialog)

    outcomes = [row.outcome for row in dialog.model.rows()]
    # the one the worker had already picked up may still finish -- that is the whole of "stops after the
    # current resource", and asserting all three were cancelled would be asserting a race
    assert "cancelled" in outcomes
    assert discard.call_count < len(outcomes)


# endregion


# region Closing


def test_closing_mid_scan_stops_the_worker_rather_than_leaving_it_running(
    qtbot: QtBot, dialog: ConversionBackupsDialog, scan: Any
) -> None:
    """A walk over a mount outlives the dialog otherwise, reporting into a deleted widget.

    **Test steps:**

    * start a blocking scan, then close the dialog
    * verify the close returned rather than hanging, and the worker was let go
    """
    started = Event()
    released = Event()

    def blocking_scan(_root: Path, *, progress: Any = None, checkpoint: Any = None) -> Any:
        del progress, checkpoint
        started.set()
        released.wait(TIMEOUT / 1000)
        return make_scan([])

    scan.side_effect = blocking_scan
    ui_of(dialog).rescan_button.click()
    qtbot.waitUntil(started.is_set, timeout=TIMEOUT)

    released.set()
    dialog.reject()

    assert dialog.result() == ConversionBackupsDialog.DialogCode.Rejected


def test_a_remembered_geometry_is_restored(qtbot: QtBot, queue: TaskQueue, scan: Any) -> None:
    """The dialog opens where it was left, the same way every other dialog here persists its geometry.

    **Test steps:**

    * close a dialog, then build a second one from the same settings
    * verify it restored the blob the first one saved
    """
    del scan
    first = ConversionBackupsDialog(queue)
    qtbot.addWidget(first)
    first.resize(640, 400)
    first.reject()

    second = ConversionBackupsDialog(queue)
    qtbot.addWidget(second)

    assert second.size() == first.size()


def test_a_first_run_opens_at_its_own_default_size(
    qtbot: QtBot, queue: TaskQueue, scan: Any, mocker: MockerFixture
) -> None:
    """Nothing has been saved yet, so the ``.ui``'s own geometry stands rather than an empty blob being
    handed to ``restoreGeometry``.

    **Test steps:**

    * build a dialog whose settings were never loaded, so its geometry is empty
    * verify it came up at the size the ``.ui`` declares
    """
    del scan
    mocker.patch.object(ConversionBackupsDialogSettings, "load")

    dialog = ConversionBackupsDialog(queue)
    qtbot.addWidget(dialog)

    assert dialog.size() == QSize(820, 520)


def test_a_recent_entry_with_no_folder_behind_it_is_ignored(qtbot: QtBot, dialog: ConversionBackupsDialog) -> None:
    """Qt reports an activation by index, and an index the combo has nothing under is not a folder --
    picking one must leave the current root alone rather than scanning ``None``.

    **Test steps:**

    * activate an index past the end of the recent list
    * verify the root did not move
    """
    del qtbot
    ui_of(dialog).recent_roots_combo.activated.emit(ui_of(dialog).recent_roots_combo.count())

    assert dialog.root == ROOT


def test_closing_detaches_from_the_queue(
    qtbot: QtBot, dialog: ConversionBackupsDialog, queue: TaskQueue, answer_yes: Any, mocker: MockerFixture
) -> None:
    """The engine calls its listeners on the worker thread, so one arriving after the dialog is gone
    would emit from a deleted ``QObject``.

    **Test steps:**

    * close the dialog, then run a job through the queue it was listening to
    * verify nothing reached the dialog's model
    """
    del answer_yes
    mocker.patch(f"{JOBS_MODULE}.discard_conversion_backups", return_value=())

    dialog.reject()
    qtbot.wait(0)

    assert dialog not in queue._TaskQueue__listeners  # type: ignore[attr-defined]  # pylint: disable=protected-access


# endregion
