"""Tests for the ``.rehuco`` file: format 4's references to ``.rehuroot`` files, round-trip, root operations and the
save's changed-on-disk check (#371, #514, #577).

Every test works on real files in ``tmp_path``: a ``.rehuco`` reads the root files it names, so the pair is what is
under test.
"""

import json
from pathlib import Path
from typing import Any, Final
from uuid import UUID

import pytest
from pytest import fixture, mark, param
from pytest_mock import MockerFixture
from rehuco_core import (
    CURRENT_REHUCO_VERSION,
    DEFAULT_LAYOUTS,
    LockReasonKind,
    RehucoChangedError,
    RehucoFile,
    RehucoFileError,
    RehucoRoot,
    RehurootChangedError,
)

REHUCO_ID: Final = "6f1c5e0a-1b2c-4d3e-8f90-a1b2c3d4e5f6"

ROOT_IDS: Final = (
    "a41b9c3d-0000-4000-8000-000000000001",
    "a41b9c3d-0000-4000-8000-000000000002",
    "a41b9c3d-0000-4000-8000-000000000003",
)

ROOTS: Final = (
    ("tutorials.rehuroot", ROOT_IDS[0], "tutorials", "//nas/data/tutorials"),
    ("discs.rehuroot", ROOT_IDS[1], "discs", "//ryzen-5600/e/discs"),
    ("shared/refs.rehuroot", ROOT_IDS[2], "refs", "//nas/data/refs"),
)
"""Each of ``HOME``'s roots: its file, relative to the ``.rehuco``, its id, label and location."""

HOME: Final = {
    "format_version": 4,
    "id": REHUCO_ID,
    "some_future_key": {"nested": [1, 2, 3]},
    "roots": [
        {"file": "tutorials.rehuroot"},
        {"file": "discs.rehuroot", "some_future_reference_key": 7},
        {"file": "shared/refs.rehuroot"},
    ],
}

V1_HOME: Final = {
    "format_version": 1,
    "id": REHUCO_ID,
    "roots": [{"id": ROOT_IDS[0], "path": "D:/tutorials", "label": "tutorials", "removable": False}],
}

V2_HOME: Final = {
    "format_version": 2,
    "id": REHUCO_ID,
    "roots": [{"id": ROOT_IDS[0], "path": "D:/tutorials", "label": "tutorials", "storage": "local"}],
}

V3_HOME: Final = {
    "format_version": 3,
    "id": REHUCO_ID,
    "roots": [{"id": ROOT_IDS[0], "label": "tutorials", "location": "//nas/data/tutorials"}],
}


