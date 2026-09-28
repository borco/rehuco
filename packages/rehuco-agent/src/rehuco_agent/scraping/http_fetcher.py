"""The default `PageFetcher`: plain HTTP, no browser ([[acquisition-tooling#scraper-protocols]])."""

from typing import Final

import requests

from .protocols import LoginRequiredError
from .results import Page

LOGIN_WALL_STATUS_CODES: Final = frozenset({401, 403})
"""The one generic login-wall signal a plain HTTP fetch has -- most login walls answer `200` with a
login page instead, which only the scraper's own parsing can recognize
([[acquisition-tooling#browser-persona]])."""

TOO_MANY_REQUESTS: Final = 429
"""The one 4xx that, like a 5xx, is a transient refusal rather than a wrong address -- see
:func:`HttpPageFetcher.is_transient`."""

USER_AGENT: Final = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
"""A browser User-Agent, since a plain library one is what gets a scrape refused by sites that gate on
it -- the same reason tc4's fetcher carried one."""

REQUEST_TIMEOUT_SECONDS: Final = 30
"""How long one fetch waits before giving up. Also the practical upper bound on how long a hung fetch
can delay the app noticing it -- `ScraperExecutor`'s pool waits for its runnables to finish."""


class HttpPageFetcher:
    """Fetches a page over plain HTTP with a browser User-Agent.

    Satisfies `PageFetcher` structurally. A failed request (a timeout, a connection error, a 4xx status
    other than a transient one) raises `requests.RequestException`; `ScrapeJob` is what catches and logs
    it, this class does not swallow anything. A **transient** status (:meth:`is_transient`) is not a
    failure here: the page is handed over with its :attr:`~.results.Page.status`, since only the site's
    scraper knows whether asking again is worth it ([[acquisition-tooling#scrape-job]]).
    """

    @staticmethod
    def is_transient(status: int) -> bool:
        """Whether ``status`` is a refusal that may clear on its own -- any ``5xx``, or ``429``.

        :param status: an HTTP status code.
        :returns: whether a page answered with it is handed to its scraper rather than raised.
        """
        return status >= 500 or status == TOO_MANY_REQUESTS

    def fetch(self, url: str) -> Page:
        """Fetch ``url`` over HTTP.

        :param url: the address to fetch.
        :returns: the fetched page, carrying its status -- a transient error status included.
        :raises LoginRequiredError: the response status was ``401`` or ``403``
            (:data:`LOGIN_WALL_STATUS_CODES`).
        :raises requests.RequestException: on a connection failure, a timeout, or a 4xx status that is
            not transient.
        """
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT_SECONDS)
        if response.status_code in LOGIN_WALL_STATUS_CODES:
            raise LoginRequiredError(f"{url} answered {response.status_code}, which usually means a login wall.")
        if not self.is_transient(response.status_code):
            response.raise_for_status()
        return Page(url=url, final_url=response.url, html=response.text, status=response.status_code)
