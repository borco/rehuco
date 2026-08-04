"""Reactive view-model wrapping a `RehuDocument` for the viewer/editor surfaces ([[plugins#view-model]])."""

# the model is one class per document, and most of its length is the per-field ``SimpleProperty``
# declarations and the docstrings that say what each field means -- splitting them off would put a
# field's declaration and its write-through handler in different files for no gain, so the
# module-length cap is lifted here rather than fragmenting the seam.
# pylint: disable=too-many-lines

import logging
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Final

from borco_pyside.core import SimpleProperty
from borco_pyside.logging import LogScope
from PySide6.QtCore import QObject, Signal
from rehuco_core import (
    CURRENT_FORMAT_VERSION,
    DEFAULT_CURRENT_USERNAME,
    FINISHED_JOB_STATES,
    FORMAT_VERSION_KEY,
    INFO_REHU_FILENAME,
    USERS_KEY,
    AuthorEntry,
    LockReason,
    RehuDocument,
    TaskQueue,
    convert_tc,
    rehu_rename_affects,
    rehu_rename_conflict,
    rename_rehu_resource,
    scan_rehu_screenshot_files,
    scan_tc_screenshot_files,
)

from ..fields.field import Field, FieldBinding
from ..fields.unknown_field import UnknownField
from .rehu_document_image_scanner import RehuDocumentImageScanner

LOG: Final = logging.getLogger(__name__)

# The three groups below are **coercion** groups: they say how a plugin-block value is read and written
# back, not which type owns it. Which fields a type *has* is the plugin's own declaration in core
# (`~rehuco_core.PluginSpec.field_names`, #195) -- so the model's SimpleProperty set stays whole and
# type-blind, and a document carrying a field its type doesn't declare still round-trips it. The two meet
# at :meth:`unknown_field_names`, which asks the declaration.
TYPE_FIELD_BOOL_NAMES: Final = ("complete", "online", "viewed", "todo", "keep", "favorite")
"""The type-field boolean flags ([[field-schema#boolean-flags]]); each name's default lives on its own
``SimpleProperty`` declaration below, read back generically via ``SimpleProperty.default_value``."""

TYPE_FIELD_INT_NAMES: Final = (
    "rating",
    "current_count",
    "original_duration",
    "current_duration",
    "advertised_duration",
)
"""The type-field integer fields ([[field-schema#field-types]]); ``rating`` may be negative, the
``*_duration`` fields are whole seconds ([[field-schema#ms-leak-history]]). Defaults live on each
``SimpleProperty`` declaration below, same as :data:`TYPE_FIELD_BOOL_NAMES`."""

TYPE_FIELD_STR_NAMES: Final = ("advertised_count",)
"""The type-field **optional string** fields ([[field-schema#field-types]]): absent reads as ``None``, not
``""``, and writing ``None`` removes the key, exactly as the optional integers above behave
([[field-schema#deferred-items]]). ``advertised_count`` is text rather than a number because the claim it
carries may be open-ended (``500+``, #198)."""

TYPE_FIELD_STR_LIST_NAMES: Final = ("level",)
"""The type-field string-list fields ([[field-schema#field-types]]); ``level`` is multi-choice, not a
mutually-exclusive single value -- tc4 could tag more than one of beginner/intermediate/advanced/any
at once. Defaults live on each ``SimpleProperty`` declaration below, same as :data:`TYPE_FIELD_BOOL_NAMES`."""

USER_FIELD_NAMES: Final = frozenset(("rating", "viewed", "todo", "keep", "favorite"))
"""The subset of the groups above that is **per-user** ([[field-schema#per-user-shared]], #99): these
route through the document's per-user accessors (`RehuDocument.active_user_field` /
`~RehuDocument.set_active_user_field` -- nested under the active block's ``users`` map, block layout
v1) instead of the shared inline ones. Mirrors the core importer's per-user set
(``tc_document``'s user fields), minus ``learning_paths`` -- a record list, not a scalar of these groups,
and one whose *visible* set spans several identities (this one's own entries, its subscriptions, and the
reserved ``public`` scope), so it resolves through :attr:`~RehuDocument.learning_paths` rather than the
single-identity accessors this set routes through."""

RECORD_LIST_FIELD_NAMES: Final = ("collections", "learning_paths")
"""The active block's two **record-list** fields ([[field-schema#sources]],
[[field-schema#learning-path-ownership]]), wired to :meth:`RehuDocumentModel.__on_record_list_changed`.

A group of their own rather than members of :data:`TYPE_FIELD_STR_LIST_NAMES` and friends, because
neither is a coercion group's shape: a collection membership is a *record* with keys no editor here shows,
and a learning path is a record whose **scope** is half its meaning. Each therefore routes through the
document's own accessor pair rather than the generic block writers -- which is also what keeps the
absent-not-empty rule and the scope bookkeeping in one place instead of two (#235)."""

COMMON_FIELD_NAMES: Final = (
    "title",
    "authors",
    "publisher",
    "url",
    "released",
    "description",
    "hidden_images",
    "original_size",
    "current_size",
    "advertised_tags",
    "extra_tags",
)
"""The common-core, non-type-scoped fields that write straight through to the document's own attribute
of the same name on edit ([[field-schema#field-mapping]]), wired generically in a loop (:meth:`__init__`)
to :meth:`__on_common_field_changed` -- the same shape :data:`TYPE_FIELD_BOOL_NAMES` et al. use for
:meth:`__on_type_field_changed`. Excludes `resource_type`: a type switch
(:meth:`__on_resource_type_changed`) claims a plugin block and reseeds the whole active block, not a
plain write-through.

The **write-through** subset of the core block's own declaration
(:data:`~rehuco_core.CORE_FIELD_NAMES`): ``created``/``updated`` are core fields too, but they are stamped
by the document rather than edited, so they carry no `SimpleProperty` and no handler here."""


