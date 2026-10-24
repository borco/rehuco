"""Tests for this machine's mappings of a catalog's roots (#514).

Real files in ``tmp_path``; the storage detector is replaced, since what a folder lives on is the drive table's to say
and is tested with it.
"""

import json
from pathlib import Path
from typing import Final
from uuid import UUID, uuid4

from pytest import raises
from pytest_mock import MockerFixture
from rehuco_core.rehuco_file import RehucoFile, RootStorage
from rehuco_core.root_mappings import MappedRoot, RootMapping, RootMappings, RootMappingsError

MODULE: Final = "rehuco_core.root_mappings"
REHUCO_ID: Final = UUID("6f1c5e0a-0000-4000-8000-000000000001")
ROOT_ID: Final = UUID("a41b9c3d-0000-4000-8000-000000000002")


def catalog_with_two_roots() -> RehucoFile:
    """A catalog of two roots, built in memory.

    :returns: the file.
    """
    file = RehucoFile(
        {"format_version": 3, "id": str(REHUCO_ID), "roots": []},
    )
    file.add_root("//nas/data/Tutorials")
    file.add_root("//ryzen/d/Downloads")
    return file


def test_a_file_that_does_not_exist_is_an_empty_one(tmp_path: Path) -> None:
    """A machine that never mapped anything has no file.

    **Test steps:**

    * load a path with nothing there
    * verify no root is mapped or skipped
    """
    mappings = RootMappings.load(tmp_path / "root-mappings.json")

    assert mappings.mapping(REHUCO_ID, ROOT_ID) is None
    assert not mappings.skipped(REHUCO_ID, ROOT_ID)


def test_a_mapping_is_saved_and_read_back(tmp_path: Path, mocker: MockerFixture) -> None:
    """A mapping records the folder and the storage detected for it, and survives a reload.

    **Test steps:**

    * map a root, with the detector saying network, and save into a folder that does not exist yet
    * load the file again
    * verify the folder and the storage come back, and the file holds the shape documented
    """
    mocker.patch(f"{MODULE}.storage_of", return_value=RootStorage.NETWORK)
    where = tmp_path / "data" / "root-mappings.json"
    mappings = RootMappings.load(where)

    mapping = mappings.map(REHUCO_ID, ROOT_ID, Path("U:/Tutorials"))
    mappings.save()

    assert mapping == RootMapping(Path("U:/Tutorials"), RootStorage.NETWORK)
    assert RootMappings.load(where).mapping(REHUCO_ID, ROOT_ID) == mapping
    assert json.loads(where.read_text(encoding="utf-8")) == {
        "format_version": 1,
        "rehucos": {str(REHUCO_ID): {str(ROOT_ID): {"path": str(Path("U:/Tutorials")), "storage": "network"}}},
    }


def test_a_skip_is_remembered_and_mapping_replaces_it(tmp_path: Path, mocker: MockerFixture) -> None:
    """A skipped root is no mapping, and mapping it later clears the skip.

    **Test steps:**

    * skip a root and save and reload
    * verify it is skipped and unmapped
    * map it
    * verify it is mapped and no longer skipped
    """
    mocker.patch(f"{MODULE}.storage_of", return_value=RootStorage.LOCAL)
    where = tmp_path / "root-mappings.json"
    mappings = RootMappings.load(where)
    mappings.skip(REHUCO_ID, ROOT_ID)
    mappings.save()

    reloaded = RootMappings.load(where)
    assert reloaded.skipped(REHUCO_ID, ROOT_ID)
    assert reloaded.mapping(REHUCO_ID, ROOT_ID) is None

    reloaded.map(REHUCO_ID, ROOT_ID, tmp_path)
    assert reloaded.mapping(REHUCO_ID, ROOT_ID) is not None
    assert not reloaded.skipped(REHUCO_ID, ROOT_ID)


def test_skipping_a_mapped_root_drops_the_mapping(mocker: MockerFixture, tmp_path: Path) -> None:
    """Skipping is the latest word: the earlier mapping goes.

    **Test steps:**

    * map a root and then skip it
    * verify it has no mapping and is skipped
    """
    mocker.patch(f"{MODULE}.storage_of", return_value=RootStorage.LOCAL)
    mappings = RootMappings.load(tmp_path / "root-mappings.json")
    mappings.map(REHUCO_ID, ROOT_ID, tmp_path)

    mappings.skip(REHUCO_ID, ROOT_ID)

    assert mappings.mapping(REHUCO_ID, ROOT_ID) is None
    assert mappings.skipped(REHUCO_ID, ROOT_ID)


def test_forgetting_a_root_drops_everything_about_it(mocker: MockerFixture, tmp_path: Path) -> None:
    """A removed root leaves nothing behind, and forgetting one never known is harmless.

    **Test steps:**

    * map a root, forget it, and forget another root
    * verify the first has no mapping and is not skipped
    """
    mocker.patch(f"{MODULE}.storage_of", return_value=RootStorage.LOCAL)
    mappings = RootMappings.load(tmp_path / "root-mappings.json")
    mappings.map(REHUCO_ID, ROOT_ID, tmp_path)

    mappings.forget(REHUCO_ID, ROOT_ID)
    mappings.forget(REHUCO_ID, uuid4())

    assert mappings.mapping(REHUCO_ID, ROOT_ID) is None
    assert not mappings.skipped(REHUCO_ID, ROOT_ID)


