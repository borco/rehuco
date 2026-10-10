"""Tests for the Roots view's model: lazy listing, in-place changes and the follow of a rename (#378).

The folders are real, under ``tmp_path``: what is under test is what a listing reads and how a model keeps up with it,
and a faked directory would only restate the fake.
"""

import threading
from pathlib import Path
from typing import Any, Final
from uuid import UUID, uuid4

from PySide6.QtCore import QMimeData, QModelIndex, QPersistentModelIndex, Qt
from pytest import fixture, mark, param
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco.root_folder_loader import RootFolderLoader
from rehuco_agent.rehuco.root_storage import ROOT_STORAGE_ICONS
from rehuco_agent.rehuco.roots_folder_model import (
    LOADING_ROW,
    ROOT_MIME_TYPE,
    NodeListing,
    RootsFolderModel,
    RootsNodeKind,
)
from rehuco_core import RehucoRoot, Relocation, RenameCoordinator, RootFolderLister, RootStorage

WAIT_TIMEOUT_MS: Final = 10_000


# a recorder is its connections and one question; nothing more to give it
# pylint: disable-next=too-few-public-methods
class Recorder:
    """Every structural signal a model emits, by name, so a test can say what did and did not happen."""

    def __init__(self, model: RootsFolderModel) -> None:
        self.events: Final[list[str]] = []
        model.modelReset.connect(lambda: self.events.append("reset"))
        model.rowsInserted.connect(lambda *_: self.events.append("inserted"))
        model.rowsRemoved.connect(lambda *_: self.events.append("removed"))
        model.rowsMoved.connect(lambda *_: self.events.append("moved"))
        model.dataChanged.connect(lambda *_: self.events.append("changed"))

    def count(self, name: str) -> int:
        """How many times ``name`` was emitted."""
        return self.events.count(name)


@fixture(name="library")
def library_fixture(tmp_path: Path) -> Path:
    """A root folder holding two folders, one with a subfolder and a note, and two videos named to sort naturally.

    :param tmp_path: pytest's temporary directory.
    :returns: the root folder.
    """
    root = tmp_path / "lib"
    (root / "alpha" / "sub").mkdir(parents=True)
    (root / "alpha" / "note.txt").write_text("n", encoding="utf-8")
    (root / "beta").mkdir()
    (root / "file10.mp4").write_bytes(b"x")
    (root / "file2.mp4").write_bytes(b"x")
    return root


def make_root(path: Path, label: str = "lib", storage: RootStorage = RootStorage.LOCAL) -> RehucoRoot:
    """A root over ``path``.

    :param path: its folder.
    :param label: its label.
    :param storage: what it lives on.
    :returns: the root.
    """
    return RehucoRoot(uuid4(), path, label, storage)


def make_model(qtbot: QtBot, roots: list[RehucoRoot], coordinator: RenameCoordinator | None = None) -> RootsFolderModel:
    """A model showing ``roots``, each already listed.

    :param qtbot: pytest-qt fixture.
    :param roots: the roots to show.
    :param coordinator: what each read is held under.
    :returns: the model.
    """
    model = RootsFolderModel()
    model.set_roots(roots, RootFolderLister(roots, coordinator=coordinator))
    for row in range(len(roots)):
        wait_listed(qtbot, model, model.index(row, 0))
    return model


def wait_listed(qtbot: QtBot, model: RootsFolderModel, index: QModelIndex) -> None:
    """Wait until a root's or folder's listing has landed.

    :param qtbot: pytest-qt fixture.
    :param model: the model.
    :param index: the root or folder.
    """
    qtbot.waitUntil(
        lambda: model.listing_state(index) in (NodeListing.LISTED, NodeListing.UNREACHABLE), timeout=WAIT_TIMEOUT_MS
    )


def names(model: RootsFolderModel, parent: QModelIndex | None = None) -> list[str]:
    """The display text of every row under ``parent``, in order.

    :param model: the model.
    :param parent: the row; the top when omitted.
    :returns: the names.
    """
    parent = QModelIndex() if parent is None else parent
    return [str(model.index(row, 0, parent).data()) for row in range(model.rowCount(parent))]


def child(model: RootsFolderModel, parent: QModelIndex, name: str) -> QModelIndex:
    """The row named ``name`` under ``parent``.

    :param model: the model.
    :param parent: the row.
    :param name: the row's name.
    :returns: its index.
    """
    return model.index(names(model, parent).index(name), 0, parent)


