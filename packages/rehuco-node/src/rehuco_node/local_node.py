"""The local node's process: a heartbeat file and a log, for as long as its host keeps it (#506).

Qt-free. The node runs as the user who runs the agent, started by the agent a little after its window is up and
stopped when the agent quits; nothing it does yet is visible to anyone but that agent, which reads the heartbeat
to say whether the node is running. What it will serve -- the web pages, the jobs, the borrow store -- lands on
this lifecycle later.

Two things decide the shape of the loop. **The agent holds the node's stdin**: the node stops when that pipe
reaches EOF, so an agent that quits, or crashes, takes the node down with it and never leaves an orphan behind.
**The heartbeat file is the node's only statement about itself**: present and fresh means running; absent or
stale means not, whatever a stale pid says.
"""

import json
import logging
import os
import signal
import sys
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO, Final, Self

from borco_core import atomic_write_text
from borco_core.logging import SharedRotatingFileHandler
from rehuco_core import AppFolders

from . import __version__

LOG: Final = logging.getLogger(__name__)

NODE_FOLDER_NAME: Final = "node"
"""The node's folder under the data folder ([[packaging-deployment#app-folders]])."""

HEARTBEAT_FILE_NAME: Final = "node.json"
"""The heartbeat, in :func:`node_folder`."""

LOG_FILE_NAME: Final = "rehuco-node.log"
"""The node's own run log, in :func:`node_folder`; the node is its only writer, so it rotates it."""

HEARTBEAT_SECONDS: Final = 2.0
"""How often the heartbeat is rewritten while the node runs."""

STALE_AFTER_SECONDS: Final = 3 * HEARTBEAT_SECONDS
"""A heartbeat older than this is a node that is gone without removing its file -- killed, or its machine
powered off."""

LOG_FORMAT: Final = "{asctime} {process} {threadName} {levelname} {name}: {message}"
LOG_MAX_BYTES: Final = 2 * 1024 * 1024
LOG_BACKUPS: Final = 2


def node_folder(folders: AppFolders) -> Path:
    """Where this node keeps its files.

    :param folders: the app folders the agent and the node share.
    :returns: the folder; not created by this call.
    """
    return folders.data / NODE_FOLDER_NAME


def now_iso() -> str:
    """The current time, in UTC, as the heartbeat writes it."""
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class NodeHeartbeat:
    """What a running node says about itself, every :data:`HEARTBEAT_SECONDS`.

    :param pid: the node process.
    :param version: the ``rehuco-node`` version running.
    :param started: when the process started, ISO 8601 UTC.
    :param beat: when this heartbeat was written, ISO 8601 UTC.
    """

    pid: int
    version: str
    started: str
    beat: str

    def to_json(self) -> str:
        """The heartbeat as the file's text."""
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, text: str) -> Self:
        """Parse a heartbeat file's text.

        :param text: the file's content.
        :returns: the heartbeat.
        :raises ValueError: when the text is not a heartbeat.
        """
        try:
            data = json.loads(text)
            return cls(
                pid=int(data["pid"]), version=str(data["version"]), started=str(data["started"]), beat=str(data["beat"])
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise ValueError(f"not a node heartbeat: {error}") from error

    def age(self, now: datetime | None = None) -> float:
        """How many seconds ago this heartbeat was written.

        :param now: the moment to measure from; the current time when ``None``.
        :returns: the age in seconds; negative when the heartbeat is from the future (clock skew).
        """
        now = datetime.now(UTC) if now is None else now
        return (now - datetime.fromisoformat(self.beat)).total_seconds()

    def is_fresh(self, now: datetime | None = None) -> bool:
        """Whether the node that wrote this is believed to be still running.

        :param now: the moment to judge at; the current time when ``None``.
        """
        return self.age(now) < STALE_AFTER_SECONDS


def read_heartbeat(folder: Path) -> NodeHeartbeat | None:
    """The heartbeat in ``folder``, or ``None`` when there is none or it cannot be read.

    :param folder: :func:`node_folder`.
    """
    try:
        return NodeHeartbeat.from_json((folder / HEARTBEAT_FILE_NAME).read_text(encoding="utf-8"))
    except OSError, ValueError:
        return None


def setup_logging(folder: Path) -> SharedRotatingFileHandler:
    """Send the node's records to its own rotating log file in ``folder``.

    :param folder: :func:`node_folder`, created if missing.
    :returns: the handler, so a caller can close it.
    """
    folder.mkdir(parents=True, exist_ok=True)
    handler = SharedRotatingFileHandler(folder / LOG_FILE_NAME)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, style="{"))
    handler.maxBytes = LOG_MAX_BYTES
    handler.backupCount = LOG_BACKUPS
    handler.rotates = True
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    return handler


