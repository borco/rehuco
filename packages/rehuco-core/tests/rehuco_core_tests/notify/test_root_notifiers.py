"""Tests for keeping one file notifier per root of the open ``.rehuco`` (#511).

The notifiers are fakes recording how they were made, started and stopped; what a polled root sweeps is read from a
real cache under ``tmp_path``.
"""

from pathlib import Path
from typing import Any, Final
from uuid import UUID

from pytest import LogCaptureFixture, fixture
from pytest_mock import MockerFixture
from rehuco_core import CatalogCache, CatalogRecord, ChangeFeed, RecordKind, RehucoFile, RenameCoordinator
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


def test_a_polled_root_sweeps_the_records_its_rows_name(tmp_path: Path) -> None:
    """What a polled root's sweep compares is every record the cache holds under it, by its absolute path, with the
    signature it was read at -- none for one that could not be read, or whose signature a schema step cleared.

    **Test steps:**

    * scan three records into a real cache: one read at a signature, one unreadable, one with no modification time
    * read what the root's sweep would compare
    * verify each record's path and expected signature
    """
    rehuco = RehucoFile.new()
    rehuco.add_root(tmp_path / "library")
    (root,) = rehuco.roots
    cache_path = tmp_path / "cache.rehudb"
    with CatalogCache.open(cache_path) as cache:
        cache.reconcile_roots(rehuco.roots)
        cache.apply_root_scan(
            root.root_id,
            [
                CatalogRecord("a/info.rehu", RecordKind.REHU, mtime_ns=5, size=7),
                CatalogRecord("b/info.rehu", RecordKind.REHU, mtime_ns=5, size=7, error="unreadable"),
                CatalogRecord("c/info.tc", RecordKind.TC, mtime_ns=0, size=7),
            ],
        )

    known = RootNotifiers.known_records(cache_path, root.root_id, root.path)()

    assert known == {
        root.path / "a" / "info.rehu": (5, 7),
        root.path / "b" / "info.rehu": None,
        root.path / "c" / "info.tc": None,
    }


def test_a_cache_that_cannot_be_read_gives_a_sweep_nothing_and_is_logged(
    tmp_path: Path, caplog: LogCaptureFixture
) -> None:
    """A sweep is no reason to fail: a cache that cannot be opened answers nothing to compare, and says so.

    **Test steps:**

    * point the reader at a folder where the cache should be
    * verify it answers nothing, and the failure was logged as an error
    """
    cache_path = tmp_path / "cache.rehudb"
    cache_path.mkdir()

    with caplog.at_level("ERROR", logger=MODULE):
        assert RootNotifiers.known_records(cache_path, FIRST, tmp_path)() == {}

    assert f"Could not read the cache {cache_path} to poll a root" in caplog.text
