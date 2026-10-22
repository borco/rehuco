"""Tests for per-user watch progress ([[field-schema#watch-progress]], #410): the one write path, the
auto-viewed rules, the ``videos`` and ``progress`` maps, and the derived totals.
"""

import json
from pathlib import Path
from typing import Any, Final

from freezegun.api import FrozenDateTimeFactory
from pytest import approx, mark, param, raises
from pytest_mock import MockerFixture
from rehuco_core import (
    CURRENT_REHUSER_VERSION,
    ContentUnreachableError,
    ProgressEntry,
    RehuDocument,
    VideoFacts,
    WatchRules,
    WatchTotals,
    current_block_version,
    forget_progress,
    merge_write,
    missing_progress_keys,
    read_progress,
    read_videos,
    record_progress,
    set_progress_entry,
    set_videos,
    user_sidecar_path,
    user_sidecar_paths,
    watch_totals,
)

UPDATED: Final = "2026-01-01T00:00:00Z"


def make_tutorial(
    folder: Path,
    files: list[str],
    *,
    block: dict[str, Any] | None = None,
    record: str = "info.rehu",
    resource_type: str = "tutorial",
) -> Path:
    """Write a tutorial record, its users' sidecars and empty content files under ``folder``.

    :param folder: the resource's folder, created.
    :param files: content files to create, relative to ``folder``.
    :param block: extra entries for the tutorial block (``videos``, ``users``); its ``users`` map is written to each
        user's sidecar beside the record, as a save stores it.
    :param record: the record's file name -- ``info.rehu``, or ``<stem>.rehu`` for a standalone one.
    :param resource_type: the record's type.
    :returns: the record's path.
    """
    folder.mkdir(parents=True, exist_ok=True)
    for name in files:
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(b"")
    shared = dict(block or {})
    users: dict[str, Any] = shared.pop("users", {})
    data: dict[str, Any] = {
        "format_version": 2,
        "core": {"type": resource_type, "id": "550e8400-e29b-41d4-a716-446655440000", "updated": UPDATED},
        resource_type: {"format_version": current_block_version(resource_type), **shared},
    }
    path = folder / record
    path.write_text(json.dumps(data), encoding="utf-8")
    for username, fields in users.items():
        sidecar = {"format_version": CURRENT_REHUSER_VERSION, resource_type: fields}
        user_sidecar_path(path, username).write_text(json.dumps(sidecar), encoding="utf-8")
    return path


def users_of(path: Path) -> dict[str, Any]:
    """Read each user's tutorial fields as stored in the sidecars beside the record.

    :param path: the record.
    :returns: each sidecar's tutorial fields, by the user its name carries; empty when there are none.
    """
    users: dict[str, Any] = {}
    for slug, sidecar in user_sidecar_paths(path).items():
        stored = json.loads(sidecar.read_text(encoding="utf-8"))
        if "tutorial" in stored:
            users[slug] = stored["tutorial"]
    return users


# region record_progress -- what it writes
def test_a_progress_write_replaces_only_its_own_entry(tmp_path: Path, freezer: FrozenDateTimeFactory) -> None:
    """The write touches ``users.<username>.progress.<key>`` and nothing else: another user's progress,
    the same user's other entries, the shared ``videos`` and ``updated`` all stay as stored -- the record and the
    other user's sidecar hold what they held.

    **Test steps:**

    * write a record holding a videos map and other fields, and sidecars holding another user's progress and an
      older entry
    * record progress on one file at a later time
    * verify the record's and the other user's payloads are unchanged and only that entry changed
    """
    videos = {"a.mp4": {"duration": 100.0}}
    path = make_tutorial(
        tmp_path / "t",
        ["a.mp4", "b.mp4"],
        block={
            "complete": True,
            "videos": videos,
            "users": {
                "admin": {"rating": 4, "progress": {"b.mp4": {"position": 5.0, "viewed": False}}},
                "bob": {"progress": {"a.mp4": {"position": 50.0, "viewed": False}}},
            },
        },
    )
    record_before = json.loads(path.read_text(encoding="utf-8"))
    bob_before = json.loads(user_sidecar_path(path, "bob").read_text(encoding="utf-8"))
    freezer.move_to("2026-10-12T10:00:00Z")

    record_progress(path, "admin", "a.mp4", 12.5, 100.0)

    assert json.loads(path.read_text(encoding="utf-8")) == record_before
    assert json.loads(user_sidecar_path(path, "bob").read_text(encoding="utf-8")) == bob_before
    assert users_of(path) == {
        "admin": {
            "rating": 4,
            "progress": {
                "a.mp4": {"position": 12.5, "duration": 100.0, "size": 0, "viewed": False},
                "b.mp4": {"position": 5.0, "viewed": False},
            },
        },
        "bob": {"progress": {"a.mp4": {"position": 50.0, "viewed": False}}},
    }


