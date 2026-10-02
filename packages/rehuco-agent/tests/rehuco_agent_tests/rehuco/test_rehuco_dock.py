"""Tests for the Root Catalog dock: opening a ``.rehuco``, scanning its roots through the queue, listing and
opening what the cache holds (#377).

No file is ever created: ``Path.read_text`` serves the ``.rehuco``, ``atomic_write_text`` is captured, and
:func:`sqlite3.connect` is patched to hand back shared-cache in-memory databases -- the dock's own connection
and every scan job's, on the worker thread, reach the same one.
"""

# the dock has a broad surface (opening, scanning, editing roots, a read-only mode, layout, the queue listener);
# one cohesive module reads better than an arbitrary split, so the module-length cap is lifted here, as it is for
# test_main_window.py and test_rehu_document_model.py
# pylint: disable=too-many-lines

import json
import logging
import sqlite3
import threading
from collections.abc import Generator
from pathlib import Path
from typing import Any, Final
from unittest.mock import MagicMock
from uuid import uuid4

import cbor2
import PySide6QtAds as QtAds
from borco_pyside.qtads import tab_close_button, tab_maximize_button
from borco_pyside.widgets import MessageBanner, RowBandDelegate
from PySide6.QtCore import QModelIndex, Qt
from pytest import LogCaptureFixture, fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco import RehucoDock
from rehuco_agent.rehuco.catalog_table_model import TITLE_COLUMN
from rehuco_agent.rehuco.rehuco_dock import (
    BROWSER_DOCK_NAME,
    ROOTS_DOCK_NAME,
    STATE_DOCK_MANAGER_KEY,
    STATE_VERSION,
    STATE_VERSION_KEY,
)
from rehuco_core import (
    FINISHED_JOB_STATES,
    CatalogCache,
    CatalogRecord,
    JobControl,
    RecordKind,
    RootScanOutcome,
    RootScanResult,
    TaskJobBase,
    TaskQueue,
)

REHUCO_PATH: Final = Path("/fake/home.rehuco")
OTHER_PATH: Final = Path("/fake/other.rehuco")
REHUCO_ID: Final = "6f1c5e0a-1b2c-4d3e-8f90-a1b2c3d4e5f6"
ROOT_IDS: Final = ("a41b9c3d-0000-4000-8000-000000000001", "a41b9c3d-0000-4000-8000-000000000002")
TUTORIALS: Final = Path("/fake/tutorials")
PACKS: Final = Path("/fake/packs")

GATE_TIMEOUT: Final = 120.0
"""How long a gate job blocks before giving up on being released, in seconds -- a deadlock guard, never a wait
anything is meant to reach, and deliberately far longer than :data:`WAIT_TIMEOUT_MS`."""

WAIT_TIMEOUT_MS: Final = 10_000
"""How long a ``waitUntil`` gives the GUI thread to show an effect -- generous, since the first wait in a Qt
test may be the spin that drains a deferred-deletion backlog."""

real_connect: Final = sqlite3.connect
"""The real :func:`sqlite3.connect`, bound before a test patches the module's."""

HOME: Final = {
    "format_version": 1,
    "id": REHUCO_ID,
    "roots": [
        {"id": ROOT_IDS[0], "path": str(TUTORIALS), "label": "tutorials"},
        {"id": ROOT_IDS[1], "path": str(PACKS), "label": "packs"},
    ],
}


class MemoryDatabase:
    """One named in-memory database, alive for as long as its keeper connection is open."""

    def __init__(self) -> None:
        self.__uri: Final = f"file:rehudb-{uuid4()}?mode=memory&cache=shared"
        self.keeper: Final = self.connect()

    def connect(self, *_args: object, **_kwargs: object) -> sqlite3.Connection:
        """A new connection to this database, as the patched :func:`sqlite3.connect` hands it out."""
        connection = real_connect(self.__uri, uri=True, autocommit=True, check_same_thread=False)
        # a shared-cache memory database takes table locks that fail at once with "table is locked" when
        # the GUI thread reads while a worker writes; the real file runs in WAL, where readers never block a
        # writer. Reading uncommitted is what makes this stand-in behave like that.
        connection.execute("PRAGMA read_uncommitted = 1")
        return connection

    def scalar(self, statement: str) -> Any:
        """The first column of the first row ``statement`` reads, through the keeper."""
        return self.keeper.execute(statement).fetchone()[0]


@fixture(name="database")
def fixture_database(mocker: MockerFixture) -> Generator[MemoryDatabase]:
    """Route every connection the cache opens to one fresh in-memory database, and fake the folder.

    :param mocker: pytest-mock fixture.
    :yields: the database; its keeper is closed when the test ends.
    """
    database = MemoryDatabase()
    mocker.patch("rehuco_core.rehudb.sqlite3.connect", side_effect=database.connect)
    mocker.patch.object(Path, "mkdir", autospec=True)
    mocker.patch("rehuco_agent.rehuco.rehuco_dock.cache_folder", return_value=Path("/fake/cache"))
    yield database
    database.keeper.close()


@fixture(name="served")
def fixture_served(mocker: MockerFixture) -> dict[str, Any]:
    """Serve ``HOME`` as the content of every ``.rehuco`` read; the test may edit what is served.

    :param mocker: pytest-mock fixture.
    :returns: the served document, copied fresh for this test.
    """
    document = json.loads(json.dumps(HOME))
    mocker.patch.object(Path, "read_text", side_effect=lambda *_args, **_kwargs: json.dumps(document))
    return document


