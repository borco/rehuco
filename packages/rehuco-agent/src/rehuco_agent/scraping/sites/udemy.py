"""Udemy course landing pages (#274).

tc4's ``udemy.py`` selectors (``lead-title``, ``instructor-name-top``, ``last-update-date``,
``curriculum-stats``) no longer exist: today's page is a Next.js/Cloudflare build whose classes are
hashed per deploy. What survives is a ``schema.org`` ``Course`` object embedded as
``application/ld+json`` -- read first, since it is a public contract rather than a styling detail. The
DOM is used only for what the ``Course`` object lacks: the instructors' profile links, the last-update
date, and the description's prose blocks, all found by ``data-purpose``, an ``href`` prefix or visible
text, never by a hashed class. The legacy ``h``/``m`` duration rule
([[acquisition-tooling#legacy-parsing]]) is skipped too: ``courseWorkload`` is already ISO 8601.
"""

import json
import re
from typing import Final
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from bs4.element import Tag

from ..html_markdown import HtmlMarkdown
from ..results import Page, ScrapedImage, ScrapeResult

COVER_SIZE_REWRITE: Final = re.compile(r"/course/\d+x\d+/")
"""Matches the Next.js resize segment in a Udemy course image URL, rewritten to ``750x422`` -- the
size the CDN still serves natively (larger sizes return 403, and a `srcset`'s largest entry is only an
upscale of the 480x270 source)."""

DURATION_TOKEN: Final = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")
"""An ISO 8601 duration as ``courseWorkload`` carries it, e.g. ``PT22H23M``."""

LAST_UPDATED: Final = re.compile(r"Last updated (\d{1,2})/(\d{4})")

INSTRUCTOR_HREF: Final = re.compile(r"^(?:https://www\.udemy\.com)?/user/")
"""An instructor's profile link, relative as today's page writes it or absolute."""


class Udemy:
    """The built-in Udemy scraper: proves itself to :class:`~.registry.ScraperRegistry` by shape,
    never by importing :class:`~.protocols.SiteScraper`.
    """

    label = "Udemy"
    publisher = "Udemy"
    site_name = "Udemy"
    site_url = "https://www.udemy.com"
    needs_browser = False

    def matches(self, url: str) -> bool:
        """Whether ``url`` is a Udemy page.

        :param url: the URL a scrape was asked to run against.
        :returns: whether this scraper should run for it.
        """
        return urlparse(url).netloc == "www.udemy.com"

    def scrape_page(self, page: Page) -> ScrapeResult:
        """Parse a Udemy course landing page.

        :param page: the page :meth:`matches` accepted.
        :returns: whatever fields, description and images the page has; an unrelated page (no
            recognizable ``Course`` object) yields an empty result rather than an exception.
        """
        soup = BeautifulSoup(page.html, "html.parser")
        course = self.__find_course(soup)
        fields: dict[str, object] = {}
        images: tuple[ScrapedImage, ...] = ()

        if course is not None:
            name = course.get("name")
            if isinstance(name, str):
                fields["title"] = name
            authors = self.__scrape_authors(soup, page.final_url, course)
            if authors:
                fields["authors"] = authors
            released = self.__scrape_released(soup)
            if released is not None:
                fields["released"] = released
            duration = self.__scrape_duration(course)
            if duration is not None:
                fields["advertised_duration"] = duration
            image = course.get("image")
            if isinstance(image, str):
                url = COVER_SIZE_REWRITE.sub("/course/750x422/", image)
                images = (ScrapedImage(slot=0, url=url, referrer=None),)

        description = self.__scrape_description(soup, course)
        return ScrapeResult(fields=fields, description=description, images=images)

    @staticmethod
    def __find_course(soup: BeautifulSoup) -> dict[str, object] | None:
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
            except TypeError, ValueError:
                continue
            candidates = data.get("@graph", [data]) if isinstance(data, dict) else []
            for candidate in candidates:
                if isinstance(candidate, dict) and candidate.get("@type") == "Course":
                    return candidate
        return None

    @staticmethod
    def __scrape_authors(soup: BeautifulSoup, referrer_url: str, course: dict[str, object]) -> list[object]:
        seen: set[str] = set()
        authors: list[object] = []
        for link in soup.find_all("a", href=INSTRUCTOR_HREF):
            href = link.get("href")
            name = link.get_text(strip=True)
            if not isinstance(href, str) or not name or href in seen:
                continue
            seen.add(href)
            authors.append({"name": name, "url": urljoin(referrer_url, href)})
        if authors:
            return authors
        raw_authors = course.get("author")
        if isinstance(raw_authors, list):
            return [
                author["name"]
                for author in raw_authors
                if isinstance(author, dict) and isinstance(author.get("name"), str)
            ]
        return []

    @staticmethod
    def __scrape_released(soup: BeautifulSoup) -> str | None:
        match = LAST_UPDATED.search(soup.get_text())
        return f"{match[2]}-{int(match[1]):02d}" if match is not None else None

    @staticmethod
    def __scrape_duration(course: dict[str, object]) -> int | None:
        instance = course.get("hasCourseInstance")
        workload = instance.get("courseWorkload") if isinstance(instance, dict) else None
        if not isinstance(workload, str):
            return None
        match = DURATION_TOKEN.fullmatch(workload)
        if match is None or not any(match.groups()):
            return None
        hours, minutes, seconds = (int(group) if group else 0 for group in match.groups())
        return hours * 3600 + minutes * 60 + seconds

    @staticmethod
    def __scrape_description(soup: BeautifulSoup, course: dict[str, object] | None) -> str | None:
        parts: list[str] = []
        headline = course.get("description") if course is not None else None
        if isinstance(headline, str) and headline:
            parts.append(f"*{headline}*")
        for block in (
            soup.select_one("div.component-margin:has([data-purpose=objective])"),
            soup.select_one("div.component-margin:has(> [data-purpose=requirements-title])"),
            soup.select_one("[data-purpose=course-description]"),
        ):
            if isinstance(block, Tag):
                for button in block.find_all("button"):
                    button.decompose()
                parts.append(HtmlMarkdown.convert(block.decode_contents()))
        return "\n\n".join(parts) if parts else None
