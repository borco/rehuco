"""Tests for :class:`~rehuco_core.RootFolderLister` (#378)."""

import threading
from pathlib import Path
from typing import Final
from uuid import UUID, uuid4

from pytest import fixture
from rehuco_core import FileType, RehucoRoot, RenameCoordinator, RootFolderLister, RootStorage

ROOT_ID: Final = UUID("a41b9c3d-0000-4000-8000-000000000001")


@fixture(name="library")
def library_fixture(tmp_path: Path) -> Path:
    """A root folder holding a directory-scoped resource, a video and a record.

    :param tmp_path: pytest's temporary directory.
    :returns: the root folder.
    """
    root = tmp_path / "library"
    (root / "python" / "week1").mkdir(parents=True)
    (root / "python" / "info.rehu").write_text("{}", encoding="utf-8")
    (root / "intro.mp4").write_bytes(b"x")
    (root / "info.rehu").write_text("{}", encoding="utf-8")
    return root


def lister_for(root: Path, coordinator: RenameCoordinator | None = None) -> RootFolderLister:
    """A lister over one root.

    :param root: the root's folder.
    :param coordinator: what each read is held under.
    :returns: the lister.
    """
    return RootFolderLister([RehucoRoot(ROOT_ID, root, "library", RootStorage.LOCAL)], coordinator=coordinator)


def test_a_root_lists_its_entries_with_their_kinds(library: Path) -> None:
    """The root's own folder lists every entry, folders marked and files typed.

    **Test steps:**

    * list the root with no relative path
    * verify it is reachable and the entries are the subfolder, the video and the record, by type
    """
    listing = lister_for(library).list(ROOT_ID)
    assert listing.reachable
    assert {(entry.name, entry.file_type, entry.is_directory) for entry in listing.entries} == {
        ("python", FileType.DIRECTORY, True),
        ("intro.mp4", FileType.VIDEO, False),
        ("info.rehu", FileType.RECORD, False),
    }


def test_a_relative_path_lists_a_folder_under_the_root(library: Path) -> None:
    """A relative path, one name per step, lists that folder.

    **Test steps:**

    * list ``python`` and then ``python/week1``
    * verify the first holds ``week1`` and its record, and the second is reachable and empty
    """
    lister = lister_for(library)
    assert {entry.name for entry in lister.list(ROOT_ID, ("python",)).entries} == {"week1", "info.rehu"}
    deepest = lister.list(ROOT_ID, ("python", "week1"))
    assert deepest.reachable
    assert not deepest.entries


def test_a_missing_folder_and_an_unknown_root_are_not_reachable(library: Path) -> None:
    """Gone is not empty: both answers say so, and neither raises.

    **Test steps:**

    * list a folder that does not exist, and a root id the lister was not given
    * verify both come back empty and not reachable
    """
    lister = lister_for(library)
    for listing in (lister.list(ROOT_ID, ("nope",)), lister.list(uuid4())):
        assert not listing.reachable
        assert not listing.entries


def test_a_listing_leaves_the_folder_renamable(library: Path) -> None:
    """No handle is held after a listing, so the folder can be renamed at once.

    **Test steps:**

    * list ``python`` under a coordinator, then rename the resource whose folder it is
    * verify the rename lands
    """
    coordinator = RenameCoordinator()
    lister_for(library, coordinator).list(ROOT_ID, ("python",))
    coordinator.rename(library / "python" / "info.rehu", "py")
    assert (library / "py" / "week1").is_dir()


def test_a_listing_waits_for_a_rename_in_flight(library: Path) -> None:
    """A read started while a rename is waiting to run holds off until the rename is done, and then sees its result.

    **Test steps:**

    * occupy the coordinator with a reader on one thread, and start a rename on another, which raises
      ``yield_wanted`` and waits for that reader
    * start a listing on a third thread: it waits, since a rename is pending
    * release the reader
    * verify the rename landed and the listing returned afterwards, naming the folder as renamed
    """
    coordinator = RenameCoordinator()
    lister = lister_for(library, coordinator)
    reader_in = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with coordinator.holding():
            reader_in.set()
            release.wait(5)

    holder = threading.Thread(target=hold)
    holder.start()
    assert reader_in.wait(5)
    renamer = threading.Thread(target=lambda: coordinator.rename(library / "python" / "info.rehu", "py"))
    renamer.start()
    while not coordinator.yield_wanted:
        threading.Event().wait(0.01)
    listed: list[set[str]] = []
    reader = threading.Thread(target=lambda: listed.append({entry.name for entry in lister.list(ROOT_ID).entries}))
    reader.start()
    release.set()
    for thread in (holder, renamer, reader):
        thread.join(5)
    assert listed == [{"py", "intro.mp4", "info.rehu"}]
