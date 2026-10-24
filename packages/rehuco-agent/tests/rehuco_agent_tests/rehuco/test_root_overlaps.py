"""Tests for what the open ``.rehuco``'s roots overlap, as the main window's banner says it (#498): the spelled overlaps
at once, the ones through links when their check answers, what the scans met -- each pair once -- and starting over
with every file followed.

The check through links is ``test_root_overlap_check``'s subject: here it is a mock whose answers the tests deliver.
"""

import itertools
from pathlib import Path
from typing import Final
from unittest.mock import MagicMock
from uuid import uuid4

from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco.root_overlap_check import RootOverlapCheck
from rehuco_agent.rehuco.root_overlaps import RootOverlaps
from rehuco_core import HardlinkedRecord, MappedRoot, RootOverlap

from rehuco_agent_tests.delete_at_teardown import DeleteAtTeardown
from rehuco_agent_tests.mapped_roots import mapped_root

BASE: Final = Path.cwd() / "fake"
OUTER: Final = mapped_root(BASE / "lib", "lib")
INNER: Final = mapped_root(BASE / "lib" / "inner", "inner")
OTHER: Final = mapped_root(BASE / "other", "other")
LINKED: Final = mapped_root(BASE / "link", "link")
"""A root no spelling relates to :data:`OUTER`, which a link puts inside it."""

HARDLINK: Final = HardlinkedRecord(OUTER.root_id, "a/info.rehu", OUTER.root_id, "b/info.rehu")


def roots_of(*roots: MappedRoot) -> tuple[MappedRoot, ...]:
    """The roots of an open file, in order.

    :param roots: the roots.
    :returns: them, as the catalog hands them over.
    """
    return roots


def line(overlap: RootOverlap) -> str:
    """What the banner says of an overlap.

    :param overlap: the overlap.
    :returns: its line.
    """
    return f"Roots overlap: {overlap.message}. Its records are cataloged under the inner root only."


@fixture(name="check")
def fixture_check(mocker: MockerFixture) -> MagicMock:
    """Stand in for the check through links, its serials counting from 1.

    :param mocker: pytest-mock fixture.
    :returns: the check every :class:`RootOverlaps` built from now on gets.
    """
    check = mocker.MagicMock(spec=RootOverlapCheck)
    check.answered = mocker.MagicMock()
    check.among.side_effect = itertools.count(1)
    mocker.patch("rehuco_agent.rehuco.root_overlaps.RootOverlapCheck", return_value=check)
    return check


@fixture(name="overlaps")
def fixture_overlaps(qtbot: QtBot, check: MagicMock, delete_at_teardown: DeleteAtTeardown) -> RootOverlaps:
    """The overlaps under test, over the mock check, following nothing yet.

    :param qtbot: pytest-qt fixture, for the application.
    :param check: the mock check.
    :param delete_at_teardown: deletes it when the test ends.
    :returns: the overlaps.
    """
    del qtbot, check
    return delete_at_teardown(RootOverlaps())


@fixture(name="changed")
def fixture_changed(overlaps: RootOverlaps) -> MagicMock:
    """Count what :attr:`RootOverlaps.changed` says.

    :param overlaps: the overlaps.
    :returns: the slot it is connected to.
    """
    slot = MagicMock()
    overlaps.changed.connect(slot)
    return slot


def answer(check: MagicMock, serial: int, *found: RootOverlap) -> None:
    """Deliver an answer of the check through links, as it would on the GUI thread.

    :param check: the mock check.
    :param serial: the check's serial.
    :param found: what it found.
    """
    (slot,) = check.answered.connect.call_args.args
    slot(serial, found)


def test_a_nesting_file_is_flagged_at_once_and_its_links_checked(
    overlaps: RootOverlaps, check: MagicMock, changed: MagicMock
) -> None:
    """The spelled overlap needs no disk, so it is said the moment the file is followed; the check through links is
    started over its roots, the unreachable ones skipped.

    **Test steps:**

    * follow a file whose second root is inside its first, one root unreachable
    * verify one line naming the pair, one change said, and the check started over the roots and the unreachable root
    """
    roots = roots_of(OUTER, INNER)

    overlaps.follow(roots, {INNER.root_id})

    assert overlaps.messages == [line(RootOverlap(OUTER, INNER.path, encloses=True))]
    changed.assert_called_once_with()
    check.among.assert_called_once_with(roots, {INNER.root_id})


