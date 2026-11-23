"""Tests for the Fab scraper (#701), from the listings and formats the #686 spike read, trimmed to what it reads
(``fab_samples/``: no prices, ratings or account state)."""

# one scraper's mapping, a region per field: split in two, a field's cases would no longer be read in one place, so
# the module-length cap is lifted here, as it is for the model's tests
# pylint: disable=too-many-lines

import json
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Final, cast
from unittest.mock import Mock

from pytest import LogCaptureFixture, mark, param, raises
from rehuco_agent.scraping.protocols import (
    FetchError,
    FetchingScraper,
    LoginRequiredError,
    PageFetcher,
    PageGoneError,
    RefetchRequestedError,
)
from rehuco_agent.scraping.registry import BUILTIN_SCRAPERS
from rehuco_agent.scraping.results import Page, ScrapeResult
from rehuco_agent.scraping.sites.fab import Fab
from requests import HTTPError, RequestException, Response

SAMPLES: Final = Path(__file__).parent / "fab_samples"

SITE: Final = "https://www.fab.com"


def sample(name: str) -> dict[str, Any]:
    """One of the trimmed Fab samples.

    :param name: its file's stem.
    :returns: its JSON.
    """
    return json.loads((SAMPLES / f"{name}.json").read_text(encoding="utf-8"))


def page_of(url: str, body: object, status: int | None = 200) -> Page:
    """A fetched page holding JSON.

    :param url: where it was fetched.
    :param body: the JSON, or the text itself when a string.
    :param status: its HTTP status.
    :returns: the page.
    """
    return Page(url=url, final_url=url, html=body if isinstance(body, str) else json.dumps(body), status=status)


def listing_url(listing: dict[str, Any]) -> str:
    """The page a listing is dropped from.

    :param listing: the listing's JSON.
    :returns: its ``/listings/<uid>`` page.
    """
    return f"{SITE}/listings/{listing['uid']}"


def fetcher_for(
    listing: dict[str, Any] | Page, formats: Mapping[str, object] | None = None, *, status: int | None = 200
) -> Mock:
    """A fetcher answering a listing's JSON address and the addresses of its formats.

    :param listing: the listing's JSON, or the page its address answers.
    :param formats: each format's code and what its address answers: JSON, a page, or an exception to raise; a code
        missing here answers a 404 page.
    :param status: the status of the listing's page, when given as JSON.
    :returns: the fetcher; its ``fetch`` calls are recorded.
    """
    formats = formats or {}
    base = listing.url if isinstance(listing, Page) else f"{SITE}/i/listings/{listing['uid']}"

    def fetch(url: str) -> Page:
        if url == base:
            return listing if isinstance(listing, Page) else page_of(url, listing, status)
        code = url.removeprefix(f"{base}/asset-formats/")
        answer = formats.get(code, Page(url=url, final_url=url, html='{"detail": "Not found."}', status=404))
        if isinstance(answer, Exception):
            raise answer
        return answer if isinstance(answer, Page) else page_of(url, answer)

    fetcher = Mock(spec=PageFetcher)
    fetcher.fetch.side_effect = fetch
    return fetcher


def scrape(listing: dict[str, Any], formats: Mapping[str, object] | None = None) -> ScrapeResult:
    """Scrape a listing dropped by its page.

    :param listing: the listing's JSON.
    :param formats: what each format's address answers.
    :returns: the result.
    """
    return Fab().scrape_url(listing_url(listing), fetcher_for(listing, formats))


# region Matching


@mark.parametrize(
    "url",
    [
        param(f"{SITE}/listings/e3ad8089-e375-4f0e-8218-b43345c69d3c", id="a listing"),
        param("https://fab.com/listings/e3ad8089-e375-4f0e-8218-b43345c69d3c", id="without www"),
        param(f"{SITE}/listings/E3AD8089-E375-4F0E-8218-B43345C69D3C/", id="upper case, a trailing slash"),
        param(f"{SITE}/fr/listings/e3ad8089-e375-4f0e-8218-b43345c69d3c", id="a locale before the path"),
        param(f"{SITE}/listings/e3ad8089-e375-4f0e-8218-b43345c69d3c?sort_by=x#reviews", id="a query and a fragment"),
    ],
)
def test_a_listing_page_is_matched(url: str) -> None:
    """The page of a listing, in any of the forms a drop can take, is Fab's to scrape (#701).

    **Test steps:**

    * ask whether the scraper claims a listing page of each form
    * verify it does
    """
    assert Fab().matches(url)


