"""Tests for what the catalog cache tells the file notifier's listeners (#511): the rows a scan touched, a root's
reachability, and the records at or beneath a changed path.

The cache is :mod:`test_rehudb`'s, over a shared-cache in-memory database; its fixtures are imported by name.
"""

from pathlib import Path

from rehuco_core import CatalogCache, CatalogRecord, RecordKind, RehucoFile, RehucoRoot

from rehuco_core_tests.test_rehudb import (  # noqa: F401  # pylint: disable=unused-import
    TUTORIALS,
    fixture_cache,
    fixture_database,
    fixture_filled,
    fixture_memory,
    ids,
    record,
)

# region The rows a scan touched


def test_a_scan_reports_the_rows_it_read_and_removed_but_not_those_it_kept(
    filled: tuple[CatalogCache, RehucoRoot, RehucoRoot],
) -> None:
    """``touched`` collects every row the scan read -- found again or new -- and every row it removed; a record an
    incremental scan found unchanged, and every other root's row, are no part of it.

    **Test steps:**

    * scan four records under the first root and one under the second
    * scan the first root again: one record read again, one new, one unchanged, one gone
    * verify ``touched`` holds the read, new and gone rows' ids, and neither the unchanged one nor the other root's
    """
    cache, first, second = filled
    cache.apply_root_scan(first.root_id, [record("read.rehu"), record("kept.rehu"), record("gone.rehu")])
    cache.apply_root_scan(second.root_id, [record("other.rehu")])
    before = ids(cache)
    touched: set[int] = set()

    applied = cache.apply_root_scan(
        first.root_id, [record("read.rehu"), record("new.rehu")], unchanged=("kept.rehu",), touched=touched
    )

    after = ids(cache)
    assert applied
    assert touched == {before["read.rehu"], after["new.rehu"], before["gone.rehu"]}


def test_a_scan_of_a_removed_root_touches_nothing(filled: tuple[CatalogCache, RehucoRoot, RehucoRoot]) -> None:
    """A scan dropped because its root went meanwhile changed no row, so it reports none.

    **Test steps:**

    * remove a root, then apply a scan of it, asking for the rows it touched
    * verify it was not applied and reported nothing
    """
    cache, first, _ = filled
    cache.remove_root(first.root_id)
    touched: set[int] = set()

    assert not cache.apply_root_scan(first.root_id, [record("a.rehu")], touched=touched)
    assert not touched


# endregion

# region A root's reachability


def test_a_roots_reachability_follows_each_mark_and_its_rows_stay(
    filled: tuple[CatalogCache, RehucoRoot, RehucoRoot],
) -> None:
    """``mark_root_reachable`` records what the root's notifier saw, either way, and touches nothing else -- not its
    rows, not when it was scanned, not the other root; ``mark_root_unreachable`` is the same mark, ``False``.

    **Test steps:**

    * scan a record under each root, at a known time
    * mark the first root unreachable, then reachable, then unreachable through ``mark_root_unreachable``
    * verify after each its reachability, its scan time and every row, and the second root still reachable
    """
    cache, first, second = filled
    cache.apply_root_scan(first.root_id, [record("a/info.rehu")], scanned_at=1000.0)
    cache.apply_root_scan(second.root_id, [record("p/info.rehu")], scanned_at=2000.0)
    rows = ids(cache)

    for mark, expected in (
        (lambda: cache.mark_root_reachable(first.root_id, False), False),
        (lambda: cache.mark_root_reachable(first.root_id, True), True),
        (lambda: cache.mark_root_unreachable(first.root_id), False),
    ):
        mark()
        tutorials, packs = cache.roots()
        assert (tutorials.reachable, tutorials.scanned_at) == (expected, 1000.0)
        assert (packs.reachable, packs.scanned_at) == (True, 2000.0)
        assert ids(cache) == rows


# endregion

# region The records at or beneath a path


def test_the_records_at_or_beneath_a_path_are_spelled_from_their_root(
    filled: tuple[CatalogCache, RehucoRoot, RehucoRoot],
) -> None:
    """A record answers itself, a folder every record beneath it, as absolute paths under the root's folder; a root's
    own folder, a sibling that merely starts alike, and a path under no root add nothing.

    **Test steps:**

    * scan three records under the first root, two of them in one folder and one in a sibling ``ab``
    * verify a record, a folder, the root itself, and a path elsewhere each answer what they hold
    """
    cache, first, _ = filled
    cache.apply_root_scan(first.root_id, [record("a/info.rehu"), record("a/b/info.rehu"), record("ab/info.rehu")])

    assert cache.record_paths([TUTORIALS / "a" / "info.rehu"]) == [TUTORIALS / "a" / "info.rehu"]
    assert sorted(cache.record_paths([TUTORIALS / "a", Path("Z:/elsewhere/a")])) == [
        TUTORIALS / "a" / "b" / "info.rehu",
        TUTORIALS / "a" / "info.rehu",
    ]
    assert not cache.record_paths([TUTORIALS, Path("Z:/elsewhere")])


def test_a_record_held_by_nested_roots_or_asked_twice_is_answered_once(cache: CatalogCache) -> None:
    """Where roots nest, a record has a row under each; and a caller may name one path twice, or a record and its
    folder: each record is still answered once.

    **Test steps:**

    * reconcile an outer root and a root nested in it, and scan the same record under both
    * verify the record, asked for directly, twice, and with its folder, is answered once
    """
    rehuco = RehucoFile.new()
    rehuco.add_root(TUTORIALS)
    rehuco.add_root(TUTORIALS / "pack")
    outer, inner = rehuco.roots
    cache.reconcile_roots(rehuco.roots)
    cache.apply_root_scan(outer.root_id, [CatalogRecord("pack/x/info.rehu", RecordKind.REHU)])
    cache.apply_root_scan(inner.root_id, [CatalogRecord("x/info.rehu", RecordKind.REHU)])
    path = TUTORIALS / "pack" / "x" / "info.rehu"

    assert len(cache.rows()) == 2
    assert cache.record_paths([path]) == [path]
    assert cache.record_paths([path, path, path.parent]) == [path]


# endregion
