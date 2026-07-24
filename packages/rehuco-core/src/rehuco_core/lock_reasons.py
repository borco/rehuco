"""The read-only **lock-reason vocabulary** ([[data-model#write-integrity]]).

A document opens read-only for a *named* cause, not a bare "locked" bool, so a viewer can say *why* and
act per kind -- and so :meth:`RehuDocument.save <rehuco_core.RehuDocument.save>` can refuse exactly the
kinds that would clobber recoverable data. The vocabulary lives here, apart from the document itself,
because it is what several layers speak: the core produces it, the agent's view-model mirrors it, and the
inline notice (#94) renders it. It depends on nothing in `rehuco_core.rehu_document`, so keeping it
separate also keeps that (already large) module to the document proper.

Field-specific message *text* deliberately does **not** live here -- it belongs next to the field check
that emits it (e.g. ``rehuco_core.rehu_locks``'s :data:`~rehuco_core.rehu_locks.INVALID_AUTHORS_MESSAGE`), so this module never accretes
per-field knowledge.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class LockReasonKind(StrEnum):
    """Why a document opens read-only ([[data-model#write-integrity]]).

    A named cause rather than a bare "locked" bool, so the viewer can say *why* and act per kind (the
    "Close Missing Files" sweep, for one, must tell ``MISSING`` apart from ``INVALID_FILE`` so it never
    closes a dock whose file the user is mid-repair on). Each has its own remedy; see
    :attr:`RehuDocument.lock_reasons <rehuco_core.RehuDocument.lock_reasons>`.
    """

    LEGACY_TC = "legacy_tc"
    """A legacy ``.tc`` mapped to the current layout but with no ``.rehu`` on disk yet
    ([[acquisition-tooling#tc-to-rehu]]); the remedy is conversion, not a text edit."""

    NEWER_FORMAT = "newer_format"
    """The file's ``format_version`` is newer than this build understands
    ([[data-model#schema-version]]'s fail-safe-on-a-newer-file rule); the fields are carried verbatim,
    never downgraded on save."""

    NEWER_BLOCK_FORMAT = "newer_block_format"
    """The **active** plugin block's own ``format_version`` is newer than the installed plugin
    understands ([[plugins#plugin-blocks]], the per-block refinement of :attr:`NEWER_FORMAT`'s
    fail-safe rule); the block's fields are carried verbatim, never downgraded on save, and never
    restamped (:func:`~rehuco_core.migrations.migrate_block_data` leaves such a block untouched)."""

    INVALID_FIELD = "invalid_field"
    """An owned field is **present but fails coercion** ([[data-model#write-integrity]]): reading coerces
    it for display, but editing must not be able to save the coerced default over the
    malformed-but-possibly-recoverable original. The message names the offending key."""

    INVALID_FILE = "invalid_file"
    """The file exists but cannot be parsed at all (``RehuFormatError``, or a non-missing ``OSError``):
    the document opens as an **empty** view bound to the path, never dirty, never savable. The message
    carries the parser's own text (a JSON error's line/column is what the user hand-fixes by)."""

    MISSING = "missing"
    """The file is gone (``FileNotFoundError``) -- deleted between sessions, an unmounted share. Same
    empty locked view as :attr:`INVALID_FILE`, kept distinct so a bulk "close vanished files" never
    sweeps away a dock whose file the user is mid-repair on."""


@dataclass(frozen=True)
class LockReason:
    """One named cause a document is locked ([[data-model#write-integrity]]): a :class:`LockReasonKind`
    plus a human-readable ``message`` naming the specifics (the offending key, the parser's line/column).

    :param kind: which cause this is.
    :param message: the specifics, for the persistent non-modal notice the viewer shows (#94).
    """

    kind: LockReasonKind
    message: str


SAVE_BLOCKING_LOCK_KINDS: Final = frozenset(
    {
        LockReasonKind.INVALID_FIELD,
        LockReasonKind.INVALID_FILE,
        LockReasonKind.MISSING,
    }
)
"""The lock kinds that make :meth:`RehuDocument.save <rehuco_core.RehuDocument.save>` refuse
([[data-model#write-integrity]]): saving would overwrite a malformed-but-recoverable field
(``INVALID_FIELD``) or a broken/absent file (``INVALID_FILE`` / ``MISSING``) with coerced defaults or an
empty document. ``LEGACY_TC``, ``NEWER_FORMAT``, and ``NEWER_BLOCK_FORMAT`` are **not** here -- a ``.tc``
saves through conversion and a newer file or block is carried verbatim, never downgraded
([[data-model#schema-version]]); all three are gated at the UI."""
