"""Tests for roots that overlap in the Root Catalog and its Roots dock (#498): the catalog keeps its
:class:`~rehuco_agent.rehuco.root_overlaps.RootOverlaps` on the open file and on what its scans met, and Add Root
compares the folder with the roots through their links before adding it.

The comparisons through links are ``RootOverlap``'s, tested in core: the suite's ``conftest`` makes them find
nothing, and a test here patches them again to answer otherwise. What
``RootOverlaps`` makes of what it is told is ``test_root_overlaps``' subject.
"""

import threading
from collections.abc import Generator
from pathlib import Path
from typing import Any, Final
from unittest.mock import MagicMock, Mock
from uuid import UUID

from PySide6.QtCore import Qt
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco.root_overlap_check import RootOverlapCheck
from rehuco_core import HardlinkedRecord, RootOverlap, RootScanOutcome, RootScanResult, TaskQueue

from rehuco_agent_tests.mapped_roots import location_at

from .test_catalog_docks import (  # noqa: F401  # pylint: disable=unused-import
    OTHER_PATH,
    REHUCO_ID,
    REHUCO_PATH,
    ROOT_IDS,
    TUTORIALS,
    WAIT_TIMEOUT_MS,
    CatalogDocks,
    GateJob,
    add_root,
    answer_add_root,
    fixture_cache,
    fixture_cached_rows,
    fixture_catalog,
    fixture_dock,
    fixture_held,
    fixture_machine,
    fixture_no_open_scan,
    fixture_on_disk,
    fixture_queue,
    fixture_saves,
    fixture_served,
    tutorial_record,
    wait_for_jobs,
)

GATE_TIMEOUT: Final = 120.0
"""How long a gated comparison blocks before giving up on being released, in seconds -- a deadlock guard only."""

TUTORIALS_ID: Final = UUID(ROOT_IDS[0])
PACKS_ID: Final = UUID(ROOT_IDS[1])
REFS: Final = str(Path.cwd() / "fake" / "refs")
"""The folder Add Root is answered with."""
OTHER_ID: Final = "0b9f2a6e-0000-4000-8000-0000000000aa"
"""Another catalog's rehuco id."""
THIRD_ID: Final = "a41b9c3d-0000-4000-8000-000000000003"
"""A third root's id, served at :data:`REFS`."""


@fixture(name="gate")
def fixture_gate(mocker: MockerFixture) -> Generator[threading.Event]:
    """Make Add Root's comparison through links wait until the test lets it answer that nothing overlaps.

    :param mocker: pytest-mock fixture.
    :yields: the event that releases it, also set at teardown.
    """
    release = threading.Event()

    def find_resolved(*_args: object) -> None:
        release.wait(GATE_TIMEOUT)

    mocker.patch.object(RootOverlap, "find_resolved", side_effect=find_resolved)
    yield release
    release.set()


def nest(served: dict[str, Any]) -> None:
    """Make the served file's second root a folder inside its first.

    :param served: the served document.
    """
    served["roots"][1]["location"] = location_at(TUTORIALS / "python")


def overlap_check(dock: CatalogDocks) -> RootOverlapCheck:
    """The check Add Root runs through links.

    :param dock: the catalog's docks.
    :returns: the Roots panel's own check.
    """
    check = dock.roots.findChild(RootOverlapCheck, options=Qt.FindChildOption.FindDirectChildrenOnly)
    assert check is not None
    return check


# region The catalog's overlaps


@mark.usefixtures("saves")
def test_the_overlaps_follow_the_file_opened_and_closed(dock: CatalogDocks, served: dict[str, Any]) -> None:
    """The banner describes the open file: a nesting one is flagged, a clean one opened after it takes the flag down,
    and so does closing.

    **Test steps:**

    * open a nesting file: verify one overlap said
    * open a clean catalog: verify none
    * open the nesting file again: verify one; close it: verify none
    """
    nest(served)
    nesting = served["roots"]
    dock.catalog.open_rehuco(REHUCO_PATH)
    assert len(dock.catalog.overlaps.messages) == 1

    served.update(id=OTHER_ID, roots=[])
    dock.catalog.open_rehuco(OTHER_PATH)
    assert dock.catalog.overlaps.messages == []

    served.update(id=REHUCO_ID, roots=nesting)
    dock.catalog.open_rehuco(REHUCO_PATH)
    assert len(dock.catalog.overlaps.messages) == 1
    dock.catalog.close_rehuco()
    assert dock.catalog.overlaps.messages == []


