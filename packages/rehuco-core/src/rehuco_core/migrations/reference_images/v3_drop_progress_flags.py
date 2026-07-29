"""**reference_images block v2 -> v3**: drop the ``viewed``/``todo`` progress flags from every user's
entry ([[field-schema#resource-types]], #195).

The one step in either chain that **deletes** rather than reshapes. Both flags are progress through timed
material -- watched it, queued to watch it -- which a reference-image pack has no notion of; the tutorial
block keeps them. They reached reference-images blocks because tc4 stored all six booleans for every type
and the importer carried them across ([[acquisition-tooling#tc-to-rehu]]), so what this removes may well
be a value someone set -- it is a deletion, not a cleanup of defaults.

Deliberate all the same, and not a precedent: carrying them instead would surface each as an unrecognized
field on every imported pack ([[plugins#fallback-editor]]), flagged as written by a *newer* plugin than
this one -- the exact opposite of their history, and a permanent nag with a drop button the user would
have to press per document. The narrow scope is what makes that acceptable: two named keys, one block
type, only inside the ``users`` map. The import side stops writing them at the source
(``tc_document``'s per-user subset), since a freshly imported block is stamped current and would never
reach this step.

Self-contained: the field set and the map key are frozen *here*, at v3, so a later change to the live
vocabulary never reaches back into this step.
"""

from typing import Any

VERSION = 3
"""The version this step brings a ``reference_images`` block up to."""

# Frozen at v3 -- this migration's own copies, deliberately not imported from the live vocabulary.
USERS_KEY = "users"
FIELDS = frozenset({"viewed", "todo"})


def upgrade(block: dict[str, Any], _username: str) -> None:
    """Remove :data:`FIELDS` from every identity filed in the block's ``users`` map, in place.

    Every user's entry, not just the caller's: the flags are per-user
    ([[field-schema#per-user-shared]]), so a file carrying several identities would otherwise keep the
    others' copies and re-surface them the moment that identity became current.

    **Only inside the map.** A block that reaches v3 with ``viewed``/``todo`` still *inline* is one the
    v0->v1 step declined to touch (it already had a ``users`` map, so its inline keys were carried
    verbatim rather than merged over data already filed,
    :func:`~rehuco_core.migrations.shared.migrate_user_fields.migrate_user_fields`). Deleting them here
    would discard exactly what that step chose to preserve, so they stay put and surface through the
    generic fallback like any other unrecognized key.

    :param block: one v2 ``reference_images`` block's own fields; mutated in place.
    :param _username: unused -- the step processes every user already filed in the block, not the
        caller's own identity.
    """
    users = block.get(USERS_KEY)
    if not isinstance(users, dict):
        return
    for fields in users.values():
        if not isinstance(fields, dict):
            continue
        for key in FIELDS:
            fields.pop(key, None)
