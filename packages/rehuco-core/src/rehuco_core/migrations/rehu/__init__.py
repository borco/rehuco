"""File-wide ``.rehu`` format migrations ([[data-model#schema-version]]).

The target for the file itself: an unstamped payload is the flat v1 layout (``BASE_VERSION``), and the
chain climbs from there. ``CURRENT_VERSION`` is derived from the chain's head, never declared separately,
so it cannot drift from the steps that actually exist.
"""

from . import v2_core_block

BASE_VERSION = 1
"""What an unstamped file resolves to -- the flat v1 layout, deduced by shape ([[data-model#schema-version]])."""

CHAIN = ((v2_core_block.VERSION, v2_core_block.upgrade),)
"""This target's ordered ``(target, step)`` chain."""

CURRENT_VERSION = max(target for target, _ in CHAIN)
"""The newest file version this build understands -- the chain's head."""