UNTITLED_LABEL: Final = "Untitled"
"""Stand-in display label for a document with no path yet -- :attr:`RehuDocumentModel.label` is empty
for one, and every dialog that names a document falls back to this, so the wording lives in one place."""


def path_label(path: Path) -> str:
    """The `info.rehu`-aware display label for ``path`` ([[data-model#resource-scoping]]): the parent
    directory's name, trailing-slashed, for `info.rehu`; the bare filename otherwise. Shared by
    :attr:`RehuDocumentModel.label` and the recents menu (#117), so the rule lives in exactly one place.

    :param path: the file path to derive a label for.
    :returns: the label.
    """
    return f"{path.parent.name}/" if path.name == INFO_REHU_FILENAME else path.name


class RehuDocumentModel(QObject):  # pylint: disable=too-many-instance-attributes
    """Reactive `QObject` over one `RehuDocument`, exposing common-core fields and a dirty flag
    ([[plugins#view-model]]).

    The viewer/editor surfaces bind to this instead of touching `RehuDocument` ([[data-model]]) directly, keeping
    the core non-GUI ([[plugins#core-vs-plugin]]). Setting ``title`` / ``publisher`` / ``url`` writes
    through to the document's **primary** source ([[field-schema#sources]]), marks the model dirty,
    and emits the field's ``<name>_changed`` signal -- which is what makes live "both" work: an edit
    in the editor updates the model, whose signal the viewer is bound to. ``sources`` is exposed as
    the list it is; the
    multi-source record-list editor is a later slice (#26) that plugs into this seam. ``authors``
    / ``advertised_tags`` / ``extra_tags`` are common-core top-level lists, not source-scoped, so they
    write straight through to the document instead of through the primary source (#23).
    :meth:`revert` is the write-through's mirror image: it re-reads the document from disk and
    reseeds every field, guarded so reseeding is never itself treated as an edit (#41).

    :param document: the document to wrap.
    :param parent: optional Qt parent.
    :param task_queue: the engine :meth:`rename_lock_reason` asks whether a rename is currently safe
        (#240); ``None`` -- most tests, and any caller with no queue to offer -- leaves a rename never
        locked by this.
    """

    unknown_fields_changed = Signal()
    """Fires when the set of unrecognized active-block fields changes -- i.e. one is dropped via
    :meth:`remove_unknown_field` ([[plugins#fallback-editor]], #28)."""

    reloaded = Signal()
    """Fires when the document's **file seam** was crossed -- the bytes this model stands for were
    re-read or replaced wholesale: every :meth:`revert` (re-reads the file) and every :meth:`convert`
    (writes a new ``.rehu`` and adopts it, [[acquisition-tooling#tc-to-rehu]]). Unlike the property
    notify signals, it is emitted **unconditionally**, because crossing the seam is the event -- a
    revert of a *clean, unlocked* document changes no property at all (``dirty`` was already ``False``,
    ``path`` and ``lock_reasons`` reseed to equal values) yet the file underneath may have just been
    edited out of band, which is exactly the workflow Revert advertises. `OnDiskView` re-reads on it
    (#174); a consumer that only cares whether a *value* moved should bind to that value's own notify
    signal instead."""

    rename_lock_reason_changed = Signal()
    """Fires when the task queue changes in a way that might change :meth:`rename_lock_reason`'s answer
    (#240). Emitted by :meth:`refresh_rename_lock_reason`, called by the owner (`DocumentsDock`) rather
    than this model watching the queue itself -- one queue listener for every open document, the same
    shape `TaskQueueStore`/`TaskQueueWidget` use for the whole app rather than one per consumer."""

    active_block_changed = Signal()
    """Fires when the whole field composition must be re-resolved from scratch: the outgoing block's
    editors go away, the incoming block's fields render, and the set of unknown-field and inactive-block
    rows (with their provenance and carry-vs-drop wiring) is rebuilt ([[plugins#plugin-blocks]], #83,
    #84). Two seams raise it -- a type switch (:meth:`__on_resource_type_changed`) and every
    :meth:`revert` (a reload can change the active type, its unknown fields, and the inactive-block fates
    at once, so revert rebuilds unconditionally rather than deciding which moved). Distinct from
    :attr:`unknown_fields_changed` (a single fallback field dropped) because that stays within a
    composition the reactive rows can show/hide, whereas this adds, removes, and re-wires whole rows --
    so ``DocumentWidget`` rebuilds its dock contents on it. Plain seeding does not raise it."""

    path = SimpleProperty[Path | None](None)
    """The document's current file path, mirroring :attr:`document`'s own path -- reassigned whenever
    it changes (construction, :meth:`revert`, :meth:`convert`, and a completed :meth:`rename_location`),
    so a consumer that needs to react to the document's identity changing (e.g. `DocumentsDock`
    resyncing a dock's persisted identity) can bind to `path_changed` instead of polling it."""

    location = SimpleProperty("")
    """The document's file location, seeded from :attr:`path` ([[field-schema#field-mapping]]'s derived
    folder/location links). The viewer binds to it (rendered as a native-path link); it is not edited
    directly -- :meth:`rename_location` is the only thing that changes it, and only once the rename on
    disk has actually succeeded ([[plugins#toolkit-surfaces]]'s read-only projection)."""

    rename_error = SimpleProperty("")
    """Why the last :meth:`rename_location` attempt failed, or empty when none has failed since
    ([[plugins#toolkit-surfaces]]). Surfaced as an inline `MessageBanner` row (#94) rather than a modal,
    like every other condition this document reports: a failed rename leaves the document exactly as it
    was, so there is nothing to interrupt the user for -- the name they picked simply isn't on disk, and
    the suggestion list they picked it from is still right there. Cleared at the **start** of every
    attempt, so the strip always shows the current attempt's outcome and a retry that succeeds takes the
    row away -- and at the file seams, :meth:`revert` and :meth:`convert`, since a revert is defined to
    leave the model exactly as a fresh open would, and a fresh open carries no failed attempt."""

    resource_type = SimpleProperty("")
    """The document's resource type ([[field-schema#resource-types]]) -- the key of its **active**
    plugin block ([[plugins#plugin-blocks]]). Editing it is a **type switch** (#83): the write-through
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

    current_count = SimpleProperty[int | None](None)
    """The **measured** ReferenceImages content-image count ([[field-schema#field-types]]) -- what counting
    the resource's archives finds ([[data-model#resource-scoping]]) -- or ``None`` when not yet scanned
    ([[field-schema#deferred-items]]). Filled only by an explicit measure-and-apply
    (:class:`~rehuco_agent.fields.content_count_field.ContentCountField`), never on open: a stored count
    disagreeing with the archive is evidence of a refreshed zip, which silently overwriting would
    destroy ([[data-model#image-meanings]], #198)."""

    advertised_count = SimpleProperty[str | None](None)
    """The pack's **own claim** about its image count ([[field-schema#field-types]]), as text so an
    open-ended ``500+`` stays the weaker claim it is, or ``None`` when absent
    ([[field-schema#deferred-items]]). Nothing measures it -- :attr:`current_count` is the measured half."""

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

    collections = SimpleProperty[list[dict[str, Any]]](default_factory=list)
    """The resource's collection memberships **as stored** ([[field-schema#sources]]) -- the records
    themselves, in stored order, not the sorted ``(index, title)`` projection the viewer shows.

    The records rather than the projection because #235's memberships table has to write one back
    *merged*: a title cell that rebuilt its entry from the two columns it can see would drop the ``url``
    the collection owns and any key a later version adds, on an entry nobody meant to touch. Only the
    stored record carries those. The projection is still where display order comes from -- the field
    computes it (:func:`~rehuco_core.collection_entries`), so this property never has to decide what a
    viewer's order is."""

    learning_paths = SimpleProperty[dict[str, list[dict[str, Any]]]](default_factory=dict)
    """The active block's learning-path records **as stored**, keyed by scope
    ([[field-schema#learning-path-ownership]]).

    Every scope, not just the visible ones: *what is in this file* is a different question from *what am I
    in*, and the editor's all-scopes view is the one that asks it -- while the viewer resolves the second
    from the same value (:func:`~rehuco_core.visible_learning_paths`, given this document's identity).
    Stored records for the same reason :attr:`collections` holds them, plus one this field has of its own:
    ownership here is expressed by *where a record sits and what it carries*, so a projection that
    flattened the scopes away would have thrown out the field's whole subject.

    Not the block's ``users`` map, which also holds the ratings and per-user flags this field is not about
    -- the document hands out the learning-path slice of it and takes that slice back
    (:attr:`~RehuDocument.learning_path_records`)."""

    advertised_tags = SimpleProperty[list[str]](default_factory=list)
    """The web-scraped ``advertised_tags`` list ([[field-schema#field-mapping]])."""

    extra_tags = SimpleProperty[list[str]](default_factory=list)
    """The personal ``extra_tags`` list ([[field-schema#field-mapping]])."""

    hidden_images = SimpleProperty[list[str]](default_factory=list)
    """The screenshot filenames curated *out* of the lightbox ([[data-model#image-meanings]], #27); a
    top-level common-core list. The lightbox shows every ``RehuDocumentImageScanner.files()`` sibling by default, so
    only the hidden exceptions are stored -- the editor's checkboxes are the inverse (checked = visible)."""

    dirty = SimpleProperty(False)
    """True when the model holds edits not yet saved to disk."""

    saved_on_disk = SimpleProperty(True)
    """Whether this document has ever been persisted to its path -- i.e. whether there is a file on disk
    to revert to. ``True`` for a **loaded** document (it stands for a file on disk -- even one that later
    goes missing out-of-band, whose revert is the fix-retry loop, [[data-model#write-integrity]]);
    ``False`` for a brand-new document (:meth:`create_new`) bound to a path that does not exist on disk
    yet. ``DocumentWidget`` keeps its Revert action **disabled** while this is ``False`` (#147): reverting
    a not-yet-written path would re-read a file that isn't there, replacing the editable in-memory
    document with an empty **locked** ``MISSING`` stub and silently discarding the edits. Set ``True``
    only forward, by the first :meth:`save`; a revert never touches it, since a not-yet-saved document
    can't be reverted at all."""

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

    image_scanner = SimpleProperty[RehuDocumentImageScanner | None](None)
    """The current screenshot-resolution scanner -- a `RehuDocumentImageScanner` over `scan_tc_screenshot_files`
    while :attr:`~RehuDocument.legacy_tc`, over `scan_rehu_screenshot_files` once converted or genuinely
    `.rehu`-native. `ImageStrip`/`ImageSelector`/`MarkdownView` each hold their own copy and bind to
    `image_scanner_changed` to pick up a `.tc` -> `.rehu` conversion's switch in naming convention
    without rebuilding the field composition ([[acquisition-tooling#tc-to-rehu]])."""

    def __init__(
        self, document: RehuDocument, parent: QObject | None = None, *, task_queue: TaskQueue | None = None
    ) -> None:
        super().__init__(parent)
        self.__document = document
        self.__task_queue: Final = task_queue

        self.__seeding = False
        """True only while :meth:`__seed_from_document` is applying field values pulled from the
        document -- guards every write-through handler below so a seed is never mistaken for a user
        edit."""

        self.__seed_from_document()
        self.lock_reasons = list(self.__document.lock_reasons)
        self.image_scanner = self.__make_image_scanner()
        self.__recompute_upgradable()
        self.__log_document_state()

        # a live edit toggles dirty, and a lock can appear/clear outside revert/convert too (tests
        # assign lock_reasons directly to simulate one) -- both must hide/reveal the upgrade offer
        # immediately, not just at the next explicit recompute seam below
        self.dirty_changed.connect(lambda _dirty: self.__recompute_upgradable())  # type: ignore[attr-defined]
        self.lock_reasons_changed.connect(lambda _reasons: self.__recompute_upgradable())  # type: ignore[attr-defined]

        self.resource_type_changed.connect(self.__on_resource_type_changed)  # type: ignore[attr-defined]
        for name in COMMON_FIELD_NAMES:
            signal_name = SimpleProperty.notify_signal_name(type(self), name)
            getattr(self, signal_name).connect(lambda value, key=name: self.__on_common_field_changed(key, value))
        for name in (*TYPE_FIELD_BOOL_NAMES, *TYPE_FIELD_INT_NAMES, *TYPE_FIELD_STR_NAMES, *TYPE_FIELD_STR_LIST_NAMES):
            signal_name = SimpleProperty.notify_signal_name(type(self), name)
            getattr(self, signal_name).connect(lambda value, key=name: self.__on_type_field_changed(key, value))
        for name in RECORD_LIST_FIELD_NAMES:
            signal_name = SimpleProperty.notify_signal_name(type(self), name)
            getattr(self, signal_name).connect(lambda value, key=name: self.__on_record_list_changed(key, value))

    @classmethod
    def create_new(
        cls,
        path: Path | str | None = None,
        parent: QObject | None = None,
        *,
        username: str = DEFAULT_CURRENT_USERNAME,
        task_queue: TaskQueue | None = None,
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
        :param task_queue: forwarded to the constructor; see its own docstring (#240).
        :returns: the new model, wrapping a fresh in-memory `RehuDocument` that already carries its own
            ``id`` (:meth:`~rehuco_core.RehuDocument.new`, [[data-model#stable-identity]]). Starts **not**
            :attr:`saved_on_disk` -- it has never been persisted to its path, so Revert is disabled until
            the first :meth:`save` (#147).
        """
        model = cls(RehuDocument.new(path, username=username), parent, task_queue=task_queue)
        model.saved_on_disk = False
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
        return path_label(path)

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
        with LogScope.open(self.path):
            self.__document.save()
            LOG.info("Saved %s", self.path)
        self.dirty = False
        # the file now exists on disk, so there is finally something to revert to: mark saved_on_disk so
        # DocumentWidget re-enables Revert (#147). Set once and never unset -- a later out-of-band
        # deletion still leaves this a document that *was* saved, whose revert is the fix-retry loop.
        self.saved_on_disk = True
        # explicit, not left to the dirty_changed connection alone: a clean-but-upgradable document
        # (the Upgrade path) saves without dirty ever having been True, so no dirty_changed would fire
        self.__recompute_upgradable()

    def rename_conflicts(self, new_name: str) -> bool:
        """Whether renaming to ``new_name`` would land on something already there
        ([[plugins#toolkit-surfaces]]).

        What lets the editor show an unavailable candidate as unavailable -- disabled, and colored --
        instead of offering a click that can only fail. Advisory by design
        (:func:`~rehuco_core.rehu_rename_conflict`): it answers the collision the user can see coming,
        another resource already sitting under that name, and leaves the authoritative whole-plan check
        to :meth:`rename_location`.

        :param new_name: the candidate folder/file name.
        :returns: whether something already occupies the destination; ``False`` for a document with no
            location yet, which has no destination to compare against.
        """
        path = self.path
        if path is None:
            return False
        return rehu_rename_conflict(path, new_name) is not None

    def rename_lock_reason(self) -> str | None:
        """Why the location editor must refuse a rename right now, or ``None`` when it may proceed
        (#240).

        Exact, not merely cautious: refused only while an *unfinished* job's own ``source`` sits among
        the paths this resource's rename would actually move
        (:func:`~rehuco_core.rehu_rename_affects`) -- a directory-scoped resource locks on a job
        anywhere beneath its directory (a nested resource, or a file-scoped sibling directly inside it,
        since renaming the directory carries both along); a file-scoped resource locks only on its own
        sibling set, never on an unrelated ``.rehu`` beside it. A ``done``/``failed``/``cancelled`` job
        is kept in the queue but is not about to touch anything, so it locks nothing
        (:data:`~rehuco_core.FINISHED_JOB_STATES`).

        A directory that cannot be listed -- an offline mount
        ([[mounts-and-storage#offline-mounts]]), reachable only through a file-scoped resource's
        sibling sweep -- reads as **unlocked**: a rename attempted there fails cleanly through
        :attr:`rename_error` anyway, where a lock would claim a busy job this model cannot actually
        see.

        :returns: a one-sentence reason, or ``None`` -- including when this document has no location
            yet, or was opened with no task queue at all.
        """
        path = self.path
        if path is None or self.__task_queue is None:
            return None
        try:
            for status in self.__task_queue.jobs():
                if status.source is None or status.state in FINISHED_JOB_STATES:
                    continue
                if rehu_rename_affects(path, status.source):
                    return "A queued task is still working on this resource -- rename it once that finishes."
        except OSError:
            return None
        return None

    def refresh_rename_lock_reason(self) -> None:
        """Re-announce that :meth:`rename_lock_reason` may have a new answer (#240): called by the
        owner (`DocumentsDock`) whenever the task queue changes in a way worth re-checking."""
        self.rename_lock_reason_changed.emit()

    def rename_location(self, new_name: str) -> bool:
        """Rename this resource to ``new_name`` -- clicked from a `PathField` rename suggestion.

        Orchestration only ([[plugins#toolkit-surfaces]]'s **execute** role): the intent is logged
        *before* anything is attempted (so the log reflects what was asked for even if it then fails),
        a dirty document is saved first (so the files actually being moved are never stale), and the
        rename itself is delegated to :meth:`__move`, which performs it and adopts the new location.

        A document that has **never been saved** renames perfectly well: it is born dirty
        (:meth:`create_new`), so the save below writes its ``.rehu`` at the location it was bound to
        (``folder/info.rehu``, or an archive's ``foo.rehu`` companion) and the rename then finds a real
        file to move. Not being on disk *yet* is a reason to write it first, never a reason to refuse --
        what is refused is a document with no location at all, which no route through the app currently
        produces (both openers bind a path; there is no File > New).

        **Every failure leaves the document exactly as it was** and reports through
        :attr:`rename_error` plus a ``False`` return: a document with no location at all, a pre-move
        save that is refused (an ``OSError`` such as an offline mount, or the ``ValueError``
        :meth:`~RehuDocument.save` raises for a locked document -- either way it simply stays dirty and
        nothing is moved), a resource whose file has since gone missing (refused by
        :func:`~rehuco_core.rename_rehu_resource` before anything is attempted), or the rename itself.
        There is no half-done outcome to recover from -- that function rolls its own multi-file plan
        back, and the one case it cannot (`PartialRenameError`) says so in the message it carries, which
        is the message this model then shows.

        A banner row, not a dialog: a retry/cancel dialog
        (:func:`~rehuco_agent.documents.save_or_prompt_retry.save_or_prompt_retry`, #146) needs a widget
        to parent to, which a `QObject` doesn't have -- but a failed rename also has nothing to
        interrupt for, since the suggestion list that produced the name is still on screen.

        :param new_name: the destination file/folder name (already sanitized by the caller, e.g. a
            clicked `PathField` suggestion).
        :returns: whether the rename succeeded.
        """
        # scoped to the path being renamed *from*: every record here is about the resource as it stands
        # now, including the failure ones, and the sink for the new path only exists once the move landed
        with LogScope.open(self.path):
            LOG.info("Attempting to rename %r to %r", self.current_name, new_name)
            self.rename_error = ""
            if self.path is None:
                return self.__rename_failed(f'Cannot rename to "{new_name}": this document has no location yet.')
            if self.dirty:
                try:
                    self.save()
                except (OSError, ValueError) as error:
                    return self.__rename_failed(
                        f'Could not save "{self.current_name}" before renaming it: {self.__failure_reason(error)}'
                    )
            return self.__move(new_name)

    def revert(self) -> None:
        """Discard in-memory edits and reseed every field from the document's file on disk.

        Re-reads the file (:meth:`RehuDocument.reload`) rather than just resetting to the
        last-loaded snapshot, so an out-of-band edit ([[data-model#write-integrity]]) is picked up
        too. :meth:`__seed_from_document` guards itself against the reseed looking like an edit --
        no write-back to the document, and :attr:`dirty` ends up ``False`` regardless of what it was.

        **A revert always rebuilds the form** ([[plugins#plugin-blocks]], #83): it fires
        :attr:`active_block_changed` unconditionally, so the whole composition re-resolves from the
        reloaded document -- a revert is defined to leave the model exactly as a fresh open would. A reload
        can change the active type, the active block's unknown fields, and the inactive-block fates
        (claimed-then-abandoned blocks revert to carried foreign, regaining their drop button, #84)
        all at once, and only a full rebuild re-wires a row's provenance and carry-vs-drop button -- the
        reactive rows can only show/hide and re-read a value, never re-wire. Rather than enumerate which
        structural axis moved (a check that has to stay exhaustive as axes are added), the coarse,
        user-driven revert just rebuilds; the cost is negligible and it is correct by construction.

        ``unknown_fields_changed`` is emitted too, for consumers that don't rebuild on
        :attr:`active_block_changed` -- the source-preview docks re-serialize off it (#111), and it also
        covers restored unknown active-block fields ([[plugins#fallback-editor]], #28). :attr:`reloaded`
        fires too, for the file seam itself: reverting a *clean, unlocked* document moves no property at
        all, so it is the only signal telling `OnDiskView` the bytes it shows may be stale (#174).

        :raises ValueError: if the document has no path (was never loaded from or saved to a file).
        """
        with LogScope.open(self.path):
            self.__document.reload()
            LOG.info("Reverted %s to what is on disk", self.path)
        self.__seed_from_document()
        self.dirty = False
        self.rename_error = ""
        self.lock_reasons = list(self.__document.lock_reasons)
        self.unknown_fields_changed.emit()
        self.active_block_changed.emit()
        self.reloaded.emit()
        self.__recompute_upgradable()
        self.__log_document_state()

    def convert(self, *, keep_backups: bool, overwrite: bool = False) -> None:
        """Convert this locked, legacy ``.tc``-backed document into a real ``.rehu`` in place
        ([[acquisition-tooling#tc-to-rehu]]).

        Delegates the file-system work to :func:`rehuco_core.convert_tc`, then adopts its result as
        this model's document -- reseeding every field and recomputing :attr:`locked` (which drops to
        ``False``, since the result is never :attr:`~RehuDocument.legacy_tc`) -- so the same dock keeps
        showing the same resource, now unlocked, without a reload round-trip. The conversion files
        the imported per-user flags under this document's **own** username -- the identity it was
        opened with, which for a legacy ``.tc`` is the **unknown** user (#109) -- so the block's
        ``users`` key and the result's :attr:`~RehuDocument.username` stay in agreement (#98's
        invariant); an identity-setting change made after this document was opened applies to later
        opens, not to it (#99).

        Emits :attr:`reloaded` on success -- the other half of the file seam :meth:`revert` raises, since
        this too replaces the file the model stands for (the ``.tc`` becomes a ``.rehu``, #174).

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
        with LogScope.open(self.path):
            LOG.info("Converting %s, %s", self.path, "keeping backups" if keep_backups else "discarding originals")
            self.__document = convert_tc(
                self.path, keep_backups=keep_backups, overwrite=overwrite, username=self.__document.username
            )
            LOG.info("Converted to %s", self.__document.path)
        self.__seed_from_document()
        self.dirty = False
        self.rename_error = ""
        self.lock_reasons = list(self.__document.lock_reasons)
        self.image_scanner = self.__make_image_scanner()
        self.unknown_fields_changed.emit()
        self.reloaded.emit()
        self.__recompute_upgradable()
        self.__log_document_state()

    def bind[T](self, field: Field[T], name: str | None = None) -> FieldBinding[T]:
        """Resolve one of a field's names into its current binding on this model
        ([[plugins#field-toolkit]], `FieldModel`).

        :param field: the field to resolve for; the name resolved matches either a `SimpleProperty`
            declared on this class or an unrecognized key in the active plugin block (an unknown field,
            [[plugins#fallback-editor]]).
        :param name: which of :attr:`~Field.names` to resolve -- passed explicitly by a composite over
            several model fields (the size pair, #232); :attr:`~Field.name` when omitted, which is every
            other field.
        :returns: the named value's current value, its notify signal, and a setter.
        """
        name = field.name if name is None else name
        # an `UnknownField` never binds a property, even when its name collides with a declared one --
        # possible since recognition went per-type (#195): a tutorial block's stray ``current_count`` is
        # unknown *here* while still being a property of the model. The property read is coerced (and,
        # for a per-user name, resolved through the ``users`` map rather than the stray inline key), so
        # binding it would fabricate a value the file never carried -- where the fallback's whole
        # contract is verbatim ([[plugins#fallback-editor]]).
        if not isinstance(field, UnknownField):
            try:
                signal_name = SimpleProperty.notify_signal_name(type(self), name)
            except KeyError:
                pass
            else:
                return FieldBinding(
                    value=getattr(self, name),
                    changed=getattr(self, signal_name),
                    set_value=lambda value: setattr(self, name, value),
                )
        # not a declared property (or deliberately not bound as one) -> a key carried verbatim and
        # surfaced through the generic fallback ([[plugins#fallback-editor]]). Two different things
        # reach here and they sit at different depths in the document: a whole **inactive block** is a
        # top-level key, while an **unknown field** is a key inside the active block -- so which one
        # this is has to be settled before reading a value, or an inactive block would read as an
        # absent field.
        inactive_block = self.__inactive_block_binding(name)
        if inactive_block is not None:
            return inactive_block
        return FieldBinding(
            value=self.__document.active_field(name),
            changed=self.unknown_fields_changed,
            set_value=lambda value: self.__document.set_active_field(name, value),
        )

    def __inactive_block_binding(self, name: str) -> FieldBinding[Any] | None:
        """Resolve ``name`` as a whole inactive plugin block, when it is one ([[plugins#plugin-blocks]]).

        The binding is read-only by design: the fallback editor's only affordance on an inactive block is
        **carry or drop**, never edit-in-place ([[plugins#fallback-editor]], #84) -- its *values* are
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
        """The active plugin block's keys the model doesn't recognize ([[plugins#fallback-editor]], #28).

        Every key in the active block ([[plugins#plugin-blocks]]) that the **active type** doesn't
        declare (`~rehuco_core.PluginRegistry.field_names`, #195) -- e.g. a field written by a newer
        plugin version than the one installed here. Recognition is per type, the same declaration the
        form composes from (`composed_field_specs`), because the two must agree: a key no type declares
        is a key no editor row renders, so anything short of surfacing it here would leave a value in the
        file with nowhere on screen to see or drop it. A ``tutorial`` block carrying ``current_count``
        therefore falls back rather than rendering an empty ReferenceImages row, and a type whose plugin
        isn't installed here declares nothing, so its whole block reaches the fallback.

        Carried verbatim on round-trip unless explicitly dropped via
        :meth:`remove_unknown_field`. The block's own ``format_version`` stamp (#81,
        [[plugins#plugin-blocks]]) is excluded -- it is block-management bookkeeping, not a resource
        field, the same way the file-wide stamp never shows up as an unknown *common* field either.
        The block's ``users`` map (:data:`~rehuco_core.USERS_KEY`, #98/#99) is excluded for the same
        reason -- it is the per-user storage *structure*, not a resource field; what's inside it
        surfaces only through the declared per-user properties (:data:`USER_FIELD_NAMES`), never
        through the generic fallback.

        :returns: the unknown keys, sorted for a stable display order.
        """
        declared = self.__document.plugins.field_names(self.__document.type)
        return sorted(
            key
            for key in self.__document.active_block
            if key not in declared and key not in (FORMAT_VERSION_KEY, USERS_KEY)
        )

    def inactive_block_keys(self) -> list[str]:
        """The keys of this document's inactive plugin blocks ([[plugins#plugin-blocks]]).

        Every block the document's ``type`` doesn't name -- inactive **whether or not** its plugin is
        installed here, since only the type decides what is active. Each is carried verbatim on save
        unless explicitly dropped (:meth:`drop_inactive_block`, #84) -- its *values* are never edited
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
        #83).

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
        """The resource types offerable in the type selector ([[plugins#plugin-blocks]], #83).

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
        """Drop an unknown active-block field, marking the model dirty ([[plugins#fallback-editor]], #28).

        No-op if ``name`` isn't present, so a double remove (e.g. a stale button click) is harmless.

        :param name: the unknown block key to delete.
        """
        if self.__document.remove_active_field(name):
            self.unknown_fields_changed.emit()
            self.dirty = True

    def drop_inactive_block(self, name: str) -> None:
        """Drop a whole inactive plugin block the user chooses not to carry ([[plugins#fallback-editor]],
        #84).

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

    def __log_document_state(self) -> None:
        """Write a record for everything the inline notice banner would show about this document (#200).

        **Banner parity.** ``DocumentWidget.__banner_rows`` builds its rows from exactly three sources:
        :attr:`lock_reasons`, :attr:`upgradable`, and :attr:`rename_error`. The first two are written
        here, in the same words the banner uses, so a reader who dismissed a banner -- or never had one
        on screen, because the dock was closed -- can still find out why a document is locked. The third
        needs nothing: :meth:`__rename_failed` already logs it where it happens, which is also the only
        place it becomes true.

        Called from the three seams that recompute this document's state -- construction, revert and
        convert -- and deliberately **not** from :attr:`lock_reasons`'s getter, which is read on every
        repaint: a record per transition is a log, a record per paint is a flood.

        A lock is a **warning**: the document is intact and inspectable, and the banner names the remedy.
        The upgrade offer is an **info** for the same reason it is an info in the banner -- nothing is
        wrong, there is simply something better available.
        """
        with LogScope.open(self.path):
            for reason in self.lock_reasons:
                LOG.warning("%s", reason.message)
            if self.upgradable:
                LOG.info("An older format: saving this document upgrades it")

    @contextmanager
    def __seeding_guard(self) -> Generator[None]:
        """Hold :attr:`__seeding` for the duration of the block, so a document-driven reseed is never
        mistaken for a user edit (#41). One guard shared by every seeding site below, instead of each
        hand-rolling its own ``try``/``finally``."""
        self.__seeding = True
        try:
            yield
        finally:
            self.__seeding = False

    def __seed_from_document(self) -> None:
        """Set every field from :attr:`document`'s current in-memory state (construction,
        :meth:`revert`, :meth:`convert`), guarded so it is never itself mistaken for a user edit."""
        with self.__seeding_guard():
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

    def __seed_active_block_fields(self) -> None:
        """Set the type-field scalars from the **active** block's current state -- shared by the full
        :meth:`__seed_from_document` reseed and the narrower one a type switch needs.

        A type switch (:meth:`__on_resource_type_changed`) re-reads *only* these block-scoped scalars
        from the newly-active block ([[plugins#plugin-blocks]], #83), leaving the common-core
        fields (title/publisher/...) untouched, so it calls this alone rather than the whole reseed.
        Callers set the :attr:`__seeding` guard themselves; this never writes back to the document, so a
        reseed is never mistaken for an edit.

        The type-field scalar fields read/write generically through the type-keyed plugin block, each
        through its own accessor -- per-user names via the users map, the rest inline
        ([[field-schema#resource-types]]); values are coerced defensively (malformed -> the field's own
        fallback -- its declared default for bool/str-list, ``None`` for the optional-scalar ints,
        matching core's own absent-vs-malformed treatment, [[data-model#write-integrity]]). The
        bool/str-list fallback comes from each field's own `SimpleProperty` declaration -- not a second,
        hand-duplicated literal here -- so there is exactly one place per field to change its default. The
        optional strings (:data:`TYPE_FIELD_STR_NAMES`) fall back to ``None`` for the same reason the ints
        do: absent is not ``""`` any more than it is ``0``.
        """
        for name in TYPE_FIELD_BOOL_NAMES:
            default = SimpleProperty.default_value(type(self), name)
            setattr(self, name, bool(self.__read_field(name, default)))
        for name in TYPE_FIELD_INT_NAMES:
            value = self.__read_field(name, None)
            setattr(self, name, value if isinstance(value, int) and not isinstance(value, bool) else None)
        for name in TYPE_FIELD_STR_NAMES:
            value = self.__read_field(name, None)
            setattr(self, name, value if isinstance(value, str) else None)
        for name in TYPE_FIELD_STR_LIST_NAMES:
            default = SimpleProperty.default_value(type(self), name)
            value = self.__read_field(name, default)
            coerced = [item for item in value if isinstance(item, str)] if isinstance(value, list) else default
            setattr(self, name, coerced)
        # the record lists take the document's own record accessors whole rather than a generic block read
        # plus a coercion here: *which* keys a membership record may carry is not this model's to decide
        # (that is the merge contract, #235), and *where* a learning path sits is half of what it means
        # ([[field-schema#learning-path-ownership]]), so the scope keying belongs to the document too
        self.collections = self.__document.collection_records
        self.learning_paths = self.__document.learning_path_records

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
        """Rename this document's file(s) to ``new_name`` on disk and adopt the result.

        The filesystem work -- which files each resource scope owns, the collision check, the rollback
        ([[data-model#resource-scoping]], [[data-model#write-integrity]]) -- belongs to
        :func:`~rehuco_core.rename_rehu_resource`, so all that is left here is *adopting* what it
        returns: the document is re-pointed at its new location (:meth:`~RehuDocument.rebind_path`),
        :attr:`path` and :attr:`location` reseed from it, and a fresh screenshot scanner is installed.
        :attr:`current_name` and :attr:`label` derive from :attr:`path`, so they follow on their own, as
        does the dock identity `DocumentsDock` resyncs off ``path_changed``.

        The scanner is **replaced** rather than left alone even though it reads the model's live path
        and so would already resolve the moved screenshots: replacing it is what emits
        ``image_scanner_changed``, which is the only thing telling the image strip and the Markdown
        viewer that the names they are holding are stale.

        Nothing here writes back to the document's payload, so a rename is not an edit: the model ends
        as clean as :meth:`rename_location`'s pre-move save left it.

        :param new_name: the destination file/folder name.
        :returns: whether the rename succeeded; a failure's reason is left in :attr:`rename_error`.
        """
        path = self.path
        if path is None:  # pragma: no cover -- rename_location refuses a path-less document before this
            return False
        current_name = self.current_name
        try:
            new_path = rename_rehu_resource(path, new_name)
        except (OSError, ValueError) as error:
            return self.__rename_failed(
                f'Could not rename "{current_name}" to "{new_name}": {self.__failure_reason(error)}'
            )
        self.__document.rebind_path(new_path)
        self.path = new_path
        self.location = new_path.as_posix()
        self.image_scanner = self.__make_image_scanner()
        LOG.info("Renamed %r to %r", current_name, new_name)
        return True

    def __rename_failed(self, message: str) -> bool:
        """Record a failed rename attempt: log it, and hand ``message`` to the banner channel.

        :param message: the user-facing explanation, a complete sentence.
        :returns: always ``False``, so a caller can ``return`` this directly as its own result.
        """
        LOG.error("%s", message)
        self.rename_error = message
        return False

    @staticmethod
    def __failure_reason(error: Exception) -> str:
        """The human-readable half of a failed rename's message.

        An ``OSError`` carries the operating system's own ``strerror`` ("Permission denied", "The
        process cannot access the file because it is being used by another process"), which reads far
        better in a banner than its full ``[Errno 13] ...: '/path/to/thing'`` rendering; anything else
        -- a refused name's ``ValueError``, or an error this codebase raised itself with a plain
        message -- has only its ``str``. Punctuated either way, so the caller's sentence closes cleanly
        whichever kind reached it.

        :param error: the failure to describe.
        :returns: the reason, ending in a period.
        """
        reason = getattr(error, "strerror", None) or str(error)
        return reason if reason.endswith(".") else f"{reason}."

    def __make_image_scanner(self) -> RehuDocumentImageScanner:
        """Build the screenshot scanner matching this document's current naming convention.

        Over `scan_tc_screenshot_files` while the document is :attr:`~RehuDocument.legacy_tc`, over
        `scan_rehu_screenshot_files` once converted or genuinely ``.rehu``-native
        ([[acquisition-tooling#tc-to-rehu]]). The one place that choice is made, so construction, a
        conversion, and a rename all install a scanner picked the same way.

        :returns: the scanner to assign to :attr:`image_scanner`.
        """
        lister = scan_tc_screenshot_files if self.__document.legacy_tc else scan_rehu_screenshot_files
        return RehuDocumentImageScanner(self, lister)

    def __on_resource_type_changed(self, value: str) -> None:
        """Switch the document's active type ([[plugins#plugin-blocks]], #83): claim the newly-active
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
            with self.__seeding_guard():
                self.resource_type = main
        with self.__seeding_guard():
            self.__seed_active_block_fields()
        self.dirty = True
        self.active_block_changed.emit()
        self.unknown_fields_changed.emit()

    def __on_common_field_changed(self, key: str, value: Any) -> None:
        """Write an edited common-core field through to the document's own attribute of the same
        name, and mark dirty.

        One handler for every :data:`COMMON_FIELD_NAMES` member: each just forwards ``value`` to
        `document`, so any field-specific behavior (e.g. `title`/`publisher`/`url` landing on the
        primary source, [[field-schema#sources]]; `authors` normalizing to canonical minimal form,
        [[field-schema#authors]]) stays owned by the document's own setter, not duplicated here.
        No-op while the model is seeding (construction, :meth:`revert`, or :meth:`convert`) -- see the
        comment there.

        :param key: the common field name that changed.
        :param value: the new value.
        """
        if self.__seeding:
            return
        setattr(self.__document, key, value)
        self.dirty = True

    def __on_type_field_changed(self, key: str, value: Any) -> None:
        """Write an edited type-field scalar through to the document's plugin block and mark dirty.

        A per-user key (:data:`USER_FIELD_NAMES`) lands in the block's ``users`` map under this
        document's own username, the rest inline in the block ([[field-schema#per-user-shared]],
        #99) -- the write half of :meth:`__read_field`'s split. ``None`` (only ever reachable for the
        optional-scalar members of :data:`TYPE_FIELD_INT_NAMES` and :data:`TYPE_FIELD_STR_NAMES` -- the
        bool/str-list fields never hold it) **removes** the key rather than writing a JSON ``null`` --
        ``set_active_field``/``set_active_user_field`` are generic value writers with no such rule of their own, unlike
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

    def __on_record_list_changed(self, key: str, value: Any) -> None:
        """Write an edited record list through to the document and mark dirty.

        One handler for both :data:`RECORD_LIST_FIELD_NAMES` members, each forwarded to the document's own
        writer for that field (:meth:`~rehuco_core.RehuDocument.set_collection_records` /
        :meth:`~rehuco_core.RehuDocument.set_learning_path_records`) rather than to the generic block
        writers :meth:`__on_type_field_changed` uses. That is where the rules live that a generic value
        write has none of: an emptied collections list removes its key instead of storing ``[]``, and a
        learning-path write spans every scope in the block, removing the key from one a path just left
        ([[field-schema#learning-path-ownership]]).

        No-op while the model is seeding (construction, :meth:`revert`, or :meth:`convert`) -- see the
        comment there. That guard matters more here than for a scalar: a seed assigns the very records it
        just read, so an unguarded write-through would dirty every document merely by opening it.

        :param key: the record-list field that changed.
        :param value: the new value -- the records for ``collections``, the scope-keyed mapping for
            ``learning_paths``.
        """
        if self.__seeding:
            return
        if key == "collections":
            self.__document.set_collection_records(value)
        else:
            self.__document.set_learning_path_records(value)
        self.dirty = True
