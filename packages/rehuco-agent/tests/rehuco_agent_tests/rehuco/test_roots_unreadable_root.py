"""Tests for the Roots view's handling of a root whose ``.rehuroot`` cannot be read (#577): it is listed greyed with one
row saying so and the reason as its tooltip, offers neither Map nor a name to edit, and can still be removed.

The panel runs over the mock catalog of ``test_catalog_docks``, with the ``.rehuco`` served and its writes captured; the
served file names one more root file than there are roots, which is the missing one.
"""

import json
from pathlib import Path
from typing import Any, Final
from unittest.mock import MagicMock, Mock

from PySide6.QtCore import Qt
from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_agent.rehuco.root_storage import NOT_MAPPED_ROW, UNREADABLE_ROW
from rehuco_agent.rehuco.roots_folder_model import RootsFolderModel

from .test_catalog_docks import (  # noqa: F401  # pylint: disable=unused-import
    REHUCO_PATH,
    CatalogDocks,
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
    served_rehuco,
)

GONE: Final = REHUCO_PATH.parent / "gone.rehuroot"
"""The root file the served catalog names and nothing serves."""


@fixture(name="gone_dock")
def fixture_gone_dock(
    dock: CatalogDocks, served: dict[str, Any], on_disk: dict[Path, str], saves: MagicMock
) -> CatalogDocks:
    """The docks over a catalog of two mapped roots and a third whose root file is missing, open, with its writes
    captured.

    :param dock: the docks.
    :param served: the served document.
    :param on_disk: what a read of a written file answers; the ``.rehuco`` is put there, naming the missing file.
    :param saves: captures the ``.rehuco`` writes.
    :returns: the docks, the unreadable root on row 2.
    """
    del saves
    rehuco = served_rehuco(served)
    rehuco["roots"].append({"file": GONE.name})
    on_disk[REHUCO_PATH] = json.dumps(rehuco)
    assert dock.catalog.open_rehuco(REHUCO_PATH)
    return dock


def test_an_unreadable_root_is_listed_greyed_with_why_and_offers_no_map(gone_dock: CatalogDocks) -> None:
    """The view lists the root by its file's name, greyed, with one row saying its file cannot be read and the reason
    as the tooltip; nothing offers to map it, and it is not among the roots to ask about.

    **Test steps:**

    * open a file naming a missing root file, and read the view
    * verify the rows, the third greyed with its one row, its tooltip the reason and its path the file
    * verify its menu offers no Map, the Map action stays disabled with it selected, and nothing asks to map it
    """
    roots = gone_dock.roots
    model = roots.roots_model
    assert [model.index(row, 0).data() for row in range(model.rowCount())] == ["tutorials", "packs", "gone"]
    gone = model.index(2, 0)
    assert gone.data(RootsFolderModel.GREYED_ROLE) is True
    assert model.index(0, 0, gone).data() == UNREADABLE_ROW
    assert gone.data(Qt.ItemDataRole.ToolTipRole) == f"The root file is missing: {GONE}"
    assert gone.data(RootsFolderModel.PATH_ROLE) == str(GONE)
    assert roots.map_root_action not in roots.roots_context_actions(gone)

    select_root(gone_dock, 2)

    assert not roots.map_root_action.isEnabled()
    assert gone_dock.catalog.unmapped_roots() == ()


def test_an_unreadable_roots_card_has_no_name_to_edit(gone_dock: CatalogDocks) -> None:
    """There is no file to write a name into, so the card's name field is off for that root, and back on for the
    next.

    **Test steps:**

    * select the unreadable root and read the card
    * verify the name field and its default button are disabled and the storage line says the file cannot be read
    * select a readable root and verify the name field is enabled again
    """
    roots = gone_dock.roots

    select_root(gone_dock, 2)

    assert not roots.root_name_edit.isEnabled()
    assert not roots.default_root_name_action.isEnabled()
    assert roots.root_storage_value.text() == UNREADABLE_ROW

    select_root(gone_dock, 0)

    assert roots.root_name_edit.isEnabled()
    assert roots.root_storage_value.text() != NOT_MAPPED_ROW


def test_the_map_slot_refuses_an_unreadable_root(mocker: MockerFixture, gone_dock: CatalogDocks) -> None:
    """Called directly, as a stray trigger might, the slot asks nothing for a root with no file to map.

    **Test steps:**

    * select the unreadable root and call the Map slot
    * verify the question was not asked
    """
    ask = mocker.patch.object(gone_dock.roots, "ask_root_folder")
    select_root(gone_dock, 2)

    gone_dock.roots._RootsPanel__on_map_root()  # type: ignore[attr-defined]  # pylint: disable=protected-access

    ask.assert_not_called()


def test_an_unreadable_root_can_be_removed(gone_dock: CatalogDocks, saves: MagicMock) -> None:
    """A reference to a file that is gone for good is dropped like any root.

    **Test steps:**

    * remove the unreadable root
    * verify the removal saved, and the written file names only the two other roots' files
    """
    assert gone_dock.catalog.remove_root(2)

    written = [entry["file"] for entry in json.loads(saves.call_args[0][1])["roots"]]
    assert len(written) == 2
    assert GONE.name not in written


def test_removing_an_unreadable_root_queues_no_cache_removal(
    mocker: MockerFixture, gone_dock: CatalogDocks, catalog: Mock
) -> None:
    """The cache never held a root it could not read, so dropping its reference touches the cache not at all.

    **Test steps:**

    * remove the unreadable root
    * verify the removal saved and nothing was hidden from the catalog or queued for it
    """
    job = mocker.patch("rehuco_agent.rehuco.root_catalog.RemoveCatalogRootJob")

    assert gone_dock.catalog.remove_root(2)

    catalog.hide.assert_not_called()
    job.assert_not_called()


def test_an_unreadable_root_cannot_be_mapped(gone_dock: CatalogDocks) -> None:
    """There is nothing a mapping of a root with no file could be keyed on, so the catalog refuses it whoever asks.

    **Test steps:**

    * map the unreadable root to a folder
    * verify it was refused and nothing is mapped for it
    """
    file = gone_dock.catalog.file
    assert file is not None
    gone_id = next(root.root_id for root in file.roots if not root.readable)

    assert not gone_dock.catalog.map_root(gone_id, Path("/fake/gone"))

    assert gone_id not in gone_dock.catalog.root_paths()
