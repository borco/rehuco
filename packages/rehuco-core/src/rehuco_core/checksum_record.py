"""The ``.checksum`` record: one resource's verification history, read and written
([[data-model#checksums]], #203).

A ``.checksum`` is **a record of verification over time**, not a manifest: per content file it holds
which hash was recorded, when the file was last checked, and what the answer was. That is what lets a
periodic sweep (#242) skip what was checked recently, and it is not expressible in any format an
external checker reads -- which is why the record is JSON of this app's own and ``cfv`` interop was
dropped deliberately. The legacy manifest suffixes stay *recognized* as bookkeeping
(:data:`~rehuco_core.constants.CHECKSUM_MANIFEST_EXTENSIONS`) so they never count as content, but
nothing writes them.

The shape, beside ``foo.rehu`` as ``foo.checksum`` (``info.rehu`` -> ``info.checksum``)::

    {
      "version": 1,
      "files": [
        { "name": "foo1/bar1.zip", "crc32": "42342424",
          "verified": "2026-08-04T23:34:56Z", "status": "matched" },
        { "name": "bar2.zip", "status": "unexpected" },
        { "name": "foo3/bar3.zip", "xxh3": "42342424",
          "verified": "2026-08-04T23:34:56Z", "status": "mismatched" }
      ]
    }

**The hash key is the algorithm tag**, at most one per entry, present only once the file has been
hashed. This is how [[data-model#checksums]]'s *record which algorithm was used per entry* is satisfied,
and it is genuinely per entry: a resource may hold ``crc32`` and ``xxh3`` entries side by side, so
changing the configured algorithm invalidates nothing already recorded.

This module is the record's *format* -- loading, saving, and reading one entry defensively. What a
generate or a verify does with the entries is :mod:`rehuco_core.rehu_checksums`'s; the split mirrors
:mod:`rehuco_core.rehu_content_files` (which files) against the operations over them.
"""

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal

from borco_core import atomic_write_text

from .checksum_algorithms import CHECKSUM_ALGORITHMS
from .constants import CHECKSUM_RECORD_SUFFIX
from .migrations import CURRENT_CHECKSUM_RECORD_VERSION, migrate_checksum_data
from .migrations.checksum import VERSION_KEY

CHECKSUM_FILES_KEY: Final = "files"
"""The record's top-level key holding the per-file entries, in the order they are kept."""

CHECKSUM_NAME_KEY: Final = "name"
"""An entry's key naming the file it is about -- relative to the ``.rehu``, POSIX-separated, never
absolute and never escaping the directory (:func:`parse_checksum_entry` enforces this on read)."""

CHECKSUM_VERIFIED_KEY: Final = "verified"
"""An entry's key holding when the file was last checked, UTC, e.g. ``"2026-08-04T23:34:56Z"`` -- the
same spelling a ``.rehu``'s ``created``/``updated`` carry ([[field-schema#record-timestamps]])."""

CHECKSUM_STATUS_KEY: Final = "status"
"""An entry's key holding what the last check answered -- one of :data:`ChecksumStatus`'s values."""

ChecksumStatus = Literal["matched", "mismatched", "missing", "unexpected", "malformed"]
"""What one check of one file can answer ([[data-model#checksums]], #203).

``matched`` / ``mismatched`` -- the file was hashed and compared. ``missing`` -- the record lists it and
the disk does not hold it. ``unexpected`` -- the disk holds it and the record carries no hash for it; a
report state rather than a resting one, since a sweep adopts such a file
(:func:`~rehuco_core.rehu_checksums.verify_checksums`). ``malformed`` -- an entry this build cannot
read; it costs itself, is carried through untouched, and its neighbours still verify. ``malformed`` is
only ever *reported*, never written into an entry: writing anything into an entry this build cannot
read is what carrying it through byte-for-byte exists to avoid."""

HEX_DIGEST_PATTERN: Final = re.compile(r"[0-9a-fA-F]+")
"""What a recorded hash must look like -- hex, either case (a value seeded from a legacy ``.sfv`` may be
uppercase); the *length* each algorithm requires is its own
(:attr:`~rehuco_core.ChecksumAlgorithm.hex_length`)."""


class ChecksumRecordError(ValueError):
    """A ``.checksum`` file this build cannot read at all ([[data-model#checksums]]).

    File-level, deliberately distinct from a *malformed entry*: an entry that cannot be read costs
    itself and its neighbours still verify, but a file that is not JSON, not an object, or stamped
    newer than this build can only be reported whole -- guessing at half of it could bless bytes the
    record never vouched for.
    """


