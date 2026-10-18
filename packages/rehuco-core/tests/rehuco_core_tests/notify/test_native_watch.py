"""Tests for the file notifier's backend on this machine's own disks: the operating system's events through
``watchdog`` (#511).

The watches are real, on folders under ``tmp_path``, and so are the renames that make a loose folder's watch let go;
what a test waits for is an observation arriving, never a sleep.
"""

import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Final

from pytest import LogCaptureFixture, MonkeyPatch, fixture, mark, raises
from pytest_mock import MockerFixture
from rehuco_core import RehuDocument, RenameCoordinator
from rehuco_core.notify import NativeWatch, RawChange, RawChangeKind, WatchedFolder
from watchdog.events import DirMovedEvent, FileClosedEvent, FileModifiedEvent, FileMovedEvent, FileOpenedEvent
from watchdog.observers.api import BaseObserver

from rehuco_core_tests.concurrency import wait_until

MODULE: Final = "rehuco_core.notify.native_watch"


class Sink:
    """What a watch reported, from its threads."""

    def __init__(self) -> None:
        self.__lock: Final = threading.Lock()
        self.__changes: list[RawChange] = []

    def __call__(self, change: RawChange) -> None:
        """Note one observation.

        :param change: what was seen.
        """
        with self.__lock:
            self.__changes.append(change)

    def changes(self) -> list[RawChange]:
        """:returns: what was reported so far."""
        with self.__lock:
            return list(self.__changes)

    def saw(self, kind: RawChangeKind, path: Path, destination: Path | None = None) -> bool:
        """Whether an observation of this kind, path and destination was reported.

        :param kind: what happened.
        :param path: to what.
        :param destination: where it went, for a move.
        :returns: whether it was.
        """
        return any(
            (change.kind, change.path, change.destination) == (kind, path, destination) for change in self.changes()
        )


def armed(folder: Path, sink: Sink) -> bool:
    """Wait until a watch of ``folder`` reports what happens in it.

    A started watch may not see what happens at once: ReadDirectoryChangesW records changes only from its first
    read, which the emitter's thread makes some time after the start returned. A probe file is written until a write
    of it is reported, then deleted.

    :param folder: the watched folder.
    :param sink: where the watch reports.
    :returns: whether it was seen in time.
    """
    probe = folder / "probe.txt"

    def seen() -> bool:
        """Write the probe; whether a write of it was reported."""
        probe.write_text("probe", encoding="utf-8")
        return any(change.path == probe for change in sink.changes())

    try:
        return wait_until(seen)
    finally:
        probe.unlink()


class Watches:  # pylint: disable=too-few-public-methods  # a starter with a teardown list
    """Every watch a test starts, stopped when it ends."""

    def __init__(self) -> None:
        self.started: list[NativeWatch] = []

    def start(
        self, folder: Path, sink: Sink, coordinator: RenameCoordinator | None = None, *, recursive: bool = True
    ) -> NativeWatch:
        """Start a watch.

        :param folder: what to watch.
        :param sink: where it reports.
        :param coordinator: the rename coordinator it lets go for, if any.
        :param recursive: whether everything beneath the folder is watched.
        :returns: the watch, started.
        """
        watch = NativeWatch(WatchedFolder(folder, None, recursive), sink, coordinator)
        watch.start()
        self.started.append(watch)
        return watch


@fixture(name="watches")
def fixture_watches() -> Iterator[Watches]:
    """Watches stopped at the end of the test.

    :yields: the starter.
    """
    watches = Watches()
    yield watches
    for watch in watches.started:
        watch.stop()


def test_what_happens_in_the_folder_is_reported(tmp_path: Path, watches: Watches) -> None:
    """A file created, written, renamed and deleted in a watched folder is each reported as it happened.

    **Test steps:**

    * watch a folder, and wait until it reports a probe file written
    * create a file, write to it, rename it, delete it
    * verify each was reported -- the rename with where it went -- and the watch has not failed
    """
    sink = Sink()
    watch = watches.start(tmp_path, sink)
    path, renamed = tmp_path / "info.rehu", tmp_path / "other.rehu"
    assert armed(tmp_path, sink)

    path.write_text("a", encoding="utf-8")
    assert wait_until(lambda: sink.saw(RawChangeKind.CREATED, path))
    with path.open("a", encoding="utf-8") as stream:
        stream.write("b")
    assert wait_until(lambda: sink.saw(RawChangeKind.MODIFIED, path))
    path.rename(renamed)
    assert wait_until(lambda: sink.saw(RawChangeKind.MOVED, path, renamed))
    renamed.unlink()
    assert wait_until(lambda: sink.saw(RawChangeKind.DELETED, renamed))

    assert not watch.failed


def test_a_folder_that_is_missing_cannot_be_watched(tmp_path: Path) -> None:
    """A folder that is not there is refused at the start, for the caller to fall back on polling.

    **Test steps:**

    * start a watch of a missing folder
    * verify ``FileNotFoundError``, an ``OSError``
    """
    with raises(FileNotFoundError, match="Not a folder to watch"):
        NativeWatch(WatchedFolder(tmp_path / "missing"), Sink()).start()


