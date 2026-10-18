"""The file notifier's backend for a folder on this machine's own disks: the operating system's change events, through
``watchdog`` -- ReadDirectoryChangesW, FSEvents, inotify (#511, [[mounts-and-storage#out-of-band]]).

**A watch blocks a rename only above it.** Measured on NTFS with a live watch: a folder beneath the watched one renames,
and so does the watched folder itself; the watched folder's *parent* is refused ("Access is denied"), because its
handle is open beneath it. A root's watch therefore never stands in the app's way -- it renames nothing above a root --
and a watch of a folder under no root (an open document's) can be asked to let go: given a
:class:`~rehuco_core.RenameCoordinator`, it closes its handle the moment a directory rename wants readers out, and
opens it again, reporting what it may have missed, once the rename is over.
"""

import logging
import os
import sys
import threading
from collections.abc import Callable
from enum import Enum, auto
from pathlib import Path
from typing import Final, override

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from ..rename_coordination import RenameCoordinator
from .raw_change import RawChange, RawChangeKind
from .watched_folder import WatchedFolder

LOG: Final = logging.getLogger(__name__)

KINDS: Final = {
    "created": RawChangeKind.CREATED,
    "modified": RawChangeKind.MODIFIED,
    "deleted": RawChangeKind.DELETED,
    "moved": RawChangeKind.MOVED,
}
"""watchdog's event types this backend reports; the rest -- opened, closed -- change nothing on disk."""


