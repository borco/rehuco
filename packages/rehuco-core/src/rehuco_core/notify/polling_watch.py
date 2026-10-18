"""The file notifier's floor: a sweep of the files it knows, by stat signature, on a timer (#511,
[[mounts-and-storage#out-of-band]]).

For a folder no event backend can watch -- a share with no credentials, a disc -- and for any whose backend failed.
**The floor, never the design**: a stat per record over a LAN is 1-3 ms, so 10k records take 10-30 s, every
:data:`POLL_INTERVAL` seconds. It reports only files it was told about changing or going; a new file is the
incremental scan's to find.

**It never holds a rename up for longer than one stat**: each is taken under the rename coordinator's hold, one at a
time, so a rename that wants readers out waits for at most the one in flight.
"""

import logging
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Final

from borco_core import Presence, presence_of

from ..access import FileSignature
from ..rename_coordination import RenameCoordinator
from .raw_change import RawChange, RawChangeKind

LOG: Final = logging.getLogger(__name__)

POLL_INTERVAL: Final = 120.0
"""Seconds between the starts of two sweeps."""


# the stop event and the lock that keeps a report from outliving it are two halves of one stop
# pylint: disable-next=too-many-instance-attributes
class PollingWatch:
    """Sweeps the files it is told of, reporting each one whose modification time or size changed, or that went.

    Each sweep compares a file with what the previous sweep saw of it; the first time a file is swept, with what
    ``known`` expected of it -- the cache's row, for a root -- or, when nothing is expected, only notes it.

    :param folder: the folder the files are under; a sweep is skipped while it cannot be reached.
    :param sink: told of each change, on the sweep's thread.
    :param known: the files to sweep, each with the signature expected of it or ``None``; asked once per sweep.
    :param coordinator: the rename coordinator each stat is taken under.
    :param on_reachability: told, after every attempt at a sweep, whether the folder could be reached.
    """

    def __init__(
        self,
        folder: Path,
        sink: Callable[[RawChange], None],
        known: Callable[[], Mapping[Path, FileSignature | None]],
        coordinator: RenameCoordinator,
        *,
        on_reachability: Callable[[bool], None] | None = None,
    ) -> None:
        self.__folder: Final = folder
        self.__sink: Final = sink
        self.__known: Final = known
        self.__coordinator: Final = coordinator
        self.__on_reachability: Final = on_reachability
        self.__stopped: Final = threading.Event()
        self.__reporting: Final = threading.Lock()
        """Held while reachability is reported, and by :meth:`stop`: once stopped, no report is still on its way."""
        self.__seen: dict[Path, FileSignature | None] = {}

    def start(self) -> None:
        """Begin sweeping, the first sweep at once."""
        threading.Thread(target=self.__run, name=f"polling-watch {self.__folder}", daemon=True).start()

    def stop(self) -> None:
        """Sweep no more and report nothing more; a stat in flight is left to end on its daemon thread.

        Waits only for a reachability report already being made -- so whoever stops this and then says the folder can
        be reached is never contradicted by a sweep that finished just before.
        """
        with self.__reporting:
            self.__stopped.set()

    @property
    def failed(self) -> bool:
        """Never: a sweep that cannot reach its folder waits for the next one."""
        return False

    def sweep(self) -> bool:
        """Compare every known file with the disk once.

        :returns: whether the folder could be reached; ``False`` leaves what was seen as it was.
        """
        if presence_of(self.__folder) is not Presence.PRESENT:
            return False
        known = self.__known()
        for path in tuple(self.__seen):
            if path not in known:
                del self.__seen[path]
        for path, expected in known.items():
            if self.__stopped.is_set():
                return True
            try:
                with self.__coordinator.holding():
                    status = path.stat()
                signature: FileSignature | None = (status.st_mtime_ns, status.st_size)
            except FileNotFoundError:
                signature = None
            except OSError as error:  # the folder went away under the sweep: nothing it says now is a verdict
                LOG.info("Stopped sweeping %s at %s: %s", self.__folder, path, error)
                return False
            if path in self.__seen:
                before = self.__seen[path]
            elif expected is not None:
                before = expected
            else:  # first seen, nothing expected of it: noted, not news
                before = signature
            self.__seen[path] = signature
            if before == signature or self.__stopped.is_set():
                continue
            kind = RawChangeKind.DELETED if signature is None else RawChangeKind.MODIFIED
            self.__sink(RawChange(kind, path))
        return True

    def __run(self) -> None:
        """Sweep, wait, sweep again; until stopped."""
        while not self.__stopped.is_set():
            reachable = self.sweep()
            with self.__reporting:
                if self.__on_reachability is not None and not self.__stopped.is_set():
                    self.__on_reachability(reachable)
            self.__stopped.wait(POLL_INTERVAL)
