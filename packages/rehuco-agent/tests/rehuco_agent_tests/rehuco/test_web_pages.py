"""Tests for which of a record's URLs is a web page (#679)."""

from pytest import mark
from rehuco_agent.rehuco.web_pages import is_web_page


@mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.fab.com/listings/abc", True),
        ("http://example.com", True),
        ("HTTPS://example.com", True),
        ("file:///C:/Windows/system32/calc.exe", False),
        ("ftp://example.com/pack.zip", False),
        ("example.com/pack", False),
        ("https:", False),
        ("https:///pack", False),
        ("", False),
    ],
)
def test_only_an_http_or_https_address_is_a_web_page(url: str, expected: bool) -> None:
    """A ``.rehu`` is outside input, so only a web address is handed to the system.

    **Test steps:**

    * ask about an address of each kind
    * verify only the http and https ones that name a host, in any case, are web pages
    """
    assert is_web_page(url) is expected