@fixture(name="saves")
def fixture_saves(mocker: MockerFixture) -> MagicMock:
    """Capture every write of a ``.rehuco``.

    :param mocker: pytest-mock fixture.
    :returns: the mock standing in for ``atomic_write_text``.
    """
    return mocker.patch("rehuco_core.rehuco_file.atomic_write_text")


@fixture(name="queue")
def fixture_queue() -> Generator[TaskQueue]:
    """A real task queue, shut down when the test ends.

    :yields: the queue.
    """
    queue = TaskQueue()
    yield queue
    queue.shutdown()


class GateJob(TaskJobBase):
    """A job that holds the worker until told to finish, so what is enqueued behind it stays waiting."""

    def __init__(self) -> None:
        super().__init__()
        self.label = "gate"
        self.entered: Final = threading.Event()
        self.__proceed: Final = threading.Event()

    def run(self, control: JobControl) -> None:
        """Signal entry, then wait to be released."""
        del control
        self.entered.set()
        # far longer than any wait a test makes, so the gate never opens by itself under an assertion
        self.__proceed.wait(GATE_TIMEOUT)

    def let_finish(self) -> None:
        """Release the worker."""
        self.__proceed.set()


@fixture(name="held")
def fixture_held(queue: TaskQueue) -> Generator[GateJob]:
    """Hold the queue by occupying its worker, so what a test enqueues behind stays unfinished.

    :param queue: the queue to hold.
    :yields: the gate, already running and released at teardown.
    """
    gate = GateJob()
    queue.enqueue(gate)
    assert gate.entered.wait(WAIT_TIMEOUT_MS / 1000), "the gate job never reached the worker"
    yield gate
    gate.let_finish()


@fixture(name="dock")
def fixture_dock(qtbot: QtBot, queue: TaskQueue, database: MemoryDatabase) -> Generator[RehucoDock]:
    """A dock over the real queue and the in-memory database, detached when the test ends.

    :param qtbot: pytest-qt fixture.
    :param queue: the queue its jobs run on.
    :param database: the cache's database.
    :yields: the dock, with nothing open.
    """
    del database
    dock = RehucoDock(queue)
    qtbot.addWidget(dock)
    yield dock
    dock.detach()


def scan_finding(mocker: MockerFixture, records: dict[Path, tuple[CatalogRecord, ...]]) -> MagicMock:
    """Make every root scan answer the records ``records`` names for its root, without touching a disk.

    :param mocker: pytest-mock fixture.
    :param records: what each root's scan finds.
    :returns: the scan class's mock.
    """
    scan_class = mocker.patch("rehuco_core.rehudb_jobs.CatalogRootScan")

    def build(root: Path, **_kwargs: object) -> MagicMock:
        scan = MagicMock()
        scan.scan.return_value = RootScanResult(root, RootScanOutcome.SCANNED, records.get(root, ()))
        return scan

    scan_class.side_effect = build
    return scan_class


def tutorial_record() -> CatalogRecord:
    """A readable ``.rehu`` record, as a scan of the tutorials root finds it."""
    return CatalogRecord("python/info.rehu", RecordKind.REHU, title="Python", type="tutorial", content_hash="0")


def wait_for_jobs(qtbot: QtBot, queue: TaskQueue) -> None:
    """Wait until every job on the queue has ended."""
    qtbot.waitUntil(
        lambda: all(status.state in FINISHED_JOB_STATES for status in queue.jobs()), timeout=WAIT_TIMEOUT_MS
    )


def shown_labels(dock: RehucoDock) -> list[str]:
    """The labels of the roots the dock lists, in row order."""
    model = dock.roots_model
    return [model.index(row, 0).data() for row in range(model.rowCount())]


def written_roots(saves: MagicMock) -> list[str]:
    """The root labels of the last ``.rehuco`` written."""
    payload = json.loads(saves.call_args[0][1])
    return [root["label"] for root in payload["roots"]]


# region Opening and creating


def test_opening_lists_the_roots_and_reconciles_the_cache(
    dock: RehucoDock, database: MemoryDatabase, served: Any
) -> None:
    """The file's roots are shown and brought into the cache, so a scan has rows to replace.

    **Test steps:**

    * open a two-root catalog over an empty cache
    * verify the path, both root labels in order, and two root rows in the cache
    """
    del served

    assert dock.open_rehuco(REHUCO_PATH)

    assert dock.rehuco_path == REHUCO_PATH
    assert shown_labels(dock) == ["tutorials", "packs"]
    assert database.scalar("SELECT COUNT(*) FROM roots") == 2


def test_opening_announces_the_new_path(qtbot: QtBot, dock: RehucoDock, served: Any) -> None:
    """Whoever shows the open file's name is told when it changes.

    **Test steps:**

    * open a catalog while waiting on the path signal
    * verify it carried the path
    """
    del served

    with qtbot.waitSignal(dock.rehuco_path_changed) as opened:
        dock.open_rehuco(REHUCO_PATH)

    assert opened.args == [REHUCO_PATH]


def test_opening_another_file_replaces_the_open_one(dock: RehucoDock, served: Any) -> None:
    """One ``.rehuco`` is open at a time.

    **Test steps:**

    * open one catalog, then another
    * verify the second is the open one
    """
    del served
    dock.open_rehuco(REHUCO_PATH)

    assert dock.open_rehuco(OTHER_PATH)

    assert dock.rehuco_path == OTHER_PATH