def test_progress_is_recorded_under_the_username_given(tmp_path: Path) -> None:
    """A node records each user's progress on one file under that user's name, not its own.

    **Test steps:**

    * record progress for two users on the same file
    * verify each landed in its own submap
    """
    path = make_tutorial(tmp_path / "t", ["a.mp4"])

    record_progress(path, "alice", "a.mp4", 1.0, 10.0)
    record_progress(path, "bob", "a.mp4", 2.0, 10.0)

    assert users_of(path) == {
        "alice": {"progress": {"a.mp4": {"position": 1.0, "duration": 10.0, "size": 0, "viewed": False}}},
        "bob": {"progress": {"a.mp4": {"position": 2.0, "duration": 10.0, "size": 0, "viewed": False}}},
    }


def test_a_progress_write_never_hands_the_owners_legacy_flags_to_another_user(tmp_path: Path) -> None:
    """Opening a record migrates a v0 tutorial block, filing its legacy per-user fields under the identity the
    record is opened as. A progress write opens it as the host's ``current_username``, never as the user whose
    progress it records -- or Bob would inherit the owner's rating and verdict ([[field-schema#per-user-shared]]).

    **Test steps:**

    * write a v0 tutorial block carrying top-level ``rating`` and ``viewed``
    * record Bob's progress, opening the record as ``owner``
    * verify the legacy fields landed under ``owner`` and Bob holds his progress only
    """
    path = make_tutorial(tmp_path / "t", ["a.mp4"])
    data = json.loads(path.read_text(encoding="utf-8"))
    data["tutorial"] = {"format_version": 0, "rating": 4, "viewed": True}
    path.write_text(json.dumps(data), encoding="utf-8")

    record_progress(path, "bob", "a.mp4", 1.0, 10.0, current_username="owner")

    assert users_of(path) == {
        "owner": {"rating": 4, "viewed": True},
        "bob": {"progress": {"a.mp4": {"position": 1.0, "duration": 10.0, "size": 0, "viewed": False}}},
    }


def test_an_unknown_length_keeps_the_one_already_recorded(tmp_path: Path) -> None:
    """A player that does not yet know the length leaves the stored one in place rather than erasing it;
    with none stored, the entry is written without one.

    **Test steps:**

    * record with a length, then without
    * record without a length on a file with no entry
    * verify the first entry keeps its length and the second has none
    """
    path = make_tutorial(tmp_path / "t", ["a.mp4", "b.mp4"])

    record_progress(path, "admin", "a.mp4", 1.0, 60.0)
    record_progress(path, "admin", "a.mp4", 2.0, None)
    record_progress(path, "admin", "b.mp4", 3.0, None)

    assert users_of(path)["admin"]["progress"] == {
        "a.mp4": {"position": 2.0, "duration": 60.0, "size": 0, "viewed": False},
        "b.mp4": {"position": 3.0, "size": 0, "viewed": False},
    }


def test_a_standalone_records_progress_is_keyed_without_its_stem(tmp_path: Path) -> None:
    """A standalone ``<stem>.rehu`` keys its one file by its extension, so the entry survives a rename of
    the stem ([[field-schema#watch-progress]]).

    **Test steps:**

    * record progress on a standalone record's video, reaching its end
    * verify the entry's key, and that the tutorial rule saw the file on disk under the same key
    """
    path = make_tutorial(tmp_path / "t", ["lesson.mp4"], record="lesson.rehu")

    record_progress(path, "admin", ".mp4", 60.0, 60.0)

    assert users_of(path) == {
        "admin": {"progress": {".mp4": {"position": 60.0, "duration": 60.0, "size": 0, "viewed": True}}, "viewed": True}
    }