@mark.parametrize(
    "url",
    [
        param(f"{SITE}/", id="the home page"),
        param(f"{SITE}/listings", id="the listings index"),
        param(f"{SITE}/listings/not-a-uid", id="a path that is no uid"),
        param(f"{SITE}/sellers/Tennur", id="a seller"),
        param(f"{SITE}/i/listings/e3ad8089-e375-4f0e-8218-b43345c69d3c", id="the JSON address itself"),
        param(f"{SITE}/library/assets/e3ad8089-e375-4f0e-8218-b43345c69d3c", id="a library entry"),
        param("https://example.com/listings/e3ad8089-e375-4f0e-8218-b43345c69d3c", id="another host"),
        param("https://notfab.com/listings/e3ad8089-e375-4f0e-8218-b43345c69d3c", id="a host ending in fab.com"),
    ],
)
def test_another_page_is_not_matched(url: str) -> None:
    """Only a listing's page is claimed, not another page of Fab nor another site's (#701).

    **Test steps:**

    * ask whether the scraper claims each URL
    * verify it does not
    """
    assert not Fab().matches(url)


def test_the_fab_scraper_is_built_in_and_downloads_for_itself() -> None:
    """It ships with the app, and is a scraper that is handed a fetcher, not a page (#701).

    **Test steps:**

    * look for it among the built-in scrapers and build one
    * verify it is there, and that it satisfies the protocol of a scraper that downloads for itself
    """
    assert Fab in BUILTIN_SCRAPERS
    assert isinstance(Fab(), FetchingScraper)
    assert (Fab.label, Fab.publisher, Fab.site_name, Fab.site_url, Fab.needs_browser) == (
        "Fab",
        "Fab",
        "Fab",
        SITE,
        False,
    )


# endregion

# region What a listing says


def test_a_listing_with_two_license_tiers_and_an_unreal_format() -> None:
    """The first sample, a Standard License listing in Unreal's format: its facts, the engine versions and platforms
    of the format, no size (the format has no files), no license (two tiers) and no counts (#701).

    **Test steps:**

    * scrape the standard listing with its Unreal format's JSON
    * verify each field the listing states, the tags with the labels and platforms, the engine range, and the images
    * verify no license, size or count is written, and the description is Markdown
    """
    listing = sample("listing-standard")

    result = scrape(listing, {"unreal-engine": sample("asset-format-unreal-engine")})

    assert result.fields == {
        "url": f"{SITE}/listings/e3ad8089-e375-4f0e-8218-b43345c69d3c",
        "site_id": "e3ad8089-e375-4f0e-8218-b43345c69d3c",
        "title": "Conference / Meeting Room Environment ( Conference Meeting Room )",
        "authors": [{"name": "Tennur", "url": "https://www.fab.com/sellers/Tennur"}],
        "released": "2024-07-26",
        "source_updated": "2025-09-08",
        "kind": "model",
        "formats": ["uasset"],
        "compatibility": {"unreal": "5.0-5.5"},
        "advertised_tags": [
            "Interior",
            "Level",
            "Conference",
            "Meeting",
            "Studio",
            "Virtual",
            "ai-forbidden",
            "platform-windows",
            "platform-win32",
            "platform-mac",
        ],
    }
    assert result.description is not None
    assert result.description.startswith("[HERE, YOU CAN CHECK A NEW ASSET PLATFORM")
    assert [image.slot for image in result.images] == [0, 1, 2]
    assert all(image.referrer == f"{SITE}/listings/e3ad8089-e375-4f0e-8218-b43345c69d3c" for image in result.images)


def test_a_creative_commons_listing_gives_its_license_formats_and_the_lead_format_s_size() -> None:
    """The second sample: one CC-BY license, three formats; the size is the lead format's files, the counts are the
    ranges of every format that states one (#701).

    **Test steps:**

    * scrape the CC-BY listing, its formats answering the samples' size and ranges (blender), none (fbx), no files (obj)
    * verify the license pair, the formats' extensions in order, and the size of the first format's files only
    * verify the counts, each a single value written as one
    """
    listing = sample("listing-cc-by")
    glb = sample("asset-format-glb-with-size")
    other = {"files": [{"name": "a.zip", "size": 5}], "techDetails": {}, "versions": []}

    result = scrape(listing, {"blender": glb, "fbx": other, "obj": {"files": [], "techDetails": {}}})

    assert result.fields["license"] == "cc-by-4.0"
    assert result.fields["license_url"] == "https://creativecommons.org/licenses/by/4.0/"
    assert result.fields["formats"] == ["blend", "fbx", "obj"]
    assert result.fields["advertised_size"] == 12_096_296
    assert result.fields["advertised_triangles"] == "12"
    assert result.fields["advertised_texture_size"] == "1024"
    assert "compatibility" not in result.fields
    assert result.fields["kind"] == "model"
    assert result.fields["released"] == "2025-11-27"
    assert result.fields["authors"] == [{"name": "Hawtor Studio", "url": "https://www.fab.com/sellers/Hawtor%20Studio"}]


