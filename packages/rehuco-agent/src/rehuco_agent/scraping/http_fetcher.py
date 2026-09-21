"""The default `PageFetcher`: plain HTTP, no browser ([[acquisition-tooling#scraper-protocols]])."""

from typing import Final

import requests

from .results import Page

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
        :raises requests.RequestException: on a connection failure, a timeout, or a 4xx/5xx status.
        """
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        return Page(url=url, final_url=response.url, html=response.text)
