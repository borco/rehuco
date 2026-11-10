"""Tests for the cache following a rename without reading a record (#373, #376), and a move across roots (#339):
every row at or beneath a renamed source lands at the same offset beneath its destination, in the destination's root.

Split from :mod:`test_rehudb`, whose cache, over a shared-cache in-memory database, and whose fixtures are imported by
name.
"""

from pathlib import Path
from typing import Final

from pytest_mock import MockerFixture
from rehuco_core import CatalogCache, CatalogRecord, MappedRoot, RecordKind

from rehuco_core_tests.test_rehudb import (  # noqa: F401  # pylint: disable=unused-import
    TUTORIALS,
    fixture_cache,
    fixture_database,
    fixture_filled,
    fixture_memory,
    ids,
    record,
)


def test_a_renamed_directory_rebases_every_record_beneath_it(
    filled: tuple[CatalogCache, MappedRoot, MappedRoot],
) -> None:
    """A directory-scoped collection's rename moves its own record and every nested ``.rehu`` and ``.tc``, ids and
    values kept, without reading one; a sibling whose name merely starts alike, and the other root, stay.

    **Test steps:**

    * fill ``series/`` with nested records, beside ``seriesX/``, and a row under the other root
    * apply the one pair ``series`` -> ``saga``
    * verify the rebased paths, the ids, the values, and the rows left alone
    """
    cache, first, second = filled
    nested = [record("series/info.rehu", authors=("Ann",)), record("series/a/info.rehu")]
    cache.apply_root_scan(
        first.root_id, [*nested, CatalogRecord("series/b/Info.tc", RecordKind.TC), record("seriesX/info.rehu")]
    )
    cache.apply_root_scan(second.root_id, [record("series/info.rehu")])
    before = {(row.root_id, row.record.path): row.resource_id for row in cache.rows()}

    moved = cache.apply_relocation([(TUTORIALS / "series", TUTORIALS / "saga")])

    assert moved == 3
    rows = {(row.root_id, row.record.path): row for row in cache.rows()}
    assert {(root_id, path): row.resource_id for (root_id, path), row in rows.items()} == {
        (first.root_id, "saga/info.rehu"): before[(first.root_id, "series/info.rehu")],
        (first.root_id, "saga/a/info.rehu"): before[(first.root_id, "series/a/info.rehu")],
        (first.root_id, "saga/b/Info.tc"): before[(first.root_id, "series/b/Info.tc")],
        (first.root_id, "seriesX/info.rehu"): before[(first.root_id, "seriesX/info.rehu")],
        (second.root_id, "series/info.rehu"): before[(second.root_id, "series/info.rehu")],
    }
    assert rows[(first.root_id, "saga/info.rehu")].record.authors == ("Ann",)
    assert cache.signature(first.root_id, "saga/a/info.rehu") is not None


def test_a_file_scoped_rename_moves_only_its_own_record(filled: tuple[CatalogCache, MappedRoot, MappedRoot]) -> None:
    """``foo.rehu``'s siblings and sidecars travel in the plan but have no rows; ``foobar.rehu`` is another
    resource."""
    cache, first, _ = filled
    cache.apply_root_scan(first.root_id, [record("dir/foo.rehu"), record("dir/foobar.rehu")])
    before = ids(cache)
    plan = [
        (TUTORIALS / f"dir/foo{tail}", TUTORIALS / f"dir/bar{tail}") for tail in (".rehu", ".zip", ".sfv", "00.jpg")
    ]

    assert cache.apply_relocation(plan) == 1
    assert ids(cache) == {"dir/bar.rehu": before["dir/foo.rehu"], "dir/foobar.rehu": before["dir/foobar.rehu"]}


def test_a_folder_rename_carries_its_file_scoped_record_and_that_records_rename_only_itself(
    filled: tuple[CatalogCache, MappedRoot, MappedRoot],
) -> None:
    """A folder holding ``info.rehu`` and ``bar.rehu``: renaming the folder rebases both; renaming ``bar`` touches
    only ``bar``'s row."""
    cache, first, _ = filled
    cache.apply_root_scan(first.root_id, [record("pack/info.rehu"), record("pack/bar.rehu")])
    before = ids(cache)

    assert cache.apply_relocation([(TUTORIALS / "pack", TUTORIALS / "kit")]) == 2
    assert cache.apply_relocation([(TUTORIALS / "kit/bar.rehu", TUTORIALS / "kit/baz.rehu")]) == 1

    assert ids(cache) == {"kit/info.rehu": before["pack/info.rehu"], "kit/baz.rehu": before["pack/bar.rehu"]}


