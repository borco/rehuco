"""**``.rehuco`` v2 -> v3**: a root's ``path`` and ``storage`` give way to a ``location``
([[mounts-and-storage#rehuco-scope]], #514).

There is no migration: a v2 root holds a path as spelled on the machine that wrote it, and a location is computed on the
machine that finds the folder, so the file is made again by adding its roots to a new catalog. The step refuses rather
than guess, so a file this build cannot read says why instead of coming up with roots that point nowhere.
"""

from typing import Any

VERSION = 3
"""The version this step brings a ``.rehuco`` up to."""


class RehucoTooOldError(ValueError):
    """A ``.rehuco`` written before roots had locations, which this build does not carry forward."""


def upgrade(_data: dict[str, Any], _username: str) -> None:
    """Refuse a file older than the layout with locations.

    :param _data: the parsed v1 or v2 ``.rehuco`` object; unused.
    :param _username: unused -- the file holds nothing per user.
    :raises RehucoTooOldError: always.
    """
    raise RehucoTooOldError(
        "This catalog was made by an older build, whose roots hold paths rather than locations. "
        "Create a new catalog and add its roots again"
    )
