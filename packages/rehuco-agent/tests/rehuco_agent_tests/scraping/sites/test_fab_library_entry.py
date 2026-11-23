"""Tests for what the Fab scraper adds for the library scan (#684): the license a tier names, and an item written from
its library entry alone once its listing has left the store."""

from typing import Any, Final

from pytest import mark, param, raises
from rehuco_agent.scraping.protocols import FetchError
from rehuco_agent.scraping.results import ScrapedImage
from rehuco_agent.scraping.sites.fab import Fab

ENTITLEMENT: Final = "11111111-2222-4333-8444-555555555555"
LISTING: Final = "D3ADC0DE-0000-4000-8000-000000000001"
LIBRARY_LINK: Final = f"https://www.fab.com/library/assets/{ENTITLEMENT}"


def entry(**changes: Any) -> dict[str, Any]:
    """A library entry of a delisted item, as ``/i/library/search`` shapes one.

    :param changes: what to set over the entry's listing.
    :returns: the entry.
    """
    return {
        "uid": ENTITLEMENT,
        "listing": {
            "uid": LISTING,
            "title": "Gone Model",
            "listingType": "3d-model",
            "isActiveInLive": False,
            "isMature": True,
            "publisher": {"sellerName": "Epic Games"},
            "lastUpdatedAt": "2025-06-03T13:40:42.407228+00:00",
            "assetFormats": [
                {
                    "assetFormatType": {"code": "unreal-engine"},
                    "technicalSpecs": {
                        "unrealEngineEngineVersions": ["UE_5.3", "UE_5.0"],
                        "unrealEngineTargetPlatforms": ["Mac", "Xbox One"],
                    },
                },
                {"assetFormatType": {"code": "fbx"}},
            ],
            "thumbnails": [
                {"mediaUrl": "https://media.fab.com/cover.png"},
                {"mediaUrl": "https://media.fab.com/2.png"},
            ],
            **changes,
        },
    }


@mark.parametrize(
    ("group", "slug", "expected"),
    [
        param(
            "standard",
            "personal",
            {"license": "fab-standard", "license_url": "https://www.fab.com/eula"},
            id="Standard",
        ),
        param("legacy", "legacy-uem", {"license": "fab-ue-only"}, id="a license with no terms page"),
        param(
            "cc",
            "cc-by",
            {"license": "cc-by-4.0", "license_url": "https://creativecommons.org/licenses/by/4.0/"},
            id="CC",
        ),
        param("new", "tier", {}, id="a tier this scraper has no id for"),
        param(None, 3, {}, id="what is no text"),
    ],
)
def test_a_tier_names_the_license_fields_of_its_record(group: object, slug: object, expected: dict[str, str]) -> None:
    """The library names the tier an account owns, and the scraper's table gives its id and where its terms are.

    **Test steps:**

    * ask for the license fields of each tier
    * verify the id and, where Fab states terms, their address; nothing for a tier the table lacks
    """
    assert Fab.license_fields(group, slug) == expected


def test_a_library_entry_is_an_item_of_its_own() -> None:
    """What the entry states is written, and what only a listing states is not.

    **Test steps:**

    * read an entry of a delisted 3D model, mature, with two Unreal platforms and engine versions out of order
    * verify the source is the library link, the id the listing's lower-cased, the seller an author, the day of its
      last update, the kind, and the engine versions as a range
    * verify the tags are the prefixed labels only, the description none, and the cover the one picture
    """
    result = Fab.scrape_library_entry(entry())

    assert result.fields == {
        "url": LIBRARY_LINK,
        "site_id": LISTING.lower(),
        "title": "Gone Model",
        "authors": ["Epic Games"],
        "source_updated": "2025-06-03",
        "kind": "model",
        "compatibility": {"unreal": "5.0-5.3"},
        "advertised_tags": ["rating-mature", "platform-mac", "platform-xbox-one"],
    }
    assert result.description is None
    assert result.images == (ScrapedImage(0, "https://media.fab.com/cover.png", LIBRARY_LINK),)


def test_a_bare_library_entry_states_only_what_it_has() -> None:
    """An entry with a listing type Fab's table lacks, and nothing else, is still an item.

    **Test steps:**

    * read an entry whose listing holds a uid, an unlisted type and values of the wrong type
    * verify only the source, the id and the unknown kind are written, with no picture
    """
    bare = {
        "uid": ENTITLEMENT,
        "listing": {
            "uid": LISTING,
            "title": "",
            "listingType": "something-new",
            "publisher": {"sellerName": ""},
            "lastUpdatedAt": "soon",
            "assetFormats": [{"technicalSpecs": {"unrealEngineEngineVersions": "UE_5.0"}}],
            "thumbnails": [{"mediaUrl": ""}],
        },
    }

    result = Fab.scrape_library_entry(bare)

    assert result.fields == {"url": LIBRARY_LINK, "site_id": LISTING.lower(), "kind": "unknown"}
    assert not result.images


def test_a_library_entry_names_a_kind_by_the_same_table_as_a_listing() -> None:
    """A plugin's entry is a plugin, as its listing would say.

    **Test steps:**

    * read an entry of the listing type ``tool-and-plugin``
    * verify its kind is ``plugin``
    """
    assert Fab.scrape_library_entry(entry(listingType="tool-and-plugin")).fields["kind"] == "plugin"


@mark.parametrize(
    "broken",
    [
        param({"uid": ENTITLEMENT, "listing": "nope"}, id="a listing that is no object"),
        param({"uid": ENTITLEMENT, "listing": {"title": "x"}}, id="a listing with no uid"),
        param({"listing": {"uid": LISTING}}, id="an entry with no entitlement"),
    ],
)
def test_an_entry_that_names_no_item_cannot_be_written(broken: dict[str, Any]) -> None:
    """Without the listing's uid and the entitlement's there is nothing to find the item by or to link it to.

    **Test steps:**

    * read each broken entry
    * verify a fetch failure
    """
    with raises(FetchError):
        Fab.scrape_library_entry(broken)
