"""Tests for the ``learning_paths`` projection: owned, subscribed, and published, per identity."""

from typing import Any, Final

from pytest import mark, param
from rehuco_core import (
    LearningPathEntry,
    RehuDocument,
    current_block_version,
    learning_path_records_by_scope,
    learning_path_ref,
    owned_learning_paths,
    visible_learning_paths,
)

# A block's ``users`` map exercising every ownership shape ([[field-schema#learning-path-ownership]]):
# ``public`` holds a published copy, ``admin`` owns one path and subscribes to the published one, and
# ``foo`` owns a path nobody else may see.
USERS: Final = {
    "public": {"learning_paths": [{"title": "Sculpting Fundamentals", "index": 3, "ref": 1}]},
    "admin": {"learning_paths": [{"ref": 1}, {"title": "My Sculpting Order", "index": 7, "ref": 2}]},
    "foo": {"learning_paths": [{"ref": 1}, {"title": "Private Study", "index": 1, "ref": 3}]},
}


def visible(users: Any, *, username: str) -> list[LearningPathEntry]:
    """Resolve a raw ``users`` map for one identity -- the two-step every viewer takes.

    The map is projected to the scope -> records mapping the resolution works on
    (:func:`~rehuco_core.learning_path_records_by_scope`), which is also where every defensive
    coercion below happens, and only then resolved.

    :param users: the block's ``users`` map, as stored.
    :param username: the identity to resolve for.
    :returns: the paths that identity sees.
    """
    return visible_learning_paths(learning_path_records_by_scope(users), username=username)


def document_with(users: dict[str, Any], *, username: str = "admin") -> RehuDocument:
    """Build an in-memory tutorial document whose block carries ``users``.

    :param users: the per-user map to nest in the tutorial block.
    :param username: the identity the document is opened under.
    :returns: the document.
    """
    return RehuDocument(
        {
            "core": {"type": "tutorial", "sources": [{"title": "Foo", "primary": True}]},
            "tutorial": {"format_version": current_block_version("tutorial"), "users": users},
        },
        username=username,
    )


def test_visible_learning_paths_shows_own_entries_subscriptions_and_public() -> None:
    """The viewer rule: this identity's own records, its subscriptions, and the ``public`` scope
    ([[field-schema#learning-path-ownership]]).

    **Test steps:**

    * resolve for ``admin``, who owns one path and subscribes to the published one
    * verify both are shown, resolved through the owning record, in index order
    * verify ``foo``'s private path is not
    """
    assert visible(USERS, username="admin") == [
        LearningPathEntry(3, "Sculpting Fundamentals"),
        LearningPathEntry(7, "My Sculpting Order"),
    ]


def test_visible_learning_paths_never_shows_another_users_private_path() -> None:
    """An identity with nothing of its own still sees the public scope, and only that.

    **Test steps:**

    * resolve for an identity absent from the map
    * verify it sees the published path alone -- neither ``admin``'s nor ``foo``'s private one
    """
    assert visible(USERS, username="stranger") == [LearningPathEntry(3, "Sculpting Fundamentals")]


def test_visible_learning_paths_shows_a_subscribed_and_published_path_once() -> None:
    """A path reached twice -- subscribed to *and* published -- renders once, keyed by its ``ref``.

    **Test steps:**

    * resolve for ``foo``, who subscribes to the ref the public scope also carries
    * verify the published path appears once, alongside ``foo``'s own
    """
    assert visible(USERS, username="foo") == [
        LearningPathEntry(1, "Private Study"),
        LearningPathEntry(3, "Sculpting Fundamentals"),
    ]


def test_visible_learning_paths_ignores_an_unresolvable_ref() -> None:
    """A subscription whose target is gone is nothing: ignored, never rendered blank
    ([[field-schema#learning-path-ownership]]).

    **Test steps:**

    * resolve for an identity subscribing to a ref no record in the block owns
    * verify only its own path is shown
    """
    users = {"admin": {"learning_paths": [{"ref": 99}, {"title": "Mine", "index": 0, "ref": 2}]}}

    assert visible(users, username="admin") == [LearningPathEntry(0, "Mine")]


