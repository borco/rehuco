"""Turns whatever a drop or a scrape names into plain, unmodified image bytes ([[acquisition-tooling#drag-drop-aids]],
#73).

The one seam every acquired screenshot goes through before it reaches
`~rehuco_agent.fields.image_organizer.ImageOrganizer.acquire`, whatever it came from: a local file
dropped on the images sub-dock, a drop's own ``image/*`` data, or a scraper's downloaded URL. Nothing
here decodes, rescales or re-encodes anything -- an animated GIF that arrives here leaves with the same
animation, byte for byte, which is the whole reason this module never imports Pillow.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Final

import requests
from rehuco_core import IMAGE_EXTENSIONS

from .http_fetcher import REQUEST_TIMEOUT_SECONDS, USER_AGENT

MIME_EXTENSIONS: Final[dict[str, str]] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}
"""What a MIME type saves as, when one is known -- checked ahead of a URL's own suffix, since a CDN
link often carries no extension at all (e.g. a query-string image endpoint)."""


@dataclass(frozen=True)
class ImageBytes:
    """A drop's own image data, read out of its mime data before this module ever sees it.

    :param data: the raw bytes, exactly as the drop carried them.
    :param mime_type: the mime format they were read under, e.g. ``"image/png"``.
    """

    data: bytes
    mime_type: str


@dataclass(frozen=True)
class AcquiredImage:
    """One image's bytes, ready for `~rehuco_agent.fields.image_organizer.ImageOrganizer.acquire`.

    :param data: the raw bytes, unmodified from wherever they came from.
    :param extension: the file's extension, leading dot included.
    """

    data: bytes
    extension: str


class NotAnImageError(ValueError):
    """``acquire`` was asked to save something that is not recognizable as an image.

    Raised for a URL fetch whose response is not ``image/*`` and whose own suffix is not one of
    :data:`~rehuco_core.IMAGE_EXTENSIONS` either -- there is nothing here that decodes bytes to find out
    what they actually are, so an extension or a content type is all this ever goes by.
    """


def acquire(source: Path | ImageBytes | str, referrer: str | None = None) -> AcquiredImage:
    """Turn ``source`` into plain bytes and an extension, downloading it first if it names a URL.

    :param source: a local file's path, a drop's own :class:`ImageBytes`, or an ``http(s)`` URL to
        fetch.
    :param referrer: the page to send as a URL fetch's ``Referer``, or ``None`` when the site does not
        need one. Ignored for the other two kinds of source, which name no page they came from.
    :returns: the acquired bytes and extension.
    :raises OSError: ``source`` is a path and could not be read.
    :raises requests.RequestException: ``source`` is a URL and the fetch failed.
    :raises NotAnImageError: ``source`` is a URL whose response was not recognizable as an image, or is
        a path or a mime type whose extension is not one of :data:`~rehuco_core.IMAGE_EXTENSIONS`.
    """
    if isinstance(source, Path):
        extension = source.suffix.lower()
        if extension not in IMAGE_EXTENSIONS:
            raise NotAnImageError(f"{source} is not a recognized image ({extension or 'no extension'})")
        return AcquiredImage(data=source.read_bytes(), extension=extension)
    if isinstance(source, ImageBytes):
        extension = MIME_EXTENSIONS.get(source.mime_type)
        if extension is None:
            raise NotAnImageError(f"{source.mime_type} is not a recognized image format")
        return AcquiredImage(data=source.data, extension=extension)
    return _download(source, referrer)


def _download(url: str, referrer: str | None) -> AcquiredImage:
    """Fetch ``url`` over plain HTTP and read its bytes and extension.

    :param url: the address to fetch.
    :param referrer: the page to send as ``Referer``, or ``None`` to send none.
    :returns: the fetched bytes and extension.
    :raises requests.RequestException: the fetch failed.
    :raises NotAnImageError: the response was not recognizable as an image.
    """
    headers = {"User-Agent": USER_AGENT}
    if referrer is not None:
        headers["Referer"] = referrer
    response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    extension = MIME_EXTENSIONS.get(content_type)
    if extension is None:
        url_suffix = Path(url.split("?", 1)[0].split("#", 1)[0]).suffix.lower()
        if url_suffix not in IMAGE_EXTENSIONS:
            raise NotAnImageError(f"{url} did not answer an image ({content_type or 'no content type'})")
        extension = url_suffix
    return AcquiredImage(data=response.content, extension=extension)
