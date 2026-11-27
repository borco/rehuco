"""Tests for the license a dropped Fab listing gets from what the account owns (#702, [[assets#licenses]]): the state
answer read through the fetcher, and the rule the library scan shares (``fab_samples/state-*.json``, trimmed to what
is read)."""

import json
from pathlib import Path
from typing import Any, Final
from unittest.mock import Mock

from pytest import LogCaptureFixture, mark, param
from rehuco_agent.scraping.protocols import FetchError, LoginRequiredError, PageFetcher
from rehuco_agent.scraping.results import Page
from rehuco_agent.scraping.sites.fab import STATE_URL, Fab, OwnedTier
from requests import ConnectionError as RequestsConnectionError

SAMPLES: Final = Path(__file__).parent / "fab_samples"

SITE: Final = "https://www.fab.com"

LISTING: Final = json.loads((SAMPLES / "listing-standard.json").read_text(encoding="utf-8"))
"""A listing offering two Standard tiers, so the public answer holds no license."""

ONE_TIER_LISTING: Final = json.loads((SAMPLES / "listing-cc-by.json").read_text(encoding="utf-8"))
"""A listing offering only Creative Commons BY, so the public answer holds that one license."""

UID: Final = LISTING["uid"]

LISTING_URL: Final = f"{SITE}/listings/{UID}"

STATE: Final = STATE_URL.format(uid=UID)

TWO_TIERS: Final = [
    {"license": "fab-standard", "url": f"{SITE}/eula"},
    {"license": "fab-uefn-reference-only", "url": f"{SITE}/eula"},
]


def state_sample(name: str) -> dict[str, Any]:
    """One of the trimmed state answers.

    :param name: its file's stem.
    :returns: its JSON.
    """
    return json.loads((SAMPLES / f"{name}.json").read_text(encoding="utf-8"))


def page_of(url: str, body: object, status: int | None = 200) -> Page:
    """A fetched page.

    :param url: where it was fetched.
    :param body: the JSON, or the text itself when a string.
    :param status: its HTTP status.
    :returns: the page.
    """
    return Page(url=url, final_url=url, html=body if isinstance(body, str) else json.dumps(body), status=status)


def fetcher_for(state: object, listing: dict[str, Any] | None = None) -> Mock:
    """A fetcher answering a listing, a 404 for each of its formats, and its state as told.

    :param state: JSON or text the state's address answers, a page, or an exception to raise.
    :param listing: the listing's JSON; the two-tier one when ``None``.
    :returns: the fetcher; its calls are recorded.
    """
    answered: Final = LISTING if listing is None else listing

    def fetch(url: str) -> Page:
        if url == f"{SITE}/i/listings/{answered['uid']}":
            return page_of(url, answered)
        if url == STATE_URL.format(uid=answered["uid"]):
            if isinstance(state, Exception):
                raise state
            return state if isinstance(state, Page) else page_of(url, state)
        return page_of(url, {"detail": "Not found."}, 404)

    fetcher = Mock(spec=PageFetcher)
    fetcher.fetch.side_effect = fetch
    return fetcher


def test_the_listing_alone_offers_no_license() -> None:
    """The listing of two tiers says nothing of which is owned, so a scrape that cannot read the state has none.

    **Test steps:**

    * scrape the listing with a state that answers a login wall
    * verify the result holds no license
    """
    result = Fab().scrape_url(LISTING_URL, fetcher_for(Page(STATE, STATE, "", 401)))

    assert "licenses" not in result.fields


def test_the_owned_tiers_are_the_licenses_broadest_first() -> None:
    """Each tier the account owns is an entry of ``licenses``, in the scan's order.

    **Test steps:**

    * scrape the listing with a state owning its Personal and its UEFN tiers
    * verify the two licenses, each with its terms' address
    * verify the listing was asked for first and the state once
    """
    fetcher = fetcher_for(state_sample("state-owned-two-tiers"))

    result = Fab().scrape_url(LISTING_URL, fetcher)

    assert result.fields["licenses"] == TWO_TIERS
    addresses = [call.args[0] for call in fetcher.fetch.call_args_list]
    assert addresses.count(STATE) == 1
    assert addresses[0] == f"{SITE}/i/listings/{UID}"


