"""Tests for is_http_author_url: the one predicate both sides of the ``authors`` field ask (#97)."""

from pytest import mark
from rehuco_agent.fields.author_url import is_http_author_url


@mark.parametrize(
    "value",
    [
        "http://example.com",
        "https://example.com",
        "https://example.com/alice?tab=gallery#top",
        "HTTPS://example.com",
    ],
)
def test_an_absolute_http_address_is_an_author_url(value: str) -> None:
    """http and https with a host are the only shapes the editor writes and the viewer links.

    **Test steps:**

    * ask the predicate about an absolute http(s) address
    * verify it says yes
    """
    assert is_http_author_url(value) is True


@mark.parametrize(
    "value",
    [
        "",
        "example.com",
        "not a url",
        "ftp://example.com",
        "file:///etc/passwd",
        "mailto:alice@example.com",
        "https://",
        "//example.com",
    ],
)
def test_anything_else_is_not(value: str) -> None:
    """A relative address, another scheme, or a scheme with no host is not a link to anywhere.

    **Test steps:**

    * ask the predicate about a value that is not an absolute http(s) address
    * verify it says no
    """
    assert is_http_author_url(value) is False
