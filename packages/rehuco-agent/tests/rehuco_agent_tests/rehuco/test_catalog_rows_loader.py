"""Tests for the browsers' rows read off the GUI thread (#455): one read at a time, the rest merged, a superseded or
cancelled answer dropped, and the collector paused while rows are built.

Every read here is a :class:`GatedReader`: a test that needs a read to be out holds its gate shut and waits for the
read to enter, rather than hoping a sleep is long enough.
"""

import gc
import logging
import threading
from collections.abc import Generator
from dataclasses import replace
from typing import Final
from uuid import uuid4

import shiboken6
from PySide6.QtCore import QThreadPool
from pytest import LogCaptureFixture, fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco.catalog_rows_loader import CatalogRowsLoad, CatalogRowsLoader
from rehuco_core import CatalogQuery, CatalogRecord, CatalogRow, CatalogUnreadable, RecordKind

ROOT_ID: Final = uuid4()

GATE_TIMEOUT: Final = 120.0
"""How long a gated read waits to be let through, in seconds -- a deadlock guard no test is meant to reach."""

WAIT_TIMEOUT_MS: Final = 10_000
"""How long a test waits for the GUI thread to see an answer."""


def catalog_row(resource_id: int, title: str) -> CatalogRow:
    """A row of the one root.

    :param resource_id: its id.
    :param title: its title, which is also its folder.
    :returns: the row.
    """
    return CatalogRow(
        resource_id, ROOT_ID, "root", CatalogRecord(f"{title}/info.rehu", RecordKind.REHU, title=title), 0.0
    )


class GatedReader:
    """What a loader reads through: the rows it holds now, each read noted and held at a gate until let through."""

    def __init__(self) -> None:
        self.rows: list[CatalogRow] = [catalog_row(1, "alpha"), catalog_row(2, "beta")]
        self.calls: Final[list[set[int] | None]] = []
        self.collecting: Final[list[bool]] = []
        """Whether the collector was on during each read."""
        self.failure: Exception | None = None
        self.entered: Final = threading.Event()
        self.gate: Final = threading.Event()
        self.gate.set()

    def __call__(self, query: CatalogQuery, ids: set[int] | None) -> list[CatalogRow]:
        """Note the read, wait at the gate, then answer every row or the ones ``ids`` names.

        :param query: always every row's.
        :param ids: the rows to read, or ``None`` for all.
        :returns: the rows.
        :raises Exception: :attr:`failure`, when set -- once, the next read answering again.
        """
        assert query == CatalogQuery()
        self.calls.append(ids)
        self.collecting.append(gc.isenabled())
        self.entered.set()
        assert self.gate.wait(GATE_TIMEOUT), "the gate was never opened"
        failure, self.failure = self.failure, None
        if failure is not None:
            raise failure
        return [row for row in self.rows if ids is None or row.resource_id in ids]

    def hold(self) -> None:
        """Shut the gate, so the next read stays out until :meth:`release`."""
        self.entered.clear()
        self.gate.clear()

    def wait_entered(self) -> None:
        """Wait until a read has reached the gate."""
        assert self.entered.wait(WAIT_TIMEOUT_MS / 1000), "no read began"

    def release(self) -> None:
        """Let every read through."""
        self.gate.set()


@fixture(name="reader")
def fixture_reader() -> Generator[GatedReader]:
    """A reader, its gate opened at teardown so no pool thread is left waiting.

    :yields: the reader.
    """
    reader = GatedReader()
    yield reader
    reader.release()
    assert QThreadPool.globalInstance().waitForDone(int(WAIT_TIMEOUT_MS))


@fixture(name="loads")
def fixture_loads() -> list[CatalogRowsLoad]:
    """Where :func:`fixture_loader` notes each answer it delivers.

    :returns: the list.
    """
    return []


