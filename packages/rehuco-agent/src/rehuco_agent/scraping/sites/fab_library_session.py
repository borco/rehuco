"""Fab's library, open for one scan run ([[acquisition-tooling#library-scan-job]], [[assets#licenses]], #684).

What only the library knows is read here: the listing, oldest acquisition first; the tiers of a license the account
owns; the text of each. Everything an item itself says is the Fab scraper's (#701), so an item filed by a scan and one
filed by a drop read alike.
"""

import base64
import datetime
import json
import logging
from collections.abc import Callable, Iterator, Mapping
from typing import Any, Final
from urllib.parse import quote, urlencode, urlsplit

from rehuco_core import LibraryCursor, LicenseTerms

from ..browser_fetcher import PersonaLease
from ..library_site import LibraryEntry, ScannedItem
from ..protocols import FetchError, PageGoneError
from ..results import InvalidScrapeResultError, ScrapeResult
from .fab import HOSTS, LIBRARY_ASSET_URL, LISTING_URL, NON_SLUG, SITE_URL, Fab
from .fab_license_texts import FabLicenseTexts
from .fab_session_fetcher import FabSessionFetcher

LOG: Final = logging.getLogger(__name__)

LIBRARY_SEARCH_PATH: Final = "/i/library/search"
"""The library's listing, JSON: the request the library page itself makes."""

LIBRARY_QUERY: Final = {"sort_by": "createdAt", "source": "acquired"}
"""The listing's order, oldest acquisition first, and which of the account's items it holds."""

CHECK_QUERY: Final = {"source": "acquired", "count": 0, "aggregate_on": "category_per_listing_type"}
"""A request that lists nothing and answers only for a session that may read the library."""

OWNED_LICENSE_ORDER: Final = (
    ("standard", "professional"),
    ("standard", "personal"),
    ("cc", "cc-by"),
    ("legacy", "legacy-uem"),
    ("standard", "uefn-reference-only"),
)
"""Fab's license tiers, the broadest rights first: the one an item holds under, when the account owns several, is the
first of these it owns, and a tier named here goes before one that is not."""

NULL_UID: Final = "00000000-0000-0000-0000-000000000000"
"""The entitlement id of a cursor that stands before every entry of its millisecond."""

EPOCH: Final = datetime.datetime(1970, 1, 1, tzinfo=datetime.UTC)
"""What a millisecond count is taken from."""


