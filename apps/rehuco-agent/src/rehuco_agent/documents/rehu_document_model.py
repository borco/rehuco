"""Reactive view-model wrapping a `RehuDocument` for the viewer/editor surfaces ([[plugins#view-model]])."""

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

from borco_pyside.core import SimpleProperty
from PySide6.QtCore import QObject, Signal
from rehuco_core import (
    CURRENT_FORMAT_VERSION,
    DEFAULT_CURRENT_USERNAME,
    FORMAT_VERSION_KEY,
    USERS_KEY,
    AuthorEntry,
    LockReason,
    RehuDocument,
    convert_tc,
)

from ..fields.field import Field, FieldBinding
from .image_scanner import ImageScanner, RehuScanner, TcScanner

LOG: Final = logging.getLogger(__name__)

INFO_REHU_FILENAME: Final = "info.rehu"
"""A directory-scoped resource's filename ([[data-model#resource-scoping]]); its label uses the parent
directory's name instead, since the literal filename is the same for every such resource."""

TYPE_FIELD_BOOL_NAMES: Final = ("complete", "online", "viewed", "todo", "keep", "favorite")
"""The type-field boolean flags ([[field-schema#boolean-flags]]); each name's default lives on its own
``SimpleProperty`` declaration below, read back generically via ``SimpleProperty.default_value``."""

TYPE_FIELD_INT_NAMES: Final = ("rating", "images_count", "original_duration", "current_duration", "advertised_duration")
"""The type-field integer fields ([[field-schema#field-types]]); ``rating`` may be negative, the
``*_duration`` fields are whole seconds ([[field-schema#ms-leak-history]]). Defaults live on each
``SimpleProperty`` declaration below, same as :data:`TYPE_FIELD_BOOL_NAMES`."""

TYPE_FIELD_STR_LIST_NAMES: Final = ("level",)
"""The type-field string-list fields ([[field-schema#field-types]]); ``level`` is multi-choice, not a
mutually-exclusive single value -- tc4 could tag more than one of beginner/intermediate/advanced/any
at once. Defaults live on each ``SimpleProperty`` declaration below, same as :data:`TYPE_FIELD_BOOL_NAMES`."""

USER_FIELD_NAMES: Final = frozenset(("rating", "viewed", "todo", "keep", "favorite"))
"""The subset of the groups above that is **per-user** ([[field-schema#per-user-shared]], #99): these
route through the document's per-user accessors (`RehuDocument.active_user_field` /
`~RehuDocument.set_active_user_field` -- nested under the active block's ``users`` map, block layout
v1) instead of the shared inline ones. Mirrors the core importer's per-user set
(``tc_document``'s user fields), minus ``learning_paths`` -- a record list the model doesn't expose
yet, not a scalar of these groups."""

KNOWN_TYPE_FIELD_NAMES: Final = frozenset(TYPE_FIELD_BOOL_NAMES + TYPE_FIELD_INT_NAMES + TYPE_FIELD_STR_LIST_NAMES)
"""Every plugin-block key the model reads as a known field ([[field-schema#resource-types]]); any other
key in the active block is an **unknown field** surfaced through the generic fallback
([[plugins#fallback-editor]], A2.8/#28)."""


