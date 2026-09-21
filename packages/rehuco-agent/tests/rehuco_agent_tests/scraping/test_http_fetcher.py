"""Tests for `HttpPageFetcher` (#269). The network is mocked; only the request shape is under test."""

from pytest import raises
from pytest_mock import MockerFixture
from rehuco_agent.scraping.http_fetcher import REQUEST_TIMEOUT_SECONDS, USER_AGENT, HttpPageFetcher
from rehuco_agent.scraping.results import Page
from requests import HTTPError

URL = "https://example.com/page"
FINAL_URL = "https://www.example.com/page"


def test_fetch_asks_with_a_browser_user_agent_and_reports_where_it_landed(mocker: MockerFixture) -> None:
    """One GET with the browser User-Agent and the timeout, answered as a `Page` carrying the URL the
    request actually resolved to (#269).

    **Test steps:**

    * stand in for ``requests.get`` with a response that redirected
    * fetch
    * verify the request's headers and timeout, and the page's three fields
    """
    response = mocker.Mock(url=FINAL_URL, text="<html>hi</html>")
    get = mocker.patch("rehuco_agent.scraping.http_fetcher.requests.get", return_value=response)

    page = HttpPageFetcher().fetch(URL)

    get.assert_called_once_with(URL, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status.assert_called_once_with()
    assert page == Page(url=URL, final_url=FINAL_URL, html="<html>hi</html>")


def test_an_error_status_raises_rather_than_handing_over_error_html(mocker: MockerFixture) -> None:
    """A 4xx/5xx is a failure the job logs, never a page of error markup handed to a scraper (#269).

    **Test steps:**

    * stand in for ``requests.get`` with a response whose status check raises
    * verify the fetch raises that error
    """
    response = mocker.Mock()
    response.raise_for_status.side_effect = HTTPError("404")
    mocker.patch("rehuco_agent.scraping.http_fetcher.requests.get", return_value=response)

    with raises(HTTPError):
        HttpPageFetcher().fetch(URL)
