"""Tests for verify-on-access in the Root Catalog: what a Roots listing and an opened record do to the cache (#487,
[[data-model#scan-and-staleness]]).

The cache is the real one over the suite's in-memory database, and the folders are real, under ``tmp_path``; only the
``.rehuco`` itself is served.
"""

import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QLabel
from pytest import mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.resource_events import ResourceEvents
from rehuco_core import CatalogRecordReader, RehuDocument

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
