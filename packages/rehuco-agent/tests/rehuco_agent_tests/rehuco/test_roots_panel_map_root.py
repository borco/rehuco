"""Tests for the Roots view's handling of a root this machine does not map (#514): it is listed greyed with *Map...* in
its menu, which asks for a folder and maps it; removing it and adding a root report in terms of the location.

The panel runs over the mock catalog of ``test_catalog_docks``, with the ``.rehuco`` served and its writes captured.
"""

from pathlib import Path
from typing import Any, Final
from unittest.mock import MagicMock
from uuid import UUID

from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco.root_catalog import RootCatalog
from rehuco_agent.rehuco.root_storage import NOT_MAPPED_ROW
from rehuco_agent.rehuco.roots_folder_model import RootsFolderModel
from rehuco_agent.rehuco.roots_panel import RootsPanel
from rehuco_core import MappedRoot, RehucoRoot

from rehuco_agent_tests.mapped_roots import location_at, mapped_root

from .test_catalog_docks import (  # noqa: F401  # pylint: disable=unused-import
    PACKS,
    REHUCO_PATH,
    TUTORIALS,
    CatalogDocks,
    add_root,
    answer_add_root,
    fixture_cache,
    fixture_cached_rows,
    fixture_catalog,
    fixture_dock,
    fixture_machine,
    fixture_no_open_scan,
    fixture_on_disk,
    fixture_queue,
    fixture_saves,
    fixture_served,
    select_root,
)

AWAY: Final = "//nas/data/Tutorials"
"""A location this machine has no mount for."""

AWAY_ID: Final = UUID("a41b9c3d-0000-4000-8000-000000000003")
"""The root served at :data:`AWAY`."""

WARNING: Final = "rehuco_agent.rehuco.roots_panel.QMessageBox.warning"


@fixture(name="away_dock")
def fixture_away_dock(dock: CatalogDocks, served: dict[str, Any], saves: MagicMock) -> CatalogDocks:
    """The docks over a catalog of two mapped roots and a third this machine has no mount for, open, with its writes
    captured.

    :param dock: the docks.
    :param served: the served document.
    :param saves: captures the ``.rehuco`` writes.
    :returns: the docks, the unmapped root on row 2.
    """
    del saves
    served["roots"].append({"id": str(AWAY_ID), "location": AWAY, "label": "away"})
    assert dock.catalog.open_rehuco(REHUCO_PATH)
    return dock


def test_an_unmapped_root_is_listed_greyed_and_offers_map_where_a_mapped_one_does_not(away_dock: CatalogDocks) -> None:
    """The view lists every root of the file; the one this machine cannot find says so, and only its menu and the
    Map action are for it.

    **Test steps:**

    * open a file with a third, unmapped root, and read the view
    * verify the rows in the file's order, the third greyed with its one row, and its menu offering Map where the
      others' do not
    * select each kind of root and verify the Map action is enabled only for the unmapped one
    """
    roots = away_dock.roots
    model = roots.roots_model
    assert [model.index(row, 0).data() for row in range(model.rowCount())] == ["tutorials", "packs", "away"]
    away = model.index(2, 0)
    assert away.data(RootsFolderModel.GREYED_ROLE) is True
    assert model.index(0, 0, away).data() == NOT_MAPPED_ROW
    assert roots.map_root_action in roots.roots_context_actions(away)
    assert roots.map_root_action not in roots.roots_context_actions(model.index(0, 0))

    select_root(away_dock, 2)
    assert roots.map_root_action.isEnabled()
    select_root(away_dock, 0)
    assert not roots.map_root_action.isEnabled()


def test_map_asks_for_the_folder_and_maps_the_root(mocker: MockerFixture, away_dock: CatalogDocks) -> None:
    """The folder asked for becomes the root's folder here: the row is no longer greyed, and the file is not written.

    **Test steps:**

    * select the unmapped root and trigger Map, answering a folder
    * verify the question was about that root, the root is mapped to the folder, and the row is a plain root again
    """
    roots = away_dock.roots
    folder = TUTORIALS.parent / "away"
    ask = mocker.patch.object(roots, "ask_root_folder", return_value=folder)
    select_root(away_dock, 2)

    roots.map_root_action.trigger()

    (asked,) = ask.call_args.args
    assert isinstance(asked, RehucoRoot)
    assert asked.root_id == AWAY_ID
    assert away_dock.catalog.root_paths()[AWAY_ID] == folder
    assert roots.roots_model.index(2, 0).data(RootsFolderModel.GREYED_ROLE) is False
    assert not roots.map_root_action.isEnabled()


def test_cancelling_the_folder_question_maps_nothing(mocker: MockerFixture, away_dock: CatalogDocks) -> None:
    """A cancelled question leaves the root as it was, without a word.

    **Test steps:**

    * select the unmapped root and trigger Map, cancelling
    * verify nothing was mapped and no warning shown
    """
    warning = mocker.patch(WARNING)
    mocker.patch.object(away_dock.roots, "ask_root_folder", return_value=None)
    map_root = mocker.spy(RootCatalog, "map_root")
    select_root(away_dock, 2)

    away_dock.roots.map_root_action.trigger()

    map_root.assert_not_called()
    warning.assert_not_called()
    assert AWAY_ID not in away_dock.catalog.root_paths()


