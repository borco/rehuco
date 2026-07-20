"""Live per-user vocabulary the plugin layer and the document model share ([[field-schema#per-user-shared]]).

The *current* spelling of the per-user map key and the fallback identity -- what the accessors and the
``.tc`` importer use today. The ``.rehu`` file-format grammar (the reserved keys, the core block) lives in
:mod:`rehuco_core.rehu_format`, not here; and which fields a *past* block layout kept where is migration
history, frozen inside each migration in :mod:`rehuco_core.migrations`.
"""

from typing import Final

USERS_KEY: Final = "users"
"""The plugin-block key holding **per-user state**, a map keyed by username ([[field-schema#per-user-shared]]).

The one place a per-user field's owner is recorded: ``rating``, the per-user boolean flags, and private
``learning_paths`` live under ``block[USERS_KEY][<username>]`` rather than inline, so a file that has only
ever seen one user still names whose flags these are -- a fact recorded at write time, which no later
migration could reconstruct by guessing ([[field-schema#per-user-shared]]).

This is the *current* spelling, read and written by the live accessors and the importer. A migration that
relocates fields under this map inlines its own frozen ``"users"`` literal instead of importing this, so a
future rename of the key never rewrites history."""

DEFAULT_USERNAME: Final = "admin"
"""The fallback identity when none is configured ([[field-schema#per-user-shared]]).

Core has no settings of its own, so a per-user write or a ``.tc`` import handed no username files its state
under this name. The real identity -- seeded from the OS login on a settings page -- is the agent's to
supply (a later slice); this is only what "who owns this" resolves to in its absence."""
