"""Tests for the roots this machine does not map, as the Roots view's model shows them (#514): a greyed row in the
file's order with one row saying so, never listed, and moving, renaming and mapping still work on it.

The folders of the mapped roots are real, under ``tmp_path``; an unmapped root has none, which is the point.
"""

from dataclasses import replace
from pathlib import Path
from typing import Final
from uuid import uuid4

from PySide6.QtCore import Qt
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco.root_folder_loader import RootFolderLoader
from rehuco_agent.rehuco.root_storage import NOT_MAPPED_ROW, ROOT_STORAGE_ICONS
from rehuco_agent.rehuco.roots_folder_model import RootsFolderModel
from rehuco_agent.rehuco.roots_node import NodeListing, RootsNodeKind
from rehuco_core import RehucoRoot, Relocation, RootFolderLister, RootStorage

from rehuco_agent_tests.delete_at_teardown import DeleteAtTeardown
from rehuco_agent_tests.mapped_roots import mapped_root
from rehuco_agent_tests.rehuco.test_roots_folder_model import Recorder, make_model, names, wait_listed

LOCATION: Final = "//nas/data/Tutorials"


def unmapped(label: str = "away") -> RehucoRoot:
    """A root of the file this machine has no folder for.

    :param label: its label.
    :returns: the root.
    """
    return RehucoRoot(uuid4(), label, LOCATION)


def test_an_unmapped_root_is_a_greyed_row_in_the_files_order_with_one_row_saying_so(
    qtbot: QtBot, tmp_path: Path, delete_at_teardown: DeleteAtTeardown
) -> None:
    """The roots are shown as the file orders them, a root this machine does not map among them, drawn greyed with a
    single child row that says why it is empty.

    **Test steps:**

    * show a mapped root, an unmapped one, and another mapped one
    * verify the order, the unmapped row's greyed role and glyph, its path line and tooltip (its location), and its one
      child row
    """
    (tmp_path / "a").mkdir()
    (tmp_path / "c").mkdir()
    first, last = mapped_root(tmp_path / "a", "a"), mapped_root(tmp_path / "c", "c")
    away = unmapped()
    model = make_model(delete_at_teardown, qtbot, [first, last])

    model.set_roots([first, away, last], RootFolderLister([first, last]))

    assert names(model) == ["a", "away", "c"]
    row = model.index(1, 0)
    assert row.data(RootsFolderModel.GREYED_ROLE) is True
    assert model.index(0, 0).data(RootsFolderModel.GREYED_ROLE) is False
    assert row.data(RootsFolderModel.ICON_PATH_ROLE) == ROOT_STORAGE_ICONS[RootStorage.LOCAL]
    assert row.data(RootsFolderModel.PATH_ROLE) == LOCATION
    assert row.data(Qt.ItemDataRole.ToolTipRole) == LOCATION
    assert row.data(Qt.ItemDataRole.FontRole) is None
    assert names(model, row) == [NOT_MAPPED_ROW]
    assert model.node_kind(model.index(0, 0, row)) is RootsNodeKind.UNREACHABLE
    assert model.index(0, 0, row).data(RootsFolderModel.GREYED_ROLE) is True


def test_an_unmapped_root_is_never_listed(
    qtbot: QtBot, mocker: MockerFixture, tmp_path: Path, delete_at_teardown: DeleteAtTeardown
) -> None:
    """There is no folder to ask for, so nothing asks: not the view, not a refresh, not a relist of its chain.

    **Test steps:**

    * show only an unmapped root over a lister, and watch the loader
    * ask to fetch more, relist the root, its chain and its folder
    * verify nothing was fetchable, no listing started, and the root is still unlisted with its one row
    """
    start = mocker.spy(RootFolderLoader, "start")
    away = unmapped()
    model = delete_at_teardown(RootsFolderModel())
    model.set_roots([away], RootFolderLister([]))
    row = model.index(0, 0)

    assert not model.canFetchMore(row)
    model.fetchMore(row)
    assert not model.relist(row)
    model.relist_chain(model.index(0, 0, row))
    model.relist_folder(tmp_path)

    start.assert_not_called()
    assert model.listing_state(row) is NodeListing.UNLISTED
    assert names(model, row) == [NOT_MAPPED_ROW]
    assert model.hasChildren(row)
    assert model.child_names(row) is None
    qtbot.wait(0)


def test_an_unmapped_root_has_no_path_but_a_key_and_keeps_its_place_among_the_roots(
    qtbot: QtBot, delete_at_teardown: DeleteAtTeardown
) -> None:
    """What the panel asks of any root row still answers for an unmapped one, except where it is on disk.

    **Test steps:**

    * show an unmapped root
    * verify its root, kind, key and index, no path for it, and nothing for its placeholder row
    """
    away = unmapped()
    model = make_model(delete_at_teardown, qtbot, [])
    model.set_roots([away], RootFolderLister([]))
    row = model.index(0, 0)
    placeholder = model.index(0, 0, row)

    assert model.root_at(row) == away
    assert model.root_of(placeholder) == away
    assert model.node_kind(row) is RootsNodeKind.ROOT
    assert model.key(row) == (away.root_id, ())
    assert model.index_for(away.root_id, ()) == row
    assert model.path_of(row) is None
    assert model.path_of(placeholder) is None
    assert model.key(placeholder) is None


