"""Tests for read-merge-write, the one way to change part of a record on disk (#410)."""

import json
import threading
from pathlib import Path
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from pytest import raises
from rehuco_core import RehuDocument, current_block_version, merge_write, user_sidecar_paths


def write_tutorial(path: Path) -> dict[str, Any]:
    """Write a minimal tutorial record to ``path``.

    :param path: where to write it.
    :returns: the payload written.
    """
    data: dict[str, Any] = {
        "format_version": 2,
        "core": {
            "type": "tutorial",
            "id": "550e8400-e29b-41d4-a716-446655440000",
            "updated": "2026-01-01T00:00:00Z",
            "description": "kept",
        },
        "tutorial": {"format_version": current_block_version("tutorial"), "complete": True},
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


def read_json(path: Path) -> dict[str, Any]:
    """Parse the record on disk.

    :param path: the record.
    :returns: its payload.
    """
    return json.loads(path.read_text(encoding="utf-8"))


def users_on_disk(path: Path) -> dict[str, Any]:
    """Parse each user's tutorial fields from the sidecars beside the record.

    :param path: the record.
    :returns: each sidecar's tutorial fields, by the user its name carries.
    """
    return {
        slug: json.loads(sidecar.read_text(encoding="utf-8"))["tutorial"]
        for slug, sidecar in user_sidecar_paths(path).items()
    }


def test_a_merge_write_changes_only_what_it_mutates(tmp_path: Path) -> None:
    """Whatever the change does not touch is written back as the file held it, so two writers changing
    different parts both survive.

    **Test steps:**

    * write a record, then merge one per-user field into it without stamping
    * verify the field landed and everything else -- shared fields, ``updated`` -- is as written
    """
    path = tmp_path / "info.rehu"
    write_tutorial(path)

    merge_write(path, lambda doc: doc.set_user_field("bob", "viewed", True), username="admin", touch_updated=False)

    saved = read_json(path)
    assert users_on_disk(path) == {"bob": {"viewed": True}}
    assert saved["tutorial"]["complete"] is True
    assert saved["core"]["description"] == "kept"
    assert saved["core"]["updated"] == "2026-01-01T00:00:00Z"


def test_a_stamping_merge_write_refreshes_updated(tmp_path: Path, freezer: FrozenDateTimeFactory) -> None:
    """A metadata change made through a merge is an edit of the resource and stamps ``updated``.

    **Test steps:**

    * merge a shared-field change with stamping on, at a frozen time
    * verify ``updated`` is that time
    """
    path = tmp_path / "info.rehu"
    write_tutorial(path)
    freezer.move_to("2026-10-12T10:00:00Z")

    merge_write(path, lambda doc: doc.set_active_field("level", "advanced"), username="admin", touch_updated=True)

    assert read_json(path)["core"]["updated"] == "2026-10-12T10:00:00Z"


def test_a_merge_reads_what_is_on_disk_not_a_stale_copy(tmp_path: Path) -> None:
    """A document loaded before another write still holds its own unsaved edit, and the merge sees the
    other write -- the merge never reaches into an open document, and never writes from one.

    **Test steps:**

    * load a document and edit it without saving
    * merge two writes onto the file
    * verify both merged writes are on disk, and the open document holds its edit and neither write
    """
    path = tmp_path / "info.rehu"
    write_tutorial(path)
    open_document = RehuDocument.load(path)
    open_document.set_active_field("level", "beginner")

    merge_write(path, lambda doc: doc.set_user_field("bob", "viewed", True), username="admin", touch_updated=False)
    merge_write(path, lambda doc: doc.set_user_field("carol", "todo", True), username="admin", touch_updated=False)

    assert users_on_disk(path) == {"bob": {"viewed": True}, "carol": {"todo": True}}
    assert "level" not in read_json(path)["tutorial"]
    assert open_document.active_field("level") == "beginner"
    assert "users" not in open_document.active_block


def test_a_locked_record_is_refused_and_left_as_it_was(tmp_path: Path) -> None:
    """A record whose stored field could not be read without loss is locked against saving, and a merge
    is a save: refused, file untouched ([[data-model#write-integrity]]).

    **Test steps:**

    * write a record with a malformed ``authors`` value
    * merge a change into it
    * verify it raises and the file's bytes are unchanged
    """
    path = tmp_path / "info.rehu"
    data = write_tutorial(path)
    data["core"]["authors"] = "not a list"
    path.write_text(json.dumps(data), encoding="utf-8")
    before = path.read_bytes()

    with raises(ValueError, match="Refusing to save"):
        merge_write(path, lambda doc: doc.set_user_field("bob", "viewed", True), username="admin", touch_updated=False)

    assert path.read_bytes() == before


def test_merge_writes_of_one_record_in_this_process_take_turns(tmp_path: Path) -> None:
    """Two writers in one process -- the agent's player and a node it hosts -- must not interleave a
    re-read and a write: the second would read the file before the first wrote, and write the first's
    change away.

    **Test steps:**

    * start a merge whose change waits on a gate, holding the record
    * start a second merge of another field on the same record
    * verify the second has not finished while the first is held, then open the gate
    * verify both changes are on disk
    """
    path = tmp_path / "info.rehu"
    write_tutorial(path)
    entered = threading.Event()
    release = threading.Event()

    def held(doc: RehuDocument) -> None:
        """Hold the record until the test opens the gate, then write one field.

        :param doc: the record being merged.
        """
        entered.set()
        release.wait(5)
        doc.set_user_field("bob", "viewed", True)

    first = threading.Thread(target=merge_write, args=(path, held), kwargs={"username": "a", "touch_updated": False})
    second = threading.Thread(
        target=merge_write,
        args=(path, lambda doc: doc.set_user_field("carol", "todo", True)),
        kwargs={"username": "a", "touch_updated": False},
    )
    try:
        first.start()
        assert entered.wait(5)
        second.start()
        second.join(0.2)
        assert second.is_alive()
    finally:
        release.set()
        first.join(5)
        second.join(5)

    assert users_on_disk(path) == {"bob": {"viewed": True}, "carol": {"todo": True}}
