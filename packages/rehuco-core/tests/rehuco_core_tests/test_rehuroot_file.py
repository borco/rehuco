"""Tests for the ``.rehuroot`` file: its format, round-trip, the lock and the save's changed-on-disk check (#577).

Real files in ``tmp_path``.
"""

import json
from pathlib import Path
from typing import Any, Final
from uuid import UUID

import pytest
from pytest import fixture, mark, param
from pytest_mock import MockerFixture
from rehuco_core import (
    DEFAULT_LAYOUTS,
    REHUROOT_FORMAT_VERSION,
    LockReasonKind,
    RehurootChangedError,
    RehurootFile,
    RehurootFileError,
)

ROOT_ID: Final = "a41b9c3d-0000-4000-8000-000000000001"

TUTORIALS: Final = {
    "format_version": 1,
    "id": ROOT_ID,
    "label": "Tutorials",
    "location": "//nas/data/Tutorials",
    "layouts": {"tutorial": ["{authors}/{title}{{ [{year}]}}"]},
    "fallbacks": {"authors": "Unknown"},
    "some_future_key": [1, 2],
}


def write_json(path: Path, data: Any) -> Path:
    """Write ``data`` as JSON.

    :param path: the file.
    :param data: what to write.
    :returns: the file.
    """
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def read_json(path: Path) -> Any:
    """A JSON file, parsed.

    :param path: the file.
    :returns: its content.
    """
    return json.loads(path.read_text(encoding="utf-8"))


@fixture
def tutorials(tmp_path: Path) -> RehurootFile:
    """A loaded copy of ``TUTORIALS``: a layout per type, a fallback and an unknown key.

    :param tmp_path: pytest's temporary directory.
    :returns: the loaded file.
    """
    return RehurootFile.load(write_json(tmp_path / "tutorials.rehuroot", TUTORIALS))


def test_load_reads_every_part(tmp_path: Path, tutorials: RehurootFile) -> None:
    """A loaded file exposes its path, id, label, location, layouts, fallbacks and version, and is not dirty.

    **Test steps:**

    * load ``TUTORIALS``
    * verify each part
    """
    assert tutorials.path == tmp_path / "tutorials.rehuroot"
    assert tutorials.root_id == UUID(ROOT_ID)
    assert (tutorials.label, tutorials.location) == ("Tutorials", "//nas/data/Tutorials")
    assert dict(tutorials.layouts) == {"tutorial": ("{authors}/{title}{{ [{year}]}}",)}
    assert dict(tutorials.fallbacks) == TUTORIALS["fallbacks"]
    assert tutorials.format_version == REHUROOT_FORMAT_VERSION
    assert tutorials.lock_reason is None
    assert not tutorials.dirty


def test_layouts_and_fallbacks_are_read_only(tutorials: RehurootFile) -> None:
    """What a caller is handed cannot change the file behind its back.

    **Test steps:**

    * try to set a layout and a fallback through the mappings handed out
    * verify both raise ``TypeError``
    """
    with pytest.raises(TypeError):
        tutorials.layouts["*"] = ("*",)  # type: ignore[index]
    with pytest.raises(TypeError):
        tutorials.fallbacks["title"] = "x"  # type: ignore[index]


def test_a_file_with_no_layouts_or_fallbacks_takes_the_defaults(tmp_path: Path) -> None:
    """A hand-written file naming neither admits any record under its name and has no fallbacks.

    **Test steps:**

    * load a file with only the stamp, id, label and location
    * verify the default layouts and no fallbacks
    """
    data = {key: TUTORIALS[key] for key in ("format_version", "id", "label", "location")}
    root = RehurootFile.load(write_json(tmp_path / "bare.rehuroot", data))

    assert dict(root.layouts) == dict(DEFAULT_LAYOUTS) == {"*": ("*",)}
    assert not root.fallbacks