def test_a_root_that_gains_or_loses_its_mapping_changes_what_it_shows(
    qtbot: QtBot, tmp_path: Path, delete_at_teardown: DeleteAtTeardown
) -> None:
    """Mapping a root lists it and drops the row that said it could not be; losing the mapping puts that row back and
    drops what was listed.

    **Test steps:**

    * show a root unmapped, then mapped over a folder holding a file
    * verify the row is gone and the file is listed, with the glyph of the detected storage
    * show it unmapped again
    * verify the file is gone and the one row is back
    """
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "file.txt").write_text("x", encoding="utf-8")
    away = unmapped()
    model = delete_at_teardown(RootsFolderModel())
    model.set_roots([away], RootFolderLister([]))
    mapped = replace(
        mapped_root(tmp_path / "lib", away.label, RootStorage.NETWORK), root_id=away.root_id, location=away.location
    )

    model.set_roots([mapped], RootFolderLister([mapped]))
    wait_listed(qtbot, model, model.index(0, 0))

    assert names(model, model.index(0, 0)) == ["file.txt"]
    assert model.index(0, 0).data(RootsFolderModel.ICON_PATH_ROLE) == ROOT_STORAGE_ICONS[RootStorage.NETWORK]
    assert model.index(0, 0).data(RootsFolderModel.GREYED_ROLE) is False

    model.set_roots([away], RootFolderLister([]))

    assert names(model, model.index(0, 0)) == [NOT_MAPPED_ROW]
    assert model.listing_state(model.index(0, 0)) is NodeListing.UNLISTED


def test_relabelling_an_unmapped_root_renames_its_row_and_lists_nothing(
    qtbot: QtBot, mocker: MockerFixture, delete_at_teardown: DeleteAtTeardown
) -> None:
    """The row follows the file's label, and nothing is listed for it: its folder, none, did not change.

    **Test steps:**

    * show an unmapped root, then the same root relabelled
    * verify the row's name, one change said, and no listing started
    """
    start = mocker.spy(RootFolderLoader, "start")
    away = unmapped()
    model = delete_at_teardown(RootsFolderModel())
    model.set_roots([away], RootFolderLister([]))
    recorder = Recorder(model)

    model.set_roots([replace(away, label="renamed")], RootFolderLister([]))

    assert names(model) == ["renamed"]
    assert recorder.count("changed") == 1
    start.assert_not_called()
    qtbot.wait(0)


def test_an_unmapped_root_is_moved_like_any_other(
    qtbot: QtBot, tmp_path: Path, delete_at_teardown: DeleteAtTeardown
) -> None:
    """Its place in the file is the file's business, so it can be dragged and asked to move.

    **Test steps:**

    * show an unmapped root between two mapped ones, reorderable
    * ask for the unmapped one to move to the end
    * verify the request names it and the place
    """
    roots = []
    for name in ("a", "c"):
        (tmp_path / name).mkdir()
        roots.append(mapped_root(tmp_path / name, name))
    away = unmapped()
    model = make_model(delete_at_teardown, qtbot, roots)
    model.set_roots([roots[0], away, roots[1]], RootFolderLister(roots))
    model.set_reorderable(True)
    asked: list[tuple[object, int]] = []
    model.root_move_requested.connect(lambda root_id, to: asked.append((root_id, to)))

    assert model.request_root_move(1, 2)

    assert asked == [(away.root_id, 2)]
    assert model.flags(model.index(1, 0)) & Qt.ItemFlag.ItemIsDragEnabled


def test_a_rename_under_a_mapped_root_is_followed_past_an_unmapped_one(
    qtbot: QtBot, tmp_path: Path, delete_at_teardown: DeleteAtTeardown
) -> None:
    """An unmapped root holds no path any rename could be under, so looking a renamed path up skips it.

    **Test steps:**

    * show an unmapped root before a mapped one that holds a file
    * relocate the file within its folder
    * verify the file's row has the new name, and the unmapped row is unchanged
    """
    folder = tmp_path / "lib"
    folder.mkdir()
    (folder / "old.txt").write_text("x", encoding="utf-8")
    mapped = mapped_root(folder, "lib")
    away = unmapped()
    model = delete_at_teardown(RootsFolderModel())
    model.set_roots([away, mapped], RootFolderLister([mapped]))
    wait_listed(qtbot, model, model.index(1, 0))

    model.relocate(Relocation(((folder / "old.txt", folder / "new.txt"),)))

    assert names(model, model.index(1, 0)) == ["new.txt"]
    assert names(model, model.index(0, 0)) == [NOT_MAPPED_ROW]
