"""What a full rescan finds gone from the account ([[acquisition-tooling#library-scan-job]], [[assets#online-only]],
#682): the records the library listing passed over.

The listing is sorted by acquisition, so a record the store no longer lists is one whose time the walk has gone past
without naming it. Knowing that needs only the walk's position, which the rescan saves, never the set of every id it
saw -- so a rescan paused and resumed a hundred times still tells a gone record from one not reached yet.
"""

from collections.abc import Iterable
from typing import Final

from rehuco_core import ACQUIRED_MILLISECOND_LENGTH, LibraryCursor


class LibraryRescan:
    """Walks a root's dated records of one site alongside the library listing, and names those the listing passes over.

    A record whose ``acquired`` is not the store's time to the millisecond -- none, a partial date, one typed in --
    cannot be placed in the walk and is never called gone.

    :param records: the ``(site_id, acquired)`` of each of the site's records in the root that has an ``acquired``.
    :param position: how far an earlier run of this rescan got; empty for one starting at the oldest item.
    """

    def __init__(self, records: Iterable[tuple[str, str]], position: LibraryCursor) -> None:
        self.__position = position
        start = position.millisecond
        self.__pending: Final = sorted(
            (acquired[:ACQUIRED_MILLISECOND_LENGTH], site_id)
            for site_id, acquired in records
            if len(acquired) >= ACQUIRED_MILLISECOND_LENGTH
            and (start is None or acquired[:ACQUIRED_MILLISECOND_LENGTH] >= start)
        )
        self.__next = 0

    @property
    def position(self) -> LibraryCursor:
        """How far the walk got: the last listed millisecond and the ids listed in it -- what the rescan saves.

        :returns: the position.
        """
        return self.__position

    def listed(self, acquired: str, site_id: str) -> list[str]:
        """Hear that the listing named an item, and say which records it passed over to get there.

        :param acquired: the item's acquisition time.
        :param site_id: its store id.
        :returns: the ids of the records gone from the account, in time order.
        """
        millisecond = acquired[:ACQUIRED_MILLISECOND_LENGTH]
        current = self.__position.millisecond
        if current is not None and millisecond < current:
            return []
        if current is not None and millisecond == current:
            self.__position = LibraryCursor(
                max(acquired, self.__position.acquired or acquired), self.__position.site_ids | {site_id}
            )
            return []
        gone = self.__passed_before(millisecond)
        self.__position = LibraryCursor(acquired, frozenset({site_id}))
        return gone

    def finished(self) -> list[str]:
        """Hear that the listing ended, and say which records it never reached.

        :returns: the ids of the records gone from the account, in time order.
        """
        return self.__passed_before(None)

    def __passed_before(self, millisecond: str | None) -> list[str]:
        """Settle every record acquired before ``millisecond``: gone unless listed in the position's own millisecond.

        :param millisecond: where the walk now is; ``None`` past the end.
        :returns: the ids gone.
        """
        listed_at = self.__position.millisecond
        listed = self.__position.site_ids
        gone: list[str] = []
        while self.__next < len(self.__pending):
            at, site_id = self.__pending[self.__next]
            if millisecond is not None and at >= millisecond:
                break
            if not (at == listed_at and site_id in listed):
                gone.append(site_id)
            self.__next += 1
        return gone
