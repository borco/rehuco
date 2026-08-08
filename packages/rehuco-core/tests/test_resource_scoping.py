"""Tests for the resource-scoping rule -- what a record describes, asked in one voice (#250).

Every case names both formats, because the whole point of the module is that ``.rehu`` and the legacy
``.tc`` get the same answer: eight call sites used to spell the rule for themselves, agreed on
``info.rehu``, and were each wrong about ``info.tc`` in a different way.
"""

from pathlib import Path
from typing import Final

from pytest import mark, param
from rehuco_core import is_directory_scoped, is_record_name, resource_name

DIRECTORY: Final = Path("/fake/sculpting")


# region is_directory_scoped


@mark.parametrize(
    ("filename", "expected"),
    [
        param("info.rehu", True, id="info-rehu"),
        param("info.tc", True, id="info-tc"),
        param("foo.rehu", False, id="named-rehu"),
        param("foo.tc", False, id="named-tc"),
        param("Info.rehu", False, id="other-casing"),
        param("info.checksum", False, id="not-a-record"),
    ],
)
def test_only_the_info_records_describe_their_directory(filename: str, expected: bool) -> None:
    """``info.rehu`` and ``info.tc`` are directory-scoped; a named record and anything else are not.

    Casing is matched exactly, the way all eight call sites this replaced did: folding it would make
    ``Info.rehu`` and ``info.rehu`` two spellings of one resource on a share that hands back either,
    which the rename plan could not then reproduce.

    **Test steps:**

    * ask the predicate about a record filename
    * verify the answer
    """
    assert is_directory_scoped(DIRECTORY / filename) is expected


# endregion

# region is_record_name


@mark.parametrize(
    ("filename", "expected"),
    [
        param("info.rehu", True, id="rehu"),
        param("info.tc", True, id="tc"),
        param("foo.TC", True, id="upper-case-suffix"),
        param("info.tc.orig", False, id="conversion-backup"),
        param("info.checksum", False, id="manifest"),
        param("info00.jpg", False, id="screenshot"),
        param("tc", False, id="no-suffix-at-all"),
    ],
)
def test_a_record_is_a_rehu_or_a_legacy_tc(filename: str, expected: bool) -> None:
    """Both formats make a file a record, whatever the suffix's casing; a backup of one does not.

    The suffix folds where :func:`~rehuco_core.is_directory_scoped` is exact, and the two differ for a
    reason: a suffix is a format, and a ``.TC`` an old tool wrote describes a resource however it is
    spelled, while a filename is an identity the rename plan has to reproduce. A ``.orig`` answers
    ``False`` here and is excluded from a content walk on its own predicate (#253), so the two sets stay
    the ones their own modules define.

    **Test steps:**

    * ask the predicate about a filename
    * verify the answer
    """
    assert is_record_name(filename) is expected


# endregion

# region resource_name


@mark.parametrize(
    ("filename", "expected"),
    [
        param("info.rehu", "sculpting", id="info-rehu"),
        param("info.tc", "sculpting", id="info-tc"),
        param("foo.rehu", "foo.rehu", id="named-rehu"),
        param("foo.tc", "foo.tc", id="named-tc"),
    ],
)
def test_a_label_names_the_directory_for_a_directory_scoped_record(filename: str, expected: str) -> None:
    """A job's label names the folder for a directory-scoped record and the file for a file-scoped one.

    The one shape all three job modules read (:mod:`rehuco_core.checksum_jobs`,
    :mod:`rehuco_core.tc_import_job`, :mod:`rehuco_core.tc_backups_jobs`): every directory-scoped record
    is called ``info.rehu`` or ``info.tc``, so naming the file would give a queue of fifty jobs fifty
    identical rows.

    **Test steps:**

    * ask for a record's display name
    * verify it is the directory's name, or the record's own filename
    """
    assert resource_name(DIRECTORY / filename) == expected


# endregion
