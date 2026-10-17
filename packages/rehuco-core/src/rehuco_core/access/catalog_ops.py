"""What :class:`~rehuco_core.access.Catalog` answers and reads through: a refusal to read, and the session
(#417)."""

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID


class CatalogUnreadable(OSError):
    """The catalog could not be read -- its cache is damaged, locked or missing.

    One type for what the cache raises as ``sqlite3.Error`` or ``OSError``, so a caller never catches a driver's
    exception.
    """


@dataclass(frozen=True, slots=True)
class CatalogSession:
    """What a :class:`~rehuco_core.access.Catalog` reads: one cache, and the roots of the view over it.

    A cache may hold rows of a root the view dropped, until the job removing it has run; those are not part of the
    view.

    :param cache_path: the cache file.
    :param root_ids: the roots the view lists.
    """

    cache_path: Path
    root_ids: frozenset[UUID]
