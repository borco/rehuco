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

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from borco_core import atomic_write_text

from rehuco_core.migrations import FORMAT_VERSION_KEY, migrate_rehu_data, stamped_version
from rehuco_core.plugins import CORE_BLOCK_KEY, DEFAULT_PLUGIN_REGISTRY, PluginRegistry

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
merely sorts with the rest, it is never misplaced. Unlike a *recognition* list
(:data:`~rehuco_core.migrations.V1_COMMON_FIELD_KEYS`), being incomplete here costs nothing."""


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
    """Raised when a ``.rehu`` payload is not a JSON object."""


class RehuDocument:  # pylint: disable=too-many-public-methods
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
    :param on_disk_format_version: the version of the file this payload was read from; see
        :attr:`on_disk_format_version`. Set only by :meth:`load`, which is the only caller that knows a
        file was involved -- constructing a document does not make one exist. Defaults to ``None``: no
        file.
    """

    __RESERVED_KEYS: Final = frozenset({FORMAT_VERSION_KEY, CORE_BLOCK_KEY})
    """The only top-level keys that are not plugin blocks ([[data-model#rehu-format]]): the file's own
    version stamp, and the common core's block. Everything else at the top level is a block, which is
    the entire recognition rule -- there is no list of common field names to keep in step."""

    def __init__(
        self,
        data: dict[str, Any],
        path: Path | None = None,
        *,
        legacy_tc: bool = False,
        plugins: PluginRegistry = DEFAULT_PLUGIN_REGISTRY,
        on_disk_format_version: int | None = None,
    ) -> None:
        # Final forbids rebinding __data to a different dict, not mutating this one -- every
        # setter edits __data (or a dict nested inside it) in place, so it is always current
        # and save() never needs a separate sync step. __path has no such guarantee: save()
        # legitimately rebinds it when called with an explicit path.
        self.__data: Final = data
        self.__path = path
        self.__legacy_tc: Final = legacy_tc
        self.__plugins: Final = plugins
        self.__on_disk_format_version = on_disk_format_version
        migrate_rehu_data(data)
        self.__normalize()

    @classmethod
    def load(cls, path: Path | str, *, plugins: PluginRegistry = DEFAULT_PLUGIN_REGISTRY) -> RehuDocument:
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
        :returns: a document backed by the parsed JSON object.
        :raises RehuFormatError: if the file cannot be parsed, or its top-level JSON value is not an object.
        """
        path = Path(path)
        try:
            data: object = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, RecursionError) as exc:
            raise RehuFormatError(f"{path}: invalid JSON — {exc}") from exc
        if not isinstance(data, dict):
            raise RehuFormatError(f"{path}: expected a JSON object at the top level")
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
            on_disk_format_version=cls.__coerced_version(data),
        )

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
        """
        target = Path(path) if path is not None else self.__path
        if target is None:
            raise ValueError("no path given and document was not loaded from a file")
        text = json.dumps(self.__ordered_for_file(), indent=2, ensure_ascii=False) + "\n"
        atomic_write_text(target, text)
        self.__path = target
        # a file now exists, at whatever version was just written -- assigned only after the write, so a
        # failed save leaves the document still describing the file that is actually there
        self.__on_disk_format_version = self.format_version

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
        for key in sorted(key for key in self.__data if key not in self.__RESERVED_KEYS):
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
        JSON here would raise; that follow-up lands with Phase 2's open-path wiring.

        :raises ValueError: if this document has no path (never loaded from or saved to a file).
        :raises RehuFormatError: if the file's top-level JSON value is not an object.
        """
        if self.__path is None:
            raise ValueError("no path to reload from -- document was not loaded from a file")
        fresh = RehuDocument.load(self.__path, plugins=self.__plugins)
        self.__data.clear()
        self.__data.update(fresh.data)
        # adopt what the freshly-read file says its version is: a reload is how an out-of-band change is
        # picked up, and that change may have been another build rewriting the file at a different version
        self.__on_disk_format_version = fresh.on_disk_format_version

    @property
    def data(self) -> dict[str, Any]:
        """The backing JSON object (the source of truth, including unknown keys)."""
        return self.__data

    @property
    def path(self) -> Path | None:
        """The file this document was loaded from or last saved to, if any."""
        return self.__path

    @property
    def legacy_tc(self) -> bool:
        """Whether this document was mapped from a legacy ``.tc`` file rather than loaded from a
        genuine ``.rehu`` ([[acquisition-tooling#tc-to-rehu]]).

        Set only by :func:`rehuco_core.tc_document.load_tc`. Locks the document independently of
        :attr:`format_version`, and *must*: the mapping emits the **current** layout, stamp included
        ([[acquisition-tooling#tc-to-rehu]]), so a ``.tc``-derived document is never a version this build
        would refuse -- the newer-format-version lock rule could not catch it under any stamp. This flag
        is the document's own reason to lock, checked by ``RehuDocumentModel.locked``: what makes it
        read-only is that no ``.rehu`` exists for it yet, which is a fact about the *file*, not about
        any schema version."""
        return self.__legacy_tc

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

    def plugin_blocks(self) -> list[PluginBlock]:
        """Enumerate this document's plugin blocks, each classified active or inactive ([[plugins#plugin-blocks]]).

        A block is any top-level key outside :attr:`__RESERVED_KEYS` whose value is a JSON object --
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
            if key not in self.__RESERVED_KEYS and isinstance(value, dict)
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
            if key in self.__RESERVED_KEYS or not isinstance(value, dict):
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
        ([[data-model#write-integrity]]); #93 later turns a skipped-because-malformed entry into a
        read-only lock reason.
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