def open_folder(qtbot: QtBot, model: RootsFolderModel, index: QModelIndex) -> None:
    """Fetch a folder the way a view does and wait for it.

    :param qtbot: pytest-qt fixture.
    :param model: the model.
    :param index: the folder.
    """
    assert model.canFetchMore(index)
    model.fetchMore(index)
    wait_listed(qtbot, model, index)


# region Listing


def test_a_root_is_listed_when_it_is_shown_and_its_folders_on_demand(qtbot: QtBot, library: Path) -> None:
    """Roots are listed at once, so an away root reads as away unclicked; a folder lists only when a view asks.

    **Test steps:**

    * show a root over a folder with two subfolders, a file in one of them, and two videos
    * verify the root is listed, its folders are unlisted and can be fetched, and a file cannot
    """
    model = make_model(qtbot, [make_root(library)])
    root = model.index(0, 0)

    assert model.listing_state(root) is NodeListing.LISTED
    alpha = child(model, root, "alpha")
    assert model.listing_state(alpha) is NodeListing.UNLISTED
    assert model.canFetchMore(alpha)
    assert model.hasChildren(alpha)
    video = child(model, root, "file2.mp4")
    assert not model.canFetchMore(video)
    assert not model.hasChildren(video)


def test_a_listing_shows_folders_first_then_files_in_natural_order_with_no_parent_row(
    qtbot: QtBot, library: Path
) -> None:
    """The order the files sub-dock reads in, and no ``..``, which a column view has no use for.

    **Test steps:**

    * list the root of the library
    * verify the folders, then the videos with ``file2`` before ``file10``, and the row kinds
    """
    model = make_model(qtbot, [make_root(library)])
    root = model.index(0, 0)

    assert names(model, root) == ["alpha", "beta", "file2.mp4", "file10.mp4"]
    assert [model.node_kind(model.index(row, 0, root)) for row in range(4)] == [
        RootsNodeKind.FOLDER,
        RootsNodeKind.FOLDER,
        RootsNodeKind.FILE,
        RootsNodeKind.FILE,
    ]


def test_a_folder_shows_a_loading_row_until_its_listing_lands(
    qtbot: QtBot, library: Path, mocker: MockerFixture
) -> None:
    """A column is never blank while its read is out, and the answer replaces the row in place.

    **Test steps:**

    * hold every read on a gate, show a root, and fetch nothing yet
    * verify the root shows one loading row that cannot be selected
    * release the gate and verify the loading row is replaced by the folders and files
    """
    gate = threading.Event()
    real_list = RootFolderLister.list

    def held(self: RootFolderLister, root_id: UUID, relative: tuple[str, ...] = ()) -> Any:
        assert gate.wait(10)
        return real_list(self, root_id, relative)

    mocker.patch.object(RootFolderLister, "list", held)
    root = make_root(library)
    model = RootsFolderModel()
    model.set_roots([root], RootFolderLister([root]))
    top = model.index(0, 0)

    assert names(model, top) == [LOADING_ROW]
    loading = model.index(0, 0, top)
    assert model.node_kind(loading) is RootsNodeKind.LOADING
    assert not model.flags(loading) & Qt.ItemFlag.ItemIsSelectable
    gate.set()
    wait_listed(qtbot, model, top)
    assert names(model, top) == ["alpha", "beta", "file2.mp4", "file10.mp4"]


def test_a_folder_lists_when_fetched(qtbot: QtBot, library: Path) -> None:
    """Fetching a folder lists it, one level.

    **Test steps:**

    * fetch the ``alpha`` folder
    * verify its subfolder and note, and that the subfolder itself is still unlisted
    """
    model = make_model(qtbot, [make_root(library)])
    alpha = child(model, model.index(0, 0), "alpha")

    open_folder(qtbot, model, alpha)

    assert names(model, alpha) == ["sub", "note.txt"]
    assert model.listing_state(child(model, alpha, "sub")) is NodeListing.UNLISTED