def test_visible_learning_paths_resolves_a_subscription_to_a_private_owner() -> None:
    """A ``ref`` is a file-scoped slot, so a subscription resolves against whoever owns it -- that is
    what makes it survive a retitle ([[field-schema#learning-path-ownership]]).

    **Test steps:**

    * subscribe ``admin`` to the ref ``foo`` privately owns
    * verify the owner's title and index are what render
    """
    users = {
        "admin": {"learning_paths": [{"ref": 3}]},
        "foo": {"learning_paths": [{"title": "Private Study", "index": 1, "ref": 3}]},
    }

    assert visible(users, username="admin") == [LearningPathEntry(1, "Private Study")]


def test_visible_learning_paths_prefers_the_owners_own_title_over_the_published_copy() -> None:
    """An owner sees the record they hold, not the copy publishing left in the public scope.

    **Test steps:**

    * give ``admin`` a full record and the public scope a differently-titled copy of the same ref
    * verify ``admin``'s own title is what renders, once
    """
    users = {
        "admin": {"learning_paths": [{"title": "My Order", "index": 7, "ref": 1}]},
        "public": {"learning_paths": [{"title": "Shared Order", "index": 3, "ref": 1}]},
    }

    assert visible(users, username="admin") == [LearningPathEntry(7, "My Order")]


def test_visible_learning_paths_renders_a_record_carrying_no_ref() -> None:
    """A full record with no ``ref`` -- nothing can subscribe to it, so nothing can duplicate it either --
    still renders on its own terms.

    **Test steps:**

    * give the identity one record with no ref
    * verify it is shown
    """
    users = {"admin": {"learning_paths": [{"title": "Refless", "index": 4}]}}

    assert visible(users, username="admin") == [LearningPathEntry(4, "Refless")]


@mark.parametrize(
    "users",
    [
        param("not a map", id="users-not-a-map"),
        param({}, id="no-users"),
        param({"admin": "not a map"}, id="user-not-a-map"),
        param({"admin": {}}, id="user-has-no-paths"),
        param({"admin": {"learning_paths": "not a list"}}, id="paths-not-a-list"),
        param({"admin": {"learning_paths": ["not a record"]}}, id="record-not-a-map"),
        param({"admin": {"learning_paths": [{"index": 2}]}}, id="record-with-neither-title-nor-ref"),
    ],
)
def test_visible_learning_paths_reads_a_malformed_map_as_no_paths(users: Any) -> None:
    """Every level is coerced defensively -- a malformed map, user, list, or record reads as no paths.

    **Test steps:**

    * resolve each malformed shape
    * verify it yields no paths
    """
    assert visible(users, username="admin") == []


def test_visible_learning_paths_resolves_the_public_scope_for_the_public_identity() -> None:
    """An identity that happens to be named ``public`` reads that scope once, not twice.

    The reserved scope is not enforced as a username yet, so the resolution must be well-behaved when
    the two coincide rather than double-rendering the published paths.

    **Test steps:**

    * resolve for ``public``
    * verify the published path is listed exactly once
    """
    assert visible(USERS, username="public") == [LearningPathEntry(3, "Sculpting Fundamentals")]


def test_document_learning_paths_resolves_for_its_own_identity() -> None:
    """`RehuDocument.learning_paths` resolves the block's ``users`` map for the document's own username.

    **Test steps:**

    * open the same block as ``admin`` and as ``foo``
    * verify each sees its own paths plus the public one, never the other's private one
    """
    assert document_with(USERS, username="admin").learning_paths == [
        LearningPathEntry(3, "Sculpting Fundamentals"),
        LearningPathEntry(7, "My Sculpting Order"),
    ]
    assert document_with(USERS, username="foo").learning_paths == [
        LearningPathEntry(1, "Private Study"),
        LearningPathEntry(3, "Sculpting Fundamentals"),
    ]


def test_document_learning_paths_are_empty_without_a_block() -> None:
    """A typeless document has no block to read paths from, and says so rather than raising.

    **Test steps:**

    * build a document with no type
    * verify the accessor reads empty
    """
    document = RehuDocument({"core": {"sources": [{"title": "Foo", "primary": True}]}})

    assert document.learning_paths == []


