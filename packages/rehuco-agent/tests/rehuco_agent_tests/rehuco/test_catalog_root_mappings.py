"""Tests for the roots a catalog's machine maps (#514): the ``.rehuco`` names a root by its location and this machine's
own ``root-mappings.json`` says which folder that is here -- opened roots mapped on their own, the rest asked about,
skipped or mapped later, and a save refused when the file changed under the catalog.

The catalog runs over the mock :class:`~rehuco_core.Catalog` of ``test_catalog_docks``, like the rest of the docks'
tests; the mappings are the one thing here that touches a disk, in ``tmp_path``.
"""

import json
import logging
from pathlib import Path
from typing import Any, Final
from unittest.mock import MagicMock, Mock
from uuid import UUID

from pytest import LogCaptureFixture, fixture, mark
from pytest_mock import MockerFixture
from rehuco_agent.rehuco.root_catalog import RootCatalog
from rehuco_core import RootMappings, RootStorage, TaskQueue

from rehuco_agent_tests.mapped_roots import location_at, resolve_test_location

from .test_catalog_docks import (  # noqa: F401  # pylint: disable=unused-import
    HOME,
    PACKS,
    REHUCO_ID,
    REHUCO_PATH,
    ROOT_IDS,
    TUTORIALS,
    CatalogDocks,
    fixture_cache,
    fixture_cached_rows,
    fixture_catalog,
    fixture_dock,
    fixture_no_open_scan,
    fixture_on_disk,
    fixture_queue,
    fixture_saves,
    fixture_served,
)

AWAY: Final = "//nas/data/Tutorials"
"""A location this machine has no mount for."""

AWAY_ID: Final = UUID("a41b9c3d-0000-4000-8000-000000000003")
"""The root served at :data:`AWAY`."""

MAPPINGS_FILE: Final = "root-mappings.json"


@fixture(name="machine")
def fixture_machine(mocker: MockerFixture, tmp_path: Path, real_path_stat: None) -> Path:
    """This machine as the tests spell it, **with real mappings in ``tmp_path``**: a location is found by taking
    ``//test/`` off it, and the mappings file is read and written for real, which is what these tests are about.

    :param mocker: pytest-mock fixture.
    :param tmp_path: pytest's temporary directory, where the mappings live.
    :param real_path_stat: the real ``Path.stat``, which writing a new file needs.
    :returns: the folder the mappings are kept in.
    """
    del real_path_stat
    mocker.patch("rehuco_agent.rehuco.root_catalog.config_folder", return_value=tmp_path)
    mocker.patch("rehuco_agent.rehuco.root_catalog.resolve_location", side_effect=resolve_test_location)
    mocker.patch("rehuco_agent.rehuco.root_catalog.location_of", side_effect=location_at)
    return tmp_path


def stored(machine: Path) -> RootMappings:
    """The mappings as they are on this machine's disk now.

    :param machine: the folder they are kept in.
    :returns: them.
    """
    return RootMappings.load(machine / MAPPINGS_FILE)


def serve_away(served: dict[str, Any]) -> None:
    """Add to the served file a third root this machine has no mount for.

    :param served: the served document.
    """
    served["roots"].append({"id": str(AWAY_ID), "location": AWAY, "label": "away"})