@dataclass(frozen=True, slots=True)
class ChecksumEntry:
    """One entry of a ``.checksum`` record, read defensively ([[data-model#checksums]], #203).

    The parsed *view* of a raw entry object -- what generate and verify reason over, while the raw
    object itself is what a run that does not touch this entry carries through byte-for-byte.

    :param name: the file's name, relative to the ``.rehu``, POSIX-separated.
    :param algorithm: the recorded hash's algorithm tag, or ``None`` when the entry has never been
        hashed (a resting ``unexpected``).
    :param digest: the recorded hash, exactly as spelled on disk, or ``None`` with ``algorithm``.
    :param verified: when the file was last checked, or ``None`` when it never was -- or when the
        recorded value does not parse, which deliberately reads as *never*: an unreadable date only
        ever costs a staleness skip, and treating it as malformed would refuse a hash that is fine.
    :param status: what the last check answered, or ``None``; carried as found, not validated --
        the next check overwrites it either way.
    """

    name: str
    algorithm: str | None
    digest: str | None
    verified: datetime | None
    status: str | None


def checksum_record_path(rehu_path: Path) -> Path:
    """Where ``rehu_path``'s record lives: the same-stem ``.checksum`` sibling.

    :param rehu_path: the resource's ``.rehu`` file.
    :returns: ``info.rehu`` -> ``info.checksum``, ``foo.rehu`` -> ``foo.checksum``.
    """
    return rehu_path.with_suffix(CHECKSUM_RECORD_SUFFIX)


