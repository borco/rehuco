"""Is the file a remembered path names still there -- answered without ever making anyone wait for a machine that is
switched off (#464).

**The question has three answers, not two.** A path that is not there is not necessarily *gone*: a share whose server
is off, a USB drive in a drawer and a disc that was swapped all hold the file, somewhere the machine cannot reach right
now. Forgetting such an entry for good would lose it for nothing, and showing it as an empty dock helps nobody. So:

- :attr:`Presence.PRESENT`: the file is there.
- :attr:`Presence.GONE`: **the device answered and the file is not on it** -- a fixed local drive without it, or a
  share/removable volume that is there and does not hold it. Safe to forget.
- :attr:`Presence.OFFLINE`: the device did not answer, or the answer is not a verdict (a disc, a permission error).
  Keep the entry, do not show it, ask again next run.

**What is local is decided without touching the network** (:func:`device_of`). Windows reads the drive letter's type
and, for a mapped letter, the share it maps to -- both answered from local state in under a millisecond. A UNC path
is remote by its form. POSIX reads the mount table. Only a path under a *removable container* (``/Volumes``,
``/media``, ``/run/media``, ``/mnt``) is a guess, and it guesses toward safe: such a path is treated as removable
whether or not anything is mounted there, so an unmounted ``/Volumes/USB`` is offline, never gone.

**Why a dead server must be asked about by the host, not by the file.** Measured on Windows 11 / Python 3.14.6 on a LAN
with one live SMB server and one address nothing answers at:

=================================================  ========================================
call                                               time
=================================================  ========================================
``stat`` of a file on the live server              0.005 s
TCP connect to its port 445                        0.005 s
``stat`` of a file on the switched-off host        **21.0 s** (the second try: 0.000 s, cached)
TCP connect to the switched-off host, 0.3 s limit  0.306 s (a timeout, which is the answer)
``GetDriveTypeW`` of the switched-off UNC root     **21.0 s**
``Path.resolve()`` of an unknown host's UNC path   1.3 s
=================================================  ========================================

So a remote path is first judged by whether its server answers on the filesystem's own port
(:attr:`Device.port`), bounded by :data:`REACH_TIMEOUT`; only a server that answered is ever ``stat``-ed.

**Why this runs on Python daemon threads and not on Qt's** (:class:`PresenceScan`). The agent's other background work
uses ``QThreadPool.globalInstance()``, and it should: that work is bounded, local or user-started, and its answer
goes back to a widget. This work is none of those -- it is a probe of machines that may be off, started before the
window exists -- and what matters about it is the opposite thing: **it must never be waited for.** Measured with a
``stat`` of the switched-off host (the 21 s call) still in flight when the program leaves its event loop:

=====================================================================  ===========================================
the worker is                                                          the process exits after
=====================================================================  ===========================================
a ``threading.Thread(daemon=True)``                                    0.66 s (0.5 s of it the test's own sleep)
a ``QRunnable`` on ``QThreadPool.globalInstance()``                    **21.28 s** -- Qt joins the global pool at exit
=====================================================================  ===========================================

Nothing can be killed to shorten that. ``QThread.terminate()`` stops a thread wherever it happens to be, holding
whatever it holds, and Qt documents it as unsafe; a ``QThread`` object destroyed while its thread still runs aborts
the process (the "worker crash" lesson in the work queue). A Python thread cannot be killed at all. A daemon thread
does not need to be: the interpreter does not join it, so the call stays blocked inside the operating system and the
process exits around it. A ``concurrent.futures.ThreadPoolExecutor`` is no way out either -- it registers an exit
handler that joins its workers.

The cost of that choice is the contract of :class:`PresenceScan`: it holds no Qt object, delivers each answer through
a plain callback **on its own thread** (the caller hops to the GUI thread, ``PresenceWatcher`` in the agent), and once
:meth:`~PresenceScan.stop` is called it delivers nothing more -- so an answer that arrives while the application is
tearing down is dropped instead of reaching an object that is already deleted. The convention for choosing between the
two kinds of thread is [[appendices.code-conventions#worker-threads]].

**Known limits.** A server that answers on its port and then hangs in ``stat`` leaves its paths unanswered, which the
caller treats like :attr:`Presence.OFFLINE` (kept, not shown). ``wsl.localhost`` is a 9P server, not SMB, so it has no
port to probe (:data:`UNPROBED_HOSTS`) and its paths are ``stat``-ed directly -- which starts a stopped distribution.
An NFS or SMB share mounted outside the removable containers and missing from the mount table reads as a local folder.
"""