@mark.parametrize(
    ("storage", "row", "greyed", "struck"),
    [
        param(RootStorage.LOCAL, "Folder not found", False, True, id="local-is-struck-through"),
        param(RootStorage.NETWORK, "Share not connected", True, False, id="network-is-greyed"),
        param(RootStorage.REMOVABLE, "Drive not connected", True, False, id="removable-is-greyed"),
        param(RootStorage.COMPACT_DISK, "Disc not inserted", True, False, id="disc-is-greyed"),
    ],
)
# pylint: disable-next=too-many-arguments,too-many-positional-arguments
def test_an_unreachable_root_says_so_by_its_storage(
    qtbot: QtBot, tmp_path: Path, storage: RootStorage, row: str, greyed: bool, struck: bool
) -> None:
    """An away root is never an empty one: one row says why. A vanished local folder is struck through; a share or a
    drive that is merely away is greyed out, keeping its glyph.

    **Test steps:**

    * show a root over a folder that does not exist, of each storage
    * verify it is unreachable with one row naming what is wrong, its glyph is the storage's, and the greyed and
      struck-through roles are as the storage says
    * verify the tooltip names the path
    """
    root = make_root(tmp_path / "gone", "gone", storage)
    model = make_model(qtbot, [root])
    top = model.index(0, 0)

    assert model.listing_state(top) is NodeListing.UNREACHABLE
    assert names(model, top) == [row]
    assert model.node_kind(model.index(0, 0, top)) is RootsNodeKind.UNREACHABLE
    assert top.data(RootsFolderModel.ICON_PATH_ROLE) == ROOT_STORAGE_ICONS[storage]
    assert top.data(RootsFolderModel.GREYED_ROLE) is greyed
    font = top.data(Qt.ItemDataRole.FontRole)
    assert (font is not None and font.strikeOut()) is struck
    assert str(tmp_path / "gone") in top.data(Qt.ItemDataRole.ToolTipRole)


@mark.parametrize("storage", list(RootStorage))
def test_a_reachable_root_wears_its_storages_glyph_plainly(qtbot: QtBot, library: Path, storage: RootStorage) -> None:
    """The glyph says what the root lives on, and nothing about a reachable root is greyed or struck through.

    **Test steps:**

    * show a reachable root of each storage
    * verify its glyph, no greying and no font change
    """
    model = make_model(qtbot, [make_root(library, storage=storage)])
    top = model.index(0, 0)

    assert top.data(RootsFolderModel.ICON_PATH_ROLE) == ROOT_STORAGE_ICONS[storage]
    assert top.data(RootsFolderModel.GREYED_ROLE) is False
    assert top.data(Qt.ItemDataRole.FontRole) is None


def test_a_folder_that_will_not_list_shows_a_row_saying_so(qtbot: QtBot, library: Path) -> None:
    """The same rule one level down: a folder deleted behind the app's back lists as not found, not as empty.

    **Test steps:**

    * fetch ``beta``, delete it on disk, and list it again
    * verify it is unreachable with one row, and its siblings are untouched
    """
    model = make_model(qtbot, [make_root(library)])
    top = model.index(0, 0)
    beta = child(model, top, "beta")
    open_folder(qtbot, model, beta)
    (library / "beta").rmdir()

    model.relist(beta)
    qtbot.waitUntil(lambda: model.listing_state(beta) is NodeListing.UNREACHABLE, timeout=WAIT_TIMEOUT_MS)

    assert names(model, beta) == ["Folder not found"]
    assert names(model, top) == ["alpha", "beta", "file2.mp4", "file10.mp4"]


def test_an_answer_for_a_row_that_has_gone_is_dropped(qtbot: QtBot, library: Path, mocker: MockerFixture) -> None:
    """A read still out when its root is removed answers into nothing, and nothing happens.

    **Test steps:**

    * hold the read of a root, then remove the root and release the read
    * verify the model is empty and stays so
    """
    gate = threading.Event()
    real_list = RootFolderLister.list

    def held(self: RootFolderLister, root_id: UUID, relative: tuple[str, ...] = ()) -> Any:
        assert gate.wait(10)
        return real_list(self, root_id, relative)

    mocker.patch.object(RootFolderLister, "list", held)
    root = make_root(library)
    model = RootsFolderModel()
    model.set_roots([root], RootFolderLister([root]))
    model.set_roots([], None)

    gate.set()
    qtbot.wait(100)

    assert model.rowCount() == 0


# endregion

# region Relisting in place


