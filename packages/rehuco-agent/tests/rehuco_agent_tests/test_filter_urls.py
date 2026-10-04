"""Tests for click-to-filter links: the one wire format a viewer writes and the Root Catalog reads (#398)."""

import pytest
from rehuco_agent.filter_urls import filter_url, filter_url_token
from rehuco_core import CatalogField


def test_a_link_carries_its_value_percent_encoded_whole() -> None:
    """Spaces, slashes and commas all survive inside the one ``name`` parameter.

    **Test steps:**

    * build the authors link for a name with a space, a slash and a comma
    * verify the URL, and that reading it back gives the field and the name
    """
    url = filter_url(CatalogField.AUTHORS, "Foo Bar/Baz, Jr")

    assert url == "filter://authors?name=Foo%20Bar%2FBaz%2C%20Jr"
    assert filter_url_token(url) == (CatalogField.AUTHORS, "Foo Bar/Baz, Jr")


def test_reading_a_link_decodes_its_name() -> None:
    """The issue's own example.

    **Test steps:**

    * read ``filter://authors?name=Foo%20Bar``
    * verify the authors field and ``Foo Bar``
    """
    assert filter_url_token("filter://authors?name=Foo%20Bar") == (CatalogField.AUTHORS, "Foo Bar")


@pytest.mark.parametrize(
    "url",
    [
        "https://authors?name=Foo",
        "filter://folder?name=Tutorials",
        "filter://colour?name=red",
        "filter://tags",
        "filter://tags?name=",
        "filter://tags?value=x",
    ],
)
def test_a_link_that_names_no_filter_reads_as_none(url: str) -> None:
    """Another scheme, a field no link filters on, or no value are not filters.

    **Test steps:**

    * read the link
    * verify it names no filter
    """
    assert filter_url_token(url) is None


def test_a_links_scheme_and_field_are_read_whatever_their_case() -> None:
    """A host is case-insensitive, so the field is too.

    **Test steps:**

    * read an upper-case scheme and field
    * verify the tags field
    """
    assert filter_url_token("FILTER://Tags?name=python") == (CatalogField.TAGS, "python")
