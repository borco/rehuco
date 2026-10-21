"""Tests for what a record's save is checked and merged against (#416): its version, the per-user merge, and the
metadata a person resolves a conflict over ([[nodes#access-seam]]).
"""

import copy
from typing import Any, Final

from rehuco_core import (
    ABSENT,
    MetadataDifference,
    canonical_json,
    merge_users,
    metadata_differences,
    metadata_of,
    put_paths,
    record_differences,
    record_version,
    user_differences,
)
from rehuco_core.record_versions import (
    metadata_hash,
    metadata_text,
    path_value,
    put_value,
    same_details,
    user_field_hashes,
    users_maps,
    value_hash,
)

USERNAME: Final = "admin"
"""Whose per-user fields the merges in this module carry."""


def payload(users: dict[str, Any] | None = None, **core: Any) -> dict[str, Any]:
    """A current-format tutorial payload.

    :param users: the tutorial block's ``users`` map, or ``None`` for none.
    :param core: extra ``core`` fields.
    :returns: the payload.
    """
    block: dict[str, Any] = {"format_version": 2}
    if users is not None:
        block["users"] = users
    return {
        "format_version": 2,
        "core": {"type": "tutorial", "updated": "2026-01-01T00:00:00Z", **core},
        "tutorial": block,
    }


def merge_matrix_base() -> dict[str, Any]:
    """The payload every merge-matrix test starts from: one field in each kind of scope.

    :returns: the payload.
    """
    return payload(
        {
            USERNAME: {"rating": 1, "viewed": True, "todo": True},
            "bob": {"rating": 2},
            "unknown": {"todo": True},
            "public": {"rating": 3},
        }
    )


