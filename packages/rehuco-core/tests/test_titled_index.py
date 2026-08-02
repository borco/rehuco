"""Tests for the shared title-and-position reading: what a stored record renders as."""

from typing import Any

from pytest import mark, param
from rehuco_core.titled_index import titled_index, with_titled_index


def test_titled_index_reads_a_full_record() -> None:
    """A record with a title and an integer index reads as that pair, index first.

    **Test steps:**

    * read a well-formed record
    * verify the ``(index, title)`` pair comes back
    """
    assert titled_index({"title": "Series", "index": 2}) == (2, "Series")


@mark.parametrize(
    "record",
    [
        param({"index": 2}, id="no-title"),
        param({"title": "   ", "index": 2}, id="blank-title"),
        param({"title": 7, "index": 2}, id="title-not-a-string"),
        param({"title": None}, id="null-title"),
        param({}, id="empty-record"),
    ],
)
def test_titled_index_refuses_a_record_with_no_usable_title(record: dict[str, Any]) -> None:
    """No title means nothing to show, so the record is refused rather than rendered blank.

    **Test steps:**

    * read each titleless shape
    * verify it reads as ``None``
    """
    assert titled_index(record) is None


@mark.parametrize(
    "record",
    [
        param({"title": "Series", "index": "3"}, id="string"),
        param({"title": "Series", "index": None}, id="null"),
        param({"title": "Series", "index": True}, id="bool"),
        param({"title": "Series"}, id="absent"),
    ],
)
def test_titled_index_reads_a_non_integer_index_as_zero(record: dict[str, Any]) -> None:
    """A missing or non-integer ``index`` reads as ``0`` -- the same *no position chosen* an import writes.

    **Test steps:**

    * read a record whose index is malformed or absent
    * verify the title survives at index ``0``
    """
    assert titled_index(record) == (0, "Series")


def test_titled_index_leaves_the_record_untouched() -> None:
    """Reading coerces nothing into the payload ([[data-model#write-integrity]]).

    **Test steps:**

    * read a record with a malformed index and an extra key the projection has no slot for
    * verify the record is unchanged
    """
    record = {"title": "Series", "index": "3", "url": "https://example.com/series"}

    assert titled_index(record) == (0, "Series")
    assert record == {"title": "Series", "index": "3", "url": "https://example.com/series"}


def test_with_titled_index_keeps_every_other_key() -> None:
    """The merge rule both membership editors are held to: a cell writes back into the record its row was
    built from, changing only the key it owns (#235).

    **Test steps:**

    * retitle a record carrying a cached ``url`` and a slot no editor shows
    * verify the title changed and both other keys survived
    """
    record = {"title": "Old", "index": 2, "url": "https://example.com", "ref": 7}

    assert with_titled_index(record, title="New") == {
        "title": "New",
        "index": 2,
        "url": "https://example.com",
        "ref": 7,
    }


def test_with_titled_index_never_mutates_the_record_it_was_given() -> None:
    """A document hands its lists out by reference, so an edit builds a new record rather than moving an
    unsaved document's own state under it ([[data-model#write-integrity]]).

    **Test steps:**

    * edit a record
    * verify the original is untouched and the result is a different object
    """
    record = {"title": "Old", "index": 2}

    edited = with_titled_index(record, title="New", index=5)

    assert record == {"title": "Old", "index": 2}
    assert edited is not record


def test_with_titled_index_writes_an_unplaced_index_explicitly() -> None:
    """``0`` is stored rather than dropped: absent and ``0`` are *defined* to be the same value here, and
    the legacy import writes it explicitly (#188) -- so storing it keeps an edited record looking like an
    imported one instead of minting a second spelling of *no position chosen*.

    **Test steps:**

    * set a record's position to ``0``
    * verify the key is present and reads back as unplaced
    """
    edited = with_titled_index({"title": "Series", "index": 4}, index=0)

    assert edited == {"title": "Series", "index": 0}
    assert titled_index(edited) == (0, "Series")


def test_with_titled_index_changes_nothing_when_told_nothing() -> None:
    """An omitted argument leaves its key exactly as it was, which is what lets one function serve both
    cells without either knowing about the other.

    **Test steps:**

    * call with neither a title nor an index
    * verify the record comes back equal
    """
    record = {"title": "Series", "index": 2}

    assert with_titled_index(record) == record
