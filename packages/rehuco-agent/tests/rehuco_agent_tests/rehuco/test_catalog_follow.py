"""Tests for what the Root Catalog and its docks follow from the roots' file notifiers (#511,
[[mounts-and-storage#out-of-band]]): which roots are watched, a root gone stale or out of reach, files changed on disk,
and how the browsers patch their rows in.

The notifiers themselves are replaced: what they would publish is published on the events' feed here.
"""

import logging
from collections.abc import Generator
from pathlib import Path
from typing import Any, Final
from unittest.mock import MagicMock, Mock
from uuid import UUID, uuid4

from PySide6.QtCore import QModelIndex, Qt
from pytest import LogCaptureFixture, fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco import TableBrowser
from rehuco_agent.rehuco.catalog_table_model import CatalogColumn
from rehuco_agent.rehuco.root_storage import ROOT_STORAGE_OFFLINE_TOOLTIPS
from rehuco_agent.resource_events import ResourceEvents
from rehuco_core import CatalogRecord, CatalogRow, RecordKind, TaskQueue
from rehuco_core.access import CatalogUnreadable, ResourceKey, RootReachable, RootStale
from rehuco_core.notify import RootNotifiers

from rehuco_agent_tests.delete_at_teardown import DeleteAtTeardown

from .test_catalog_docks import (  # noqa: F401  # pylint: disable=unused-import
    OTHER_PATH,
    PACKS,
    REHUCO_PATH,
    ROOT_IDS,
    TUTORIALS,
    WAIT_TIMEOUT_MS,
    CatalogDocks,
    GateJob,
    add_root,
    answer_add_root,
    build_docks,
    catalog_row,
    first_browser,
    fixture_cache,
    fixture_cached_rows,
    fixture_catalog,
    fixture_folders,
    fixture_followed,
    fixture_held,
    fixture_listening,
    fixture_no_open_scan,
    fixture_queue,
    fixture_saves,
    fixture_served,
    open_root_folder,
    publish_changed,
    scan_finding,
    tutorial_record,
    verified,
    wait_for_jobs,
    wait_for_rows,
)
from .test_catalog_verify import settle

FIRST_ROOT: Final = UUID(ROOT_IDS[0])
SECOND_ROOT: Final = UUID(ROOT_IDS[1])
RECORD: Final = ResourceKey(TUTORIALS / "python" / "info.rehu")
"""The record :func:`~.test_catalog_docks.tutorial_record` stands for."""


@fixture(name="watched")
def fixture_watched(
    qtbot: QtBot,
    queue: TaskQueue,
    catalog: Mock,
    mocker: MockerFixture,
    delete_at_teardown: DeleteAtTeardown,
) -> Generator[tuple[CatalogDocks, ResourceEvents, MagicMock]]:
    """Docks following the app's events, whose catalog keeps a stand-in for the roots' notifiers in step with its
    roots.

    :param qtbot: pytest-qt fixture.
    :param queue: the queue its jobs run on.
    :param catalog: the mock catalog.
    :param mocker: pytest-mock fixture.
    :param delete_at_teardown: deletes the `ResourceEvents` when the test ends.
    :yields: the docks, with nothing open, their events and the notifiers' stand-in.
    """
    notifiers = MagicMock(spec=RootNotifiers)
    events = delete_at_teardown(ResourceEvents())
    docks = build_docks(qtbot, queue, events, notifiers, catalog=catalog)
    mocker.patch.object(docks.roots, "confirm_remove_root", return_value=True)
    yield docks, events, notifiers
    docks.detach()


def followed_roots(notifiers: MagicMock) -> dict[UUID, Path]:
    """The roots the last :meth:`RootNotifiers.follow` was told to watch.

    :param notifiers: the notifiers' stand-in.
    :returns: each root's folder, by its id.
    """
    roots, cache_path = notifiers.follow.call_args.args
    assert isinstance(cache_path, Path)
    return dict(roots)


def offline_reason(docks: CatalogDocks) -> str:
    """What a row of the first root says while that root cannot be reached.

    :param docks: the catalog's docks, with a catalog open.
    :returns: the reason its storage gives.
    """
    file = docks.catalog.file
    assert file is not None
    first, *_ = file.roots
    return ROOT_STORAGE_OFFLINE_TOOLTIPS[first.storage]