import logging
import os
import socket
import sys
import threading
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from .platforms.linux.mount_table import Mount, read_mounts

LOG: Final = logging.getLogger(__name__)

REACH_TIMEOUT: Final = 0.3
"""Seconds to wait for a server to accept a connection before calling it offline. A live server on a LAN answers in
about 5 ms; a switched-off one never does, and this is what makes the difference between 0.3 s and 21 s."""

SMB_PORT: Final = 445
"""The port an SMB server listens on, which a Windows share's server is asked on."""

UNPROBED_HOSTS: Final = frozenset({"wsl.localhost", "wsl$"})
"""Windows hosts that are not SMB servers, so port 445 says nothing about them."""

REMOVABLE_CONTAINERS: Final = ("/Volumes", "/media", "/run/media", "/mnt")
"""Where POSIX desktops mount what is plugged in, and where an administrator mounts a share: a path under one of these
is judged by the volume it names, not by the (always present) filesystem the empty mount folder lives on."""

USER_LEVEL_CONTAINERS: Final = ("/media", "/run/media")
"""The containers that put a per-user folder before the volume's label (``/run/media/<user>/<label>``)."""


class StorageKind(StrEnum):
    """What a path's storage is, decided without touching it."""

    LOCAL = "local"
    """A fixed drive of this machine: if it is there at all, it answers, so a missing file on it is gone."""

    NETWORK = "network"
    """Served by another machine: may be off, so a missing file proves nothing until the server answers."""

    REMOVABLE = "removable"
    """Plugged in and out: the volume may simply not be there."""

    OPTICAL = "optical"
    """A disc: what is in the drive is whatever was last put in it, so a file missing from it is never gone."""


