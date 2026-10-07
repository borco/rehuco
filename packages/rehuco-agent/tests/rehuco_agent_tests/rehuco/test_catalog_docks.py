"""Tests for the Root Catalog and its two docks: opening a ``.rehuco``, scanning its roots through the queue, the
Roots view over its roots and the browsers listing and opening what the cache holds (#377, #461).

No file is ever created: ``Path.read_text`` serves the ``.rehuco``, ``atomic_write_text`` is captured, and
:func:`sqlite3.connect` is patched to hand back shared-cache in-memory databases -- the dock's own connection
and every scan job's, on the worker thread, reach the same one.
"""

# the docks have a broad surface (opening, scanning, editing roots, a read-only mode, layout, the queue listener);
# one cohesive module reads better than an arbitrary split, so the module-length cap is lifted here, as it is for
# test_main_window.py and test_rehu_document_model.py
# pylint: disable=too-many-lines

import json
import logging
import os
import sqlite3
import tempfile
import threading
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import PySide6QtAds as QtAds
from borco_pyside.qtads import tab_close_button, tab_label, tab_maximize_button
from borco_pyside.widgets import MessageBanner, RowBandDelegate
from PySide6.QtCore import QItemSelectionModel, QModelIndex, QPoint, Qt, QUrl
from PySide6.QtGui import QAction, QContextMenuEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QLabel,
    QListView,
    QMenu,
    QMessageBox,
    QSplitter,
)
from pytest import LogCaptureFixture, MonkeyPatch, fixture, mark, param
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco import BrowsersDock, RootCatalog, RootsPanel, TableBrowser
from rehuco_agent.rehuco.add_root_dialog import AddRootDialog
from rehuco_agent.rehuco.browser_presets import browser_presets
from rehuco_agent.rehuco.catalog_table_model import CatalogColumn
from rehuco_agent.rehuco.root_storage import ROOT_STORAGE_ICONS
from rehuco_agent.rehuco.roots_folder_model import NodeListing, RootsNodeKind
from rehuco_agent.rehuco.roots_item_delegate import RootsItemDelegate
from rehuco_agent.rehuco.roots_management import managing_record
from rehuco_agent.rehuco.roots_preview import RootsPreview
from rehuco_agent.resource_events import ResourceEvents
from rehuco_agent.settings.catalog_state_store import TABLE_BROWSER_KIND, BrowserState, CatalogState
from rehuco_agent.settings.checksum_settings import shared_checksum_settings
from rehuco_core import (
    FINISHED_JOB_STATES,
    CatalogCache,
    CatalogField,
    CatalogRecord,
    GenerateChecksumsJob,
    JobControl,
    RecordKind,
    RehucoRoot,
    Relocation,
    RootScanOutcome,
    RootScanResult,
    RootStorage,
    TaskJobBase,
    TaskQueue,
    VerifyChecksumsJob,
)

from rehuco_agent_tests.conftest import MemoryCatalogStateStore

REAL_READ_TEXT: Final = Path.read_text
"""The real :meth:`Path.read_text`, bound before a fixture patches it."""

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
    mocker.patch("rehuco_agent.rehuco.root_catalog.cache_folder", return_value=Path("/fake/cache"))
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


@dataclass(frozen=True)
class CatalogDocks:
    """One catalog and the two docks' contents over it, wired as the main window wires them (#461)."""

    catalog: RootCatalog
    """The open file and its cache."""

    roots: RootsPanel
    """The Root Catalog dock's content."""

    browsers: BrowsersDock
    """The Browsers dock's content."""

    def detach(self) -> None:
        """Detach the panel and the catalog, as the window does on close."""
        self.roots.detach()
        self.catalog.detach()


def build_docks(qtbot: QtBot, queue: TaskQueue, events: ResourceEvents | None = None) -> CatalogDocks:
    """A catalog over ``queue`` and both docks' contents over it, the folder filter wired to the browsers.

    :param qtbot: pytest-qt fixture, which deletes the two widgets.
    :param queue: the queue its jobs run on.
    :param events: the file announcements to follow, if any.
    :returns: the three.
    """
    catalog = RootCatalog(queue, resource_events=events)
    roots = RootsPanel(catalog, queue, resource_events=events)
    browsers = BrowsersDock(catalog)
    roots.filter_requested.connect(browsers.set_filter_token)
    qtbot.addWidget(roots)
    qtbot.addWidget(browsers)
    return CatalogDocks(catalog, roots, browsers)


@fixture(name="dock")
def fixture_dock(
    qtbot: QtBot, queue: TaskQueue, database: MemoryDatabase, mocker: MockerFixture
) -> Generator[CatalogDocks]:
    """A catalog and its docks over the real queue and the in-memory database, detached when the test ends.

    Removing a root asks first, and that question is replaced per instance with a yes -- a test of the question
    itself replaces it again.

    :param qtbot: pytest-qt fixture.
    :param queue: the queue its jobs run on.
    :param database: the cache's database.
    :param mocker: pytest-mock fixture.
    :yields: the docks, with nothing open.
    """
    del database
    dock = build_docks(qtbot, queue)
    mocker.patch.object(dock.roots, "confirm_remove_root", return_value=True)
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
    return CatalogRecord(
        "python/info.rehu", RecordKind.REHU, title="Python", type="tutorial", current_size=1536, content_hash="0"
    )


def wait_for_jobs(qtbot: QtBot, queue: TaskQueue) -> None:
    """Wait until every job on the queue has ended."""
    qtbot.waitUntil(
        lambda: all(status.state in FINISHED_JOB_STATES for status in queue.jobs()), timeout=WAIT_TIMEOUT_MS
    )


def select_root(dock: CatalogDocks, row: int) -> None:
    """Make a root row the Roots view's current one.

    :param dock: the catalog's docks.
    :param row: the root's row.
    """
    dock.roots.roots_view.setCurrentIndex(dock.roots.roots_model.index(row, 0))


def answer_add_root(
    mocker: MockerFixture, dock: CatalogDocks, folder: str | None, storage: RootStorage = RootStorage.LOCAL
) -> MagicMock:
    """Make the Add Root question answer, instead of opening its dialog.

    :param mocker: pytest-mock fixture.
    :param dock: the catalog's docks.
    :param folder: the folder to answer with; ``None`` cancels.
    :param storage: what the answered folder lives on.
    :returns: the mock standing in for the question.
    """
    return mocker.patch.object(
        dock.roots, "ask_root_to_add", return_value=None if folder is None else (folder, storage)
    )


def shown_labels(dock: CatalogDocks) -> list[str]:
    """The labels of the roots the dock lists, in row order."""
    model = dock.roots.roots_model
    return [model.index(row, 0).data() for row in range(model.rowCount())]


def written_roots(saves: MagicMock) -> list[str]:
    """The root labels of the last ``.rehuco`` written."""
    payload = json.loads(saves.call_args[0][1])
    return [root["label"] for root in payload["roots"]]


# region Opening and creating


def test_opening_lists_the_roots_and_reconciles_the_cache(
    dock: CatalogDocks, database: MemoryDatabase, served: Any
) -> None:
    """The file's roots are shown and brought into the cache, so a scan has rows to replace.

    **Test steps:**

    * open a two-root catalog over an empty cache
    * verify the path, both root labels in order, and two root rows in the cache
    """
    del served

    assert dock.catalog.open_rehuco(REHUCO_PATH)

    assert dock.catalog.rehuco_path == REHUCO_PATH
    assert shown_labels(dock) == ["tutorials", "packs"]
    assert database.scalar("SELECT COUNT(*) FROM roots") == 2


def test_opening_announces_the_new_path(qtbot: QtBot, dock: CatalogDocks, served: Any) -> None:
    """Whoever shows the open file's name is told when it changes.

    **Test steps:**

    * open a catalog while waiting on the path signal
    * verify it carried the path
    """
    del served

    with qtbot.waitSignal(dock.catalog.rehuco_path_changed) as opened:
        dock.catalog.open_rehuco(REHUCO_PATH)

    assert opened.args == [REHUCO_PATH]


def test_opening_another_file_replaces_the_open_one(dock: CatalogDocks, served: Any) -> None:
    """One ``.rehuco`` is open at a time.

    **Test steps:**

    * open one catalog, then another
    * verify the second is the open one
    """
    del served
    dock.catalog.open_rehuco(REHUCO_PATH)

    assert dock.catalog.open_rehuco(OTHER_PATH)

    assert dock.catalog.rehuco_path == OTHER_PATH


def test_a_missing_file_does_not_open_and_says_why(mocker: MockerFixture, dock: CatalogDocks, served: Any) -> None:
    """The error is kept for whoever asked, and the file that was open stays open.

    **Test steps:**

    * open a catalog, then make every read fail and open another
    * verify the open failed, the error names the file, and the first stays open
    """
    del served
    dock.catalog.open_rehuco(REHUCO_PATH)
    mocker.patch.object(Path, "read_text", side_effect=FileNotFoundError("gone"))

    assert not dock.catalog.open_rehuco(OTHER_PATH)

    assert str(OTHER_PATH) in dock.catalog.load_error
    assert dock.catalog.rehuco_path == REHUCO_PATH


def test_a_file_that_is_not_a_rehuco_does_not_open(mocker: MockerFixture, dock: CatalogDocks) -> None:
    """A parse failure is an error to report, not an exception for the window.

    **Test steps:**

    * serve a JSON list as the file
    * verify nothing opened and the error says why
    """
    mocker.patch.object(Path, "read_text", return_value="[1, 2]")

    assert not dock.catalog.open_rehuco(REHUCO_PATH)

    assert dock.catalog.rehuco_path is None
    assert "Not a JSON object" in dock.catalog.load_error


def test_a_new_rehuco_is_written_and_opened_empty(dock: CatalogDocks, saves: MagicMock) -> None:
    """Creating writes the file first, then opens what was written.

    **Test steps:**

    * create a catalog at a new path
    * verify it was written there, is open, lists no roots and can be scanned
    """
    assert dock.catalog.new_rehuco(OTHER_PATH)

    saves.assert_called_once()
    assert saves.call_args[0][0] == OTHER_PATH
    assert dock.catalog.rehuco_path == OTHER_PATH
    assert dock.roots.roots_model.rowCount() == 0
    assert dock.roots.scan_action.isEnabled()


def test_a_new_rehuco_that_cannot_be_written_is_not_opened(dock: CatalogDocks, saves: MagicMock) -> None:
    """A failed write leaves nothing open, and says why.

    **Test steps:**

    * make the write fail and create a catalog
    * verify nothing is open and the error names the cause
    """
    saves.side_effect = PermissionError("read-only folder")

    assert not dock.catalog.new_rehuco(OTHER_PATH)

    assert dock.catalog.rehuco_path is None
    assert "read-only folder" in dock.catalog.load_error


def test_a_new_rehuco_whose_cache_cannot_open_is_never_written(
    mocker: MockerFixture, dock: CatalogDocks, saves: MagicMock
) -> None:
    """The cache is opened before the file is written, so a file reported as not created is not on disk either.

    **Test steps:**

    * make the cache refuse to open
    * create a catalog
    * verify it failed, nothing was written, and the reason names the cache
    """
    mocker.patch("rehuco_agent.rehuco.root_catalog.CatalogCache.open", side_effect=sqlite3.OperationalError("locked"))

    assert not dock.catalog.new_rehuco(OTHER_PATH)

    saves.assert_not_called()
    assert dock.catalog.rehuco_path is None
    assert "cache" in dock.catalog.load_error and "locked" in dock.catalog.load_error


def test_closing_empties_the_dock(qtbot: QtBot, dock: CatalogDocks, served: Any) -> None:
    """Nothing of the closed file stays on screen, and the path change is announced as none.

    **Test steps:**

    * open a catalog and close it while waiting on the path signal
    * verify the signal carried ``None``, nothing is open, the roots are empty, no browser is left and Scan is off
    """
    del served
    dock.catalog.open_rehuco(REHUCO_PATH)

    with qtbot.waitSignal(dock.catalog.rehuco_path_changed) as closed:
        dock.catalog.close_rehuco()

    assert closed.args == [None]
    assert dock.catalog.rehuco_path is None
    assert dock.roots.roots_model.rowCount() == 0
    assert not dock.browsers.browsers
    assert not dock.roots.scan_action.isEnabled()


def test_closing_with_nothing_open_is_a_no_op(qtbot: QtBot, dock: CatalogDocks) -> None:
    """No signal fires for a close that closed nothing.

    **Test steps:**

    * close with nothing open
    * verify no path signal fired
    """
    with qtbot.assertNotEmitted(dock.catalog.rehuco_path_changed):
        dock.catalog.close_rehuco()


# endregion

# region Scanning and listing


def test_a_scan_enqueues_one_job_per_root(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, queue: TaskQueue, served: Any
) -> None:
    """Each root is one job, over the root's folder, so each is online or offline on its own.

    **Test steps:**

    * open a two-root catalog and scan
    * verify one job per root, in root order
    """
    del served
    scan_finding(mocker, {})
    dock.catalog.open_rehuco(REHUCO_PATH)

    dock.roots.scan_action.trigger()

    assert [status.source for status in queue.jobs()] == [TUTORIALS, PACKS]
    wait_for_jobs(qtbot, queue)


@mark.usefixtures("served")
def test_a_scan_that_is_already_queued_is_not_queued_again(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, queue: TaskQueue, held: GateJob
) -> None:
    """Scanning twice while the first scans still wait leaves the queue as it was.

    **Test steps:**

    * hold the queue, open a catalog and scan twice
    * verify one job per root, not two
    """
    scan_finding(mocker, {})
    dock.catalog.open_rehuco(REHUCO_PATH)

    dock.roots.scan_action.trigger()
    dock.roots.scan_action.trigger()

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
    first = build_docks(qtbot, queue)
    first.catalog.open_rehuco(REHUCO_PATH)
    first.roots.scan_action.trigger()
    second = build_docks(qtbot, queue)
    second.catalog.open_rehuco(REHUCO_PATH)

    second.roots.scan_action.trigger()

    assert [status.source for status in queue.jobs()[1:]] == [TUTORIALS, PACKS, TUTORIALS, PACKS]
    held.let_finish()
    wait_for_jobs(qtbot, queue)
    first.detach()
    second.detach()


@mark.usefixtures("served", "saves")
def test_removing_a_re_added_root_is_queued_again(
    qtbot: QtBot, dock: CatalogDocks, queue: TaskQueue, held: GateJob, mocker: MockerFixture
) -> None:
    """A second removal of a root with the same label is its own job: a removal names no folder, so matching
    on label alone would have refused it.

    **Test steps:**

    * hold the queue; remove a root, add the same folder back, remove it again
    * verify two removal jobs wait
    """
    answer_add_root(mocker, dock, str(TUTORIALS))
    dock.catalog.open_rehuco(REHUCO_PATH)
    select_root(dock, 0)
    dock.roots.remove_root_action.trigger()
    dock.roots.add_root_action.trigger()
    select_root(dock, 1)

    dock.roots.remove_root_action.trigger()

    assert [status.label for status in queue.jobs()[1:]] == ["Remove root - tutorials", "Remove root - tutorials"]
    held.let_finish()
    wait_for_jobs(qtbot, queue)


@mark.usefixtures("served")
def test_the_table_is_read_once_when_the_last_scan_ends(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, queue: TaskQueue
) -> None:
    """Two roots, two jobs, one re-read: the picture is only complete when the last one ends.

    **Test steps:**

    * spy on the catalog model's ``set_rows``, open and scan a two-root catalog
    * wait for both jobs to end
    * verify the rows were set once for the open and once more for the scan
    """
    scan_finding(mocker, {TUTORIALS: (tutorial_record(),)})
    dock.catalog.open_rehuco(REHUCO_PATH)
    set_rows = mocker.spy(TableBrowser, "set_rows")

    dock.roots.scan_action.trigger()

    qtbot.waitUntil(lambda: first_browser(dock).model.rowCount() == 1, timeout=WAIT_TIMEOUT_MS)
    wait_for_jobs(qtbot, queue)
    qtbot.wait(50)
    assert set_rows.call_count == 1


@mark.usefixtures("served")
def test_reopening_the_open_catalog_keeps_its_running_scans_tracked(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, queue: TaskQueue, held: GateJob
) -> None:
    """Picking the open file from the recents while its scan waits still refreshes the table when the scan
    ends -- the same cache is shown, so the jobs are still this dock's.

    **Test steps:**

    * hold the queue, open and scan, then open the same file again
    * release the queue
    * verify the scanned rows appear
    """
    scan_finding(mocker, {TUTORIALS: (tutorial_record(),)})
    dock.catalog.open_rehuco(REHUCO_PATH)
    dock.roots.scan_action.trigger()

    assert dock.catalog.open_rehuco(REHUCO_PATH)
    held.let_finish()

    qtbot.waitUntil(lambda: first_browser(dock).model.rowCount() == 1, timeout=WAIT_TIMEOUT_MS)
    wait_for_jobs(qtbot, queue)


@mark.usefixtures("served")
def test_opening_another_catalog_forgets_the_old_ones_scans(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, queue: TaskQueue, held: GateJob
) -> None:
    """A scan of the previous catalog ends in a cache no longer shown, so it reads nothing back.

    **Test steps:**

    * hold the queue, open and scan, then open a file with another rehuco id
    * release the queue and let the scan end
    * verify the table stays empty
    """
    scan_finding(mocker, {TUTORIALS: (tutorial_record(),)})
    dock.catalog.open_rehuco(REHUCO_PATH)
    dock.roots.scan_action.trigger()
    set_rows = mocker.spy(TableBrowser, "set_rows")
    mocker.patch.object(Path, "read_text", return_value=json.dumps({**HOME, "id": str(uuid4())}))
    assert dock.catalog.open_rehuco(OTHER_PATH)
    assert set_rows.call_count == 1

    held.let_finish()
    wait_for_jobs(qtbot, queue)

    qtbot.wait(50)
    assert set_rows.call_count == 1
    assert first_browser(dock).model.rowCount() == 0


def test_what_a_scan_finds_is_listed_once_it_ends(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, queue: TaskQueue, served: Any
) -> None:
    """The table is read again when a scan job ends, with authors, title, type and a root-qualified path.

    **Test steps:**

    * open a catalog over a scan that finds one record, and scan
    * wait for the row, then verify its four cells
    """
    del served
    scan_finding(mocker, {TUTORIALS: (tutorial_record(),)})
    dock.catalog.open_rehuco(REHUCO_PATH)
    assert first_browser(dock).model.rowCount() == 0

    dock.roots.scan_action.trigger()

    qtbot.waitUntil(lambda: first_browser(dock).model.rowCount() == 1, timeout=WAIT_TIMEOUT_MS)
    wait_for_jobs(qtbot, queue)
    model = first_browser(dock).model
    assert [model.index(0, column).data() for column in range(4)] == [
        None,
        "Python",
        "tutorial",
        "tutorials/python/info.rehu",
    ]


def test_a_double_click_opens_the_resource_by_its_absolute_path(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, queue: TaskQueue, served: Any
) -> None:
    """The row answers where its record lives, which is what the window's ordinary open route takes.

    **Test steps:**

    * scan one record in, then double-click its row
    * verify the open request carried the root's folder joined to the record's path
    """
    del served
    scan_finding(mocker, {TUTORIALS: (tutorial_record(),)})
    dock.catalog.open_rehuco(REHUCO_PATH)
    dock.roots.scan_action.trigger()
    qtbot.waitUntil(lambda: first_browser(dock).model.rowCount() == 1, timeout=WAIT_TIMEOUT_MS)
    wait_for_jobs(qtbot, queue)

    with qtbot.waitSignal(dock.browsers.open_requested) as requested:
        first_browser(dock).view.doubleClicked.emit(first_browser(dock).model.index(0, 0))

    assert requested.args == [TUTORIALS / "python/info.rehu"]


# endregion

# region The browser's status bar