def test_reading_the_learning_paths_leaves_the_document_unchanged_on_save() -> None:
    """Reading the accessor is not an edit: the serialized document is byte-identical afterwards
    ([[data-model#write-integrity]]).

    **Test steps:**

    * build a document carrying several identities' paths
    * serialize it, read the accessor, and serialize again
    * verify the two serializations match
    """
    document = document_with(USERS)
    before = document.serialize()

    assert document.learning_paths

    assert document.serialize() == before


def test_records_by_scope_projects_the_learning_path_slice_only() -> None:
    """The mapping is the learning-path slice of the ``users`` map, keyed by scope -- the ratings and flags
    beside it are a different field's business ([[field-schema#per-user-shared]]).

    **Test steps:**

    * project a map whose identity also carries a rating and a flag
    * verify only the records come through, by reference and in stored order
    """
    records = [{"title": "Mine", "index": 1, "ref": 1}]
    users = {"admin": {"rating": 4, "viewed": True, "learning_paths": records}}

    projected = learning_path_records_by_scope(users)

    assert projected == {"admin": records}
    assert projected["admin"][0] is records[0]


def test_records_by_scope_leaves_out_a_scope_with_no_records() -> None:
    """A scope carrying no paths at all is absent, so the mapping reads as *who has paths*.

    **Test steps:**

    * project a map with one identity holding paths and two holding none
    * verify only the one is listed
    """
    users = {"admin": {"learning_paths": [{"title": "Mine", "ref": 1}]}, "foo": {"rating": 2}, "bar": {}}

    assert list(learning_path_records_by_scope(users)) == ["admin"]


@mark.parametrize(
    ("record", "expected"),
    [
        param({"ref": 3}, 3, id="an-integer-slot"),
        param({}, None, id="no-slot-at-all"),
        param({"ref": "3"}, None, id="a-string-is-not-a-slot"),
        param({"ref": True}, None, id="a-bool-is-not-a-slot"),
    ],
)
def test_learning_path_ref_coerces_the_slot(record: dict[str, Any], expected: int | None) -> None:
    """The slot is read defensively, ``bool`` excluded explicitly -- ``True`` is an ``int`` in Python, and
    a slot numbered by a stray ``true`` would silently collide with a real one.

    **Test steps:**

    * read each record's slot
    * verify only a genuine integer is one
    """
    assert learning_path_ref(record) == expected


def test_owned_learning_paths_indexes_every_owner_by_slot() -> None:
    """What a subscription resolves against: every *owned* record in the block, whoever holds it
    ([[field-schema#learning-path-ownership]]).

    **Test steps:**

    * index the shared fixture map
    * verify all three owned paths are there, and the bare subscriptions are not
    """
    assert owned_learning_paths(learning_path_records_by_scope(USERS)) == {
        1: LearningPathEntry(3, "Sculpting Fundamentals"),
        2: LearningPathEntry(7, "My Sculpting Order"),
        3: LearningPathEntry(1, "Private Study"),
    }


def test_owned_learning_paths_resolves_a_duplicated_slot_by_scope_name() -> None:
    """A malformed file with two owners of one slot resolves the same way every time -- scope name order,
    not mapping insertion order.

    **Test steps:**

    * index a map where ``zed`` and ``abe`` both own ref ``1``, ``zed`` listed first
    * verify the alphabetically-first scope wins
    """
    users = {
        "zed": {"learning_paths": [{"title": "Zed", "index": 1, "ref": 1}]},
        "abe": {"learning_paths": [{"title": "Abe", "index": 2, "ref": 1}]},
    }

    assert owned_learning_paths(learning_path_records_by_scope(users)) == {1: LearningPathEntry(2, "Abe")}


def test_document_learning_path_records_carry_every_scope() -> None:
    """The editor's read is every scope's records, not the visible ones -- *what is in this file* is a
    different question from *what am I in* ([[field-schema#learning-path-ownership]], #235).

    **Test steps:**

    * read the records off a document opened as ``admin``
    * verify ``foo``'s private path is there, which the resolved accessor never shows
    """
    document = document_with(USERS, username="admin")

    assert set(document.learning_path_records) == {"public", "admin", "foo"}
    assert document.learning_path_records["foo"] == USERS["foo"]["learning_paths"]