@mark.usefixtures("served", "saves")
def test_editing_or_reopening_the_catalog_follows_it_again_keeping_what_its_scans_said(
    mocker: MockerFixture, dock: CatalogDocks
) -> None:
    """A root removed or added, and the same catalog opened again, keep what the scans said of the roots still there;
    closing forgets it.

    **Test steps:**

    * open the file, and spy on what the overlaps follow
    * remove a root, add one and commit, open the same file again, and close it
    * verify each followed the open file keeping the scans, and closing followed nothing
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    follow = mocker.spy(dock.catalog.overlaps, "follow")

    assert dock.catalog.remove_root(1)
    assert dock.catalog.add_root(Path(REFS)) is not None
    dock.catalog.open_rehuco(REHUCO_PATH)
    dock.catalog.close_rehuco()

    assert [call.kwargs.get("keep_scans") for call in follow.call_args_list] == [True, True, True, None]
    assert [
        None if call.args[0] is None else [root.label for root in call.args[0]] for call in follow.call_args_list
    ] == [
        ["tutorials"],
        ["tutorials", "refs"],
        ["tutorials", "refs"],
        None,
    ]


@mark.usefixtures("served")
def test_a_scans_end_tells_the_overlaps_what_it_met(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, queue: TaskQueue
) -> None:
    """A scan that met another root inside its own, and a record under a second name, says so when it ends.

    **Test steps:**

    * make the tutorials scan meet the packs root and a hardlinked record, and spy on the overlaps
    * scan the tutorials root and wait for its end to be heard
    * verify the overlaps were told the root, the root met and the record, and say both
    """
    scan_class = mocker.patch("rehuco_core.rehudb_jobs.CatalogRootScan")
    scan_class.return_value.scan.return_value = RootScanResult(
        TUTORIALS,
        RootScanOutcome.SCANNED,
        (tutorial_record(),),
        hardlinked=(("python/info.rehu", "copy/info.rehu"),),
        met_roots=frozenset({PACKS_ID}),
    )
    dock.catalog.open_rehuco(REHUCO_PATH)
    scan_finished = mocker.spy(dock.catalog.overlaps, "scan_finished")

    dock.catalog.scan_root(TUTORIALS_ID)
    wait_for_jobs(qtbot, queue)
    qtbot.waitUntil(lambda: scan_finished.called, timeout=WAIT_TIMEOUT_MS)

    assert scan_finished.call_args.args == (
        TUTORIALS_ID,
        frozenset({PACKS_ID}),
        (HardlinkedRecord(TUTORIALS_ID, "python/info.rehu", TUTORIALS_ID, "copy/info.rehu"),),
    )
    assert len(dock.catalog.overlaps.messages) == 2


@mark.usefixtures("saves")
@mark.parametrize("change", ["opened", "committed", "removed"])
# pylint: disable-next=too-many-arguments,too-many-positional-arguments
def test_the_comparison_among_the_roots_skips_the_unreachable_ones(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, catalog: Mock, served: dict[str, Any], change: str
) -> None:
    """The roots the cache holds unreachable are not followed through links: the file opened, its roots committed or
    one removed, each comparison is told the ones unreachable then.

    **Test steps:**

    * serve a third root, and spy on the comparison among the roots
    * mark the first root unreachable and open the file; or open it, mark the root, and commit the roots or remove the
      third one
    * verify each comparison was asked over the file's roots, skipping the first root once it was unreachable
    """
    served["roots"].append({"id": THIRD_ID, "location": location_at(REFS), "label": "refs"})
    among = mocker.patch.object(RootOverlap, "among_resolved", return_value=())
    if change == "opened":
        catalog.mark_reachable(TUTORIALS_ID, False)
    dock.catalog.open_rehuco(REHUCO_PATH)
    if change == "committed":
        catalog.mark_reachable(TUTORIALS_ID, False)
        assert dock.catalog.commit_roots()
    elif change == "removed":
        catalog.mark_reachable(TUTORIALS_ID, False)
        assert dock.catalog.remove_root(2)
    skips = [frozenset({TUTORIALS_ID})] if change == "opened" else [frozenset(), frozenset({TUTORIALS_ID})]

    qtbot.waitUntil(lambda: among.call_count == len(skips), timeout=WAIT_TIMEOUT_MS)
    assert [call.args[1] for call in among.call_args_list] == skips
    assert among.call_args.args[0] == dock.catalog.mapped_roots()


@mark.usefixtures("served")
def test_detaching_the_catalog_stops_its_overlaps(mocker: MockerFixture, dock: CatalogDocks) -> None:
    """The window going stops the overlaps' check through links.

    **Test steps:**

    * open the file, spy on the overlaps' stop, and detach the catalog
    * verify they were stopped
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    stop = mocker.spy(dock.catalog.overlaps, "stop")

    dock.catalog.detach()

    stop.assert_called_once_with()


# endregion

# region Add Root through links


@mark.usefixtures("served")
def test_add_root_refuses_a_folder_inside_a_root_through_a_link(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, saves: MagicMock
) -> None:
    """A folder that a link puts inside a root is refused once the check answers, with the overlap's own words, and
    Add Root is offered again.

    **Test steps:**

    * open the file; make the comparison through links find the folder inside the first root
    * add the folder and wait for the check
    * verify the warning, nothing written, two roots, and Add Root enabled
    """
    answer_add_root(mocker, dock, REFS)
    warning = mocker.patch("rehuco_agent.rehuco.roots_panel.QMessageBox.warning")
    dock.catalog.open_rehuco(REHUCO_PATH)
    roots = dock.catalog.mapped_roots()
    overlap = RootOverlap(roots[0], Path(REFS), encloses=True)
    find = mocker.patch.object(RootOverlap, "find_resolved", return_value=overlap)

    add_root(qtbot, dock)

    warning.assert_called_once_with(dock.roots, "Add Root", overlap.message)
    saves.assert_not_called()
    assert dock.roots.roots_model.rowCount() == 2
    assert dock.roots.add_root_action.isEnabled()
    assert find.call_args.args == (REFS, roots, frozenset())