def watch_stdin(stop: threading.Event, stream: BinaryIO | None = None) -> threading.Thread:
    """Set ``stop`` when stdin reaches EOF -- the host closed its end of the pipe, or went away.

    :param stop: the event to set.
    :param stream: the binary stream to read; the process's stdin when ``None``.
    :returns: the started daemon thread.
    """
    source: BinaryIO = sys.stdin.buffer if stream is None else stream

    def read_until_eof() -> None:
        """Block on the stream; EOF or a broken pipe both mean the host is gone."""
        try:
            while source.read(1):
                pass
        except OSError, ValueError:
            pass
        LOG.info("stdin closed: the host is gone, stopping")
        stop.set()

    thread = threading.Thread(target=read_until_eof, name="stdin-watch", daemon=True)
    thread.start()
    return thread


def install_signal_handlers(stop: threading.Event) -> None:
    """Make SIGINT and SIGTERM set ``stop`` instead of killing the process mid-write.

    :param stop: the event to set.
    """

    def on_signal(signum: int, _frame: object) -> None:
        """Ask the loop to stop.

        :param signum: which signal arrived.
        """
        LOG.info("signal %d: stopping", signum)
        stop.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, on_signal)


class LocalNode:
    """The node's main loop: write the heartbeat until told to stop, then take it away.

    :param folders: the app folders the agent and the node share.
    :param heartbeat_seconds: how often the heartbeat is rewritten.
    """

    def __init__(self, folders: AppFolders, heartbeat_seconds: float = HEARTBEAT_SECONDS) -> None:
        self.__folder: Final = node_folder(folders)
        self.__heartbeat_seconds: Final = heartbeat_seconds
        self.__started: Final = now_iso()
        self.__pid: Final = os.getpid()

    @property
    def folder(self) -> Path:
        """Where this node keeps its files."""
        return self.__folder

    def run(self, stop: threading.Event) -> None:
        """Write the heartbeat every :attr:`heartbeat_seconds` until ``stop`` is set, then remove it.

        :param stop: set by whoever wants the node to stop.
        """
        self.__folder.mkdir(parents=True, exist_ok=True)
        LOG.info("node %s started, pid %d, folder %s", __version__, self.__pid, self.__folder)
        try:
            self.__beat()
            while not stop.wait(self.__heartbeat_seconds):
                self.__beat()
        finally:
            self.__remove_heartbeat()
            LOG.info("node stopped")

    def __beat(self) -> None:
        """Rewrite the heartbeat; a failure is logged and the loop goes on, since the next beat may succeed."""
        heartbeat = NodeHeartbeat(pid=self.__pid, version=__version__, started=self.__started, beat=now_iso())
        try:
            atomic_write_text(self.__folder / HEARTBEAT_FILE_NAME, heartbeat.to_json())
        except OSError:
            LOG.warning("could not write the heartbeat", exc_info=True)

    def __remove_heartbeat(self) -> None:
        """Take the heartbeat away, so a reader sees a stopped node at once rather than after it goes stale."""
        try:
            (self.__folder / HEARTBEAT_FILE_NAME).unlink(missing_ok=True)
        except OSError:
            LOG.warning("could not remove the heartbeat", exc_info=True)
