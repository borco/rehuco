"""Tests for verify-on-access in the Root Catalog: how a Roots listing and an opened record are planned against the
cache, checked against the disk on the pool and written back on the GUI thread (#487,
[[data-model#scan-and-staleness]]).

The catalog is a mock, and so is the check (``check_records``): planning, checking and writing back are each core's
and tested there. What is left, and tested here, is the catalog's routing between them and the threads it runs them on.
The folders are real, under ``tmp_path``, so the Roots view lists them; only the ``.rehuco`` itself is served.
"""

import logging
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, Mock

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QLabel
from pytest import LogCaptureFixture, fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco.root_folder_loader import RootFolderLoader
from rehuco_agent.rehuco.roots_panel import FRESH_LISTING_SECONDS
from rehuco_agent.resource_events import ResourceEvents
from rehuco_core import CatalogRecord, CatalogRow, RecordKind, RecordsChecked
from rehuco_core.access import ResourceKey

from rehuco_agent_tests.delete_at_teardown import DeleteAtTeardown

from .test_catalog_docks import (  # noqa: F401  # pylint: disable=unused-import
    REHUCO_PATH,
    WAIT_TIMEOUT_MS,
    CatalogDocks,
    build_docks,
    catalog_row,
    fixture_cache,
    fixture_cached_rows,
    fixture_catalog,
    fixture_dock,
    fixture_folders,
    fixture_no_open_scan,
    fixture_queue,
    fixture_served,
    open_root_folder,
)


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


def checked_on_the_pool(mocker: MockerFixture, catalog: Mock) -> list[threading.Thread]:
    """Make every verify from now on plan one check, and the check of it find one finding, noting the thread each
    check runs on; the plans asked before are forgotten.

    :param mocker: pytest-mock fixture.
    :param catalog: the mock catalog.
    :returns: the threads the checks ran on, in order.
    """
    threads: list[threading.Thread] = []
    catalog.plan_verify.reset_mock()
    catalog.plan_verify.return_value = [MagicMock()]

    def check(*_args: object) -> RecordsChecked:
        threads.append(threading.current_thread())
        return RecordsChecked([MagicMock()], {})

    mocker.patch("rehuco_agent.rehuco.root_catalog.check_records", side_effect=check)
    return threads


@mark.usefixtures("served")
# pylint: disable-next=too-many-arguments,too-many-positional-arguments
def test_a_listed_folder_gives_a_record_with_no_row_its_row_and_the_pane_its_pack_line(
    qtbot: QtBot,
    queue: Any,
    catalog: Mock,
    cached_rows: list[CatalogRow],
    folders: Path,
    mocker: MockerFixture,
    delete_at_teardown: DeleteAtTeardown,
) -> None:
    """Listing a folder plans its records against the cache, checks them off the GUI thread, writes what the check
    found back, and publishes it on the change feed; the pane follows it from there (#487, #511).

    **Test steps:**

    * a reference pack, ``pack.zip`` with its ``pack.rehu``, that the cache has no row for, under docks following the
      app's events; a write-back that gives the record a reference-images row
    * open its folder and select the zip
    * verify the check ran on a pool thread, the record was published as changed, and the pane says it is a pack
    """
    events = delete_at_teardown(ResourceEvents())
    heard = MagicMock()
    events.changed.connect(heard)
    dock = build_docks(qtbot, queue, events, catalog=catalog)
    folder = folders / "my folder"
    (folder / "pack.zip").write_bytes(b"z")
    (folder / "pack.rehu").write_bytes(b"")
    threads = checked_on_the_pool(mocker, catalog)

    def apply(_findings: object) -> tuple[set[int], set[Path]]:
        cached_rows.append(
            catalog_row(1, 0, CatalogRecord("my folder/pack.rehu", RecordKind.REHU, type="ReferenceImages"))
        )
        return {1}, {folder / "pack.rehu"}

    catalog.apply_verify.side_effect = apply
    dock.catalog.open_rehuco(REHUCO_PATH)
    try:
        open_root_folder(qtbot, dock, "my folder", "pack.zip")

        qtbot.waitUntil(lambda: pack_line(dock).startswith("Reference images"), timeout=WAIT_TIMEOUT_MS)
        assert threads
        assert all(thread is not threading.main_thread() for thread in threads)
        heard.assert_any_call((ResourceKey(folder / "pack.rehu"),))
    finally:
        dock.detach()