@mark.usefixtures("served")
def test_the_status_bar_counts_the_rows_the_table_shows(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, queue: TaskQueue
) -> None:
    """The count follows the rows a scan lands and the rows a close clears, with the singular spelled right.

    **Test steps:**

    * open a catalog and scan one 1.5 KiB record in; verify ``1 resource / 1.5K``
    * scan again, now finding a second 2 KiB record; verify ``2 resources / 3.5K``
    """
    scan_finding(mocker, {TUTORIALS: (tutorial_record(),)})
    dock.catalog.open_rehuco(REHUCO_PATH)
    dock.roots.scan_action.trigger()
    qtbot.waitUntil(lambda: first_browser(dock).model.rowCount() == 1, timeout=WAIT_TIMEOUT_MS)
    wait_for_jobs(qtbot, queue)
    assert first_browser(dock).status_line.full_text == "1 resource / 1.5K"

    second = CatalogRecord(
        "go/info.rehu", RecordKind.REHU, title="Go", type="tutorial", current_size=2048, content_hash="1"
    )
    scan_finding(mocker, {TUTORIALS: (tutorial_record(), second)})
    dock.roots.scan_action.trigger()
    qtbot.waitUntil(lambda: first_browser(dock).model.rowCount() == 2, timeout=WAIT_TIMEOUT_MS)
    wait_for_jobs(qtbot, queue)
    assert first_browser(dock).status_line.full_text == "2 resources / 3.5K"


# endregion

# region Editing the roots


def test_adding_a_root_saves_the_file_and_the_cache_follows(
    mocker: MockerFixture, dock: CatalogDocks, database: MemoryDatabase, served: Any, saves: MagicMock
) -> None:
    """The edit is on disk before the dock says it happened.

    **Test steps:**

    * mock the folder picker and add a root
    * verify the file was written with three roots, the list shows three, and the cache holds three
    """
    del served
    answer_add_root(mocker, dock, "/fake/refs")
    dock.catalog.open_rehuco(REHUCO_PATH)

    dock.roots.add_root_action.trigger()

    assert written_roots(saves) == ["tutorials", "packs", "refs"]
    assert dock.roots.roots_model.rowCount() == 3
    assert database.scalar("SELECT COUNT(*) FROM roots") == 3


def test_cancelling_the_folder_picker_adds_nothing(
    mocker: MockerFixture, dock: CatalogDocks, served: Any, saves: MagicMock
) -> None:
    """No folder chosen, no edit and no write.

    **Test steps:**

    * cancel the folder picker
    * verify nothing was written and the list is unchanged
    """
    del served
    answer_add_root(mocker, dock, None)
    dock.catalog.open_rehuco(REHUCO_PATH)

    dock.roots.add_root_action.trigger()

    saves.assert_not_called()
    assert dock.roots.roots_model.rowCount() == 2


def test_adding_a_folder_that_is_already_a_root_warns_and_changes_nothing(
    mocker: MockerFixture, dock: CatalogDocks, served: Any, saves: MagicMock
) -> None:
    """The file's own refusal reaches the person, and nothing is written.

    **Test steps:**

    * pick a folder that is already a root
    * verify a warning was shown, nothing was written and the list is unchanged
    """
    del served
    answer_add_root(mocker, dock, str(PACKS))
    warning = mocker.patch("rehuco_agent.rehuco.roots_panel.QMessageBox.warning")
    dock.catalog.open_rehuco(REHUCO_PATH)

    dock.roots.add_root_action.trigger()

    warning.assert_called_once()
    saves.assert_not_called()
    assert dock.roots.roots_model.rowCount() == 2


def test_a_failed_save_drops_the_edit_from_the_screen_too(
    mocker: MockerFixture, dock: CatalogDocks, served: Any, saves: MagicMock
) -> None:
    """The file is read back, so what is shown is what is on disk.

    **Test steps:**

    * add a root while the write fails
    * verify a warning was shown and the list is back to two roots
    """
    del served
    answer_add_root(mocker, dock, "/fake/refs")
    warning = mocker.patch("rehuco_agent.rehuco.roots_panel.QMessageBox.warning")
    saves.side_effect = PermissionError("read-only folder")
    dock.catalog.open_rehuco(REHUCO_PATH)

    dock.roots.add_root_action.trigger()

    warning.assert_called_once()
    assert dock.roots.roots_model.rowCount() == 2


def test_a_failed_save_that_cannot_be_read_back_closes_the_file(
    mocker: MockerFixture, dock: CatalogDocks, served: Any, saves: MagicMock
) -> None:
    """With neither the edit nor the disk to trust, nothing stays open.

    **Test steps:**

    * add a root while the write fails and the file can no longer be read
    * verify nothing is open
    """
    del served
    answer_add_root(mocker, dock, "/fake/refs")
    mocker.patch("rehuco_agent.rehuco.roots_panel.QMessageBox.warning")
    saves.side_effect = PermissionError("read-only folder")
    dock.catalog.open_rehuco(REHUCO_PATH)
    mocker.patch.object(Path, "read_text", side_effect=FileNotFoundError("gone"))

    dock.roots.add_root_action.trigger()

    assert dock.catalog.rehuco_path is None


@mark.usefixtures("served")
def test_removing_a_root_saves_the_file_and_queues_the_removal(
    qtbot: QtBot, dock: CatalogDocks, queue: TaskQueue, database: MemoryDatabase, saves: MagicMock
) -> None:
    """The file loses the root at once; its rows leave the cache on the worker.

    **Test steps:**

    * select the first root and remove it
    * verify the file was written without it, the list shrank, a removal job ran, and the cache lost the root
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    assert not dock.roots.remove_root_action.isEnabled()
    select_root(dock, 0)
    assert dock.roots.remove_root_action.isEnabled()

    dock.roots.remove_root_action.trigger()

    assert written_roots(saves) == ["packs"]
    assert dock.roots.roots_model.rowCount() == 1
    assert [status.label for status in queue.jobs()] == ["Remove root - tutorials"]
    wait_for_jobs(qtbot, queue)
    assert database.scalar("SELECT COUNT(*) FROM roots") == 1


@mark.usefixtures("served", "saves")
def test_a_removed_roots_rows_leave_the_table_at_once(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, queue: TaskQueue
) -> None:
    """The rows stay in the cache until the removal job has run, but are not shown meanwhile.

    **Test steps:**

    * scan a record in, then remove its root
    * verify the table is empty before the removal job has run
    """
    scan_finding(mocker, {TUTORIALS: (tutorial_record(),)})
    dock.catalog.open_rehuco(REHUCO_PATH)
    dock.roots.scan_action.trigger()
    qtbot.waitUntil(lambda: first_browser(dock).model.rowCount() == 1, timeout=WAIT_TIMEOUT_MS)
    wait_for_jobs(qtbot, queue)
    select_root(dock, 0)

    dock.roots.remove_root_action.trigger()

    assert first_browser(dock).model.rowCount() == 0
    wait_for_jobs(qtbot, queue)


# endregion

# region A file newer than this build


def test_a_newer_file_opens_read_only_with_a_banner(dock: CatalogDocks, served: Any) -> None:
    """Every edit of the roots is off and the reason is shown; scanning writes only the cache, so stays on.

    **Test steps:**

    * serve a file stamped with a newer format version
    * verify it opened, the banner shows, Add and Remove are off, and Scan is on
    """
    served["format_version"] = 99

    assert dock.catalog.open_rehuco(REHUCO_PATH)

    banner = dock.roots.findChild(MessageBanner)
    assert banner is not None
    assert not banner.isHidden()
    assert not dock.roots.add_root_action.isEnabled()
    select_root(dock, 0)
    assert not dock.roots.remove_root_action.isEnabled()
    assert dock.roots.scan_action.isEnabled()


def test_an_editable_file_shows_no_banner(dock: CatalogDocks, served: Any) -> None:
    """Nothing is said about a file nothing is wrong with.

    **Test steps:**

    * open an ordinary file
    * verify the banner is hidden
    """
    del served

    dock.catalog.open_rehuco(REHUCO_PATH)

    banner = dock.roots.findChild(MessageBanner)
    assert banner is not None
    assert banner.isHidden()


# endregion

# region Layout


def first_browser(dock: CatalogDocks) -> TableBrowser:
    """The first browser, taken through a local: ``pylint_qt`` reads ``dock.browsers.browsers[0]`` as a
    subscripted signal.

    :param dock: the catalog's docks, with a catalog open.
    :returns: its first browser.
    """
    browsers = dock.browsers.browsers
    return browsers[0]


def sub_docks(dock: CatalogDocks) -> dict[str, QtAds.CDockWidget]:
    """Every sub-dock the shell holds, by object name: ``roots`` and each browser's id.

    :param dock: the catalog's docks.
    :returns: the sub-docks.
    """
    return {widget.objectName(): widget for widget in dock.browsers.findChildren(QtAds.CDockWidget)}


def make_current(qtbot: QtBot, widget: QtAds.CDockWidget) -> None:
    """Make ``widget`` the focus tracker's current sub-dock the way a user does, by clicking its tab title.

    :param qtbot: the Qt test driver.
    :param widget: the sub-dock to make current.
    """
    qtbot.mouseClick(tab_label(widget), Qt.MouseButton.LeftButton)


@mark.usefixtures("served")
def test_the_sub_dock_tabs_keep_their_buttons_small_before_the_dock_is_ever_shown(
    qtbot: QtBot, dock: CatalogDocks
) -> None:
    """Built inside a closed outer dock, the sub-docks' tabs have never been laid out, and their buttons used to be
    fixed at the tab's 480 px default -- each tab a 600 px box, the tab strip half the window (#377).

    **Test steps:**

    * open a catalog without showing the dock
    * wait for the browser sub-dock's maximize button to appear
    * verify neither it nor the close button is taller than a couple of text lines
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    sub_dock = dock.browsers.browser_dock(first_browser(dock))
    qtbot.waitUntil(lambda: tab_maximize_button(sub_dock) is not None, timeout=WAIT_TIMEOUT_MS)
    maximize = tab_maximize_button(sub_dock)
    close = tab_close_button(sub_dock)
    assert maximize is not None
    assert close is not None
    limit = 2 * maximize.fontMetrics().height()
    qtbot.waitUntil(lambda: close.minimumHeight() == close.maximumHeight(), timeout=WAIT_TIMEOUT_MS)
    assert maximize.height() <= limit
    assert close.height() <= limit


@mark.usefixtures("served")
def test_the_browser_paints_bands_and_the_roots_columns_their_own_rows(dock: CatalogDocks) -> None:
    """The browser looks like every other table in the app: one band per selected row, no grid. Each Roots column is
    drawn by the delegate that adds the glyph and the arrow -- the column view's own delegate would draw neither
    the glyph nor a greyed row.

    **Test steps:**

    * open a catalog and read the browser's delegate, grid and word wrap
    * verify the row band delegate, no grid, no wrapping
    * verify every column the Roots view made uses the roots delegate
    """
    dock.catalog.open_rehuco(REHUCO_PATH)

    view = first_browser(dock).view
    assert isinstance(view.itemDelegate(), RowBandDelegate)
    assert not view.showGrid()
    assert not view.wordWrap()
    columns = dock.roots.roots_view.findChildren(QListView)
    assert columns
    assert all(isinstance(column.itemDelegate(), RootsItemDelegate) for column in columns)


@mark.usefixtures("served")
def test_a_browser_starts_unsorted_but_sortable(dock: CatalogDocks) -> None:
    """No arrow on a column until one is clicked, because the rows start in the cache's order.

    **Test steps:**

    * open a catalog and read the browser's sorting switch and sort indicator
    * verify sorting is on and no column is marked
    """
    dock.catalog.open_rehuco(REHUCO_PATH)

    assert first_browser(dock).view.isSortingEnabled()
    assert first_browser(dock).view.horizontalHeader().sortIndicatorSection() == -1


@mark.usefixtures("served")
def test_column_widths_and_the_sort_survive_closing_and_reopening(dock: CatalogDocks) -> None:
    """What a reader set on the browser comes back the next time the catalog is opened: its column width and
    sort.

    **Test steps:**

    * widen a column of the browser, sort it by title descending, then close the catalog
    * open it again
    * verify the width and the sort indicator
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    first_browser(dock).view.horizontalHeader().resizeSection(0, 233)
    first_browser(dock).view.sortByColumn(CatalogColumn.TITLE, Qt.SortOrder.DescendingOrder)
    dock.catalog.close_rehuco()

    dock.catalog.open_rehuco(REHUCO_PATH)

    header = first_browser(dock).view.horizontalHeader()
    assert header.sectionSize(0) == 233
    assert (header.sortIndicatorSection(), header.sortIndicatorOrder()) == (
        CatalogColumn.TITLE,
        Qt.SortOrder.DescendingOrder,
    )


@mark.usefixtures("served")
def test_the_layout_comes_back_with_the_catalog(dock: CatalogDocks) -> None:
    """Where the browsers' sub-docks sit is remembered per catalog: two browsers side by side stay side by side.

    **Test steps:**

    * open a catalog, add a second browser and move it beside the first
    * close the catalog and open it again
    * verify both browsers are shown, each in an area of its own
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    dock.browsers.new_browser_action.trigger()
    manager = dock.browsers.findChild(QtAds.CDockManager)
    assert manager is not None
    _, second_browser = dock.browsers.browsers
    manager.addDockWidget(QtAds.RightDockWidgetArea, dock.browsers.browser_dock(second_browser))
    dock.catalog.close_rehuco()

    dock.catalog.open_rehuco(REHUCO_PATH)

    first, second = (dock.browsers.browser_dock(browser) for browser in dock.browsers.browsers)
    assert not first.isClosed()
    assert not second.isClosed()
    assert first.dockAreaWidget() is not second.dockAreaWidget()


def test_a_remembered_catalog_with_no_layout_tabs_every_browser_together(
    served: Any, dock: CatalogDocks, catalog_store: MemoryCatalogStateStore
) -> None:
    """Browsers remembered without a layout -- what a catalog saved before #461 is read as, its layout having nested
    the Roots view among them -- open with their names, every one on screen in one tab strip.

    **Test steps:**

    * remember two named browsers and no layout for the served catalog
    * open it
    * verify both browsers by name, both shown, sharing one area
    """
    del served
    states = catalog_store.states
    states[UUID(REHUCO_ID)] = CatalogState(
        [
            BrowserState(uuid4(), TABLE_BROWSER_KIND, "Tutorials", "type:tutorial"),
            BrowserState(uuid4(), TABLE_BROWSER_KIND, "Packs"),
        ]
    )

    dock.catalog.open_rehuco(REHUCO_PATH)

    tutorials, packs = dock.browsers.browsers
    assert (tutorials.name, packs.name) == ("Tutorials", "Packs")
    assert tutorials.filter_text == "type:tutorial"
    assert is_on_screen(dock, tutorials)
    assert is_on_screen(dock, packs)
    assert dock.browsers.browser_dock(tutorials).dockAreaWidget() is dock.browsers.browser_dock(packs).dockAreaWidget()


# endregion

# region Browsers (#396)


def test_there_is_no_browser_until_a_catalog_is_open(dock: CatalogDocks) -> None:
    """Browsers belong to a catalog, so none exists -- and none can be added -- without one.

    **Test steps:**

    * read the browsers and the New Browser action of a dock with nothing open
    * verify there are none and the action is disabled
    """
    assert not dock.browsers.browsers
    assert not dock.browsers.new_browser_action.isEnabled()


@mark.usefixtures("served")
def test_a_catalog_with_no_remembered_browsers_opens_one_default_browser(dock: CatalogDocks) -> None:
    """The first time a catalog is opened it shows one browser, named as a new one is.

    **Test steps:**

    * open a catalog the store knows nothing about
    * verify one browser named "Browser", whose sub-dock is named by its id
    """
    dock.catalog.open_rehuco(REHUCO_PATH)

    assert [browser.name for browser in dock.browsers.browsers] == ["Browser"]
    assert str(first_browser(dock).browser_id) in sub_docks(dock)
    assert dock.browsers.new_browser_action.isEnabled()


def test_the_browsers_title_bar_carries_new_table_browser_only(dock: CatalogDocks) -> None:
    """Rename Browser stays off the Browsers dock's title bar: the current browser's own title bar has its Rename,
    and the ``Browsers`` menu has Rename Browser (#461).

    **Test steps:**

    * read the title bar actions the Browsers dock offers its holder
    * verify they are New Table Browser alone
    """
    assert dock.browsers.title_bar_actions == [dock.browsers.new_browser_action]


@mark.usefixtures("served")
def test_new_browser_adds_a_browser_with_the_rows_and_makes_it_current(dock: CatalogDocks) -> None:
    """A new browser is tabbed beside the first, shows the same rows and is the current one.

    **Test steps:**

    * open a catalog and trigger New Table Browser
    * verify two browsers, the new one current, and both areas the same
    """
    dock.catalog.open_rehuco(REHUCO_PATH)

    dock.browsers.new_browser_action.trigger()

    first, second = dock.browsers.browsers
    assert dock.browsers.current_browser is second
    assert dock.browsers.browser_dock(second).dockAreaWidget() is dock.browsers.browser_dock(first).dockAreaWidget()
    assert second.model.rowCount() == first.model.rowCount()


@mark.usefixtures("served")
def test_new_table_browser_offers_the_presets_and_one_starts_a_browser_as_it_says(dock: CatalogDocks) -> None:
    """New Table Browser carries a menu of the presets; an entry adds a browser named, filtered and with the columns
    the preset gives, and makes it current (#400).

    **Test steps:**

    * verify the action's menu lists the presets
    * open a catalog and trigger Reference Images Columns
    * verify the new browser is current, with the preset's name, line and hidden columns
    """
    menu = dock.browsers.presets_menu
    assert dock.browsers.new_browser_action.menu() is menu
    assert [action.text() for action in menu.actions()] == [preset.label for preset in browser_presets()]
    dock.catalog.open_rehuco(REHUCO_PATH)

    entry = next(action for action in menu.actions() if action.text() == "Reference Images Columns")
    entry.trigger()

    _, added = dock.browsers.browsers
    header = added.view.horizontalHeader()
    preset = browser_presets()[-1]
    assert dock.browsers.current_browser is added
    assert added.name == "Reference Images"
    assert added.filter_text == "type:reference_images"
    assert {column for column in CatalogColumn if header.isSectionHidden(column)} == preset.hidden