def test_a_relabel_is_saved_canonically_with_unknown_keys_carried(tmp_path: Path, tutorials: RehurootFile) -> None:
    """A relabel marks the file dirty; the save writes it in canonical order, the unknown key after the known ones.

    **Test steps:**

    * relabel the root, verify it is dirty, and save
    * verify the file's content and key order, and that it is no longer dirty
    """
    tutorials.label = "Courses"
    assert tutorials.dirty

    tutorials.save()

    saved = read_json(tmp_path / "tutorials.rehuroot")
    assert saved == {**TUTORIALS, "label": "Courses"}
    assert list(saved) == ["format_version", "id", "label", "location", "layouts", "fallbacks", "some_future_key"]
    assert not tutorials.dirty


def test_setting_the_same_label_changes_nothing(tutorials: RehurootFile) -> None:
    """A label set to what it is leaves nothing to save.

    **Test steps:**

    * set the label to its own value and verify the file is not dirty
    """
    tutorials.label = "Tutorials"

    assert not tutorials.dirty


def test_new_layouts_and_fallbacks_are_saved_and_copied(tmp_path: Path, tutorials: RehurootFile) -> None:
    """Layouts and fallbacks set are the file's own copies, written by the next save, the unknown key carried (#578).

    **Test steps:**

    * set new layouts and fallbacks from dicts, then change those dicts
    * verify the file holds what was set and is dirty
    * save and verify the file's content
    """
    layouts = {"*": ("*",), "tutorial": ("{title}", "{authors}/{title}")}
    fallbacks = {"title": "Untitled"}
    tutorials.layouts = layouts
    tutorials.fallbacks = fallbacks
    layouts["*"] = ("changed",)
    fallbacks.clear()

    assert dict(tutorials.layouts) == {"*": ("*",), "tutorial": ("{title}", "{authors}/{title}")}
    assert dict(tutorials.fallbacks) == {"title": "Untitled"}
    assert tutorials.dirty
    tutorials.save()
    assert read_json(tmp_path / "tutorials.rehuroot") == {
        **TUTORIALS,
        "layouts": {"*": ["*"], "tutorial": ["{title}", "{authors}/{title}"]},
        "fallbacks": {"title": "Untitled"},
    }


def test_setting_the_same_layouts_and_fallbacks_changes_nothing(tutorials: RehurootFile) -> None:
    """Maps equal to what the file holds leave nothing to save.

    **Test steps:**

    * set the layouts and fallbacks to copies of their own values and verify the file is not dirty
    """
    tutorials.layouts = dict(tutorials.layouts)
    tutorials.fallbacks = dict(TUTORIALS["fallbacks"])

    assert not tutorials.dirty


def test_a_read_only_file_refuses_new_layouts_and_fallbacks(tmp_path: Path) -> None:
    """A file stamped newer than this build is not edited.

    **Test steps:**

    * load a file stamped newer
    * verify setting its layouts and its fallbacks each raises ``ValueError`` and leaves them as they were
    """
    root = RehurootFile.load(write_json(tmp_path / "newer.rehuroot", {**TUTORIALS, "format_version": 2}))

    with pytest.raises(ValueError, match="read-only"):
        root.layouts = {"*": ("*",)}
    with pytest.raises(ValueError, match="read-only"):
        root.fallbacks = {}
    assert dict(root.layouts) == {"tutorial": ("{authors}/{title}{{ [{year}]}}",)}
    assert dict(root.fallbacks) == TUTORIALS["fallbacks"]


def test_a_new_file_takes_the_layouts_and_fallbacks_given(tmp_path: Path) -> None:
    """``RehurootFile.new`` starts with the maps it is given, copied (#578).

    **Test steps:**

    * create a new file with layouts and fallbacks, then change the dict given
    * save and verify the file holds what was given
    """
    layouts = {"tutorial": ("{authors}/{title}",)}
    root = RehurootFile.new(tmp_path / "a.rehuroot", "//nas/data/a", "a", layouts=layouts, fallbacks={"authors": "?"})
    layouts.clear()

    root.save()

    saved = read_json(tmp_path / "a.rehuroot")
    assert (saved["layouts"], saved["fallbacks"]) == ({"tutorial": ["{authors}/{title}"]}, {"authors": "?"})