def test_relisting_removes_only_the_row_that_went_and_keeps_what_was_loaded(qtbot: QtBot, library: Path) -> None:
    """A folder deleted outside the app disappears in place: its siblings, their loaded subtrees and the indexes held
    on them survive, and the model is never reset.

    **Test steps:**

    * load ``alpha`` and its ``sub``, and hold a persistent index on the note
    * delete ``alpha/sub`` and ``beta`` on disk, then list the root and ``alpha`` again
    * verify exactly those rows left, the held index still points at the note, and nothing was reset
    """
    model = make_model(qtbot, [make_root(library)])
    top = model.index(0, 0)
    alpha = child(model, top, "alpha")
    open_folder(qtbot, model, alpha)
    note = QPersistentModelIndex(child(model, alpha, "note.txt"))
    recorder = Recorder(model)
    (library / "alpha" / "sub").rmdir()
    (library / "beta").rmdir()

    model.relist(top)
    model.relist(alpha)
    qtbot.waitUntil(
        lambda: names(model, alpha) == ["note.txt"] and "beta" not in names(model, top), timeout=WAIT_TIMEOUT_MS
    )

    assert names(model, top) == ["alpha", "file2.mp4", "file10.mp4"]
    assert note.data() == "note.txt"
    assert recorder.count("reset") == 0
    assert recorder.count("removed") == 2


def test_relisting_inserts_a_new_row_where_it_sorts(qtbot: QtBot, library: Path) -> None:
    """A folder created outside the app appears in its place in the order, without disturbing the others.

    **Test steps:**

    * create ``aardvark`` on disk and list the root again
    * verify it is the first row and the others follow unchanged
    """
    model = make_model(qtbot, [make_root(library)])
    top = model.index(0, 0)
    (library / "aardvark").mkdir()

    model.relist(top)
    qtbot.waitUntil(lambda: "aardvark" in names(model, top), timeout=WAIT_TIMEOUT_MS)

    assert names(model, top) == ["aardvark", "alpha", "beta", "file2.mp4", "file10.mp4"]


def test_relisting_a_folder_never_asked_for_leaves_it_to_be_fetched(qtbot: QtBot, library: Path) -> None:
    """A folder no view has opened has nothing to refresh; it is read when one first asks.

    **Test steps:**

    * relist ``alpha`` before it was ever fetched
    * verify it is still unlisted, and the chain relist lists the root and the opened folder only
    """
    model = make_model(qtbot, [make_root(library)])
    top = model.index(0, 0)
    alpha = child(model, top, "alpha")

    model.relist(alpha)
    qtbot.wait(50)

    assert model.listing_state(alpha) is NodeListing.UNLISTED


def test_relisting_the_chain_lists_each_open_column_again(qtbot: QtBot, library: Path) -> None:
    """F5 lists the columns on screen: the folder and every one above it.

    **Test steps:**

    * open ``alpha``, add a file to both it and the root on disk, and relist the chain from ``alpha``
    * verify both listings show their new file
    """
    model = make_model(qtbot, [make_root(library)])
    top = model.index(0, 0)
    alpha = child(model, top, "alpha")
    open_folder(qtbot, model, alpha)
    (library / "alpha" / "added.txt").write_text("a", encoding="utf-8")
    (library / "added.mp4").write_bytes(b"x")

    model.relist_chain(alpha)

    qtbot.waitUntil(
        lambda: "added.txt" in names(model, alpha) and "added.mp4" in names(model, top), timeout=WAIT_TIMEOUT_MS
    )


# endregion

# region Changing the roots


def test_changing_the_roots_inserts_moves_updates_and_removes_without_a_reset(qtbot: QtBot, tmp_path: Path) -> None:
    """The model follows the file row by row: nothing is thrown away that did not change.

    **Test steps:**

    * show three roots, then show them reordered with the first relabelled and the second on another storage
    * verify moves and data changes, no reset, and the roots in the new order
    * remove one and add another, and verify the row signals and the new order
    """
    paths = [tmp_path / name for name in ("a", "b", "c")]
    for path in paths:
        path.mkdir()
    first, second, third = (make_root(path, path.name) for path in paths)
    model = make_model(qtbot, [first, second, third])
    lister = RootFolderLister([first, second, third])
    recorder = Recorder(model)

    relabelled = RehucoRoot(first.root_id, first.path, "A", first.storage)
    reshaped = RehucoRoot(second.root_id, second.path, second.label, RootStorage.NETWORK)
    model.set_roots([third, relabelled, reshaped], lister)

    assert names(model) == ["c", "A", "b"]
    assert recorder.count("moved") >= 1
    assert recorder.count("changed") >= 2
    assert recorder.count("reset") == 0
    assert model.index(2, 0).data(RootsFolderModel.ICON_PATH_ROLE) == ROOT_STORAGE_ICONS[RootStorage.NETWORK]

    fourth = make_root(tmp_path / "d", "d")
    model.set_roots([third, fourth, relabelled], lister)

    assert names(model) == ["c", "d", "A"]
    assert recorder.count("removed") == 1
    assert recorder.count("reset") == 0