@mark.parametrize(
    ("name", "kind", "license_fields"),
    [
        param("listing-plugin", "plugin", {}, id="a plugin, two tiers"),
        param(
            "listing-ue-marketplace",
            "template",
            {"license": "fab-ue-only"},
            id="a Marketplace tutorial, limited to Unreal, with no terms page",
        ),
    ],
)
def test_the_listing_type_gives_the_kind_and_the_license_gives_its_id(
    name: str, kind: str, license_fields: dict[str, str]
) -> None:
    """The remaining samples: a type to a kind, and a single legacy license to its restriction without a URL (#701).

    **Test steps:**

    * scrape the listing with no formats answering
    * verify its kind and its license fields
    """
    result = scrape(sample(name))

    assert result.fields["kind"] == kind
    assert {key: value for key, value in result.fields.items() if key.startswith("license")} == license_fields


@mark.parametrize(
    ("changes", "expected"),
    [
        param({"listingType": "3d-model"}, "model", id="a model"),
        param({"listingType": "decal"}, "decal", id="a decal"),
        param({"listingType": "never-heard-of"}, "unknown", id="a type Fab did not name here"),
        param({"listingType": None}, "unknown", id="no type"),
        param(
            {"assetFormats": [{"assetFormatType": {"code": "fbx", "extensions": ["fbx"]}, "containsPack": True}]},
            "pack",
            id="a model whose format holds a pack",
        ),
        param(
            {
                "listingType": "decal",
                "assetFormats": [{"assetFormatType": {"code": "fbx", "extensions": ["fbx"]}, "containsPack": True}],
            },
            "decal",
            id="a pack of decals stays a decal",
        ),
    ],
)
def test_the_kind_follows_the_listing_type(changes: dict[str, Any], expected: str) -> None:
    """A listing's type is mapped to a kind, a pack of models is a pack, and a type unnamed is ``unknown``, the
    one field of the block never left empty (#701).

    **Test steps:**

    * scrape the CC-BY listing with its type and formats changed
    * verify the kind
    """
    listing = {**sample("listing-cc-by"), **changes}

    assert scrape(listing).fields["kind"] == expected


@mark.parametrize(
    ("licenses", "expected"),
    [
        param(
            [{"group": "standard", "slug": "personal"}],
            {"license": "fab-standard", "license_url": f"{SITE}/eula"},
            id="one tier",
        ),
        param(
            [{"group": "standard", "slug": "personal"}, {"group": "standard", "slug": "professional"}],
            {},
            id="two tiers",
        ),
        param(
            [{"group": "standard", "slug": "uefn-reference-only"}],
            {"license": "fab-uefn-reference-only", "license_url": f"{SITE}/eula"},
            id="the reference-only tier, a restriction with an id of its own",
        ),
        param([{"group": "cc", "slug": "cc0"}], {}, id="a license without an id here"),
        param([], {}, id="none"),
    ],
)
def test_a_license_is_written_only_when_the_listing_offers_one_the_scraper_knows(
    licenses: list[dict[str, str]], expected: dict[str, str]
) -> None:
    """Several tiers, an unknown pair and no license each leave the pair out; the library, which knows the owned tier,
    fills it (#701).

    **Test steps:**

    * scrape the CC-BY listing with its licenses replaced
    * verify the license fields written
    """
    listing = {**sample("listing-cc-by"), "licenses": licenses}

    result = scrape(listing)

    assert {key: value for key, value in result.fields.items() if key.startswith("license")} == expected


@mark.parametrize(
    ("flags", "labels"),
    [
        param({"isMature": True}, ["rating-mature"], id="mature"),
        param({"isAiGenerated": True}, ["ai-generated"], id="created with AI"),
        param(
            {"isMature": True, "isAiForbidden": True, "isAiGenerated": True},
            ["rating-mature", "ai-forbidden", "ai-generated"],
            id="all",
        ),
        param({"isMature": False, "isAiForbidden": False}, [], id="none"),
    ],
)
def test_the_store_s_labels_are_prefixed_tags_after_the_advertised_ones(
    flags: dict[str, bool], labels: list[str]
) -> None:
    """Fab's marks come as prefixed tags, in a fixed order, after the category and the listing's own tags (#701).

    **Test steps:**

    * scrape the CC-BY listing with its marks set
    * verify the tags are the category and tags, then the labels set
    """
    listing = {**sample("listing-cc-by"), "isMature": False, "isAiForbidden": False, "isAiGenerated": False, **flags}
    names = ["Humans", *(tag["name"] for tag in listing["tags"])]

    assert scrape(listing).fields["advertised_tags"] == [*names, *labels]