def retitle(mocker: MockerFixture, catalog: Mock, cached_rows: list[CatalogRow], title: str) -> None:
    """Make a check of the tutorial's record find it moved on, with a new title (:func:`verified`).

    :param mocker: pytest-mock fixture.
    :param catalog: the mock catalog.
    :param cached_rows: what it holds: the tutorial's row.
    :param title: its new title.
    """
    verified(
        mocker, catalog, cached_rows, CatalogRecord("python/info.rehu", RecordKind.REHU, title=title, type="tutorial")
    )


def relisted_rows(relist: MagicMock) -> list[int]:
    """The rows a spy on :meth:`RootsFolderModel.relist` was asked to list again, in order.

    :param relist: the spy.
    :returns: each call's row.
    """
    indexes: list[QModelIndex] = [call.args[0] for call in relist.call_args_list]
    return [index.row() for index in indexes]


def shown_title(docks: CatalogDocks) -> str:
    """The title the first browser's first row shows."""
    return first_browser(docks).model.index(0, CatalogColumn.TITLE).data()


# region Which roots are watched, and when the docks read every row


@mark.usefixtures("served", "saves")
def test_the_notifiers_watch_exactly_the_open_files_roots(
    qtbot: QtBot, mocker: MockerFixture, watched: tuple[CatalogDocks, ResourceEvents, MagicMock]
) -> None:
    """The notifiers follow the roots as the file has them -- opened, a root added, a root removed -- and stop with the
    file (#511).

    **Test steps:**

    * open a two-root catalog: verify both are watched
    * add a root: verify all three are watched
    * remove the first root: verify the other two are watched
    * close the file: verify the notifiers were stopped
    """
    docks, _, notifiers = watched
    answer_add_root(mocker, docks, str(Path.cwd() / "fake" / "refs"))

    docks.catalog.open_rehuco(REHUCO_PATH)
    assert followed_roots(notifiers) == {FIRST_ROOT: TUTORIALS, SECOND_ROOT: PACKS}

    add_root(qtbot, docks)
    assert len(followed_roots(notifiers)) == 3

    assert docks.catalog.remove_root(0)
    assert FIRST_ROOT not in followed_roots(notifiers)
    assert len(followed_roots(notifiers)) == 2

    notifiers.stop.reset_mock()
    docks.catalog.close_rehuco()
    notifiers.stop.assert_called_once_with()


@mark.usefixtures("saves")
def test_a_new_file_is_watched_with_no_roots(watched: tuple[CatalogDocks, ResourceEvents, MagicMock]) -> None:
    """A new ``.rehuco`` has no roots, so the notifiers are told to watch none (#511).

    **Test steps:**

    * create a catalog
    * verify the notifiers follow no root
    """
    docks, _, notifiers = watched

    assert docks.catalog.new_rehuco(OTHER_PATH)

    assert not followed_roots(notifiers)


@mark.usefixtures("saves")
def test_the_roots_change_on_new_open_commit_remove_and_close_and_never_at_a_scans_end(
    mocker: MockerFixture,
    qtbot: QtBot,
    queue: TaskQueue,
    served: dict[str, Any],
    watched: tuple[CatalogDocks, ResourceEvents, MagicMock],
) -> None:
    """:attr:`~RootCatalog.roots_changed` says the set of rows changed as a whole, which only a change of which roots
    are shown does; a scan's end says which rows it touched instead (#511).

    **Test steps:**

    * create a file, open one, add a root, remove it and close, counting the roots changes
    * verify one per step
    * open again, scan a record in and wait for the scans to end
    * verify only the open said the roots changed
    """
    del served
    docks, _, _ = watched
    answer_add_root(mocker, docks, str(Path.cwd() / "fake" / "refs"))
    roots_changed = MagicMock()
    docks.catalog.roots_changed.connect(roots_changed)

    docks.catalog.new_rehuco(OTHER_PATH)
    docks.catalog.open_rehuco(REHUCO_PATH)
    add_root(qtbot, docks)
    docks.catalog.remove_root(2)
    docks.catalog.close_rehuco()
    assert roots_changed.call_count == 5

    roots_changed.reset_mock()
    scan_finding(mocker, {TUTORIALS: (tutorial_record(),)})
    docks.catalog.open_rehuco(REHUCO_PATH)
    docks.roots.scan_action.trigger()
    qtbot.waitUntil(lambda: first_browser(docks).model.rowCount() == 1, timeout=WAIT_TIMEOUT_MS)
    wait_for_jobs(qtbot, queue)
    qtbot.wait(50)

    roots_changed.assert_called_once_with()