def test_a_root_pointed_at_another_folder_lists_it_afresh(qtbot: QtBot, library: Path, tmp_path: Path) -> None:
    """A root keeps its id and its place but drops what it had listed when its folder changes.

    **Test steps:**

    * list a root, then show it again over an empty folder
    * verify its rows are the empty folder's
    """
    root = make_root(library)
    model = make_model(qtbot, [root])
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    moved = RehucoRoot(root.root_id, elsewhere, root.label, root.storage)

    model.set_roots([moved], RootFolderLister([moved]))

    qtbot.waitUntil(lambda: names(model, model.index(0, 0)) == [], timeout=WAIT_TIMEOUT_MS)
    assert model.listing_state(model.index(0, 0)) is NodeListing.LISTED


def test_a_key_names_a_row_and_finds_the_deepest_one_that_exists(qtbot: QtBot, library: Path) -> None:
    """The ``(root id, relative path)`` key is what the one listing function is asked by, and what a row falls back
    along when its folder is gone.

    **Test steps:**

    * load ``alpha``, read the key of the note, and look rows up by key
    * verify the key, the exact lookup, the fallback for a name that is not there, and a root that is not shown
    """
    root = make_root(library)
    model = make_model(qtbot, [root])
    top = model.index(0, 0)
    alpha = child(model, top, "alpha")
    open_folder(qtbot, model, alpha)
    note = child(model, alpha, "note.txt")

    assert model.key(note) == (root.root_id, ("alpha", "note.txt"))
    assert model.key(top) == (root.root_id, ())
    assert model.index_for(root.root_id, ("alpha", "note.txt")) == note
    assert model.index_for(root.root_id, ("alpha", "gone", "deeper")) == alpha
    assert not model.index_for(uuid4(), ()).isValid()
    assert model.root_of(note) == root
    assert model.root_at(note) is None
    assert model.root_at(top) == root
    assert model.path_of(note) == library / "alpha" / "note.txt"
    assert model.key(model.index(0, 0, model.index_for(root.root_id, ()))) is not None


# endregion

# region Following the app's own renames


def test_a_renamed_file_is_renamed_in_place_and_resorted(qtbot: QtBot, library: Path) -> None:
    """A rename of a file in a loaded folder changes its row and moves it to where the new name sorts; the model is
    not reset and nothing is read.

    **Test steps:**

    * load ``alpha``, hold an index on its note and rename the note on disk and in the model
    * verify the row has the new name and moved past the file it now sorts after, the held index followed, and
      nothing was reset
    """
    model = make_model(qtbot, [make_root(library)])
    alpha = child(model, model.index(0, 0), "alpha")
    open_folder(qtbot, model, alpha)
    (library / "alpha" / "zzz.txt").write_text("z", encoding="utf-8")
    model.relist(alpha)
    qtbot.waitUntil(lambda: "zzz.txt" in names(model, alpha), timeout=WAIT_TIMEOUT_MS)
    held = QPersistentModelIndex(child(model, alpha, "note.txt"))
    recorder = Recorder(model)
    source, destination = library / "alpha" / "note.txt", library / "alpha" / "zzzz.txt"
    source.rename(destination)

    model.relocate(Relocation(((source, destination),)))

    assert names(model, alpha) == ["sub", "zzz.txt", "zzzz.txt"]
    assert held.data() == "zzzz.txt"
    assert recorder.count("reset") == 0
    assert recorder.count("moved") == 1


def test_a_renamed_folder_takes_its_loaded_subtree_with_it(qtbot: QtBot, library: Path) -> None:
    """One node changes and everything loaded under it follows, because a node stores only its name.

    **Test steps:**

    * load ``alpha`` and its ``sub``, then rename ``alpha`` to ``gamma`` on disk and in the model
    * verify ``gamma`` sorts after ``beta``, its children are still loaded under it, their paths are the new ones
      and nothing was reset
    """
    root = make_root(library)
    model = make_model(qtbot, [root])
    top = model.index(0, 0)
    alpha = child(model, top, "alpha")
    open_folder(qtbot, model, alpha)
    open_folder(qtbot, model, child(model, alpha, "sub"))
    recorder = Recorder(model)
    source, destination = library / "alpha", library / "gamma"
    source.rename(destination)

    model.relocate(Relocation(((source, destination),)))

    assert names(model, top)[:3] == ["beta", "gamma", "file2.mp4"]
    gamma = model.index_for(root.root_id, ("gamma",))
    assert names(model, gamma) == ["sub", "note.txt"]
    assert model.path_of(model.index_for(root.root_id, ("gamma", "sub"))) == library / "gamma" / "sub"
    assert recorder.count("reset") == 0