class NativeWatch:
    """Watches one folder through the operating system's change events.

    :param folder: the folder, and whether everything beneath it is watched.
    :param sink: told of each change, on a watchdog thread.
    :param coordinator: when given, the watch lets go for every directory rename (see the module docstring); a root's
        watch is given none.
    """

    class State(Enum):
        """Where the watch stands."""

        WATCHING = auto()
        """Armed, or let go for a rename and about to be armed again."""

        STOPPED = auto()
        """Told to stop."""

        FAILED = auto()
        """Could not be armed again after a rename -- the folder itself was what moved."""

    class Handler(FileSystemEventHandler):
        """Turns watchdog's events into :class:`~rehuco_core.notify.RawChange` observations.

        :param sink: where to report them.
        """

        def __init__(self, sink: Callable[[RawChange], None]) -> None:
            super().__init__()
            self.__sink: Final = sink

        @override
        def on_any_event(self, event: FileSystemEvent) -> None:
            kind = KINDS.get(event.event_type)
            # a folder moved within the watch arrives once, and then once more for every entry beneath it, made up by
            # walking the new folder: the folder's own pair already says where each of them went
            if kind is None or (kind is RawChangeKind.MOVED and event.is_synthetic):
                return
            source = os.fsdecode(event.src_path)
            destination = os.fsdecode(event.dest_path) if kind is RawChangeKind.MOVED else ""
            if kind is RawChangeKind.MOVED and not source:
                # the rename's old half came at the end of an earlier read, which watchdog forgets between reads:
                # all that is known is that the new name appeared
                self.__sink(RawChange(RawChangeKind.CREATED, Path(destination), None, event.is_directory))
                return
            self.__sink(RawChange(kind, Path(source), Path(destination) if destination else None, event.is_directory))

    def __init__(
        self, folder: WatchedFolder, sink: Callable[[RawChange], None], coordinator: RenameCoordinator | None = None
    ) -> None:
        self.__folder: Final = folder
        self.__sink: Final = sink
        self.__coordinator: Final = coordinator
        self.__lock: Final = threading.Lock()
        self.__observer: BaseObserver | None = None
        self.__generation = 0
        self.__state = NativeWatch.State.WATCHING

    def start(self) -> None:
        """Begin watching.

        :raises OSError: when the folder cannot be watched -- it is missing, or the system refused a handle.
        """
        with self.__lock:
            self.__observer = self.__armed()
        if self.__coordinator is not None:
            self.__coordinator.add_yield_listener(self.__on_yield)

    def stop(self) -> None:
        """Stop watching. Every handle is closed before this returns; the watchdog threads end on their own."""
        if self.__coordinator is not None:
            self.__coordinator.remove_yield_listener(self.__on_yield)
        with self.__lock:
            self.__state = NativeWatch.State.STOPPED
            observer, self.__observer = self.__observer, None
        if observer is not None:
            NativeWatch.close(observer)

    @property
    def failed(self) -> bool:
        """Whether the watch ended without being told to: the folder was deleted, or the system dropped the handle."""
        with self.__lock:
            state, observer = self.__state, self.__observer
        if state is not NativeWatch.State.WATCHING:
            return state is NativeWatch.State.FAILED
        if observer is None:  # let go for a rename, and not armed again yet
            return False
        return not observer.is_alive() or any(not emitter.is_alive() for emitter in tuple(observer.emitters))

    @staticmethod
    def close(observer: BaseObserver) -> None:
        """Close an observer's handles now on Windows, and leave the joining of its threads to a daemon thread.

        ``BaseObserver.stop`` joins every emitter after closing its handle; the handle is what a rename collides with,
        and the join is nobody's business -- least of all a rename's yield listener, which must not block. The teardown
        stops each emitter a second time, which only the package's own emitter survives (it closes its handle once,
        see :mod:`~rehuco_core.platforms.windows.overflow_reporting_emitter`), so the handles are closed here only on
        Windows -- the one platform where a handle blocks a rename at all.

        :param observer: the observer.
        """
        if sys.platform == "win32":
            for emitter in tuple(observer.emitters):
                emitter.stop()
        threading.Thread(target=observer.stop, name="native-watch-close", daemon=True).start()

    @staticmethod
    def observer() -> BaseObserver:
        """An observer for this platform, one that reports a lost buffer on Windows.

        :returns: a new, unstarted observer.
        """
        if sys.platform == "win32":
            # pylint: disable-next=import-outside-toplevel
            from ..platforms.windows.overflow_reporting_emitter import OverflowReportingEmitter

            return BaseObserver(OverflowReportingEmitter)
        return Observer()

    def __armed(self) -> BaseObserver:
        """A started observer on the folder.

        :returns: the observer.
        :raises OSError: when the folder cannot be watched.
        """
        path = self.__folder.path
        if not path.is_dir():
            raise FileNotFoundError(f"Not a folder to watch: {path}")
        observer = NativeWatch.observer()
        observer.schedule(NativeWatch.Handler(self.__sink), str(path), recursive=self.__folder.recursive)
        if sys.platform == "win32":
            # pylint: disable-next=import-outside-toplevel
            from ..platforms.windows.overflow_reporting_emitter import OverflowReportingEmitter

            for emitter in observer.emitters:
                if isinstance(emitter, OverflowReportingEmitter):
                    emitter.on_overflow = self.__on_overflow
        observer.start()
        return observer

    def __on_overflow(self) -> None:
        """Report that the system discarded events (an emitter thread)."""
        self.__sink(RawChange(RawChangeKind.OVERFLOW, self.__folder.path))

    def __on_yield(self) -> None:
        """Let go of the folder for a directory rename, and arm again once it is over (the renaming thread; must not
        block)."""
        with self.__lock:
            if self.__state is not NativeWatch.State.WATCHING or self.__observer is None:
                return
            self.__generation += 1
            generation = self.__generation
            observer, self.__observer = self.__observer, None
        NativeWatch.close(observer)
        threading.Thread(target=self.__rearm, args=(generation,), name="native-watch-rearm", daemon=True).start()

    def __rearm(self, generation: int) -> None:
        """Watch again once the rename that asked for the handle is over, and report that events may have been missed.

        :param generation: the yield this answers; a later yield or a stop supersedes it.
        """
        assert self.__coordinator is not None  # nosec  # B101: only a watch with a coordinator yields
        with self.__coordinator.holding():  # waits for the rename to end; a new one waits for this to leave
            with self.__lock:
                if self.__state is not NativeWatch.State.WATCHING or generation != self.__generation:
                    return
                try:
                    self.__observer = self.__armed()
                except OSError as error:  # the folder itself was what the rename moved
                    LOG.info("Could not watch %s again after a rename: %s", self.__folder.path, error)
                    self.__state = NativeWatch.State.FAILED
                    return
        self.__sink(RawChange(RawChangeKind.OVERFLOW, self.__folder.path))