def test_two_formats_with_one_extension_list_it_once() -> None:
    """The ``formats`` field is the set of file formats, so two formats whose first extension is the same name it
    once (#701).

    **Test steps:**

    * scrape a listing whose formats are two with the extension ``fbx`` and one without any
    * verify ``fbx`` is listed once and the format with no extension adds nothing
    """
    kind = {"code": "x", "extensions": ["fbx", "other"]}
    listing = {
        **sample("listing-cc-by"),
        "assetFormats": [
            {"assetFormatType": kind},
            {"assetFormatType": {"code": "y", "extensions": ["fbx"]}},
            {"assetFormatType": {"code": "z", "extensions": []}},
        ],
    }

    assert scrape(listing).fields["formats"] == ["fbx"]


def test_an_archive_is_not_a_file_format() -> None:
    """Fab's *Texture Set* format states only ``zip``, a container that says nothing of what is delivered, so it
    gives no format; a format naming an archive first gives the extension after it (#701).

    **Test steps:**

    * scrape a listing whose formats state ``zip`` alone, ``ZIP`` then ``fbx``, and ``zip`` alone again
    * verify ``fbx`` is the only format
    * scrape a listing whose only format states ``zip``, and verify no ``formats`` is written
    """
    archive = {"assetFormatType": {"code": "texture-set", "extensions": ["zip"]}}
    mixed = {"assetFormatType": {"code": "x", "extensions": ["ZIP", "fbx"]}}
    other = {"assetFormatType": {"code": "additional-files", "extensions": ["zip"]}}

    several = scrape({**sample("listing-cc-by"), "assetFormats": [archive, mixed, other]})
    alone = scrape({**sample("listing-cc-by"), "assetFormats": [archive]})

    assert several.fields["formats"] == ["fbx"]
    assert "formats" not in alone.fields


def test_a_tag_is_listed_once_whatever_its_case() -> None:
    """The category's name repeated among the tags, or a platform listed twice by two versions, is one tag (#701).

    **Test steps:**

    * scrape a listing whose category is also a tag in another case, with two versions on the same platforms
    * verify each tag once, the first spelling kept, and blank names dropped
    """
    listing = {
        **sample("listing-cc-by"),
        "category": {"name": "Humans"},
        "tags": [{"name": "humans"}, {"name": "  "}, {"name": "Armor"}, {}],
    }
    versions = {
        "versions": [
            {"engineVersions": [], "targetPlatforms": ["Mac"]},
            {"engineVersions": [], "targetPlatforms": ["Mac"]},
        ]
    }

    assert scrape(listing, {"blender": versions}).fields["advertised_tags"] == ["Humans", "Armor", "platform-mac"]


def test_a_platform_s_name_is_slugged_into_its_tag() -> None:
    """Fab's platform names carry spaces and slashes, which would split a tag on the search line: they become words
    joined by the block's ``-``, and a name with nothing in it is no tag (#701).

    **Test steps:**

    * scrape a listing whose Unreal format names Fab's own spellings, and some that are no name
    * verify the platform tags
    """
    names: list[object] = ["Xbox One", "SteamVR / HTC Vive", "Nintendo Switch", "Win32", " / ", "", 7]
    entry = {"versions": [{"engineVersions": [], "targetPlatforms": names}]}

    tags = cast(list[str], scrape(sample("listing-standard"), {"unreal-engine": entry}).fields["advertised_tags"])

    assert [tag for tag in tags if tag.startswith("platform-")] == [
        "platform-xbox-one",
        "platform-steamvr-htc-vive",
        "platform-nintendo-switch",
        "platform-win32",
    ]


def test_a_listing_with_nothing_to_say_still_gives_its_identity() -> None:
    """A listing stating only its uid yields its page and id, a kind of ``unknown`` and nothing else (#701).

    **Test steps:**

    * scrape a listing of a uid and nothing more
    * verify the fields, and no description, tags or images
    """
    result = scrape({"uid": "e3ad8089-e375-4f0e-8218-b43345c69d3c"})

    assert result.fields == {
        "url": f"{SITE}/listings/e3ad8089-e375-4f0e-8218-b43345c69d3c",
        "site_id": "e3ad8089-e375-4f0e-8218-b43345c69d3c",
        "kind": "unknown",
    }
    assert result.description is None
    assert not result.images


@mark.parametrize(
    "sample_name",
    ["listing-standard", "listing-cc-by", "listing-plugin", "listing-ue-marketplace"],
)
def test_what_every_sample_gives_passes_the_scrape_schema(sample_name: str) -> None:
    """A drop validates the result, so nothing the scraper writes may be a field or a value the schema refuses (#701).

    **Test steps:**

    * scrape each sample with its formats answering what they can
    * validate the result as a drop does
    * verify it is accepted unchanged
    """
    listing = sample(sample_name)
    formats = {
        entry["assetFormatType"]["code"]: sample("asset-format-glb-with-size") for entry in listing["assetFormats"]
    }
    formats["unreal-engine"] = sample("asset-format-unreal-engine")

    result = scrape(listing, formats)

    assert ScrapeResult.coerce(result).fields == result.fields


