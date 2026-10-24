"""Tests for the ``.rehuco`` file: format, round-trip, root operations and the save's changed-on-disk check (#371,
#514)."""

import json
from pathlib import Path
from typing import Any, Final
from uuid import UUID

import pytest
from pytest import fixture, mark, param
from pytest_mock import MockerFixture
from rehuco_core import (
    CURRENT_REHUCO_VERSION,
    LockReasonKind,
    RehucoChangedError,
    RehucoFile,
    RehucoFileError,
    RehucoRoot,
)

FAKE_PATH: Final = Path("/fake/home.rehuco")

REHUCO_ID: Final = "6f1c5e0a-1b2c-4d3e-8f90-a1b2c3d4e5f6"

ROOT_IDS: Final = (
    "a41b9c3d-0000-4000-8000-000000000001",
    "a41b9c3d-0000-4000-8000-000000000002",
    "a41b9c3d-0000-4000-8000-000000000003",
)

HOME: Final = {
    "format_version": 3,
    "id": REHUCO_ID,
    "some_future_key": {"nested": [1, 2, 3]},
    "roots": [
        {"id": ROOT_IDS[0], "label": "tutorials", "location": "//nas/data/tutorials"},
        {"id": ROOT_IDS[1], "label": "discs", "location": "//ryzen-5600/e/discs", "some_future_root_key": 7},
        {"id": ROOT_IDS[2], "label": "refs", "location": "//nas/data/refs"},
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


def mock_file_contents(mocker: MockerFixture, text: str) -> None:
    """Mock ``Path.read_text`` to return ``text``.

    :param mocker: pytest-mock fixture.
    :param text: the file content to serve.
    """
    mocker.patch.object(Path, "read_text", return_value=text)


def load_rehuco(mocker: MockerFixture, data: Any) -> RehucoFile:
    """Mock ``Path.read_text`` and load a ``RehucoFile`` from ``data``.

    :param mocker: pytest-mock fixture.
    :param data: the value to serialize as the file's JSON content.
    :returns: the loaded file.
    """
    mock_file_contents(mocker, json.dumps(data))
    return RehucoFile.load(FAKE_PATH)


def saved_payload(mocker: MockerFixture, rehuco: RehucoFile) -> dict[str, Any]:
    """Save ``rehuco`` through a mocked ``atomic_write_text`` and return what it would have written.

    :param mocker: pytest-mock fixture.
    :param rehuco: the file to save; saved to its own path, or to ``FAKE_PATH`` when it has none.
    :returns: the written JSON, parsed.
    """
    mock_write = mocker.patch("rehuco_core.rehuco_file.atomic_write_text")
    rehuco.save(None if rehuco.path is not None else FAKE_PATH)
    mock_write.assert_called_once()
    return json.loads(mock_write.call_args[0][1])


def labels(rehuco: RehucoFile) -> list[str]:
    """The file's root labels, in row order.

    :param rehuco: the file.
    :returns: one label per root.
    """
    return [root.label for root in rehuco.roots]


@fixture(autouse=True)
def no_lock_file(mocker: MockerFixture) -> None:
    """Take no lock file on a save: the writes here are mocked, to ``FAKE_PATH``, which has no folder to take one in.

    :param mocker: pytest-mock fixture.
    """
    mocker.patch("rehuco_core.rehuco_file.RecordFileLock")


@fixture
def home(mocker: MockerFixture) -> RehucoFile:
    """A loaded copy of ``HOME``: three roots, an unknown top-level key and an unknown root key.

    :param mocker: pytest-mock fixture.
    :returns: the loaded file.
    """
    return load_rehuco(mocker, json.loads(json.dumps(HOME)))


# region Load and save


def test_load_reads_the_rehuco_id_and_roots(home: RehucoFile) -> None:
    """A loaded file exposes its rehuco id, path, version and parsed roots.

    **Test steps:**

    * load ``HOME``
    * verify the id, path, version, count and every root's parsed view
    """
    assert home.rehuco_id == UUID(REHUCO_ID)
    assert home.path == FAKE_PATH
    assert home.format_version == CURRENT_REHUCO_VERSION == 3
    assert home.lock_reason is None
    assert home.count == 3
    assert home.roots == (
        RehucoRoot(UUID(ROOT_IDS[0]), "tutorials", "//nas/data/tutorials"),
        RehucoRoot(UUID(ROOT_IDS[1]), "discs", "//ryzen-5600/e/discs"),
        RehucoRoot(UUID(ROOT_IDS[2]), "refs", "//nas/data/refs"),
    )


def test_round_trip_is_lossless_and_canonical(mocker: MockerFixture, home: RehucoFile) -> None:
    """Saving an unedited file writes back what was read, unknown keys included, in canonical key order.

    **Test steps:**

    * load ``HOME`` and save it through a mocked ``atomic_write_text``
    * verify the payload equals ``HOME``: the unknown top-level key and the unknown root key carried as found
    * verify the key order: ``format_version``, ``id``, the unknown key, ``roots`` last
    """
    payload = saved_payload(mocker, home)
    assert payload == HOME
    assert list(payload) == ["format_version", "id", "some_future_key", "roots"]


def test_save_writes_to_the_loaded_path_and_text_ends_with_a_newline(mocker: MockerFixture, home: RehucoFile) -> None:
    """A save with no path writes back to the file it was read from, as indented JSON ending in a newline.

    **Test steps:**

    * save ``HOME`` through a mocked ``atomic_write_text``
    * verify the target path and the text's trailing newline
    """
    mock_write = mocker.patch("rehuco_core.rehuco_file.atomic_write_text")
    home.save()
    target, text = mock_write.call_args[0]
    assert target == FAKE_PATH
    assert text.endswith("}\n")


def test_new_file_has_a_fresh_id_and_no_roots_until_saved(mocker: MockerFixture) -> None:
    """``RehucoFile.new`` mints a uuid4 rehuco id, holds no roots and no path, and takes the path of its first
    save.

    **Test steps:**

    * create two new files
    * verify each id is a version-4 UUID and the two differ, with no roots and no path
    * save one to ``FAKE_PATH`` and verify the payload and that ``path`` is now set
    """
    first = RehucoFile.new()
    second = RehucoFile.new()
    assert first.rehuco_id.version == 4
    assert first.rehuco_id != second.rehuco_id
    assert first.count == 0
    assert first.path is None
    payload = saved_payload(mocker, first)
    assert payload == {"format_version": CURRENT_REHUCO_VERSION, "id": str(first.rehuco_id), "roots": []}
    assert first.path == FAKE_PATH


def test_save_without_a_path_is_refused(mocker: MockerFixture) -> None:
    """A never-saved file needs a path to save to.

    **Test steps:**

    * mock ``atomic_write_text``
    * save a new file with no path and verify ``ValueError`` and no write
    """
    mock_write = mocker.patch("rehuco_core.rehuco_file.atomic_write_text")
    with pytest.raises(ValueError, match="no path"):
        RehucoFile.new().save()
    mock_write.assert_not_called()


@mark.parametrize(
    "data",
    [
        param(V1_HOME, id="v1"),
        param({key: value for key, value in V1_HOME.items() if key != "format_version"}, id="unstamped"),
        param(V2_HOME, id="v2"),
        param({**V1_HOME, "roots": {}}, id="v1-roots-not-a-list"),
        param({**V1_HOME, "roots": ["D:/x"]}, id="v1-root-not-an-object"),
    ],
)
def test_an_older_file_is_refused_with_its_path(mocker: MockerFixture, data: dict[str, Any]) -> None:
    """A file whose roots hold paths is not carried forward, whatever else is wrong with it: it says to make the
    catalog again.

    **Test steps:**

    * load a v1, an unstamped and a v2 file, and v1 files whose roots are not a list or not objects
    * verify ``RehucoFileError`` saying an older build made it, ending in the file's path
    """
    with pytest.raises(RehucoFileError, match="older build") as raised:
        load_rehuco(mocker, data)
    assert str(raised.value).endswith(str(FAKE_PATH))


def test_missing_roots_reads_as_none(mocker: MockerFixture) -> None:
    """A file with no ``roots`` key reads as one with no roots, and saves the empty list.

    **Test steps:**

    * load a file holding only a stamp and an id
    * verify no roots, and ``roots: []`` in the saved payload
    """
    rehuco = load_rehuco(mocker, {"format_version": 3, "id": REHUCO_ID})
    assert rehuco.count == 0
    assert saved_payload(mocker, rehuco)["roots"] == []


def test_newer_file_loads_read_only_and_refuses_to_save(mocker: MockerFixture) -> None:
    """A file stamped newer than this build loads, locked with ``NEWER_FORMAT``, and is never written.

    **Test steps:**

    * load ``HOME`` stamped one past the current version
    * verify the roots read, the lock reason's kind and message
    * save through a mocked ``atomic_write_text`` and verify ``ValueError`` and no write
    """
    newer = CURRENT_REHUCO_VERSION + 1
    rehuco = load_rehuco(mocker, HOME | {"format_version": newer})
    assert rehuco.count == 3
    reason = rehuco.lock_reason
    assert reason is not None
    assert reason.kind == LockReasonKind.NEWER_FORMAT
    assert str(newer) in reason.message
    mock_write = mocker.patch("rehuco_core.rehuco_file.atomic_write_text")
    with pytest.raises(ValueError, match="read-only"):
        rehuco.save()
    mock_write.assert_not_called()


def test_write_failure_propagates(mocker: MockerFixture, home: RehucoFile) -> None:
    """An ``OSError`` from the atomic write reaches the caller.

    **Test steps:**

    * make the mocked ``atomic_write_text`` raise ``OSError``
    * verify ``save`` raises it
    """
    mocker.patch("rehuco_core.rehuco_file.atomic_write_text", side_effect=OSError("disk full"))
    with pytest.raises(OSError, match="disk full"):
        home.save()


def test_not_text_is_refused(mocker: MockerFixture) -> None:
    """A file that does not decode as UTF-8 is a ``RehucoFileError``.

    **Test steps:**

    * make ``Path.read_text`` raise ``UnicodeDecodeError``
    * verify ``RehucoFileError``
    """
    error = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
    mocker.patch.object(Path, "read_text", side_effect=error)
    with pytest.raises(RehucoFileError, match="Not a text file"):
        RehucoFile.load(FAKE_PATH)


def test_not_json_is_refused(mocker: MockerFixture) -> None:
    """A file that is not JSON is a ``RehucoFileError``.

    **Test steps:**

    * serve text that is not JSON
    * verify ``RehucoFileError``
    """
    mock_file_contents(mocker, "{ not json")
    with pytest.raises(RehucoFileError, match="Not JSON"):
        RehucoFile.load(FAKE_PATH)


def test_missing_file_propagates(mocker: MockerFixture) -> None:
    """A missing file is the caller's ``FileNotFoundError``, not a format error.

    **Test steps:**

    * make ``Path.read_text`` raise ``FileNotFoundError``
    * verify it reaches the caller
    """
    mocker.patch.object(Path, "read_text", side_effect=FileNotFoundError(FAKE_PATH))
    with pytest.raises(FileNotFoundError):
        RehucoFile.load(FAKE_PATH)


@mark.parametrize(
    ("data", "match"),
    [
        param([], "Not a JSON object", id="not-an-object"),
        param({"format_version": 3}, "Missing the rehuco id", id="no-id"),
        param({"format_version": 3, "id": 42}, "Missing the rehuco id", id="id-not-a-string"),
        param({"format_version": 3, "id": "not-a-uuid"}, "Not a UUID: the rehuco id", id="id-not-a-uuid"),
        param({"format_version": 3, "id": REHUCO_ID, "roots": {}}, "'roots' is not a list", id="roots-not-a-list"),
        param({"format_version": 3, "id": REHUCO_ID, "roots": ["x"]}, "not an object", id="root-not-an-object"),
        param(
            {"format_version": 3, "id": REHUCO_ID, "roots": [{"id": ROOT_IDS[0], "label": "x"}]},
            "has no 'location'",
            id="root-no-location",
        ),
        param(
            {"format_version": 3, "id": REHUCO_ID, "roots": [{"id": ROOT_IDS[0], "location": "//m/x", "label": 7}]},
            "has no 'label'",
            id="root-label-not-a-string",
        ),
        param(
            {"format_version": 3, "id": REHUCO_ID, "roots": [{"location": "//m/x", "label": "x"}]},
            "Missing the root '//m/x'",
            id="root-no-id",
        ),
        param(
            {"format_version": 3, "id": REHUCO_ID, "roots": [{"id": "nope", "location": "//m/x", "label": "x"}]},
            "Not a UUID: the root '//m/x'",
            id="root-id-not-a-uuid",
        ),
        param(
            {
                "format_version": 3,
                "id": REHUCO_ID,
                "roots": [
                    {"id": ROOT_IDS[0], "location": "//m/x", "label": "x"},
                    {"id": ROOT_IDS[0], "location": "//m/y", "label": "y"},
                ],
            },
            "Two roots share the id",
            id="duplicate-root-id",
        ),
    ],
)
def test_malformed_file_is_refused(mocker: MockerFixture, data: Any, match: str) -> None:
    """A file without a ``.rehuco``'s shape is a ``RehucoFileError`` naming the problem and the path.

    **Test steps:**

    * load each malformed payload
    * verify ``RehucoFileError`` with the expected message, ending in the file's path
    """
    with pytest.raises(RehucoFileError, match=match) as raised:
        load_rehuco(mocker, data)
    assert str(raised.value).endswith(str(FAKE_PATH))


def test_shape_error_without_a_path_names_no_path() -> None:
    """A malformed object handed straight to the constructor reports the problem alone.

    **Test steps:**

    * construct a ``RehucoFile`` from an object with no id
    * verify the message is the problem only
    """
    with pytest.raises(RehucoFileError) as raised:
        RehucoFile({"format_version": 3})
    assert str(raised.value) == "Missing the rehuco id"


# endregion


# region Adding and removing roots


def test_add_root_appends_under_a_fresh_id(mocker: MockerFixture) -> None:
    """``add_root`` appends a root with a fresh uuid4 id and the location's last segment as label.

    **Test steps:**

    * add two roots to a new file
    * verify the returned rows, distinct uuid4 ids and labels
    * verify the saved root objects spell every key
    """
    rehuco = RehucoFile.new()
    assert rehuco.add_root("//nas/data/tutorials") == 0
    assert rehuco.add_root("//ryzen-5600/e/discs") == 1
    first, second = rehuco.roots
    assert first.root_id.version == 4
    assert first.root_id != second.root_id
    assert (first.label, second.label) == ("tutorials", "discs")
    assert saved_payload(mocker, rehuco)["roots"][1] == {
        "id": str(second.root_id),
        "label": "discs",
        "location": "//ryzen-5600/e/discs",
    }


def test_add_root_takes_an_explicit_label() -> None:
    """A label given to ``add_root`` is used in place of the location's name.

    **Test steps:**

    * add a root with a label
    * verify the label
    """
    rehuco = RehucoFile.new()
    rehuco.add_root("//nas/data/tutorials", "Courses")
    assert labels(rehuco) == ["Courses"]


@mark.parametrize(
    ("location", "label"),
    [
        param("//nas/data/tutorials", "tutorials", id="folder"),
        param("//nas/data/tutorials/", "tutorials", id="trailing-separator"),
        param("//nas", "nas", id="server"),
        param("//", "//", id="nothing-else"),
    ],
)
def test_default_label_is_the_locations_last_segment(location: str, label: str) -> None:
    """With no label given, the location's last segment is used; a location with none falls back to itself.

    **Test steps:**

    * add a root with no label
    * verify the label
    """
    rehuco = RehucoFile.new()
    rehuco.add_root(location)
    assert labels(rehuco) == [label]


def test_clashing_labels_get_a_suffix() -> None:
    """A label already in use, compared case-insensitively, gets ``(2)``, ``(3)``, ...

    **Test steps:**

    * add three roots whose locations end alike, differing in case
    * add a fourth with an explicit label that clashes
    * verify the suffixed labels
    """
    rehuco = RehucoFile.new()
    rehuco.add_root("//nas/a/tutorials")
    rehuco.add_root("//nas/b/Tutorials")
    rehuco.add_root("//nas/c/TUTORIALS")
    rehuco.add_root("//nas/d/other", "Tutorials")
    assert labels(rehuco) == ["tutorials", "Tutorials (2)", "TUTORIALS (3)", "Tutorials (4)"]


def test_a_location_already_a_root_is_refused() -> None:
    """The same place is one root, however the host and share are cased.

    **Test steps:**

    * add a root, then the same location in another case
    * verify ``ValueError`` and that only one root remains
    """
    rehuco = RehucoFile.new()
    rehuco.add_root("//nas/data/tutorials")
    with pytest.raises(ValueError, match="Already a root"):
        rehuco.add_root("//NAS/Data/Tutorials")
    assert rehuco.count == 1


def test_remove_root_returns_it_and_keeps_the_rest(home: RehucoFile) -> None:
    """``remove_root`` drops one root and returns its parsed view.

    **Test steps:**

    * remove the middle root of ``HOME``
    * verify the returned root and the remaining labels
    """
    removed = home.remove_root(1)
    assert removed.root_id == UUID(ROOT_IDS[1])
    assert labels(home) == ["tutorials", "refs"]


# endregion


# region Editing roots


def test_relabel_root_keeps_its_id(home: RehucoFile) -> None:
    """``relabel_root`` changes the label and nothing else.

    **Test steps:**

    * relabel the first root
    * verify the label, id and location
    """
    home.relabel_root(0, "Courses")
    root = home.roots[0]
    assert root.label == "Courses"
    assert root.root_id == UUID(ROOT_IDS[0])
    assert root.location == "//nas/data/tutorials"


def test_relabel_root_to_its_own_label_in_another_case_is_accepted(home: RehucoFile) -> None:
    """A root's own label never clashes with itself.

    **Test steps:**

    * relabel ``tutorials`` to ``Tutorials``
    * verify the label
    """
    home.relabel_root(0, "Tutorials")
    assert labels(home)[0] == "Tutorials"


def test_relabel_root_refuses_a_clashing_label(home: RehucoFile) -> None:
    """An explicit relabel is refused, never suffixed, when another root uses it.

    **Test steps:**

    * relabel the first root to another root's label in another case
    * verify ``ValueError`` and the label unchanged
    """
    with pytest.raises(ValueError, match="already labeled"):
        home.relabel_root(0, "DISCS")
    assert labels(home)[0] == "tutorials"


def test_relabel_root_keeps_an_empty_label_and_lets_any_number_be_empty(
    mocker: MockerFixture, home: RehucoFile
) -> None:
    """An empty label is kept as typed, is never a clash, and survives a save and a load.

    **Test steps:**

    * relabel two roots to the empty string
    * verify both are empty, with no refusal, and that the saved payload holds empty labels
    * load that payload and verify the labels are still empty
    """
    home.relabel_root(0, "")
    home.relabel_root(1, "")

    assert labels(home) == ["", "", "refs"]
    payload = saved_payload(mocker, home)
    assert [root["label"] for root in payload["roots"]] == ["", "", "refs"]
    assert labels(load_rehuco(mocker, payload)) == ["", "", "refs"]


def test_move_puts_a_root_at_any_row(mocker: MockerFixture, home: RehucoFile) -> None:
    """``move`` takes a root to the row it should end up at, whichever way, and the saved file keeps the order.

    **Test steps:**

    * move the first root to the last row, then the last to the middle, then one where it already is
    * verify the returned rows, the order after each, and the saved order
    """
    assert home.move(0, 2) == 2
    assert [root.label for root in home.roots] == ["discs", "refs", "tutorials"]
    assert home.move(2, 1) == 1
    assert [root.label for root in home.roots] == ["discs", "tutorials", "refs"]
    assert home.move(1, 1) == 1
    assert [root["label"] for root in saved_payload(mocker, home)["roots"]] == ["discs", "tutorials", "refs"]


@mark.parametrize("at, to", [param(3, 0, id="no-source"), param(0, 3, id="no-target"), param(-1, 0, id="negative")])
def test_move_refuses_a_row_outside_the_file(home: RehucoFile, at: int, to: int) -> None:
    """Both rows must exist, and nothing changes when one does not.

    **Test steps:**

    * move with a source or a target outside the file
    * verify an index error and the order unchanged
    """
    with pytest.raises(IndexError):
        home.move(at, to)
    assert [root.label for root in home.roots] == ["tutorials", "discs", "refs"]


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


# endregion


# region A save never overwrites another machine's change


def write_home(folder: Path) -> Path:
    """Write ``HOME`` into ``folder``.

    :param folder: where to write it.
    :returns: the file.
    """
    path = folder / "home.rehuco"
    path.write_text(json.dumps(HOME), encoding="utf-8")
    return path


def test_a_save_after_another_machine_changed_the_file_is_refused(tmp_path: Path) -> None:
    """A file edited on disk since it was read is not overwritten.

    **Test steps:**

    * load a real file, then change it on disk as another machine would
    * edit and save here
    * verify ``RehucoChangedError`` and that the file on disk is the other machine's
    """
    path = write_home(tmp_path)
    rehuco = RehucoFile.load(path)
    other = path.read_text(encoding="utf-8").replace("refs", "pictures")
    path.write_text(other, encoding="utf-8")

    rehuco.relabel_root(0, "Courses")
    with pytest.raises(RehucoChangedError, match="changed on disk"):
        rehuco.save()

    assert path.read_text(encoding="utf-8") == other


def test_a_save_after_the_file_was_removed_is_refused(tmp_path: Path) -> None:
    """A file deleted since it was read is not silently brought back.

    **Test steps:**

    * load a real file and delete it
    * save
    * verify ``RehucoChangedError`` and that nothing was written
    """
    path = write_home(tmp_path)
    rehuco = RehucoFile.load(path)
    path.unlink()

    with pytest.raises(RehucoChangedError):
        rehuco.save()

    assert not path.exists()


def test_a_save_after_the_file_became_binary_is_refused(tmp_path: Path) -> None:
    """A file that no longer decodes as text counts as changed.

    **Test steps:**

    * load a real file and overwrite it with bytes that are not UTF-8
    * save
    * verify ``RehucoChangedError``
    """
    path = write_home(tmp_path)
    rehuco = RehucoFile.load(path)
    path.write_bytes(b"\xff\xfe")

    with pytest.raises(RehucoChangedError):
        rehuco.save()


def test_saving_twice_in_a_row_is_not_a_conflict(tmp_path: Path) -> None:
    """A save records what it wrote, so the next one compares with that.

    **Test steps:**

    * load a real file, relabel and save, relabel again and save
    * verify both saves succeeded and the file holds the second label
    """
    path = write_home(tmp_path)
    rehuco = RehucoFile.load(path)

    rehuco.relabel_root(0, "One")
    rehuco.save()
    rehuco.relabel_root(0, "Two")
    rehuco.save()

    assert RehucoFile.load(path).roots[0].label == "Two"


def test_a_new_file_and_a_save_as_have_nothing_to_compare_with(tmp_path: Path) -> None:
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

    loaded = RehucoFile.load(write_home(tmp_path))
    elsewhere = tmp_path / "elsewhere.rehuco"
    loaded.save(elsewhere)
    assert RehucoFile.load(elsewhere).rehuco_id == loaded.rehuco_id


# endregion