@mark.usefixtures("served")
def test_a_scan_that_touched_nothing_says_nothing(
    mocker: MockerFixture, qtbot: QtBot, queue: TaskQueue, watched: tuple[CatalogDocks, ResourceEvents, MagicMock]
) -> None:
    """A scan that found every row as it was changed none, so its end has no row to name (#511).

    **Test steps:**

    * open a catalog and scan, finding nothing, and wait for both scans to end
    * verify no rows were said to have changed, and the scans are forgotten
    """
    docks, _, _ = watched
    scan_finding(mocker, {})
    docks.catalog.open_rehuco(REHUCO_PATH)
    touched = MagicMock()
    docks.catalog.rows_changed.connect(touched)

    docks.roots.scan_action.trigger()
    wait_for_jobs(qtbot, queue)
    scans = docks.catalog._RootCatalog__scans  # type: ignore[attr-defined]  # pylint: disable=protected-access
    qtbot.waitUntil(lambda: not scans, timeout=WAIT_TIMEOUT_MS)

    touched.assert_not_called()


# endregion


# region A root gone stale is scanned again


@mark.usefixtures("served")
def test_a_stale_root_is_scanned_again_and_an_unknown_one_is_not(
    queue: TaskQueue, held: GateJob, watched: tuple[CatalogDocks, ResourceEvents, MagicMock]
) -> None:
    """A root whose notifier lost events gets a scan of its own; a root reported with no file open, or one the file
    does not list, gets none (#511).

    **Test steps:**

    * with the queue held and nothing open, report a root stale: verify nothing was queued
    * open the catalog and report a root the file does not list stale: verify nothing was queued
    * report the second root stale, twice
    * verify one scan was queued, of that root
    """
    del held
    docks, events, _ = watched

    events.changes.publish(RootStale(SECOND_ROOT))
    assert len(queue.jobs()) == 1

    docks.catalog.open_rehuco(REHUCO_PATH)
    events.changes.publish(RootStale(uuid4()))
    assert len(queue.jobs()) == 1

    events.changes.publish(RootStale(SECOND_ROOT))
    events.changes.publish(RootStale(SECOND_ROOT))

    _, scan = queue.jobs()
    assert scan.label == "Scan - packs"


@mark.usefixtures("served")
def test_a_stale_or_returning_root_is_listed_again_and_no_other(
    mocker: MockerFixture,
    qtbot: QtBot,
    queue: TaskQueue,
    listening: tuple[CatalogDocks, ResourceEvents, Path],
) -> None:
    """The Roots view lists a root's loaded folders again, as F5 does, when its notifier says nothing held about it can
    be trusted, or that it went away or came back (#511).

    **Test steps:**

    * open the first root's folder, then spy on the model's relisting
    * report the second root stale: verify only its root row was listed again
    * report the first root reachable: verify only its root row was listed again
    """
    dock, events, _ = listening
    open_root_folder(qtbot, dock, "alpha")
    model = dock.roots.roots_model
    relist = mocker.patch.object(model, "relist")

    events.changes.publish(RootStale(SECOND_ROOT))
    assert relisted_rows(relist) == [1]

    relist.reset_mock()
    events.changes.publish(RootReachable(FIRST_ROOT, True))
    assert relisted_rows(relist) == [0]
    wait_for_jobs(qtbot, queue)


# endregion


# region A root out of reach