# endregion

# region The counts


def test_counts_across_formats_are_joined_in_order_without_repeats() -> None:
    """Triangles and texture sides stated by several formats are one range: a value alone, a band with a dash, values
    apart with commas, ascending (#701).

    **Test steps:**

    * scrape a three-format listing whose formats state different ranges, one of them twice
    * verify the two counts' text
    """
    ranges = {
        "blender": {"lower": 2048, "upper": 2049, "bounds": "[)"},
        "fbx": {"lower": 1024, "upper": 1025, "bounds": "[)"},
        "obj": {"lower": 1024, "upper": 1025, "bounds": "[)"},
    }
    formats = {
        code: {
            "files": [],
            "techDetails": {
                "threeDModel": {
                    "totalTrianglesCountRange": {"lower": 1000, "upper": 5000},
                    "textureResolutionRange": span,
                }
            },
        }
        for code, span in ranges.items()
    }

    fields = scrape(sample("listing-cc-by"), formats).fields

    assert fields["advertised_texture_size"] == "1024,2048"
    assert fields["advertised_triangles"] == "1000-4999"


@mark.parametrize(
    "stated",
    [
        param(None, id="none"),
        param("12", id="text"),
        param({"lower": None, "upper": 13}, id="no lower end"),
        param({"lower": 12, "upper": None}, id="no upper end"),
        param({"lower": "12", "upper": 13}, id="text ends"),
        param({"lower": True, "upper": 13}, id="a boolean end"),
        param({"lower": 12, "upper": 12}, id="an empty half-open range"),
        param({"lower": 12, "upper": 13, "bounds": "{}"}, id="odd bounds"),
        param({"lower": 12, "upper": 13, "bounds": 5}, id="bounds of no kind"),
    ],
)
def test_a_range_that_holds_nothing_leaves_the_count_out(stated: object) -> None:
    """A range with an end missing, an end that is no number, nothing inside it or unreadable bounds states no count,
    so the field is left out rather than guessed; bounds that are not text read as Fab's usual half-open pair (#701).

    **Test steps:**

    * scrape a listing whose format states such a range for its triangles
    * verify no triangle count is written (but a range of text bounds of the wrong kind reads as half-open)
    """
    entry = {"files": [], "techDetails": {"threeDModel": {"totalTrianglesCountRange": stated}}}

    fields = scrape(sample("listing-cc-by"), {"blender": entry}).fields

    if isinstance(stated, dict) and stated.get("bounds") == 5:
        assert fields["advertised_triangles"] == "12"
    else:
        assert "advertised_triangles" not in fields


@mark.parametrize(
    ("versions", "expected"),
    [
        param([["UE_5.0"], ["UE_5.5"]], "5.0-5.5", id="a range"),
        param([["UE_5.5"]], "5.5", id="one version"),
        param([["UE_5.10", "UE_5.2"]], "5.2-5.10", id="compared as numbers, not text"),
        param([["UE_4.27"], ["UE_5.1"]], "4.27-5.1", id="across a major"),
        param([["UE_5.2"], ["UE_5.2"]], "5.2", id="the same twice"),
        param([["Latest"], []], None, id="none that reads"),
    ],
)
def test_the_engine_versions_become_the_range_they_cover(versions: list[list[str]], expected: str | None) -> None:
    """Unreal Engine versions across a listing's formats are written as the range from the oldest to the newest,
    compared as numbers (#701).

    **Test steps:**

    * scrape a listing whose Unreal format states those versions
    * verify the compatibility written, or none when no version reads
    """
    entry = {"versions": [{"engineVersions": names, "targetPlatforms": []} for names in versions]}

    fields = scrape(sample("listing-standard"), {"unreal-engine": entry}).fields

    assert fields.get("compatibility") == ({"unreal": expected} if expected else None)


@mark.parametrize(
    ("files", "expected"),
    [
        param([{"size": 100}, {"size": 25}], 125, id="the files add up"),
        param([{"size": 0}], 0, id="an empty file is zero, stated"),
        param([], None, id="no files"),
        param([{"size": 100}, {"size": None}], None, id="a size missing"),
        param([{"size": "5 MB"}], None, id="a size as text"),
        param([{"size": True}], None, id="a boolean size"),
        param([{"size": -3}], None, id="a negative size"),
    ],
)
def test_the_size_is_the_lead_format_s_files_when_every_one_states_a_size(
    files: list[dict[str, object]], expected: int | None
) -> None:
    """The size is the sum of the lead format's files, and absent unless every file states one: never a guess (#701).

    **Test steps:**

    * scrape a listing whose lead format has those files
    * verify the size written, or none
    """
    result = scrape(sample("listing-cc-by"), {"blender": {"files": files}})

    assert result.fields.get("advertised_size") == expected