@dataclass(frozen=True)
class Device:
    """The storage under a path."""

    kind: StorageKind
    """What the storage is."""

    root: Path
    """Where the volume starts: ``D:\\``, ``\\\\nas\\share\\``, ``/Volumes/USB``. Also what groups paths that share a
    server, so it is probed once for all of them."""

    host: str | None = None
    """The server of a network volume, when the path names it."""

    port: int | None = None
    """The port to ask that server, or ``None`` when there is nothing to ask (a local volume, a server of another
    protocol)."""

    @property
    def is_local(self) -> bool:
        """Whether this is a fixed local drive -- the only kind a missing file is proof of absence on, unasked."""
        return self.kind is StorageKind.LOCAL

    @classmethod
    def of(cls, path: Path, mounts: Sequence[Mount] | None = None) -> Device:
        """The storage under ``path``, from local state only -- never a network call.

        :param path: an absolute path; it need not exist.
        :param mounts: the mount table, for a caller classifying many paths (POSIX only); ``None`` reads it.
        :returns: the device.
        """
        if sys.platform == "win32":
            return cls.__windows(path)
        return cls.__posix(path, read_mounts() if mounts is None else mounts)

    def reachable(self) -> bool:
        """Whether this device's server accepts a connection within :data:`REACH_TIMEOUT`.

        :returns: whether it answered; ``True`` where there is no server to ask.
        """
        if self.host is None or self.port is None:
            return True
        try:
            with socket.create_connection((self.host, self.port), timeout=REACH_TIMEOUT):
                return True
        except OSError:
            return False

    def volume_present(self) -> bool:
        """Whether the volume itself is there -- the drive letter exists, the folder is a mount point.

        :returns: whether it is there.
        """
        if sys.platform != "win32":
            return os.path.ismount(self.root)
        try:
            os.stat(self.root)
        except OSError:
            return False
        return True

    @classmethod
    def __windows(cls, path: Path) -> Device:  # win32-only
        """Classify a Windows path by its anchor: a UNC share, or a drive letter.

        :param path: an absolute path.
        :returns: the device.
        """
        anchor = path.anchor
        if not path.drive:
            # ``\folder\file``: no drive at all means the current one, which is whatever the process runs from -- local
            return cls(StorageKind.LOCAL, Path(anchor))
        if anchor.startswith("\\\\"):
            # never GetDriveTypeW here: on a switched-off host it blocks 21 s (see platforms.windows.drives)
            return cls.__windows_network(Path(anchor), anchor.strip("\\").split("\\", 1)[0])

        # pylint: disable-next=import-outside-toplevel
        from .platforms.windows import drives

        kind = drives.drive_type(anchor)
        if kind == drives.DRIVE_REMOTE:
            share = drives.mapped_share(anchor.rstrip("\\"))
            return cls.__windows_network(Path(anchor), share.strip("\\").split("\\", 1)[0] if share else None)
        if kind == drives.DRIVE_CDROM:
            return cls(StorageKind.OPTICAL, Path(anchor))
        if kind in (drives.DRIVE_FIXED, drives.DRIVE_RAMDISK):
            return cls(StorageKind.LOCAL, Path(anchor))
        # removable, or no drive at all behind the letter -- which is what an unplugged one looks like
        return cls(StorageKind.REMOVABLE, Path(anchor))

    @classmethod
    def __windows_network(cls, root: Path, host: str | None) -> Device:
        """A Windows network volume: SMB on :data:`SMB_PORT`, unless the host is not an SMB server.

        :param root: where the volume starts.
        :param host: its server, ``None`` when nothing names it.
        :returns: the device.
        """
        port = None if host is None or host.lower() in UNPROBED_HOSTS else SMB_PORT
        return cls(StorageKind.NETWORK, root, host, port)

    @classmethod
    def __posix(cls, path: Path, mounts: Sequence[Mount]) -> Device:
        """Classify a POSIX path by the mount holding it, else by the removable container it sits under.

        :param path: an absolute path.
        :param mounts: the mount table.
        :returns: the device.
        """
        holding = [mount for mount in mounts if path.is_relative_to(mount.point)]
        best = max(holding, key=lambda mount: len(mount.point.parts), default=None)
        if best is not None and best.is_network:
            return cls(StorageKind.NETWORK, best.point, best.host, best.port)
        if best is not None and best.is_optical:
            return cls(StorageKind.OPTICAL, best.point)
        volume = cls.__removable_volume(path)
        if volume is not None:
            return cls(StorageKind.REMOVABLE, volume)
        return cls(StorageKind.LOCAL, Path(path.anchor))

    @staticmethod
    def __removable_volume(path: Path) -> Path | None:
        """The volume folder ``path`` sits under in a removable container, or ``None`` outside every container.

        ``/Volumes/USB/x`` and ``/mnt/nas/x`` name their volume one level down; ``/run/media/<user>/<label>/x`` two. The
        one container that is ambiguous is ``/media``, which older systems use without a user level: it takes two levels
        only when the first is the current user's name.

        :param path: an absolute POSIX path.
        :returns: the volume's folder, or ``None``.
        """
        for container in REMOVABLE_CONTAINERS:
            if not path.is_relative_to(container):
                continue
            parts = path.relative_to(container).parts
            levels = 1
            if container in USER_LEVEL_CONTAINERS and (
                container == "/run/media" or parts[:1] == (os.environ.get("USER"),)
            ):
                levels = 2
            return Path(container, *parts[:levels]) if len(parts) >= levels else None
        return None


class Presence(StrEnum):
    """What is known about a remembered path."""

    PRESENT = "present"
    """The file is there."""

    GONE = "gone"
    """The device answered and the file is not on it: safe to forget."""

    OFFLINE = "offline"
    """The device did not answer, or its answer is no verdict: keep the entry, ask again."""

    @classmethod
    def judge(cls, path: Path, device: Device, reachable: Callable[[], bool]) -> Presence:
        """The verdict for one path on its device.

        :param path: the path.
        :param device: its device.
        :param reachable: whether its server answers, passed in so a scan asks it once per server.
        :returns: the verdict.
        """
        if device.is_local:
            found = cls.__exists(path)
            return cls.OFFLINE if found is None else cls.PRESENT if found else cls.GONE
        if not reachable():
            return cls.OFFLINE
        found = cls.__exists(path)
        if found is None:
            return cls.OFFLINE
        if found:
            return cls.PRESENT
        if device.kind is StorageKind.OPTICAL or not device.volume_present():
            return cls.OFFLINE
        return cls.GONE

    @staticmethod
    def __exists(path: Path) -> bool | None:
        """Whether ``path`` exists, as a plain ``stat`` says: ``Path.exists()`` folds every ``OSError`` into ``False``.

        :param path: the path.
        :returns: ``True`` or ``False``; ``None`` when the operating system gave no verdict (a permission error, an
            unusable name), which is not the same as absent.
        """
        try:
            os.stat(path)
        except FileNotFoundError, NotADirectoryError:
            return False
        except OSError:
            return None
        return True