def test_setting_the_learning_path_records_writes_each_scope() -> None:
    """The mapping is written scope by scope into the block's ``users`` map.

    **Test steps:**

    * write one owned path for ``admin`` and a subscription for ``foo``
    * verify each lands under its own identity
    """
    document = document_with({})

    document.set_learning_path_records({"admin": [{"title": "Mine", "index": 1, "ref": 1}], "foo": [{"ref": 1}]})

    users = document.data["tutorial"]["users"]
    assert users["admin"]["learning_paths"] == [{"title": "Mine", "index": 1, "ref": 1}]
    assert users["foo"]["learning_paths"] == [{"ref": 1}]


def test_setting_the_learning_path_records_leaves_the_other_per_user_keys_alone() -> None:
    """Only the ``learning_paths`` key is ever touched: a scope's rating and flags sit beside it and are
    none of this field's business ([[field-schema#per-user-shared]]).

    **Test steps:**

    * write paths into a block whose identity already carries a rating
    * verify the rating survives
    """
    document = document_with({"admin": {"rating": 4, "learning_paths": [{"title": "Old", "ref": 1}]}})

    document.set_learning_path_records({"admin": [{"title": "New", "ref": 1}]})

    assert document.data["tutorial"]["users"]["admin"] == {"rating": 4, "learning_paths": [{"title": "New", "ref": 1}]}


def test_setting_the_learning_path_records_removes_the_key_from_an_emptied_scope() -> None:
    """The last path leaving a scope takes the key with it, rather than leaving ``learning_paths: []``.

    **Test steps:**

    * write an empty mapping over a block that had one identity's paths and its rating
    * verify the key is gone and the rating stays
    """
    document = document_with({"admin": {"rating": 4, "learning_paths": [{"title": "Old", "ref": 1}]}})

    document.set_learning_path_records({})

    assert document.data["tutorial"]["users"]["admin"] == {"rating": 4}


def test_setting_the_learning_path_records_drops_a_scope_left_holding_nothing() -> None:
    """A scope that only ever existed to hold a subscription goes with it, rather than leaving an identity
    in the file that was never really there.

    **Test steps:**

    * write an empty mapping over a block whose identity carried nothing but a subscription
    * verify the identity is gone from the map
    """
    document = document_with({"admin": {"learning_paths": [{"ref": 1}]}})

    document.set_learning_path_records({})

    assert document.data["tutorial"]["users"] == {}


def test_setting_the_learning_path_records_repairs_a_malformed_scope() -> None:
    """A per-user submap that is present but not a map is replaced rather than crashed on, the same way
    every other writer here treats malformed payload ([[data-model#write-integrity]]).

    **Test steps:**

    * write a path into a block whose ``admin`` entry is a string
    * verify the path lands and the string is gone
    """
    document = document_with({"admin": "not a map"})

    document.set_learning_path_records({"admin": [{"title": "Mine", "ref": 1}]})

    assert document.data["tutorial"]["users"]["admin"] == {"learning_paths": [{"title": "Mine", "ref": 1}]}


def test_setting_no_learning_path_records_on_a_typeless_document_is_a_no_op() -> None:
    """Clearing what a typeless document does not have is nothing, not an error -- there is no block to
    remove a key from.

    **Test steps:**

    * clear the records on a document with no type
    * verify nothing was created
    """
    document = RehuDocument({"core": {"sources": [{"title": "Foo", "primary": True}]}})

    document.set_learning_path_records({})

    assert document.learning_path_records == {}


def test_next_learning_path_ref_is_one_past_the_highest_in_the_whole_file() -> None:
    """The slot is **file**-scoped, so a block this build is not even showing still holds its refs
    ([[field-schema#learning-path-ownership]]).

    **Test steps:**

    * build a document whose active block tops out at ref ``3`` and whose inactive one carries ref ``9``
    * verify the next slot is one past the file-wide highest, not the active block's
    """
    document = document_with(USERS)
    document.data["reference_images"] = {"users": {"admin": {"learning_paths": [{"title": "Other", "ref": 9}]}}}

    assert document.next_learning_path_ref() == 10


def test_next_learning_path_ref_starts_at_one_for_a_file_holding_none() -> None:
    """A file with no paths at all mints from ``1``.

    **Test steps:**

    * ask a pathless document for a slot
    * verify it is ``1``
    """
    assert document_with({}).next_learning_path_ref() == 1
