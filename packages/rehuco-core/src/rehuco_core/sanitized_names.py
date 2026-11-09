"""How a rendered name becomes one a filesystem keeps: transliterated to ASCII, then sanitized (#322, #577).

One step shared by every place that turns a record's fields into a file or folder name -- the agent's rename
suggestions and a root's layouts (:mod:`rehuco_core.root_destination`) -- so the two never name one record
differently.
"""

from typing import Final

from anyascii import anyascii
from pathvalidate import is_valid_filename, sanitize_filename


def sanitize_name(raw: str) -> str | None:
    """Transliterate ``raw`` to ASCII and sanitize it into a valid filesystem name.

    :param raw: a rendered name (may hold unicode or characters no filesystem keeps).
    :returns: the sanitized name, or ``None`` if nothing valid survives.
    """
    name = sanitize_filename(anyascii(raw)).strip()
    return name if name and is_valid_filename(name) else None


LOCATION_STEM_SEPARATOR: Final = "--"
"""What joins a location's segments in the name of its root file."""


def location_stem(location: str) -> str | None:
    """A root file name for a root's location: its segments, each sanitized as a name is, joined by ``--``.

    :param location: where the root is, as :func:`rehuco_core.root_location.location_of` spells it.
    :returns: for ``//nas/data_14t/DATA1/TUTORIALS`` ``nas--data_14t--DATA1--TUTORIALS``; ``None`` if no segment
        survives sanitizing.
    """
    names = (sanitize_name(segment) for segment in location.split("/"))
    return LOCATION_STEM_SEPARATOR.join(name for name in names if name) or None