@mark.parametrize(
    ("relative", "position", "duration"),
    [
        param("../x.mp4", 1.0, 10.0, id="key-escaping-the-resource"),
        param("a.mp4", -1.0, 10.0, id="negative-position"),
        param("a.mp4", float("nan"), 10.0, id="position-not-a-number"),
        param("a.mp4", 1.0, 0.0, id="zero-length"),
    ],
)
def test_a_malformed_progress_write_is_refused_before_reading(
    tmp_path: Path, relative: str, position: float, duration: float
) -> None:
    """A key that could reach outside the resource, or a position or length that is not a finite
    non-negative number, is refused and the record untouched.

    **Test steps:**

    * record malformed progress
    * verify it raises and the file's bytes are unchanged
    """
    path = make_tutorial(tmp_path / "t", ["a.mp4"])
    before = path.read_bytes()

    with raises(ValueError):
        record_progress(path, "admin", relative, position, duration)

    assert path.read_bytes() == before


def test_progress_is_refused_on_a_record_that_is_not_a_tutorial(tmp_path: Path) -> None:
    """Watch progress lives in the tutorial block; another type has nowhere to keep it.

    **Test steps:**

    * record progress on a reference-images record
    * verify it raises and the file is unchanged
    """
    path = make_tutorial(tmp_path / "t", ["a.mp4"], resource_type="reference_images")
    before = path.read_bytes()

    with raises(ValueError, match="tutorials only"):
        record_progress(path, "admin", "a.mp4", 1.0, 10.0)

    assert path.read_bytes() == before


# endregion


# region record_progress -- the file's viewed
@mark.parametrize(
    ("position", "viewed"),
    [
        param(99.0, True, id="one-second-short-is-the-end"),
        param(98.9, False, id="more-than-a-second-short-is-not"),
        param(100.0, True, id="at-the-end"),
    ],
)
def test_reaching_the_end_marks_the_file_viewed(tmp_path: Path, position: float, viewed: bool) -> None:
    """A player stopping on the last frame reports a position a frame or two short of the container's
    length, so within a second of the end counts as the end.

    **Test steps:**

    * record a position near the end of a 100 s file
    * verify the entry's ``viewed``
    """
    path = make_tutorial(tmp_path / "t", ["a.mp4", "b.mp4"])

    assert record_progress(path, "admin", "a.mp4", position, 100.0).viewed is viewed


def test_the_measured_length_decides_the_end_over_the_players(tmp_path: Path) -> None:
    """``videos`` is the length's home and wins whenever both exist ([[field-schema#watch-progress]]).

    **Test steps:**

    * record a position at the measured end of a file the player reports as longer
    * verify the file is viewed
    """
    path = make_tutorial(tmp_path / "t", ["a.mp4", "b.mp4"], block={"videos": {"a.mp4": {"duration": 100.0}}})

    assert record_progress(path, "admin", "a.mp4", 99.5, 200.0).viewed is True


def test_with_the_setting_off_reaching_the_end_marks_nothing(tmp_path: Path) -> None:
    """The first auto-viewed rule sits behind a setting.

    **Test steps:**

    * record a position at the end with the file rule off
    * verify the file is not viewed
    """
    path = make_tutorial(tmp_path / "t", ["a.mp4"])
    rules = WatchRules(mark_file_viewed_at_end=False)

    assert record_progress(path, "admin", "a.mp4", 100.0, 100.0, rules=rules).viewed is False


def test_a_rewatch_moves_the_position_and_keeps_viewed(tmp_path: Path) -> None:
    """``position`` and ``viewed`` are independent: reviewing a finished video resumes where the review
    stopped and leaves it watched.

    **Test steps:**

    * watch a file to the end, then record an early position
    * verify the entry is at the early position and still viewed
    """
    path = make_tutorial(tmp_path / "t", ["a.mp4", "b.mp4"])
    record_progress(path, "admin", "a.mp4", 100.0, 100.0)

    entry = record_progress(path, "admin", "a.mp4", 10.0, 100.0)

    assert entry == ProgressEntry(10.0, 100.0, True, 0)


def test_the_checkbox_sets_or_clears_viewed_whatever_the_position(tmp_path: Path) -> None:
    """An explicit ``viewed`` is the user's hand on the checkbox, stored as given.

    **Test steps:**

    * clear a file watched to the end, then set one never played past the start
    * verify each entry holds the flag given
    """
    path = make_tutorial(tmp_path / "t", ["a.mp4", "b.mp4", "c.mp4"])
    record_progress(path, "admin", "a.mp4", 100.0, 100.0)

    assert record_progress(path, "admin", "a.mp4", 100.0, 100.0, viewed=False).viewed is False
    assert record_progress(path, "admin", "b.mp4", 0.0, None, viewed=True).viewed is True


