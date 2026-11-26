"""Tests for Fab's library session (#684): the listing and its cursor, an item read through the Fab scraper or from its
library entry, the license an account owns it under, and the text of each license.

The persona is a mock: what a request answers is told by address, as `FabSessionFetcher` would hand it over."""

import base64
import json
from collections.abc import Callable
from typing import Any, Final
from unittest.mock import Mock
from urllib.parse import parse_qs, unquote, urlsplit

import requests
from pytest import LogCaptureFixture, MonkeyPatch, mark, param, raises
from rehuco_agent.scraping.browser_fetcher import PersonaLease
from rehuco_agent.scraping.library_site import (
    LibraryEntry,
    LibrarySession,
    StoreOfflineError,
    StorePausedError,
)
from rehuco_agent.scraping.protocols import FetchError, LoginRequiredError
from rehuco_agent.scraping.results import InvalidScrapeResultError, Page
from rehuco_agent.scraping.sites import fab_library_session, fab_license_texts
from rehuco_agent.scraping.sites.fab_library_session import FabLibrarySession
from rehuco_agent.scraping.sites.fab_license_texts import CC_TEXTS, EULA_JSON_URL
from rehuco_core import LibraryCursor

SITE: Final = "https://www.fab.com"
SEARCH: Final = f"{SITE}/i/library/search"
LISTING_UID: Final = "e3ad8089-e375-4f0e-8218-b43345c69d3c"
ENTITLEMENT: Final = "11111111-2222-4333-8444-555555555555"

PERSONAL: Final = {
    "group": {"slug": "standard", "name": "Standard License", "url": "/eula"},
    "slug": "personal",
    "name": "Personal",
    "path": "license/standard/reference-plus-source",
}
PROFESSIONAL: Final = {
    **PERSONAL,
    "slug": "professional",
    "name": "Professional",
    "path": "license/standard/professional",
}
UEFN: Final = {**PERSONAL, "slug": "uefn-reference-only", "path": "license/standard/reference-only"}
CC_BY: Final = {"group": {"slug": "cc"}, "slug": "cc-by", "path": "license/cc/cc-by"}
MARKETPLACE: Final = {"group": {"slug": "legacy"}, "slug": "legacy-uem", "path": "license/legacy/uem"}
UNKNOWN_TIER: Final = {"group": {"slug": "new"}, "slug": "Fancy One!", "path": "license/new/fancy"}


def result_of(
    *,
    uid: str = LISTING_UID,
    created: object = "2025-01-01T10:00:00.123456+00:00",
    licenses: list[dict[str, Any]] | None = None,
    live: bool = True,
    title: object = "A Listing",
) -> dict[str, Any]:
    """One library result, shaped as ``/i/library/search`` gives it.

    :param uid: the listing's uid.
    :param created: when the account got it.
    :param licenses: the tiers it owns.
    :param live: whether its listing is still public.
    :param title: the listing's title.
    :returns: the result.
    """
    return {
        "uid": ENTITLEMENT,
        "createdAt": created,
        "entitlement": {"licenses": [PERSONAL] if licenses is None else licenses},
        "listing": {
            "uid": uid,
            "title": title,
            "isActiveInLive": live,
            "listingType": "3d-model",
            "publisher": {"sellerName": "Epic Games"},
            "lastUpdatedAt": "2025-06-03T13:40:42.407228+00:00",
            "assetFormats": [
                {
                    "assetFormatType": {"code": "unreal-engine"},
                    "technicalSpecs": {
                        "unrealEngineEngineVersions": ["UE_5.0", "UE_5.3"],
                        "unrealEngineTargetPlatforms": ["Mac"],
                    },
                }
            ],
            "thumbnails": [{"mediaUrl": "https://media.fab.com/cover.png"}],
        },
    }


def json_page(url: str, body: object, status: int = 200) -> Page:
    """A page holding JSON.

    :param url: its address.
    :param body: the JSON.
    :param status: its status.
    :returns: the page.
    """
    return Page(url=url, final_url=url, html=json.dumps(body), status=status)