def test_opening_maps_the_roots_this_machine_finds_on_its_own_and_remembers_them(
    dock: CatalogDocks, machine: Path, catalog: Mock, served: dict[str, Any]
) -> None:
    """A location the machine can find is mapped without a question: reached, listed to the cache, and kept in the
    mappings file under the catalog's id with the storage detected for it.

    **Test steps:**

    * serve a file of two roots whose locations this machine resolves, and open it
    * verify both are mapped and none is asked about, the cache was given both folders, and the mappings file holds
      each folder and storage under the file's id
    """
    del served
    assert dock.catalog.open_rehuco(REHUCO_PATH)

    assert [root.path for root in dock.catalog.mapped_roots()] == [TUTORIALS, PACKS]
    assert dock.catalog.unmapped_roots() == ()
    assert dock.catalog.unmapped_root_ids() == frozenset()
    assert dock.catalog.root_paths() == {UUID(ROOT_IDS[0]): TUTORIALS, UUID(ROOT_IDS[1]): PACKS}
    assert [root.path for root in catalog.prepare.call_args.args[1]] == [TUTORIALS, PACKS]
    entries = json.loads((machine / MAPPINGS_FILE).read_text(encoding="utf-8"))["rehucos"][REHUCO_ID]
    assert {UUID(key): Path(value["path"]) for key, value in entries.items()} == {
        UUID(ROOT_IDS[0]): TUTORIALS,
        UUID(ROOT_IDS[1]): PACKS,
    }
    assert all(value["storage"] in {storage.value for storage in RootStorage} for value in entries.values())


def test_a_root_this_machine_cannot_find_stays_unmapped_and_is_asked_about(
    dock: CatalogDocks, catalog: Mock, served: dict[str, Any]
) -> None:
    """The file still lists the root, in its place, but the cache and the watches get only the mapped ones.

    **Test steps:**

    * serve a third root at a location with no mount here, and open the file
    * verify it is unmapped and asked about, the file lists it last, and the cache was given only the other two
    """
    serve_away(served)

    assert dock.catalog.open_rehuco(REHUCO_PATH)

    assert [root.root_id for root in dock.catalog.unmapped_roots()] == [AWAY_ID]
    assert dock.catalog.unmapped_root_ids() == frozenset({AWAY_ID})
    assert [root.label for root in dock.catalog.mapped_roots()] == ["tutorials", "packs"]
    assert dock.catalog.file is not None
    assert [root.label for root in dock.catalog.file.roots] == ["tutorials", "packs", "away"]
    assert [root.label for root in catalog.prepare.call_args.args[1]] == ["tutorials", "packs"]
    assert AWAY_ID not in dock.catalog.root_paths()


def test_a_skipped_root_is_not_asked_about_again_and_stays_unmapped(
    dock: CatalogDocks, machine: Path, served: dict[str, Any]
) -> None:
    """A skip is kept in the mappings file, so opening the catalog again neither asks nor maps it -- even when its
    location can now be found.

    **Test steps:**

    * open a file with an unmapped root and skip it; verify the skip is stored and the root is no longer asked about
    * serve the root at a location this machine resolves and open the file again
    * verify it is still unmapped, still not asked about, and not mapped by itself
    """
    serve_away(served)
    dock.catalog.open_rehuco(REHUCO_PATH)

    assert dock.catalog.skip_roots([AWAY_ID])

    assert dock.catalog.unmapped_roots() == ()
    assert dock.catalog.unmapped_root_ids() == frozenset({AWAY_ID})
    assert stored(machine).skipped(UUID(REHUCO_ID), AWAY_ID)
    served["roots"][2]["location"] = location_at(TUTORIALS / "again")
    assert dock.catalog.open_rehuco(REHUCO_PATH)
    assert dock.catalog.unmapped_roots() == ()
    assert dock.catalog.unmapped_root_ids() == frozenset({AWAY_ID})


def test_mapping_a_root_later_maps_it_replaces_a_skip_and_queues_its_scan(
    mocker: MockerFixture, dock: CatalogDocks, machine: Path, catalog: Mock, served: dict[str, Any]
) -> None:
    """Map gives an unmapped root its folder: stored, handed to the cache, announced, and scanned; the file itself is
    not written.

    **Test steps:**

    * open a file with a skipped, unmapped root and map it to a folder
    * verify it returned true, the root is mapped, the mapping is stored and the skip gone, the cache was given three
      roots, the roots were announced changed, the root is scanned, and no ``.rehuco`` was written
    """
    serve_away(served)
    saves = mocker.patch("rehuco_core.rehuco_file.atomic_write_text")
    scan = mocker.patch.object(RootCatalog, "scan_root")
    dock.catalog.open_rehuco(REHUCO_PATH)
    dock.catalog.skip_roots([AWAY_ID])
    changed = mocker.MagicMock()
    dock.catalog.roots_changed.connect(changed)
    folder = TUTORIALS.parent / "away"

    assert dock.catalog.map_root(AWAY_ID, folder)

    assert dock.catalog.root_paths()[AWAY_ID] == folder
    assert dock.catalog.unmapped_root_ids() == frozenset()
    mapping = stored(machine).mapping(UUID(REHUCO_ID), AWAY_ID)
    assert mapping is not None
    assert mapping.path == folder
    assert not stored(machine).skipped(UUID(REHUCO_ID), AWAY_ID)
    assert [root.label for root in catalog.reconcile.call_args.args[0]] == ["tutorials", "packs", "away"]
    changed.assert_called_once_with()
    scan.assert_called_once_with(AWAY_ID)
    saves.assert_not_called()


