"""Tests for `acquire` (#73): turning a path, a drop's own bytes, or a URL into plain image bytes and
an extension. The network is mocked; only the request shape and the dispatch logic are under test."""

from pathlib import Path
from typing import Final

from pytest import mark, raises
from pytest_mock import MockerFixture
from rehuco_agent.scraping.http_fetcher import REQUEST_TIMEOUT_SECONDS, USER_AGENT
from rehuco_agent.scraping.image_pipeline import ImageBytes, NotAnImageError, acquire
from requests import RequestException

URL: Final = "https://example.com/photo.jpg"


# region a path


def test_a_path_with_a_known_extension_is_read_verbatim(mocker: MockerFixture) -> None:
    """A local file's bytes are read exactly as they are, with its own extension (#73).

    **Test steps:**

    * acquire a ``.png`` path whose bytes are stood in for
    * verify the bytes and extension came back unchanged
    """
    mocker.patch.object(Path, "read_bytes", return_value=b"pixels")

    result = acquire(Path("/fake/cover.png"))

    assert result.data == b"pixels"
    assert result.extension == ".png"


def test_a_path_with_an_unknown_extension_is_refused() -> None:
    """A path whose suffix is not a recognized image extension is refused outright (#73).

    **Test steps:**

    * acquire a ``.txt`` path
    * verify `NotAnImageError` was raised
    """
    with raises(NotAnImageError):
        acquire(Path("/fake/notes.txt"))


def test_a_path_with_no_extension_is_refused() -> None:
    """A path with no extension at all is refused too (#73).

    **Test steps:**

    * acquire a path with no suffix
    * verify `NotAnImageError` was raised
    """
    with raises(NotAnImageError):
        acquire(Path("/fake/cover"))


# endregion

# region a drop's own bytes


def test_known_mime_bytes_are_carried_through_with_the_matching_extension() -> None:
    """A drop's own ``image/*`` payload keeps its bytes, mapped to the matching extension (#73).

    **Test steps:**

    * acquire an `ImageBytes` carrying a recognized mime type
    * verify the bytes and the mapped extension came back
    """
    result = acquire(ImageBytes(data=b"pixels", mime_type="image/png"))

    assert result.data == b"pixels"
    assert result.extension == ".png"


def test_an_unrecognized_mime_type_is_refused() -> None:
    """A drop's own payload under a mime type this pipeline does not map is refused (#73).

    **Test steps:**

    * acquire an `ImageBytes` carrying an unrecognized mime type
    * verify `NotAnImageError` was raised
    """
    with raises(NotAnImageError):
        acquire(ImageBytes(data=b"pixels", mime_type="image/bmp"))


# endregion

# region a URL download