# endregion


# region record_progress -- the tutorial's viewed
def test_the_tutorial_is_viewed_when_its_last_file_becomes_viewed(tmp_path: Path) -> None:
    """The second rule checks the tutorial at the moment its last file becomes viewed, and not before.

    **Test steps:**

    * watch the first of two files to the end, then the second
    * verify the tutorial is unviewed after the first and viewed after the second
    """
    path = make_tutorial(tmp_path / "t", ["01/a.mp4", "02/b.mp4", "notes.pdf"])

    record_progress(path, "admin", "01/a.mp4", 10.0, 10.0)
    assert "viewed" not in users_of(path)["admin"]

    record_progress(path, "admin", "02/b.mp4", 10.0, 10.0)
    assert users_of(path)["admin"]["viewed"] is True


def test_with_the_setting_off_the_tutorial_is_left_alone(tmp_path: Path) -> None:
    """The tutorial rule sits behind its own setting.

    **Test steps:**

    * watch a tutorial's only file to the end with the tutorial rule off
    * verify the file is viewed and the tutorial is not
    """
    path = make_tutorial(tmp_path / "t", ["a.mp4"])
    rules = WatchRules(mark_tutorial_viewed_on_last_file=False)

    record_progress(path, "admin", "a.mp4", 10.0, 10.0, rules=rules)

    assert users_of(path)["admin"] == {
        "progress": {"a.mp4": {"position": 10.0, "duration": 10.0, "size": 0, "viewed": True}}
    }


def test_a_tutorial_unchecked_by_hand_stays_unchecked(tmp_path: Path) -> None:
    """The rule acts on a file *becoming* viewed, never as a standing rule: a tutorial the user unchecked
    while all its files are viewed stays unchecked through later progress writes.

    **Test steps:**

    * hold a tutorial whose files are all viewed and whose own flag the user cleared
    * record more progress on a viewed file
    * verify the tutorial is still unchecked
    """
    path = make_tutorial(
        tmp_path / "t",
        ["a.mp4"],
        block={"users": {"admin": {"viewed": False, "progress": {"a.mp4": {"position": 10.0, "viewed": True}}}}},
    )

    record_progress(path, "admin", "a.mp4", 10.0, 10.0)

    assert users_of(path)["admin"]["viewed"] is False


def test_unchecking_a_file_never_unchecks_the_tutorial(tmp_path: Path) -> None:
    """The tutorial's ``viewed`` is the user's verdict; a file's flag going off does not take it back.

    **Test steps:**

    * watch a tutorial's only file to the end, then clear the file by hand
    * verify the tutorial is still viewed
    """
    path = make_tutorial(tmp_path / "t", ["a.mp4"])
    record_progress(path, "admin", "a.mp4", 10.0, 10.0)

    record_progress(path, "admin", "a.mp4", 10.0, 10.0, viewed=False)

    assert users_of(path)["admin"]["viewed"] is True


def test_a_missing_files_entry_counts_toward_the_tutorial(tmp_path: Path) -> None:
    """Every missing file with an entry counts as one of the tutorial's files: watching every file on disk
    is not enough while a deleted one with an entry stays unwatched.

    **Test steps:**

    * hold an unviewed entry for a file no longer on disk
    * watch the one file on disk to the end, and verify the tutorial is not viewed
    * check the missing file by hand, and verify the tutorial is viewed
    """
    path = make_tutorial(
        tmp_path / "t", ["a.mp4"], block={"users": {"admin": {"progress": {"gone.mp4": {"position": 3.0}}}}}
    )

    record_progress(path, "admin", "a.mp4", 10.0, 10.0)
    assert "viewed" not in users_of(path)["admin"]

    record_progress(path, "admin", "gone.mp4", 3.0, None, viewed=True)
    assert users_of(path)["admin"]["viewed"] is True


def test_a_resource_that_will_not_list_skips_the_tutorial_rule(tmp_path: Path, mocker: MockerFixture) -> None:
    """A walk that cannot list the resource -- a share gone mid-write -- must not fail the progress write;
    the tutorial rule is skipped.

    **Test steps:**

    * make the content walk refuse
    * watch the only file to the end
    * verify the file is viewed and the tutorial is not
    """
    path = make_tutorial(tmp_path / "t", ["a.mp4"])
    mocker.patch("rehuco_core.watch_progress.content_video_files", side_effect=ContentUnreachableError([tmp_path]))

    entry = record_progress(path, "admin", "a.mp4", 10.0, 10.0)

    assert entry.viewed is True
    assert "viewed" not in users_of(path)["admin"]


