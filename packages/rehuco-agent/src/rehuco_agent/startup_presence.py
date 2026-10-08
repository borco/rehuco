"""Which of the paths the last run remembered are still there -- settled without the start ever waiting (#464).

The remembered paths are the ``File`` menu's recents, the root catalogs' recents and open one, and the documents the
session left open. A file deleted since is noise in all of them (an empty locked ``missing`` dock, a menu entry that
opens nothing), and the application cannot yet show it from a retained copy (Release 0.4.0), so it is forgotten.

**Two speeds, decided without touching the network** (:func:`borco_core.device_of`):

- A path on a **fixed local drive** is checked right here, on the GUI thread, with one ``stat``: a local drive that is
  there answers in microseconds, and a path on it that is not there is *gone*. The window is built already knowing.
- Every other path -- a share, a removable drive, a disc -- is handed to a :class:`borco_core.PresenceScan` on daemon
  threads and answered later, one signal per path. Until it is, :meth:`StartupPresence.unavailable` says so and the
  menus show the entry disabled. A server that does not answer is **offline**: the entry stays disabled, remembered,
  and is asked again next run; only a device that answered and does not hold the file makes it *gone*.

**Why the scan is not a Qt job** is the module docstring of :mod:`borco_core.path_presence`, with the measurements:
a ``QThreadPool`` worker stuck in a call to a switched-off server keeps the process alive for the 21 s the call takes,
and a daemon thread does not. This class is the Qt side of that contract: the scan's callback runs on its thread, so
it only emits a signal, which Qt delivers to the GUI thread; and :meth:`~StartupPresence.stop` is called first thing
when the window closes, so an answer racing the teardown is dropped.
"""

import logging
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Final

from borco_core import Device, Presence, PresenceScan, device_of, presence_of
from borco_core.platforms.linux.mount_table import read_mounts
from PySide6.QtCore import QObject, Qt, Signal, Slot

LOG: Final = logging.getLogger(__name__)


class StartupPresence(QObject):
    """The verdict on every remembered path: local ones at construction, the rest as the scan hears from them.

    :param paths: every remembered path to judge; duplicates are judged once.
    :param parent: optional Qt parent.
    """

    answered: Signal = Signal(object, object)
    """Emitted ``(path, presence)`` on the GUI thread for each **remote** path once it is judged -- never for a path
    on a fixed local drive, which :meth:`local_presence` already holds."""

    __relayed: Signal = Signal(object, object)
    """Emitted from a scan thread with each answer; its slot runs on the GUI thread (the connection is queued because
    the sender's thread is not the receiver's), which is where the stale-answer judgement belongs."""

    def __init__(self, paths: Iterable[Path], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__relayed.connect(self.__on_relayed, Qt.ConnectionType.QueuedConnection)
        self.__local: Final[dict[Path, Presence]] = {}
        self.__remote: Final[dict[Path, Presence | None]] = {}
        """Each remote path's verdict, ``None`` until it is heard."""
        mounts = read_mounts() if sys.platform != "win32" else ()
        for path in dict.fromkeys(paths):
            device: Device = device_of(path, mounts)
            if device.is_local:
                self.__local[path] = presence_of(path, mounts, device=device)  # pylint: disable=unsupported-assignment-operation
            else:
                self.__remote[path] = None  # pylint: disable=unsupported-assignment-operation
        self.__scan: Final = PresenceScan(self.__remote, self.__relay)
        # a window torn down without a close (a test, a crash path) must not be emitted into from a scan thread
        # after its C++ object is gone: ``stop`` is a plain Python bound method, so it is safe to run from here
        self.destroyed.connect(self.__scan.stop)

    @property
    def local_paths(self) -> dict[Path, Presence]:
        """The verdict on every path on a fixed local drive. It is final: a local drive's answer is one ``stat``."""
        return dict(self.__local)

    def local_presence(self, path: Path) -> Presence | None:
        """The verdict on one local path, or ``None`` when it is not a local path this judged."""
        return self.__local.get(path)

    def is_remote(self, path: Path) -> bool:
        """Whether ``path`` was left to the scan."""
        return path in self.__remote

    def unavailable(self, path: Path) -> bool:
        """Whether ``path`` is remote and not known to be there -- not heard from yet, or its device is offline.

        A path this never saw -- one opened during the run -- is available: it was just reached.
        """
        return path in self.__remote and self.__remote[path] is not Presence.PRESENT

    def start(self) -> None:
        """Begin asking about the remote paths."""
        self.__scan.start()

    def stop(self) -> None:
        """Deliver no more answers. Does not wait for a call still blocked on a switched-off server: it is on a daemon
        thread, and the process leaves without it."""
        self.__scan.stop()

    def forget(self, path: Path) -> None:
        """Stop tracking ``path`` -- it was forgotten, so a later answer about it is moot."""
        self.__local.pop(path, None)
        self.__remote.pop(path, None)

    def __relay(self, path: Path, presence: Presence) -> None:
        """The scan's callback, on a scan thread: hand the answer to the GUI thread and nothing else."""
        self.__relayed.emit(path, presence)

    @Slot(object, object)
    def __on_relayed(self, path: Path, presence: Presence) -> None:
        """On the GUI thread: note the verdict, then tell everyone -- so a listener asking :meth:`unavailable` from
        its slot already hears the new answer. An answer about a path forgotten meanwhile is dropped."""
        if path not in self.__remote:
            return
        self.__remote[path] = presence  # pylint: disable=unsupported-assignment-operation
        self.answered.emit(path, presence)