def test_a_root_out_of_reach_is_written_into_the_cache_and_greys_its_rows(
    qtbot: QtBot, followed: tuple[CatalogDocks, ResourceEvents]
) -> None:
    """What a notifier says of its root's folder is written into the cache, and the browsers grey its rows, which say
    why; once it is back they draw as usual again (#511).

    **Test steps:**

    * report the first root out of reach
    * verify the catalog says so, after the cache holds it, and the row is greyed and says why
    * report it back
    * verify the catalog lists no root out of reach and the row says nothing of it
    """
    dock, events = followed
    model = first_browser(dock).model

    with qtbot.waitSignal(dock.catalog.root_reachable, timeout=WAIT_TIMEOUT_MS) as said:
        events.changes.publish(RootReachable(FIRST_ROOT, False))

    assert said.args == [FIRST_ROOT, False]
    assert dock.catalog.unreachable_roots() == {FIRST_ROOT}
    assert model.offline_reason(FIRST_ROOT) == offline_reason(dock)
    assert model.index(0, CatalogColumn.TITLE).data(Qt.ItemDataRole.ToolTipRole) == offline_reason(dock)
    assert model.index(0, CatalogColumn.TITLE).data(Qt.ItemDataRole.ForegroundRole) is not None

    events.changes.publish(RootReachable(FIRST_ROOT, True))

    assert not dock.catalog.unreachable_roots()
    assert model.offline_reason(FIRST_ROOT) is None
    assert model.index(0, CatalogColumn.TITLE).data(Qt.ItemDataRole.ForegroundRole) is None


def test_a_double_click_on_a_row_of_a_root_out_of_reach_says_why_and_opens_nothing(
    qtbot: QtBot, followed: tuple[CatalogDocks, ResourceEvents]
) -> None:
    """Nothing under a root that cannot be reached can be opened: the double-click says why instead (#511).

    **Test steps:**

    * report the first root out of reach, then double-click its row
    * verify the refusal carried the reason, and no open was asked for
    * report it back and double-click again: verify the record is asked to be opened
    """
    dock, events = followed
    browser = first_browser(dock)
    events.changes.publish(RootReachable(FIRST_ROOT, False))

    with (
        qtbot.assertNotEmitted(dock.browsers.open_requested),
        qtbot.waitSignal(dock.browsers.open_refused) as refused,
    ):
        browser.view.doubleClicked.emit(browser.model.index(0, 0))

    assert refused.args == [offline_reason(dock)]

    events.changes.publish(RootReachable(FIRST_ROOT, True))
    with qtbot.waitSignal(dock.browsers.open_requested) as requested:
        browser.view.doubleClicked.emit(browser.model.index(0, 0))

    assert requested.args == [RECORD]


@mark.usefixtures("served")
def test_the_roots_out_of_reach_are_read_from_the_cache_when_the_roots_change(
    qtbot: QtBot, followed: tuple[CatalogDocks, ResourceEvents]
) -> None:
    """Which roots cannot be reached is kept in the cache -- by a notifier, or a scan, before the browsers were there to
    hear it -- so a file opened again greys them from the start (#511).

    **Test steps:**

    * write the first root out of reach into the cache alone: verify the browser does not know it yet
    * open the file again and wait for its rows
    * verify its browser greys the root
    """
    dock, _ = followed
    cache = dock.catalog._RootCatalog__catalog  # type: ignore[attr-defined]  # pylint: disable=protected-access
    cache.mark_reachable(FIRST_ROOT, False)
    assert first_browser(dock).model.offline_reason(FIRST_ROOT) is None

    dock.catalog.open_rehuco(REHUCO_PATH)
    wait_for_rows(qtbot, dock)

    assert first_browser(dock).model.offline_reason(FIRST_ROOT) == offline_reason(dock)


def test_a_browser_added_while_a_root_is_out_of_reach_greys_it_too(
    qtbot: QtBot, followed: tuple[CatalogDocks, ResourceEvents]
) -> None:
    """A browser added after a root went out of reach greys that root's rows from the start, not from the next read
    of the rows (#511).

    **Test steps:**

    * write the first root out of reach and open the file again, so the existing browser greys it
    * add a browser
    * verify the new browser greys the root as well
    """
    dock, _ = followed
    cache = dock.catalog._RootCatalog__catalog  # type: ignore[attr-defined]  # pylint: disable=protected-access
    cache.mark_reachable(FIRST_ROOT, False)
    dock.catalog.open_rehuco(REHUCO_PATH)
    wait_for_rows(qtbot, dock)

    dock.browsers.new_browser_action.trigger()

    _, added = dock.browsers.browsers
    assert added.model.offline_reason(FIRST_ROOT) == offline_reason(dock)


