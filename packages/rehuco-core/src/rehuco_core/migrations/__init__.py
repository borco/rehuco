"""Read-time format migrations -- file-wide and per plugin block ([[data-model#schema-version]],
[[plugins#plugin-blocks]]).

Migrations run **in memory, on load** and never touch the file until it is saved. The package is Alembic-
shaped: a generic :mod:`~rehuco_core.migrations.runner` walks a chain and names nothing; each *target* is
its own subpackage declaring a ``BASE_VERSION`` and a ``CHAIN`` of ``(version, step)`` pairs, and each step
is a self-contained transform that inlines the literals it operates on (importing nothing from the live
vocabulary, because a migration is a frozen historical record).

- :mod:`~rehuco_core.migrations.rehu` -- the file-wide chain (v1 -> v2: nest common fields under ``core``).
- :mod:`~rehuco_core.migrations.tutorial`, :mod:`~rehuco_core.migrations.reference_images` -- the plugin
  block chains, each adopting the shared
  :func:`~rehuco_core.migrations.shared.migrate_user_fields.migrate_user_fields` mechanism at its own
  version (both v1 today, free to differ -- and they do differ from v3, where only the reference-images
  chain drops the ``viewed``/``todo`` progress flags).
- :mod:`~rehuco_core.migrations.checksum` -- the ``.checksum`` record's chain (empty today: v1 is the
  first shape), stamped under the record's own ``version`` key (#203).

The direction is one-way: migrations know which plugin a chain belongs to (by key -- :data:`BLOCK_TARGETS`);
a plugin knows nothing about its own history. Every chain is validated at import (:func:`validate_all_chains`).
"""

from typing import Final, Protocol

from . import checksum, reference_images, rehu, tutorial
from .runner import Chain, Step, run, stamped_version, validate_chain


class MigrationTarget(Protocol):
    """The shape a plugin block's migration subpackage must have to sit in :data:`BLOCK_TARGETS`.

    Modules satisfy protocols structurally, so ``tutorial`` and ``reference_images`` need no explicit
    declaration -- this only gives their three module-level attributes a real type in place of
    :class:`~types.ModuleType`'s ``Any``.
    """

    # Read-only properties, not plain attributes: a target module's own CHAIN/BASE_VERSION/CURRENT_VERSION
    # are typed via `max(...)`/tuple-literal inference rather than an explicit `int`/`Chain` annotation, so
    # a mutable Protocol attribute (invariant) would reject them on the literal's exact type; a getter only
    # needs the return type to be assignable, which is what structural module access actually is.
    # pylint: disable=invalid-name,missing-function-docstring
    @property
    def CHAIN(self) -> Chain: ...

    @property
    def BASE_VERSION(self) -> int: ...

    @property
    def CURRENT_VERSION(self) -> int: ...


BLOCK_TARGETS: Final[dict[str, MigrationTarget]] = {
    # Keyed by each plugin's stable **main key** -- referenced by name, so the migration layer depends on
    # plugins and never the reverse. A key with no entry (collection, an uninstalled type, a stray block)
    # has an empty chain: head 0, nothing to run.
    "tutorial": tutorial,
    "reference_images": reference_images,
}
"""Every plugin's block-migration target, keyed by main key ([[plugins#plugin-blocks]])."""

CURRENT_FORMAT_VERSION = rehu.CURRENT_VERSION
"""The file-wide ``format_version`` this build understands, and stamps onto every payload it reads -- the
head of the :mod:`~rehuco_core.migrations.rehu` chain ([[data-model#schema-version]])."""

CURRENT_CHECKSUM_RECORD_VERSION = checksum.CURRENT_VERSION
"""The ``.checksum`` record ``version`` this build understands -- the head of the
:mod:`~rehuco_core.migrations.checksum` chain ([[data-model#checksums]], #203)."""


def validate_all_chains() -> None:
    """Assert every registered chain is well-formed; called once at import (fail-fast on a declaration bug).

    :raises ValueError: if any chain has duplicate or non-contiguous targets (see
        :func:`~rehuco_core.migrations.runner.validate_chain`).
    """
    validate_chain(rehu.CHAIN, rehu.BASE_VERSION)
    validate_chain(checksum.CHAIN, checksum.BASE_VERSION)
    for target in BLOCK_TARGETS.values():
        validate_chain(target.CHAIN, target.BASE_VERSION)


validate_all_chains()


def migrate_rehu_data(data: dict) -> None:
    """Bring a parsed ``.rehu`` payload up to :data:`CURRENT_FORMAT_VERSION`, in place.

    :param data: the parsed JSON object; mutated to the current layout.
    """
    run(data, rehu.CHAIN, base_version=rehu.BASE_VERSION)


def migrate_checksum_data(data: dict) -> None:
    """Bring a parsed ``.checksum`` record up to :data:`CURRENT_CHECKSUM_RECORD_VERSION`, in place
    ([[data-model#checksums]], #203).

    :param data: the parsed JSON object; mutated to the current layout and stamped under the record's
        own ``version`` key.
    """
    checksum.migrate_checksum_data(data)


def migrate_block_data(block: dict, plugin_key: str, username: str) -> None:
    """Bring one plugin block up to its chain's head, in place ([[plugins#plugin-blocks]]).

    :param block: the block's own fields; mutated in place.
    :param plugin_key: the plugin's main key, used to look up its chain; an unknown key migrates nothing
        and stamps the block ``0``.
    :param username: the caller's active identity, handed to each step so one that reshapes per-user state
        records whose it is ([[field-schema#per-user-shared]]).
    """
    target = BLOCK_TARGETS.get(plugin_key)
    chain = target.CHAIN if target is not None else ()
    base = target.BASE_VERSION if target is not None else 0
    run(block, chain, base_version=base, username=username)


def current_block_version(plugin_key: str) -> int:
    """The newest block version this build understands for a plugin -- its chain's head, derived not
    declared ([[plugins#plugin-blocks]]).

    :param plugin_key: the plugin's main key, as spelled on disk.
    :returns: the target's ``CURRENT_VERSION``, or ``0`` when it has no chain.
    """
    target = BLOCK_TARGETS.get(plugin_key)
    return target.CURRENT_VERSION if target is not None else 0


__all__ = [
    "BLOCK_TARGETS",
    "CURRENT_CHECKSUM_RECORD_VERSION",
    "CURRENT_FORMAT_VERSION",
    "Chain",
    "MigrationTarget",
    "Step",
    "current_block_version",
    "migrate_block_data",
    "migrate_checksum_data",
    "migrate_rehu_data",
    "run",
    "stamped_version",
    "validate_all_chains",
    "validate_chain",
]
