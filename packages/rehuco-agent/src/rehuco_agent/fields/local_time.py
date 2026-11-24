"""A stored UTC timestamp as the local time a person reads (#623, #678)."""

from datetime import datetime, tzinfo
from typing import Final

LOCAL_TIME_FORMAT: Final = "%Y-%m-%d %H:%M:%S"
"""How :func:`local_time_text` spells a moment, ``2026-11-08 17:32:54``."""


def local_time_text(value: str, tz: tzinfo | None = None) -> str | None:
    """A stored UTC timestamp, ``2026-11-08T15:32:54Z``, in local time, ``2026-11-08 17:32:54``.

    :param value: the stored text.
    :param tz: the zone to show a moment in; the machine's local zone when omitted.
    :returns: the local time, or ``None`` for text that is empty, a date with no time, or no timestamp -- which a
        reader shows as stored.
    """
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    return moment.astimezone(tz).strftime(LOCAL_TIME_FORMAT)
