"""Reference-images plugin block migrations ([[plugins#plugin-blocks]], [[field-schema#per-user-shared]]).

The ``reference_images`` block adopts the same shared per-user map at v1 as the tutorial block, and the
same learning-path ``ref``-minting step at v2 ([[field-schema#learning-path-ownership]]) -- each step
serves both, referenced from each target's own chain. ``CURRENT_VERSION`` is the chain's head, derived.
"""

from . import v1_migrate_user_fields, v2_learning_path_refs

BASE_VERSION = 0
"""An unstamped block is v0 outright ([[plugins#plugin-blocks]])."""

CHAIN = (
    (v1_migrate_user_fields.VERSION, v1_migrate_user_fields.upgrade),
    (v2_learning_path_refs.VERSION, v2_learning_path_refs.upgrade),
)
"""This target's ordered ``(target, step)`` chain."""

CURRENT_VERSION = max(target for target, _ in CHAIN)
"""The newest ``reference_images`` block version this build understands -- the chain's head."""
