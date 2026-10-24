"""Tests for the catalog's rows held in memory and filtered there (#455).

**The matcher and the cache's SQL are one rule implemented twice**, so the battery below runs every query through
both, over one cache, and requires the same rows in the same order: neither can drift from the other unnoticed.
"""

import gc
import random
from collections.abc import Generator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final
from uuid import UUID, uuid4

from pytest import TempPathFactory, fixture, mark
from rehuco_core import (
    CatalogCache,
    CatalogField,
    CatalogMatcher,
    CatalogQuery,
    CatalogRecord,
    CatalogRow,
    CatalogSearchKey,
    CatalogSnapshot,
    MappedRoot,
    RecordKind,
)

from rehuco_core_tests.mapped_roots import location_at

WORDS: Final = (
    "Café",
    "cafe",
    "ŞTRASSE",
    "straße",
    "İstanbul",
    "ﬁsh",
    "Ålborg",
    "50%_off",
    "back\\slash",
    "Ǆungla",
    "ΣΟΦΟΣ",
    "łódź",
    "x％y",
    "Résumé",
    "plain",
    "Kanji 漢字",
    "ABC",
    "abc_def",
    "a%b",
)
"""Spellings that fold, escape or compare differently: accents, ligatures, letters folding to two, wildcards, a
backslash, a fullwidth sign, a letter fold cannot decompose, and text with no case."""

FOLDERS: Final = ("Art", "art/Sub", "Ärt", "Courses/Python", "courses/python 2", "x%y", "a_b", "Ünï", "ß/ss")
"""Folders a record sits under: case and accents apart, wildcards, segment edges (``python`` and ``python 2``)."""

TYPES: Final = ("Tutorial", "tutorial", "REFERENCE_images", "Bóok")
"""Types alike but for ASCII case, and one with an accent ``NOCASE`` does not fold."""

LABELS: Final = ("R1", "Two/Lab")
"""The roots' labels; the second holds a ``/``, so a ``folder`` token splits more than one way."""

RECORDS_PER_ROOT: Final = 300


@dataclass(frozen=True)
class Catalog:
    """A cache over two roots, and the snapshot of every row it holds.

    :param path: the cache file.
    :param root_ids: the roots' ids, in the roots' order.
    :param snapshot: every row, keyed.
    """

    path: Path
    root_ids: tuple[UUID, ...]
    snapshot: CatalogSnapshot

    def sql(self, query: CatalogQuery) -> list[int]:
        """The ids of the rows the cache reads for ``query``, in its order.

        :param query: what to match.
        :returns: the ids.
        """
        with CatalogCache.open(self.path) as cache:
            return [row.resource_id for row in cache.rows(query)]


def record(index: int, rng: random.Random) -> CatalogRecord:
    """A record mixing the spellings above.

    :param index: what makes its path unique.
    :param rng: where its choices come from.
    :returns: the record.
    """
    return CatalogRecord(
        path=f"{rng.choice(FOLDERS)}/{rng.choice(WORDS)} {index}/r.rehu",
        kind=RecordKind.REHU,
        type=rng.choice(TYPES),
        title=" ".join(rng.sample(WORDS, 2)),
        authors=tuple(rng.sample(WORDS, rng.randint(0, 2))),
        tags=tuple(rng.sample(WORDS, rng.randint(0, 3))),
        publishers=tuple(rng.sample(WORDS, rng.randint(0, 1))),
    )


@fixture(name="catalog", scope="module")
def fixture_catalog(tmp_path_factory: TempPathFactory) -> Generator[Catalog]:
    """One cache for the whole battery, its records drawn from a fixed seed.

    :param tmp_path_factory: pytest's temporary folders.
    :yields: the catalog.
    """
    path = tmp_path_factory.mktemp("snapshot") / "catalog.rehudb"
    folder = path.parent
    roots = [
        MappedRoot(uuid4(), label, location_at(folder / f"root{number}"), folder / f"root{number}")
        for number, label in enumerate(LABELS)
    ]
    rng = random.Random(4)
    with CatalogCache.open(path) as cache:
        cache.reconcile_roots(roots)
        for number, root in enumerate(roots):
            records = [record(number * RECORDS_PER_ROOT + index, rng) for index in range(RECORDS_PER_ROOT)]
            cache.apply_root_scan(root.root_id, records)
        rows = cache.rows()
    root_ids = tuple(root.root_id for root in roots)
    yield Catalog(path, root_ids, CatalogSnapshot.build(rows, root_ids))