def test_reading_changes_nothing(tmp_path: Path) -> None:
    """Asking about a root nobody mapped does not create entries.

    **Test steps:**

    * ask about a mapping, a skip and the mapped roots of a catalog
    * save
    * verify the file holds only the version stamp
    """
    where = tmp_path / "root-mappings.json"
    mappings = RootMappings.load(where)

    mappings.mapping(REHUCO_ID, ROOT_ID)
    mappings.skipped(REHUCO_ID, ROOT_ID)
    mappings.mapped(catalog_with_two_roots())
    mappings.save()

    assert json.loads(where.read_text(encoding="utf-8")) == {"format_version": 1}


def test_a_catalog_splits_into_mapped_and_unmapped_roots(tmp_path: Path, mocker: MockerFixture) -> None:
    """The roots this machine reaches carry their folder and storage; the others are the shared roots alone.

    **Test steps:**

    * map only the second root of a two-root catalog
    * verify ``mapped`` holds that root with its folder and label, and ``unmapped`` the first, in display order
    """
    mocker.patch(f"{MODULE}.storage_of", return_value=RootStorage.REMOVABLE)
    file = catalog_with_two_roots()
    first, second = file.roots
    mappings = RootMappings.load(tmp_path / "root-mappings.json")
    mappings.map(file.rehuco_id, second.root_id, tmp_path)

    assert mappings.mapped(file) == (
        MappedRoot(second.root_id, "Downloads", "//ryzen/d/Downloads", tmp_path, RootStorage.REMOVABLE),
    )
    assert mappings.unmapped(file) == (first,)


def test_only_removable_media_are_removable() -> None:
    """A removable drive and a compact disk can be taken away; a local disk and a share cannot.

    **Test steps:**

    * build a mapped root of each storage
    * verify ``removable`` is true for the removable drive and the disk only
    """
    states = {storage: MappedRoot(ROOT_ID, "x", "//m/x", Path("x"), storage).removable for storage in RootStorage}

    assert states == {
        RootStorage.LOCAL: False,
        RootStorage.NETWORK: False,
        RootStorage.REMOVABLE: True,
        RootStorage.COMPACT_DISK: True,
    }


def test_a_malformed_entry_reads_as_unmapped(tmp_path: Path) -> None:
    """An entry with no usable path or an unknown storage is not a mapping, and does not break the others.

    **Test steps:**

    * write a file with entries lacking a path, with an unknown storage, with a non-object, and a catalog that
      is not an object
    * verify none maps, and mapping one replaces the malformed pieces
    """
    where = tmp_path / "root-mappings.json"
    other = uuid4()
    where.write_text(
        json.dumps(
            {
                "rehucos": {
                    str(REHUCO_ID): {
                        str(ROOT_ID): {"storage": "local"},
                        str(uuid4()): {"path": "x", "storage": "floppy"},
                        str(uuid4()): "oops",
                    },
                    str(other): "oops",
                }
            }
        ),
        encoding="utf-8",
    )
    mappings = RootMappings.load(where)

    assert mappings.mapping(REHUCO_ID, ROOT_ID) is None
    assert mappings.mapping(other, ROOT_ID) is None
    mappings.skip(other, ROOT_ID)
    assert mappings.skipped(other, ROOT_ID)


def test_a_rehucos_value_that_is_no_object_is_replaced(tmp_path: Path) -> None:
    """A file whose ``rehucos`` is not an object loses only that.

    **Test steps:**

    * load a file whose ``rehucos`` is a list and skip a root
    * verify the skip is remembered
    """
    where = tmp_path / "root-mappings.json"
    where.write_text(json.dumps({"rehucos": []}), encoding="utf-8")
    mappings = RootMappings.load(where)

    mappings.skip(REHUCO_ID, ROOT_ID)

    assert mappings.skipped(REHUCO_ID, ROOT_ID)


def test_what_this_build_does_not_know_is_carried(tmp_path: Path, mocker: MockerFixture) -> None:
    """An unknown key at the top and on an entry come back out of a save.

    **Test steps:**

    * load a file with an unknown top-level key and an unknown key on an entry
    * map that root again, save and read the file
    * verify both unknown keys are still there
    """
    mocker.patch(f"{MODULE}.storage_of", return_value=RootStorage.LOCAL)
    where = tmp_path / "root-mappings.json"
    where.write_text(
        json.dumps({"extra": 1, "rehucos": {str(REHUCO_ID): {str(ROOT_ID): {"note": "keep"}}}}), encoding="utf-8"
    )
    mappings = RootMappings.load(where)

    mappings.map(REHUCO_ID, ROOT_ID, tmp_path)
    mappings.save()

    saved = json.loads(where.read_text(encoding="utf-8"))
    assert saved["extra"] == 1
    assert saved["rehucos"][str(REHUCO_ID)][str(ROOT_ID)]["note"] == "keep"


def test_a_file_this_build_cannot_read_is_refused(tmp_path: Path) -> None:
    """Not text, not JSON, not an object, and a newer build's file are each refused with the file named.

    **Test steps:**

    * load a binary file, a broken one, a JSON list and a file stamped version 2
    * verify each raises ``RootMappingsError``
    """
    where = tmp_path / "root-mappings.json"
    for content in (b"\xff\xfe\x00", b"{", b"[]", b'{"format_version": 2}'):
        where.write_bytes(content)
        with raises(RootMappingsError):
            RootMappings.load(where)


def test_a_stamp_that_is_not_a_number_is_not_newer(tmp_path: Path) -> None:
    """Only a version above this build's refuses; a malformed stamp is rewritten by the next save.

    **Test steps:**

    * load a file stamped ``"x"`` and save it
    * verify it loads and the stamp is repaired
    """
    where = tmp_path / "root-mappings.json"
    where.write_text('{"format_version": "x"}', encoding="utf-8")

    RootMappings.load(where).save()

    assert json.loads(where.read_text(encoding="utf-8")) == {"format_version": 1}