def load_checksum_record(path: Path) -> dict[str, Any]:
    """Read a ``.checksum`` file whole, migrated to the current version.

    Returns the record object **raw** -- the entry list unparsed, and any top-level key beside
    ``version`` and ``files`` carried as found -- because the callers' contract is byte-for-byte
    carry-through of everything a run does not touch, the same round-trip discipline a ``.rehu`` owes
    fields it does not understand ([[data-model#schema-version]]). Parsing belongs to
    :func:`parse_checksum_entry`, entry by entry, where a failure costs one entry rather than the file.

    :param path: the record file, from :func:`checksum_record_path`.
    :returns: the record object, stamped, with :data:`CHECKSUM_FILES_KEY` guaranteed present as a
        (possibly empty) list.
    :raises FileNotFoundError: no record file -- the caller's ``create_if_missing`` decision, not this
        reader's.
    :raises OSError: the file exists and cannot be read.
    :raises ChecksumRecordError: the file is not JSON, not an object, holds no entry list, or is
        stamped newer than this build understands.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise ChecksumRecordError(f"Not a text file: {path}") from error
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise ChecksumRecordError(f"Not JSON: {path}") from error
    if not isinstance(data, dict):
        raise ChecksumRecordError(f"Not a JSON object: {path}")
    migrate_checksum_data(data)
    version = data[VERSION_KEY]
    if version > CURRENT_CHECKSUM_RECORD_VERSION:
        raise ChecksumRecordError(
            f"Record version {version} is newer than this build understands ({CURRENT_CHECKSUM_RECORD_VERSION}): {path}"
        )
    files = data.setdefault(CHECKSUM_FILES_KEY, [])
    if not isinstance(files, list):
        raise ChecksumRecordError(f"'{CHECKSUM_FILES_KEY}' is not a list: {path}")
    return data


def new_checksum_record() -> dict[str, Any]:
    """A record for a resource that has never had one -- what ``create_if_missing`` starts from.

    :returns: a current-version record holding no entries, shaped as :func:`load_checksum_record`
        shapes a loaded one.
    """
    return {VERSION_KEY: CURRENT_CHECKSUM_RECORD_VERSION, CHECKSUM_FILES_KEY: []}


def save_checksum_record(path: Path, record: dict[str, Any]) -> None:
    """Write ``record`` back as a current-version file, atomically.

    Through :func:`borco_core.atomic_write_text`, and written **once per run, at the end**
    ([[data-model#checksums]]): a stopped or crashed run leaves the previous record intact rather than
    a truncated one a later verify would read as authority for half the resource.

    The layout is canonical: ``version`` first, any carried unknown key next in the order it was read,
    the entry list last so the bulk trails. The stamp written is always this build's -- the record came
    through the migration chain, so its content *is* current whatever a missing or malformed stamp
    said on the way in.

    :param path: the record file, from :func:`checksum_record_path`.
    :param record: the record object as :func:`load_checksum_record` shaped it, entries included.
    :raises OSError: the file could not be written.
    """
    payload: dict[str, Any] = {VERSION_KEY: CURRENT_CHECKSUM_RECORD_VERSION}
    payload.update({key: value for key, value in record.items() if key not in (VERSION_KEY, CHECKSUM_FILES_KEY)})
    payload[CHECKSUM_FILES_KEY] = record.get(CHECKSUM_FILES_KEY, [])
    atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def checksum_entry_name(raw: Any) -> str | None:
    """Read an entry's name, and validate it names a file *inside* the resource.

    Separate from :func:`parse_checksum_entry` because a malformed entry with a readable name is still
    reportable by that name, and still *selectable*: a targeted generate naming it re-baselines it,
    which is how a broken entry gets fixed rather than carried forever.

    :param raw: one element of the record's entry list, of any shape.
    :returns: the name, or ``None`` when the entry is not an object, has no string name, or the name
        is empty, absolute, escapes the directory (``..``), or is not POSIX-plain (``\\`` or a drive
        colon) -- a name that could reach outside the resource is refused outright, never resolved.
    """
    if not isinstance(raw, dict):
        return None
    name = raw.get(CHECKSUM_NAME_KEY)
    if not isinstance(name, str) or not name:
        return None
    parts = name.split("/")
    if any(part in ("", ".", "..") or "\\" in part or ":" in part for part in parts):
        return None
    return name


def parse_checksum_entry(raw: Any) -> ChecksumEntry | None:
    """Read one raw entry into a :class:`ChecksumEntry`, or refuse it as malformed.

    Malformed means **this build cannot read it** ([[data-model#checksums]], #203): no usable name
    (:func:`checksum_entry_name`), more than one hash key, a hash that is not well-formed hex of its
    algorithm's length -- or no known hash key alongside keys this build does not know, which is how a
    hash recorded by some *other* build under an algorithm this one has no entry for is refused rather
    than silently re-hashed: adopting such a file would replace a hash that was never checked, which is
    exactly the laundering a verify must not do. Extra keys *beside* a known hash are fine and carried.

    :param raw: one element of the record's entry list, of any shape.
    :returns: the parsed entry, or ``None`` when it is malformed -- in which case the caller reports it
        and carries the raw object through untouched.
    """
    name = checksum_entry_name(raw)
    if name is None:
        return None
    hash_keys = [key for key in raw if key in CHECKSUM_ALGORITHMS]
    if len(hash_keys) > 1:
        return None
    if not hash_keys:
        known = {CHECKSUM_NAME_KEY, CHECKSUM_VERIFIED_KEY, CHECKSUM_STATUS_KEY}
        if any(key not in known for key in raw):
            return None
        algorithm = None
        digest = None
    else:
        algorithm = hash_keys[0]
        digest = raw[algorithm]
        specification = CHECKSUM_ALGORITHMS[algorithm]
        if not isinstance(digest, str) or len(digest) != specification.hex_length:
            return None
        if HEX_DIGEST_PATTERN.fullmatch(digest) is None:
            return None
    status = raw.get(CHECKSUM_STATUS_KEY)
    return ChecksumEntry(
        name=name,
        algorithm=algorithm,
        digest=digest,
        verified=parse_verified(raw.get(CHECKSUM_VERIFIED_KEY)),
        status=status if isinstance(status, str) else None,
    )


def parse_verified(value: Any) -> datetime | None:
    """Read an entry's ``verified`` stamp defensively.

    :param value: the recorded value, of any shape.
    :returns: the stamp as an aware UTC datetime -- a naive one is taken *as* UTC, since UTC is the
        only thing this app ever writes -- or ``None`` when it is absent or does not parse, which
        reads as *never verified*: the stamp only ever gates a staleness skip, so an unreadable one
        costs a re-check, never the entry.
    """
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    return stamp if stamp.tzinfo is not None else stamp.replace(tzinfo=UTC)


def verified_stamp(moment: datetime) -> str:
    """Spell a check's moment the way the record stores it.

    :param moment: an aware datetime; taken to UTC.
    :returns: e.g. ``"2026-08-04T23:34:56Z"`` -- whole seconds, ``Z``-suffixed, the same spelling a
        ``.rehu``'s timestamps carry ([[field-schema#record-timestamps]]).
    """
    return moment.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
