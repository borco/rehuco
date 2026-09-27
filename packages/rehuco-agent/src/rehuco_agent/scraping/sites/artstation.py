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
and the same ``.product-description`` class name by what is presumably coincidence). The theme carries **no**
structured author markup and its ``.product-categories`` are broad site sections (``Resources``), not the
marketplace's tag vocabulary, so `authors` and `advertised_tags` are simply left unset on a store-host result
rather than guessed from description prose -- a different preset theme, unconfirmed, would fall back to the
same empty-field behaviour any unrecognized markup gets. Either way, `fields["url"]` carries the reconstructed
``www.artstation.com`` URL, so it lands as the primary source while the store URL actually fetched is
appended as a second one ([[acquisition-tooling#scraper-protocols]]) -- `ScrapeActions.__apply` and
`RehuDocumentModel.add_source` already do that ordering for any scraper that returns a ``url`` field, so
nothing beyond this reconstruction is needed there.
"""

import re
from typing import Final
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from bs4.element import Tag

from ..html_markdown import HtmlMarkdown
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
        """
        store_match = self.__store_path_match(page.final_url)
        if store_match is not None:
            return self.__scrape_store_page(page, store_match)
        return self.__scrape_marketplace_page(page)

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

    def __scrape_marketplace_page(self, page: Page) -> ScrapeResult:
        """Parse a ``www.artstation.com`` product page -- this module's original shape (#273)."""
        soup = BeautifulSoup(page.html, "html.parser")
        fields: dict[str, object] = {}

        header = soup.select_one(".productPage-header")
        if isinstance(header, Tag):
            title = header.find("h1")
            if isinstance(title, Tag):
                fields["title"] = title.get_text(strip=True)
            author_link = header.select_one(".productPage-header-author a[itemprop='url']")
            if isinstance(author_link, Tag):
                name = author_link.get_text(strip=True)
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

    def __scrape_store_page(self, page: Page, store_match: re.Match[str]) -> ScrapeResult:
        """Parse an artist store host's product page (#366) -- a different, white-label storefront
        template, not a re-skin of the marketplace one. No structured author link exists on this
        template, and its ``.product-categories`` name broad site sections rather than the marketplace's
        tag vocabulary, so `authors` and `advertised_tags` are left unset rather than guessed from
        description prose.
        """
        soup = BeautifulSoup(page.html, "html.parser")
        product_id, slug = store_match.groups()
        fields: dict[str, object] = {"url": f"https://www.artstation.com/marketplace/p/{product_id}/{slug}"}

        title = soup.select_one(".product-title")
        if isinstance(title, Tag):
            fields["title"] = title.get_text(strip=True)

        images = self.__scrape_store_images(soup, page.final_url)
        description = self.__scrape_description(soup)

        return ScrapeResult(fields=fields, description=description, images=images)

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
