"""Read-merge-write: change one part of a record on disk without clobbering the rest (#410).

A record is written by more than one party: the agent's form saving metadata, the agent's player
recording progress, a node serving the web player and other users. A party holding a document loaded
minutes ago and writing it back whole would erase whatever the others wrote since. :func:`merge_write`
is the other way to write: re-read the file, apply one change to what is there now, write it back
atomically -- so a progress write never clobbers a metadata edit and the other way round
([[field-schema#watch-progress]]).

Record saves (#416, :class:`~rehuco_core.access.Records`) take the same lock,
:func:`~rehuco_core.record_file_lock.locked_record`, and add a :class:`~rehuco_core.RecordVersion` over the non-user
part and a field-by-field merge of the per-user maps (:func:`~rehuco_core.record_versions.merge_users`). The re-read
and the write are serialized twice over (#512): within this process, which keeps the agent's player, its form and a
node hosted by it queued in memory, and across processes and machines by the record's lock file
(:class:`~rehuco_core.record_file_lock.RecordFileLock`).
"""

from collections.abc import Callable
from pathlib import Path

from .plugins import DEFAULT_PLUGIN_REGISTRY, PluginRegistry
from .record_file_lock import locked_record
from .rehu_document import RehuDocument


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
    so two writers changing different parts both survive. The re-read and the write are made under the record's
    lock (:func:`~rehuco_core.record_file_lock.locked_record`), so no writer that takes it lands in between, in this
    process or another.

    :param path: the record, which must exist: a merge has nothing to merge into otherwise.
    :param mutate: applies the one change, in place, to the freshly loaded document.
    :param username: the identity the document is loaded as -- whose per-user data its own-user
        accessors reach, and whose identity a block migration files under.
    :param plugins: the plugin registry to load with.
    :param touch_updated: whether a change stamps ``updated``; ``False`` for per-user writes, which
        describe one person rather than the resource ([[field-schema#record-timestamps]]).
    :returns: the document as written.
    :raises RecordLockedError: someone else held the record's lock for longer than a write waits.
    :raises OSError: the file could not be read or written.
    :raises RehuFormatError: the file is not a readable record.
    :raises ValueError: the record is locked against saving (a newer format, an invalid field), or
        ``mutate`` refused the change.
    """
    with locked_record(path, user=username):
        document = RehuDocument.load(path, plugins=plugins, username=username)
        mutate(document)
        document.save(touch_updated=touch_updated)
        return document