def session_with(monkeypatch: MonkeyPatch, answer: Callable[[str], Page]) -> tuple[FabLibrarySession, Mock]:
    """A library session whose requests are answered by ``answer``.

    :param monkeypatch: replaces the fetcher the session builds.
    :param answer: the page an address answers.
    :returns: the session and the fetcher, whose calls are recorded.
    """
    fetcher = Mock()
    fetcher.fetch.side_effect = answer
    monkeypatch.setattr(fab_library_session, "FabSessionFetcher", Mock(return_value=fetcher))
    return FabLibrarySession(Mock(spec=PersonaLease)), fetcher


def entry_of(raw: dict[str, Any], url: str | None = None) -> LibraryEntry:
    """The entry the listing makes of a result.

    :param raw: the result.
    :param url: the page to read it from; its listing page when not given.
    :returns: the entry.
    """
    return LibraryEntry(
        site_id=raw["listing"]["uid"],
        acquired="2025-01-01T10:00:00.123456Z",
        title=raw["listing"]["title"],
        url=url or f"{SITE}/listings/{raw['listing']['uid']}",
        payload=raw,
    )


def test_it_is_a_library_session_and_its_own_context(monkeypatch: MonkeyPatch) -> None:
    """The scan opens it with ``with`` and hands it nothing back at the end.

    **Test steps:**

    * open a session as a context manager
    * verify it is the session, and a `LibrarySession` by shape
    """
    session, _ = session_with(monkeypatch, Mock())

    with session as opened:
        assert opened is session
    assert isinstance(session, LibrarySession)


# region The listing


def test_check_asks_the_library_for_nothing(monkeypatch: MonkeyPatch) -> None:
    """A persona that is logged in and not challenged is answered; one that is not fails the same request.

    **Test steps:**

    * check a session whose library answers
    * verify the request counted and listed nothing, sorted by nothing
    * check a session whose request is refused, and verify the refusal is the scan's stop
    """
    session, fetcher = session_with(monkeypatch, lambda url: json_page(url, {"results": []}))
    session.check()
    query = parse_qs(urlsplit(fetcher.fetch.call_args.args[0]).query)
    assert query["count"] == ["0"] and query["source"] == ["acquired"]

    stopped, _ = session_with(monkeypatch, Mock(side_effect=StorePausedError("logged out", SITE)))
    with raises(StorePausedError):
        stopped.check()


@mark.parametrize(
    ("page", "message"),
    [
        param(Page(SEARCH, SEARCH, "{}", 500), "answered 500", id="a status that is not 200"),
        param(Page(SEARCH, SEARCH, "<html>", 200), "not JSON", id="a body that is no JSON"),
        param(Page(SEARCH, SEARCH, "[]", 200), "not a JSON object", id="JSON that is no object"),
    ],
)
def test_an_answer_that_is_not_the_library_is_a_failure(monkeypatch: MonkeyPatch, page: Page, message: str) -> None:
    """What Fab answers that is not a JSON object is reported, never read.

    **Test steps:**

    * check a session whose library answers each wrong way
    * verify a fetch failure naming what was wrong
    """
    session, _ = session_with(monkeypatch, lambda _: page)

    with raises(FetchError, match=message):
        session.check()


def test_the_listing_starts_at_the_first_item_with_no_cursor(monkeypatch: MonkeyPatch) -> None:
    """An empty cursor reads the library from its oldest item, sorted by acquisition.

    **Test steps:**

    * list with an empty cursor
    * verify the request sorts by ``createdAt`` over the acquired items, with no cursor, and the entries come back
    """
    first = result_of()
    session, fetcher = session_with(monkeypatch, lambda url: json_page(url, {"results": [first], "next": None}))

    entries = list(session.listing(LibraryCursor(), Mock()))

    query = parse_qs(urlsplit(fetcher.fetch.call_args.args[0]).query)
    assert query == {"sort_by": ["createdAt"], "source": ["acquired"]}
    assert [(e.site_id, e.title, e.url, e.payload) for e in entries] == [
        (LISTING_UID, "A Listing", f"{SITE}/listings/{LISTING_UID}", first)
    ]


