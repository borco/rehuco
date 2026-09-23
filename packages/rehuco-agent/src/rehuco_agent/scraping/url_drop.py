"""What the Main Editor dock's URL drop reads out of a `QMimeData` ([[acquisition-tooling#drag-drop-aids]],
#272): the URL a `ScrapeJob` is built for, and the already-rendered page fragment a selection drop may
carry alongside it.
"""

from dataclasses import dataclass
from typing import Final

from bs4 import BeautifulSoup
from PySide6.QtCore import QMimeData

ACCEPTED_SCHEMES: Final = frozenset({"http", "https"})
"""What §15.1's `text/uri-list`/plain-text URL rule accepts -- a `file:` URL, or any other scheme, is
refused rather than handed to a fetcher that only ever speaks HTTP(S)."""


@dataclass(frozen=True)
class UrlDrop:
    """A drop the Main Editor dock recognizes as a scrape ([[acquisition-tooling#drag-drop-aids]]).

    :param url: the `http(s)` page URL to scrape.
    :param fragment: the drop's `text/html`, when it carries more than the link itself -- the
        already-rendered page a selection drop hands the scraper directly, sparing it a refetch
        ([[acquisition-tooling#drag-drop-aids]]). `None` for a link, an address-bar drop, or a bare
        plain-text URL, which carry no page to read.
    """

    url: str
    fragment: str | None

    @staticmethod
    def parse(data: QMimeData) -> UrlDrop | None:
        """Read a `UrlDrop` out of a drop's mime data, or answer that this drop is not one
        ([[acquisition-tooling#drag-drop-aids]], §15.1.1).

        The URL is read, in order: the first `http(s)` entry of `text/uri-list`; failing that, the
        first line of `text/x-moz-url` (Firefox and Chromium's shared link/address-bar convention,
        ``URL\\nTitle``); failing that, `text/plain` when the whole stripped text is one `http(s)` URL
        with no embedded whitespace. Anything else -- a `file:` URL, another scheme, or plain text that
        is not a single URL -- answers `None`: there is nothing here to scrape.

        :param data: the drop's mime data.
        :returns: the parsed drop, or `None` when it carries no usable URL.
        """
        url = UrlDrop.__read_url(data)
        if url is None:
            return None
        return UrlDrop(url=url, fragment=UrlDrop.__read_fragment(data, url))

    @staticmethod
    def __read_url(data: QMimeData) -> str | None:
        if data.hasUrls():
            for candidate in data.urls():
                if candidate.scheme() in ACCEPTED_SCHEMES:
                    return candidate.toString()
        if data.hasFormat("text/x-moz-url"):
            first_line = bytes(data.data("text/x-moz-url").data()).decode("utf-16", errors="replace").splitlines()
            if first_line and UrlDrop.__is_bare_url(first_line[0]):
                return first_line[0]
        if data.hasText():
            text = data.text().strip()
            if UrlDrop.__is_bare_url(text):
                return text
        return None

    @staticmethod
    def __is_bare_url(text: str) -> bool:
        stripped = text.strip()
        if not stripped or any(character.isspace() for character in stripped):
            return False
        scheme, separator, _ = stripped.partition("://")
        return separator == "://" and scheme in ACCEPTED_SCHEMES

    @staticmethod
    def __read_fragment(data: QMimeData, url: str) -> str | None:
        if not data.hasHtml():
            return None
        html = data.html()
        if not html.strip():
            return None
        soup = BeautifulSoup(html, "html.parser")
        tags = list(soup.find_all(True))
        if len(tags) == 1 and tags[0].name in {"a", "img"}:
            link_url = tags[0].get("href") or tags[0].get("src")
            if link_url == url:
                return None
        text = soup.get_text(strip=True)
        if text in (url, ""):
            return None
        return html
