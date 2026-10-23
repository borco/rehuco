"""Per-user sidecars: one user's state for one record, in a file of its own beside it ([[data-model#single-file]]).

``<stem>.user-<name>.rehuser`` holds what the plugin blocks' ``users`` maps hold for one scope -- ratings, flags,
learning paths, watch progress -- so a write every few seconds of one person's progress never rewrites the record
everyone edits. Its first version is a JSON object of ``block key -> that user's fields`` beside its ``format_version``.

The split is a storage concern only: in memory a record still carries its ``users`` maps, so the version, the
field-by-field merge and the conflict rows (:mod:`rehuco_core.record_versions`) work on one payload. Reading joins the
sidecars into it (:func:`read_user_sidecars`, :func:`join_user_sidecars`); writing splits them out again
(:func:`split_user_sidecars`, :func:`write_user_sidecars`) -- and a record that still carries maps from before the
sidecars existed loses them to the sidecars on its next save, the one-time move the spec names. Both happen under the
record's own lock (:func:`~rehuco_core.record_file_lock.locked_record`), which guards its sidecars too.
"""

import json
import logging
import os
import re
import unicodedata
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from borco_core import atomic_write_text

from .constants import USER_SIDECAR_SUFFIX
from .migrations import CURRENT_REHUSER_VERSION, migrate_rehuser_data
from .plugins import USERS_KEY
from .rehu_format import FORMAT_VERSION_KEY
from .rehu_parse_limits import excessive_entry_reason, excessive_nesting_reason, oversized_file_reason

LOG: Final = logging.getLogger(__name__)

USER_INFIX: Final = ".user-"
"""What separates a sidecar's record stem from its user's name: ``info.user-ioan.rehuser``."""

UNSAFE_SLUG_RUN: Final = re.compile(r"[^a-z0-9._-]+")
"""A run of characters a sidecar's user name never holds."""

SLUG_TRIMMED: Final = "._-"
"""What a user name in a sidecar's file name never starts or ends with."""


class UserSidecarError(ValueError):
    """A sidecar that cannot be read, or one written by a newer build, which this one must not write over."""


@dataclass(frozen=True, slots=True)
class UserSidecar:
    """One per-user sidecar, as read.

    :param name: its file name.
    :param slug: whose it is: the user name its file name carries (:func:`user_slug`).
    :param fields: its ``block key -> that user's fields``, migrated, its version stamp left out.
    :param text: the file's text.
    """

    name: str
    slug: str
    fields: dict[str, Any]
    text: str


@dataclass(frozen=True, slots=True)
class UnreadableSidecar:
    """One per-user sidecar that could not be read, left out of its record's ``users`` maps and never written over.

    :param name: its file name.
    :param slug: whose it is: the user name its file name carries (:func:`user_slug`).
    :param reason: why it could not be read, starting with its file name.
    """

    name: str
    slug: str
    reason: str


def user_slug(username: str) -> str:
    """The name a user's sidecar is filed under: lower-cased ASCII, safe in a file name. Windows and macOS compare names
    without case, so the fold is not optional: ``Ioan`` and ``ioan`` share one sidecar.

    :param username: a scope of a ``users`` map -- a username, ``public`` or ``unknown``.
    :returns: the slug.
    :raises ValueError: nothing of ``username`` survives the fold.
    """
    folded = unicodedata.normalize("NFKD", username).encode("ascii", "ignore").decode("ascii").lower()
    slug = UNSAFE_SLUG_RUN.sub("_", folded).strip(SLUG_TRIMMED)
    if not slug:
        raise ValueError(f"{username!r} leaves nothing to name a sidecar by")
    return slug


def user_sidecar_path(record: Path, username: str) -> Path:
    """Where a user's sidecar for a record sits.

    :param record: the ``.rehu``.
    :param username: the user, or another scope of a ``users`` map.
    :returns: ``<stem>.user-<slug>.rehuser`` beside the record.
    :raises ValueError: ``username`` has no slug (:func:`user_slug`).
    """
    return record.with_name(f"{record.stem}{USER_INFIX}{user_slug(username)}{USER_SIDECAR_SUFFIX}")


def user_sidecar_owner(filename: str) -> tuple[str, str] | None:
    """Whose sidecar a file is, by its name alone.

    :param filename: a file name.
    :returns: the record stem it belongs to and the user's slug, or ``None`` when it is no sidecar.
    """
    if not filename.lower().endswith(USER_SIDECAR_SUFFIX):
        return None
    base = filename[: -len(USER_SIDECAR_SUFFIX)]
    index = base.lower().rfind(USER_INFIX)
    if index <= 0 or index + len(USER_INFIX) == len(base):
        return None
    return base[:index], base[index + len(USER_INFIX) :]


