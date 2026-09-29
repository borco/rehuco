"""ArtStation product pages, tutorial and reference-images alike (#273): one page shape sells both,
so :meth:`ArtStation.scrape_page` returns whatever the page has and leaves picking out what applies
to a document's type to whoever applies the result ([[acquisition-tooling#scraper-protocols]]).

tc4's ``artstation.py`` is the source for the selectors below, re-verified against a saved fixture.
Unlike tc4, this scraper never embeds `![](...)` placeholders in the description -- ArtStation
downloads images without ever mentioning them in the description text
([[acquisition-tooling#scraper-protocols]]).

The same product also serves under an artist's own store host (``<artist>.artstation.com/store/<id>/<slug>``,
#366) -- a second URL for the identical page, but **not** the identical markup: a store-host page is
ArtStation's own storefront product (its Website Builder's ``theme-basic`` preset, confirmed against two
unrelated artists' stores), a wholly different, artist-branded template, not a re-skin of the marketplace
page above. :meth:`ArtStation.matches` accepts both shapes; :meth:`ArtStation.scrape_page` dispatches to
whichever parsing the host calls for -- :meth:`__scrape_marketplace_page` (this module's original selectors)
or :meth:`__scrape_store_page` (the storefront theme's own: ``.product-title``, ``.product-carousel-row``,
and the same ``.product-description`` class name by what is presumably coincidence). The theme's author is
the header's site title paired with the platform's own "Report" dropdown link -- no ``itemprop`` to rely on
here, unlike the marketplace page, so name and URL come from two unrelated corners of the page rather than
one element. Its ``.product-categories`` are broad site sections (``Resources``), not the marketplace's tag
vocabulary, so `advertised_tags` alone is left unset on a store-host result rather than guessed from
description prose -- a different preset theme, unconfirmed, would fall back to the same empty-field
behaviour any unrecognized markup gets. Either way, `fields["url"]` carries the reconstructed
``www.artstation.com`` URL: `ScrapeActions.__apply` adds it as a source ahead of the store URL actually
fetched, so on a fresh document it becomes the primary and the store URL a second entry, and on one that
already has sources both are kept beside them ([[acquisition-tooling#scraper-protocols]]) -- nothing
beyond this reconstruction is needed here.

**A transient refusal on the store host is retried on the marketplace** (#369): a ``503`` or ``429``
(:data:`RETRYABLE_STATUSES`) makes :meth:`ArtStation.scrape_page` raise
`~.protocols.RefetchRequestedError` itself, ahead of `~.scrape_job.ScrapeJob.scrape`'s generic status check,
naming the marketplace URL the same reconstruction builds. The reverse has nothing to go on -- a
marketplace URL never names the artist whose store serves it -- so a refused marketplace page asks for
itself again.

The refusal is read from the page's HTTP status when the fetcher could report one, and from the page
itself otherwise: ArtStation's refusal is its front server's stock error page, titled
``503 Service Temporarily Unavailable`` with the same line as its only heading -- confirmed against a copy
saved from the persona browser (:data:`STOCK_ERROR_TITLE`).
"""

import re
from typing import Final
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from bs4.element import Tag

from ..html_markdown import HtmlMarkdown
from ..protocols import RefetchRequestedError
from ..results import Page, ScrapedImage, ScrapeResult

FULL_SIZE_REWRITE: Final = re.compile(
    r"/(small|smaller_square|small_square|medium|medium_square|medium_rectangle|thumb|thumbnail)"
    r"/([^/?]+)(?=\?|$)"
)
"""Matches a smaller named ArtStation asset-size segment directly before the filename, so it can be
rewritten to ``large`` -- the "rewrite to the full-size asset where the URL pattern allows" the issue
asks for. A `data-src` already at `large` (or some other pattern) is left untouched."""

STORE_PATH: Final = re.compile(r"^/store/([^/]+)/([^/]+)/?$")
"""An artist store host's product path, ``/store/<id>/<slug>`` -- the two captures
:meth:`ArtStation.__scrape_store_page` reassembles into the ``www.artstation.com`` marketplace URL."""

RETRYABLE_STATUSES: Final = frozenset({429}) | frozenset(range(500, 600))
"""The statuses a scrape asks to re-fetch (#369): a server error or the rate-limit answer, each worth
asking again, as opposed to a permanent refusal (``404``, a login wall)."""

STOCK_ERROR_TITLE: Final = re.compile(
    r"(\d{3}) (?:Internal Server Error|Bad Gateway|Service (?:Temporarily )?Unavailable|Gateway Time-?out"
    r"|Too Many Requests)"
)
"""The ``<title>`` of a web server's stock error page -- nginx's wording (``503 Service Temporarily
Unavailable``, ``504 Gateway Time-out``) and the standard one alike -- matched whole, so a product that
merely starts its name with a number is never taken for one (#369). The capture is the status it names."""


