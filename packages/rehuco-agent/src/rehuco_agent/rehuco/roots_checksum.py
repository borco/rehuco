"""What the Roots view says about a file's checksum, in one place (#457).

A row shows a state icon, and the details pane two lines; both come from the same three facts about a file -- what
the record that covers it last found, when, and whether the file is bookkeeping a record never checksums. This module
turns those into a :class:`RowChecksum` (the model's data) and into the pane's words, so the delegate, the pane and
the model cannot disagree, and none of the wording is buried in a widget.

**A file reads two ways.** It has *no checksum* -- the record does not list it, or lists it with no hash (the
*unexpected* entry of a record written before #467 is one), or no record covers it -- or it has a checked
result, aged by :func:`~rehuco_agent.documents.files_rows.checksum_verdict_for`: *matching* or *not matching*, and
old when the check has expired or was made where this machine did not trust the record yet (#358). A claim moved here
from another record (#257, #467) has a hash and no result yet: it reads *not checked yet*, old and not a warning.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from PySide6.QtGui import QColor
from rehuco_core import CoveredFile, FileKind

from ..documents.files_rows import (
    OLD_CHECKSUM_STATES,
    FileChecksumState,
    checksum_verdict_for,
)

BOOKKEEPING_KINDS: Final = frozenset(
    {
        FileKind.OWN_RECORD,
        FileKind.OWN_SCREENSHOT,
        FileKind.OWN_MANIFEST,
        FileKind.FOREIGN_RECORD,
        FileKind.FOREIGN_SIDECAR,
    }
)
"""The kinds a record, a checksum file or a screenshot is listed as: files a record never checksums."""

VERDICT_WORDS: Final = {
    FileChecksumState.OK: "Matching",
    FileChecksumState.OLD_OK: "Matching",
    FileChecksumState.BAD: "Not matching",
    FileChecksumState.OLD_BAD: "Not matching",
    FileChecksumState.MISSING: "No checksum",
    FileChecksumState.MALFORMED: "Unreadable",
}
"""The first line of the pane's *Checksum* row: the verdict alone. When it was reached, and whether it still counts, is
the second line's."""

NO_CHECKSUM: Final = "No checksum"
NOT_CHECKED_YET: Final = "Not checked yet"
"""The verdict of a claim moved here from another record (#467): a hash this record has never checked, so neither
*matching* nor *not matching* is true of it yet."""

NEVER_CHECKED: Final = "Never"
NOT_COVERED: Final = "Not covered"
NOT_APPLICABLE: Final = "Not applicable"
"""The second line when there is no date: a covered file never hashed, a file no record covers, and a record, checksum
file or screenshot, which no record checksums."""

BAD_INK: Final = QColor(214, 69, 69)
"""What a file that did not match is drawn in -- its name and its icon -- off the selection band."""

OLD_BAD_INK: Final = QColor(217, 130, 43)
"""The same for a file whose mismatch was found by a check that has since expired: the same problem, less certain."""

EXPIRED_NOTE: Final = "expired"
OTHER_LOCATION_NOTE: Final = "at another location"


@dataclass(frozen=True, slots=True)
class RowChecksum:
    """What a covered file's row shows.

    :param state: the file's state.
    :param untrusted: whether the stamp is old only because this machine has not trusted the record where it is, or
        the entry is a claim moved here that this record has not checked yet.
    :param verified: when the file was last checked, or ``None`` when it never was.
    """

    state: FileChecksumState
    untrusted: bool = False
    verified: datetime | None = None


def row_checksum(covered: CoveredFile | None, stale_after: timedelta, now: datetime) -> RowChecksum | None:
    """The state a listing's covered file reads as.

    :param covered: what the record that covers the file says, or ``None`` when no record covers it.
    :param stale_after: how long a check stays fresh.
    :param now: the instant every file of one listing is aged against.
    :returns: the row's state; ``None`` when no record covers the file.
    """
    if covered is None:
        return None
    if covered.malformed:
        return RowChecksum(FileChecksumState.MALFORMED)
    entry = covered.entry
    if entry is None or entry.digest is None:
        return RowChecksum(FileChecksumState.MISSING)
    state, untrusted = checksum_verdict_for(entry, stale_after, now, covered.trusted_since)
    return RowChecksum(state, untrusted, entry.verified)


def checksum_lines(checksum: RowChecksum | None, *, bookkeeping: bool, now: datetime) -> tuple[str, str]:
    """The two lines of the pane's *Checksum* block for a file.

    :param checksum: the file's state, or ``None`` when no record covers it.
    :param bookkeeping: whether the file is a record, a checksum file or a screenshot.
    :param now: the instant ages are told against.
    :returns: the verdict, and the line under it: the date with its age and why it may not count, else a short reason
        there is none.
    """
    if checksum is None:
        return NO_CHECKSUM, NOT_APPLICABLE if bookkeeping else NOT_COVERED
    verdict = VERDICT_WORDS.get(checksum.state, NO_CHECKSUM)
    if checksum.verified is None:
        # a dateless state is untrusted only when it is a moved claim (checksum_verdict_for)
        return NOT_CHECKED_YET if checksum.untrusted else verdict, NEVER_CHECKED
    return verdict, checked_text(checksum, now)


def checked_text(checksum: RowChecksum, now: datetime) -> str:
    """When a file was last checked, as the pane writes it: ``2025-09-02 08:29 (400 days ago, check expired)``.

    :param checksum: a state that has a date.
    :param now: the instant the age is told against.
    :returns: the text; *Never* for a state with no date.
    """
    verified = checksum.verified
    if verified is None:
        return NEVER_CHECKED
    if checksum.untrusted:
        note = OTHER_LOCATION_NOTE
    elif checksum.state in OLD_CHECKSUM_STATES:
        note = EXPIRED_NOTE
    else:
        days = (now - verified).days
        note = "today" if days < 1 else f"{days} day{'' if days == 1 else 's'} ago"
    return f"{verified.astimezone():%Y-%m-%d %H:%M} ({note})"


def warning_ink(checksum: RowChecksum | None) -> QColor | None:
    """The ink a problem file is drawn in, or ``None`` for the row's own.

    :param checksum: the file's state.
    :returns: red for a file that did not match, orange when that is an expired result, else ``None``.
    """
    if checksum is None:
        return None
    if checksum.state is FileChecksumState.BAD:
        return BAD_INK
    if checksum.state is FileChecksumState.OLD_BAD:
        return OLD_BAD_INK
    return None
