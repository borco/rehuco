"""Tests for what the Roots view says about a file's checksum: the state a row reads as, and the pane's lines (#457).

Pure functions over a record's entry and an instant, so nothing here touches a widget or a disk.
"""

from datetime import UTC, datetime, timedelta
from typing import Final

from pytest import mark
from rehuco_agent.documents.files_rows import FileChecksumState
from rehuco_agent.rehuco.roots_checksum import (
    BAD_INK,
    NEVER_CHECKED,
    NO_CHECKSUM,
    NOT_APPLICABLE,
    NOT_COVERED,
    OLD_BAD_INK,
    RowChecksum,
    checked_text,
    checksum_lines,
    row_checksum,
    warning_ink,
)
from rehuco_core import TRUST_NOT_TRACKED, ChecksumEntry, CoveredFile

NOW: Final = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
WINDOW: Final = timedelta(days=90)


def entry(*, status: str | None = "matched", days: float | None = 1, digest: str | None = "aabbccdd") -> ChecksumEntry:
    """One entry of a record, as a check ``days`` ago left it.

    :param status: what the check answered.
    :param days: how long ago it was made; ``None`` for an entry never checked.
    :param digest: the recorded hash; ``None`` for an entry listed with none.
    :returns: the entry.
    """
    return ChecksumEntry(
        "a.mp4",
        None if digest is None else "crc32",
        digest,
        None if days is None else NOW - timedelta(days=days),
        status,
    )


def covered(parsed: ChecksumEntry | None, *, trusted_since: datetime | None = TRUST_NOT_TRACKED) -> CoveredFile:
    """What a record says about a file.

    :param parsed: the file's entry, or ``None`` when the record does not list it.
    :param trusted_since: since when the machine has trusted the record where it is.
    :returns: the covered file.
    """
    return CoveredFile(parsed, trusted_since)


# region The state a file reads as


def test_a_file_no_record_covers_has_no_state() -> None:
    """Nothing says it is checked, or not: it carries no state at all.

    **Test steps:**

    * ask for the state of a file with no covering record
    * verify there is none
    """
    assert row_checksum(None, WINDOW, NOW) is None


@mark.parametrize(
    "file",
    [
        covered(None),
        covered(entry(digest=None, days=None, status=None)),
        covered(entry(digest="aabbccdd", status="unexpected")),
    ],
    ids=["not listed", "listed with no hash", "reported unexpected"],
)
def test_a_file_with_no_hash_of_its_own_reads_as_no_checksum(file: CoveredFile) -> None:
    """Not listed, listed without a hash, and the old *unexpected* all say the same: nothing is recorded.

    **Test steps:**

    * ask for the state of each
    * verify it is *missing*, with no date
    """
    assert row_checksum(file, WINDOW, NOW) == RowChecksum(FileChecksumState.MISSING)


def test_an_entry_this_build_cannot_read_reads_as_unreadable() -> None:
    """A malformed entry costs only itself.

    **Test steps:**

    * ask for the state of a file whose entry did not parse
    * verify it is *malformed*
    """
    assert row_checksum(CoveredFile(None, TRUST_NOT_TRACKED, malformed=True), WINDOW, NOW) == RowChecksum(
        FileChecksumState.MALFORMED
    )


@mark.parametrize(
    ("file", "state", "untrusted"),
    [
        (covered(entry()), FileChecksumState.OK, False),
        (covered(entry(status="mismatched")), FileChecksumState.BAD, False),
        (covered(entry(days=400)), FileChecksumState.OLD_OK, False),
        (covered(entry(status="mismatched", days=400)), FileChecksumState.OLD_BAD, False),
        (covered(entry(), trusted_since=NOW), FileChecksumState.OLD_OK, True),
    ],
    ids=["fresh match", "fresh mismatch", "old match", "old mismatch", "match at an unknown location"],
)
def test_a_checked_file_reads_the_verdict_the_files_dock_reads(
    file: CoveredFile, state: FileChecksumState, untrusted: bool
) -> None:
    """The age rule is the Files dock's own (#358): a stamp counts while it is recent *and* made where this machine
    trusts the record.

    **Test steps:**

    * ask for the state of a file checked a day ago, 400 days ago, and a day ago before the record was trusted
    * verify each verdict, and that only the last is old for the location's sake
    """
    row = row_checksum(file, WINDOW, NOW)

    assert row is not None
    assert (row.state, row.untrusted) == (state, untrusted)
    assert row.verified == file.entry.verified  # type: ignore[union-attr]