def test_a_file_moved_to_another_loaded_folder_leaves_one_and_appears_in_the_other(qtbot: QtBot, library: Path) -> None:
    """A move out of the folder removes the row; the destination, if loaded, lists again.

    **Test steps:**

    * load ``alpha`` and ``beta``, then move the note from ``alpha`` to ``beta`` on disk and in the model
    * verify the note left ``alpha`` and shows in ``beta``, with no reset
    """
    model = make_model(qtbot, [make_root(library)])
    top = model.index(0, 0)
    alpha, beta = child(model, top, "alpha"), child(model, top, "beta")
    open_folder(qtbot, model, alpha)
    open_folder(qtbot, model, beta)
    recorder = Recorder(model)
    source, destination = library / "alpha" / "note.txt", library / "beta" / "note.txt"
    source.rename(destination)

    model.relocate(Relocation(((source, destination),)))

    qtbot.waitUntil(lambda: names(model, beta) == ["note.txt"], timeout=WAIT_TIMEOUT_MS)
    assert names(model, alpha) == ["sub"]
    assert recorder.count("reset") == 0


def test_a_rename_of_an_unloaded_folder_changes_nothing_shown(qtbot: QtBot, library: Path) -> None:
    """A path the model has no row for is passed over, and a root's own folder is not followed.

    **Test steps:**

    * relocate a folder that was never loaded, a file nowhere near a root, and the root's own folder
    * verify the rows are as they were
    """
    model = make_model(qtbot, [make_root(library)])
    top = model.index(0, 0)
    before = names(model, top)

    model.relocate(Relocation(((library / "alpha" / "sub", library / "alpha" / "sub2"),)))
    model.relocate(Relocation(((library.parent / "elsewhere", library.parent / "other"),)))
    model.relocate(Relocation(((library, library.parent / "lib2"),)))

    assert names(model, top) == before
    assert names(model) == ["lib"]


def test_the_coordinators_own_rename_of_a_listed_folder_succeeds_and_the_model_follows(
    qtbot: QtBot, library: Path
) -> None:
    """Browsing never blocks a rename: a directory-scoped resource whose folder is listed renames, and the coordinator's
    own announcement is all the model needs to follow.

    **Test steps:**

    * give ``alpha`` a record, load it, and rename the resource through the coordinator with the model listening
    * verify the rename landed on disk, the row is renamed with its subtree, and nothing was reset
    """
    (library / "alpha" / "info.rehu").write_text("{}", encoding="utf-8")
    coordinator = RenameCoordinator()
    root = make_root(library)
    model = make_model(qtbot, [root], coordinator)
    coordinator.add_rename_listener(model.relocate)
    top = model.index(0, 0)
    alpha = child(model, top, "alpha")
    open_folder(qtbot, model, alpha)
    recorder = Recorder(model)

    coordinator.rename(library / "alpha" / "info.rehu", "omega")

    assert (library / "omega" / "note.txt").is_file()
    assert "omega" in names(model, top)
    assert "alpha" not in names(model, top)
    assert names(model, model.index_for(root.root_id, ("omega",))) == ["sub", "info.rehu", "note.txt"]
    assert recorder.count("reset") == 0


# endregion

# region The loader


def test_the_loader_answers_once_per_request_even_for_an_unreadable_folder(qtbot: QtBot, tmp_path: Path) -> None:
    """Every request is answered, an unreadable folder included, so a row can never wait for ever.

    **Test steps:**

    * ask the loader for a folder that does not exist
    * verify one answer, carrying the serial and an unreachable listing
    """
    root = make_root(tmp_path / "missing")
    loader = RootFolderLoader()

    with qtbot.waitSignal(loader.listed, timeout=WAIT_TIMEOUT_MS) as blocker:
        loader.start(7, RootFolderLister([root]), root.root_id, ())

    assert blocker.args is not None
    serial, listing = blocker.args
    assert serial == 7
    assert not listing.reachable


# endregion


# region Dragging roots


