"""Tests for where the catalog cache looks for a free-text term (#647): a title, a path, and part of any author,
publisher or tag name by default; only the places a query's scope names otherwise.

The cache is :mod:`test_rehudb`'s, over a shared-cache in-memory database; its fixtures are imported by name.
:mod:`test_catalog_snapshot` holds the contract that the in-memory matcher answers the same.
"""

from pytest import fixture, mark
from rehuco_core import CatalogCache, CatalogField, CatalogQuery, CatalogTextField

from rehuco_core_tests.mapped_roots import mapped
from rehuco_core_tests.test_rehudb import (  # noqa: F401  # pylint: disable=unused-import
    fixture_cache,
    fixture_database,
    fixture_memory,
    record,
    two_roots,
)


@fixture(name="shelf")
def fixture_shelf(cache: CatalogCache) -> CatalogCache:
    """A cache holding four resources, each naming ``owl`` in one place only.

    :param cache: the cache to fill.
    :returns: it, filled.
    """
    rehuco, first, _ = two_roots()
    cache.reconcile_roots(mapped(rehuco))
    cache.apply_root_scan(
        first.root_id,
        [
            record("a/info.rehu", title="Owl Sketching", authors=("Ann",)),
            record("b/info.rehu", title="Painting", authors=("Ann Barnowl",), tags=("ink",)),
            record("c/info.rehu", title="Shading", publishers=("Owlbridge Press",)),
            record("d/info.rehu", title="Inking", tags=("snowy owl", "50%_off")),
        ],
    )
    return cache


def titles(cache: CatalogCache, query: CatalogQuery) -> list[str]:
    """The titles of the rows ``query`` reads, in their order."""
    return [row.record.title for row in cache.rows(query)]


def test_free_text_finds_part_of_a_title_path_author_publisher_or_tag(shelf: CatalogCache) -> None:
    """By default a term is looked for everywhere: here in a title, an author, a publisher and a tag, in any case.

    **Test steps:**

    * read the word every resource holds in one place, in capitals
    * verify every resource is found
    """
    assert titles(shelf, CatalogQuery(("OWL",))) == ["Owl Sketching", "Painting", "Shading", "Inking"]


@mark.parametrize(
    ("scope", "expected"),
    [
        ({CatalogTextField.TITLE}, ["Owl Sketching"]),
        ({CatalogTextField.AUTHORS}, ["Painting"]),
        ({CatalogTextField.PUBLISHERS}, ["Shading"]),
        ({CatalogTextField.TAGS}, ["Inking"]),
        ({CatalogTextField.AUTHORS, CatalogTextField.PUBLISHERS}, ["Painting", "Shading"]),
        (set(), []),
    ],
    ids=lambda value: "-".join(sorted(value)) if isinstance(value, set) else None,
)
def test_a_scope_keeps_a_term_to_its_places(
    shelf: CatalogCache, scope: set[CatalogTextField], expected: list[str]
) -> None:
    """A scope looks only where it names, adding its places up; an empty one finds nothing once there is a term.

    **Test steps:**

    * read the shared word kept to the scope
    * verify only the resources holding it there
    """
    assert titles(shelf, CatalogQuery(("owl",), scope=frozenset(scope))) == expected


def test_every_term_must_be_found_each_in_any_place(shelf: CatalogCache) -> None:
    """Terms are still ANDed: one may be found in a title and another in a tag of the same resource.

    **Test steps:**

    * read a title word with a tag word of the same resource, and with a tag word of another
    * verify the first finds that resource and the second nothing
    """
    assert titles(shelf, CatalogQuery(("painting", "ink"))) == ["Painting"]
    assert not titles(shelf, CatalogQuery(("shading", "ink")))


def test_a_term_in_a_name_takes_wildcards_literally(shelf: CatalogCache) -> None:
    """``%`` and ``_`` in a term are themselves in a name too, never ``LIKE``'s wildcards.

    **Test steps:**

    * read ``0%_o``, which only the tag ``50%_off`` holds, and ``0_%o``, which wildcards would match there too
    * verify the first finds that resource and the second nothing
    """
    assert titles(shelf, CatalogQuery(("0%_o",))) == ["Inking"]
    assert not titles(shelf, CatalogQuery(("0_%o",)))


def test_a_value_token_still_matches_a_whole_name(shelf: CatalogCache) -> None:
    """``authors:`` is unchanged by free text looking in names: part of a name finds nothing.

    **Test steps:**

    * read ``authors:barnowl`` and ``authors:"ann barnowl"``
    * verify only the whole name finds its resource
    """
    assert not titles(shelf, CatalogQuery(tokens=((CatalogField.AUTHORS, "barnowl"),)))
    assert titles(shelf, CatalogQuery(tokens=((CatalogField.AUTHORS, "ann barnowl"),))) == ["Painting"]