def test_the_listing_resumes_at_the_millisecond_the_records_reach(monkeypatch: MonkeyPatch) -> None:
    """Fab's cursor is built from the time alone, standing before every entry of that millisecond.

    **Test steps:**

    * list from a cursor whose newest time is 2025-01-01T10:00:00.123456Z
    * decode the cursor the request carried
    * verify it is ``v=[<that millisecond>, "<the null id>"]``, URL-quoted as Fab's own
    """
    session, fetcher = session_with(monkeypatch, lambda url: json_page(url, {"results": []}))
    cursor = LibraryCursor("2025-01-01T10:00:00.123456Z", frozenset({"a"}))

    list(session.listing(cursor, Mock()))

    sent = parse_qs(urlsplit(fetcher.fetch.call_args.args[0]).query)["cursor"][0]
    decoded = unquote(base64.b64decode(sent).decode("ascii"))
    assert decoded == 'v=[1735725600123,"00000000-0000-0000-0000-000000000000"]'
    assert base64.b64decode(sent).decode("ascii").startswith("v=%5B1735725600123%2C%22")


def test_a_cursor_that_is_no_time_lists_from_the_start(monkeypatch: MonkeyPatch, caplog: LogCaptureFixture) -> None:
    """A typed-in ``acquired`` long enough to pass for a time must not stop the scan: the library is read whole.

    **Test steps:**

    * list from a cursor whose newest ``acquired`` is text of a time's length that is no time
    * verify the request carries no cursor, and the oddity was warned of
    """
    session, fetcher = session_with(monkeypatch, lambda url: json_page(url, {"results": []}))

    list(session.listing(LibraryCursor("sometime in the spring of 2025", frozenset()), Mock()))

    assert "cursor" not in parse_qs(urlsplit(fetcher.fetch.call_args.args[0]).query)
    assert "is no time" in caplog.text


def test_an_item_that_cannot_be_written_stops_the_scan_by_name(monkeypatch: MonkeyPatch) -> None:
    """What Fab states that the result's schema refuses is reported with the item, never as a traceback.

    **Test steps:**

    * read a live item whose result the schema check refuses
    * verify a fetch failure naming the item and its page
    """
    session, _ = session_with(monkeypatch, live_fetcher(public_listing()))
    monkeypatch.setattr(
        "rehuco_agent.scraping.results.ScrapeResult.coerce",
        Mock(side_effect=InvalidScrapeResultError("data.fields", "bad")),
    )

    with raises(FetchError, match=r"A Listing \(https://www.fab.com/listings/.*cannot be written"):
        session.read_item(entry_of(result_of()))


def test_the_listing_follows_next_and_waits_only_between_pages(monkeypatch: MonkeyPatch) -> None:
    """Each page after the first is asked for from the ``next`` the last one gave, after the scan's paced wait.

    **Test steps:**

    * list a library of two pages and an empty third
    * verify the entries come in page order, ``wait`` ran twice (before the second and the third), and the walk ends
      at a page with no results
    """
    second_url = f"{SEARCH}?cursor=abc&sort_by=createdAt&source=acquired"
    third_url = f"{SEARCH}?cursor=def&sort_by=createdAt&source=acquired"
    pages = {
        0: {"results": [result_of(uid="a" * 8 + LISTING_UID[8:])], "next": second_url},
        1: {"results": [result_of(uid="b" * 8 + LISTING_UID[8:])], "next": third_url},
        2: {"results": [], "next": third_url},
    }
    asked: list[str] = []

    def answer(url: str) -> Page:
        asked.append(url)
        return json_page(url, pages[len(asked) - 1])

    session, _ = session_with(monkeypatch, answer)
    wait = Mock()

    entries = list(session.listing(LibraryCursor(), wait))

    assert [entry.site_id[:1] for entry in entries] == ["a", "b"]
    assert asked[1:] == [second_url, third_url]
    assert wait.call_count == 2


@mark.parametrize(
    "following",
    [
        param("http://www.fab.com/i/library/search?x=1", id="not https"),
        param("https://example.com/i/library/search?x=1", id="another host"),
        param("https://www.fab.com/i/listings/x", id="another endpoint"),
    ],
)
def test_a_next_page_that_is_not_the_listing_is_refused(monkeypatch: MonkeyPatch, following: str) -> None:
    """The listing never goes where its own answer sends it unless that is Fab's listing.

    **Test steps:**

    * list a page whose ``next`` is each wrong address
    * verify a fetch failure naming it, after the page's entries
    """
    session, _ = session_with(monkeypatch, lambda url: json_page(url, {"results": [result_of()], "next": following}))
    entries = session.listing(LibraryCursor(), Mock())

    assert next(entries).site_id == LISTING_UID
    with raises(FetchError, match="goes on elsewhere"):
        next(entries)


