"""The app's one source of what changed on disk: a folder watched by the best backend its storage allows, polled when
none can, publishing on the change feed (#511, [[mounts-and-storage#out-of-band]]).

**The backend follows the storage kind**, detected without touching the folder (:func:`borco_core.device_of`):

- a local or removable disk: the operating system's events (:class:`~rehuco_core.notify.NativeWatch`);
- an SMB share: ``CHANGE_NOTIFY`` on a session of our own (:class:`~rehuco_core.notify.SmbWatch`), on Windows;
- anything else -- a disc, a share on macOS or Linux, which would need stored credentials -- and any folder whose
  backend failed: a sweep by stat signature on a timer (:class:`~rehuco_core.notify.PollingWatch`).

**It survives the folder going away** ([[mounts-and-storage#offline-mounts]]): when the backend fails, the folder is
polled -- each sweep says whether it can be reached -- and the backend is tried again every :data:`RETRY_SECONDS` while
it can. Once it is back, everything that may have happened in between is announced at once: the root is
:class:`~rehuco_core.access.RootStale`.

**It never holds up quitting** ([[appendices.code-conventions#worker-threads]]): everything runs on daemon threads,
:meth:`FileNotifier.stop` returns at once, and nothing is delivered after it.
"""

import logging
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Final

from borco_core import Device, Presence, StorageKind, device_of, presence_of

from ..access import ChangeFeed, FileSignature, RootReachable
from ..rename_coordination import DEFAULT_RENAME_COORDINATOR, RenameCoordinator
from .change_coalescer import ChangeCoalescer
from .native_watch import NativeWatch
from .polling_watch import PollingWatch
from .raw_change import RawChange, RawChangeKind
from .smb_watch import SmbWatch
from .watch import Watch
from .watched_folder import WatchedFolder

LOG: Final = logging.getLogger(__name__)

HEALTH_SECONDS: Final = 1.0
"""How often a running backend is checked for having failed."""

RETRY_SECONDS: Final = 30.0
"""How often a failed backend is tried again while its folder can be reached."""

PRESENCE_SECONDS: Final = 30.0
"""How often a folder a backend watches is checked for still being there -- what no backend says on its own."""