def is_user_sidecar_name(filename: str) -> bool:
    """Whether a file is a per-user sidecar -- what scans, checksums and listings never take for content.

    :param filename: a file name.
    :returns: whether it is named as one.
    """
    return user_sidecar_owner(filename) is not None


def user_sidecar_paths(record: Path) -> dict[str, Path]:
    """The sidecars beside a record, as named on disk.

    :param record: the ``.rehu``.
    :returns: each sidecar's path, by its slug lower-cased; empty when the record's folder is gone.
    :raises OSError: the folder could not be listed.
    """
    stem = record.stem.casefold()
    try:
        names = sorted(os.listdir(record.parent))
    except FileNotFoundError:
        return {}
    found: dict[str, Path] = {}
    for name in names:
        owner = user_sidecar_owner(name)
        if owner is not None and owner[0].casefold() == stem:
            found[owner[1].lower()] = record.parent / name
    return found


def read_user_sidecars(record: Path) -> tuple[list[UserSidecar], list[UnreadableSidecar]]:
    """Read every sidecar beside a record. One that cannot be read costs its own scope and nothing else
    ([[data-model#single-file]]).

    :param record: the ``.rehu``.
    :returns: the sidecars read, by name, and the ones that could not be -- unparseable, past a sanity cap, written by
        a newer build, or unreadable; one gone between the listing and its read is in neither.
    :raises OSError: the folder could not be listed.
    """
    read: list[UserSidecar] = []
    unreadable: list[UnreadableSidecar] = []
    for slug, path in user_sidecar_paths(record).items():
        try:
            read.append(read_user_sidecar(path, slug))
        except FileNotFoundError:
            continue
        except UserSidecarError as error:
            unreadable.append(UnreadableSidecar(path.name, slug, str(error)))
        except OSError as error:
            unreadable.append(UnreadableSidecar(path.name, slug, f"{path.name}: could not be read — {error}."))
    return read, unreadable


def read_user_sidecar(path: Path, slug: str) -> UserSidecar:
    """Read one sidecar, held to the same sanity caps as a record ([[data-model#write-integrity]]).

    :param path: the sidecar.
    :param slug: whose it is.
    :returns: the sidecar.
    :raises UserSidecarError: it could not be parsed, trips a sanity cap, or was written by a newer build.
    :raises OSError: it could not be read.
    """
    oversized = oversized_file_reason(path.stat().st_size)
    if oversized is not None:
        raise UserSidecarError(f"{path.name}: refusing to parse — {oversized}")
    text = path.read_text(encoding="utf-8")
    nested_too_deep = excessive_nesting_reason(text)
    if nested_too_deep is not None:
        raise UserSidecarError(f"{path.name}: refusing to parse — {nested_too_deep}")
    try:
        data: object = json.loads(text)
    except (ValueError, RecursionError) as error:
        raise UserSidecarError(f"{path.name}: invalid JSON — {error}.") from error
    if not isinstance(data, dict):
        raise UserSidecarError(f"{path.name}: expected a JSON object at the top level.")
    oversized_entry = excessive_entry_reason(data)
    if oversized_entry is not None:
        raise UserSidecarError(f"{path.name}: refusing to parse — {oversized_entry}")
    migrate_rehuser_data(data)
    version = data.pop(FORMAT_VERSION_KEY)
    if version > CURRENT_REHUSER_VERSION:
        raise UserSidecarError(
            f"{path.name}: format_version {version} is newer than this build understands ({CURRENT_REHUSER_VERSION})."
        )
    return UserSidecar(path.name, slug, data, text)


def join_user_sidecars(
    data: dict[str, Any],
    sidecars: list[UserSidecar],
    username: str,
    unreadable: Collection[UnreadableSidecar] = (),
) -> None:
    """Put each sidecar's fields into the record's ``users`` maps, in place.

    The current user's sidecar fills ``username``'s scope; every other one the scope its slug spells, which is what
    ``public`` and ``unknown`` are. A sidecar replaces a scope the record still carries itself: the record's is the
    state from before the sidecar, which its next save moves out. The scope of one that could not be read is left out
    altogether, the record's own copy of it included, so nothing of it is written back over that file.

    :param data: the record's payload.
    :param sidecars: its sidecars (:func:`read_user_sidecars`).
    :param username: the identity the record is opened as.
    :param unreadable: the sidecars that could not be read.
    """
    own = slug_or_none(username)
    left_out = {sidecar.slug for sidecar in unreadable}
    if left_out:
        for block in data.values():
            users = block.get(USERS_KEY) if isinstance(block, dict) else None
            if isinstance(users, dict):
                for scope in [scope for scope in users if slug_or_none(scope) in left_out]:
                    del users[scope]
    for sidecar in sidecars:
        scope = username if sidecar.slug == own else sidecar.slug
        for key, fields in sidecar.fields.items():
            block = data.setdefault(key, {})
            if not isinstance(block, dict):
                continue
            users = block.setdefault(USERS_KEY, {})
            if isinstance(users, dict):
                users[scope] = fields


