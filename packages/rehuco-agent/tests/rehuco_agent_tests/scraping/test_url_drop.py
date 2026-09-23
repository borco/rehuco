"""Tests for `UrlDrop.parse` (#272): the acceptance matrix for what the Main Editor dock's drop
handler recognizes as a scrape."""

from PySide6.QtCore import QMimeData, QUrl
from rehuco_agent.scraping.url_drop import UrlDrop

URL = "https://example.com/page"


def _moz_url_data(text: str) -> QMimeData:
    data = QMimeData()
    data.setData("text/x-moz-url", text.encode("utf-16"))
    return data


# region uri-list


def test_a_uri_list_url_is_accepted() -> None:
    """A `text/uri-list` drop with one `http(s)` entry gives that URL, no fragment (#272)."""
    data = QMimeData()
    data.setUrls([QUrl(URL)])

    drop = UrlDrop.parse(data)

    assert drop == UrlDrop(url=URL, fragment=None)


def test_a_file_uri_list_is_refused() -> None:
    """A `file:` URL is not something a `PageFetcher` can read, so the drop is refused (#272)."""
    data = QMimeData()
    data.setUrls([QUrl.fromLocalFile("C:/some/file.jpg")])

    assert UrlDrop.parse(data) is None


# endregion
# region text/x-moz-url


def test_an_x_moz_url_is_accepted() -> None:
    """The link/address-bar convention Firefox and Chromium both write, `URL\\nTitle` (#272)."""
    data = _moz_url_data(f"{URL}\nSome Title")

    drop = UrlDrop.parse(data)

    assert drop == UrlDrop(url=URL, fragment=None)


def test_an_x_moz_url_whose_first_line_is_not_a_url_falls_through() -> None:
    """A malformed `text/x-moz-url` (its first line isn't a bare URL) is not used, and with nothing
    else in the drop this falls through to `None` (#272)."""
    data = _moz_url_data("not a url\nSome Title")

    assert UrlDrop.parse(data) is None


# endregion
# region text/plain


def test_a_bare_plain_text_url_is_accepted() -> None:
    """A plain-text drop that is exactly one `http(s)` URL, nothing else (#272)."""
    data = QMimeData()
    data.setText(URL)

    drop = UrlDrop.parse(data)

    assert drop == UrlDrop(url=URL, fragment=None)


def test_plain_text_that_is_not_a_url_is_refused() -> None:
    """Ordinary text -- what a Firefox selection carries with no URL at all -- is refused (#272)."""
    data = QMimeData()
    data.setText("just some selected words")

    assert UrlDrop.parse(data) is None


def test_an_ftp_url_is_refused() -> None:
    """A non-http(s) scheme is refused even when it parses as a URL (#272)."""
    data = QMimeData()
    data.setText("ftp://example.com/file")

    assert UrlDrop.parse(data) is None


def test_plain_text_with_a_url_plus_more_words_is_refused() -> None:
    """The whole stripped text must be the URL -- a sentence containing one is not a URL drop (#272)."""
    data = QMimeData()
    data.setText(f"check out {URL} it's great")

    assert UrlDrop.parse(data) is None


# endregion
# region fragment


def test_html_with_only_the_matching_link_carries_no_fragment() -> None:
    """A lone `<a>` pointing at the dropped URL is the link itself, not page content (#272)."""
    data = QMimeData()
    data.setUrls([QUrl(URL)])
    data.setHtml(f'<a href="{URL}">Example</a>')

    drop = UrlDrop.parse(data)

    assert drop == UrlDrop(url=URL, fragment=None)


def test_html_with_real_page_content_carries_it_as_the_fragment() -> None:
    """A selection whose `text/html` is more than the URL travels with it as the page fragment (#272)."""
    data = QMimeData()
    data.setUrls([QUrl(URL)])
    html = "<h1>Title</h1><p>Some real page content.</p>"
    data.setHtml(html)

    drop = UrlDrop.parse(data)

    assert drop is not None
    assert drop.url == URL
    assert drop.fragment == html


def test_html_with_no_content_carries_no_fragment() -> None:
    """Blank `text/html` (e.g. a bare image drag with nothing else) carries no fragment (#272)."""
    data = QMimeData()
    data.setUrls([QUrl(URL)])
    data.setHtml("   ")

    drop = UrlDrop.parse(data)

    assert drop == UrlDrop(url=URL, fragment=None)


def test_html_with_a_bare_image_pointing_elsewhere_carries_no_fragment() -> None:
    """A lone `<img>` whose `src` is not the dropped URL is still just the drag thumbnail, not page
    content -- its empty text falls through the same way the matching-link case does (#272)."""
    data = QMimeData()
    data.setUrls([QUrl(URL)])
    data.setHtml('<img src="https://cdn.example.com/thumb.jpg">')

    drop = UrlDrop.parse(data)

    assert drop == UrlDrop(url=URL, fragment=None)


def test_html_with_no_url_at_all_is_refused() -> None:
    """A selection whose `text/html` carries page content but no URL anywhere has nothing to scrape by
    (§15.1.1: this is every Firefox selection) (#272)."""
    data = QMimeData()
    data.setHtml("<h1>Title</h1><p>Some real page content.</p>")

    assert UrlDrop.parse(data) is None


# endregion
