"""How a rendered name becomes one a filesystem keeps: transliterated to ASCII, then sanitized (#322, #577).

One step shared by every place that turns a record's fields into a file or folder name -- the agent's rename
suggestions and a root's layouts (:mod:`rehuco_core.root_destination`) -- so the two never name one record
differently.
"""

from anyascii import anyascii
from pathvalidate import is_valid_filename, sanitize_filename


def sanitize_name(raw: str) -> str | None:
    """Transliterate ``raw`` to ASCII and sanitize it into a valid filesystem name.

    :param raw: a rendered name (may hold unicode or characters no filesystem keeps).
    :returns: the sanitized name, or ``None`` if nothing valid survives.
    """
    name = sanitize_filename(anyascii(raw)).strip()
    return name if name and is_valid_filename(name) else None
