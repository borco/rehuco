"""Reactive view-model wrapping a `RehuDocument` for the viewer/editor surfaces ([[plugins#view-model]])."""

import logging
from pathlib import Path
from typing import Any, Final

from borco_pyside.core import SimpleProperty
from PySide6.QtCore import QObject, Signal
from rehuco_core import CURRENT_FORMAT_VERSION, RehuDocument, convert_tc

from rehuco_agent.documents.image_scanner import ImageScanner, RehuScanner, TcScanner
from rehuco_agent.fields.field import Field, FieldBinding

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

    title = SimpleProperty("")
    """The primary source's display title ([[field-schema#sources]])."""

    authors = SimpleProperty[list[str]](default_factory=list)
    """The shared ``authors`` list ([[field-schema#resource-types]])."""

    publisher = SimpleProperty("")
    """The primary source's publisher ([[field-schema#sources]])."""

    url = SimpleProperty("")
    """The primary source's URL ([[field-schema#sources]])."""

    released = SimpleProperty("")
    """The shared, partial-precision ``released`` date ([[field-schema#field-mapping]])."""

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

    rating = SimpleProperty(0)
    """The per-user rating ([[field-schema#per-user-shared]]); may be negative ([[field-schema#field-types]])."""

    images_count = SimpleProperty(0)
    """The ReferenceImages image count ([[field-schema#field-types]])."""

    level = SimpleProperty[list[str]](default_factory=list)
    """The Tutorial-only multi-choice level tags ([[field-schema#field-types]]); beginner /
    intermediate / advanced / any, zero or more at once."""

    original_duration = SimpleProperty(0)
    """Measured total duration, in seconds, of the complete download ([[field-schema#duration-size]])."""

    current_duration = SimpleProperty(0)
    """Measured duration, in seconds, of the files still on disk ([[field-schema#duration-size]])."""

    advertised_duration = SimpleProperty(0)
    """The coarse web-claimed duration, in seconds ([[field-schema#duration-size]])."""

    original_size = SimpleProperty(0)
    """Measured total size, in bytes, of the complete download ([[field-schema#duration-size]])."""

    current_size = SimpleProperty(0)
    """Disk space, in bytes, currently used by this copy ([[field-schema#duration-size]])."""

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

    locked = SimpleProperty(False)
    """True when either :attr:`document`'s ``format_version`` is newer than this build understands
    ([[data-model#schema-version]]'s fail-safe-on-a-newer-file rule), or the document was mapped from a
    legacy ``.tc`` file not yet converted ([[acquisition-tooling#tc-to-rehu]], `RehuDocument.legacy_tc`)
    -- a document *older* than this build's format version, which the first rule alone would never
    catch. Recomputed at construction and on every :meth:`revert`/:meth:`convert` (never by an edit --
    there is no setter path back to either locked state). ``DocumentWidget`` disables its editor docks while this
    is true; nothing else in the model changes, since the underlying `RehuDocument` already preserves
    a newer file's fields verbatim and never downgrades its version stamp on save
    ([[data-model#schema-version]])."""

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
        self.locked = self.__document.format_version > CURRENT_FORMAT_VERSION or self.__document.legacy_tc
        self.image_scanner = TcScanner(self) if self.__document.legacy_tc else RehuScanner(self)

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
    def create_new(cls, path: Path | str | None = None, parent: QObject | None = None) -> RehuDocumentModel:
        """Start a new, empty document, optionally already bound to a save path.

        :param path: destination this document will save to by default. When given, the model
            starts dirty -- nothing is written to disk until :meth:`save`, but the caller already
            knows where it belongs (e.g. :meth:`~rehuco_agent.documents.documents_dock.DocumentsDock.open_folder`'s
            directory-scoped resource with no `info.rehu` yet). When omitted, the model starts
            clean, with no destination decided yet.
        :param parent: optional Qt parent.
        :returns: the new model, wrapping a fresh in-memory `RehuDocument`.
        """
        model = cls(RehuDocument({}, Path(path) if path is not None else None), parent)
        if path is not None:
            model.dirty = True
        return model

    @property
    def document(self) -> RehuDocument:
        """The wrapped document."""
        return self.__document

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
        """Atomically save the document ([[data-model#write-integrity]]) and clear the dirty flag."""
        self.__document.save()
        self.dirty = False

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

        The reload also restores any unknown active-block fields dropped this session, so
        ``unknown_fields_changed`` is emitted to let the generic fallbacks re-show themselves
        ([[plugins#fallback-editor]], A2.8/#28).

        :raises ValueError: if the document has no path (was never loaded from or saved to a file).
        """
        self.__document.reload()
        self.__seed_from_document()
        self.dirty = False
        self.locked = self.__document.format_version > CURRENT_FORMAT_VERSION or self.__document.legacy_tc
        self.unknown_fields_changed.emit()

    def convert(self, *, keep_backups: bool, overwrite: bool = False) -> None:
        """Convert this locked, legacy ``.tc``-backed document into a real ``.rehu`` in place
        (A3.1 Phase 4, [[acquisition-tooling#tc-to-rehu]]).

        Delegates the file-system work to :func:`rehuco_core.convert_tc`, then adopts its result as
        this model's document -- reseeding every field and recomputing :attr:`locked` (which drops to
        ``False``, since the result is never :attr:`~RehuDocument.legacy_tc`) -- so the same dock keeps
        showing the same resource, now unlocked, without a reload round-trip.

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
        self.__document = convert_tc(self.path, keep_backups=keep_backups, overwrite=overwrite)
        self.__seed_from_document()
        self.dirty = False
        self.locked = self.__document.format_version > CURRENT_FORMAT_VERSION or self.__document.legacy_tc
        self.image_scanner = RehuScanner(self)
        self.unknown_fields_changed.emit()

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

        The binding is read-only: an inactive block is carried verbatim and is not this file's to edit,
        so its setter refuses rather than writing. Whatever affordance an inactive block eventually gets
        (carry vs. drop) is A4.4's ([[plugins#fallback-editor]]) -- and the drop-on-abandon rule that
        governs it is A4.2's, so guessing at a setter here would be guessing at exactly the invariant
        those slices exist to settle.

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
            set_value=lambda _value: LOG.error("Refusing to edit inactive block %r: not editable until A4.4", name),
        )

    def unknown_field_names(self) -> list[str]:
        """The active plugin block's keys the model doesn't recognize ([[plugins#fallback-editor]], A2.8/#28).

        Every key in the active block ([[plugins#plugin-blocks]]) that isn't a known field
        (:data:`KNOWN_TYPE_FIELD_NAMES`) -- e.g. a field written by a newer plugin version than the one
        installed here. Carried verbatim on round-trip unless explicitly dropped via
        :meth:`remove_unknown_field`.

        :returns: the unknown keys, sorted for a stable display order.
        """
        return sorted(key for key in self.__document.active_block if key not in KNOWN_TYPE_FIELD_NAMES)

    def inactive_block_keys(self) -> list[str]:
        """The keys of this document's inactive plugin blocks ([[plugins#plugin-blocks]]).

        Every block the document's ``type`` doesn't name -- inactive **whether or not** its plugin is
        installed here, since only the type decides what is active. Each is carried verbatim on save; the
        collapsible, drop-capable fallback UI they eventually get is A4.4 ([[plugins#fallback-editor]]),
        which is why nothing here offers a way to edit or drop one --
        so for now they surface as read-only flagged rows.

        :returns: the inactive block keys, in document order.
        """
        return [block.key for block in self.__document.inactive_blocks()]

    def remove_unknown_field(self, name: str) -> None:
        """Drop an unknown active-block field, marking the model dirty ([[plugins#fallback-editor]], A2.8/#28).

        No-op if ``name`` isn't present, so a double remove (e.g. a stale button click) is harmless.

        :param name: the unknown block key to delete.
        """
        if self.__document.remove_active_field(name):
            self.unknown_fields_changed.emit()
            self.dirty = True

    def __seed_from_document(self) -> None:
        """Set every field from :attr:`document`'s current in-memory state (construction,
        :meth:`revert`, :meth:`convert`), guarded so it is never itself mistaken for a user edit."""
        self.__seeding = True
        try:
            self.path = self.__document.path
            self.location = self.__document.path.as_posix() if self.__document.path is not None else ""
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

            # The type-field scalar fields read/write generically through the type-keyed plugin block
            # ([[field-schema#resource-types]]); values are coerced defensively (malformed -> default,
            # [[data-model#write-integrity]]).
            # The fallback default comes from each field's own SimpleProperty declaration -- not a second,
            # hand-duplicated literal here -- so there is exactly one place per field to change its default.
            for name in TYPE_FIELD_BOOL_NAMES:
                default = SimpleProperty.default_value(type(self), name)
                setattr(self, name, bool(self.__document.active_field(name, default)))
            for name in TYPE_FIELD_INT_NAMES:
                default = SimpleProperty.default_value(type(self), name)
                value = self.__document.active_field(name, default)
                setattr(self, name, value if isinstance(value, int) and not isinstance(value, bool) else default)
            for name in TYPE_FIELD_STR_LIST_NAMES:
                default = SimpleProperty.default_value(type(self), name)
                value = self.__document.active_field(name, default)
                coerced = [item for item in value if isinstance(item, str)] if isinstance(value, list) else default
                setattr(self, name, coerced)
        finally:
            self.__seeding = False

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

    def __on_title_changed(self, value: str) -> None:
        """Write an edited title through to the document's primary source and mark dirty.

        No-op while the model is seeding (construction, :meth:`revert`, or :meth:`convert`) -- see the comment there.

        :param value: the new title.
        """
        if self.__seeding:
            return
        self.__document.title = value
        self.dirty = True

    def __on_authors_changed(self, value: list[str]) -> None:
        """Write an edited authors list through to the document and mark dirty.

        No-op while the model is seeding (construction, :meth:`revert`, or :meth:`convert`) -- see the comment there.

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

    def __on_released_changed(self, value: str) -> None:
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

    def __on_original_size_changed(self, value: int) -> None:
        """Write an edited original_size through to the document and mark dirty.

        No-op while the model is seeding (construction, :meth:`revert`, or :meth:`convert`) -- see the comment there.

        :param value: the new original_size.
        """
        if self.__seeding:
            return
        self.__document.original_size = value
        self.dirty = True

    def __on_current_size_changed(self, value: int) -> None:
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

        No-op while the model is seeding (construction, :meth:`revert`, or :meth:`convert`) -- see the comment there.

        :param key: the type-field key that changed.
        :param value: the new value.
        """
        if self.__seeding:
            return
        self.__document.set_active_field(key, value)
        self.dirty = True
