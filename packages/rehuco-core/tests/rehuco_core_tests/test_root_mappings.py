"""Tests for this machine's mappings of roots, keyed by root id (#514, #577).

Real files in ``tmp_path``; the storage detector is replaced, since what a folder lives on is the drive table's to say
and is tested with it.
"""

import json
from pathlib import Path
from typing import Final
from uuid import UUID, uuid4

from pytest import raises
from pytest_mock import MockerFixture
from rehuco_core import RootOverlap
from rehuco_core.rehuco_file import RehucoFile, RootStorage
from rehuco_core.root_mappings import (
    SET_ASIDE_FILE_NAME,
    MappedRoot,
    RootMapping,
    RootMappings,
    RootMappingsError,
)

from rehuco_core_tests.mapped_roots import new_catalog

MODULE: Final = "rehuco_core.root_mappings"
ROOT_ID: Final = UUID("a41b9c3d-0000-4000-8000-000000000002")


def catalog_with_two_roots() -> RehucoFile:
    """A catalog of two roots, never saved.

    :returns: the file.
    """
    file = new_catalog()
    file.add_root("//nas/data/Tutorials")
    file.add_root("//ryzen/d/Downloads")
    return file


def saved_catalog(folder: Path, name: str, *locations: str) -> RehucoFile:
    """A catalog saved in ``folder`` with a root at each location, read back from disk.

    :param folder: where the ``.rehuco`` and its root files go.
    :param name: the ``.rehuco``'s stem.
    :param locations: the roots' locations.
    :returns: the file as loaded.
    """
    file = RehucoFile.new()
    file.save(folder / f"{name}.rehuco")
    for location in locations:
        file.add_root(location)
    file.save()
    return RehucoFile.load(folder / f"{name}.rehuco")


def test_a_file_that_does_not_exist_is_an_empty_one(tmp_path: Path) -> None:
    """A machine that never mapped anything has no file.

    **Test steps:**

    * load a path with nothing there
    * verify no root is mapped or skipped
    """
    mappings = RootMappings.load(tmp_path / "root-mappings.json")

    assert mappings.mapping(ROOT_ID) is None
    assert not mappings.skipped(ROOT_ID)


def test_a_mapping_is_saved_and_read_back(tmp_path: Path, mocker: MockerFixture) -> None:
    """A mapping records the folder and the storage detected for it, under the root's id, and survives a reload.

    **Test steps:**

    * map a root, with the detector saying network, and save into a folder that does not exist yet
    * load the file again
    * verify the folder and the storage come back, and the file holds the shape documented
    """
    mocker.patch(f"{MODULE}.storage_of", return_value=RootStorage.NETWORK)
    where = tmp_path / "data" / "root-mappings.json"
    mappings = RootMappings.load(where)

    mapping = mappings.map(ROOT_ID, Path("U:/Tutorials"))
    mappings.save()

    assert mapping == RootMapping(Path("U:/Tutorials"), RootStorage.NETWORK)
    assert RootMappings.load(where).mapping(ROOT_ID) == mapping
    assert json.loads(where.read_text(encoding="utf-8")) == {
        "format_version": 2,
        "roots": {str(ROOT_ID): {"path": str(Path("U:/Tutorials")), "storage": "network"}},
    }


def test_a_root_two_catalogs_list_is_mapped_once_for_both(tmp_path: Path, mocker: MockerFixture) -> None:
    """A root's id is its ``.rehuroot``'s, so a second catalog listing the same file finds it already mapped.

    **Test steps:**

    * save a catalog with one root, and a second catalog whose reference names the same root file
    * map the root once, through the first catalog
    * verify both catalogs reach it, at the one folder
    """
    mocker.patch(f"{MODULE}.storage_of", return_value=RootStorage.LOCAL)
    first = saved_catalog(tmp_path, "first", "//nas/data/Tutorials")
    (tmp_path / "second.rehuco").write_text(
        json.dumps({"format_version": 4, "id": str(uuid4()), "roots": [{"file": "Tutorials.rehuroot"}]}),
        encoding="utf-8",
    )
    second = RehucoFile.load(tmp_path / "second.rehuco")
    mappings = RootMappings.load(tmp_path / "root-mappings.json")

    mappings.map(first.roots[0].root_id, tmp_path / "tutorials")

    assert [root.path for root in mappings.mapped(first)] == [tmp_path / "tutorials"]
    assert mappings.mapped(second) == mappings.mapped(first)


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
    mappings.skip(ROOT_ID)
    mappings.save()

    reloaded = RootMappings.load(where)
    assert reloaded.skipped(ROOT_ID)
    assert reloaded.mapping(ROOT_ID) is None

    reloaded.map(ROOT_ID, tmp_path)
    assert reloaded.mapping(ROOT_ID) is not None
    assert not reloaded.skipped(ROOT_ID)


