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


@runtime_checkable
# one method is the design, not an omission -- see the docstring above
# pylint: disable-next=too-few-public-methods
class PageFetcher(Protocol):
    """Turns a URL into a fetched page. The default (:class:`~.http_fetcher.HttpPageFetcher`) does this
    over plain HTTP; a browser-driven one is future work a scraper opts into via
    :attr:`SiteScraper.needs_browser` ([[acquisition-tooling#browser-persona]]).
    """

    def fetch(self, url: str) -> Page:  # pyright: ignore[reportReturnType]
        """Fetch ``url`` and report where it actually landed.

        :param url: the address to fetch.
        :returns: the fetched page.
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
    def needs_browser(self) -> bool:  # pyright: ignore[reportReturnType]
        """Whether this scraper needs the browser-driven fetcher
        ([[acquisition-tooling#browser-persona]]) rather than a plain HTTP one.

        `True` for a scraper that cannot read its site without a real browser session (a paywalled or
        members-only page); every other scraper answers `False`. A scrape asking for one before it
        exists is refused with a clear message rather than silently fetched over plain HTTP, which would
        return a login wall instead of the page.
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
