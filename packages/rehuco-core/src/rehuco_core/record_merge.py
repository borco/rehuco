"""Read-merge-write: change one part of a record on disk without clobbering the rest (#410).

A record is written by more than one party: the agent's form saving metadata, the agent's player
recording progress, a node serving the web player and other users. A party holding a document loaded
minutes ago and writing it back whole would erase whatever the others wrote since. :func:`merge_write`
is the other way to write: re-read the file, apply one change to what is there now, write it back
atomically -- so a progress write never clobbers a metadata edit and the other way round
([[field-schema#watch-progress]]).

Record saves (#416, :class:`~rehuco_core.access.Records`) take the same per-file lock,
:func:`record_lock`, and add a :class:`~rehuco_core.RecordVersion` over the non-user part and a field-by-field
merge of the per-user maps (:func:`~rehuco_core.record_versions.merge_users`). The re-read and the write are
serialized **within this process** only, which is what keeps the agent's player, its form and a node hosted by it
from interleaving on one file; another process writing meanwhile is caught by the version check only when it
lands before the re-read.
"""

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Final

from .plugins import DEFAULT_PLUGIN_REGISTRY, PluginRegistry
from .rehu_document import RehuDocument

LOCKS_GUARD: Final = threading.Lock()
"""Guards :data:`LOCKS` itself, held only long enough to find or add one path's lock."""

LOCKS: Final[dict[Path, threading.Lock]] = {}
"""One lock per record this process has merge-written, by resolved path. Never pruned: an entry is a
path and a lock, and a session touches as many records as it opens."""


def merge_write(
    path: Path,
    mutate: Callable[[RehuDocument], None],
    *,
    username: str,
    plugins: PluginRegistry = DEFAULT_PLUGIN_REGISTRY,
    touch_updated: bool,
) -> RehuDocument:
    """Re-read ``path``, apply ``mutate`` to it, and write the result back atomically.

    Whatever ``mutate`` does not touch is written back as the file held it at the moment of the re-read,
    so two writers changing different parts both survive. Another process writing between the re-read and
    the write is not detected here -- that is #416's ``RecordVersion``.

    :param path: the record, which must exist: a merge has nothing to merge into otherwise.
    :param mutate: applies the one change, in place, to the freshly loaded document.
    :param username: the identity the document is loaded as -- whose per-user data its own-user
        accessors reach, and whose identity a block migration files under.
    :param plugins: the plugin registry to load with.
    :param touch_updated: whether a change stamps ``updated``; ``False`` for per-user writes, which
        describe one person rather than the resource ([[field-schema#record-timestamps]]).
    :returns: the document as written.
    :raises OSError: the file could not be read or written.
    :raises RehuFormatError: the file is not a readable record.
    :raises ValueError: the record is locked against saving (a newer format, an invalid field), or
        ``mutate`` refused the change.
    """
    with record_lock(path):
        document = RehuDocument.load(path, plugins=plugins, username=username)
        mutate(document)
        document.save(touch_updated=touch_updated)
        return document


def record_lock(path: Path) -> threading.Lock:
    """The lock serializing merge-writes of ``path`` in this process.

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