# endregion

# region The pictures


def test_the_gallery_gives_the_pictures_in_its_order_without_repeats_and_not_the_thumbnail() -> None:
    """The pictures are the gallery's images by position, the thumbnail left out; a picture listed twice, a video
    and an entry with no address are skipped (#701).

    **Test steps:**

    * scrape a listing whose gallery is out of order, repeats a picture and holds a video, an entry with no
      address and one with no position, and whose thumbnail is a file of its own
    * verify the addresses by slot
    """
    listing = {
        **sample("listing-cc-by"),
        "thumbnails": [{"mediaUrl": "https://m/t.png"}, {"mediaUrl": "https://m/second-thumb.png"}],
        "medias": [
            {"type": "image", "position": 2, "mediaUrl": "https://m/c.jpg"},
            {"type": "video", "position": 1, "mediaUrl": "https://m/v.mp4"},
            {"type": "image", "position": 0, "mediaUrl": "https://m/a.jpg"},
            {"type": "image", "position": 1, "mediaUrl": "https://m/a.jpg"},
            {"type": "image", "position": 3},
            {"type": "image", "mediaUrl": "https://m/no-position.jpg"},
        ],
    }

    images = scrape(listing).images

    assert [(image.slot, image.url) for image in images] == [
        (0, "https://m/a.jpg"),
        (1, "https://m/c.jpg"),
        (2, "https://m/no-position.jpg"),
    ]


def test_the_thumbnail_is_the_picture_only_when_the_gallery_has_none() -> None:
    """A listing whose gallery holds no image falls back on its first thumbnail (#701).

    **Test steps:**

    * scrape a listing with two thumbnails and a gallery of one video
    * verify the first thumbnail is the only picture, in slot 0
    """
    listing = {
        **sample("listing-cc-by"),
        "thumbnails": [{"mediaUrl": "https://m/t.png"}, {"mediaUrl": "https://m/second-thumb.png"}],
        "medias": [{"type": "video", "position": 0, "mediaUrl": "https://m/v.mp4"}],
    }

    images = scrape(listing).images

    assert [(image.slot, image.url) for image in images] == [(0, "https://m/t.png")]


def test_no_more_than_a_hundred_pictures_are_taken() -> None:
    """Slots end at ninety-nine ([[data-model#image-meanings]]) (#701).

    **Test steps:**

    * scrape a listing of 120 gallery images
    * verify 100 images, the last in slot 99
    """
    listing = {
        **sample("listing-cc-by"),
        "thumbnails": [],
        "medias": [{"type": "image", "position": n, "mediaUrl": f"https://m/{n}.jpg"} for n in range(120)],
    }

    images = scrape(listing).images

    assert (len(images), images[-1].slot) == (100, 99)


# endregion

# region What is not there, or no longer


@mark.parametrize(
    "answer",
    [
        param(HTTPError(response=Mock(spec=Response, status_code=404)), id="the fetcher raises for a 404"),
        param(
            Page(url="u", final_url="u", html='{"detail": "Not found."}', status=404), id="the browser reports a 404"
        ),
    ],
)
def test_a_listing_that_answers_404_is_no_longer_public(answer: object) -> None:
    """A delisted listing, however the fetcher reports its 404, fails the drop with a sentence naming the listing
    page; writing it from the library is #684's (#701).

    **Test steps:**

    * scrape a listing whose JSON address answers 404, as an error and as a page
    * verify `PageGoneError` says the listing is no longer public, naming its page
    """
    uid = "e3ad8089-e375-4f0e-8218-b43345c69d3c"
    fetcher = Mock(spec=PageFetcher)
    fetcher.fetch.side_effect = answer if isinstance(answer, Exception) else lambda url: answer

    with raises(PageGoneError, match=f"^This Fab listing is no longer public: {SITE}/listings/{uid}$"):
        Fab().scrape_url(f"{SITE}/listings/{uid}", fetcher)


def test_the_delisted_sample_is_a_gone_listing_even_with_a_200() -> None:
    """The body Fab sends for a delisted listing is the spike's sample: not a listing, so it is refused as one (#701).

    **Test steps:**

    * scrape the delisted sample served with status 200
    * verify the scrape fails as an unreadable listing
    """
    body = (SAMPLES / "listing-delisted-404.json").read_text(encoding="utf-8")
    uid = "e3ad8089-e375-4f0e-8218-b43345c69d3c"
    fetcher = fetcher_for(page_of(f"{SITE}/i/listings/{uid}", body))

    with raises(FetchError, match="not a listing"):
        Fab().scrape_url(f"{SITE}/listings/{uid}", fetcher)


