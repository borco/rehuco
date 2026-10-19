"""Tests for turning a watched folder's observations into the change feed's events (#511,
[[mounts-and-storage#out-of-band]]).

:meth:`ChangeCoalescer.events_of` and :meth:`ChangeCoalescer.compose` are pure, and tested on paths alone; the daemon
thread that batches and publishes is tested with its timing constants patched, and the clock replaced where the cap on
waiting is what is asserted.
"""

import queue
import threading
from itertools import chain, repeat
from pathlib import Path
from types import SimpleNamespace
from typing import Final
from uuid import UUID

from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_core import Changed, ChangeEvent, ChangeFeed, FolderChanged, KeyRelocation, Moved, ResourceKey, RootStale
from rehuco_core.notify import ChangeCoalescer, RawChange, RawChangeKind

from rehuco_core_tests.concurrency import wait_until

FOLDER: Final = Path(Path.cwd().anchor) / "fake" / "library"
"""The watched folder; never touched."""

ROOT_ID: Final = UUID("00000000-0000-0000-0000-0000000000a1")

MODULE: Final = "rehuco_core.notify.change_coalescer"

CREATED: Final = RawChangeKind.CREATED
MODIFIED: Final = RawChangeKind.MODIFIED
DELETED: Final = RawChangeKind.DELETED
MOVED: Final = RawChangeKind.MOVED


def key(*parts: str) -> ResourceKey:
    """A key beneath :data:`FOLDER`.

    :param parts: the components below it.
    :returns: the key.
    """
    return ResourceKey(FOLDER.joinpath(*parts))


def change(kind: RawChangeKind, *parts: str, to: tuple[str, ...] = (), directory: bool = False) -> RawChange:
    """An observation beneath :data:`FOLDER`.

    :param kind: what happened.
    :param parts: the entry's components below the folder.
    :param to: a move's destination components, below the folder.
    :param directory: whether the entry is a folder.
    :returns: the observation.
    """
    return RawChange(kind, FOLDER.joinpath(*parts), FOLDER.joinpath(*to) if to else None, directory)


def events_of(*batch: RawChange, root_id: UUID | None = ROOT_ID) -> list[ChangeEvent]:
    """What a batch adds up to, under :data:`FOLDER`.

    :param batch: the observations.
    :param root_id: the folder's root.
    :returns: the events.
    """
    return ChangeCoalescer.events_of(batch, FOLDER, root_id)


# region What a batch adds up to


def test_an_overflow_makes_the_root_stale_after_what_was_seen() -> None:
    """A backend that lost events saw less than what changed, but what it saw still holds: it is published, and then
    the root is stale.

    **Test steps:**

    * coalesce a modification, an overflow and a creation under a root
    * verify the two files changed and the folder relisted are published, then ``RootStale`` for the root
    """
    batch = (change(MODIFIED, "a.rehu"), RawChange(RawChangeKind.OVERFLOW, FOLDER), change(CREATED, "b.rehu"))

    assert events_of(*batch) == [
        Changed((key("a.rehu"), key("b.rehu"))),
        FolderChanged(ResourceKey(FOLDER)),
        RootStale(ROOT_ID),
    ]


def test_an_overflow_in_a_folder_under_no_root_changes_the_whole_folder() -> None:
    """A loose folder has no root to call stale, so its whole listing has changed.

    **Test steps:**

    * coalesce an overflow in a folder with no root id
    * verify the batch is one ``FolderChanged`` for the watched folder
    """
    assert events_of(RawChange(RawChangeKind.OVERFLOW, FOLDER), root_id=None) == [FolderChanged(ResourceKey(FOLDER))]


def test_an_atomic_save_over_an_existing_file_is_that_file_changed_and_relists_nothing() -> None:
    """NTFS reports an atomic save as the temporary sibling written, the file deleted, and the sibling renamed onto
    its name: the file is there before and after, so it changed and its folder's listing did not.

    **Test steps:**

    * coalesce the temporary sibling created and written, the file deleted, and the sibling renamed over it
    * verify the batch is the file changed, and nothing else
    """
    temporary = "info.rehu.k3j9a0_z.tmp"
    batch = (
        change(CREATED, "a", temporary),
        change(MODIFIED, "a", temporary),
        change(DELETED, "a", "info.rehu"),
        change(MOVED, "a", temporary, to=("a", "info.rehu")),
    )

    assert events_of(*batch) == [Changed((key("a", "info.rehu"),))]