def test_a_missing_file_does_not_open_and_says_why(mocker: MockerFixture, dock: RehucoDock, served: Any) -> None:
    """The error is kept for whoever asked, and the file that was open stays open.

    **Test steps:**

    * open a catalog, then make every read fail and open another
    * verify the open failed, the error names the file, and the first stays open
    """
    del served
    dock.open_rehuco(REHUCO_PATH)
    mocker.patch.object(Path, "read_text", side_effect=FileNotFoundError("gone"))

    assert not dock.open_rehuco(OTHER_PATH)

    assert str(OTHER_PATH) in dock.load_error
    assert dock.rehuco_path == REHUCO_PATH


def test_a_file_that_is_not_a_rehuco_does_not_open(mocker: MockerFixture, dock: RehucoDock) -> None:
    """A parse failure is an error to report, not an exception for the window.

    **Test steps:**

    * serve a JSON list as the file
    * verify nothing opened and the error says why
    """
    mocker.patch.object(Path, "read_text", return_value="[1, 2]")

    assert not dock.open_rehuco(REHUCO_PATH)

    assert dock.rehuco_path is None
    assert "Not a JSON object" in dock.load_error


def test_a_new_rehuco_is_written_and_opened_empty(dock: RehucoDock, saves: MagicMock) -> None:
    """Creating writes the file first, then opens what was written.

    **Test steps:**

    * create a catalog at a new path
    * verify it was written there, is open, lists no roots and can be scanned
    """
    assert dock.new_rehuco(OTHER_PATH)

    saves.assert_called_once()
    assert saves.call_args[0][0] == OTHER_PATH
    assert dock.rehuco_path == OTHER_PATH
    assert dock.roots_model.rowCount() == 0
    assert dock.scan_action.isEnabled()


def test_a_new_rehuco_that_cannot_be_written_is_not_opened(dock: RehucoDock, saves: MagicMock) -> None:
    """A failed write leaves nothing open, and says why.

    **Test steps:**

    * make the write fail and create a catalog
    * verify nothing is open and the error names the cause
    """
    saves.side_effect = PermissionError("read-only folder")

    assert not dock.new_rehuco(OTHER_PATH)

    assert dock.rehuco_path is None
    assert "read-only folder" in dock.load_error


def test_a_new_rehuco_whose_cache_cannot_open_is_never_written(
    mocker: MockerFixture, dock: RehucoDock, saves: MagicMock
) -> None:
    """The cache is opened before the file is written, so a file reported as not created is not on disk either.

    **Test steps:**

    * make the cache refuse to open
    * create a catalog
    * verify it failed, nothing was written, and the reason names the cache
    """
    mocker.patch("rehuco_agent.rehuco.rehuco_dock.CatalogCache.open", side_effect=sqlite3.OperationalError("locked"))

    assert not dock.new_rehuco(OTHER_PATH)

    saves.assert_not_called()
    assert dock.rehuco_path is None
    assert "cache" in dock.load_error and "locked" in dock.load_error


def test_closing_empties_the_dock(qtbot: QtBot, dock: RehucoDock, served: Any) -> None:
    """Nothing of the closed file stays on screen, and the path change is announced as none.

    **Test steps:**

    * open a catalog and close it while waiting on the path signal
    * verify the signal carried ``None``, nothing is open, both tables are empty and Scan is off
    """
    del served
    dock.open_rehuco(REHUCO_PATH)

    with qtbot.waitSignal(dock.rehuco_path_changed) as closed:
        dock.close_rehuco()

    assert closed.args == [None]
    assert dock.rehuco_path is None
    assert dock.roots_model.rowCount() == 0
    assert dock.catalog_model.rowCount() == 0
    assert not dock.scan_action.isEnabled()


def test_closing_with_nothing_open_is_a_no_op(qtbot: QtBot, dock: RehucoDock) -> None:
    """No signal fires for a close that closed nothing.

    **Test steps:**

    * close with nothing open
    * verify no path signal fired
    """
    with qtbot.assertNotEmitted(dock.rehuco_path_changed):
        dock.close_rehuco()


# endregion

# region Scanning and listing


def test_a_scan_enqueues_one_job_per_root(
    mocker: MockerFixture, qtbot: QtBot, dock: RehucoDock, queue: TaskQueue, served: Any
) -> None:
    """Each root is one job, over the root's folder, so each is online or offline on its own.

    **Test steps:**

    * open a two-root catalog and scan
    * verify one job per root, in root order
    """
    del served
    scan_finding(mocker, {})
    dock.open_rehuco(REHUCO_PATH)

    dock.scan_action.trigger()

    assert [status.source for status in queue.jobs()] == [TUTORIALS, PACKS]
    wait_for_jobs(qtbot, queue)


@mark.usefixtures("served")
def test_a_scan_that_is_already_queued_is_not_queued_again(
    mocker: MockerFixture, qtbot: QtBot, dock: RehucoDock, queue: TaskQueue, held: GateJob
) -> None:
    """Scanning twice while the first scans still wait leaves the queue as it was.

    **Test steps:**

    * hold the queue, open a catalog and scan twice
    * verify one job per root, not two
    """
    scan_finding(mocker, {})
    dock.open_rehuco(REHUCO_PATH)

    dock.scan_action.trigger()
    dock.scan_action.trigger()

    assert [status.source for status in queue.jobs()[1:]] == [TUTORIALS, PACKS]
    held.let_finish()
    wait_for_jobs(qtbot, queue)


