""".rehu document model: JSON read/write that preserves unknown fields on round-trip.

A ``.rehu`` is ``format_version`` plus a map of **keyed blocks** ([[data-model#rehu-format]]): the
reserved ``core`` block holding the common fields every type shares, and one block per plugin, exactly
one of which is **active** ([[plugins#plugin-blocks]]). The parsed JSON object is kept verbatim as the
source of truth; typed accessors read and write the core block's fields
([[field-schema#resource-types]]) on top of it. Keys the model does not understand -- including every
inactive plugin block -- are never dropped, satisfying the preserve-unknown-fields rule
([[data-model#schema-version]]). Older layouts are upgraded in memory on load by
`rehuco_core.migrations`. Writes go through :func:`borco_core.atomic_write_text` so a crash never yields
a torn file ([[data-model#write-integrity]]).
"""

# the document has a broad surface (common-core accessors, the plugin block model -- identity, versioning,
# and lock reasons alike -- round-trip fidelity); one cohesive module reads better than an arbitrary split,
# so the module-length cap is lifted here rather than fragmenting it.
# pylint: disable=too-many-lines

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from borco_core import atomic_write_text

from .lock_reasons import SAVE_BLOCKING_LOCK_KINDS, LockReason, LockReasonKind
from .migrations import (
    CURRENT_FORMAT_VERSION,
    current_block_version,
    migrate_block_data,
    migrate_rehu_data,
    stamped_version,
)
from .plugins import (
    DEFAULT_PLUGIN_REGISTRY,
    DEFAULT_USERNAME,
    USERS_KEY,
    PluginRegistry,
)
from .rehu_format import CORE_BLOCK_KEY, FORMAT_VERSION_KEY, RESERVED_KEYS

LOG: Final = logging.getLogger(__name__)

PRIMARY_KEY: Final = "primary"
"""Marker key on the canonical entry in ``sources`` ([[field-schema#sources]])."""

# One ``authors`` entry ([[field-schema#authors]]): a plain name string, or a ``{"name", "url"}``
# record carrying an author-page URL. The record form is canonical only when it has a URL to carry --
# a bare name is stored as a plain string (:attr:`RehuDocument.authors` setter).
type AuthorEntry = str | dict[str, Any]

CORE_LEADING_KEYS: Final = ("type", "id", "created", "updated", "sources")
"""The core block's keys that lead the file, in this order; everything else follows alphabetically
(:meth:`RehuDocument.save`).

What a reader looks for first when opening a `.rehu` by hand: what it is, which record it is, when it was
made, and -- via ``sources`` -- what it is *called* ([[field-schema#sources]]). Everything after is
alphabetical, which is why this list can stay short and needs no maintenance: a field missing from it
merely sorts with the rest, it is never misplaced. Unlike a *recognition* list (a migration's frozen
common-field set), being incomplete here costs nothing."""


@dataclass(frozen=True)
class PluginBlock:
    """One plugin block found in a document, classified active or inactive ([[plugins#plugin-blocks]]).

    :param key: the block's top-level key, already normalized to its plugin's main spelling when that
        plugin is installed here.
    :param fields: the block's own fields, held **by reference** into the document's backing data --
        mutating it in place is reflected on the next save.
    :param active: whether this is the one block the document's ``type`` names.
    """

    key: str
    fields: dict[str, Any]
    active: bool


class RehuFormatError(ValueError):
    """Raised when a ``.rehu`` payload cannot be read as valid: not a JSON object, unparseable, or
    misusing a reserved key ([[data-model#rehu-format]])."""


INVALID_AUTHORS_MESSAGE: Final = (
    "authors: contains an entry this build cannot read -- each must be a name string or a "
    "{name, url} record ([[field-schema#authors]])"
)
"""The :attr:`~LockReasonKind.INVALID_FIELD` message for a present ``authors`` the getter cannot read
cleanly -- a non-list, or a list with an entry it would skip ([[field-schema#authors]])."""


