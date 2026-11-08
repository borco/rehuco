"""Tests for the Roots view's handling of a root whose ``.rehuroot`` cannot be read (#577): it is listed greyed with one
row saying so and the reason as its tooltip, offers neither Map nor a name to edit, and can still be removed. The rows
the cache holds for it are kept, as an offline root's are, until it is.

The panel runs over the mock catalog of ``test_catalog_docks``, with the ``.rehuco`` served and its writes captured; the
served file names one more root file than there are roots, which is the missing one.
"""

import json
from pathlib import Path
from typing import Any, Final
from unittest.mock import MagicMock, Mock
from uuid import UUID

from PySide6.QtCore import Qt
from pytest import LogCaptureFixture, fixture
from pytest_mock import MockerFixture
from rehuco_agent.rehuco.root_storage import NOT_MAPPED_ROW, UNREADABLE_ROW
from rehuco_agent.rehuco.roots_folder_model import RootsFolderModel
from rehuco_core import RemoveCatalogRootJob
from rehuco_core.access import CatalogUnreadable

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
    * verify the name field, its default button and the Edit toggle are disabled, and the storage line says the file
      cannot be read
    * select a readable root and verify the name field and the Edit toggle are enabled again
    """
    roots = gone_dock.roots

    select_root(gone_dock, 2)

    assert not roots.root_name_edit.isEnabled()
    assert not roots.default_root_name_action.isEnabled()
    assert not roots.edit_root_action.isEnabled()
    assert roots.root_storage_value.text() == UNREADABLE_ROW

    select_root(gone_dock, 0)

    assert roots.root_name_edit.isEnabled()
    assert roots.edit_root_action.isEnabled()
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
    """The cache holds nothing of a root this machine never read, so dropping its reference touches the cache not at
    all.

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


@fixture(name="lost_dock")
def fixture_lost_dock(
    dock: CatalogDocks, served: dict[str, Any], on_disk: dict[Path, str], saves: MagicMock
) -> tuple[CatalogDocks, UUID, Path]:
    """The docks over the served catalog, opened once with both roots readable -- so the cache holds both, each with
    its root file -- then opened again after the second root's file went missing.

    :param dock: the docks.
    :param served: the served document; its second root is taken out, so its root file reads as missing.
    :param on_disk: what a read of a written file answers; the ``.rehuco`` is put there, still naming both files.
    :param saves: captures the ``.rehuco`` writes.
    :returns: the docks, the lost root's id, and its root file.
    """
    del saves
    assert dock.catalog.open_rehuco(REHUCO_PATH)
    file = dock.catalog.file
    assert file is not None
    lost = next(root for root in file.roots if root.label == "packs")
    assert lost.file is not None
    on_disk[REHUCO_PATH] = json.dumps(served_rehuco(served))
    del served["roots"][1]
    assert dock.catalog.open_rehuco(REHUCO_PATH)
    return dock, lost.root_id, lost.file


def test_a_root_whose_file_went_missing_keeps_its_rows_offline(
    lost_dock: tuple[CatalogDocks, UUID, Path], catalog: Mock
) -> None:
    """The cache is handed the missing file to hold, keeps the root's rows under its own id, and the root reads as one
    that cannot be reached -- greyed in the browsers, left out of the overlap check -- rather than as gone.

    **Test steps:**

    * open the catalog with both root files, then again with the second one missing
    * verify the cache was handed the missing file, still lists the root, and the root reads as unreachable
    * verify the root is not one this machine reaches, so nothing scans or watches it
    """
    dock, lost_id, lost_file = lost_dock

    assert catalog.prepare.call_args.args[2] == (lost_file,)
    assert lost_id in {root.root_id for root in catalog.roots()}
    assert lost_id in dock.catalog.unreachable_roots()
    assert lost_id not in dock.catalog.root_paths()


def test_removing_a_root_whose_file_went_missing_removes_its_rows(
    mocker: MockerFixture, lost_dock: tuple[CatalogDocks, UUID, Path], catalog: Mock
) -> None:
    """Removal is what clears a held root's rows: its id is read from the cache's row of its file, the one place
    it is still known.

    **Test steps:**

    * remove the root whose file went missing
    * verify it was hidden from the catalog and a removal of its rows queued, both by its own id
    """
    job = mocker.patch("rehuco_agent.rehuco.root_catalog.RemoveCatalogRootJob", wraps=RemoveCatalogRootJob)
    dock, lost_id, _ = lost_dock

    assert dock.catalog.remove_root(1)

    catalog.hide.assert_called_once_with(lost_id)
    assert job.call_args.args[1] == lost_id


def test_removing_a_root_whose_file_went_missing_from_a_cache_that_cannot_be_read(
    mocker: MockerFixture, lost_dock: tuple[CatalogDocks, UUID, Path], catalog: Mock, caplog: LogCaptureFixture
) -> None:
    """With no cache to read the root's id from, the reference is still dropped; the failure is logged and nothing is
    queued, the rows left to the next removal or scan to sort out.

    **Test steps:**

    * make the cache unreadable, and remove the root whose file went missing
    * verify the removal saved, nothing was hidden or queued, and the failure was logged
    """
    job = mocker.patch("rehuco_agent.rehuco.root_catalog.RemoveCatalogRootJob")
    catalog.root_read_from.side_effect = CatalogUnreadable("the cache is locked")
    dock, _, _ = lost_dock

    assert dock.catalog.remove_root(1)

    catalog.hide.assert_not_called()
    job.assert_not_called()
    assert "the cache is locked" in caplog.text