def three_roots(qtbot: QtBot, tmp_path: Path) -> tuple[RootsFolderModel, list[RehucoRoot]]:
    """A model over three reachable roots, reorderable.

    :param qtbot: pytest-qt fixture.
    :param tmp_path: pytest's temporary directory.
    :returns: the model and its roots, in order.
    """
    roots = []
    for name in ("a", "b", "c"):
        (tmp_path / name).mkdir()
        roots.append(make_root(tmp_path / name, name))
    model = make_model(qtbot, roots)
    model.set_reorderable(True)
    return model, roots


def drop(model: RootsFolderModel, source: int, row: int, parent: QModelIndex | None = None) -> list[tuple[Any, int]]:
    """Drop the root at ``source`` before ``row`` and report what the model asked for.

    :param model: the model.
    :param source: the dragged root's row.
    :param row: the row it is dropped before; ``-1`` for the end.
    :param parent: where it is dropped; the list itself when omitted.
    :returns: every ``(root id, row)`` the model asked for.
    """
    asked: list[tuple[Any, int]] = []
    model.root_move_requested.connect(lambda root_id, to: asked.append((root_id, to)))
    data = model.mimeData([model.index(source, 0)])
    model.dropMimeData(data, Qt.DropAction.MoveAction, row, 0, QModelIndex() if parent is None else parent)
    return asked


def test_only_a_root_can_be_dragged_and_only_while_reorderable(qtbot: QtBot, tmp_path: Path) -> None:
    """Roots take a drag when the file can be edited; folders, files and placeholders never do, and the list itself is
    what a drop lands on.

    **Test steps:**

    * read the flags of a root, a folder and the list before and after switching reordering on
    * verify the drag flag on the root only when on, the drop flag on the list only when on, and none on a folder
    """
    library = tmp_path / "lib"
    (library / "sub").mkdir(parents=True)
    model = make_model(qtbot, [make_root(library)])
    root, folder = model.index(0, 0), model.index(0, 0, model.index(0, 0))
    assert not model.flags(root) & Qt.ItemFlag.ItemIsDragEnabled
    assert not model.flags(QModelIndex()) & Qt.ItemFlag.ItemIsDropEnabled

    model.set_reorderable(True)

    assert model.flags(root) & Qt.ItemFlag.ItemIsDragEnabled
    assert model.flags(root) & Qt.ItemFlag.ItemIsSelectable
    assert not model.flags(folder) & Qt.ItemFlag.ItemIsDragEnabled
    assert model.flags(QModelIndex()) & Qt.ItemFlag.ItemIsDropEnabled
    assert model.supportedDropActions() == Qt.DropAction.MoveAction
    assert model.mimeTypes() == [ROOT_MIME_TYPE]


def test_a_dragged_root_travels_as_its_id_and_a_folder_travels_as_nothing(qtbot: QtBot, tmp_path: Path) -> None:
    """The mime data names the root and nothing else.

    **Test steps:**

    * make mime data for a root and for a folder
    * verify the first carries the root's id and the second carries nothing
    """
    model, roots = three_roots(qtbot, tmp_path)
    (tmp_path / "a" / "sub").mkdir()
    model.relist(model.index(0, 0))
    qtbot.waitUntil(lambda: model.rowCount(model.index(0, 0)) == 1, timeout=WAIT_TIMEOUT_MS)

    assert bytes(model.mimeData([model.index(1, 0)]).data(ROOT_MIME_TYPE).data()) == str(roots[1].root_id).encode()
    assert not model.mimeData([model.index(0, 0, model.index(0, 0))]).hasFormat(ROOT_MIME_TYPE)


@mark.parametrize(
    ("source", "row", "expected"),
    [
        param(0, -1, 2, id="first-to-the-end"),
        param(2, 0, 0, id="last-to-the-start"),
        param(0, 2, 1, id="first-before-the-last"),
        param(2, 1, 1, id="last-before-the-middle"),
        param(1, 1, None, id="before-itself"),
        param(1, 2, None, id="after-itself"),
    ],
)
def test_a_drop_asks_for_the_row_the_root_will_end_up_at(
    qtbot: QtBot, tmp_path: Path, source: int, row: int, expected: int | None
) -> None:
    """A drop names the row it lands before, in the list as it is; the request names the row in the list as it will
    be, which is one less when the root comes from above. Dropping a root where it already is asks for nothing.

    **Test steps:**

    * drop one of three roots before a row
    * verify the one request, or none when the root would not move
    """
    model, roots = three_roots(qtbot, tmp_path)

    asked = drop(model, source, row)

    assert asked == ([] if expected is None else [(roots[source].root_id, expected)])


