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
    text: str | None = None
    """The link's own text, set only by :meth:`parse_link`."""

    @staticmethod
    def parse_link(data: QMimeData) -> UrlDrop | None:
        """Read a **link with text** out of a drop's mime data, or answer that this drop is not one
        (#385).

        Stricter than :meth:`parse`: the drop must carry a name as well as an `http(s)` URL, from a
        `text/x-moz-url` (``URL\\nTitle``) or from the `text/html` of a dragged anchor. A bare
        `text/uri-list`, and plain text that happens to be a single URL, carry no name and answer `None`.

        :param data: the drop's mime data.
        :returns: the link, its :attr:`text` set and its :attr:`fragment` empty, or `None`.
        """
        link = UrlDrop.__read_moz_link(data) or UrlDrop.__read_anchor(data)
        if link is None:
            return None
        return UrlDrop(url=link[0], fragment=None, text=link[1])

    @staticmethod
    def __read_moz_link(data: QMimeData) -> tuple[str, str] | None:
        lines = UrlDrop.__moz_lines(data)
        if len(lines) < 2 or not UrlDrop.__is_bare_url(lines[0]):
            return None
        text = " ".join(lines[1].split())
        return (lines[0].strip(), text) if text else None

    @staticmethod
    def __read_anchor(data: QMimeData) -> tuple[str, str] | None:
        if not data.hasHtml():
            return None
        soup = BeautifulSoup(data.html(), "html.parser")
        anchor = soup.find("a", href=True)
        if anchor is None:
            return None
        href = str(anchor["href"]).strip()
        text = " ".join(anchor.get_text().split())
        # a selection spanning more than the link is page content, not a link
        if not text or not UrlDrop.__is_bare_url(href) or " ".join(soup.get_text().split()) != text:
            return None
        return href, text

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
        first_line = UrlDrop.__moz_lines(data)[:1]
        if first_line and UrlDrop.__is_bare_url(first_line[0]):
            return first_line[0]
        if data.hasText():
            text = data.text().strip()
            if UrlDrop.__is_bare_url(text):
                return text
        return None

    @staticmethod
    def __moz_lines(data: QMimeData) -> list[str]:
        if not data.hasFormat("text/x-moz-url"):
            return []
        # browsers terminate the UTF-16 text with a NUL, which would otherwise end up in the last line
        return (
            bytes(data.data("text/x-moz-url").data())
            .decode("utf-16", errors="replace")
            .replace("\x00", "")
            .splitlines()
        )

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
