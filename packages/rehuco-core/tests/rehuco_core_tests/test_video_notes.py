"""Tests for per-user video notes and favorites ([[field-schema#video-notes]], #571): the one write path, what it
leaves alone, the readers, and Forget.
"""

import json
from pathlib import Path
from typing import Any

from pytest import mark, param, raises
from rehuco_core import (
    RehuDocument,
    forget_progress,
    read_notes,
    read_video_favorites,
    read_video_notes,
    read_video_sizes,
    record_notes,
    record_progress,
    video_data_keys,
)
from rehuco_core.watch_progress import rekey_video_data, set_video_favorite

from rehuco_core_tests.test_watch_progress import UPDATED, make_tutorial, users_of


# region record_notes -- what it writes
def test_a_notes_write_stores_each_key_in_the_users_sidecar_with_the_files_sizes(tmp_path: Path) -> None:
    """The tutorial's notes, a video's note and a favorite are stored beside the progress, and a noted or starred
    video also records the file's size.

    **Test steps:**

    * write a record with a file of five bytes and another of three
    * record the tutorial's notes, a note on the first video and a favorite on the second
    * verify the sidecar holds the three keys and each video's size, and the record's own file is untouched
    """
    path = make_tutorial(tmp_path / "t", ["a.mp4", "b.mp4"])
    (tmp_path / "t" / "a.mp4").write_bytes(b"12345")
    (tmp_path / "t" / "b.mp4").write_bytes(b"123")
    record_before = json.loads(path.read_text(encoding="utf-8"))

    record_notes(
        path,
        "admin",
        notes="About it",
        video_notes={"a.mp4": "- [0:05](rehuco-video:a.mp4#t=5)"},
        favorites={"b.mp4": True},
    )

    assert users_of(path)["admin"] == {
        "notes": "About it",
        "video_notes": {"a.mp4": "- [0:05](rehuco-video:a.mp4#t=5)"},
        "video_favorites": ["b.mp4"],
        "video_sizes": {"a.mp4": 5, "b.mp4": 3},
    }
    assert json.loads(path.read_text(encoding="utf-8")) == record_before


def test_the_readers_give_back_what_was_written(tmp_path: Path) -> None:
    """Each reader answers one key of one user.

    **Test steps:**

    * record notes for one user and a note for another
    * read the first user's back through each reader
    * verify the values, and that the other user's note is not among them
    """
    path = make_tutorial(tmp_path / "t", ["a.mp4", "b.mp4"])
    record_notes(
        path, "admin", notes="About it", video_notes={"a.mp4": "note"}, favorites={"b.mp4": True, "a.mp4": True}
    )
    record_notes(path, "bob", video_notes={"b.mp4": "bob's"})

    document = RehuDocument.load(path)

    assert read_notes(document, "admin") == "About it"
    assert read_video_notes(document, "admin") == {"a.mp4": "note"}
    assert read_video_favorites(document, "admin") == {"a.mp4", "b.mp4"}
    assert read_video_sizes(document, "admin") == {"a.mp4": 0, "b.mp4": 0}
    assert read_notes(document, "bob") == ""
    assert read_video_notes(document, "bob") == {"b.mp4": "bob's"}


def test_a_notes_write_leaves_the_record_the_other_users_and_the_progress_as_stored(tmp_path: Path) -> None:
    """A note is the user's own state: ``updated``, another user's fields and the user's progress stay as stored.

    **Test steps:**

    * write a record with progress for two users
    * record a note for one of them
    * verify ``updated``, the other user's sidecar and the first user's progress are unchanged
    """
    block = {"users": {"admin": {"progress": {"a.mp4": {"position": 5.0, "viewed": False}}}, "bob": {"rating": 3}}}
    path = make_tutorial(tmp_path / "t", ["a.mp4"], block=block)
    bob_before = users_of(path)["bob"]

    record_notes(path, "admin", video_notes={"a.mp4": "note"})

    assert json.loads(path.read_text(encoding="utf-8"))["core"]["updated"] == UPDATED
    assert users_of(path)["bob"] == bob_before
    assert users_of(path)["admin"]["progress"] == {"a.mp4": {"position": 5.0, "viewed": False}}


