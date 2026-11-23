"""Tests for Fab's in-page fetcher (#684): what it asks the persona for, and how it tells a challenge and a login that
expired, which the user answers in the browser, from a store that does not answer, which is waited out."""

from typing import Any, Final
from unittest.mock import Mock

from pytest import MonkeyPatch, fixture, mark, param, raises
from rehuco_agent.scraping.browser_fetcher import PersonaLease
from rehuco_agent.scraping.library_site import StoreOfflineError, StorePausedError
from rehuco_agent.scraping.sites import fab_session_fetcher
from rehuco_agent.scraping.sites.fab_session_fetcher import (
    CHALLENGE_REASON,
    CHALLENGE_TITLE,
    FETCH_SCRIPT,
    LOGIN_REASON,
    LOGIN_URL,
    REQUEST_INTERVAL_SECONDS,
    SCRIPT_TIMEOUT_SECONDS,
    FabSessionFetcher,
)
from selenium.common.exceptions import TimeoutException, WebDriverException

URL: Final = "https://www.fab.com/i/listings/x"


@fixture(autouse=True)
def no_sleeping(monkeypatch: MonkeyPatch) -> None:
    """Never wait out the interval between two requests for real.

    :param monkeypatch: replaces the sleep.
    """
    monkeypatch.setattr("rehuco_agent.scraping.sites.fab_session_fetcher.time.sleep", Mock())


def driver_on(url: str = "https://www.fab.com/library", *, title: str = "Fab", answer: object = None) -> Mock:
    """A browser session standing on a page.

    :param url: the page it is on.
    :param title: that page's title.
    :param answer: what a script run in it answers.
    :returns: the session.
    """
    driver = Mock()
    driver.current_url = url
    driver.title = title
    ok = {"status": 200, "mitigated": None, "body": "{}"}
    driver.execute_async_script.return_value = ok if answer is None else answer
    return driver


def fetcher_on(driver: Mock) -> tuple[FabSessionFetcher, Mock]:
    """A fetcher over a lease that hands out one session.

    :param driver: the session.
    :returns: the fetcher and its lease.
    """
    lease = Mock(spec=PersonaLease)
    lease.driver.return_value = driver
    return FabSessionFetcher(lease), lease


def test_a_request_runs_in_the_page_and_comes_back_as_a_page() -> None:
    """The request is a ``fetch`` run in the Fab page the session stands on, and its answer is a `Page`.

    **Test steps:**

    * fetch an address through a session already on a Fab page
    * verify the script ran with the address, under the script timeout, and nothing was navigated to
    * verify the page carries the address, the body and the status
    """
    driver = driver_on(answer={"status": 404, "mitigated": None, "body": "nothing"})
    fetcher, lease = fetcher_on(driver)

    page = fetcher.fetch(URL)

    driver.execute_async_script.assert_called_once_with(FETCH_SCRIPT, URL)
    driver.set_script_timeout.assert_called_once_with(SCRIPT_TIMEOUT_SECONDS)
    driver.get.assert_not_called()
    lease.driver.assert_called_once_with()
    assert (page.url, page.final_url, page.html, page.status) == (URL, URL, "nothing", 404)


def test_a_session_on_no_fab_page_goes_to_fab_first() -> None:
    """A session just started stands on a blank page, where a same-origin request has no origin.

    **Test steps:**

    * fetch through a session on ``about:blank``
    * verify it was sent to Fab's home page, then the request ran
    """
    driver = driver_on("about:blank")
    fetcher, _ = fetcher_on(driver)

    fetcher.fetch(URL)

    driver.get.assert_called_once_with("https://www.fab.com")
    driver.execute_async_script.assert_called_once()


def test_the_session_is_asked_for_at_every_request() -> None:
    """The lease may give the browser up between two requests, so no session is kept.

    **Test steps:**

    * make two requests, the lease handing out a different session each time
    * verify each ran on the session it handed out at that request
    """
    first, second = driver_on(), driver_on("about:blank")
    lease = Mock(spec=PersonaLease)
    lease.driver.side_effect = [first, second]
    fetcher = FabSessionFetcher(lease)

    fetcher.fetch(URL)
    fetcher.fetch(URL)

    first.execute_async_script.assert_called_once()
    second.get.assert_called_once_with("https://www.fab.com")
    second.execute_async_script.assert_called_once()


