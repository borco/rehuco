"""ArtStation product pages, tutorial and reference-images alike (#273): one page shape sells both,
so :meth:`ArtStation.scrape_page` returns whatever the page has and leaves picking out what applies
to a document's type to whoever applies the result ([[acquisition-tooling#scraper-protocols]]).

tc4's ``artstation.py`` is the source for the selectors below, re-verified against a saved fixture.
Unlike tc4, this scraper never embeds `![](...)` placeholders in the description -- ArtStation
downloads images without ever mentioning them in the description text
([[acquisition-tooling#scraper-protocols]]).
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


class ArtStation:
    """The built-in ArtStation scraper: proves itself to :class:`~.registry.ScraperRegistry` by shape,
    never by importing :class:`~.protocols.SiteScraper`.
    """

    label = "ArtStation"
    publisher = "ArtStation"
    needs_browser = False

    def matches(self, url: str) -> bool:
        """Whether ``url`` is an ArtStation page.

        :param url: the URL a scrape was asked to run against.
        :returns: whether this scraper should run for it.
        """
        return urlparse(url).netloc == "www.artstation.com"

    def scrape_page(self, page: Page) -> ScrapeResult:
        """Parse an ArtStation product page.

        :param page: the page :meth:`matches` accepted.
        :returns: whatever fields, description and images the page has; an unrelated page (no
            recognizable product markup) yields an empty result rather than an exception.
        """
        soup = BeautifulSoup(page.html, "html.parser")
        fields: dict[str, object] = {}

        header = soup.select_one(".productPage-header")
        if isinstance(header, Tag):
            title = header.find("h1")
            if isinstance(title, Tag):
                fields["title"] = title.get_text(strip=True)
            author = header.select_one(".productPage-header-author span a span[itemprop='name']")
            if isinstance(author, Tag):
                fields["authors"] = [author.get_text(strip=True)]

        gallery = soup.select_one(".productPage-gallery-col")
        description = None
        images: tuple[ScrapedImage, ...] = ()
        if isinstance(gallery, Tag):
            images = self.__scrape_images(gallery, page.final_url)
            description = self.__scrape_description(gallery)
            tags = self.__scrape_tags(gallery)
            if tags:
                fields["advertised_tags"] = tags

        return ScrapeResult(fields=fields, description=description, images=images)

    @staticmethod
    def __scrape_images(gallery: Tag, referrer: str) -> tuple[ScrapedImage, ...]:
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
    def __scrape_description(gallery: Tag) -> str | None:
        description_block = gallery.select_one(".product-description")
        if not isinstance(description_block, Tag):
            return None
        return HtmlMarkdown.convert(description_block.decode_contents())

    @staticmethod
    def __scrape_tags(gallery: Tag) -> list[str]:
        tags_block = gallery.select_one(".productPage-tags")
        if not isinstance(tags_block, Tag):
            return []
        excluded = {"tutorials", "other tutorials"}
        return [
            text
            for tag in tags_block.find_all("a", class_="productPage-tag")
            if isinstance(tag, Tag) and (text := tag.get_text(strip=True).lower()) not in excluded
        ]