def test_a_write_names_only_what_it_changes(tmp_path: Path) -> None:
    """What a write leaves out stays as stored: a favorite does not touch the notes, and a note not the favorites.

    **Test steps:**

    * record notes, a video's note and a favorite
    * record a second video's note, then star a third video
    * verify the first values stand beside the new ones
    """
    path = make_tutorial(tmp_path / "t", ["a.mp4", "b.mp4", "c.mp4"])
    record_notes(path, "admin", notes="About it", video_notes={"a.mp4": "one"}, favorites={"a.mp4": True})

    record_notes(path, "admin", video_notes={"b.mp4": "two"})
    record_notes(path, "admin", favorites={"c.mp4": True})

    stored = users_of(path)["admin"]
    assert stored["notes"] == "About it"
    assert stored["video_notes"] == {"a.mp4": "one", "b.mp4": "two"}
    assert stored["video_favorites"] == ["a.mp4", "c.mp4"]


# endregion


# region record_notes -- what it removes
def test_empty_values_are_removed_and_never_stored(tmp_path: Path) -> None:
    """An empty text, an unstarred last video and a video left with neither remove their keys, the sizes with them.

    **Test steps:**

    * record notes, a note and a favorite on one video
    * record an empty tutorial note, an empty video note and an unstarred video
    * verify no ``notes``, ``video_notes``, ``video_favorites`` or ``video_sizes`` key is left
    """
    path = make_tutorial(tmp_path / "t", ["a.mp4"])
    record_notes(path, "admin", notes="About it", video_notes={"a.mp4": "note"}, favorites={"a.mp4": True})

    record_notes(path, "admin", notes="", video_notes={"a.mp4": ""}, favorites={"a.mp4": False})

    assert users_of(path).get("admin", {}) == {}


def test_a_video_keeps_its_size_while_either_note_or_favorite_remains(tmp_path: Path) -> None:
    """The size goes with the last of the video's note and favorite, not the first.

    **Test steps:**

    * record a note and a favorite on one video
    * remove the note, and verify the size stays
    * unstar the video, and verify the size goes
    """
    path = make_tutorial(tmp_path / "t", ["a.mp4"])
    record_notes(path, "admin", video_notes={"a.mp4": "note"}, favorites={"a.mp4": True})

    record_notes(path, "admin", video_notes={"a.mp4": ""})
    assert users_of(path)["admin"]["video_sizes"] == {"a.mp4": 0}

    record_notes(path, "admin", favorites={"a.mp4": False})
    assert "video_sizes" not in users_of(path).get("admin", {})


def test_a_file_that_cannot_be_read_keeps_the_size_stored(tmp_path: Path) -> None:
    """The size recorded while the file was there stands when it is gone and its note is edited.

    **Test steps:**

    * note a file of four bytes, then delete the file
    * edit the note
    * verify the stored size is still four
    """
    path = make_tutorial(tmp_path / "t", ["a.mp4"])
    (tmp_path / "t" / "a.mp4").write_bytes(b"1234")
    record_notes(path, "admin", video_notes={"a.mp4": "first"})
    (tmp_path / "t" / "a.mp4").unlink()

    record_notes(path, "admin", video_notes={"a.mp4": "second"})

    assert users_of(path)["admin"]["video_sizes"] == {"a.mp4": 4}


# endregion


# region record_notes -- what it refuses
@mark.parametrize("key", [param("../escape.mp4", id="outside"), param("", id="empty"), param("a/../../b.mp4", id="up")])
def test_a_key_that_is_not_a_content_key_is_refused_before_anything_is_written(tmp_path: Path, key: str) -> None:
    """Every key is checked before the record is read.

    **Test steps:**

    * record a note and a favorite, one of them under a bad key
    * verify the refusal and that the record and its sidecars are unchanged
    """
    path = make_tutorial(tmp_path / "t", ["a.mp4"], block={"users": {"admin": {"rating": 4}}})
    before = (path.read_bytes(), users_of(path))

    with raises(ValueError, match="content key"):
        record_notes(path, "admin", video_notes={"a.mp4": "fine"}, favorites={key: True})

    assert (path.read_bytes(), users_of(path)) == before


