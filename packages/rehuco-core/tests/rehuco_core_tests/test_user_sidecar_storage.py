"""Tests for a record stored as its ``.rehu`` and one sidecar per user (#513, [[data-model#single-file]]): saves move
the per-user maps out and write each file only when it changes, reads join them back, and scans, listings, renames and
the notifier know the sidecar as the record's own."""

import json
from pathlib import Path
from typing import Any, Final

from pytest import mark, raises
from pytest_mock import MockerFixture
from rehuco_core import (
    CURRENT_REHUSER_VERSION,
    Changed,
    DirectoryClassifier,
    FileKind,
    Records,
    RehuDocument,
    ResourceKey,
    UserSidecarError,
    enumerate_content_files,
    record_progress,
    rename_rehu_resource,
)
from rehuco_core.notify import ChangeCoalescer, RawChange, RawChangeKind
from rehuco_core.user_sidecars import sidecar_text

USERS: Final = "users"

RATED: Final = {
    "format_version": 2,
    "core": {"id": "00000000-0000-0000-0000-000000000001", "type": "tutorial", "title": "Lesson"},
    "tutorial": {
        "format_version": 2,
        USERS: {"ioan": {"rating": 4}, "unknown": {"viewed": True}, "public": {"learning_paths": []}},
    },
}
"""A record saved before the sidecars: its per-user state still inside it."""


def write_record(path: Path, payload: dict[str, Any]) -> None:
    """Write a record's payload as its file.

    :param path: the record.
    :param payload: what it holds.
    """
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    """A JSON file's value.

    :param path: the file.
    :returns: its value.
    """
    return json.loads(path.read_text(encoding="utf-8"))


def bare_record(path: Path) -> None:
    """Write a tutorial record holding no per-user state.

    :param path: the record.
    """
    write_record(path, {**RATED, "tutorial": {"format_version": 2}})


# region Saving and reading


def test_a_save_moves_the_records_maps_into_one_sidecar_per_scope(tmp_path: Path) -> None:
    """The one-time move: a record still carrying its maps is written without them, each scope -- the user's own,
    ``unknown``'s and ``public``'s -- into its own sidecar, and reads back the same.

    **Test steps:**

    * write a record whose block carries three scopes, and load it as ``ioan``
    * save it
    * verify the record holds no map, each scope's sidecar holds its fields, and a fresh load holds all three
    """
    record = tmp_path / "info.rehu"
    write_record(record, RATED)
    document = RehuDocument.load(record, username="ioan")

    document.save()

    assert USERS not in read_json(record)["tutorial"]
    assert {name: read_json(tmp_path / name) for name in sorted(p.name for p in tmp_path.glob("*.rehuser"))} == {
        "info.user-ioan.rehuser": {"format_version": CURRENT_REHUSER_VERSION, "tutorial": {"rating": 4}},
        "info.user-public.rehuser": {"format_version": CURRENT_REHUSER_VERSION, "tutorial": {"learning_paths": []}},
        "info.user-unknown.rehuser": {"format_version": CURRENT_REHUSER_VERSION, "tutorial": {"viewed": True}},
    }
    assert RehuDocument.load(record, username="ioan").active_block[USERS] == RATED["tutorial"][USERS]


def test_a_record_with_no_per_user_state_gets_no_sidecar(tmp_path: Path) -> None:
    """Nothing per-user, nothing beside the record.

    **Test steps:**

    * save a record holding no per-user state
    * verify the folder holds the record alone
    """
    record = tmp_path / "info.rehu"
    bare_record(record)

    RehuDocument.load(record, username="ioan").save()

    assert [path.name for path in tmp_path.iterdir()] == ["info.rehu"]


def test_a_per_user_edit_leaves_the_record_file_untouched(tmp_path: Path) -> None:
    """A rating describes one person: the save writes that person's sidecar, and the file everyone edits keeps its
    bytes and its modification time.

    **Test steps:**

    * save a record once so its maps are out, and note its text and modification time
    * rate it and save again
    * verify the record is byte- and time-identical, and the sidecar holds the new rating
    """
    record = tmp_path / "info.rehu"
    write_record(record, RATED)
    RehuDocument.load(record, username="ioan").save()
    before = record.read_text(encoding="utf-8"), record.stat().st_mtime_ns
    document = RehuDocument.load(record, username="ioan")

    document.set_active_user_field("rating", 2)
    document.save()

    assert (record.read_text(encoding="utf-8"), record.stat().st_mtime_ns) == before
    assert read_json(tmp_path / "info.user-ioan.rehuser")["tutorial"] == {"rating": 2}


