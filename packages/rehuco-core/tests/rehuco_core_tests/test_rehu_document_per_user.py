"""Tests for the username-taking per-user accessors and the non-stamping save (#410).

A node serves several users, so a per-user read or write names whose data it means rather than taking
the identity the document was loaded as ([[field-schema#per-user-shared]]); a per-user write such as
watch progress never stamps ``updated`` ([[field-schema#watch-progress]]).
"""

import json
from pathlib import Path
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from rehuco_core import RehuDocument, current_block_version


def tutorial_data(users: dict[str, Any] | None = None) -> dict[str, Any]:
    """A minimal current-format tutorial payload.

    :param users: the tutorial block's ``users`` map, or ``None`` for none.
    :returns: the payload.
    """
    block: dict[str, Any] = {"format_version": current_block_version("tutorial")}
    if users is not None:
        block["users"] = users
    return {
        "format_version": 2,
        "core": {"type": "tutorial", "id": "550e8400-e29b-41d4-a716-446655440000", "updated": "2026-01-01T00:00:00Z"},
        "tutorial": block,
    }


# region username-taking accessors
def test_a_per_user_read_names_whose_value_it_wants() -> None:
    """``user_field`` reads the named user's submap whatever identity the document was loaded as -- a node
    answering Bob's request on a document it opened as itself.

    **Test steps:**

    * build a document loaded as ``admin`` holding values for ``admin`` and ``bob``
    * verify ``user_field`` answers each user's own value, and the default for an absent user or key
    """
    doc = RehuDocument(tutorial_data({"admin": {"rating": 1}, "bob": {"rating": 4}}), username="admin")

    assert doc.user_field("bob", "rating") == 4
    assert doc.user_field("admin", "rating") == doc.active_user_field("rating") == 1
    assert doc.user_field("carol", "rating", 0) == 0
    assert doc.user_field("bob", "viewed", False) is False


def test_a_per_user_write_lands_under_the_named_user_only() -> None:
    """``set_user_field`` creates the named user's submap and leaves the document's own user untouched.

    **Test steps:**

    * write a value for ``bob`` on a document loaded as ``admin``
    * verify only ``bob``'s submap changed
    """
    doc = RehuDocument(tutorial_data({"admin": {"rating": 1}}), username="admin")

    doc.set_user_field("bob", "viewed", True)

    assert doc.data["tutorial"]["users"] == {"admin": {"rating": 1}, "bob": {"viewed": True}}


def test_writing_none_removes_a_per_user_key() -> None:
    """``None`` removes the key rather than storing a JSON ``null`` -- the rule that moved from the agent's
    form into core (#410), so every host clears a per-user field the same way.

    **Test steps:**

    * clear one key through ``set_user_field`` and another through ``set_active_user_field``
    * verify both keys are gone and the other user's submap is untouched
    """
    doc = RehuDocument(tutorial_data({"admin": {"rating": 3, "todo": True}, "bob": {"rating": 2}}), username="admin")

    doc.set_user_field("admin", "rating", None)
    doc.set_active_user_field("todo", None)

    assert doc.data["tutorial"]["users"] == {"admin": {}, "bob": {"rating": 2}}


def test_clearing_an_absent_per_user_key_creates_nothing() -> None:
    """Clearing what is not there never installs a block, a ``users`` map or a submap -- not even on a
    typeless document, where a write would be refused.

    **Test steps:**

    * clear a key for a user with no submap, on a tutorial and on a typeless document
    * verify neither payload changed and ``remove_user_field`` reports nothing removed
    """
    data = tutorial_data()
    doc = RehuDocument(data, username="admin")
    typeless = RehuDocument({"format_version": 2, "core": {}}, username="admin")

    doc.set_user_field("bob", "rating", None)
    typeless.set_active_user_field("rating", None)

    assert "users" not in data["tutorial"]
    assert typeless.data == {"format_version": 2, "core": {}}
    assert doc.remove_user_field("bob", "rating") is False


def test_removing_a_per_user_key_reports_whether_it_was_there() -> None:
    """``remove_user_field`` answers ``True`` only when it deleted something, from the named user only.

    **Test steps:**

    * remove a present key for ``bob``, then the same key again
    * verify the first answers ``True``, the second ``False``, and ``admin``'s copy survives
    """
    doc = RehuDocument(tutorial_data({"admin": {"rating": 1}, "bob": {"rating": 4}}), username="admin")

    assert doc.remove_user_field("bob", "rating") is True
    assert doc.remove_user_field("bob", "rating") is False
    assert doc.active_user_field("rating") == 1


# endregion


# region touch_updated
def test_a_non_stamping_save_leaves_updated_alone(tmp_path: Path, freezer: FrozenDateTimeFactory) -> None:
    """A changed save with ``touch_updated=False`` writes the change and keeps the stored ``updated``: a
    per-user write describes one person's viewing, not the resource ([[field-schema#record-timestamps]]).

    **Test steps:**

    * write a tutorial record, then load it at a later time
    * change a per-user field and save without stamping
    * verify the change landed and ``updated`` is the stored value
    """
    path = tmp_path / "info.rehu"
    path.write_text(json.dumps(tutorial_data()), encoding="utf-8")
    freezer.move_to("2026-10-12T10:00:00Z")
    doc = RehuDocument.load(path)

    doc.set_user_field("bob", "viewed", True)
    doc.save(touch_updated=False)

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["tutorial"]["users"] == {"bob": {"viewed": True}}
    assert saved["core"]["updated"] == "2026-01-01T00:00:00Z"


def test_a_non_stamping_first_write_stamps_no_created_either(tmp_path: Path) -> None:
    """``touch_updated=False`` stamps neither timestamp, so even a record's first write carries none --
    the stamps belong to edits of the resource, which this write is not.

    **Test steps:**

    * save a never-written document without stamping
    * verify the written core carries neither ``created`` nor a new ``updated``
    """
    data = tutorial_data()
    del data["core"]["updated"]
    path = tmp_path / "info.rehu"

    RehuDocument(data).save(path, touch_updated=False)

    core = json.loads(path.read_text(encoding="utf-8"))["core"]
    assert "created" not in core
    assert "updated" not in core


# endregion
