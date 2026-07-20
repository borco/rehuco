"""The ``.rehu`` file-format grammar: the reserved top-level keys and the core block's identity
([[data-model#rehu-format]]).

A **pure leaf** that both :mod:`rehuco_core.plugins` and :mod:`rehuco_core.migrations` sit on, depending on
neither the other and importing nothing itself. These are facts about the *file format* -- which top-level
keys are not plugin blocks, what the version stamp is called -- not about any plugin and not about any
migration. In particular :data:`FORMAT_VERSION_KEY` is the versioning *mechanism*: the runner reads and
writes it to track where a payload is, so it is the one key a migration step never reshapes (the odometer,
not the cargo) and the one that is genuinely invariant rather than frozen per migration.

Only the *strings* live here. :data:`~rehuco_core.CORE_PLUGIN` -- the ``PluginSpec`` describing the core
block -- stays in :mod:`rehuco_core.plugins`, because pulling ``PluginSpec`` into this leaf would close a
``rehu_format`` -> ``plugins`` -> ``rehu_format`` import cycle; the grammar needs only the key it spells.
"""

from typing import Final

FORMAT_VERSION_KEY: Final = "format_version"
"""The schema-version key ([[data-model#schema-version]]); at the file's top level it describes the file's
own layout, and inside a plugin block it describes that block's ([[plugins#plugin-blocks]]). The version
stamp the migration runner reads and writes -- never data a migration reshapes."""

CORE_BLOCK_KEY: Final = "core"
"""The common core's block key ([[data-model#rehu-format]]); spelled once, here. The reserved block that
holds the common fields every type shares -- :data:`~rehuco_core.CORE_PLUGIN` describes it, but its *name*
is grammar and lives here."""

RESERVED_KEYS: Final = frozenset({FORMAT_VERSION_KEY, CORE_BLOCK_KEY})
"""The two top-level ``.rehu`` keys that are not plugin blocks ([[data-model#rehu-format]]): the file's
own version stamp, and the common core's block. The single source of truth
:class:`~rehuco_core.PluginRegistry` (no plugin may declare one) and ``RehuDocument`` (no document may
misuse one as a block) both check against."""