def test_the_acquisition_time_is_stored_in_utc(monkeypatch: MonkeyPatch) -> None:
    """The block stores UTC with six fractional digits and a ``Z``, whatever zone or precision Fab states.

    **Test steps:**

    * list results created at +00:00 with microseconds, at +02:00, and with no fraction
    * verify each is UTC, six digits, ``Z``
    """
    results = [
        result_of(created="2025-01-01T10:00:00.123456+00:00"),
        result_of(created="2025-01-01T12:00:00.5+02:00"),
        result_of(created="2025-01-01T10:00:00+00:00"),
    ]
    session, _ = session_with(monkeypatch, lambda url: json_page(url, {"results": results}))

    entries = list(session.listing(LibraryCursor(), Mock()))

    assert [entry.acquired for entry in entries] == [
        "2025-01-01T10:00:00.123456Z",
        "2025-01-01T10:00:00.500000Z",
        "2025-01-01T10:00:00.000000Z",
    ]


def test_an_item_that_left_the_store_is_listed_at_its_library_link(monkeypatch: MonkeyPatch) -> None:
    """A delisted item has no public page, so its entry's address is its place in the account's library.

    **Test steps:**

    * list a result whose listing is not live, and another with no title
    * verify the first's address is the library link by its entitlement, and the second is titled by its uid
    """
    results = [result_of(live=False), result_of(title=None)]
    session, _ = session_with(monkeypatch, lambda url: json_page(url, {"results": results}))

    gone, untitled = list(session.listing(LibraryCursor(), Mock()))

    assert gone.url == f"{SITE}/library/assets/{ENTITLEMENT}"
    assert untitled.title == LISTING_UID


def test_an_entry_that_cannot_be_read_is_left_out_and_logged(
    monkeypatch: MonkeyPatch, caplog: LogCaptureFixture
) -> None:
    """One malformed entry costs itself, never the page.

    **Test steps:**

    * list a page of a good entry between a result that is no object, one with no listing, one with no entitlement,
      one with no time, one with a time that has no zone and one that is no time
    * verify only the good entry comes back, and each of the others was warned of
    """
    bad_time = result_of(created="2025-01-01T10:00:00")
    no_time = result_of(created=None)
    no_listing = {"uid": ENTITLEMENT, "createdAt": "2025-01-01T10:00:00+00:00"}
    no_entitlement = {**result_of(), "uid": None}
    not_a_time = result_of(created="yesterday")
    results = ["nonsense", no_listing, no_entitlement, no_time, bad_time, not_a_time, result_of()]
    session, _ = session_with(monkeypatch, lambda url: json_page(url, {"results": results}))

    entries = list(session.listing(LibraryCursor(), Mock()))

    assert len(entries) == 1
    assert len([record for record in caplog.records if record.levelname == "WARNING"]) == 6


def test_a_page_whose_results_are_no_list_ends_the_walk(monkeypatch: MonkeyPatch) -> None:
    """A page that holds no list of results is the end, whatever else it says.

    **Test steps:**

    * list a page whose ``results`` is an object and whose ``next`` names a page
    * verify nothing comes back and no second page is asked for
    """
    session, fetcher = session_with(
        monkeypatch, lambda url: json_page(url, {"results": {}, "next": f"{SEARCH}?cursor=x"})
    )

    assert not list(session.listing(LibraryCursor(), Mock()))
    assert fetcher.fetch.call_count == 1


# endregion
# region An item


def live_fetcher(listing_json: dict[str, Any]) -> Callable[[str], Page]:
    """What a library answers for one live listing: its JSON, and a 404 for any format.

    :param listing_json: the listing's JSON.
    :returns: the answer by address.
    """

    def answer(url: str) -> Page:
        if url == f"{SITE}/i/listings/{listing_json['uid']}":
            return json_page(url, listing_json)
        return json_page(url, {"detail": "Not found."}, 404)

    return answer