def test_a_new_file_refuses_layouts_that_are_not_strings(tmp_path: Path) -> None:
    """Maps a ``.rehuroot`` could not hold are refused when the file is made.

    **Test steps:**

    * create a new file whose layouts hold a number and verify ``RehurootFileError``
    """
    with pytest.raises(RehurootFileError, match="'layouts' is not an object of templates"):
        RehurootFile.new(tmp_path / "a.rehuroot", "//nas/data/a", "a", layouts={"*": 1})  # type: ignore[dict-item]


def test_a_new_file_has_a_fresh_id_and_the_default_layouts(tmp_path: Path) -> None:
    """``RehurootFile.new`` mints a uuid4 id, takes the default layouts and no fallbacks, and is dirty until saved.

    **Test steps:**

    * create two new files and verify their ids are version 4 and differ
    * save one and verify its content
    """
    first = RehurootFile.new(tmp_path / "a.rehuroot", "//nas/data/a", "a")
    second = RehurootFile.new(tmp_path / "b.rehuroot", "//nas/data/b", "b")
    assert first.root_id.version == 4
    assert first.root_id != second.root_id
    assert first.dirty

    first.save()

    assert read_json(tmp_path / "a.rehuroot") == {
        "format_version": 1,
        "id": str(first.root_id),
        "label": "a",
        "location": "//nas/data/a",
        "layouts": {"*": ["*"]},
        "fallbacks": {},
    }
    assert not first.dirty


def test_a_new_file_never_writes_over_one_already_there(tmp_path: Path) -> None:
    """A root file made meanwhile by someone else is not overwritten by a new one of the same name.

    **Test steps:**

    * create a new file at a path, then put a file there before saving
    * verify ``RehurootChangedError`` and the other file kept
    """
    path = tmp_path / "a.rehuroot"
    fresh = RehurootFile.new(path, "//nas/data/a", "a")
    path.write_text("someone else's", encoding="utf-8")

    with pytest.raises(RehurootChangedError, match="already there"):
        fresh.save()

    assert path.read_text(encoding="utf-8") == "someone else's"


def test_a_save_after_another_machine_changed_the_file_is_refused(tmp_path: Path, tutorials: RehurootFile) -> None:
    """A file edited on disk since it was read is not overwritten, and stays dirty here.

    **Test steps:**

    * change the file on disk as another machine would, then relabel and save here
    * verify ``RehurootChangedError``, the other machine's file kept, and the edit still pending
    """
    other = json.dumps({**TUTORIALS, "label": "Lessons"})
    (tmp_path / "tutorials.rehuroot").write_text(other, encoding="utf-8")

    tutorials.label = "Courses"
    with pytest.raises(RehurootChangedError, match="changed on disk"):
        tutorials.save()

    assert (tmp_path / "tutorials.rehuroot").read_text(encoding="utf-8") == other
    assert tutorials.dirty


def test_a_save_after_the_file_was_removed_is_refused(tmp_path: Path, tutorials: RehurootFile) -> None:
    """A file deleted since it was read is not silently brought back.

    **Test steps:**

    * delete the file, relabel and save
    * verify ``RehurootChangedError`` and nothing written
    """
    (tmp_path / "tutorials.rehuroot").unlink()
    tutorials.label = "Courses"

    with pytest.raises(RehurootChangedError):
        tutorials.save()

    assert not (tmp_path / "tutorials.rehuroot").exists()


def test_saving_twice_in_a_row_is_not_a_conflict(tmp_path: Path, tutorials: RehurootFile) -> None:
    """A save records what it wrote, so the next one compares with that.

    **Test steps:**

    * relabel and save twice
    * verify the file holds the second label
    """
    tutorials.label = "One"
    tutorials.save()
    tutorials.label = "Two"
    tutorials.save()

    assert RehurootFile.load(tmp_path / "tutorials.rehuroot").label == "Two"


