"""Plugin identity: what a plugin *is*, and how this build knows one exists ([[plugins#core-vs-plugin]]).

A plugin is identified by a **declared key list**, not by a name transformed at runtime
([[plugins#plugin-blocks]]). This is the non-GUI half of a plugin -- the layer agent and node alike load
-- and it holds *identity* only.

The package is split by dependency layer:

- :mod:`~rehuco_core.plugins.plugin_spec` -- the :class:`~rehuco_core.PluginSpec` identity dataclass.
- :mod:`~rehuco_core.plugins.constants` -- the live per-user vocabulary (`USERS_KEY`, the current/unknown
  identity defaults).
- :mod:`~rehuco_core.plugins.plugin_registry` -- the shipped plugin declarations (including the
  descriptive :data:`~rehuco_core.CORE_PLUGIN`) and the :class:`~rehuco_core.PluginRegistry` index.

The ``.rehu`` file-format grammar (reserved keys, the core block key) lives in
:mod:`rehuco_core.rehu_format`, not here; and nothing here imports :mod:`rehuco_core.migrations` -- a
plugin knows nothing about how its block was laid out in an older build.
"""

from .constants import DEFAULT_CURRENT_USERNAME, DEFAULT_UNKNOWN_USERNAME, USERS_KEY
from .plugin_registry import (
    BUILTIN_PLUGINS,
    COLLECTION_PLUGIN,
    CORE_PLUGIN,
    DEFAULT_PLUGIN_REGISTRY,
    REFERENCE_IMAGES_PLUGIN,
    TUTORIAL_PLUGIN,
    PluginRegistry,
)
from .plugin_spec import PluginSpec

__all__ = [
    "BUILTIN_PLUGINS",
    "COLLECTION_PLUGIN",
    "CORE_PLUGIN",
    "DEFAULT_CURRENT_USERNAME",
    "DEFAULT_PLUGIN_REGISTRY",
    "DEFAULT_UNKNOWN_USERNAME",
    "REFERENCE_IMAGES_PLUGIN",
    "TUTORIAL_PLUGIN",
    "USERS_KEY",
    "PluginRegistry",
    "PluginSpec",
]
