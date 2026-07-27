"""Tests for the ``learning_paths`` projection: owned, subscribed, and published, per identity."""

from typing import Any, Final

from pytest import mark, param
from rehuco_core import LearningPathEntry, RehuDocument, current_block_version, visible_learning_paths

# A block's ``users`` map exercising every ownership shape ([[field-schema#learning-path-ownership]]):
# ``public`` holds a published copy, ``admin`` owns one path and subscribes to the published one, and
# ``foo`` owns a path nobody else may see.
USERS: Final = {
    "public": {"learning_paths": [{"title": "Sculpting Fundamentals", "index": 3, "ref": 1}]},
    "admin": {"learning_paths": [{"ref": 1}, {"title": "My Sculpting Order", "index": 7, "ref": 2}]},
    "foo": {"learning_paths": [{"ref": 1}, {"title": "Private Study", "index": 1, "ref": 3}]},
}


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
    assert visible_learning_paths(USERS, username="admin") == [
        LearningPathEntry(3, "Sculpting Fundamentals"),
        LearningPathEntry(7, "My Sculpting Order"),
    ]


def test_visible_learning_paths_never_shows_another_users_private_path() -> None:
    """An identity with nothing of its own still sees the public scope, and only that.

    **Test steps:**

    * resolve for an identity absent from the map
    * verify it sees the published path alone -- neither ``admin``'s nor ``foo``'s private one
    """
    assert visible_learning_paths(USERS, username="stranger") == [LearningPathEntry(3, "Sculpting Fundamentals")]


def test_visible_learning_paths_shows_a_subscribed_and_published_path_once() -> None:
    """A path reached twice -- subscribed to *and* published -- renders once, keyed by its ``ref``.

    **Test steps:**

    * resolve for ``foo``, who subscribes to the ref the public scope also carries
    * verify the published path appears once, alongside ``foo``'s own
    """
    assert visible_learning_paths(USERS, username="foo") == [
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

    assert visible_learning_paths(users, username="admin") == [LearningPathEntry(0, "Mine")]


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

    assert visible_learning_paths(users, username="admin") == [LearningPathEntry(1, "Private Study")]


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

    assert visible_learning_paths(users, username="admin") == [LearningPathEntry(7, "My Order")]


def test_visible_learning_paths_renders_a_record_carrying_no_ref() -> None:
    """A full record with no ``ref`` -- nothing can subscribe to it, so nothing can duplicate it either --
    still renders on its own terms.

    **Test steps:**

    * give the identity one record with no ref
    * verify it is shown
    """
    users = {"admin": {"learning_paths": [{"title": "Refless", "index": 4}]}}

    assert visible_learning_paths(users, username="admin") == [LearningPathEntry(4, "Refless")]


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
    assert visible_learning_paths(users, username="admin") == []


def test_visible_learning_paths_resolves_the_public_scope_for_the_public_identity() -> None:
    """An identity that happens to be named ``public`` reads that scope once, not twice.

    The reserved scope is not enforced as a username yet, so the resolution must be well-behaved when
    the two coincide rather than double-rendering the published paths.

    **Test steps:**

    * resolve for ``public``
    * verify the published path is listed exactly once
    """
    assert visible_learning_paths(USERS, username="public") == [LearningPathEntry(3, "Sculpting Fundamentals")]


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