@mark.usefixtures("served")
def test_open_browsers_and_the_focused_one_follow_the_sub_docks(qtbot: QtBot, dock: CatalogDocks) -> None:
    """The Browsers menu's two reads: every browser with an open sub-dock, and the current one (#402).

    **Test steps:**

    * open a catalog, add a second browser, and verify both are open with the new one focused
    * make the first current and verify it is the focused one
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    dock.browsers.new_browser_action.trigger()
    first, second = dock.browsers.browsers

    assert dock.browsers.open_browsers() == (first, second)
    assert dock.browsers.focused_browser() is second

    make_current(qtbot, dock.browsers.browser_dock(first))

    assert dock.browsers.focused_browser() is first


@mark.usefixtures("served")
def test_focus_browser_brings_a_background_tab_to_the_front_and_makes_it_current(dock: CatalogDocks) -> None:
    """Focusing a browser fronts its tab and makes it the current sub-dock (#402).

    **Test steps:**

    * open a catalog, add a second browser and verify the first tab is behind it
    * focus the first browser
    * verify its tab is current in its area and the dock reports it focused
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    dock.browsers.new_browser_action.trigger()
    first, second = dock.browsers.browsers
    area = dock.browsers.browser_dock(first).dockAreaWidget()
    assert area is not None
    assert area.dockWidget(area.currentIndex()) is dock.browsers.browser_dock(second)

    dock.browsers.focus_browser(first)

    assert area.dockWidget(area.currentIndex()) is dock.browsers.browser_dock(first)
    assert dock.browsers.focused_browser() is first


@mark.usefixtures("served")
def test_a_root_row_menu_leads_with_the_folder_actions_then_the_moves_then_remove(dock: CatalogDocks) -> None:
    """A root's right-click menu offers the folder filter and Open in file explorer, then the four moves, then Remove
    Root -- the action the title bar and the Root Catalog menu hold (#402) -- last and apart, since it is the one that
    cannot be undone; the view asks for it itself.

    **Test steps:**

    * open a catalog and read the view's context menu policy
    * ask for the actions of the first root's row
    * verify the policy is custom, and the actions are in that order, in three groups
    """
    dock.catalog.open_rehuco(REHUCO_PATH)

    actions = dock.roots.roots_context_actions(dock.roots.roots_model.index(0, 0))

    assert dock.roots.roots_view.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu
    assert [action.isSeparator() for action in actions] == [False, False, True, False, False, False, False, True, False]
    assert actions[0] is dock.roots.filter_folder_action
    assert actions[1] is dock.roots.open_explorer_action
    assert actions[3:7] == list(dock.roots.move_root_actions)
    assert actions[8] is dock.roots.remove_root_action


@mark.usefixtures("served")
def test_rename_browser_sets_only_the_window_title(mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks) -> None:
    """A real new name becomes the tab's title; the object name the registry keys on is never touched.

    **Test steps:**

    * open a catalog, make the browser current and answer the name box with a new name
    * trigger Rename Browser
    * verify the browser's and the dock's title, and that the dock's object name is still its id
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    browser = first_browser(dock)
    sub_dock = dock.browsers.browser_dock(browser)
    ask = mocker.patch.object(dock.browsers, "ask_browser_name", return_value="  Renamed ")
    make_current(qtbot, sub_dock)

    dock.browsers.rename_browser_action.trigger()

    ask.assert_called_once_with("Browser")
    assert browser.name == "Renamed"
    assert sub_dock.windowTitle() == "Renamed"
    assert sub_dock.objectName() == str(browser.browser_id)


@mark.parametrize("answer", [None, "   ", "Browser"])
@mark.usefixtures("served")
def test_a_cancelled_blank_or_unchanged_name_renames_nothing(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, answer: str | None
) -> None:
    """Only a real, different name is a rename.

    **Test steps:**

    * open a catalog and answer the name box with a cancel, blanks or the same name
    * trigger Rename Browser
    * verify the title is unchanged
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    mocker.patch.object(dock.browsers, "ask_browser_name", return_value=answer)
    make_current(qtbot, dock.browsers.browser_dock(first_browser(dock)))

    dock.browsers.rename_browser_action.trigger()

    assert first_browser(dock).name == "Browser"
    assert dock.browsers.browser_dock(first_browser(dock)).windowTitle() == "Browser"


@mark.usefixtures("served")
def test_rename_browser_is_enabled_only_while_a_browser_is_current(qtbot: QtBot, dock: CatalogDocks) -> None:
    """Rename needs a current browser: off with no catalog, on once one is current, off again once it is closed.

    **Test steps:**

    * verify Rename is disabled with nothing open
    * open a catalog, make the browser current and verify it is enabled
    * close the browser and verify it is disabled
    """
    assert not dock.browsers.rename_browser_action.isEnabled()
    dock.catalog.open_rehuco(REHUCO_PATH)

    make_current(qtbot, dock.browsers.browser_dock(first_browser(dock)))
    assert dock.browsers.rename_browser_action.isEnabled()

    dock.browsers.browser_dock(first_browser(dock)).closeRequested.emit()
    assert not dock.browsers.rename_browser_action.isEnabled()


@mark.usefixtures("served")
def test_clone_copies_the_columns_under_a_new_id_and_name(mocker: MockerFixture, dock: CatalogDocks) -> None:
    """A clone starts with the source's header state, beside it, with a name asked for.

    **Test steps:**

    * open a catalog, widen a column and trigger the browser's Clone with a name answered
    * verify the clone's name, column width and id, that the box was offered "<name> copy", and that it is current
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    source = first_browser(dock)
    source.view.horizontalHeader().resizeSection(0, 233)
    ask = mocker.patch.object(dock.browsers, "ask_browser_name", return_value="Tutorials")

    dock.browsers.browser_dock(source).titleBarActions()[1].trigger()

    ask.assert_called_once_with("Browser copy", "Clone Browser")
    _, clone = dock.browsers.browsers
    assert clone.name == "Tutorials"
    assert clone.view.horizontalHeader().sectionSize(0) == 233
    assert clone.browser_id != source.browser_id
    assert dock.browsers.current_browser is clone


@mark.usefixtures("served")
def test_a_cancelled_clone_adds_nothing(mocker: MockerFixture, dock: CatalogDocks) -> None:
    """Cancelling the name box makes no copy.

    **Test steps:**

    * open a catalog and trigger Clone with the box cancelled
    * verify there is still one browser
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    mocker.patch.object(dock.browsers, "ask_browser_name", return_value=None)

    dock.browsers.browser_dock(first_browser(dock)).titleBarActions()[1].trigger()

    assert len(dock.browsers.browsers) == 1


@mark.usefixtures("served")
def test_closing_a_browser_deletes_it_and_its_registry_entry(dock: CatalogDocks) -> None:
    """Its [x] deletes it without asking -- a browser is only a view -- and takes the dock off the manager *and*
    out of its registry: no dangling name (#364).

    **Test steps:**

    * open a catalog, add a second browser, and request the first one's close
    * verify the first is gone from the browsers and the manager's registry
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    dock.browsers.new_browser_action.trigger()
    first, second = dock.browsers.browsers
    first_name = str(first.browser_id)
    manager = dock.browsers.findChild(QtAds.CDockManager)
    assert manager is not None

    dock.browsers.browser_dock(first).closeRequested.emit()

    assert dock.browsers.browsers == (second,)
    assert first_name not in manager.dockWidgetsMap()


@mark.usefixtures("served")
def test_a_browsers_tab_menu_lists_its_actions_above_detach(mocker: MockerFixture, dock: CatalogDocks) -> None:
    """Right-clicking a browser's tab offers Rename and Clone, a separator, then QtAds' own entries.

    **Test steps:**

    * open a catalog and right-click the browser's tab, with the popup captured
    * verify the two actions, a separator and Detach, in that order
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    mocker.patch.object(QMenu, "popup")
    event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(5, 5), QPoint(5, 5))
    sub_dock = dock.browsers.browser_dock(first_browser(dock))

    QApplication.sendEvent(sub_dock.tabWidget(), event)

    entries = sub_dock.tabWidget().findChildren(QMenu)[0].actions()
    assert [entry.text() for entry in entries[:2]] == ["Rename...", "Clone..."]
    assert entries[2].isSeparator()
    assert entries[3].text() == "Detach"


@mark.usefixtures("served")
def test_browsers_their_order_and_names_come_back_with_the_catalog(mocker: MockerFixture, dock: CatalogDocks) -> None:
    """What the catalog is closed with is what it opens with: the browsers, in order, with their names, ids and
    columns.

    **Test steps:**

    * open a catalog, rename the first browser, widen its column and add a second
    * close the catalog and open it again
    * verify both browsers with the same ids, names and column width, in the same order
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    first = first_browser(dock)
    mocker.patch.object(dock.browsers, "ask_browser_name", return_value="Everything")
    dock.browsers.browser_dock(first).titleBarActions()[0].trigger()
    first.view.horizontalHeader().resizeSection(0, 233)
    dock.browsers.new_browser_action.trigger()
    ids = [browser.browser_id for browser in dock.browsers.browsers]

    dock.catalog.close_rehuco()
    assert not dock.browsers.browsers
    dock.catalog.open_rehuco(REHUCO_PATH)

    assert [browser.browser_id for browser in dock.browsers.browsers] == ids
    assert [browser.name for browser in dock.browsers.browsers] == ["Everything", "Browser"]
    assert first_browser(dock).view.horizontalHeader().sectionSize(0) == 233


def test_two_catalogs_keep_their_own_browsers(mocker: MockerFixture, served: Any, dock: CatalogDocks) -> None:
    """Browsers are remembered by rehuco id, so another catalog neither shows nor disturbs them.

    **Test steps:**

    * open a catalog and rename its browser
    * open a catalog with another id, and verify it has a default browser
    * open the first again and verify its rename came back
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    mocker.patch.object(dock.browsers, "ask_browser_name", return_value="Mine")
    dock.browsers.browser_dock(first_browser(dock)).titleBarActions()[0].trigger()

    served["id"] = str(uuid4())
    dock.catalog.open_rehuco(OTHER_PATH)
    assert [browser.name for browser in dock.browsers.browsers] == ["Browser"]

    served["id"] = REHUCO_ID
    dock.catalog.open_rehuco(REHUCO_PATH)
    assert [browser.name for browser in dock.browsers.browsers] == ["Mine"]


def test_a_read_only_catalogs_browsers_are_remembered_too(
    served: Any, dock: CatalogDocks, catalog_store: MemoryCatalogStateStore
) -> None:
    """Browsers are the agent's state, not the file's, so a catalog from a newer build keeps them like any other.

    **Test steps:**

    * open a catalog stamped by a newer build and add a browser
    * close it
    * verify the store holds both browsers
    """
    served["format_version"] = 999
    dock.catalog.open_rehuco(REHUCO_PATH)
    assert dock.browsers.new_browser_action.isEnabled()
    dock.browsers.new_browser_action.trigger()

    dock.catalog.close_rehuco()

    states = catalog_store.states
    assert len(states[UUID(REHUCO_ID)].browsers) == 2


