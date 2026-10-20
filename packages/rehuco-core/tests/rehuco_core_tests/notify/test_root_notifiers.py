"""Tests for keeping one file notifier per root of the open ``.rehuco`` (#511).

The notifiers are fakes recording how they were made, started and stopped; what a polled root sweeps is read from a
mocked cache (#545).
"""

import sqlite3
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from pytest import LogCaptureFixture, fixture
from pytest_mock import MockerFixture
from rehuco_core import CatalogCache, ChangeFeed, RecordSignature, RenameCoordinator
from rehuco_core.notify import RootNotifiers, WatchedFolder

MODULE: Final = "rehuco_core.notify.root_notifiers"

FIRST: Final = UUID("00000000-0000-0000-0000-0000000000c1")
SECOND: Final = UUID("00000000-0000-0000-0000-0000000000c2")

ANCHOR: Final = Path(Path.cwd().anchor)


class FakeNotifier:
    """A notifier that only notes what happens to it.

    :param folder: what it watches.
    :param feed: where it publishes.
    :param known: what a sweep would compare.
    :param coordinator: the rename coordinator.
    """

    def __init__(self, folder: WatchedFolder, feed: ChangeFeed, known: Any, coordinator: RenameCoordinator) -> None:
        self.folder: Final = folder
        self.feed: Final = feed
        self.known: Final = known
        self.coordinator: Final = coordinator
        self.started = False
        self.stopped = False

    def start(self) -> None:
        """Note the start."""
        self.started = True

    def stop(self) -> None:
        """Note the stop."""
        self.stopped = True


@fixture(name="made")
def fixture_made(mocker: MockerFixture) -> list[FakeNotifier]:
    """Replace the module's notifier with :class:`FakeNotifier`, keeping each one made.

    :param mocker: pytest-mock fixture.
    :returns: the notifiers made, in order.
    """
    made: list[FakeNotifier] = []

    def make(*args: Any) -> FakeNotifier:
        """A fake notifier, kept."""
        notifier = FakeNotifier(*args)
        made.append(notifier)
        return notifier

    mocker.patch(f"{MODULE}.FileNotifier", side_effect=make)
    return made


def test_following_starts_a_notifier_per_root_and_keeps_those_unchanged(made: list[FakeNotifier]) -> None:
    """Each root gets a started notifier of its folder, on the feed and coordinator given; following the same roots
    again changes nothing.

    **Test steps:**

    * follow two roots, then the same two again
    * verify two notifiers were made and started, each for its root, and none stopped
    """
    feed, coordinator = ChangeFeed(), RenameCoordinator()
    notifiers = RootNotifiers(feed, coordinator)
    roots = {FIRST: ANCHOR / "library", SECOND: ANCHOR / "packs"}
    cache = ANCHOR / "cache.rehudb"

    notifiers.follow(roots, cache)
    notifiers.follow(roots, cache)

    assert [notifier.folder for notifier in made] == [
        WatchedFolder(ANCHOR / "library", FIRST),
        WatchedFolder(ANCHOR / "packs", SECOND),
    ]
    assert all(notifier.started and not notifier.stopped for notifier in made)
    assert all((notifier.feed, notifier.coordinator) == (feed, coordinator) for notifier in made)
    assert notifiers.root_ids == {FIRST, SECOND}


def test_a_root_gone_is_stopped_and_a_root_moved_is_restarted(made: list[FakeNotifier]) -> None:
    """A root no longer followed has its notifier stopped; a root whose folder changed gets a new one.

    **Test steps:**

    * follow two roots; then follow only the second, at another folder
    * verify both first notifiers stopped, and one new one watches the second root's new folder
    """
    notifiers = RootNotifiers(ChangeFeed())
    cache = ANCHOR / "cache.rehudb"
    notifiers.follow({FIRST: ANCHOR / "library", SECOND: ANCHOR / "packs"}, cache)

    notifiers.follow({SECOND: ANCHOR / "moved"}, cache)

    first, second, moved = made
    assert first.stopped and second.stopped
    assert moved.folder == WatchedFolder(ANCHOR / "moved", SECOND) and not moved.stopped
    assert notifiers.root_ids == {SECOND}


def test_another_cache_restarts_every_root_and_a_stop_stops_them_all(made: list[FakeNotifier]) -> None:
    """The rows a sweep compares come from the cache, so another cache restarts every root; a stop stops every
    notifier and forgets the cache, so following again starts afresh.

    **Test steps:**

    * follow a root over one cache, then over another; then stop; then follow it over the second cache again
    * verify each change of cache, and the follow after the stop, made a new notifier, and the stop stopped all
    """
    notifiers = RootNotifiers(ChangeFeed())
    roots = {FIRST: ANCHOR / "library"}

    notifiers.follow(roots, ANCHOR / "one.rehudb")
    notifiers.follow(roots, ANCHOR / "two.rehudb")
    notifiers.stop()
    assert not notifiers.root_ids
    notifiers.follow(roots, ANCHOR / "two.rehudb")

    assert len(made) == 3
    assert made[0].stopped and made[1].stopped and not made[2].stopped


def test_a_polled_root_sweeps_the_records_its_rows_name(mocker: MockerFixture) -> None:
    """What a polled root's sweep compares is every record the cache holds under it, by its absolute path, with the
    signature it was read at -- none for one that could not be read, or whose signature a schema step cleared.

    **Test steps:**

    * mock the cache, its rows under the root three: one read at a signature, one unreadable, one with no
      modification time
    * read what the root's sweep would compare
    * verify the cache at the path was asked for the root's rows, and each record's path and expected signature
    """
    root, cache_path = ANCHOR / "library", ANCHOR / "cache.rehudb"
    cache = mocker.MagicMock()
    cache.__enter__.return_value = cache
    cache.signatures.return_value = {
        "a/info.rehu": RecordSignature("a/info.rehu", 5, 7),
        "b/info.rehu": RecordSignature("b/info.rehu", 5, 7, "unreadable"),
        "c/info.tc": RecordSignature("c/info.tc", 0, 7),
    }
    opened = mocker.patch.object(CatalogCache, "open", return_value=cache)

    known = RootNotifiers.known_records(cache_path, FIRST, root)()

    opened.assert_called_once_with(cache_path)
    cache.signatures.assert_called_once_with(FIRST)
    assert known == {
        root / "a" / "info.rehu": (5, 7),
        root / "b" / "info.rehu": None,
        root / "c" / "info.tc": None,
    }


def test_a_cache_that_cannot_be_read_gives_a_sweep_nothing_and_is_logged(
    mocker: MockerFixture, caplog: LogCaptureFixture
) -> None:
    """A sweep is no reason to fail: a cache that cannot be opened answers nothing to compare, and says so.

    **Test steps:**

    * make opening the cache fail
    * verify the reader answers nothing, and the failure was logged as an error
    """
    cache_path = ANCHOR / "cache.rehudb"
    mocker.patch.object(CatalogCache, "open", side_effect=sqlite3.OperationalError("unable to open database file"))

    with caplog.at_level("ERROR", logger=MODULE):
        assert RootNotifiers.known_records(cache_path, FIRST, ANCHOR)() == {}

    assert f"Could not read the cache {cache_path} to poll a root" in caplog.text