def test_a_case_only_rename_on_a_case_insensitive_filesystem_respells_in_place(
    filled: tuple[CatalogCache, MappedRoot, MappedRoot], mocker: MockerFixture
) -> None:
    """Both ends share their keys, so the rows moving are not mistaken for stale ones already at the destination."""
    mocker.patch("rehuco_core.rehudb.catalog_path_key", side_effect=str.casefold)
    cache, first, _ = filled
    cache.apply_root_scan(first.root_id, [record("course/info.rehu"), record("course/lesson.rehu")])
    before = ids(cache)

    assert cache.apply_relocation([(TUTORIALS / "course", TUTORIALS / "Course")]) == 2

    assert ids(cache) == {
        "Course/info.rehu": before["course/info.rehu"],
        "Course/lesson.rehu": before["course/lesson.rehu"],
    }


def test_a_stale_row_at_the_destination_gives_way(filled: tuple[CatalogCache, MappedRoot, MappedRoot]) -> None:
    """The rename found nothing there, so a row there is out of date."""
    cache, first, _ = filled
    cache.apply_root_scan(first.root_id, [record("old/info.rehu", title="Moved"), record("new/info.rehu")])
    before = ids(cache)

    cache.apply_relocation([(TUTORIALS / "old", TUTORIALS / "new")])

    (row,) = cache.rows()
    assert (row.record.path, row.resource_id, row.record.title) == ("new/info.rehu", before["old/info.rehu"], "Moved")


def test_a_rename_of_the_root_itself_leaves_its_rows_alone(filled: tuple[CatalogCache, MappedRoot, MappedRoot]) -> None:
    """Relative to the root, nothing moved; where the root now is, is the ``.rehuco``'s to say."""
    cache, first, _ = filled
    cache.apply_root_scan(first.root_id, [record("info.rehu")])

    assert cache.apply_relocation([(TUTORIALS, Path("D:/tuts"))]) == 0
    assert list(ids(cache)) == ["info.rehu"]


PACKS: Final = Path("E:/packs")
""":func:`~rehuco_core_tests.test_rehudb.two_roots`'s second root's folder."""


def test_a_move_to_another_root_carries_its_rows_there(filled: tuple[CatalogCache, MappedRoot, MappedRoot]) -> None:
    """A record moved across roots keeps its row, its id and its values, now under the other root and the new path
    (#339); a stale row already at the destination gives way.

    **Test steps:**

    * scan a folder record with a nested one under the first root, and a stale row under the second where it goes
    * apply the pair from the first root's folder to a folder under the second
    * verify both rows moved to the second root with their ids, and the stale row is gone
    """
    cache, first, second = filled
    cache.apply_root_scan(first.root_id, [record("series/info.rehu", authors=("Ann",)), record("series/a/info.rehu")])
    cache.apply_root_scan(second.root_id, [record("Ann/saga/info.rehu")])
    before = ids(cache)

    moved = cache.apply_relocation([(TUTORIALS / "series", PACKS / "Ann" / "saga")])

    assert moved == 2
    rows = {(row.root_id, row.record.path): row for row in cache.rows()}
    assert {key: row.resource_id for key, row in rows.items()} == {
        (second.root_id, "Ann/saga/info.rehu"): before["series/info.rehu"],
        (second.root_id, "Ann/saga/a/info.rehu"): before["series/a/info.rehu"],
    }
    assert rows[(second.root_id, "Ann/saga/info.rehu")].record.authors == ("Ann",)


def test_a_move_out_of_every_root_drops_its_rows(filled: tuple[CatalogCache, MappedRoot, MappedRoot]) -> None:
    """A record moved to a folder no root holds is no longer anything the catalog lists (#339).

    **Test steps:**

    * scan a record and its neighbour under the first root
    * apply a pair moving the record to a folder under no root
    * verify one row went and the neighbour stayed
    """
    cache, first, _ = filled
    cache.apply_root_scan(first.root_id, [record("series/info.rehu"), record("other/info.rehu")])

    assert cache.apply_relocation([(TUTORIALS / "series", Path("F:/elsewhere/series"))]) == 1

    assert list(ids(cache)) == ["other/info.rehu"]


def test_a_move_from_under_no_root_changes_no_row(filled: tuple[CatalogCache, MappedRoot, MappedRoot]) -> None:
    """A record that was under no root has no row to carry; it joins its new root when it is next read there (#339).

    **Test steps:**

    * scan a record under the first root
    * apply a pair from a folder under no root into the first root
    * verify nothing moved and the row is as it was
    """
    cache, first, _ = filled
    cache.apply_root_scan(first.root_id, [record("kept/info.rehu")])

    assert cache.apply_relocation([(Path("F:/elsewhere/series"), TUTORIALS / "series")]) == 0

    assert list(ids(cache)) == ["kept/info.rehu"]
