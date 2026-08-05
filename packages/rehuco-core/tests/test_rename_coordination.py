"""Tests for the yield barrier a rename runs behind (#241).

Real threads, no mocked locks: the whole subject is what two threads do to each other, and a fake
:class:`~threading.Condition` would only prove the fake works. The filesystem underneath is mocked as
usual -- what a rename does to disk is ``test_rehu_rename``'s to check, and this is about who is allowed
to be holding a handle while it happens.

Every wait is bounded, so a broken barrier fails as a failing assertion rather than as a suite that
hangs: :data:`SETTLE` is what a test waits for something to happen, and it is generous enough that a
slow machine does not read as a defect.
"""

from pathlib import Path
from threading import Event
from typing import Any, Final

from concurrency import BRIEF, SETTLE, running, wait_until
from pytest import fixture, raises
from pytest_mock import MockerFixture
from rehuco_core import RenameCoordinator, RenameYieldTimeout, ResourceLocation

DIRECTORY: Final = Path("/fake/library")
FOLDER: Final = DIRECTORY / "old_folder"
INFO_PATH: Final = FOLDER / "info.rehu"
CONTENT: Final = FOLDER / "content.zip"
NEW_NAME: Final = "new_name"
RENAMED: Final = DIRECTORY / NEW_NAME


@fixture(name="filesystem")
def fixture_filesystem(mocker: MockerFixture) -> Any:
    """Mock the filesystem so a directory-scoped rename succeeds without touching a disk.

    :param mocker: pytest-mock fixture.
    :returns: the ``Path.rename`` mock, so a test can prove the rename did or did not run.
    """
    mocker.patch.object(Path, "is_file", autospec=True, return_value=True)
    mocker.patch.object(Path, "exists", autospec=True, return_value=False)
    return mocker.patch.object(Path, "rename", autospec=True)


@fixture(name="coordinator")
def fixture_coordinator() -> RenameCoordinator:
    """A fresh coordinator per test.

    :returns: the coordinator under test.
    """
    return RenameCoordinator()


def tracked_count(coordinator: RenameCoordinator) -> int:
    """How many locations ``coordinator`` still holds a reference to.

    Reaches for the private list on purpose: the invariant under test is that a long-lived coordinator
    does not accumulate one entry per file ever read, and that is not observable from the outside --
    exposing it just to be testable would put a method in production code that nothing else wants.

    :param coordinator: the coordinator to inspect.
    :returns: the number of tracked locations, dead references included.
    """
    return len(getattr(coordinator, "_RenameCoordinator__locations"))  # noqa: B009  # name-mangled, see above


# region ResourceLocation
def test_a_location_starts_where_it_was_created() -> None:
    """A tracked location reads back the path it was given.

    **Test steps:**

    * build a location over a path and read it
    """
    assert ResourceLocation(CONTENT).path == CONTENT


def test_a_location_reports_where_it_was_moved_to() -> None:
    """Once told it moved, a location answers the new path -- the whole of "the job continues at the
    new location".

    **Test steps:**

    * move a location, then read it
    """
    location = ResourceLocation(CONTENT)
    location.moved_to(RENAMED / "content.zip")

    assert location.path == RENAMED / "content.zip"


# endregion


# region the barrier
def test_a_rename_with_no_readers_runs_straight_through(coordinator: RenameCoordinator, filesystem: Any) -> None:
    """Nothing is holding, so there is nothing to wait for.

    **Test steps:**

    * rename with no reader anywhere
    * check the new path came back, the directory moved, and the flag is down again
    """
    assert coordinator.rename(INFO_PATH, NEW_NAME) == RENAMED / "info.rehu"
    assert filesystem.call_args.args == (FOLDER, RENAMED)
    assert coordinator.yield_wanted is False


def test_a_rename_waits_for_a_holder_to_let_go(coordinator: RenameCoordinator, filesystem: Any) -> None:
    """A reader holding a handle keeps the rename waiting, and releasing lets it through.

    The measured behaviour this whole module exists for: the rename does not fail and does not force
    anything, it waits for an acknowledgement that arrives one chunk later.

    **Test steps:**

    * hold on a worker thread, then start a rename on another
    * check the flag went up and the rename has not run
    * release the hold, and check the rename completes
    """
    holding = Event()
    release = Event()
    renamed = Event()

    def reader() -> None:
        with coordinator.holding():
            holding.set()
            release.wait(SETTLE)

    def renamer() -> None:
        coordinator.rename(INFO_PATH, NEW_NAME)
        renamed.set()

    with running(reader):
        assert holding.wait(SETTLE)
        with running(renamer):
            assert wait_until(lambda: coordinator.yield_wanted)
            assert renamed.wait(BRIEF) is False
            filesystem.assert_not_called()

            release.set()

            assert renamed.wait(SETTLE)
            assert filesystem.call_args.args == (FOLDER, RENAMED)
            assert coordinator.yield_wanted is False