@mark.usefixtures("served", "saves")
def test_add_root_skips_the_unreachable_roots(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, catalog: Mock
) -> None:
    """The folder is compared through links with the reachable roots only: a root the cache holds unreachable is not
    followed.

    **Test steps:**

    * open the file, mark its first root unreachable, and spy on the comparison of a candidate
    * add a folder and wait for the check
    * verify the comparison was asked over the folder and the roots, skipping the first root, and the root added
    """
    answer_add_root(mocker, dock, REFS)
    dock.catalog.open_rehuco(REHUCO_PATH)
    roots = dock.catalog.mapped_roots()
    catalog.mark_reachable(TUTORIALS_ID, False)
    find = mocker.patch.object(RootOverlap, "find_resolved", return_value=None)

    add_root(qtbot, dock)

    assert find.call_args.args == (REFS, roots, frozenset({TUTORIALS_ID}))
    assert dock.roots.roots_model.rowCount() == 3


@mark.usefixtures("served", "saves")
def test_add_root_is_disabled_while_its_check_is_out(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, gate: threading.Event
) -> None:
    """One add at a time: while the check through links has not answered, Add Root cannot be asked again.

    **Test steps:**

    * open the file, hold the check, and add a folder
    * verify Add Root is disabled and the root not added yet
    * let the check answer
    * verify the root added and Add Root enabled again
    """
    answer_add_root(mocker, dock, REFS)
    dock.catalog.open_rehuco(REHUCO_PATH)

    with qtbot.waitSignal(overlap_check(dock).answered, timeout=WAIT_TIMEOUT_MS):
        dock.roots.add_root_action.trigger()
        assert not dock.roots.add_root_action.isEnabled()
        assert dock.roots.roots_model.rowCount() == 2
        gate.set()

    assert dock.roots.roots_model.rowCount() == 3
    assert dock.roots.add_root_action.isEnabled()


@mark.usefixtures("served")
@mark.parametrize("change", ["closed", "reopened"])
# pylint: disable-next=too-many-arguments,too-many-positional-arguments
def test_an_answer_for_a_file_no_longer_open_adds_nothing(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, saves: MagicMock, gate: threading.Event, change: str
) -> None:
    """The file the add was asked of was closed, or replaced by a fresh read of itself, while the check was out: the
    answer is for a file no longer shown, so nothing is added to any.

    **Test steps:**

    * open the file, hold the check, and add a folder
    * close the file, or open it again
    * let the check answer
    * verify nothing was written
    """
    answer_add_root(mocker, dock, REFS)
    dock.catalog.open_rehuco(REHUCO_PATH)

    with qtbot.waitSignal(overlap_check(dock).answered, timeout=WAIT_TIMEOUT_MS):
        dock.roots.add_root_action.trigger()
        if change == "closed":
            dock.catalog.close_rehuco()
        else:
            dock.catalog.open_rehuco(REHUCO_PATH)
        gate.set()

    saves.assert_not_called()


@mark.usefixtures("served", "saves")
def test_an_answer_for_another_add_is_dropped(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, gate: threading.Event
) -> None:
    """Only the pending add's own answer adds: one with another serial, or with no add pending, does nothing.

    **Test steps:**

    * open the file, and answer for an add never asked
    * hold the check, add a folder, and answer with another serial
    * verify the root not added and Add Root still disabled
    * let the check answer
    * verify the root added
    """
    answer_add_root(mocker, dock, REFS)
    dock.catalog.open_rehuco(REHUCO_PATH)
    check = overlap_check(dock)
    check.answered.emit(1_000, ())
    assert dock.roots.roots_model.rowCount() == 2

    dock.roots.add_root_action.trigger()
    check.answered.emit(1_000, ())
    assert dock.roots.roots_model.rowCount() == 2
    assert not dock.roots.add_root_action.isEnabled()
    gate.set()

    qtbot.waitUntil(lambda: dock.roots.roots_model.rowCount() == 3, timeout=WAIT_TIMEOUT_MS)


@mark.usefixtures("saves")
def test_the_roots_view_draws_the_duplicate_roots(
    mocker: MockerFixture, dock: CatalogDocks, served: dict[str, Any]
) -> None:
    """The later root of a nesting pair is handed to the view to be drawn in red, and nothing once the file is closed.

    **Test steps:**

    * spy on the view, and open a file whose second root is inside its first
    * verify the second root handed to the view
    * close the file
    * verify none handed
    """
    nest(served)
    set_duplicates = mocker.spy(dock.roots.roots_view, "set_duplicate_roots")

    dock.catalog.open_rehuco(REHUCO_PATH)
    assert set_duplicates.call_args.args == (frozenset({PACKS_ID}),)

    dock.catalog.close_rehuco()
    assert set_duplicates.call_args.args == (frozenset(),)


# endregion