class FileNotifier:
    """Watches one folder and publishes what changed in it on a :class:`~rehuco_core.access.ChangeFeed`.

    :param folder: what to watch.
    :param feed: where to publish.
    :param known: the files a sweep compares with the disk, each with the signature expected of it, for when the folder
        is polled; asked on the sweep's thread. A root's are its cache rows.
    :param coordinator: the rename coordinator a sweep's stats and a yielding watch answer to.
    """

    def __init__(
        self,
        folder: WatchedFolder,
        feed: ChangeFeed,
        known: Callable[[], Mapping[Path, FileSignature | None]] | None = None,
        coordinator: RenameCoordinator = DEFAULT_RENAME_COORDINATOR,
    ) -> None:
        self.__folder: Final = folder
        self.__feed: Final = feed
        self.__known: Final = known if known is not None else dict
        self.__coordinator: Final = coordinator
        self.__coalescer: Final = ChangeCoalescer(feed, folder.path, folder.root_id)
        self.__stopped: Final = threading.Event()
        self.__reachable: bool | None = None

    @property
    def folder(self) -> WatchedFolder:
        """What it watches."""
        return self.__folder

    def start(self) -> None:
        """Begin watching, on daemon threads."""
        self.__coalescer.start()
        threading.Thread(target=self.__run, name=f"file-notifier {self.__folder.path}", daemon=True).start()

    def stop(self) -> None:
        """Publish nothing more. The backend closes within :data:`HEALTH_SECONDS`, on its thread."""
        self.__stopped.set()
        self.__coalescer.stop()

    def __run(self) -> None:
        """Watch with the best backend; poll while it cannot; try it again while the folder is there."""
        path = self.__folder.path
        device = device_of(path)
        polling: PollingWatch | None = None
        lost = complained = False
        while not self.__stopped.is_set():
            watch = self.__opened(device, complained)
            if watch is not None:
                if polling is not None:
                    polling.stop()
                    polling = None
                self.__reach(True)
                if lost:
                    LOG.info("Watching %s again.", path)
                    self.__coalescer.push(RawChange(RawChangeKind.OVERFLOW, path))
                lost = complained = False
                self.__watching(watch, device)
                watch.stop()
                if self.__stopped.is_set():
                    break
                LOG.warning("Lost the watch of %s; polling it until it can be watched again.", path)
            # a sweep finds only the files it knows: once watched again, a scan finds the rest
            lost = complained = True
            if polling is None:
                polling = PollingWatch(
                    path, self.__coalescer.push, self.__known, self.__coordinator, on_reachability=self.__reach
                )
                polling.start()
            if not FileNotifier.watchable(device):
                self.__stopped.wait()
                break
            while not self.__stopped.wait(RETRY_SECONDS) and presence_of(path, device=device) is not Presence.PRESENT:
                pass
        if polling is not None:
            polling.stop()

    def __watching(self, watch: Watch, device: Device) -> None:
        """Wait while a backend watches: until it fails, the folder stops being there, or the notifier is stopped.

        **A backend does not always notice its folder going.** An SMB session waits out the server's silence for many
        minutes when the server vanished without closing the connection -- its power cut, a cable pulled -- and a
        native watch follows its folder when it is renamed, reporting on under the old name. So the folder itself is
        looked at every :data:`PRESENCE_SECONDS`: a share by asking its server, for at most
        :data:`~borco_core.path_presence.REACH_TIMEOUT`.

        :param watch: the running backend.
        :param device: the folder's storage.
        """
        path = self.__folder.path
        checked = time.monotonic()
        while not watch.failed and not self.__stopped.wait(HEALTH_SECONDS):
            if time.monotonic() - checked < PRESENCE_SECONDS:
                continue
            checked = time.monotonic()
            if presence_of(path, device=device) is not Presence.PRESENT:
                LOG.warning("%s is not there any more.", path)
                return

    @staticmethod
    def watchable(device: Device) -> bool:
        """Whether a folder on ``device`` has an event backend at all, or can only ever be polled.

        :param device: the folder's storage.
        :returns: whether an event backend is worth trying.
        """
        return device.kind in (StorageKind.LOCAL, StorageKind.REMOVABLE, StorageKind.NETWORK)

    def __opened(self, device: Device, quietly: bool) -> Watch | None:
        """The event backend for the folder's storage, started; ``None`` when it has none, or it would not start.

        :param device: the folder's storage.
        :param quietly: whether a failure to start was already logged in this outage.
        :returns: the running backend, or ``None``.
        """
        folder = self.__folder
        watch: Watch | None
        match device.kind:
            case StorageKind.LOCAL | StorageKind.REMOVABLE:
                # a root's watch never stands in a rename's way; a loose folder's may, so it lets go (see NativeWatch)
                coordinator = self.__coordinator if folder.root_id is None else None
                watch = NativeWatch(folder, self.__coalescer.push, coordinator)
            case StorageKind.NETWORK:
                watch = SmbWatch.located(folder.path, self.__coalescer.push)
            case _:
                watch = None
        if watch is None:
            return None
        try:
            watch.start()
        except OSError as error:
            (LOG.debug if quietly else LOG.warning)("Could not watch %s: %s", folder.path, error)
            return None
        return watch

    def __reach(self, reachable: bool) -> None:
        """Publish whether a root's folder can be reached, when that changed (any of the notifier's threads).

        :param reachable: whether it can.
        """
        root_id = self.__folder.root_id
        if root_id is None or self.__stopped.is_set() or reachable == self.__reachable:
            return
        self.__reachable = reachable
        self.__feed.publish(RootReachable(root_id, reachable))
