"""**reference_images block v1 -> v2**: drop ``visibility`` from owned learning paths and mint each a
``ref`` -- the same step the ``tutorial`` block takes, since both share the ``learning_paths`` field
([[field-schema#learning-path-ownership]]).

Self-contained: the map key is frozen *here*, at v2, and passed to the shared
:func:`~rehuco_core.migrations.shared.migrate_learning_path_refs.migrate_learning_path_refs` mechanism. A
later change to another plugin's ``users`` key never touches this historical step.
"""

from typing import Any

from ..shared.migrate_learning_path_refs import migrate_learning_path_refs

VERSION = 2
"""The version this step brings a ``reference_images`` block up to."""

# Frozen at v2 -- this migration's own copy, deliberately not imported from the live vocabulary.
USERS_KEY = "users"


def upgrade(block: dict[str, Any], _username: str) -> None:
    """Drop ``visibility`` and mint a ``ref`` for every owned learning path already in the block, in place.

    :param block: one v1 ``reference_images`` block's own fields; mutated in place.
    :param _username: unused -- the step processes every user already filed in the block, not the
        caller's own identity.
    """
    migrate_learning_path_refs(block, users_key=USERS_KEY)
