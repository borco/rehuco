"""Fab listings (#701): an asset's page read from the JSON the page itself reads
([[acquisition-tooling#scraper-protocols]], [[assets#block]]).

Fab's listing page is a shell; what it shows comes from ``/i/listings/<uid>``, which reads logged out, and a format's
size and engine versions from ``/i/listings/<uid>/asset-formats/<code>`` (#686). So this scraper is a
`~rehuco_agent.scraping.protocols.FetchingScraper`: it is handed the URL dropped and the fetcher, asks for those
addresses itself, and never reads the page. The library scan (#684) reads each of its items through the same mapping,
so an item filed either way reads alike.

**What a listing does not say is left out**, never guessed: a license of several tiers (the account owns some, which
only the library says), a size with no files, a count Fab states no range for. ``acquired`` is the scan's alone.
"""

import json
import logging
import re
from collections.abc import Iterable, Mapping
from typing import Any, Final
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from rehuco_core import ValueRange, ValueSpan
from requests import HTTPError, RequestException

from ..html_markdown import HtmlMarkdown
from ..http_fetcher import HttpPageFetcher
from ..protocols import FetchError, LoginRequiredError, PageFetcher, PageGoneError, RefetchRequestedError
from ..results import Page, ScrapedImage, ScrapeResult

LOG: Final = logging.getLogger(__name__)

HOSTS: Final = frozenset({"fab.com", "www.fab.com"})
"""The hosts a listing is dropped from."""

UID_PATTERN: Final = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
"""A listing's uid, a UUID."""

LISTING_PATH: Final = re.compile(rf"^(?:/[a-z]{{2}}(?:-[A-Za-z]{{2}})?)?/listings/({UID_PATTERN})/?$")
"""A listing page's path, ``/listings/<uid>``, with the locale segment Fab may put before it; the capture is the uid."""

SITE_URL: Final = "https://www.fab.com"
"""Where Fab is; the origin of every address below."""

LISTING_URL: Final = SITE_URL + "/listings/{uid}"
"""A listing's page: the URL its record's source holds, whatever form the drop took."""

LISTING_JSON_URL: Final = SITE_URL + "/i/listings/{uid}"
"""A listing's JSON, public."""

FORMAT_JSON_URL: Final = SITE_URL + "/i/listings/{uid}/asset-formats/{code}"
"""One format of a listing: its files with their sizes, its engine versions and platforms, its technical ranges."""

LIBRARY_ASSET_URL: Final = SITE_URL + "/library/assets/{entitlement}"
"""An owned item's page in the account's library, by its entitlement's uid: where a listing that left the store is
still found (#684)."""

EULA_URL: Final = SITE_URL + "/eula"
"""Where Fab states the Standard License."""

GONE_MESSAGE: Final = "This Fab listing is no longer public: {url}"
"""What a drop of a listing that answers 404 fails with; writing such an item from the library is #684's."""

NOT_A_LISTING_MESSAGE: Final = "Fab answered with something that is not a listing: {url}"
"""What a fetch fails with when an address answers, but not with listing JSON."""

KINDS: Final = {
    "3d-model": "model",
    "decal": "decal",
    "brush": "brush",
    "material": "material",
    "animation": "animation",
    "hdri": "hdri",
    "audio": "audio",
    "vfx": "vfx",
    "tool-and-plugin": "plugin",
    "tutorials-examples": "template",
}
"""Fab's ``listingType`` to an asset ``kind`` ([[assets#kind]]); one not named here is ``unknown``, never
inferred from a title."""

PACK_KIND: Final = "pack"
"""The kind of a 3D model whose formats say they ``containsPack``: many models sold as one item."""

UNKNOWN_KIND: Final = "unknown"
"""What an item no table here classifies is."""

