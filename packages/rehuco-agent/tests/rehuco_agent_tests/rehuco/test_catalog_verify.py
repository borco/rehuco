"""Tests for verify-on-access in the Root Catalog: what a Roots listing and an opened record do to the cache (#487,
[[data-model#scan-and-staleness]]).

The cache is the real one over the suite's in-memory database, and the folders are real, under ``tmp_path``; only the
``.rehuco`` itself is served.
"""

import logging
import threading
from pathlib import Path
from sqlite3 import OperationalError
from typing import Any
from unittest.mock import MagicMock

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QLabel
from pytest import LogCaptureFixture, fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco.root_folder_loader import RootFolderLoader
from rehuco_agent.rehuco.roots_panel import FRESH_LISTING_SECONDS
from rehuco_agent.resource_events import ResourceEvents
from rehuco_core import CatalogRecordReader, RecordsChecked, RehuDocument

from .test_catalog_docks import (  # noqa: F401  # pylint: disable=unused-import
    REHUCO_PATH,
    WAIT_TIMEOUT_MS,
    CatalogDocks,
    build_docks,
    fixture_database,
    fixture_dock,
    fixture_folders,
    fixture_queue,
    fixture_served,
    open_root_folder,
)


def write_pack_record(path: Path, title: str = "Pack") -> None:
    """Write a reference-images ``.rehu``.

    :param path: where the record goes.
    :param title: its title.
    """
    path.touch()  # the suite's default ``Path.stat`` answers a missing file with a mock the atomic write cannot use
    document = RehuDocument.new(path)
    document.set_active_type("ReferenceImages")
    document.title = title
    document.save()


def reads_of(mocker: MockerFixture) -> MagicMock:
    """Spy on every record read a verify makes, noting the thread each runs on.

    :param mocker: pytest-mock fixture.
    :returns: the spy; each call's thread is in its ``threads`` attribute.
    """
    real = CatalogRecordReader.read
    threads: list[threading.Thread] = []

    def read(path: Path) -> Any:
        threads.append(threading.current_thread())
        return real(path)

    spy = mocker.patch("rehuco_core.rehudb_updates.CatalogRecordReader.read", side_effect=read)
    spy.threads = threads
    return spy


def settle(qtbot: QtBot) -> None:
    """Let every listing, its verify and their answers land: each hop is a pool job whose answer is a queued call.

    :param qtbot: pytest-qt fixture.
    """
    for _ in range(4):
        QThreadPool.globalInstance().waitForDone()
        qtbot.wait(20)


def pack_line(dock: CatalogDocks) -> str:
    """What the Roots pane's *Pack* row says."""
    label = dock.roots.findChild(QLabel, "pack_value")
    assert label is not None
    return label.text() if label.isVisibleTo(dock.roots) else ""


@mark.usefixtures("served")
def test_a_listed_folder_gives_a_record_with_no_row_its_row_and_the_pane_its_pack_line(
    qtbot: QtBot, dock: CatalogDocks, folders: Path, mocker: MockerFixture
) -> None:
    """Listing a folder reads a record the cache has no row for, off the GUI thread; the pane follows (#487).

    **Test steps:**

    * a reference pack, ``pack.zip`` with its ``pack.rehu``, that no scan has read
    * open its folder and select the zip
    * verify the record was read on a pool thread, the cache now types it, and the pane says it is a pack
    """
    folder = folders / "my folder"
    (folder / "pack.zip").write_bytes(b"z")
    write_pack_record(folder / "pack.rehu")
    reads = reads_of(mocker)
    dock.catalog.open_rehuco(REHUCO_PATH)
    assert dock.catalog.resource_type(folder / "pack.rehu") is None

    open_root_folder(qtbot, dock, "my folder", "pack.zip")

    qtbot.waitUntil(lambda: dock.catalog.resource_type(folder / "pack.rehu") is not None, timeout=WAIT_TIMEOUT_MS)
    qtbot.waitUntil(lambda: pack_line(dock).startswith("Reference images"), timeout=WAIT_TIMEOUT_MS)
    assert reads.call_count >= 1
    assert all(thread is not threading.main_thread() for thread in reads.threads)