def test_a_details_edit_leaves_every_sidecar_untouched(tmp_path: Path) -> None:
    """A details save writes the record; no sidecar's text changes, so none is written.

    **Test steps:**

    * save a record once so its maps are out, and note each sidecar's modification time
    * change its title and save again
    * verify the title on disk and every sidecar's modification time unchanged
    """
    record = tmp_path / "info.rehu"
    write_record(record, RATED)
    RehuDocument.load(record, username="ioan").save()
    before = {path.name: path.stat().st_mtime_ns for path in tmp_path.glob("*.rehuser")}
    document = RehuDocument.load(record, username="ioan")

    document.title = "Renamed"
    document.save()

    assert RehuDocument.load(record, username="ioan").title == "Renamed"
    assert {path.name: path.stat().st_mtime_ns for path in tmp_path.glob("*.rehuser")} == before


BAD_SIDECARS: Final = [
    ("{not json", "invalid JSON"),
    (json.dumps({"format_version": CURRENT_REHUSER_VERSION + 1, "tutorial": {"future": 1}}), "newer than this build"),
]
"""Sidecars this build cannot read, and the words their reason carries."""


@mark.parametrize(("text", "message"), BAD_SIDECARS)
def test_a_bad_sidecar_of_another_user_locks_only_its_own_scope(tmp_path: Path, text: str, message: str) -> None:
    """The issue's *done when*: a record beside a malformed or newer ``info.user-bob.rehuser`` opens for ``alice`` with
    its details and her own state editable, says which sidecar it could not read, and a save leaves bob's file
    byte-identical.

    **Test steps:**

    * save a record rated by ``alice``, and put a bad sidecar for ``bob`` beside it
    * load it as ``alice`` through ``Records``
    * verify no lock reason, bob's file named with its cause, and bob's scope left out
    * change the title, rate it and save
    * verify the title and alice's rating on disk, and bob's file byte-identical
    """
    record = tmp_path / "info.rehu"
    write_record(record, {**RATED, "tutorial": {"format_version": 2, USERS: {"alice": {"rating": 1}}}})
    RehuDocument.load(record, username="alice").save()
    bob = tmp_path / "info.user-bob.rehuser"
    bob.write_text(text, encoding="utf-8")
    records = Records()

    loaded = records.load(ResourceKey(record), username="alice", unknown_username="unknown")

    assert not loaded.lock_reasons
    assert not loaded.document.own_sidecar_unreadable
    assert [(sidecar.name, sidecar.slug) for sidecar in loaded.document.unreadable_sidecars] == [
        ("info.user-bob.rehuser", "bob")
    ]
    assert message in loaded.document.unreadable_sidecars[0].reason
    assert "bob" not in loaded.document.active_block[USERS]
    loaded.document.title = "Renamed"
    loaded.document.set_active_user_field("rating", 5)
    records.save(ResourceKey(record), loaded.document, loaded.version, username="alice", overwrite=False)

    saved = RehuDocument.load(record, username="alice")
    assert (saved.title, saved.active_user_field("rating")) == ("Renamed", 5)
    assert bob.read_text(encoding="utf-8") == text


@mark.parametrize("text", [text for text, _ in BAD_SIDECARS])
def test_a_bad_sidecar_is_not_written_over_by_the_scope_the_record_still_carries(tmp_path: Path, text: str) -> None:
    """A record saved before the sidecars still carries bob's map; it is left out with his scope, so the one-time move
    never writes it over his unreadable file.

    **Test steps:**

    * write a record still carrying ``bob``'s map, and a bad sidecar for him
    * load it as ``alice`` and save
    * verify bob's file byte-identical and his map gone from the record
    """
    record = tmp_path / "info.rehu"
    write_record(record, {**RATED, "tutorial": {"format_version": 2, USERS: {"bob": {"rating": 2}}}})
    bob = tmp_path / "info.user-bob.rehuser"
    bob.write_text(text, encoding="utf-8")
    document = RehuDocument.load(record, username="alice")

    document.save()

    assert bob.read_text(encoding="utf-8") == text
    assert USERS not in read_json(record)["tutorial"]