def test_skipping_a_mapped_root_drops_the_mapping(mocker: MockerFixture, tmp_path: Path) -> None:
    """Skipping is the latest word: the earlier mapping goes.

    **Test steps:**

    * map a root and then skip it
    * verify it has no mapping and is skipped
    """
    mocker.patch(f"{MODULE}.storage_of", return_value=RootStorage.LOCAL)
    mappings = RootMappings.load(tmp_path / "root-mappings.json")
    mappings.map(ROOT_ID, tmp_path)

    mappings.skip(ROOT_ID)

    assert mappings.mapping(ROOT_ID) is None
    assert mappings.skipped(ROOT_ID)


def test_reading_changes_nothing(tmp_path: Path) -> None:
    """Asking about a root nobody mapped does not create entries.

    **Test steps:**

    * ask about a mapping, a skip and the mapped roots of a catalog
    * save
    * verify the file holds only the version stamp
    """
    where = tmp_path / "root-mappings.json"
    mappings = RootMappings.load(where)

    mappings.mapping(ROOT_ID)
    mappings.skipped(ROOT_ID)
    mappings.mapped(catalog_with_two_roots())
    mappings.save()

    assert json.loads(where.read_text(encoding="utf-8")) == {"format_version": 2}


def test_a_catalog_splits_into_mapped_and_unmapped_roots(tmp_path: Path, mocker: MockerFixture) -> None:
    """The roots this machine reaches carry their folder, storage and root file; the others are the shared roots alone.

    **Test steps:**

    * map only the second root of a two-root catalog
    * verify ``mapped`` holds that root with its folder, label and root file, and ``unmapped`` the first, in display
      order
    """
    mocker.patch(f"{MODULE}.storage_of", return_value=RootStorage.REMOVABLE)
    file = catalog_with_two_roots()
    first, second = file.roots
    mappings = RootMappings.load(tmp_path / "root-mappings.json")
    mappings.map(second.root_id, tmp_path)

    assert mappings.mapped(file) == (
        MappedRoot(second.root_id, "Downloads", "//ryzen/d/Downloads", tmp_path, RootStorage.REMOVABLE),
    )
    assert mappings.mapped(file)[0].file == second.file
    assert mappings.unmapped(file) == (first,)


def test_an_unreadable_root_is_neither_mapped_nor_asked_about(tmp_path: Path, mocker: MockerFixture) -> None:
    """A root whose file cannot be read has nothing to map: it is not reached, and not offered for mapping either.

    **Test steps:**

    * save a two-root catalog, map both roots, then delete the first root's file and reload
    * verify only the second is mapped, and neither is unmapped
    """
    mocker.patch(f"{MODULE}.storage_of", return_value=RootStorage.LOCAL)
    file = saved_catalog(tmp_path, "home", "//nas/data/Tutorials", "//nas/data/Packs")
    mappings = RootMappings.load(tmp_path / "root-mappings.json")
    for root in file.roots:
        mappings.map(root.root_id, tmp_path / root.label)
    (tmp_path / "Tutorials.rehuroot").unlink()

    reloaded = RehucoFile.load(tmp_path / "home.rehuco")

    assert [root.label for root in mappings.mapped(reloaded)] == ["Packs"]
    assert not mappings.unmapped(reloaded)


