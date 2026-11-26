"""What a store adds for its library to be scanned ([[acquisition-tooling#library-scan-job]], #682): its listing and
its item reading, nothing else -- the scan job does the rest for every store alike.

Grouped rather than split one class per file, as :mod:`~.protocols` is: the site, the session it opens, what a listing
yields, and how either says the scan must stop mean nothing apart. Plain `Protocol`s, so a user's own script can
satisfy them without importing this package, as a `~.protocols.SiteScraper` does.
"""

from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Final, Protocol, runtime_checkable

from rehuco_core import LibraryCursor, LicenseTerms

from .browser_fetcher import PersonaLease
from .results import ScrapeResult


@dataclass(frozen=True)
class LibraryEntry:
    """One item of an account's library, as its listing names it.

    :param site_id: the store's own id for the item ([[assets#site-id]]), what a record of it is found by.
    :param acquired: when the account got it, in UTC with six fractional digits and a ``Z`` ([[assets#block]]).
    :param title: its title, for the scan's log line.
    :param url: its page, for the scan's log line.
    :param payload: whatever else the listing said, the site's own, handed back to :meth:`LibrarySession.read_item`.
    """

    site_id: str
    acquired: str
    title: str
    url: str
    payload: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ScannedItem:
    """One item read in full: what its record is written from.

    :param result: the item's fields, description and images, as a dropped URL of it would give them
        ([[acquisition-tooling#scraper-protocols]]).
    :param page_url: the page it was read from, the record's source.
    :param license_paths: the store's stable id of each license it is held under (Fab: ``license/cc/cc-by``,
        [[assets#licenses]]), by the license's short id, whose text is saved beside the record; empty when it names
        none.
    """

    result: ScrapeResult
    page_url: str
    license_paths: Mapping[str, str] = field(default_factory=dict)


class StorePausedError(Exception):
    """The store stopped the scan in a way the user can fix in the browser: a challenge page, a login that expired
    ([[acquisition-tooling#library-scan-stops]]). The scan ends paused with :attr:`reason` as its row's message, and
    the persona browser is opened at :attr:`url`.

    :param reason: what stopped it, as the sentence the row shows.
    :param url: the page to open for the user.
    """

    def __init__(self, reason: str, url: str) -> None:
        super().__init__(reason)
        self.reason: Final = reason
        self.url: Final = url


class StoreOfflineError(Exception):
    """The store does not answer -- the network is down, or it is -- which passes by itself: the scan waits and the
    queue tries again ([[appendices.task-queue#waiting]]).

    :param reason: what it waits for, as the sentence the row shows.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason: Final = reason


@runtime_checkable
class LibrarySession(Protocol):
    """A store's library, open for one run of a scan; every call may raise :class:`StorePausedError` or
    :class:`StoreOfflineError`."""

    def check(self) -> None:
        """Make sure the scan can go on -- logged in, not challenged: what every run asks first, so a resumed scan
        looks again at what stopped it ([[acquisition-tooling#library-scan-stops]])."""

    def listing(
        self,
        cursor: LibraryCursor,
        wait: Callable[[], None],
    ) -> Iterator[LibraryEntry]:  # pyright: ignore[reportReturnType]
        """The library, oldest acquisition first, from the cursor's millisecond on.

        :param cursor: where the scan's records reach; an empty one reads from the first item. What of its
            millisecond is filed already is the scan's to skip, so a site never builds the store's own cursor from it
            by more than the time.
        :param wait: called between two pages: the scan's paced pause, where it may be stopped or give the persona
            browser up to a drop.
        :returns: the entries, page by page.
        """

    def read_item(self, entry: LibraryEntry) -> ScannedItem:  # pyright: ignore[reportReturnType]
        """Read one item in full.

        :param entry: what the listing said of it.
        :returns: the item.
        """

    def read_license(self, path: str) -> LicenseTerms | None:  # pyright: ignore[reportReturnType]
        """Read a license's text, once per run for each license a scan meets.

        :param path: the store's stable id for the license.
        :returns: the terms, or ``None`` for a license the store states no text for (Fab's *UE Marketplace*).
        """


@runtime_checkable
class LibrarySite(Protocol):
    """A store whose library can be scanned: how its records are told apart, and how its library is opened."""

    @property
    def key(self) -> str:  # pyright: ignore[reportReturnType]
        """The stable name the scan is saved under, in a saved queue."""

    @property
    def name(self) -> str:  # pyright: ignore[reportReturnType]
        """The site as its records' sources name it -- the publisher a scraper fills in -- which a scan finds its
        records by ([[assets#site-id]])."""

    def session(
        self,
        lease: PersonaLease,
    ) -> AbstractContextManager[LibrarySession]:  # pyright: ignore[reportReturnType]
        """Open the library for one run.

        :param lease: the persona browser, held for the run and given up between pages to a drop that needs it; the
            session reaches the browser only through it, asking it for its session at every use and never keeping
            one: between two uses the lease may have given the browser up and started another.
        :returns: the session, closed when the run ends however it ends.
        """