@mark.usefixtures("served")
def test_a_layout_naming_a_browser_that_is_gone_restores_without_crashing(
    dock: CatalogDocks, catalog_store: MemoryCatalogStateStore
) -> None:
    """The layout was saved with two browsers; the store now lists one. Opening restores what it can and shows
    every browser it builds.

    **Test steps:**

    * open a catalog with two browsers, close it, and drop the second from the store, keeping the layout
    * open it again
    * verify the one browser is shown
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    dock.browsers.new_browser_action.trigger()
    dock.catalog.close_rehuco()
    states = catalog_store.states
    states[UUID(REHUCO_ID)].browsers.pop()

    dock.catalog.open_rehuco(REHUCO_PATH)

    assert len(dock.browsers.browsers) == 1
    assert not dock.browsers.browser_dock(first_browser(dock)).isClosed()
    assert is_on_screen(dock, first_browser(dock))


# endregion

# region Guards and failures the views never reach on their own


@mark.usefixtures("served")
def test_a_cache_whose_roots_cannot_be_reconciled_does_not_open(mocker: MockerFixture, dock: CatalogDocks) -> None:
    """A cache that opens but cannot be written is closed again, and the open fails with the reason.

    **Test steps:**

    * make ``reconcile_roots`` raise, and spy on ``close``
    * open a catalog
    * verify it failed naming the cache, and the cache was closed
    """
    mocker.patch.object(CatalogCache, "reconcile_roots", side_effect=sqlite3.OperationalError("locked"))
    close = mocker.spy(CatalogCache, "close")

    assert not dock.catalog.open_rehuco(REHUCO_PATH)

    assert "Could not read the cache" in dock.catalog.load_error
    assert dock.catalog.rehuco_path is None
    close.assert_called_once()


@mark.usefixtures("served", "saves")
def test_a_cache_that_cannot_be_read_keeps_what_is_shown(
    mocker: MockerFixture, dock: CatalogDocks, caplog: LogCaptureFixture
) -> None:
    """A failed read is logged and the browsers are left as they were -- the next scan rebuilds the cache. The Roots
    view reads the file, not the cache, so it still shows the edit (#461).

    **Test steps:**

    * open a catalog, then make ``rows`` raise and spy on the browsers
    * add a root through the picker, which re-reads
    * verify an error was logged, no browser was refilled, and the Roots view lists the new root
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    mocker.patch.object(CatalogCache, "rows", side_effect=sqlite3.OperationalError("locked"))
    set_rows = mocker.spy(TableBrowser, "set_rows")
    answer_add_root(mocker, dock, "/fake/refs")

    with caplog.at_level(logging.ERROR):
        dock.roots.add_root_action.trigger()

    assert "Could not read the cache" in caplog.text
    set_rows.assert_not_called()
    assert shown_labels(dock) == ["tutorials", "packs", "refs"]


@mark.usefixtures("served")
def test_a_double_click_on_no_row_opens_nothing(qtbot: QtBot, dock: CatalogDocks) -> None:
    """An invalid index -- a double-click on the empty area -- asks for nothing.

    **Test steps:**

    * open a catalog and emit a double-click with an invalid index
    * verify no open was requested
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    with qtbot.assertNotEmitted(dock.browsers.open_requested):
        first_browser(dock).view.doubleClicked.emit(QModelIndex())


def test_the_root_edits_do_nothing_with_no_catalog_open(mocker: MockerFixture, dock: CatalogDocks) -> None:
    """The slots behind the disabled actions refuse on their own too, so a stray trigger cannot edit nothing.

    **Test steps:**

    * spy on the Add Root question, then call the add and remove slots with nothing open
    * verify the question never opened and nothing was written
    """
    picker = answer_add_root(mocker, dock, "/fake/refs")
    saves = mocker.patch("rehuco_core.rehuco_file.atomic_write_text")

    dock.roots._RootsPanel__on_add_root()  # type: ignore[attr-defined]  # pylint: disable=protected-access
    dock.roots._RootsPanel__on_remove_root()  # type: ignore[attr-defined]  # pylint: disable=protected-access
    dock.catalog.scan()

    picker.assert_not_called()
    saves.assert_not_called()


def test_the_browser_slots_do_nothing_with_nothing_to_act_on(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks
) -> None:
    """The slots behind the disabled New and Rename actions refuse on their own too.

    **Test steps:**

    * call the new, rename, close and fill slots with no catalog open, and with a dock that holds no browser
    * verify no browser appeared, the name box never opened, the unfilled browser has no rows and nothing raised
    """
    ask = mocker.patch.object(dock.browsers, "ask_browser_name")
    manager = dock.browsers.findChild(QtAds.CDockManager)
    assert manager is not None
    stranger = QtAds.CDockWidget(manager, "stranger")
    qtbot.addWidget(stranger)
    stray = TableBrowser()
    qtbot.addWidget(stray)

    dock.browsers._BrowsersDock__on_new_browser()  # type: ignore[attr-defined]  # pylint: disable=protected-access
    dock.browsers._BrowsersDock__on_rename_current_browser()  # type: ignore[attr-defined]  # pylint: disable=protected-access
    dock.browsers._BrowsersDock__close_browser(stranger)  # type: ignore[attr-defined]  # pylint: disable=protected-access
    dock.browsers._BrowsersDock__fill(stray)  # type: ignore[attr-defined]  # pylint: disable=protected-access

    assert not dock.browsers.browsers
    ask.assert_not_called()
    assert stray.model.rowCount() == 0


@mark.usefixtures("served")
def test_a_new_browser_whose_rows_cannot_be_read_is_still_added(
    mocker: MockerFixture, dock: CatalogDocks, caplog: LogCaptureFixture
) -> None:
    """A failed read is logged and the new browser starts empty -- the next scan rebuilds the cache.

    **Test steps:**

    * open a catalog, make ``rows`` raise and trigger New Table Browser
    * verify an error was logged and the browser exists, with no rows
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    mocker.patch.object(CatalogCache, "rows", side_effect=sqlite3.OperationalError("locked"))

    with caplog.at_level(logging.ERROR):
        dock.browsers.new_browser_action.trigger()

    assert "Could not read the cache" in caplog.text
    _, added = dock.browsers.browsers
    assert added.model.rowCount() == 0


@mark.parametrize(("accepted", "expected"), [(True, "Typed"), (False, None)])
def test_ask_browser_name_returns_the_typed_name_or_none(
    mocker: MockerFixture, dock: CatalogDocks, accepted: bool, expected: str | None
) -> None:
    """The real name box yields its text when accepted and ``None`` when cancelled, opened on the offered name.

    **Test steps:**

    * patch ``QInputDialog.getText`` to accept, then to cancel
    * verify the name or ``None``, and that the box was given the title and the current name
    """
    get_text = mocker.patch("rehuco_agent.rehuco.browsers_dock.QInputDialog.getText", return_value=("Typed", accepted))

    assert dock.browsers.ask_browser_name("Current", "Clone Browser") == expected
    assert get_text.call_args.args[1] == "Clone Browser"
    assert get_text.call_args.kwargs["text"] == "Current"


@mark.usefixtures("served")
def test_removing_with_no_root_selected_does_nothing(dock: CatalogDocks, saves: MagicMock) -> None:
    """The remove slot with no selection writes nothing.

    **Test steps:**

    * open a catalog without selecting a root, call the remove slot
    * verify nothing was written and both roots remain
    """
    dock.catalog.open_rehuco(REHUCO_PATH)

    dock.roots._RootsPanel__on_remove_root()  # type: ignore[attr-defined]  # pylint: disable=protected-access

    saves.assert_not_called()
    assert dock.roots.roots_model.rowCount() == 2


@mark.usefixtures("served")
def test_a_removal_whose_save_fails_queues_no_job(
    mocker: MockerFixture, dock: CatalogDocks, queue: TaskQueue, saves: MagicMock
) -> None:
    """The cache keeps the root the file still has.

    **Test steps:**

    * open a catalog, select a root, make the write fail and remove
    * verify no job was queued and the list is back to two roots
    """
    mocker.patch("rehuco_agent.rehuco.roots_panel.QMessageBox.warning")
    saves.side_effect = PermissionError("read-only folder")
    dock.catalog.open_rehuco(REHUCO_PATH)
    select_root(dock, 0)

    dock.roots.remove_root_action.trigger()

    assert not queue.jobs()
    assert dock.roots.roots_model.rowCount() == 2


@mark.usefixtures("served", "saves")
def test_a_cache_that_cannot_take_a_new_root_is_logged(
    mocker: MockerFixture, dock: CatalogDocks, caplog: LogCaptureFixture
) -> None:
    """The file is saved either way; the cache is disposable, so the failure is a log line.

    **Test steps:**

    * open a catalog, then make the cache's root reconciliation fail and add a root
    * verify the root is listed and the failure was logged
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    mocker.patch.object(CatalogCache, "reconcile_roots", side_effect=sqlite3.OperationalError("locked"))
    answer_add_root(mocker, dock, "/fake/refs")

    with caplog.at_level(logging.ERROR):
        dock.roots.add_root_action.trigger()

    assert "Could not update the cache" in caplog.text
    assert dock.roots.roots_model.rowCount() == 3


@mark.usefixtures("served")
def test_a_tracked_job_cleared_from_the_queue_reads_the_table_again(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, queue: TaskQueue, held: GateJob
) -> None:
    """A job the user cleared will say nothing more, so its removal is the moment to read back; a reorder, a
    pause and the removal of a job that is not this dock's say nothing at all.

    **Test steps:**

    * hold the queue, open and scan, spy on ``set_rows``
    * tell the dock the jobs were reordered, the queue paused, and a stranger removed; then remove the jobs
    * verify only the removal of its own jobs re-read the rows
    """
    scan_finding(mocker, {})
    dock.catalog.open_rehuco(REHUCO_PATH)
    dock.roots.scan_action.trigger()
    serials = [status.serial for status in queue.jobs()[1:]]
    set_rows = mocker.spy(TableBrowser, "set_rows")

    dock.catalog.jobs_reordered(serials)
    dock.catalog.queue_paused_changed(True)
    dock.catalog.jobs_removed([999])
    qtbot.wait(50)
    assert set_rows.call_count == 0

    for serial in serials:
        queue.remove(serial)
    qtbot.waitUntil(lambda: set_rows.call_count == 1, timeout=WAIT_TIMEOUT_MS)
    held.let_finish()


# endregion


# region Following the app's own file changes (#376)


@fixture(name="followed")
def fixture_followed(
    qtbot: QtBot, mocker: MockerFixture, queue: TaskQueue, database: MemoryDatabase, served: Any
) -> Generator[tuple[CatalogDocks, ResourceEvents]]:
    """A dock following the app's file announcements, its catalog open and one tutorial scanned in.

    :param qtbot: pytest-qt fixture.
    :param mocker: pytest-mock fixture.
    :param queue: the queue its scan runs on.
    :param database: the cache's database.
    :param served: the served ``.rehuco``.
    :yields: the dock and the events it follows.
    """
    del database, served
    events = ResourceEvents()
    dock = build_docks(qtbot, queue, events)
    scan_finding(mocker, {TUTORIALS: (tutorial_record(),)})
    dock.catalog.open_rehuco(REHUCO_PATH)
    dock.roots.scan_action.trigger()
    qtbot.waitUntil(lambda: first_browser(dock).model.rowCount() == 1, timeout=WAIT_TIMEOUT_MS)
    wait_for_jobs(qtbot, queue)
    yield dock, events
    dock.detach()


def shown_path(dock: CatalogDocks) -> str:
    """The root-qualified path the one row shows."""
    return first_browser(dock).model.index(0, CatalogColumn.PATH).data()


def test_a_rename_rebases_its_row_without_a_scan(followed: tuple[CatalogDocks, ResourceEvents]) -> None:
    """A renamed folder's record keeps its row, under the new path, with nothing read.

    **Test steps:**

    * announce the rename of the scanned tutorial's folder
    * verify the row now shows the new path
    """
    dock, events = followed

    events.announce_moved(Relocation(((TUTORIALS / "python", TUTORIALS / "py"),)))

    assert shown_path(dock) == "tutorials/py/info.rehu"


def test_a_rename_elsewhere_reads_the_cache_not_again(
    mocker: MockerFixture, followed: tuple[CatalogDocks, ResourceEvents]
) -> None:
    """A rename that moved no row leaves the table alone, and an empty one is not even looked at.

    **Test steps:**

    * announce an unrelated rename and an empty one
    * verify the table was not read again
    """
    _, events = followed
    set_rows = mocker.spy(TableBrowser, "set_rows")

    events.announce_moved(Relocation(((Path("/fake/elsewhere/a"), Path("/fake/elsewhere/b")),)))
    events.announce_moved(Relocation())

    assert set_rows.call_count == 0


def test_a_written_record_is_read_back_into_its_row(
    mocker: MockerFixture, followed: tuple[CatalogDocks, ResourceEvents]
) -> None:
    """A save is reflected in the table at once, the record read back through the updater; a file that is not a
    record is passed over.

    **Test steps:**

    * make the record read as retitled, and announce it and a screenshot as written
    * verify the row shows the new title
    """
    dock, events = followed
    mocker.patch.object(Path, "is_file", autospec=True, return_value=True)
    mocker.patch(
        "rehuco_core.rehudb_updates.CatalogRecordReader.read",
        return_value=CatalogRecord(
            "python/info.rehu", RecordKind.REHU, title="Python 3", type="tutorial", current_size=1536, content_hash="1"
        ),
    )

    events.announce_changed((TUTORIALS / "python" / "info.rehu", TUTORIALS / "python" / "info00.jpg"))

    assert first_browser(dock).model.index(0, CatalogColumn.TITLE).data() == "Python 3"


def test_a_rename_moves_the_row_in_place_and_keeps_it_selected(
    qtbot: QtBot, followed: tuple[CatalogDocks, ResourceEvents]
) -> None:
    """A rename changes the row where it stands: no reset, the selection kept, the current resource renamed (#379).

    **Test steps:**

    * select the one row, then announce its folder renamed
    * verify no reset, the row still selected, and the new key announced as current
    """
    dock, events = followed
    browser = first_browser(dock)
    browser.view.selectRow(0)

    with qtbot.assertNotEmitted(browser.model.modelReset), qtbot.waitSignal(browser.current_changed) as changed:
        events.announce_moved(Relocation(((TUTORIALS / "python", TUTORIALS / "py"),)))

    assert changed.args is not None
    (current,) = changed.args
    assert current is not None
    root_id, relative = current
    assert relative == "py/info.rehu"
    assert browser.current_resource == (root_id, "py/info.rehu")
    assert browser.view.selectionModel().isRowSelected(0, QModelIndex())


def test_a_written_record_changes_its_row_without_a_reset(
    qtbot: QtBot, mocker: MockerFixture, followed: tuple[CatalogDocks, ResourceEvents]
) -> None:
    """A save reads back just its own row, and the table changes it in place (#379).

    **Test steps:**

    * make the record read as retitled, and announce it written
    * verify no reset and the new title
    """
    dock, events = followed
    model = first_browser(dock).model
    mocker.patch.object(Path, "is_file", autospec=True, return_value=True)
    mocker.patch(
        "rehuco_core.rehudb_updates.CatalogRecordReader.read",
        return_value=CatalogRecord("python/info.rehu", RecordKind.REHU, title="Python 3", type="tutorial"),
    )

    with qtbot.assertNotEmitted(model.modelReset):
        events.announce_changed((TUTORIALS / "python" / "info.rehu",))

    assert model.index(0, CatalogColumn.TITLE).data() == "Python 3"


def test_a_deleted_record_leaves_the_table_in_place(
    qtbot: QtBot, mocker: MockerFixture, followed: tuple[CatalogDocks, ResourceEvents]
) -> None:
    """A record gone from a root that is there loses its row, and only that row goes (#379).

    **Test steps:**

    * make the record missing under an online root, and announce it changed
    * verify the row was removed without a reset
    """
    dock, events = followed
    model = first_browser(dock).model
    mocker.patch.object(Path, "is_file", autospec=True, return_value=False)
    mocker.patch.object(Path, "is_dir", autospec=True, return_value=True)

    with qtbot.assertNotEmitted(model.modelReset), qtbot.waitSignal(model.rowsRemoved):
        events.announce_changed((TUTORIALS / "python" / "info.rehu",))

    assert model.rowCount() == 0


def test_a_rename_out_of_a_folder_filter_removes_the_row(
    qtbot: QtBot, followed: tuple[CatalogDocks, ResourceEvents]
) -> None:
    """Each browser reads the touched rows with its own query, so a row renamed out of what it filters leaves it.

    **Test steps:**

    * filter the browser to the tutorial's folder, then rename that folder
    * verify the row was removed without a reset
    """
    dock, events = followed
    browser = first_browser(dock)
    browser.set_filter_text('folder:"tutorials/python"')
    qtbot.waitUntil(lambda: browser.model.rowCount() == 1, timeout=WAIT_TIMEOUT_MS)

    with qtbot.assertNotEmitted(browser.model.modelReset):
        events.announce_moved(Relocation(((TUTORIALS / "python", TUTORIALS / "py"),)))

    assert browser.model.rowCount() == 0


def test_browsers_filtering_alike_share_one_read_of_the_touched_rows(
    mocker: MockerFixture, followed: tuple[CatalogDocks, ResourceEvents]
) -> None:
    """Two browsers with one query are updated from one read of the rows a rename touched.

    **Test steps:**

    * add a second browser, then announce the tutorial's folder renamed
    * verify both show the new path, read once
    """
    dock, events = followed
    dock.browsers.new_browser_action.trigger()
    rows = mocker.spy(CatalogCache, "rows")

    events.announce_moved(Relocation(((TUTORIALS / "python", TUTORIALS / "py"),)))

    assert {browser.model.index(0, CatalogColumn.PATH).data() for browser in dock.browsers.browsers} == {
        "tutorials/py/info.rehu"
    }
    assert rows.call_count == 1


def test_a_failed_read_of_the_touched_rows_is_logged_and_the_table_kept(
    mocker: MockerFixture, followed: tuple[CatalogDocks, ResourceEvents], caplog: LogCaptureFixture
) -> None:
    """The rename is in the cache; a failure to read its rows back leaves the table as it was, logged.

    **Test steps:**

    * make the cache refuse to read rows, and announce a rename
    * verify the error was logged and the row still shows its old path
    """
    dock, events = followed
    mocker.patch.object(CatalogCache, "rows", side_effect=sqlite3.OperationalError("locked"))
    caplog.set_level(logging.ERROR, logger="rehuco_agent.rehuco.rehuco_dock")

    events.announce_moved(Relocation(((TUTORIALS / "python", TUTORIALS / "py"),)))

    assert "locked" in caplog.text
    assert shown_path(dock) == "tutorials/python/info.rehu"


def test_a_cache_failure_while_following_is_logged(
    mocker: MockerFixture, followed: tuple[CatalogDocks, ResourceEvents], caplog: LogCaptureFixture
) -> None:
    """The cache is disposable and the next scan rebuilds it, so a failure to follow is a log line.

    **Test steps:**

    * make the cache refuse a relocation and an upsert, and announce both
    * verify each was logged as an error
    """
    _dock, events = followed
    mocker.patch.object(CatalogCache, "apply_relocation", side_effect=sqlite3.OperationalError("locked"))
    mocker.patch.object(CatalogCache, "locate", side_effect=sqlite3.OperationalError("locked"))
    caplog.set_level(logging.ERROR, logger="rehuco_agent.rehuco.rehuco_dock")

    events.announce_moved(Relocation(((TUTORIALS / "python", TUTORIALS / "py"),)))
    events.announce_changed((TUTORIALS / "python" / "info.rehu",))

    assert caplog.text.count("locked") == 2


def test_with_nothing_open_an_announcement_is_nothing(qtbot: QtBot, queue: TaskQueue, database: MemoryDatabase) -> None:
    """A dock with no catalog open has no cache to follow anything into.

    **Test steps:**

    * announce a rename and a write to a dock with nothing open, then detach it
    * verify nothing failed and no browser appeared
    """
    del database
    events = ResourceEvents()
    dock = build_docks(qtbot, queue, events)

    events.announce_moved(Relocation(((TUTORIALS, PACKS),)))
    events.announce_changed((TUTORIALS / "info.rehu",))
    dock.detach()
    events.announce_changed((TUTORIALS / "info.rehu",))

    assert not dock.browsers.browsers


def is_on_screen(dock: CatalogDocks, browser: TableBrowser) -> bool:
    """Whether ``browser``'s sub-dock is open in an area its manager shows.

    :param dock: the catalog's docks.
    :param browser: one of its browsers.
    :returns: whether a reader can see it.
    """
    sub_dock = dock.browsers.browser_dock(browser)
    manager = dock.browsers.findChild(QtAds.CDockManager)
    assert manager is not None
    return not sub_dock.isClosed() and sub_dock.dockAreaWidget() in manager.openedDockAreas()


@mark.usefixtures("served")
def test_after_every_browser_was_closed_a_reopen_and_new_browser_show_on_screen(dock: CatalogDocks) -> None:
    """A layout saved with no browser left must not swallow the browsers built after it: the restore used to leave
    the default browser in an area off the manager, and every New Table Browser joined that invisible area.

    **Test steps:**

    * open a catalog, close its only browser, close the catalog and open it again
    * verify the default browser is on screen
    * trigger New Table Browser and verify both browsers are on screen
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    dock.browsers.browser_dock(first_browser(dock)).closeRequested.emit()
    dock.catalog.close_rehuco()

    dock.catalog.open_rehuco(REHUCO_PATH)
    assert is_on_screen(dock, first_browser(dock))

    dock.browsers.new_browser_action.trigger()
    assert all(is_on_screen(dock, browser) for browser in dock.browsers.browsers)


@mark.usefixtures("served")
def test_new_browser_after_closing_every_browser_shows_on_screen(dock: CatalogDocks) -> None:
    """With no browser left, a new one is placed beside the Roots view.

    **Test steps:**

    * open a catalog and close its only browser
    * trigger New Table Browser
    * verify one browser, on screen
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    dock.browsers.browser_dock(first_browser(dock)).closeRequested.emit()

    dock.browsers.new_browser_action.trigger()

    assert len(dock.browsers.browsers) == 1
    assert is_on_screen(dock, first_browser(dock))


# endregion

# region The filter line


def authored_record(path: str, author: str) -> CatalogRecord:
    """A readable ``.rehu`` record by one author, as a scan of the tutorials root finds it.

    :param path: its path under the root.
    :param author: its author.
    :returns: the record.
    """
    return CatalogRecord(
        path, RecordKind.REHU, title=path, type="tutorial", authors=(author,), current_size=1, content_hash=path
    )


@mark.usefixtures("served")
def test_each_browser_shows_the_rows_its_own_filter_matches(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, queue: TaskQueue
) -> None:
    """A filter narrows its own browser only, at once, and is kept when the rows are read again (#398).

    **Test steps:**

    * open a catalog with a second browser and scan in two records by different authors
    * filter the first browser on one author
    * verify it shows one row while the second still shows both
    * scan again, now finding a third record by the filtered author
    * verify the first shows its two rows and the second all three
    """
    scan_finding(
        mocker, {TUTORIALS: (authored_record("a/info.rehu", "Foo Bar"), authored_record("b/info.rehu", "Baz"))}
    )
    dock.catalog.open_rehuco(REHUCO_PATH)
    dock.browsers.new_browser_action.trigger()
    first, second = dock.browsers.browsers
    dock.roots.scan_action.trigger()
    qtbot.waitUntil(lambda: second.model.rowCount() == 2, timeout=WAIT_TIMEOUT_MS)
    wait_for_jobs(qtbot, queue)

    first.set_filter_text('authors:"Foo Bar"')

    assert (first.model.rowCount(), second.model.rowCount()) == (1, 2)

    scan_finding(
        mocker,
        {
            TUTORIALS: (
                authored_record("a/info.rehu", "Foo Bar"),
                authored_record("b/info.rehu", "Baz"),
                authored_record("c/info.rehu", "Foo Bar"),
            )
        },
    )
    dock.roots.scan_action.trigger()
    qtbot.waitUntil(lambda: second.model.rowCount() == 3, timeout=WAIT_TIMEOUT_MS)
    wait_for_jobs(qtbot, queue)

    assert first.model.rowCount() == 2


@mark.usefixtures("served")
def test_a_filter_link_lands_on_the_current_browser(dock: CatalogDocks) -> None:
    """``filter://authors?name=Foo%20Bar`` sets ``authors:"Foo Bar"`` on the current browser, which stays current
    ([[plugins#filter-urls]]).

    **Test steps:**

    * open a catalog and add a second browser, which is then current
    * apply an authors link; verify the second browser's line carries it and the first's does not
    * apply a tags link
    * verify the second browser carries both tokens and is still current
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    dock.browsers.new_browser_action.trigger()
    first, second = dock.browsers.browsers

    assert dock.browsers.apply_filter_url("filter://authors?name=Foo%20Bar")
    assert (first.filter_text, second.filter_text) == ("", 'authors:"Foo Bar"')

    assert dock.browsers.apply_filter_url("filter://tags?name=python")

    assert second.filter_text == 'authors:"Foo Bar" tags:python'
    assert dock.browsers.current_browser is second


@mark.usefixtures("served")
def test_a_filter_link_with_every_browser_closed_opens_a_default_browser_carrying_it(dock: CatalogDocks) -> None:
    """With nothing to filter, a link opens a browser to filter instead of doing nothing.

    **Test steps:**

    * open a catalog and close its only browser
    * apply an authors link
    * verify one new default browser, current and on screen, carrying the token
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    dock.browsers.browser_dock(first_browser(dock)).closeRequested.emit()

    assert dock.browsers.apply_filter_url("filter://authors?name=Foo%20Bar")

    browser = first_browser(dock)
    assert len(dock.browsers.browsers) == 1
    assert (browser.name, browser.filter_text) == (TableBrowser.DEFAULT_NAME, 'authors:"Foo Bar"')
    assert dock.browsers.current_browser is browser
    assert is_on_screen(dock, browser)


def test_a_filter_link_with_no_catalog_open_or_naming_no_filter_sets_nothing(
    served: Any, dock: CatalogDocks, caplog: LogCaptureFixture
) -> None:
    """Nothing is set with no catalog to filter, nor for a link that is not a filter, which is logged.

    **Test steps:**

    * apply an authors link with nothing open; verify it was not set
    * open a catalog and apply a link naming a field no link filters on
    * verify it was not set, its browser's line is empty, and the link was logged
    """
    del served
    assert not dock.browsers.apply_filter_url("filter://authors?name=Foo")

    dock.catalog.open_rehuco(REHUCO_PATH)
    with caplog.at_level(logging.WARNING, logger="rehuco_agent.rehuco.rehuco_dock"):
        assert not dock.browsers.apply_filter_url("filter://colour?name=red")

    assert first_browser(dock).filter_text == ""
    assert "filter://colour?name=red" in caplog.text


@mark.usefixtures("served")
def test_a_filter_set_from_the_dock_replaces_that_fields_token(dock: CatalogDocks) -> None:
    """The Roots view's folder filter, through the same seam: one folder at a time, the rest of the line kept.

    **Test steps:**

    * open a catalog and type free text and a folder on its browser
    * set another folder from the dock
    * verify the line keeps the text and carries only the new folder
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    browser = first_browser(dock)
    browser.set_filter_text("intro folder:packs")

    assert dock.browsers.set_filter_token(CatalogField.FOLDER, "tutorials/python")

    assert browser.filter_text == "intro folder:tutorials/python"


# endregion


# region The Roots view


@fixture(name="folders")
def fixture_folders(served: dict[str, Any]) -> Generator[Path]:
    """Point both served roots at real folders: ``tutorials`` holds ``alpha`` (with ``sub`` and a note) and a folder
    with a space in its name; ``packs`` is empty.

    Not under ``tmp_path``: the ``database`` fixture replaces ``Path.mkdir``, which is what pytest makes that folder
    with, so the folders are made with :func:`os.makedirs` in a directory of their own.

    :param served: the served ``.rehuco``.
    :yields: the ``tutorials`` folder, with everything removed when the test ends.
    """
    with tempfile.TemporaryDirectory() as base:
        tutorials, packs = Path(base) / "tutorials", Path(base) / "packs"
        os.makedirs(tutorials / "alpha" / "sub")
        os.makedirs(tutorials / "my folder")
        os.makedirs(packs)
        (tutorials / "alpha" / "note.txt").write_text("n", encoding="utf-8")
        served["roots"][0]["path"] = str(tutorials)
        served["roots"][1]["path"] = str(packs)
        yield tutorials


def child_names(dock: CatalogDocks, parent: QModelIndex) -> list[str]:
    """The names of the rows under a row of the Roots view.

    :param dock: the catalog's docks.
    :param parent: the row.
    :returns: the names, in order.
    """
    model = dock.roots.roots_model
    return [model.index(row, 0, parent).data() for row in range(model.rowCount(parent))]


def wait_for_root_listing(qtbot: QtBot, dock: CatalogDocks, index: QModelIndex) -> None:
    """Wait until a root or folder of the Roots view has been listed.

    :param qtbot: pytest-qt fixture.
    :param dock: the catalog's docks.
    :param index: the root or folder.
    """
    qtbot.waitUntil(
        lambda: dock.roots.roots_model.listing_state(index) in (NodeListing.LISTED, NodeListing.UNREACHABLE),
        timeout=WAIT_TIMEOUT_MS,
    )


def open_root_folder(qtbot: QtBot, dock: CatalogDocks, *names: str) -> QModelIndex:
    """Make a folder of the first root the Roots view's current row, listing each folder on the way as a column does.

    :param qtbot: pytest-qt fixture.
    :param dock: the Root Catalog dock, with a catalog open.
    :param names: the folder names down from the first root.
    :returns: the folder's index.
    """
    model = dock.roots.roots_model
    index = model.index(0, 0)
    for name in names:
        wait_for_root_listing(qtbot, dock, index)
        rows = [model.index(row, 0, index) for row in range(model.rowCount(index))]
        index = next(row for row in rows if row.data() == name)
        dock.roots.roots_view.setCurrentIndex(index)
    if dock.roots.roots_model.node_kind(index) in (RootsNodeKind.ROOT, RootsNodeKind.FOLDER):
        wait_for_root_listing(qtbot, dock, index)
    return index


@mark.usefixtures("served")
def test_the_roots_view_lists_folders_when_a_column_opens(qtbot: QtBot, dock: CatalogDocks, folders: Path) -> None:
    """Selecting a root opens its folders, and a folder opens its own: the view fetches them itself.

    **Test steps:**

    * open a catalog over real folders and select the first root
    * verify its folders are listed, then select ``alpha`` and verify its subfolder and note
    """
    del folders
    dock.catalog.open_rehuco(REHUCO_PATH)

    select_root(dock, 0)
    root = dock.roots.roots_model.index(0, 0)
    wait_for_root_listing(qtbot, dock, root)
    alpha = open_root_folder(qtbot, dock, "alpha")

    assert [dock.roots.roots_model.index(row, 0, root).data() for row in range(2)] == ["alpha", "my folder"]
    assert [dock.roots.roots_model.index(row, 0, alpha).data() for row in range(2)] == ["sub", "note.txt"]


@mark.usefixtures("served")
def test_an_unreachable_root_is_a_state_the_view_shows_unclicked(qtbot: QtBot, dock: CatalogDocks) -> None:
    """The served roots point at folders that do not exist: both list as away at once, without being selected.

    **Test steps:**

    * open the catalog whose roots' folders are missing
    * verify both roots become unreachable
    """
    dock.catalog.open_rehuco(REHUCO_PATH)

    for row in range(2):
        index = dock.roots.roots_model.index(row, 0)
        qtbot.waitUntil(
            lambda index=index: dock.roots.roots_model.listing_state(index) is NodeListing.UNREACHABLE,
            timeout=WAIT_TIMEOUT_MS,
        )


@mark.usefixtures("served")
def test_the_root_actions_follow_the_current_row(qtbot: QtBot, dock: CatalogDocks, folders: Path) -> None:
    """Remove and the moves act on a **root row** only, the moves not at the end they move towards; the folder filter
    takes a root or a folder; nothing is enabled with no current row.

    **Test steps:**

    * open a catalog and read the actions with no current row
    * select the first root, the second, then a folder, reading them each time
    * verify each state
    """
    del folders
    to_top, up, down, to_bottom = dock.roots.move_root_actions
    dock.catalog.open_rehuco(REHUCO_PATH)
    assert not any(
        a.isEnabled()
        for a in (dock.roots.remove_root_action, to_top, up, down, to_bottom, dock.roots.filter_folder_action)
    )
    assert dock.roots.refresh_roots_action.isEnabled()

    select_root(dock, 0)
    assert [a.isEnabled() for a in (dock.roots.remove_root_action, to_top, up, down, to_bottom)] == [
        True,
        False,
        False,
        True,
        True,
    ]
    assert dock.roots.filter_folder_action.isEnabled()

    select_root(dock, 1)
    assert [a.isEnabled() for a in (to_top, up, down, to_bottom)] == [True, True, False, False]

    open_root_folder(qtbot, dock, "alpha")
    assert not any(a.isEnabled() for a in (dock.roots.remove_root_action, to_top, up, down, to_bottom))
    assert dock.roots.filter_folder_action.isEnabled()


def test_a_read_only_file_turns_the_root_edits_off_but_not_refresh_or_the_filter(
    dock: CatalogDocks, served: Any, folders: Path
) -> None:
    """Nothing that would write the file is on for a newer one; browsing and filtering still are.

    **Test steps:**

    * open a newer file and select the first root
    * verify the edits, the moves and the card are off, and Refresh and the folder filter are on
    """
    del folders
    served["format_version"] = 99
    dock.catalog.open_rehuco(REHUCO_PATH)

    select_root(dock, 0)

    assert not any(
        a.isEnabled()
        for a in (dock.roots.add_root_action, dock.roots.remove_root_action, *dock.roots.move_root_actions)
    )
    assert dock.roots.refresh_roots_action.isEnabled()
    assert dock.roots.filter_folder_action.isEnabled()
    assert not dock.roots.root_name_edit.isEnabled()
    assert not dock.roots.root_storage_combo.isEnabled()


def written_storages(saves: MagicMock) -> list[str]:
    """The root storages of the last ``.rehuco`` written.

    :param saves: the mock standing in for ``atomic_write_text``.
    :returns: each root's storage, in file order.
    """
    return [root["storage"] for root in json.loads(saves.call_args[0][1])["roots"]]


@mark.usefixtures("served")
def test_a_move_is_saved_and_the_moved_root_stays_current(dock: CatalogDocks, saves: MagicMock) -> None:
    """The file is reordered at once and the root the reader moved is still the one selected.

    **Test steps:**

    * select the second root and move it to the top, then down, then to the bottom, then up
    * verify the saved order after each, and that the same root is current throughout
    """
    to_top, up, down, to_bottom = dock.roots.move_root_actions
    dock.catalog.open_rehuco(REHUCO_PATH)
    select_root(dock, 1)

    for action, expected in ((to_top, ["packs", "tutorials"]), (down, ["tutorials", "packs"])):
        action.trigger()
        assert written_roots(saves) == expected
        assert shown_labels(dock) == expected
        assert getattr(dock.roots.roots_model.root_at(dock.roots.roots_view.currentIndex()), "label", "") == "packs"
    to_top.trigger()
    to_bottom.trigger()
    up.trigger()
    assert written_roots(saves) == ["packs", "tutorials"]
    assert getattr(dock.roots.roots_model.root_at(dock.roots.roots_view.currentIndex()), "label", "") == "packs"


@mark.usefixtures("served")
def test_a_move_whose_save_fails_is_undone_on_screen(
    mocker: MockerFixture, dock: CatalogDocks, saves: MagicMock
) -> None:
    """The file is read back, so what is shown is what is on disk.

    **Test steps:**

    * select the second root and move it up while the write fails
    * verify a warning and the roots back in their saved order
    """
    warning = mocker.patch("rehuco_agent.rehuco.roots_panel.QMessageBox.warning")
    saves.side_effect = PermissionError("read-only folder")
    dock.catalog.open_rehuco(REHUCO_PATH)
    select_root(dock, 1)

    _to_top, up, _down, _to_bottom = dock.roots.move_root_actions
    up.trigger()

    warning.assert_called_once()
    assert shown_labels(dock) == ["tutorials", "packs"]


def test_a_move_with_no_root_selected_does_nothing(dock: CatalogDocks, served: Any, saves: MagicMock) -> None:
    """The slot behind a disabled move refuses on its own too.

    **Test steps:**

    * open a catalog selecting nothing, and trigger the moves anyway
    * verify nothing was written
    """
    del served
    dock.catalog.open_rehuco(REHUCO_PATH)

    for action in dock.roots.move_root_actions:
        action.trigger()

    saves.assert_not_called()


@mark.usefixtures("served")
def test_the_root_editors_show_for_a_root_row_only(qtbot: QtBot, dock: CatalogDocks, folders: Path) -> None:
    """The details pane edits a root when the root itself is current: the name and storage show with its values, and
    are hidden for a folder, a file and no row.

    **Test steps:**

    * open a catalog and read the editors with no row current
    * select the second root, then a folder of the first
    * verify the editors are hidden, shown with the root's label and storage, and hidden again
    """
    del folders
    dock.catalog.open_rehuco(REHUCO_PATH)
    dock.roots.show()
    assert dock.roots.root_name_edit.isHidden()
    assert dock.roots.root_storage_combo.isHidden()

    select_root(dock, 1)
    assert not dock.roots.root_name_edit.isHidden()
    assert dock.roots.root_name_edit.text() == "packs"
    assert dock.roots.root_name_edit.isEnabled()
    assert dock.roots.root_storage_combo.currentData() == RootStorage.LOCAL

    open_root_folder(qtbot, dock, "alpha", "sub")
    assert dock.roots.root_name_edit.isHidden()
    assert dock.roots.root_storage_combo.isHidden()


@mark.usefixtures("served")
def test_filling_the_card_never_saves(dock: CatalogDocks, saves: MagicMock) -> None:
    """Moving about the view only shows roots on the card; an edit is what saves.

    **Test steps:**

    * open a catalog and select each root in turn
    * verify nothing was written
    """
    dock.catalog.open_rehuco(REHUCO_PATH)

    select_root(dock, 0)
    select_root(dock, 1)

    saves.assert_not_called()


@mark.usefixtures("served")
def test_renaming_on_the_card_saves_the_label_and_updates_the_row(
    dock: CatalogDocks, saves: MagicMock, database: MemoryDatabase
) -> None:
    """A new name is the root's label in the file, the cache and the view; the folder is untouched and the row stays
    current.

    **Test steps:**

    * select the second root, type a name into the card and finish editing
    * verify the saved labels, the shown labels, the cache's label and the current row
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    select_root(dock, 1)

    dock.roots.root_name_edit.setText("  Packs & Co  ")
    dock.roots.root_name_edit.editingFinished.emit()

    assert written_roots(saves) == ["tutorials", "Packs & Co"]
    assert shown_labels(dock) == ["tutorials", "Packs & Co"]
    assert database.scalar("SELECT label FROM roots WHERE position = 1") == "Packs & Co"
    assert dock.roots.roots_view.currentIndex().row() == 1
    assert dock.roots.root_name_edit.text() == "Packs & Co"


@mark.usefixtures("served")
@mark.parametrize("typed", ["tutorials", "TUTORIALS", ""])
def test_a_name_another_root_has_or_none_is_refused_and_reverted(
    mocker: MockerFixture, dock: CatalogDocks, saves: MagicMock, typed: str
) -> None:
    """The file's own refusal reaches the person, nothing is written, and the field goes back to the label.

    **Test steps:**

    * select the second root and type another root's label, in another case, and nothing
    * verify a warning, no write, the old label shown in the field and in the view
    """
    warning = mocker.patch("rehuco_agent.rehuco.roots_panel.QMessageBox.warning")
    dock.catalog.open_rehuco(REHUCO_PATH)
    select_root(dock, 1)

    dock.roots.root_name_edit.setText(typed)
    dock.roots.root_name_edit.editingFinished.emit()

    warning.assert_called_once()
    saves.assert_not_called()
    assert dock.roots.root_name_edit.text() == "packs"
    assert shown_labels(dock) == ["tutorials", "packs"]


@mark.usefixtures("served")
def test_leaving_the_name_as_it_was_writes_nothing(mocker: MockerFixture, dock: CatalogDocks, saves: MagicMock) -> None:
    """Finishing an edit that changed nothing is not an edit.

    **Test steps:**

    * select a root and finish editing its name untouched
    * verify nothing was written and no warning shown
    """
    warning = mocker.patch("rehuco_agent.rehuco.roots_panel.QMessageBox.warning")
    dock.catalog.open_rehuco(REHUCO_PATH)
    select_root(dock, 0)

    dock.roots.root_name_edit.editingFinished.emit()

    saves.assert_not_called()
    warning.assert_not_called()


@mark.usefixtures("served")
def test_choosing_a_storage_on_the_card_saves_it_and_restyles_the_row_without_a_reset(
    dock: CatalogDocks, saves: MagicMock, database: MemoryDatabase
) -> None:
    """The root's storage is saved at once, the row's glyph changes in place, and the cache's removable flag follows.

    **Test steps:**

    * select the first root and choose Removable drive, then CD or DVD, then Network share
    * verify the saved storage each time, the row's glyph, the cache's flag, and that the model was not reset
    """
    resets: list[int] = []
    dock.roots.roots_model.modelReset.connect(lambda: resets.append(1))
    dock.catalog.open_rehuco(REHUCO_PATH)
    select_root(dock, 0)
    combo = dock.roots.root_storage_combo

    for storage, flag in (
        (RootStorage.REMOVABLE, 1),
        (RootStorage.COMPACT_DISK, 1),
        (RootStorage.NETWORK, 0),
    ):
        combo.setCurrentIndex(combo.findData(storage))
        combo.activated.emit(combo.currentIndex())
        assert written_storages(saves)[0] == storage.value
        assert (
            dock.roots.roots_model.index(0, 0).data(dock.roots.roots_model.ICON_PATH_ROLE)
            == ROOT_STORAGE_ICONS[storage]
        )
        assert database.scalar("SELECT removable FROM roots WHERE position = 0") == flag

    assert not resets
    assert dock.roots.roots_view.currentIndex().row() == 0


@mark.usefixtures("served")
def test_choosing_the_storage_it_already_has_writes_nothing(dock: CatalogDocks, saves: MagicMock) -> None:
    """Re-choosing the current storage is not an edit.

    **Test steps:**

    * select a local root and choose Local folder
    * verify nothing was written
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    select_root(dock, 0)

    dock.roots.root_storage_combo.activated.emit(dock.roots.root_storage_combo.currentIndex())

    saves.assert_not_called()


@mark.usefixtures("served")
def test_a_card_edit_whose_save_fails_is_undone_on_screen(
    mocker: MockerFixture, dock: CatalogDocks, saves: MagicMock
) -> None:
    """The file is read back, so the card and the view show what is on disk.

    **Test steps:**

    * select a root and rename it while the write fails
    * verify a warning, and the old label in the view and on the card
    """
    mocker.patch("rehuco_agent.rehuco.roots_panel.QMessageBox.warning")
    saves.side_effect = PermissionError("read-only folder")
    dock.catalog.open_rehuco(REHUCO_PATH)
    select_root(dock, 0)

    dock.roots.root_name_edit.setText("renamed")
    dock.roots.root_name_edit.editingFinished.emit()

    assert shown_labels(dock) == ["tutorials", "packs"]
    assert dock.roots.root_name_edit.text() == "tutorials"


@mark.usefixtures("served")
@mark.parametrize("storage", [RootStorage.LOCAL, RootStorage.REMOVABLE, RootStorage.NETWORK, RootStorage.COMPACT_DISK])
def test_adding_a_root_saves_its_storage_and_makes_it_current(
    mocker: MockerFixture, dock: CatalogDocks, saves: MagicMock, storage: RootStorage
) -> None:
    """What the dialog answers is what is saved, and the new root is the one selected.

    **Test steps:**

    * answer the Add Root question with a folder and each storage
    * verify the saved storage, the third row, and that it is current and on the card
    """
    answer_add_root(mocker, dock, "/fake/refs", storage)
    dock.catalog.open_rehuco(REHUCO_PATH)

    dock.roots.add_root_action.trigger()

    assert written_storages(saves)[2] == storage.value
    assert dock.roots.roots_view.currentIndex().row() == 2
    assert dock.roots.root_name_edit.text() == "refs"
    assert dock.roots.root_storage_combo.currentData() == storage


@mark.usefixtures("served", "saves")
def test_declining_the_removal_keeps_the_root(mocker: MockerFixture, dock: CatalogDocks, queue: TaskQueue) -> None:
    """Remove asks first, and a no leaves the file, the view and the queue alone.

    **Test steps:**

    * select a root and remove it, answering no
    * verify the question named the root, nothing was written or queued, and both roots remain
    """
    confirm = mocker.patch.object(dock.roots, "confirm_remove_root", return_value=False)
    saved = mocker.patch("rehuco_core.rehuco_file.atomic_write_text")
    dock.catalog.open_rehuco(REHUCO_PATH)
    select_root(dock, 0)

    dock.roots.remove_root_action.trigger()

    confirm.assert_called_once()
    asked = confirm.call_args.args
    assert asked[0].label == "tutorials"
    saved.assert_not_called()
    assert not queue.jobs()
    assert shown_labels(dock) == ["tutorials", "packs"]


@mark.usefixtures("served", "saves")
def test_the_removal_question_is_told_how_many_cached_entries_go(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, queue: TaskQueue
) -> None:
    """The count the confirmation states is the root's rows in the cache.

    **Test steps:**

    * scan a record into the first root, select it and remove it
    * verify the question was asked with the root and a count of one
    """
    scan_finding(mocker, {TUTORIALS: (tutorial_record(),)})
    dock.catalog.open_rehuco(REHUCO_PATH)
    dock.roots.scan_action.trigger()
    qtbot.waitUntil(lambda: first_browser(dock).model.rowCount() == 1, timeout=WAIT_TIMEOUT_MS)
    wait_for_jobs(qtbot, queue)
    select_root(dock, 0)

    dock.roots.remove_root_action.trigger()

    confirm: Any = dock.roots.confirm_remove_root
    assert confirm.call_args.args[1] == 1
    wait_for_jobs(qtbot, queue)


@mark.parametrize(
    ("cached", "stated"),
    [param(0, "0 cached entries are"), param(1, "1 cached entry is"), param(12, "12 cached entries are")],
)
def test_the_removal_question_says_what_goes_and_what_stays(
    mocker: MockerFixture, dock: CatalogDocks, cached: int, stated: str
) -> None:
    """The wording: the files stay on disk, where; the cached entries go, how many; and the answer is Yes only for Yes.

    **Test steps:**

    * ask the real question with the box patched to answer Yes, then No
    * verify the text names the root and its folder and counts the entries, and the answers map to booleans
    """
    root = RehucoRoot(UUID(ROOT_IDS[0]), TUTORIALS, "tutorials", RootStorage.LOCAL)
    box = mocker.patch(
        "rehuco_agent.rehuco.roots_panel.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes
    )

    assert RootsPanel.confirm_remove_root(dock.roots, root, cached) is True

    text = box.call_args.args[2]
    assert "tutorials" in text
    assert str(TUTORIALS) in text
    assert "stay where they are" in text
    assert stated in text
    box.return_value = QMessageBox.StandardButton.No
    assert RootsPanel.confirm_remove_root(dock.roots, root, cached) is False


def test_the_real_add_root_question_returns_what_the_dialog_holds(mocker: MockerFixture, dock: CatalogDocks) -> None:
    """The dock opens its dialog and answers its folder and storage; a cancelled dialog answers nothing.

    **Test steps:**

    * run the question with the dialog's ``exec`` patched to fill in a folder and a storage, then to cancel
    * verify the answer and the cancel
    """

    def accept(self: AddRootDialog) -> QDialog.DialogCode:
        self.folder = "/fake/refs"
        self.storage_combo.setCurrentIndex(self.storage_combo.findData(RootStorage.NETWORK))
        return QDialog.DialogCode.Accepted

    mocker.patch.object(AddRootDialog, "exec", new=accept)
    assert dock.roots.ask_root_to_add() == ("/fake/refs", RootStorage.NETWORK)

    mocker.patch.object(AddRootDialog, "exec", return_value=QDialog.DialogCode.Rejected)
    assert dock.roots.ask_root_to_add() is None


@mark.usefixtures("served")
def test_the_folder_filter_sets_the_current_browsers_folder_token(
    qtbot: QtBot, dock: CatalogDocks, folders: Path
) -> None:
    """*Show only rehu in this folder* filters the current browser on ``folder:<label>/<relative path>`` -- a root
    by its label, a nested folder with its path, and a name with a space quoted -- keeping the rest of the line.

    **Test steps:**

    * type free text on the browser, then trigger the filter on the first root, on ``alpha/sub`` and on ``my folder``
    * verify the line each time
    """
    del folders
    dock.catalog.open_rehuco(REHUCO_PATH)
    browser = first_browser(dock)
    browser.set_filter_text("intro")

    select_root(dock, 0)
    dock.roots.filter_folder_action.trigger()
    assert browser.filter_text == "intro folder:tutorials"

    open_root_folder(qtbot, dock, "alpha", "sub")
    dock.roots.filter_folder_action.trigger()
    assert browser.filter_text == "intro folder:tutorials/alpha/sub"

    open_root_folder(qtbot, dock, "my folder")
    dock.roots.filter_folder_action.trigger()
    assert browser.filter_text == 'intro folder:"tutorials/my folder"'


@mark.usefixtures("served")
def test_the_folder_filter_does_nothing_on_a_file_or_with_no_row(
    qtbot: QtBot, dock: CatalogDocks, folders: Path
) -> None:
    """Only a root or a folder names a folder.

    **Test steps:**

    * trigger the filter with no current row, then with a file current
    * verify the browser's filter is untouched
    """
    del folders
    dock.catalog.open_rehuco(REHUCO_PATH)
    browser = first_browser(dock)

    dock.roots.filter_folder_action.trigger()
    open_root_folder(qtbot, dock, "alpha", "note.txt")
    dock.roots.filter_folder_action.trigger()

    assert browser.filter_text == ""


def add_files_to_a_folder(folders: Path) -> None:
    """Give two folders what the Open and Create tests need, before any of them is opened.

    ``my folder`` holds a rehu record, a video with no rehu of its own (``y.mp4``) and one with (``w.mp4``,
    ``w.rehu``); ``alpha`` gets an ``info.rehu``, so it has an associated rehu and ``my folder`` has none.

    :param folders: the first root's folder.
    """
    inside = folders / "my folder"
    (inside / "x.rehu").write_text("{}", encoding="utf-8")
    (inside / "y.mp4").write_bytes(b"y")
    (inside / "w.mp4").write_bytes(b"w")
    (inside / "w.rehu").write_text("{}", encoding="utf-8")
    (folders / "alpha" / "info.rehu").write_text("{}", encoding="utf-8")


def without_separators(actions: list[QAction]) -> list[QAction]:
    """A menu's entries, the separators left out.

    :param actions: the menu's actions.
    :returns: the others, in order.
    """
    return [action for action in actions if not action.isSeparator()]


@mark.usefixtures("served")
def test_the_context_menu_of_each_kind_of_row(qtbot: QtBot, dock: CatalogDocks, folders: Path) -> None:
    """A root offers Remove, the moves, the filter and the file manager. A folder offers **Open associated rehu** if
    it has one and **Create a rehu** if nothing manages it, then the filter and the file manager; a rehu record Open
    and the file manager; any other file Open and then Open associated rehu or Create likewise, then the file manager.
    What manages a row (#469) ends the list under a separator with the checksum verb for it. The default -- bold, what
    a double-click runs -- is Open in every case, and a folder with no rehu has none.

    **Test steps:**

    * ask for the actions of a root row, a folder with and one without a rehu, a record, a video with and one
      without a rehu, and no row
    * verify each list, which action is bold after each, and what Create is called
    """
    add_files_to_a_folder(folders)
    dock.catalog.open_rehuco(REHUCO_PATH)
    alpha = open_root_folder(qtbot, dock, "alpha")
    no_rehu = open_root_folder(qtbot, dock, "my folder")
    record = open_root_folder(qtbot, dock, "my folder", "x.rehu")
    bare = open_root_folder(qtbot, dock, "my folder", "y.mp4")
    paired = open_root_folder(qtbot, dock, "my folder", "w.mp4")
    row_actions = (
        dock.roots.open_record_action,
        dock.roots.open_file_action,
        dock.roots.open_companion_action,
        dock.roots.create_companion_action,
        dock.roots.filter_folder_action,
        dock.roots.open_explorer_action,
    )

    def bold() -> list[bool]:
        return [action.font().bold() for action in row_actions]

    assert dock.roots.roots_context_actions(dock.roots.roots_model.index(0, 0))[0] is dock.roots.filter_folder_action
    assert not any(bold())
    assert without_separators(dock.roots.roots_context_actions(alpha)) == [
        dock.roots.open_companion_action,
        dock.roots.filter_folder_action,
        dock.roots.open_explorer_action,
        dock.roots.generate_record_action,
    ]
    assert bold() == [False, False, True, False, False, False]
    assert without_separators(dock.roots.roots_context_actions(no_rehu)) == [
        dock.roots.create_companion_action,
        dock.roots.filter_folder_action,
        dock.roots.open_explorer_action,
    ]
    assert dock.roots.create_companion_action.text() == "Create a rehu for this folder"
    assert not any(bold())
    assert without_separators(dock.roots.roots_context_actions(record)) == [
        dock.roots.open_record_action,
        dock.roots.open_explorer_action,
        dock.roots.generate_record_action,
    ]
    assert dock.roots.generate_record_action.text() == "Generate checksums for all x.* files"
    assert bold() == [True, False, False, False, False, False]
    assert dock.roots.roots_context_actions(bare) == [
        dock.roots.open_file_action,
        dock.roots.create_companion_action,
        dock.roots.open_explorer_action,
    ]
    assert dock.roots.create_companion_action.text() == "Create a rehu for this file"
    assert bold() == [False, True, False, False, False, False]
    assert without_separators(dock.roots.roots_context_actions(paired)) == [
        dock.roots.open_file_action,
        dock.roots.open_companion_action,
        dock.roots.open_explorer_action,
        dock.roots.generate_record_action,
    ]
    assert bold() == [False, True, False, False, False, False]
    assert not dock.roots.roots_context_actions(QModelIndex())


@mark.usefixtures("served")
def test_double_clicking_runs_the_rows_default_action_and_never_creates(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, folders: Path
) -> None:
    """A record opens in Documents, a folder opens its rehu there when it has one, any other file opens with the
    application the system associates with it; a root, and a folder with no rehu, only navigate -- a rehu is never
    created by a double-click.

    **Test steps:**

    * double-click a root, a folder with no rehu, a record, a folder with one and a video in turn, watching the
      requests
    * verify each asked for what it should, and the folder with no rehu and the root for nothing
    """
    add_files_to_a_folder(folders)
    dock.catalog.open_rehuco(REHUCO_PATH)
    opener = mocker.patch("rehuco_agent.rehuco.roots_panel.QDesktopServices.openUrl")
    alpha = open_root_folder(qtbot, dock, "alpha")
    no_rehu = open_root_folder(qtbot, dock, "my folder")
    record = open_root_folder(qtbot, dock, "my folder", "x.rehu")
    video = open_root_folder(qtbot, dock, "my folder", "y.mp4")
    records: list[object] = []
    folders_asked: list[object] = []
    files_asked: list[object] = []
    dock.roots.open_requested.connect(records.append)
    dock.roots.open_folder_requested.connect(folders_asked.append)
    dock.roots.open_companion_requested.connect(files_asked.append)

    for ignored in (dock.roots.roots_model.index(0, 0), no_rehu):
        dock.roots.roots_view.doubleClicked.emit(ignored)
    assert not records and not folders_asked and not files_asked
    opener.assert_not_called()

    dock.roots.roots_view.doubleClicked.emit(record)
    assert records == [folders / "my folder" / "x.rehu"]
    dock.roots.roots_view.doubleClicked.emit(alpha)
    assert folders_asked == [folders / "alpha"]
    dock.roots.roots_view.doubleClicked.emit(video)
    opener.assert_called_once_with(QUrl.fromLocalFile(str(folders / "my folder" / "y.mp4")))
    assert len(records) == 1 and not files_asked


@mark.usefixtures("served")
def test_open_acts_on_the_current_row_by_what_it_is(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, folders: Path
) -> None:
    """Open on a record opens it in Documents and does nothing for a file that is not one; Open on a file runs the
    system's application.

    **Test steps:**

    * trigger Open (record) with a record current, then with a video current, then Open (file) with the video current
    * verify one Documents request, for the record, and one system open, for the video
    """
    add_files_to_a_folder(folders)
    dock.catalog.open_rehuco(REHUCO_PATH)
    opener = mocker.patch("rehuco_agent.rehuco.roots_panel.QDesktopServices.openUrl")
    open_root_folder(qtbot, dock, "my folder", "x.rehu")
    asked: list[object] = []
    dock.roots.open_requested.connect(asked.append)

    dock.roots.open_record_action.trigger()
    open_root_folder(qtbot, dock, "my folder", "y.mp4")
    dock.roots.open_record_action.trigger()
    opener.assert_not_called()
    dock.roots.open_file_action.trigger()

    assert asked == [folders / "my folder" / "x.rehu"]
    opener.assert_called_once_with(QUrl.fromLocalFile(str(folders / "my folder" / "y.mp4")))


@mark.usefixtures("served")
def test_opening_and_creating_an_associated_rehu_ask_by_what_the_row_is(
    qtbot: QtBot, dock: CatalogDocks, folders: Path
) -> None:
    """A folder's is its ``info.rehu``, a file's the one named like it; the window opens or starts either, so Open
    and Create send the same request and differ only in which the menu offers.

    **Test steps:**

    * trigger Open and Create with no row, with folders and with files current
    * verify nothing for no row, and the folder request and the file request otherwise
    """
    add_files_to_a_folder(folders)
    dock.catalog.open_rehuco(REHUCO_PATH)
    for_folders: list[object] = []
    for_files: list[object] = []
    dock.roots.open_folder_requested.connect(for_folders.append)
    dock.roots.open_companion_requested.connect(for_files.append)
    dock.roots.create_companion_action.trigger()
    dock.roots.open_companion_action.trigger()
    assert not for_folders and not for_files

    open_root_folder(qtbot, dock, "my folder")
    dock.roots.create_companion_action.trigger()
    open_root_folder(qtbot, dock, "alpha")
    dock.roots.open_companion_action.trigger()
    open_root_folder(qtbot, dock, "my folder", "y.mp4")
    dock.roots.create_companion_action.trigger()
    open_root_folder(qtbot, dock, "my folder", "w.mp4")
    dock.roots.open_companion_action.trigger()

    assert for_folders == [folders / "my folder", folders / "alpha"]
    assert for_files == [folders / "my folder" / "y.mp4", folders / "my folder" / "w.mp4"]


@mark.usefixtures("served")
# one walk over every kind of row, each step reading what the last one left, is the test
# pylint: disable-next=too-many-locals
def test_the_details_pane_follows_the_current_row_and_has_a_button_for_each_menu_entry(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, folders: Path
) -> None:
    """The pane beside the columns names the current row and offers a button for the common and the harmless of its
    context menu, in order, the default in bold (#469); clicking one does what the entry does. Create, the filter and
    Remove Root are never buttons.

    **Test steps:**

    * select a root, a folder with no rehu, a folder with one, a record and a video in turn
    * verify the buttons' actions, which one is bold, and what clicking the default asks for
    """
    add_files_to_a_folder(folders)
    dock.catalog.open_rehuco(REHUCO_PATH)
    dock.roots.show()
    opener = mocker.patch("rehuco_agent.rehuco.roots_panel.QDesktopServices.openUrl")
    reveal = mocker.patch("rehuco_agent.rehuco.roots_panel.reveal_in_file_browser")
    preview = dock.roots.findChild(RootsPreview)
    assert preview is not None
    name = preview.findChild(QLabel, "name_label")
    assert name is not None
    folder_requests: list[object] = []
    record_requests: list[object] = []
    dock.roots.open_folder_requested.connect(folder_requests.append)
    dock.roots.open_requested.connect(record_requests.append)

    def shown() -> list[tuple[QAction | None, bool]]:
        return [(button.defaultAction(), button.font().bold()) for button in preview.buttons]

    select_root(dock, 0)
    assert [action for action, _bold in shown() if action is not None and not action.isSeparator()] == [
        dock.roots.open_explorer_action,
    ]
    assert not any(bold for _action, bold in shown())

    open_root_folder(qtbot, dock, "my folder")
    assert preview.title == "my folder"
    assert shown() == [(dock.roots.open_explorer_action, False)]

    open_root_folder(qtbot, dock, "alpha")
    assert shown()[0] == (dock.roots.open_companion_action, True)
    open_rehu, explorer, generate = preview.buttons
    assert generate.defaultAction() is dock.roots.generate_record_action
    open_rehu.click()
    assert folder_requests == [folders / "alpha"]
    reveal.reset_mock()
    explorer.click()
    reveal.assert_called_once_with(folders / "alpha")

    open_root_folder(qtbot, dock, "my folder", "x.rehu")
    assert shown() == [
        (dock.roots.open_record_action, True),
        (dock.roots.open_explorer_action, False),
        (dock.roots.generate_record_action, False),
    ]
    open_record, *_others = preview.buttons
    open_record.click()
    assert record_requests == [folders / "my folder" / "x.rehu"]

    open_root_folder(qtbot, dock, "my folder", "y.mp4")
    assert shown() == [(dock.roots.open_file_action, True), (dock.roots.open_explorer_action, False)]
    open_external, _explorer = preview.buttons
    opener.reset_mock()
    open_external.click()
    opener.assert_called_once_with(QUrl.fromLocalFile(str(folders / "my folder" / "y.mp4")))


@mark.usefixtures("served")
def test_the_details_pane_sits_beside_the_columns_in_a_splitter(dock: CatalogDocks) -> None:
    """The view and the pane share a splitter, the columns first.

    **Test steps:**

    * open a catalog and find the panel's splitter
    * verify it holds the view and then the pane, and that neither can be collapsed away
    """
    dock.catalog.open_rehuco(REHUCO_PATH)

    splitter = dock.roots.findChild(QSplitter, "roots_splitter")
    assert splitter is not None
    assert splitter.widget(0) is dock.roots.roots_view
    assert isinstance(splitter.widget(1), RootsPreview)
    assert not splitter.childrenCollapsible()


@mark.usefixtures("served")
def test_refresh_lists_a_deleted_folder_away_and_falls_back_to_its_parent(
    qtbot: QtBot, dock: CatalogDocks, folders: Path
) -> None:
    """F5 re-lists the open columns: a folder deleted outside the app disappears in place, and the selection falls
    back to the nearest folder that survives -- not to a neighbour of the one that went.

    **Test steps:**

    * select ``alpha/sub``, delete it on disk and trigger Refresh
    * verify it left ``alpha``, ``alpha`` is current rather than the note beside it, and nothing was reset
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    open_root_folder(qtbot, dock, "alpha", "sub")
    resets: list[int] = []
    dock.roots.roots_model.modelReset.connect(lambda: resets.append(1))
    os.rmdir(folders / "alpha" / "sub")

    dock.roots.refresh_roots_action.trigger()

    qtbot.waitUntil(
        lambda: dock.roots.roots_model.key(dock.roots.roots_view.currentIndex()) == (UUID(ROOT_IDS[0]), ("alpha",)),
        timeout=WAIT_TIMEOUT_MS,
    )
    alpha = dock.roots.roots_model.index_for(UUID(ROOT_IDS[0]), ("alpha",))
    assert [
        dock.roots.roots_model.index(row, 0, alpha).data() for row in range(dock.roots.roots_model.rowCount(alpha))
    ] == ["note.txt"]
    assert not resets


@mark.usefixtures("served")
def test_refresh_with_no_current_row_lists_every_root_again(qtbot: QtBot, dock: CatalogDocks, folders: Path) -> None:
    """With nothing selected the open column is the roots, so each is listed again.

    **Test steps:**

    * add a folder on disk under the first root and trigger Refresh with no current row
    * verify the root lists it
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    root = dock.roots.roots_model.index(0, 0)
    wait_for_root_listing(qtbot, dock, root)
    os.makedirs(folders / "added")

    dock.roots.refresh_roots_action.trigger()

    qtbot.waitUntil(
        lambda: (
            "added"
            in [
                dock.roots.roots_model.index(row, 0, root).data()
                for row in range(dock.roots.roots_model.rowCount(root))
            ]
        ),
        timeout=WAIT_TIMEOUT_MS,
    )


def test_refresh_is_on_the_roots_title_bar_and_bound_to_f5(dock: CatalogDocks, served: Any) -> None:
    """The refresh action carries F5 and works from any column of the view, and it is the one title bar action the
    Root Catalog dock shows -- Scan and the root edits stay in the menu (#461).

    **Test steps:**

    * read the refresh action's shortcut, its context, the panel's title bar actions and its own actions
    * verify F5, children of the panel, Refresh alone on the title bar, and that the panel carries it
    """
    del served

    assert dock.roots.refresh_roots_action.shortcut().toString() == "F5"
    assert dock.roots.refresh_roots_action.shortcutContext() == Qt.ShortcutContext.WidgetWithChildrenShortcut
    assert dock.roots.title_bar_actions == [dock.roots.refresh_roots_action]
    assert dock.roots.refresh_roots_action in dock.roots.actions()


@fixture(name="listening")
def fixture_listening(
    qtbot: QtBot, queue: TaskQueue, database: MemoryDatabase, served: dict[str, Any], folders: Path
) -> Generator[tuple[CatalogDocks, ResourceEvents, Path]]:
    """A dock over real folders that follows an announcer, with the catalog open.

    :param qtbot: pytest-qt fixture.
    :param queue: the queue its jobs run on.
    :param database: the cache's database.
    :param served: the served ``.rehuco``.
    :param folders: the first root's folder.
    :yields: the dock, its events and the first root's folder.
    """
    del database, served
    events = ResourceEvents()
    dock = build_docks(qtbot, queue, events)
    dock.catalog.open_rehuco(REHUCO_PATH)
    yield dock, events, folders
    if dock.catalog.rehuco_path is not None:  # a test may have detached it already, which cannot be done twice
        dock.detach()


def test_an_announced_rename_renames_the_row_in_place(
    qtbot: QtBot, listening: tuple[CatalogDocks, ResourceEvents, Path]
) -> None:
    """A rename the app carries out changes the row of a loaded folder without a reset, and its subtree follows.

    **Test steps:**

    * load ``alpha`` and its ``sub``, rename ``alpha`` on disk and announce the rename
    * verify the row has the new name, ``sub`` is still loaded under it, and the model was not reset
    """
    dock, events, folder = listening
    open_root_folder(qtbot, dock, "alpha", "sub")
    resets: list[int] = []
    dock.roots.roots_model.modelReset.connect(lambda: resets.append(1))
    os.rename(folder / "alpha", folder / "omega")

    events.announce_moved(Relocation(((folder / "alpha", folder / "omega"),)))

    root_id = UUID(ROOT_IDS[0])
    assert (
        dock.roots.roots_model.path_of(dock.roots.roots_model.index_for(root_id, ("omega", "sub")))
        == folder / "omega" / "sub"
    )
    assert not resets


def test_an_announced_folder_change_lists_a_loaded_folder_again(
    qtbot: QtBot, listening: tuple[CatalogDocks, ResourceEvents, Path]
) -> None:
    """A folder whose listing the app changed is read again if the view has it loaded.

    **Test steps:**

    * load ``alpha``, add a file to it on disk and announce the folder changed
    * verify the file appears
    """
    dock, events, folder = listening
    alpha = open_root_folder(qtbot, dock, "alpha")
    (folder / "alpha" / "added.txt").write_text("a", encoding="utf-8")

    events.announce_folder_changed(folder / "alpha")

    qtbot.waitUntil(
        lambda: (
            "added.txt"
            in [
                dock.roots.roots_model.index(row, 0, alpha).data()
                for row in range(dock.roots.roots_model.rowCount(alpha))
            ]
        ),
        timeout=WAIT_TIMEOUT_MS,
    )


def test_a_detached_dock_stops_following_folder_changes(
    qtbot: QtBot, listening: tuple[CatalogDocks, ResourceEvents, Path]
) -> None:
    """After detach nothing is connected to the announcer any more, so a late announcement is harmless.

    **Test steps:**

    * detach the dock and announce a folder change
    * verify nothing failed
    """
    dock, events, folder = listening
    dock.detach()

    events.announce_folder_changed(folder / "alpha")
    qtbot.wait(20)

    assert dock.catalog.rehuco_path is None


# endregion


# region Dragging roots


@mark.usefixtures("served")
def test_dropping_a_root_reorders_the_file_saves_it_and_keeps_it_current(
    qtbot: QtBot, dock: CatalogDocks, saves: MagicMock
) -> None:
    """A root dragged by its grip to another place is moved in the file at once, as the move buttons do, and stays the
    one selected.

    **Test steps:**

    * open a catalog and drop the second root before the first
    * verify the saved order, the shown order and that the dropped root is current
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    model = dock.roots.roots_model
    assert model.flags(model.index(1, 0)) & Qt.ItemFlag.ItemIsDragEnabled

    model.dropMimeData(model.mimeData([model.index(1, 0)]), Qt.DropAction.MoveAction, 0, 0, QModelIndex())

    qtbot.waitUntil(lambda: saves.call_count == 1, timeout=WAIT_TIMEOUT_MS)
    assert written_roots(saves) == ["packs", "tutorials"]
    assert shown_labels(dock) == ["packs", "tutorials"]
    assert getattr(dock.roots.roots_model.root_at(dock.roots.roots_view.currentIndex()), "label", "") == "packs"


@mark.usefixtures("served")
def test_a_read_only_file_takes_no_drag_and_no_drop(dock: CatalogDocks, served: Any, saves: MagicMock) -> None:
    """The grip is for a catalog that can be saved: a newer file shows none, and a drop is refused.

    **Test steps:**

    * open a newer file and read the drag flag of a root
    * try to drop a root
    * verify no drag flag, a refused drop and nothing written
    """
    served["format_version"] = 99
    dock.catalog.open_rehuco(REHUCO_PATH)
    model = dock.roots.roots_model

    assert not model.flags(model.index(1, 0)) & Qt.ItemFlag.ItemIsDragEnabled
    taken = model.dropMimeData(model.mimeData([model.index(1, 0)]), Qt.DropAction.MoveAction, 0, 0, QModelIndex())

    assert not taken
    saves.assert_not_called()


@mark.usefixtures("served")
def test_a_drop_for_a_root_that_is_not_in_the_file_changes_nothing(dock: CatalogDocks, saves: MagicMock) -> None:
    """The slot behind the drop refuses a root it cannot find, and a catalog it cannot write.

    **Test steps:**

    * call the slot with a root id the file does not have
    * verify nothing was written
    """
    dock.catalog.open_rehuco(REHUCO_PATH)

    dock.roots._RootsPanel__on_root_dropped(uuid4(), 0)  # type: ignore[attr-defined]  # pylint: disable=protected-access

    saves.assert_not_called()
    assert shown_labels(dock) == ["tutorials", "packs"]


# endregion


# region Verifying a checksum file


def add_checksum_files(folders: Path) -> None:
    """Put a checksum record beside a rehu record in ``alpha``, and a lone one in ``my folder``.

    :param folders: the first root's folder.
    """
    (folders / "alpha" / "info.rehu").write_text("{}", encoding="utf-8")
    (folders / "alpha" / "info.checksum").write_text("{}", encoding="utf-8")
    (folders / "my folder" / "lonely.checksum").write_text("{}", encoding="utf-8")


@mark.usefixtures("served")
def test_a_checksum_file_offers_verify_and_it_needs_its_rehu(qtbot: QtBot, dock: CatalogDocks, folders: Path) -> None:
    """The menu of a checksum file holds its associated rehu and Open in file explorer, then under a separator Verify
    old checksums, its default, and Verify checksums; both verifies are on only when the ``.rehu`` it records is
    beside it (#457, #469).

    **Test steps:**

    * ask for the actions of a checksum file with its rehu beside it, and of one without
    * verify the order, and that Verify is enabled for the first and disabled, with its own tooltip, for the second
    """
    add_checksum_files(folders)
    dock.catalog.open_rehuco(REHUCO_PATH)
    paired = open_root_folder(qtbot, dock, "alpha", "info.checksum")
    lonely = open_root_folder(qtbot, dock, "my folder", "lonely.checksum")

    with_rehu = dock.roots.roots_context_actions(paired)
    assert without_separators(with_rehu) == [
        dock.roots.open_companion_action,
        dock.roots.open_explorer_action,
        dock.roots.verify_old_checksums_action,
        dock.roots.verify_checksums_action,
    ]
    assert with_rehu[2].isSeparator()
    assert dock.roots.verify_old_checksums_action.isEnabled()
    assert dock.roots.verify_checksums_action.isEnabled()
    enabled_tip = dock.roots.verify_checksums_action.toolTip()

    without = dock.roots.roots_context_actions(lonely)
    assert without_separators(without) == [
        dock.roots.create_companion_action,
        dock.roots.open_explorer_action,
        dock.roots.verify_old_checksums_action,
        dock.roots.verify_checksums_action,
    ]
    assert not dock.roots.verify_old_checksums_action.isEnabled()
    assert not dock.roots.verify_checksums_action.isEnabled()
    assert dock.roots.verify_checksums_action.toolTip() != enabled_tip


@mark.usefixtures("served")
def test_verifying_a_checksum_file_queues_a_verify_of_its_resource(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, queue: TaskQueue, folders: Path
) -> None:
    """Verify queues the job the Checksums dock queues, for the ``.rehu`` that shares the file's name, and does nothing
    for a checksum file with no rehu beside it.

    **Test steps:**

    * trigger Verify on a lone checksum file, then on one with its rehu
    * verify nothing queued, then one verify job whose resource is that rehu
    """
    add_checksum_files(folders)
    dock.catalog.open_rehuco(REHUCO_PATH)
    enqueue = mocker.patch.object(queue, "enqueue")
    open_root_folder(qtbot, dock, "my folder", "lonely.checksum")
    dock.roots.roots_context_actions(
        dock.roots.roots_model.index_for(UUID(ROOT_IDS[0]), ("my folder", "lonely.checksum"))
    )

    dock.roots.verify_checksums_action.trigger()
    enqueue.assert_not_called()

    paired = open_root_folder(qtbot, dock, "alpha", "info.checksum")
    dock.roots.roots_context_actions(paired)
    dock.roots.verify_checksums_action.trigger()

    enqueue.assert_called_once()
    (job,) = enqueue.call_args.args
    assert isinstance(job, VerifyChecksumsJob)
    assert job.source == folders / "alpha" / "info.rehu"


@mark.usefixtures("served")
def test_verifying_twice_is_not_asking_twice(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, queue: TaskQueue, folders: Path
) -> None:
    """A verify already waiting for the same resource is not queued again.

    **Test steps:**

    * say the queue already holds the job, and trigger Verify
    * verify nothing was queued
    """
    add_checksum_files(folders)
    dock.catalog.open_rehuco(REHUCO_PATH)
    enqueue = mocker.patch.object(queue, "enqueue")
    mocker.patch("rehuco_agent.rehuco.roots_checksum_verbs.job_already_queued", return_value=True)
    paired = open_root_folder(qtbot, dock, "alpha", "info.checksum")
    dock.roots.roots_context_actions(paired)

    dock.roots.verify_checksums_action.trigger()

    enqueue.assert_not_called()


# endregion


# region Guards the actions never reach, because a disabled action does not fire (#461)


@mark.usefixtures("served")
def test_the_root_slots_refuse_without_a_current_root_and_a_move_that_goes_nowhere_writes_nothing(
    qtbot: QtBot, dock: CatalogDocks, queue: TaskQueue, saves: MagicMock
) -> None:
    """Called directly, the slots behind the root editors, the moves, Verify and the folder filter each refuse on
    their own, since a disabled action never reaches them.

    **Test steps:**

    * open a catalog with no row current and call the name, storage, move, verify and folder-filter slots
    * select the first root and call the move slot with a move that leaves it where it is
    * verify nothing was written or queued, no filter was asked for, and the file is as it was
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    panel = dock.roots

    with qtbot.assertNotEmitted(panel.filter_requested):
        panel._RootsPanel__on_root_name_edited()  # type: ignore[attr-defined]  # pylint: disable=protected-access
        panel._RootsPanel__on_root_storage_chosen()  # type: ignore[attr-defined]  # pylint: disable=protected-access
        panel._RootsPanel__move_root(lambda _file, row: row)  # type: ignore[attr-defined]  # pylint: disable=protected-access
        verbs = panel._RootsPanel__verbs  # type: ignore[attr-defined]  # pylint: disable=protected-access
        verbs._RootsChecksumVerbs__on_verify_checksums(old=False)  # pylint: disable=protected-access
        panel._RootsPanel__on_filter_folder()  # type: ignore[attr-defined]  # pylint: disable=protected-access
        select_root(dock, 0)
        panel._RootsPanel__move_root(lambda _file, row: row)  # type: ignore[attr-defined]  # pylint: disable=protected-access

    saves.assert_not_called()
    assert not queue.jobs()
    assert shown_labels(dock) == ["tutorials", "packs"]


class RecordingMenu(QMenu):
    """A menu that records what it was asked to show instead of running a modal loop."""

    shown: list[list[QAction]] = []

    def exec(self, *_args: object) -> None:  # type: ignore[override]
        """Record the menu's actions."""
        RecordingMenu.shown.append(self.actions())


@mark.usefixtures("served")
def test_the_roots_context_menu_shows_the_rows_actions_and_makes_it_current(
    mocker: MockerFixture, monkeypatch: MonkeyPatch, dock: CatalogDocks
) -> None:
    """Right-clicking a row opens a menu of that row's actions and makes the row current first; right-clicking
    nothing opens none.

    **Test steps:**

    * open a catalog and ask for the menu where the pointer is over the second root
    * verify the menu held that root's actions and the root became current
    * ask for it where there is no row and verify no menu was shown
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    monkeypatch.setattr("rehuco_agent.rehuco.roots_panel.QMenu", RecordingMenu)
    RecordingMenu.shown = []
    view = dock.roots.roots_view
    second = dock.roots.roots_model.index(1, 0)
    answers = mocker.patch.object(view, "index_at_global", return_value=second)

    dock.roots._RootsPanel__on_roots_context_menu(QPoint(1, 1))  # type: ignore[attr-defined]  # pylint: disable=protected-access

    assert RecordingMenu.shown == [dock.roots.roots_context_actions(second)]
    assert view.currentIndex() == second

    answers.return_value = QModelIndex()
    dock.roots._RootsPanel__on_roots_context_menu(QPoint(1, 1))  # type: ignore[attr-defined]  # pylint: disable=protected-access

    assert len(RecordingMenu.shown) == 1


def test_a_catalog_counts_nothing_with_no_cache_and_logs_a_cache_it_cannot_read(
    mocker: MockerFixture, dock: CatalogDocks, served: Any, caplog: LogCaptureFixture
) -> None:
    """The entries a removal would drop are zero with nothing open and when the cache cannot be read.

    **Test steps:**

    * count a root's entries with no catalog open
    * open one, make the count raise, and count again
    * verify zero both times and an error naming the root
    """
    del served
    root = RehucoRoot(UUID(ROOT_IDS[0]), TUTORIALS, "tutorials")
    assert dock.catalog.resource_count(root) == 0
    dock.catalog.open_rehuco(REHUCO_PATH)
    mocker.patch.object(CatalogCache, "resource_count", side_effect=sqlite3.OperationalError("locked"))

    with caplog.at_level(logging.ERROR):
        assert dock.catalog.resource_count(root) == 0

    assert "Could not count the cached entries of tutorials" in caplog.text


def test_removing_a_root_with_no_catalog_open_does_nothing_and_a_save_that_closes_the_file_is_not_announced(
    mocker: MockerFixture, dock: CatalogDocks, served: Any, saves: MagicMock
) -> None:
    """The catalog refuses a removal it has no file for, and says nothing more when a failed save left it closed.

    **Test steps:**

    * remove a root with nothing open
    * open a catalog, make the save fail and the file unreadable, and remove the first root
    * verify both removals report failure, the second closed the file, and no refresh was announced after it
    """
    del served
    assert not dock.catalog.remove_root(0)
    dock.catalog.open_rehuco(REHUCO_PATH)
    saves.side_effect = PermissionError("read-only folder")
    mocker.patch.object(Path, "read_text", side_effect=FileNotFoundError("gone"))
    refreshed = mocker.MagicMock()
    dock.catalog.refreshed.connect(refreshed)

    assert not dock.catalog.remove_root(0)

    assert dock.catalog.rehuco_path is None
    refreshed.assert_called_once_with()
    assert dock.catalog.save_error.startswith("Could not save")


# endregion


# region Selecting a resource shows it in the preview (#381)


def select_rows(browser: TableBrowser, *rows: int) -> None:
    """Make exactly these rows of a browser the selected ones, as a click or the arrow keys do.

    :param browser: the browser.
    :param rows: the rows to select; none clears the selection.
    """
    selection = browser.view.selectionModel()
    flags = QItemSelectionModel.SelectionFlag
    if not rows:
        selection.clearSelection()
    # the first row replaces the selection in one step, as a click does -- a clear and then a select would pass
    # through a state of its own
    for position, row in enumerate(rows):
        selection.select(
            browser.model.index(row, 0),
            (flags.ClearAndSelect if position == 0 else flags.Select) | flags.Rows,
        )


def scan_two_records(mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, queue: TaskQueue) -> None:
    """Open the catalog and scan the tutorials root, which finds two records, into the first browser.

    :param mocker: pytest-mock fixture.
    :param qtbot: pytest-qt fixture.
    :param dock: the catalog's docks.
    :param queue: the queue the scan runs on.
    """
    ruby = CatalogRecord(
        "ruby/info.rehu", RecordKind.REHU, title="Ruby", type="tutorial", current_size=1, content_hash="1"
    )
    scan_finding(mocker, {TUTORIALS: (tutorial_record(), ruby)})
    dock.catalog.open_rehuco(REHUCO_PATH)
    dock.roots.scan_action.trigger()
    qtbot.waitUntil(lambda: first_browser(dock).model.rowCount() == 2, timeout=WAIT_TIMEOUT_MS)
    wait_for_jobs(qtbot, queue)


@mark.usefixtures("served")
def test_a_resource_key_resolves_to_its_path_in_one_place(dock: CatalogDocks) -> None:
    """A ``(root_id, relative)`` key becomes a path through the catalog alone; a root the file does not list, or no
    file at all, has none.

    **Test steps:**

    * resolve a key with nothing open, then with the catalog open: a listed root, and one the file lacks
    * verify nothing, the root's folder joined to the relative path, and nothing
    """
    listed, unknown = UUID(ROOT_IDS[0]), uuid4()
    assert dock.catalog.resource_path(listed, "python/info.rehu") is None

    dock.catalog.open_rehuco(REHUCO_PATH)

    assert dock.catalog.resource_path(listed, "python/info.rehu") == TUTORIALS / "python/info.rehu"
    assert dock.catalog.resource_path(unknown, "python/info.rehu") is None


@mark.usefixtures("served")
def test_the_current_browsers_one_selected_row_is_announced_and_nothing_else_is(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, queue: TaskQueue
) -> None:
    """One selected row names its resource; several name nothing -- and the next row names the next.

    **Test steps:**

    * scan two records in, make the browser current and spy on the dock's ``resource_selected``
    * select the first row, then both, then none, then the second
    * verify the first's key, ``None``, then the second's key -- a selection that stays empty says nothing again
    """
    scan_two_records(mocker, qtbot, dock, queue)
    browser = first_browser(dock)
    dock.browsers.focus_browser(browser)
    announced: list[object] = []
    dock.browsers.resource_selected.connect(announced.append)

    select_rows(browser, 0)
    select_rows(browser, 0, 1)
    select_rows(browser)
    select_rows(browser, 1)

    assert announced == [browser.model.row_key(0), None, browser.model.row_key(1)]


@mark.usefixtures("served")
def test_a_browser_behind_the_current_one_announces_nothing(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, queue: TaskQueue
) -> None:
    """A browser the reader is not in is not being read: what its selection does says nothing about them.

    **Test steps:**

    * scan two records in, add a second browser, which becomes the current one
    * select a row of the first browser
    * verify nothing was announced, then select one of the second and verify that was
    """
    scan_two_records(mocker, qtbot, dock, queue)
    first = first_browser(dock)
    new_browser_action = dock.browsers.new_browser_action
    new_browser_action.trigger()
    browsers = dock.browsers.browsers
    second = browsers[1]
    assert dock.browsers.current_browser is second
    qtbot.waitUntil(lambda: second.model.rowCount() == 2, timeout=WAIT_TIMEOUT_MS)
    announced: list[object] = []
    dock.browsers.resource_selected.connect(announced.append)

    select_rows(first, 0)
    assert not announced

    select_rows(second, 0)
    assert announced == [second.model.row_key(0)]


def add_records_around_the_folders(folders: Path) -> None:
    """Give the first root what the Roots selection tests need: records of each shape the Open action knows.

    ``my folder`` holds a record (``x.rehu``), a video with no record (``y.mp4``), one with a ``.rehu`` (``w.mp4``) and
    one with only a ``.tc`` (``t.mp4``); ``alpha`` has an ``info.rehu``; ``legacy`` has only an ``info.tc``.

    :param folders: the first root's folder.
    """
    add_files_to_a_folder(folders)
    inside = folders / "my folder"
    (inside / "t.mp4").write_bytes(b"t")
    (inside / "t.tc").write_text("type: Tutorial", encoding="utf-8")
    os.makedirs(folders / "legacy")
    (folders / "legacy" / "info.tc").write_text("type: Tutorial", encoding="utf-8")


def announced_on_selecting(qtbot: QtBot, dock: CatalogDocks, *names: str) -> object:
    """What the Roots view announces once the row at ``names`` is its current one.

    :param qtbot: pytest-qt fixture.
    :param dock: the Root Catalog dock, with a catalog open.
    :param names: the names down from the first root.
    :returns: the last thing announced, which is the row's own: the rows on the way were announced first.
    """
    announced: list[object] = []
    dock.roots.record_selected.connect(announced.append)
    try:
        open_root_folder(qtbot, dock, *names)
    finally:
        dock.roots.record_selected.disconnect(announced.append)
    return announced[-1]


@mark.usefixtures("served")
def test_a_roots_row_announces_the_record_opening_it_would_open(
    qtbot: QtBot, dock: CatalogDocks, folders: Path
) -> None:
    """A record names itself, a folder its ``info.rehu``, a file its same-name ``.rehu``, and the ``.tc`` of either
    stands in when that is all there is -- the same record the Open action finds.

    **Test steps:**

    * make each kind of row current in turn
    * verify the record each announced, as a root id and a ``/``-joined path
    """
    add_records_around_the_folders(folders)
    dock.catalog.open_rehuco(REHUCO_PATH)
    root_id = UUID(ROOT_IDS[0])

    assert announced_on_selecting(qtbot, dock, "my folder", "x.rehu") == (root_id, "my folder/x.rehu")
    assert announced_on_selecting(qtbot, dock, "alpha") == (root_id, "alpha/info.rehu")
    assert announced_on_selecting(qtbot, dock, "my folder", "w.mp4") == (root_id, "my folder/w.rehu")
    assert announced_on_selecting(qtbot, dock, "my folder", "t.mp4") == (root_id, "my folder/t.tc")
    assert announced_on_selecting(qtbot, dock, "legacy") == (root_id, "legacy/info.tc")


@mark.usefixtures("served")
def test_a_roots_row_with_no_record_announces_nothing_and_creates_none(
    qtbot: QtBot, dock: CatalogDocks, folders: Path
) -> None:
    """A root, a folder with no rehu, a file with none, a file that is not a record -- each leaves the preview
    alone, and none of them is a request to create one.

    **Test steps:**

    * make a root, a folder with no rehu, a video with none and a note current in turn, then no row at all
    * verify each announced ``None``, and the folders hold exactly the files they did
    """
    add_records_around_the_folders(folders)
    dock.catalog.open_rehuco(REHUCO_PATH)
    before = sorted(str(path) for path in folders.rglob("*"))
    announced: list[object] = []
    dock.roots.record_selected.connect(announced.append)

    select_root(dock, 0)
    assert announced == [None]
    assert announced_on_selecting(qtbot, dock, "my folder") is None
    assert announced_on_selecting(qtbot, dock, "my folder", "y.mp4") is None
    assert announced_on_selecting(qtbot, dock, "alpha", "note.txt") is None
    announced.clear()
    dock.roots.roots_view.setCurrentIndex(QModelIndex())
    assert announced == [None]

    assert sorted(str(path) for path in folders.rglob("*")) == before


@mark.usefixtures("served")
def test_a_folder_not_yet_listed_is_asked_of_the_disk(qtbot: QtBot, dock: CatalogDocks, folders: Path) -> None:
    """A folder the view has not listed yet has no names to ask, so its rehu is looked for on the disk.

    **Test steps:**

    * list the root, then make ``alpha`` current before its own listing is there
    * verify it announced its ``info.rehu``
    """
    add_records_around_the_folders(folders)
    dock.catalog.open_rehuco(REHUCO_PATH)
    model = dock.roots.roots_model
    root = model.index(0, 0)
    wait_for_root_listing(qtbot, dock, root)
    alpha = next(
        index for index in (model.index(row, 0, root) for row in range(model.rowCount(root))) if index.data() == "alpha"
    )
    assert model.child_names(alpha) is None
    announced: list[object] = []
    dock.roots.record_selected.connect(announced.append)

    dock.roots.roots_view.setCurrentIndex(alpha)

    assert announced[0] == (UUID(ROOT_IDS[0]), "alpha/info.rehu")


# endregion


# region A checksum file's two verbs, and what follows a verify (#457)


@mark.usefixtures("served")
def test_verify_old_leaves_a_valid_check_alone_and_verify_checksums_checks_everything(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, queue: TaskQueue, folders: Path
) -> None:
    """The checksum file's two verbs differ in one thing: whether a check still valid is skipped.

    **Test steps:**

    * trigger Verify old checksums, then Verify checksums, on a checksum file with its rehu beside it
    * verify both queue a verify of the resource, the first with the settings' window and the second with none
    """
    add_checksum_files(folders)
    dock.catalog.open_rehuco(REHUCO_PATH)
    enqueue = mocker.patch.object(queue, "enqueue")
    paired = open_root_folder(qtbot, dock, "alpha", "info.checksum")
    dock.roots.roots_context_actions(paired)

    dock.roots.verify_old_checksums_action.trigger()
    dock.roots.verify_checksums_action.trigger()

    old, everything = (call.args[0] for call in enqueue.call_args_list)
    assert isinstance(old, VerifyChecksumsJob)
    assert isinstance(everything, VerifyChecksumsJob)
    assert old.stale_after == shared_checksum_settings().stale_after
    assert everything.stale_after is None


@mark.usefixtures("served")
def test_a_double_click_on_a_checksum_file_verifies_what_is_old_and_only_where_it_can(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, queue: TaskQueue, folders: Path
) -> None:
    """The bold entry is what a double-click runs: Verify old checksums, when the rehu it records is beside it.

    **Test steps:**

    * double-click a checksum file with its rehu, and one without
    * verify the default of each is Verify old, one verify of the resource was queued, and the lone file queued none
    """
    add_checksum_files(folders)
    dock.catalog.open_rehuco(REHUCO_PATH)
    enqueue = mocker.patch.object(queue, "enqueue")
    lonely = open_root_folder(qtbot, dock, "my folder", "lonely.checksum")
    paired = open_root_folder(qtbot, dock, "alpha", "info.checksum")

    dock.roots.roots_context_actions(lonely)
    dock.roots.roots_view.doubleClicked.emit(lonely)
    enqueue.assert_not_called()

    dock.roots.roots_context_actions(paired)
    assert dock.roots.verify_old_checksums_action.font().bold()
    assert not dock.roots.verify_checksums_action.font().bold()
    dock.roots.roots_view.doubleClicked.emit(paired)

    enqueue.assert_called_once()
    (job,) = enqueue.call_args.args
    assert job.stale_after == shared_checksum_settings().stale_after


@mark.usefixtures("served")
def test_a_screenshot_never_offers_to_create_a_rehu_and_opens_the_record_it_belongs_to(
    qtbot: QtBot, dock: CatalogDocks, folders: Path
) -> None:
    """``info00.jpg`` beside ``info.rehu`` is that record's own file: its associated rehu is the record, and a rehu of
    its own would be a second resource inside the first.

    **Test steps:**

    * list a folder holding ``info.rehu`` and its ``info00.jpg``, and a picture no record numbers
    * verify the screenshot's menu is Open and Open associated rehu, and the stranger's offers Create
    """
    add_files_to_a_folder(folders)
    (folders / "alpha" / "info00.jpg").write_bytes(b"x")
    (folders / "my folder" / "poster.jpg").write_bytes(b"x")
    dock.catalog.open_rehuco(REHUCO_PATH)
    screenshot = open_root_folder(qtbot, dock, "alpha", "info00.jpg")
    stranger = open_root_folder(qtbot, dock, "my folder", "poster.jpg")

    assert without_separators(dock.roots.roots_context_actions(screenshot)) == [
        dock.roots.open_file_action,
        dock.roots.open_companion_action,
        dock.roots.open_explorer_action,
        dock.roots.generate_record_action,
    ]
    assert dock.roots.roots_context_actions(stranger) == [
        dock.roots.open_file_action,
        dock.roots.create_companion_action,
        dock.roots.open_explorer_action,
    ]
    assert dock.roots.create_companion_action.text() == "Create a rehu for this file"


@mark.usefixtures("served")
def test_reselecting_says_again_which_record_the_current_row_stands_for(
    qtbot: QtBot, dock: CatalogDocks, folders: Path
) -> None:
    """A listener that has just started to care -- the preview, switched back on -- asks for the current record.

    **Test steps:**

    * make a folder with an ``info.rehu`` current
    * reselect, and verify the record's key is announced
    """
    add_files_to_a_folder(folders)
    dock.catalog.open_rehuco(REHUCO_PATH)
    open_root_folder(qtbot, dock, "alpha")

    with qtbot.waitSignal(dock.roots.record_selected, timeout=WAIT_TIMEOUT_MS) as announced:
        dock.roots.reselect()

    assert announced.args == [(UUID(ROOT_IDS[0]), "alpha/info.rehu")]


@mark.usefixtures("served")
def test_what_a_finished_verify_rewrote_is_announced_where_there_is_someone_to_hear_it(
    mocker: MockerFixture, qtbot: QtBot, queue: TaskQueue, folders: Path
) -> None:
    """With the app's events the rewritten record is announced, so every view of it follows; without, the Roots view
    lists what is under it again itself.

    **Test steps:**

    * finish a verify over a panel that has events, and over one that has none
    * verify the first announces the checksum record and the second lists the resource's folder again
    """
    del folders
    events = ResourceEvents()
    heard: list[object] = []
    events.changed.connect(heard.append)
    with_events = build_docks(qtbot, queue, events)
    without = build_docks(qtbot, queue)
    relist = mocker.patch.object(without.roots.roots_model, "relist_under")
    resource = Path("/fake/pack/info.rehu")

    with_events.roots._RootsPanel__announce_rewritten(resource)  # type: ignore[attr-defined]  # pylint: disable=protected-access
    without.roots._RootsPanel__announce_rewritten(resource)  # type: ignore[attr-defined]  # pylint: disable=protected-access

    qtbot.waitUntil(lambda: bool(heard), timeout=WAIT_TIMEOUT_MS)
    assert heard == [(Path("/fake/pack/info.checksum"),)]
    relist.assert_called_once_with(Path("/fake/pack"))


@mark.usefixtures("served")
def test_a_rewritten_checksum_record_lists_its_folder_again_and_nothing_else_does(
    mocker: MockerFixture, qtbot: QtBot, followed: tuple[CatalogDocks, ResourceEvents]
) -> None:
    """The app saying it wrote files moves the Roots view only for a checksum record: it is the one file whose change
    alters what the rows under it show.

    **Test steps:**

    * announce a checksum record and a rehu being written
    * verify the folder of the record, and only that one, is listed again
    """
    dock, events = followed
    relist = mocker.patch.object(dock.roots.roots_model, "relist_under")

    events.announce_changed((Path("/fake/pack/other.rehu"), Path("/fake/pack/INFO.CHECKSUM")))

    qtbot.waitUntil(lambda: relist.called, timeout=WAIT_TIMEOUT_MS)
    relist.assert_called_once_with(Path("/fake/pack"))


# endregion


# region The checksum verbs of the Roots view, and what manages a row (#469)


def checksum_entry(name: str, status: str = "matched", **extra: str) -> dict[str, str]:
    """One entry of a ``.checksum`` record, as a verify writes it.

    :param name: the entry's name under the record's folder.
    :param status: what the last check found.
    :param extra: keys to add or replace.
    :returns: the entry.
    """
    return {"name": name, "xxh3": "e6c632b61e964e1f", "verified": "2099-01-01T00:00:00Z", "status": status} | extra


def write_checksum_record(path: Path, *entries: dict[str, str]) -> None:
    """Write a ``.checksum`` record.

    :param path: where.
    :param entries: its entries.
    """
    path.write_text(json.dumps({"version": 1, "files": list(entries)}), encoding="utf-8")


@fixture(name="records")
def fixture_records(served: dict[str, Any], folders: Path, mocker: MockerFixture) -> Path:
    """Folders of every shape a record can manage, with checksum records the lister reads.

    ``res`` is an ``info.rehu`` with its ``info.checksum`` (a good, a bad and an unreadable entry, a file the record
    does not list, a subfolder, a nested resource and a junk file); ``pair`` a file-scoped ``foo.rehu`` with its
    ``foo.checksum``; ``bare`` an ``info.rehu`` with no checksum file; ``legacy`` an ``info.tc``; ``plain`` nothing.

    **A real read for everything but the catalog**, which the ``served`` fixture otherwise answers for every file.

    :param served: the served ``.rehuco``.
    :param folders: the first root's folder.
    :param mocker: pytest-mock fixture.
    :returns: the first root's folder.
    """

    def read_text(self: Path, *args: Any, **kwargs: Any) -> str:
        if self.suffix == ".rehuco":
            return json.dumps(served)
        return REAL_READ_TEXT(self, *args, **kwargs)

    mocker.patch.object(Path, "read_text", read_text)
    for folder in ("res/sub", "res/nested", "pair", "bare", "legacy", "plain"):
        os.makedirs(folders / folder)
    files = {
        "res/info.rehu": "{}",
        "res/ok.mp4": "o",
        "res/bad.mp4": "b",
        "res/weird.mp4": "w",
        "res/new.mp4": "n",
        "res/Thumbs.db": "t",
        "res/sub/a.mp4": "a",
        "res/nested/info.rehu": "{}",
        "pair/foo.rehu": "{}",
        "pair/foo.mp4": "f",
        "pair/bar.mp4": "r",
        "bare/info.rehu": "{}",
        "bare/b.mp4": "b",
        "legacy/info.tc": "{}",
        "legacy/l.mp4": "l",
        "plain/c.mp4": "c",
    }
    for name, text in files.items():
        (folders / name).write_text(text, encoding="utf-8")
    write_checksum_record(
        folders / "res" / "info.checksum",
        checksum_entry("ok.mp4"),
        checksum_entry("bad.mp4", "mismatched"),
        {"name": "weird.mp4", "xxh3": "zz"},
        checksum_entry("sub/a.mp4"),
    )
    write_checksum_record(folders / "res" / "nested" / "info.checksum")
    write_checksum_record(folders / "pair" / "foo.checksum", checksum_entry("foo.mp4"))
    return folders


def verbs_of(actions: list[QAction], dock: CatalogDocks) -> list[QAction]:
    """The checksum verbs among a list of actions.

    :param actions: a menu's or a pane's actions.
    :param dock: the catalog's docks.
    :returns: the verbs, in order.
    """
    roots = dock.roots
    verbs = (
        roots.verify_record_action,
        roots.generate_record_action,
        roots.verify_file_action,
        roots.add_file_checksum_action,
        roots.update_file_checksum_action,
    )
    return [action for action in actions if action in verbs]


def pane_buttons(dock: CatalogDocks, index: QModelIndex) -> list[QAction]:
    """What the details pane makes buttons of for a row.

    :param dock: the catalog's docks.
    :param index: the row.
    :returns: the actions, the separators left out.
    """
    actions, _default = dock.roots._RootsPanel__actions_for_row(index)  # type: ignore[attr-defined]  # pylint: disable=protected-access
    return without_separators(actions)


def test_a_file_gets_the_verbs_its_checksum_state_calls_for(qtbot: QtBot, dock: CatalogDocks, records: Path) -> None:
    """A file with a stored result can be verified now; one the record lacks can be added, one that no longer matches
    or cannot be read can be updated -- and only verifying is ever a button, as the other two hash a file at once.

    **Test steps:**

    * open a good, a bad, an unreadable and an unlisted file of a resource that has its checksum file
    * verify the checksum verbs of each file's menu and of its buttons
    """
    del records
    dock.catalog.open_rehuco(REHUCO_PATH)
    roots = dock.roots
    bulk = roots.verify_record_action
    for name, in_menu, as_buttons in (
        ("ok.mp4", [roots.verify_file_action], [roots.verify_file_action]),
        ("bad.mp4", [roots.verify_file_action, roots.update_file_checksum_action], [roots.verify_file_action]),
        ("weird.mp4", [roots.update_file_checksum_action], []),
        ("new.mp4", [roots.add_file_checksum_action], []),
    ):
        index = open_root_folder(qtbot, dock, "res", name)
        assert verbs_of(roots.roots_context_actions(index), dock) == [bulk, *in_menu], name
        assert verbs_of(pane_buttons(dock, index), dock) == [bulk, *as_buttons], name
    assert bulk.text() == "Verify all files in the folder"


def test_every_checksum_verb_queues_its_job_over_the_record_that_manages_the_row(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, queue: TaskQueue, records: Path
) -> None:
    """Each verb queues the job for the scope it names: a bulk verify with the settings' window, a bulk generate where
    there is no checksum file yet, and a single file's verify or re-baseline with no window and only its own name --
    for a file of a ``foo.rehu``, a file and a subfolder under an ``info.rehu``.

    **Test steps:**

    * trigger each verb on the row it belongs to, with the queue's enqueue replaced
    * verify the job's class, the record it works over, its ``only`` and its ``stale_after``
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    enqueue = mocker.patch.object(queue, "enqueue")
    roots = dock.roots
    window = shared_checksum_settings().stale_after

    def queued(action: QAction, *names: str) -> tuple[type[object], Path, tuple[str, ...] | None, object]:
        index = open_root_folder(qtbot, dock, *names)
        roots.roots_context_actions(index)
        enqueue.reset_mock()
        action.trigger()
        enqueue.assert_called_once()
        (job,) = enqueue.call_args.args
        return type(job), job.source, job.only, job.stale_after

    res, pair = records / "res" / "info.rehu", records / "pair" / "foo.rehu"
    assert queued(roots.verify_record_action, "res", "ok.mp4") == (VerifyChecksumsJob, res, None, window)
    assert queued(roots.verify_record_action, "res", "sub") == (VerifyChecksumsJob, res, None, window)
    assert queued(roots.verify_record_action, "res", "sub", "a.mp4") == (VerifyChecksumsJob, res, None, window)
    assert roots.verify_record_action.text() == "Verify all files of the parent resource"
    assert queued(roots.verify_file_action, "res", "sub", "a.mp4") == (
        VerifyChecksumsJob,
        res,
        ("sub/a.mp4",),
        None,
    )
    assert queued(roots.update_file_checksum_action, "res", "bad.mp4") == (
        GenerateChecksumsJob,
        res,
        ("bad.mp4",),
        None,
    )
    assert queued(roots.add_file_checksum_action, "res", "new.mp4") == (GenerateChecksumsJob, res, ("new.mp4",), None)
    assert queued(roots.verify_record_action, "pair", "foo.mp4") == (VerifyChecksumsJob, pair, None, window)
    assert roots.verify_record_action.text() == "Verify all foo.* files"
    assert queued(roots.verify_file_action, "pair", "foo.mp4") == (VerifyChecksumsJob, pair, ("foo.mp4",), None)
    assert queued(roots.generate_record_action, "bare", "b.mp4") == (
        GenerateChecksumsJob,
        records / "bare" / "info.rehu",
        None,
        None,
    )
    assert roots.generate_record_action.text() == "Generate checksums for all files in the folder"


def test_what_manages_a_row_decides_where_create_and_the_checksum_group_are_offered(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, queue: TaskQueue, records: Path
) -> None:
    """Create is offered only where no record manages the row; the checksum group only where a ``.rehu`` does.

    **Test steps:**

    * ask for the menu of a stranger beside a record, a file and a folder a record manages, junk it leaves out, a
      nested resource, a folder with a legacy ``.tc`` and a root
    * verify Create and the checksum group in each, and that a verb triggered on a row nothing manages queues nothing
    """
    del records
    dock.catalog.open_rehuco(REHUCO_PATH)
    roots = dock.roots
    create, generate = roots.create_companion_action, roots.generate_record_action

    def menu(*names: str) -> list[QAction]:
        return without_separators(roots.roots_context_actions(open_root_folder(qtbot, dock, *names)))

    assert create in menu("pair", "bar.mp4") and not verbs_of(menu("pair", "bar.mp4"), dock)
    assert create in menu("plain", "c.mp4") and create in menu("plain")
    assert create in menu("res", "Thumbs.db") and not verbs_of(menu("res", "Thumbs.db"), dock)
    assert create not in menu("res", "sub") and roots.verify_record_action in menu("res", "sub")
    assert create not in menu("res", "weird.mp4")
    assert create not in menu("res", "nested") and roots.open_companion_action in menu("res", "nested")
    assert generate in menu("bare") and generate in menu("bare", "b.mp4")
    # a legacy .tc is a record, so nothing else offers to start one -- but it is not checksummed
    assert create not in menu("legacy", "l.mp4") and not verbs_of(menu("legacy", "l.mp4"), dock)
    assert not verbs_of(menu("legacy"), dock) and roots.open_companion_action in menu("legacy")
    # a root, and the pane's buttons for a folder this record manages by a record above it
    root = roots.roots_model.index(0, 0)
    assert roots.verify_record_action not in roots.roots_context_actions(root)
    assert managing_record(roots.roots_model, root) is None
    enqueue = mocker.patch.object(queue, "enqueue")
    open_root_folder(qtbot, dock, "plain", "c.mp4")
    for verb in (roots.verify_record_action, roots.verify_file_action):
        verb.trigger()
    enqueue.assert_not_called()
    assert pane_buttons(dock, open_root_folder(qtbot, dock, "res", "sub")) == [
        roots.open_explorer_action,
        roots.verify_record_action,
    ]


def test_a_placeholder_row_has_no_menu_and_no_buttons(
    mocker: MockerFixture,
    qtbot: QtBot,
    dock: CatalogDocks,
    served: dict[str, Any],
    folders: Path,
) -> None:
    """The row an unreachable root shows in place of its folders offers nothing, and a right-click there opens no
    menu.

    **Test steps:**

    * point a root at a folder that is not there and open the catalog
    * verify the row's actions and buttons are empty, and that a right-click on it shows no menu
    """
    served["roots"][1]["path"] = str(folders.parent / "gone")
    dock.catalog.open_rehuco(REHUCO_PATH)
    packs = dock.roots.roots_model.index(1, 0)
    wait_for_root_listing(qtbot, dock, packs)
    placeholder = dock.roots.roots_model.index(0, 0, packs)
    assert dock.roots.roots_model.node_kind(placeholder) is RootsNodeKind.UNREACHABLE
    mocker.patch("rehuco_agent.rehuco.roots_panel.QMenu", RecordingMenu)
    RecordingMenu.shown = []
    mocker.patch.object(dock.roots.roots_view, "index_at_global", return_value=placeholder)

    assert not dock.roots.roots_context_actions(placeholder)
    assert dock.roots._RootsPanel__actions_for_row(placeholder) == ([], None)  # type: ignore[attr-defined]  # pylint: disable=protected-access
    dock.roots._RootsPanel__on_roots_context_menu(QPoint(1, 1))  # type: ignore[attr-defined]  # pylint: disable=protected-access

    assert not RecordingMenu.shown


def test_the_empty_part_of_a_column_opens_its_folders_menu_and_leaves_the_selection(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, records: Path
) -> None:
    """A right-click below the last row of a column opens the menu of the folder that column lists, acting on that
    folder while it is open, with the selection where it was and the verbs put back for it afterwards; on the column of
    roots it offers Scan, Add Root and Refresh; off every column it opens nothing.

    **Test steps:**

    * select a file in a subfolder and show the panel
    * right-click below the rows of the folder's column, then of the roots column, then off the panel
    * verify each menu, that Open in file explorer acted on the folder, and that nothing moved
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    roots, view = dock.roots, dock.roots.roots_view
    reveal = mocker.patch("rehuco_agent.rehuco.roots_panel.reveal_in_file_browser")

    class ChoosingMenu(QMenu):
        """A menu that records its entries and, when asked, runs the one with this text."""

        shown: list[list[str]] = []
        chosen = ""

        def exec(self, *_args: object) -> None:  # type: ignore[override]
            """Record the entries and run the chosen one."""
            ChoosingMenu.shown.append([action.text() for action in self.actions()])
            for action in self.actions():
                if action.text() == ChoosingMenu.chosen:
                    action.trigger()

    mocker.patch("rehuco_agent.rehuco.roots_panel.QMenu", ChoosingMenu)
    ChoosingMenu.shown, ChoosingMenu.chosen = [], "Open in file explorer"
    roots.show()
    roots.resize(1400, 700)
    qtbot.waitExposed(roots)
    current = open_root_folder(qtbot, dock, "res", "sub", "a.mp4")
    res = roots.roots_model.index_for(UUID(ROOT_IDS[0]), ("res",))
    columns = {
        c.rootIndex(): c for c in view.findChildren(QAbstractItemView) if c is not view and c.model() is not None
    }

    def below_the_rows(column: QAbstractItemView) -> QPoint:
        viewport = column.viewport()
        point = QPoint(5, viewport.height() - 5)
        assert not column.indexAt(point).isValid()
        return view.mapFromGlobal(viewport.mapToGlobal(point))

    assert roots.verify_record_action.text() == "Verify all files of the parent resource"
    roots._RootsPanel__on_roots_context_menu(below_the_rows(columns[res]))  # type: ignore[attr-defined]  # pylint: disable=protected-access

    assert [entry for entry in ChoosingMenu.shown[-1] if entry] == [
        "Open associated rehu",
        "Show only rehu in this folder",
        "Open in file explorer",
        "Verify all files in the folder",
    ]
    reveal.assert_called_once_with(records / "res")
    assert view.currentIndex() == current
    assert roots.verify_record_action.text() == "Verify all files of the parent resource"
    assert pane_buttons(dock, current)[-2:] == [roots.verify_record_action, roots.verify_file_action]

    ChoosingMenu.chosen = ""
    roots._RootsPanel__on_roots_context_menu(below_the_rows(columns[QModelIndex()]))  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert ChoosingMenu.shown[-1] == ["Scan", "Add Root...", "Refresh"]
    assert view.currentIndex() == current

    ChoosingMenu.shown = []
    roots._RootsPanel__on_roots_context_menu(QPoint(-500, -500))  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert not ChoosingMenu.shown


# endregion