# endregion


# region concurrent writers
def test_a_progress_write_and_a_metadata_write_both_survive_in_either_order(tmp_path: Path) -> None:
    """Progress and metadata written through the merge each re-read what the other wrote, so neither
    clobbers the other ([[field-schema#watch-progress]]).

    **Test steps:**

    * record progress, then merge a metadata change, then record progress again
    * verify both progress entries and the metadata change are on disk
    """
    path = make_tutorial(tmp_path / "t", ["a.mp4", "b.mp4"])

    record_progress(path, "admin", "a.mp4", 1.0, 10.0)
    merge_write(path, lambda doc: doc.set_active_field("level", "advanced"), username="admin", touch_updated=True)
    record_progress(path, "admin", "b.mp4", 2.0, 10.0)

    assert json.loads(path.read_text(encoding="utf-8"))["tutorial"]["level"] == "advanced"
    assert set(users_of(path)["admin"]["progress"]) == {"a.mp4", "b.mp4"}


def test_a_progress_write_leaves_an_open_documents_unsaved_edit_alone(tmp_path: Path) -> None:
    """The agent's open document keeps its unsaved edit through a progress write -- the write goes to disk
    and never through, or into, the open copy.

    **Test steps:**

    * open the record and edit it without saving
    * record progress
    * verify the open copy still holds its edit and the disk holds the progress
    """
    path = make_tutorial(tmp_path / "t", ["a.mp4"])
    open_document = RehuDocument.load(path)
    open_document.set_active_field("level", "beginner")

    record_progress(path, "admin", "a.mp4", 1.0, 10.0)

    assert open_document.active_field("level") == "beginner"
    assert read_progress(open_document, "admin") == {}
    assert "a.mp4" in users_of(path)["admin"]["progress"]


# endregion


# region videos and progress maps
def test_the_videos_map_round_trips_sorted(tmp_path: Path) -> None:
    """A Measure's map is written whole with sorted keys, an unknown size left out, and read back as given.

    **Test steps:**

    * set an unsorted map holding a file with no frame size
    * verify the stored order and payload, and the read-back facts
    """
    doc = RehuDocument.load(make_tutorial(tmp_path / "t", []))
    measured = {"b.mp4": VideoFacts(2.0, 1280, 720), "a.mp4": VideoFacts(1.5)}

    set_videos(doc, measured)

    assert list(doc.active_field("videos")) == ["a.mp4", "b.mp4"]
    assert doc.active_field("videos")["a.mp4"] == {"duration": 1.5}
    assert read_videos(doc) == measured


def test_an_empty_measure_removes_the_videos_map(tmp_path: Path) -> None:
    """A tutorial left with no video has no map rather than an empty one.

    **Test steps:**

    * set an empty map over a stored one
    * verify the key is gone
    """
    doc = RehuDocument.load(make_tutorial(tmp_path / "t", [], block={"videos": {"a.mp4": {"duration": 1.0}}}))

    set_videos(doc, {})

    assert doc.active_field("videos") is None


def test_malformed_stored_maps_read_as_defaults_and_stay_on_disk(tmp_path: Path) -> None:
    """Data from another build, node or hand edit is read defensively: an entry that is not an object is
    skipped, a malformed value reads as its default, and none of it is rewritten by reading.

    **Test steps:**

    * hold malformed ``videos`` and ``progress`` entries
    * verify what reads back, and that the payload is unchanged
    """
    block = {
        "videos": {"a.mp4": {"duration": "long"}, "b.mp4": "junk", "c.mp4": {"duration": 3, "width": True}},
        "users": {"admin": {"progress": {"a.mp4": {"position": "x", "duration": -1, "viewed": 1}, "b.mp4": []}}},
    }
    doc = RehuDocument.load(make_tutorial(tmp_path / "t", [], block=block))
    before = json.dumps(doc.data, sort_keys=True)

    assert read_videos(doc) == {"c.mp4": VideoFacts(3.0, None, None)}
    assert read_progress(doc, "admin") == {"a.mp4": ProgressEntry(0.0, None, False)}
    assert json.dumps(doc.data, sort_keys=True) == before


