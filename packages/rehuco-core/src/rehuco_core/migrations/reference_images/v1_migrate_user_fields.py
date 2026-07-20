"""**reference_images block v0 -> v1**: nest the per-user fields under the block's ``users`` map
([[field-schema#per-user-shared]]).

Self-contained: the field set and the map key are frozen *here*, at v1, and passed to the shared
:func:`~rehuco_core.migrations.shared.migrate_user_fields.migrate_user_fields` mechanism. This is a
*separate* frozen record from the tutorial step it currently coincides with -- if the reference-images
per-user set ever diverges, only this file changes.
"""

from typing import Any

from ..shared.migrate_user_fields import migrate_user_fields

VERSION = 1
"""The version this step brings a ``reference_images`` block up to."""

# Frozen at v1 -- this migration's own copies, deliberately not imported from the live vocabulary.
USERS_KEY = "users"
FIELDS = frozenset({"rating", "viewed", "todo", "keep", "favorite", "learning_paths"})


def upgrade(block: dict[str, Any], username: str) -> None:
    """Relocate the reference-images block's per-user fields under ``users[username]``, in place.

    :param block: one v0 ``reference_images`` block's own fields; mutated in place.
    :param username: the identity the moved fields are filed under.
    """
    migrate_user_fields(block, username, fields=FIELDS, users_key=USERS_KEY)