@mark.usefixtures("served")
def test_a_record_is_read_again_only_once_it_changed(
    qtbot: QtBot, dock: CatalogDocks, folders: Path, mocker: MockerFixture
) -> None:
    """A folder listed again checks its records by their stat signature: a matching one is not read, a changed one is.

    **Test steps:**

    * list a folder whose record has no row, and wait for its read
    * list it again: verify nothing is read
    * change the record outside the app and list it again: verify it is read, and the cache has the new title
    """
    folder = folders / "my folder"
    record = folder / "pack.rehu"
    write_pack_record(record, "Old")
    reads = reads_of(mocker)
    dock.catalog.open_rehuco(REHUCO_PATH)
    index = open_root_folder(qtbot, dock, "my folder")
    settle(qtbot)
    assert reads.call_count == 1

    dock.roots.roots_model.relist(index)
    settle(qtbot)
    assert reads.call_count == 1

    write_pack_record(record, "New, and longer")
    dock.roots.roots_model.relist(index)
    qtbot.waitUntil(lambda: reads.call_count == 2, timeout=WAIT_TIMEOUT_MS)
    browser, *_ = dock.browsers.browsers
    qtbot.waitUntil(
        lambda: [row.record.title for row in dock.catalog.rows(browser.query)] == ["New, and longer"],
        timeout=WAIT_TIMEOUT_MS,
    )


@mark.usefixtures("served")
def test_a_record_under_a_root_that_is_offline_is_not_read_and_keeps_its_row(
    qtbot: QtBot, dock: CatalogDocks, mocker: MockerFixture
) -> None:
    """A root that is not there says nothing about what is in it (#487, [[mounts-and-storage#offline-mounts]]).

    **Test steps:**

    * verify a record under the served roots, whose folders do not exist
    * verify nothing was read, and no row was written or announced
    """
    reads = reads_of(mocker)
    changed = MagicMock()
    dock.catalog.open_rehuco(REHUCO_PATH)
    dock.catalog.rows_changed.connect(changed)
    file = dock.catalog.file
    assert file is not None
    first, *_ = file.roots
    root = first.path

    dock.catalog.verify_records([root / "gone" / "info.rehu"], key="probe")
    qtbot.wait(200)

    reads.assert_not_called()
    changed.assert_not_called()


@mark.usefixtures("served")
def test_an_opened_record_is_verified_through_the_app_announcements(
    qtbot: QtBot, queue: Any, database: Any, folders: Path, mocker: MockerFixture
) -> None:
    """Opening a record announces it, and the catalog verifies it -- the route every open takes (#487).

    **Test steps:**

    * a record no scan has read, and a catalog listening to the app's announcements
    * announce it as accessed, as the document registry does on an open
    * verify it was read, and its row exists
    """
    del database  # the cache's, in memory
    events = ResourceEvents()
    docks = build_docks(qtbot, queue, events)
    record = folders / "alpha" / "info.rehu"
    write_pack_record(record)
    reads = reads_of(mocker)
    docks.catalog.open_rehuco(REHUCO_PATH)
    try:
        events.announce_accessed((record,))

        qtbot.waitUntil(lambda: docks.catalog.resource_type(record) is not None, timeout=WAIT_TIMEOUT_MS)
        reads.assert_called_once()
    finally:
        docks.detach()


@mark.usefixtures("real_path_stat")
def test_the_files_open_documents_stand_for_are_read_on_the_pool_and_announced(
    qtbot: QtBot, dock: CatalogDocks, folders: Path
) -> None:
    """What a scan's end asks of the open documents' files: their time and size, off the GUI thread; a file that is
    not there is left out (#487).

    **Test steps:**

    * ask for a record that is there and one that is not
    * verify one announcement, of the first, with its time and size
    """
    record = folders / "alpha" / "info.rehu"
    write_pack_record(record)
    stat = record.stat()

    with qtbot.waitSignal(dock.catalog.files_seen, timeout=WAIT_TIMEOUT_MS) as seen:
        dock.catalog.read_signatures([record, folders / "gone.rehu"])

    assert seen.args == [{record: (stat.st_mtime_ns, stat.st_size)}]