def test_forgetting_the_last_entry_removes_the_progress_key(tmp_path: Path) -> None:
    """``None`` forgets one entry; forgetting the last leaves no empty ``progress`` behind.

    **Test steps:**

    * forget one of two entries, then the other
    * verify the remaining entry after the first, and no key after the second
    """
    block = {"users": {"admin": {"progress": {"a.mp4": {"position": 1.0}, "b.mp4": {"position": 2.0}}}}}
    doc = RehuDocument.load(make_tutorial(tmp_path / "t", [], block=block))

    set_progress_entry(doc, "admin", "a.mp4", None)
    assert list(doc.user_field("admin", "progress")) == ["b.mp4"]

    set_progress_entry(doc, "admin", "b.mp4", None)
    assert doc.user_field("admin", "progress") is None


# endregion


# region watch_totals
def test_a_viewed_file_counts_its_full_length_during_a_rewatch() -> None:
    """A ``viewed`` file counts its whole length even while a rewatch has its position at 20%.

    **Test steps:**

    * total a viewed file at 20% and an unviewed one at half
    * verify the watched seconds
    """
    totals = watch_totals(
        ["a.mp4", "b.mp4"],
        {"a.mp4": VideoFacts(100.0), "b.mp4": VideoFacts(100.0)},
        {"a.mp4": ProgressEntry(20.0, None, True), "b.mp4": ProgressEntry(50.0)},
    )

    assert totals[""] == WatchTotals(watched=150.0, length=200.0, unknown_length=0, files=2)
    assert totals[""].remaining == approx(50.0)


def test_folders_sum_their_subfolders() -> None:
    """A folder and the resource sum their files recursively; a file never played counts its length and
    nothing watched.

    **Test steps:**

    * total files at the root, in a folder and in a subfolder
    * verify each folder's sums
    """
    measured = {"a.mp4": VideoFacts(10.0), "01/b.mp4": VideoFacts(20.0), "01/x/c.mp4": VideoFacts(30.0)}
    entries = {"01/x/c.mp4": ProgressEntry(30.0, None, True)}

    totals = watch_totals(list(measured), measured, entries)

    assert totals[""] == WatchTotals(30.0, 60.0, 0, 3)
    assert totals["01"] == WatchTotals(30.0, 50.0, 0, 2)
    assert totals["01/x"] == WatchTotals(30.0, 30.0, 0, 1)


def test_lengths_come_from_videos_first_then_the_entry() -> None:
    """``videos`` wins over an entry's own length, the entry is the fallback, and a file with neither
    counts only as unknown; a position past a short length is capped at it.

    **Test steps:**

    * total a measured file whose entry disagrees, an unmeasured played one, and an unmeasured unplayed one
    * verify the sums and the unknown count
    """
    totals = watch_totals(
        ["a.mp4", "b.mp4", "c.mp4"],
        {"a.mp4": VideoFacts(10.0)},
        {"a.mp4": ProgressEntry(15.0, 40.0), "b.mp4": ProgressEntry(5.0, 20.0)},
    )

    assert totals[""] == WatchTotals(watched=15.0, length=30.0, unknown_length=1, files=3)


def test_a_missing_files_entry_still_counts() -> None:
    """A file that is gone keeps counting through its entry: the history worth keeping.

    **Test steps:**

    * total one file on disk and an entry for one that is not
    * verify both count
    """
    totals = watch_totals(["a.mp4"], {"a.mp4": VideoFacts(10.0)}, {"gone/b.mp4": ProgressEntry(5.0, 20.0, True)})

    assert totals[""] == WatchTotals(watched=20.0, length=30.0, unknown_length=0, files=2)
    assert totals["gone"] == WatchTotals(20.0, 20.0, 0, 1)


def test_an_empty_tutorial_totals_nothing() -> None:
    """The resource's total is always there, zero for a tutorial with nothing to watch.

    **Test steps:**

    * total no files
    * verify the one zero total
    """
    assert watch_totals([], {}, {}) == {"": WatchTotals()}


# endregion


# region the file's size, missing entries and forgetting (#411)
def test_a_progress_write_records_the_files_size(tmp_path: Path) -> None:
    """The entry carries the file's size off disk -- the evidence a rename is told by once the file is gone.

    **Test steps:**

    * record progress on a 5-byte file
    * verify the stored entry's size
    """
    path = make_tutorial(tmp_path / "t", [])
    (tmp_path / "t" / "a.mp4").write_bytes(b"12345")

    entry = record_progress(path, "admin", "a.mp4", 1.0, 10.0)

    assert entry.size == 5
    assert users_of(path)["admin"]["progress"]["a.mp4"]["size"] == 5


