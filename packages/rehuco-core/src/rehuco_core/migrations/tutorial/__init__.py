"""Tutorial plugin block migrations ([[plugins#plugin-blocks]], [[field-schema#per-user-shared]]).

The ``tutorial`` block adopts the shared per-user map at v1. ``CURRENT_VERSION`` is the chain's head,
derived not declared.
"""

from . import v1_migrate_user_fields

BASE_VERSION = 0
"""An unstamped block is v0 outright -- block versioning has no pre-stamping history ([[plugins#plugin-blocks]])."""

CHAIN = ((v1_migrate_user_fields.VERSION, v1_migrate_user_fields.upgrade),)
"""This target's ordered ``(target, step)`` chain."""

CURRENT_VERSION = max(target for target, _ in CHAIN)
"""The newest ``tutorial`` block version this build understands -- the chain's head."""