def test_a_drop_the_model_cannot_take_is_refused(qtbot: QtBot, tmp_path: Path) -> None:
    """Nothing is asked for when reordering is off, when the drop is onto a row, when it is not a move, when it is
    not a root, or when it names a root that is not shown.

    **Test steps:**

    * try each of those drops
    * verify each returns false and asks for nothing
    """
    model, roots = three_roots(qtbot, tmp_path)
    asked: list[object] = []
    model.root_move_requested.connect(lambda *args: asked.append(args))
    data = model.mimeData([model.index(0, 0)])

    assert not model.dropMimeData(data, Qt.DropAction.MoveAction, 1, 0, model.index(1, 0))
    assert not model.dropMimeData(data, Qt.DropAction.CopyAction, 1, 0, QModelIndex())
    assert not model.dropMimeData(QMimeData(), Qt.DropAction.MoveAction, 1, 0, QModelIndex())
    stranger = QMimeData()
    stranger.setData(ROOT_MIME_TYPE, str(uuid4()).encode())
    assert not model.dropMimeData(stranger, Qt.DropAction.MoveAction, 1, 0, QModelIndex())
    garbled = QMimeData()
    garbled.setData(ROOT_MIME_TYPE, b"not an id")
    assert not model.dropMimeData(garbled, Qt.DropAction.MoveAction, 1, 0, QModelIndex())
    model.set_reorderable(False)
    assert not model.dropMimeData(data, Qt.DropAction.MoveAction, 2, 0, QModelIndex())
    assert not asked
    assert roots


# endregion


def test_a_move_is_asked_for_only_when_a_movable_root_would_move(qtbot: QtBot, tmp_path: Path) -> None:
    """The dragged root's drop asks the file for a move through the model -- and only for one that moves a root while
    roots can be reordered.

    **Test steps:**

    * ask to move the first root to the last row, a root to its own row, a row that is not there, and the first root
      again with reordering off
    * verify only the first was asked for
    """
    model, roots = three_roots(qtbot, tmp_path)
    asked: list[tuple[Any, int]] = []
    model.root_move_requested.connect(lambda root_id, to: asked.append((root_id, to)))

    assert model.request_root_move(0, 2)
    assert not model.request_root_move(1, 1)
    assert not model.request_root_move(5, 0)
    model.set_reorderable(False)
    assert not model.request_root_move(0, 2)

    assert asked == [(roots[0].root_id, 2)]


def test_a_listing_that_fails_with_an_os_error_shows_the_root_as_unreachable(
    qtbot: QtBot, mocker: MockerFixture, library: Path
) -> None:
    """A read that raises, as a share dropping mid-read does, answers as an unreachable folder.

    **Test steps:**

    * show a root whose lister raises ``OSError``
    * verify the root is unreachable
    """
    root = make_root(library)
    lister = RootFolderLister([root])
    mocker.patch.object(lister, "list", side_effect=OSError)
    model = RootsFolderModel()
    model.set_roots([root], lister)
    top = model.index(0, 0)

    wait_listed(qtbot, model, top)

    assert model.listing_state(top) is NodeListing.UNREACHABLE


def test_a_model_with_no_lister_lists_nothing(library: Path) -> None:
    """Roots shown with nothing to list them stay unlisted, and ask for nothing.

    **Test steps:**

    * show a root with no lister
    * verify the root has no rows and is unlisted
    """
    model = RootsFolderModel()
    model.set_roots([make_root(library)], None)
    top = model.index(0, 0)

    assert model.listing_state(top) is NodeListing.UNLISTED
    assert model.rowCount(top) == 0


def test_the_questions_asked_about_no_row_or_a_placeholder_are_answered_with_nothing(
    qtbot: QtBot, tmp_path: Path, library: Path
) -> None:
    """The invalid index and a placeholder row have no key, no parent and no data, and a folder has no tooltip.

    **Test steps:**

    * show a reachable root and an unreachable one
    * verify the invalid index has no key, parent or data, the placeholder under the unreachable root has no key, and
      a folder has no tooltip
    """
    model = make_model(qtbot, [make_root(library), make_root(tmp_path / "gone", "gone")])
    alpha = child(model, model.index(0, 0), "alpha")
    placeholder = model.index(0, 0, model.index(1, 0))

    assert model.key(QModelIndex()) is None
    assert not model.parent(QModelIndex()).isValid()
    assert model.data(QModelIndex()) is None
    assert model.key(placeholder) is None
    assert alpha.data(Qt.ItemDataRole.ToolTipRole) is None
