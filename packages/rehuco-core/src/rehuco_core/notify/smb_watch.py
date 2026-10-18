"""The file notifier's backend for a folder on an SMB share: ``CHANGE_NOTIFY`` on a session of our own (#502, #511,
[[mounts-and-storage#out-of-band]]).

**Why a session of our own, and not the OS client's watcher on the mount.** The server answers ``CHANGE_NOTIFY`` from
its own watches (Samba: inotify), so it reports every writer on every client. On Windows the OS client forwards
ReadDirectoryChangesW to the server too, but #502 saw it lose events under load with no overflow signal; on macOS
FSEvents over SMB is blind. A session opened here sees the same server events, says when its buffer overflowed (an
empty answer), and carries notifications only: the data still flows through the mount.

**Windows only, for now.** The session authenticates with the logged-on user's credentials (SSPI) and needs no
password. macOS and Linux would need stored credentials, whose UI is not designed yet, so their shares are polled.
"""

import logging
import os
import sys
import threading
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, Final

from smbprotocol.change_notify import ChangeNotifyFlags, CompletionFilter, FileAction, FileSystemWatcher
from smbprotocol.connection import Connection
from smbprotocol.file_info import FileAttributes
from smbprotocol.open import (
    CreateDisposition,
    CreateOptions,
    DirectoryAccessMask,
    ImpersonationLevel,
    Open,
    ShareAccess,
)
from smbprotocol.session import Session
from smbprotocol.tree import TreeConnect

from .raw_change import RawChange, RawChangeKind

LOG: Final = logging.getLogger(__name__)

SMB_PORT: Final = 445

CONNECT_TIMEOUT: Final = 10
"""Seconds to wait for the server to accept the session. Only ever spent on a daemon thread."""

WAIT_SECONDS: Final = 0.5
"""How often a watch waiting for the server looks up to see whether it was stopped."""

OUTPUT_BUFFER_LENGTH: Final = 65536
"""The most a server may answer one request with; past it, the answer is empty and means *rescan*."""

COMPLETION_FILTER: Final = (
    CompletionFilter.FILE_NOTIFY_CHANGE_FILE_NAME
    | CompletionFilter.FILE_NOTIFY_CHANGE_DIR_NAME
    | CompletionFilter.FILE_NOTIFY_CHANGE_SIZE
    | CompletionFilter.FILE_NOTIFY_CHANGE_LAST_WRITE
)
"""Names, sizes and writes: what changes a record's signature or a folder's listing."""

KINDS: Final = {
    FileAction.FILE_ACTION_ADDED: RawChangeKind.CREATED,
    FileAction.FILE_ACTION_REMOVED: RawChangeKind.DELETED,
    FileAction.FILE_ACTION_MODIFIED: RawChangeKind.MODIFIED,
}
"""The actions reported as they are; a rename's two halves are paired instead."""


@dataclass(frozen=True, slots=True)
class SmbLocation:
    """Where a folder is, as the server knows it.

    :param server: the host serving the share.
    :param share: the share's name.
    :param relative: the folder's path inside the share, ``\\``-separated; empty for the share itself.
    """

    server: str
    share: str
    relative: str

    @classmethod
    def of(cls, folder: Path) -> SmbLocation | None:
        """Where ``folder`` is on its server, when it is on an SMB share -- by a UNC path, or a drive letter mapped to
        one -- and this is Windows, where the logon serves as credentials.

        Never touches the network: a mapped letter's share comes from the connection table.

        :param folder: the folder.
        :returns: its location; ``None`` when it is not on a share this backend can reach.
        """
        if sys.platform != "win32":
            return None
        windows = PureWindowsPath(folder)
        share_root: str | None = windows.drive
        if not windows.drive.startswith("\\\\"):
            # pylint: disable-next=import-outside-toplevel
            from borco_core.platforms.windows import drives

            share_root = drives.mapped_share(windows.drive)
        if share_root is None:
            return None
        server, _, share = share_root.strip("\\").partition("\\")
        if not server or not share:
            return None
        return cls(server, share, "\\".join(windows.parts[1:]))