@mark.parametrize(("text", "message"), BAD_SIDECARS)
def test_a_bad_sidecar_of_the_current_user_locks_per_user_editing_only(tmp_path: Path, text: str, message: str) -> None:
    """The record opens editable, the details save, and the user's own state is refused rather than written over the
    file -- until the file is fixed and the record reloaded.

    **Test steps:**

    * put a bad sidecar for ``alice`` beside a record, and load it as her
    * verify no lock reason and ``own_sidecar_unreadable``
    * save a new title, and write her progress
    * verify the title saved, the progress refused with her file byte-identical
    * fix her sidecar and reload
    * verify the document reads her state and no longer names it
    """
    record = tmp_path / "info.rehu"
    bare_record(record)
    (tmp_path / "a.mp4").write_bytes(b"x" * 10)
    alice = tmp_path / "info.user-alice.rehuser"
    alice.write_text(text, encoding="utf-8")
    document = RehuDocument.load(record, username="alice")

    assert not document.lock_reasons
    assert document.own_sidecar_unreadable
    document.title = "Renamed"
    document.save()
    with raises(UserSidecarError, match=message):
        record_progress(record, "alice", "a.mp4", 3.0, 10.0, current_username="alice")

    assert RehuDocument.load(record, username="alice").title == "Renamed"
    assert alice.read_text(encoding="utf-8") == text
    alice.write_text(sidecar_text({"tutorial": {"rating": 3}}), encoding="utf-8")
    document.reload()
    assert document.unreadable_sidecars == ()
    assert not document.own_sidecar_unreadable
    assert document.active_user_field("rating") == 3


def test_a_sidecar_that_turns_readable_changes_the_records_version(tmp_path: Path) -> None:
    """An unreadable sidecar adds nothing to the version, so fixing it is a change a save merges rather than misses.

    **Test steps:**

    * load a record beside a bad sidecar for ``bob``, and note its version
    * fix his sidecar and load again
    * verify the versions differ
    """
    record = tmp_path / "info.rehu"
    bare_record(record)
    bob = tmp_path / "info.user-bob.rehuser"
    bob.write_text("{not json", encoding="utf-8")
    records = Records()
    before = records.load(ResourceKey(record), username="alice", unknown_username="unknown").version

    bob.write_text(sidecar_text({"tutorial": {"rating": 2}}), encoding="utf-8")
    after = records.load(ResourceKey(record), username="alice", unknown_username="unknown").version

    assert before is not None and after is not None
    assert before.file_hash != after.file_hash


# endregion

# region Saves beside other writers


def test_watching_while_another_agent_edits_the_details_conflicts_with_neither(tmp_path: Path) -> None:
    """The issue's first *done when*: a progress write lands between another agent's read and its details save; the
    save merges it and neither side conflicts.

    **Test steps:**

    * save a record with a video once, so its file is in a save's own layout, and open it as ``bob`` for a details
      edit
    * record ``ioan``'s progress on the video
    * save ``bob``'s new title
    * verify the title and ``ioan``'s progress are both on disk, and the progress never touched the record
    """
    record = tmp_path / "info.rehu"
    bare_record(record)
    RehuDocument.load(record, username="bob").save()
    (tmp_path / "a.mp4").write_bytes(b"x" * 10)
    records = Records()
    opened = records.load(ResourceKey(record), username="bob", unknown_username="unknown")
    before = record.stat().st_mtime_ns

    record_progress(record, "ioan", "a.mp4", 3.0, 10.0, current_username="ioan")
    assert record.stat().st_mtime_ns == before
    opened.document.title = "Bob's"
    records.save(ResourceKey(record), opened.document, opened.version, username="bob", overwrite=False)

    saved = RehuDocument.load(record, username="ioan")
    assert saved.title == "Bob's"
    assert saved.active_block[USERS]["ioan"]["progress"]["a.mp4"]["position"] == 3.0


def test_a_change_made_to_a_sidecar_alone_is_merged_not_written_over(tmp_path: Path) -> None:
    """The version covers the sidecars: a user's own other device writes their sidecar after this one read it, and
    this save merges that field rather than writing back the stale scope it holds.

    **Test steps:**

    * open a record as ``ioan``
    * on "another device", mark it viewed in ``ioan``'s sidecar
    * rate it here and save
    * verify ``ioan``'s sidecar holds both the rating and the viewed flag
    """
    record = tmp_path / "info.rehu"
    write_record(record, RATED)
    RehuDocument.load(record, username="ioan").save()
    records = Records()
    opened = records.load(ResourceKey(record), username="ioan", unknown_username="unknown")
    elsewhere = RehuDocument.load(record, username="ioan")
    elsewhere.set_active_user_field("viewed", True)
    elsewhere.save(touch_updated=False)

    opened.document.set_active_user_field("rating", 5)
    saved = records.save(ResourceKey(record), opened.document, opened.version, username="ioan", overwrite=False)

    assert saved.users_merged
    assert read_json(tmp_path / "info.user-ioan.rehuser")["tutorial"] == {"rating": 5, "viewed": True}