LICENSES: Final = {
    ("standard", "personal"): ("fab-standard", EULA_URL),
    ("standard", "professional"): ("fab-standard", EULA_URL),
    ("standard", "uefn-reference-only"): ("fab-uefn-reference-only", EULA_URL),
    ("cc", "cc-by"): ("cc-by-4.0", "https://creativecommons.org/licenses/by/4.0/"),
    ("legacy", "legacy-uem"): ("fab-ue-only", ""),
}
"""Fab's license ``(group, slug)`` to the record's short id and the URL of its terms ([[assets#licenses]]); the
Marketplace license is limited to Unreal Engine, so it is the ``fab-ue-only`` restriction, with no terms page, and
the Standard License's *UEFN - Reference only* tier is a restriction too, so it has an id of its own. A pair
not here, as a listing of several tiers, is left out: the library names the one that is owned."""

ARCHIVE_EXTENSIONS: Final = frozenset({"zip", "rar", "7z"})
"""Extensions that name a container, not a file format: Fab's *Texture Set* and *Additional files* formats state
only ``zip``, which says nothing of what an item is delivered as, so ``formats`` skips them."""

UNREAL_FORMAT_KEY: Final = "unreal"
"""The ``compatibility`` key an Unreal format's engine versions go under."""

UNREAL_VERSION: Final = re.compile(r"^UE_(\d+)\.(\d+)$")
"""An engine version as Fab states it, ``UE_5.5``; the captures are the major and the minor."""

TAG_MATURE: Final = "rating-mature"
"""The tag of a listing Fab marks mature ([[assets#block]])."""

TAG_AI_FORBIDDEN: Final = "ai-forbidden"
"""The tag of a listing Fab marks *NoAI*."""

TAG_AI_GENERATED: Final = "ai-generated"
"""The tag of a listing Fab marks *CreatedWithAI*."""

TAG_PLATFORM_PREFIX: Final = "platform-"
"""Prefixes each platform an Unreal format is limited to, its name lower-cased and slugged."""

NON_SLUG: Final = re.compile(r"[^a-z0-9]+")
"""What a platform's name loses to become a tag: Fab's are ``Xbox One`` and ``SteamVR / HTC Vive``, and a space or a
slash would split the tag on the search line, where ``-`` is the block's own separator ([[assets#block]])"""

MAX_IMAGE_SLOT: Final = 99
"""The last screenshot slot ([[data-model#image-meanings]])."""