@mark.usefixtures("served")
def test_another_catalogs_waiting_scan_does_not_refuse_this_ones(
    mocker: MockerFixture, qtbot: QtBot, queue: TaskQueue, held: GateJob, database: MemoryDatabase
) -> None:
    """Two catalogs whose roots share a label and folder each get their own scan: the check is among this
    dock's own jobs, not the whole queue's.

    **Test steps:**

    * hold the queue; scan from one dock, then from a second dock over the same file
    * verify both scans of each root are queued
    """
    del database
    scan_finding(mocker, {})
    first = RehucoDock(queue)
    qtbot.addWidget(first)
    first.open_rehuco(REHUCO_PATH)
    first.scan_action.trigger()
    second = RehucoDock(queue)
    qtbot.addWidget(second)
    second.open_rehuco(REHUCO_PATH)

    second.scan_action.trigger()

    assert [status.source for status in queue.jobs()[1:]] == [TUTORIALS, PACKS, TUTORIALS, PACKS]
    held.let_finish()
    wait_for_jobs(qtbot, queue)
    first.detach()
    second.detach()


@mark.usefixtures("served", "saves")
def test_removing_a_re_added_root_is_queued_again(
    qtbot: QtBot, dock: RehucoDock, queue: TaskQueue, held: GateJob, mocker: MockerFixture
) -> None:
    """A second removal of a root with the same label is its own job: a removal names no folder, so matching
    on label alone would have refused it.

    **Test steps:**

    * hold the queue; remove a root, add the same folder back, remove it again
    * verify two removal jobs wait
    """
    mocker.patch("rehuco_agent.rehuco.rehuco_dock.QFileDialog.getExistingDirectory", return_value=str(TUTORIALS))
    dock.open_rehuco(REHUCO_PATH)
    dock.roots_view.selectRow(0)
    dock.remove_root_action.trigger()
    dock.add_root_action.trigger()
    dock.roots_view.selectRow(1)

    dock.remove_root_action.trigger()

    assert [status.label for status in queue.jobs()[1:]] == ["Remove root - tutorials", "Remove root - tutorials"]
    held.let_finish()
    wait_for_jobs(qtbot, queue)


@mark.usefixtures("served")
def test_the_table_is_read_once_when_the_last_scan_ends(
    mocker: MockerFixture, qtbot: QtBot, dock: RehucoDock, queue: TaskQueue
) -> None:
    """Two roots, two jobs, one re-read: the picture is only complete when the last one ends.

    **Test steps:**

    * spy on the catalog model's ``set_rows``, open and scan a two-root catalog
    * wait for both jobs to end
    * verify the rows were set once for the open and once more for the scan
    """
    scan_finding(mocker, {TUTORIALS: (tutorial_record(),)})
    dock.open_rehuco(REHUCO_PATH)
    set_rows = mocker.spy(dock.catalog_model, "set_rows")

    dock.scan_action.trigger()

    qtbot.waitUntil(lambda: dock.catalog_model.rowCount() == 1, timeout=WAIT_TIMEOUT_MS)
    wait_for_jobs(qtbot, queue)
    qtbot.wait(50)
    assert set_rows.call_count == 1


@mark.usefixtures("served")
def test_reopening_the_open_catalog_keeps_its_running_scans_tracked(
    mocker: MockerFixture, qtbot: QtBot, dock: RehucoDock, queue: TaskQueue, held: GateJob
) -> None:
    """Picking the open file from the recents while its scan waits still refreshes the table when the scan
    ends -- the same cache is shown, so the jobs are still this dock's.

    **Test steps:**

    * hold the queue, open and scan, then open the same file again
    * release the queue
    * verify the scanned rows appear
    """
    scan_finding(mocker, {TUTORIALS: (tutorial_record(),)})
    dock.open_rehuco(REHUCO_PATH)
    dock.scan_action.trigger()

    assert dock.open_rehuco(REHUCO_PATH)
    held.let_finish()

    qtbot.waitUntil(lambda: dock.catalog_model.rowCount() == 1, timeout=WAIT_TIMEOUT_MS)
    wait_for_jobs(qtbot, queue)


@mark.usefixtures("served")
def test_opening_another_catalog_forgets_the_old_ones_scans(
    mocker: MockerFixture, qtbot: QtBot, dock: RehucoDock, queue: TaskQueue, held: GateJob
) -> None:
    """A scan of the previous catalog ends in a cache no longer shown, so it reads nothing back.

    **Test steps:**

    * hold the queue, open and scan, then open a file with another rehuco id
    * release the queue and let the scan end
    * verify the table stays empty
    """
    scan_finding(mocker, {TUTORIALS: (tutorial_record(),)})
    dock.open_rehuco(REHUCO_PATH)
    dock.scan_action.trigger()
    set_rows = mocker.spy(dock.catalog_model, "set_rows")
    mocker.patch.object(Path, "read_text", return_value=json.dumps({**HOME, "id": str(uuid4())}))
    assert dock.open_rehuco(OTHER_PATH)
    assert set_rows.call_count == 1

    held.let_finish()
    wait_for_jobs(qtbot, queue)

    qtbot.wait(50)
    assert set_rows.call_count == 1
    assert dock.catalog_model.rowCount() == 0