class FabLibrarySession:
    """A scan's view of the account's Fab library, through the persona the scan leases.

    Satisfies `~rehuco_agent.scraping.library_site.LibrarySession`, and is its own context manager: closing it gives
    nothing back, since the lease is the scan's.

    :param lease: the scan's hold on the persona.
    """

    def __init__(self, lease: PersonaLease) -> None:
        self.__fetcher: Final = FabSessionFetcher(lease)

    def __enter__(self) -> FabLibrarySession:
        """Open the library for a ``with`` block.

        :returns: this session.
        """
        return self

    def __exit__(self, *_: object) -> None:
        """Close nothing: the persona is the lease's, given back by the scan."""

    def check(self) -> None:
        """Ask the library for nothing, which only a persona that is logged in and not challenged is answered.

        :raises StorePausedError: a challenge page, or a login that expired.
        :raises StoreOfflineError: Fab does not answer.
        :raises FetchError: the answer is not the library's.
        """
        self.__get_json(f"{SITE_URL}{LIBRARY_SEARCH_PATH}?{urlencode(CHECK_QUERY)}")

    def listing(self, cursor: LibraryCursor, wait: Callable[[], None]) -> Iterator[LibraryEntry]:
        """The library, oldest acquisition first, from the cursor's millisecond on.

        The listing is asked for from the millisecond alone: it breaks a tie within one by the entitlement's id, so no
        cursor of the records' own can say where in it they stop, and the scan skips what it filed.

        :param cursor: where the scan's records reach.
        :param wait: called before every page but the first.
        :returns: the entries, page by page; one that cannot be read is logged and left out.
        :raises StorePausedError: a challenge page, or a login that expired.
        :raises StoreOfflineError: Fab does not answer.
        :raises FetchError: a page is not the library's.
        """
        query = dict(LIBRARY_QUERY)
        position = FabLibrarySession.__cursor_at(cursor)
        if position is not None:
            query["cursor"] = position
        url: str | None = f"{SITE_URL}{LIBRARY_SEARCH_PATH}?{urlencode(query)}"
        first = True
        while url is not None:
            if not first:
                wait()
            first = False
            page = self.__get_json(url)
            results = page.get("results")
            for result in results if isinstance(results, list) else ():
                entry = FabLibrarySession.__entry_of(result)
                if entry is not None:
                    yield entry
            url = FabLibrarySession.__next_page(page, url) if results else None

    def read_item(self, entry: LibraryEntry) -> ScannedItem:
        """Read one item: through the Fab scraper while its listing is public, from its library entry once it is not,
        with the license the account owns it under.

        :param entry: what the listing said of it.
        :returns: the item.
        :raises StorePausedError: a challenge page, or a login that expired.
        :raises StoreOfflineError: Fab does not answer.
        :raises FetchError: a listing is not Fab's, or what it states cannot be written as a record.
        """
        raw = entry.payload
        listing = raw.get("listing")
        live = not (isinstance(listing, dict) and listing.get("isActiveInLive") is False)
        result = None
        if live:
            try:
                result = Fab().scrape_url(entry.url, self.__fetcher)
            except PageGoneError:
                LOG.info("%s left the store; written from the library.", entry.title)
        if result is None:
            result = Fab.scrape_library_entry(raw)
        owned = FabLibrarySession.__owned_tiers(raw)
        fields = dict(result.fields)
        license_paths = FabLibrarySession.__license_fields(fields, owned)
        merged = ScrapeResult(fields=fields, description=result.description, images=result.images)
        try:
            checked = ScrapeResult.coerce(merged)
        except InvalidScrapeResultError as error:
            # one item Fab states oddly stops the scan with its name, never with a traceback
            raise FetchError(f"{entry.title} ({entry.url}) cannot be written: {error}") from error
        return ScannedItem(checked, str(fields["url"]), license_paths)

    def read_license(self, path: str) -> LicenseTerms | None:
        """Read a license's text, through the persona for Fab's own and plainly for the Creative Commons page
        (:class:`~.fab_license_texts.FabLicenseTexts`).

        :param path: Fab's stable id for the license (``license/cc/cc-by``).
        :returns: the terms; ``None`` for a license Fab states no text for, the Marketplace's.
        :raises StorePausedError: a challenge page, or a login that expired.
        :raises StoreOfflineError: Fab, or the page holding a Creative Commons text, does not answer.
        :raises FetchError: Fab's text is not the JSON it should be.
        """
        return FabLicenseTexts(self.__get_json).read(path)

    def __get_json(self, url: str) -> dict[str, Any]:
        """One request to Fab, its answer read as a JSON object.

        :param url: the address.
        :returns: the object.
        :raises StorePausedError: a challenge page, or a login that expired.
        :raises StoreOfflineError: Fab does not answer.
        :raises FetchError: the answer is not a JSON object, or its status says the address is wrong.
        """
        page = self.__fetcher.fetch(url)
        if page.status != 200:
            raise FetchError(f"Fab answered {page.status}: {url}")
        try:
            data = json.loads(page.html)
        except ValueError as error:
            raise FetchError(f"Fab answered something that is not JSON: {url}") from error
        if not isinstance(data, dict):
            raise FetchError(f"Fab answered something that is not a JSON object: {url}")
        return data

    @staticmethod
    def __cursor_at(cursor: LibraryCursor) -> str | None:
        """Fab's own cursor, standing before every entry of the scan's millisecond.

        :param cursor: where the scan's records reach.
        :returns: the cursor Fab's listing takes: base64 of ``v=[<epoch ms>, "<entitlement id>"]`` ([[assets#block]]),
            ``None`` to read from the first item, as for a cursor that is no time.
        """
        millisecond = cursor.millisecond
        if millisecond is None:
            return None
        try:
            moment = datetime.datetime.fromisoformat(millisecond).replace(tzinfo=datetime.UTC)
        except ValueError:
            # a typed-in acquired long enough to pass for a time: the library is read whole, and the scan skips
            # what it filed by id
            LOG.warning(
                "The newest acquired of the root's Fab records is no time (%s); listing from the start.", millisecond
            )
            return None
        stamp = (moment - EPOCH) // datetime.timedelta(milliseconds=1)
        raw = f"v={quote(f'[{stamp},{json.dumps(NULL_UID)}]', safe='')}"
        return base64.b64encode(raw.encode("ascii")).decode("ascii")

    @staticmethod
    def __next_page(page: Mapping[str, Any], current: str) -> str | None:
        """Where the listing goes on.

        :param page: the page just read.
        :param current: its address.
        :returns: the next page's address; ``None`` at the last.
        :raises FetchError: the next page is not the library's listing.
        """
        following = page.get("next")
        if not following:
            return None
        parts = urlsplit(str(following))
        if parts.scheme != "https" or parts.hostname not in HOSTS or parts.path != LIBRARY_SEARCH_PATH:
            raise FetchError(f"Fab's listing after {current} goes on elsewhere: {following}")
        return str(following)

    @staticmethod
    def __entry_of(result: object) -> LibraryEntry | None:
        """One library result as an entry.

        :param result: a ``results`` member of the listing.
        :returns: the entry; ``None`` when it names no listing, no entitlement or no time, which is logged.
        """
        if not isinstance(result, dict):
            LOG.warning("A library entry of Fab is not an object; left out.")
            return None
        listing, entitlement = result.get("listing"), result.get("uid")
        uid = listing.get("uid") if isinstance(listing, dict) else None
        if not isinstance(listing, dict) or not isinstance(uid, str) or not isinstance(entitlement, str):
            LOG.warning("A library entry of Fab names no listing or no entitlement; left out.")
            return None
        acquired = FabLibrarySession.__acquired_of(result.get("createdAt"))
        if acquired is None:
            LOG.warning("The library entry of Fab listing %s has no readable acquisition time; left out.", uid)
            return None
        title = listing.get("title")
        url = (
            LISTING_URL.format(uid=uid.lower())
            if listing.get("isActiveInLive") is not False
            else LIBRARY_ASSET_URL.format(entitlement=entitlement)
        )
        return LibraryEntry(
            site_id=uid.lower(),
            acquired=acquired,
            title=title if isinstance(title, str) and title else uid,
            url=url,
            payload=result,
        )

    @staticmethod
    def __acquired_of(stamp: object) -> str | None:
        """An acquisition time as the block stores it: UTC, six fractional digits, a ``Z`` ([[assets#block]]).

        :param stamp: ``2025-09-02T18:13:27.317034+00:00``.
        :returns: ``2025-09-02T18:13:27.317034Z``; ``None`` for anything but a time with its zone.
        """
        if not isinstance(stamp, str):
            return None
        try:
            moment = datetime.datetime.fromisoformat(stamp)
        except ValueError:
            return None
        if moment.tzinfo is None:
            return None
        return moment.astimezone(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    @staticmethod
    def __owned_tiers(raw: Mapping[str, Any]) -> list[dict[str, Any]]:
        """The license tiers the account owns an item under, the broadest rights first.

        :param raw: the library entry.
        :returns: the tiers, as the entry states them; empty for none (a delisted item may have none).
        """
        entitlement = raw.get("entitlement")
        stated = entitlement.get("licenses") if isinstance(entitlement, dict) else None
        tiers = [tier for tier in stated if isinstance(tier, dict)] if isinstance(stated, list) else []
        return sorted(tiers, key=FabLibrarySession.__rank)

    @staticmethod
    def __rank(tier: Mapping[str, Any]) -> int:
        """How broad the rights of a tier are, by :data:`OWNED_LICENSE_ORDER`.

        :param tier: an owned tier.
        :returns: its place in the order; one the order does not name is after every one it does.
        """
        pair = FabLibrarySession.__pair_of(tier)
        return OWNED_LICENSE_ORDER.index(pair) if pair in OWNED_LICENSE_ORDER else len(OWNED_LICENSE_ORDER)

    @staticmethod
    def __pair_of(tier: Mapping[str, Any]) -> tuple[str, str]:
        """A tier's group and slug, which Fab's license table is keyed by.

        :param tier: an owned tier.
        :returns: ``(group, slug)``; a part the tier does not state is empty.
        """
        group = tier.get("group")
        return str(group.get("slug") if isinstance(group, dict) else ""), str(tier.get("slug") or "")

    @staticmethod
    def __license_fields(fields: dict[str, Any], owned: list[dict[str, Any]]) -> dict[str, str]:
        """Write the owned licenses into an item's fields: each tier an entry of its ``licenses``, the broadest first
        and each id once (#705); a tier this scraper has no id for is kept under its own slug, with no url.

        :param fields: the item's fields, changed here.
        :param owned: the owned tiers, the broadest first.
        :returns: the path naming each license's text, by id, from the first tier of that id that states one; empty
            when none is owned.
        """
        # what the listing offered is replaced: the library names the tiers that are owned
        fields.pop("licenses", None)
        entries: list[dict[str, str]] = []
        paths: dict[str, str] = {}
        for tier in owned:
            pair = FabLibrarySession.__pair_of(tier)
            entry = Fab.license_entry(*pair) or {"license": NON_SLUG.sub("-", "-".join(pair).lower()).strip("-")}
            license_id = entry["license"]
            if not license_id or any(kept["license"] == license_id for kept in entries):
                continue
            entries.append(entry)
            path = tier.get("path")
            if isinstance(path, str) and path:
                paths[license_id] = path
        if entries:
            fields["licenses"] = entries
        return paths