def test_the_group_is_the_second_segment_of_the_path() -> None:
    """An ownership entry has no group, so a Creative Commons one is told by its path.

    **Test steps:**

    * scrape the listing with a state owning ``license/cc/cc-by``
    * verify the license is Creative Commons BY with its address
    """
    result = Fab().scrape_url(LISTING_URL, fetcher_for(state_sample("state-owned-cc-by")))

    assert result.fields["licenses"] == [
        {"license": "cc-by-4.0", "url": "https://creativecommons.org/licenses/by/4.0/"}
    ]


def test_the_owned_license_replaces_the_one_the_listing_offers() -> None:
    """A listing of one tier writes that license by itself; what the account owns it under replaces it.

    **Test steps:**

    * scrape a listing offering only Creative Commons BY, with no state: verify that one license
    * scrape it with a state owning it under the Marketplace license
    * verify the one license is the Marketplace's, with no address
    """
    url = f"{SITE}/listings/{ONE_TIER_LISTING['uid']}"
    state = {"acquired": True, "ownership": [{"slug": "legacy-uem", "path": "license/legacy/uem"}]}

    offered = Fab().scrape_listing(url, fetcher_for(state, ONE_TIER_LISTING))
    result = Fab().scrape_url(url, fetcher_for(state, ONE_TIER_LISTING))

    assert offered.fields["licenses"] == [
        {"license": "cc-by-4.0", "url": "https://creativecommons.org/licenses/by/4.0/"}
    ]
    assert result.fields["licenses"] == [{"license": "fab-ue-only"}]


def test_an_entry_that_is_no_tier_is_skipped_and_the_others_kept() -> None:
    """One ownership entry Fab states oddly costs only itself.

    **Test steps:**

    * scrape the listing with a state whose entries lack a slug, hold a slug that is no text, a path of two segments
      and a path that is no text, beside one good entry
    * verify the one license is the good entry's
    """
    state = {
        "acquired": True,
        "ownership": [
            {"path": "license/standard/reference-plus-source"},
            {"slug": 7, "path": "license/standard/reference-plus-source"},
            {"slug": "", "path": "license/standard/reference-plus-source"},
            {"slug": "personal", "path": "license/standard"},
            {"slug": "personal", "path": None},
            {"slug": "cc-by", "path": "license/cc/cc-by"},
        ],
    }

    result = Fab().scrape_url(LISTING_URL, fetcher_for(state))

    assert result.fields["licenses"] == [
        {"license": "cc-by-4.0", "url": "https://creativecommons.org/licenses/by/4.0/"}
    ]


def test_tiers_that_name_no_license_leave_the_offered_one(caplog: LogCaptureFixture) -> None:
    """A tier whose group and slug hold nothing an id can be made of gives no license, so the listing's own stays.

    **Test steps:**

    * scrape a one-tier listing with a state whose only tier is punctuation
    * verify the license is the one the listing offers, and one info line says the owned license was not read
    """
    url = f"{SITE}/listings/{ONE_TIER_LISTING['uid']}"
    state = {"acquired": True, "ownership": [{"slug": "!!!", "path": "license//x"}]}
    caplog.set_level("INFO")

    result = Fab().scrape_url(url, fetcher_for(state, ONE_TIER_LISTING))

    assert result.fields["licenses"] == [
        {"license": "cc-by-4.0", "url": "https://creativecommons.org/licenses/by/4.0/"}
    ]
    lines = [record.getMessage() for record in caplog.records if "owned for Fab listing" in record.getMessage()]
    assert len(lines) == 1
    assert "names no license" in lines[0]


def test_a_tier_fab_has_no_id_for_is_kept_by_its_slug() -> None:
    """A tier the table does not know is a license named by its group and slug, as the scan names it.

    **Test steps:**

    * scrape the listing with a state owning a tier of a group the table lacks
    * verify the license is that group and slug, with no address
    """
    state = {"acquired": True, "ownership": [{"slug": "Fancy One!", "path": "license/new/fancy"}]}

    result = Fab().scrape_url(LISTING_URL, fetcher_for(state))

    assert result.fields["licenses"] == [{"license": "new-fancy-one"}]