def test_only_events_that_change_the_disk_and_no_made_up_moves_are_reported(tmp_path: Path) -> None:
    """A file opened or closed changes nothing on disk; the moves watchdog makes up for every entry beneath a moved
    folder are already said by the folder's own move.

    **Test steps:**

    * hand the watch's handler an open, a close, a synthetic move and a real write
    * verify only the write is reported, with its path and file-ness
    """
    sink = Sink()
    handler = NativeWatch.Handler(sink)
    path = str(tmp_path / "info.rehu")

    for event in (
        FileOpenedEvent(path),
        FileClosedEvent(path),
        FileMovedEvent(path, str(tmp_path / "moved.rehu"), is_synthetic=True),
        FileModifiedEvent(path),
    ):
        handler.on_any_event(event)

    assert sink.changes() == [RawChange(RawChangeKind.MODIFIED, tmp_path / "info.rehu", None, False)]


def test_a_move_whose_old_half_went_missing_is_the_new_name_created(tmp_path: Path) -> None:
    """watchdog forgets a rename's old half between two reads of the system's buffer, and reports the move from
    nowhere: all that is known is that the new name appeared -- never a path that is no path.

    **Test steps:**

    * hand the watch's handler a file move and a folder move with no source
    * verify each is reported as its destination created, with its folder-ness
    """
    sink = Sink()
    handler = NativeWatch.Handler(sink)

    handler.on_any_event(FileMovedEvent("", str(tmp_path / "new.rehu")))
    handler.on_any_event(DirMovedEvent("", str(tmp_path / "new folder")))

    assert sink.changes() == [
        RawChange(RawChangeKind.CREATED, tmp_path / "new.rehu", None, False),
        RawChange(RawChangeKind.CREATED, tmp_path / "new folder", None, True),
    ]


def test_a_watch_whose_folder_is_deleted_has_failed(tmp_path: Path, watches: Watches) -> None:
    """The folder going away ends the system's watch of it, which the watch reports as having failed.

    **Test steps:**

    * watch a folder, then delete it
    * verify the watch reports failing
    """
    folder = tmp_path / "watched"
    folder.mkdir()
    watch = watches.start(folder, Sink())

    folder.rmdir()

    assert wait_until(lambda: watch.failed)


def test_a_stopped_watch_has_let_go_of_its_folder(tmp_path: Path, watches: Watches) -> None:
    """A stop closes every handle before it returns -- on Windows, the parent of a watched folder renames again at
    once -- and a stopped watch never reports failing; a second stop does nothing.

    **Test steps:**

    * watch a folder inside a parent
    * stop the watch, twice
    * verify the parent renames, and the watch does not report failing
    """
    parent = tmp_path / "parent"
    (parent / "watched").mkdir(parents=True)
    watch = watches.start(parent / "watched", Sink())

    watch.stop()
    watch.stop()

    parent.rename(tmp_path / "renamed")
    assert not watch.failed


@mark.windows
def test_a_running_watch_holds_its_folders_parent(tmp_path: Path, watches: Watches) -> None:
    """The reason a loose folder's watch lets go for a rename: on NTFS the watched folder's parent cannot be renamed
    while the watch runs -- the guard :func:`test_a_stopped_watch_has_let_go_of_its_folder` relies on.

    **Test steps:**

    * watch a folder inside a parent
    * verify renaming the parent is refused
    """
    parent = tmp_path / "parent"
    (parent / "watched").mkdir(parents=True)
    watches.start(parent / "watched", Sink())

    with raises(PermissionError):
        parent.rename(tmp_path / "renamed")


def resource(folder: Path) -> Path:
    """A directory-scoped resource: its folder, holding its ``info.rehu``.

    :param folder: the resource's folder; created.
    :returns: the record.
    """
    folder.mkdir(parents=True)
    record = folder / "info.rehu"
    RehuDocument.new(record).save()
    return record


def test_a_watch_given_a_coordinator_lets_go_for_a_rename_and_watches_again(tmp_path: Path, watches: Watches) -> None:
    """A loose folder's watch closes its handle when a rename wants readers out, so a resource beneath it renames,
    and watches again once the rename is over -- reporting that it may have missed something.

    **Test steps:**

    * watch a folder holding a resource's folder, with a coordinator
    * rename the resource through the coordinator
    * verify the rename landed, an overflow of the watched folder was reported, and what happens afterwards is seen
    """
    coordinator = RenameCoordinator()
    record = resource(tmp_path / "library" / "course")
    sink = Sink()
    watch = watches.start(tmp_path / "library", sink, coordinator)

    renamed = coordinator.rename(record, "lesson")

    assert renamed == tmp_path / "library" / "lesson" / "info.rehu"
    assert wait_until(lambda: sink.saw(RawChangeKind.OVERFLOW, tmp_path / "library"))
    assert armed(tmp_path / "library", sink)
    assert not watch.failed


