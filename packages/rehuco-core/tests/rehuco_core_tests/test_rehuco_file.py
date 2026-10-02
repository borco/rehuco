"""Tests for the ``.rehuco`` file: format, round-trip, and root operations (#371)."""

import json
import ntpath
import posixpath
from pathlib import Path
from typing import Any, Final
from uuid import UUID

import pytest
from pytest import fixture, mark, param
from pytest_mock import MockerFixture
from rehuco_core import (
    CURRENT_REHUCO_VERSION,
    LockReasonKind,
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
    "format_version": 1,
    "id": REHUCO_ID,
    "some_future_key": {"nested": [1, 2, 3]},
    "roots": [
        {"id": ROOT_IDS[0], "path": "D:/tutorials", "label": "tutorials", "removable": False},
        {"id": ROOT_IDS[1], "path": "E:/discs", "label": "discs", "removable": True, "some_future_root_key": 7},
        {"id": ROOT_IDS[2], "path": "F:/refs", "label": "refs"},
    ],
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
    * verify the id, path, version, count and every root's parsed view, ``removable`` defaulting to false
    """
    assert home.rehuco_id == UUID(REHUCO_ID)
    assert home.path == FAKE_PATH
    assert home.format_version == CURRENT_REHUCO_VERSION
    assert home.lock_reason is None
    assert home.count == 3
    assert home.roots == (
        RehucoRoot(UUID(ROOT_IDS[0]), Path("D:/tutorials"), "tutorials", False),
        RehucoRoot(UUID(ROOT_IDS[1]), Path("E:/discs"), "discs", True),
        RehucoRoot(UUID(ROOT_IDS[2]), Path("F:/refs"), "refs", False),
    )


def test_round_trip_is_lossless_and_canonical(mocker: MockerFixture, home: RehucoFile) -> None:
    """Saving an unedited file writes back what was read, unknown keys included, in canonical key order.

    **Test steps:**

    * load ``HOME`` and save it through a mocked ``atomic_write_text``
    * verify the payload equals ``HOME``: the unknown top-level key, the unknown root key and the absent
      ``removable`` all carried as found
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


def test_unstamped_file_reads_as_version_one(mocker: MockerFixture) -> None:
    """A file with no ``format_version`` is read as v1 and saved stamped.

    **Test steps:**

    * load ``HOME`` without its stamp
    * verify the version and the saved stamp
    """
    data = {key: value for key, value in HOME.items() if key != "format_version"}
    rehuco = load_rehuco(mocker, data)
    assert rehuco.format_version == 1
    assert saved_payload(mocker, rehuco)["format_version"] == CURRENT_REHUCO_VERSION


def test_missing_roots_reads_as_none(mocker: MockerFixture) -> None:
    """A file with no ``roots`` key reads as one with no roots, and saves the empty list.

    **Test steps:**

    * load a file holding only a stamp and an id
    * verify no roots, and ``roots: []`` in the saved payload
    """
    rehuco = load_rehuco(mocker, {"format_version": 1, "id": REHUCO_ID})
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
        param({"format_version": 1}, "Missing the rehuco id", id="no-id"),
        param({"format_version": 1, "id": 42}, "Missing the rehuco id", id="id-not-a-string"),
        param({"format_version": 1, "id": "not-a-uuid"}, "Not a UUID: the rehuco id", id="id-not-a-uuid"),
        param({"format_version": 1, "id": REHUCO_ID, "roots": {}}, "'roots' is not a list", id="roots-not-a-list"),
        param({"format_version": 1, "id": REHUCO_ID, "roots": ["D:/x"]}, "not an object", id="root-not-an-object"),
        param(
            {"format_version": 1, "id": REHUCO_ID, "roots": [{"id": ROOT_IDS[0], "label": "x"}]},
            "has no 'path'",
            id="root-no-path",
        ),
        param(
            {"format_version": 1, "id": REHUCO_ID, "roots": [{"id": ROOT_IDS[0], "path": "D:/x", "label": ""}]},
            "has no 'label'",
            id="root-empty-label",
        ),
        param(
            {"format_version": 1, "id": REHUCO_ID, "roots": [{"path": "D:/x", "label": "x"}]},
            "Missing the root 'D:/x'",
            id="root-no-id",
        ),
        param(
            {"format_version": 1, "id": REHUCO_ID, "roots": [{"id": "nope", "path": "D:/x", "label": "x"}]},
            "Not a UUID: the root 'D:/x'",
            id="root-id-not-a-uuid",
        ),
        param(
            {
                "format_version": 1,
                "id": REHUCO_ID,
                "roots": [{"id": ROOT_IDS[0], "path": "D:/x", "label": "x", "removable": "yes"}],
            },
            "non-boolean 'removable'",
            id="removable-not-a-bool",
        ),
        param(
            {
                "format_version": 1,
                "id": REHUCO_ID,
                "roots": [
                    {"id": ROOT_IDS[0], "path": "D:/x", "label": "x"},
                    {"id": ROOT_IDS[0], "path": "D:/y", "label": "y"},
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
        RehucoFile({"format_version": 1})
    assert str(raised.value) == "Missing the rehuco id"


# endregion


# region Adding and removing roots


def test_add_root_appends_under_a_fresh_id(mocker: MockerFixture) -> None:
    """``add_root`` appends a root with a fresh uuid4 id, the folder's name as label, and the removable flag.

    **Test steps:**

    * add two roots to a new file, the second removable
    * verify the returned rows, distinct uuid4 ids, labels and flags
    * verify the saved root objects spell every key
    """
    rehuco = RehucoFile.new()
    assert rehuco.add_root(Path("D:/tutorials")) == 0
    assert rehuco.add_root("E:/discs", removable=True) == 1
    first, second = rehuco.roots
    assert first.root_id.version == 4
    assert first.root_id != second.root_id
    assert (first.label, first.removable) == ("tutorials", False)
    assert (second.label, second.removable) == ("discs", True)
    assert saved_payload(mocker, rehuco)["roots"][1] == {
        "id": str(second.root_id),
        "path": "E:/discs",
        "label": "discs",
        "removable": True,
    }


def test_add_root_takes_an_explicit_label() -> None:
    """A label given to ``add_root`` is used in place of the folder's name.

    **Test steps:**

    * add a root with a label
    * verify the label
    """
    rehuco = RehucoFile.new()
    rehuco.add_root("D:/tutorials", "Courses")
    assert labels(rehuco) == ["Courses"]


@mark.parametrize(
    ("path", "label"),
    [
        param("D:/tutorials", "tutorials", id="folder"),
        param("D:/tutorials/", "tutorials", id="trailing-separator"),
        param("D:\\", "D:", id="drive-root"),
        param("/", "/", id="posix-root"),
    ],
)
def test_default_label_is_the_folder_name(path: str, label: str) -> None:
    """With no label given, the folder's name is used; a folder with no name falls back to its path.

    **Test steps:**

    * add a root with no label
    * verify the label
    """
    rehuco = RehucoFile.new()
    rehuco.add_root(path)
    assert labels(rehuco) == [label]


def test_clashing_labels_get_a_suffix() -> None:
    """A label already in use, compared case-insensitively, gets ``(2)``, ``(3)``, ...

    **Test steps:**

    * add three roots whose folders share a name, differing in case
    * add a fourth with an explicit label that clashes
    * verify the suffixed labels
    """
    rehuco = RehucoFile.new()
    rehuco.add_root("D:/tutorials")
    rehuco.add_root("E:/Tutorials")
    rehuco.add_root("F:/TUTORIALS")
    rehuco.add_root("G:/other", "Tutorials")
    assert labels(rehuco) == ["tutorials", "Tutorials (2)", "TUTORIALS (3)", "Tutorials (4)"]


@mark.parametrize(
    "duplicate",
    [
        param("D:/Tutorials", id="case"),
        param("D:/tutorials/", id="trailing-separator"),
        param("D:\\tutorials", id="backslash"),
        param("D:/x/../tutorials", id="dot-dot"),
    ],
)
def test_duplicate_root_is_refused_where_paths_fold_case(mocker: MockerFixture, duplicate: str) -> None:
    """On Windows paths, a folder already a root is refused however it is spelled.

    **Test steps:**

    * compare paths the way ``ntpath`` does
    * add a root, then the same folder spelled differently
    * verify ``ValueError`` and that only one root remains
    """
    mocker.patch("rehuco_core.rehuco_file.os_path", ntpath)
    rehuco = RehucoFile.new()
    rehuco.add_root("D:/tutorials")
    with pytest.raises(ValueError, match="Already a root"):
        rehuco.add_root(duplicate)
    assert rehuco.count == 1


def test_case_variant_is_another_root_where_paths_do_not_fold_case(mocker: MockerFixture) -> None:
    """On POSIX paths, a case variant is a different folder, but a trailing separator is not.

    **Test steps:**

    * compare paths the way ``posixpath`` does
    * add ``/data/tutorials`` and ``/data/Tutorials`` and verify both are kept
    * add ``/data/tutorials/`` and verify ``ValueError``
    """
    mocker.patch("rehuco_core.rehuco_file.os_path", posixpath)
    rehuco = RehucoFile.new()
    rehuco.add_root("/data/tutorials")
    rehuco.add_root("/data/Tutorials")
    assert rehuco.count == 2
    with pytest.raises(ValueError, match="Already a root"):
        rehuco.add_root("/data/tutorials/")


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
    * verify the label, id and path
    """
    home.relabel_root(0, "Courses")
    root = home.roots[0]
    assert root.label == "Courses"
    assert root.root_id == UUID(ROOT_IDS[0])
    assert root.path == Path("D:/tutorials")


def test_relabel_root_to_its_own_label_in_another_case_is_accepted(home: RehucoFile) -> None:
    """A root's own label never clashes with itself.

    **Test steps:**

    * relabel ``tutorials`` to ``Tutorials``
    * verify the label
    """
    home.relabel_root(0, "Tutorials")
    assert labels(home)[0] == "Tutorials"


@mark.parametrize(
    ("label", "match"),
    [
        param("", "cannot be empty", id="empty"),
        param("DISCS", "already labeled", id="clash"),
    ],
)
def test_relabel_root_refuses_an_empty_or_clashing_label(home: RehucoFile, label: str, match: str) -> None:
    """An explicit relabel is refused, never suffixed, when it is empty or another root uses it.

    **Test steps:**

    * relabel the first root
    * verify ``ValueError`` and the label unchanged
    """
    with pytest.raises(ValueError, match=match):
        home.relabel_root(0, label)
    assert labels(home)[0] == "tutorials"


def test_set_removable_round_trips(mocker: MockerFixture, home: RehucoFile) -> None:
    """``set_removable`` flips the flag, and the saved file carries it.

    **Test steps:**

    * mark the third root removable and the second not
    * verify the parsed flags and the saved root objects
    """
    home.set_removable(2, True)
    home.set_removable(1, False)
    assert [root.removable for root in home.roots] == [False, False, True]
    roots = saved_payload(mocker, home)["roots"]
    assert [root["removable"] for root in roots] == [False, False, True]
    assert roots[1]["some_future_root_key"] == 7


@mark.parametrize(
    "operation",
    [
        param(lambda rehuco: rehuco.remove_root(3), id="remove"),
        param(lambda rehuco: rehuco.relabel_root(-1, "x"), id="relabel"),
        param(lambda rehuco: rehuco.set_removable(3, True), id="set-removable"),
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


# region Ordering


@mark.parametrize(
    ("method", "at", "row", "order"),
    [
        param("move_to_top", 2, 0, ["refs", "tutorials", "discs"], id="top-from-bottom"),
        param("move_to_top", 0, 0, ["tutorials", "discs", "refs"], id="top-at-top"),
        param("move_up", 1, 0, ["discs", "tutorials", "refs"], id="up-from-middle"),
        param("move_up", 0, 0, ["tutorials", "discs", "refs"], id="up-at-top"),
        param("move_down", 1, 2, ["tutorials", "refs", "discs"], id="down-from-middle"),
        param("move_down", 2, 2, ["tutorials", "discs", "refs"], id="down-at-bottom"),
        param("move_to_bottom", 0, 2, ["discs", "refs", "tutorials"], id="bottom-from-top"),
        param("move_to_bottom", 2, 2, ["tutorials", "discs", "refs"], id="bottom-at-bottom"),
    ],
)
def test_ordering_moves(home: RehucoFile, method: str, at: int, row: int, order: list[str]) -> None:
    """Each ordering move returns the row the root ends up at and reorders the roots, ids travelling with them.

    **Test steps:**

    * run the move on ``HOME``
    * verify the returned row, the label order, and that the moved root kept its id
    """
    moved_id = home.roots[at].root_id
    assert getattr(home, method)(at) == row
    assert labels(home) == order
    assert home.roots[row].root_id == moved_id


# endregion
