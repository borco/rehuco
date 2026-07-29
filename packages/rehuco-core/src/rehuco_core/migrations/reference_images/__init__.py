"""Reference-images plugin block migrations ([[plugins#plugin-blocks]], [[field-schema#per-user-shared]]).

The ``reference_images`` block adopts the same shared per-user map at v1 as the tutorial block, and the
same learning-path ``ref``-minting step at v2 ([[field-schema#learning-path-ownership]]) -- each step
serves both, referenced from each target's own chain. At **v3 the two chains diverge** for the first
time: only this one drops the ``viewed``/``todo`` progress flags ([[field-schema#resource-types]], #195),
which is the divergence the per-target declaration was written to allow. ``CURRENT_VERSION`` is the
chain's head, derived.
"""

# every target declares its own chain, frozen independently -- two plugins that happen to
# share both steps therefore read alike on purpose, and collapsing them would be the very
# coupling the per-target declaration exists to prevent
# pylint: disable=duplicate-code
from . import v1_migrate_user_fields, v2_learning_path_refs, v3_drop_progress_flags

BASE_VERSION = 0
"""An unstamped block is v0 outright ([[plugins#plugin-blocks]])."""

CHAIN = (
    (v1_migrate_user_fields.VERSION, v1_migrate_user_fields.upgrade),
    (v2_learning_path_refs.VERSION, v2_learning_path_refs.upgrade),
    (v3_drop_progress_flags.VERSION, v3_drop_progress_flags.upgrade),
)
"""This target's ordered ``(target, step)`` chain."""

CURRENT_VERSION = max(target for target, _ in CHAIN)
"""The newest ``reference_images`` block version this build understands -- the chain's head."""