def test_a_first_atomic_save_is_the_file_changed_and_its_folder_relisted() -> None:
    """A file an atomic save writes for the first time was not there before the batch, so its folder's listing
    changed too.

    **Test steps:**

    * coalesce a temporary sibling created and renamed onto a name that was free
    * verify the batch is the file changed, then its folder changed
    """
    temporary = "new.rehu.x1b2c3d4.tmp"
    batch = (change(CREATED, "a", temporary), change(MOVED, "a", temporary, to=("a", "new.rehu")))

    assert events_of(*batch) == [Changed((key("a", "new.rehu"),)), FolderChanged(key("a"))]


def test_temporary_siblings_on_their_own_are_no_ones_business() -> None:
    """An atomic write's temporary sibling created, written, deleted, or renamed to another temporary name says
    nothing about any file.

    **Test steps:**

    * coalesce each kind of observation of temporary siblings only
    * verify the batch adds up to nothing
    """
    first, second = "info.rehu.aaaaaaaa.tmp", "info.rehu.bbbbbbbb.tmp"
    batch = (
        change(CREATED, first),
        change(MODIFIED, first),
        change(MOVED, first, to=(second,)),
        change(DELETED, second),
    )

    assert not events_of(*batch)


def test_a_temporary_sibling_a_build_before_526_left_behind_is_still_one() -> None:
    """Earlier builds named the temporary sibling with a leading dot; a crash may have kept one, and its removal is
    no one's business either.

    **Test steps:**

    * coalesce the creation and deletion of ``.info.rehu.k3j9a0_z.tmp``
    * verify the batch adds up to nothing
    """
    leftover = ".info.rehu.k3j9a0_z.tmp"

    assert not events_of(change(CREATED, leftover), change(DELETED, leftover))


def test_a_users_own_tmp_file_is_no_temporary_sibling() -> None:
    """A file whose name only ends in ``.tmp`` is a file like any other: the random part is mkstemp's eight
    characters.

    **Test steps:**

    * coalesce the creation of ``scratch.part1.tmp``
    * verify the batch is that file changed, then its folder relisted
    """
    assert events_of(change(CREATED, "a", "scratch.part1.tmp")) == [
        Changed((key("a", "scratch.part1.tmp"),)),
        FolderChanged(key("a")),
    ]


def test_a_file_renamed_out_of_being_a_record_is_the_record_gone_and_a_file_created() -> None:
    """A conversion keeping its backup renames ``info.tc`` to ``info.tc.orig``: the record is gone, not moved to a
    name no holder can open; and a file renamed into a record's name is a record created. Both ends change, and the
    listing.

    **Test steps:**

    * coalesce ``info.tc`` renamed to ``info.tc.orig``, and ``notes.txt`` renamed to ``info.rehu``
    * verify no move, all four ends changed, and their folder relisted once
    """
    batch = (
        change(MOVED, "a", "info.tc", to=("a", "info.tc.orig")),
        change(MOVED, "a", "notes.txt", to=("a", "info.rehu")),
    )

    assert events_of(*batch) == [
        Changed((key("a", "info.tc"), key("a", "info.tc.orig"), key("a", "notes.txt"), key("a", "info.rehu"))),
        FolderChanged(key("a")),
    ]


def test_a_record_renamed_and_a_folder_renamed_are_one_move() -> None:
    """A record renamed to another record's name, and a folder renamed -- even to or from a record-like name -- are
    one rename plan, relisting nothing.

    **Test steps:**

    * coalesce a record renamed, and a folder named like a record renamed to a plain name
    * verify the batch is one ``Moved`` with both pairs, in order
    """
    batch = (
        change(MOVED, "a", "one.rehu", to=("a", "two.rehu")),
        change(MOVED, "pack.rehu", to=("pack",), directory=True),
    )

    assert events_of(*batch) == [
        Moved(KeyRelocation(((key("a", "one.rehu"), key("a", "two.rehu")), (key("pack.rehu"), key("pack")))))
    ]


def test_files_created_written_and_deleted_are_changed_and_relist_only_what_came_or_went() -> None:
    """A file written is changed; one created and deleted within the batch is changed but relists nothing; a folder
    created relists its parent without being a changed file; a folder deleted is changed itself; a folder's own
    modification is nothing.

    **Test steps:**

    * coalesce a write, a create-then-delete, a folder created, a folder deleted, and a folder modified
    * verify the changed files and folders in order, and one relist for each folder whose entries came or went
    """
    batch = (
        change(MODIFIED, "a", "info.rehu"),
        change(CREATED, "a", "brief.rehu"),
        change(DELETED, "a", "brief.rehu"),
        change(CREATED, "b", "new", directory=True),
        change(DELETED, "c", "old", directory=True),
        change(MODIFIED, "d", directory=True),
    )

    assert events_of(*batch) == [
        Changed((key("a", "info.rehu"), key("a", "brief.rehu"), key("c", "old"))),
        FolderChanged(key("b")),
        FolderChanged(key("c")),
    ]