def write_json(path: Path, data: Any) -> Path:
    """Write ``data`` as JSON, making the folder.

    :param path: the file.
    :param data: what to write.
    :returns: the file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def root_data(root_id: str, label: str, location: str) -> dict[str, Any]:
    """A ``.rehuroot``'s content.

    :param root_id: its id.
    :param label: its label.
    :param location: its location.
    :returns: the object.
    """
    return {"format_version": 1, "id": root_id, "label": label, "location": location, "layouts": {"*": "*"}}


def write_home(folder: Path, data: Any = None) -> Path:
    """Write ``HOME``'s root files and a ``.rehuco`` holding ``data`` into ``folder``.

    :param folder: where to write them.
    :param data: the ``.rehuco``'s content; ``None`` is ``HOME``.
    :returns: the ``.rehuco``.
    """
    for file, root_id, label, location in ROOTS:
        write_json(folder / file, root_data(root_id, label, location))
    return write_json(folder / "home.rehuco", HOME if data is None else data)


def read_json(path: Path) -> Any:
    """A JSON file, parsed.

    :param path: the file.
    :returns: its content.
    """
    return json.loads(path.read_text(encoding="utf-8"))


def labels(rehuco: RehucoFile) -> list[str]:
    """The file's root labels, in row order.

    :param rehuco: the file.
    :returns: one label per root.
    """
    return [root.label for root in rehuco.roots]


@fixture
def home(tmp_path: Path) -> RehucoFile:
    """A loaded copy of ``HOME``: three roots, one in a subfolder, an unknown top-level key and an unknown reference
    key.

    :param tmp_path: pytest's temporary directory.
    :returns: the loaded file.
    """
    return RehucoFile.load(write_home(tmp_path))


# region Load and save


def test_load_reads_the_rehuco_id_and_each_root_file(tmp_path: Path, home: RehucoFile) -> None:
    """A loaded file exposes its rehuco id, path and version, and each root as its ``.rehuroot`` says.

    **Test steps:**

    * load ``HOME``
    * verify the id, path, version and count
    * verify every root's id, label, location, layouts, file and that it is readable
    """
    assert home.rehuco_id == UUID(REHUCO_ID)
    assert home.path == tmp_path / "home.rehuco"
    assert home.format_version == CURRENT_REHUCO_VERSION == 4
    assert home.lock_reason is None
    assert home.count == 3
    assert home.roots == tuple(
        RehucoRoot(UUID(root_id), label, location, file=tmp_path / file) for file, root_id, label, location in ROOTS
    )
    assert all(root.readable and dict(root.layouts) == dict(DEFAULT_LAYOUTS) for root in home.roots)


def test_round_trip_is_lossless_and_canonical(tmp_path: Path, home: RehucoFile) -> None:
    """Saving an unedited file writes back what was read, unknown keys included, in canonical key order, and leaves
    the root files alone.

    **Test steps:**

    * load ``HOME`` and save it
    * verify the file equals ``HOME``: the unknown top-level key and the unknown reference key carried as found
    * verify the key order: ``format_version``, ``id``, the unknown key, ``roots`` last
    * verify a root file's text is unchanged
    """
    before = (tmp_path / "discs.rehuroot").read_text(encoding="utf-8")

    home.save()

    payload = read_json(tmp_path / "home.rehuco")
    assert payload == HOME
    assert list(payload) == ["format_version", "id", "some_future_key", "roots"]
    assert (tmp_path / "home.rehuco").read_text(encoding="utf-8").endswith("}\n")
    assert (tmp_path / "discs.rehuroot").read_text(encoding="utf-8") == before


def test_a_save_elsewhere_names_each_root_file_from_there(tmp_path: Path, home: RehucoFile) -> None:
    """A reference is relative to the ``.rehuco``, so saving it to another folder respells every reference, and the
    copy reads the same roots.

    **Test steps:**

    * save ``HOME`` into a subfolder
    * verify each reference climbs out of it, with ``/`` separators
    * load the copy and verify it reads the same roots
    """
    elsewhere = tmp_path / "catalogs" / "copy.rehuco"
    elsewhere.parent.mkdir()

    home.save(elsewhere)

    assert [entry["file"] for entry in read_json(elsewhere)["roots"]] == [
        "../tutorials.rehuroot",
        "../discs.rehuroot",
        "../shared/refs.rehuroot",
    ]
    assert RehucoFile.load(elsewhere).roots == home.roots


def test_a_root_file_on_another_drive_is_named_whole(mocker: MockerFixture, tmp_path: Path, home: RehucoFile) -> None:
    """Where no relative path exists -- the root file on another drive -- the reference names it whole.

    **Test steps:**

    * make the relative path fail as it does across Windows drives
    * save, and verify each reference is the root file's whole path spelled with ``/``
    """
    mocker.patch("rehuco_core.rehuco_file.os.path.relpath", side_effect=ValueError("path is on mount 'D:'"))

    home.save()

    assert [entry["file"] for entry in read_json(tmp_path / "home.rehuco")["roots"]] == [
        str(tmp_path / file).replace("\\", "/") for file, *_ in ROOTS
    ]


def test_new_file_has_a_fresh_id_and_no_roots_until_saved(tmp_path: Path) -> None:
    """``RehucoFile.new`` mints a uuid4 rehuco id, holds no roots and no path, and takes the path of its first
    save.

    **Test steps:**

    * create two new files
    * verify each id is a version-4 UUID and the two differ, with no roots and no path
    * save one and verify the file and that ``path`` is now set
    """
    first = RehucoFile.new()
    second = RehucoFile.new()
    assert first.rehuco_id.version == 4
    assert first.rehuco_id != second.rehuco_id
    assert first.count == 0
    assert first.path is None

    first.save(tmp_path / "home.rehuco")

    assert read_json(tmp_path / "home.rehuco") == {
        "format_version": CURRENT_REHUCO_VERSION,
        "id": str(first.rehuco_id),
        "roots": [],
    }
    assert first.path == tmp_path / "home.rehuco"


def test_save_without_a_path_is_refused(mocker: MockerFixture) -> None:
    """A never-saved file needs a path to save to.

    **Test steps:**

    * save a new file with no path and verify ``ValueError`` and no write
    """
    mock_write = mocker.patch("rehuco_core.rehuco_file.atomic_write_text")
    with pytest.raises(ValueError, match="no path"):
        RehucoFile.new().save()
    mock_write.assert_not_called()


@mark.parametrize(
    "data, match",
    [
        param(V1_HOME, "paths rather than locations", id="v1"),
        param({key: value for key, value in V1_HOME.items() if key != "format_version"}, "paths", id="unstamped"),
        param(V2_HOME, "paths rather than locations", id="v2"),
        param({**V1_HOME, "roots": {}}, "paths", id="v1-roots-not-a-list"),
        param({**V1_HOME, "roots": ["D:/x"]}, "paths", id="v1-root-not-an-object"),
        param(V3_HOME, "lists its roots inline", id="v3"),
    ],
)
def test_an_older_file_is_refused_with_its_path(tmp_path: Path, data: dict[str, Any], match: str) -> None:
    """A file from before roots were files of their own is not carried forward: it says to make the catalog again.

    **Test steps:**

    * load a v1, an unstamped, a v2 and a v3 file, and v1 files whose roots are not a list or not objects
    * verify ``RehucoFileError`` saying an older build made it, ending in the file's path
    """
    path = write_json(tmp_path / "home.rehuco", data)
    with pytest.raises(RehucoFileError, match="older build") as raised:
        RehucoFile.load(path)
    assert match in str(raised.value)
    assert str(raised.value).endswith(str(path))


def test_missing_roots_reads_as_none(tmp_path: Path) -> None:
    """A file with no ``roots`` key reads as one with no roots, and saves the empty list.

    **Test steps:**

    * load a file holding only a stamp and an id
    * verify no roots, and ``roots: []`` once saved
    """
    path = write_json(tmp_path / "home.rehuco", {"format_version": 4, "id": REHUCO_ID})
    rehuco = RehucoFile.load(path)
    assert rehuco.count == 0
    rehuco.save()
    assert read_json(path)["roots"] == []


def test_newer_file_loads_read_only_and_refuses_to_save(tmp_path: Path) -> None:
    """A file stamped newer than this build loads, but read-only, and a save is refused.

    **Test steps:**

    * load ``HOME`` stamped one version past this build's
    * verify the lock reason, and that a save raises without writing
    """
    path = write_home(tmp_path, {**HOME, "format_version": CURRENT_REHUCO_VERSION + 1})
    before = path.read_text(encoding="utf-8")
    rehuco = RehucoFile.load(path)

    reason = rehuco.lock_reason
    assert reason is not None
    assert reason.kind is LockReasonKind.NEWER_FORMAT
    with pytest.raises(ValueError, match="read-only"):
        rehuco.save()
    assert path.read_text(encoding="utf-8") == before


def test_write_failure_propagates(mocker: MockerFixture, home: RehucoFile) -> None:
    """A write that fails raises to the caller.

    **Test steps:**

    * make ``atomic_write_text`` raise ``OSError``, and move a root
    * verify the save raises it
    """
    mocker.patch("rehuco_core.rehuco_file.atomic_write_text", side_effect=OSError("disk full"))
    home.move_to_top(2)
    with pytest.raises(OSError, match="disk full"):
        home.save()


@mark.parametrize(
    "content, match",
    [
        param(b"\xff\xfe", "Not a text file", id="not-text"),
        param(b"{not json", "Not JSON", id="not-json"),
        param(b"[1, 2]", "Not a JSON object", id="not-an-object"),
    ],
)
def test_a_file_that_is_no_json_object_is_refused(tmp_path: Path, content: bytes, match: str) -> None:
    """Bytes that are not a JSON object are not a ``.rehuco``.

    **Test steps:**

    * write the bytes and load them
    * verify ``RehucoFileError`` with the reason
    """
    path = tmp_path / "home.rehuco"
    path.write_bytes(content)
    with pytest.raises(RehucoFileError, match=match):
        RehucoFile.load(path)


def test_missing_file_propagates(tmp_path: Path) -> None:
    """A file that is not there is the caller's to report.

    **Test steps:**

    * load a path with no file and verify ``FileNotFoundError``
    """
    with pytest.raises(FileNotFoundError):
        RehucoFile.load(tmp_path / "home.rehuco")


@mark.parametrize(
    "data, match",
    [
        param({"format_version": 4}, "Missing the rehuco id", id="no-id"),
        param({"format_version": 4, "id": 5}, "Missing the rehuco id", id="id-not-a-string"),
        param({"format_version": 4, "id": "nope"}, "Not a UUID", id="id-not-a-uuid"),
        param({"format_version": 4, "id": REHUCO_ID, "roots": {}}, "not a list", id="roots-not-a-list"),
        param({"format_version": 4, "id": REHUCO_ID, "roots": ["x"]}, "not an object", id="root-not-an-object"),
        param({"format_version": 4, "id": REHUCO_ID, "roots": [{}]}, "has no 'file'", id="root-no-file"),
        param({"format_version": 4, "id": REHUCO_ID, "roots": [{"file": ""}]}, "has no 'file'", id="root-file-empty"),
        param(
            {"format_version": 4, "id": REHUCO_ID, "roots": [{"file": "discs.rehuroot"}, {"file": "./discs.rehuroot"}]},
            "name one file",
            id="one-file-twice",
        ),
    ],
)
def test_malformed_file_is_refused(tmp_path: Path, data: Any, match: str) -> None:
    """A file whose shape is wrong is refused, naming what is wrong and the file.

    **Test steps:**

    * write ``HOME``'s root files and a ``.rehuco`` with the fault, and load it
    * verify ``RehucoFileError`` with the reason
    """
    with pytest.raises(RehucoFileError, match=match):
        RehucoFile.load(write_home(tmp_path, data))


def test_two_root_files_with_one_id_are_refused(tmp_path: Path) -> None:
    """Two files claiming one root -- a copy made by hand -- would be one root listed twice: refused.

    **Test steps:**

    * write a second root file with the first one's id, and a ``.rehuco`` naming both
    * verify ``RehucoFileError`` naming the id
    """
    write_json(tmp_path / "copy.rehuroot", root_data(ROOT_IDS[0], "copy", "//nas/data/copy"))
    data = {**HOME, "roots": [{"file": "tutorials.rehuroot"}, {"file": "copy.rehuroot"}]}
    with pytest.raises(RehucoFileError, match=f"share the id {ROOT_IDS[0]}"):
        RehucoFile.load(write_home(tmp_path, data))


def test_shape_error_without_a_path_names_no_path() -> None:
    """A file built in memory has no path to name, so its errors name none; nor can it resolve a reference.

    **Test steps:**

    * build a file with a bad id, and one with a reference, both with no path
    * verify each error's message carries no path
    """
    with pytest.raises(RehucoFileError, match=r"^Not a UUID: the rehuco id$"):
        RehucoFile({"format_version": 4, "id": "nope"})
    with pytest.raises(RehucoFileError, match=r"^A root file cannot be found without the \.rehuco's folder$"):
        RehucoFile({"format_version": 4, "id": REHUCO_ID, "roots": [{"file": "x.rehuroot"}]})


# endregion


# region A root file that cannot be read


@mark.parametrize(
    "write, match",
    [
        param(lambda path: None, "The root file is missing", id="missing"),
        param(lambda path: path.write_text("{", encoding="utf-8"), "cannot be read: Not JSON", id="not-json"),
        param(lambda path: path.mkdir(), "cannot be read", id="a-folder"),
    ],
)
def test_a_root_file_that_cannot_be_read_is_kept_with_why(tmp_path: Path, write: Any, match: str) -> None:
    """A reference whose file is missing or unreadable does not refuse the catalog: the root is there, named by its
    file, with the reason, and the reference survives a save.

    **Test steps:**

    * write ``HOME`` with its ``discs`` file missing, not JSON, or a folder, and load it
    * verify that root's label is the file's stem, its location empty, its problem the reason, and it is unreadable
    * verify its id is the same at every load
    * save and verify the reference is written back as it was
    """
    path = write_home(tmp_path)
    (tmp_path / "discs.rehuroot").unlink()
    write(tmp_path / "discs.rehuroot")

    rehuco = RehucoFile.load(path)
    discs = rehuco.roots[1]

    assert (discs.label, discs.location, discs.file, discs.readable) == (
        "discs",
        "",
        tmp_path / "discs.rehuroot",
        False,
    )
    assert match in discs.problem
    assert RehucoFile.load(path).roots[1].root_id == discs.root_id
    rehuco.save()
    assert read_json(path)["roots"][1] == {"file": "discs.rehuroot", "some_future_reference_key": 7}


def test_an_unreadable_root_cannot_be_relabeled(tmp_path: Path) -> None:
    """There is no file to write a label into.

    **Test steps:**

    * load ``HOME`` with one root file missing
    * verify relabelling that root raises ``ValueError`` with the reason
    """
    path = write_home(tmp_path)
    (tmp_path / "discs.rehuroot").unlink()
    rehuco = RehucoFile.load(path)

    with pytest.raises(ValueError, match="could not be read: The root file is missing"):
        rehuco.relabel_root(1, "Discs")


def test_an_unreadable_root_takes_no_label_or_location(tmp_path: Path) -> None:
    """An unreadable root's stem holds no label and its empty location no place: another root may use either.

    **Test steps:**

    * load ``HOME`` with the ``discs`` file missing
    * relabel another root ``discs`` and add a root whose label would be ``discs``
    * verify both are accepted unsuffixed
    """
    path = write_home(tmp_path)
    (tmp_path / "discs.rehuroot").unlink()
    rehuco = RehucoFile.load(path)

    rehuco.relabel_root(0, "discs")
    row = rehuco.add_root("//nas/data/more", "refs (2)")

    assert labels(rehuco) == ["discs", "discs", "refs", "refs (2)"]
    assert rehuco.roots[row].file == tmp_path / "refs (2).rehuroot"


# endregion


# region Adding a root


def test_add_root_makes_a_root_file_beside_the_rehuco(tmp_path: Path, home: RehucoFile) -> None:
    """A root added from a folder is a new ``.rehuroot`` beside the ``.rehuco``, under a fresh id and the default
    layouts, written by the next save.

    **Test steps:**

    * add a root by location
    * verify its row, label, fresh id and file, and that nothing is written yet
    * save, and verify the root file's content and the reference to it
    """
    row = home.add_root("//nas/data/courses")
    added = home.roots[row]

    assert (row, added.label, added.location) == (3, "courses", "//nas/data/courses")
    assert added.root_id.version == 4
    assert added.root_id not in {UUID(root_id) for root_id in ROOT_IDS}
    file = tmp_path / "courses.rehuroot"
    assert added.file == file
    assert not file.exists()

    home.save()

    assert read_json(file) == {
        "format_version": 1,
        "id": str(added.root_id),
        "label": "courses",
        "location": "//nas/data/courses",
        "layouts": {"*": "*"},
        "fallbacks": {},
    }
    assert read_json(tmp_path / "home.rehuco")["roots"][3] == {"file": "courses.rehuroot"}


def test_add_root_takes_an_explicit_label_and_names_its_file_after_it(tmp_path: Path, home: RehucoFile) -> None:
    """A label given is the root's, and the file is named after it, sanitized.

    **Test steps:**

    * add a root labelled with characters no file name keeps
    * verify the label as given and the file name sanitized
    """
    row = home.add_root("//nas/data/courses", "Courses: 2026")

    assert home.roots[row].label == "Courses: 2026"
    assert home.roots[row].file == tmp_path / "Courses 2026.rehuroot"


def test_a_label_that_sanitizes_to_nothing_names_its_file_root(tmp_path: Path, home: RehucoFile) -> None:
    """A label with nothing a file name keeps still gets a file.

    **Test steps:**

    * add a root labelled only with characters no file name keeps
    * verify its file is ``root.rehuroot``
    """
    row = home.add_root("//nas/data/courses", "???")

    assert home.roots[row].file == tmp_path / "root.rehuroot"


def test_a_root_file_name_already_taken_gets_a_suffix(tmp_path: Path, home: RehucoFile) -> None:
    """A file already on disk, or a name another reference holds, is never written over.

    **Test steps:**

    * put a file named ``courses.rehuroot`` beside the ``.rehuco``, then add two roots labelled ``courses``-ish
    * verify the files are ``courses (2)`` and, for a label taken by an unreadable root's file, ``discs (2)``
    """
    (tmp_path / "courses.rehuroot").write_text("someone else's", encoding="utf-8")
    first = home.add_root("//nas/data/courses")
    (tmp_path / "discs.rehuroot").unlink()
    reloaded = RehucoFile.load(tmp_path / "home.rehuco")
    second = reloaded.add_root("//nas/data/more", "discs")

    assert home.roots[first].file == tmp_path / "courses (2).rehuroot"
    assert reloaded.roots[second].file == tmp_path / "discs (2).rehuroot"


def test_adding_a_root_needs_the_rehuco_saved_first() -> None:
    """A root file goes beside the ``.rehuco``, so a never-saved one has nowhere to put it.

    **Test steps:**

    * add a root to a new file and verify ``ValueError``
    """
    with pytest.raises(ValueError, match="saved first"):
        RehucoFile.new().add_root("//nas/data/courses")


@mark.parametrize(
    "location, label",
    [
        param("//nas/data/foo", "foo", id="folder"),
        param("//nas/data/foo/", "foo", id="trailing-separator"),
        param("//nas", "nas", id="server"),
        param("//", "//", id="nothing-else"),
    ],
)
def test_default_label_is_the_locations_last_segment(location: str, label: str) -> None:
    """With no label given, a root is labelled by its location's last segment.

    **Test steps:**

    * take the default label of each location
    * verify the segment, or the whole text when there is none
    """
    assert RehucoFile.default_label(location) == label


def test_clashing_labels_get_a_suffix(home: RehucoFile) -> None:
    """A label already in use, in any case, gets the first free numbered suffix.

    **Test steps:**

    * add three roots whose default label is ``Tutorials``, ``tutorials`` and ``tutorials``
    * verify the suffixes count on from 2
    """
    home.add_root("//other/a/Tutorials")
    home.add_root("//other/b/tutorials")
    home.add_root("//other/c/tutorials")

    assert labels(home)[3:] == ["Tutorials (2)", "tutorials (3)", "tutorials (4)"]


def test_a_location_already_a_root_is_refused(home: RehucoFile) -> None:
    """The same location twice is one root, whatever its case.

    **Test steps:**

    * add a root at ``HOME``'s first location, upper-cased
    * verify ``ValueError`` and three roots still
    """
    with pytest.raises(ValueError, match="Already a root"):
        home.add_root("//NAS/data/tutorials")
    assert home.count == 3


# endregion


# region Removing, relabelling and moving


def test_remove_root_returns_it_and_keeps_its_file(tmp_path: Path, home: RehucoFile) -> None:
    """Removing a root drops only the reference: another catalog may list its file.

    **Test steps:**

    * remove the middle root and save
    * verify the root returned, the rest in order, the reference gone, and the root file still there
    """
    removed = home.remove_root(1)
    home.save()

    assert removed.root_id == UUID(ROOT_IDS[1])
    assert labels(home) == ["tutorials", "refs"]
    assert [entry["file"] for entry in read_json(tmp_path / "home.rehuco")["roots"]] == [
        "tutorials.rehuroot",
        "shared/refs.rehuroot",
    ]
    assert (tmp_path / "discs.rehuroot").exists()


def test_relabel_root_writes_its_root_file(tmp_path: Path, home: RehucoFile) -> None:
    """A label is the root's, so relabelling writes the ``.rehuroot`` and keeps the root's id.

    **Test steps:**

    * relabel the first root and save
    * verify the id is kept, the root file holds the label, and the other root files are untouched
    """
    others = (tmp_path / "discs.rehuroot").read_text(encoding="utf-8")

    home.relabel_root(0, "Courses")
    home.save()

    assert home.roots[0].root_id == UUID(ROOT_IDS[0])
    assert read_json(tmp_path / "tutorials.rehuroot")["label"] == "Courses"
    assert (tmp_path / "discs.rehuroot").read_text(encoding="utf-8") == others


def test_relabel_root_to_its_own_label_in_another_case_is_accepted(home: RehucoFile) -> None:
    """A root's own label is no clash with itself.

    **Test steps:**

    * relabel ``tutorials`` to ``Tutorials``
    * verify the new label
    """
    home.relabel_root(0, "Tutorials")
    assert labels(home)[0] == "Tutorials"


def test_relabel_root_refuses_a_clashing_label(home: RehucoFile) -> None:
    """Another root's label, in any case, is refused.

    **Test steps:**

    * relabel the first root ``DISCS``
    * verify ``ValueError`` and the labels unchanged
    """
    with pytest.raises(ValueError, match="already labeled"):
        home.relabel_root(0, "DISCS")
    assert labels(home) == ["tutorials", "discs", "refs"]


def test_relabel_root_keeps_an_empty_label_and_lets_any_number_be_empty(tmp_path: Path, home: RehucoFile) -> None:
    """An empty label is kept as it is, and is no clash with another empty one.

    **Test steps:**

    * empty two roots' labels and save
    * verify both read back empty
    """
    home.relabel_root(0, "")
    home.relabel_root(1, "")
    home.save()

    assert labels(RehucoFile.load(tmp_path / "home.rehuco")) == ["", "", "refs"]


def test_a_read_only_root_file_cannot_be_relabeled(tmp_path: Path) -> None:
    """A root file stamped newer than this build is not written.

    **Test steps:**

    * load ``HOME`` with one root file stamped newer
    * verify relabelling it raises ``ValueError``
    """
    path = write_home(tmp_path)
    write_json(tmp_path / "discs.rehuroot", {**root_data(ROOT_IDS[1], "discs", "//x/discs"), "format_version": 2})

    with pytest.raises(ValueError, match="read-only"):
        RehucoFile.load(path).relabel_root(1, "Discs")


def test_move_puts_a_root_at_any_row(tmp_path: Path, home: RehucoFile) -> None:
    """Each move returns where the root lands, and the order is what a save writes.

    **Test steps:**

    * move the last root to the top, the first one down, then to the bottom
    * verify each returned row and the saved order
    """
    assert home.move(2, 0) == 0
    assert home.move_down(0) == 1
    assert home.move_to_bottom(0) == 2
    assert home.move_up(0) == 0
    assert home.move_to_top(1) == 0
    home.save()

    assert labels(home) == ["discs", "refs", "tutorials"]
    assert [entry["file"] for entry in read_json(tmp_path / "home.rehuco")["roots"]] == [
        "discs.rehuroot",
        "shared/refs.rehuroot",
        "tutorials.rehuroot",
    ]


@mark.parametrize("at, to", [param(3, 0, id="no-source"), param(0, 3, id="no-target"), param(-1, 0, id="negative")])
def test_move_refuses_a_row_outside_the_file(home: RehucoFile, at: int, to: int) -> None:
    """A move from or to a row the file does not have is refused.

    **Test steps:**

    * move with a source or a target outside the file
    * verify an index error and the order unchanged
    """
    with pytest.raises(IndexError):
        home.move(at, to)
    assert labels(home) == ["tutorials", "discs", "refs"]


@mark.parametrize(
    "operation",
    [
        param(lambda rehuco: rehuco.remove_root(3), id="remove"),
        param(lambda rehuco: rehuco.relabel_root(-1, "x"), id="relabel"),
        param(lambda rehuco: rehuco.move_to_top(3), id="move-to-top"),
        param(lambda rehuco: rehuco.move_up(-1), id="move-up"),
        param(lambda rehuco: rehuco.move_down(3), id="move-down"),
        param(lambda rehuco: rehuco.move_to_bottom(3), id="move-to-bottom"),
    ],
)
def test_out_of_range_row_is_an_index_error(home: RehucoFile, operation: Any) -> None:
    """Every row operation refuses a row outside the file, and changes nothing.

    **Test steps:**

    * run the operation on a row ``HOME`` does not have
    * verify ``IndexError`` and the labels unchanged
    """
    with pytest.raises(IndexError):
        operation(home)
    assert labels(home) == ["tutorials", "discs", "refs"]


# endregion


# region A save never overwrites another machine's change


def test_a_save_after_another_machine_changed_the_file_is_refused(tmp_path: Path, home: RehucoFile) -> None:
    """A ``.rehuco`` edited on disk since it was read is not overwritten.

    **Test steps:**

    * change the loaded file on disk as another machine would
    * move a root and save here
    * verify ``RehucoChangedError`` and that the file on disk is the other machine's
    """
    path = tmp_path / "home.rehuco"
    other = path.read_text(encoding="utf-8").replace("some_future_key", "another_key")
    path.write_text(other, encoding="utf-8")

    home.move_to_top(2)
    with pytest.raises(RehucoChangedError, match="changed on disk"):
        home.save()

    assert path.read_text(encoding="utf-8") == other


def test_a_root_file_another_machine_changed_is_not_overwritten(tmp_path: Path, home: RehucoFile) -> None:
    """A label edited in the root file by another machine is not overwritten by this one's, and the ``.rehuco`` is
    not written either.

    **Test steps:**

    * change a root file on disk, relabel that root here and save
    * verify ``RehurootChangedError``, the root file the other machine's, and the ``.rehuco`` untouched
    """
    root_file = tmp_path / "tutorials.rehuroot"
    other = root_file.read_text(encoding="utf-8").replace('"tutorials"', '"lessons"')
    root_file.write_text(other, encoding="utf-8")
    before = (tmp_path / "home.rehuco").read_text(encoding="utf-8")

    home.relabel_root(0, "Courses")
    with pytest.raises(RehurootChangedError, match="changed on disk"):
        home.save()

    assert root_file.read_text(encoding="utf-8") == other
    assert (tmp_path / "home.rehuco").read_text(encoding="utf-8") == before


def test_a_save_after_the_file_was_removed_is_refused(tmp_path: Path, home: RehucoFile) -> None:
    """A file deleted since it was read is not silently brought back.

    **Test steps:**

    * delete the loaded file, move a root and save
    * verify ``RehucoChangedError`` and that nothing was written
    """
    path = tmp_path / "home.rehuco"
    path.unlink()
    home.move_to_top(2)

    with pytest.raises(RehucoChangedError):
        home.save()

    assert not path.exists()


def test_a_save_after_the_file_became_binary_is_refused(tmp_path: Path, home: RehucoFile) -> None:
    """A file that no longer decodes as text counts as changed.

    **Test steps:**

    * overwrite the loaded file with bytes that are not UTF-8, move a root and save
    * verify ``RehucoChangedError``
    """
    (tmp_path / "home.rehuco").write_bytes(b"\xff\xfe")
    home.move_to_top(2)

    with pytest.raises(RehucoChangedError):
        home.save()


def test_saving_twice_in_a_row_is_not_a_conflict(tmp_path: Path, home: RehucoFile) -> None:
    """A save records what it wrote, of the ``.rehuco`` and of each root file, so the next one compares with that.

    **Test steps:**

    * relabel and save, relabel again and save
    * verify both saves succeeded and the root file holds the second label
    """
    home.relabel_root(0, "One")
    home.save()
    home.relabel_root(0, "Two")
    home.save()

    assert RehucoFile.load(tmp_path / "home.rehuco").roots[0].label == "Two"


def test_a_new_file_and_a_save_as_have_nothing_to_compare_with(tmp_path: Path, home: RehucoFile) -> None:
    """The check applies to the file this one was read from, not to a new file or another path.

    **Test steps:**

    * save a new file over a path that already holds something
    * save a loaded file to another path
    * verify both are written
    """
    taken = tmp_path / "taken.rehuco"
    taken.write_text("not a rehuco", encoding="utf-8")
    fresh = RehucoFile.new()
    fresh.save(taken)
    assert RehucoFile.load(taken).rehuco_id == fresh.rehuco_id

    elsewhere = tmp_path / "elsewhere.rehuco"
    home.save(elsewhere)
    assert RehucoFile.load(elsewhere).rehuco_id == home.rehuco_id


# endregion


def test_a_relabel_writes_only_the_root_file(tmp_path: Path, home: RehucoFile) -> None:
    """A label lives in the root file, so the ``.rehuco`` is not rewritten -- and another machine's edit of it
    meanwhile is no conflict.

    **Test steps:**

    * change the ``.rehuco`` on disk as another machine would, then relabel a root here and save
    * verify the save succeeded, the root file holds the label, and the ``.rehuco`` is the other machine's
    """
    path = tmp_path / "home.rehuco"
    other = path.read_text(encoding="utf-8").replace("some_future_key", "another_key")
    path.write_text(other, encoding="utf-8")

    home.relabel_root(0, "Courses")
    home.save()

    assert read_json(tmp_path / "tutorials.rehuroot")["label"] == "Courses"
    assert path.read_text(encoding="utf-8") == other


def test_a_refused_save_writes_no_new_root_file(tmp_path: Path, home: RehucoFile) -> None:
    """The ``.rehuco`` is checked before any root file is written, so a refused add leaves no stray ``.rehuroot``.

    **Test steps:**

    * change the ``.rehuco`` on disk as another machine would, then add a root here and save
    * verify ``RehucoChangedError`` and that the new root's file was not written
    """
    path = tmp_path / "home.rehuco"
    path.write_text(path.read_text(encoding="utf-8").replace("some_future_key", "another_key"), encoding="utf-8")
    row = home.add_root("//nas/data/courses")

    with pytest.raises(RehucoChangedError):
        home.save()

    file = home.roots[row].file
    assert file is not None
    assert not file.exists()