class SmbWatch:
    """Watches one folder on an SMB share, everything beneath it included.

    :param folder: the folder as this machine reaches it -- a mapped drive's path or a UNC one; what is reported is
        spelled beneath it.
    :param location: where it is on its server.
    :param sink: told of each change, on the watch's thread.
    """

    def __init__(self, folder: Path, location: SmbLocation, sink: Callable[[RawChange], None]) -> None:
        self.__folder: Final = folder
        self.__location: Final = location
        self.__sink: Final = sink
        self.__stopped: Final = threading.Event()
        self.__connection: Connection | None = None
        self.__failed = False
        self.__renamed_from: Path | None = None
        """A rename's old half still waiting for its new one: the server may end an answer between the two."""

    @classmethod
    def located(cls, folder: Path, sink: Callable[[RawChange], None]) -> SmbWatch | None:
        """A watch of ``folder``, when it is on an SMB share this backend can reach (:meth:`SmbLocation.of`).

        :param folder: the folder.
        :param sink: told of each change.
        :returns: the watch, not started; ``None`` when the folder is not on such a share.
        """
        location = SmbLocation.of(folder)
        return cls(folder, location, sink) if location is not None else None

    def start(self) -> None:
        """Open the session, the share and the folder, and begin watching.

        :raises OSError: when the server cannot be reached, refuses the credentials, or has no such folder.
        """
        location = self.__location
        try:
            connection = Connection(uuid.uuid4(), location.server, SMB_PORT)
            connection.connect(timeout=CONNECT_TIMEOUT)
            self.__connection = connection
            # signed, not sealed: the session carries file names only, which the mount carries in the clear already
            session = Session(connection, require_encryption=False)
            session.connect()
            tree = TreeConnect(session, rf"\\{location.server}\{location.share}")
            tree.connect()
            directory = Open(tree, location.relative)
            directory.create(
                ImpersonationLevel.Impersonation,
                DirectoryAccessMask.FILE_LIST_DIRECTORY,
                FileAttributes.FILE_ATTRIBUTE_DIRECTORY,
                ShareAccess.FILE_SHARE_READ | ShareAccess.FILE_SHARE_WRITE | ShareAccess.FILE_SHARE_DELETE,
                CreateDisposition.FILE_OPEN,
                CreateOptions.FILE_DIRECTORY_FILE,
            )
        except Exception as error:  # smbprotocol raises its own errors, and socket's
            self.__disconnect()
            raise OSError(f"Could not watch {self.__folder} over SMB: {error}") from error
        threading.Thread(target=self.__run, args=(directory,), name=f"smb-watch {self.__folder}", daemon=True).start()

    def stop(self) -> None:
        """Stop watching. The session is closed on a daemon thread: a server that went away would make it wait."""
        self.__stopped.set()
        threading.Thread(target=self.__disconnect, name="smb-watch-close", daemon=True).start()

    @property
    def failed(self) -> bool:
        """Whether the session ended without being told to: the server went away or dropped it."""
        return self.__failed and not self.__stopped.is_set()

    def __run(self, directory: Open) -> None:
        """Ask the server for changes, one request after another, until stopped or the session fails.

        :param directory: the open folder.
        """
        while not self.__stopped.is_set():
            watcher = FileSystemWatcher(directory)
            try:
                watcher.start(
                    COMPLETION_FILTER,
                    flags=ChangeNotifyFlags.SMB2_WATCH_TREE,
                    output_buffer_length=OUTPUT_BUFFER_LENGTH,
                )
                while not watcher.response_event.wait(WAIT_SECONDS):
                    if self.__stopped.is_set():
                        return
                actions = watcher.result
            # whatever ends the session ends the watch
            except Exception as error:  # pylint: disable=broad-exception-caught
                if not self.__stopped.is_set():
                    LOG.warning("The SMB watch of %s ended: %s", self.__folder, error)
                    self.__failed = True
                return
            if self.__stopped.is_set():
                return
            if actions is None:  # cancelled under us: the session is going
                self.__failed = True
                return
            self.__report(actions)

    def __report(self, actions: Sequence[Any]) -> None:
        """Hand one answer's actions to the sink, a rename's two halves as one move -- the halves may come in two
        answers -- and a folder that appeared with everything in it.

        :param actions: the server's ``FILE_NOTIFY_INFORMATION`` entries; none means the buffer overflowed.
        """
        if not actions:
            self.__sink(RawChange(RawChangeKind.OVERFLOW, self.__folder))
            return
        for action in actions:
            code = action["action"].get_value()
            path = self.__folder.joinpath(*action["file_name"].get_value().split("\\"))
            pending, self.__renamed_from = self.__renamed_from, None
            if code == FileAction.FILE_ACTION_RENAMED_NEW_NAME:
                directory = os.path.isdir(path)
                if pending is not None:
                    self.__sink(RawChange(RawChangeKind.MOVED, pending, path, directory))
                else:  # the old half went missing: the new name appeared, as far as anyone can tell
                    self.__appeared(path, directory)
                continue
            if pending is not None:  # no new half followed: renamed out of the watched folder, as good as gone
                self.__sink(RawChange(RawChangeKind.DELETED, pending))
            if code == FileAction.FILE_ACTION_RENAMED_OLD_NAME:
                self.__renamed_from = path
            elif (kind := KINDS.get(code)) is RawChangeKind.CREATED:
                self.__appeared(path, os.path.isdir(path))
            elif kind is not None:
                # a folder's own write time changes with every entry in it: only a file's write is news
                directory = kind is not RawChangeKind.DELETED and os.path.isdir(path)
                self.__sink(RawChange(kind, path, None, directory))

    def __appeared(self, path: Path, directory: bool) -> None:
        """Report an entry that appeared -- and, for a folder, everything in it, walked through the mount.

        The server reports a folder moved in from elsewhere as that one folder; the records in it are news too, and a
        local watch reports them the same way (watchdog walks a new folder for its contents).

        :param path: the entry.
        :param directory: whether it is a folder.
        """
        self.__sink(RawChange(RawChangeKind.CREATED, path, None, directory))
        if not directory:
            return
        for folder, folders, files in os.walk(path):
            if self.__stopped.is_set():
                return
            for name in folders:
                self.__sink(RawChange(RawChangeKind.CREATED, Path(folder, name), None, True))
            for name in files:
                self.__sink(RawChange(RawChangeKind.CREATED, Path(folder, name)))

    def __disconnect(self) -> None:
        """Close the session, if one was opened; whatever the server answers -- or does not -- is ignored."""
        connection, self.__connection = self.__connection, None
        if connection is None:
            return
        try:
            connection.disconnect(close=True)
        except Exception as error:  # pylint: disable=broad-exception-caught  # closing what may already be gone
            LOG.debug("Closing the SMB session to %s: %s", self.__location.server, error)
