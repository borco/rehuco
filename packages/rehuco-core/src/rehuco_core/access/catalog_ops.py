"""What the catalog operation group answers: a refusal to read, and the session a local catalog reads through (#417).

The group itself, :class:`~rehuco_core.access.CatalogOps`, is declared beside the other groups in
:mod:`~rehuco_core.access.resource_access`; these are the values around it.
"""

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID


class CatalogUnreadable(OSError):
    """The catalog could not be read -- its cache is damaged or locked, or the node serving it did not answer.

    One type for what a local cache raises as ``sqlite3.Error``, so a caller never catches a driver's exception that
    a remote implementation would not raise.
    """


@dataclass(frozen=True, slots=True)
class CatalogSession:
    """What a :class:`~rehuco_core.access.LocalCatalog` reads: one cache, and the roots of the view over it.

    A cache may hold rows of a root the view dropped, until the job removing it has run; those are not part of the
    view.

    :param cache_path: the cache file.
    :param root_ids: the roots the view lists.
    """

    cache_path: Path
    root_ids: frozenset[UUID]
