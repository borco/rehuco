"""Tests for the ``collections`` projection: the inline records a resource's series memberships."""

from typing import Any

from pytest import mark, param
from rehuco_core import CollectionEntry, LearningPathEntry, RehuDocument, collection_entries


def tutorial_with(collections: Any) -> RehuDocument:
    """Build an in-memory tutorial document whose block carries ``collections``.

    :param collections: the value to store under the block's ``collections`` key.
    :returns: the document.
    """
    return RehuDocument(
        {
            "core": {"type": "tutorial", "sources": [{"title": "Foo", "primary": True}]},
            "tutorial": {"collections": collections},
        }
    )


def test_collection_entries_sort_by_index_then_title() -> None:
    """Entries order by ``index``, and entries sharing one order alphabetically ([[field-schema#sources]]).

    **Test steps:**

    * project a list whose indexes are out of order and whose first two share an index
    * verify the result is ordered by index, then by title within the shared index
    """
    records = [
        {"title": "Zeta", "index": 0},
        {"title": "Alpha", "index": 0},
        {"title": "Middle", "index": 2},
    ]

    assert collection_entries(records) == [
        CollectionEntry(0, "Alpha"),
        CollectionEntry(0, "Zeta"),
        CollectionEntry(2, "Middle"),
    ]


@mark.parametrize(
    "records",
    [
        param("not a list", id="not-a-list"),
        param(None, id="absent"),
        param([], id="empty"),
        param(["a title"], id="record-not-a-map"),
        param([{"index": 2}], id="no-title"),
    ],
)
def test_collection_entries_drop_what_they_cannot_render(records: Any) -> None:
    """A malformed list or record reads as nothing rather than raising or inventing a row.

    **Test steps:**

    * project each malformed shape
    * verify it yields no entries
    """
    assert collection_entries(records) == []


def test_collection_entries_keep_the_stored_record_untouched() -> None:
    """The projection never mutates the records it reads ([[data-model#write-integrity]]).

    **Test steps:**

    * project a list whose record carries a cached ``url`` the projection has no slot for
    * verify the stored record is unchanged, url included
    """
    records = [{"title": "Series", "index": 2, "url": "https://example.com/series"}]

    assert collection_entries(records) == [CollectionEntry(2, "Series")]
    assert records == [{"title": "Series", "index": 2, "url": "https://example.com/series"}]


def test_a_collection_entry_is_not_a_learning_path_entry() -> None:
    """The two projections are **distinct types**, not one shared shape: a collection belongs to nobody
    where a path is owned, so nothing that reads one may silently accept the other.

    **Test steps:**

    * build the two projections of the same title and index
    * verify they do not compare equal
    """
    assert CollectionEntry(3, "Sculpting") != LearningPathEntry(3, "Sculpting")


def test_document_collections_projects_the_inline_block_records() -> None:
    """`RehuDocument.collections` reads the block's inline records, sorted ([[field-schema#sources]]).

    **Test steps:**

    * build a document whose tutorial block carries two collection memberships
    * verify both project in index order
    """
    document = tutorial_with([{"title": "Second", "index": 2}, {"title": "First", "index": 1}])

    assert document.collections == [CollectionEntry(1, "First"), CollectionEntry(2, "Second")]


def test_document_collections_are_empty_without_a_block() -> None:
    """A typeless document has no block to read memberships from, and says so rather than raising.

    **Test steps:**

    * build a document with no type
    * verify the accessor reads empty
    """
    document = RehuDocument({"core": {"sources": [{"title": "Foo", "primary": True}]}})

    assert document.collections == []


def test_reading_the_collections_leaves_the_document_unchanged_on_save() -> None:
    """Reading the accessor is not an edit: the serialized document is byte-identical afterwards
    ([[data-model#write-integrity]]).

    **Test steps:**

    * build a document whose membership carries a cached ``url``
    * serialize it, read the accessor, and serialize again
    * verify the two serializations match
    """
    document = tutorial_with([{"title": "Series", "index": 2, "url": "https://example.com"}])
    before = document.serialize()

    assert document.collections

    assert document.serialize() == before
