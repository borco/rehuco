"""Tests for the reader of Fab's license texts (#688, [[assets#licenses]]): which address reads which text, the
text with its lines ended alike, and the public JSON a refresh reads without the persona.

The library session's own use of it -- through the persona, by Fab's path -- is tested with the session."""

from typing import Any, Final
from unittest.mock import Mock

import requests
from pytest import MonkeyPatch, mark, param, raises
from rehuco_agent.scraping.library_site import StoreOfflineError
from rehuco_agent.scraping.protocols import FetchError, LoginRequiredError
from rehuco_agent.scraping.results import Page
from rehuco_agent.scraping.sites import fab_license_texts
from rehuco_agent.scraping.sites.fab_license_texts import (
    CC_TEXTS,
    EULA_JSON_URL,
    FabLicenseTexts,
    fetch_public_json,
)

STANDARD_URL: Final = "https://www.fab.com/eula"
CC_PAGE: Final = "https://creativecommons.org/licenses/by/4.0/"


def plain(monkeypatch: MonkeyPatch, answer: object) -> Mock:
    """Make the plain HTTP fetch answer, or fail, as told.

    :param monkeypatch: pytest fixture.
    :param answer: the page it answers, or the exception it raises.
    :returns: the fetch, to read what it was asked for.
    """
    fetch = Mock(side_effect=answer) if isinstance(answer, Exception) else Mock(return_value=answer)
    monkeypatch.setattr(fab_license_texts, "HttpPageFetcher", Mock(return_value=Mock(fetch=fetch)))
    return fetch


def page(text: str, status: int = 200) -> Page:
    """A page as the plain fetch hands it over.

    :param text: its body.
    :param status: its status.
    :returns: the page.
    """
    return Page("u", "u", text, status)


# region which address reads which text


@mark.parametrize(
    ("url", "path"),
    [
        param(STANDARD_URL, "license/standard/", id="Standard"),
        param(STANDARD_URL + "/", "license/standard/", id="Standard with its slash"),
        param("  HTTPS://WWW.FAB.COM/EULA ", "license/standard/", id="Standard in any case"),
        param(CC_PAGE, "license/cc/cc-by", id="CC BY"),
        param(CC_PAGE.rstrip("/"), "license/cc/cc-by", id="CC BY without its slash"),
        param("https://creativecommons.org/licenses/by/3.0/", None, id="another version"),
        param("https://example.com/terms", None, id="someone else's"),
        param("", None, id="none"),
    ],
)
def test_a_records_license_address_names_the_text_read_for_it(url: str, path: str | None) -> None:
    """The address a record states is the license's page, which is not always where its text is read from.

    **Test steps:**

    * ask which path an address is read through
    * verify the two texts Fab's listings point at map to theirs, whatever the case or the closing slash, and any
      other address to none
    """
    assert FabLicenseTexts.path_of_url(url) == path


def test_the_standard_license_is_read_by_its_address_through_the_given_fetch() -> None:
    """**Test steps:**

    * read the Standard License's address with a fetch that answers its JSON
    * verify the fetch was asked for Fab's EULA, and the terms are the Standard License's, as Markdown
    """
    get_json = Mock(return_value={"body": "<h1>Fab End User License Agreement</h1><p>Terms.</p>"})

    terms = FabLicenseTexts(get_json).read_url(STANDARD_URL)

    get_json.assert_called_once_with(EULA_JSON_URL)
    assert terms is not None
    assert (terms.title, terms.url, terms.text) == (
        "Standard License",
        STANDARD_URL,
        "# Fab End User License Agreement\n\nTerms.",
    )


def test_the_text_is_kept_with_lf_line_ends_whatever_the_server_sent(monkeypatch: MonkeyPatch) -> None:
    """A saved text is compared with a fresh one: the same terms must not differ for how a page ends its lines.

    **Test steps:**

    * read the Creative Commons text from a page whose lines end in CRLF and CR
    * verify the terms hold LF alone
    """
    title, url = CC_TEXTS["license/cc/cc-by"]
    fetch = plain(monkeypatch, page("\r\nAttribution 4.0\r\nInternational\rEnd\r\n"))

    terms = FabLicenseTexts(Mock()).read_url(CC_PAGE)

    fetch.assert_called_once_with(url)
    assert terms is not None
    assert (terms.title, terms.url, terms.text) == (title, url, "Attribution 4.0\nInternational\nEnd")


def test_an_address_no_reader_knows_has_no_text_and_asks_for_none() -> None:
    """**Test steps:**

    * read an address nobody here reads
    * verify no terms, and nothing was fetched
    """
    get_json = Mock()

    assert FabLicenseTexts(get_json).read_url("https://example.com/terms") is None

    get_json.assert_not_called()


# endregion

# region the public JSON


def test_public_json_is_read_over_plain_http(monkeypatch: MonkeyPatch) -> None:
    """**Test steps:**

    * fetch an address whose page is a JSON object
    * verify the object, and that the plain fetch was asked for the address
    """
    fetch = plain(monkeypatch, page('{"body": "x"}'))

    assert fetch_public_json(EULA_JSON_URL) == {"body": "x"}

    fetch.assert_called_once_with(EULA_JSON_URL)


@mark.parametrize(
    "answer",
    [
        param(requests.ConnectionError("down"), id="no connection"),
        param(LoginRequiredError("403"), id="a refusal"),
        param(page("Service Unavailable", 503), id="a refusal that passes"),
    ],
)
def test_a_public_json_that_does_not_answer_is_the_store_not_answering(
    monkeypatch: MonkeyPatch, answer: object
) -> None:
    """**Test steps:**

    * fetch an address that fails, is refused, or answers a passing refusal
    * verify the store is said not to answer, the reason naming the address
    """
    plain(monkeypatch, answer)

    with raises(StoreOfflineError, match="fab_eula"):
        fetch_public_json(EULA_JSON_URL)


@mark.parametrize("body", [param("<html>", id="not JSON"), param("[1]", id="not an object")])
def test_a_public_answer_that_is_no_json_object_is_a_fetch_failure(monkeypatch: MonkeyPatch, body: Any) -> None:
    """**Test steps:**

    * fetch an address whose page is text, or a JSON list
    * verify a fetch failure
    """
    plain(monkeypatch, page(body))

    with raises(FetchError):
        fetch_public_json(EULA_JSON_URL)


# endregion