@fixture(name="loader")
def fixture_loader(qtbot: QtBot, reader: GatedReader, loads: list[CatalogRowsLoad]) -> CatalogRowsLoader:
    """A loader over ``reader``, noting what it delivers.

    :param qtbot: pytest-qt fixture.
    :param reader: what it reads through.
    :param loads: where its answers go.
    :returns: the loader.
    """
    del qtbot
    loader = CatalogRowsLoader(reader)
    loader.loaded.connect(loads.append)
    return loader


def wait_idle(qtbot: QtBot, loader: CatalogRowsLoader) -> None:
    """Wait until no read is out.

    :param qtbot: pytest-qt fixture.
    :param loader: the loader.
    """
    qtbot.waitUntil(lambda: not loader.busy, timeout=WAIT_TIMEOUT_MS)


def titles(load: CatalogRowsLoad) -> list[str]:
    """The titles a load's snapshot holds, in order.

    :param load: the answer.
    :returns: the titles.
    """
    return [row.record.title for row in load.snapshot.rows]


def test_a_refresh_delivers_every_row(qtbot: QtBot, loader: CatalogRowsLoader, loads: list[CatalogRowsLoad]) -> None:
    """A read of every row lands as one answer naming no rows in particular, and becomes the snapshot.

    **Test steps:**

    * refresh and wait for the read
    * verify one answer with both rows, no ids, the loader's snapshot the same and no read out
    """
    loader.refresh([ROOT_ID])
    assert loader.busy

    wait_idle(qtbot, loader)

    (load,) = loads
    assert (titles(load), load.affected) == (["alpha", "beta"], None)
    assert loader.snapshot is load.snapshot
    assert load.snapshot.root_ids == (ROOT_ID,)


def test_an_update_patches_just_the_rows_it_names(
    qtbot: QtBot, loader: CatalogRowsLoader, reader: GatedReader, loads: list[CatalogRowsLoad]
) -> None:
    """A change reads back only its rows and patches them into the snapshot.

    **Test steps:**

    * refresh, then retitle a row and update it
    * verify the second read asked for that row alone, and the answer names it and holds the new title
    """
    loader.refresh([ROOT_ID])
    wait_idle(qtbot, loader)
    reader.rows = [catalog_row(1, "zulu"), catalog_row(2, "beta")]

    loader.update({1})
    wait_idle(qtbot, loader)

    assert reader.calls == [None, {1}]
    assert (titles(loads[-1]), loads[-1].affected) == (["beta", "zulu"], frozenset({1}))


def test_two_refreshes_in_a_row_show_the_second(
    qtbot: QtBot, loader: CatalogRowsLoader, reader: GatedReader, loads: list[CatalogRowsLoad]
) -> None:
    """A refresh asked for while one is out waits for it, and the first answer, already superseded, is never shown.

    **Test steps:**

    * hold the reader, refresh, and once the read is out change the rows and refresh again
    * let both reads through
    * verify two reads, one answer, and that answer the second read's rows
    """
    reader.hold()
    loader.refresh([ROOT_ID])
    reader.wait_entered()
    reader.rows = [catalog_row(3, "gamma")]
    loader.refresh([ROOT_ID])

    reader.release()
    qtbot.waitUntil(lambda: len(reader.calls) == 2, timeout=WAIT_TIMEOUT_MS)
    wait_idle(qtbot, loader)

    assert reader.calls == [None, None]
    assert [titles(load) for load in loads] == [["gamma"]]


def test_an_update_waiting_behind_a_refresh_is_absorbed_by_it(
    qtbot: QtBot, loader: CatalogRowsLoader, reader: GatedReader
) -> None:
    """A read of every row waiting covers the rows a change touched, so the change starts no read of its own.

    **Test steps:**

    * hold the reader, refresh, and once the read is out refresh again and update a row
    * let the reads through
    * verify two reads of every row and none of a few
    """
    reader.hold()
    loader.refresh([ROOT_ID])
    reader.wait_entered()
    loader.refresh([ROOT_ID])
    loader.update({1})

    reader.release()
    qtbot.waitUntil(lambda: len(reader.calls) == 2, timeout=WAIT_TIMEOUT_MS)
    wait_idle(qtbot, loader)

    assert reader.calls == [None, None]


