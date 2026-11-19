"""Tests for the store ids the catalog cache keeps per source, and the lookup by site and id (#675,
[[assets#site-id]]).

The cache is :mod:`test_rehudb`'s, over a shared-cache in-memory database; its fixtures are imported by name.
"""

import re
from collections.abc import Callable

from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_core import CatalogCache, CatalogRow, MappedRoot

from rehuco_core_tests.mapped_roots import mapped
from rehuco_core_tests.test_rehudb import (  # noqa: F401  # pylint: disable=unused-import
    MemoryDatabase,
    fixture_cache,
    fixture_database,
    fixture_memory,
    record,
    two_roots,
    upgraded_one_record,
)


@fixture(name="stores")
def fixture_stores(cache: CatalogCache) -> tuple[CatalogCache, MappedRoot, MappedRoot]:
    """A cache whose two roots hold records with store ids: one item owned on two stores, one store's item found in
    both roots, and a record with no id at all.

    :param cache: the cache to fill.
    :returns: it, filled, and its two roots.
    """
    rehuco, first, second = two_roots()
    cache.reconcile_roots(mapped(rehuco))
    cache.apply_root_scan(
        first.root_id,
        [
            record("a/info.rehu", title="Both", site_ids=(("Fab", "f-1"), ("Udemy", "u-9"))),
            record("b/info.rehu", title="Fab only", site_ids=(("Fab", "f-2"),)),
            record("c/info.rehu", title="No id"),
        ],
    )
    cache.apply_root_scan(second.root_id, [record("d/info.rehu", title="Elsewhere", site_ids=(("Fab", "f-2"),))])
    return cache, first, second


def titles(rows: list[CatalogRow]) -> list[str]:
    """The titles of ``rows``, in order."""
    return [row.record.title for row in rows]


def test_a_record_is_found_by_any_of_its_sources_ids(stores: tuple[CatalogCache, MappedRoot, MappedRoot]) -> None:
    """An item owned on two stores is one record found from either store's id.

    **Test steps:**

    * fill the cache with a record carrying a Fab and a Udemy id
    * look up each pair
    * verify both find that record, with its ids read back in order
    """
    cache, _, _ = stores

    (by_fab,) = cache.find_by_site_id("Fab", "f-1")
    (by_udemy,) = cache.find_by_site_id("Udemy", "u-9")

    assert by_fab == by_udemy
    assert by_fab.record.site_ids == (("Fab", "f-1"), ("Udemy", "u-9"))


def test_the_site_matches_ignoring_case_and_the_id_exactly(stores: tuple[CatalogCache, MappedRoot, MappedRoot]) -> None:
    """The site is a publisher, compared as the publishers table compares names; the id is the store's own spelling.

    **Test steps:**

    * look up a known id under its site spelled in another case
    * look it up with its id spelled in another case, and under another site
    * verify only the first finds the record
    """
    cache, _, _ = stores

    assert titles(cache.find_by_site_id("fab", "f-1")) == ["Both"]
    assert not cache.find_by_site_id("Fab", "F-1")
    assert not cache.find_by_site_id("Udemy", "f-1")


def test_a_lookup_within_a_root_finds_only_that_roots_record(
    stores: tuple[CatalogCache, MappedRoot, MappedRoot],
) -> None:
    """The same item in two roots is two records; a lookup names the root it asks about.

    **Test steps:**

    * look up an id that records in both roots carry, with no root and then with each
    * verify the first finds both in root order, and each other finds its own root's record
    """
    cache, first, second = stores

    assert titles(cache.find_by_site_id("Fab", "f-2")) == ["Fab only", "Elsewhere"]
    assert titles(cache.find_by_site_id("Fab", "f-2", first.root_id)) == ["Fab only"]
    assert titles(cache.find_by_site_id("Fab", "f-2", second.root_id)) == ["Elsewhere"]


def test_an_id_no_record_names_finds_nothing(stores: tuple[CatalogCache, MappedRoot, MappedRoot]) -> None:
    """An unknown id is an empty answer, not an error.

    **Test steps:**

    * look up an id no record carries
    * verify nothing is found
    """
    cache, _, _ = stores

    assert cache.find_by_site_id("Fab", "missing") == []


def test_a_rewritten_record_is_found_by_its_new_ids_only(stores: tuple[CatalogCache, MappedRoot, MappedRoot]) -> None:
    """A record read again replaces its ids, so one it no longer names stops finding it.

    **Test steps:**

    * write a record's row again with a different id
    * verify the old id finds nothing and the new one finds the record
    """
    cache, first, _ = stores

    cache.upsert_record(first.root_id, record("a/info.rehu", title="Both", site_ids=(("Fab", "f-3"),)))

    assert not cache.find_by_site_id("Fab", "f-1")
    assert not cache.find_by_site_id("Udemy", "u-9")
    assert titles(cache.find_by_site_id("Fab", "f-3")) == ["Both"]


def test_a_record_gone_takes_its_ids_with_it(
    stores: tuple[CatalogCache, MappedRoot, MappedRoot], database: MemoryDatabase
) -> None:
    """A record a scan no longer finds leaves no id behind.

    **Test steps:**

    * scan the first root again, finding only the record with no id
    * verify its old records' ids find nothing and only the second root's id rows are left
    """
    cache, first, _ = stores

    cache.apply_root_scan(first.root_id, [record("c/info.rehu", title="No id")])

    assert not cache.find_by_site_id("Fab", "f-1")
    assert titles(cache.find_by_site_id("Fab", "f-2")) == ["Elsewhere"]
    assert database.scalar("SELECT COUNT(*) FROM resource_sources") == 1


def test_a_version_8_cache_upgrades_with_no_ids_and_stale(
    memory: Callable[[], MemoryDatabase], mocker: MockerFixture
) -> None:
    """The version-9 step adds the sources' ids (#675): a row from before it has none, and carries no signature a real
    file could match, so the next scan reads its ids in.

    **Test steps:**

    * build a version-8 cache holding one scanned record and reopen it with the full chain
    * verify the stamp is current and the row is kept with no ids and its signature cleared
    """
    row = upgraded_one_record(memory, mocker, 8)

    assert (row.record.title, row.record.site_ids) == ("T", ())
    assert (row.record.mtime_ns, row.record.content_hash) == (0, "")


def test_the_lookup_reads_the_ids_through_their_index(stores: tuple[CatalogCache, MappedRoot, MappedRoot]) -> None:
    """Finding a record by site and id is an indexed lookup, never a walk ([[assets#site-id]]): every statement it
    runs reaches the ids through the ``(site, site_id)`` index and ``resources`` through one of its own.

    **Test steps:**

    * trace the statements a lookup within one root runs
    * ask SQLite for the plan of each
    * verify each searches the ``(site, site_id)`` index and none scans ``resources``
    """
    cache, first, _ = stores
    statements: list[str] = []
    cache.connection.set_trace_callback(statements.append)
    try:
        cache.find_by_site_id("Fab", "f-2", first.root_id)
    finally:
        cache.connection.set_trace_callback(None)
    plans = [
        [step for (*_, step) in cache.connection.execute(f"EXPLAIN QUERY PLAN {statement}")]
        for statement in statements
        if "FROM resources r" in statement
    ]

    assert len(plans) == 5  # the rows, the three value tables and the sources' ids
    assert all(any("resource_sources_site (site=? AND site_id=?)" in step for step in steps) for steps in plans)
    assert not [step for steps in plans for step in steps if re.fullmatch(r"SCAN r( .*)?", step)]