def merged(mine: dict[str, Any], theirs: dict[str, Any], base: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Merge ``theirs`` into ``mine`` against ``base`` as :data:`USERNAME`.

    :param mine: the edited payload, merged into.
    :param theirs: the payload on disk now.
    :param base: the payload ``mine`` was read as.
    :returns: what :func:`merge_users` answered, and the tutorial block's merged ``users`` map.
    """
    changed = merge_users(mine, theirs, record_version(base, "text"), USERNAME)
    return changed, mine["tutorial"].get("users", {})


# region record versions
def test_a_record_version_hashes_the_metadata_the_text_and_each_per_user_field() -> None:
    """The three parts of a version answer to different changes: the text to anything, the metadata hash only to
    what is not a per-user field, and the per-user hashes field by field.

    **Test steps:**

    * take the version of a payload, of the same payload as another text, and with a rating changed
    * verify which hashes moved, and that the per-user fields come sorted as ``(block, scope, key, hash)``
    """
    data = payload({USERNAME: {"rating": 1}, "bob": {"viewed": True}})
    rated = copy.deepcopy(data)
    rated["tutorial"]["users"][USERNAME]["rating"] = 5

    version = record_version(data, "one")
    retyped = record_version(data, "two")
    rerated = record_version(rated, "one")

    assert retyped.metadata_hash == version.metadata_hash
    assert retyped.file_hash != version.file_hash
    assert rerated.metadata_hash == version.metadata_hash
    assert rerated.user_fields != version.user_fields
    assert version.user_fields == (
        ("tutorial", USERNAME, "rating", value_hash(1)),
        ("tutorial", "bob", "viewed", value_hash(True)),
    )


def test_a_malformed_scope_map_is_one_per_user_field_under_the_empty_key() -> None:
    """A scope that is not an object still counts, as one field, so a change to it is a change; a ``users`` map that
    is not an object is not one at all.

    **Test steps:**

    * hash the per-user fields of a payload with a string scope and a block whose ``users`` is a list
    * verify the string scope is one field under ``""`` and the list contributes nothing
    """
    data = payload({"bob": "garbage"})
    data["other"] = {"users": ["not", "a", "map"]}

    assert user_field_hashes(data) == (("tutorial", "bob", "", value_hash("garbage")),)
    assert users_maps(data) == {"tutorial": {"bob": "garbage"}}


def test_canonical_json_is_one_text_whatever_the_key_order() -> None:
    """Key-sorted, compact, and not ASCII-escaped, so two builds of one value hash alike.

    **Test steps:**

    * serialize two dicts built in different orders, one with a non-ASCII value
    * verify the texts and their hashes match
    """
    first = {"b": "é", "a": [1, {"d": 1, "c": 2}]}
    second = {"a": [1, {"c": 2, "d": 1}], "b": "é"}

    assert canonical_json(first) == '{"a":[1,{"c":2,"d":1}],"b":"é"}'
    assert canonical_json(second) == canonical_json(first)
    assert value_hash(second) == value_hash(first)


# endregion


# region metadata
def test_metadata_leaves_out_every_users_map_and_a_block_made_only_to_hold_one() -> None:
    """A ``users`` map is not metadata, nor is a block left holding only its version stamp -- or nothing -- without
    it; a block with other fields, one with no ``users`` map and a plain value stay.

    **Test steps:**

    * take the metadata of a payload with each kind of block
    * verify which survive, and that the result is a deep copy
    """
    data = payload({USERNAME: {"rating": 1}}, sources=[{"title": "T"}])
    data["rated_only"] = {"users": {USERNAME: {"rating": 2}}}
    data["described"] = {"format_version": 1, "notes": "kept", "users": {}}

    metadata = metadata_of(data)
    metadata["core"]["sources"][0]["title"] = "changed"
    metadata["described"]["notes"] = "changed"

    assert set(metadata) == {"format_version", "core", "described"}
    assert metadata["described"] == {"format_version": 1, "notes": "changed"}
    assert data["core"]["sources"][0]["title"] == "T"
    assert data["described"]["notes"] == "kept"


def test_the_metadata_text_and_hash_ignore_per_user_fields_and_key_order() -> None:
    """Two payloads differing only in per-user fields and key order have one metadata text and hash; a metadata
    edit moves both.

    **Test steps:**

    * build a payload, a reordered copy with other ratings, and a copy with another description
    * compare their metadata texts and hashes
    """
    data = payload({USERNAME: {"rating": 1}}, description="one")
    reordered = {key: data[key] for key in reversed(list(data))}
    reordered = copy.deepcopy(reordered)
    reordered["tutorial"]["users"] = {"bob": {"rating": 5}}
    edited = payload({USERNAME: {"rating": 1}}, description="two")

    assert metadata_text(reordered) == metadata_text(data)
    assert metadata_hash(reordered) == metadata_hash(data)
    assert metadata_hash(edited) != metadata_hash(data)


# endregion


# region merge_users
def test_a_field_the_caller_changed_wins_and_an_unchanged_one_takes_the_files() -> None:
    """The caller's own edit survives a concurrent write to the same scope, and a field it merely still holds
    takes the value written meanwhile.

    **Test steps:**

    * the caller changes its rating; the file changes the caller's ``viewed`` and its rating
    * verify the caller's rating and the file's ``viewed``
    """
    base = merge_matrix_base()
    mine = copy.deepcopy(base)
    mine["tutorial"]["users"][USERNAME]["rating"] = 5
    theirs = copy.deepcopy(base)
    theirs["tutorial"]["users"][USERNAME]["rating"] = 4
    theirs["tutorial"]["users"][USERNAME]["viewed"] = False

    _, users = merged(mine, theirs, base)

    assert users[USERNAME] == {"rating": 5, "viewed": False, "todo": True}


def test_a_removal_by_the_caller_sticks_and_a_field_added_on_disk_survives() -> None:
    """Removing a field is a change like any other, and a field the file gained is kept.

    **Test steps:**

    * the caller removes its ``todo``; the file adds a progress entry for the caller
    * verify ``todo`` is gone and the progress entry is there
    """
    base = merge_matrix_base()
    mine = copy.deepcopy(base)
    del mine["tutorial"]["users"][USERNAME]["todo"]
    theirs = copy.deepcopy(base)
    theirs["tutorial"]["users"][USERNAME]["progress"] = {"a.mp4": 12}

    _, users = merged(mine, theirs, base)

    assert users[USERNAME] == {"rating": 1, "viewed": True, "progress": {"a.mp4": 12}}


def test_another_users_scope_and_unknowns_are_always_the_files() -> None:
    """Only the caller's own scope and ``public`` are writable: an edit to anyone else's -- ``unknown`` included --
    is replaced by the file's, and a scope the caller made up for them is dropped.

    **Test steps:**

    * the caller changes ``bob`` and ``unknown`` and adds ``carol``; the file changes ``bob`` too
    * verify ``bob`` and ``unknown`` are the file's and ``carol`` is absent
    """
    base = merge_matrix_base()
    mine = copy.deepcopy(base)
    mine["tutorial"]["users"]["bob"]["rating"] = 9
    mine["tutorial"]["users"]["unknown"] = {"todo": False}
    mine["tutorial"]["users"]["carol"] = {"rating": 1}
    theirs = copy.deepcopy(base)
    theirs["tutorial"]["users"]["bob"]["rating"] = 3

    _, users = merged(mine, theirs, base)

    assert users["bob"] == {"rating": 3}
    assert users["unknown"] == {"todo": True}
    assert "carol" not in users


def test_the_public_scope_is_writable() -> None:
    """A publish writes to ``public``, so the caller's change there is kept like one to its own scope.

    **Test steps:**

    * the caller changes the public rating
    * verify the merge keeps it
    """
    base = merge_matrix_base()
    mine = copy.deepcopy(base)
    mine["tutorial"]["users"]["public"]["rating"] = 4

    _, users = merged(mine, copy.deepcopy(base), base)

    assert users["public"] == {"rating": 4}


def test_a_scope_emptied_on_both_sides_is_dropped_and_one_new_on_disk_is_kept() -> None:
    """A writable scope the caller removed whole loses the fields it held, keeps a field the file added meanwhile,
    and disappears once nothing is left; one that only the file has is taken as it is.

    **Test steps:**

    * the caller removes its whole scope and ``public``; the file adds a field to ``public`` and a scope for the
      caller in a block the caller never read
    * verify the caller's scope is gone, ``public`` holds only the new field, and the new scope is there
    """
    base = merge_matrix_base()
    base["extra"] = {"format_version": 1, "users": {}}
    mine = copy.deepcopy(base)
    del mine["tutorial"]["users"][USERNAME]
    del mine["tutorial"]["users"]["public"]
    theirs = copy.deepcopy(base)
    theirs["tutorial"]["users"]["public"]["viewed"] = True
    theirs["extra"]["users"][USERNAME] = {"rating": 2}

    merge_users(mine, theirs, record_version(base, "text"), USERNAME)

    assert USERNAME not in mine["tutorial"]["users"]
    assert mine["tutorial"]["users"]["public"] == {"viewed": True}
    assert mine["extra"]["users"] == {USERNAME: {"rating": 2}}


def test_a_malformed_scope_map_merges_as_one_field() -> None:
    """A scope that is not an object is one field: kept when the caller changed it, the file's when not.

    **Test steps:**

    * merge a caller that turned its scope into a string against an unchanged file
    * merge a caller that still holds the string it read against a file that fixed it
    * verify the first keeps the string, the second takes the file's map
    """
    base = merge_matrix_base()
    broken = copy.deepcopy(base)
    broken["tutorial"]["users"][USERNAME] = "garbage"

    _, kept = merged(copy.deepcopy(broken), copy.deepcopy(base), base)
    _, fixed = merged(copy.deepcopy(broken), copy.deepcopy(base), broken)

    assert kept[USERNAME] == "garbage"
    assert fixed[USERNAME] == base["tutorial"]["users"][USERNAME]


def test_a_malformed_scope_on_disk_reads_as_an_empty_one() -> None:
    """A file whose scope is not an object contributes no fields to it: the caller's changes are kept, its
    unchanged ones dropped.

    **Test steps:**

    * the caller changes its rating; the file turned the caller's scope into a string
    * verify only the changed rating is left
    """
    base = merge_matrix_base()
    mine = copy.deepcopy(base)
    mine["tutorial"]["users"][USERNAME]["rating"] = 5
    theirs = copy.deepcopy(base)
    theirs["tutorial"]["users"][USERNAME] = "garbage"

    _, users = merged(mine, theirs, base)

    assert users[USERNAME] == {"rating": 5}


def test_a_block_with_no_users_map_on_one_side_merges_against_an_empty_one() -> None:
    """A block the caller holds without a ``users`` map -- or with a broken one -- gets the file's; a block whose
    ``users`` map the file lost keeps only the caller's changes.

    **Test steps:**

    * the caller's tutorial block has no ``users`` and its ``extra`` block a list; the file has maps for both
    * the caller changes a rating in a third block whose map the file dropped
    * verify the first two take the file's maps and the third keeps only the changed field
    """
    base = payload()
    base["kept"] = {"format_version": 1, "users": {USERNAME: {"rating": 1, "viewed": True}}}
    mine = copy.deepcopy(base)
    mine["extra"] = {"format_version": 1, "users": ["broken"]}
    mine["kept"]["users"][USERNAME]["rating"] = 5
    theirs = copy.deepcopy(base)
    theirs["tutorial"]["users"] = {"bob": {"rating": 2}}
    theirs["extra"] = {"format_version": 1, "users": {USERNAME: {"viewed": True}}}
    del theirs["kept"]["users"]

    changed = merge_users(mine, theirs, record_version(base, "text"), USERNAME)

    assert changed is True
    assert mine["tutorial"]["users"] == {"bob": {"rating": 2}}
    assert mine["extra"]["users"] == {USERNAME: {"viewed": True}}
    assert mine["kept"]["users"] == {USERNAME: {"rating": 5}}


def test_a_block_only_the_file_has_is_added_with_its_per_user_fields() -> None:
    """A block that appeared on disk to hold per-user fields is added to the caller's payload, with the file's version
    stamp when it has one; a block left empty by the merge -- its fields all removed by the caller -- is not added.

    **Test steps:**

    * the base has a ``gone`` block with the caller's rating, which the caller's payload no longer holds
    * the file has ``gone`` still, a stamped ``first`` block with ``bob``'s rating, and an unstamped ``bare`` one
    * verify ``first`` and ``bare`` are added with their maps (only ``first`` stamped) and ``gone`` stays out
    """
    base = payload()
    base["gone"] = {"format_version": 1, "users": {USERNAME: {"rating": 1}}}
    mine = copy.deepcopy(base)
    del mine["gone"]
    theirs = copy.deepcopy(base)
    theirs["first"] = {"format_version": 3, "users": {"bob": {"rating": 2}}}
    theirs["bare"] = {"users": {"bob": {"todo": True}}}

    changed = merge_users(mine, theirs, record_version(base, "text"), USERNAME)

    assert changed is True
    assert mine["first"] == {"format_version": 3, "users": {"bob": {"rating": 2}}}
    assert mine["bare"] == {"users": {"bob": {"todo": True}}}
    assert "gone" not in mine


def test_a_block_the_save_drops_is_not_added_back_from_the_file() -> None:
    """A block the caller left out on purpose -- claimed and abandoned -- stays out, however many per-user fields the
    file holds in it (#497); the same block left out by accident would be added back.

    **Test steps:**

    * the base has a ``gone`` block; the caller's payload no longer holds it; the file holds ``bob``'s rating in it
    * merge naming ``gone`` as dropped; verify it stays out and nothing changed
    * merge again without naming it; verify it is added back
    """
    base = payload()
    base["gone"] = {"format_version": 1, "users": {USERNAME: {"rating": 1}}}
    mine = copy.deepcopy(base)
    del mine["gone"]
    theirs = copy.deepcopy(base)
    theirs["gone"]["users"]["bob"] = {"rating": 2}
    version = record_version(base, "text")

    changed = merge_users(mine, theirs, version, USERNAME, dropped=("gone",))

    assert changed is False
    assert "gone" not in mine
    assert merge_users(mine, theirs, version, USERNAME) is True
    assert mine["gone"] == {"format_version": 1, "users": {"bob": {"rating": 2}}}


def test_merge_users_answers_whether_the_callers_fields_changed() -> None:
    """``True`` only when the file held a per-user value the caller did not: merging an identical file, or one
    differing only in metadata, changes nothing and adds no empty ``users`` map.

    **Test steps:**

    * merge a caller with a block lacking ``users`` against a file with the same block and another description
    * merge a caller against a file with one more progress entry
    * verify the first answers ``False`` and left the block alone, the second ``True``
    """
    base = payload(description="one")
    mine = copy.deepcopy(base)
    theirs = payload(description="two")

    assert merge_users(mine, theirs, record_version(base, "text"), USERNAME) is False
    assert "users" not in mine["tutorial"]

    rated = payload({USERNAME: {"rating": 1}})
    progressed = payload({USERNAME: {"rating": 1, "progress": {"a.mp4": 3}}})
    assert merge_users(copy.deepcopy(rated), progressed, record_version(rated, "text"), USERNAME) is True


# endregion


# region metadata_differences
def test_differences_are_found_key_by_key_with_their_base_values() -> None:
    """Objects are walked key by key: one row per differing value, in the edited document's order with the
    file-only keys last, each carrying its value when opened and which side changed it.

    **Test steps:**

    * the caller changes the description and adds a ``released``; the file changes the publisher and adds
      ``authors``
    * verify the rows' paths and values, and ``mine_changed``/``theirs_changed``
    """
    base = payload(description="one", publisher="P")
    mine = payload(description="two", publisher="P", released="2025")
    theirs = payload(description="one", publisher="Q", authors=["A"])

    differences = metadata_differences(base, mine, theirs)

    assert differences == [
        MetadataDifference(("core", "description"), "one", "two", "one"),
        MetadataDifference(("core", "publisher"), "P", "P", "Q"),
        MetadataDifference(("core", "released"), ABSENT, "2025", ABSENT),
        MetadataDifference(("core", "authors"), ABSENT, ABSENT, ["A"]),
    ]
    assert [(row.mine_changed, row.theirs_changed) for row in differences] == [
        (True, False),
        (False, True),
        (True, False),
        (False, True),
    ]


def test_equal_length_lists_are_compared_item_by_item() -> None:
    """A source's title and another's publisher are two rows, each under its index -- and an item the base did not
    have reads as absent from it.

    **Test steps:**

    * the base has one source; both sides have two, differing in the first's title and the second's publisher
    * verify one row per differing item field
    """
    base = payload(sources=[{"title": "T", "publisher": "P"}])
    mine = payload(sources=[{"title": "Mine", "publisher": "P"}, {"title": "U", "publisher": "P"}])
    theirs = payload(sources=[{"title": "T", "publisher": "P"}, {"title": "U", "publisher": "Q"}])

    assert metadata_differences(base, mine, theirs) == [
        MetadataDifference(("core", "sources", 0, "title"), "T", "Mine", "T"),
        MetadataDifference(("core", "sources", 1, "publisher"), ABSENT, "P", "Q"),
    ]


def test_lists_of_different_lengths_are_one_value() -> None:
    """Which item is which is anyone's guess once the lengths differ, so the list is compared whole.

    **Test steps:**

    * the caller has one author more than the file
    * verify one row for the whole list
    """
    base = payload(authors=["A"])
    mine = payload(authors=["A", "B"])
    theirs = payload(authors=["C"])

    assert metadata_differences(base, mine, theirs) == [
        MetadataDifference(("core", "authors"), ["A"], ["A", "B"], ["C"])
    ]


def test_a_value_whose_base_was_another_shape_reads_as_absent_below_it() -> None:
    """Where the base held a plain value and both sides now hold an object or a list, the rows below have no base.

    **Test steps:**

    * the base's ``extra`` and ``tags`` are strings; both sides make them a differing object and list
    * verify the rows below carry ``ABSENT`` as their base
    """
    base = payload(extra="flat", tags="flat")
    mine = payload(extra={"a": 1}, tags=["x"])
    theirs = payload(extra={"a": 2}, tags=["y"])

    assert metadata_differences(base, mine, theirs) == [
        MetadataDifference(("core", "extra", "a"), ABSENT, 1, 2),
        MetadataDifference(("core", "tags", 0), ABSENT, "x", "y"),
    ]


def test_the_updated_stamp_and_per_user_fields_never_appear() -> None:
    """``core.updated`` is stamped by the save itself and per-user fields are merged, so neither is a choice; a
    block holding only the ``users`` map is not metadata at all.

    **Test steps:**

    * the two sides differ only in ``updated``, the ``users`` maps, and a users-only block one of them has
    * verify there are no differences
    """
    base = payload({USERNAME: {"rating": 1}})
    mine = payload({USERNAME: {"rating": 2}})
    mine["core"]["updated"] = "2026-02-02T00:00:00Z"
    theirs = payload({"bob": {"rating": 3}})
    theirs["core"]["updated"] = "2026-03-03T00:00:00Z"
    theirs["rated"] = {"format_version": 1, "users": {"bob": {"rating": 1}}}

    assert not metadata_differences(base, mine, theirs)


# endregion


# region user_differences, record_differences, same_details
def users_path(scope: str, key: str, block: str = "tutorial") -> tuple[str, ...]:
    """Where a per-user field sits, as a difference names it.

    :param scope: the scope (a username, or ``public``).
    :param key: the field.
    :param block: the block holding the ``users`` map.
    :returns: its path.
    """
    return (block, "users", scope, key)


def test_user_differences_list_the_callers_own_and_public_fields_with_their_base_values() -> None:
    """The per-user fields the caller may write -- its own and ``public`` -- are rows to choose, each with its value
    when opened, own scope first; another user's and ``unknown``'s are always the file's and never appear, however
    they differ.

    **Test steps:**

    * the caller changes its rating and the public one; the file changes the caller's ``viewed``, adds a public
      ``viewed``, changes ``bob`` and ``unknown`` and adds ``carol``
    * verify the rows: the caller's rating and ``viewed``, then the public rating and ``viewed``, with base values
    * verify which side changed each
    """
    base = merge_matrix_base()
    mine = copy.deepcopy(base)
    mine["tutorial"]["users"][USERNAME]["rating"] = 5
    mine["tutorial"]["users"]["public"]["rating"] = 4
    theirs = copy.deepcopy(base)
    theirs["tutorial"]["users"][USERNAME]["viewed"] = False
    theirs["tutorial"]["users"]["public"]["viewed"] = True
    theirs["tutorial"]["users"]["bob"]["rating"] = 9
    theirs["tutorial"]["users"]["unknown"]["todo"] = False
    theirs["tutorial"]["users"]["carol"] = {"rating": 1}

    differences = user_differences(base, mine, theirs, USERNAME)

    assert differences == [
        MetadataDifference(users_path(USERNAME, "rating"), 1, 5, 1),
        MetadataDifference(users_path(USERNAME, "viewed"), True, True, False),
        MetadataDifference(users_path("public", "rating"), 3, 4, 3),
        MetadataDifference(users_path("public", "viewed"), ABSENT, ABSENT, True),
    ]
    assert [(row.mine_changed, row.theirs_changed) for row in differences] == [
        (True, False),
        (False, True),
        (True, False),
        (False, True),
    ]


def test_a_scope_one_side_lacks_compares_as_empty_so_each_field_is_its_own_row() -> None:
    """A scope the caller created, or one the file dropped, is not one row for the whole map: it reads as an empty
    one, so each of its fields is a row -- with no base where the scope was not there when opened.

    **Test steps:**

    * the base has no scope for the caller and a public one; the caller adds its own scope with two fields; the file
      drops the public scope
    * verify one row per field of the caller's new scope, and one per field of the dropped public one
    """
    base = payload({"public": {"rating": 3}})
    mine = payload({USERNAME: {"rating": 5, "todo": True}, "public": {"rating": 3}})
    theirs = payload({})

    assert user_differences(base, mine, theirs, USERNAME) == [
        MetadataDifference(users_path(USERNAME, "rating"), ABSENT, 5, ABSENT),
        MetadataDifference(users_path(USERNAME, "todo"), ABSENT, True, ABSENT),
        MetadataDifference(users_path("public", "rating"), 3, 3, ABSENT),
    ]


def test_a_block_one_side_lacks_compares_as_empty_with_the_files_only_blocks_last() -> None:
    """A block -- or a ``users`` map -- only one side has reads as empty on the other; the edited document's blocks
    come first, then the ones only the file has.

    **Test steps:**

    * the caller has a ``kept`` block with its rating that the file lacks; the file has an ``extra`` block with the
      caller's rating, which the caller lacks; neither has a ``users`` map in the tutorial block
    * verify one row for each, the caller's block first, none for the tutorial block
    """
    base = payload()
    mine = payload()
    mine["kept"] = {"format_version": 1, "users": {USERNAME: {"rating": 1}}}
    theirs = payload()
    theirs["extra"] = {"format_version": 1, "users": {USERNAME: {"rating": 2}}}

    assert user_differences(base, mine, theirs, USERNAME) == [
        MetadataDifference(users_path(USERNAME, "rating", "kept"), ABSENT, 1, ABSENT),
        MetadataDifference(users_path(USERNAME, "rating", "extra"), ABSENT, ABSENT, 2),
    ]


def test_equal_per_user_fields_are_no_difference() -> None:
    """Two sides holding the same per-user fields -- whatever the base was -- have nothing to choose.

    **Test steps:**

    * the caller and the file both changed the caller's rating to the same value
    * verify no rows
    """
    base = payload({USERNAME: {"rating": 1}})
    both = payload({USERNAME: {"rating": 4}})

    assert not user_differences(base, both, copy.deepcopy(both), USERNAME)


def test_record_differences_are_the_metadata_rows_then_the_per_user_ones() -> None:
    """The dialog's rows: every detail first, then the caller's own and public per-user fields -- another user's
    never.

    **Test steps:**

    * the caller changes the description and its rating; the file changes the description, the public rating and
      ``bob``'s
    * verify the description row, then the caller's rating, then the public rating
    """
    base = payload({USERNAME: {"rating": 1}, "public": {"rating": 2}, "bob": {"rating": 3}}, description="one")
    mine = payload({USERNAME: {"rating": 5}, "public": {"rating": 2}, "bob": {"rating": 3}}, description="two")
    theirs = payload({USERNAME: {"rating": 1}, "public": {"rating": 4}, "bob": {"rating": 6}}, description="three")

    assert record_differences(base, mine, theirs, USERNAME) == [
        MetadataDifference(("core", "description"), "one", "two", "three"),
        MetadataDifference(users_path(USERNAME, "rating"), 1, 5, 1),
        MetadataDifference(users_path("public", "rating"), 2, 2, 4),
    ]


def test_same_details_ignores_the_stamp_and_per_user_fields_but_not_a_detail() -> None:
    """Two payloads carry the same details when only what a save stamps and the per-user fields differ -- a block
    holding nothing but a ``users`` map included; any metadata value differing makes them not the same.

    **Test steps:**

    * compare payloads differing in ``updated``, the ratings, and a users-only block one of them has
    * compare payloads differing in the description, and in a field only one of them has
    * verify the first are the same details and the others are not
    """
    rated = payload({USERNAME: {"rating": 1}}, description="one")
    restamped = payload({"bob": {"rating": 2}}, description="one")
    restamped["core"]["updated"] = "2026-05-05T00:00:00Z"
    restamped["rated"] = {"format_version": 1, "users": {"bob": {"rating": 1}}}

    assert same_details(rated, restamped)
    assert same_details(restamped, rated)
    assert not same_details(payload(description="one"), payload(description="two"))
    assert not same_details(payload(description="one"), payload())


# endregion


# region put_paths
def test_put_paths_sets_and_removes_values() -> None:
    """A path is set to its value, or removed where it is ``ABSENT``; the value is copied in.

    **Test steps:**

    * set the description, remove the publisher, set a list item's title
    * mutate the value handed in afterwards
    * verify the payload, untouched by the later mutation
    """
    data = payload(publisher="P", sources=[{"title": "T"}])
    authors = ["A"]

    put_paths(
        data,
        {
            ("core", "description"): "new",
            ("core", "publisher"): ABSENT,
            ("core", "sources", 0, "title"): "U",
            ("core", "authors"): authors,
        },
    )
    authors.append("B")

    assert data["core"]["description"] == "new"
    assert "publisher" not in data["core"]
    assert data["core"]["sources"] == [{"title": "U"}]
    assert data["core"]["authors"] == ["A"]


def test_put_paths_creates_missing_containers_as_objects() -> None:
    """A path whose container is missing -- or a plain value -- gets an object made for it.

    **Test steps:**

    * put a value under a block the payload lacks, and under a field that is a string
    * verify both objects were created
    """
    data = payload(extra="flat")

    put_paths(data, {("new_block", "inner", "value"): 1, ("core", "extra", "a"): 2})

    assert data["new_block"] == {"inner": {"value": 1}}
    assert data["core"]["extra"] == {"a": 2}


def test_put_paths_stamps_a_block_it_creates_with_the_files_version() -> None:
    """A plugin block created to hold a value takes its ``format_version`` from the stamps' payload when that has one,
    so a resolved conflict never writes an unstamped block; a container below a block, or a block the stamps lack,
    gets none.

    **Test steps:**

    * put a per-user value under a missing block the stamps hold at version 3, and one under a block they lack
    * verify the first block is stamped 3 and the second is not stamped
    """
    data = payload()
    stamps = {"first": {"format_version": 3, "users": {}}}

    put_paths(
        data,
        {("first", "users", USERNAME, "rating"): 2, ("second", "users", USERNAME, "rating"): 1},
        stamps=stamps,
    )

    assert data["first"] == {"format_version": 3, "users": {USERNAME: {"rating": 2}}}
    assert data["second"] == {"users": {USERNAME: {"rating": 1}}}


def test_put_paths_prunes_what_a_per_user_removal_leaves_empty() -> None:
    """Removing a per-user field takes the scope and the ``users`` map it leaves empty with it, as a merge does --
    never the block, and never a container that still holds something; a metadata removal prunes nothing.

    **Test steps:**

    * remove the only progress entry of one user, whose scope holds nothing else
    * remove a rating from a scope that keeps another field
    * remove the only key of a metadata object
    * verify the first user's scope and the emptied ``users`` map are gone, the second scope kept, the metadata object
      kept empty
    """
    data = payload({USERNAME: {"progress": {"a.mp4": 3}}})
    data["other"] = {"format_version": 1, "users": {USERNAME: {"rating": 2, "todo": True}}}
    data["core"]["extra"] = {"a": 1}

    put_paths(
        data,
        {
            ("tutorial", "users", USERNAME, "progress", "a.mp4"): ABSENT,
            ("other", "users", USERNAME, "rating"): ABSENT,
            ("core", "extra", "a"): ABSENT,
        },
    )

    assert data["tutorial"] == {"format_version": 2}
    assert data["other"]["users"] == {USERNAME: {"todo": True}}
    assert data["core"]["extra"] == {}


def test_put_paths_skips_what_it_cannot_place() -> None:
    """A list item the payload lacks is skipped, and removing from a container that is not there creates nothing.

    **Test steps:**

    * set an out-of-range list item, a field under an out-of-range list item, and remove a field under a missing
      block
    * verify the payload is unchanged
    """
    data = payload(sources=[{"title": "T"}])
    before = copy.deepcopy(data)

    put_paths(
        data,
        {
            ("core", "sources", 3): {"title": "U"},
            ("core", "sources", 3, "title"): "U",
            ("missing", "field"): ABSENT,
        },
    )

    assert data == before


def test_put_value_only_sets_entries_that_fit_their_container() -> None:
    """An object takes a string key, a list an index in range; a list item is never removed, and a mismatched key
    does nothing.

    **Test steps:**

    * try an index on an object, a key on a list, a negative index, and ``ABSENT`` on a list item
    * verify nothing changed, then that a valid index is set
    """
    mapping: dict[str, Any] = {"a": 1}
    items = [1, 2]

    put_value(mapping, 0, "x")
    put_value(items, "a", "x")
    put_value(items, -1, "x")
    put_value(items, 0, ABSENT)
    assert (mapping, items) == ({"a": 1}, [1, 2])

    put_value(items, 1, "x")
    assert items == [1, "x"]


def test_path_value_answers_absent_wherever_the_path_leaves_the_payload() -> None:
    """A missing key, an out-of-range index, or a key of the wrong kind answers ``ABSENT``; an empty path is the
    value itself.

    **Test steps:**

    * look up existing and missing paths through objects and lists
    """
    data = {"a": [{"b": 1}]}

    assert path_value(data, ("a", 0, "b")) == 1
    assert path_value(data, ()) is data
    assert path_value(data, ("missing",)) is ABSENT
    assert path_value(data, ("a", 1)) is ABSENT
    assert path_value(data, ("a", "b")) is ABSENT
    assert path_value(data, (0,)) is ABSENT


# endregion