def public_listing(**changes: Any) -> dict[str, Any]:
    """A public listing's JSON, of one Standard tier, with a category and a tag.

    :param changes: what to set over it.
    :returns: the JSON.
    """
    return {
        "uid": LISTING_UID,
        "title": "Public Title",
        "listingType": "3d-model",
        "user": {"sellerName": "Seller"},
        "category": {"name": "Environments"},
        "tags": [{"name": "interior"}],
        "licenses": [{"group": "standard", "slug": "personal"}, {"group": "standard", "slug": "professional"}],
        "assetFormats": [],
        **changes,
    }


def test_a_live_item_is_read_through_the_fab_scraper(monkeypatch: MonkeyPatch) -> None:
    """A listing that is public is read as a dropped URL of it would be.

    **Test steps:**

    * read the item of a live entry whose listing answers
    * verify the page is the listing's, the fields are the scraper's, and the library's own owned tiers were added
    """
    raw = result_of(licenses=[PERSONAL])
    session, _ = session_with(monkeypatch, live_fetcher(public_listing()))

    item = session.read_item(entry_of(raw))

    assert item.page_url == f"{SITE}/listings/{LISTING_UID}"
    assert item.result.fields["title"] == "Public Title"
    assert item.result.fields["licenses"] == [{"license": "fab-standard", "url": f"{SITE}/eula"}]
    assert item.license_paths == {"fab-standard": "license/standard/reference-plus-source"}


def test_a_listing_that_answers_404_is_written_from_its_library_entry(monkeypatch: MonkeyPatch) -> None:
    """A listing that left between the listing and the read is written as a delisted item is.

    **Test steps:**

    * read the item of an entry marked live whose listing answers 404
    * verify the record is the library entry's: its source the library link, and what only a listing says empty
    """
    raw = result_of()
    session, _ = session_with(monkeypatch, lambda url: json_page(url, {"detail": "Not found."}, 404))

    item = session.read_item(entry_of(raw))

    assert item.page_url == f"{SITE}/library/assets/{ENTITLEMENT}"
    assert item.result.description is None
    assert "advertised_tags" in item.result.fields


def test_a_delisted_item_is_never_asked_of_its_listing(monkeypatch: MonkeyPatch) -> None:
    """An entry marked not live is written from the library entry, with no request at all.

    **Test steps:**

    * read the item of a delisted entry
    * verify the fetcher was never called, the page is the library link, and its title and compatibility are the
      entry's
    """
    raw = result_of(live=False)
    session, fetcher = session_with(monkeypatch, Mock())

    item = session.read_item(entry_of(raw, f"{SITE}/library/assets/{ENTITLEMENT}"))

    fetcher.fetch.assert_not_called()
    assert item.page_url == f"{SITE}/library/assets/{ENTITLEMENT}"
    assert item.result.fields["title"] == "A Listing"
    assert item.result.fields["compatibility"] == {"unreal": "5.0-5.3"}


def test_an_entry_whose_listing_is_no_object_is_read_as_live(monkeypatch: MonkeyPatch) -> None:
    """Only an explicit ``isActiveInLive: false`` marks an item delisted.

    **Test steps:**

    * read an entry whose payload has no listing member
    * verify the listing was read through the scraper, and the item owns no license
    """
    session, _ = session_with(monkeypatch, live_fetcher(public_listing()))
    entry = LibraryEntry(LISTING_UID, "2025-01-01T10:00:00.000000Z", "T", f"{SITE}/listings/{LISTING_UID}", {})

    item = session.read_item(entry)

    assert item.page_url == f"{SITE}/listings/{LISTING_UID}"
    assert not item.license_paths


