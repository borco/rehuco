"""What a scraper is, structurally ([[acquisition-tooling#scraper-protocols]]).

Two roles, both plain `Protocol`: something that turns a URL into a :class:`~.results.Page` over HTTP,
and something that turns a fetched `Page` into a :class:`~.results.ScrapeResult` for one site. Neither
needs a base class or an import from this package to be satisfied -- a user's own script in the scripts
folder ([[acquisition-tooling#scraper-registry]]) can define a class that never heard of this module and
still be picked up, as long as its shape matches.
"""

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from .results import Page, ScrapeResult


class FetchError(Exception):
    """A `PageFetcher` could not produce a page -- a browser session failed to start, or the driver
    itself raised ([[acquisition-tooling#browser-persona]]). `~.http_fetcher.HttpPageFetcher` raises
    `requests.RequestException` instead, which `~.scrape_job.ScrapeJob` catches alongside this one."""


class LoginRequiredError(Exception):
    """Raised by :meth:`SiteScraper.scrape_page` when a fetched page is a login wall rather than the
    page it asked for ([[acquisition-tooling#browser-persona]]).

    Only the scraper itself knows what its site's login wall looks like, so detecting one is the
    scraper's job, not the fetcher's -- `~.http_fetcher.HttpPageFetcher` raises it too, but only for the
    one generic signal a plain HTTP fetch has: a ``401``/``403`` status.
    """


@runtime_checkable
# one method is the design, not an omission -- see the docstring above
# pylint: disable-next=too-few-public-methods
class PageFetcher(Protocol):
    """Turns a URL into a fetched page. The default (:class:`~.http_fetcher.HttpPageFetcher`) does this
    over plain HTTP; a scraper whose :attr:`SiteScraper.needs_browser` is `True`, or that the user
    ticked **Use browser** for, is fetched through the persona browser instead
    (:class:`~.browser_fetcher.BrowserPageFetcher`, [[acquisition-tooling#browser-persona]]).
    """

    def fetch(self, url: str) -> Page:  # pyright: ignore[reportReturnType]
        """Fetch ``url`` and report where it actually landed.

        :param url: the address to fetch.
        :returns: the fetched page.
        :raises FetchError: the fetch failed.
        :raises LoginRequiredError: the fetch landed on a login wall.
        """


@runtime_checkable
class SiteScraper(Protocol):
    """What every scraper is: something that claims a host and turns one of its pages into a result.

    Scoped to a **site** -- :attr:`label`, :attr:`publisher` and :meth:`matches` are all facts about the
    site, not about any one page -- even though its one method, :meth:`scrape_page`, is called once per
    page. A concrete class satisfies this by having the right shape, never by inheriting from it or
    importing it: :class:`~.registry.ScraperRegistry` checks with `isinstance`, which is what lets a
    user's own script in the scripts folder work with no import of this package at all.

    **One method, not one per resource type** ([[acquisition-tooling#scraper-protocols]]): a
    :class:`~.results.ScrapeResult`'s fields are an unvalidated mapping, so there is nothing left for a
    per-type dispatch to decide that :meth:`scrape_page` doesn't already answer by itself.
    """

    @property
    def label(self) -> str:  # pyright: ignore[reportReturnType]
        """How this scraper names itself, e.g. ``"ArtStation"``."""

    @property
    def publisher(self) -> str:  # pyright: ignore[reportReturnType]
        """The publisher this scraper fills into a scraped result's ``publisher`` field."""

    @property
    def site_name(self) -> str:  # pyright: ignore[reportReturnType]
        """What to display for a link to this scraper's site, on the Scrapers settings page's table
        row -- what to show, as opposed to :attr:`site_url`, where clicking it takes the user
        ([[acquisition-tooling#browser-persona]])."""

    @property
    def site_url(self) -> str:  # pyright: ignore[reportReturnType]
        """Where a click on :attr:`site_name` takes the user -- opened in the persona browser through
        `~.browser_fetcher.PersonaBrowser.open_for_login`, never through Selenium, so it is exactly as
        eligible to sign in as **Open the browser** itself is ([[acquisition-tooling#browser-persona]]).
        A new tab if the persona browser is already open, a fresh window otherwise."""

    @property
    def needs_browser(self) -> bool:  # pyright: ignore[reportReturnType]
        """Whether this scraper is always fetched through the persona browser
        ([[acquisition-tooling#browser-persona]]) rather than plain HTTP.

        `True` for a scraper that cannot read its site without a real browser session (a paywalled or
        members-only page); every other scraper answers `False` and may still be routed through the
        browser by the user's own **Use browser** choice on the Scrapers settings page.
        """

    def matches(self, url: str) -> bool:  # pyright: ignore[reportReturnType]
        """Whether this scraper handles ``url``, ordinarily a host test.

        :param url: the URL a scrape was asked to run against.
        :returns: whether this scraper should run for it.
        """

    def scrape_page(self, page: Page) -> ScrapeResult | Mapping[str, object]:  # pyright: ignore[reportReturnType]
        """Parse a fetched page into a result.

        :param page: the page :meth:`matches` accepted.
        :returns: whatever fields, description and images this scraper found, either as a `ScrapeResult`
            or as its JSON-shaped mapping ([[acquisition-tooling#scraper-protocols]]) -- a plain script
            can return the mapping directly, with no import of this package at all.
            `~.results.ScrapeResult.coerce` normalizes either form, and validates it, before it is used.
        """