@mark.usefixtures("served")
def test_a_cache_that_cannot_be_read_lists_no_root_out_of_reach(
    watched: tuple[CatalogDocks, ResourceEvents, MagicMock], catalog: Mock, caplog: LogCaptureFixture
) -> None:
    """Greying is a courtesy: a cache that cannot say which roots are out of reach greys none, and the failure is
    logged (#511).

    **Test steps:**

    * open a catalog, then make reading the cache's roots fail
    * verify no root is listed out of reach, and the failure is logged
    """
    docks, _, _ = watched
    docks.catalog.open_rehuco(REHUCO_PATH)
    catalog.roots.side_effect = CatalogUnreadable("Could not read the roots: locked")

    with caplog.at_level(logging.ERROR, logger="rehuco_agent.rehuco.root_catalog"):
        assert docks.catalog.unreachable_roots() == frozenset()

    assert "Could not read the roots: locked" in caplog.text


# endregion


# region Files changed on disk


def test_a_reported_change_is_not_published_back_on_the_feed(
    mocker: MockerFixture,
    qtbot: QtBot,
    followed: tuple[CatalogDocks, ResourceEvents],
    catalog: Mock,
    cached_rows: list[CatalogRow],
) -> None:
    """A verify of files the feed said changed brings their rows in line, and says nothing more on the feed: it has
    said it (#511).

    **Test steps:**

    * make the record read retitled, listen to the feed, and publish the record changed
    * wait for the row's new title
    * verify the feed carried the one change published
    """
    dock, events = followed
    retitle(mocker, catalog, cached_rows, "Python 3")
    heard = MagicMock()
    events.changed.connect(heard)

    publish_changed(events, (RECORD,))
    qtbot.waitUntil(lambda: shown_title(dock) == "Python 3", timeout=WAIT_TIMEOUT_MS)
    settle(qtbot)

    heard.assert_called_once_with((RECORD,))


def test_a_change_an_access_found_is_published_on_the_feed(
    mocker: MockerFixture,
    qtbot: QtBot,
    followed: tuple[CatalogDocks, ResourceEvents],
    catalog: Mock,
    cached_rows: list[CatalogRow],
) -> None:
    """A record the app opens is verified, and a change no notifier reported -- the catch-all -- is published, so every
    other view hears of it the way it hears of any change (#487, #511).

    **Test steps:**

    * make the record read retitled, listen to the feed, and announce the record accessed
    * verify the row shows the new title, and the feed carried the record as changed
    """
    dock, events = followed
    retitle(mocker, catalog, cached_rows, "Python 3")

    with qtbot.waitSignal(events.changed, timeout=WAIT_TIMEOUT_MS) as heard:
        events.announce_accessed((RECORD,))

    assert heard.args == [(RECORD,)]
    qtbot.waitUntil(lambda: shown_title(dock) == "Python 3", timeout=WAIT_TIMEOUT_MS)


def test_a_folder_reported_changed_stands_for_every_record_beneath_it(
    mocker: MockerFixture,
    qtbot: QtBot,
    followed: tuple[CatalogDocks, ResourceEvents],
    catalog: Mock,
    cached_rows: list[CatalogRow],
) -> None:
    """A folder deleted or replaced outside the app is checked through every record the cache holds beneath it
    (#511).

    **Test steps:**

    * make the cache name the tutorial's record beneath its folder, and a check find it gone; publish the folder changed
    * verify the records beneath the folder were asked for, the record was planned, and its row removed in place
    """
    dock, events = followed
    model = first_browser(dock).model
    folder = ResourceKey(TUTORIALS / "python")
    catalog.record_paths.return_value = [RECORD.path]
    verified(mocker, catalog, cached_rows, None)

    with (
        qtbot.assertNotEmitted(model.modelReset),
        qtbot.waitSignal(model.rowsRemoved, timeout=WAIT_TIMEOUT_MS),
    ):
        publish_changed(events, (folder,))

    catalog.record_paths.assert_called_once_with((folder,))
    assert RECORD in catalog.plan_verify.call_args.args[0]
    assert model.rowCount() == 0