def device_of(path: Path, mounts: Sequence[Mount] | None = None) -> Device:
    """The storage under ``path``, from local state only -- never a network call (:meth:`Device.of`).

    :param path: an absolute path; it need not exist.
    :param mounts: the mount table, for a caller classifying many paths (POSIX only); ``None`` reads it.
    :returns: the device.
    """
    return Device.of(path, mounts)


def presence_of(path: Path, mounts: Sequence[Mount] | None = None, *, device: Device | None = None) -> Presence:
    """Whether ``path`` is there, blocking for at most :data:`REACH_TIMEOUT` when its server is off.

    For a path on a fixed local drive this is one ``stat`` and is safe to call on the GUI thread; for any other it can
    wait the full timeout (and, past a server that accepts and then hangs, longer), so it belongs on a
    :class:`PresenceScan`.

    :param path: an absolute path.
    :param mounts: see :func:`device_of`.
    :param device: ``path``'s device when the caller has already classified it, to not do that twice.
    :returns: the verdict.
    """
    device = device_of(path, mounts) if device is None else device
    return Presence.judge(path, device, device.reachable)


class PresenceScan:
    """Finds out, for a set of remembered paths, which are there -- on daemon threads, delivering each answer as it
    arrives, and never delaying the program's exit.

    Local paths are answered first, from one coordinator thread; every other path is grouped by its volume and each
    group gets a thread of its own, which asks the server once and then judges its paths. One switched-off server
    therefore delays only its own paths, and only by :data:`REACH_TIMEOUT`.

    **Why Python threads rather than Qt's is documented once, in the module docstring**, with the measurements.
    The contract that follows from it: ``on_answer`` runs on a scan thread, so it must only hand the answer on (the
    agent's ``PresenceWatcher`` emits a queued signal); and after :meth:`stop` it is never called again.

    :param paths: the paths to ask about; each is answered exactly once, unless the scan is stopped first.
    :param on_answer: called with ``(path, presence)`` from a scan thread.
    """

    def __init__(self, paths: Iterable[Path], on_answer: Callable[[Path, Presence], None]) -> None:
        self.__paths: Final = tuple(dict.fromkeys(paths))
        self.__on_answer: Final = on_answer
        self.__stopped: Final = threading.Event()
        self.__started = False

    def start(self) -> None:
        """Begin asking. A no-op the second time, and when there is nothing to ask."""
        if self.__started or not self.__paths:
            return
        self.__started = True
        threading.Thread(target=self.__run, name="presence-scan", daemon=True).start()

    def stop(self) -> None:
        """Deliver no more answers. Does not wait for, or interrupt, a call still blocked in the operating system:
        that thread is a daemon, and the process leaves without it.
        """
        self.__stopped.set()

    @property
    def stopped(self) -> bool:
        """Whether :meth:`stop` was called."""
        return self.__stopped.is_set()

    def __run(self) -> None:
        """The coordinator: classify every path, answer the local ones, hand the rest to a thread per volume."""
        mounts = read_mounts() if sys.platform != "win32" else ()
        groups: dict[Path, list[tuple[Path, Device]]] = {}
        for path in self.__paths:
            if self.stopped:
                return
            device = device_of(path, mounts)
            if device.is_local:
                self.__answer(path, Presence.judge(path, device, lambda: True))
            else:
                groups.setdefault(device.root, []).append((path, device))
        for index, members in enumerate(groups.values()):
            threading.Thread(
                target=self.__run_group, args=(members,), name=f"presence-scan-{index}", daemon=True
            ).start()

    def __run_group(self, members: list[tuple[Path, Device]]) -> None:
        """One volume's paths: ask its server once, then judge each.

        :param members: the volume's paths, each with its device.
        """
        answer: list[bool] = []

        def reachable() -> bool:
            """Whether the volume's server answers, asked the first time only.

            :returns: its answer.
            """
            if not answer:
                answer.append(members[0][1].reachable())
            return answer[0]

        for path, device in members:
            if self.stopped:
                return
            self.__answer(path, Presence.judge(path, device, reachable))

    def __answer(self, path: Path, presence: Presence) -> None:
        """Deliver one answer, unless the scan was stopped while it was being worked out.

        :param path: the path.
        :param presence: its verdict.
        """
        if not self.stopped:
            self.__on_answer(path, presence)
