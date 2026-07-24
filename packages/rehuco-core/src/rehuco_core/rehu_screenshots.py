"""Current ``.rehu`` screenshot recognition: the ``<stem>NN`` sibling convention ([[data-model#image-meanings]]).

The reader counterpart of `rehuco_core.tc_screenshots`: where the legacy scanner produces a *rename
plan* (a ``.tc``'s files must be renamed on conversion), a ``.rehu`` resource's screenshots are
already correctly named, so this just lists them. Core-side and GUI-free: the caller resolves ``stem``
however it needs to and passes it in as a plain string.
"""

import re
from pathlib import Path

from .constants import IMAGE_EXTENSIONS


def scan_rehu_screenshot_files(directory: Path, stem: str) -> list[Path]:
    """List ``directory``'s ``<stem>NN`` screenshot siblings, sorted by filename.

    For ``stem="info"`` these are ``info00.jpg`` / ``info01.png`` / ... -- a two-digit index and an
    :data:`IMAGE_EXTENSIONS` extension, matched case-insensitively.

    :param directory: the resource's directory to scan.
    :param stem: the filename base (e.g. ``"info"`` for a directory-scoped resource, or the file stem).
    :returns: the matching absolute paths sorted by name, or empty when ``directory`` is
        missing/unreadable (e.g. an offline mount, [[mounts-and-storage#offline-mounts]]) or holds none.
    """
    pattern = re.compile(rf"^{re.escape(stem)}\d{{2}}$", re.IGNORECASE)
    try:
        siblings = list(directory.iterdir())
    except OSError:
        return []
    matches = [
        sibling for sibling in siblings if sibling.suffix.lower() in IMAGE_EXTENSIONS and pattern.match(sibling.stem)
    ]
    return sorted(matches, key=lambda sibling: sibling.name)