def test_what_a_scan_finds_is_listed_once_it_ends(
    mocker: MockerFixture, qtbot: QtBot, dock: RehucoDock, queue: TaskQueue, served: Any
) -> None:
    """The table is read again when a scan job ends, with authors, title, type and a root-qualified path.

    **Test steps:**

    * open a catalog over a scan that finds one record, and scan
    * wait for the row, then verify its four cells
    """
    del served
    scan_finding(mocker, {TUTORIALS: (tutorial_record(),)})
    dock.open_rehuco(REHUCO_PATH)
    assert dock.catalog_model.rowCount() == 0

    dock.scan_action.trigger()

    qtbot.waitUntil(lambda: dock.catalog_model.rowCount() == 1, timeout=WAIT_TIMEOUT_MS)
    wait_for_jobs(qtbot, queue)
    model = dock.catalog_model
    assert [model.index(0, column).data() for column in range(4)] == [
        "",
        "Python",
        "tutorial",
        "tutorials/python/info.rehu",
    ]


def test_a_double_click_opens_the_resource_by_its_absolute_path(
    mocker: MockerFixture, qtbot: QtBot, dock: RehucoDock, queue: TaskQueue, served: Any
) -> None:
    """The row answers where its record lives, which is what the window's ordinary open route takes.

    **Test steps:**

    * scan one record in, then double-click its row
    * verify the open request carried the root's folder joined to the record's path
    """
    del served
    scan_finding(mocker, {TUTORIALS: (tutorial_record(),)})
    dock.open_rehuco(REHUCO_PATH)
    dock.scan_action.trigger()
    qtbot.waitUntil(lambda: dock.catalog_model.rowCount() == 1, timeout=WAIT_TIMEOUT_MS)
    wait_for_jobs(qtbot, queue)

    with qtbot.waitSignal(dock.open_requested) as requested:
        dock.catalog_view.doubleClicked.emit(dock.catalog_model.index(0, 0))

    assert requested.args == [TUTORIALS / "python/info.rehu"]


def test_a_row_whose_root_is_gone_has_no_path(dock: RehucoDock) -> None:
    """Nothing is opened for a double-click on a row the model no longer holds.

    **Test steps:**

    * ask the empty model for row 0's path
    * verify there is none
    """
    assert dock.catalog_model.absolute_path(0) is None


# endregion

# region Editing the roots


def test_adding_a_root_saves_the_file_and_the_cache_follows(
    mocker: MockerFixture, dock: RehucoDock, database: MemoryDatabase, served: Any, saves: MagicMock
) -> None:
    """The edit is on disk before the dock says it happened.

    **Test steps:**

    * mock the folder picker and add a root
    * verify the file was written with three roots, the list shows three, and the cache holds three
    """
    del served
    mocker.patch("rehuco_agent.rehuco.rehuco_dock.QFileDialog.getExistingDirectory", return_value="/fake/refs")
    dock.open_rehuco(REHUCO_PATH)

    dock.add_root_action.trigger()

    assert written_roots(saves) == ["tutorials", "packs", "refs"]
    assert dock.roots_model.rowCount() == 3
    assert database.scalar("SELECT COUNT(*) FROM roots") == 3


def test_cancelling_the_folder_picker_adds_nothing(
    mocker: MockerFixture, dock: RehucoDock, served: Any, saves: MagicMock
) -> None:
    """No folder chosen, no edit and no write.

    **Test steps:**

    * cancel the folder picker
    * verify nothing was written and the list is unchanged
    """
    del served
    mocker.patch("rehuco_agent.rehuco.rehuco_dock.QFileDialog.getExistingDirectory", return_value="")
    dock.open_rehuco(REHUCO_PATH)

    dock.add_root_action.trigger()

    saves.assert_not_called()
    assert dock.roots_model.rowCount() == 2


def test_adding_a_folder_that_is_already_a_root_warns_and_changes_nothing(
    mocker: MockerFixture, dock: RehucoDock, served: Any, saves: MagicMock
) -> None:
    """The file's own refusal reaches the person, and nothing is written.

    **Test steps:**

    * pick a folder that is already a root
    * verify a warning was shown, nothing was written and the list is unchanged
    """
    del served
    mocker.patch("rehuco_agent.rehuco.rehuco_dock.QFileDialog.getExistingDirectory", return_value=str(PACKS))
    warning = mocker.patch("rehuco_agent.rehuco.rehuco_dock.QMessageBox.warning")
    dock.open_rehuco(REHUCO_PATH)

    dock.add_root_action.trigger()

    warning.assert_called_once()
    saves.assert_not_called()
    assert dock.roots_model.rowCount() == 2


def test_a_failed_save_drops_the_edit_from_the_screen_too(
    mocker: MockerFixture, dock: RehucoDock, served: Any, saves: MagicMock
) -> None:
    """The file is read back, so what is shown is what is on disk.

    **Test steps:**

    * add a root while the write fails
    * verify a warning was shown and the list is back to two roots
    """
    del served
    mocker.patch("rehuco_agent.rehuco.rehuco_dock.QFileDialog.getExistingDirectory", return_value="/fake/refs")
    warning = mocker.patch("rehuco_agent.rehuco.rehuco_dock.QMessageBox.warning")
    saves.side_effect = PermissionError("read-only folder")
    dock.open_rehuco(REHUCO_PATH)

    dock.add_root_action.trigger()

    warning.assert_called_once()
    assert dock.roots_model.rowCount() == 2