class RehuDocumentModel(QObject):  # pylint: disable=too-many-instance-attributes
    """Reactive `QObject` over one `RehuDocument`, exposing common-core fields and a dirty flag
    ([[plugins#view-model]]).

    The viewer/editor surfaces bind to this instead of touching `RehuDocument` ([[data-model]]) directly, keeping
    the core non-GUI ([[plugins#core-vs-plugin]]). Setting ``title`` / ``publisher`` / ``url`` writes
    through to the document's **primary** source ([[field-schema#sources]]), marks the model dirty,
    and emits the field's ``<name>_changed`` signal -- which is what makes live "both" work: an edit
    in the editor updates the model, whose signal the viewer is bound to. ``sources`` is exposed as
    the list it is; the
    multi-source record-list editor is a later slice (A2.6/#26) that plugs into this seam. ``authors``
    / ``advertised_tags`` / ``extra_tags`` are common-core top-level lists, not source-scoped, so they
    write straight through to the document instead of through the primary source (A2.3/#23).
    :meth:`revert` is the write-through's mirror image: it re-reads the document from disk and
    reseeds every field, guarded so reseeding is never itself treated as an edit (#41).

    :param document: the document to wrap.
    :param parent: optional Qt parent.
    """

    unknown_fields_changed = Signal()
    """Fires when the set of unrecognized active-block fields changes -- i.e. one is dropped via
    :meth:`remove_unknown_field` ([[plugins#fallback-editor]], A2.8/#28)."""

    active_block_changed = Signal()
    """Fires when the whole field composition must be re-resolved from scratch: the outgoing block's
    editors go away, the incoming block's fields render, and the set of unknown-field and inactive-block
    rows (with their provenance and carry-vs-drop wiring) is rebuilt ([[plugins#plugin-blocks]], A4.3/#83,
    A4.4/#84). Two seams raise it -- a type switch (:meth:`__on_resource_type_changed`) and every
    :meth:`revert` (a reload can change the active type, its unknown fields, and the inactive-block fates
    at once, so revert rebuilds unconditionally rather than deciding which moved). Distinct from
    :attr:`unknown_fields_changed` (a single fallback field dropped) because that stays within a
    composition the reactive rows can show/hide, whereas this adds, removes, and re-wires whole rows --
    so ``DocumentWidget`` rebuilds its dock contents on it. Plain seeding does not raise it."""

    path = SimpleProperty[Path | None](None)
    """The document's current file path, mirroring :attr:`document`'s own path -- reassigned whenever
    it changes (construction, :meth:`revert`, :meth:`convert`, and eventually a completed rename, A5),
    so a consumer that needs to react to the document's identity changing (e.g. `DocumentsDock`
    resyncing a dock's persisted identity) can bind to `path_changed` instead of polling it."""

    location = SimpleProperty("")
    """The document's file location, seeded from :attr:`path` ([[field-schema#field-mapping]]'s derived
    folder/location links). The viewer binds to it (rendered as a native-path link); it is not edited
    directly -- :meth:`rename_location` is the only thing that changes it, and only once the deferred
    move-on-disk (A5) actually succeeds."""

    resource_type = SimpleProperty("")
    """The document's resource type ([[field-schema#resource-types]]) -- the key of its **active**
    plugin block ([[plugins#plugin-blocks]]). Editing it is a **type switch** (A4.3/#83): the write-through
    (:meth:`__on_resource_type_changed`) claims the newly-active block, re-seeds the type-field scalars
    from it, marks dirty, and fires :attr:`active_block_changed`. Switching away and back within a
    session is non-destructive -- the outgoing block stays resurrectable in memory until save (the block
    persistence invariant, #82). Empty when the document has no type yet (a brand-new document); its
    editor is the special, editor-only ``TypeField`` (:mod:`~rehuco_agent.fields.type_field`)."""

    title = SimpleProperty("")
    """The primary source's display title ([[field-schema#sources]])."""

    authors = SimpleProperty[Sequence[AuthorEntry]](default_factory=list)
    """The shared ``authors`` list ([[field-schema#authors]]); entries are tolerantly
    **string-or-record** (a plain name, or a ``{"name", "url"}`` record), and an edit to one entry
    never alters another's type -- seeding and write-through round-trip records untouched. Whether
    every entry is losslessly comma-editable is :func:`~rehuco_core.authors_comma_editable`'s to
    answer (#95/#97)."""

    publisher = SimpleProperty("")
    """The primary source's publisher ([[field-schema#sources]])."""

    url = SimpleProperty("")
    """The primary source's URL ([[field-schema#sources]])."""

    released = SimpleProperty[str | None](None)
    """The shared, partial-precision ``released`` date ([[field-schema#field-mapping]]), or ``None``
    when absent ([[field-schema#deferred-items]])."""

    description = SimpleProperty("")
    """The resource's Markdown description; a top-level common-core string, edited in its own dock and
    rendered in the viewer ([[plugins#viewer-editor-both]])."""

    complete = SimpleProperty(True)
    """The shared "all files present" flag ([[field-schema#boolean-flags]]); defaults ``true``."""

    online = SimpleProperty(False)
    """The shared "source still available online" flag ([[field-schema#online-flag]])."""

    viewed = SimpleProperty(False)
    """The per-user "viewed" flag ([[field-schema#per-user-shared]])."""

    todo = SimpleProperty(False)
    """The per-user "to do" flag ([[field-schema#per-user-shared]])."""

    keep = SimpleProperty(False)
    """The per-user "keep" flag ([[field-schema#per-user-shared]])."""

    favorite = SimpleProperty(False)
    """The per-user "favorite" flag ([[field-schema#boolean-flags]])."""

    rating = SimpleProperty[int | None](None)
    """The per-user rating ([[field-schema#per-user-shared]]); may be negative
    ([[field-schema#field-types]]), or ``None`` for unrated ([[field-schema#deferred-items]])."""

    images_count = SimpleProperty[int | None](None)
    """The ReferenceImages image count ([[field-schema#field-types]]), or ``None`` when not yet
    scanned ([[field-schema#deferred-items]])."""

    level = SimpleProperty[list[str]](default_factory=list)
    """The Tutorial-only multi-choice level tags ([[field-schema#field-types]]); beginner /
    intermediate / advanced / any, zero or more at once."""

    original_duration = SimpleProperty[int | None](None)
    """Measured total duration, in seconds, of the complete download ([[field-schema#duration-size]]),
    or ``None`` when unmeasured ([[field-schema#deferred-items]])."""

    current_duration = SimpleProperty[int | None](None)
    """Measured duration, in seconds, of the files still on disk ([[field-schema#duration-size]]), or
    ``None`` when unmeasured ([[field-schema#deferred-items]])."""

    advertised_duration = SimpleProperty[int | None](None)
    """The coarse web-claimed duration, in seconds ([[field-schema#duration-size]]), or ``None`` when
    absent ([[field-schema#deferred-items]])."""

    original_size = SimpleProperty[int | None](None)
    """Measured total size, in bytes, of the complete download ([[field-schema#duration-size]]), or
    ``None`` when absent (e.g. a Collection, [[field-schema#deferred-items]])."""

    current_size = SimpleProperty[int | None](None)
    """Disk space, in bytes, currently used by this copy ([[field-schema#duration-size]]), or ``None``
    when absent ([[field-schema#deferred-items]])."""

    advertised_tags = SimpleProperty[list[str]](default_factory=list)
    """The web-scraped ``advertised_tags`` list ([[field-schema#field-mapping]])."""

    extra_tags = SimpleProperty[list[str]](default_factory=list)
    """The personal ``extra_tags`` list ([[field-schema#field-mapping]])."""

    hidden_images = SimpleProperty[list[str]](default_factory=list)
    """The screenshot filenames curated *out* of the lightbox ([[data-model#image-meanings]], #27); a
    top-level common-core list. The lightbox shows every ``ImageScanner.files()`` sibling by default, so
    only the hidden exceptions are stored -- the editor's checkboxes are the inverse (checked = visible)."""

    dirty = SimpleProperty(False)
    """True when the model holds edits not yet saved to disk."""

    lock_reasons = SimpleProperty[list[LockReason]](default_factory=list)
    """Every named cause this document is read-only ([[data-model#write-integrity]]), mirrored from
    :attr:`document`'s own :attr:`~RehuDocument.lock_reasons`; empty when it is freely editable. Carries
    *why* -- a newer ``format_version`` ([[data-model#schema-version]]), an unconverted legacy ``.tc``
    ([[acquisition-tooling#tc-to-rehu]]), an owned field present-but-uncoercible, or a file that could not
    be read at all -- so the viewer can explain the lock and act per kind (#94). Recomputed at
    construction and on every :meth:`revert`/:meth:`convert` (never by an edit -- there is no setter path
    back to a locked state). ``DocumentWidget`` disables its editor docks while this is non-empty; the
    inline notice (#94) and `DocumentsDock`'s tab marker bind to `lock_reasons_changed`."""

    upgradable = SimpleProperty(False)
    """Whether this document can be brought current by a plain save (#89, [[data-model#schema-version]]):
    the file on disk is older -- at the file-wide :data:`~rehuco_core.CURRENT_FORMAT_VERSION`, at the
    active plugin block's own version ([[plugins#plugin-blocks]], #81), or both, since the user is never
    shown which layer is stale -- the model holds no unsaved
    edits (a dirty old file's remedy is Save, which upgrades anyway -- no separate offer needed then),
    and the document isn't :attr:`locked` (a locked document can't be saved at all). Recomputed at the
    same seams as :attr:`lock_reasons` -- construction, :meth:`revert`, :meth:`convert` -- plus
    :meth:`save` (since saving is what clears it), and live off `dirty_changed`/`lock_reasons_changed`
    so an in-place edit or a newly-appearing lock hides the offer immediately rather than leaving it
    stale until the next explicit seam. `DocumentWidget`'s upgrade toolbar button and inline notice
    banner row both key off this flag directly, the same shape every other lock reason already uses
    (a toolbar remedy, plus a message-only banner row explaining it)."""

    image_scanner = SimpleProperty[ImageScanner | None](None)
    """The current screenshot-resolution strategy -- `TcScanner` while :attr:`~RehuDocument.legacy_tc`,
    `RehuScanner` once converted or genuinely `.rehu`-native. `ImageStrip`/`ImageSelector`/`MarkdownView`
    each hold their own copy and bind to `image_scanner_changed` to pick up a `.tc` -> `.rehu`
    conversion's switch in naming convention without rebuilding the field composition
    ([[acquisition-tooling#tc-to-rehu]])."""

    def __init__(self, document: RehuDocument, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__document = document

        self.__seeding = False
        """True only while :meth:`__seed_from_document` is applying field values pulled from the
        document -- guards every write-through handler below so a seed is never mistaken for a user
        edit."""

        self.__seed_from_document()
        self.lock_reasons = list(self.__document.lock_reasons)
        self.image_scanner = TcScanner(self) if self.__document.legacy_tc else RehuScanner(self)
        self.__recompute_upgradable()

        # a live edit toggles dirty, and a lock can appear/clear outside revert/convert too (tests
        # assign lock_reasons directly to simulate one) -- both must hide/reveal the upgrade offer
        # immediately, not just at the next explicit recompute seam below
        self.dirty_changed.connect(lambda _dirty: self.__recompute_upgradable())  # type: ignore[attr-defined]
        self.lock_reasons_changed.connect(lambda _reasons: self.__recompute_upgradable())  # type: ignore[attr-defined]

        self.resource_type_changed.connect(self.__on_resource_type_changed)  # type: ignore[attr-defined]
        self.title_changed.connect(self.__on_title_changed)  # type: ignore[attr-defined]
        self.authors_changed.connect(self.__on_authors_changed)  # type: ignore[attr-defined]
        self.publisher_changed.connect(self.__on_publisher_changed)  # type: ignore[attr-defined]
        self.url_changed.connect(self.__on_url_changed)  # type: ignore[attr-defined]
        self.released_changed.connect(self.__on_released_changed)  # type: ignore[attr-defined]
        self.description_changed.connect(self.__on_description_changed)  # type: ignore[attr-defined]
        self.hidden_images_changed.connect(self.__on_hidden_images_changed)  # type: ignore[attr-defined]
        self.original_size_changed.connect(self.__on_original_size_changed)  # type: ignore[attr-defined]
        self.current_size_changed.connect(self.__on_current_size_changed)  # type: ignore[attr-defined]
        self.advertised_tags_changed.connect(self.__on_advertised_tags_changed)  # type: ignore[attr-defined]
        self.extra_tags_changed.connect(self.__on_extra_tags_changed)  # type: ignore[attr-defined]
        for name in (*TYPE_FIELD_BOOL_NAMES, *TYPE_FIELD_INT_NAMES, *TYPE_FIELD_STR_LIST_NAMES):
            signal_name = SimpleProperty.notify_signal_name(type(self), name)
            getattr(self, signal_name).connect(lambda value, key=name: self.__on_type_field_changed(key, value))

    @classmethod
    def create_new(
        cls, path: Path | str | None = None, parent: QObject | None = None, *, username: str = DEFAULT_CURRENT_USERNAME
    ) -> RehuDocumentModel:
        """Start a new, empty document, optionally already bound to a save path.

        :param path: destination this document will save to by default. When given, the model
            starts dirty -- nothing is written to disk until :meth:`save`, but the caller already
            knows where it belongs (e.g. :meth:`~rehuco_agent.documents.documents_dock.DocumentsDock.open_folder`'s
            directory-scoped resource with no `info.rehu` yet). When omitted, the model starts
            clean, with no destination decided yet.
        :param parent: optional Qt parent.
        :param username: the identity the new document's per-user writes are filed under
            ([[field-schema#per-user-shared]], #99) -- the caller (e.g. `DocumentsDock`) passes the
            **current**-user identity setting; core's :data:`~rehuco_core.DEFAULT_CURRENT_USERNAME` otherwise.
        :returns: the new model, wrapping a fresh in-memory `RehuDocument`.
        """
        model = cls(RehuDocument({}, Path(path) if path is not None else None, username=username), parent)
        if path is not None:
            model.dirty = True
        return model

    @property
    def document(self) -> RehuDocument:
        """The wrapped document."""
        return self.__document

    @property
    def locked(self) -> bool:
        """Whether the document is read-only -- derived from whether :attr:`lock_reasons` is non-empty
        ([[data-model#write-integrity]]). A convenience over ``bool(self.lock_reasons)`` for the many
        callers that only need "is it locked", not why; consumers that must react to the lock *changing*
        bind to ``lock_reasons_changed``, since a derived read-only property carries no notify signal of
        its own."""
        return bool(self.lock_reasons)

    @property
    def label(self) -> str:
        """This document's display label: the parent directory's name, trailing-slashed, for
        `info.rehu` ([[data-model#resource-scoping]]), the bare filename otherwise.

        :returns: the label, or an empty string when the document has no path yet.
        """
        path = self.path
        if path is None:
            return ""
        return f"{path.parent.name}/" if path.name == INFO_REHU_FILENAME else path.name

    @property
    def current_name(self) -> str:
        """The resource's current rename target name -- the name a rename suggestion would replace
        ([[field-schema#field-mapping]]): the **parent directory** name for a directory-scoped
        ``info.rehu`` ([[data-model#resource-scoping]]), the file **stem** (no extension) otherwise,
        since a standalone ``foo.rehu`` renames its whole ``foo.*`` sibling set. Empty when the
        document has no path yet.
        """
        path = self.path
        if path is None:
            return ""
        return path.parent.name if path.name == INFO_REHU_FILENAME else path.stem

    @property
    def sources(self) -> list[dict[str, Any]]:
        """The document's ``sources`` list ([[field-schema#sources]]); the model edits its primary entry."""
        return self.__document.sources

    def save(self) -> None:
        """Atomically save the document ([[data-model#write-integrity]]) and clear the dirty flag.

        Also how an :attr:`upgradable` document is actually upgraded (#89): the document's own
        ``save()`` already restamps it to :data:`~rehuco_core.CURRENT_FORMAT_VERSION` on write, so
        there is no separate migrate call -- this is the only one needed, whether reached from the
        toolbar's Save action or the inline banner's Upgrade action.
        """
        self.__document.save()
        self.dirty = False
        # explicit, not left to the dirty_changed connection alone: a clean-but-upgradable document
        # (the Upgrade path) saves without dirty ever having been True, so no dirty_changed would fire
        self.__recompute_upgradable()

    def rename_location(self, new_name: str) -> bool:
        """Rename this resource to ``new_name`` -- clicked from a `PathField` rename suggestion.

        Orchestration only: the intent is logged *before* anything is attempted (so the log reflects
        what was asked for even if it then fails), a dirty document is saved first (so the files
        actually being moved are never stale), and the move itself is delegated to :meth:`__move`.
        :meth:`__move` owns performing the rename and reseeding :attr:`location` on success; it always
        fails for now -- the real rename-on-disk (folder-rename-from-suggestions, checksum-gated safe
        move) is deferred to A5 ([[implementation-plan]]) -- so :attr:`location` never actually
        changes through this path yet.

        :param new_name: the destination file/folder name (already sanitized by the caller, e.g. a
            clicked `PathField` suggestion).
        :returns: whether the rename succeeded.
        """
        LOG.info("Attempting to rename %r to %r", self.current_name, new_name)
        if self.dirty:
            self.save()
        return self.__move(new_name)

    def revert(self) -> None:
        """Discard in-memory edits and reseed every field from the document's file on disk.

        Re-reads the file (:meth:`RehuDocument.reload`) rather than just resetting to the
        last-loaded snapshot, so an out-of-band edit ([[data-model#write-integrity]]) is picked up
        too. :meth:`__seed_from_document` guards itself against the reseed looking like an edit --
        no write-back to the document, and :attr:`dirty` ends up ``False`` regardless of what it was.

        **A revert always rebuilds the form** ([[plugins#plugin-blocks]], A4.3/#83): it fires
        :attr:`active_block_changed` unconditionally, so the whole composition re-resolves from the
        reloaded document -- a revert is defined to leave the model exactly as a fresh open would. A reload
        can change the active type, the active block's unknown fields, and the inactive-block fates
        (claimed-then-abandoned blocks revert to carried foreign, regaining their drop button, A4.4/#84)
        all at once, and only a full rebuild re-wires a row's provenance and carry-vs-drop button -- the
        reactive rows can only show/hide and re-read a value, never re-wire. Rather than enumerate which
        structural axis moved (a check that has to stay exhaustive as axes are added), the coarse,
        user-driven revert just rebuilds; the cost is negligible and it is correct by construction.

        ``unknown_fields_changed`` is emitted too, for consumers that don't rebuild on
        :attr:`active_block_changed` -- the source-preview docks re-serialize off it (#111), and it also
        covers restored unknown active-block fields ([[plugins#fallback-editor]], A2.8/#28).

        :raises ValueError: if the document has no path (was never loaded from or saved to a file).
        """
        self.__document.reload()
        self.__seed_from_document()
        self.dirty = False
        self.lock_reasons = list(self.__document.lock_reasons)
        self.unknown_fields_changed.emit()
        self.active_block_changed.emit()
        self.__recompute_upgradable()

    def convert(self, *, keep_backups: bool, overwrite: bool = False) -> None:
        """Convert this locked, legacy ``.tc``-backed document into a real ``.rehu`` in place
        (A3.1 Phase 4, [[acquisition-tooling#tc-to-rehu]]).

        Delegates the file-system work to :func:`rehuco_core.convert_tc`, then adopts its result as
        this model's document -- reseeding every field and recomputing :attr:`locked` (which drops to
        ``False``, since the result is never :attr:`~RehuDocument.legacy_tc`) -- so the same dock keeps
        showing the same resource, now unlocked, without a reload round-trip. The conversion files
        the imported per-user flags under this document's **own** username -- the identity it was
        opened with, which for a legacy ``.tc`` is the **unknown** user (#109) -- so the block's
        ``users`` key and the result's :attr:`~RehuDocument.username` stay in agreement (#98's
        invariant); an identity-setting change made after this document was opened applies to later
        opens, not to it (#99).

        :param keep_backups: whether to keep ``.orig`` backups of the ``.tc`` and legacy screenshots.
        :param overwrite: whether an already-converted ``.rehu`` at the target path may be replaced.
        :raises ValueError: this document isn't :attr:`~RehuDocument.legacy_tc`, or has no path.
        :raises OSError: propagated from :func:`rehuco_core.convert_tc` (``FileExistsError`` for an
            unconfirmed overwrite or a stale backup; any other ``OSError`` from the underlying file
            operations) -- this model's ``document``/``locked``/``dirty`` are left untouched.
        """
        if not self.__document.legacy_tc:
            raise ValueError("only a legacy .tc-backed document can be converted")
        if self.path is None:
            raise ValueError("no path to convert -- document was not loaded from a file")
        self.__document = convert_tc(
            self.path, keep_backups=keep_backups, overwrite=overwrite, username=self.__document.username
        )
        self.__seed_from_document()
        self.dirty = False
        self.lock_reasons = list(self.__document.lock_reasons)
        self.image_scanner = RehuScanner(self)
        self.unknown_fields_changed.emit()
        self.__recompute_upgradable()

    def bind[T](self, field: Field[T]) -> FieldBinding[T]:
        """Resolve a field into its current binding on this model ([[plugins#field-toolkit]], `FieldModel`).

        :param field: the field to resolve; its :attr:`~Field.name` matches either a `SimpleProperty`
            declared on this class or an unrecognized key in the active plugin block (an unknown field,
            [[plugins#fallback-editor]]).
        :returns: the field's current value, its notify signal, and a setter.
        """
        name = field.name
        try:
            signal_name = SimpleProperty.notify_signal_name(type(self), name)
        except KeyError:
            # not a declared property -> a key carried verbatim and surfaced through the generic
            # fallback ([[plugins#fallback-editor]]). Two different things reach here and they sit at
            # different depths in the document: a whole **inactive block** is a top-level key, while an
            # **unknown field** is a key inside the active block -- so which one this is has to be
            # settled before reading a value, or an inactive block would read as an absent field.
            inactive_block = self.__inactive_block_binding(name)
            if inactive_block is not None:
                return inactive_block
            return FieldBinding(
                value=self.__document.active_field(name),
                changed=self.unknown_fields_changed,
                set_value=lambda value: self.__document.set_active_field(name, value),
            )
        return FieldBinding(
            value=getattr(self, name),
            changed=getattr(self, signal_name),
            set_value=lambda value: setattr(self, name, value),
        )

    def __inactive_block_binding(self, name: str) -> FieldBinding[Any] | None:
        """Resolve ``name`` as a whole inactive plugin block, when it is one ([[plugins#plugin-blocks]]).

        The binding is read-only by design: the fallback editor's only affordance on an inactive block is
        **carry or drop**, never edit-in-place ([[plugins#fallback-editor]], A4.4/#84) -- its *values* are
        foreign payload this file is merely custodian of. The drop half goes through
        :meth:`drop_inactive_block` (a whole-block remove), not this setter, so the setter refuses rather
        than writing a value into a block this document doesn't own.

        :param name: the field name being bound.
        :returns: a binding over the block's verbatim contents, or ``None`` when ``name`` isn't an
            inactive block's key.
        """
        block = next((block for block in self.__document.inactive_blocks() if block.key == name), None)
        if block is None:
            return None
        return FieldBinding(
            value=block.fields,
            changed=self.unknown_fields_changed,
            set_value=lambda _value: LOG.error("Refusing to edit inactive block %r: carry or drop, never edit", name),
        )

    def unknown_field_names(self) -> list[str]:
        """The active plugin block's keys the model doesn't recognize ([[plugins#fallback-editor]], A2.8/#28).

        Every key in the active block ([[plugins#plugin-blocks]]) that isn't a known field
        (:data:`KNOWN_TYPE_FIELD_NAMES`) -- e.g. a field written by a newer plugin version than the one
        installed here. Carried verbatim on round-trip unless explicitly dropped via
        :meth:`remove_unknown_field`. The block's own ``format_version`` stamp (#81,
        [[plugins#plugin-blocks]]) is excluded -- it is block-management bookkeeping, not a resource
        field, the same way the file-wide stamp never shows up as an unknown *common* field either.
        The block's ``users`` map (:data:`~rehuco_core.USERS_KEY`, #98/#99) is excluded for the same
        reason -- it is the per-user storage *structure*, not a resource field; what's inside it
        surfaces only through the declared per-user properties (:data:`USER_FIELD_NAMES`), never
        through the generic fallback.

        :returns: the unknown keys, sorted for a stable display order.
        """
        return sorted(
            key
            for key in self.__document.active_block
            if key not in KNOWN_TYPE_FIELD_NAMES and key not in (FORMAT_VERSION_KEY, USERS_KEY)
        )

    def inactive_block_keys(self) -> list[str]:
        """The keys of this document's inactive plugin blocks ([[plugins#plugin-blocks]]).

        Every block the document's ``type`` doesn't name -- inactive **whether or not** its plugin is
        installed here, since only the type decides what is active. Each is carried verbatim on save
        unless explicitly dropped (:meth:`drop_inactive_block`, A4.4/#84) -- its *values* are never edited
        in place; the fallback surfaces it as a flagged, provenance-labeled row with a carry-or-drop
        choice ([[plugins#fallback-editor]]). This list is just the keys; the fates driving the flagging
        are :meth:`inactive_block_fates`.

        **Sorted** for a stable display order, the same discipline :meth:`unknown_field_names` applies to
        the active block's unknown fields -- a presentation concern, independent of the document order the
        core :meth:`~rehuco_core.RehuDocument.inactive_blocks` preserves for save (:meth:`save` imposes
        its own canonical key order regardless, [[plugins#plugin-blocks]]).

        :returns: the inactive block keys, sorted alphabetically.
        """
        return sorted(block.key for block in self.__document.inactive_blocks())

    def inactive_block_fates(self) -> list[tuple[str, bool]]:
        """Each inactive block's key paired with **whether saving will drop it** ([[plugins#plugin-blocks]],
        A4.3/#83).

        The block persistence invariant (#82) gives the same inactive block opposite fates depending on
        whether it was ever active this session: a **claimed-then-abandoned** block (switched *to* and
        then away from) is dropped on save (``True``), while a **never-claimed foreign** block is carried
        verbatim (``False``). Surfacing the split is the "visually distinguish former-identity from
        foreign" the slice decides to honour ([[plugins#plugin-blocks]]'s safety net): a user may switch
        to a type merely to preview it, which arms its deletion, so the form flags an abandoned block
        differently from one that will simply be carried.

        **Sorted by key**, the same stable display order :meth:`inactive_block_keys` uses -- independent
        of the document order save imposes its own canonical layout over.

        :returns: ``(key, dropped_on_save)`` pairs, sorted alphabetically by key.
        """
        return sorted((block.key, block.dropped_on_save) for block in self.__document.inactive_blocks())

    def available_types(self) -> list[str]:
        """The resource types offerable in the type selector ([[plugins#plugin-blocks]], A4.3/#83).

        The union of every installed plugin's main key
        (:attr:`~rehuco_core.plugins.PluginRegistry.main_keys`) and every block key this document already
        carries -- active or inactive (:meth:`~rehuco_core.RehuDocument.plugin_blocks`). The block keys
        matter for **resurrection**: a foreign or former-active block (e.g. an ``audiopack`` this build
        has no plugin for) must stay selectable so the user can switch back to it and revive its
        in-memory values, non-destructively, until save ([[plugins#plugin-blocks]]'s worked example,
        steps 2 and 4).

        Installed keys lead, in declaration order (the primary, offer-these-first set); any extra block
        key the document carries follows, sorted, so a not-installed type a file happens to hold is still
        reachable without reordering the common offers. The empty type a brand-new document has is **not**
        included -- it is representable by the selector's own placeholder, not a switch target.

        :returns: the selectable type keys: installed mains first, then the document's own extra block
            keys, sorted.
        """
        installed = list(self.__document.plugins.main_keys)
        present = {block.key for block in self.__document.plugin_blocks()}
        extra = sorted(present - set(installed))
        return installed + extra

    def remove_unknown_field(self, name: str) -> None:
        """Drop an unknown active-block field, marking the model dirty ([[plugins#fallback-editor]], A2.8/#28).

        No-op if ``name`` isn't present, so a double remove (e.g. a stale button click) is harmless.

        :param name: the unknown block key to delete.
        """
        if self.__document.remove_active_field(name):
            self.unknown_fields_changed.emit()
            self.dirty = True

    def drop_inactive_block(self, name: str) -> None:
        """Drop a whole inactive plugin block the user chooses not to carry ([[plugins#fallback-editor]],
        A4.4/#84).

        The block-level sibling of :meth:`remove_unknown_field`: the *drop* half of the fallback editor's
        carry-vs-drop choice on a foreign inactive block. Delegates the deletion to
        :meth:`~rehuco_core.RehuDocument.remove_block` (which refuses the active block), then emits
        ``unknown_fields_changed`` so the reactive fallback row hides itself, and marks dirty. A
        :meth:`revert` restores the block from disk and re-shows the row, exactly like a dropped unknown
        field. No-op if ``name`` isn't a droppable inactive block, so a stale button click is harmless.

        :param name: the inactive block's top-level key to delete.
        """
        if self.__document.remove_block(name):
            self.unknown_fields_changed.emit()
            self.dirty = True

    def __recompute_upgradable(self) -> None:
        """Recompute :attr:`upgradable` from the document's current on-disk version(s), dirtiness, and
        lock state (#89, [[plugins#plugin-blocks]]) -- see :attr:`upgradable`'s own docstring for the
        three conditions.

        A stale **file-wide** version and a stale **active-block** version (#81) are both "something
        this document's Upgrade action would bring current" -- one offer covers either, or both, so a
        caller never has to know which layer is actually behind.
        """
        on_disk = self.__document.on_disk_format_version
        file_pending = on_disk is not None and on_disk < CURRENT_FORMAT_VERSION
        self.upgradable = (
            (file_pending or self.__document.active_block_upgrade_pending) and not self.dirty and not self.locked
        )

    def __seed_from_document(self) -> None:
        """Set every field from :attr:`document`'s current in-memory state (construction,
        :meth:`revert`, :meth:`convert`), guarded so it is never itself mistaken for a user edit."""
        self.__seeding = True
        try:
            self.path = self.__document.path
            self.location = self.__document.path.as_posix() if self.__document.path is not None else ""
            self.resource_type = self.__document.type
            self.title = self.__document.title
            self.authors = self.__document.authors
            self.publisher = self.__document.publisher
            self.url = self.__document.url
            self.released = self.__document.released
            self.description = self.__document.description
            self.hidden_images = self.__document.hidden_images
            self.original_size = self.__document.original_size
            self.current_size = self.__document.current_size
            self.advertised_tags = self.__document.advertised_tags
            self.extra_tags = self.__document.extra_tags
            self.__seed_active_block_fields()
        finally:
            self.__seeding = False

    def __seed_active_block_fields(self) -> None:
        """Set the type-field scalars from the **active** block's current state -- shared by the full
        :meth:`__seed_from_document` reseed and the narrower one a type switch needs.

        A type switch (:meth:`__on_resource_type_changed`) re-reads *only* these block-scoped scalars
        from the newly-active block ([[plugins#plugin-blocks]], A4.3/#83), leaving the common-core
        fields (title/publisher/...) untouched, so it calls this alone rather than the whole reseed.
        Callers set the :attr:`__seeding` guard themselves; this never writes back to the document, so a
        reseed is never mistaken for an edit.

        The type-field scalar fields read/write generically through the type-keyed plugin block, each
        through its own accessor -- per-user names via the users map, the rest inline
        ([[field-schema#resource-types]]); values are coerced defensively (malformed -> the field's own
        fallback -- its declared default for bool/str-list, ``None`` for the optional-scalar ints,
        matching core's own absent-vs-malformed treatment, [[data-model#write-integrity]]). The
        bool/str-list fallback comes from each field's own `SimpleProperty` declaration -- not a second,
        hand-duplicated literal here -- so there is exactly one place per field to change its default.
        """
        for name in TYPE_FIELD_BOOL_NAMES:
            default = SimpleProperty.default_value(type(self), name)
            setattr(self, name, bool(self.__read_field(name, default)))
        for name in TYPE_FIELD_INT_NAMES:
            value = self.__read_field(name, None)
            setattr(self, name, value if isinstance(value, int) and not isinstance(value, bool) else None)
        for name in TYPE_FIELD_STR_LIST_NAMES:
            default = SimpleProperty.default_value(type(self), name)
            value = self.__read_field(name, default)
            coerced = [item for item in value if isinstance(item, str)] if isinstance(value, list) else default
            setattr(self, name, coerced)

    def __read_field(self, name: str, default: Any) -> Any:
        """Read active-block field ``name`` through its own accessor: the per-user one for a
        :data:`USER_FIELD_NAMES` member (`RehuDocument.active_user_field`, reaching into the block's
        ``users`` map, [[field-schema#per-user-shared]]), the shared inline one for everything else
        (`~RehuDocument.active_field`) -- the read half of the split
        :meth:`__on_type_field_changed` applies on write (#99).

        :param name: the field to read.
        :param default: the value an absent field reads as.
        :returns: the stored value, or ``default`` when absent.
        """
        if name in USER_FIELD_NAMES:
            return self.__document.active_user_field(name, default)
        return self.__document.active_field(name, default)

    def __move(self, new_name: str) -> bool:
        """Rename this document's underlying file(s) to ``new_name`` and reseed :attr:`location`.

        Always fails, for now -- the real rename-on-disk (folder-rename-from-suggestions, plus the
        checksum-gated safe move a cross-filesystem destination needs) is deferred to A5
        ([[implementation-plan]]); this stub exists so :meth:`rename_location` has somewhere to call
        that already fails the way missing permissions or a name collision would, rather than
        silently pretending to succeed. When implemented, it will perform the move and reseed
        :attr:`location`/:attr:`current_name` from the new path.

        :param new_name: the destination file/folder name.
        :returns: always ``False``.
        """
        LOG.error(
            "Rename not implemented yet (rename-on-disk is deferred to A5, #25): %r -> %r",
            self.current_name,
            new_name,
        )
        return False

    def __on_resource_type_changed(self, value: str) -> None:
        """Switch the document's active type ([[plugins#plugin-blocks]], A4.3/#83): claim the newly-active
        block, re-resolve the form, and mark dirty.

        This is the agent-side seam that **arms** the block persistence invariant (#82). The order matters:

        #. :meth:`~rehuco_core.RehuDocument.set_active_type` switches ``type`` and **claims** the target
           block -- from now until close, switching away from it drops it on save. The requested value is
           normalized to its plugin's main key there; :attr:`resource_type` is reconciled to that main key
           under the seed guard (no recursion, no second edit) so the selector shows the spelling actually
           stored.
        #. The type-field scalars re-seed from the **newly-active** block
           (:meth:`__seed_active_block_fields`), so its values render (or reset to defaults for a
           never-before-used type -- the empty active block the slice starts). The common-core fields are
           deliberately left alone: a type switch is not a reload.
        #. :attr:`dirty` is set -- a type switch is an edit, so the close guard treats it as one -- and
           :attr:`active_block_changed`/:attr:`unknown_fields_changed` fire so the view rebuilds the
           fallback rows and the live previews re-render.

        No-op while seeding (construction, :meth:`revert`, :meth:`convert`, or the reconcile below) -- a
        reseed sets ``type`` to whatever is already on disk and must not be mistaken for a switch.

        :param value: the resource type to switch to (a main key or alias spelling).
        """
        if self.__seeding:
            return
        self.__document.set_active_type(value)
        main = self.__document.type
        if main != value:
            # an alias normalized to its main key on write -- mirror it onto the property so the selector
            # reflects the stored spelling. Guarded, so this reconcile is not itself taken for a switch.
            self.__seeding = True
            try:
                self.resource_type = main
            finally:
                self.__seeding = False
        self.__seeding = True
        try:
            self.__seed_active_block_fields()
        finally:
            self.__seeding = False
        self.dirty = True
        self.active_block_changed.emit()
        self.unknown_fields_changed.emit()

    def __on_title_changed(self, value: str) -> None:
        """Write an edited title through to the document's primary source and mark dirty.

        No-op while the model is seeding (construction, :meth:`revert`, or :meth:`convert`) -- see the comment there.

        :param value: the new title.
        """
        if self.__seeding:
            return
        self.__document.title = value
        self.dirty = True

    def __on_authors_changed(self, value: Sequence[AuthorEntry]) -> None:
        """Write an edited authors list through to the document and mark dirty.

        The document's setter normalizes each entry to canonical minimal form
        ([[field-schema#authors]]); a record entry passes through untouched, so editing one entry
        never shreds another's type. No-op while the model is seeding (construction, :meth:`revert`,
        or :meth:`convert`) -- see the comment there.

        :param value: the new authors list.
        """
        if self.__seeding:
            return
        self.__document.authors = value
        self.dirty = True

    def __on_publisher_changed(self, value: str) -> None:
        """Write an edited publisher through to the document's primary source and mark dirty.

        No-op while the model is seeding (construction, :meth:`revert`, or :meth:`convert`) -- see the comment there.

        :param value: the new publisher.
        """
        if self.__seeding:
            return
        self.__document.publisher = value
        self.dirty = True

    def __on_url_changed(self, value: str) -> None:
        """Write an edited url through to the document's primary source and mark dirty.

        No-op while the model is seeding (construction, :meth:`revert`, or :meth:`convert`) -- see the comment there.

        :param value: the new url.
        """
        if self.__seeding:
            return
        self.__document.url = value
        self.dirty = True

    def __on_released_changed(self, value: str | None) -> None:
        """Write an edited released date through to the document and mark dirty.

        No-op while the model is seeding (construction, :meth:`revert`, or :meth:`convert`) -- see the comment there.

        :param value: the new released date.
        """
        if self.__seeding:
            return
        self.__document.released = value
        self.dirty = True

    def __on_description_changed(self, value: str) -> None:
        """Write an edited description through to the document and mark dirty.

        No-op while the model is seeding (construction, :meth:`revert`, or :meth:`convert`) -- see the comment there.

        :param value: the new description.
        """
        if self.__seeding:
            return
        self.__document.description = value
        self.dirty = True

    def __on_hidden_images_changed(self, value: list[str]) -> None:
        """Write an edited hidden-images list through to the document and mark dirty.

        No-op while the model is seeding (construction, :meth:`revert`, or :meth:`convert`) -- see the comment there.

        :param value: the new hidden-images list.
        """
        if self.__seeding:
            return
        self.__document.hidden_images = value
        self.dirty = True

    def __on_original_size_changed(self, value: int | None) -> None:
        """Write an edited original_size through to the document and mark dirty.

        No-op while the model is seeding (construction, :meth:`revert`, or :meth:`convert`) -- see the comment there.

        :param value: the new original_size.
        """
        if self.__seeding:
            return
        self.__document.original_size = value
        self.dirty = True

    def __on_current_size_changed(self, value: int | None) -> None:
        """Write an edited current_size through to the document and mark dirty.

        No-op while the model is seeding (construction, :meth:`revert`, or :meth:`convert`) -- see the comment there.

        :param value: the new current_size.
        """
        if self.__seeding:
            return
        self.__document.current_size = value
        self.dirty = True

    def __on_advertised_tags_changed(self, value: list[str]) -> None:
        """Write an edited advertised_tags list through to the document and mark dirty.

        No-op while the model is seeding (construction, :meth:`revert`, or :meth:`convert`) -- see the comment there.

        :param value: the new advertised_tags list.
        """
        if self.__seeding:
            return
        self.__document.advertised_tags = value
        self.dirty = True

    def __on_extra_tags_changed(self, value: list[str]) -> None:
        """Write an edited extra_tags list through to the document and mark dirty.

        No-op while the model is seeding (construction, :meth:`revert`, or :meth:`convert`) -- see the comment there.

        :param value: the new extra_tags list.
        """
        if self.__seeding:
            return
        self.__document.extra_tags = value
        self.dirty = True

    def __on_type_field_changed(self, key: str, value: Any) -> None:
        """Write an edited type-field scalar through to the document's plugin block and mark dirty.

        A per-user key (:data:`USER_FIELD_NAMES`) lands in the block's ``users`` map under this
        document's own username, the rest inline in the block ([[field-schema#per-user-shared]],
        #99) -- the write half of :meth:`__read_field`'s split. ``None`` (only ever reachable for the
        optional-scalar members of :data:`TYPE_FIELD_INT_NAMES` -- the bool/str-list fields never hold
        it) **removes** the key rather than writing a JSON ``null`` -- ``set_active_field``/
        ``set_active_user_field`` are generic value writers with no such rule of their own, unlike
        `RehuDocument`'s typed scalar properties ([[field-schema#deferred-items]]). No-op while the
        model is seeding (construction, :meth:`revert`, or :meth:`convert`) -- see the comment there.

        :param key: the type-field key that changed.
        :param value: the new value, or ``None`` to remove the key.
        """
        if self.__seeding:
            return
        if key in USER_FIELD_NAMES:
            if value is None:
                self.__document.remove_active_user_field(key)
            else:
                self.__document.set_active_user_field(key, value)
        else:
            if value is None:
                self.__document.remove_active_field(key)
            else:
                self.__document.set_active_field(key, value)
        self.dirty = True