@mark.parametrize(
    ("owned", "licenses", "paths"),
    [
        param(
            [UEFN, PERSONAL],
            [
                {"license": "fab-standard", "url": f"{SITE}/eula"},
                {"license": "fab-uefn-reference-only", "url": f"{SITE}/eula"},
            ],
            {
                "fab-standard": "license/standard/reference-plus-source",
                "fab-uefn-reference-only": "license/standard/reference-only",
            },
            id="Personal before UEFN reference only, each its own license",
        ),
        param(
            [PERSONAL, PROFESSIONAL],
            [{"license": "fab-standard", "url": f"{SITE}/eula"}],
            {"fab-standard": "license/standard/professional"},
            id="Professional comes first, and the one id is held once",
        ),
        param(
            [CC_BY],
            [{"license": "cc-by-4.0", "url": "https://creativecommons.org/licenses/by/4.0/"}],
            {"cc-by-4.0": "license/cc/cc-by"},
            id="Creative Commons",
        ),
        param(
            [MARKETPLACE],
            [{"license": "fab-ue-only"}],
            {"fab-ue-only": "license/legacy/uem"},
            id="Marketplace, with no terms page",
        ),
        param(
            [UNKNOWN_TIER, CC_BY],
            [
                {"license": "cc-by-4.0", "url": "https://creativecommons.org/licenses/by/4.0/"},
                {"license": "new-fancy-one"},
            ],
            {"cc-by-4.0": "license/cc/cc-by", "new-fancy-one": "license/new/fancy"},
            id="a tier unknown to Fab's table is kept by its group and slug, after the known",
        ),
    ],
)
def test_every_owned_tier_is_a_license_of_the_record_broadest_first(
    monkeypatch: MonkeyPatch, owned: list[dict[str, Any]], licenses: list[dict[str, str]], paths: dict[str, str]
) -> None:
    """The record holds every license the account owns the item under, broadest first and each id once, and each
    names the path its text is read from (#705); no ``license-`` tag is written.

    **Test steps:**

    * read a live item owned under each set of tiers
    * verify its ``licenses`` and the path naming each one's text
    * verify the tags are the listing's own alone
    """
    session, _ = session_with(monkeypatch, live_fetcher(public_listing()))

    item = session.read_item(entry_of(result_of(licenses=owned)))

    assert item.result.fields["licenses"] == licenses
    assert item.license_paths == paths
    assert item.result.fields["advertised_tags"] == ["Environments", "interior"]


def test_a_listing_offering_one_tier_does_not_outweigh_the_tier_owned(monkeypatch: MonkeyPatch) -> None:
    """What the public listing offers is replaced by what the library says is owned.

    **Test steps:**

    * read a listing offering only a Creative Commons tier, owned under the Marketplace license
    * verify the one license is the Marketplace's, with no address
    """
    listing = public_listing(licenses=[{"group": "cc", "slug": "cc-by"}])
    session, _ = session_with(monkeypatch, live_fetcher(listing))

    item = session.read_item(entry_of(result_of(licenses=[MARKETPLACE])))

    assert item.result.fields["licenses"] == [{"license": "fab-ue-only"}]


def test_an_item_owned_under_no_tier_has_no_license(monkeypatch: MonkeyPatch) -> None:
    """A delisted item can carry no license at all, and the scan does not make one up.

    **Test steps:**

    * read a live item whose entry lists no tier, and a delisted one with a tier that has no path
    * verify no license or path is named for the first, and the second holds its license with no path
    """
    session, _ = session_with(monkeypatch, live_fetcher(public_listing(licenses=[])))
    bare = session.read_item(entry_of(result_of(licenses=[])))
    assert not bare.license_paths
    assert "licenses" not in bare.result.fields

    pathless = {"group": {"slug": "standard"}, "slug": "personal"}
    item = session.read_item(entry_of(result_of(licenses=[pathless], live=False)))
    assert not item.license_paths
    assert item.result.fields["licenses"] == [{"license": "fab-standard", "url": f"{SITE}/eula"}]


def test_an_entry_with_no_entitlement_object_has_no_tiers(monkeypatch: MonkeyPatch) -> None:
    """A result that states no entitlement, or tiers that are no list, is owned under nothing.

    **Test steps:**

    * read delisted entries whose ``entitlement`` is missing, and whose ``licenses`` is no list
    * verify neither names a license
    """
    session, _ = session_with(monkeypatch, Mock())
    for entitlement in (None, {"licenses": "none"}):
        raw = {**result_of(live=False), "entitlement": entitlement}
        assert not session.read_item(entry_of(raw)).license_paths


# endregion
# region License texts