def test_a_reader_cannot_start_holding_while_a_rename_is_pending(
    coordinator: RenameCoordinator, filesystem: Any
) -> None:
    """A reader arriving mid-rename waits at the door rather than opening a handle the rename is about
    to trip over.

    Without this the barrier would leak: the wait could see zero holders and start renaming into a
    handle that had just been opened behind it.

    **Test steps:**

    * hold, start a rename, and wait for the flag
    * have a second reader try to hold, and check it does not get in
    * release the first hold and check the second gets in once the rename is done
    """
    holding = Event()
    release = Event()
    second_holding = Event()

    def first_reader() -> None:
        with coordinator.holding():
            holding.set()
            release.wait(SETTLE)

    def second_reader() -> None:
        with coordinator.holding():
            second_holding.set()

    with running(first_reader):
        assert holding.wait(SETTLE)
        with running(lambda: coordinator.rename(INFO_PATH, NEW_NAME)):
            assert wait_until(lambda: coordinator.yield_wanted)
            with running(second_reader):
                assert second_holding.wait(BRIEF) is False

                release.set()

                assert second_holding.wait(SETTLE)
                assert filesystem.call_args.args == (FOLDER, RENAMED)


def test_a_wedged_reader_makes_the_rename_give_up(coordinator: RenameCoordinator, filesystem: Any) -> None:
    """A reader that never lets go costs the rename its ceiling and nothing more.

    **Test steps:**

    * hold and never release
    * rename with a short ceiling
    * check it raised, touched nothing, and left the flag down
    """
    holding = Event()
    release = Event()

    def reader() -> None:
        with coordinator.holding():
            holding.set()
            release.wait(SETTLE)

    with running(reader):
        assert holding.wait(SETTLE)

        with raises(RenameYieldTimeout):
            coordinator.rename(INFO_PATH, NEW_NAME, timeout=BRIEF)

        filesystem.assert_not_called()
        assert coordinator.yield_wanted is False
        release.set()


def test_a_failed_rename_still_releases_the_readers(coordinator: RenameCoordinator, mocker: MockerFixture) -> None:
    """A rename that fails for its own reasons does not leave the resource permanently unreadable.

    Readers come back to paths that never changed, which is correct -- nothing moved.

    **Test steps:**

    * make the ``.rehu`` missing so the rename refuses
    * check it raised, and the flag is down
    """
    mocker.patch.object(Path, "is_file", autospec=True, return_value=False)

    with raises(FileNotFoundError):
        coordinator.rename(INFO_PATH, NEW_NAME)

    assert coordinator.yield_wanted is False


def test_two_renames_do_not_share_one_flag(coordinator: RenameCoordinator, filesystem: Any) -> None:
    """Renames serialize: the second waits for the first rather than lowering its flag underneath it.

    The failure this prevents is specific and silent -- the second rename clearing the flag mid-way
    through the first would release every reader onto a directory about to move.

    **Test steps:**

    * hold a reader, then start two renames
    * check neither ran and the flag is up
    * release, and check both landed and the flag is down
    """
    del filesystem  # the fixture mocks the disk; this test asserts on the renames' own completion
    holding = Event()
    release = Event()
    done = Event()
    finished: list[str] = []

    def reader() -> None:
        with coordinator.holding():
            holding.set()
            release.wait(SETTLE)

    def rename(name: str) -> None:
        coordinator.rename(INFO_PATH, name)
        finished.append(name)
        if len(finished) == 2:
            done.set()

    with running(reader):
        assert holding.wait(SETTLE)
        with running(lambda: rename("first")), running(lambda: rename("second")):
            assert wait_until(lambda: coordinator.yield_wanted)
            assert done.wait(BRIEF) is False

            release.set()

            assert done.wait(SETTLE)
            assert sorted(finished) == ["first", "second"]
            assert coordinator.yield_wanted is False


# endregion


# region following the rename
def test_a_tracked_location_follows_the_rename(coordinator: RenameCoordinator, filesystem: Any) -> None:
    """Every tracked path is rewritten by the rename that moved it.

    **Test steps:**

    * track the directory, its `info.rehu` and a content file
    * rename
    * check all three now read under the new name
    """
    del filesystem
    folder = coordinator.track(FOLDER)
    record = coordinator.track(INFO_PATH)
    content = coordinator.track(CONTENT)

    coordinator.rename(INFO_PATH, NEW_NAME)

    assert folder.path == RENAMED
    assert record.path == RENAMED / "info.rehu"
    assert content.path == RENAMED / "content.zip"


