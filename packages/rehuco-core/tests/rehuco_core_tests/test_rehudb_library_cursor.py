"""Tests for how far a site's records reach in its library, the cursor a library scan resumes from (#682,
[[acquisition-tooling#library-scan-job]]), and the rows a full rescan checks the library against.

The cache is :mod:`test_rehudb`'s, over a shared-cache in-memory database; its fixtures are imported by name.
"""

from typing import Final

import pytest
from pytest import fixture
from rehuco_core import CatalogCache, LibraryCursor, MappedRoot

from rehuco_core_tests.mapped_roots import mapped
from rehuco_core_tests.test_rehudb import (  # noqa: F401  # pylint: disable=unused-import
    fixture_cache,
    fixture_database,
    fixture_memory,
    record,
    two_roots,
)

NEWEST: Final = "2024-05-03T12:34:56.789123Z"
"""The newest acquisition among the first root's Fab records."""

SAME_MILLISECOND: Final = "2024-05-03T12:34:56.789001Z"
"""An acquisition in :data:`NEWEST`'s millisecond, earlier by the microseconds -- a bundle's contents (#686)."""


@fixture(name="library")
def fixture_library(cache: CatalogCache) -> tuple[CatalogCache, MappedRoot, MappedRoot]:
    """A cache whose first root holds Fab records acquired at various times -- two in the newest millisecond, one with
    no acquisition, one from another store acquired later -- and whose second root holds a later Fab record.

    :param cache: the cache to fill.
    :returns: it, filled, and its two roots.
    """
    rehuco, first, second = two_roots()
    cache.reconcile_roots(mapped(rehuco))
    cache.apply_root_scan(
        first.root_id,
        [
            record("a/info.rehu", title="Old", site_ids=(("Fab", "f-1"),), acquired="2023-01-02T03:04:05.000000Z"),
            record("b/info.rehu", title="Newest", site_ids=(("Fab", "f-2"),), acquired=NEWEST),
            record("c/info.rehu", title="Same ms", site_ids=(("Fab", "f-3"),), acquired=SAME_MILLISECOND),
            record("d/info.rehu", title="Undated", site_ids=(("Fab", "f-4"),)),
            record("e/info.rehu", title="Udemy", site_ids=(("Udemy", "u-1"),), acquired="2025-01-01T00:00:00.000000Z"),
            record("f/info.rehu", title="No id", acquired="2025-06-01T00:00:00.000000Z"),
        ],
    )
    cache.apply_root_scan(
        second.root_id,
        [record("g/info.rehu", title="Elsewhere", site_ids=(("Fab", "f-9"),), acquired="2026-01-01T00:00:00.000000Z")],
    )
    return cache, first, second


def test_the_cursor_is_the_newest_acquisition_with_the_ids_in_its_millisecond(
    library: tuple[CatalogCache, MappedRoot, MappedRoot],
) -> None:
    """The listing is resumed at the newest millisecond, so the cursor names every id already filed in it.

    **Test steps:**

    * fill a root with Fab records, two in the newest millisecond, beside another store's later one
    * read the root's Fab cursor
    * verify it holds the newest acquisition and the two ids of that millisecond, nothing of the other store
    """
    cache, first, _ = library

    cursor = cache.library_cursor("Fab", first.root_id)

    assert cursor == LibraryCursor(NEWEST, frozenset({"f-2", "f-3"}))


def test_the_cursor_reads_one_root_and_the_site_ignoring_case(
    library: tuple[CatalogCache, MappedRoot, MappedRoot],
) -> None:
    """A site's records in another root reach elsewhere; the site is a publisher, compared ignoring case.

    **Test steps:**

    * read the Fab cursor of the second root, with the site spelled in lower case
    * verify it is the second root's one record, not the first root's
    """
    cache, _, second = library

    cursor = cache.library_cursor("fab", second.root_id)

    assert cursor == LibraryCursor("2026-01-01T00:00:00.000000Z", frozenset({"f-9"}))


def test_a_roots_rows_are_every_record_of_it(library: tuple[CatalogCache, MappedRoot, MappedRoot]) -> None:
    """A rebalance reads every record of one root, whatever its site (#681).

    **Test steps:**

    * read the rows of the first root of a cache with two
    * verify its records alone, in path order
    """
    cache, first, _ = library

    rows = cache.root_rows(first.root_id)

    assert [row.record.path for row in rows] == [f"{letter}/info.rehu" for letter in "abcdef"]


def test_a_site_with_no_dated_record_has_an_empty_cursor(library: tuple[CatalogCache, MappedRoot, MappedRoot]) -> None:
    """No record with an acquisition means the listing is read from the start.

    **Test steps:**

    * read the cursor of a site no record of the root names
    * verify it is empty, resuming nowhere
    """
    cache, first, _ = library

    cursor = cache.library_cursor("ArtStation", first.root_id)

    assert cursor == LibraryCursor()
    assert cursor.millisecond is None


def test_the_library_rows_are_the_sites_records_in_the_root(
    library: tuple[CatalogCache, MappedRoot, MappedRoot],
) -> None:
    """A full rescan checks every record of the site in the root, dated or not.

    **Test steps:**

    * read the first root's Fab rows
    * verify they are its four Fab records, undated included, and none of another store, root or none
    """
    cache, first, _ = library

    rows = cache.library_rows("Fab", first.root_id)

    assert [row.record.title for row in rows] == ["Old", "Newest", "Same ms", "Undated"]


@pytest.mark.parametrize(
    ("acquired", "site_id", "covered"),
    [
        ("2023-01-02T03:04:05.000000Z", "f-1", True),
        (SAME_MILLISECOND, "f-3", True),
        ("2024-05-03T12:34:56.789999Z", "f-5", False),
        ("2024-05-03T12:34:56.790000Z", "f-2", False),
    ],
    ids=["earlier", "filed-in-its-millisecond", "new-in-its-millisecond", "later"],
)
def test_a_cursor_covers_what_is_before_it_and_what_is_filed_in_its_millisecond(
    acquired: str, site_id: str, covered: bool
) -> None:
    """A resumed listing passes by what is filed, and nothing else.

    **Test steps:**

    * build a cursor at a millisecond holding two ids
    * ask it about an earlier entry, a filed and a new one in its millisecond, and a later one
    * verify it covers only the earlier and the filed ones
    """
    cursor = LibraryCursor(NEWEST, frozenset({"f-2", "f-3"}))

    assert cursor.covers(acquired, site_id) is covered


def test_an_empty_cursor_covers_nothing() -> None:
    """A scan with no record yet reads the listing from its first entry.

    **Test steps:**

    * ask an empty cursor about an old entry
    * verify it is not covered
    """
    assert LibraryCursor().covers("2000-01-01T00:00:00.000000Z", "f-1") is False


def test_a_record_not_dated_to_the_millisecond_moves_no_cursor(cache: CatalogCache) -> None:
    """A partial date sorts by its text, not its time, so a larger one would put the cursor past items never filed.

    **Test steps:**

    * fill a root with a Fab record timed to the microsecond and a later one dated by its month only
    * read the root's Fab cursor
    * verify it is the timed record's
    """
    rehuco, first, _ = two_roots()
    cache.reconcile_roots(mapped(rehuco))
    cache.apply_root_scan(
        first.root_id,
        [
            record("a/info.rehu", site_ids=(("Fab", "f-1"),), acquired=NEWEST),
            record("b/info.rehu", site_ids=(("Fab", "f-2"),), acquired="2025-12"),
        ],
    )

    assert cache.library_cursor("Fab", first.root_id) == LibraryCursor(NEWEST, frozenset({"f-1"}))
