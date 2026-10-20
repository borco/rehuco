"""The lock file beside a record, which keeps its writers apart across processes and machines (#512,
[[sync#lock-file]]).

Every write to a record takes ``<record>.lock`` beside it -- ``info.rehu.lock`` beside ``info.rehu`` -- created with an
exclusive create, which on SMB2 is a server-side atomic create and the one locking primitive Windows, macOS and Linux
clients all honour (#503). **The lock is the directory entry, never an open handle**: it is created, written with who
holds it (``user@host pid app time``) and closed in one go, and read back when someone else finds it; a handle kept
open would outlive its holder by a minute on the macOS client. It is read with delete shared: a plain Windows open of
it denies its holder the delete that releases it, and every writer then waits out the TTL.

- **Busy** is retried with a random back-off of a few tens of milliseconds, never spun, for a bounded time; still busy,
  the write fails with a :class:`RecordLockedError` naming the holder.
- **Stale** is a lock older than the TTL by the time its own content names -- by its modification time when it names
  none, which is a holder that died between the create and the write. It is deleted, verified gone, and logged; a name
  that lingers is treated as held.
- **The lock narrows the window; the compare is the safety** ([[sync#compare-and-swap]]). Two writers breaking one
  stale lock at once can delete a fresh one taken between the read and the delete -- microseconds against a 2-minute
  TTL -- and a save then still meets the compare under the lock.
"""

import getpass
import logging
import os
import random
import socket
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Final, Self, override

from borco_core import shared_read_open

from .constants import CHECKSUM_RECORD_SUFFIX, REHUCO_SUFFIX
from .resource_scoping import is_record_name

LOG: Final = logging.getLogger(__name__)

LOCK_SUFFIX: Final = ".lock"
"""What a record's lock file adds to the record's own name."""

DEFAULT_LOCK_TTL_SECONDS: Final = 120.0
"""How old a lock must be to count as abandoned ([[sync#lock-file]]): far longer than any save holds one, and far
longer than the ~10 s the Windows SMB client caches a file's attributes."""

DEFAULT_LOCK_TIMEOUT_SECONDS: Final = 2.0
"""How long a busy lock is retried before the write gives up. Short: a save runs on the GUI thread, and a lock is held
for milliseconds."""

LOCK_BACKOFF_SECONDS: Final = (0.01, 0.05)
"""The range a busy lock's random back-off is drawn from, so contenders spread out rather than retry in step."""

RELEASE_RETRY_SECONDS: Final = (0.01, 0.02, 0.05, 0.1)
"""How long to wait before each retry of a release refused with a ``PermissionError`` -- a scanner or indexer briefly
holding the lock open, on Windows. A lock left behind costs every other writer the TTL."""


LOCKS_GUARD: Final = threading.Lock()
"""Guards :data:`LOCKS` itself, held only long enough to find or add one path's lock."""

LOCKS: Final[dict[Path, threading.Lock]] = {}
"""One lock per file this process has written under :func:`locked_record`, by resolved path. Never pruned: an entry
is a path and a lock, and a session touches as many records as it opens."""


@contextmanager
def locked_record(path: Path, *, user: str | None, timeout: float = DEFAULT_LOCK_TIMEOUT_SECONDS) -> Iterator[None]:
    """Hold a record for one write: this process's lock on it first, then its lock file ([[sync#lock-file]]).

    In that order, so two threads here queue in memory rather than race each other for the file.

    :param path: the record -- a ``.rehu``, a ``.checksum``.
    :param user: the identity written into the lock file; ``None`` takes the login name.
    :param timeout: how long a busy lock file is retried, in seconds.
    :returns: a context holding both locks.
    :raises RecordLockedError: someone else held the lock file for longer than ``timeout``.
    :raises OSError: the lock file could not be created.
    """
    with record_lock(path), RecordFileLock(path, user=user, timeout=timeout):
        yield