def test_a_failed_save_that_cannot_be_read_back_closes_the_file(
    mocker: MockerFixture, dock: RehucoDock, served: Any, saves: MagicMock
) -> None:
    """With neither the edit nor the disk to trust, nothing stays open.

    **Test steps:**

    * add a root while the write fails and the file can no longer be read
    * verify nothing is open
    """
    del served
    mocker.patch("rehuco_agent.rehuco.rehuco_dock.QFileDialog.getExistingDirectory", return_value="/fake/refs")
    mocker.patch("rehuco_agent.rehuco.rehuco_dock.QMessageBox.warning")
    saves.side_effect = PermissionError("read-only folder")
    dock.open_rehuco(REHUCO_PATH)
    mocker.patch.object(Path, "read_text", side_effect=FileNotFoundError("gone"))

    dock.add_root_action.trigger()

    assert dock.rehuco_path is None


@mark.usefixtures("served")
def test_removing_a_root_saves_the_file_and_queues_the_removal(
    qtbot: QtBot, dock: RehucoDock, queue: TaskQueue, database: MemoryDatabase, saves: MagicMock
) -> None:
    """The file loses the root at once; its rows leave the cache on the worker.

    **Test steps:**

    * select the first root and remove it
    * verify the file was written without it, the list shrank, a removal job ran, and the cache lost the root
    """
    dock.open_rehuco(REHUCO_PATH)
    assert not dock.remove_root_action.isEnabled()
    dock.roots_view.selectRow(0)
    assert dock.remove_root_action.isEnabled()

    dock.remove_root_action.trigger()

    assert written_roots(saves) == ["packs"]
    assert dock.roots_model.rowCount() == 1
    assert [status.label for status in queue.jobs()] == ["Remove root - tutorials"]
    wait_for_jobs(qtbot, queue)
    assert database.scalar("SELECT COUNT(*) FROM roots") == 1


@mark.usefixtures("served", "saves")
def test_a_removed_roots_rows_leave_the_table_at_once(
    mocker: MockerFixture, qtbot: QtBot, dock: RehucoDock, queue: TaskQueue
) -> None:
    """The rows stay in the cache until the removal job has run, but are not shown meanwhile.

    **Test steps:**

    * scan a record in, then remove its root
    * verify the table is empty before the removal job has run
    """
    scan_finding(mocker, {TUTORIALS: (tutorial_record(),)})
    dock.open_rehuco(REHUCO_PATH)
    dock.scan_action.trigger()
    qtbot.waitUntil(lambda: dock.catalog_model.rowCount() == 1, timeout=WAIT_TIMEOUT_MS)
    wait_for_jobs(qtbot, queue)
    dock.roots_view.selectRow(0)

    dock.remove_root_action.trigger()

    assert dock.catalog_model.rowCount() == 0
    wait_for_jobs(qtbot, queue)


# endregion

# region A file newer than this build


def test_a_newer_file_opens_read_only_with_a_banner(dock: RehucoDock, served: Any) -> None:
    """Every edit of the roots is off and the reason is shown; scanning writes only the cache, so stays on.

    **Test steps:**

    * serve a file stamped with a newer format version
    * verify it opened, the banner shows, Add and Remove are off, and Scan is on
    """
    served["format_version"] = 99

    assert dock.open_rehuco(REHUCO_PATH)

    banner = dock.findChild(MessageBanner)
    assert banner is not None
    assert not banner.isHidden()
    assert not dock.add_root_action.isEnabled()
    dock.roots_view.selectRow(0)
    assert not dock.remove_root_action.isEnabled()
    assert dock.scan_action.isEnabled()


def test_an_editable_file_shows_no_banner(dock: RehucoDock, served: Any) -> None:
    """Nothing is said about a file nothing is wrong with.

    **Test steps:**

    * open an ordinary file
    * verify the banner is hidden
    """
    del served

    dock.open_rehuco(REHUCO_PATH)

    banner = dock.findChild(MessageBanner)
    assert banner is not None
    assert banner.isHidden()


# endregion

# region Layout


def test_the_sub_dock_tabs_keep_their_buttons_small_before_the_dock_is_ever_shown(
    qtbot: QtBot, dock: RehucoDock
) -> None:
    """Built inside a closed outer dock, the sub-docks' tabs have never been laid out, and their buttons used to be
    fixed at the tab's 480 px default -- each tab a 600 px box, the tab strip half the window (#377).

    **Test steps:**

    * build the dock without showing it
    * wait for both sub-docks' maximize buttons to appear
    * verify neither they nor the close buttons are taller than a couple of text lines
    """
    manager = dock.findChild(QtAds.CDockManager)
    assert manager is not None
    for name in (ROOTS_DOCK_NAME, BROWSER_DOCK_NAME):
        sub_dock = manager.findDockWidget(name)
        assert sub_dock is not None
        qtbot.waitUntil(lambda sub_dock=sub_dock: tab_maximize_button(sub_dock) is not None, timeout=WAIT_TIMEOUT_MS)
        maximize = tab_maximize_button(sub_dock)
        close = tab_close_button(sub_dock)
        assert maximize is not None
        assert close is not None
        limit = 2 * maximize.fontMetrics().height()
        qtbot.waitUntil(lambda close=close: close.minimumHeight() == close.maximumHeight(), timeout=WAIT_TIMEOUT_MS)
        assert maximize.height() <= limit
        assert close.height() <= limit