def test_a_url_download_sends_the_pipelines_user_agent(mocker: MockerFixture) -> None:
    """Every download identifies itself with the same browser User-Agent the scraper's own fetches use
    (#73).

    **Test steps:**

    * stand in for ``requests.get`` with an ``image/jpeg`` response
    * acquire the URL with no referrer
    * verify the request carried the User-Agent and timeout, and no ``Referer``
    """
    response = mocker.Mock(content=b"pixels", headers={"Content-Type": "image/jpeg"})
    get = mocker.patch("rehuco_agent.scraping.image_pipeline.requests.get", return_value=response)

    result = acquire(URL)

    get.assert_called_once_with(URL, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status.assert_called_once_with()
    assert result.data == b"pixels"
    assert result.extension == ".jpg"


def test_a_referrer_is_sent_only_when_given(mocker: MockerFixture) -> None:
    """A page to attribute the download to is sent as ``Referer``; omitted entirely when there is none
    (#73).

    **Test steps:**

    * stand in for ``requests.get``
    * acquire the URL with a referrer
    * verify the request carried it
    """
    response = mocker.Mock(content=b"pixels", headers={"Content-Type": "image/png"})
    get = mocker.patch("rehuco_agent.scraping.image_pipeline.requests.get", return_value=response)

    acquire(URL, referrer="https://example.com/page")

    get.assert_called_once_with(
        URL,
        headers={"User-Agent": USER_AGENT, "Referer": "https://example.com/page"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )


def test_the_content_type_wins_over_the_urls_own_suffix(mocker: MockerFixture) -> None:
    """A response's own ``Content-Type`` decides the extension, even when the URL's path suffix
    disagrees (#73).

    **Test steps:**

    * download a ``.jpg``-suffixed URL whose response answers ``image/png``
    * verify the extension came from the content type, not the URL
    """
    response = mocker.Mock(content=b"pixels", headers={"Content-Type": "image/png"})
    mocker.patch("rehuco_agent.scraping.image_pipeline.requests.get", return_value=response)

    result = acquire("https://example.com/cover.jpg")

    assert result.extension == ".png"


def test_a_content_type_with_charset_params_is_still_recognized(mocker: MockerFixture) -> None:
    """A ``Content-Type`` carrying extra parameters (e.g. ``; charset=utf-8``) is still matched on its
    leading mime type alone (#73).

    **Test steps:**

    * download with a response answering ``image/gif; charset=binary``
    * verify the ``.gif`` extension was recognized
    """
    response = mocker.Mock(content=b"pixels", headers={"Content-Type": "image/gif; charset=binary"})
    mocker.patch("rehuco_agent.scraping.image_pipeline.requests.get", return_value=response)

    result = acquire(URL)

    assert result.extension == ".gif"


def test_an_unrecognized_content_type_falls_back_to_the_urls_own_suffix(mocker: MockerFixture) -> None:
    """A response with no recognized content type falls back to the URL's own suffix -- a CDN that
    answers ``application/octet-stream`` for a plainly-named image (#73).

    **Test steps:**

    * download a ``.png``-suffixed URL whose response answers an unrecognized content type
    * verify the ``.png`` extension came from the URL
    """
    response = mocker.Mock(content=b"pixels", headers={"Content-Type": "application/octet-stream"})
    mocker.patch("rehuco_agent.scraping.image_pipeline.requests.get", return_value=response)

    result = acquire("https://example.com/cover.png")

    assert result.extension == ".png"


def test_the_fallback_suffix_strips_the_query_and_fragment(mocker: MockerFixture) -> None:
    """The URL's own suffix is read off its path alone -- a query string or a fragment never becomes
    part of the extension (#73).

    **Test steps:**

    * download a URL carrying a query string and a fragment after its ``.jpg`` path
    * verify the ``.jpg`` extension was recognized
    """
    response = mocker.Mock(content=b"pixels", headers={"Content-Type": "application/octet-stream"})
    mocker.patch("rehuco_agent.scraping.image_pipeline.requests.get", return_value=response)

    result = acquire("https://example.com/cover.jpg?w=100&h=200#top")

    assert result.extension == ".jpg"


def test_neither_content_type_nor_suffix_recognized_raises(mocker: MockerFixture) -> None:
    """A response that answers no recognized content type, from a URL with no recognized suffix, is not
    something this pipeline can save (#73).

    **Test steps:**

    * download a suffix-less URL whose response answers an unrecognized content type
    * verify `NotAnImageError` was raised
    """
    response = mocker.Mock(content=b"pixels", headers={"Content-Type": "text/html"})
    mocker.patch("rehuco_agent.scraping.image_pipeline.requests.get", return_value=response)

    with raises(NotAnImageError):
        acquire("https://example.com/gallery")


@mark.parametrize("content_type", ["", None])
def test_a_missing_content_type_header_is_treated_as_unrecognized(
    mocker: MockerFixture, content_type: str | None
) -> None:
    """A response with no ``Content-Type`` at all falls back to the URL's own suffix, same as an
    explicitly unrecognized one (#73).

    **Test steps:**

    * download a ``.jpg``-suffixed URL whose response carries no content type header
    * verify the ``.jpg`` extension came from the URL
    """
    headers = {} if content_type is None else {"Content-Type": content_type}
    response = mocker.Mock(content=b"pixels", headers=headers)
    mocker.patch("rehuco_agent.scraping.image_pipeline.requests.get", return_value=response)

    result = acquire("https://example.com/cover.jpg")

    assert result.extension == ".jpg"


def test_raise_for_status_propagates(mocker: MockerFixture) -> None:
    """A failed fetch's error propagates as-is; no image ever gets synthesized from it (#73).

    **Test steps:**

    * stand in for ``requests.get`` with a response whose status check raises
    * verify the failure propagates
    """
    response = mocker.Mock()
    response.raise_for_status.side_effect = RequestException("boom")
    mocker.patch("rehuco_agent.scraping.image_pipeline.requests.get", return_value=response)

    with raises(RequestException, match="boom"):
        acquire(URL)


# endregion
