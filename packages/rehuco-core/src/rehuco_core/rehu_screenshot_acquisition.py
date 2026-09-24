"""Writing one newly-acquired image into a resource's ``<stem>NN`` set ([[data-model#image-meanings]], #73).

The third writer beside `rehuco_core.rehu_screenshot_ordering` (moving/deleting) and
`rehuco_core.tc_screenshots.convert_screenshot` (numbering a pattern-matched legacy file): this one
gives a slot to bytes that arrived from outside the resource entirely -- a local file dropped on the
images sub-dock, image data carried by the drop itself, or a scraper's downloaded URL. Core-side and
GUI-free, and ignorant of where the bytes came from: a caller has already turned a drop or a fetch into
plain bytes and an extension by the time either function here is asked to do anything.
"""

from pathlib import Path
from typing import Final

from .constants import LEGACY_SUFFIX
from .rehu_screenshots import scan_rehu_screenshot_files
from .tc_conversion_backups import BACKUP_SUFFIX
from .tc_screenshots import MAX_SCREENSHOT_SLOT

MAX_BACKUP_ATTEMPTS: Final = 1000
"""How many collision counters :func:`screenshot_backup_path` will try before giving up.

Never expected to bind in practice -- it would take a thousand acquisitions landing on the same slot
between saves -- but an unbounded loop has no honest way to say a directory is stuck rather than
merely busy."""


def screenshot_backup_path(original: Path) -> Path:
    """The first free ``.orig`` name for ``original``, so backing it up never overwrites another backup.

    The plain ``<name>.orig`` (:data:`~rehuco_core.tc_conversion_backups.BACKUP_SUFFIX`, the same one a
    ``.tc`` conversion's own backups carry -- one kind of backup, not two, so a single Discard cleans up
    either) is tried first. A collision inserts a counter between the stem and the extension --
    ``info00.2.jpg.orig``, then ``info00.3.jpg.orig`` -- rather than after ``.orig``, so every name this
    returns still ends in the one suffix a directory listing (or a discard) recognizes as a backup at all.

    :param original: the file about to be backed up.
    :returns: the first name, in that order, that does not already exist.
    """
    first = original.with_name(original.name + BACKUP_SUFFIX)
    if not first.exists():
        return first
    for counter in range(2, MAX_BACKUP_ATTEMPTS):
        candidate = original.with_name(f"{original.stem}.{counter}{original.suffix}{BACKUP_SUFFIX}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"no free backup name for {original} after {MAX_BACKUP_ATTEMPTS} attempts")


def save_screenshot(directory: Path, stem: str, data: bytes, extension: str, slot: int | None = None) -> Path:
    """Write ``data`` into ``directory`` as a new ``<stem>NN`` screenshot.

    ``data`` is written exactly as given -- nothing here decodes, rescales or re-encodes it, so an
    animated GIF keeps its animation and a caller's own bytes are what land on disk.

    :param directory: the resource's directory.
    :param stem: the filename base the numbered set shares.
    :param data: the image's raw bytes.
    :param extension: the file's extension, leading dot included (e.g. ``".jpg"``).
    :param slot: the ``<stem>NN`` slot to write into. ``None`` (a plain drop) takes the slot one past
        the current highest, the same rule :func:`~rehuco_core.tc_screenshots.convert_screenshot`
        appends by. An explicit slot (a scrape result's own numbering, assigned in encounter order) may
        already be occupied -- by this call's own extension or another -- in which case the file
        already there is renamed to :func:`screenshot_backup_path` first, never overwritten.
    :returns: the new file's path.
    :raises PermissionError: ``directory`` still holds a legacy ``.tc`` record -- the same refusal
        :func:`~rehuco_core.tc_screenshots.convert_screenshot` makes.
    :raises ValueError: ``slot`` is ``None`` and the numbered set is already full.
    """
    if (directory / f"{stem}{LEGACY_SUFFIX}").exists():
        raise PermissionError(f"{directory} belongs to a resource that is still a {LEGACY_SUFFIX}")
    existing = scan_rehu_screenshot_files(directory, stem)
    if slot is None:
        taken = {int(path.stem[len(stem) :]) for path in existing}
        slot = max(taken, default=-1) + 1
        if slot >= MAX_SCREENSHOT_SLOT:
            raise ValueError(f"cannot number a new screenshot: the {stem}NN set is full")
    else:
        for occupant in existing:
            if occupant.stem == f"{stem}{slot:02d}":
                occupant.rename(screenshot_backup_path(occupant))
    destination = directory / f"{stem}{slot:02d}{extension}"
    # exclusive create, not write_bytes: a slot just vacated by the rename above -- or freshly picked
    # as the next free one -- must still never be silently overwritten if something is wrong with
    # either computation
    with destination.open("xb") as file:
        file.write(data)
    return destination
