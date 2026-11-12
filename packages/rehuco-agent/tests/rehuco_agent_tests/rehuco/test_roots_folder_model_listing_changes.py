"""Tests for what a Roots listing tells the cache: the records a folder bears on, the names it holds, and the folders
that appeared in it since its listing before (#487, #645).

The folders are real, under ``tmp_path``, as in the model's other tests.
"""

import shutil
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco.roots_folder_model import RootsFolderModel
from rehuco_agent.rehuco.roots_listing import ListedFolder
from rehuco_agent.rehuco.roots_node import NodeListing
from rehuco_core import RootFolderLister

from rehuco_agent_tests.delete_at_teardown import DeleteAtTeardown
from rehuco_agent_tests.mapped_roots import location_at

from .test_roots_folder_model import (  # noqa: F401  # pylint: disable=unused-import
    WAIT_TIMEOUT_MS,
    child,
    library_fixture,
    make_model,
    make_root,
    open_folder,
)


def heard(model: RootsFolderModel) -> MagicMock:
    """A spy on the listings the model announces from now on.

    :param model: the model.
    :returns: the spy, called with each :class:`ListedFolder`.
    """
    spy = MagicMock()
    model.folder_listed.connect(spy)
    return spy


def last(spy: MagicMock) -> ListedFolder:
    """The listing a spy heard last.

    :param spy: what :func:`heard` returned.
    :returns: the listing.
    """
    listed = spy.call_args.args[0]
    assert isinstance(listed, ListedFolder)
    return listed


def test_a_relist_names_what_the_folder_holds_and_the_folders_that_appeared(
    qtbot: QtBot, library: Path, delete_at_teardown: DeleteAtTeardown
) -> None:
    """A folder listed again names the folders and files it holds now, and the folders new since its listing before;
    a folder where a file was is new (#645).

    **Test steps:**

    * list a root; on disk, delete a folder and a file, add a folder, and put a folder where a file was
    * list the root again
    * verify the listing names what is left, and the two folders that appeared, under the root
    """
    model = make_model(delete_at_teardown, qtbot, [make_root(library)])
    root = model.index(0, 0)
    spy = heard(model)
    shutil.rmtree(library / "beta")
    (library / "file2.mp4").unlink()
    (library / "gamma").mkdir()
    (library / "file10.mp4").unlink()
    (library / "file10.mp4").mkdir()

    assert model.relist(root)
    qtbot.waitUntil(lambda: spy.call_count == 1, timeout=WAIT_TIMEOUT_MS)

    listed = last(spy)
    assert listed.folder == library
    assert sorted(listed.folders) == ["alpha", "file10.mp4", "gamma"]
    assert listed.files == ()
    assert sorted(listed.appeared) == sorted([library / "file10.mp4", library / "gamma"])


def test_a_first_listing_names_its_records_and_no_folder_appeared(
    qtbot: QtBot, library: Path, delete_at_teardown: DeleteAtTeardown
) -> None:
    """A folder listed for the first time has no listing before it to compare with: no folder appeared, and one made
    before its column was ever opened is a scan's to find. Its records are those it holds and the directory-scoped one
    above that manages it (#487, #645).

    **Test steps:**

    * a folder holding a directory-scoped record, and a subfolder holding a file-scoped one and a folder
    * open the subfolder for the first time
    * verify its listing names both records and what the subfolder holds, and no folder appeared
    """
    (library / "alpha" / "info.rehu").write_bytes(b"")
    (library / "alpha" / "sub" / "x.rehu").write_bytes(b"")
    (library / "alpha" / "sub" / "made").mkdir()
    model = make_model(delete_at_teardown, qtbot, [make_root(library)])
    alpha = child(model, model.index(0, 0), "alpha")
    open_folder(qtbot, model, alpha)
    spy = heard(model)

    open_folder(qtbot, model, child(model, alpha, "sub"))

    assert last(spy) == ListedFolder(
        library / "alpha" / "sub",
        (library / "alpha" / "sub" / "x.rehu", library / "alpha" / "info.rehu"),
        ("made",),
        ("x.rehu",),
    )


def test_a_relist_after_the_folder_could_not_be_read_names_nothing_appeared(
    qtbot: QtBot, tmp_path: Path, delete_at_teardown: DeleteAtTeardown
) -> None:
    """A listing that could not read the folder showed nothing of it, so the next one has nothing to compare with
    (#645).

    **Test steps:**

    * show a root whose folder is not there, and wait for its listing
    * create the folder with a subfolder in it, and list the root again
    * verify the listing names the subfolder, and nothing appeared
    """
    folder = tmp_path / "missing"
    model = make_model(delete_at_teardown, qtbot, [make_root(folder)])
    root = model.index(0, 0)
    assert model.listing_state(root) is NodeListing.UNREACHABLE
    spy = heard(model)
    (folder / "sub").mkdir(parents=True)

    assert model.relist(root)
    qtbot.waitUntil(lambda: spy.call_count == 1, timeout=WAIT_TIMEOUT_MS)

    assert last(spy) == ListedFolder(folder, (), ("sub",))


def test_a_relist_that_cannot_read_the_folder_announces_nothing(
    qtbot: QtBot, library: Path, delete_at_teardown: DeleteAtTeardown
) -> None:
    """A folder that will not list says nothing about what it holds: an offline root keeps every row ([[mounts-and-
    storage#offline-mounts]], #645).

    **Test steps:**

    * list a root, then take its folder away and list it again
    * verify it reads as unreachable and nothing was announced
    """
    model = make_model(delete_at_teardown, qtbot, [make_root(library)])
    root = model.index(0, 0)
    spy = heard(model)
    library.rename(library.with_name("away"))

    assert model.relist(root)
    qtbot.waitUntil(lambda: model.listing_state(root) is NodeListing.UNREACHABLE, timeout=WAIT_TIMEOUT_MS)

    spy.assert_not_called()


def test_a_root_pointed_at_another_folder_compares_its_first_listing_with_nothing(
    qtbot: QtBot, library: Path, tmp_path: Path, delete_at_teardown: DeleteAtTeardown
) -> None:
    """A root whose folder changed lists the new folder afresh: what the old one showed is no listing before it
    (#645).

    **Test steps:**

    * list a root, then point it at another folder holding other folders
    * verify the new folder's listing names its folder, and nothing appeared
    """
    root = make_root(library)
    model = make_model(delete_at_teardown, qtbot, [root])
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "inside").mkdir(parents=True)
    moved = replace(root, path=elsewhere, location=location_at(elsewhere))
    spy = heard(model)

    model.set_roots([moved], RootFolderLister([moved]))
    qtbot.waitUntil(lambda: spy.call_count == 1, timeout=WAIT_TIMEOUT_MS)

    assert last(spy) == ListedFolder(elsewhere, (), ("inside",))
