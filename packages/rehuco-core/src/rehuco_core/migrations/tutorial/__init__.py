"""Tutorial plugin block migrations ([[plugins#plugin-blocks]], [[field-schema#per-user-shared]]).

The ``tutorial`` block adopts the shared per-user map at v1, then drops learning-path ``visibility`` and
mints ``ref``s at v2 ([[field-schema#learning-path-ownership]]). ``CURRENT_VERSION`` is the chain's head,
derived not declared.
"""

# every target declares its own chain, frozen independently -- two plugins that happen to
# share both steps therefore read alike on purpose, and collapsing them would be the very
# coupling the per-target declaration exists to prevent
# pylint: disable=duplicate-code
from . import v1_migrate_user_fields, v2_learning_path_refs

BASE_VERSION = 0
"""An unstamped block is v0 outright -- block versioning has no pre-stamping history ([[plugins#plugin-blocks]])."""

CHAIN = (
    (v1_migrate_user_fields.VERSION, v1_migrate_user_fields.upgrade),
    (v2_learning_path_refs.VERSION, v2_learning_path_refs.upgrade),
)
"""This target's ordered ``(target, step)`` chain."""

CURRENT_VERSION = max(target for target, _ in CHAIN)
"""The newest ``tutorial`` block version this build understands -- the chain's head."""
