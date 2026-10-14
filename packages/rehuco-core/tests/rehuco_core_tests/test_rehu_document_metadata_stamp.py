"""Tests for reading a record with its text, and for ``updated`` moving on a metadata edit only (#416).

A per-user field describes one person, not the resource, and a save merges other writers' ones in, so neither may
move ``updated`` ([[field-schema#record-timestamps]]).
"""

import json
from pathlib import Path
from typing import Any, Final

from freezegun.api import FrozenDateTimeFactory
from rehuco_core import RehuDocument, current_block_version

UPDATED: Final = "2026-01-01T00:00:00Z"
"""The ``updated`` stamp every record here is written with."""

LATER: Final = "2026-10-12T10:00:00Z"
"""When the saves here happen."""


def write_record(path: Path, users: dict[str, Any] | None = None) -> None:
    """Write a current-format tutorial record.

    :param path: where.
    :param users: the tutorial block's ``users`` map, or ``None`` for none.
    """
    block: dict[str, Any] = {"format_version": current_block_version("tutorial")}
    if users is not None:
        block["users"] = users
    data = {
        "format_version": 2,
        "core": {"type": "tutorial", "id": "550e8400-e29b-41d4-a716-446655440000", "updated": UPDATED},
        "tutorial": block,
    }
    path.write_text(json.dumps(data, indent=3), encoding="utf-8")


def stored_updated(path: Path) -> str:
    """A record's ``updated`` as stored.

    :param path: the record.
    :returns: the stamp.
    """
    return json.loads(path.read_text(encoding="utf-8"))["core"]["updated"]


def test_load_with_text_hands_back_the_text_the_document_was_read_from(tmp_path: Path) -> None:
    """The text is the file's own, not the document reserialized, and the document is what ``load`` gives.

    **Test steps:**

    * write a record with a layout of its own
    * load it with its text, and plainly
    * verify the text is the file's and the two documents agree
    """
    path = tmp_path / "info.rehu"
    write_record(path, {"admin": {"rating": 2}})

    document, text = RehuDocument.load_with_text(path, username="bob")

    assert text == path.read_text(encoding="utf-8")
    assert document.username == "bob"
    assert document.path == path
    assert document.data == RehuDocument.load(path).data


def test_a_per_user_change_does_not_move_updated(tmp_path: Path, freezer: FrozenDateTimeFactory) -> None:
    """Changing only a rating writes it but leaves ``updated`` alone, even on a stamping save.

    **Test steps:**

    * load a rated record, change the rating at a later time, save
    * verify the new rating is written and ``updated`` is the stored one
    """
    path = tmp_path / "info.rehu"
    write_record(path, {"admin": {"rating": 2}})
    document = RehuDocument.load(path, username="admin")

    freezer.move_to(LATER)
    document.set_active_user_field("rating", 5)
    document.save()

    assert json.loads(path.read_text(encoding="utf-8"))["tutorial"]["users"] == {"admin": {"rating": 5}}
    assert stored_updated(path) == UPDATED


def test_a_metadata_change_moves_updated_and_rebases_the_baseline(
    tmp_path: Path, freezer: FrozenDateTimeFactory
) -> None:
    """A description edit is a metadata edit, so the save stamps ``updated``; the next save, changing only a
    rating, compares against what was just saved and leaves the new stamp alone.

    **Test steps:**

    * load a record, change its description at a later time, save
    * change only a rating even later, save again
    * verify ``updated`` is the first save's time
    """
    path = tmp_path / "info.rehu"
    write_record(path, {"admin": {"rating": 2}})
    document = RehuDocument.load(path, username="admin")

    freezer.move_to(LATER)
    document.data["core"]["description"] = "edited"
    document.save()
    freezer.move_to("2026-10-13T10:00:00Z")
    document.set_active_user_field("rating", 4)
    document.save()

    assert stored_updated(path) == LATER


def test_a_reload_rebases_the_metadata_baseline(tmp_path: Path, freezer: FrozenDateTimeFactory) -> None:
    """After a reload the file as reread is the baseline: a per-user change to it then saves without moving
    ``updated``, even though the document had a metadata edit before the reload.

    **Test steps:**

    * load a record, edit its description, reload it
    * change only a rating at a later time and save
    * verify ``updated`` is the stored one
    """
    path = tmp_path / "info.rehu"
    write_record(path, {"admin": {"rating": 2}})
    document = RehuDocument.load(path, username="admin")
    document.data["core"]["description"] = "discarded"
    document.reload()

    freezer.move_to(LATER)
    document.set_active_user_field("rating", 4)
    document.save()

    assert stored_updated(path) == UPDATED
