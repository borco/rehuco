"""Tests for what a full rescan finds gone from the account (#682): `LibraryRescan` walks a root's dated records
alongside the listing and names those it passes over."""

from typing import Final

from rehuco_agent.scraping.library_rescan import LibraryRescan
from rehuco_core import LibraryCursor

FIRST: Final = "2024-01-01T00:00:00.000000Z"
"""The oldest acquisition below."""

SECOND: Final = "2024-02-01T00:00:00.000000Z"
"""The second acquisition below."""

SECOND_TIE: Final = "2024-02-01T00:00:00.000500Z"
"""An acquisition in :data:`SECOND`'s millisecond -- a bundle's other item."""

THIRD: Final = "2024-03-01T00:00:00.000000Z"
"""The newest acquisition below."""

RECORDS: Final = (("a", FIRST), ("b", SECOND), ("c", SECOND_TIE), ("d", THIRD))
"""Four dated records of one site, two of them in one millisecond."""


def test_a_record_the_listing_passes_over_is_gone() -> None:
    """The listing is sorted by acquisition, so a record whose time it went past without naming it left the account.

    **Test steps:**

    * walk four records alongside a listing that names the first and the last only
    * verify the two in between are gone once the last is listed, and nothing more at the end
    """
    rescan = LibraryRescan(RECORDS, LibraryCursor())

    assert not rescan.listed(FIRST, "a")
    assert rescan.listed(THIRD, "d") == ["b", "c"]
    assert not rescan.finished()


def test_a_record_in_a_listed_millisecond_is_gone_only_if_not_named_there() -> None:
    """Two items share a millisecond; the one the listing names stays, the other is gone.

    **Test steps:**

    * list the second record's millisecond naming only it, then the last record
    * verify only the unnamed record of that millisecond is gone
    """
    rescan = LibraryRescan(RECORDS, LibraryCursor())
    rescan.listed(FIRST, "a")

    assert not rescan.listed(SECOND, "b")
    assert rescan.listed(THIRD, "d") == ["c"]


def test_the_records_past_the_listings_end_are_gone() -> None:
    """What the listing never reached left the account.

    **Test steps:**

    * list the first record only and end the listing
    * verify every other record is gone, in time order
    """
    rescan = LibraryRescan(RECORDS, LibraryCursor())
    rescan.listed(FIRST, "a")

    assert rescan.finished() == ["b", "c", "d"]


def test_the_position_is_the_last_millisecond_with_what_it_named() -> None:
    """What a rescan saves is how far it got: the last listed millisecond and the ids named in it.

    **Test steps:**

    * list both items of one millisecond
    * verify the position holds the later time and both ids
    """
    rescan = LibraryRescan(RECORDS, LibraryCursor())
    rescan.listed(SECOND, "b")
    rescan.listed(SECOND_TIE, "c")

    assert rescan.position == LibraryCursor(SECOND_TIE, frozenset({"b", "c"}))


def test_a_resumed_rescan_judges_only_what_it_had_not_reached() -> None:
    """Resumed from its position, a rescan keeps what it listed before the pause and settles the rest.

    **Test steps:**

    * resume from a position in the second millisecond that named one of its two records
    * end the listing at once
    * verify the earlier record is left alone, and the unnamed one of that millisecond and the later one are gone
    """
    rescan = LibraryRescan(RECORDS, LibraryCursor(SECOND, frozenset({"b"})))

    assert rescan.finished() == ["c", "d"]


def test_an_entry_before_the_position_changes_nothing() -> None:
    """A listing that names an item the rescan is already past leaves the walk where it is.

    **Test steps:**

    * resume from the last record's position
    * list an older item
    * verify nothing is called gone and the position is unchanged
    """
    position = LibraryCursor(THIRD, frozenset({"d"}))
    rescan = LibraryRescan(RECORDS, position)

    assert not rescan.listed(FIRST, "a")
    assert rescan.position == position


def test_a_record_not_dated_to_the_millisecond_is_never_called_gone() -> None:
    """A partial date or a time typed in cannot be placed in the walk, so it is left alone whatever the listing says.

    **Test steps:**

    * walk a record dated by its month and one timed to the second, alongside a listing that names neither
    * end the listing
    * verify neither is called gone
    """
    rescan = LibraryRescan((("month", "2024-05"), ("second", "2024-05-03T12:34:56Z")), LibraryCursor())

    assert not rescan.listed(THIRD, "d")
    assert not rescan.finished()