def test_the_check_through_links_adds_what_only_links_reveal(
    overlaps: RootOverlaps, check: MagicMock, changed: MagicMock
) -> None:
    """Two roots no spelling relates are clean until the check answers that one is inside the other.

    **Test steps:**

    * follow a file of two unrelated spellings
    * verify nothing to say
    * answer the check with an overlap
    * verify its line, and a second change said
    """
    overlaps.follow(roots_of(OUTER, LINKED), ())
    assert overlaps.messages == []

    answer(check, 1, RootOverlap(OUTER, LINKED.path, encloses=True))

    assert overlaps.messages == [line(RootOverlap(OUTER, LINKED.path, encloses=True))]
    assert changed.call_count == 2


def test_an_answer_about_a_file_no_longer_followed_is_dropped(
    overlaps: RootOverlaps, check: MagicMock, changed: MagicMock
) -> None:
    """A late answer about the previous file must not flag the one open now; an empty answer has nothing to add.

    **Test steps:**

    * follow a file, then another
    * answer the first file's check with an overlap, then the second's with nothing
    * verify nothing to say, and only the two follows said a change
    """
    overlaps.follow(roots_of(OUTER, LINKED), ())
    overlaps.follow(roots_of(OUTER, LINKED), ())

    answer(check, 1, RootOverlap(OUTER, LINKED.path, encloses=True))
    answer(check, 2)

    assert overlaps.messages == []
    assert changed.call_count == 2


def test_following_a_clean_file_or_none_takes_the_flags_down(overlaps: RootOverlaps, check: MagicMock) -> None:
    """Every follow starts over: a clean file has nothing to say, and neither does no file -- whose roots are not
    checked, as a file of one root's are not.

    **Test steps:**

    * follow a nesting file, then a clean one: verify the line, then none
    * follow a nesting file, then none: verify nothing to say and no duplicates
    * follow a file of one root
    * verify the check was started for the two files of two roots only
    """
    overlaps.follow(roots_of(OUTER, INNER), ())
    assert len(overlaps.messages) == 1
    overlaps.follow(roots_of(OUTER, OTHER), ())
    assert overlaps.messages == []

    overlaps.follow(roots_of(OUTER, INNER), ())
    overlaps.follow(None, ())
    assert overlaps.messages == []
    assert overlaps.duplicates == frozenset()

    overlaps.follow(roots_of(OUTER), ())
    assert check.among.call_count == 3


def test_a_scan_that_met_a_root_flags_the_pair_until_a_clean_scan_of_it(
    overlaps: RootOverlaps, changed: MagicMock
) -> None:
    """A scan replaces what its root's last scan reported: a root met inside it and a record under a second name are
    flagged, and the next scan that meets neither takes both down.

    **Test steps:**

    * follow a clean file, and finish a scan of its first root that met the second and a hardlinked record
    * verify the pair's line and the hardlink's
    * finish a clean scan of the same root
    * verify nothing to say, and a change said for each scan
    """
    overlaps.follow(roots_of(OUTER, OTHER), ())

    overlaps.scan_finished(OUTER.root_id, {OTHER.root_id}, [HARDLINK])
    assert overlaps.messages == [
        line(RootOverlap(OUTER, OTHER.path, encloses=True)),
        "1 record reached under a second name (a hardlink) is cataloged once, under one of the names; the log names "
        "them.",
    ]

    overlaps.scan_finished(OUTER.root_id, (), ())
    assert overlaps.messages == []
    assert changed.call_count == 3


def test_a_scan_that_reports_what_was_already_known_says_no_change(overlaps: RootOverlaps, changed: MagicMock) -> None:
    """Scans end often; one that changes nothing must not have the banner rebuilt.

    **Test steps:**

    * follow a file, and finish the same scan twice
    * verify the follow and the first scan said a change, the second did not
    """
    overlaps.follow(roots_of(OUTER, OTHER), ())

    overlaps.scan_finished(OUTER.root_id, {OTHER.root_id}, [HARDLINK, HARDLINK])
    overlaps.scan_finished(OUTER.root_id, {OTHER.root_id}, [HARDLINK])

    assert changed.call_count == 2