def test_changes_made_while_a_read_is_out_are_merged_and_read_after_it(
    qtbot: QtBot, loader: CatalogRowsLoader, reader: GatedReader, loads: list[CatalogRowsLoad]
) -> None:
    """Changes announced during a read wait for it, and are read back together once it lands -- whatever it saw.

    **Test steps:**

    * hold the reader, refresh, and once the read is out update one row, then another
    * let the reads through
    * verify the second read asked for both rows, after the first answer was shown
    """
    reader.hold()
    loader.refresh([ROOT_ID])
    reader.wait_entered()
    loader.update({1})
    loader.update({2})

    reader.release()
    qtbot.waitUntil(lambda: len(loads) == 2, timeout=WAIT_TIMEOUT_MS)

    assert reader.calls == [None, {1, 2}]
    assert [load.affected for load in loads] == [None, frozenset({1, 2})]


def test_an_update_naming_no_rows_reads_nothing(loader: CatalogRowsLoader, reader: GatedReader) -> None:
    """A change that touched no rows starts no read.

    **Test steps:**

    * update with no ids
    * verify nothing was read and no read is out
    """
    loader.update(set())

    assert not loader.busy
    assert not reader.calls


def test_a_cancelled_read_delivers_nothing_and_leaves_no_thread_running(
    qtbot: QtBot, loader: CatalogRowsLoader, reader: GatedReader, loads: list[CatalogRowsLoad]
) -> None:
    """A catalog closed while its read is out forgets it: the answer is dropped, what waited never starts, and the
    pool is left with nothing running.

    **Test steps:**

    * refresh and wait for the rows, then hold the reader, refresh, and queue an update behind it
    * cancel, then let the read through and wait for the pool
    * verify the snapshot is empty, no read is out, nothing was delivered after the first answer, and one read more
    """
    loader.refresh([ROOT_ID])
    wait_idle(qtbot, loader)
    reader.hold()
    loader.refresh([ROOT_ID])
    reader.wait_entered()
    loader.update({1})

    loader.cancel()
    reader.release()

    assert QThreadPool.globalInstance().waitForDone(WAIT_TIMEOUT_MS)
    qtbot.wait(50)
    assert not loader.snapshot.rows
    assert not loader.busy
    assert len(loads) == 1
    assert reader.calls == [None, None]


def test_a_loader_destroyed_while_its_read_is_out_delivers_nothing(qtbot: QtBot, reader: GatedReader) -> None:
    """A dock closed while its read is out takes the loader with it, and the read's answer goes nowhere, quietly.

    **Test steps:**

    * hold the reader, refresh, and delete the loader once the read is out
    * let the read through and wait for the pool
    * verify the read ran to its end and nothing raised
    """
    loader = CatalogRowsLoader(reader)
    reader.hold()
    loader.refresh([ROOT_ID])
    reader.wait_entered()

    shiboken6.delete(loader)
    reader.release()

    assert QThreadPool.globalInstance().waitForDone(WAIT_TIMEOUT_MS)
    qtbot.wait(50)
    assert reader.calls == [None]