def test_a_challenge_page_met_on_arrival_pauses_the_scan() -> None:
    """Fab's home page answering with Cloudflare's challenge is the user's to pass in the browser.

    **Test steps:**

    * fetch through a session whose first page is the challenge
    * verify the scan is stopped with the challenge's reason and Fab's address, and no request ran
    """
    driver = driver_on("about:blank", title=CHALLENGE_TITLE)
    fetcher, _ = fetcher_on(driver)

    with raises(StorePausedError) as stopped:
        fetcher.fetch(URL)

    assert (stopped.value.reason, stopped.value.url) == (CHALLENGE_REASON, "https://www.fab.com")
    driver.execute_async_script.assert_not_called()


@mark.parametrize(
    "answer",
    [
        param({"status": 403, "mitigated": "challenge", "body": "{}"}, id="the header says it"),
        param({"status": 403, "mitigated": None, "body": "  <html>Just a moment</html>"}, id="a 403 that is a page"),
    ],
)
def test_a_challenged_request_pauses_the_scan(answer: dict[str, Any]) -> None:
    """A request Cloudflare held back, whichever way it says so, is a challenge.

    **Test steps:**

    * fetch, the page answering each form of challenge
    * verify the scan is stopped with the challenge's reason
    """
    fetcher, _ = fetcher_on(driver_on(answer=answer))

    with raises(StorePausedError) as stopped:
        fetcher.fetch(URL)

    assert (stopped.value.reason, stopped.value.url) == (CHALLENGE_REASON, "https://www.fab.com")


@mark.parametrize("status", [401, 403])
def test_a_refused_login_pauses_the_scan_at_the_library(status: int) -> None:
    """A 401, or a 403 that is JSON, is a login that expired: the user signs in again in the browser.

    **Test steps:**

    * fetch, Fab answering each status with JSON
    * verify the scan is stopped with the login's reason and the library's address
    """
    fetcher, _ = fetcher_on(driver_on(answer={"status": status, "mitigated": None, "body": '{"detail": "no"}'}))

    with raises(StorePausedError) as stopped:
        fetcher.fetch(URL)

    assert (stopped.value.reason, stopped.value.url) == (LOGIN_REASON, LOGIN_URL)


@mark.parametrize(
    "answer",
    [
        param({"status": 429, "mitigated": None, "body": ""}, id="too many requests"),
        param({"status": 503, "mitigated": None, "body": ""}, id="a server error"),
        param({"error": "TypeError: NetworkError"}, id="a request that did not complete"),
        param(None, id="no answer"),
        param("garbled", id="an answer that is no object"),
    ],
)
def test_a_store_that_does_not_answer_is_waited_for(answer: object) -> None:
    """A refusal that passes, or no answer at all, is for the queue to try again.

    **Test steps:**

    * fetch, Fab answering each way
    * verify the scan is made to wait, the reason naming the address
    """
    driver = driver_on()
    driver.execute_async_script.return_value = answer
    fetcher, _ = fetcher_on(driver)

    with raises(StoreOfflineError, match="fab.com"):
        fetcher.fetch(URL)


def test_a_request_the_browser_gives_up_is_waited_for() -> None:
    """A script that outlives its timeout is a store that does not answer, and the session stays.

    **Test steps:**

    * fetch, the browser raising its timeout
    * verify the scan is made to wait, and the lease was not closed
    """
    driver = driver_on()
    driver.execute_async_script.side_effect = TimeoutException("slow")
    fetcher, lease = fetcher_on(driver)

    with raises(StoreOfflineError, match="did not answer"):
        fetcher.fetch(URL)

    lease.close.assert_not_called()


def test_a_browser_that_went_away_is_given_up() -> None:
    """A dead session is not handed to the next request: the lease is closed, and the scan waits.

    **Test steps:**

    * fetch, the browser raising a driver failure
    * verify the scan is made to wait, and the lease was closed
    """
    driver = driver_on()
    driver.execute_async_script.side_effect = WebDriverException("gone")
    fetcher, lease = fetcher_on(driver)

    with raises(StoreOfflineError, match="stopped answering"):
        fetcher.fetch(URL)

    lease.close.assert_called_once_with()


def test_requests_are_spaced(monkeypatch: MonkeyPatch) -> None:
    """The next request waits out what is left of the interval since the last, and none is waited for after a long gap.

    **Test steps:**

    * make three requests, the second 0.25 s after the first ended, the third long after the second
    * verify only the second slept, for the rest of the interval
    """
    clock = Mock()
    clock.monotonic.side_effect = [0.0, 0.25, 1.0, 5.0, 5.0]
    monkeypatch.setattr(fab_session_fetcher, "time", clock)
    fetcher, _ = fetcher_on(driver_on())

    for _ in range(3):
        fetcher.fetch(URL)

    clock.sleep.assert_called_once_with(REQUEST_INTERVAL_SECONDS - 0.25)
