"""Tests for adding several roots at once from the Roots view (#578): the first becomes current, each one this
machine reaches is scanned, and a refusal leaves the file as it is on disk -- or closed, when even that cannot be read.

The panel runs over the mock catalog of ``test_catalog_docks``, with the ``.rehuco`` served and its writes captured.
"""

from dataclasses import replace
from pathlib import Path
from typing import Any

from pytest import mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.settings.root_catalog_settings import shared_root_catalog_settings

from rehuco_agent_tests.mapped_roots import location_at

from .test_catalog_docks import (  # noqa: F401  # pylint: disable=unused-import
    REHUCO_PATH,
    TUTORIALS,
    CatalogDocks,
    add_root,
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
    folder_candidate,
)


@mark.usefixtures("served", "saves")
def test_several_roots_added_at_once_are_shown_the_first_current_and_each_scanned(
    qtbot: QtBot, mocker: MockerFixture, dock: CatalogDocks
) -> None:
    """Three folders picked at once join in order; the view moves to the first, and each is scanned.

    **Test steps:**

    * answer Add Roots with three folders, spy on the scans, and add
    * verify the labels shown, the current row, and one scan per new root, in order
    """
    shared_root_catalog_settings().scan_after_adding = True
    scan = mocker.patch.object(dock.catalog, "scan_root")
    dock.catalog.open_rehuco(REHUCO_PATH)
    scan.reset_mock()
    mocker.patch.object(
        dock.roots,
        "ask_roots_to_add",
        side_effect=lambda: tuple(folder_candidate(dock, TUTORIALS.parent / name) for name in ("a", "b", "c")),
    )

    add_root(qtbot, dock)

    file = dock.catalog.file
    assert file is not None
    assert [root.label for root in file.roots] == ["tutorials", "packs", "a", "b", "c"]
    assert dock.roots.roots_view.currentIndex().row() == 2
    assert [call.args[0] for call in scan.call_args_list] == [root.root_id for root in file.roots[2:]]


@mark.usefixtures("served", "saves")
def test_an_empty_answer_adds_nothing(mocker: MockerFixture, dock: CatalogDocks) -> None:
    """A dialog accepted with nothing addable is no add.

    **Test steps:**

    * answer Add Roots with no lines, spying on the catalog's add
    * verify it was never asked
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    mocker.patch.object(dock.roots, "ask_roots_to_add", return_value=())
    adding = mocker.spy(dock.catalog, "add_roots")

    dock.roots.add_roots_action.trigger()

    adding.assert_not_called()


def test_a_refusal_whose_file_cannot_be_read_back_closes_it(
    mocker: MockerFixture, dock: CatalogDocks, served: Any
) -> None:
    """A line the file refuses puts the file back from disk; with the disk unreadable too, nothing stays open.

    **Test steps:**

    * open a catalog, make its file unreadable, and add a line whose location a root already has
    * verify nothing was added and nothing is open
    """
    del served
    dock.catalog.open_rehuco(REHUCO_PATH)
    clash = replace(folder_candidate(dock, TUTORIALS.parent / "x"), location=location_at(TUTORIALS))
    mocker.patch.object(Path, "read_text", side_effect=FileNotFoundError("gone"))

    assert dock.catalog.add_roots((clash,)) is None

    assert dock.catalog.rehuco_path is None