@mark.parametrize(
    ("folder", "said"),
    [
        (TUTORIALS / "python", "is inside the root tutorials"),
        (TUTORIALS.parent, "contains the root"),
    ],
)
def test_mapping_a_root_inside_or_around_another_is_refused(
    dock: CatalogDocks, served: dict[str, Any], folder: Path, said: str
) -> None:
    """The folders must not nest, as when a root is added: nothing is stored and the reason is kept.

    **Test steps:**

    * open a file with an unmapped root and map it to a folder inside, then around, a mapped root
    * verify it returned false, said so, and the root is still unmapped
    """
    serve_away(served)
    dock.catalog.open_rehuco(REHUCO_PATH)

    assert not dock.catalog.map_root(AWAY_ID, folder)

    assert said in dock.catalog.save_error
    assert dock.catalog.unmapped_root_ids() == frozenset({AWAY_ID})


@mark.usefixtures("served")
def test_mapping_a_root_the_file_does_not_list_or_with_no_file_open_does_nothing(
    dock: CatalogDocks, machine: Path
) -> None:
    """Only a root of the open file can be mapped.

    **Test steps:**

    * map and skip a root with no file open, then map one the open file does not list
    * verify nothing was done and nothing was stored
    """
    assert not dock.catalog.map_root(AWAY_ID, TUTORIALS)
    assert not dock.catalog.skip_roots([AWAY_ID])
    assert dock.catalog.mapped_roots() == ()
    assert dock.catalog.unmapped_roots() == ()
    assert dock.catalog.unmapped_root_ids() == frozenset()
    assert dock.catalog.root_paths() == {}
    dock.catalog.open_rehuco(REHUCO_PATH)

    assert not dock.catalog.map_root(AWAY_ID, PACKS.parent / "other")

    assert str(AWAY_ID) not in (machine / MAPPINGS_FILE).read_text(encoding="utf-8")


def test_mappings_that_cannot_be_saved_are_reported_and_not_applied(
    mocker: MockerFixture, dock: CatalogDocks, served: dict[str, Any]
) -> None:
    """A failed write of the mappings file says so with the reason; a skip or a map that was not kept does not
    announce itself, and opening still works with what could be mapped.

    **Test steps:**

    * make saving the mappings fail and open a file whose roots are found on their own: it still opens with them
    * try to skip and to map a root
    * verify both return false with the reason
    """
    serve_away(served)
    mocker.patch.object(RootMappings, "save", side_effect=PermissionError("read-only folder"))
    assert dock.catalog.open_rehuco(REHUCO_PATH)

    assert len(dock.catalog.mapped_roots()) == 2
    assert not dock.catalog.skip_roots([AWAY_ID])
    assert dock.catalog.save_error == "Could not save the root mappings: read-only folder"
    dock.catalog.close_rehuco()
    dock.catalog.open_rehuco(REHUCO_PATH)
    assert not dock.catalog.map_root(AWAY_ID, TUTORIALS.parent / "away")
    assert dock.catalog.save_error == "Could not save the root mappings: read-only folder"


