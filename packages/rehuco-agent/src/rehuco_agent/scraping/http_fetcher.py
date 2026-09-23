"""The default `PageFetcher`: plain HTTP, no browser ([[acquisition-tooling#scraper-protocols]])."""

from typing import Final

import requests

from .protocols import LoginRequiredError
from .results import Page

LOGIN_WALL_STATUS_CODES: Final = frozenset({401, 403})
"""The one generic login-wall signal a plain HTTP fetch has -- most login walls answer `200` with a
login page instead, which only the scraper's own parsing can recognize
([[acquisition-tooling#browser-persona]])."""

USER_AGENT: Final = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
"""A browser User-Agent, since a plain library one is what gets a scrape refused by sites that gate on
it -- the same reason tc4's fetcher carried one."""

REQUEST_TIMEOUT_SECONDS: Final = 30
"""How long one fetch waits before giving up. Also the practical upper bound on how long a hung fetch
can delay the app noticing it -- `ScraperExecutor`'s pool waits for its runnables to finish."""


# one method is the design, not an omission -- see the docstring below
# pylint: disable-next=too-few-public-methods
class HttpPageFetcher:
    """Fetches a page over plain HTTP with a browser User-Agent.

    Satisfies `PageFetcher` structurally. A failed request (a timeout, a connection error, a 4xx/5xx
    status) raises `requests.RequestException`; `ScrapeJob` is what catches and logs it, this class
    does not swallow anything.
    """

    def fetch(self, url: str) -> Page:
        """Fetch ``url`` over HTTP.

        :param url: the address to fetch.
        :returns: the fetched page.
        :raises LoginRequiredError: the response status was ``401`` or ``403``
            (:data:`LOGIN_WALL_STATUS_CODES`).
        :raises requests.RequestException: on a connection failure, a timeout, or another 4xx/5xx
            status.
        """
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT_SECONDS)
        if response.status_code in LOGIN_WALL_STATUS_CODES:
            raise LoginRequiredError(f"{url} answered {response.status_code}, which usually means a login wall.")
        response.raise_for_status()
        return Page(url=url, final_url=response.url, html=response.text)