def record_lock(path: Path) -> threading.Lock:
    """The lock serializing writes of ``path`` in this process.

    :param path: the record; resolved, so two spellings of one file share a lock.
    :returns: its lock, created on first use.
    """
    key = path.resolve()
    with LOCKS_GUARD:
        lock = LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            LOCKS[key] = lock
        return lock


def lock_path_for(path: Path) -> Path:
    """The lock file of a record.

    :param path: the record -- a ``.rehu``, a ``.tc``, a ``.rehuco``.
    :returns: the lock beside it, its name the record's with :data:`LOCK_SUFFIX` added.
    """
    return path.with_name(path.name + LOCK_SUFFIX)


def is_lock_name(filename: str) -> bool:
    """Whether ``filename`` names a record's lock file -- what scans, checksums, listings and renames leave out.

    Only a lock *beside a record's name* is one: a ``yarn.lock`` or ``poetry.lock`` in a code tutorial is content.

    :param filename: a file's name, not its path.
    :returns: whether it is ``<record>.lock`` for a ``.rehu``, ``.tc``, ``.checksum`` or ``.rehuco``.
    """
    if not filename.lower().endswith(LOCK_SUFFIX):
        return False
    locked = filename[: -len(LOCK_SUFFIX)]
    return is_record_name(locked) or locked.lower().endswith((CHECKSUM_RECORD_SUFFIX, REHUCO_SUFFIX))


@dataclass(frozen=True, slots=True)
class LockHolder:
    """Who holds a lock, as its content says.

    :param user: the identity the holder writes as.
    :param host: the machine it runs on.
    :param pid: its process id.
    :param app: the program, from its executable's name.
    :param time: when it took the lock, in UTC.
    """

    user: str
    host: str
    pid: int
    app: str
    time: datetime

    @classmethod
    def current(cls, user: str | None, at: float) -> Self:
        """This process, as a holder.

        :param user: the identity it writes as; ``None`` takes the login name.
        :param at: when, in seconds since the epoch.
        :returns: the holder.
        """
        app = "-".join(Path(sys.argv[0]).stem.split()) or "python"
        return cls(
            user if user else getpass.getuser(), socket.gethostname(), os.getpid(), app, datetime.fromtimestamp(at, UTC)
        )

    @classmethod
    def parse(cls, text: str) -> Self | None:
        """Read a lock's content.

        :param text: what the lock holds.
        :returns: its holder, or ``None`` when the text is not one -- empty, while its holder is between the create
            and the write.
        """
        parts = text.strip().rsplit(" ", 3)
        if len(parts) != 4:
            return None
        user_at_host, pid, app, stamp = parts
        user, at, host = user_at_host.rpartition("@")
        try:
            moment = datetime.fromisoformat(stamp)
            number = int(pid)
        except ValueError:
            return None
        if not at or moment.tzinfo is None:
            return None
        return cls(user, host, number, app, moment)

    def text(self) -> str:
        """The lock's content for this holder.

        :returns: ``user@host pid app time``.
        """
        return f"{self.user}@{self.host} {self.pid} {self.app} {self.time.isoformat(timespec='milliseconds')}"

    def is_this_process(self) -> bool:
        """Whether this holder is the process asking.

        :returns: whether its host and process id are this one's.
        """
        return self.host == socket.gethostname() and self.pid == os.getpid()

    @override
    def __str__(self) -> str:
        """The holder as a sentence names it: ``user@host (app, pid N) since <time> UTC``."""
        return f"{self.user}@{self.host} ({self.app}, pid {self.pid}) since {self.time:%Y-%m-%d %H:%M:%S} UTC"


class RecordLockedError(OSError):
    """A record whose lock someone else holds -- a write that waited out its time, or a rename refused.

    An ``OSError``, so a caller treating every failed write alike offers it as one, with the holder in the message.

    :param path: the record.
    :param holder: who holds its lock, or ``None`` when the lock does not say.
    """

    def __init__(self, path: Path, holder: LockHolder | None) -> None:
        super().__init__(f"{path} is locked by {holder if holder is not None else 'someone else'}")
        self.path: Final = path
        self.holder: Final = holder