def test_both_tables_paint_rows_as_bands_with_no_grid(dock: RehucoDock) -> None:
    """The roots and the browser look like every other table in the app: one band per selected row, no grid.

    **Test steps:**

    * read both views' delegate, grid and word wrap
    * verify the row band delegate, no grid, no wrapping
    """
    for view in (dock.roots_view, dock.catalog_view):
        assert isinstance(view.itemDelegate(), RowBandDelegate)
        assert not view.showGrid()
        assert not view.wordWrap()


def test_the_browser_starts_unsorted_but_sortable(dock: RehucoDock) -> None:
    """No arrow on a column until one is clicked, because the rows start in the cache's order.

    **Test steps:**

    * read the browser's sorting switch and sort indicator
    * verify sorting is on and no column is marked
    """
    assert dock.catalog_view.isSortingEnabled()
    assert dock.catalog_view.horizontalHeader().sortIndicatorSection() == -1


@mark.usefixtures("database")
def test_column_widths_and_the_sort_survive_a_layout_round_trip(
    mocker: MockerFixture, qtbot: QtBot, queue: TaskQueue
) -> None:
    """What a reader set on the tables comes back on the next start: widths, and the browser's sort.

    **Test steps:**

    * widen a column on each table and sort the browser by title, descending, then save
    * restore into a fresh dock
    * verify both widths and the sort indicator, and that the model sorts as the header says
    """
    first = RehucoDock(queue)
    qtbot.addWidget(first)
    first.roots_view.horizontalHeader().resizeSection(0, 211)
    first.catalog_view.horizontalHeader().resizeSection(0, 233)
    first.catalog_view.sortByColumn(TITLE_COLUMN, Qt.SortOrder.DescendingOrder)
    saved = first.save_state()
    first.detach()

    second = RehucoDock(queue)
    qtbot.addWidget(second)
    sort = mocker.spy(second.catalog_model, "sort")

    assert second.restore_state(saved)

    header = second.catalog_view.horizontalHeader()
    assert second.roots_view.horizontalHeader().sectionSize(0) == 211
    assert header.sectionSize(0) == 233
    assert (header.sortIndicatorSection(), header.sortIndicatorOrder()) == (TITLE_COLUMN, Qt.SortOrder.DescendingOrder)
    sort.assert_called_with(TITLE_COLUMN, Qt.SortOrder.DescendingOrder)
    second.detach()


def test_the_layout_round_trips(dock: RehucoDock) -> None:
    """What ``save_state`` writes, ``restore_state`` takes back.

    **Test steps:**

    * save the layout and restore it
    * verify the restore succeeded
    """
    assert dock.restore_state(dock.save_state())


def test_a_layout_of_another_version_is_ignored(dock: RehucoDock) -> None:
    """The built default stays, since an old layout would hide the current sub-docks.

    **Test steps:**

    * save the layout and bump its version
    * verify the restore refuses it
    """
    state = cbor2.loads(dock.save_state())
    state[STATE_VERSION_KEY] = STATE_VERSION + 1

    assert not dock.restore_state(cbor2.dumps(state))


def test_a_layout_with_no_dock_state_is_ignored(dock: RehucoDock) -> None:
    """A blob of the right version that holds nothing restores nothing.

    **Test steps:**

    * restore a current-version blob with empty dock state
    * verify it is refused
    """
    assert not dock.restore_state(cbor2.dumps({STATE_VERSION_KEY: STATE_VERSION, STATE_DOCK_MANAGER_KEY: b""}))


def test_garbage_and_empty_layouts_are_ignored(dock: RehucoDock) -> None:
    """Nothing a settings file holds can raise from here.

    **Test steps:**

    * restore empty bytes, invalid CBOR and a CBOR list
    * verify each is refused
    """
    assert not dock.restore_state(b"")
    assert not dock.restore_state(b"\xff\xff")
    assert not dock.restore_state(cbor2.dumps([1, 2]))


# endregion

# region Guards and failures the views never reach on their own


@mark.usefixtures("served")
def test_a_cache_whose_roots_cannot_be_reconciled_does_not_open(mocker: MockerFixture, dock: RehucoDock) -> None:
    """A cache that opens but cannot be written is closed again, and the open fails with the reason.

    **Test steps:**

    * make ``reconcile_roots`` raise, and spy on ``close``
    * open a catalog
    * verify it failed naming the cache, and the cache was closed
    """
    mocker.patch.object(CatalogCache, "reconcile_roots", side_effect=sqlite3.OperationalError("locked"))
    close = mocker.spy(CatalogCache, "close")

    assert not dock.open_rehuco(REHUCO_PATH)

    assert "Could not read the cache" in dock.load_error
    assert dock.rehuco_path is None
    close.assert_called_once()


@mark.usefixtures("served", "saves")
def test_a_cache_that_cannot_be_read_keeps_what_is_shown(
    mocker: MockerFixture, dock: RehucoDock, caplog: LogCaptureFixture
) -> None:
    """A failed read is logged and the tables are left as they were -- the next scan rebuilds the cache.

    **Test steps:**

    * open a catalog, then make ``rows`` raise and spy on the models
    * add a root through the picker, which re-reads
    * verify an error was logged and neither model was reset
    """
    dock.open_rehuco(REHUCO_PATH)
    mocker.patch.object(CatalogCache, "rows", side_effect=sqlite3.OperationalError("locked"))
    set_rows = mocker.spy(dock.catalog_model, "set_rows")
    set_roots = mocker.spy(dock.roots_model, "set_roots")
    mocker.patch("rehuco_agent.rehuco.rehuco_dock.QFileDialog.getExistingDirectory", return_value="/fake/refs")

    with caplog.at_level(logging.ERROR):
        dock.add_root_action.trigger()

    assert "Could not read the cache" in caplog.text
    set_rows.assert_not_called()
    set_roots.assert_not_called()


