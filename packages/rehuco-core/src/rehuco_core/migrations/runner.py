"""The generic migration **runner** ([[data-model#schema-version]], [[plugins#plugin-blocks]]).

One walk serves every target -- the file, and each plugin's block: resolve the payload's stamp, run every
step whose target is above it in ascending order, then restamp. The runner knows *how* to walk a chain and
**names nothing** -- not a plugin, not a field. The chains and the steps (the "versions") live in the
per-target subpackages; a target differs only in its ``base_version`` (what an unstamped payload resolves
to: the file deduces v1 by shape, a block is v0 outright).
"""

from collections.abc import Callable
from typing import Any

from ..rehu_format import FORMAT_VERSION_KEY

Step = Callable[[dict[str, Any], str], None]
"""A migration step: reshapes one payload in place, filing any per-user data it moves under the caller's
``username`` ([[field-schema#per-user-shared]]). File-wide steps ignore the username."""

Chain = tuple[tuple[int, Step], ...]
"""An ordered ``(target, step)`` chain -- each ``step`` runs when the payload's version is below its
``target`` and brings it up to that version. The chain's head (its highest target) is the newest version
this build understands for that target."""


def chain_head(chain: Chain, base_version: int) -> int:
    """The newest version a chain reaches -- what a target derives its ``CURRENT_VERSION`` from.

    Derived rather than declared, so a target's head cannot drift from the steps it actually has. A
    function rather than a ``max`` at each target because an **empty** chain has no head to take: a
    target whose current shape is its first (the ``.checksum`` record, #203) answers its base version,
    and gets there without every such target spelling the fallback itself.

    :param chain: the target's ``(target, step)`` pairs.
    :param base_version: what an unstamped payload resolves to -- the answer for an empty chain.
    :returns: the highest target in the chain, or ``base_version`` when it is empty.
    """
    return max((target for target, _ in chain), default=base_version)


def stamped_version(payload: dict[str, Any], version_key: str = FORMAT_VERSION_KEY) -> int | None:
    """Read a payload's version stamp defensively -- one reader for the file, a block and the
    ``.checksum`` record ([[data-model#schema-version]]).

    :param payload: the parsed file object, one block's own fields, or a whole ``.checksum`` record.
    :param version_key: which key carries the stamp -- ``format_version`` for the ``.rehu`` targets,
        which is why it is the default; the ``.checksum`` record spells its own ``version`` (#203).
    :returns: the stamped version, or ``None`` when it is absent or malformed (a ``bool`` is malformed
        despite being an ``int`` subclass).
    """
    stamp = payload.get(version_key)
    return stamp if isinstance(stamp, int) and not isinstance(stamp, bool) else None


def run(
    payload: dict[str, Any],
    chain: Chain,
    *,
    base_version: int,
    username: str = "",
    version_key: str = FORMAT_VERSION_KEY,
) -> None:
    """Walk ``chain`` over ``payload`` in place, then stamp the version it ends at.

    **Never restamps a payload newer than the chain reaches.** When the payload's own version is already
    past every step's target, no guard is satisfied -- the loop is a no-op and the stamp written back is
    the value already there (never lowered).

    :param payload: the file object or block to migrate; mutated in place.
    :param chain: the ordered ``(target, step)`` pairs to walk; empty for a target with no history, which
        merely gets stamped ``base_version``.
    :param base_version: what an unstamped payload resolves to (1 for the file, 0 for a block).
    :param username: threaded to every step; the file-wide steps ignore it.
    :param version_key: which key carries the stamp, read and written under the same spelling
        (see :func:`stamped_version`).
    """
    version = stamped_version(payload, version_key)
    if version is None:
        version = base_version
    for target, upgrade in sorted(chain, key=lambda pair: pair[0]):
        if version < target:
            upgrade(payload, username)
            version = target
    payload[version_key] = version


def validate_chain(chain: Chain, base_version: int) -> None:
    """Assert a chain is well-formed, at import time -- fail-fast on a declaration bug
    ([[plugins#plugin-blocks]]).

    A chain must have **unique** targets that are **contiguous** from ``base_version + 1`` up to its head:
    a gap means a "2->3" step would silently run on a v1 payload, and a duplicate makes "which step is
    *the* v2" ambiguous. This restores the discipline the old ``PluginSpec`` validated at construction,
    now that a plugin declares no versions of its own.

    :param chain: the ``(target, step)`` pairs to check.
    :param base_version: the version an unstamped payload starts at.
    :raises ValueError: if the targets are not unique, or not contiguous from ``base_version + 1``.
    """
    targets = [target for target, _ in chain]
    if len(set(targets)) != len(targets):
        raise ValueError(f"duplicate migration target in chain: {sorted(targets)}")
    expected = list(range(base_version + 1, base_version + 1 + len(chain)))
    if sorted(targets) != expected:
        raise ValueError(
            f"migration chain must be contiguous from {base_version + 1} to its head; got {sorted(targets)}"
        )