@mark.usefixtures("served")
# pylint: disable-next=too-many-arguments,too-many-positional-arguments
def test_an_opened_record_is_verified_through_the_app_announcements(
    qtbot: QtBot, queue: Any, catalog: Mock, folders: Path, mocker: MockerFixture, delete_at_teardown: DeleteAtTeardown
) -> None:
    """Opening a record announces it, and the catalog verifies it -- the route every open takes (#487).

    **Test steps:**

    * a catalog listening to the app's announcements
    * announce a record as accessed, as the document registry does on an open
    * verify the record was planned, and checked on the pool
    """
    events = delete_at_teardown(ResourceEvents())
    docks = build_docks(qtbot, queue, events, catalog=catalog)
    record = folders / "alpha" / "info.rehu"
    docks.catalog.open_rehuco(REHUCO_PATH)
    settle(qtbot)
    threads = checked_on_the_pool(mocker, catalog)
    try:
        events.announce_accessed((ResourceKey(record),))

        qtbot.waitUntil(lambda: len(threads) == 1, timeout=WAIT_TIMEOUT_MS)
        catalog.plan_verify.assert_called_once_with([ResourceKey(record)])
        assert threads[0] is not threading.main_thread()
    finally:
        docks.detach()


@mark.usefixtures("served")
def test_a_relative_path_among_the_records_to_verify_is_passed_over(
    dock: CatalogDocks, catalog: Mock, folders: Path
) -> None:
    """A relative path is no record of any root: a verify passes it over and still plans the others (#417).

    **Test steps:**

    * verify a relative path and an absolute record together
    * verify only the record was planned
    """
    record = folders / "alpha" / "info.rehu"
    dock.catalog.open_rehuco(REHUCO_PATH)

    dock.catalog.verify_records([Path("alpha") / "info.rehu", record], key="probe")

    catalog.plan_verify.assert_called_once_with([ResourceKey(record)])


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
# pylint: disable-next=too-many-arguments,too-many-positional-arguments
def test_a_check_that_fails_is_logged_and_still_releases_its_key(
    qtbot: QtBot, dock: CatalogDocks, catalog: Mock, folders: Path, mocker: MockerFixture, caplog: LogCaptureFixture
) -> None:
    """The pool swallows what escapes a job, so a failing check answers empty: the key is released and nothing is
    announced (#487).

    **Test steps:**

    * make the check fail, and verify a record the plan has a check for
    * verify the failure is logged, nothing is announced, and the key no longer waits for an answer
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    catalog.plan_verify.return_value = [MagicMock()]
    mocker.patch("rehuco_agent.rehuco.root_catalog.check_records", side_effect=RuntimeError("boom"))
    seen = MagicMock()
    dock.catalog.rows_changed.connect(seen)

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

    seam(dock, "run_verify")(1, "probe", seam(dock, "catalog").cache_path, [])

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
    dock.catalog.rows_changed.connect(seen)
    seam(dock, "latest_verify")["probe"] = 2
    stale = RecordsChecked([], {folders / "alpha" / "info.rehu": (1, 1)})

    seam(dock, "on_verified")(1, "probe", seam(dock, "catalog").cache_path, stale)

    seen.assert_not_called()
    assert dict(seam(dock, "latest_verify")) == {"probe": 2}


@mark.usefixtures("served")
def test_an_answer_for_a_catalog_that_is_gone_is_dropped_quietly(dock: CatalogDocks, mocker: MockerFixture) -> None:
    """The pool may finish after the window is gone: the answer has nowhere to go, and that is not an error (#487).

    **Test steps:**

    * make the answer's emit fail as a destroyed object's does
    * run a check: verify it does not raise
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    seam(dock, "latest_verify")["probe"] = 1
    dead = mocker.MagicMock()
    dead.answered.emit.side_effect = RuntimeError("Internal C++ object already deleted")
    mocker.patch.object(dock.catalog, "_RootCatalog__verifier", dead)

    seam(dock, "run_verify")(1, "probe", seam(dock, "catalog").cache_path, [])

    dead.answered.emit.assert_called_once()


@mark.usefixtures("served")
def test_a_write_back_that_changes_nothing_announces_no_row(
    qtbot: QtBot, dock: CatalogDocks, catalog: Mock, folders: Path, mocker: MockerFixture
) -> None:
    """A write that left every row as it was is quiet (#487).

    **Test steps:**

    * verify a record whose check finds something, with a write-back that changes no record
    * verify the write-back ran and no row change is announced
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    settle(qtbot)
    checked_on_the_pool(mocker, catalog)
    catalog.apply_verify.return_value = ({1}, set())
    rows = MagicMock()
    dock.catalog.rows_changed.connect(rows)

    dock.catalog.verify_records([folders / "alpha" / "info.rehu"], key="probe")
    settle(qtbot)

    catalog.apply_verify.assert_called_once()
    rows.assert_not_called()


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
