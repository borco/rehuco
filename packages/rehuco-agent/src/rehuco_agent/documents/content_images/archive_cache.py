"""Open archive handles, kept and read through a lock each (#221).

`zipfile` is the project's only archive reader, and a `ZipFile` is neither cheap to open over a NAS
mount nor safe to read from two threads at once: it seeks one shared file object. This holds a bounded
LRU of open handles and serializes reads per handle, so the decode pool's workers share an archive
without reopening it per thumbnail and without racing on it.
"""

import threading
import zipfile
from collections import OrderedDict
from pathlib import Path
from typing import Final

from rehuco_core import ContentImageEntry

HANDLE_LIMIT: Final = 8
"""How many archives stay open at once. A directory-scoped resource's packs are browsed a few at a
time -- the rows in view span one or two -- and an evicted handle is one reopen away."""

HEADER_BYTES: Final = 64 * 1024
"""How much of a member :meth:`ArchiveCache.read_head` inflates for its header: every recognized
format states its dimensions within the first few hundred bytes, except a JPEG carrying a large EXIF
preview ahead of its frame header, for which 64 KiB is the usual ceiling. A header not found in this
much is read in full by the caller."""


class ArchiveCache:
    """A bounded LRU of open `zipfile.ZipFile` handles, each read under its own lock (#221).

    Every failure -- an offline mount, a truncated zip, a member gone from a re-packed archive -- is
    reported as ``None`` rather than raised: a browse over an unreachable pack paints placeholders and
    says nothing, the same document-level tolerance the enumeration itself has.

    :param limit: how many handles to keep open.
    """

    def __init__(self, limit: int = HANDLE_LIMIT) -> None:
        self.__limit: Final = limit
        self.__lock: Final = threading.Lock()
        self.__handles: Final[OrderedDict[Path, tuple[zipfile.ZipFile, threading.Lock]]] = OrderedDict()

    def read(self, entry: ContentImageEntry) -> bytes | None:
        """The member's whole bytes.

        :param entry: the member.
        :returns: its bytes, or ``None`` when the archive or the member cannot be read.
        """
        return self.__read(entry, None)

    def read_head(self, entry: ContentImageEntry, limit: int = HEADER_BYTES) -> bytes | None:
        """The member's leading ``limit`` bytes -- a partial inflate, enough for its header.

        :param entry: the member.
        :param limit: how many bytes to inflate.
        :returns: the bytes, or ``None`` when the archive or the member cannot be read.
        """
        return self.__read(entry, limit)

    def close(self) -> None:
        """Close every open handle."""
        with self.__lock:
            handles = list(self.__handles.values())
            self.__handles.clear()
        for archive, _ in handles:
            archive.close()

    def __read(self, entry: ContentImageEntry, limit: int | None) -> bytes | None:
        """Read ``limit`` bytes (or all) of ``entry`` through its archive's handle, under that handle's
        lock.

        :param entry: the member.
        :param limit: how many bytes, or ``None`` for all.
        :returns: the bytes, or ``None`` on any failure.
        """
        # twice at most: a handle looked up and then closed by an eviction before its lock was taken
        # is already out of the cache, so the second lookup opens the archive afresh. Not merely an
        # exception to swallow -- a read that fails is recorded as unreadable for good by its callers
        # (a header's size, a thumbnail), and an eviction race is no fact about the member
        for _ in range(2):
            opened = self.__handle(entry.archive)
            if opened is None:
                return None
            archive, lock = opened
            try:
                with lock:
                    if archive.fp is None:
                        continue
                    with archive.open(entry.name) as member:
                        return member.read() if limit is None else member.read(limit)
            except OSError, zipfile.BadZipFile, KeyError, RuntimeError, ValueError:
                # KeyError: the member is not in this archive any more; RuntimeError: encrypted;
                # ValueError: a member whose compression this zipfile cannot inflate
                return None
        return None

    def __handle(self, path: Path) -> tuple[zipfile.ZipFile, threading.Lock] | None:
        """The open handle for ``path``, opening it (and evicting the least recently used) if needed.

        :param path: the archive.
        :returns: the handle and its lock, or ``None`` when the archive cannot be opened.
        """
        with self.__lock:
            if path in self.__handles:
                self.__handles.move_to_end(path)
                return self.__handles[path]
        # opened outside the cache lock: a NAS open can take a while, and it need not stall a read
        # of another archive already open. Kept open on purpose -- the cache is what closes it.
        try:
            archive = zipfile.ZipFile(path)  # pylint: disable=consider-using-with
        except OSError, zipfile.BadZipFile:
            return None
        evicted: list[tuple[zipfile.ZipFile, threading.Lock]] = []
        with self.__lock:
            if path in self.__handles:
                # another thread opened it first: keep theirs, drop ours
                archive.close()
                self.__handles.move_to_end(path)
                return self.__handles[path]
            handle = (archive, threading.Lock())
            self.__handles[path] = handle
            while len(self.__handles) > self.__limit:
                evicted.append(self.__handles.popitem(last=False)[1])
        # closed under each handle's own lock, so a read in flight on it finishes first
        for old, old_lock in evicted:
            with old_lock:
                old.close()
        return handle