def test_a_record_that_is_not_a_tutorial_is_refused(tmp_path: Path) -> None:
    """Notes live on tutorials only.

    **Test steps:**

    * record a note on a course record
    * verify the refusal
    """
    path = make_tutorial(tmp_path / "t", [], resource_type="course")

    with raises(ValueError, match="tutorials only"):
        record_notes(path, "admin", notes="About it")


# endregion


# region readers -- malformed values
@mark.parametrize(
    "stored",
    [
        param({"notes": 3, "video_notes": [], "video_favorites": "a.mp4", "video_sizes": 7}, id="wrong types"),
        param({}, id="absent"),
    ],
)
def test_a_malformed_or_absent_value_reads_as_empty(tmp_path: Path, stored: dict[str, Any]) -> None:
    """A value another build or a hand edit wrote wrong reads as nothing, never raises.

    **Test steps:**

    * load a record whose per-user fields are of the wrong types, or absent
    * verify every reader answers empty
    """
    path = make_tutorial(tmp_path / "t", [], block={"users": {"admin": stored}})
    document = RehuDocument.load(path)

    assert read_notes(document, "admin") == ""
    assert read_video_notes(document, "admin") == {}
    assert read_video_favorites(document, "admin") == set()
    assert read_video_sizes(document, "admin") == {}


def test_a_malformed_entry_is_skipped_and_the_rest_still_read(tmp_path: Path) -> None:
    """One bad entry does not hide its neighbours, and a write leaves it where it is.

    **Test steps:**

    * load a record holding a good and a bad entry in each map
    * verify the readers return the good ones only
    * record another note and verify the bad entry is still stored
    """
    stored = {
        "video_notes": {"a.mp4": "good", "b.mp4": 5},
        "video_favorites": ["a.mp4", 3],
        "video_sizes": {"a.mp4": 4, "b.mp4": -1, "c.mp4": True},
    }
    path = make_tutorial(tmp_path / "t", ["a.mp4", "c.mp4"], block={"users": {"admin": stored}})
    document = RehuDocument.load(path)

    assert read_video_notes(document, "admin") == {"a.mp4": "good"}
    assert read_video_favorites(document, "admin") == {"a.mp4"}
    assert read_video_sizes(document, "admin") == {"a.mp4": 4}

    record_notes(path, "admin", video_notes={"c.mp4": "new"})

    assert users_of(path)["admin"]["video_notes"] == {"a.mp4": "good", "b.mp4": 5, "c.mp4": "new"}


# endregion


# region data of one video -- keys, favorites, moving
def test_a_videos_data_is_the_union_of_what_is_kept_about_it(tmp_path: Path) -> None:
    """A progress entry, a note, a favorite or a size each makes a key a video with data.

    **Test steps:**

    * record progress on one video, a note on a second, a favorite on a third
    * verify the data keys are those three, and a user with nothing has none
    """
    path = make_tutorial(tmp_path / "t", ["a.mp4", "b.mp4", "c.mp4", "d.mp4"])
    record_progress(path, "admin", "a.mp4", 1.0, None)
    record_notes(path, "admin", video_notes={"b.mp4": "note"}, favorites={"c.mp4": True})
    document = RehuDocument.load(path)

    assert video_data_keys(document, "admin") == {"a.mp4", "b.mp4", "c.mp4"}
    assert video_data_keys(document, "bob") == set()


def test_favorites_are_kept_sorted_and_without_duplicates(tmp_path: Path) -> None:
    """Starring twice stores one key, and the list is in key order whatever order they were starred in.

    **Test steps:**

    * star two videos out of order, and one of them again
    * verify the stored list
    """
    document = RehuDocument.load(make_tutorial(tmp_path / "t", []))

    set_video_favorite(document, "admin", "b.mp4", True)
    set_video_favorite(document, "admin", "a.mp4", True)
    set_video_favorite(document, "admin", "b.mp4", True)

    assert document.user_field("admin", "video_favorites") == ["a.mp4", "b.mp4"]


