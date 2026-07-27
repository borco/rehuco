"""Tests for the shared title-and-position reading: what a stored record renders as."""

from typing import Any

from pytest import mark, param
from rehuco_core.titled_index import titled_index


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
