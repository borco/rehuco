"""Tests for the level each checksum finding is logged at (#642).

One line per file, at a level that says how bad it is: the verifier does not log, and
:func:`~rehuco_core.log_report_findings` reads its report for a single verify and for each resource of a sweep.
"""

from typing import Any, Final

from pytest import mark
from rehuco_core import ChecksumReport, log_report_findings

VIDEO: Final = "lesson1.mp4"
ARCHIVE: Final = "extras/pack.zip"


@mark.parametrize(
    ("report", "level", "message"),
    [
        (ChecksumReport(statuses={ARCHIVE: "added"}), "INFO", f"Checksum added for new file {ARCHIVE}"),
        (ChecksumReport(statuses={ARCHIVE: "missing"}), "WARNING", f"File {ARCHIVE} is missing."),
        (
            ChecksumReport(unreadable=(ARCHIVE,), unadopted=(ARCHIVE,)),
            "WARNING",
            f"New file {ARCHIVE} could not be read, so no checksum was added.",
        ),
        (
            ChecksumReport(unreadable=(ARCHIVE,)),
            "WARNING",
            f"Listed file {ARCHIVE} could not be read.",
        ),
        (ChecksumReport(statuses={ARCHIVE: "malformed"}), "WARNING", f"The entry for {ARCHIVE} is malformed."),
        (ChecksumReport(unnamed_malformed=2), "WARNING", "Malformed entries with no name: 2."),
        (ChecksumReport(statuses={ARCHIVE: "mismatched"}), "ERROR", f"Checksum failed for {ARCHIVE}."),
    ],
)
def test_each_finding_is_logged_at_the_level_that_says_how_bad_it_is(
    report: ChecksumReport, level: str, message: str, caplog: Any
) -> None:
    """One line per file, whose level tells an added file, a warning and a failure apart (#642).

    **Test steps:**

    * log a report holding one kind of finding, with a prefix
    * check exactly one record, at the expected level, naming the file
    """
    with caplog.at_level("INFO", logger="rehuco_core.checksum_jobs"):
        log_report_findings(report, "painting: ")

    assert [(record.levelname, record.getMessage()) for record in caplog.records] == [(level, f"painting: {message}")]


def test_a_clean_file_is_not_logged(caplog: Any) -> None:
    """A matched file has nothing to say (#642).

    **Test steps:**

    * log a report of one matched file
    * check nothing was logged
    """
    with caplog.at_level("INFO", logger="rehuco_core.checksum_jobs"):
        log_report_findings(ChecksumReport(statuses={VIDEO: "matched"}))

    assert not caplog.records