class ArtStation:
    """The built-in ArtStation scraper: proves itself to :class:`~.registry.ScraperRegistry` by shape,
    never by importing :class:`~.protocols.SiteScraper`.
    """

    label = "ArtStation"
    publisher = "ArtStation"
    site_name = "ArtStation"
    site_url = "https://www.artstation.com"
    needs_browser = False

    def matches(self, url: str) -> bool:
        """Whether ``url`` is an ArtStation product page: the marketplace host, or an artist's own
        store host at its ``/store/<id>/<slug>`` path (#366) -- the same product, a different URL. A
        store-host page with any other path (a portfolio, ``magazine.``, a CDN host) is not a product
        page and is left unmatched.

        :param url: the URL a scrape was asked to run against.
        :returns: whether this scraper should run for it.
        """
        return urlparse(url).netloc == "www.artstation.com" or self.__store_path_match(url) is not None

    def scrape_page(self, page: Page) -> ScrapeResult:
        """Parse an ArtStation product page, marketplace-host or store-host (#366) alike.

        :param page: the page :meth:`matches` accepted.
        :returns: whatever fields, description and images the page has; an unrelated page (no
            recognizable product markup, of either shape) yields an empty result rather than an
            exception.
        :raises RefetchRequestedError: the page is a transient refusal (:meth:`__refusal_status`) --
            asking for the marketplace URL when a store host refused, the same URL again otherwise (#369).
        """
        soup = BeautifulSoup(page.html, "html.parser")
        store_match = self.__store_path_match(page.final_url)
        refusal = self.__refusal_status(page, soup)
        if refusal is not None:
            raise RefetchRequestedError(
                f"ArtStation answered {refusal}",
                url=self.__marketplace_url(store_match) if store_match is not None else None,
            )
        if store_match is not None:
            return self.__scrape_store_page(page, soup, store_match)
        return self.__scrape_marketplace_page(page, soup)

    @staticmethod
    def __refusal_status(page: Page, soup: BeautifulSoup) -> int | None:
        """The transient refusal ``page`` is, if it is one (#369): its HTTP status when that is one of
        :data:`RETRYABLE_STATUSES`, else the status a stock error page names in its title
        (:data:`STOCK_ERROR_TITLE`) -- what a fetcher that reports no status, or a server that served its
        error page as ``200``, leaves to go on.

        :param page: the fetched page.
        :param soup: its parsed markup.
        :returns: the refusal's status, or `None` when the page is not one.
        """
        if page.status in RETRYABLE_STATUSES:
            return page.status
        title = soup.title.get_text(strip=True) if isinstance(soup.title, Tag) else ""
        match = STOCK_ERROR_TITLE.fullmatch(title)
        if match is None:
            return None
        status = int(match.group(1))
        return status if status in RETRYABLE_STATUSES else None

    @staticmethod
    def __marketplace_url(store_match: re.Match[str]) -> str:
        """The ``www.artstation.com`` URL of the product a store-host path names (#366).

        :param store_match: :meth:`__store_path_match` of a store-host URL.
        :returns: ``https://www.artstation.com/marketplace/p/<id>/<slug>``.
        """
        product_id, slug = store_match.groups()
        return f"https://www.artstation.com/marketplace/p/{product_id}/{slug}"

    @staticmethod
    def __store_path_match(url: str) -> re.Match[str] | None:
        """``url``'s ``/store/<id>/<slug>`` match, when it names an artist's own store host (#366) rather
        than ``www.artstation.com`` -- the one test :meth:`scrape_page` needs to pick its parsing, shared
        with :meth:`matches`.

        :param url: the page actually fetched, `Page.final_url`.
        :returns: the match, or `None` on the marketplace host or an unrecognized path.
        """
        parsed = urlparse(url)
        if parsed.netloc == "www.artstation.com":
            return None
        return STORE_PATH.match(parsed.path) if parsed.netloc.endswith(".artstation.com") else None

    def __scrape_marketplace_page(self, page: Page, soup: BeautifulSoup) -> ScrapeResult:
        """Parse a ``www.artstation.com`` product page -- this module's original shape (#273)."""
        fields: dict[str, object] = {}

        header = soup.select_one(".productPage-header")
        if isinstance(header, Tag):
            title = header.find("h1")
            if isinstance(title, Tag):
                fields["title"] = title.get_text(strip=True)
            author_link = header.select_one(".productPage-header-author a[itemprop='url']")
            if isinstance(author_link, Tag):
                name = self.__seller_name(author_link)
                url = author_link.get("href")
                fields["authors"] = [{"name": name, "url": url} if isinstance(url, str) else name]

        gallery = soup.select_one(".productPage-gallery-col")
        description = None
        images: tuple[ScrapedImage, ...] = ()
        if isinstance(gallery, Tag):
            images = self.__scrape_marketplace_images(gallery, page.final_url)
            description = self.__scrape_description(gallery)
            tags = self.__scrape_marketplace_tags(gallery)
            if tags:
                fields["advertised_tags"] = tags

        return ScrapeResult(fields=fields, description=description, images=images)

    @staticmethod
    def __seller_name(author_link: Tag) -> str:
        """The seller's name alone (#384): the link can carry more text than the name -- a "Learn more about
        this seller" label -- and ``get_text`` over the whole link would glue it on. Reads the
        ``itemprop="name"`` node when there is one, else only the link's own direct text nodes.

        :param author_link: the header's ``itemprop="url"`` author link.
        :returns: the name, empty when the link holds none.
        """
        name_node = author_link.select_one("[itemprop='name']")
        if isinstance(name_node, Tag):
            return name_node.get_text(strip=True)
        return " ".join(text.strip() for text in author_link.find_all(string=True, recursive=False) if text.strip())

    def __scrape_store_page(self, page: Page, soup: BeautifulSoup, store_match: re.Match[str]) -> ScrapeResult:
        """Parse an artist store host's product page (#366) -- a different, white-label storefront
        template, not a re-skin of the marketplace one. Its ``.product-categories`` name broad site
        sections rather than the marketplace's tag vocabulary, so `advertised_tags` is left unset rather
        than guessed from description prose.
        """
        fields: dict[str, object] = {"url": self.__marketplace_url(store_match)}

        title = soup.select_one(".product-title")
        if isinstance(title, Tag):
            fields["title"] = title.get_text(strip=True)

        author = self.__scrape_store_author(soup)
        if author is not None:
            fields["authors"] = [author]

        images = self.__scrape_store_images(soup, page.final_url)
        description = self.__scrape_description(soup)

        return ScrapeResult(fields=fields, description=description, images=images)

    @staticmethod
    def __scrape_store_author(soup: BeautifulSoup) -> object | None:
        """The store's own seller, the same identity the marketplace page's author link names (#366): the
        header's site title for the name, no ``itemprop`` to rely on here, so paired with the platform's
        own "Report" dropdown for the profile link -- present on every product page, unlike the footer's
        social icons, which turn out to be an artist's optional choice. Falls back to the page's
        ``og:site_name`` meta tag for the name when the site title is missing -- a different preset theme
        need not use ``.site-title`` at all, and the Open Graph tag is there for social sharing regardless
        of theme.

        :param soup: the store page's parsed markup.
        :returns: a name+url record, a plain name when no report-dropdown link is found, or `None` when
            neither the site title nor ``og:site_name`` names anyone.
        """
        title_link = soup.select_one(".site-title a")
        name = title_link.get_text(strip=True) if isinstance(title_link, Tag) else ""
        if not name:
            site_name_meta = soup.select_one('meta[property="og:site_name"]')
            content = site_name_meta.get("content") if isinstance(site_name_meta, Tag) else None
            name = content.strip() if isinstance(content, str) else ""
        if not name:
            return None
        author_link = soup.select_one('.report-section a[href*="artstation.com"]')
        url = author_link.get("href") if isinstance(author_link, Tag) else None
        return {"name": name, "url": url} if isinstance(url, str) else name

    @staticmethod
    def __scrape_marketplace_images(gallery: Tag, referrer: str) -> tuple[ScrapedImage, ...]:
        images = []
        for slot, button in enumerate(gallery.select("button.image-gallery-thumbnail")):
            img = button.find("img")
            if not isinstance(img, Tag):
                continue
            data_src = img.get("data-src")
            if not isinstance(data_src, str):
                continue
            url = FULL_SIZE_REWRITE.sub(r"/large/\2", data_src)
            images.append(ScrapedImage(slot=slot, url=url, referrer=referrer))
        return tuple(images)

    @staticmethod
    def __scrape_store_images(soup: BeautifulSoup, referrer: str) -> tuple[ScrapedImage, ...]:
        carousel = soup.select_one(".product-carousel-row")
        if not isinstance(carousel, Tag):
            return ()
        images = []
        for slot, item in enumerate(carousel.select(".product-carousel-item")):
            img = item.find("img")
            if not isinstance(img, Tag):
                continue
            src = img.get("src")
            if not isinstance(src, str):
                continue
            url = FULL_SIZE_REWRITE.sub(r"/large/\2", src)
            images.append(ScrapedImage(slot=slot, url=url, referrer=referrer))
        return tuple(images)

    @staticmethod
    def __scrape_description(root: Tag) -> str | None:
        description_block = root.select_one(".product-description")
        if not isinstance(description_block, Tag):
            return None
        return HtmlMarkdown.convert(description_block.decode_contents())

    @staticmethod
    def __scrape_marketplace_tags(gallery: Tag) -> list[str]:
        tags_block = gallery.select_one(".productPage-tags")
        if not isinstance(tags_block, Tag):
            return []
        excluded = {"tutorials", "other tutorials"}
        return [
            text
            for tag in tags_block.find_all("a", class_="productPage-tag")
            if isinstance(tag, Tag) and (text := tag.get_text(strip=True).lower()) not in excluded
        ]