@mark.usefixtures("served")
def test_adding_a_root_names_it_by_location_and_maps_it_here(
    dock: CatalogDocks, machine: Path, saves: MagicMock, catalog: Mock
) -> None:
    """The file gets the folder's location, never its path; this machine's mapping gets the folder, and the cache
    follows.

    **Test steps:**

    * open a catalog and add a folder
    * verify the new row, the written file holds the location only, the mapping is stored, and the cache was given the
      three roots
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    folder = TUTORIALS.parent / "refs"

    row = dock.catalog.add_root(folder)

    assert row == 2
    written = json.loads(saves.call_args[0][1])["roots"][2]
    assert written["location"] == location_at(folder)
    assert set(written) == {"id", "label", "location"}
    mapping = stored(machine).mapping(UUID(REHUCO_ID), UUID(written["id"]))
    assert mapping is not None
    assert mapping.path == folder
    assert [root.path for root in catalog.reconcile.call_args.args[0]] == [TUTORIALS, PACKS, folder]


@mark.usefixtures("served")
@mark.parametrize(("label", "expected"), [("Mine", "Mine"), (None, "refs"), ("", "refs")])
def test_adding_a_root_labels_it_as_asked_or_by_its_folders_name(
    dock: CatalogDocks, saves: MagicMock, label: str | None, expected: str
) -> None:
    """The label given is the root's; none, or an empty one, is the folder's name.

    **Test steps:**

    * open a catalog and add a folder with a label, none, and an empty one
    * verify the label written for the new root
    """
    dock.catalog.open_rehuco(REHUCO_PATH)

    assert dock.catalog.add_root(TUTORIALS.parent / "refs", label) == 2

    assert json.loads(saves.call_args[0][1])["roots"][2]["label"] == expected


@mark.usefixtures("served")
def test_adding_a_root_that_cannot_be_added_says_why(dock: CatalogDocks) -> None:
    """Nothing is added with no file open, or for a folder around or inside a mapped root.

    **Test steps:**

    * add a folder with no file open
    * open a catalog and add a folder inside a root, and one around it
    * verify each returned none, and the reasons name the overlap
    """
    assert dock.catalog.add_root(TUTORIALS) is None
    dock.catalog.open_rehuco(REHUCO_PATH)

    assert dock.catalog.add_root(TUTORIALS / "python") is None
    assert "is inside the root tutorials" in dock.catalog.save_error
    assert dock.catalog.add_root(TUTORIALS.parent) is None
    assert "contains the root" in dock.catalog.save_error


def test_a_newer_file_takes_no_new_root(dock: CatalogDocks, served: dict[str, Any]) -> None:
    """A file written by a newer build is read-only, so a root is not added to it.

    **Test steps:**

    * open a file stamped with a newer format and add a folder
    * verify nothing was added
    """
    served["format_version"] = 99
    dock.catalog.open_rehuco(REHUCO_PATH)

    assert dock.catalog.add_root(TUTORIALS.parent / "other") is None


@mark.usefixtures("served")
def test_adding_the_location_a_root_already_has_is_refused_by_the_file(
    mocker: MockerFixture, dock: CatalogDocks
) -> None:
    """Two spellings of the folder that the overlap check does not relate -- here the location is the same while the
    mapped folder is not -- still stop at the file, whose refusal is the reason given.

    **Test steps:**

    * open a catalog, make the folder's location the first root's, and add a folder
    * verify it returned none and the reason is the file's
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    mocker.patch("rehuco_agent.rehuco.root_catalog.location_of", return_value=location_at(TUTORIALS))

    assert dock.catalog.add_root(TUTORIALS.parent / "elsewhere") is None

    assert dock.catalog.save_error == f"Already a root: {location_at(TUTORIALS)}"