def test_a_scan_of_the_later_root_words_the_pair_from_the_earlier_one(overlaps: RootOverlaps) -> None:
    """The pair is worded the way the spelled check words it -- the root earlier in the file first -- whichever root's
    scan met the other; a root the file does not hold is not a pair.

    **Test steps:**

    * follow a file, and finish a scan of its second root that met the first and a root the file does not hold
    * verify one line: the second root containing the first
    """
    overlaps.follow(roots_of(OUTER, OTHER), ())

    overlaps.scan_finished(OTHER.root_id, {OUTER.root_id, uuid4()}, ())

    assert overlaps.messages == [line(RootOverlap(OUTER, OTHER.path, encloses=False))]


def test_a_pair_seen_spelled_and_met_by_a_scan_is_said_once(overlaps: RootOverlaps) -> None:
    """The same pair found two ways is one overlap.

    **Test steps:**

    * follow a nesting file, and finish a scan of the outer root that met the inner one
    * verify one line
    """
    overlaps.follow(roots_of(OUTER, INNER), ())

    overlaps.scan_finished(OUTER.root_id, {INNER.root_id}, ())

    assert overlaps.messages == [line(RootOverlap(OUTER, INNER.path, encloses=True))]


@mark.parametrize("keep_scans", [True, False])
def test_editing_the_roots_keeps_what_the_scans_said_of_the_roots_still_there(
    overlaps: RootOverlaps, keep_scans: bool
) -> None:
    """The same catalog, its roots edited, keeps the scans' pairs and hardlinks between roots it still holds; another
    catalog keeps nothing.

    **Test steps:**

    * follow a file of three roots; finish a scan of the first that met the second and a hardlink into the third
    * follow the file without its third root, keeping the scans or not
    * verify the pair alone is still said when kept, nothing when not
    * follow it without its second root too, keeping the scans
    * verify nothing to say
    """
    third = mapped_root(BASE / "third", "third")
    overlaps.follow(roots_of(OUTER, OTHER, third), ())
    overlaps.scan_finished(
        OUTER.root_id, {OTHER.root_id}, [HardlinkedRecord(OUTER.root_id, "a.rehu", third.root_id, "b.rehu")]
    )

    overlaps.follow(roots_of(OUTER, OTHER), (), keep_scans=keep_scans)
    assert overlaps.messages == ([line(RootOverlap(OUTER, OTHER.path, encloses=True))] if keep_scans else [])

    overlaps.follow(roots_of(OUTER), (), keep_scans=True)
    assert overlaps.messages == []


def test_the_duplicates_are_the_later_root_of_each_pair(overlaps: RootOverlaps, check: MagicMock) -> None:
    """The root Add Root would refuse now is the later one of each pair, however the pair was found.

    **Test steps:**

    * follow a file whose second root is inside its first, with a third a link puts inside the first and a fourth
    * answer the check with the link's overlap, and finish a scan of the fourth root that met the first
    * verify the second, third and fourth roots are the duplicates, and the first is not
    """
    overlaps.follow(roots_of(OUTER, INNER, LINKED, OTHER), ())
    answer(check, 1, RootOverlap(OUTER, LINKED.path, encloses=True))
    overlaps.scan_finished(OTHER.root_id, {OUTER.root_id}, ())

    assert overlaps.duplicates == {INNER.root_id, LINKED.root_id, OTHER.root_id}


def test_records_with_a_second_name_are_counted_in_one_line(overlaps: RootOverlaps) -> None:
    """Many hardlinks are one line, its count and verb agreeing.

    **Test steps:**

    * follow a file, and finish a scan that found two records under a second name
    * verify the plural line
    """
    overlaps.follow(roots_of(OUTER), ())

    overlaps.scan_finished(
        OUTER.root_id, (), [HARDLINK, HardlinkedRecord(OUTER.root_id, "c/info.rehu", OUTER.root_id, "d/info.rehu")]
    )

    assert overlaps.messages == [
        "2 records reached under a second name (a hardlink) are cataloged once, under one of the names; the log "
        "names them."
    ]


def test_stopping_stops_the_check(overlaps: RootOverlaps, check: MagicMock) -> None:
    """The window going stops what is still being checked through links.

    **Test steps:**

    * stop the overlaps
    * verify the check was stopped
    """
    overlaps.stop()

    check.stop.assert_called_once_with()
