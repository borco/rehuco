"""Tests for merging a checksum run's entries into the record as it is on disk now (#512): what the run did not change
is the file's, what it changed is its own, and when both changed one entry the later check wins."""

from typing import Any, Final

from pytest import mark, param
from rehuco_core import merge_checksum_entries

OLD: Final = "2026-10-01T10:00:00Z"
"""When every entry the run read was last checked."""

RUN: Final = "2026-10-19T10:00:00Z"
"""When the run checked what it checked."""

LATER: Final = "2026-10-19T11:00:00Z"
"""A check landing on disk after the run's."""

EARLIER: Final = "2026-10-18T10:00:00Z"
"""A check landing on disk while the run was hashing, made before the run's own."""


def entry(name: str, verified: str | None = OLD, digest: str = "0123abcd", **extra: Any) -> dict[str, Any]:
    """One raw entry.

    :param name: the file.
    :param verified: when it was checked, or ``None`` for a dateless claim.
    :param digest: its ``crc32``.
    :param extra: further keys.
    :returns: the entry.
    """
    raw: dict[str, Any] = {"name": name, "crc32": digest, **extra}
    if verified is not None:
        raw["verified"] = verified
        raw["status"] = "matched"
    return raw


def names(entries: list[Any]) -> list[str | None]:
    """The names of ``entries``, in order.

    :param entries: raw entries.
    :returns: each one's name, ``None`` for one that has none.
    """
    return [raw.get("name") if isinstance(raw, dict) else None for raw in entries]


def test_a_file_nobody_touched_meanwhile_takes_the_run_s_entries_as_they_are() -> None:
    """With the file as the run read it, the run's entries are written as it left them, in its order.

    **Test steps:**

    * merge a run that re-dated one entry, reordered and added one, into the file it read
    * verify the result is the run's list
    """
    base = [entry("a"), entry("b")]
    mine = [entry("c", RUN), entry("b"), entry("a", RUN)]

    assert merge_checksum_entries(base, mine, list(base)) == mine


def test_what_the_run_did_not_change_is_the_file_s_now() -> None:
    """An entry the run carried untouched takes the file's version: a claim moved in stays, a forgotten entry stays
    gone, a re-checked one keeps its new date.

    **Test steps:**

    * the run re-dates ``a`` and carries ``b``, ``c`` and ``d`` untouched
    * meanwhile the file forgot ``b``, re-dated ``c``, and took a claim for ``e``
    * verify ``a`` is the run's, ``b`` is gone, ``c`` is the file's, ``d`` is kept and ``e`` is there
    """
    base = [entry("a"), entry("b"), entry("c"), entry("d")]
    mine = [entry("a", RUN), entry("b"), entry("c"), entry("d")]
    theirs = [entry("a"), entry("c", LATER), entry("d"), entry("e", None)]

    merged = merge_checksum_entries(base, mine, theirs)

    assert merged == [entry("a", RUN), entry("c", LATER), entry("d"), entry("e", None)]


def test_what_the_run_added_or_dropped_is_its_own() -> None:
    """An entry the run adopted is added, one it pruned or moved away is dropped, while the file keeps what the run
    never saw.

    **Test steps:**

    * the run drops ``b`` and adopts ``c``; meanwhile the file took a claim for ``d``
    * verify ``a``, ``c`` and ``d`` are written, and ``b`` is not
    """
    base = [entry("a"), entry("b")]
    mine = [entry("a"), entry("c", RUN)]
    theirs = [entry("a"), entry("b"), entry("d", None)]

    assert names(merge_checksum_entries(base, mine, theirs)) == ["a", "c", "d"]


@mark.parametrize(
    ("mine", "theirs", "kept"),
    [
        param(entry("a", RUN, "11111111"), entry("a", LATER, "22222222"), "theirs", id="a-later-check-on-disk"),
        param(entry("a", RUN, "11111111"), entry("a", EARLIER, "22222222"), "mine", id="an-earlier-check-on-disk"),
        param(entry("a", RUN, "11111111"), entry("a", RUN, "22222222"), "mine", id="a-tie-goes-to-the-run"),
        param(entry("a", RUN), None, "mine", id="forgotten-on-disk-but-re-checked-by-the-run"),
        param(None, entry("a", LATER), "theirs", id="dropped-by-the-run-but-re-checked-on-disk"),
        param(None, entry("a", None, "22222222"), "mine", id="dropped-by-the-run-and-a-dateless-claim-on-disk"),
    ],
)
def test_when_both_changed_an_entry_the_later_check_wins(
    mine: dict[str, Any] | None, theirs: dict[str, Any] | None, kept: str
) -> None:
    """Both sides changed ``a``: the one checked later is kept; a side with no date is older than any; a tie is the
    run's.

    **Test steps:**

    * merge a run's ``a`` against the file's ``a``, either of them possibly absent
    * verify the expected side is what is written
    """
    base = [entry("a"), entry("z")]
    merged = merge_checksum_entries(
        base, [*([mine] if mine else []), entry("z")], [*([theirs] if theirs else []), entry("z")]
    )

    winner = mine if kept == "mine" else theirs
    assert [raw for raw in merged if raw["name"] == "a"] == ([winner] if winner else [])


def test_a_run_from_no_record_on_disk_keeps_everything_it_has() -> None:
    """A seeded or new run started from nothing on disk: each of its entries is its own addition, merged beside a
    record someone else created meanwhile.

    **Test steps:**

    * merge a run with no base, holding ``a`` and ``b``, into a file holding a claim for ``b`` and an entry ``c``
    * verify the run's ``a`` and ``b`` and the file's ``c`` are written
    """
    mine = [entry("a", RUN), entry("b", RUN)]
    theirs = [entry("b", None, "99999999"), entry("c")]

    assert merge_checksum_entries([], mine, theirs) == [entry("a", RUN), entry("b", RUN), entry("c")]


def test_entries_the_run_cannot_name_are_carried_as_the_file_has_them() -> None:
    """An entry whose name cannot be read was never the run's to change: the file's are carried, after the named
    ones, and duplicates of a name the run left alone come through as the file holds them.

    **Test steps:**

    * the run re-dates ``a``; the file meanwhile holds an unnamed entry, two of ``b`` and a new date on ``a``'s twin
    * verify the merged list
    """
    unnamed = {"crc32": "0123abcd"}
    base = [entry("a"), entry("b"), entry("b", digest="ffffffff"), unnamed]
    mine = [entry("a", RUN), entry("b"), entry("b", digest="ffffffff"), unnamed]
    theirs = [entry("a"), entry("b"), entry("b", digest="ffffffff"), unnamed, entry("x", None)]

    merged = merge_checksum_entries(base, mine, theirs)

    assert merged == [entry("a", RUN), entry("b"), entry("b", digest="ffffffff"), entry("x", None), unnamed]


def test_a_date_that_does_not_parse_is_no_date() -> None:
    """An entry whose date does not parse reads as never checked, so any dated check beats it.

    **Test steps:**

    * the run re-dates ``a``; the file holds an ``a`` whose date does not parse
    * verify the run's ``a`` is written
    """
    base = [entry("a")]
    mine = [entry("a", RUN)]
    theirs = [{"name": "a", "crc32": "1", "verified": "not a date"}]

    assert merge_checksum_entries(base, mine, theirs) == mine