class Fab:
    """The built-in Fab scraper: proves itself to :class:`~rehuco_agent.scraping.registry.ScraperRegistry` by shape,
    never by importing the protocols.
    """

    label = "Fab"
    publisher = "Fab"
    site_name = "Fab"
    site_url = SITE_URL
    needs_browser = False

    def matches(self, url: str) -> bool:
        """Whether ``url`` is a Fab listing page, ``/listings/<uid>`` on ``fab.com``.

        :param url: the URL a scrape was asked to run against.
        :returns: whether this scraper should run for it.
        """
        return Fab.__uid_of(url) is not None

    def scrape_page(self, page: Page) -> ScrapeResult:
        """Read a page whose body is a listing's JSON, with nothing of its formats: no size, versions or platforms.

        Not what a drop calls (:meth:`scrape_url`, which asks for the formats too); what a body already in hand gives.

        :param page: the page.
        :returns: the listing's fields, description and images.
        :raises FetchError: the body is not listing JSON.
        :raises PageGoneError: the body says the listing is not found.
        :raises RefetchRequestedError: Fab refused for the moment.
        """
        return Fab.__result(Fab.__listing_of(page, page.url), ())

    def scrape_url(self, url: str, fetcher: PageFetcher) -> ScrapeResult:
        """Read a listing from its JSON, and each of its formats from theirs.

        A format whose request fails costs only what it would have given: the rest of the listing is still written.

        :param url: the listing page dropped.
        :param fetcher: what to fetch with.
        :returns: the listing's fields, description and images.
        :raises PageGoneError: the listing answers 404.
        :raises FetchError: the listing's JSON is unreadable.
        :raises RefetchRequestedError: Fab refused for the moment.
        :raises LoginRequiredError: Fab asked for a login.
        """
        uid = Fab.__uid_of(url)
        if uid is None:
            raise FetchError(NOT_A_LISTING_MESSAGE.format(url=url))
        listing_url = LISTING_JSON_URL.format(uid=uid)
        try:
            page = fetcher.fetch(listing_url)
        except HTTPError as error:
            if error.response is not None and error.response.status_code == 404:
                raise PageGoneError(GONE_MESSAGE.format(url=LISTING_URL.format(uid=uid))) from error
            raise
        listing = Fab.__listing_of(page, LISTING_URL.format(uid=uid))
        codes = [
            code for code in (Fab.__format_code(entry) for entry in Fab.__entries(listing, "assetFormats")) if code
        ]
        return Fab.__result(listing, tuple(Fab.__format_of(fetcher, uid, code) for code in codes))

    @staticmethod
    def license_entry(group: object, slug: object) -> dict[str, str] | None:
        """The ``licenses`` entry of one of Fab's license tiers ([[assets#licenses]], #705), which the library scan uses
        for each tier the account owns.

        :param group: the tier's group slug (``standard``).
        :param slug: the tier's own slug (``personal``).
        :returns: ``license`` and, where Fab states terms, ``url``; ``None`` for a tier this scraper has no id for.
        """
        known = LICENSES.get((str(group), str(slug)))
        if known is None:
            return None
        short_id, url = known
        return {"license": short_id, **({"url": url} if url else {})}

    @staticmethod
    def scrape_library_entry(entry: Mapping[str, Any]) -> ScrapeResult:
        """An item written from its library entry alone: one whose listing left the store (#684), so Fab has no page
        to read but the account still owns it.

        What the entry does not say is left out, never guessed: no description, category, tags, formats or size. The
        source is the library link, since the public listing is dead.

        :param entry: one ``/i/library/search`` result, with its ``uid`` the entitlement's and its ``listing``.
        :returns: the item's fields and its cover picture.
        :raises FetchError: the entry names no listing uid or no entitlement.
        """
        listing = entry.get("listing")
        entitlement = entry.get("uid")
        uid = listing.get("uid") if isinstance(listing, dict) else None
        if not isinstance(listing, dict) or not isinstance(uid, str) or not isinstance(entitlement, str):
            raise FetchError(NOT_A_LISTING_MESSAGE.format(url=SITE_URL + "/library"))
        page_url = LIBRARY_ASSET_URL.format(entitlement=entitlement)
        fields: dict[str, Any] = {"url": page_url, "site_id": uid.lower()}
        title = listing.get("title")
        if isinstance(title, str) and title:
            fields["title"] = title
        name = Fab.__dig(listing, "publisher", "sellerName")
        if isinstance(name, str) and name:
            fields["authors"] = [name]
        day = Fab.__day_of(listing.get("lastUpdatedAt"))
        if day is not None:
            fields["source_updated"] = day
        fields["kind"] = KINDS.get(str(listing.get("listingType")), UNKNOWN_KIND)
        versions = Fab.__spec_values(listing, "unrealEngineEngineVersions")
        compatibility = Fab.__engine_range(versions)
        if compatibility:
            fields["compatibility"] = {UNREAL_FORMAT_KEY: compatibility}
        tags = Fab.__label_tags(listing, Fab.__spec_values(listing, "unrealEngineTargetPlatforms"))
        if tags:
            fields["advertised_tags"] = tags
        cover = Fab.__entries(listing, "thumbnails")[:1]
        urls = [media["mediaUrl"] for media in cover if isinstance(media.get("mediaUrl"), str) and media["mediaUrl"]]
        return ScrapeResult(
            fields=fields,
            description=None,
            images=tuple(ScrapedImage(slot, url, page_url) for slot, url in enumerate(urls)),
        )

    @staticmethod
    def __spec_values(listing: Mapping[str, Any], key: str) -> list[object]:
        """What the formats of a library entry's listing state under one technical key, all formats together.

        :param listing: the library entry's listing.
        :param key: the key under each format's ``technicalSpecs``.
        :returns: the values; empty when no format states any.
        """
        values: list[object] = []
        for format_ in Fab.__entries(listing, "assetFormats"):
            stated = Fab.__dig(format_, "technicalSpecs", key)
            if isinstance(stated, list):
                values.extend(stated)
        return values

    @staticmethod
    def __uid_of(url: str) -> str | None:
        """The uid of the listing ``url`` is the page of.

        :param url: any URL.
        :returns: the uid; ``None`` for another host or another kind of page.
        """
        parts = urlsplit(url)
        found = LISTING_PATH.match(parts.path)
        return found.group(1).lower() if parts.hostname in HOSTS and found is not None else None

    @staticmethod
    def __listing_of(page: Page, listing_page: str) -> dict[str, Any]:
        """A listing's JSON from the page that holds it, refusing what is not one.

        :param page: the page fetched from the listing's JSON address.
        :param listing_page: the listing's own page, which a refusal names.
        :returns: the listing.
        :raises PageGoneError: the page is a 404.
        :raises RefetchRequestedError: the page is a transient refusal.
        :raises FetchError: the body is not a listing.
        """
        if page.status == 404:
            raise PageGoneError(GONE_MESSAGE.format(url=listing_page))
        if page.status is not None and HttpPageFetcher.is_transient(page.status):
            raise RefetchRequestedError(f"Fab answered {page.status}")
        data = Fab.__json_of(page)
        if not isinstance(data, dict) or not isinstance(data.get("uid"), str):
            raise FetchError(NOT_A_LISTING_MESSAGE.format(url=listing_page))
        return data

    @staticmethod
    def __json_of(page: Page) -> object:
        """The JSON in a page's body: the body as it is for a plain fetch, or the text of its ``<pre>`` where a
        browser showed the document.

        :param page: the page.
        :returns: the parsed JSON; ``None`` when there is none.
        """
        for text in (page.html, Fab.__pre_text(page.html)):
            try:
                return json.loads(text)
            except ValueError:
                continue
        return None

    @staticmethod
    def __pre_text(html: str) -> str:
        """The text of the first ``<pre>`` of ``html``.

        :param html: markup.
        :returns: the text; empty when there is no ``<pre>``.
        """
        element = BeautifulSoup(html, "html.parser").find("pre")
        return element.get_text() if element is not None else ""

    @staticmethod
    def __format_of(fetcher: PageFetcher, uid: str, code: str) -> dict[str, Any]:
        """One format's JSON; empty where the request fails, which only costs what the format would have given.

        :param fetcher: what to fetch with.
        :param uid: the listing's uid.
        :param code: the format's code.
        :returns: the format's JSON, or an empty mapping.
        """
        url = FORMAT_JSON_URL.format(uid=uid, code=code)
        try:
            page = fetcher.fetch(url)
        except (RequestException, FetchError, LoginRequiredError) as error:
            LOG.warning("The %s format of Fab listing %s could not be read: %s", code, uid, error)
            return {"code": code}
        data = Fab.__json_of(page) if page.status is None or page.status < 400 else None
        if not isinstance(data, dict):
            LOG.warning("The %s format of Fab listing %s answered no JSON (%s).", code, uid, page.status)
            return {"code": code}
        return {**data, "code": code}

    @staticmethod
    def __format_code(entry: Mapping[str, Any]) -> str:
        """The code of one of a listing's formats.

        :param entry: an ``assetFormats`` entry.
        :returns: the code; empty when it states none.
        """
        code = Fab.__dig(entry, "assetFormatType", "code")
        return code if isinstance(code, str) else ""

    @staticmethod
    def __result(listing: Mapping[str, Any], formats: tuple[dict[str, Any], ...]) -> ScrapeResult:
        """What a listing, and the JSON of each of its formats, say.

        :param listing: the listing's JSON.
        :param formats: the JSON of each format asked for, in the listing's order, each with its ``code``.
        :returns: the result.
        """
        uid = str(listing["uid"]).lower()
        page_url = LISTING_URL.format(uid=uid)
        fields: dict[str, Any] = {"url": page_url, "site_id": uid}
        fields.update(Fab.__listing_fields(listing))
        fields.update(Fab.__format_fields(formats))
        tags = Fab.__tags(listing, formats)
        if tags:
            fields["advertised_tags"] = tags
        description = listing.get("description")
        return ScrapeResult(
            fields=fields,
            description=HtmlMarkdown.convert(description) if isinstance(description, str) and description else None,
            images=Fab.__images(listing, page_url),
        )

    @staticmethod
    def __listing_fields(listing: Mapping[str, Any]) -> dict[str, Any]:
        """What the listing alone gives: title, seller, dates, kind, formats, license.

        :param listing: the listing's JSON.
        :returns: the fields it states.
        """
        fields: dict[str, Any] = {}
        title = listing.get("title")
        if isinstance(title, str) and title:
            fields["title"] = title
        name, profile = Fab.__dig(listing, "user", "sellerName"), Fab.__dig(listing, "user", "profileUrl")
        if isinstance(name, str) and name:
            fields["authors"] = [
                {"name": name, "url": profile}
                if isinstance(profile, str) and profile.lower().startswith("http")
                else name
            ]
        for key, source in (("released", "firstPublishedAt"), ("source_updated", "publishedAt")):
            day = Fab.__day_of(listing.get(source))
            if day is not None:
                fields[key] = day
        fields["kind"] = Fab.__kind(listing)
        extensions = Fab.__extensions(listing)
        if extensions:
            fields["formats"] = extensions
        fields.update(Fab.__license(listing))
        return fields

    @staticmethod
    def __day_of(stamp: object) -> str | None:
        """The day of an ISO 8601 time as Fab states it.

        :param stamp: ``2024-07-26T16:25:46.947000Z``.
        :returns: ``2024-07-26``; ``None`` for anything else.
        """
        return stamp[:10] if isinstance(stamp, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}T.*", stamp) else None

    @staticmethod
    def __kind(listing: Mapping[str, Any]) -> str:
        """The asset kind of a listing ([[assets#kind]]).

        :param listing: the listing's JSON.
        :returns: the kind its type maps to; a model holding a pack is a ``pack``; ``unknown`` for a type unlisted.
        """
        kind = KINDS.get(str(listing.get("listingType")), UNKNOWN_KIND)
        holds_pack = any(entry.get("containsPack") is True for entry in Fab.__entries(listing, "assetFormats"))
        return PACK_KIND if kind == "model" and holds_pack else kind

    @staticmethod
    def __extensions(listing: Mapping[str, Any]) -> list[str]:
        """The file format of each of a listing's formats: its first extension that is not an archive's
        (:data:`ARCHIVE_EXTENSIONS`).

        :param listing: the listing's JSON.
        :returns: the extensions, in the listing's order, none twice.
        """
        found: list[str] = []
        for entry in Fab.__entries(listing, "assetFormats"):
            extensions = Fab.__dig(entry, "assetFormatType", "extensions")
            names = extensions if isinstance(extensions, list) else []
            first = next(
                (name for name in names if isinstance(name, str) and name.lower() not in ARCHIVE_EXTENSIONS), None
            )
            if first and first not in found:
                found.append(first)
        return found

    @staticmethod
    def __license(listing: Mapping[str, Any]) -> dict[str, list[dict[str, str]]]:
        """The license a listing offers when it offers one, as the record's one ``licenses`` entry.

        :param listing: the listing's JSON.
        :returns: ``licenses`` of that one entry; empty for several tiers, or for a license this scraper has no id for.
        """
        licenses = Fab.__entries(listing, "licenses")
        entry = Fab.license_entry(licenses[0].get("group"), licenses[0].get("slug")) if len(licenses) == 1 else None
        return {} if entry is None else {"licenses": [entry]}

    @staticmethod
    def __format_fields(formats: tuple[dict[str, Any], ...]) -> dict[str, Any]:
        """What the formats' own JSON gives: the lead format's size, the engine versions, the technical ranges.

        :param formats: the JSON of each format, in the listing's order.
        :returns: the fields they state.
        """
        fields: dict[str, Any] = {}
        stated = [file.get("size") for file in Fab.__entries(formats[0], "files")] if formats else []
        sizes = [size for size in stated if isinstance(size, int) and not isinstance(size, bool) and size >= 0]
        if sizes and len(sizes) == len(stated):
            fields["advertised_size"] = sum(sizes)
        compatibility = Fab.__engine_versions(formats)
        if compatibility:
            fields["compatibility"] = {UNREAL_FORMAT_KEY: compatibility}
        for key, name in (
            ("advertised_triangles", "totalTrianglesCountRange"),
            ("advertised_texture_size", "textureResolutionRange"),
        ):
            spans = (Fab.__span(Fab.__dig(entry, "techDetails", "threeDModel", name)) for entry in formats)
            joined = ValueRange.of(span for span in spans if span is not None)
            if joined is not None:
                fields[key] = str(joined)
        return fields

    @staticmethod
    def __engine_versions(formats: Iterable[Mapping[str, Any]]) -> str:
        """The Unreal Engine versions across a listing's formats, as the range they cover.

        :param formats: the JSON of each format.
        :returns: ``5.0-5.5``, or ``5.5`` for one; empty when none states a version.
        """
        return Fab.__engine_range(
            name
            for entry in formats
            for version in Fab.__entries(entry, "versions")
            for name in version.get("engineVersions") or ()
        )

    @staticmethod
    def __engine_range(names: Iterable[object]) -> str:
        """The range the engine versions named cover, however the JSON that held them was shaped.

        :param names: versions as Fab states them, ``UE_5.5``; anything else is skipped.
        :returns: ``5.0-5.5``, or ``5.5`` for one; empty when none is a version.
        """
        found: set[tuple[int, int]] = set()
        for name in names:
            matched = UNREAL_VERSION.match(str(name))
            if matched is not None:
                found.add((int(matched.group(1)), int(matched.group(2))))
        if not found:
            return ""
        low, high = min(found), max(found)
        text = f"{low[0]}.{low[1]}"
        return text if low == high else f"{text}-{high[0]}.{high[1]}"

    @staticmethod
    def __span(stated: object) -> ValueSpan | None:
        """The whole numbers a range Fab states holds.

        :param stated: ``{"lower": 12, "upper": 13, "bounds": "[)"}``, or anything else.
        :returns: the span; ``None`` when there is no range, it holds nothing, or it holds only zero -- a seller's
            "not stated" (a ZBrush sculpt's ``[0, 1)`` beside its FBX's real band), since no model has zero triangles
            or a zero-pixel texture.
        """
        if not isinstance(stated, dict):
            return None
        lower, upper, bounds = stated.get("lower"), stated.get("upper"), stated.get("bounds", "[)")
        ends = (lower, upper)
        if not all(end is None or (isinstance(end, int) and not isinstance(end, bool)) for end in ends):
            return None
        span = ValueSpan.from_bounds(lower, upper, bounds if isinstance(bounds, str) else "[)")
        return None if span is None or span.upper == 0 else span

    @staticmethod
    def __tags(listing: Mapping[str, Any], formats: tuple[dict[str, Any], ...]) -> list[str]:
        """The tags Fab advertises, and those it states as labels ([[assets#block]]): the category and the listing's
        tags as they are, then the prefixed ones.

        :param listing: the listing's JSON.
        :param formats: the JSON of each format.
        :returns: the tags, none twice by name.
        """
        names: list[str] = [str(Fab.__dig(listing, "category", "name") or "")]
        names.extend(str(tag.get("name") or "") for tag in Fab.__entries(listing, "tags"))
        platforms = [
            platform
            for entry in formats
            for version in Fab.__entries(entry, "versions")
            for platform in version.get("targetPlatforms") or ()
        ]
        return Fab.__distinct([*names, *Fab.__labels(listing, platforms)])

    @staticmethod
    def __label_tags(listing: Mapping[str, Any], platforms: Iterable[object]) -> list[str]:
        """The tags Fab states as labels only, for an item with no listing JSON to read the rest from.

        :param listing: the library entry's listing.
        :param platforms: the platforms its formats are limited to, as Fab spells them.
        :returns: the tags, none twice by name.
        """
        return Fab.__distinct(Fab.__labels(listing, platforms))

    @staticmethod
    def __labels(listing: Mapping[str, Any], platforms: Iterable[object]) -> list[str]:
        """The prefixed tags the flags and platforms of an item give ([[assets#block]]).

        :param listing: a listing's JSON, or a library entry's listing; each states the flags it knows.
        :param platforms: the platforms an Unreal format is limited to.
        :returns: the tags; a flag a shape does not state gives none.
        """
        names: list[str] = []
        for key, tag in (
            ("isMature", TAG_MATURE),
            ("isAiForbidden", TAG_AI_FORBIDDEN),
            ("isAiGenerated", TAG_AI_GENERATED),
        ):
            if listing.get(key) is True:
                names.append(tag)
        for platform in platforms:
            slug = NON_SLUG.sub("-", platform.lower()).strip("-") if isinstance(platform, str) else ""
            if slug:
                names.append(f"{TAG_PLATFORM_PREFIX}{slug}")
        return names

    @staticmethod
    def __distinct(names: Iterable[str]) -> list[str]:
        """Tags with the blank ones dropped and none kept twice by name, the first spelling winning.

        :param names: the tags.
        :returns: the kept ones, in order.
        """
        kept: dict[str, str] = {}
        for name in names:
            if name.strip():
                kept.setdefault(name.casefold(), name.strip())
        return list(kept.values())

    @staticmethod
    def __images(listing: Mapping[str, Any], page_url: str) -> tuple[ScrapedImage, ...]:
        """The listing's pictures: the gallery the page shows, in its order.

        The thumbnail is the cover the store's search cards use, a file of its own the page never shows, so it
        is taken only when the gallery holds no picture.

        :param listing: the listing's JSON.
        :param page_url: the listing's page, sent as the referrer.
        :returns: the images, one per slot, none twice, at most one hundred.
        """
        gallery = sorted(
            (media for media in Fab.__entries(listing, "medias") if media.get("type") == "image"),
            key=lambda media: (not isinstance(media.get("position"), int), media.get("position") or 0),
        )
        urls: list[str] = []
        for media in gallery or Fab.__entries(listing, "thumbnails")[:1]:
            url = media.get("mediaUrl")
            if isinstance(url, str) and url and url not in urls:
                urls.append(url)
        return tuple(ScrapedImage(slot, url, page_url) for slot, url in enumerate(urls[: MAX_IMAGE_SLOT + 1]))

    @staticmethod
    def __entries(source: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
        """The mappings of a list a JSON object holds, skipping anything else in it.

        :param source: the object.
        :param key: the list's key.
        :returns: its mappings; empty when the key is missing or holds no list.
        """
        value = source.get(key)
        return [entry for entry in value if isinstance(entry, dict)] if isinstance(value, list) else []

    @staticmethod
    def __dig(source: object, *keys: str) -> object:
        """A value some objects down, ``None`` if any step is missing or is not an object.

        :param source: the outermost object.
        :param keys: the keys to follow, in order.
        :returns: the value.
        """
        for key in keys:
            if not isinstance(source, dict):
                return None
            source = source.get(key)
        return source