def test_another_http_error_is_not_taken_for_a_gone_listing() -> None:
    """Only a 404 is a gone listing: any other HTTP error, or one with no response, is the caller's to report as a
    failed fetch (#701).

    **Test steps:**

    * scrape with a fetcher raising an HTTP error of 500, and one with no response
    * verify each propagates unchanged
    """
    uid = "e3ad8089-e375-4f0e-8218-b43345c69d3c"
    for error in (HTTPError(response=Mock(spec=Response, status_code=500)), HTTPError("no response")):
        fetcher = Mock(spec=PageFetcher)
        fetcher.fetch.side_effect = error

        with raises(HTTPError) as caught:
            Fab().scrape_url(f"{SITE}/listings/{uid}", fetcher)

        assert caught.value is error


@mark.parametrize("status", [param(429, id="rate limited"), param(503, id="unavailable")])
def test_a_refusal_for_the_moment_asks_to_try_again(status: int) -> None:
    """A rate limit or a server error on the listing is a re-fetch request, not a failure (#701).

    **Test steps:**

    * scrape a listing whose address answers 429 or 503
    * verify the scraper asks for a re-fetch, saying what Fab answered
    """
    listing = sample("listing-cc-by")

    with raises(RefetchRequestedError, match=f"Fab answered {status}"):
        Fab().scrape_url(listing_url(listing), fetcher_for(listing, status=status))


@mark.parametrize(
    "body",
    [
        param("<html>a challenge page</html>", id="markup"),
        param("[1, 2]", id="a list"),
        param('{"title": "no uid"}', id="no uid"),
        param('{"uid": 7}', id="a uid that is no text"),
        param("", id="nothing"),
    ],
)
def test_a_body_that_is_not_a_listing_fails_the_fetch(body: str) -> None:
    """Markup, a list or an object with no uid is not a listing, and says so instead of yielding an empty record (#701).

    **Test steps:**

    * scrape with a listing address answering each body
    * verify a `FetchError` naming the listing's page
    """
    uid = "e3ad8089-e375-4f0e-8218-b43345c69d3c"
    fetcher = fetcher_for(page_of(f"{SITE}/i/listings/{uid}", body))

    with raises(FetchError, match=f"Fab answered with something that is not a listing: {SITE}/listings/{uid}"):
        Fab().scrape_url(f"{SITE}/listings/{uid}", fetcher)


def test_a_page_a_browser_wrapped_the_json_in_is_read_from_its_pre() -> None:
    """Through the persona browser a JSON document may arrive inside a ``<pre>`` (#701).

    **Test steps:**

    * scrape a listing whose JSON arrives as ``<html><body><pre>…</pre></body></html>``
    * verify it reads as the same listing
    """
    listing = sample("listing-cc-by")
    wrapped = f"<html><body><pre>{json.dumps(listing)}</pre></body></html>"
    fetcher = fetcher_for(page_of(f"{SITE}/i/listings/{listing['uid']}", wrapped))

    result = Fab().scrape_url(listing_url(listing), fetcher)

    assert result.fields["title"] == "Dark Knight - Female Character"


def test_a_url_that_is_no_listing_page_fails_before_any_request() -> None:
    """Asked to scrape a URL that is not a listing's page, the scraper makes no request (#701).

    **Test steps:**

    * scrape the home page with a fetcher
    * verify a `FetchError`, and the fetcher untouched
    """
    fetcher = Mock(spec=PageFetcher)

    with raises(FetchError, match="not a listing"):
        Fab().scrape_url(f"{SITE}/", fetcher)

    fetcher.fetch.assert_not_called()


@mark.parametrize(
    "answer",
    [
        param(RequestException("boom"), id="a network error"),
        param(FetchError("no browser"), id="a browser failure"),
        param(LoginRequiredError("403"), id="a refusal"),
        param(Page(url="u", final_url="u", html="<html></html>", status=200), id="a page that is no JSON"),
        param(Page(url="u", final_url="u", html='{"detail": "Server error"}', status=500), id="an error status"),
        param(Page(url="u", final_url="u", html="[1]", status=200), id="JSON that is no object"),
    ],
)
def test_a_format_that_cannot_be_read_costs_only_what_it_would_have_given(
    answer: object, caplog: LogCaptureFixture
) -> None:
    """A failed request for the lead format leaves out the size, its engine versions and counts, and writes everything
    else of the listing; the failure is logged (#701).

    **Test steps:**

    * scrape the CC-BY listing whose lead format fails in each way, the second format answering
    * verify the size is absent, the second format's counts are written, and the failure was logged as a warning
    """
    other = {
        "files": [],
        "techDetails": {"threeDModel": {"totalTrianglesCountRange": {"lower": 7, "upper": 8, "bounds": "[)"}}},
    }

    with caplog.at_level("WARNING"):
        result = scrape(sample("listing-cc-by"), {"blender": answer, "fbx": other})

    assert "advertised_size" not in result.fields
    assert result.fields["advertised_triangles"] == "7"
    assert result.fields["title"] == "Dark Knight - Female Character"
    assert "The blender format of Fab listing 5be9349e-acb1-4a0b-8811-9e999e036755" in caplog.text