def test_a_tracked_location_outside_the_rename_is_left_alone(coordinator: RenameCoordinator, filesystem: Any) -> None:
    """A path this rename did not move reads back unchanged.

    **Test steps:**

    * track a resource in a sibling directory
    * rename
    * check it is where it was
    """
    del filesystem
    elsewhere = coordinator.track(DIRECTORY / "other" / "info.rehu")

    coordinator.rename(INFO_PATH, NEW_NAME)

    assert elsewhere.path == DIRECTORY / "other" / "info.rehu"


def test_a_location_follows_several_renames_in_a_row(coordinator: RenameCoordinator, filesystem: Any) -> None:
    """A long job survives being renamed under repeatedly, which is the point of holding a location
    rather than a path.

    **Test steps:**

    * track a content file and rename three times
    * check it reads under the last name
    """
    del filesystem
    content = coordinator.track(CONTENT)

    coordinator.rename(INFO_PATH, "first")
    coordinator.rename(DIRECTORY / "first" / "info.rehu", "second")
    coordinator.rename(DIRECTORY / "second" / "info.rehu", "third")

    assert content.path == DIRECTORY / "third" / "content.zip"


def test_a_dropped_location_stops_being_tracked(coordinator: RenameCoordinator, filesystem: Any) -> None:
    """A location whose job has finished is forgotten, so a long-lived coordinator does not accumulate
    one entry per file ever read.

    **Test steps:**

    * track a location and drop the only reference to it
    * rename, and check the coordinator kept nothing
    """
    del filesystem
    coordinator.track(CONTENT)

    coordinator.rename(INFO_PATH, NEW_NAME)

    assert tracked_count(coordinator) == 0


def test_locations_are_rewritten_before_readers_are_let_back_in(
    coordinator: RenameCoordinator, filesystem: Any
) -> None:
    """A reader coming back through ``holding`` never sees a moved resource and a stale location.

    The ordering the whole design rests on: were the flag lowered first, a reader could wake, re-read
    its location, and re-open the path the rename had just emptied.

    **Test steps:**

    * hold a reader, start a rename, release once the flag is up
    * have the reader re-enter and record what its location says
    * check it is the new path
    """
    del filesystem
    content = coordinator.track(CONTENT)
    holding = Event()
    release = Event()
    seen: list[Path] = []

    def reader() -> None:
        with coordinator.holding():
            holding.set()
            release.wait(SETTLE)
        with coordinator.holding():
            seen.append(content.path)

    with running(reader):
        assert holding.wait(SETTLE)
        with running(lambda: coordinator.rename(INFO_PATH, NEW_NAME)):
            assert wait_until(lambda: coordinator.yield_wanted)
            release.set()
            assert wait_until(lambda: bool(seen))

    assert seen == [RENAMED / "content.zip"]


# endregion


# region announcing
def test_a_listener_is_told_once_a_rename_lands(coordinator: RenameCoordinator, filesystem: Any) -> None:
    """The one event, carrying nothing: whoever cares re-reads what they hold.

    **Test steps:**

    * attach two listeners and rename twice
    * check each was called once per rename
    """
    del filesystem
    calls: list[str] = []
    coordinator.add_rename_listener(lambda: calls.append("first"))
    coordinator.add_rename_listener(lambda: calls.append("second"))

    coordinator.rename(INFO_PATH, "one")
    coordinator.rename(DIRECTORY / "one" / "info.rehu", "two")

    assert calls == ["first", "second", "first", "second"]


def test_a_listener_is_not_told_about_a_rename_that_failed(
    coordinator: RenameCoordinator, mocker: MockerFixture
) -> None:
    """Nothing moved, so there is nothing to re-read.

    **Test steps:**

    * attach a listener and make the rename refuse
    * check it was never called
    """
    mocker.patch.object(Path, "is_file", autospec=True, return_value=False)
    calls: list[None] = []
    coordinator.add_rename_listener(lambda: calls.append(None))

    with raises(FileNotFoundError):
        coordinator.rename(INFO_PATH, NEW_NAME)

    assert not calls


def test_a_failing_listener_is_logged_and_the_rest_still_run(coordinator: RenameCoordinator, filesystem: Any) -> None:
    """A broken observer costs itself and nothing else -- the rename already happened, and raising out
    of the notification would report a failure that did not occur.

    **Test steps:**

    * attach a listener that raises, followed by one that records
    * rename, and check it returned normally and the second listener ran
    """
    del filesystem
    calls: list[None] = []

    def raising() -> None:
        raise RuntimeError("boom")

    coordinator.add_rename_listener(raising)
    coordinator.add_rename_listener(lambda: calls.append(None))

    assert coordinator.rename(INFO_PATH, NEW_NAME) == RENAMED / "info.rehu"
    assert calls == [None]


# endregion