def test_an_unreadable_catalog_is_logged_and_the_rows_kept(
    qtbot: QtBot,
    loader: CatalogRowsLoader,
    reader: GatedReader,
    loads: list[CatalogRowsLoad],
    caplog: LogCaptureFixture,
) -> None:
    """A read the catalog refuses keeps the rows shown, says why in the log, and does not hold up the next read.

    **Test steps:**

    * refresh, then make the reader refuse and refresh while holding it, with an update queued behind
    * let the reads through
    * verify the refusal was logged, nothing delivered for it, and the update read and patched into the kept rows
    """
    loader.refresh([ROOT_ID])
    wait_idle(qtbot, loader)
    kept = loader.snapshot
    reader.failure = CatalogUnreadable("locked")
    reader.hold()
    loader.refresh([ROOT_ID])
    reader.wait_entered()
    loader.update({1})

    with caplog.at_level(logging.ERROR):
        reader.release()
        qtbot.waitUntil(lambda: len(reader.calls) == 3, timeout=WAIT_TIMEOUT_MS)
        wait_idle(qtbot, loader)

    assert "Could not read the catalog's rows: locked" in caplog.text
    assert reader.calls == [None, None, {1}]
    assert [load.affected for load in loads] == [None, frozenset({1})]
    assert [row.resource_id for row in loads[-1].snapshot.rows] == [row.resource_id for row in kept.rows]


def test_an_unexpected_failure_is_logged_with_its_trace(
    qtbot: QtBot,
    loader: CatalogRowsLoader,
    reader: GatedReader,
    loads: list[CatalogRowsLoad],
    caplog: LogCaptureFixture,
) -> None:
    """A read that fails in a way nobody planned for is still answered, so the loader is never left busy.

    **Test steps:**

    * make the reader raise a ``ValueError``, and refresh
    * verify the failure was logged with its trace, nothing delivered and no read left out
    """
    reader.failure = ValueError("bad row")

    with caplog.at_level(logging.ERROR):
        loader.refresh([ROOT_ID])
        wait_idle(qtbot, loader)

    (logged,) = [entry for entry in caplog.records if entry.getMessage() == "Could not read the catalog's rows."]
    assert logged.exc_info is not None
    assert not loads


# region The collector


@fixture(name="collector_on")
def fixture_collector_on() -> Generator[None]:
    """The collector on for the test, and back as it was after it."""
    was_on = gc.isenabled()
    gc.enable()
    yield
    if not was_on:
        gc.disable()


def test_the_collector_is_off_while_rows_are_read_and_back_on_after(
    qtbot: QtBot, collector_on: None, loader: CatalogRowsLoader, reader: GatedReader
) -> None:
    """A read builds its rows with the collector off, and leaves it on again.

    **Test steps:**

    * with the collector on, refresh and wait for the rows
    * verify it was off during the read and is on now
    """
    del collector_on

    loader.refresh([ROOT_ID])
    wait_idle(qtbot, loader)

    assert reader.collecting == [False]
    assert gc.isenabled()


def test_nested_pauses_switch_the_collector_on_only_when_the_last_ends(collector_on: None) -> None:
    """Two reads pausing it together leave it off until both have ended.

    **Test steps:**

    * pause the collector, and pause it again inside
    * verify it is off inside both, still off after the inner one, and on after the outer one
    """
    del collector_on

    with CatalogRowsLoader.collector_paused():
        with CatalogRowsLoader.collector_paused():
            assert not gc.isenabled()
        assert not gc.isenabled()

    assert gc.isenabled()


def test_a_collector_already_off_is_left_off(collector_on: None) -> None:
    """A pause never switches on a collector someone else had switched off.

    **Test steps:**

    * switch the collector off, then pause and end the pause
    * verify it is still off
    """
    del collector_on
    gc.disable()

    with CatalogRowsLoader.collector_paused():
        pass

    assert not gc.isenabled()


# endregion


def test_a_patch_reads_the_rows_it_was_started_from(
    qtbot: QtBot, loader: CatalogRowsLoader, reader: GatedReader, loads: list[CatalogRowsLoad]
) -> None:
    """A read of a few rows patches the snapshot shown when it started, so a row gone from the cache leaves it.

    **Test steps:**

    * refresh, then remove a row from the catalog and update it
    * verify the answer names it and no longer holds it
    """
    loader.refresh([ROOT_ID])
    wait_idle(qtbot, loader)
    reader.rows = [replace(reader.rows[1])]

    loader.update({1})
    wait_idle(qtbot, loader)

    assert (titles(loads[-1]), loads[-1].affected) == (["beta"], frozenset({1}))