@mark.parametrize(
    ("state", "reason"),
    [
        param(LoginRequiredError("Fab asked for a login"), "Fab asked for a login", id="a login wall"),
        param(
            LoginRequiredError("It answered 401, which usually means a login wall."),
            "which usually means a login wall.",
            id="a reason ending in a period, which is not doubled",
        ),
        param(FetchError("no browser"), "no browser", id="a failed fetch"),
        param(RequestsConnectionError("offline"), "offline", id="a failed request"),
        param(Page(STATE, STATE, '{"detail": "no"}', 401), "answered 401", id="a 401 page"),
        param(Page(STATE, STATE, "", 403), "answered 403", id="a 403 page"),
        param(page_of(STATE, "<html>Just a moment...</html>"), "not JSON", id="a challenge page"),
        param(page_of(STATE, ["acquired"]), "not JSON", id="JSON that is no object"),
        param(
            Page(STATE, STATE, '{"detail": "Authentication credentials were not provided."}', None),
            "not a listing's state (Authentication credentials were not provided.)",
            id="a refusal whose status the browser did not report",
        ),
        param({"acquired": False, "ownership": []}, "does not own it", id="an item not acquired"),
        param({"acquired": True, "ownership": []}, "names no license", id="no ownership"),
        param(
            {"acquired": True, "ownership": [{"slug": "personal", "path": "other/standard/personal"}, "x"]},
            "names no license",
            id="entries that are not licenses",
        ),
    ],
)
def test_a_state_that_cannot_be_read_leaves_the_scrape_as_it_was(
    caplog: LogCaptureFixture, state: object, reason: str
) -> None:
    """Whatever stops the owned license being read costs only it: the scrape is the one without the state, and one
    line in the log says why.

    **Test steps:**

    * scrape the listing with each kind of state that cannot be used
    * verify the result equals the one of a listing scraped with no state asked for
    * verify one info line says the owned license was not read, and why
    """
    expected = Fab().scrape_listing(LISTING_URL, fetcher_for(Page(STATE, STATE, "", 404)))
    caplog.set_level("INFO")

    result = Fab().scrape_url(LISTING_URL, fetcher_for(state))

    assert result == expected
    lines = [record.getMessage() for record in caplog.records if "owned for Fab listing" in record.getMessage()]
    assert len(lines) == 1
    assert UID in lines[0]
    assert lines[0].endswith(f"{reason.rstrip('.')}.")


def test_scraping_a_listing_asks_nothing_of_the_account() -> None:
    """The library scan reads each item through :meth:`~rehuco_agent.scraping.sites.fab.Fab.scrape_listing`, which
    never asks for the state, since its entry already says what is owned.

    **Test steps:**

    * scrape a listing through ``scrape_listing``
    * verify the state's address was not fetched
    """
    fetcher = fetcher_for(state_sample("state-owned-two-tiers"))

    result = Fab().scrape_listing(LISTING_URL, fetcher)

    assert STATE not in [call.args[0] for call in fetcher.fetch.call_args_list]
    assert "licenses" not in result.fields


def test_owned_licenses_replace_what_the_fields_held_and_name_each_text() -> None:
    """The rule the scan and the drop share: the broadest first, each id once, the offered license replaced, and the
    path of each text by id.

    **Test steps:**

    * apply tiers out of order, two of one id, to fields that held another license
    * verify the licenses, and the path kept for the id's first tier
    * verify that no tier clears the offered license and names no path
    """
    fields: dict[str, Any] = {"licenses": [{"license": "cc-by-4.0"}], "title": "T"}
    tiers = [
        OwnedTier("standard", "uefn-reference-only", "license/standard/reference-only"),
        OwnedTier("standard", "personal", "license/standard/reference-plus-source"),
        OwnedTier("standard", "professional", "license/standard/professional"),
    ]

    paths = Fab.apply_owned_licenses(fields, tiers)

    assert fields["licenses"] == TWO_TIERS
    assert paths == {
        "fab-standard": "license/standard/professional",
        "fab-uefn-reference-only": "license/standard/reference-only",
    }
    assert not Fab.apply_owned_licenses(fields, [])
    assert fields == {"title": "T"}