def test_a_favorite_write_that_changes_nothing_leaves_the_list_as_stored(tmp_path: Path) -> None:
    """Unstarring a video that is not starred, or forgetting one, rewrites nothing -- an item this build cannot read
    stays where it is.

    **Test steps:**

    * hold a favorites list with a malformed item and progress on another video
    * unstar a video that is not starred, and forget the other
    * verify the list is as stored, malformed item included
    """
    block = {"users": {"admin": {"video_favorites": ["a.mp4", 5], "progress": {"b.mp4": {"position": 1.0}}}}}
    path = make_tutorial(tmp_path / "t", ["a.mp4"], block=block)
    document = RehuDocument.load(path)

    set_video_favorite(document, "admin", "c.mp4", False)
    assert document.user_field("admin", "video_favorites") == ["a.mp4", 5]

    forget_progress(path, "admin", "b.mp4")
    assert users_of(path)["admin"]["video_favorites"] == ["a.mp4", 5]


def test_rekeying_moves_all_four_and_nothing_else(tmp_path: Path) -> None:
    """A video's progress, note, favorite and size move to the new key together; another video's stay.

    **Test steps:**

    * hold progress, a note, a favorite and a size under one key, and a note under another
    * rekey the first
    * verify everything is under the new key, the other note stays, and the old key is gone from every map
    """
    stored = {
        "progress": {"old.mp4": {"position": 1.0}},
        "video_notes": {"old.mp4": "note", "other.mp4": "kept"},
        "video_favorites": ["old.mp4", "other.mp4"],
        "video_sizes": {"old.mp4": 9},
    }
    document = RehuDocument.load(make_tutorial(tmp_path / "t", [], block={"users": {"admin": stored}}))

    assert rekey_video_data(document, "admin", "old.mp4", "new.mp4") is True

    assert document.user_field("admin", "progress") == {"new.mp4": {"position": 1.0}}
    assert document.user_field("admin", "video_notes") == {"new.mp4": "note", "other.mp4": "kept"}
    assert document.user_field("admin", "video_favorites") == ["new.mp4", "other.mp4"]
    assert document.user_field("admin", "video_sizes") == {"new.mp4": 9}
    assert rekey_video_data(document, "admin", "old.mp4", "newer.mp4") is False


# endregion


# region forget_progress -- the note and favorite go too
def test_forgetting_a_video_removes_its_note_favorite_and_size_with_its_progress(tmp_path: Path) -> None:
    """Forget removes everything the user keeps about one video, and only that video.

    **Test steps:**

    * keep progress, a note and a favorite on two videos
    * forget one
    * verify the other's data stands whole and the forgotten one has none in any map
    """
    path = make_tutorial(tmp_path / "t", ["a.mp4", "b.mp4"])
    for key in ("a.mp4", "b.mp4"):
        record_progress(path, "admin", key, 1.0, None)
    record_notes(path, "admin", video_notes={"a.mp4": "one", "b.mp4": "two"}, favorites={"a.mp4": True, "b.mp4": True})

    assert forget_progress(path, "admin", "a.mp4") is True

    stored = users_of(path)["admin"]
    assert list(stored["progress"]) == ["b.mp4"]
    assert stored["video_notes"] == {"b.mp4": "two"}
    assert stored["video_favorites"] == ["b.mp4"]
    assert stored["video_sizes"] == {"b.mp4": 0}


def test_forgetting_a_video_with_only_a_note_removes_it(tmp_path: Path) -> None:
    """A video that never played still has data to forget, and the answer says it was there.

    **Test steps:**

    * note a video that has no progress entry
    * forget it, then forget it again
    * verify the first answers ``True``, the second ``False``, and nothing is left
    """
    path = make_tutorial(tmp_path / "t", ["a.mp4"])
    record_notes(path, "admin", video_notes={"a.mp4": "note"})

    assert forget_progress(path, "admin", "a.mp4") is True
    assert forget_progress(path, "admin", "a.mp4") is False

    assert users_of(path).get("admin", {}) == {}


# endregion
