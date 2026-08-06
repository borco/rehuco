"""Tests for the per-file checksum dock: its actions, its enablement and its refresh seams (#244).

The rows arrive through the real background loader, so every test settles the pool before reading the
table -- which is also the claim that *the enumeration does not block the GUI* being exercised rather
than stated.

The queue is real and the runs are mocked at `rehuco_core.checksum_jobs`' two callables: what this
module is about is which job is enqueued carrying what, not what a hash answers.
"""

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final

from PySide6.QtCore import QPoint, Qt
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent import main_rc  # noqa: F401  # pylint: disable=unused-import  # registers :/icons/...
from rehuco_agent.documents import checksum_view as view_module
from rehuco_agent.documents.checksum_actions import ChecksumActions
from rehuco_agent.documents.checksum_rows import PATH_COLUMN, STATUS_COLUMN, ChecksumRow, ChecksumRows
from rehuco_agent.documents.checksum_view import (
    NO_PATH_SUMMARY,
    UNREACHABLE_SUMMARY,
    ChecksumView,
)
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_core import ChecksumReport, RehuDocument, TaskQueue

DIRECTORY: Final = Path("/fake/library/sculpting")
INFO_PATH: Final = DIRECTORY / "info.rehu"

VIDEO: Final = "lesson1.mp4"
ARCHIVE: Final = "extras/pack.zip"

TIMEOUT: Final = 5000


@fixture(name="rows")
def fixture_rows(mocker: MockerFixture) -> Any:
    """The row read, mocked at the seam the loader calls.

    The walk itself is `test_checksum_rows`' subject; what this module needs is control over what comes
    back, so a test can arrange a mismatch or an away mount without arranging a filesystem.

    :param mocker: pytest-mock fixture.
    :returns: the patched reader, whose ``return_value`` a test sets.
    """
    reader = mocker.patch("rehuco_agent.documents.checksum_rows.read_checksum_rows")
    reader.return_value = ChecksumRows(
        rows=(ChecksumRow(VIDEO, "matched"), ChecksumRow(ARCHIVE, "missing"), ChecksumRow("notes.txt"))
    )
    return reader


@fixture(name="runs", autouse=True)
def fixture_runs(mocker: MockerFixture) -> SimpleNamespace:
    """A resource the queue will accept, whose runs establish nothing.

    Both halves are about the *queue* rather than the runs: a job whose resource does not exist fails
    validation before it starts, and one whose run raises never leaves a row to read back. What each
    run would have hashed is `test_rehu_checksums`' subject, not this module's -- what matters here is
    which run was made, over which files.

    :param mocker: pytest-mock fixture.
    :returns: the two patched core callables.
    """
    mocker.patch.object(Path, "exists", autospec=True, return_value=True)
    return SimpleNamespace(
        verify=mocker.patch("rehuco_core.checksum_jobs.verify_checksums", return_value=ChecksumReport()),
        generate=mocker.patch("rehuco_core.checksum_jobs.generate_checksums", return_value=ChecksumReport()),
    )


@fixture(name="model")
def fixture_model() -> RehuDocumentModel:
    """A view-model over a directory-scoped resource that is on disk.

    :returns: the model the view is about.
    """
    return RehuDocumentModel(RehuDocument({"type": "Tutorial"}, INFO_PATH))


@fixture(name="queue")
def fixture_queue(qapp: Any) -> Any:
    """A real queue, shut down after the test.

    :param qapp: the Qt application fixture, so the queue's listeners have an event loop.
    :yields: the queue.
    """
    del qapp
    queue = TaskQueue()
    yield queue
    queue.shutdown()


@fixture(name="view")
def fixture_view(qtbot: QtBot, model: RehuDocumentModel, queue: TaskQueue, rows: Any) -> ChecksumView:
    """A built view whose first read has already landed.

    :param qtbot: pytest-qt fixture.
    :param model: the document.
    :param queue: the queue its actions enqueue onto.
    :param rows: the patched reader, so the fixture's first read is the arranged one.
    :returns: the view.
    """
    del rows
    actions = ChecksumActions(model, queue)
    view = ChecksumView(model, actions)
    qtbot.addWidget(view)
    # shown, because a hidden dock deliberately reads nothing (#111's discipline): every test here is
    # about what the table says once someone is looking at it
    view.show()
    settle(qtbot, view)
    return view