def test_a_converted_record_keeps_its_row_and_its_selection(
    mocker: MockerFixture,
    qtbot: QtBot,
    followed: tuple[CatalogDocks, ResourceEvents],
    catalog: Mock,
    cached_rows: list[CatalogRow],
) -> None:
    """A ``.tc`` converted outside the app is reported gone with its ``.rehu`` new; the cache gives the ``.rehu`` the
    ``.tc``'s row (its own contract, tested in core), so the row keeps its id and the browser its selection (#511).

    **Test steps:**

    * hold a ``.tc``'s row, show it and select it
    * make a check find the ``.rehu`` in its place under the same row, and publish both changed
    * verify the row now names the ``.rehu``, still selected and current, with no reset
    """
    dock, events = followed
    cached_rows[0] = catalog_row(1, 0, CatalogRecord("python/info.tc", RecordKind.TC, title="Python"))
    dock.catalog.rows_changed.emit({1})
    wait_for_rows(qtbot, dock)
    browser = first_browser(dock)
    browser.view.selectRow(0)
    verified(mocker, catalog, cached_rows, CatalogRecord("python/info.rehu", RecordKind.REHU, title="Python"))

    with qtbot.assertNotEmitted(browser.model.modelReset):
        publish_changed(events, (ResourceKey(TUTORIALS / "python" / "info.tc"), RECORD))
        qtbot.waitUntil(
            lambda: browser.model.index(0, CatalogColumn.PATH).data() == "tutorials/python/info.rehu",
            timeout=WAIT_TIMEOUT_MS,
        )

    assert browser.model.rowCount() == 1
    assert browser.view.selectionModel().isRowSelected(0)
    assert browser.current_resource == (FIRST_ROOT, "python/info.rehu")


# endregion


# region How the browsers patch their rows in


@mark.parametrize(("touched", "full_reads"), [(1, 0), (2, 1)])
def test_a_change_touching_more_rows_than_an_update_in_place_is_worth_reads_every_row(
    mocker: MockerFixture, qtbot: QtBot, followed: tuple[CatalogDocks, ResourceEvents], touched: int, full_reads: int
) -> None:
    """Up to :data:`~rehuco_agent.rehuco.browsers_dock.IN_PLACE_LIMIT` rows are read again in place; past it -- a first
    scan of a big root -- every row is read again (#511).

    **Test steps:**

    * lower the limit to one row, and say a change touched ``touched`` rows
    * verify every row was read again only past the limit, and in place otherwise
    """
    dock, _ = followed
    mocker.patch("rehuco_agent.rehuco.browsers_dock.IN_PLACE_LIMIT", 1)
    set_rows = mocker.spy(TableBrowser, "set_rows")
    update_rows = mocker.spy(TableBrowser, "update_rows")
    row_id = next(iter(dock.catalog.rows(first_browser(dock).query))).resource_id

    dock.catalog.rows_changed.emit({row_id, *range(row_id + 1, row_id + touched)})
    wait_for_rows(qtbot, dock)

    assert set_rows.call_count == full_reads
    assert update_rows.call_count == 1 - full_reads


# endregion


# region Detaching


@mark.usefixtures("served")
def test_a_detached_catalog_follows_no_root_any_more(
    mocker: MockerFixture, queue: TaskQueue, listening: tuple[CatalogDocks, ResourceEvents, Path]
) -> None:
    """After detach a late report of a root reaches neither the catalog nor the Roots view (#511).

    **Test steps:**

    * detach the docks, spying on the Roots view's relisting and the catalog's reachability
    * report a root stale and out of reach
    * verify no scan was queued, nothing listed again and nothing said of the root
    """
    dock, events, _ = listening
    relist = mocker.patch.object(dock.roots.roots_model, "relist")
    reachable = MagicMock()
    dock.catalog.root_reachable.connect(reachable)
    dock.detach()

    events.changes.publish(RootStale(FIRST_ROOT))
    events.changes.publish(RootReachable(FIRST_ROOT, False))

    assert not queue.jobs()
    relist.assert_not_called()
    reachable.assert_not_called()


# endregion