def split_user_sidecars(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Split a record's payload into what its file holds and what each user's sidecar holds.

    A scope with no slug (:func:`user_slug`) and a ``users`` map that is not an object stay in the record, which then
    holds the only copy of them. A scope holding nothing goes nowhere: a user with no state gets no sidecar. Two scopes
    folding to one slug share one sidecar, the later name's field winning.

    :param payload: the record as a save writes it, its ``users`` maps in.
    :returns: the record without them, and each sidecar's ``block key -> fields``, by slug.
    """
    record: dict[str, Any] = {}
    sidecars: dict[str, dict[str, Any]] = {}
    for key, value in payload.items():
        if not isinstance(value, dict) or not isinstance(value.get(USERS_KEY), dict):
            record[key] = value
            continue
        kept: dict[str, Any] = {}
        for scope, fields in sorted(value[USERS_KEY].items()):
            if fields == {}:
                continue
            slug = slug_or_none(scope)
            if slug is None:
                kept[scope] = fields
                continue
            sidecar = sidecars.setdefault(slug, {})
            earlier = sidecar.get(key)
            if isinstance(earlier, dict) and isinstance(fields, dict):
                sidecar[key] = {**earlier, **fields}
            else:
                sidecar[key] = fields
        block = {name: item for name, item in value.items() if name != USERS_KEY}
        if kept:
            block[USERS_KEY] = kept
        record[key] = block
    return record, sidecars


def write_user_sidecars(record: Path, sidecars: dict[str, dict[str, Any]]) -> None:
    """Write a record's sidecars, each only where its text changes.

    A sidecar beside the record that ``sidecars`` no longer names -- its user's state all removed -- is written
    holding nothing but its stamp, so it never reads back what was removed.

    One that cannot be read (:func:`read_user_sidecar`) is never written over -- unparseable, past a sanity cap, or
    written by a newer build, whose fields this one has never seen ([[data-model#schema-version]]). Its scope was left
    out of the record when it was read (:func:`join_user_sidecars`), so ``sidecars`` holds nothing for it and it is
    skipped; fields for it mean a write reached a scope that was never read, and are refused.

    :param record: the ``.rehu`` they sit beside.
    :param sidecars: each sidecar's ``block key -> fields``, by slug (:func:`split_user_sidecars`).
    :raises UserSidecarError: ``sidecars`` holds fields for a sidecar that cannot be read.
    :raises OSError: one could not be read or written.
    """
    existing = user_sidecar_paths(record)
    for slug in sorted(sidecars.keys() | existing.keys()):
        path = existing.get(slug) or record.with_name(f"{record.stem}{USER_INFIX}{slug}{USER_SIDECAR_SUFFIX}")
        text = sidecar_text(sidecars.get(slug, {}))
        try:
            current = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            current = None
        if current == text:
            continue
        if current is not None:
            try:
                read_user_sidecar(path, slug)
            except UserSidecarError as error:
                if sidecars.get(slug):
                    raise
                LOG.debug("%s is left as it is: %s", path.name, error)
                continue
        atomic_write_text(path, text)


def sidecar_text(fields: dict[str, Any]) -> str:
    """A sidecar's text: its stamp, then its blocks and each block's fields in key order.

    :param fields: its ``block key -> fields``.
    :returns: the pretty-printed JSON, trailing newline included.
    """
    payload: dict[str, Any] = {FORMAT_VERSION_KEY: CURRENT_REHUSER_VERSION}
    for key in sorted(fields):
        value = fields[key]
        payload[key] = {name: value[name] for name in sorted(value)} if isinstance(value, dict) else value
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def joined_text(record_text: str, sidecars: list[UserSidecar]) -> str:
    """A record's text followed by each of its sidecars' -- what a version hashes, so a change to either is a change.

    :param record_text: the record's text.
    :param sidecars: its sidecars, as read with it.
    :returns: the texts, each sidecar's after its name.
    """
    return record_text + "".join(f"\0{sidecar.name}\0{sidecar.text}" for sidecar in sidecars)


def slug_or_none(scope: str) -> str | None:
    """:func:`user_slug`, or ``None`` for a scope with none.

    :param scope: a scope of a ``users`` map.
    :returns: its slug.
    """
    try:
        return user_slug(scope)
    except ValueError:
        return None