def test_a_double_click_on_no_row_opens_nothing(qtbot: QtBot, dock: RehucoDock) -> None:
    """An invalid index -- a double-click on the empty area -- asks for nothing.

    **Test steps:**

    * emit a double-click with an invalid index
    * verify no open was requested
    """
    with qtbot.assertNotEmitted(dock.open_requested):
        dock.catalog_view.doubleClicked.emit(QModelIndex())


def test_the_root_edits_do_nothing_with_no_catalog_open(mocker: MockerFixture, dock: RehucoDock) -> None:
    """The slots behind the disabled actions refuse on their own too, so a stray trigger cannot edit nothing.

    **Test steps:**

    * spy on the folder picker, then call the add and remove slots with nothing open
    * verify the picker never opened and nothing was written
    """
    picker = mocker.patch("rehuco_agent.rehuco.rehuco_dock.QFileDialog.getExistingDirectory")
    saves = mocker.patch("rehuco_core.rehuco_file.atomic_write_text")

    dock._RehucoDock__on_add_root()  # type: ignore[attr-defined]  # pylint: disable=protected-access
    dock._RehucoDock__on_remove_root()  # type: ignore[attr-defined]  # pylint: disable=protected-access
    dock.scan()

    picker.assert_not_called()
    saves.assert_not_called()


@mark.usefixtures("served")
def test_removing_with_no_root_selected_does_nothing(dock: RehucoDock, saves: MagicMock) -> None:
    """The remove slot with no selection writes nothing.

    **Test steps:**

    * open a catalog without selecting a root, call the remove slot
    * verify nothing was written and both roots remain
    """
    dock.open_rehuco(REHUCO_PATH)

    dock._RehucoDock__on_remove_root()  # type: ignore[attr-defined]  # pylint: disable=protected-access

    saves.assert_not_called()
    assert dock.roots_model.rowCount() == 2


@mark.usefixtures("served")
def test_a_removal_whose_save_fails_queues_no_job(
    mocker: MockerFixture, dock: RehucoDock, queue: TaskQueue, saves: MagicMock
) -> None:
    """The cache keeps the root the file still has.

    **Test steps:**

    * open a catalog, select a root, make the write fail and remove
    * verify no job was queued and the list is back to two roots
    """
    mocker.patch("rehuco_agent.rehuco.rehuco_dock.QMessageBox.warning")
    saves.side_effect = PermissionError("read-only folder")
    dock.open_rehuco(REHUCO_PATH)
    dock.roots_view.selectRow(0)

    dock.remove_root_action.trigger()

    assert not queue.jobs()
    assert dock.roots_model.rowCount() == 2


@mark.usefixtures("served", "saves")
def test_a_cache_that_cannot_take_a_new_root_is_logged(
    mocker: MockerFixture, dock: RehucoDock, caplog: LogCaptureFixture
) -> None:
    """The file is saved either way; the cache is disposable, so the failure is a log line.

    **Test steps:**

    * open a catalog, then make the cache's root reconciliation fail and add a root
    * verify the root is listed and the failure was logged
    """
    dock.open_rehuco(REHUCO_PATH)
    mocker.patch.object(CatalogCache, "reconcile_roots", side_effect=sqlite3.OperationalError("locked"))
    mocker.patch("rehuco_agent.rehuco.rehuco_dock.QFileDialog.getExistingDirectory", return_value="/fake/refs")

    with caplog.at_level(logging.ERROR):
        dock.add_root_action.trigger()

    assert "Could not update the cache" in caplog.text
    assert dock.roots_model.rowCount() == 3


@mark.usefixtures("served")
def test_a_tracked_job_cleared_from_the_queue_reads_the_table_again(
    mocker: MockerFixture, qtbot: QtBot, dock: RehucoDock, queue: TaskQueue, held: GateJob
) -> None:
    """A job the user cleared will say nothing more, so its removal is the moment to read back; a reorder, a
    pause and the removal of a job that is not this dock's say nothing at all.

    **Test steps:**

    * hold the queue, open and scan, spy on ``set_rows``
    * tell the dock the jobs were reordered, the queue paused, and a stranger removed; then remove the jobs
    * verify only the removal of its own jobs re-read the rows
    """
    scan_finding(mocker, {})
    dock.open_rehuco(REHUCO_PATH)
    dock.scan_action.trigger()
    serials = [status.serial for status in queue.jobs()[1:]]
    set_rows = mocker.spy(dock.catalog_model, "set_rows")

    dock.jobs_reordered(serials)
    dock.queue_paused_changed(True)
    dock.jobs_removed([999])
    qtbot.wait(50)
    assert set_rows.call_count == 0

    for serial in serials:
        queue.remove(serial)
    qtbot.waitUntil(lambda: set_rows.call_count == 1, timeout=WAIT_TIMEOUT_MS)
    held.let_finish()


# endregion