# region What goes wrong between the GUI thread and the pool (#487)


def seam(dock: CatalogDocks, name: str) -> Any:
    """One of the catalog's private members, which these tests reach by design: the thread hops cannot be provoked
    through the public surface.

    :param dock: the catalog's docks.
    :param name: the member's name.
    :returns: it.
    """
    return getattr(dock.catalog, f"_RootCatalog__{name}")


@mark.usefixtures("served")
def test_a_cache_that_cannot_be_read_verifies_nothing_and_says_so(
    qtbot: QtBot, dock: CatalogDocks, folders: Path, mocker: MockerFixture, caplog: LogCaptureFixture
) -> None:
    """A failing plan is logged, and nothing is queued (#487).

    **Test steps:**

    * make the plan fail with a database error, and verify a record
    * verify the error is logged and nothing is announced
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    mocker.patch("rehuco_agent.rehuco.root_catalog.CatalogRecordUpdater.plan", side_effect=OperationalError("locked"))
    seen = MagicMock()
    dock.catalog.files_seen.connect(seen)

    with caplog.at_level(logging.ERROR):
        dock.catalog.verify_records([folders / "alpha" / "info.rehu"], key="probe")
    settle(qtbot)

    assert "Could not read the cache" in caplog.text
    seen.assert_not_called()


@mark.usefixtures("served")
def test_a_check_that_fails_is_logged_and_still_releases_its_key(
    qtbot: QtBot, dock: CatalogDocks, folders: Path, mocker: MockerFixture, caplog: LogCaptureFixture
) -> None:
    """The pool swallows what escapes a job, so a failing check answers empty: the key is released and nothing is
    announced (#487).

    **Test steps:**

    * make the check fail, and verify a record that has a row to check
    * verify the failure is logged, nothing is announced, and the key no longer waits for an answer
    """
    write_pack_record(folders / "alpha" / "info.rehu")
    dock.catalog.open_rehuco(REHUCO_PATH)
    mocker.patch("rehuco_agent.rehuco.root_catalog.check_records", side_effect=RuntimeError("boom"))
    seen = MagicMock()
    dock.catalog.files_seen.connect(seen)

    with caplog.at_level(logging.ERROR):
        dock.catalog.verify_records([folders / "alpha" / "info.rehu"], key="probe")
        settle(qtbot)

    assert "Could not verify 1 records" in caplog.text
    assert not seam(dock, "latest_verify")
    seen.assert_not_called()


@mark.usefixtures("served")
def test_a_check_superseded_before_it_starts_does_nothing(dock: CatalogDocks, mocker: MockerFixture) -> None:
    """A newer check of the same key leaves an older one that has not started to do nothing (#487).

    **Test steps:**

    * note a newer check for a key, then run an older one
    * verify it compared nothing with the disk
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    check = mocker.patch("rehuco_agent.rehuco.root_catalog.check_records")
    seam(dock, "latest_verify")["probe"] = 2

    seam(dock, "run_verify")(1, "probe", seam(dock, "cache"), [])

    check.assert_not_called()


@mark.usefixtures("served")
def test_an_answer_superseded_while_it_was_out_is_dropped_on_the_gui_thread(dock: CatalogDocks, folders: Path) -> None:
    """A newer check of a key makes an older answer that arrives late say nothing: it is judged where it lands, not
    where it was made (#487).

    **Test steps:**

    * note a newer check for a key, then deliver an older answer that saw a file
    * verify nothing was announced, and the newer check is still waited for
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    seen = MagicMock()
    dock.catalog.files_seen.connect(seen)
    seam(dock, "latest_verify")["probe"] = 2
    stale = RecordsChecked([], {folders / "alpha" / "info.rehu": (1, 1)})

    seam(dock, "on_verified")(1, "probe", seam(dock, "cache"), stale)

    seen.assert_not_called()
    assert dict(seam(dock, "latest_verify")) == {"probe": 2}


@mark.usefixtures("served")
def test_an_answer_for_a_catalog_that_is_gone_is_dropped_quietly(dock: CatalogDocks, mocker: MockerFixture) -> None:
    """The pool may finish after the window is gone: the answer has nowhere to go, and that is not an error (#487).

    **Test steps:**

    * make every answer's emit fail as a destroyed object's does
    * run a check, and a read of file states: verify neither raises
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    seam(dock, "latest_verify")["probe"] = 1
    dead = mocker.MagicMock()
    dead.answered.emit.side_effect = RuntimeError("Internal C++ object already deleted")
    dead.statted.emit.side_effect = RuntimeError("Internal C++ object already deleted")
    mocker.patch.object(dock.catalog, "_RootCatalog__verifier", dead)

    seam(dock, "run_verify")(1, "probe", seam(dock, "cache"), [])
    seam(dock, "run_stat")(1, [])

    dead.answered.emit.assert_called_once()
    dead.statted.emit.assert_called_once()


@mark.usefixtures("served")
def test_a_read_of_file_states_that_fails_still_answers_and_says_nothing_of_it(
    dock: CatalogDocks, mocker: MockerFixture, caplog: LogCaptureFixture
) -> None:
    """An unexpected failure is logged, and an answer with no files announces nothing (#487).

    **Test steps:**

    * read the state of a file whose stat raises something that is no OSError
    * verify the failure is logged, and the empty answer announces nothing
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    seen = MagicMock()
    dock.catalog.files_seen.connect(seen)
    bad = mocker.MagicMock()
    bad.stat.side_effect = RuntimeError("boom")

    with caplog.at_level(logging.ERROR):
        seam(dock, "run_stat")(1, [bad])
    seam(dock, "on_statted")(1, {})

    assert "Could not read the state of 1 files" in caplog.text
    seen.assert_not_called()


def verify_a_new_record(qtbot: QtBot, dock: CatalogDocks, folders: Path) -> tuple[MagicMock, MagicMock]:
    """Verify a record the cache has no row for, through whatever now writes the findings back.

    :param qtbot: pytest-qt fixture.
    :param dock: the catalog's docks.
    :param folders: the first root's folder.
    :returns: what heard :attr:`~RootCatalog.rows_changed` and :attr:`~RootCatalog.records_verified`.
    """
    write_pack_record(folders / "alpha" / "info.rehu")
    dock.catalog.open_rehuco(REHUCO_PATH)
    rows, verified = MagicMock(), MagicMock()
    dock.catalog.rows_changed.connect(rows)
    dock.catalog.records_verified.connect(verified)
    dock.catalog.verify_records([folders / "alpha" / "info.rehu"], key="probe")
    settle(qtbot)
    return rows, verified


@mark.usefixtures("served")
def test_a_write_back_that_fails_is_logged_and_announces_no_row(
    qtbot: QtBot, dock: CatalogDocks, folders: Path, mocker: MockerFixture, caplog: LogCaptureFixture
) -> None:
    """A failed write is logged, and says no row changed (#487).

    **Test steps:**

    * verify a record the cache has no row for, with the write-back failing
    * verify the failure is logged and no row change is announced
    """
    mocker.patch("rehuco_agent.rehuco.root_catalog.CatalogRecordUpdater.apply", side_effect=OperationalError("locked"))

    with caplog.at_level(logging.ERROR):
        rows, verified = verify_a_new_record(qtbot, dock, folders)

    assert "Could not update the cache" in caplog.text
    rows.assert_not_called()
    verified.assert_not_called()


@mark.usefixtures("served")
def test_a_write_back_that_changes_nothing_announces_no_row(
    qtbot: QtBot, dock: CatalogDocks, folders: Path, mocker: MockerFixture
) -> None:
    """A write that left every row as it was is quiet (#487).

    **Test steps:**

    * verify a record the cache has no row for, with a write-back that changes nothing
    * verify no row change is announced
    """
    mocker.patch("rehuco_agent.rehuco.root_catalog.CatalogRecordUpdater.apply", return_value=set())

    rows, verified = verify_a_new_record(qtbot, dock, folders)

    rows.assert_not_called()
    verified.assert_not_called()


# endregion


# region When the selection lists a folder again (#487)


class Clock:  # pylint: disable=too-few-public-methods
    """A clock the test moves by hand, standing in for ``time.monotonic``."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def listed_folders(start: MagicMock) -> list[tuple[str, ...]]:
    """The folders a spy on :meth:`RootFolderLoader.start` was asked to list, in order.

    :param start: the spy.
    :returns: each call's folder, as the names below its root.
    """
    return [call.args[3] for call in start.call_args_list]


def select(dock: CatalogDocks, *names: str) -> None:
    """Make a folder or file of the first root the Roots view's current row.

    :param dock: the catalog's docks.
    :param names: the names down from the first root.
    """
    file = dock.catalog.file
    assert file is not None
    first, *_ = file.roots
    dock.roots.roots_view.setCurrentIndex(dock.roots.roots_model.index_for(first.root_id, names))


@fixture(name="visited")
def fixture_visited(
    qtbot: QtBot, dock: CatalogDocks, folders: Path, mocker: MockerFixture
) -> tuple[CatalogDocks, Clock, MagicMock]:
    """A catalog whose first root's ``alpha`` and ``my folder`` have both been entered, with every later listing spied
    on and the clock held by hand.

    :param qtbot: pytest-qt fixture.
    :param dock: the catalog's docks.
    :param folders: the first root's folder; ``alpha`` gets a second file.
    :param mocker: pytest-mock fixture.
    :returns: the docks, the clock and the spy on listings.
    """
    clock = Clock()
    mocker.patch("rehuco_agent.rehuco.roots_folder_model.time.monotonic", clock)
    (folders / "alpha" / "second.txt").write_text("s", encoding="utf-8")
    dock.catalog.open_rehuco(REHUCO_PATH)
    open_root_folder(qtbot, dock, "alpha")
    open_root_folder(qtbot, dock, "my folder")
    settle(qtbot)
    return dock, clock, mocker.patch.object(RootFolderLoader, "start")


@mark.usefixtures("served")
def test_moving_between_the_files_of_one_folder_lists_nothing(visited: tuple[CatalogDocks, Clock, MagicMock]) -> None:
    """Arrowing through a folder's files enters no folder, so no listing is started per file -- on the folder's own
    account, not because its listing is still fresh (#487).

    **Test steps:**

    * enter a folder, and let its listing go stale
    * make each of two of its files the current row in turn
    * verify no listing was started by moving between them
    """
    dock, clock, start = visited
    select(dock, "alpha")
    clock.now += FRESH_LISTING_SECONDS + 1
    start.reset_mock()

    select(dock, "alpha", "note.txt")
    select(dock, "alpha", "second.txt")
    select(dock, "alpha", "note.txt")

    start.assert_not_called()


@mark.usefixtures("served")
def test_returning_to_a_folder_lists_it_again_only_once_its_listing_is_stale(
    visited: tuple[CatalogDocks, Clock, MagicMock],
) -> None:
    """A folder the selection comes back to within the window is shown as it was; after it, it is read again -- by a
    time stamp compared at the visit, not by a timer (#487).

    **Test steps:**

    * return to a folder listed a moment ago: verify nothing is started
    * move the clock past the window and return to the other: verify only that folder is listed again
    """
    dock, clock, start = visited
    select(dock, "alpha")
    start.assert_not_called()

    clock.now += FRESH_LISTING_SECONDS + 1
    select(dock, "my folder")

    assert listed_folders(start) == [("my folder",)]


@mark.usefixtures("served")
def test_refresh_lists_the_open_folders_again_whatever_their_age(
    visited: tuple[CatalogDocks, Clock, MagicMock],
) -> None:
    """F5 never waits for a window (#487).

    **Test steps:**

    * make a folder listed a moment ago the current row, and press Refresh
    * verify the folder and the root above it were listed again
    """
    dock, _clock, start = visited
    select(dock, "alpha")
    start.reset_mock()

    dock.roots.refresh_roots_action.trigger()

    assert ("alpha",) in listed_folders(start)
    assert () in listed_folders(start)


# endregion