def test_a_records_signature_moves_when_only_a_sidecar_changes(tmp_path: Path) -> None:
    """Another device's progress is a change to the record as read: its signature covers its sidecars.

    **Test steps:**

    * save a record once so its maps are out, and take its signature
    * rewrite ``ioan``'s sidecar, one byte longer
    * verify the signature moved while the record file did not
    """
    record = tmp_path / "info.rehu"
    write_record(record, RATED)
    RehuDocument.load(record, username="ioan").save()
    records = Records()
    before = records.signature(ResourceKey(record))
    record_before = record.stat().st_mtime_ns

    sidecar = tmp_path / "info.user-ioan.rehuser"
    sidecar.write_text(sidecar.read_text(encoding="utf-8") + " ", encoding="utf-8")

    assert records.signature(ResourceKey(record)) != before
    assert record.stat().st_mtime_ns == record_before


def test_a_sidecar_gone_between_the_listing_and_its_stat_is_left_out_of_the_signature(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    """A sidecar deleted as the signature is taken changes nothing the record holds: the signature is the record's
    own, never ``None`` -- which would read as the record gone.

    **Test steps:**

    * list, beside a record, a sidecar that is not there
    * verify the signature is the record's modification time and size
    """
    record = tmp_path / "info.rehu"
    bare_record(record)
    mocker.patch("rehuco_core.access.records.user_sidecar_paths", return_value={"ioan": tmp_path / "gone.rehuser"})

    status = record.stat()
    assert Records().signature(ResourceKey(record)) == (status.st_mtime_ns, status.st_size)


def test_a_sidecar_that_cannot_be_statted_is_left_out_of_the_signature(tmp_path: Path, mocker: MockerFixture) -> None:
    """A sidecar the share refuses says nothing about the record, which is still there: its signature is the
    record's own, never ``None``, which a watch would report as the record gone.

    **Test steps:**

    * list, beside a record, a sidecar whose ``stat`` is refused
    * verify the signature is the record's modification time and size
    """
    record = tmp_path / "info.rehu"
    bare_record(record)
    refused = mocker.Mock(spec=Path)
    refused.stat.side_effect = PermissionError("refused")
    mocker.patch("rehuco_core.access.records.user_sidecar_paths", return_value={"ioan": refused})

    status = record.stat()
    assert Records().signature(ResourceKey(record)) == (status.st_mtime_ns, status.st_size)


def test_a_sidecar_gone_between_the_listing_and_its_read_is_left_out_of_the_stored_files(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    """The On Disk view shows what is there: a sidecar deleted as it is read is simply not among the files.

    **Test steps:**

    * list, beside a record, a sidecar that is not there
    * verify the stored files are the record alone
    """
    record = tmp_path / "info.rehu"
    bare_record(record)
    mocker.patch("rehuco_core.access.records.user_sidecar_paths", return_value={"ioan": tmp_path / "gone.rehuser"})

    assert Records().stored_files(ResourceKey(record)) == [("info.rehu", record.read_text(encoding="utf-8"))]


# endregion

# region Known as the record's own


def test_a_sidecar_is_no_content_wherever_it_sits(tmp_path: Path) -> None:
    """The content walk -- sizes, checksums, videos -- leaves every sidecar out: the record's own, and a nested
    file-scoped record's, which would otherwise count as the enclosing folder's content.

    **Test steps:**

    * put ``info.rehu``, its sidecar, a video, and a file-scoped ``extra.rehu`` with its sidecar in one folder
    * walk the directory-scoped record's content
    * verify the video alone
    """
    record = tmp_path / "info.rehu"
    bare_record(record)
    bare_record(tmp_path / "extra.rehu")
    for name in ("info.user-ioan.rehuser", "extra.user-ioan.rehuser", "lesson.mp4"):
        (tmp_path / name).write_bytes(b"x")

    assert [path.name for path in enumerate_content_files(record).files] == ["lesson.mp4"]


def test_a_listing_names_a_sidecar_as_its_records_user_state(tmp_path: Path) -> None:
    """The Files listing and the Roots view show a sidecar as what it is: this record's user state, or another
    record's bookkeeping.

    **Test steps:**

    * put ``lesson.rehu`` and ``other.rehu``, each with a sidecar, in a folder
    * classify the folder from ``lesson.rehu``
    * verify ``lesson``'s sidecar is its user state and ``other``'s is a foreign sidecar
    """
    record = tmp_path / "lesson.rehu"
    bare_record(record)
    bare_record(tmp_path / "other.rehu")
    for name in ("lesson.user-ioan.rehuser", "other.user-bob.rehuser"):
        (tmp_path / name).write_bytes(b"{}")

    listing = DirectoryClassifier(record).classify(tmp_path)

    kinds = {entry.name: entry.kind for entry in listing.entries}
    assert kinds["lesson.user-ioan.rehuser"] is FileKind.OWN_USER_STATE
    assert kinds["other.user-bob.rehuser"] is FileKind.FOREIGN_SIDECAR


def test_renaming_a_resource_carries_every_users_sidecar(tmp_path: Path) -> None:
    """The issue's second *done when*: a file-scoped rename takes each user's sidecar to the new stem, and a folder
    rename takes them with the folder.

    **Test steps:**

    * put ``lesson.rehu`` with two users' sidecars and a video, and a folder ``course`` with ``info.rehu`` and one
    * rename ``lesson`` to ``intro`` and ``course`` to ``class``
    * verify every sidecar followed its record, and each reads back with its record
    """
    record = tmp_path / "lesson.rehu"
    write_record(record, RATED)
    (tmp_path / "lesson.mp4").write_bytes(b"x")
    RehuDocument.load(record, username="ioan").save()
    course = tmp_path / "course"
    course.mkdir()
    write_record(course / "info.rehu", RATED)
    RehuDocument.load(course / "info.rehu", username="ioan").save()

    renamed = rename_rehu_resource(record, "intro")
    moved = rename_rehu_resource(course / "info.rehu", "class")

    assert sorted(path.name for path in tmp_path.iterdir() if path.is_file()) == [
        "intro.mp4",
        "intro.rehu",
        "intro.user-ioan.rehuser",
        "intro.user-public.rehuser",
        "intro.user-unknown.rehuser",
    ]
    assert sorted(path.name for path in moved.parent.iterdir()) == [
        "info.rehu",
        "info.user-ioan.rehuser",
        "info.user-public.rehuser",
        "info.user-unknown.rehuser",
    ]
    assert RehuDocument.load(renamed, username="ioan").active_block[USERS] == RATED["tutorial"][USERS]


def test_a_sidecars_save_is_its_records_change_too(tmp_path: Path) -> None:
    """The notifier reports an atomic save of a sidecar as the sidecar changed and its record changed: whoever holds
    the record holds what it was read with.

    **Test steps:**

    * coalesce an atomic save of ``info.user-ioan.rehuser``, and one of ``lesson.user-bob.rehuser``
    * verify each batch publishes the sidecar and its record as changed, and nothing of the temporary file
    """
    for record, sidecar in (("info.rehu", "info.user-ioan.rehuser"), ("lesson.rehu", "lesson.user-bob.rehuser")):
        temporary = tmp_path / f"{sidecar}.abcd1234.tmp"
        batch = [
            RawChange(RawChangeKind.CREATED, temporary),
            RawChange(RawChangeKind.MOVED, temporary, tmp_path / sidecar),
        ]

        events = ChangeCoalescer.events_of(batch, tmp_path, None)

        assert Changed((ResourceKey(tmp_path / sidecar), ResourceKey(tmp_path / record))) in events


def test_a_sidecar_deleted_is_its_records_change_too(tmp_path: Path) -> None:
    """A sidecar gone takes its user's state out of the record as read.

    **Test steps:**

    * coalesce a sidecar's deletion
    * verify its record is among the changed
    """
    events = ChangeCoalescer.events_of(
        [RawChange(RawChangeKind.DELETED, tmp_path / "info.user-ioan.rehuser")], tmp_path, None
    )

    changed = next(event for event in events if isinstance(event, Changed))
    assert ResourceKey(tmp_path / "info.rehu") in changed.keys


# endregion
