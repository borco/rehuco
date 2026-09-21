"""Rewrites the image links a scraped description embeds to stem-less placeholders
([[acquisition-tooling#scraper-protocols]]), the tc4 `extract_scaled_images_from_markdown` idea ported
fresh and renamed -- nothing here scales anything.

A scraper that embeds images in its description (a future Domestika one) calls
:func:`rewrite_markdown_images` on its own text; one that only downloads images without mentioning them
(ArtStation, Udemy) never does. Substituting the real `<stem>` back in
(:func:`substitute_image_stem`) is applied downstream, not by anything in this package.
"""

import re
from typing import Final

from .results import ScrapedImage

IMAGE_LINK: Final = re.compile(r"!\[([^\]]*)\]\(\s*(\S+?)(?:\s+\"[^\"]*\")?\s*\)")
"""A Markdown image link: ``![alt](url)`` or ``![alt](url "title")``. Matches the whole link so it can
be replaced in place; the optional title is dropped rather than kept as part of the URL."""

PLACEHOLDER_TEMPLATE: Final = "#image-{slot:02d}"
"""The stem-less placeholder a slot is rewritten to -- an anchor-shaped target that is harmless Markdown
if it is ever shown unsubstituted, and trivially unambiguous to find again."""

PLACEHOLDER_PATTERN: Final = re.compile(r"#image-(\d+)")
"""Matches a placeholder written by :data:`PLACEHOLDER_TEMPLATE`, capturing its slot."""


def rewrite_markdown_images(
    markdown: str, referrer: str | None, first_slot: int = 0
) -> tuple[str, tuple[ScrapedImage, ...]]:
    """Rewrite every image link in ``markdown`` to a stem-less placeholder, in encounter order.

    :param markdown: the scraped description, as Markdown.
    :param referrer: the page to record as every image's download referrer.
    :param first_slot: the slot the first image found takes; lets a scraper reserve lower slots for
        images it downloads without embedding (a cover at ``00``, then the description's own images
        starting at ``01``).
    :returns: the rewritten Markdown, and the images found, in the same order their placeholders appear.
    """
    images: list[ScrapedImage] = []

    def replace(match: re.Match[str]) -> str:
        slot = first_slot + len(images)
        images.append(ScrapedImage(slot=slot, url=match.group(2), referrer=referrer))
        return f"![{match.group(1)}]({PLACEHOLDER_TEMPLATE.format(slot=slot)})"

    rewritten = IMAGE_LINK.sub(replace, markdown)
    return rewritten, tuple(images)


def substitute_image_stem(markdown: str, stem: str) -> str:
    """Turn every stem-less placeholder in ``markdown`` into its real `<stem>NN` name.

    :param markdown: text produced by :func:`rewrite_markdown_images`, or anything containing no
        placeholder at all.
    :param stem: the document's own screenshot stem.
    :returns: ``markdown`` with every ``#image-NN`` replaced by ``<stem>NN``.
    """
    return PLACEHOLDER_PATTERN.sub(lambda match: f"{stem}{int(match.group(1)):02d}", markdown)