def test_a_save_takes_the_files_lock(mocker: MockerFixture, tutorials: RehurootFile) -> None:
    """The write happens under the root file's own lock, as a record's does.

    **Test steps:**

    * spy on the lock and save
    * verify the lock was taken for the root file and released
    """
    lock = mocker.patch("rehuco_core.rehuroot_file.RecordFileLock")

    tutorials.save()

    lock.assert_called_once_with(tutorials.path)
    lock.return_value.__enter__.assert_called_once()
    lock.return_value.__exit__.assert_called_once()


def test_a_newer_file_loads_read_only(tmp_path: Path) -> None:
    """A file stamped newer than this build loads, but refuses a relabel and a save.

    **Test steps:**

    * load ``TUTORIALS`` stamped one version past this build's
    * verify the lock reason, and that a relabel and a save each raise
    """
    root = RehurootFile.load(write_json(tmp_path / "t.rehuroot", {**TUTORIALS, "format_version": 2}))

    reason = root.lock_reason
    assert reason is not None
    assert reason.kind is LockReasonKind.NEWER_FORMAT
    with pytest.raises(ValueError, match="read-only"):
        root.label = "x"
    with pytest.raises(ValueError, match="read-only"):
        root.save()


@mark.parametrize(
    "content, match",
    [
        param(b"\xff\xfe", "Not a text file", id="not-text"),
        param(b"{not json", "Not JSON", id="not-json"),
        param(b"[1]", "Not a JSON object", id="not-an-object"),
    ],
)
def test_a_file_that_is_no_json_object_is_refused(tmp_path: Path, content: bytes, match: str) -> None:
    """Bytes that are not a JSON object are not a ``.rehuroot``.

    **Test steps:**

    * write the bytes and load them
    * verify ``RehurootFileError`` with the reason
    """
    path = tmp_path / "t.rehuroot"
    path.write_bytes(content)
    with pytest.raises(RehurootFileError, match=match):
        RehurootFile.load(path)


@mark.parametrize(
    "changes, match",
    [
        param({"format_version": None}, "not a version", id="no-stamp"),
        param({"format_version": "1"}, "not a version", id="stamp-not-a-number"),
        param({"format_version": True}, "not a version", id="stamp-a-bool"),
        param({"format_version": 0}, "not a version", id="stamp-too-old"),
        param({"id": None}, "No 'id'", id="no-id"),
        param({"id": "nope"}, "Not a UUID", id="id-not-a-uuid"),
        param({"location": ""}, "No 'location'", id="location-empty"),
        param({"location": 3}, "No 'location'", id="location-not-a-string"),
        param({"label": None}, "No 'label'", id="no-label"),
        param({"layouts": []}, "'layouts' is not an object of templates", id="layouts-not-an-object"),
        param({"layouts": {"*": 1}}, "'layouts' is not an object of templates", id="layout-not-a-string"),
        param(
            {"layouts": {"*": ["{title}", 1]}}, "'layouts' is not an object of templates", id="template-not-a-string"
        ),
        param({"fallbacks": {"title": None}}, "'fallbacks' is not an object of strings", id="fallback-not-a-string"),
    ],
)
def test_a_malformed_file_is_refused_naming_it(tmp_path: Path, changes: dict[str, Any], match: str) -> None:
    """A file whose shape is wrong is refused, naming what is wrong and the file.

    **Test steps:**

    * write ``TUTORIALS`` with one part broken or missing, and load it
    * verify ``RehurootFileError`` with the reason, ending in the file's path
    """
    data = {key: value for key, value in {**TUTORIALS, **changes}.items() if value is not None}
    path = write_json(tmp_path / "t.rehuroot", data)

    with pytest.raises(RehurootFileError, match=match) as raised:
        RehurootFile.load(path)
    assert str(raised.value).endswith(str(path))


def test_a_missing_file_propagates(tmp_path: Path) -> None:
    """A file that is not there is the caller's to report.

    **Test steps:**

    * load a path with no file and verify ``FileNotFoundError``
    """
    with pytest.raises(FileNotFoundError):
        RehurootFile.load(tmp_path / "t.rehuroot")
