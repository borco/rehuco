"""What a finished checksum run says ([[data-model#checksums]], #204, #457, #467).

The words of a run's report, apart from the jobs that make one: the one-line summary a log record, the Tasks row and
the document's banner share, the rule for a clean run, and the order verdicts are counted in. Kept beside
:mod:`rehuco_core.checksum_jobs` rather than inside it, so the jobs read as what they do and this reads as what
they say.
"""

from typing import Final

from .rehu_checksums import ChecksumReport
from .rehu_content_files import ContentExclusionTier

VERIFY_FINDING: Final = "Checksums verified: {summary}."
GENERATE_FINDING: Final = "Checksums recorded: {summary}."
"""What a finished run says -- the document's inline banner and the Tasks dock's row, one wording (#457).

The **summary**, not the file list: a tutorial of two hundred videos reports two hundred statuses, and a row is not
where those belong -- the log has the detail, and the per-file view is #244's."""

CLEAN_STATUSES: Final = frozenset({"matched", "added"})
"""The verdicts that are not a finding about the files.

``added`` is a *report* word rather than a resting state ([[data-model#checksums]], #467) -- the run
hashed a file the record held no hash for and recorded it ``matched`` -- so a resource whose only news is a
new file has come back clean."""

STATUS_ORDER: Final = ("matched", "mismatched", "missing", "added", "malformed")
"""The order a summary counts verdicts in: what was checked first, then what the run added, then what it could
not read -- ``"210 matched, 2 mismatched, 3 added"``. A status this build does not know follows, alphabetically."""


def status_counts_text(counts: dict[str, int]) -> list[str]:
    """One ``"<count> <status>"`` part per verdict counted, in :data:`STATUS_ORDER`.

    :param counts: how many files came back with each status.
    :returns: the parts, for a summary to join.
    """
    known = [status for status in STATUS_ORDER if status in counts]
    others = sorted(status for status in counts if status not in STATUS_ORDER)
    return [f"{counts[status]} {status}" for status in (*known, *others)]


def checksum_report_is_clean(report: ChecksumReport) -> bool:
    """Whether a run found nothing to act on.

    :param report: what the run established.
    :returns: whether every verdict was a clean one and nothing went unread.
    """
    return (
        all(status in CLEAN_STATUSES for status in report.statuses.values())
        and not report.unreadable
        and not report.unnamed_malformed
        # a run that could not list part of the tree is not a clean run, whether or not the record
        # happened to hold entries under the branch it could not see (#245)
        and not report.unreadable_directories
    )


PRUNE_REASONS: Final[dict[ContentExclusionTier, str]] = {
    "structural": "it is a record's own bookkeeping, which is never a resource's content",
    "junk": "its name matches an excluded-files pattern",
}
"""How each exclusion tier reads in the log line naming a dropped entry (#254).

The sentence lives here rather than in :mod:`rehuco_core.rehu_content_files`, which answers *which tier*
and has no reader to address; a tier a build does not know cannot occur, since both ends read the same
:data:`~rehuco_core.ContentExclusionTier`."""


def checksum_report_summary(report: ChecksumReport) -> str:
    """One line saying what a run established, for a log record and a banner alike.

    Counts rather than names: a tutorial of two hundred videos reports two hundred statuses, and the
    question a verify raises is *how many of what*. Which files those were is the record's answer, and
    the dock that shows it is #244's.

    :param report: what the run established.
    :returns: the summary, e.g. ``"210 matched, 2 mismatched, 1 missing"``, or a plain statement when
        the run established nothing.
    """
    counts: dict[str, int] = {}
    for status in report.statuses.values():
        counts[status] = counts.get(status, 0) + 1
    parts = status_counts_text(counts)
    if report.skipped:
        parts.append(f"{len(report.skipped)} skipped")
    if report.unreadable:
        parts.append(f"{len(report.unreadable)} unreadable")
    if report.unnamed_malformed:
        parts.append(f"{report.unnamed_malformed} unnamed malformed")
    if report.seed is not None:
        # named rather than counted, because a seed happens once in a resource's life and which file
        # it came from is the thing a reader wants back later (#243)
        parts.append(f"seeded {len(report.seed.entries)} from {report.seed.manifest.name}")
        if report.seed.dropped:
            count = len(report.seed.dropped)
            parts.append(f"{count} seed line{'' if count == 1 else 's'} dropped")
        if report.seed.ignored:
            count = len(report.seed.ignored)
            parts.append(f"{count} manifest{'' if count == 1 else 's'} ignored")
        if report.seed.retired:
            # named rather than counted, for the reason the seed itself is: retirement happens once in a
            # resource's life, and *which file stopped being the authority* is what a reader wants back
            parts.append(f"retired {', '.join(manifest.name for manifest in report.seed.retired)}")
    if report.pruned:
        # counted here and named in the log (:meth:`ChecksumJob.__log_pruned`), because this is the one
        # part of a run that takes something away and a reader has to be able to find out what (#254)
        parts.append(f"{len(report.pruned)} pruned")
    if report.moved:
        # the other half of what a record catching up with the coverage rule does, and the half that has
        # to be visible: these entries left this record for another one, rather than ceasing to exist
        parts.append(f"{len(report.moved)} moved")
    if report.unreadable_directories:
        # the one part that is not a count of files: a branch that would not list has no files to
        # count, which is exactly why it has to be said out loud (#245)
        count = len(report.unreadable_directories)
        parts.append(f"{count} unreadable director{'y' if count == 1 else 'ies'}")
    return ", ".join(parts) if parts else "nothing to check"