def battery() -> list[CatalogQuery]:
    """Every query the matcher must answer as the cache does.

    :returns: the queries.
    """
    terms = [*WORDS, "%", "_", "\\", "ss", "SS", "fi", "e", "/", "sub/", "ART/", "a_", "r.rehu", "σοφος", "Sigma"]
    queries = [CatalogQuery(), *(CatalogQuery(terms=(term,)) for term in terms)]
    for word in WORDS:
        for field in (CatalogField.AUTHORS, CatalogField.TAGS, CatalogField.PUBLISHERS):
            queries += [CatalogQuery(tokens=((field, word),)), CatalogQuery(tokens=((field, word.upper()),))]
    for value in ("tutorial", "TUTORIAL", "bóok", "BÓOK", "reference_images", "Tutori"):
        queries.append(CatalogQuery(tokens=((CatalogField.TYPE, value),)))
    folders = (
        "R1",
        "r1",
        "R1/Art",
        "r1/art",
        "R1/art/",
        "/R1/Art/Sub",
        "R1/Ar",
        "R1/Ärt",
        "R1/ärt",
        "R1/x%y",
        "R1/a_b",
        "R1/ß",
        "R1/SS",
        "Two/Lab",
        "two/lab/Courses",
        "Two/Lab/Courses/Python",
        "R1/courses",
        "R1/Courses/python 2",
        "nothing",
    )
    queries += [CatalogQuery(tokens=((CatalogField.FOLDER, value),)) for value in folders]
    queries.append(CatalogQuery(terms=("cafe", "1"), tokens=((CatalogField.TYPE, "tutorial"),)))
    combined = ((CatalogField.FOLDER, "R1/Art"), (CatalogField.AUTHORS, "plain"), (CatalogField.TAGS, "abc"))
    queries.append(CatalogQuery(tokens=combined))
    return queries


@mark.parametrize("query", battery(), ids=str)
def test_the_matcher_picks_what_the_cache_reads(catalog: Catalog, query: CatalogQuery) -> None:
    """The snapshot selects exactly the rows the cache's ``WHERE`` reads, in the cache's order.

    **Test steps:**

    * read the query from the cache, and select it from the snapshot
    * verify the same ids in the same order
    """
    assert [row.resource_id for row in catalog.snapshot.select(query)] == catalog.sql(query)


def test_the_battery_finds_something_and_misses_something(catalog: Catalog) -> None:
    """A battery whose queries all match everything, or nothing, would prove no agreement at all.

    **Test steps:**

    * count the rows each query of the battery reads
    * verify most queries pick some rows but not every row
    """
    total = len(catalog.snapshot)
    picked = [len(catalog.sql(query)) for query in battery()]

    assert sum(1 for count in picked if 0 < count < total) > len(picked) // 2


def test_matches_tests_one_key(catalog: Catalog) -> None:
    """One key is tested by the same rule a whole list is.

    **Test steps:**

    * key the first row, and test it against a query naming its title's first word, and against one it lacks
    * verify the first matches and the second does not
    """
    first = catalog.snapshot.rows[0]
    key = CatalogSearchKey.of(first)
    word = first.record.title.split()[0]

    assert CatalogMatcher(CatalogQuery(terms=(word,))).matches(key)
    assert not CatalogMatcher(CatalogQuery(terms=("no such words",))).matches(key)


# region What the collector tracks (#500)


TRACKED_OVERHEAD: Final = 8
"""The tracked objects a snapshot makes besides its keys -- itself and its few containers -- with room to spare."""


def test_a_reads_rows_of_a_root_share_one_root_id(catalog: Catalog) -> None:
    """A read parses each root's id once, so its rows share one ``UUID`` rather than each tracking its own.

    **Test steps:**

    * read every row of the cache
    * verify each root's rows hold one and the same ``UUID`` object, equal to the root's id
    """
    with CatalogCache.open(catalog.path) as cache:
        rows = cache.rows()

    for root_id in catalog.root_ids:
        held = {id(row.root_id) for row in rows if row.root_id == root_id}
        assert len(held) == 1


def test_a_snapshot_adds_one_tracked_object_per_row(catalog: Catalog) -> None:
    """Keying a read adds a key per row and nothing more the collector walks: no pairs, and names it never tracks.

    **Test steps:**

    * with the collector off, count the objects it tracks before and after building a snapshot over read rows
    * verify the build added one per row, give or take the snapshot's own few, and a key's names are untracked
    """
    rows = catalog.snapshot.rows
    was_on = gc.isenabled()
    gc.collect()
    gc.disable()
    try:
        before = len(gc.get_objects())
        snapshot = CatalogSnapshot.build(rows, catalog.root_ids)
        added = len(gc.get_objects()) - before
    finally:
        if was_on:
            gc.enable()

    assert len(rows) <= added <= len(rows) + TRACKED_OVERHEAD
    named = next(row for row in snapshot.rows if row.record.authors)
    key = CatalogSearchKey.of(named)
    assert key.row is named
    assert key.authors
    assert not any(gc.is_tracked(names) for names in (key.authors, key.tags, key.publishers))


# endregion


