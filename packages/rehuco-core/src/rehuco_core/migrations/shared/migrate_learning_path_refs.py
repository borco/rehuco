"""Reusable learning-path ownership **mechanism** ([[field-schema#learning-path-ownership]]).

A library, not a migration: it holds *how* to drop the retired ``visibility`` flag from a block's owned
learning paths and mint each a ``ref``, with no version of its own. Each plugin's v1->v2 step passes the
map key it froze at its own version -- so the mechanism is written once while every historical fact stays
frozen in the migration that owns it.
"""

from typing import Any


def migrate_learning_path_refs(block: dict[str, Any], *, users_key: str) -> None:
    """Drop ``visibility`` from every owned learning path under ``block[users_key]`` and mint each a
    ``ref``, in place.

    A v1 block has only owned entries -- the bare ``{ref}`` subscription shape did not exist before this
    step -- so every entry present gets a fresh ``ref``. Refs are minted in one pass over every user
    already in the block, in ascending username order, so they are unique across the whole block -- the
    widest scope a block migration can guarantee, since a step is handed one block and never sees a
    sibling. In practice that is the file's whole ref space: no importer writes learning paths into two
    blocks, and only the active block is ever migrated. But a file already carrying a *second* block
    with such entries mints from 1 again when that block later becomes active, so the file-wide
    uniqueness of [[field-schema#learning-path-ownership]] is the invariant of ref-minting writers,
    not of this per-block step.

    :param block: one block's own fields; mutated in place.
    :param users_key: the map key the per-user subset already nests under (this step never runs before
        the v0->v1 relocation that creates it).
    """
    users = block.get(users_key)
    if not isinstance(users, dict):
        return
    ref = 0
    for username in sorted(users):
        user = users[username]
        if not isinstance(user, dict):
            continue
        paths = user.get("learning_paths")
        if not isinstance(paths, list):
            continue
        for entry in paths:
            if not isinstance(entry, dict):
                continue
            entry.pop("visibility", None)
            ref += 1
            entry["ref"] = ref