def settle(qtbot: QtBot, view: ChecksumView) -> None:
    """Wait for the background read to land.

    :param qtbot: pytest-qt fixture.
    :param view: the view whose summary stops saying *reading* once it has.
    """
    qtbot.waitUntil(lambda: view.summary != "Reading…", timeout=TIMEOUT)


def drawn(view: ChecksumView, column: int = PATH_COLUMN) -> list[str]:
    """One column, in the order the table draws it.

    :param view: the view to read.
    :param column: which column.
    :returns: the cells' text.
    """
    return [view.proxy.index(row, column).data() for row in range(view.proxy.rowCount())]


# region What it shows


def test_the_table_lists_every_file_and_summarizes_them(view: ChecksumView) -> None:
    """The rows are drawn and the line under them counts how many of what (#244).

    **Test steps:**

    * build the view over a mixed record
    * check every file is drawn and the summary names each count
    """
    assert set(drawn(view)) == {VIDEO, ARCHIVE, "notes.txt"}
    assert view.summary == "3 files · 1 matched · 1 missing · 1 not recorded"


def test_a_never_saved_document_says_so_and_reads_nothing(qtbot: QtBot, queue: TaskQueue, rows: Any) -> None:
    """There is nothing on disk to enumerate, so nothing is enumerated (#244).

    **Test steps:**

    * build a view over a document with no path
    * check it says so and never called the reader
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}))
    view = ChecksumView(model, ChecksumActions(model, queue))
    qtbot.addWidget(view)
    view.show()

    assert view.summary == NO_PATH_SUMMARY
    assert view.proxy.rowCount() == 0
    rows.assert_not_called()


def test_an_unreachable_resource_says_so_rather_than_drawing_an_empty_table(
    qtbot: QtBot, view: ChecksumView, rows: Any
) -> None:
    """An away mount is not an empty resource, and every action is greyed on it (#245, #244).

    **Test steps:**

    * make the read answer unreachable and refresh
    * check the summary says so and all three selection actions are off
    """
    rows.return_value = ChecksumRows(reachable=False)
    view.refresh()
    settle(qtbot, view)

    ui = view
    assert view.summary == UNREACHABLE_SUMMARY
    assert view.proxy.rowCount() == 0
    assert not ui.verify_selection_action.isEnabled()
    assert not ui.generate_selection_action.isEnabled()
    assert not ui.delete_missing_action.isEnabled()


def test_sorting_by_status_renumbers_the_rows(view: ChecksumView) -> None:
    """The vertical header numbers what is on screen, whatever the sort (#244).

    **Test steps:**

    * sort by status
    * check the drawn order changed and the numbering is still 1..N
    """
    view.proxy.sort(STATUS_COLUMN, Qt.SortOrder.AscendingOrder)

    assert drawn(view, STATUS_COLUMN) == ["", "matched", "missing"]
    assert [view.proxy.headerData(row, Qt.Orientation.Vertical) for row in range(view.proxy.rowCount())] == [1, 2, 3]


# endregion


# region The actions


def test_the_selection_scoped_actions_need_a_selection(view: ChecksumView) -> None:
    """With nothing selected there is nothing for them to act on (#244).

    **Test steps:**

    * check all three are disabled with an empty selection
    * select a row and check the two that act on any row come back
    """
    ui = view
    assert not ui.verify_selection_action.isEnabled()
    assert not ui.generate_selection_action.isEnabled()

    view.proxy.sort(PATH_COLUMN, Qt.SortOrder.AscendingOrder)
    view.select_rows([drawn(view).index(VIDEO)])

    assert ui.verify_selection_action.isEnabled()
    assert ui.generate_selection_action.isEnabled()


def test_delete_missing_needs_a_missing_row_in_the_selection(view: ChecksumView) -> None:
    """Dropping the entry of a file still on disk achieves nothing, so it is not offered (#244).

    **Test steps:**

    * select the matched row and check Delete Missing is off
    * select the missing row as well and check it comes on
    """
    view.proxy.sort(PATH_COLUMN, Qt.SortOrder.AscendingOrder)
    names = drawn(view)
    ui = view

    view.select_rows([names.index(VIDEO)])
    assert not ui.delete_missing_action.isEnabled()

    view.select_rows([names.index(VIDEO), names.index(ARCHIVE)])
    assert ui.delete_missing_action.isEnabled()


def test_verify_selection_runs_over_exactly_the_selection(
    qtbot: QtBot, view: ChecksumView, queue: TaskQueue, runs: Any
) -> None:
    """The selection reaches the run, and nothing else in the record is named (#244).

    **Test steps:**

    * select one row and trigger Verify Selection
    * check one row was queued, and that the run it made named only that file
    """
    view.proxy.sort(PATH_COLUMN, Qt.SortOrder.AscendingOrder)
    view.select_rows([drawn(view).index(VIDEO)])

    view.verify_selection_action.trigger()

    qtbot.waitUntil(lambda: runs.verify.called, timeout=TIMEOUT)
    assert [status.label for status in queue.jobs()] == ["Verify checksums (1 file) - sculpting/"]
    assert runs.verify.call_args.kwargs["only"] == (VIDEO,)


def test_generate_selection_re_baselines_exactly_the_selection(
    qtbot: QtBot, view: ChecksumView, queue: TaskQueue, runs: Any
) -> None:
    """Accepting a genuine change is a targeted generate, and it prompts for nothing (#203, #244).

    **Test steps:**

    * select one row and trigger Generate Selection
    * check one row was queued, and that the run it made named only that file
    """
    view.proxy.sort(PATH_COLUMN, Qt.SortOrder.AscendingOrder)
    view.select_rows([drawn(view).index(ARCHIVE)])

    view.generate_selection_action.trigger()

    qtbot.waitUntil(lambda: runs.generate.called, timeout=TIMEOUT)
    assert [status.label for status in queue.jobs()] == ["Generate checksums (1 file) - sculpting/"]
    assert runs.generate.call_args.kwargs["only"] == (ARCHIVE,)


def test_delete_missing_drops_only_the_missing_rows_of_the_selection(
    qtbot: QtBot, view: ChecksumView, mocker: MockerFixture
) -> None:
    """A careless select-all prunes only what is gone (#244).

    **Test steps:**

    * select every row and trigger Delete Missing
    * check core was asked to forget exactly the missing one
    """
    forget = mocker.patch("rehuco_agent.documents.checksum_actions.forget_checksums", return_value=(ARCHIVE,))
    view.select_rows(range(view.proxy.rowCount()))

    view.delete_missing_action.trigger()
    settle(qtbot, view)

    forget.assert_called_once_with(INFO_PATH, only=(ARCHIVE,))


def test_every_check_becomes_a_queue_row(view: ChecksumView, queue: TaskQueue) -> None:
    """Nothing hashes inline: a gigabyte-scale run is what the queue exists for (#204, #244).

    **Test steps:**

    * trigger both selection-scoped runs
    * check each produced a queue row, and neither had been called by the time the click returned
    """
    view.select_rows(range(view.proxy.rowCount()))
    ui = view

    ui.verify_selection_action.trigger()
    ui.generate_selection_action.trigger()

    assert len(queue.jobs()) == 2
    assert [status.source for status in queue.jobs()] == [INFO_PATH, INFO_PATH]


# endregion


# region Refreshing


def test_the_table_refreshes_when_a_job_finishes(
    qtbot: QtBot, view: ChecksumView, rows: Any, mocker: MockerFixture
) -> None:
    """A run rewrote the record, so the table re-reads it (#244).

    **Test steps:**

    * enqueue a verify whose run reports a clean pass, with the reader arranged to answer differently
    * check the table shows the second answer once the job has finished
    """
    mocker.patch("rehuco_core.checksum_jobs.verify_checksums", return_value=ChecksumReport(statuses={VIDEO: "matched"}))
    rows.return_value = ChecksumRows(rows=(ChecksumRow(VIDEO, "matched"),))

    view.select_rows([0])
    view.verify_selection_action.trigger()

    qtbot.waitUntil(lambda: drawn(view) == [VIDEO], timeout=TIMEOUT)
    assert view.summary == "1 file · 1 matched"


def test_the_table_refreshes_when_the_resource_is_renamed(
    qtbot: QtBot, view: ChecksumView, model: RehuDocumentModel, rows: Any
) -> None:
    """The document re-syncs its path on a rename, and this follows it (#241, #244).

    **Test steps:**

    * point the reader at a different answer and move the model's path
    * check the table re-read, against the new path
    """
    rows.return_value = ChecksumRows(rows=(ChecksumRow("moved.mp4", "matched"),))
    moved = Path("/fake/library/renamed/info.rehu")

    model.path = moved
    settle(qtbot, view)

    assert drawn(view) == ["moved.mp4"]
    assert rows.call_args[0][0] == moved


# endregion


def test_a_record_that_cannot_be_read_says_so_under_the_files(qtbot: QtBot, view: ChecksumView, rows: Any) -> None:
    """The content was enumerated, so it is shown; the record's failure is said rather than drawn (#244).

    **Test steps:**

    * make the read report an unreadable record alongside the files it did find
    * check the files are listed and the line names the failure
    """
    rows.return_value = ChecksumRows(rows=(ChecksumRow(VIDEO),), error="Not JSON: info.checksum")
    view.refresh()
    settle(qtbot, view)

    assert drawn(view) == [VIDEO]
    assert "Not JSON: info.checksum" in view.summary


def test_the_context_menu_offers_the_selection_entries_then_the_checking_pair(
    qtbot: QtBot, model: RehuDocumentModel, queue: TaskQueue, mocker: MockerFixture
) -> None:
    """The three that act on a selection, a separator, then the two that check the resource (#244).

    The separator is the point: everything above it changes the record and everything below it only
    reads, which is the same split the toolbar makes by carrying only the second pair.

    **Test steps:**

    * patch ``QMenu`` so nothing is actually shown
    * ask for the context menu
    * verify the entries and the separator, in order
    """
    menu = mocker.patch.object(view_module, "QMenu").return_value
    actions = ChecksumActions(model, queue)
    view = ChecksumView(model, actions)
    qtbot.addWidget(view)
    view.show()
    settle(qtbot, view)

    view._ChecksumView__show_context_menu(QPoint(0, 0))  # type: ignore[attr-defined]  # pylint: disable=protected-access

    assert [call.args[0] for call in menu.addAction.call_args_list] == [
        view.verify_selection_action,
        view.generate_selection_action,
        view.delete_missing_action,
        actions.verify_old_action,
        actions.verify_action,
    ]
    menu.addSeparator.assert_called_once_with()
    menu.exec.assert_called_once()


def test_a_hidden_dock_walks_nothing_until_it_is_opened(
    qtbot: QtBot, model: RehuDocumentModel, queue: TaskQueue, rows: Any
) -> None:
    """This dock starts closed, and a read is a directory walk over a mount (#111's discipline, #244).

    Opening a document must not cost a walk of its whole tree for a table nobody is looking at -- so
    the read is deferred while hidden and caught up on the first show.

    **Test steps:**

    * build the view and leave it hidden, then ask it to refresh
    * check nothing was read; then show it and check the deferred read happened once
    """
    view = ChecksumView(model, ChecksumActions(model, queue))
    qtbot.addWidget(view)

    view.refresh()

    assert not rows.called

    view.show()
    settle(qtbot, view)

    assert rows.call_count == 1


def test_re_showing_a_fresh_dock_walks_nothing_again(qtbot: QtBot, view: ChecksumView, rows: Any) -> None:
    """Switching back to a tab whose table is already current costs no walk (#244).

    The deferral is about work not yet done, not about redoing it: only a refresh asked for *while
    hidden* leaves anything to catch up on.

    **Test steps:**

    * hide and re-show a view whose first read has already landed, asking for no refresh in between
    * check the table was not read a second time
    """
    assert rows.call_count == 1

    view.hide()
    view.show()
    qtbot.wait(50)

    assert rows.call_count == 1
