"""What a record's save is checked and merged against: its version, its per-user fields, its metadata (#416).

A record has two kinds of content ([[nodes#access-seam]]): its **metadata** -- everything but the plugin blocks'
``users`` maps -- which describes the resource and has one editor at a time, and its **per-user fields**, which many
writers touch at once (a form's rating, a player's progress, a node serving other users). So a save is checked on the
metadata alone, and the per-user fields are merged one by one:

- :class:`RecordVersion` -- what a record was when it was read: a hash of its metadata, of its text, and of each
  per-user field. Opaque to its holders, who only hand it back.
- :func:`merge_users` -- a three-way merge of the ``users`` maps, field by field, against that version.
- :func:`metadata_differences` and :func:`put_paths` -- what two readings of the metadata disagree on, and the
  values a person keeps, for a conflict they resolve.

Pure functions of parsed payloads: nothing here reads a file.
"""

import copy
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final

import xxhash

from .plugins import PUBLIC_USERNAME, USERS_KEY
from .rehu_format import CORE_BLOCK_KEY, FORMAT_VERSION_KEY

type FieldPath = tuple[str | int, ...]
"""Where a metadata value sits: the keys and list indexes leading to it from the top of the payload."""

type UserFieldHash = tuple[str, str, str, str]
"""One per-user field as read: its block, scope, key, and the hash of its value."""


class Absent(Enum):
    """The value of a field one side does not have."""

    ABSENT = "absent"


ABSENT: Final = Absent.ABSENT
"""A field one reading of the metadata does not have (:class:`MetadataDifference`)."""

STAMPED_PATHS: Final = frozenset({(CORE_BLOCK_KEY, "updated")})
"""Metadata a save stamps itself, so a person resolving a conflict has nothing to choose there
([[field-schema#record-timestamps]])."""


@dataclass(frozen=True, slots=True)
class RecordVersion:
    """What a record was when it was read, for a save to be checked and merged against ([[nodes#access-seam]]).

    Opaque: a holder keeps the one it was given and hands it back with its save.

    :param metadata_hash: the hash of the record without its per-user fields; a save is refused when the record's
        has moved on, since that is someone else's metadata edit.
    :param file_hash: the hash of the file's text; while it is unchanged nothing needs merging.
    :param user_fields: every per-user field as read, sorted; what tells a field this holder changed from one it
        merely still holds.
    """

    metadata_hash: str
    file_hash: str
    user_fields: tuple[UserFieldHash, ...]


@dataclass(frozen=True, slots=True)
class MetadataDifference:
    """One metadata value two readings of a record disagree on.

    :param path: where it sits.
    :param base: its value when the record was opened, or :data:`ABSENT`.
    :param mine: its value in the edited document, or :data:`ABSENT`.
    :param theirs: its value on disk now, or :data:`ABSENT`.
    """

    path: FieldPath
    base: Any
    mine: Any
    theirs: Any

    @property
    def mine_changed(self) -> bool:
        """Whether the edited document changed it since the record was opened."""
        return self.mine != self.base

    @property
    def theirs_changed(self) -> bool:
        """Whether the file changed it since the record was opened."""
        return self.theirs != self.base


def record_version(data: dict[str, Any], text: str) -> RecordVersion:
    """The version of a record as read.

    :param data: the record's payload, as loaded -- after migration, so two readings by one build compare alike.
    :param text: the file's text.
    :returns: its version.
    """
    return RecordVersion(metadata_hash(data), xxhash.xxh3_128_hexdigest(text.encode("utf-8")), user_field_hashes(data))


def metadata_of(data: dict[str, Any]) -> dict[str, Any]:
    """A deep copy of a payload without its per-user fields: every block's ``users`` map left out.

    A block holding nothing but its own version stamp is left out too, whether or not it has a ``users`` map: the
    first rating or progress entry on a record creates its block, and a type switch writes one empty, so the same
    block reads alike before and after its first per-user field. It says nothing about the resource -- its type is
    ``core.type``'s.

    :param data: the record's payload.
    :returns: its metadata.
    """
    metadata: dict[str, Any] = {}
    for key, value in data.items():
        if not isinstance(value, dict):
            metadata[key] = copy.deepcopy(value)
            continue
        rest = {name: copy.deepcopy(item) for name, item in value.items() if name != USERS_KEY}
        if rest.keys() - {FORMAT_VERSION_KEY}:
            metadata[key] = rest
    return metadata


def metadata_text(data: dict[str, Any]) -> str:
    """The metadata of a payload as one canonical text, for comparing and hashing.

    :param data: the record's payload.
    :returns: its metadata as key-sorted JSON.
    """
    return canonical_json(metadata_of(data))


def metadata_hash(data: dict[str, Any]) -> str:
    """The hash of a payload's metadata.

    :param data: the record's payload.
    :returns: the hash, as hex.
    """
    return xxhash.xxh3_128_hexdigest(metadata_text(data).encode("utf-8"))