def test_a_watch_whose_own_folder_was_renamed_cannot_watch_again(
    tmp_path: Path, watches: Watches, caplog: LogCaptureFixture
) -> None:
    """A watch of the resource's own folder lets it rename, and then finds nothing to watch: it has failed, and
    says why.

    **Test steps:**

    * watch a resource's own folder, with a coordinator
    * rename the resource through the coordinator
    * verify the watch reports failing, logged, and reported no overflow
    """
    coordinator = RenameCoordinator()
    record = resource(tmp_path / "course")
    sink = Sink()

    with caplog.at_level("INFO", logger=MODULE):
        watch = watches.start(record.parent, sink, coordinator)
        coordinator.rename(record, "lesson")
        assert wait_until(lambda: watch.failed)

    assert "Could not watch" in caplog.text and "again after a rename" in caplog.text
    assert not sink.saw(RawChangeKind.OVERFLOW, record.parent)


def test_a_watch_stopped_while_it_let_go_stays_stopped(tmp_path: Path, mocker: MockerFixture) -> None:
    """A second yield while the handle is already let go does nothing; a stop while it is let go stops the watch for
    good -- it is not armed again once the rename is over, and reports nothing.

    **Test steps:**

    * watch a folder with a coordinator, noting the yield listener the watch adds
    * add a listener after it that calls the watch's listener again and then stops the watch
    * make the coordinator raise its flag, by a rename of a record that does not exist
    * verify the rename failed for its own reason, no re-arm thread is left, the watch is not failed and reported
      nothing
    """
    coordinator = RenameCoordinator()
    added = mocker.spy(coordinator, "add_yield_listener")
    sink = Sink()
    watch = NativeWatch(WatchedFolder(tmp_path), sink, coordinator)
    watch.start()
    (on_yield,) = added.call_args.args

    def again_then_stop() -> None:
        """Yield the watch again while it is let go, then stop it."""
        on_yield()
        watch.stop()

    coordinator.add_yield_listener(again_then_stop)

    with raises(OSError):
        coordinator.rename(tmp_path / "missing" / "info.rehu", "other")

    assert wait_until(lambda: not any(thread.name == "native-watch-rearm" for thread in threading.enumerate()))
    assert not watch.failed
    assert not sink.saw(RawChangeKind.OVERFLOW, tmp_path)


@mark.windows
def test_an_overflow_the_system_reports_is_an_overflow_of_the_folder(
    tmp_path: Path, watches: Watches, mocker: MockerFixture
) -> None:
    """On Windows the watch's emitter is told to report a lost buffer, as an overflow of the watched folder.

    **Test steps:**

    * note every observer the watch makes, and start a watch
    * call the overflow callback set on its emitter
    * verify an overflow of the folder was reported
    """
    made: list[BaseObserver] = []
    real_observer = NativeWatch.observer

    def noted() -> BaseObserver:
        """A real observer, noted."""
        observer = real_observer()
        made.append(observer)
        return observer

    mocker.patch.object(NativeWatch, "observer", side_effect=noted)
    sink = Sink()
    watches.start(tmp_path, sink)

    (emitter,) = made[0].emitters
    emitter.on_overflow()  # type: ignore[attr-defined]

    assert sink.changes() == [RawChange(RawChangeKind.OVERFLOW, tmp_path)]


def test_off_windows_the_platform_observer_is_used_and_left_to_close_itself(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Elsewhere the platform's own observer watches, with no overflow wiring, and a stop leaves its handles to the
    observer's own teardown.

    **Test steps:**

    * as Linux, make an observer, and start and stop a watch
    * verify the observer is watchdog's platform one, and the watch, stopped, does not report failing
    """
    monkeypatch.setattr(sys, "platform", "linux")

    assert type(NativeWatch.observer()).__name__ != "BaseObserver"
    watch = NativeWatch(WatchedFolder(tmp_path), Sink())
    watch.start()
    watch.stop()

    assert not watch.failed


@mark.windows
def test_an_observer_with_watchdogs_own_emitters_is_given_no_overflow_callback(
    tmp_path: Path, mocker: MockerFixture, monkeypatch: MonkeyPatch
) -> None:
    """Only the package's own emitter can report an overflow; an observer built with watchdog's emitters still
    watches, with nothing wired.

    **Test steps:**

    * make the watch's observer watchdog's Windows one, and start a watch
    * verify what happens in the folder is reported
    * stop it as off Windows, leaving the handles to the observer's teardown -- watchdog's emitter closes its handle on
      every stop, so it must be stopped once
    """
    # pylint: disable-next=import-outside-toplevel  # loads the Windows API, absent elsewhere
    from watchdog.observers.read_directory_changes import WindowsApiObserver

    mocker.patch.object(NativeWatch, "observer", side_effect=WindowsApiObserver)
    sink = Sink()
    watch = NativeWatch(WatchedFolder(tmp_path), sink)
    watch.start()

    assert armed(tmp_path, sink)

    monkeypatch.setattr(sys, "platform", "linux")
    watch.stop()