def test_a_snapshot_tells_its_rows_their_count_and_its_roots(catalog: Catalog) -> None:
    """What a browser reads off a snapshot besides a selection.

    **Test steps:**

    * read the snapshot's rows, length, roots and ids
    * verify they are the cache's rows, in its order, the roots given, and every row's id
    """
    snapshot = catalog.snapshot

    assert [row.resource_id for row in snapshot.rows] == catalog.sql(CatalogQuery())
    assert len(snapshot) == 2 * RECORDS_PER_ROOT
    assert snapshot.root_ids == catalog.root_ids
    assert set(snapshot.ids) == {row.resource_id for row in snapshot.rows}


def test_a_selection_of_some_rows_keeps_the_caches_order(catalog: Catalog) -> None:
    """Given ids, only those rows are tested, in the cache's order whatever order the ids came in; an id the snapshot
    lacks is passed over.

    **Test steps:**

    * select every row by a query matching all, among three ids given backwards plus one unknown
    * verify the three, in the cache's order
    """
    rows = catalog.snapshot.rows
    chosen = [rows[5].resource_id, rows[1].resource_id, rows[3].resource_id, -1]

    selected = catalog.snapshot.select(CatalogQuery(), chosen)

    assert [row.resource_id for row in selected] == [rows[1].resource_id, rows[3].resource_id, rows[5].resource_id]


# region Patching


ROOT_A: Final = uuid4()
ROOT_B: Final = uuid4()


def snapshot_row(resource_id: int, path: str, root_id: UUID = ROOT_A, title: str = "") -> CatalogRow:
    """A row under ``root_id``.

    :param resource_id: its id.
    :param path: its root-relative path.
    :param root_id: its root.
    :param title: its title.
    :returns: the row.
    """
    return CatalogRow(resource_id, root_id, "label", CatalogRecord(path, RecordKind.REHU, title=title), 0.0)


def paths(snapshot: CatalogSnapshot) -> list[tuple[UUID, str]]:
    """Each row's root and path, in order.

    :param snapshot: the snapshot.
    :returns: the pairs.
    """
    return [(row.root_id, row.record.path) for row in snapshot.rows]


def test_a_patch_replaces_removes_and_inserts_where_the_cache_would() -> None:
    """A changed row moves to where its new path sorts, a gone one leaves, and a new one lands by root then path.

    **Test steps:**

    * snapshot three rows under one root and one under another
    * patch one renamed, one removed and one new under the second root
    * verify the order, and that the original snapshot is unchanged
    """
    original = CatalogSnapshot.build(
        [snapshot_row(1, "a"), snapshot_row(2, "b"), snapshot_row(3, "c"), snapshot_row(4, "a", ROOT_B)],
        [ROOT_A, ROOT_B],
    )

    patched = original.patched({1, 2, 5}, [snapshot_row(1, "d"), snapshot_row(5, "0", ROOT_B)])

    assert paths(patched) == [(ROOT_A, "c"), (ROOT_A, "d"), (ROOT_B, "0"), (ROOT_B, "a")]
    assert paths(original) == [(ROOT_A, "a"), (ROOT_A, "b"), (ROOT_A, "c"), (ROOT_B, "a")]
    assert patched.root_ids == (ROOT_A, ROOT_B)


def test_a_patched_row_is_found_by_its_new_text() -> None:
    """A patch keys the rows it brings, so a query reads their new text.

    **Test steps:**

    * snapshot a row titled ``old``, then patch it to ``new``
    * verify ``new`` selects it and ``old`` no longer does
    """
    original = CatalogSnapshot.build([snapshot_row(1, "a", title="old")], [ROOT_A])

    patched = original.patched({1}, [snapshot_row(1, "a", title="new")])

    assert [row.resource_id for row in patched.select(CatalogQuery(terms=("new",)))] == [1]
    assert not patched.select(CatalogQuery(terms=("old",)))


def test_a_row_of_a_root_the_snapshot_does_not_list_goes_last() -> None:
    """A row under a root the snapshot's order does not name sorts after every listed root's.

    **Test steps:**

    * patch a row under an unlisted root into a snapshot of one root
    * verify it comes last
    """
    stranger = uuid4()
    original = CatalogSnapshot.build([snapshot_row(1, "z")], [ROOT_A])

    patched = original.patched({2}, [snapshot_row(2, "a", stranger)])

    assert paths(patched) == [(ROOT_A, "z"), (stranger, "a")]


# endregion


def test_rows_unchanged_by_a_replace_keep_their_place(catalog: Catalog) -> None:
    """A patch of a row with nothing changed keeps every row where it was.

    **Test steps:**

    * patch the snapshot's middle row with an equal copy of itself
    * verify the order is unchanged
    """
    rows = catalog.snapshot.rows
    middle = rows[len(rows) // 2]

    patched = catalog.snapshot.patched({middle.resource_id}, [replace(middle)])

    assert [row.resource_id for row in patched.rows] == [row.resource_id for row in rows]