# endregion

# region Composing a rename plan


def test_a_rename_continuing_an_earlier_one_is_folded_into_it() -> None:
    """``A -> B`` then ``B -> C`` is ``A -> C``, as a reorder that parked a screenshot under a temporary name arrives.

    **Test steps:**

    * compose ``A -> B``, then ``B -> C``, then an unrelated ``X -> Y``
    * verify the plan is ``A -> C`` and ``X -> Y``
    """
    pairs: list[tuple[ResourceKey, ResourceKey]] = []

    ChangeCoalescer.compose(pairs, key("A"), key("B"))
    ChangeCoalescer.compose(pairs, key("B"), key("C"))
    ChangeCoalescer.compose(pairs, key("X"), key("Y"))

    assert pairs == [(key("A"), key("C")), (key("X"), key("Y"))]


def test_a_rename_beneath_an_earlier_destination_gets_its_own_pair_first() -> None:
    """A move of something an earlier pair moved -- ``A -> B``, then ``B/x -> D`` -- is spelled from the earlier
    source and put before it, so a key read as it was before the plan ran matches it first.

    **Test steps:**

    * compose ``A -> B``, then ``B/x -> D``
    * verify the plan is ``A/x -> D`` then ``A -> B``, and maps both an entry of ``A`` and ``A/x`` where they went
    """
    pairs: list[tuple[ResourceKey, ResourceKey]] = []

    ChangeCoalescer.compose(pairs, key("A"), key("B"))
    ChangeCoalescer.compose(pairs, key("B", "x"), key("D"))

    assert pairs == [(key("A", "x"), key("D")), (key("A"), key("B"))]
    relocation = KeyRelocation(tuple(pairs))
    assert relocation.relocate(key("A", "x", "info.rehu")) == key("D", "info.rehu")
    assert relocation.relocate(key("A", "y")) == key("B", "y")


# endregion

# region Batching on its own thread


@fixture(name="heard")
def fixture_heard() -> tuple[ChangeFeed, list[ChangeEvent]]:
    """A feed, and what was published on it.

    :returns: the feed and the list it appends to.
    """
    feed = ChangeFeed()
    heard: list[ChangeEvent] = []
    feed.add_listener(heard.append)
    return feed, heard


def coalescer_thread_ended() -> bool:
    """Whether no coalescer thread for :data:`FOLDER` is running.

    :returns: whether it ended.
    """
    return not any(thread.name == f"change-coalescer {FOLDER}" for thread in threading.enumerate())


def test_a_burst_is_published_once_the_folder_is_quiet(
    heard: tuple[ChangeFeed, list[ChangeEvent]], mocker: MockerFixture
) -> None:
    """Observations pushed from any thread are held, and published together once nothing more arrives.

    **Test steps:**

    * start a coalescer -- twice, which starts one thread -- and push two writes
    * verify one ``Changed`` naming both is published
    * stop it, and verify its thread ends
    """
    mocker.patch(f"{MODULE}.POLL_SECONDS", 0.01)
    feed, events = heard
    coalescer = ChangeCoalescer(feed, FOLDER, ROOT_ID)
    coalescer.start()
    coalescer.start()

    coalescer.push(change(MODIFIED, "a.rehu"))
    coalescer.push(change(MODIFIED, "b.rehu"))

    assert wait_until(lambda: bool(events))
    assert events == [Changed((key("a.rehu"), key("b.rehu")))]
    coalescer.stop()
    assert wait_until(coalescer_thread_ended)


def test_a_folder_that_never_goes_quiet_is_still_published_within_the_longest_wait(
    heard: tuple[ChangeFeed, list[ChangeEvent]], mocker: MockerFixture
) -> None:
    """A steady stream is cut into batches at :data:`LONGEST_WAIT_SECONDS`, however soon each observation follows
    the last.

    **Test steps:**

    * replace the coalescer's clock: the batch opens at 0, its second observation arrives at 0.5, and by the third
      the clock reads past the longest wait
    * push three writes before starting it
    * verify the first two are published as one batch and the third as the next
    """
    clock = chain([0.0, 0.5, 2.0], repeat(10.0))
    mocker.patch(f"{MODULE}.time", SimpleNamespace(monotonic=lambda: next(clock)))
    mocker.patch(f"{MODULE}.QUIET_SECONDS", 0.05)
    feed, events = heard
    coalescer = ChangeCoalescer(feed, FOLDER, ROOT_ID)
    for name in ("a.rehu", "b.rehu", "c.rehu"):
        coalescer.push(change(MODIFIED, name))

    coalescer.start()

    assert wait_until(lambda: len(events) == 2)
    assert events == [Changed((key("a.rehu"), key("b.rehu"))), Changed((key("c.rehu"),))]
    coalescer.stop()


