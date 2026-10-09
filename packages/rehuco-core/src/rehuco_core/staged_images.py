"""An image taken out of a resource to another app: a byte-identical copy, staged under a name that says where it came
from ([[reference-images#modes]], #395).

A content image inside an archive has no file of its own, and a loose image's name carries no provenance, so every
image dragged or copied out of the app is first copied -- **its bytes unchanged** -- into a folder the app owns, and
that copy is what the other app receives. Nothing is written into the image (no EXIF, XMP or PNG text): content
images are immutable and checksummed ([[data-model#image-meanings]]), and an unchanged copy stays identifiable by its
content hash even after someone renames it.

**The name** is ``rehu-<origin>__<path>``, the image's path relative to its record with ``__`` between the segments
and an archive as a segment of its own -- ``foo.zip/bar/a.jpg`` becomes ``rehu-<uuid>__foo.zip__bar__a.jpg``. The
origin is the resource's id; a record with none (an old or hand-written ``.rehu``, a ``.tc``) is named by its location
folder or its file's stem instead, and :func:`parse_staged_name` tells the two apart by the id's shape.

Core takes the folder as a parameter and knows no platform's cache location, as with the catalog cache
([[data-model#cache-schema]]): where the folder lives, and when :func:`prune_staged` runs, is the app's to say.
"""

import logging
import os
import re
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path, PurePosixPath
from typing import Final

from borco_core import atomic_write_bytes

from .resource_scoping import is_directory_scoped

LOG: Final = logging.getLogger(__name__)

STAGED_PREFIX: Final = "rehu-"
"""What every staged name starts with: what :func:`parse_staged_name` recognizes one by."""

SEGMENT_SEPARATOR: Final = "__"
"""Between the origin and each path segment. A segment never contains it, nor starts or ends with ``_``
(:func:`sanitized_segment`), so splitting on it gives the segments back exactly."""

MAX_NAME_BYTES: Final = 200
"""The longest staged name, in UTF-8 bytes: well under the 255 every target file system allows -- in bytes on APFS,
which is why this counts bytes rather than characters -- so an app that adds ``(1)`` to a duplicate still fits."""

SHORTENED_MARK: Final = "~"
"""Ends a segment cut short to fit :data:`MAX_NAME_BYTES`, so a reader can see that it was."""

MIDDLE_SEGMENT_FLOOR: Final = 8
"""How many bytes of a folder or archive segment are kept, before the mark, when one is cut short."""

UNSAFE_CHARACTERS: Final = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
"""What Windows or macOS refuses in a file name, replaced by ``_``."""

UNDERSCORE_RUNS: Final = re.compile(r"_{2,}")

UUID_SHAPE: Final = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
"""A resource id as the app mints it (``str(uuid4())``): what tells an id origin from a location one."""


@dataclass(frozen=True, slots=True)
class StagedImageName:
    """What a staged name says about where its image came from.

    :ivar origin: the resource's id, or the location folder or file stem of a record that has none.
    :ivar path: the image's path relative to its record, ``/``-separated -- **as sanitized** for the name, so a
        segment that held an unsafe character, or was cut short to fit, reads as it does in the name.
    """

    origin: str
    path: str

    @property
    def uuid(self) -> str | None:
        """The resource's id when the origin is one, else ``None`` -- the origin is then a location."""
        return self.origin if UUID_SHAPE.fullmatch(self.origin) else None


def staging_origin(document_id: str, record_path: Path | None) -> str:
    """What a staged name says its image came from: the resource's id, or where its record is when it has none.

    :param document_id: the record's id; ``""`` when it has none (a ``.tc``, an old or hand-written ``.rehu``).
    :param record_path: the record, ``.rehu`` or ``.tc``; ``None`` when it was never saved.
    :returns: the id; else the location folder of a directory-scoped record, or a file-scoped record's stem; ``""``
        when there is neither.
    """
    if document_id:
        return document_id
    if record_path is None:
        return ""
    return record_path.parent.name if is_directory_scoped(record_path) else record_path.stem


def sanitized_segment(segment: str) -> str:
    """One segment of a staged name, safe on every target file system and free of the separator.

    :param segment: the origin, or one segment of the image's path.
    :returns: the segment with unsafe characters replaced by ``_``, runs of ``_`` collapsed, no ``_`` at either end
        and no trailing dot or space; ``-`` when nothing is left.
    """
    cleaned = UNDERSCORE_RUNS.sub("_", UNSAFE_CHARACTERS.sub("_", segment))
    cleaned = cleaned.rstrip("._ ").lstrip("_")
    return cleaned or "-"


def shortened(text: str, max_bytes: int) -> str:
    """``text`` cut to ``max_bytes`` UTF-8 bytes, ending in :data:`SHORTENED_MARK`.

    :param text: the segment to cut.
    :param max_bytes: the most it may take, the mark included.
    :returns: the cut segment, never cut inside a character.
    """
    budget = max_bytes - len(SHORTENED_MARK.encode())
    encoded = text.encode()[: max(budget, 0)]
    return encoded.decode(errors="ignore") + SHORTENED_MARK


