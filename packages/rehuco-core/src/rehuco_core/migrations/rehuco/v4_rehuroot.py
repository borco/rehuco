"""**``.rehuco`` v3 -> v4**: roots inline give way to references to ``.rehuroot`` files
([[mounts-and-storage#rehuroot]], #577).

There is no migration, as there was none to v3: a v3 root's id was minted per catalog, and a ``.rehuroot`` is one root
shared by every catalog that lists it, so the file is made again by adding its roots to a new catalog. The step refuses
rather than write root files on the user's behalf.
"""

from typing import Any

from .v3_root_location import RehucoTooOldError

VERSION = 4
"""The version this step brings a ``.rehuco`` up to."""


def upgrade(_data: dict[str, Any], _username: str) -> None:
    """Refuse a file whose roots are inline.

    :param _data: the parsed v3 ``.rehuco`` object; unused.
    :param _username: unused -- the file holds nothing per user.
    :raises RehucoTooOldError: always.
    """
    raise RehucoTooOldError(
        "This catalog lists its roots inline, from an older build. Create a new catalog and add its roots again"
    )
