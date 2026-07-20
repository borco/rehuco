"""Reusable per-user relocation **mechanism** ([[field-schema#per-user-shared]]).

A library, not a migration: it holds *how* to move a set of fields under a block's ``users`` map,
parameterized, with no version and no field set of its own. Each plugin's migration passes the field set
and the map key it froze at its own version -- so the mechanism is written once while every historical
fact stays frozen in the migration that owns it.
"""

from typing import Any


def migrate_user_fields(block: dict[str, Any], username: str, *, fields: frozenset[str], users_key: str) -> None:
    """Move ``fields`` (those present) out of ``block`` and under ``block[users_key][username]``, in place.

    The generic per-user relocation every plugin's v0->v1 step is built from; it hardcodes none of the
    specifics -- the caller passes the field set and the map key it froze at its own version.

    :param block: one block's own fields; mutated in place.
    :param username: the identity the moved fields are filed under.
    :param fields: the keys to relocate -- whichever of them the block actually has.
    :param users_key: the map key to nest the moved fields under.
    """
    moved = {key: value for key, value in block.items() if key in fields}
    for key in moved:
        del block[key]
    block[users_key] = {username: moved}