def test_overlap_is_found_across_a_catalogs_root_files(tmp_path: Path, mocker: MockerFixture) -> None:
    """Roots in files of their own still overlap as before: one mapped inside another is found.

    **Test steps:**

    * save a catalog of two roots, map the second inside the first
    * verify the mapped roots overlap, the outer enclosing the inner
    """
    mocker.patch(f"{MODULE}.storage_of", return_value=RootStorage.LOCAL)
    file = saved_catalog(tmp_path, "home", "//nas/data/Tutorials", "//nas/data/Tutorials/Krita")
    mappings = RootMappings.load(tmp_path / "root-mappings.json")
    outer, inner = file.roots
    mappings.map(outer.root_id, tmp_path / "Tutorials")
    mappings.map(inner.root_id, tmp_path / "Tutorials" / "Krita")

    (overlap,) = RootOverlap.among(mappings.mapped(file))

    assert (overlap.root.root_id, overlap.other, overlap.encloses) == (
        outer.root_id,
        tmp_path / "Tutorials" / "Krita",
        True,
    )


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

    * write a file with entries lacking a path, with an unknown storage, and one that is not an object
    * verify none maps, and skipping the last replaces it
    """
    where = tmp_path / "root-mappings.json"
    other = uuid4()
    where.write_text(
        json.dumps(
            {
                "format_version": 2,
                "roots": {
                    str(ROOT_ID): {"storage": "local"},
                    str(uuid4()): {"path": "x", "storage": "floppy"},
                    str(other): "oops",
                },
            }
        ),
        encoding="utf-8",
    )
    mappings = RootMappings.load(where)

    assert mappings.mapping(ROOT_ID) is None
    assert mappings.mapping(other) is None
    mappings.skip(other)
    assert mappings.skipped(other)


def test_a_roots_value_that_is_no_object_is_replaced(tmp_path: Path) -> None:
    """A file whose ``roots`` is not an object loses only that.

    **Test steps:**

    * load a file whose ``roots`` is a list and skip a root
    * verify the skip is remembered
    """
    where = tmp_path / "root-mappings.json"
    where.write_text(json.dumps({"format_version": 2, "roots": []}), encoding="utf-8")
    mappings = RootMappings.load(where)

    mappings.skip(ROOT_ID)

    assert mappings.skipped(ROOT_ID)


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
        json.dumps({"format_version": 2, "extra": 1, "roots": {str(ROOT_ID): {"note": "keep"}}}), encoding="utf-8"
    )
    mappings = RootMappings.load(where)

    mappings.map(ROOT_ID, tmp_path)
    mappings.save()

    saved = json.loads(where.read_text(encoding="utf-8"))
    assert saved["extra"] == 1
    assert saved["roots"][str(ROOT_ID)]["note"] == "keep"


def test_a_format_1_file_is_set_aside_and_read_as_empty(tmp_path: Path) -> None:
    """Mappings keyed by catalog are not carried forward: the file is moved aside, kept, and nothing is mapped.

    **Test steps:**

    * write a format-1 file mapping a root under a catalog's id, and load it
    * verify the root is unmapped, the file is gone from its place and kept, byte for byte, under the set-aside name
    * save, and verify a format-2 file takes its place
    """
    where = tmp_path / "root-mappings.json"
    old = json.dumps(
        {"format_version": 1, "rehucos": {str(uuid4()): {str(ROOT_ID): {"path": "U:/x", "storage": "local"}}}}
    )
    where.write_text(old, encoding="utf-8")

    mappings = RootMappings.load(where)

    assert mappings.mapping(ROOT_ID) is None
    assert not where.exists()
    assert (tmp_path / SET_ASIDE_FILE_NAME).read_text(encoding="utf-8") == old
    mappings.save()
    assert json.loads(where.read_text(encoding="utf-8")) == {"format_version": 2}


def test_a_file_this_build_cannot_read_is_refused(tmp_path: Path) -> None:
    """Not text, not JSON, not an object, and a newer build's file are each refused with the file named.

    **Test steps:**

    * load a binary file, a broken one, a JSON list and a file stamped version 3
    * verify each raises ``RootMappingsError``
    """
    where = tmp_path / "root-mappings.json"
    for content in (b"\xff\xfe\x00", b"{", b"[]", b'{"format_version": 3}'):
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

    assert json.loads(where.read_text(encoding="utf-8")) == {"format_version": 2}