def staged_name(origin: str, relative_path: str) -> str:
    """The name an image is staged under: ``rehu-<origin>__<segments joined by __>``.

    Shortened to :data:`MAX_NAME_BYTES` in this order, until it fits: the folder and archive segments between the
    origin and the basename, the longest first, down to :data:`MIDDLE_SEGMENT_FLOOR` bytes; then all of them
    collapsed into one :data:`SHORTENED_MARK`; then an origin that is not an id; and only then the basename's stem,
    its extension kept. An id is never shortened.

    :param origin: what :func:`staging_origin` says.
    :param relative_path: the image's path relative to its record, ``/``-separated, an archive a segment of its own.
    :returns: the name.
    """
    parts = [sanitized_segment(part) for part in PurePosixPath(relative_path).parts if part != "/"]
    basename = parts[-1] if parts else "-"
    middles = parts[:-1]
    origin = sanitized_segment(origin)

    def excess() -> int:
        name = STAGED_PREFIX + SEGMENT_SEPARATOR.join([origin, *middles, basename])
        return len(name.encode()) - MAX_NAME_BYTES

    floor = MIDDLE_SEGMENT_FLOOR + len(SHORTENED_MARK.encode())
    while excess() > 0:
        longest = max(range(len(middles)), key=lambda index: len(middles[index].encode()), default=None)
        if longest is None or len(middles[longest].encode()) <= floor:
            break
        size = len(middles[longest].encode())
        middles[longest] = shortened(middles[longest], max(size - excess(), floor))
    if excess() > 0 and middles:
        middles = [SHORTENED_MARK]
    if excess() > 0 and not UUID_SHAPE.fullmatch(origin):
        origin = shortened(origin, max(len(origin.encode()) - excess(), 1 + len(SHORTENED_MARK.encode())))
    if excess() > 0:
        stem, dot, suffix = basename.rpartition(".")
        if not dot:
            stem, suffix = basename, ""
        kept = max(len(stem.encode()) - excess(), 1 + len(SHORTENED_MARK.encode()))
        basename = shortened(stem, kept) + dot + suffix
    return STAGED_PREFIX + SEGMENT_SEPARATOR.join([origin, *middles, basename])


def parse_staged_name(name: str) -> StagedImageName | None:
    """Read back where a staged image came from -- the inverse of :func:`staged_name`.

    What round-trips is the **sanitized** path: a segment that held an unsafe character or was cut short to fit
    reads as the name has it. The content hash, not the name, is what identifies the image for certain.

    :param name: a file name, as another app may have kept it.
    :returns: the origin and path; ``None`` for a name that is not a staged one.
    """
    if not name.startswith(STAGED_PREFIX):
        return None
    parts = name.removeprefix(STAGED_PREFIX).split(SEGMENT_SEPARATOR)
    if len(parts) < 2 or not all(parts):
        return None
    return StagedImageName(parts[0], "/".join(parts[1:]))


def stage_image(folder: Path, name: str, data: bytes) -> Path | None:
    """Write an image's bytes, unchanged, to ``folder / name`` -- or reuse the copy already there.

    A copy that already holds exactly these bytes is kept, with its modification time bumped so
    :func:`prune_staged` counts its age from this use; one that holds other bytes (the pack changed since) is
    replaced. Written atomically, so a drop target reading the file never sees half of it.

    :param folder: the staging folder, created when missing.
    :param name: what :func:`staged_name` says.
    :param data: the image's bytes.
    :returns: the staged file; ``None`` when it could not be written, which is logged.
    """
    path = folder / name
    try:
        folder.mkdir(parents=True, exist_ok=True)
        if holds_bytes(path, data):
            os.utime(path)
        else:
            atomic_write_bytes(path, data)
    except OSError as error:
        LOG.warning("Could not stage %s: %s", path, error)
        return None
    return path


def holds_bytes(path: Path, data: bytes) -> bool:
    """Whether the file at ``path`` holds exactly ``data``.

    :param path: the file.
    :param data: the bytes to compare.
    :returns: whether it does; ``False`` when there is no file.
    :raises OSError: when the file exists but cannot be read.
    """
    try:
        if path.stat().st_size != len(data):
            return False
    except FileNotFoundError:
        return False
    return path.read_bytes() == data


def prune_staged(folder: Path, max_age: timedelta, now: float) -> None:
    """Delete the staged files not used for ``max_age``.

    A staged file must outlive the drop -- a file manager may copy it after the drag has ended -- and a paste hours
    later, so nothing is deleted when it is handed over; this is what keeps the folder from growing.

    :param folder: the staging folder; a missing one has nothing to prune.
    :param max_age: how long since its last use a file is kept.
    :param now: the current time, in seconds since the epoch.
    """
    cutoff = now - max_age.total_seconds()
    try:
        files = [entry for entry in folder.iterdir() if entry.is_file()]
    except OSError:
        return
    for file in files:
        try:
            if file.stat().st_mtime < cutoff:
                file.unlink()
        except OSError:
            LOG.warning("Could not prune staged image %s", file, exc_info=True)