class RehuDocument:  # pylint: disable=too-many-public-methods,too-many-instance-attributes
    """In-memory view over one ``.rehu`` JSON document.

    Wraps the parsed object and exposes the common-core fields as typed properties while
    keeping every other key untouched for round-trips. A ``.rehu`` holds *several* keyed plugin blocks,
    exactly one of which is active ([[plugins#plugin-blocks]]): see :meth:`plugin_blocks`.

    :param data: the parsed JSON object backing this document.
    :param path: the file this document was loaded from, used as the default save target.
    :param legacy_tc: whether this document was mapped from a legacy ``.tc`` file
        ([[acquisition-tooling#tc-to-rehu]]) rather than loaded from a genuine ``.rehu``; see
        :attr:`legacy_tc`.
    :param plugins: the plugins installed here ([[plugins#core-vs-plugin]]), used **only** to normalize
        alias spellings to their main key on the way in; defaults to this build's shipped set. Never
        consulted to decide which block is active -- that follows from ``type`` alone
        ([[plugins#plugin-blocks]]).
    :param username: the active identity whose per-user state this document reads, writes, and files a
        v0->v1 block migration under ([[field-schema#per-user-shared]]); defaults to
        :data:`~rehuco_core.plugins.DEFAULT_USERNAME` since core has no settings to seed a real one (the
        agent supplies that in a later slice). One value serves both consumers -- the per-user accessors
        (:meth:`active_user_field`) and the block migration run at construction -- so they can never
        disagree about whose data a file holds.
    :param on_disk_format_version: the version of the file this payload was read from; see
        :attr:`on_disk_format_version`. Set only by :meth:`load`, which is the only caller that knows a
        file was involved -- constructing a document does not make one exist. Defaults to ``None``: no
        file.
    :param on_disk_active_block_format_version: the active block's own version, as it was on the file
        this payload was read from, before construction migrated it; see
        :attr:`on_disk_active_block_format_version`. Set only by :meth:`load`, for the same reason as
        ``on_disk_format_version``. Defaults to ``None``: no on-disk block to compare against.
    :param load_failure: the reason this document stands in for a file that could not be read at all
        (:attr:`~LockReasonKind.MISSING` / :attr:`~LockReasonKind.INVALID_FILE`); set only by
        :meth:`locked_stub_for_error`. Defaults to ``None``: a genuinely-parsed document.
    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        data: dict[str, Any],
        path: Path | None = None,
        *,
        legacy_tc: bool = False,
        plugins: PluginRegistry = DEFAULT_PLUGIN_REGISTRY,
        username: str = DEFAULT_USERNAME,
        on_disk_format_version: int | None = None,
        on_disk_active_block_format_version: int | None = None,
        load_failure: LockReason | None = None,
    ) -> None:
        # Final forbids rebinding __data to a different dict, not mutating this one -- every
        # setter edits __data (or a dict nested inside it) in place, so it is always current
        # and save() never needs a separate sync step. __path has no such guarantee: save()
        # legitimately rebinds it when called with an explicit path.
        self.__data: Final = data
        self.__path = path
        self.__legacy_tc: Final = legacy_tc
        self.__plugins: Final = plugins
        self.__username: Final = username
        self.__on_disk_format_version = on_disk_format_version
        self.__on_disk_active_block_format_version = on_disk_active_block_format_version
        self.__load_failure = load_failure
        """The load-failure reason (:attr:`load_failed`), or ``None`` for a genuinely-parsed document.
        Not ``Final``: :meth:`reload` rebinds it, which is what makes revert the fix-retry loop
        ([[data-model#write-integrity]])."""
        self.__check_reserved_keys(data)
        migrate_rehu_data(data)
        self.__normalize()
        self.__migrate_active_block()

    def __check_reserved_keys(self, data: dict[str, Any]) -> None:
        """Refuse a payload that misuses a reserved key ([[data-model#rehu-format]]), before anything
        else touches it.

        Must run **before** :func:`~rehuco_core.migrations.migrate_rehu_data`: an unstamped
        ``format_version`` reads as v1, and the v1->v2 step restamps it, overwriting the very evidence
        of misuse this checks for. Unlike an unrecognized plugin block ([[plugins#fallback-editor]]),
        there is no coherent reading to fall back to here -- the payload contradicts the format's own
        grammar, so construction itself refuses rather than producing a document that is quietly
        incoherent.

        :param data: the payload as handed to ``__init__``, not yet migrated or normalized.
        :raises RehuFormatError: if ``format_version`` holds an object (a plugin's data, mistaken for
            the version stamp), or ``core.type`` names a reserved key (which is not a resource type).
        """
        if isinstance(data.get(FORMAT_VERSION_KEY), dict):
            raise RehuFormatError(
                f"{FORMAT_VERSION_KEY!r} holds an object, but it is the file's version number, not a plugin block."
            )
        core = data.get(CORE_BLOCK_KEY)
        if isinstance(core, dict) and core.get("type") in RESERVED_KEYS:
            raise RehuFormatError(f"'type' is {core['type']!r}, which is a reserved key rather than a resource type.")

    @classmethod
    def load(
        cls,
        path: Path | str,
        *,
        plugins: PluginRegistry = DEFAULT_PLUGIN_REGISTRY,
        username: str = DEFAULT_USERNAME,
    ) -> RehuDocument:
        """Read and parse a ``.rehu`` file from disk.

        A ``.rehu`` is untrusted outside input ([[data-model#write-integrity]]) -- a double-clicked file
        is not this app's just because of its extension -- so a payload that cannot be parsed is
        **refused** as a `RehuFormatError` rather than being allowed to escape as whatever the parser
        happened to raise. ``json.loads`` raises more than ``JSONDecodeError``: deep nesting exhausts the
        interpreter stack (``RecursionError``), and an over-long integer literal trips CPython's
        integer-digit limit (a bare ``ValueError``). Catching ``ValueError`` covers both that and
        ``JSONDecodeError``, which is a subclass of it.

        This does **not** make parsing safe against a hostile file's *size* -- the full sanity caps this
        section calls for (total bytes, nesting depth, entry counts) are not implemented, and the read
        below buys the whole file into memory before ``json`` ever sees it (#88).

        :param path: path to the ``.rehu`` file.
        :param plugins: the plugins installed here, for alias normalization; see :class:`RehuDocument`.
        :param username: the active identity; see :class:`RehuDocument`. Threaded so a file opened at an
            older block layout is migrated under the caller's identity, not a bare default.
        :returns: a document backed by the parsed JSON object.
        :raises RehuFormatError: if the file cannot be parsed, or its top-level JSON value is not an object.
        """
        path = Path(path)
        try:
            data: object = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, RecursionError) as exc:
            raise RehuFormatError(f"Invalid JSON — {exc}.") from exc
        if not isinstance(data, dict):
            raise RehuFormatError("Expected a JSON object at the top level.")
        if stamped_version(data) is None and CORE_BLOCK_KEY in data:
            # No build wrote this: `core` arrived with format v2, and saving has stamped since v1, so a
            # file cannot honestly have the one without the other. Not fatal -- it is carried verbatim
            # and read as best it can be ([[data-model#schema-version]]) -- but it is not a v2 file
            # either, and silence would let a broken one pass for one.
            LOG.warning("%s: has a 'core' block but no usable format_version -- reading it as unversioned", path)
        # read the file's own stamp before constructing: the migrator restamps the payload to the current
        # version on the way in, so this is the last moment the *file*'s version is visible
        return cls(
            data,
            path,
            plugins=plugins,
            username=username,
            on_disk_format_version=cls.__coerced_version(data),
            on_disk_active_block_format_version=cls.__raw_active_block_version(data),
        )

    @classmethod
    def open_or_locked(
        cls,
        path: Path | str,
        *,
        plugins: PluginRegistry = DEFAULT_PLUGIN_REGISTRY,
        username: str = DEFAULT_USERNAME,
    ) -> RehuDocument:
        """Load ``path``, or return an **empty document bound to it, locked**, when it cannot be read.

        The one place the *refuse-vs-lock* line is drawn ([[data-model#write-integrity]]): a file that is
        missing, unparseable, or refused by :meth:`load` does not raise past here and does not surface as a
        modal error box -- it opens as a locked, never-dirty, never-savable view whose
        :attr:`lock_reasons` name the failure, so the file stays inspectable in exactly the tool best
        suited to hand-fixing it. :meth:`reload` retries through here, which is what makes revert the
        fix-retry loop rather than a reopen cycle.

        A ``FileNotFoundError`` is :attr:`~LockReasonKind.MISSING`; any other ``OSError`` or a
        :class:`RehuFormatError` is :attr:`~LockReasonKind.INVALID_FILE` (:meth:`locked_stub_for_error`
        draws that distinction once). Loading a legacy ``.tc`` is *not* routed here -- that path goes
        through :func:`rehuco_core.load_tc` -- but its failures reach the same stub via
        :meth:`locked_stub_for_error`.

        :param path: path to the ``.rehu`` file.
        :param plugins: the plugins installed here, for alias normalization; see :class:`RehuDocument`.
        :param username: the active identity; see :class:`RehuDocument`.
        :returns: the loaded document, or an empty locked stub bound to ``path``.
        """
        path = Path(path)
        try:
            return cls.load(path, plugins=plugins, username=username)
        except (OSError, RehuFormatError) as error:
            return cls.locked_stub_for_error(path, error, plugins=plugins, username=username)

    @classmethod
    def locked_stub_for_error(
        cls,
        path: Path | str,
        error: Exception,
        *,
        plugins: PluginRegistry = DEFAULT_PLUGIN_REGISTRY,
        username: str = DEFAULT_USERNAME,
    ) -> RehuDocument:
        """Build the empty, locked document that stands in for a file ``error`` prevented reading.

        Bound to ``path`` so the failure is repairable in place, but with **no data** -- so nothing is
        ever written back over the broken/absent original (:meth:`save` refuses,
        :data:`SAVE_BLOCKING_LOCK_KINDS`). A ``FileNotFoundError`` becomes :attr:`~LockReasonKind.MISSING`;
        anything else becomes :attr:`~LockReasonKind.INVALID_FILE`, carrying the error's own text (a JSON
        parser's line/column included). This is the single seam both :meth:`open_or_locked` (``.rehu``) and
        the legacy ``.tc`` open path route their failures through, so the missing-vs-unparseable line is
        drawn exactly once.

        :param path: the path the failed read was for; the stub is bound to it for a later revert.
        :param error: the exception that prevented reading (``OSError`` or :class:`RehuFormatError`).
        :param plugins: the plugins installed here; see :class:`RehuDocument`.
        :param username: the active identity; see :class:`RehuDocument`.
        :returns: an empty document bound to ``path``, locked with the matching reason.
        """
        kind = LockReasonKind.MISSING if isinstance(error, FileNotFoundError) else LockReasonKind.INVALID_FILE
        return cls({}, Path(path), plugins=plugins, username=username, load_failure=LockReason(kind, str(error)))

    def save(self, path: Path | str | None = None) -> None:
        """Atomically write the document back to disk as pretty-printed JSON, in canonical key order.

        Every rule about the file's *content* was already applied to ``__data`` at construction, and
        nothing here re-derives them.

        - The **upgrade-on-write** half of [[data-model#schema-version]] lands because
          `rehuco_core.migrations` upgraded the payload *and* restamped it on the way in, so the new
          layout and its version reach disk together. A document loaded at a **newer** version keeps that
          version: migrations never lower a stamp, since such a file still carries fields from a schema
          this build has never seen ([[data-model#schema-version]]'s preserve-unknown-fields rule) and
          relabelling it would mislead the build that *can* read them.
        - The **active block plus every inactive block** ([[plugins#plugin-blocks]]) are written, with
          alias block keys already normalized to their main spelling (:meth:`__normalize`), because no
          accessor here ever prunes ``__data``.

        **Key order is imposed here, and only here** (:meth:`__ordered_for_file`). It cannot be
        maintained in ``__data`` -- every setter appends -- and it does not need to be: JSON objects are
        unordered, so order is purely how the file reads to a human, which makes it a property of the
        write rather than of the document. Doing it at the one boundary that produces a file is also what
        keeps two documents with the same fields byte-identical regardless of how each was built -- a
        converted `.tc` and a migrated v1 file otherwise serialize their common fields in completely
        different orders.

        :param path: destination; defaults to the path the document was loaded from.
        :raises ValueError: if no path is given and the document has no loaded path.
        :raises RehuFormatError: if a save-blocking lock is in force
            (:data:`SAVE_BLOCKING_LOCK_KINDS`) -- an ``INVALID_FIELD`` document (whose coerced defaults
            would overwrite the malformed-but-recoverable original) or an ``INVALID_FILE`` / ``MISSING``
            stub (whose empty payload would clobber the broken/absent file). Editing is disabled while a
            document is locked, so a save reaches here only by a path that bypassed that guard; refusing
            is the backstop the write-integrity rule requires ([[data-model#write-integrity]]).
        """
        blocking = next((reason for reason in self.lock_reasons if reason.kind in SAVE_BLOCKING_LOCK_KINDS), None)
        if blocking is not None:
            raise RehuFormatError(f"Refusing to save a locked document ({blocking.kind}): {blocking.message}.")
        target = Path(path) if path is not None else self.__path
        if target is None:
            raise ValueError("No path given and document was not loaded from a file.")
        text = json.dumps(self.__ordered_for_file(), indent=2, ensure_ascii=False) + "\n"
        atomic_write_text(target, text)
        self.__path = target
        # a file now exists, at whatever version was just written -- assigned only after the write, so a
        # failed save leaves the document still describing the file that is actually there
        self.__on_disk_format_version = self.format_version
        self.__on_disk_active_block_format_version = self.__coerced_active_block_version()

    def __ordered_for_file(self) -> dict[str, Any]:
        """Lay the document out in canonical key order, for :meth:`save` to write.

        ``format_version`` leads (it describes the file), then ``core``, then every other top-level key
        alphabetically -- the plugin blocks, plus any stray key carried verbatim, which sorts among them
        rather than needing a category of its own.

        Inside ``core``, :data:`CORE_LEADING_KEYS` lead and the rest sort. The **active** block is
        ordered the same way, led by its own ``format_version`` ([[plugins#plugin-blocks]]).

        **Inactive blocks are copied untouched.** They are payload this file is merely custodian of
        ([[plugins#plugin-blocks]]), and "carried verbatim" is worth honouring literally when the
        alternative buys nothing: reordering them would churn bytes this document has no business
        churning, to reorganize fields it does not understand.

        A malformed block (not an object) is passed through as-is rather than skipped -- it is still
        the file's content, and dropping it would be exactly the silent loss the round-trip rule forbids
        ([[data-model#schema-version]]).

        :returns: a fresh dict; ``__data`` is left alone, since its order is not meaningful.
        """
        # not a guarded read: `rehuco_core.migrations` stamps every payload it is handed, including an
        # empty one, so a constructed document always carries a version
        ordered: dict[str, Any] = {FORMAT_VERSION_KEY: self.__data[FORMAT_VERSION_KEY]}
        if CORE_BLOCK_KEY in self.__data:
            ordered[CORE_BLOCK_KEY] = self.__ordered_block(self.__data[CORE_BLOCK_KEY], CORE_LEADING_KEYS)
        active_key = self.active_block_key
        for key in sorted(key for key in self.__data if key not in RESERVED_KEYS):
            value = self.__data[key]
            ordered[key] = self.__ordered_block(value, (FORMAT_VERSION_KEY,)) if key == active_key else value
        return ordered

    @staticmethod
    def __ordered_block(block: Any, leading: Sequence[str]) -> Any:
        """Order one block's keys: ``leading`` first, in the given order, then the rest alphabetically.

        :param block: the block's value; returned untouched when it is not an object
            ([[data-model#write-integrity]]).
        :param leading: the keys to place first; those absent from ``block`` are skipped.
        :returns: the block with its keys ordered.
        """
        if not isinstance(block, dict):
            return block
        lead = [key for key in leading if key in block]
        return {key: block[key] for key in (*lead, *sorted(set(block) - set(lead)))}

    def reload(self) -> None:
        """Re-read this document from its own path, replacing all in-memory data in place.

        Picks up an out-of-band change ([[data-model#write-integrity]]) -- an edit made outside this
        app -- rather than just resetting to the last-loaded snapshot. Keeps this document's identity
        (the same backing :attr:`data` object a caller may already hold a reference to): the dict is
        cleared and refilled, not replaced.

        Always re-reads :attr:`path` as JSON, even when :attr:`legacy_tc` is set -- nothing calls
        ``reload()`` on a ``.tc``-backed document yet ([[acquisition-tooling#tc-to-rehu]]'s Phase 1 is
        exercised directly, not through the app's real open/revert path), so re-parsing a `.tc` path as
        JSON here would lock the document rather than convert it; that follow-up lands with Phase 2's
        open-path wiring.

        **Never raises on an unreadable file** -- that is what makes revert the fix-retry loop
        ([[data-model#write-integrity]]). The re-read goes through :meth:`open_or_locked`, so a file that
        has since gone missing or become unparseable leaves this document **empty and locked** with a
        refreshed reason, and a re-read that now succeeds refills the data and **drops** the lock. Only a
        genuinely path-less document (never loaded or saved) still raises, since there is nothing to
        re-read.

        :raises ValueError: if this document has no path (never loaded from or saved to a file).
        """
        if self.__path is None:
            raise ValueError("no path to reload from -- document was not loaded from a file")
        fresh = RehuDocument.open_or_locked(self.__path, plugins=self.__plugins, username=self.__username)
        self.__data.clear()
        self.__data.update(fresh.data)
        # adopt what the freshly-read file says its version is: a reload is how an out-of-band change is
        # picked up, and that change may have been another build rewriting the file at a different version
        self.__on_disk_format_version = fresh.on_disk_format_version
        self.__on_disk_active_block_format_version = fresh.on_disk_active_block_format_version
        # adopt the fresh read's load-failure verdict: None when it parsed (dropping any prior lock), or a
        # refreshed MISSING/INVALID_FILE reason when it still cannot be read. Read off the fresh document's
        # public surface -- a stub's lock_reasons is exactly its single load-failure reason (lock_reasons)
        self.__load_failure = fresh.lock_reasons[0] if fresh.load_failed else None

    @property
    def data(self) -> dict[str, Any]:
        """The backing JSON object (the source of truth, including unknown keys)."""
        return self.__data

    @property
    def path(self) -> Path | None:
        """The file this document was loaded from or last saved to, if any."""
        return self.__path

    @property
    def username(self) -> str:
        """The active identity whose per-user state this document reads and writes
        ([[field-schema#per-user-shared]]); :data:`~rehuco_core.plugins.DEFAULT_USERNAME` unless a caller
        set one. Fixed for the document's life -- a per-user accessor is never told whose data it wants,
        and the v0->v1 block migration filed under exactly this name at construction."""
        return self.__username

    @property
    def legacy_tc(self) -> bool:
        """Whether this document was mapped from a legacy ``.tc`` file rather than loaded from a
        genuine ``.rehu`` ([[acquisition-tooling#tc-to-rehu]]).

        Set only by :func:`rehuco_core.tc_document.load_tc`. Locks the document independently of
        :attr:`format_version`, and *must*: the mapping emits the **current** layout, stamp included
        ([[acquisition-tooling#tc-to-rehu]]), so a ``.tc``-derived document is never a version this build
        would refuse -- the newer-format-version lock rule could not catch it under any stamp. This flag
        is the document's own reason to lock, surfaced through :attr:`lock_reasons`: what makes it
        read-only is that no ``.rehu`` exists for it yet, which is a fact about the *file*, not about
        any schema version."""
        return self.__legacy_tc

    @property
    def load_failed(self) -> bool:
        """Whether this document is an **empty stub** standing in for a file that could not be read at all
        ([[data-model#write-integrity]]) -- missing (:attr:`~LockReasonKind.MISSING`) or unparseable
        (:attr:`~LockReasonKind.INVALID_FILE`), as opposed to a genuinely-loaded document that merely
        locked (a newer format, a legacy ``.tc``, a present-but-uncoercible field).

        The load-vs-lock distinction a caller needs when a lock alone is too coarse: whether anything was
        actually read. "Don't record a file you couldn't open into recent-files", for one, keys off this
        rather than off :attr:`lock_reasons` being non-empty (a real newer-format file is locked too).
        Tracks :meth:`reload`, so a later re-read that succeeds clears it."""
        return self.__load_failure is not None

    @property
    def lock_reasons(self) -> list[LockReason]:
        """Every named cause this document is read-only ([[data-model#write-integrity]]); empty when it is
        freely editable. ``RehuDocumentModel.locked`` is derived from whether this is non-empty.

        A **load failure** (:attr:`~LockReasonKind.INVALID_FILE` / :attr:`~LockReasonKind.MISSING`) is the
        *sole* reason when present: the document is an empty stub standing in for a file that could not be
        read at all (:meth:`open_or_locked`), so no in-memory field could contribute a further cause.

        Otherwise the causes accumulate from the genuinely-parsed payload, and a document can carry more
        than one at once:

        - :attr:`~LockReasonKind.LEGACY_TC` -- a ``.tc`` mapping with no ``.rehu`` yet (:attr:`legacy_tc`).
        - :attr:`~LockReasonKind.NEWER_FORMAT` -- :attr:`format_version` above what this build understands
          ([[data-model#schema-version]]). The stamp itself is never *malformed*-locked: repairing a
          missing/bad stamp is a specified deduction, not a default masking data, so it does not appear as
          an ``INVALID_FIELD`` here.
        - :attr:`~LockReasonKind.NEWER_BLOCK_FORMAT` -- the **active** block's own ``format_version``
          above what its plugin understands ([[plugins#plugin-blocks]]); the same fail-safe as
          ``NEWER_FORMAT``, scoped to one block.
        - :attr:`~LockReasonKind.INVALID_FIELD` -- one per owned field that is **present but fails
          coercion** (:meth:`__invalid_field_reasons`), so an edit can never save the coerced default over
          the malformed-but-recoverable original.

        Recomputed on every read from the current payload, so :meth:`reload` (hence revert) picks up a
        hand-fix without any cached-reason bookkeeping.

        :returns: the lock reasons, or an empty list when the document is editable.
        """
        if self.__load_failure is not None:
            return [self.__load_failure]
        reasons: list[LockReason] = []
        if self.__legacy_tc:
            reasons.append(
                LockReason(
                    LockReasonKind.LEGACY_TC,
                    "a legacy .tc file with no .rehu on disk yet -- convert it to edit",
                )
            )
        if self.format_version > CURRENT_FORMAT_VERSION:
            reasons.append(
                LockReason(
                    LockReasonKind.NEWER_FORMAT,
                    f"format_version {self.format_version} is newer than this build understands "
                    f"({CURRENT_FORMAT_VERSION}).",
                )
            )
        reasons.extend(self.__newer_block_format_reasons())
        reasons.extend(self.__invalid_field_reasons())
        return reasons

    def __newer_block_format_reasons(self) -> list[LockReason]:
        """The :attr:`~LockReasonKind.NEWER_BLOCK_FORMAT` reason when the **active** block's own
        ``format_version`` is newer than its plugin understands ([[plugins#plugin-blocks]], the
        per-block refinement of :attr:`lock_reasons`'s ``NEWER_FORMAT`` check).

        Only checked when a plugin is installed for the active key -- an uninstalled type's block has
        no ``current_block_version`` to compare against, and is handled by the fallback-editor path
        instead ([[plugins#fallback-editor]]). :meth:`__migrate_active_block` never restamps such a
        block, so the version reported here is whatever the block actually carries.

        :returns: a single-element list naming the block and its versions, or empty when it is at or
            below what the plugin understands, or no plugin is installed for the active key.
        """
        if self.__plugins.resolve(self.active_block_key) is None:
            return []
        head = current_block_version(self.active_block_key)
        block_version = self.__coerced_active_block_version() or 0
        if block_version <= head:
            return []
        return [
            LockReason(
                LockReasonKind.NEWER_BLOCK_FORMAT,
                f"The {self.active_block_key!r} block's format_version {block_version} is newer than "
                f"the installed plugin understands ({head}).",
            )
        ]

    def __invalid_field_reasons(self) -> list[LockReason]:
        """The :attr:`~LockReasonKind.INVALID_FIELD` reasons for owned fields present-but-uncoercible
        ([[data-model#write-integrity]]).

        An owned field that is merely **absent** reads as a clean default and is fine to save. One that is
        **present** but whose stored value the getter has to coerce lossily is not: writing the coerced
        default back would quietly replace a malformed value the user may yet recover by hand. Each such
        field contributes one reason naming the key.

        Only ``authors`` is checked today ([[field-schema#authors]], the seam #92 set up): its getter
        skips an entry that is neither a name string nor a ``{name, url}`` record, and a non-list value
        entirely, so "present but not skip-clean" is exactly the present-but-uncoercible condition. Other
        owned fields join here as their own lossy-coercion cases are specified; the ``format_version``
        stamp deliberately never does (see :attr:`lock_reasons`).

        :returns: the invalid-field reasons, in a stable order.
        """
        reasons: list[LockReason] = []
        core = self.core
        if "authors" in core:
            value = core["authors"]
            clean = isinstance(value, list) and all(
                isinstance(entry, str) or self.__is_author_record(entry) for entry in value
            )
            if not clean:
                reasons.append(LockReason(LockReasonKind.INVALID_FIELD, INVALID_AUTHORS_MESSAGE))
        return reasons

    @property
    def core(self) -> dict[str, Any]:
        """The **core block**'s fields -- the common core every type shares
        ([[field-schema#resource-types]], [[data-model#rehu-format]]); an empty dict when the block is
        absent (a brand-new document) or malformed (not an object, [[data-model#write-integrity]]).

        Read-only in the same sense every accessor here is: the typed properties below are the supported
        way to edit a common field, and they create the block on demand. Exposed because a plugin's core
        layer needs to *read* the common fields ([[plugins#core-vs-plugin]]) without going through the
        agent's view-model."""
        block = self.__data.get(CORE_BLOCK_KEY)
        return block if isinstance(block, dict) else {}

    def __core_or_create(self) -> dict[str, Any]:
        """Return the mutable core block, installing a fresh one when absent or malformed.

        :returns: the block dict, attached by reference to ``data`` so mutating it in place is reflected
            on the next :meth:`save`.
        """
        block = self.__data.get(CORE_BLOCK_KEY)
        if not isinstance(block, dict):
            block = {}
            self.__data[CORE_BLOCK_KEY] = block
        return block

    @property
    def format_version(self) -> int:
        """The layout version this document is at ([[data-model#schema-version]]).

        Never below :data:`CURRENT_FORMAT_VERSION` in practice, and never ``0``: `rehuco_core.migrations`
        upgrades and restamps the payload at construction, so by the time anything can read this the
        stamp and the layout agree. A **higher** value is the case that matters -- a file written by a
        newer build, which ``RehuDocumentModel.locked`` compares against
        :data:`CURRENT_FORMAT_VERSION` to open the document read-only.

        Still coerces defensively (``0`` for an absent or malformed key): a `.rehu` is untrusted
        input ([[data-model#write-integrity]]), and this must not raise on one just because the migrator
        is expected to have gotten there first."""
        return self.__coerced_version(self.__data)

    @property
    def on_disk_format_version(self) -> int | None:
        """The format version of the **file**, as it currently sits on disk
        ([[data-model#schema-version]]); ``None`` when there is no file yet.

        A different question from :attr:`format_version`, which is what the in-memory payload *is* --
        always current, because loading upgrades it. This one is what the *file* is, so the two differ
        exactly when a document was read from an older `.rehu` and not yet saved. That gap is the thing
        worth acting on: it is what makes an upgrade **possible and pending** (#89).

        ``None`` is not the same as ``0``, and the distinction is load-bearing: ``0`` means "a file
        exists and is unstamped" (so it *is* older, and upgradeable), while ``None`` means **no file
        exists to upgrade**. A brand-new document reads ``None`` even once it has been handed a path,
        since a path is a destination, not a file. So is a ``.tc``-derived document
        ([[acquisition-tooling#tc-to-rehu]]): its path is a `.tc`, and no `.rehu` lives there until it is
        converted.

        Set only where a `.rehu` is genuinely read or written -- :meth:`load`, :meth:`reload`,
        :meth:`save` -- so ``on_disk_format_version < CURRENT_FORMAT_VERSION`` is never true of a file
        that isn't there."""
        return self.__on_disk_format_version

    @property
    def on_disk_active_block_format_version(self) -> int | None:
        """The active block's own ``format_version``, as it currently sits on disk
        ([[plugins#plugin-blocks]]); the per-block sibling of :attr:`on_disk_format_version`, same
        ``None``-vs-``0`` distinction and the same set of seams (:meth:`load`, :meth:`reload`,
        :meth:`save`).

        ``None`` when there is no on-disk block to compare against: no file yet, or the active type
        names no top-level object on it. A brand-new or ``.tc``-derived document also reads ``None``,
        for the same reason :attr:`on_disk_format_version` does."""
        return self.__on_disk_active_block_format_version

    @property
    def active_block_upgrade_pending(self) -> bool:
        """Whether the active block, as it currently sits on disk, predates what its plugin
        understands ([[plugins#plugin-blocks]]) -- the per-block sibling of comparing
        :attr:`on_disk_format_version` against :data:`~rehuco_core.migrations.CURRENT_FORMAT_VERSION`,
        so a caller offering a single, layer-agnostic "Upgrade" action (#89) can ask one question
        instead of two.

        ``False`` when there is nothing to compare -- no on-disk block (:attr:`on_disk_active_block_format_version`
        is ``None``), or no plugin installed for the active key to say what "current" even means."""
        on_disk = self.__on_disk_active_block_format_version
        if on_disk is None or self.__plugins.resolve(self.active_block_key) is None:
            return False
        return on_disk < current_block_version(self.active_block_key)

    @staticmethod
    def __coerced_version(data: dict[str, Any]) -> int:
        """Read a payload's ``format_version`` as a plain number ([[data-model#write-integrity]]).

        Defers the "is this stamp usable" judgement to `rehuco_core.migrations`, so this class and the
        migrator can never disagree about what a stamp says. The two differ only in what they do when it
        says nothing: this reports **v0**, while the migrator goes on to read the payload's shape.

        :param data: the parsed JSON object.
        :returns: the stamped version, or ``0`` when absent or malformed.
        """
        stamp = stamped_version(data)
        return stamp if stamp is not None else 0

    @staticmethod
    def __raw_active_block_version(data: dict[str, Any]) -> int | None:
        """The active block's own stamp, read straight off ``data`` as parsed -- the same moment
        :meth:`load` reads the file-wide stamp, before construction migrates anything
        ([[plugins#plugin-blocks]]).

        Resolves the active key from the raw payload's own shape (``core.type`` if present, else a
        top-level ``type`` for a not-yet-migrated v1 file) rather than through :attr:`active_block_key`,
        which only exists once a document -- and its normalization -- does.

        :param data: the parsed JSON object, not yet touched by ``__init__``.
        :returns: the raw block's stamp (``0`` if absent or malformed), or ``None`` when there is no
            active block at all yet -- the type is unset, or names no top-level object.
        """
        core = data.get(CORE_BLOCK_KEY)
        resource_type = core.get("type") if isinstance(core, dict) else data.get("type")
        if not isinstance(resource_type, str) or not resource_type:
            return None
        block = data.get(resource_type)
        if not isinstance(block, dict):
            return None
        stamp = stamped_version(block)
        return stamp if stamp is not None else 0

    @property
    def type(self) -> str:
        """The resource type selector (``Tutorial`` / ``ReferenceImages`` / ``Collection``)."""
        return str(self.core.get("type", ""))

    @property
    def id(self) -> str:
        """The resource UUID ([[data-model#stable-identity]]); empty string if absent (e.g. a not-yet-imported file)."""
        return str(self.core.get("id", ""))

    @property
    def sources(self) -> list[dict[str, Any]]:
        """The ``sources`` list ([[field-schema#sources]]); empty when the key is absent."""
        sources = self.core.get("sources", [])
        return sources if isinstance(sources, list) else []

    @property
    def primary_source(self) -> dict[str, Any] | None:
        """The canonical source, resolved permissively per [[field-schema#sources]].

        The first entry flagged ``primary: true`` wins; if none is flagged, the first entry
        is treated as primary; if there are no sources, ``None``. Non-object entries in a
        malformed ``sources`` are skipped in both passes rather than crashing the accessors
        ([[data-model#write-integrity]]).

        :returns: the primary source object, or ``None`` when there are no sources.
        """
        sources = self.sources
        for source in sources:
            if isinstance(source, dict) and source.get(PRIMARY_KEY) is True:
                return source
        return next((source for source in sources if isinstance(source, dict)), None)

    @property
    def title(self) -> str:
        """The display title -- the primary source's ``title`` ([[field-schema#sources]]); empty if none."""
        primary = self.primary_source
        return str(primary.get("title", "")) if primary else ""

    @title.setter
    def title(self, value: str) -> None:
        self.__primary_source_or_create()["title"] = value

    @property
    def publisher(self) -> str:
        """The primary source's ``publisher`` ([[field-schema#sources]]); empty if none."""
        primary = self.primary_source
        return str(primary.get("publisher", "")) if primary else ""

    @publisher.setter
    def publisher(self, value: str) -> None:
        self.__primary_source_or_create()["publisher"] = value

    @property
    def url(self) -> str:
        """The primary source's ``url`` ([[field-schema#sources]]); empty if none."""
        primary = self.primary_source
        return str(primary.get("url", "")) if primary else ""

    @url.setter
    def url(self, value: str) -> None:
        self.__primary_source_or_create()["url"] = value

    def __primary_source_or_create(self) -> dict[str, Any]:
        """Return the mutable primary source, appending a new flagged entry to ``sources`` if none exists.

        :returns: the primary source dict ([[field-schema#sources]]), attached by reference to ``sources`` so
            mutating it in place is reflected on the next :meth:`save`.
        """
        primary = self.primary_source
        if primary is None:
            primary = {PRIMARY_KEY: True}
            self.__core_or_create().setdefault("sources", []).append(primary)
        return primary

    @property
    def active_block_key(self) -> str:
        """The **active** plugin block's key -- the one this document's ``type`` names
        ([[plugins#plugin-blocks]]); empty when the type is.

        The type's value *is* the key, which is why this is a plain read rather than a lookup: alias
        spellings were normalized away at construction (:meth:`__normalize`), so by the time anything
        asks, ``type`` and its block are spelled the same. A type no installed plugin claims keeps its
        own spelling and therefore still names its block -- which is what keeps active/inactive independent
        of what happens to be installed here.
        """
        return self.type

    @property
    def active_block(self) -> dict[str, Any]:
        """The active plugin block's own fields ([[plugins#plugin-blocks]]); an empty dict when the block
        is absent or malformed (not an object)."""
        block = self.__data.get(self.active_block_key)
        return block if isinstance(block, dict) else {}

    def __coerced_active_block_version(self) -> int | None:
        """The active block's own ``format_version``, defensively coerced -- the block-scoped sibling
        of :meth:`__coerced_version` ([[plugins#plugin-blocks]]).

        :returns: the stamped version (``0`` if absent or malformed), or ``None`` when there is no
            active block at all -- the key is not present in :attr:`data`.
        """
        if self.active_block_key not in self.__data:
            return None
        stamp = stamped_version(self.active_block)
        return stamp if stamp is not None else 0

    def plugin_blocks(self) -> list[PluginBlock]:
        """Enumerate this document's plugin blocks, each classified active or inactive ([[plugins#plugin-blocks]]).

        A block is any top-level key outside :data:`~rehuco_core.plugins.RESERVED_KEYS` whose value is a JSON object --
        which is what tells a block apart from an ordinary unknown top-level key: a stray scalar or list
        is carried verbatim but is not a block. Because the common fields live in ``core`` rather than at
        the top level, no list of their names is consulted, and a common field this build has never heard
        of can never be mistaken for a block.

        Exactly one block is active: the one :attr:`active_block_key` names, **regardless of whether a
        matching plugin is installed**. Every other block is inactive even when its own plugin *is*
        installed -- a ``reference_images:`` block inside an ``audiopack``-typed file is inactive, and
        treated as unknown, because the file's type isn't reference-images. Installed-ness only decides
        whether the *active* block renders richly or falls back to the generic editor
        ([[plugins#fallback-editor]]); it never promotes an inactive block to active.

        :returns: the blocks, in document order.
        """
        active_key = self.active_block_key
        return [
            PluginBlock(key=key, fields=value, active=key == active_key)
            for key, value in self.__data.items()
            if key not in RESERVED_KEYS and isinstance(value, dict)
        ]

    def inactive_blocks(self) -> list[PluginBlock]:
        """This document's non-active plugin blocks ([[plugins#plugin-blocks]]).

        All of them are carried verbatim on :meth:`save` -- the carry-only half of the block persistence
        invariant, which is correct for a session with no type switching. Session claim-tracking and the
        drop-on-abandon rule are A4.2 ([[plugins#plugin-blocks]]).

        :returns: the inactive blocks, in document order.
        """
        return [block for block in self.plugin_blocks() if not block.active]

    def active_field(self, key: str, default: Any = None) -> Any:
        """Read a value from the active plugin block ([[plugins#plugin-blocks]]).

        Generic value access only -- **not** the block save invariant (A4.2, [[plugins#plugin-blocks]]).

        :param key: the key to read inside the block.
        :param default: value to return when the block or key is absent.
        :returns: the stored value, or ``default`` when absent.
        """
        return self.active_block.get(key, default)

    def set_active_field(self, key: str, value: Any) -> None:
        """Write a value into the active plugin block ([[plugins#plugin-blocks]]), creating the block if it
        is absent or malformed.

        Generic value access only -- **not** the block save invariant (A4.2, [[plugins#plugin-blocks]]).

        :param key: the key to write inside the block.
        :param value: the value to store.
        """
        self.__active_block_or_create()[key] = value

    def remove_active_field(self, key: str) -> bool:
        """Delete a key from the active plugin block ([[plugins#plugin-blocks]]).

        Generic value access only -- **not** the block save invariant (A4.2, [[plugins#plugin-blocks]]).
        Used to drop an unrecognized field the user explicitly discards via the fallback editor's remove
        action ([[plugins#fallback-editor]], A2.8/#28); an unremoved unknown field is otherwise carried
        verbatim on round-trip.

        :param key: the key to delete inside the block.
        :returns: ``True`` if the key was present and removed, ``False`` if the block or key was absent.
        """
        block = self.__data.get(self.active_block_key)
        if isinstance(block, dict) and key in block:
            del block[key]
            return True
        return False

    def __active_block_or_create(self) -> dict[str, Any]:
        """Return the mutable active block, installing a fresh one when absent or malformed.

        :returns: the block dict, attached by reference to ``data`` so mutating it in place is reflected
            on the next :meth:`save`.
        """
        block = self.__data.get(self.active_block_key)
        if not isinstance(block, dict):
            block = {}
            self.__data[self.active_block_key] = block
        return block

    def active_user_field(self, key: str, default: Any = None) -> Any:
        """Read a **per-user** value from the active block's ``users`` map, for this document's own
        username ([[field-schema#per-user-shared]]).

        The per-user sibling of :meth:`active_field`: where that reads a shared field sitting inline in the
        block, this reaches into ``active_block["users"][<username>]`` (block layout v1). Reading one
        user's value never sees another's, and an absent block, an absent ``users`` map, an absent user, or
        an absent key all read as ``default`` -- so an uninstalled or blockless type answers sanely rather
        than crashing, the same defensive read every accessor here gives ([[data-model#write-integrity]]).

        :param key: the per-user key to read inside this user's sub-map.
        :param default: value to return when the block, the ``users`` map, this user, or the key is absent.
        :returns: the stored value, or ``default`` when absent.
        """
        users = self.active_block.get(USERS_KEY)
        if not isinstance(users, dict):
            return default
        user = users.get(self.__username)
        return user.get(key, default) if isinstance(user, dict) else default

    def set_active_user_field(self, key: str, value: Any) -> None:
        """Write a **per-user** value into the active block's ``users`` map, under this document's own
        username ([[field-schema#per-user-shared]]), creating the block, the ``users`` map, and this user's
        sub-map on demand.

        The per-user sibling of :meth:`set_active_field`. A ``users`` map or a per-user sub-map that is
        present but malformed (not an object) is replaced rather than crashed on, the same way
        :meth:`set_active_field` replaces a malformed block ([[data-model#write-integrity]]).

        :param key: the per-user key to write inside this user's sub-map.
        :param value: the value to store.
        """
        self.__active_user_or_create()[key] = value

    def __active_user_or_create(self) -> dict[str, Any]:
        """Return this user's mutable per-user sub-map, installing the ``users`` map and the sub-map when
        either is absent or malformed.

        :returns: the per-user dict for this document's username, attached by reference into ``data`` so
            mutating it in place is reflected on the next :meth:`save`.
        """
        block = self.__active_block_or_create()
        users = block.get(USERS_KEY)
        if not isinstance(users, dict):
            users = {}
            block[USERS_KEY] = users
        user = users.get(self.__username)
        if not isinstance(user, dict):
            user = {}
            users[self.__username] = user
        return user

    def __normalize(self) -> None:
        """Rewrite alias spellings to their plugin's main key, in place, at construction
        ([[plugins#plugin-blocks]]).

        Prior art from TutCatalog5 (`base_item.py`'s ``KEY``): a plugin *declares* its keys rather than
        having one derived from its name, the first is the main key, and storing rewrites an alias to it
        -- a rename/migration path for free, and the only way to express a key like ``daz3d`` that is the
        snake_case of no type name at all.

        Doing this on the way **in** rather than on the way out is what buys the rest of this class its
        simplicity: from here on the document is canonical, so :attr:`active_block_key` is a read and
        :meth:`plugin_blocks` classifies by plain key identity, with the registry out of the picture. The
        on-disk rewrite still happens -- ``__data`` is the source of truth :meth:`save` dumps.

        A block whose main key is **already taken** keeps its alias spelling rather than clobbering the
        occupant (or another alias racing it for the same key). It is then simply a different key, so it
        classifies inactive and is carried verbatim -- foreign payload, which is what it looks like.
        """
        core = self.__data.get(CORE_BLOCK_KEY)
        if isinstance(core, dict):
            resource_type = core.get("type")
            if isinstance(resource_type, str) and resource_type:
                core["type"] = self.__plugins.main_key(resource_type)
        taken = set(self.__data)
        renames: dict[str, str] = {}
        for key, value in self.__data.items():
            if key in RESERVED_KEYS or not isinstance(value, dict):
                continue
            main_key = self.__plugins.main_key(key)
            if main_key == key:
                continue
            if main_key in taken:
                LOG.warning("Not normalizing block %r to %r: that key is already present", key, main_key)
                continue
            renames[key] = main_key
            taken.add(main_key)
        if not renames:
            return
        # rebuild rather than pop/insert, so a renamed block keeps its position instead of jumping to
        # the end of the file on the next save
        normalized = {renames.get(key, key): value for key, value in self.__data.items()}
        self.__data.clear()
        self.__data.update(normalized)

    def __migrate_active_block(self) -> None:
        """Bring the **active** block up to its plugin's ``current_block_version``, in place, at
        construction -- the per-block mirror of the file-wide upgrade-on-load step
        ([[plugins#plugin-blocks]], [[data-model#schema-version]]).

        Only the active block is ever touched: an inactive block has no standing to be restamped by a
        plugin that is not even reading it (:meth:`inactive_blocks`), and a type no installed plugin
        declares has no ``current_block_version`` to migrate toward -- both cases are simply skipped,
        leaving the block exactly as constructed.
        """
        if self.__plugins.resolve(self.active_block_key) is None:
            return
        block = self.__data.get(self.active_block_key)
        if isinstance(block, dict):
            migrate_block_data(block, self.active_block_key, self.__username)

    @property
    def authors(self) -> list[AuthorEntry]:
        """The shared ``authors`` list ([[field-schema#authors]]); empty when absent.

        Entries are tolerantly **string-or-record** ([[field-schema#authors]]): a plain name string
        passes through, and a ``{"name": <str>, "url"?: <str>}`` record is preserved so an
        author-page URL survives a read rather than being flattened. Anything else -- a number,
        ``None``, a list, a record without a string ``name`` -- is a malformed entry and is
        **skipped**, the same defensive coercion ``sources`` applies to a non-object entry
        ([[data-model#write-integrity]]): a getter must never crash on a value's type, and skipping
        is safer than inventing a name by stringifying it. This shapes *reading* only -- the backing
        list is untouched, so an unedited document round-trips byte-identical
        ([[data-model#write-integrity]]). A present ``authors`` the getter has to coerce this way is
        exactly what :attr:`lock_reasons` reports as an :attr:`~LockReasonKind.INVALID_FIELD`, so the
        coerced reading is safe to display but the document loads **locked** rather than letting an edit
        save the coerced list over the original.
        """
        authors = self.core.get("authors", [])
        if not isinstance(authors, list):
            return []
        return [entry for entry in authors if isinstance(entry, str) or self.__is_author_record(entry)]

    @authors.setter
    def authors(self, value: Sequence[AuthorEntry]) -> None:
        self.__core_or_create()["authors"] = [self.__canonical_author(entry) for entry in value]

    @staticmethod
    def __is_author_record(entry: Any) -> bool:
        """Whether ``entry`` is a valid author record: a dict with a string ``name`` ([[field-schema#authors]])."""
        return isinstance(entry, dict) and isinstance(entry.get("name"), str)

    @staticmethod
    def __canonical_author(entry: AuthorEntry) -> AuthorEntry:
        """Reduce one entry to its canonical minimal form for storage ([[field-schema#authors]]).

        A record is written only when it carries a URL; a record reduced to a bare name -- no
        ``url``, or a non-string/empty one -- is written back as a plain string, so "are all entries
        simple?" stays a trivial test (:func:`authors_comma_editable`). A plain string, and anything
        this build does not recognize as an author record, pass through untouched: the setter is a
        lossless write boundary, while the *reading* :attr:`authors` getter is where a malformed
        entry is skipped.
        """
        if isinstance(entry, dict) and isinstance(entry.get("name"), str):
            url = entry.get("url")
            return {"name": entry["name"], "url": url} if isinstance(url, str) and url else entry["name"]
        return entry

    @property
    def released(self) -> str:
        """The partial-precision content release date ([[field-schema#field-mapping]]), as stored; empty if absent."""
        return str(self.core.get("released", ""))

    @released.setter
    def released(self, value: str) -> None:
        self.__core_or_create()["released"] = value

    @property
    def created(self) -> str:
        """When this record was first written ([[field-schema#record-timestamps]]), as stored; empty if absent."""
        return str(self.core.get("created", ""))

    @created.setter
    def created(self, value: str) -> None:
        self.__core_or_create()["created"] = value

    @property
    def updated(self) -> str:
        """When this record was last edited ([[field-schema#record-timestamps]]), as stored; empty if absent."""
        return str(self.core.get("updated", ""))

    @updated.setter
    def updated(self, value: str) -> None:
        self.__core_or_create()["updated"] = value

    @property
    def original_size(self) -> int:
        """Measured total size, in bytes, of the complete download ([[field-schema#duration-size]]);
        ``0`` when absent (e.g. a Collection, which has none of its own) or malformed
        ([[data-model#write-integrity]])."""
        value = self.core.get("original_size", 0)
        return value if isinstance(value, int) and not isinstance(value, bool) else 0

    @original_size.setter
    def original_size(self, value: int) -> None:
        self.__core_or_create()["original_size"] = value

    @property
    def current_size(self) -> int:
        """Disk space, in bytes, currently used by this copy ([[field-schema#duration-size]]); ``0``
        when absent or malformed ([[data-model#write-integrity]])."""
        value = self.core.get("current_size", 0)
        return value if isinstance(value, int) and not isinstance(value, bool) else 0

    @current_size.setter
    def current_size(self, value: int) -> None:
        self.__core_or_create()["current_size"] = value

    @property
    def advertised_tags(self) -> list[str]:
        """The web-scraped ``advertised_tags`` list ([[field-schema#field-mapping]]); empty when absent."""
        tags = self.core.get("advertised_tags", [])
        return [str(t) for t in tags] if isinstance(tags, list) else []

    @advertised_tags.setter
    def advertised_tags(self, value: list[str]) -> None:
        self.__core_or_create()["advertised_tags"] = list(value)

    @property
    def extra_tags(self) -> list[str]:
        """The personal ``extra_tags`` list ([[field-schema#field-mapping]]); empty when absent."""
        tags = self.core.get("extra_tags", [])
        return [str(t) for t in tags] if isinstance(tags, list) else []

    @extra_tags.setter
    def extra_tags(self, value: list[str]) -> None:
        self.__core_or_create()["extra_tags"] = list(value)

    @property
    def description(self) -> str:
        """The Markdown ``description`` ([[field-schema#field-types]]), as stored; empty when absent.

        Line endings are normalized to LF regardless of the source platform's convention (CRLF,
        bare CR, or already LF) -- editing should read the same no matter which platform wrote the
        file. Read-time only, like every other coercion here: this does not mutate the backing
        dict, so a file whose description is never actually edited keeps its original on-disk line
        endings until something calls the setter.
        """
        value = str(self.core.get("description", ""))
        return value.replace("\r\n", "\n").replace("\r", "\n")

    @description.setter
    def description(self, value: str) -> None:
        self.__core_or_create()["description"] = value

    @property
    def hidden_images(self) -> list[str]:
        """The screenshot filenames curated *out* of the lightbox ([[data-model#image-meanings]], #27).

        App-managed presentation metadata: the lightbox defaults to showing every ``<stem>NN`` sibling
        screenshot, so only the **hidden exceptions** are stored -- an empty/absent list means all are
        shown. Filenames (basenames) only, never paths. Empty when the key is absent or malformed
        ([[data-model#write-integrity]])."""
        names = self.core.get("hidden_images", [])
        return [str(name) for name in names] if isinstance(names, list) else []

    @hidden_images.setter
    def hidden_images(self, value: list[str]) -> None:
        self.__core_or_create()["hidden_images"] = list(value)


def author_name(entry: AuthorEntry) -> str:
    """The display name of one ``authors`` entry ([[field-schema#authors]]).

    A plain-string entry is its own name; a ``{"name", "url"}`` record reduces to its ``name``. This is
    the entry-shape knowledge in one place, for a consumer that wants names rather than the mixed
    entries -- e.g. building a rename candidate. Assumes an entry the :attr:`RehuDocument.authors`
    getter would yield (a string, or a record with a string ``name``); a stray non-string ``name`` is
    stringified defensively rather than raising.

    :param entry: one author entry, string or record.
    :returns: the plain author name.
    """
    return entry if isinstance(entry, str) else str(entry.get("name", ""))


def authors_comma_editable(authors: Sequence[AuthorEntry]) -> bool:
    """Whether every ``authors`` entry survives a round-trip through the comma-separated line editor.

    The single-line comma editor is lossless **iff** every entry is a plain string containing no
    comma ([[field-schema#authors]]): a record entry (an author-page URL) has no comma-line
    representation, and a name containing a comma (``Foo Bar, Jr.``) would split into two on
    re-parse -- expressible only as a record ([[field-schema#authors]]). An empty list is trivially
    editable. This is the predicate the deferred record-list editor and the comma editor's own
    disable guard gate on (#95, #97); a pure function of the entries, so a widget can ask it directly
    without reaching for a document.

    :param authors: the entries, as :attr:`RehuDocument.authors` yields them.
    :returns: whether the comma line editor can represent every entry without loss.
    """
    return all(isinstance(entry, str) and "," not in entry for entry in authors)
