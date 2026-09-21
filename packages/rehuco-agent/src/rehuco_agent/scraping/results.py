"""What a fetch and a scrape hand back ([[acquisition-tooling#scraper-protocols]])."""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Page:
    """One fetched page: what was asked for, where it actually landed, and its markup.

    :param url: the URL that was asked for.
    :param final_url: where the fetch actually landed, after any redirect -- the same as :attr:`url`
        when nothing redirected.
    :param html: the page's markup.
    """

    url: str
    final_url: str
    html: str


@dataclass(frozen=True)
class ScrapedImage:
    """One image a scrape found, not yet downloaded.

    :param slot: the two-digit screenshot slot (``0`` -> ``00``) this image will take, assigned by the
        scraper in encounter order. Stem-less on purpose: the `<stem>` of `<stem>NN`
        ([[data-model#image-meanings]]) is a per-document fact -- the folder name for a directory-scoped
        resource, else the ``.rehu`` file's stem -- that neither a scraper nor a `ScrapeJob` knows;
        whoever applies a result substitutes it.
    :param url: where to download the image from.
    :param referrer: the page to send as the download's referrer, or `None` when the site does not need
        one.
    """

    slot: int
    url: str
    referrer: str | None


@dataclass(frozen=True)
class ScrapeResult:
    """What one scrape found on a page: field values, a description, and images to download.

    :param fields: a plain, unvalidated mapping -- a scraper spells its keys from the plugin field-name
        vocabulary (`rehuco_core.DEFAULT_PLUGIN_REGISTRY.field_names`, e.g. ``"title"``,
        ``"advertised_duration"``) so the spelling lines up, but returns whatever it found on the page
        rather than only what one resource type declares. Picking out what fits the document a result is
        applied to is done where it is applied, not here. A field the scraper could not find is simply
        absent, never a guess.
    :param description: Markdown, with any embedded images already rewritten to the stem-less
        placeholder :func:`~.markdown_images.rewrite_markdown_images` produces, or `None` when the
        scraper found no description.
    :param images: images to download, in the order their slots were assigned. A scraper decides for
        itself whether any of these are also referenced in :attr:`description` -- nothing here requires
        it.
    """

    fields: Mapping[str, object]
    description: str | None
    images: tuple[ScrapedImage, ...]