def test_nothing_is_published_after_a_stop(heard: tuple[ChangeFeed, list[ChangeEvent]], mocker: MockerFixture) -> None:
    """A stop drops what is still held -- the rest of a batch being published, and anything pushed later.

    **Test steps:**

    * listen with a listener that stops the coalescer on the first event it hears
    * push a rename and a write, which add up to a ``Moved`` and a ``Changed``
    * verify only the ``Moved`` was published, a later push is dropped, and the thread ends
    """
    mocker.patch(f"{MODULE}.POLL_SECONDS", 0.01)
    mocker.patch(f"{MODULE}.QUIET_SECONDS", 0.01)
    feed, events = heard
    coalescer = ChangeCoalescer(feed, FOLDER, ROOT_ID)
    feed.add_listener(lambda _event: coalescer.stop())
    coalescer.start()

    coalescer.push(change(MOVED, "a.rehu", to=("b.rehu",)))
    coalescer.push(change(MODIFIED, "c.rehu"))

    assert wait_until(lambda: bool(events))
    assert wait_until(coalescer_thread_ended)
    coalescer.push(change(MODIFIED, "d.rehu"))
    assert events == [Moved(KeyRelocation(((key("a.rehu"), key("b.rehu")),)))]


def test_an_idle_coalescer_looks_up_for_a_stop(
    heard: tuple[ChangeFeed, list[ChangeEvent]], mocker: MockerFixture
) -> None:
    """With nothing to publish, the thread wakes every :data:`POLL_SECONDS` to see whether it was stopped.

    **Test steps:**

    * replace the coalescer's queue with one that counts the waits that found nothing
    * start a coalescer and push nothing; wait for two empty waits
    * stop it, and verify its thread ends having published nothing
    """
    empty_waits: list[None] = []

    class CountingQueue(queue.SimpleQueue[RawChange]):
        """A queue noting each wait that ran out."""

        def get(self, block: bool = True, timeout: float | None = None) -> RawChange:
            """See :meth:`queue.SimpleQueue.get`; notes an empty wait.

            :param block: whether to wait.
            :param timeout: how long.
            :returns: the next observation.
            :raises queue.Empty: when none arrived in time.
            """
            try:
                return super().get(block, timeout)
            except queue.Empty:
                empty_waits.append(None)
                raise

    mocker.patch(f"{MODULE}.queue", SimpleNamespace(SimpleQueue=CountingQueue, Empty=queue.Empty))
    mocker.patch(f"{MODULE}.POLL_SECONDS", 0.01)
    feed, events = heard
    coalescer = ChangeCoalescer(feed, FOLDER, ROOT_ID)
    coalescer.start()

    assert wait_until(lambda: len(empty_waits) >= 2)
    coalescer.stop()

    assert wait_until(coalescer_thread_ended)
    assert not events


# endregion


def test_a_batch_that_cannot_be_made_sense_of_makes_the_root_stale_and_the_watch_goes_on(
    heard: tuple[ChangeFeed, list[ChangeEvent]], mocker: MockerFixture
) -> None:
    """A batch whose events cannot be worked out must not end the thread -- every later change would be lost with no
    one told: what it said is logged as lost, the root is read again, and the next batch is published as usual.

    **Test steps:**

    * make working out the first batch fail, and push a write
    * verify ``RootStale`` is published and the failure logged
    * push another write, and verify it is published as changed
    """
    mocker.patch(f"{MODULE}.POLL_SECONDS", 0.01)
    mocker.patch(f"{MODULE}.QUIET_SECONDS", 0.01)
    feed, events = heard
    real = ChangeCoalescer.events_of
    calls = iter([ValueError("a relative path"), None])

    def events_of_once(batch: list[RawChange], folder: Path, root_id: UUID | None) -> list[ChangeEvent]:
        failure = next(calls, None)
        if isinstance(failure, Exception):
            raise failure
        return real(batch, folder, root_id)

    mocker.patch.object(ChangeCoalescer, "events_of", side_effect=events_of_once)
    log = mocker.patch(f"{MODULE}.LOG")
    coalescer = ChangeCoalescer(feed, FOLDER, ROOT_ID)
    coalescer.start()

    coalescer.push(change(MODIFIED, "a.rehu"))
    assert wait_until(lambda: bool(events))
    assert events == [RootStale(ROOT_ID)]
    log.exception.assert_called_once()

    coalescer.push(change(MODIFIED, "b.rehu"))
    assert wait_until(lambda: len(events) == 2)
    assert events[1] == Changed((key("b.rehu"),))
    coalescer.stop()