def standard_eula(url: str) -> Page:
    """What Fab answers for its Standard License.

    :param url: the address.
    :returns: the page.
    """
    return json_page(url, {"body": "<h1>Fab End User License Agreement</h1><p>Terms.</p>"})


def test_the_standard_license_is_read_from_fabs_text(monkeypatch: MonkeyPatch) -> None:
    """One text covers every Standard tier, read from Fab's public JSON and kept as Markdown.

    **Test steps:**

    * read the license of a Standard path
    * verify the request was Fab's EULA JSON, and the terms are titled and addressed as the Standard License, hold the
      text as Markdown and the day it was read
    """
    session, fetcher = session_with(monkeypatch, standard_eula)

    terms = session.read_license("license/standard/reference-plus-source")

    fetcher.fetch.assert_called_once_with(EULA_JSON_URL)
    assert terms is not None
    assert (terms.title, terms.url) == ("Standard License", f"{SITE}/eula")
    assert terms.text == "# Fab End User License Agreement\n\nTerms."


@mark.parametrize("body", [param({"body": ""}, id="empty"), param({"text": "x"}, id="missing")])
def test_a_standard_license_with_no_text_is_a_failure(monkeypatch: MonkeyPatch, body: dict[str, Any]) -> None:
    """A license saved with no text would be saved for good, so it is not saved.

    **Test steps:**

    * read the Standard license, Fab answering no body
    * verify a fetch failure
    """
    session, _ = session_with(monkeypatch, lambda url: json_page(url, body))

    with raises(FetchError, match="no text"):
        session.read_license("license/standard/x")


def test_the_creative_commons_text_is_read_from_its_page(monkeypatch: MonkeyPatch) -> None:
    """The CC BY text is the plain legal code its page serves, which is not Fab's.

    **Test steps:**

    * read the license ``license/cc/cc-by`` with the plain fetch answering a text
    * verify the terms are titled and addressed as that legal code, the text stripped
    """
    session, _ = session_with(monkeypatch, Mock())
    title, url = CC_TEXTS["license/cc/cc-by"]
    fetch = Mock(return_value=Page(url, url, "\nAttribution 4.0 International\n", 200))
    monkeypatch.setattr(fab_license_texts, "HttpPageFetcher", Mock(return_value=Mock(fetch=fetch)))

    terms = session.read_license("license/cc/cc-by")

    fetch.assert_called_once_with(url)
    assert terms is not None
    assert (terms.title, terms.url, terms.text) == (title, url, "Attribution 4.0 International")


@mark.parametrize(
    "answer",
    [
        param(requests.ConnectionError("down"), id="no connection"),
        param(LoginRequiredError("403"), id="a refusal"),
        param(Page("u", "u", "Service Unavailable", 503), id="a passing refusal handed over as a page"),
        param(Page("u", "u", "  ", 200), id="an empty page"),
    ],
)
def test_a_creative_commons_page_that_does_not_answer_is_waited_for(monkeypatch: MonkeyPatch, answer: object) -> None:
    """A text that cannot be read is no reason to save a record without it, or with an error page as its license: the
    scan waits and tries again.

    **Test steps:**

    * read the CC license with the plain fetch failing, refused, or answering a page that is no text
    * verify the scan is made to wait, the reason naming the address
    """
    session, _ = session_with(monkeypatch, Mock())
    fetch = Mock(side_effect=answer) if isinstance(answer, Exception) else Mock(return_value=answer)
    monkeypatch.setattr(fab_license_texts, "HttpPageFetcher", Mock(return_value=Mock(fetch=fetch)))

    with raises(StoreOfflineError, match="legalcode"):
        session.read_license("license/cc/cc-by")


def test_a_license_fab_states_no_text_for_has_no_terms(monkeypatch: MonkeyPatch, caplog: LogCaptureFixture) -> None:
    """The Marketplace license has no page, and an unknown path is not guessed at.

    **Test steps:**

    * read the license of the Marketplace's path
    * verify no terms, and the license was logged
    """
    session, fetcher = session_with(monkeypatch, Mock())

    with caplog.at_level("INFO"):
        assert session.read_license("license/legacy/uem") is None

    fetcher.fetch.assert_not_called()
    assert "license/legacy/uem" in caplog.text


# endregion