# endregion

# region The two lines of the pane


def local(moment: datetime) -> str:
    """A stamp as the pane writes it, in the machine's own time.

    :param moment: the instant.
    :returns: its date and time.
    """
    return f"{moment.astimezone():%Y-%m-%d %H:%M}"


@mark.parametrize(
    ("checksum", "bookkeeping", "expected"),
    [
        (None, False, (NO_CHECKSUM, NOT_COVERED)),
        (None, True, (NO_CHECKSUM, NOT_APPLICABLE)),
        (RowChecksum(FileChecksumState.MISSING), False, (NO_CHECKSUM, NEVER_CHECKED)),
        (RowChecksum(FileChecksumState.MALFORMED), False, ("Unreadable", NEVER_CHECKED)),
    ],
    ids=["not covered", "bookkeeping", "covered, never hashed", "unreadable entry"],
)
def test_a_file_with_nothing_checked_says_why_there_is_no_date(
    checksum: RowChecksum | None, bookkeeping: bool, expected: tuple[str, str]
) -> None:
    """The second line is never blank: *Never*, *Not covered* and *Not applicable* are three different reasons.

    **Test steps:**

    * ask for the lines of a file no record covers, of a record or screenshot, and of two covered files with no date
    * verify each pair
    """
    assert checksum_lines(checksum, bookkeeping=bookkeeping, now=NOW) == expected


@mark.parametrize(
    ("days", "state", "untrusted", "verdict", "note"),
    [
        (0.2, FileChecksumState.OK, False, "Matching", "today"),
        (1, FileChecksumState.OK, False, "Matching", "1 day ago"),
        (2, FileChecksumState.BAD, False, "Not matching", "2 days ago"),
        (400, FileChecksumState.OLD_OK, False, "Matching", "expired"),
        (400, FileChecksumState.OLD_BAD, False, "Not matching", "expired"),
        (3, FileChecksumState.OLD_OK, True, "Matching", "at another location"),
    ],
    ids=["today", "yesterday", "mismatch", "expired match", "expired mismatch", "another location"],
)
def test_a_checked_file_says_its_verdict_and_when_with_the_reason_it_may_not_count(
    days: float, state: FileChecksumState, untrusted: bool, verdict: str, note: str
) -> None:
    """The verdict alone on the first line; the date and, in brackets, how long ago -- or why it does not count.

    **Test steps:**

    * ask for the lines of files checked a day ago, 400 days ago and at another location
    * verify the verdict, the date, and the bracketed note, which for an old check is *expired*, not its age
    """
    verified = NOW - timedelta(days=days)

    lines = checksum_lines(RowChecksum(state, untrusted, verified), bookkeeping=False, now=NOW)

    assert lines == (verdict, f"{local(verified)} ({note})")


def test_a_state_with_no_date_is_never_dated_in_the_text() -> None:
    """The date text is only ever asked for a dated state; asked anyway, it says *Never*.

    **Test steps:**

    * ask for the date text of a state with no date
    * verify it says so
    """
    assert checked_text(RowChecksum(FileChecksumState.MISSING), NOW) == NEVER_CHECKED


# endregion

# region The ink of a problem


@mark.parametrize(
    ("checksum", "ink"),
    [
        (None, None),
        (RowChecksum(FileChecksumState.OK), None),
        (RowChecksum(FileChecksumState.OLD_OK), None),
        (RowChecksum(FileChecksumState.MISSING), None),
        (RowChecksum(FileChecksumState.BAD), BAD_INK),
        (RowChecksum(FileChecksumState.OLD_BAD), OLD_BAD_INK),
    ],
    ids=["none", "ok", "old ok", "no checksum", "bad", "old bad"],
)
def test_only_a_mismatch_is_drawn_as_a_problem(checksum: RowChecksum | None, ink: object) -> None:
    """Red for a file that did not match, orange when that finding has expired, the row's own ink otherwise.

    **Test steps:**

    * ask for the ink of a file of each state
    * verify only the two mismatches have one
    """
    assert warning_ink(checksum) == ink


# endregion