def canonical_json(value: Any) -> str:
    """A JSON value as one text whatever order its keys were built in.

    :param value: the value.
    :returns: key-sorted, compact JSON.
    """
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def value_hash(value: Any) -> str:
    """The hash of one JSON value.

    :param value: the value.
    :returns: the hash, as hex.
    """
    return xxhash.xxh3_128_hexdigest(canonical_json(value).encode("utf-8"))


def user_field_hashes(data: dict[str, Any]) -> tuple[UserFieldHash, ...]:
    """Every per-user field of a payload, hashed.

    A scope whose map is malformed (not an object) counts as one field under the empty key, so a change to it is
    still a change.

    :param data: the record's payload.
    :returns: ``(block, scope, key, hash)`` for each, sorted.
    """
    found: list[UserFieldHash] = []
    for block, users in users_maps(data).items():
        for scope, fields in users.items():
            if isinstance(fields, dict):
                found.extend((block, scope, key, value_hash(value)) for key, value in fields.items())
            else:
                found.append((block, scope, "", value_hash(fields)))
    return tuple(sorted(found))


def users_maps(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The ``users`` map of every block of a payload that has a well-formed one.

    :param data: the record's payload.
    :returns: each block's map, by block key.
    """
    return {
        key: value[USERS_KEY]
        for key, value in data.items()
        if isinstance(value, dict) and isinstance(value.get(USERS_KEY), dict)
    }


def merge_users(mine: dict[str, Any], theirs: dict[str, Any], base: RecordVersion, username: str) -> bool:
    """Merge the file's per-user fields into an edited payload, field by field, in place ([[nodes#access-seam]]).

    Every block ``mine`` holds gets the ``users`` map the file has now, except for the fields ``mine`` changed since
    ``base`` was read -- set, changed or removed -- and only in the scopes its writer may change: ``username``'s own
    and the reserved ``public`` one a publish writes to. Another user's fields, and ``unknown``'s, are the file's.
    So a progress entry written while a rating was being edited survives the rating's save, and the other way round.

    A block only the file has -- made by the first per-user field written there since ``mine`` was read, which holds
    nothing else (:func:`metadata_of`) -- is added to ``mine`` with its version stamp, so those fields survive too.

    :param mine: the edited payload, merged into.
    :param theirs: the payload on disk now.
    :param base: the version ``mine`` was read at.
    :param username: whose fields the save carries.
    :returns: whether ``mine``'s per-user fields changed -- a value the file had that the editor did not.
    """
    read: Final = {(block, scope, key): digest for block, scope, key, digest in base.user_fields}
    writable: Final = frozenset({username, PUBLIC_USERNAME})
    theirs_maps = users_maps(theirs)
    changed = False
    for block, value in mine.items():
        if not isinstance(value, dict):
            continue
        own = value.get(USERS_KEY)
        own_map: dict[str, Any] = own if isinstance(own, dict) else {}
        merged = merge_block(own_map, theirs_maps.get(block, {}), read, block, writable)
        if merged != own_map:
            value[USERS_KEY] = merged
            changed = True
    return add_file_only_blocks(mine, theirs, read, writable) or changed


def add_file_only_blocks(
    mine: dict[str, Any], theirs: dict[str, Any], read: dict[tuple[str, str, str], str], writable: frozenset[str]
) -> bool:
    """Add to ``mine`` every block only the file has, holding its merged per-user fields and its version stamp.

    :param mine: the edited payload, added to.
    :param theirs: the payload on disk now.
    :param read: each per-user field's hash as read, by block, scope and key.
    :param writable: the scopes the writer may change.
    :returns: whether a block was added.
    """
    added_any = False
    for block, their_map in users_maps(theirs).items():
        if block in mine:
            continue
        merged = merge_block({}, their_map, read, block, writable)
        if merged:
            added: dict[str, Any] = {USERS_KEY: merged}
            stamp = theirs[block].get(FORMAT_VERSION_KEY)
            if stamp is not None:
                added[FORMAT_VERSION_KEY] = stamp
            mine[block] = added
            added_any = True
    return added_any


def merge_block(
    mine: dict[str, Any],
    theirs: dict[str, Any],
    read: dict[tuple[str, str, str], str],
    block: str,
    writable: frozenset[str],
) -> dict[str, Any]:
    """Merge one block's ``users`` maps, scope by scope: a scope the writer may not change is the file's.

    :param mine: the block's map in the edited payload.
    :param theirs: its map on disk now.
    :param read: each per-user field's hash as read, by block, scope and key.
    :param block: the block.
    :param writable: the scopes the writer may change.
    :returns: the merged map.
    """
    merged: dict[str, Any] = {}
    for scope in sorted(mine.keys() | theirs.keys()):
        if scope not in writable:
            kept = theirs.get(scope, ABSENT)
        else:
            kept = merge_scope(mine.get(scope, ABSENT), theirs.get(scope, ABSENT), read, block, scope)
        if kept is not ABSENT:
            merged[scope] = kept
    return merged


def merge_scope(mine: Any, theirs: Any, read: dict[tuple[str, str, str], str], block: str, scope: str) -> Any:
    """Merge one scope's fields: the ones changed since they were read from ``mine``, the rest from ``theirs``.

    :param mine: the scope's map in the edited payload, or :data:`ABSENT`.
    :param theirs: its map on disk now, or :data:`ABSENT`.
    :param read: each per-user field's hash as read, by block, scope and key.
    :param block: the block the scope is in.
    :param scope: the scope.
    :returns: the merged map, or :data:`ABSENT` when it is left with nothing.
    """
    if mine is not ABSENT and not isinstance(mine, dict):
        # a malformed map is one field under the empty key (user_field_hashes)
        return mine if value_hash(mine) != read.get((block, scope, "")) else theirs
    mine = mine if isinstance(mine, dict) else {}
    theirs = theirs if isinstance(theirs, dict) else {}
    merged: dict[str, Any] = {}
    for key in sorted(mine.keys() | theirs.keys()):
        own = mine.get(key, ABSENT)
        own_hash = None if own is ABSENT else value_hash(own)
        kept = own if own_hash != read.get((block, scope, key)) else theirs.get(key, ABSENT)
        if kept is not ABSENT:
            merged[key] = kept
    return merged if merged else ABSENT


def metadata_differences(
    base: dict[str, Any], mine: dict[str, Any], theirs: dict[str, Any]
) -> list[MetadataDifference]:
    """Every metadata value an edited document and the file on disk disagree on, with its value when opened.

    Objects are compared key by key, and a list item by item while both sides hold as many -- so a source's title and
    its publisher are two rows, not one ``sources`` list. A list whose length differs is one value, compared whole:
    which item is which is then anyone's guess. Per-user fields are not metadata and never appear, nor does what a
    save stamps (:data:`STAMPED_PATHS`).

    :param base: the metadata when the record was opened (:func:`metadata_of`).
    :param mine: the edited payload.
    :param theirs: the payload on disk now.
    :returns: the differences, in document order.
    """
    found: list[MetadataDifference] = []
    collect_differences(metadata_of(base), metadata_of(mine), metadata_of(theirs), (), found)
    return found


def collect_differences(base: Any, mine: Any, theirs: Any, path: FieldPath, found: list[MetadataDifference]) -> None:
    """Add where ``mine`` and ``theirs`` disagree, at or below ``path``, to ``found``.

    :param base: the value when opened, or :data:`ABSENT`.
    :param mine: the edited value, or :data:`ABSENT`.
    :param theirs: the value on disk now, or :data:`ABSENT`.
    :param path: where the three sit.
    :param found: the differences so far, appended to.
    """
    if path in STAMPED_PATHS or mine == theirs:
        return
    if isinstance(mine, dict) and isinstance(theirs, dict):
        known = base if isinstance(base, dict) else {}
        for key in [*mine, *(key for key in theirs if key not in mine)]:
            collect_differences(
                known.get(key, ABSENT), mine.get(key, ABSENT), theirs.get(key, ABSENT), (*path, key), found
            )
    elif isinstance(mine, list) and isinstance(theirs, list) and len(mine) == len(theirs):
        known = base if isinstance(base, list) else []
        for index, (own, their) in enumerate(zip(mine, theirs, strict=True)):
            collect_differences(known[index] if index < len(known) else ABSENT, own, their, (*path, index), found)
    else:
        found.append(MetadataDifference(path, base, mine, theirs))


def put_paths(data: dict[str, Any], values: Mapping[FieldPath, Any]) -> None:
    """Set each path to its value in ``data``, in place -- removed where the value is :data:`ABSENT`.

    How a person's choices in a conflict become one payload: start from the edited one and put the value kept for
    each detail -- the file's, or one typed in. A path whose container ``data`` lacks is created as an object; a list
    item ``data`` lacks is skipped -- :func:`metadata_differences` names one only where both sides hold it.

    :param data: the payload changed.
    :param values: the value of each path (:func:`metadata_differences`).
    """
    for path, value in values.items():
        container: Any = data
        for key in path[:-1]:
            child = path_value(container, (key,))
            if not isinstance(child, (dict, list)):
                if value is ABSENT or not isinstance(container, dict):
                    break
                child = {}
                container[key] = child
            container = child
        else:
            put_value(container, path[-1], value)


def put_value(container: Any, key: str | int, value: Any) -> None:
    """Set or remove one entry of an object or a list.

    :param container: the object or list.
    :param key: the entry's key or index.
    :param value: the new value, or :data:`ABSENT` to remove it from an object.
    """
    if isinstance(container, dict) and isinstance(key, str):
        if value is ABSENT:
            container.pop(key, None)
        else:
            container[key] = copy.deepcopy(value)
    elif isinstance(container, list) and isinstance(key, int) and 0 <= key < len(container) and value is not ABSENT:
        container[key] = copy.deepcopy(value)


def path_value(data: Any, path: FieldPath) -> Any:
    """The value at a path, or :data:`ABSENT`.

    :param data: the payload, or a value inside it.
    :param path: the keys and list indexes leading to it.
    :returns: the value.
    """
    value: Any = data
    for key in path:
        if isinstance(value, dict) and isinstance(key, str) and key in value:
            value = value[key]
        elif isinstance(value, list) and isinstance(key, int) and 0 <= key < len(value):
            value = value[key]
        else:
            return ABSENT
    return value