@mark.usefixtures("served")
def test_a_file_changed_on_disk_since_it_was_read_is_not_overwritten_but_read_again(
    dock: CatalogDocks, on_disk: dict[Path, str], saves: MagicMock, caplog: LogCaptureFixture
) -> None:
    """Another machine's edit is never written over: the save is refused, the catalog shows what is on disk -- a root
    it added mapped, if this machine can find it -- and the reader is told to make the edit again.

    **Test steps:**

    * open a catalog, then change the file on disk under it: a root relabelled and a third one added
    * relabel a root here and commit
    * verify the commit returned false, nothing was written, the reason says the file changed, and the catalog now lists
      what is on disk with the new root mapped
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    file = dock.catalog.file
    assert file is not None
    late = {"id": str(AWAY_ID), "location": location_at(TUTORIALS.parent / "late"), "label": "late"}
    changed = {**HOME, "roots": [{**HOME["roots"][0], "label": "by another machine"}, HOME["roots"][1], late]}
    on_disk[REHUCO_PATH] = json.dumps(changed)
    file.relabel_root(0, "mine")

    with caplog.at_level(logging.WARNING):
        assert not dock.catalog.commit_roots()

    saves.assert_not_called()
    assert "changed on disk" in dock.catalog.save_error
    assert "make the edit again" in dock.catalog.save_error
    assert dock.catalog.file is not None
    assert [root.label for root in dock.catalog.file.roots] == ["by another machine", "packs", "late"]
    assert [root.label for root in dock.catalog.mapped_roots()] == ["by another machine", "packs", "late"]
    assert "changed on disk" in caplog.text


@mark.usefixtures("served")
def test_a_save_that_fails_reads_the_file_back_and_says_why(dock: CatalogDocks, saves: MagicMock) -> None:
    """After a write fails the edit is gone from the catalog, which is the file on disk again.

    **Test steps:**

    * open a catalog, make the write fail, relabel a root and commit
    * verify the commit failed with the reason, and the old label is back
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    saves.side_effect = PermissionError("read-only folder")
    file = dock.catalog.file
    assert file is not None
    file.relabel_root(0, "mine")

    assert not dock.catalog.commit_roots()

    assert dock.catalog.save_error.startswith("Could not save")
    assert "read-only folder" in dock.catalog.save_error
    assert [root.label for root in dock.catalog.mapped_roots()] == ["tutorials", "packs"]


def test_removing_a_root_forgets_where_this_machine_had_it(
    dock: CatalogDocks, machine: Path, saves: MagicMock, served: dict[str, Any], queue: TaskQueue
) -> None:
    """A root that is gone from the file leaves nothing behind in the mappings, mapped or not.

    **Test steps:**

    * open a file with an unmapped root; remove it, then a mapped one
    * verify each removal succeeded and neither root has a mapping or a skip left
    """
    serve_away(served)
    dock.catalog.open_rehuco(REHUCO_PATH)
    dock.catalog.skip_roots([AWAY_ID])

    assert dock.catalog.remove_root(2)
    assert dock.catalog.remove_root(0)

    saves.assert_called()
    kept = stored(machine)
    assert kept.mapping(UUID(REHUCO_ID), AWAY_ID) is None
    assert not kept.skipped(UUID(REHUCO_ID), AWAY_ID)
    assert kept.mapping(UUID(REHUCO_ID), UUID(ROOT_IDS[0])) is None
    assert kept.mapping(UUID(REHUCO_ID), UUID(ROOT_IDS[1])) is not None
    queue.wait_until_idle()


@mark.parametrize("opening", ["open", "new"])
def test_mappings_that_cannot_be_read_fail_the_open(
    dock: CatalogDocks, machine: Path, served: dict[str, Any], tmp_path: Path, opening: str
) -> None:
    """A catalog is not opened over mappings nobody can read: guessing would map nothing and then write over them.

    **Test steps:**

    * put a file that is not JSON where the mappings belong
    * open a catalog, or create one
    * verify it failed and the load error names the mappings file
    """
    del served
    (machine / MAPPINGS_FILE).write_text("not json", encoding="utf-8")

    opened = (
        dock.catalog.open_rehuco(REHUCO_PATH) if opening == "open" else dock.catalog.new_rehuco(tmp_path / "n.rehuco")
    )

    assert not opened
    assert "root mappings" in dock.catalog.load_error
    assert str(machine / MAPPINGS_FILE) in dock.catalog.load_error