def test_scrape_page_reads_a_listing_body_alone() -> None:
    """A body in hand reads as the listing without its formats: no size, versions or counts; a 404 body or a refusal
    raises as a fetched listing's does (#701).

    **Test steps:**

    * read the CC-BY listing's JSON as a page
    * verify its fields, with no format fields
    * read a 404 page and a 503 page
    * verify a gone listing and a re-fetch request
    """
    listing = sample("listing-cc-by")
    url = f"{SITE}/i/listings/{listing['uid']}"

    result = Fab().scrape_page(page_of(url, listing))

    assert result.fields["license"] == "cc-by-4.0"
    assert not {"advertised_size", "advertised_triangles", "compatibility"} & set(result.fields)
    with raises(PageGoneError):
        Fab().scrape_page(page_of(url, {"detail": "Not found."}, 404))
    with raises(RefetchRequestedError):
        Fab().scrape_page(page_of(url, "", 503))


def test_every_format_is_asked_for_by_its_code_once() -> None:
    """The scraper asks for the listing, then each format by its code, and for nothing else (#701).

    **Test steps:**

    * scrape a three-format listing whose formats answer
    * verify the addresses fetched, in order
    """
    listing = sample("listing-cc-by")
    fetcher = fetcher_for(listing, {"blender": {}, "fbx": {}, "obj": {}})

    Fab().scrape_url(listing_url(listing), fetcher)

    base = f"{SITE}/i/listings/{listing['uid']}"
    assert [call.args[0] for call in fetcher.fetch.call_args_list] == [
        base,
        f"{base}/asset-formats/blender",
        f"{base}/asset-formats/fbx",
        f"{base}/asset-formats/obj",
    ]


def test_a_dropped_uid_in_capitals_asks_for_the_lower_case_address() -> None:
    """The uid is the listing's id however the drop wrote it, so a site id and an address are always lower case (#701).

    **Test steps:**

    * scrape a listing dropped by a page whose uid is upper case
    * verify the addresses asked for and the site id are lower case
    """
    listing = {"uid": "e3ad8089-e375-4f0e-8218-b43345c69d3c"}
    fetcher = fetcher_for(listing)

    result = Fab().scrape_url(f"{SITE}/listings/{listing['uid'].upper()}", fetcher)

    fetcher.fetch.assert_called_once_with(f"{SITE}/i/listings/{listing['uid']}")
    assert result.fields["site_id"] == listing["uid"]


def test_dates_that_are_not_iso_times_are_left_out() -> None:
    """``released`` and ``source_updated`` are written only from an ISO 8601 time (#701).

    **Test steps:**

    * scrape a listing whose two dates are text that is no time, and a number
    * verify neither field is written
    """
    listing = {**sample("listing-cc-by"), "firstPublishedAt": "yesterday", "publishedAt": 20250101}

    fields = scrape(listing).fields

    assert not {"released", "source_updated"} & set(fields)


def test_a_seller_with_no_profile_address_is_a_name_alone() -> None:
    """An author is a name and its page where Fab gives an http(s) one, else the name alone, and none when there is no
    name (#701).

    **Test steps:**

    * scrape a listing whose seller has a profile that is no URL, and one with a profile and no name
    * verify the first author is a bare name, and the second listing has no author
    """
    base = sample("listing-cc-by")

    named = scrape({**base, "user": {"sellerName": "Ann", "profileUrl": "ann"}}).fields
    unnamed = scrape({**base, "user": {"profileUrl": "https://www.fab.com/sellers/x"}}).fields

    assert named["authors"] == ["Ann"]
    assert "authors" not in unnamed


# endregion


def test_the_samples_hold_nothing_personal() -> None:
    """The trimmed samples keep nothing of the account that read them: no price, which names its currency, no
    entitlement, no rating or review (#701).

    **Test steps:**

    * read every sample
    * verify none has a key naming a price, a currency, an entitlement, a rating, a review or a wishlist, and
      none states an amount in the persona's currency
    """
    forbidden = ("price", "currency", "entitlement", "rating", "review", "wishlist", "ownership")

    def keys_of(value: object) -> set[str]:
        if isinstance(value, dict):
            return {key.lower() for key in value} | {key for item in value.values() for key in keys_of(item)}
        if isinstance(value, list):
            return {key for item in value for key in keys_of(item)}
        return set()

    for path in SAMPLES.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        assert not [word for word in forbidden if any(word in key for key in keys_of(json.loads(text)))], path.name
        assert not re.search(r"\bRON\b", text), path.name


JsonResponder = Callable[[str], Page]
"""A fetcher's answer to an address."""