def test_a_file_gone_at_write_time_keeps_its_recorded_size(tmp_path: Path) -> None:
    """A write on a file that can no longer be read keeps the size stored before, and records none when there was
    none.

    **Test steps:**

    * record progress on a file, delete it, record again
    * record progress on a file that never existed
    * verify the first keeps its size and the second has none
    """
    path = make_tutorial(tmp_path / "t", [])
    (tmp_path / "t" / "a.mp4").write_bytes(b"123")
    record_progress(path, "admin", "a.mp4", 1.0, 10.0)
    (tmp_path / "t" / "a.mp4").unlink()

    assert record_progress(path, "admin", "a.mp4", 2.0, 10.0).size == 3
    assert record_progress(path, "admin", "b.mp4", 2.0, 10.0).size is None
    assert "size" not in users_of(path)["admin"]["progress"]["b.mp4"]


@mark.parametrize("size", [param(-1, id="negative"), param(1.5, id="float"), param(True, id="bool"), param("3")])
def test_a_malformed_stored_size_reads_as_unknown(size: object) -> None:
    """A size another build or a hand edit spelled wrong reads as unknown -- which keeps the entry from moving --
    rather than as a size that could match the wrong file.

    **Test steps:**

    * read an entry with a malformed size
    * verify it reads as ``None``
    """
    assert ProgressEntry.from_stored({"position": 1.0, "size": size}).size is None


def test_missing_entries_are_those_whose_file_is_not_on_disk() -> None:
    """Missing is derived from the listing, never stored: an entry whose key is not among the files on disk.

    **Test steps:**

    * list two files on disk against three entries
    * verify the one missing key
    """
    entries = {"a.mp4": ProgressEntry(1.0), "gone/c.mp4": ProgressEntry(2.0), "b.mp4": ProgressEntry(3.0)}

    assert missing_progress_keys(["a.mp4", "b.mp4", "d.mp4"], entries) == ["gone/c.mp4"]


def test_forgetting_removes_only_that_entry(tmp_path: Path) -> None:
    """Forget removes one entry by hand: the user's other entries, other users' and ``updated`` stay as stored.

    **Test steps:**

    * forget one of a user's two entries, beside another user's entry under the same key
    * verify only that entry went and ``updated`` is unchanged
    """
    path = make_tutorial(
        tmp_path / "t",
        [],
        block={
            "users": {
                "admin": {"progress": {"a.mp4": {"position": 1.0}, "b.mp4": {"position": 2.0}}},
                "bob": {"progress": {"a.mp4": {"position": 3.0}}},
            }
        },
    )

    assert forget_progress(path, "admin", "a.mp4") is True

    assert users_of(path) == {
        "admin": {"progress": {"b.mp4": {"position": 2.0}}},
        "bob": {"progress": {"a.mp4": {"position": 3.0}}},
    }
    assert json.loads(path.read_text(encoding="utf-8"))["core"]["updated"] == UPDATED


def test_forgetting_an_entry_that_is_not_there_says_so(tmp_path: Path) -> None:
    """Forgetting a key with no entry changes nothing and answers ``False``.

    **Test steps:**

    * forget a key the user has no entry for
    * verify the answer and that the other user's entry stays
    """
    path = make_tutorial(tmp_path / "t", [], block={"users": {"bob": {"progress": {"a.mp4": {"position": 3.0}}}}})

    assert forget_progress(path, "admin", "a.mp4") is False

    assert users_of(path) == {"bob": {"progress": {"a.mp4": {"position": 3.0}}}}


def test_forgetting_removes_a_stored_key_that_is_not_a_content_key(tmp_path: Path) -> None:
    """A key a hand edit wrote wrong names no file and can never be reattached; forgetting resolves no path, so it
    is the one way such an entry leaves the record.

    **Test steps:**

    * hold an entry under ``../a.mp4``
    * forget it
    * verify it is gone, and with it all of the user's state: their sidecar holds nothing
    """
    path = make_tutorial(tmp_path / "t", [], block={"users": {"admin": {"progress": {"../a.mp4": {"position": 1}}}}})

    assert forget_progress(path, "admin", "../a.mp4") is True

    assert not users_of(path)


# endregion
