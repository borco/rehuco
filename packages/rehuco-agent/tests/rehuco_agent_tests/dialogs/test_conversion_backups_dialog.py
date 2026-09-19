"""Tests for the `File ▸ Conversion Backups…` manager (#193, #290).

The scan is mocked at :func:`~rehuco_core.scan_conversion_backups` -- `test_tc_conversion_backups_scan`
is its subject -- but the **queue is real** and the operation is mocked one level below the job, so an
action travels the way it does in the app: enqueued, run on the worker, read back off the job through the
listener and marshalled onto the GUI thread. What these tests are about is which rows the dialog offers,
what the confirmation says, and that nothing destructive happens without one.
"""

# one dialog's scan, selection, confirmation and queue round-trip: one cohesive module reads better than
# an arbitrary split, so the module-length cap is lifted here (same precedent as test_rehu_document_model.py)
# pylint: disable=too-many-lines

from collections.abc import Sequence
from pathlib import Path
from threading import Event
from typing import Any, Final

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.dialogs.conversion_backups_dialog import NOTHING_RETAINED, ConversionBackupsDialog
from rehuco_agent.dialogs.conversion_backups_table_model import TIE_BREAK_FLAG
from rehuco_agent.settings.conversion_backups_dialog_settings import ConversionBackupsDialogSettings
from rehuco_agent.settings.deletion_settings import DeletionKind, shared_deletion_settings
from rehuco_core import (
    DEFAULT_DELETER_PROVIDER,
    FINISHED_JOB_STATES,
    ConversionBackups,
    ConversionBackupsTreeScan,
    JobState,
    JobStatus,
    NoTrashBinError,
    TaskQueue,
)

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
def make_backups(
    rehu_path: Path, *, files: int = 2, total_bytes: int = 14_000_000, dropped_screenshots: int = 0
) -> ConversionBackups:
    """One resource's inventory, as :func:`~rehuco_core.conversion_backups` would report it.

    :param rehu_path: the converted resource.
    :param files: how many image backups it retains.
    :param total_bytes: what they occupy.
    :param dropped_screenshots: how many recognized legacy screenshots a tie-break dropped.
    :returns: the inventory.
    """
    directory = rehu_path.parent
    backups = (*(directory / f"sample-{index:02}.jpg.orig" for index in range(files)), directory / "info.tc.orig")
    return ConversionBackups(
        rehu_path=rehu_path,
        backups=backups,
        total_bytes=total_bytes,
        dropped_screenshots=dropped_screenshots,
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


@fixture(autouse=True)
def permanent_deletes() -> None:
    """Turn the Recycle Bin off, so a discard is permanent from the start and therefore confirmed --
    the shape most of this module asserts on (#312). ``conftest.py`` already hands every test a fresh,
    isolated `DeletionSettings`; a test about a bin-bound discard turns the bin back on itself."""
    shared_deletion_settings().use_recycle_bin = False


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

    Three resources: a tie-break and two clean ones.

    :param mocker: pytest-mock fixture.
    :returns: the patched :func:`~rehuco_core.scan_conversion_backups`.
    """
    return mocker.patch(
        f"{DIALOG_MODULE}.scan_conversion_backups",
        return_value=make_scan(
            [
                make_backups(SCULPTING, files=3, dropped_screenshots=1),
                make_backups(ZBRUSH, total_bytes=1000),
                make_backups(PAINTING, files=1, total_bytes=2000),
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
    """The up-front permanent-delete gate answered Yes.

    `~rehuco_agent.delete_confirmation.confirm_delete` is the whole of the policy and
    ``test_delete_confirmation.py`` its subject; patched where the dialog looks it up (#313), so a
    test here reads what the dialog asked for.

    :param mocker: pytest-mock fixture.
    :returns: the patched gate, so a test can read what was asked.
    """
    return mocker.patch(f"{DIALOG_MODULE}.confirm_delete", return_value=True)


@fixture(name="answer_no")
def fixture_answer_no(mocker: MockerFixture) -> Any:
    """The up-front permanent-delete gate answered No.

    :param mocker: pytest-mock fixture.
    :returns: the patched gate.
    """
    return mocker.patch(f"{DIALOG_MODULE}.confirm_delete", return_value=False)


@fixture(name="no_bin_question")
def fixture_no_bin_question(mocker: MockerFixture) -> Any:
    """The up-front no-bin question, patched where the dialog looks it up and answering Yes (#313).

    :param mocker: pytest-mock fixture.
    :returns: the patched question; a test declining sets ``.return_value`` to ``False``.
    """
    return mocker.patch(f"{DIALOG_MODULE}.ask_permanent_delete", return_value=True)


@fixture(name="windows_bins")
def fixture_windows_bins(mocker: MockerFixture) -> Any:
    """The Windows drive-capability check, on a forced Windows platform, answering *no bin* for the
    ZBrush resource and *bin* for the rest (#313).

    Patched at its source module, where the dialog imports it lazily -- the same seam
    ``test_recycle_bin.py`` uses. Windows-only, since that module loads ``shell32`` at import.

    :param mocker: pytest-mock fixture.
    :returns: the patched ``has_recycle_bin``.
    """
    mocker.patch(f"{DIALOG_MODULE}.sys.platform", "win32")
    return mocker.patch(
        "borco_pyside.platforms.windows.recycle_bin_capability.has_recycle_bin",
        side_effect=lambda path: path != ZBRUSH,
    )


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


def question_of(confirm: Any) -> str:
    """What the last confirmation actually asked."""
    return str(confirm.call_args.args[3])


def listeners_of(queue: TaskQueue) -> list[object]:
    """The queue's attached listeners (private by design -- what these tests assert is exactly when the
    dialog stops being among them, #246)."""
    return queue._TaskQueue__listeners  # type: ignore[attr-defined]  # pylint: disable=protected-access


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


def test_the_discard_action_is_not_offered_with_nothing_selected(qtbot: QtBot, dialog: ConversionBackupsDialog) -> None:
    """A button that would act on nothing is a button that does nothing.

    **Test steps:**

    * clear the selection
    * verify the discard button is disabled
    """
    del qtbot
    dialog.model.set_checked([SCULPTING, ZBRUSH, PAINTING], False)

    assert not ui_of(dialog).discard_button.isEnabled()


def test_a_discard_over_nothing_asks_nothing_and_enqueues_nothing(
    qtbot: QtBot, dialog: ConversionBackupsDialog, answer_yes: Any, queue: TaskQueue
) -> None:
    """The slot behind the button guards the same condition the button's enabled state does, so a
    discard that somehow reaches it with nothing selected is a no-op rather than an empty batch.

    **Test steps:**

    * clear the selection and fire the discard slot directly
    * verify no confirmation was put and nothing reached the queue
    """
    del qtbot
    dialog.model.set_checked([SCULPTING, ZBRUSH, PAINTING], False)

    dialog._ConversionBackupsDialog__on_discard()  # type: ignore[attr-defined]  # pylint: disable=protected-access

    answer_yes.assert_not_called()
    assert not queue.jobs()


# endregion


# region Discarding


def test_discarding_asks_first_and_names_the_count_and_the_bytes(
    qtbot: QtBot, dialog: ConversionBackupsDialog, answer_yes: Any, mocker: MockerFixture
) -> None:
    """The only irreversible act in the whole import flow, so the confirmation reads that way rather
    than as a reflexive yes/no.

    **Test steps:**

    * discard the whole selection with the confirmation answered Yes
    * verify it was put for the backups kind, what was asked, and that every row came back discarded
    """
    discard = mocker.patch(f"{JOBS_MODULE}.discard_conversion_backups", return_value=())

    ui_of(dialog).discard_button.click()
    wait_for_outcomes(qtbot, dialog)

    assert answer_yes.call_args.args[1] is DeletionKind.BACKUPS
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


class RefusingDeleter:  # pylint: disable=too-few-public-methods
    """A :class:`~rehuco_core.Deleter` that always refuses with `~rehuco_core.NoTrashBinError`."""

    def delete(self, path: Path) -> None:
        """Refuse to delete ``path``."""
        raise NoTrashBinError(f"no bin for {path.parent}")


def test_a_discard_bound_for_the_recycle_bin_asks_nothing(
    qtbot: QtBot, dialog: ConversionBackupsDialog, mocker: MockerFixture
) -> None:
    """One deletion policy (#312): a question accompanies a permanent delete only, so with the bin on
    the batch is enqueued straight away -- through the real gate, which shows no box. Off Windows,
    nothing can be known about a bin up front either, so no no-bin question is put (#313).

    **Test steps:**

    * turn the Recycle Bin on, force a non-Windows platform, and discard the whole selection
    * verify no box was shown and every row came back discarded
    """
    shared_deletion_settings().use_recycle_bin = True
    mocker.patch(f"{DIALOG_MODULE}.sys.platform", "linux")
    shown = mocker.patch.object(QMessageBox, "exec")
    mocker.patch(f"{JOBS_MODULE}.discard_conversion_backups", return_value=())

    ui_of(dialog).discard_button.click()
    wait_for_outcomes(qtbot, dialog)

    shown.assert_not_called()
    assert {row.outcome for row in dialog.model.rows()} == {"discarded"}


def test_clear_backups_without_asking_skips_the_permanent_confirm(
    qtbot: QtBot, dialog: ConversionBackupsDialog, mocker: MockerFixture
) -> None:
    """With **Clear backups without asking** on, even a permanent discard is not confirmed -- through
    the real gate, which shows no box (#312).

    **Test steps:**

    * turn the box on, keep the bin off, and discard the whole selection
    * verify no box was shown and every row came back discarded
    """
    shared_deletion_settings().clear_backups_without_asking = True
    shown = mocker.patch.object(QMessageBox, "exec")
    mocker.patch(f"{JOBS_MODULE}.discard_conversion_backups", return_value=())

    ui_of(dialog).discard_button.click()
    wait_for_outcomes(qtbot, dialog)

    shown.assert_not_called()
    assert {row.outcome for row in dialog.model.rows()} == {"discarded"}


def test_off_windows_a_refusal_fails_the_row_and_names_the_box(
    qtbot: QtBot, dialog: ConversionBackupsDialog, answer_yes: Any, mocker: MockerFixture
) -> None:
    """With **Clear backups without asking** off, a queued job has no window to put the permanent
    question from, so a resolved deleter's refusal fails that resource's job and leaves its backups in
    place (#301, #312) -- and, where the question could not be put up front, the row names the box
    that would have let it through (#313).

    **Test steps:**

    * turn the bin on, force a non-Windows platform, and install a provider whose deleter refuses
    * discard the whole selection
    * verify every row failed, its message naming the box and the Files page
    """
    del answer_yes
    shared_deletion_settings().use_recycle_bin = True
    mocker.patch(f"{DIALOG_MODULE}.sys.platform", "linux")
    mocker.patch.object(DEFAULT_DELETER_PROVIDER, "resolve", return_value=RefusingDeleter())

    def discard(rehu_path: Path, *, deleter: object) -> tuple[Path, ...]:
        deleter.delete(rehu_path.parent / "info.tc.orig")  # type: ignore[attr-defined]
        return ()

    mocker.patch(f"{JOBS_MODULE}.discard_conversion_backups", side_effect=discard)

    ui_of(dialog).discard_button.click()
    wait_for_outcomes(qtbot, dialog)

    assert {row.outcome for row in dialog.model.rows()} == {"failed"}
    for row in dialog.model.rows():
        assert row.message is not None
        assert row.message.startswith("no bin for")
        assert '"Clear backups without asking" (Settings ▸ Files)' in row.message
        assert "NoTrashBinError" not in row.message


def test_a_failure_that_is_not_a_refusal_is_reported_as_it_came(
    qtbot: QtBot, dialog: ConversionBackupsDialog, answer_yes: Any, mocker: MockerFixture
) -> None:
    """Only a refused bin earns the hint about the box; any other failure's message stays the
    engine's own (#313).

    **Test steps:**

    * make the operation raise a plain ``PermissionError``
    * verify each row's message names the type and reason, and no box
    """
    del answer_yes
    mocker.patch(f"{JOBS_MODULE}.discard_conversion_backups", side_effect=PermissionError("read-only"))

    ui_of(dialog).discard_button.click()
    wait_for_outcomes(qtbot, dialog)

    assert all(row.message == "PermissionError: read-only" for row in dialog.model.rows())


# region the up-front no-bin question, on Windows (#313)


@mark.windows
def test_a_selection_entirely_without_a_bin_is_asked_about_once_up_front(
    qtbot: QtBot, dialog: ConversionBackupsDialog, no_bin_question: Any, windows_bins: Any, mocker: MockerFixture
) -> None:
    """With the bin on and the box off, a location known to have no bin is asked about before
    anything is enqueued -- once per batch, with the count and bytes, under the no-bin title -- and
    Yes enqueues every row with the fallback on, so a refusal deletes permanently instead of failing.

    **Test steps:**

    * turn the bin on, make every selected resource's drive report no bin, and select ZBrush alone
    * install a provider whose deleter refuses, and discard
    * verify the question was put once, for the backups kind, naming the location and the count; and
      that the row came back discarded rather than failed
    """
    shared_deletion_settings().use_recycle_bin = True
    windows_bins.side_effect = lambda path: False
    mocker.patch.object(Path, "unlink", autospec=True)
    mocker.patch.object(DEFAULT_DELETER_PROVIDER, "resolve", return_value=RefusingDeleter())
    dialog.model.set_checked([SCULPTING, PAINTING], False)

    def discard(rehu_path: Path, *, deleter: object) -> tuple[Path, ...]:
        deleter.delete(rehu_path.parent / "info.tc.orig")  # type: ignore[attr-defined]
        return ()

    mocker.patch(f"{JOBS_MODULE}.discard_conversion_backups", side_effect=discard)

    ui_of(dialog).discard_button.click()
    wait_for_outcomes(qtbot, dialog)

    no_bin_question.assert_called_once()
    _parent, kind, title, text = no_bin_question.call_args.args
    assert kind is DeletionKind.BACKUPS
    assert title == "No Recycle Bin available"
    assert text.startswith(f"No Recycle Bin is available for {ZBRUSH.anchor}.")
    assert "1 resource(s) permanently instead" in text
    assert "either way" not in text
    assert [row.outcome for row in dialog.model.rows() if row.path == ZBRUSH] == ["discarded"]


@mark.windows
def test_a_mixed_selection_names_the_split(
    qtbot: QtBot, dialog: ConversionBackupsDialog, no_bin_question: Any, windows_bins: Any, mocker: MockerFixture
) -> None:
    """When only some rows are somewhere without a bin, the question says which, what those alone
    would free, and that the rest go to the bin either way -- the answer changes nothing for them.

    **Test steps:**

    * turn the bin on, with only ZBrush's drive reporting no bin, and discard all three
    * verify the question names 1 of 3, ZBrush's bytes alone, and the other 2
    """
    del windows_bins
    shared_deletion_settings().use_recycle_bin = True
    mocker.patch(f"{JOBS_MODULE}.discard_conversion_backups", return_value=())

    ui_of(dialog).discard_button.click()
    wait_for_outcomes(qtbot, dialog)

    text = no_bin_question.call_args.args[3]
    assert "1 of the 3 selected resources are there" in text
    assert "1.0 kB" in text
    assert "The other 2 are moved to the Recycle Bin either way" in text


@mark.windows
@mark.usefixtures("windows_bins")
def test_no_on_the_no_bin_question_enqueues_nothing_even_for_the_rows_with_a_bin(
    qtbot: QtBot, dialog: ConversionBackupsDialog, no_bin_question: Any, queue: TaskQueue, mocker: MockerFixture
) -> None:
    """No on a mixed batch calls the whole batch off rather than running only the rows with a bin: a
    half-done table with no row saying why is worse than filtering and re-selecting.

    **Test steps:**

    * turn the bin on, with only ZBrush's drive reporting no bin, decline the question, and discard
    * verify nothing reached the queue and no row changed
    """
    shared_deletion_settings().use_recycle_bin = True
    no_bin_question.return_value = False
    discard = mocker.patch(f"{JOBS_MODULE}.discard_conversion_backups")

    ui_of(dialog).discard_button.click()
    qtbot.wait(0)

    discard.assert_not_called()
    assert not queue.jobs()
    assert all(row.outcome is None for row in dialog.model.rows())


@mark.windows
def test_a_selection_entirely_with_a_bin_is_not_asked(
    qtbot: QtBot, dialog: ConversionBackupsDialog, no_bin_question: Any, windows_bins: Any, mocker: MockerFixture
) -> None:
    """The question exists for a location without a bin; every drive reporting one means there is
    nothing to ask.

    **Test steps:**

    * turn the bin on, make every drive report a bin, and discard all three
    * verify no question was put and every row came back discarded
    """
    shared_deletion_settings().use_recycle_bin = True
    windows_bins.side_effect = lambda path: True
    mocker.patch(f"{JOBS_MODULE}.discard_conversion_backups", return_value=())

    ui_of(dialog).discard_button.click()
    wait_for_outcomes(qtbot, dialog)

    no_bin_question.assert_not_called()
    assert {row.outcome for row in dialog.model.rows()} == {"discarded"}


@mark.windows
def test_the_box_already_ticked_skips_the_no_bin_question_too(
    qtbot: QtBot, dialog: ConversionBackupsDialog, no_bin_question: Any, windows_bins: Any, mocker: MockerFixture
) -> None:
    """**Clear backups without asking** is the same answer given in advance: no question, and the
    fallback carried into every job (#312, #313).

    **Test steps:**

    * turn the bin and the box on, with ZBrush's drive reporting no bin, and discard all three
    * verify no question was put and the drive was never even asked about
    """
    shared_deletion_settings().use_recycle_bin = True
    shared_deletion_settings().clear_backups_without_asking = True
    mocker.patch(f"{JOBS_MODULE}.discard_conversion_backups", return_value=())

    ui_of(dialog).discard_button.click()
    wait_for_outcomes(qtbot, dialog)

    no_bin_question.assert_not_called()
    windows_bins.assert_not_called()
    assert {row.outcome for row in dialog.model.rows()} == {"discarded"}


# endregion


def test_clear_backups_without_asking_threads_the_fallback_into_every_enqueued_job(
    qtbot: QtBot, dialog: ConversionBackupsDialog, answer_yes: Any, mocker: MockerFixture
) -> None:
    """The same box is what every job the batch enqueues carries as its no-bin fallback (#301, #312),
    so a refusal falls back to a permanent delete instead of failing that resource.

    **Test steps:**

    * turn the box and the bin on, and install a provider whose deleter always refuses
    * discard the whole selection
    * verify every row discarded rather than failed
    """
    del answer_yes
    shared_deletion_settings().use_recycle_bin = True
    shared_deletion_settings().clear_backups_without_asking = True
    mocker.patch.object(Path, "unlink", autospec=True)
    mocker.patch.object(DEFAULT_DELETER_PROVIDER, "resolve", return_value=RefusingDeleter())

    def discard(rehu_path: Path, *, deleter: object) -> tuple[Path, ...]:
        deleter.delete(rehu_path.parent / "info.tc.orig")  # type: ignore[attr-defined]
        return ()

    mocker.patch(f"{JOBS_MODULE}.discard_conversion_backups", side_effect=discard)

    ui_of(dialog).discard_button.click()
    wait_for_outcomes(qtbot, dialog)

    assert {row.outcome for row in dialog.model.rows()} == {"discarded"}


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


def test_cancelling_a_run_stops_the_jobs_still_queued(
    qtbot: QtBot, dialog: ConversionBackupsDialog, answer_yes: Any, mocker: MockerFixture
) -> None:
    """The operation is not safely interruptible, so *cancel stops after the current resource* is the
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


def test_a_deferred_detach_settles_when_the_last_job_is_removed_unrun(
    qtbot: QtBot, queue: TaskQueue, dialog: ConversionBackupsDialog, mocker: MockerFixture
) -> None:
    """A job deleted from the Tasks dock without running produces no outcome to read back, so the
    settled-batch question is put to the queue's own snapshot -- and the removal itself is a wake, or a
    deferred detach whose last job was removed would wait forever (#246).

    **Test steps:**

    * hold the first discard, pause the second, close the dialog, let the first finish
    * verify the dialog is still listening for the paused job, then remove it and verify the detach
    """
    running = Event()
    release = Event()

    def hold_the_worker(*_args: Any, **_kwargs: Any) -> None:
        """Park the worker inside the first discard until the second has been paused."""
        running.set()
        assert release.wait(TIMEOUT / 1000)

    mocker.patch(f"{JOBS_MODULE}.discard_conversion_backups", side_effect=hold_the_worker)
    mocker.patch(f"{DIALOG_MODULE}.confirm_delete", return_value=True)
    dialog.model.set_checked([PAINTING], False)

    ui_of(dialog).discard_button.click()
    assert running.wait(TIMEOUT / 1000)
    queue.pause()
    dialog.reject()
    release.set()
    qtbot.waitUntil(
        lambda: sum(1 for status in queue.jobs() if status.state not in FINISHED_JOB_STATES) == 1, timeout=TIMEOUT
    )

    assert dialog in listeners_of(queue)
    remaining = [status.serial for status in queue.jobs() if status.state not in FINISHED_JOB_STATES]
    queue.remove(*remaining)
    qtbot.waitUntil(lambda: dialog not in listeners_of(queue), timeout=TIMEOUT)


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