class RecordFileLock:
    """The lock file of one record, taken for one write ([[sync#lock-file]]).

    A context manager: entering takes the lock, waiting out a busy one and breaking a stale one; leaving removes it.

    :param path: the record; the lock goes beside it (:func:`lock_path_for`).
    :param user: the identity written into the lock; ``None`` takes the login name.
    :param ttl: how old a lock must be to be broken, in seconds.
    :param timeout: how long a busy lock is retried, in seconds.
    :param clock: the time now, in seconds since the epoch.
    :param sleep: how a back-off waits.
    """

    @dataclass(frozen=True, slots=True)
    class Sighting:
        """A lock as found.

        :param text: its content.
        :param holder: who it names, if it names anyone.
        :param fresh: whether it is younger than the TTL.
        """

        text: str
        holder: LockHolder | None
        fresh: bool

    def __init__(  # pylint: disable=too-many-arguments
        self,
        path: Path,
        *,
        user: str | None = None,
        ttl: float = DEFAULT_LOCK_TTL_SECONDS,
        timeout: float = DEFAULT_LOCK_TIMEOUT_SECONDS,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.__record: Final = path
        self.__user: Final = user
        self.__ttl: Final = ttl
        self.__timeout: Final = timeout
        self.__clock: Final = clock
        self.__sleep: Final = sleep
        self.__text: str | None = None

    @property
    def path(self) -> Path:
        """The lock file."""
        return lock_path_for(self.__record)

    def __enter__(self) -> Self:
        """Take the lock (:meth:`acquire`).

        :returns: this lock.
        """
        self.acquire()
        return self

    def __exit__(
        self, kind: type[BaseException] | None, error: BaseException | None, traceback: TracebackType | None
    ) -> None:
        """Remove the lock (:meth:`release`), whatever the write did.

        :param kind: the exception's type, if the write raised.
        :param error: the exception.
        :param traceback: its traceback.
        """
        self.release()

    def acquire(self) -> None:
        """Take the lock, retrying a busy one with a random back-off and breaking a stale one.

        :raises RecordLockedError: still busy after the timeout.
        :raises PermissionError: the create was refused with no lock there to refuse it -- a folder this process may
            not write; raised at once, not after the timeout.
        :raises OSError: the lock could not be created for another reason, such as a folder that is gone.
        """
        deadline = self.__clock() + self.__timeout
        refusal: PermissionError | None = None
        seen: RecordFileLock.Sighting | None = None
        while True:
            text = LockHolder.current(self.__user, self.__clock()).text()
            try:
                self.__create(text)
            except FileExistsError:
                pass
            except PermissionError as error:
                # what Windows answers for a name whose delete is still pending, as well as for a folder it may not
                # write: told apart by whether a lock was ever there to read
                refusal = error
            else:
                self.__text = text
                return
            sighting = self.__look()
            if sighting is not None:
                seen = sighting
                if not sighting.fresh and self.__break(sighting):
                    continue
            elif not self.path.exists():
                # no lock there at all: a refused create was the folder's doing, and a lock seen earlier is gone
                if refusal is not None:
                    raise refusal
                seen = None
            if self.__clock() >= deadline:
                raise RecordLockedError(self.__record, seen.holder if seen is not None else None)
            self.__sleep(random.uniform(*LOCK_BACKOFF_SECONDS))  # nosec  # B311: a back-off jitter, not a secret

    def release(self) -> None:
        """Remove the lock this took, and verify it is gone. Never raises, so a write's own failure is what is seen.

        A lock whose content is no longer this one's -- broken as stale and taken by someone else -- is left alone.
        """
        text = self.__text
        if text is None:
            return
        self.__text = None
        try:
            if self.__read() != text:
                LOG.warning("The lock on %s was taken over before it was released, and is left", self.__record)
                return
        except FileNotFoundError:
            LOG.warning("The lock on %s was gone before it was released", self.__record)
            return
        except OSError as error:
            LOG.warning("Could not remove the lock on %s: %s", self.__record, error)
            return
        if self.__remove() and self.path.exists():
            # a delete pending while another writer reads the lock: the name goes when that read closes, and until
            # then it reads as held, which is what it is meant to do
            LOG.info("The lock on %s is still listed after it was removed", self.__record)

    def refuse_if_held(self) -> None:
        """Refuse an operation that moves the record without writing it -- a rename -- while someone else holds its
        lock. A stale lock is broken rather than obeyed -- but one that lingers after the break, or was retaken
        meanwhile, is held; this process's own is no one else's.

        :raises RecordLockedError: a fresh lock held by another process, or a stale one that would not go.
        """
        sighting = self.__look()
        if sighting is not None and not sighting.fresh:
            if self.__break(sighting):
                return
            sighting = self.__look() or sighting
        if sighting is None:
            return
        if sighting.holder is not None and sighting.holder.is_this_process():
            return
        raise RecordLockedError(self.__record, sighting.holder)

    def __create(self, text: str) -> None:
        """Create the lock exclusively, write ``text`` into it and close it at once.

        :param text: the holder's content.
        :raises FileExistsError: the lock is there.
        :raises OSError: it could not be created or written; one created and not written is removed again.
        """
        descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.write(descriptor, text.encode("utf-8"))
        except OSError:
            os.close(descriptor)
            self.path.unlink(missing_ok=True)
            raise
        os.close(descriptor)

    def __remove(self) -> bool:
        """Delete this process's lock, retrying a refusal for :data:`RELEASE_RETRY_SECONDS`.

        :returns: whether it was deleted; a failure is logged.
        """
        delays = iter(RELEASE_RETRY_SECONDS)
        while True:
            try:
                self.path.unlink()
            except FileNotFoundError:
                LOG.warning("The lock on %s was gone before it was released", self.__record)
                return False
            except PermissionError as error:
                delay = next(delays, None)
                if delay is None:
                    LOG.warning("Could not remove the lock on %s: %s", self.__record, error)
                    return False
                self.__sleep(delay)
            except OSError as error:
                LOG.warning("Could not remove the lock on %s: %s", self.__record, error)
                return False
            else:
                return True

    def __read(self) -> str:
        """The lock's content, read without denying its holder the delete that releases it -- a plain open on Windows
        would, and leave the lock to go stale.

        :returns: its text.
        :raises OSError: it could not be read; ``FileNotFoundError`` when it is gone.
        """
        with shared_read_open(self.path) as file:
            return file.read().decode("utf-8", errors="replace")

    def __look(self) -> Sighting | None:
        """Read the lock someone else holds, and judge its age.

        :returns: the lock as found, or ``None`` when it is gone or could not be read.
        """
        try:
            text = self.__read()
            modified = self.path.stat().st_mtime
        except OSError:
            return None
        holder = LockHolder.parse(text)
        taken = holder.time.timestamp() if holder is not None else modified
        return self.Sighting(text, holder, self.__clock() - taken < self.__ttl)

    def __break(self, sighting: Sighting) -> bool:
        """Delete a stale lock, if it is still the one judged stale, and verify it is gone.

        :param sighting: the stale lock as found.
        :returns: whether it is gone, so taking the lock may be tried again at once; ``False`` when it changed, could
            not be deleted, or lingers -- held, then.
        """
        try:
            if self.__read() != sighting.text:
                return False
            self.path.unlink()
        except FileNotFoundError:
            return True
        except OSError:
            return False
        if self.path.exists():
            return False
        holder = sighting.holder if sighting.holder is not None else "a holder it does not name"
        LOG.warning("Broke the stale lock on %s, left by %s", self.__record, holder)
        return True
