"""Tests for the ``collections`` projection: the inline records a resource's series memberships."""

from typing import Any

from pytest import mark, param
from rehuco_core import CollectionEntry, LearningPathEntry, RehuDocument, collection_entries, collection_records


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


def test_collection_records_are_the_stored_records_by_reference() -> None:
    """The editor's read is the records themselves, in stored order -- a title cell that rebuilt its
    record from the two columns it shows would sever the ``url`` beside it (#235).

    **Test steps:**

    * read the records off a document whose membership carries a cached ``url``
    * verify the ``url`` is there, and the record is the stored object itself
    """
    stored = [{"title": "Series", "index": 2, "url": "https://example.com"}]
    document = tutorial_with(stored)

    records = document.collection_records

    assert records == stored
    assert records[0] is stored[0]


def test_collection_records_keep_the_stored_order() -> None:
    """Stored order is kept where the projection sorts: ``index`` is the position, and the records' own
    order means nothing -- which is exactly why an editor must not quietly rewrite it.

    **Test steps:**

    * read the records off a document whose memberships are stored out of index order
    * verify they come back as stored, unlike :attr:`collections`
    """
    document = tutorial_with([{"title": "Second", "index": 2}, {"title": "First", "index": 1}])

    assert [record["title"] for record in document.collection_records] == ["Second", "First"]
    assert [entry.title for entry in document.collections] == ["First", "Second"]


@mark.parametrize(
    ("stored", "expected"),
    [
        param("not a list", [], id="value-not-a-list"),
        param([], [], id="an-empty-list"),
        param(["not a record", {"title": "Real"}], [{"title": "Real"}], id="a-non-record-is-skipped"),
    ],
)
def test_collection_records_are_read_defensively(stored: Any, expected: list[dict[str, Any]]) -> None:
    """Malformed payload reads as no records the same way the projection reads it as no entries
    ([[data-model#write-integrity]]).

    **Test steps:**

    * read each malformed shape, through the projection and through the document alike
    * verify only genuine records come through
    """
    assert collection_records(stored) == expected
    assert tutorial_with(stored).collection_records == expected


def test_setting_the_collection_records_stores_them_whole() -> None:
    """A table edit is one new list, so the whole list is what is written.

    **Test steps:**

    * write two records over a document that had one
    * verify the block carries exactly what was written
    """
    document = tutorial_with([{"title": "Old"}])

    document.set_collection_records([{"title": "One", "index": 1}, {"title": "Two", "index": 2}])

    assert document.data["tutorial"]["collections"] == [{"title": "One", "index": 1}, {"title": "Two", "index": 2}]


def test_setting_no_collection_records_removes_the_key() -> None:
    """An emptied list removes the key rather than storing ``[]`` -- absent is not empty
    ([[field-schema#deferred-items]]), and a resource belonging to no series should read the way one
    imported with no collection does.

    **Test steps:**

    * clear the memberships of a document that had one
    * verify the key is gone from the block
    """
    document = tutorial_with([{"title": "Old"}])

    document.set_collection_records([])

    assert "collections" not in document.data["tutorial"]


def test_setting_the_collection_records_does_not_adopt_the_caller_s_list() -> None:
    """The list is copied on the way in, so a caller mutating its own afterwards cannot reach the document.

    **Test steps:**

    * write a list, then append to the caller's own copy of it
    * verify the document still holds one record
    """
    document = tutorial_with(None)
    records = [{"title": "One"}]

    document.set_collection_records(records)
    records.append({"title": "Two"})

    assert document.data["tutorial"]["collections"] == [{"title": "One"}]


def test_setting_no_collection_records_on_a_typeless_document_is_a_no_op() -> None:
    """Clearing what a typeless document does not have is nothing, not an error.

    **Test steps:**

    * clear the memberships on a document with no type
    * verify the accessor still reads empty
    """
    document = RehuDocument({"core": {"sources": [{"title": "Foo", "primary": True}]}})

    document.set_collection_records([])

    assert document.collection_records == []
