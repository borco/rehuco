"""Fab's own JSON, fetched from inside the persona's page ([[acquisition-tooling#library-scan-job]], #684).

A library scan reads Fab as the page does: a ``fetch`` run in a Fab page of the persona, same-origin, so the account's
cookies go with it and Cloudflare sees what it sees of the page itself (#686). The lease's session is asked for at every
request and never kept: between two requests the lease may have given the browser up to a drop and started another.

**What stops a scan is told here and nowhere else**: a challenge page or a login that expired is the user's to answer in
the browser (`~rehuco_agent.scraping.library_site.StorePausedError`); a store that does not answer, or answers with a
refusal that passes, is waited out (`~rehuco_agent.scraping.library_site.StoreOfflineError`).
"""

import logging
import time
from typing import Any, Final
from urllib.parse import urlsplit

from selenium.common.exceptions import TimeoutException, WebDriverException

from ..browser_fetcher import PersonaLease
from ..library_site import StoreOfflineError, StorePausedError
from ..results import Page
from .fab import HOSTS, SITE_URL

LOG: Final = logging.getLogger(__name__)

REQUEST_INTERVAL_SECONDS: Final = 1.0
"""The least time between two requests to Fab. A first scan of a large library makes tens of thousands of them, and a
store that starts challenging the persona costs more than the time saved ([[acquisition-tooling#library-scan-job]])."""

SCRIPT_TIMEOUT_SECONDS: Final = 30
"""How long one request may take before the browser gives it up."""

CHALLENGE_TITLE: Final = "Just a moment..."
"""The title of Cloudflare's challenge page."""

CHALLENGE_HEADER_VALUE: Final = "challenge"
"""The value of ``cf-mitigated`` on a request Cloudflare held back for a challenge."""

LOGIN_URL: Final = SITE_URL + "/library"
"""Where the persona browser is opened when the login has expired: the library, which asks for one."""

CHALLENGE_REASON: Final = "Fab is asking the persona browser to prove it is not a robot: answer it there, then resume."
"""What a scan stopped by a challenge page says."""

LOGIN_REASON: Final = "The persona browser is not logged in to Fab: sign in there, then resume."
"""What a scan stopped by a login that expired says."""

FETCH_SCRIPT: Final = """
const done = arguments[arguments.length - 1];
fetch(arguments[0], {credentials: 'same-origin', headers: {'Accept': 'application/json'}})
  .then((response) => response.text().then((body) => done({
    status: response.status,
    mitigated: response.headers.get('cf-mitigated'),
    body: body,
  })))
  .catch((error) => done({error: String(error)}));
"""
"""Runs in the page: answers ``{status, mitigated, body}``, or ``{error}`` when the request did not complete."""


# one method is the design, not an omission: it is what a `PageFetcher` is
# pylint: disable-next=too-few-public-methods
class FabSessionFetcher:
    """Satisfies `~rehuco_agent.scraping.protocols.PageFetcher` through the persona a scan leases.

    :param lease: the scan's hold on the persona.
    """

    def __init__(self, lease: PersonaLease) -> None:
        self.__lease: Final = lease
        self.__last_request: float | None = None

    def fetch(self, url: str) -> Page:
        """Fetch ``url`` from inside a Fab page, at least :data:`REQUEST_INTERVAL_SECONDS` after the last request.

        :param url: a Fab address.
        :returns: the page, whatever its status below 429 -- a ``404`` is the scraper's to read.
        :raises StorePausedError: a challenge page, or a login that expired.
        :raises StoreOfflineError: the browser or the store did not answer, or Fab refused for the moment.
        :raises FetchError: the browser could not be started.
        """
        self.__pace()
        driver = self.__lease.driver()
        try:
            if urlsplit(driver.current_url).hostname not in HOSTS:
                driver.get(SITE_URL)
                if driver.title == CHALLENGE_TITLE:
                    raise StorePausedError(CHALLENGE_REASON, SITE_URL)
            driver.set_script_timeout(SCRIPT_TIMEOUT_SECONDS)
            answer = driver.execute_async_script(FETCH_SCRIPT, url)
        except TimeoutException as error:
            raise StoreOfflineError(f"Fab did not answer in {SCRIPT_TIMEOUT_SECONDS} s: {url}") from error
        except WebDriverException as error:
            # a browser that went away is not given back to the next request
            self.__lease.close()
            raise StoreOfflineError(f"The persona browser stopped answering: {error.msg}") from error
        finally:
            self.__last_request = time.monotonic()
        return self.__page_of(url, answer)

    def __pace(self) -> None:
        """Wait out what is left of the interval since the last request."""
        if self.__last_request is not None:
            left = self.__last_request + REQUEST_INTERVAL_SECONDS - time.monotonic()
            if left > 0:
                time.sleep(left)

    @staticmethod
    def __page_of(url: str, answer: Any) -> Page:
        """What the page's script answered, as a page, or the reason the scan must stop.

        :param url: the address asked for.
        :param answer: what :data:`FETCH_SCRIPT` returned.
        :returns: the page.
        :raises StorePausedError: a challenge, or a login that expired.
        :raises StoreOfflineError: the request did not complete, or Fab refused for the moment.
        """
        if not isinstance(answer, dict) or "status" not in answer:
            reason = answer.get("error") if isinstance(answer, dict) else None
            raise StoreOfflineError(f"Fab did not answer {url}: {reason or 'no answer'}")
        status, body = answer["status"], str(answer.get("body") or "")
        if answer.get("mitigated") == CHALLENGE_HEADER_VALUE or (status == 403 and body.lstrip().startswith("<")):
            raise StorePausedError(CHALLENGE_REASON, SITE_URL)
        if status in (401, 403):
            raise StorePausedError(LOGIN_REASON, LOGIN_URL)
        if status == 429 or status >= 500:
            raise StoreOfflineError(f"Fab answered {status}: {url}")
        return Page(url=url, final_url=url, html=body, status=status)