def test_a_folder_the_catalog_refuses_is_reported_with_its_reason(
    mocker: MockerFixture, away_dock: CatalogDocks
) -> None:
    """Mapping the root to a folder inside another root is refused, and the warning says why.

    **Test steps:**

    * select the unmapped root and trigger Map, answering a folder inside the first root
    * verify a warning titled Map Root with the catalog's reason, and the root is still unmapped
    """
    warning = mocker.patch(WARNING)
    mocker.patch.object(away_dock.roots, "ask_root_folder", return_value=TUTORIALS / "python")
    select_root(away_dock, 2)

    away_dock.roots.map_root_action.trigger()

    warning.assert_called_once_with(away_dock.roots, "Map Root", away_dock.catalog.save_error)
    assert "is inside the root tutorials" in away_dock.catalog.save_error
    assert AWAY_ID not in away_dock.catalog.root_paths()


def test_the_map_slot_refuses_a_row_that_is_not_an_unmapped_root(
    mocker: MockerFixture, away_dock: CatalogDocks
) -> None:
    """Called directly, as a stray trigger might, the slot asks nothing for a mapped root.

    **Test steps:**

    * select a mapped root and call the Map slot
    * verify the question was not asked
    """
    ask = mocker.patch.object(away_dock.roots, "ask_root_folder")
    select_root(away_dock, 0)

    away_dock.roots._RootsPanel__on_map_root()  # type: ignore[attr-defined]  # pylint: disable=protected-access

    ask.assert_not_called()


@mark.parametrize(("picked", "expected"), [("/picked/folder", Path("/picked/folder")), ("", None)])
def test_the_real_folder_question_returns_the_folder_picked(
    mocker: MockerFixture, away_dock: CatalogDocks, picked: str, expected: Path | None
) -> None:
    """The system's folder dialog is the question, titled with the root's name; cancelling answers nothing.

    **Test steps:**

    * ask the real question with the system dialog answering a folder, then nothing
    * verify the folder or none, and the dialog's title named the root
    """
    chooser = mocker.patch("rehuco_agent.rehuco.roots_panel.QFileDialog.getExistingDirectory", return_value=picked)
    root = RehucoRoot(AWAY_ID, "away", AWAY)

    assert away_dock.roots.ask_root_folder(root) == expected

    assert chooser.call_args.args[1] == 'Map "away"'


def test_the_folder_question_names_a_root_with_an_empty_name_by_its_location(
    mocker: MockerFixture, away_dock: CatalogDocks
) -> None:
    """With no name to show, the folder question is titled with the root's location.

    **Test steps:**

    * ask the real question for a root whose name is empty
    * verify the dialog's title named its location
    """
    chooser = mocker.patch("rehuco_agent.rehuco.roots_panel.QFileDialog.getExistingDirectory", return_value="")

    away_dock.roots.ask_root_folder(RehucoRoot(AWAY_ID, "", AWAY))

    assert chooser.call_args.args[1] == f'Map "{AWAY}"'


def test_removing_an_unmapped_root_asks_with_no_cached_entries_and_removes_it(
    mocker: MockerFixture, away_dock: CatalogDocks
) -> None:
    """Nothing of an unmapped root is in the cache, so the question counts none, and it names the root as the file does.

    **Test steps:**

    * select the unmapped root and remove it
    * verify the question was about the location, with no cached entries, and the root is gone from the view
    """
    confirm = mocker.patch.object(away_dock.roots, "confirm_remove_root", return_value=True)
    select_root(away_dock, 2)

    away_dock.roots.remove_root_action.trigger()

    (asked, cached) = confirm.call_args.args
    assert isinstance(asked, RehucoRoot)
    assert asked.location == AWAY
    assert cached == 0
    assert away_dock.roots.roots_model.rowCount() == 2


@mark.parametrize(
    ("root", "name", "where"),
    [
        (mapped_root(TUTORIALS, "tutorials"), "tutorials", str(TUTORIALS)),
        (mapped_root(TUTORIALS, ""), str(TUTORIALS), str(TUTORIALS)),
        (RehucoRoot(AWAY_ID, "away", AWAY), "away", AWAY),
        (RehucoRoot(AWAY_ID, "", AWAY), AWAY, AWAY),
    ],
)
def test_the_removal_question_names_where_the_files_are(
    mocker: MockerFixture, away_dock: CatalogDocks, root: MappedRoot | RehucoRoot, name: str, where: str
) -> None:
    """The files stay where they are: this machine's folder for a mapped root, the location for one it cannot find.
    The root is named by its name, or by that same place while the name is empty.

    **Test steps:**

    * ask the real question for a mapped and an unmapped root, each with a name and without, the box patched to answer
    * verify the text names the root and the folder or the location
    """
    box = mocker.patch("rehuco_agent.rehuco.roots_panel.QMessageBox.question")

    RootsPanel.confirm_remove_root(away_dock.roots, root, 0)

    assert f'Remove the root "{name}" from this catalog?' in box.call_args.args[2]
    assert f"stay where they are, in {where}." in box.call_args.args[2]


def test_a_root_the_catalog_refuses_to_add_is_reported_with_its_reason(
    mocker: MockerFixture, qtbot: QtBot, dock: CatalogDocks, served: dict[str, Any], saves: MagicMock
) -> None:
    """Add Root asks the catalog, and what it refuses -- here a location the file already lists -- is shown as the
    warning, with nothing written.

    **Test steps:**

    * open a catalog and add a folder whose location is the first root's
    * verify a warning titled Add Root with the file's reason, nothing written, and no new row
    """
    del served
    warning = mocker.patch(WARNING)
    mocker.patch("rehuco_agent.rehuco.root_catalog.location_of", return_value=location_at(TUTORIALS))
    answer_add_root(mocker, dock, str(PACKS.parent / "elsewhere"))
    dock.catalog.open_rehuco(REHUCO_PATH)

    add_root(qtbot, dock)

    warning.assert_called_once_with(dock.roots, "Add Root", f"Already a root: {location_at(TUTORIALS)}")
    saves.assert_not_called()
    assert dock.roots.roots_model.rowCount() == 2
