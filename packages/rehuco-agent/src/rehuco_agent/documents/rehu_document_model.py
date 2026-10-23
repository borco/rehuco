"""Reactive view-model wrapping a `RehuDocument` for the viewer/editor surfaces ([[plugins#view-model]])."""

# the model is one class per document, and most of its length is the per-field ``SimpleProperty``
# declarations and the docstrings that say what each field means -- splitting them off would put a
# field's declaration and its write-through handler in different files for no gain, so the
# module-length cap is lifted here rather than fragmenting the seam.
# pylint: disable=too-many-lines

import copy
import logging
from collections.abc import Callable, Generator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path
from typing import Any, Final, cast

from borco_core.logging import LogScope
from borco_pyside.core import ConnectionList, SimpleProperty
from PySide6.QtCore import QObject, Signal
from rehuco_core import (
    CURRENT_FORMAT_VERSION,
    DEFAULT_CURRENT_USERNAME,
    FORMAT_VERSION_KEY,
    USERS_KEY,
    AuthorEntry,
    Deleter,
    FieldPath,
    JobWaiting,
    LockReason,
    RecordConflict,
    RecordVersion,
    RehuDocument,
    RenameCoordinator,
    SaveOutcome,
    SavePayload,
    SaveRecordJob,
    is_directory_scoped_name,
    merge_users,
    paths_overlap,
    payload_changes,
    put_paths,
    rehu_rename_conflict,
    rename_rehu_resource,
    scan_rehu_screenshot_files,
    scan_unconverted_screenshots,
)
from rehuco_core.access import FileSignature, KeyRelocation, LoadedRecord, Records, ResourceKey
from rehuco_core.lock_reasons import SAVE_BLOCKING_LOCK_KINDS

from ..fields.field import Field, FieldBinding
from ..fields.unknown_field import UnknownField
from ..recycle_bin_deleter import configured_deleter
from ..settings.excluded_files_settings import shared_excluded_files_settings
from ..settings.screenshot_patterns_settings import shared_screenshot_patterns_settings
from .record_reader import RecordReader
from .rehu_document_image_scanner import RehuDocumentImageScanner
from .rename_holders import RenameHolderReport
from .tc_conversion_outcomes import scan_after_conversion

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

USER_STATE_FIELD_NAMES: Final = USER_FIELD_NAMES | {"learning_paths"}
"""Every field that holds the current user's own state: :data:`USER_FIELD_NAMES` and ``learning_paths``. What goes
read-only while the user's own sidecar cannot be read ([[data-model#single-file]], #568) -- the record's details do
not."""

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


PRIMARY_SOURCE_FIELD_NAMES: Final = ("title", "publisher", "url")
"""The members of :data:`COMMON_FIELD_NAMES` that are the **top source's own** values
([[field-schema#sources]]): writing one changes an entry of :attr:`RehuDocumentModel.sources`, which is
re-read after it so the list never lags its own top row."""

UNTITLED_LABEL: Final = "Untitled"
"""Stand-in display label for a document with no location -- :attr:`RehuDocumentModel.label` is empty
for one, and every dialog that names a document falls back to this, so the wording lives in one place."""


def key_label(key: ResourceKey) -> str:
    """The scope-aware display label for the record at ``key`` ([[data-model#resource-scoping]]): the parent
    directory's name, trailing-slashed, for a directory-scoped record; the bare filename otherwise.
    Shared by :attr:`RehuDocumentModel.label` and the recents menu (#117), so the rule lives in exactly
    one place.

    Which records those are is :func:`~rehuco_core.is_directory_scoped_name`'s answer rather than a name
    matched here, so a legacy ``info.tc`` -- one per resource directory, which is what tc4 wrote -- names
    its folder like the ``info.rehu`` that replaces it (#250). Keying on ``info.rehu`` alone gave a
    catalog opened before conversion a tab strip reading ``info.tc`` all the way across, which is the one
    failure this label exists to prevent.

    :param key: the record's key.
    :returns: the label.
    """
    return f"{key.parent.name}/" if is_directory_scoped_name(key.name) else key.name


class RehuDocumentModel(QObject):  # pylint: disable=too-many-instance-attributes,too-many-public-methods
    """Reactive `QObject` over one `RehuDocument`, exposing common-core fields and a dirty flag
    ([[plugins#view-model]]).

    The viewer/editor surfaces bind to this instead of touching `RehuDocument` ([[data-model]]) directly, keeping
    the core non-GUI ([[plugins#core-vs-plugin]]). Setting ``title`` / ``publisher`` / ``url`` writes
    through to the document's **primary** source ([[field-schema#sources]]), marks the model dirty,
    and emits the field's ``<name>_changed`` signal -- which is what makes live "both" work: an edit
    in the editor updates the model, whose signal the viewer is bound to. ``sources`` is the whole list,
    top entry first -- that entry is the primary -- and a write to it moves ``title`` / ``publisher`` /
    ``url`` with it (#386); the multi-source record-list editor plugs into this seam. ``authors``
    / ``advertised_tags`` / ``extra_tags`` are common-core top-level lists, not source-scoped, so they
    write straight through to the document instead of through the primary source (#23).
    :meth:`revert` is the write-through's mirror image: it re-reads the document from disk and
    reseeds every field, guarded so reseeding is never itself treated as an edit (#41).

    :param document: the document to wrap.
    :param parent: optional Qt parent.
    :param records: what the record is read and saved through ([[nodes#access-seam]], #416); records announcing on a
        private feed when not given.
    :param version: what ``document`` was read at, which a save is checked and merged against
        (:class:`~rehuco_core.RecordVersion`); ``None`` for a document not read from its file, whose first save
        writes it as it is.
    :param signature: the file's modification time and size when ``document`` was read, which a later stat is
        compared with (:meth:`note_file_signature`); ``None`` when there is no file to compare.
    :param rename_coordinator: what :meth:`rename_location` renames through, so a job reading this
        resource is asked to stand aside rather than made to finish first (#241). ``None`` -- most
        tests, and any caller with no running work to coordinate with -- renames directly, which is
        exactly what a coordinator holding no readers does anyway.
    :param reader: what the record is read through off the GUI thread when it is opened, reverted or loaded (#564);
        a reader of this model's own when not given.
    """

    @dataclass(frozen=True, slots=True)
    class OutstandingRead:
        """A read of the record this model waits for (#564).

        :param key: the record being read.
        :param rebuild: rebuild the form whatever its structure once it arrives (:meth:`__load`).
        :param fill: the document already shows the record's save not landed, so the read only fills in what that is
            based on.
        """

        key: ResourceKey
        rebuild: bool
        fill: bool

    unknown_fields_changed = Signal()
    """Fires when the set of unrecognized active-block fields changes -- i.e. one is dropped via
    :meth:`remove_unknown_field` ([[plugins#fallback-editor]], #28)."""

    switched = Signal()
    """Fires after :meth:`load` moved this model to a **different file** (#470): what belongs to one record --
    a measurement this session made and never saved -- stops being true. Not a rename (the same record under
    a new name) and not a revert (the same file read again), neither of which changes the path while
    :attr:`loading`."""

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

    renamed = Signal()
    """Fires once a :meth:`rename_location` landed, after every holder followed it (#566): the record at its new key
    may say more than what was cached of it under the old one -- the save the rename wrote first, or one whose report
    named the path the rename emptied -- so it is checked again. Never on a rename that failed: nothing moved."""

    active_block_changed = Signal()
    """Fires when the whole field composition must be re-resolved from scratch: the outgoing block's
    editors go away, the incoming block's fields render, and the set of unknown-field and inactive-block
    rows (with their provenance and carry-vs-drop wiring) is rebuilt ([[plugins#plugin-blocks]], #83,
    #84). Two seams raise it -- a type switch (:meth:`__on_resource_type_changed`) and every
    :meth:`revert` (a reload can change the active type, its unknown fields, and the inactive-block fates
    at once, so revert rebuilds unconditionally rather than deciding which moved). Distinct from
    :attr:`unknown_fields_changed` (a single fallback field dropped) because that stays within a
    composition the reactive rows can show/hide, whereas this adds, removes, and re-wires whole rows --
    so ``DocumentSubDocks`` rebuilds its dock contents on it. Plain seeding does not raise it."""

    key = SimpleProperty[ResourceKey | None](None)
    """Where the document is reached ([[nodes#access-seam]]): what the registry, the docks and every holder that
    follows a rename know it by. ``None`` only for a document with no location
    at all. Reassigned with :attr:`path`, and **before** it, so a `path_changed` listener already reads the new key."""

    path = SimpleProperty[Path | None](None)
    """The record's file on this machine, mirroring :attr:`document`'s own path -- reassigned whenever
    it changes (construction, :meth:`revert`, :meth:`convert`, and a completed :meth:`rename_location`).
    What the features still reading files directly gate on: ``None`` is a document that is not a file this
    machine reads, whose identity is :attr:`key`."""

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

    sources = SimpleProperty[list[Any]](default_factory=list)
    """The document's ``sources`` entries, **top first** ([[field-schema#sources]]): each object without
    a ``primary`` key, because the top entry *is* the primary -- :attr:`title`/:attr:`publisher`/:attr:`url`
    are its own values, empty or not, and an assignment here rewrites the flag onto whichever entry ends up
    on top (:meth:`~rehuco_core.RehuDocument.set_source_records`). Duplicated URLs are kept as they are;
    :func:`~rehuco_core.duplicate_source_rows` names them for an editor to show (#386)."""

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

    changed_on_disk = SimpleProperty(False)
    """True when the file was changed outside this model since it last read or wrote it, while the model holds unsaved
    edits that a reload would discard (#487). Cleared by anything that reads or writes the file: a revert, a load, a
    save. A clean model never shows it: it just reloads (:meth:`note_file_signature`)."""

    conflict = SimpleProperty[RecordConflict | None](None)
    """The last save refused because the record's details were changed on disk since this model read them (#416),
    carrying the file as it is now; ``None`` while there is none. Cleared by anything that reads or writes the file.
    The conflict dialog resolves it (:meth:`resolve_conflict`, or :meth:`revert`)."""

    saving = SimpleProperty(False)
    """Whether a save of this document has been handed to a job and has not come back yet (#497): the document stays
    editable meanwhile, and the banner says so. Cleared when the save lands (:meth:`complete_save`) or fails
    (:meth:`fail_save`)."""

    pending_save = SimpleProperty("")
    """What this document's save that has not landed is doing, in the banner's words -- *Save pending*, *Waiting for
    the share*, *Save failed* -- or empty while there is none (#497). Set by whoever owns the save jobs."""

    reading = SimpleProperty[Path | None](None)
    """The file being read for this document while it shows nothing it can be edited from yet, or ``None`` (#564): a
    record opened, reverted or loaded with no save of it pending, its read off the GUI thread
    ([[offline-editing#overview]]). The document keeps showing what it showed -- nothing, for one just opened -- and
    ``DocumentSubDocks`` locks its editors and says *Reading…* until the file arrives. A record with a save not landed
    never reads this way: that save shows at once, and the read only fills in what it is based on
    ([[sync#unlanded-save]])."""

    gone = SimpleProperty("")
    """The sentence naming this edited document's file or folder that is not there any more, or empty (#497): its
    edits are kept, and no save is made until it is reverted, closed, or the file or folder comes back -- a save never
    recreates a folder ([[sync#compare-and-swap]])."""

    saved_on_disk = SimpleProperty(True)
    """Whether this document has ever been persisted to its path -- i.e. whether there is a file on disk
    to revert to. ``True`` for a **loaded** document (it stands for a file on disk -- even one that later
    goes missing out-of-band, whose revert is the fix-retry loop, [[data-model#write-integrity]]);
    ``False`` for a brand-new document (:meth:`create_new`) bound to a path that does not exist on disk
    yet. ``DocumentSubDocks`` keeps its Revert action **disabled** while this is ``False`` (#147): reverting
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
    back to a locked state). ``DocumentSubDocks`` disables its editor docks while this is non-empty; the
    inline notice (#94) and `DocumentsDock`'s tab marker bind to `lock_reasons_changed`."""

    unreadable_sidecars = SimpleProperty[list[str]](default_factory=list)
    """Why each per-user sidecar beside the record could not be read, mirrored from :attr:`document`'s
    :attr:`~RehuDocument.unreadable_sidecars` ([[data-model#single-file]], #568). Not a lock: the record stays editable
    and only the unreadable scope is left out. Set at the seams :attr:`lock_reasons` is; the inline notice binds to
    `unreadable_sidecars_changed`."""

    user_state_locked = SimpleProperty(False)
    """Whether the current user's own sidecar is among those :attr:`unreadable_sidecars` names -- what makes
    :data:`USER_STATE_FIELD_NAMES` read-only while the details stay editable (#568). Set with
    :attr:`unreadable_sidecars`."""

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
    stale until the next explicit seam. `DocumentSubDocks`' upgrade toolbar button and inline notice
    banner row both key off this flag directly, the same shape every other lock reason already uses
    (a toolbar remedy, plus a message-only banner row explaining it)."""

    image_scanner = SimpleProperty[RehuDocumentImageScanner | None](None)
    """The current screenshot-resolution scanner -- a `RehuDocumentImageScanner` over the ``<stem>NN``
    set and the pattern-matched images holding no slot yet (:meth:`__make_image_scanner`, #270), the
    same pair whether or not the document is :attr:`~RehuDocument.legacy_tc`.
    `ImageStrip`/`ImageSelector`/`MarkdownView` each hold their own copy and bind to
    `image_scanner_changed` to pick up a `.tc` -> `.rehu` conversion -- which renames files rather than
    switching conventions, so what changes is the answer, not the scanner's shape
    ([[acquisition-tooling#tc-to-rehu]])."""

    # what a holder hands a model it builds: the document, and where it came from and how to reach it again
    def __init__(  # pylint: disable=too-many-arguments
        self,
        document: RehuDocument,
        parent: QObject | None = None,
        *,
        records: Records | None = None,
        version: RecordVersion | None = None,
        signature: FileSignature | None = None,
        rename_coordinator: RenameCoordinator | None = None,
        pending: bool = False,
        pending_save_of: Callable[[ResourceKey], SavePayload | None] | None = None,
        reader: RecordReader | None = None,
    ) -> None:
        super().__init__(parent)
        self.__document = document
        self.__records: Final = records if records is not None else Records()
        self.__reader: Final = reader if reader is not None else RecordReader(self.__records, rename_coordinator, self)
        self.__read_serial = 0
        """Counts the reads asked for: an answer carrying an older count is for a read this model moved on from."""
        self.__read_out: RehuDocumentModel.OutstandingRead | None = None
        """The read this model waits for, or ``None``."""
        self.__after_read: Final[list[Callable[[], None]]] = []
        """What waits for the read out to arrive (:meth:`when_read`)."""
        self.__version = version
        """What the document was read or last saved at; see the class's ``version``."""
        self.__base_data = copy.deepcopy(document.data)
        """The document as read or last saved, for showing what a conflict changed on each side."""
        self.__rename_coordinator: Final = rename_coordinator
        self.__pending_save_of: Final = pending_save_of
        """Where a record's save that has not landed is found -- its saved state on this machine
        ([[sync#unlanded-save]]); ``None`` for a model no save owner looks after."""
        self.__pending = pending
        """See :attr:`pending`; set only by :meth:`create_pending`, cleared at the file seam that
        replaces the placeholder with real content (:meth:`revert`, which :meth:`load_pending`
        delegates to)."""

        self.__seeding = False
        """True only while :meth:`__seed_from_document` is applying field values pulled from the
        document -- guards every write-through handler below so a seed is never mistaken for a user
        edit."""
        self.__loading = False
        """See :attr:`loading`."""
        self.__disk_signature = signature
        """The file's modification time and size as this model last read or wrote it, or ``None`` before any."""
        self.__signature_during_save: FileSignature | None = None
        """A stat heard while a save was out or pending, judged once it is back: the save's own write, or one after
        it."""

        self.__seed_from_document()
        self.__mirror_locks()
        self.image_scanner = self.__make_image_scanner()
        self.__recompute_upgradable()
        self.__log_document_state()

        # a live edit toggles dirty, and a lock can appear/clear outside revert/convert too (tests
        # assign lock_reasons directly to simulate one) -- both must hide/reveal the upgrade offer
        # immediately, not just at the next explicit recompute seam below
        self.dirty_changed.connect(lambda _dirty: self.__recompute_upgradable())  # type: ignore[attr-defined]
        self.lock_reasons_changed.connect(lambda _reasons: self.__recompute_upgradable())  # type: ignore[attr-defined]

        # a saved patterns edit must reach an already-open document ([[appendices.settings-pages#reacting-to-changes]],
        # #281): rebuilding here re-emits image_scanner_changed, the seam the strip, the selector and the
        # Markdown view already rebind on for a .tc -> .rehu conversion. The settings are a process-wide
        # singleton that outlives every document, and Qt does not sever this lambda when the model dies
        # with its dock -- so the connection is scoped to the model's lifetime explicitly
        self.__external_connections: Final = ConnectionList()
        self.__external_connections.connect(
            shared_screenshot_patterns_settings().patterns_changed,  # type: ignore[attr-defined]
            lambda _patterns: self.__on_screenshot_patterns_changed(),
        )
        self.__external_connections.clear_on_destroyed(self)

        self.resource_type_changed.connect(self.__on_resource_type_changed)  # type: ignore[attr-defined]
        for name in COMMON_FIELD_NAMES:
            signal_name = SimpleProperty.notify_signal_name(type(self), name)
            getattr(self, signal_name).connect(lambda value, key=name: self.__on_common_field_changed(key, value))
        for name in (*TYPE_FIELD_BOOL_NAMES, *TYPE_FIELD_INT_NAMES, *TYPE_FIELD_STR_NAMES, *TYPE_FIELD_STR_LIST_NAMES):
            signal_name = SimpleProperty.notify_signal_name(type(self), name)
            getattr(self, signal_name).connect(lambda value, key=name: self.__on_type_field_changed(key, value))
        self.sources_changed.connect(self.__on_sources_changed)  # type: ignore[attr-defined]
        for name in RECORD_LIST_FIELD_NAMES:
            signal_name = SimpleProperty.notify_signal_name(type(self), name)
            getattr(self, signal_name).connect(lambda value, key=name: self.__on_record_list_changed(key, value))

    # the constructor's own seams, forwarded whole
    @classmethod
    def create_new(  # pylint: disable=too-many-arguments
        cls,
        path: Path | str | None = None,
        parent: QObject | None = None,
        *,
        username: str = DEFAULT_CURRENT_USERNAME,
        records: Records | None = None,
        rename_coordinator: RenameCoordinator | None = None,
        pending_save_of: Callable[[ResourceKey], SavePayload | None] | None = None,
        reader: RecordReader | None = None,
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
        :param records: forwarded to the constructor; see the class docstring.
        :param rename_coordinator: forwarded to the constructor; see its own docstring (#241).
        :param pending_save_of: forwarded to the constructor; see the class docstring.
        :param reader: forwarded to the constructor; see the class docstring.
        :returns: the new model, wrapping a fresh in-memory `RehuDocument` that already carries its own
            ``id`` (:meth:`~rehuco_core.RehuDocument.new`, [[data-model#stable-identity]]). Starts **not**
            :attr:`saved_on_disk` -- it has never been persisted to its path, so Revert is disabled until
            the first :meth:`save` (#147).
        """
        model = cls(
            RehuDocument.new(path, username=username),
            parent,
            records=records,
            rename_coordinator=rename_coordinator,
            pending_save_of=pending_save_of,
            reader=reader,
        )
        model.saved_on_disk = False
        if path is not None:
            model.dirty = True
        return model

    # the constructor's own seams, forwarded whole
    @classmethod
    def create_pending(  # pylint: disable=too-many-arguments
        cls,
        path: Path,
        parent: QObject | None = None,
        *,
        username: str = DEFAULT_CURRENT_USERNAME,
        records: Records | None = None,
        rename_coordinator: RenameCoordinator | None = None,
        pending_save_of: Callable[[ResourceKey], SavePayload | None] | None = None,
        reader: RecordReader | None = None,
    ) -> RehuDocumentModel:
        """Start a **pending** stand-in for an existing file that has deliberately not been read yet --
        session restore's deferred document load (#66).

        The model is bound to ``path`` but wraps an *empty* document, and :attr:`pending` is set so the
        consumers that would otherwise touch the file or its directory at construction hold off (each
        names the guard at its own seam). Unlike :meth:`create_new` it is **not** dirty and **not**
        built through :meth:`RehuDocument.new` -- the file already exists, so minting a fresh ``id``
        here would fabricate an identity for a resource that has one on disk
        ([[data-model#stable-identity]]); the bare constructor is the one that stands for an existing
        payload without inventing anything.

        :param path: the existing file this placeholder stands in for; :meth:`load_pending` reads it.
        :param parent: optional Qt parent.
        :param username: the identity the eventual read files per-user state under
            ([[field-schema#per-user-shared]], #99) -- same seam as :meth:`create_new`.
        :param records: forwarded to the constructor; see the class docstring.
        :param rename_coordinator: forwarded to the constructor; see its own docstring (#241).
        :param pending_save_of: forwarded to the constructor; see the class docstring.
        :param reader: forwarded to the constructor; see the class docstring.
        :returns: the pending model; empty, clean, and unlocked until :meth:`load_pending` runs.
        """
        return cls(
            RehuDocument({}, path, username=username),
            parent,
            records=records,
            rename_coordinator=rename_coordinator,
            pending=True,
            pending_save_of=pending_save_of,
            reader=reader,
        )

    @property
    def rename_coordinator(self) -> RenameCoordinator | None:
        """What :meth:`rename_location` renames through, or ``None`` for a plain rename (#241) -- so a
        reader this document owns can stand aside for it (#347).

        :returns: the coordinator this model was built with.
        """
        return self.__rename_coordinator

    @property
    def pending(self) -> bool:
        """Whether this model is a placeholder whose file has not been read yet: a session-restore one (#66), or one
        just opened whose read is out (#564).

        While true, every consumer that reads the file or its directory as a side effect of merely
        *existing* stands down -- the On Disk view already defers to its ``showEvent``, and
        `ConversionBackupActions`, `ChecksumActions`, and `RehuDocumentImageScanner` each guard on this
        -- so building the dock shell for a restored session touches no files at all
        ([[mounts-and-storage#offline-mounts]]). Cleared when the read arrives, or at once when the record's save not
        landed is shown instead, and by any other file seam that replaces the placeholder with real content; each of
        those emits :attr:`reloaded`, which is the signal those consumers already catch up on -- so no separate notify
        signal is carried for this flag.
        """
        return self.__pending

    def load_pending(self) -> None:
        """Read the file this :attr:`pending` placeholder stands in for -- the deferred half of the
        session restore's open (#66), run the first time the document's tab actually becomes visible, and the
        whole of an ordinary open (#564).

        Reads the path the way :meth:`load` reads any file, off the GUI thread -- including materializing the empty
        **locked** dock for a file that has since vanished or become unparseable ([[data-model#write-integrity]]) --
        and always rebuilds the whole form (:attr:`active_block_changed`) for the real type in place of the
        placeholder's typeless one, since that rebuild is also when the dock adopts the layout the session remembered
        for it.

        A no-op on a model that is not (or no longer) pending, or whose read is already out, so a stale second trigger
        never reloads a document out from under live edits.
        """
        if self.__pending and self.reading is None:
            # a placeholder is always bound to the path it stands in for (create_pending)
            self.__read(cast(ResourceKey, self.key), rebuild=True)

    def follow_pending_save(self, record: LoadedRecord | None = None) -> None:
        """Show the record's save that has not landed, if it has one and this model holds no edits of its own -- what
        a document just opened shows ([[sync#unlanded-save]]). A record never saved holds none yet, however dirty a
        new document starts.

        Never reads: the save is laid over the file as this model last read it, or as the caller just did. A placeholder
        not read yet, or one whose read is out, is left to that read, which shows the save when it arrives.

        :param record: the file as the caller has just read it; ``None`` takes what this model last read.
        """
        key = self.key
        own_edits = self.dirty and self.saved_on_disk
        if key is None or own_edits or self.__pending or self.reading is not None:
            return
        payload = self.__pending_save_for(key)
        if payload is None:
            return
        if record is None:
            record = LoadedRecord(
                self.__document, self.__version, tuple(self.__document.lock_reasons), self.__disk_signature
            )
        self.adopt_unsaved(payload, record if record.version is not None else None, dirty=False)

    def when_read(self, callback: Callable[[], None]) -> None:
        """Run ``callback`` once the file being read for this document has arrived and is shown (#564) -- at once when
        no such read is out. For a caller that judges what an open showed: whether it read at all, what type it is.

        :param callback: what to run; dropped with the model (:meth:`stop_reading`).
        """
        if self.reading is None:
            callback()
        else:
            self.__after_read.append(callback)

    def stop_reading(self) -> None:
        """Take nothing from the read out, if any, nor run what waits for it -- for a holder letting this model go."""
        self.__read_out = None

    @property
    def document(self) -> RehuDocument:
        """The wrapped document."""
        return self.__document

    @property
    def loading(self) -> bool:
        """Whether :meth:`load` (or a revert) is mid-way through moving every field to a newly read file (#381).

        Its path, dirty flag and lock reasons each announce their own change on the way, and :attr:`reloaded`
        follows once it is all done: a consumer that re-reads the disk on any of them waits for that one.
        """
        return self.__loading

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
        """This document's display label: the parent directory's name, trailing-slashed, for a
        directory-scoped record ([[data-model#resource-scoping]]), the bare filename otherwise.

        :returns: the label, or an empty string when the document has no location.
        """
        key = self.key
        if key is None:
            return ""
        return key_label(key)

    @property
    def current_name(self) -> str:
        """The resource's current rename target name -- the name a rename suggestion would replace
        ([[field-schema#field-mapping]]): the **parent directory** name for a directory-scoped record
        ([[data-model#resource-scoping]]), the file **stem** (no extension) otherwise, since a
        standalone ``foo.rehu`` renames its whole ``foo.*`` sibling set. Empty when the document has no
        location.

        Reads :func:`~rehuco_core.is_directory_scoped_name` rather than matching a name, so this and the
        rename plan that would execute the suggestion (:class:`~rehuco_core.RehuRenamer`) cannot
        disagree about which entry the name belongs to (#250).
        """
        key = self.key
        if key is None:
            return ""
        return key.parent.name if is_directory_scoped_name(key.name) else key.stem

    def save(self) -> None:
        """Save the document here and now, waiting for the write ([[nodes#access-seam]], #416) -- the same job a queued
        save runs (:class:`~rehuco_core.SaveRecordJob`, #497), run on the caller's thread.

        For the one caller that must have the file written before it goes on and has no window to wait in -- a rename
        writes the record before moving it (:meth:`rename_location`). Everything else hands a :meth:`snapshot` to the
        task queue and keeps editing.

        Per-user fields written to the file since it was read are merged in and shown (:meth:`complete_save`). Details
        changed on disk since it was read refuse the save as a :class:`~rehuco_core.RecordConflict`, kept in
        :attr:`conflict`. Also how an :attr:`upgradable` document is upgraded (#89): the write restamps it.

        :raises RecordConflict: details were changed on disk since the document was read.
        :raises OSError: the file could not be read or written, its share does not answer, or its lock is held.
        :raises ValueError: the document has no location, or is locked against saving.
        """
        payload = self.snapshot()
        self.begin_save()
        job = SaveRecordJob(payload, records=self.__records, coordinator=self.__rename_coordinator)
        with LogScope.open(self.path):
            try:
                outcome = job.write()
            except RecordConflict as conflict:
                LOG.warning("Not saved: %s", conflict)
                self.__failed_inline(conflict)
                raise
            except JobWaiting as waiting:
                self.__failed_inline(None)
                raise OSError(waiting.reason) from waiting
            except OSError, ValueError:
                self.__failed_inline(None, gone=job.gone)
                raise
        self.complete_save(payload, outcome)

    def __failed_inline(self, conflict: RecordConflict | None, *, gone: str | None = None) -> None:
        """Take back an inline :meth:`save` that did not land: with no job holding its data, the edits are unsaved
        again.

        :param conflict: why it was refused, when the record's details changed on disk.
        :param gone: the sentence naming the record's file or folder that is not there, when that is why.
        """
        self.fail_save(conflict, gone=gone)
        self.dirty = True

    def snapshot(self) -> SavePayload:
        """What a save of this document writes, taken now, so editing can go on while it runs (#497).

        A deep copy: nothing the document does afterwards reaches it. Also what the document's edits are kept as across
        a quit.

        :returns: the payload.
        :raises ValueError: the document has no location, is a legacy ``.tc``, or is locked against saving
            ([[data-model#write-integrity]]).
        """
        path = self.path
        if path is None:
            raise ValueError("No path given and document was not loaded from a file.")
        if self.__document.legacy_tc:
            raise ValueError(f"Refusing to save over a legacy record: {path}")
        blocking = next(
            (reason for reason in self.__document.lock_reasons if reason.kind in SAVE_BLOCKING_LOCK_KINDS), None
        )
        if blocking is not None:
            raise ValueError(f"Refusing to save a locked document ({blocking.kind}): {blocking.message}")
        written = self.__document.payload_to_write()
        return SavePayload(
            path=path,
            username=self.__document.username,
            payload=copy.deepcopy(written),
            base_payload=copy.deepcopy(self.__base_data) if self.__version is not None else None,
            base=self.__version,
            dropped=tuple(sorted(self.__document.data.keys() - written.keys())),
            discarded=self.__document.unlogged_dropped_block_keys(),
            first_save=not self.saved_on_disk,
            excluded_patterns=shared_excluded_files_settings().excluded_file_patterns,
        )

    def begin_save(self) -> None:
        """Say that a :meth:`snapshot` of this document has been handed to a save (#497): it is the record's saved state
        now ([[sync#unlanded-save]]), so the document is clean until it is edited again."""
        self.saving = True
        self.dirty = False

    def complete_save(self, payload: SavePayload, outcome: SaveOutcome, *, latest: SavePayload | None = None) -> None:
        """Take back a save that landed, keeping what was edited since (#497, [[sync#apply-payload]]).

        **The hard part is the merge-back.** The save wrote a snapshot; the document went on being edited. What the
        save changed on its way to disk -- the stamps, per-user fields merged in from the file, a block only the file
        had -- is put onto the live document **except where the user edited since the snapshot**, which wins. The
        document stays dirty exactly when it was edited since the last Save, and the next save is checked against the
        version this one wrote.

        :param payload: what the save wrote, as it was handed over.
        :param outcome: what landed.
        :param latest: a later Save of the record still pending, which the document's edits since are judged against
            instead -- it is the saved state now ([[sync#unlanded-save]]).
        """
        self.saving = False
        if self.__read_out is not None and self.__read_out.fill:
            # what landed is newer than anything the read out can say of the file
            self.__read_out = None
        deferred, self.__signature_during_save = self.__signature_during_save, None
        edited = payload_changes(payload.payload, self.__document.payload_to_write())
        kept = {
            path: value
            for path, value in payload_changes(payload.payload, outcome.written).items()
            if not any(paths_overlap(path, mine) for mine in edited)
        }
        if kept:
            put_paths(self.__document.data, kept, stamps=outcome.written)
        self.__document.note_written(outcome.written, payload.discarded)
        self.__version = outcome.version
        self.__base_data = copy.deepcopy(outcome.written)
        self.__disk_signature = outcome.signature
        if kept:
            self.__seed_from_document(description=False)
            with self.__seeding_guard():
                self.description = self.__document.description
        self.dirty = bool(
            edited if latest is None else payload_changes(latest.payload, self.__document.payload_to_write())
        )
        self.conflict = None
        self.changed_on_disk = False
        self.gone = ""
        # the file now exists on disk, so there is finally something to revert to (#147). Set once and never unset --
        # a later out-of-band deletion still leaves this a document that *was* saved
        self.saved_on_disk = True
        # explicit: a clean-but-upgradable document saves without dirty ever having been True (#89)
        self.__recompute_upgradable()
        if deferred is not None:
            # the same signature as the write's is heard as nothing changed, which is what it is
            self.note_file_signature(*deferred)

    def fail_save(self, conflict: RecordConflict | None, *, gone: str | None = None) -> None:
        """Take back a save that did not land; nothing asks the user anything (#497). Its data stays the record's saved
        state while its job keeps it ([[sync#unlanded-save]]).

        :param conflict: why it was refused, when the record's details changed on disk: kept in :attr:`conflict`, so
            the banner says so and the next save shows what differs.
        :param gone: the sentence naming the record's file or folder that is not there, when that is why.
        """
        self.saving = False
        if conflict is not None:
            self.conflict = conflict
        if gone:
            self.gone = gone
        deferred, self.__signature_during_save = self.__signature_during_save, None
        if deferred is not None:
            self.note_file_signature(*deferred)

    @property
    def base_version(self) -> RecordVersion | None:
        """What the document was read or last saved at, which its next save is checked against; ``None`` for a
        document not read from its file."""
        return self.__version

    def adopt_unsaved(self, payload: SavePayload, current: LoadedRecord | None, *, dirty: bool = True) -> None:
        """Show edits kept from elsewhere in place of what this model shows (#497): a session that quit with them
        unsaved, still unsaved -- or, not ``dirty``, the record's save that has not landed, which is its saved state
        ([[sync#unlanded-save]]).

        The document becomes ``payload``'s, based on what it was read at. When unsaved edits are no longer based on the
        file -- changed since, or created meanwhile for a record never saved -- the model says the file changed on
        disk, so the next save shows the differences first and nothing is overwritten unseen. A pending save is the
        save's own to judge, and keeps whatever its failure said.

        :param payload: the kept edits (:meth:`snapshot`), or the pending save's data.
        :param current: the record as it is on disk now, or ``None`` when there is none to read.
        :param dirty: whether the edits are unsaved; ``False`` for a pending save's.
        """
        shape = self.__form_shape()
        # a placeholder's form was built for a document not read yet (#66), so it is rebuilt whatever the shape
        rebuild = self.__pending
        previous_path = self.path
        on_disk = current.version if current is not None else None
        self.__pending = False
        self.__loading = True
        try:
            self.__document = RehuDocument(
                copy.deepcopy(payload.payload),
                payload.path,
                username=payload.username,
                on_disk_format_version=current.document.on_disk_format_version if current is not None else None,
            )
            self.__version = payload.base
            self.__base_data = copy.deepcopy(payload.base_payload) if payload.base_payload is not None else {}
            self.__disk_signature = current.signature if current is not None else None
            self.__signature_during_save = None
            if dirty:
                self.conflict = None
                self.gone = ""
            self.__seed_from_document(description=False)
            self.dirty = dirty
            self.saved_on_disk = not payload.first_save
            self.changed_on_disk = (
                dirty and on_disk is not None and (payload.base is None or on_disk.file_hash != payload.base.file_hash)
            )
            self.rename_error = ""
            self.__mirror_locks()
        finally:
            self.__loading = False
        self.image_scanner = self.__make_image_scanner()
        with self.__seeding_guard():
            self.description = self.__document.description
        self.unknown_fields_changed.emit()
        if rebuild or self.__form_shape() != shape:
            self.active_block_changed.emit()
        self.reloaded.emit()
        if self.path != previous_path:
            self.switched.emit()
        self.__recompute_upgradable()
        self.__log_document_state()

    def note_file_gone(self, *, folder_gone: bool) -> None:
        """Hear that this document's file is not there, its device having answered (#497).

        A clean, saved document reverts, as it does for a change -- which makes it the locked *missing* stub a reopen
        would make ([[data-model#lock-vocabulary]]). One with edits, or with a save not landed, keeps them and says what
        is gone in :attr:`gone`; so does a never-saved one whose folder went, while a never-saved one whose file is
        simply not written yet has nothing to hear.

        :param folder_gone: whether the folder the file is in is gone too.
        """
        path = self.path
        if self.__pending or self.reading is not None or self.saving or path is None or self.locked:
            # a read out says what it finds itself
            return
        if not self.saved_on_disk:
            self.gone = f"The resource's folder is gone: {path.parent}" if folder_gone else ""
        elif self.dirty or self.__pending_save_for(cast(ResourceKey, self.key)) is not None:
            self.gone = f"The resource's folder is gone: {path.parent}" if folder_gone else f"The file is gone: {path}"
        else:
            self.revert()

    def resolve_conflict(self, values: Mapping[FieldPath, Any]) -> None:
        """Take the values the user kept in :attr:`conflict` into the document, ready to be saved again (#416).

        The per-user fields are merged first, against what the document was read at, so the file's ones survive; then
        every row of the conflict is set to the side kept for it -- a row kept as *Mine* too, since the merge may have
        taken the file's value of a per-user field this document did not change -- and the document is based on the
        file as it is now, so its next save is refused again only if the file changed once more meanwhile. The save is
        the caller's: a queued one (#497), or :meth:`save`.

        :param values: the value kept for each row (:func:`~rehuco_core.record_differences`), by its path;
            :data:`~rehuco_core.ABSENT` removes it.
        :raises ValueError: there is no conflict to resolve.
        """
        conflict = self.conflict
        if conflict is None:
            raise ValueError("no conflict to resolve")
        if self.__version is not None:
            merge_users(self.__document.data, conflict.theirs.data, self.__version, self.__document.username)
        put_paths(self.__document.data, values, stamps=conflict.theirs.data)
        self.__version = conflict.version
        self.__seed_from_document(description=False)
        with self.__seeding_guard():
            self.description = self.__document.description
        self.dirty = True
        self.conflict = None
        self.changed_on_disk = False

    def base_data(self) -> dict[str, Any]:
        """The document as this model read or last saved it, per-user fields included -- the *Original* side of a
        conflict.

        :returns: a copy of it.
        """
        return copy.deepcopy(self.__base_data)

    def stored_files(self) -> list[tuple[str, str]]:
        """The record's files as they sit on disk -- the record and every user's sidecar -- not what a save would
        write.

        :returns: each file's name and text, the record first.
        :raises OSError: there is no file, or it could not be read.
        """
        key = self.key
        if key is None:
            raise FileNotFoundError("this document has no file yet")
        return self.__records.stored_files(key)

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

        A rename that landed emits :attr:`renamed`, so the record is read at its new key (#566): the cache follows a
        rename by rebasing its rows, reading nothing, and the save written first was reported under the old path.

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
            if self.__pending_save_for(cast(ResourceKey, self.key)) is not None:
                # the save is the record here until it lands ([[sync#unlanded-save]]); a second write of the record
                # made now, to move it, would run ahead of it and the two would conflict
                return self.__rename_failed(
                    f'Cannot rename to "{new_name}": a save of this record has not landed yet. Wait for it, or discard '
                    "it from the Tasks panel."
                )
            if self.dirty:
                try:
                    self.save()
                except (OSError, ValueError, RecordConflict) as error:
                    return self.__rename_failed(
                        f'Could not save "{self.current_name}" before renaming it: {self.__failure_reason(error)}'
                    )
            if not self.__move(new_name):
                return False
        # after the move was announced and every holder followed it: a check planned before the cache rebased its row
        # would be dropped as overtaken
        self.renamed.emit()
        return True

    def revert(self) -> None:
        """Discard in-memory edits and go back to the record's saved state: its save that has not landed, if it has
        one ([[sync#unlanded-save]]), else its file, loaded exactly as :meth:`load` loads any other (#381) -- so an
        out-of-band edit ([[data-model#write-integrity]]) is picked up too, and a revert is fast whenever the file's
        structure is what the form already shows. Like any open, it reads under the identity set now, which an
        identity-setting change made since the document was opened has moved.

        **The file is read off the GUI thread** (#564): a save not landed is shown at once, the file filling in only
        what it is based on; otherwise the document is :attr:`reading`, locked, until the file arrives.

        :raises ValueError: if the document has no local path (it is no file this machine reads).
        """
        path, key = self.path, self.key
        if path is None or key is None:
            raise ValueError("no path to revert from -- document was not loaded from or saved to a file")
        pending = self.__read(key, rebuild=False)
        with LogScope.open(path):
            LOG.info("Reverted %s to %s", path, "its save not landed yet" if pending else "what is on disk")

    def load(self, path: Path) -> None:
        """Show the ``.rehu`` (or legacy ``.tc``) at ``path`` in this model, in place of what it showed (#381).

        The one way a model takes a file's contents after it is built -- a preview moving on to the next
        resource, and :meth:`revert` loading the same file again: the file is read the way a holder opens it, off the
        GUI thread (:class:`~.record_reader.RecordReader` -- a ``.tc`` routed to its own loader, a file that will not
        read as an empty **locked** stub), and every field is reseeded from it once it arrives, which every editor and
        viewer follows through its binding. Until then the model shows what it showed, :attr:`reading`. **Nothing is
        rebuilt unless the form's structure changed** (:meth:`__form_shape`).

        :param path: the file to show.
        """
        self.__read(ResourceKey(path), rebuild=False)

    def __read(self, key: ResourceKey, *, rebuild: bool) -> bool:
        """Show the record at ``key`` as it stands on this machine, its file read off the GUI thread (#564): its save
        that has not landed, if it has one, **at once** -- the read then fills in only what that save is based on
        ([[sync#unlanded-save]]) -- else the file once it arrives, :attr:`reading` meanwhile.

        :param key: the record.
        :param rebuild: rebuild the form whatever its structure once the file arrives (:meth:`__load`).
        :returns: whether a save not landed is what is shown.
        """
        payload = self.__pending_save_for(key)
        if payload is not None:
            self.adopt_unsaved(payload, None, dirty=False)
        self.__request_read(RehuDocumentModel.OutstandingRead(key, rebuild, fill=payload is not None))
        return payload is not None

    def __request_read(self, read: RehuDocumentModel.OutstandingRead) -> None:
        """Ask for ``read``, in place of any read out: whatever that one brings is dropped when it arrives.

        :param read: the read.
        """
        self.__read_serial += 1
        self.__read_out = read
        self.reading = None if read.fill else read.key.path
        self.__reader.read(read.key, partial(self.__on_read, self.__read_serial))

    def __on_read(self, serial: int, record: LoadedRecord) -> None:
        """Take a read that arrived, unless this model moved on from it (GUI thread, #564).

        **A read is judged on arrival.** One this model no longer waits for -- another read asked for since (a
        revert, the preview moving on to another record), a save that landed meanwhile, or the model let go -- is
        dropped. One that only fills in the record's save not landed touches nothing the document shows or anything
        edited meanwhile: only the file's signature and its on-disk format version, as far as the file could be read.
        One the document was waiting for shows the record as it stands now: its save not landed, if one
        appeared meanwhile, laid over the file, else the file.

        :param serial: which read this is.
        :param record: what it read.
        """
        read = self.__read_out
        if serial != self.__read_serial or read is None:
            return
        self.__read_out = None
        self.reading = None
        if read.fill:
            self.__disk_signature = record.signature
            self.__document.adopt_disk_versions(record.document)
            self.__recompute_upgradable()
        elif (payload := self.__pending_save_for(read.key)) is not None:
            self.adopt_unsaved(payload, record if record.version is not None else None, dirty=False)
        else:
            self.__load(record, rebuild=read.rebuild)
        waiting = list(self.__after_read)
        self.__after_read.clear()
        for callback in waiting:
            callback()

    def __pending_save_for(self, key: ResourceKey) -> SavePayload | None:
        """The record's save that has not landed, if it has one.

        :param key: the record.
        :returns: its data, or ``None``.
        """
        return None if self.__pending_save_of is None else self.__pending_save_of(key)

    def __load(self, record: LoadedRecord, *, rebuild: bool) -> None:
        """Adopt ``record`` and reseed every field from it, as a fresh open would leave the model.

        **The form is rebuilt only when its structure moved** ([[plugins#plugin-blocks]], #83, #381):
        :attr:`active_block_changed` fires when the type, the active block's unknown fields, the inactive
        blocks' fates or the identity differ from what the form was built for -- the axes only a rebuild
        re-wires (a row's provenance, its carry-vs-drop button) -- or when ``rebuild`` asks for it. Otherwise
        the bound rows re-read their values, which is all a rebuild would have changed; it costs a few
        milliseconds where a rebuild of every editor and viewer cost a few hundred.

        ``unknown_fields_changed`` is emitted too, for consumers that don't rebuild on
        :attr:`active_block_changed` -- the source-preview docks re-serialize off it (#111), and it also
        covers restored unknown active-block fields ([[plugins#fallback-editor]], #28). :attr:`reloaded` fires
        for the file seam itself: reloading a *clean, unlocked* document moves no property at all, so it is the
        only signal telling `OnDiskView` the bytes it shows may be stale (#174). The image scanner is installed
        afresh, which is what has the strip, the curation list and the description's embedded images read the
        folder again -- a different file's, or this one's as it is now.

        :param record: the record to show.
        :param rebuild: rebuild the form whatever its structure -- the deferred first read of a session-restore
            placeholder (#66), whose form was built for a document not read yet.
        """
        shape = self.__form_shape()
        previous_path = self.path
        # cleared before anything is emitted: the refresh handlers this raises (reloaded,
        # active_block_changed) are the very consumers whose I/O the pending flag was holding back (#66)
        self.__pending = False
        self.__loading = True
        try:
            self.__adopt(record)
            self.__seed_from_document(description=False)
            self.dirty = False
            self.rename_error = ""
            self.__mirror_locks()
        finally:
            self.__loading = False
        self.image_scanner = self.__make_image_scanner()
        # after the scanner: a description renders its embedded images against the new folder, once (#381)
        with self.__seeding_guard():
            self.description = self.__document.description
        self.unknown_fields_changed.emit()
        if rebuild or self.__form_shape() != shape:
            self.active_block_changed.emit()
        self.reloaded.emit()
        if self.path != previous_path:
            self.switched.emit()
        self.__recompute_upgradable()
        self.__log_document_state()

    def __adopt(self, record: LoadedRecord) -> None:
        """Take ``record`` as what this model stands for: its document, and what a save of it is checked against.

        :param record: the record as read.
        """
        self.__document = record.document
        self.__version = record.version
        self.__base_data = copy.deepcopy(record.document.data)
        self.__disk_signature = record.signature
        self.__signature_during_save = None
        self.conflict = None
        self.changed_on_disk = False
        self.gone = ""

    def __form_shape(self) -> tuple[object, ...]:
        """What the form is built from beyond the values it binds: the type, the active block's unknown fields,
        the inactive blocks with whether each is dropped on save, and the identity the per-user fields are
        minted under (#381). Two documents of one shape are shown by the same rows.

        :returns: the shape, comparable for equality.
        """
        return (
            self.resource_type,
            tuple(self.unknown_field_names()),
            tuple(self.inactive_block_fates()),
            self.__document.username,
        )

    def convert(self, *, keep_backups: bool, overwrite: bool = False, deleter: Deleter | None = None) -> None:
        """Convert this locked, legacy ``.tc``-backed document into a real ``.rehu`` in place
        ([[acquisition-tooling#tc-to-rehu]]).

        Delegates the file-system work to the records' :meth:`~rehuco_core.access.Records.convert`, which announces
        the new ``.rehu`` and the ``.tc`` it replaced, then adopts its result as
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
        :param deleter: how a discarded backup is actually removed; ``None`` leaves that choice to
            `~rehuco_agent.recycle_bin_deleter.configured_deleter` (#301).
        :raises ValueError: this document isn't :attr:`~RehuDocument.legacy_tc`, or has no local path.
        :raises OSError: propagated from :func:`rehuco_core.convert_tc` (``FileExistsError`` for an
            unconfirmed overwrite or a stale backup; any other ``OSError`` from the underlying file
            operations) -- this model's ``document``/``locked``/``dirty`` are left untouched. Not
            raised for a discarded ``.tc`` backup the Recycle Bin cannot reach (#298): `convert_tc`
            already logs and keeps that ``.orig`` sibling rather than undoing a successful conversion,
            so this method's own success is unaffected by it.
        """
        if not self.__document.legacy_tc:
            raise ValueError("only a legacy .tc-backed document can be converted")
        key = self.key
        if self.path is None or key is None:
            raise ValueError("no path to convert -- document was not loaded from a file")
        legacy_path = self.path
        with LogScope.open(legacy_path):
            LOG.info("Converting %s, %s", legacy_path, "keeping backups" if keep_backups else "discarding originals")
            record = self.__records.convert(
                key,
                keep_backups=keep_backups,
                overwrite=overwrite,
                username=self.__document.username,
                excluded_patterns=shared_excluded_files_settings().excluded_file_patterns,
                screenshot_name_patterns=shared_screenshot_patterns_settings().screenshot_name_patterns,
                deleter=deleter if deleter is not None else configured_deleter(),
            )
            LOG.info("Converted to %s", record.document.path)
        self.__adopt(record)
        self.__seed_from_document()
        self.dirty = False
        self.rename_error = ""
        self.__mirror_locks()
        self.image_scanner = self.__make_image_scanner()
        self.unknown_fields_changed.emit()
        self.reloaded.emit()
        self.__recompute_upgradable()
        self.__log_document_state()

    def note_file_signature(self, mtime_ns: int, size: int) -> None:
        """Hear that the file on disk has this modification time and size, and follow it if it is not what this model
        read or wrote (#487, verify-on-access).

        A clean model reloads at once -- every editor and viewer follows. One with unsaved edits is left as it is, with
        :attr:`changed_on_disk` raised: a reload would discard them, and a save would overwrite the other change, so the
        user chooses. A model not yet read, or standing for a file that was never written, has nothing to compare.

        :param mtime_ns: the file's modification time now.
        :param size: its size now.
        """
        # the file is there: whatever was gone has come back, and the change-on-disk rule below decides the rest
        self.gone = ""
        key = self.key
        if self.saving or (key is not None and self.__pending_save_for(key) is not None):
            # the save's own write, or one after it: told apart once the save is back (complete_save) -- and a save not
            # landed is the record here, which nothing on disk reloads over; its own check judges the file
            self.__signature_during_save = (mtime_ns, size)
            return
        if (
            self.__pending
            or self.reading is not None
            or self.__disk_signature is None
            or self.__disk_signature == (mtime_ns, size)
        ):
            # not read yet, or a read out that will show the file as it is now
            return
        if self.dirty:
            self.changed_on_disk = True
        else:
            self.revert()

    def forget_folder_listing(self) -> None:
        """Drop what the image scanner remembers of this document's folder, for a collaborator that has just renamed,
        deleted or written files there -- the screenshot organizer -- and is about to ask again in the same turn.

        Nobody else is told: the folder's file notifier reports the writes to every view (#511).
        """
        # installed at construction and only ever replaced, never cleared
        cast(RehuDocumentImageScanner, self.image_scanner).forget()

    def relocate(self, relocation: KeyRelocation) -> bool:
        """Follow a rename that moved this document's record ([[mounts-and-storage#out-of-band]], #376).

        The holder's half of a rename announced app-wide: whoever holds this model hands it every rename's
        executed plan, and the model adopts the path the plan gives its record -- a record nested in a renamed
        collection folder, or one whose own sibling set was renamed. Adopting is :meth:`rename_location`'s own
        (:meth:`__adopt_path`), and as there it is not an edit: unsaved edits stay unsaved, now bound to the new
        location.

        **Idempotent**, which is what lets the renaming document hear its own rename: the announcement reaches
        it before :meth:`rename_location` has adopted the result, and whichever comes second finds the path
        already there and does nothing.

        :param relocation: the rename's executed plan.
        :returns: whether this document's location changed.
        """
        read = self.__read_out
        if read is not None and (moved := relocation.relocate(read.key)) != read.key:
            # the record being read went with the rename: what the old path gives now is not it
            self.__request_read(replace(read, key=moved))
        key = self.key
        if key is None:
            return False
        return self.__adopt_path(relocation.relocate(key).path)

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

    def add_source(self, publisher: str, url: str) -> None:
        """Add a scraped page as a source ([[field-schema#sources]], #272), never a duplicate of one
        already there by ``url``.

        Three cases, decided by ``url`` alone (#366, #386), with URLs compared after trimming: a source
        with this ``url`` **already exists** -- its ``publisher`` is filled in if empty and it is
        otherwise left as it is, so a re-scrape never duplicates it and never relabels a publisher the
        document already names; the top source (the primary) **has no url** -- it takes this one, with or
        without a publisher, and takes the scraper's publisher only if it names none; or the ``url`` is
        **new** -- appended below whatever the document already has, never overwriting a source from an
        earlier drop or a `.tc` migration. The primary is filled through the
        `~RehuDocumentModel.url`/`~RehuDocumentModel.publisher` properties, so dirty tracking and the Save
        Preview refresh exactly as an edit through those fields already does; the other writes go through
        :attr:`sources`.

        :param publisher: the scraper's publisher -- fills the matching or primary source's own empty
            ``publisher``, and seeds a new entry's.
        :param url: the scraped page's URL.
        """
        url = url.strip()
        sources = self.sources
        match = next(
            (
                row
                for row, source in enumerate(sources)
                if isinstance(source, dict) and str(source.get("url") or "").strip() == url
            ),
            None,
        )
        if match is not None:
            if sources[match].get("publisher"):
                return
            if match == 0:
                self.publisher = publisher
            else:
                self.sources = [*sources[:match], {**sources[match], "publisher": publisher}, *sources[match + 1 :]]
            return
        if not self.url.strip():
            self.url = url
            if not self.publisher:
                self.publisher = publisher
            return
        self.sources = [*sources, {"title": self.title, "publisher": publisher, "url": url}]

    def rescan_images(self) -> None:
        """Send this resource's ``<stem>NN`` set back to the directory (#73).

        Reinstalls :attr:`image_scanner`, the same seam :meth:`__on_screenshot_patterns_changed`
        reinstalls it through for a saved patterns edit -- the strip, the curation editor and the
        Markdown view all rebuild from disk on that signal. What an image acquired outside this
        model's own editors -- a drop's own write, or a scrape's downloaded URL -- calls once its
        bytes have landed, since neither wrote through anything that would otherwise notice.
        """
        self.image_scanner = self.__make_image_scanner()

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

        **Banner parity.** ``DocumentSubDocks.__banner_rows`` builds its rows from exactly three sources:
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

    def __mirror_locks(self) -> None:
        """Mirror what keeps the document from being edited, whole or in part, from :attr:`document`: its lock reasons
        and, as notices of a part (#568), the sidecars that could not be read."""
        self.unreadable_sidecars = [sidecar.reason for sidecar in self.__document.unreadable_sidecars]
        self.user_state_locked = self.__document.own_sidecar_unreadable
        self.lock_reasons = list(self.__document.lock_reasons)

    def __seed_from_document(self, *, description: bool = True) -> None:
        """Set every field from :attr:`document`'s current in-memory state (construction,
        :meth:`revert`, :meth:`convert`), guarded so it is never itself mistaken for a user edit.

        :param description: seed the description too; :meth:`__load` seeds it on its own, once the new image
            scanner is installed, so it is rendered once and against the right folder (#381).
        """
        with self.__seeding_guard():
            self.key = None if self.__document.path is None else ResourceKey(self.__document.path)
            self.path = self.__document.path
            self.location = self.__document.path.as_posix() if self.__document.path is not None else ""
            self.resource_type = self.__document.type
            self.sources = self.__document.source_records
            self.title = self.__document.title
            self.authors = self.__document.authors
            self.publisher = self.__document.publisher
            self.url = self.__document.url
            self.released = self.__document.released
            if description:
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
        :func:`~rehuco_core.rename_rehu_resource`, and standing the readers aside first belongs to
        :class:`~rehuco_core.RenameCoordinator` (#241), so all that is left here is *adopting* what it
        returns (:meth:`__adopt_path`). :attr:`current_name` and :attr:`label` derive from :attr:`path`,
        so they follow on their own, as does the dock identity `DocumentsDock` resyncs off
        ``path_changed``.

        Nothing here writes back to the document's payload, so a rename is not an edit: the model ends
        as clean as :meth:`rename_location`'s pre-move save left it.

        **The wait is short and it is on this thread.** Renaming through the coordinator asks any job
        reading beneath this resource to close its handle, which costs one chunk read -- ~7 ms measured
        -- so the editor is not made to wait for the *job* the way #240's lock made the user wait
        (#241). A reader that never answers costs
        :data:`~rehuco_core.DEFAULT_RENAME_YIELD_TIMEOUT` instead and then fails through
        :attr:`rename_error` like any other refusal, which is why that ceiling is seconds rather than
        the queue's own shutdown wait: a window that stops repainting for five seconds is one the
        operating system starts drawing as hung.

        :param new_name: the destination file/folder name.
        :returns: whether the rename succeeded; a failure's reason is left in :attr:`rename_error`.
        """
        path = self.path
        if path is None:  # pragma: no cover -- rename_location refuses a document with no local path before this
            return False
        current_name = self.current_name
        try:
            new_path = self.__renamed(path, new_name)
        except (OSError, ValueError) as error:
            # a refusal over an open handle also says whose handle it is, when that can be found (#355)
            holders = RenameHolderReport.describe(path, error)
            return self.__rename_failed(
                f'Could not rename "{current_name}" to "{new_name}": {self.__failure_reason(error)}'
                + (f" {holders}" if holders else "")
            )
        # already adopted when the coordinator's announcement reached this model through its holder (#376)
        self.__adopt_path(new_path)
        LOG.info("Renamed %r to %r", current_name, new_name)
        return True

    def __adopt_path(self, new_path: Path) -> bool:
        """Re-point this document at ``new_path`` after a rename moved its record, once.

        The document is re-pointed (:meth:`~RehuDocument.rebind_path`), :attr:`path` and :attr:`location`
        follow, and a fresh screenshot scanner is installed -- replaced rather than left alone, because
        replacing it is what emits ``image_scanner_changed``, the only thing telling the image strip and the
        Markdown viewer that the names they hold are stale. A path already adopted is left alone, so a rename
        heard twice -- from :meth:`rename_location` and from the app-wide announcement -- moves the document
        and fires each signal exactly once.

        :param new_path: where the record is now.
        :returns: whether anything changed.
        """
        if new_path == self.path:
            return False
        self.__document.rebind_path(new_path)
        self.key = ResourceKey(new_path)
        self.path = new_path
        self.location = new_path.as_posix()
        self.image_scanner = self.__make_image_scanner()
        return True

    def __renamed(self, path: Path, new_name: str) -> Path:
        """Perform the rename, through the coordinator when there is one (#241).

        The two paths differ only in whether anybody is asked to stand aside first: with no coordinator
        there are no tracked readers to ask, which is the same answer the barrier would reach, so the
        direct call is not a lesser mode -- it is the same operation with the empty case skipped.

        :param path: the resource's current ``.rehu``.
        :param new_name: the destination file/folder name.
        :returns: the resource's ``.rehu`` under its new name.
        :raises OSError: the rename failed, or readers did not stand aside in time.
        :raises ValueError: ``new_name`` is not a plain file/folder name.
        """
        if self.__rename_coordinator is None:
            return rename_rehu_resource(path, new_name)
        return self.__rename_coordinator.rename(path, new_name)

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
        """Build the screenshot scanner: the ``<stem>NN`` set, the images holding no slot yet, and what
        converting would do to each of the latter.

        **The same row-listing pair for a `.tc` and a `.rehu`**, deliberately, and not the
        naming-convention switch this used to be. The numbered half is `scan_rehu_screenshot_files`
        either way, because it answers what is *on disk* -- a ``.tc``'s directory simply has none yet,
        which is what being un-converted means; the un-converted half is `scan_unconverted_screenshots`
        either way, since a pattern-matched image with no slot is the same thing beside either kind of
        record ([[data-model#image-meanings]], #270).

        The tc rename plan (`scan_tc_screenshots`) is **not** what a ``.tc`` lists *from*: it reports
        each slot's winner out of renames that have not run, so a collision the plan would leave alone
        ([[acquisition-tooling#tc-to-rehu]]) came back looking like the one un-converted file among
        three that are all un-converted. Every pattern-matched image is a row (#292); what the plan is
        good for is the *After conversion* column (#293, `scan_after_conversion`) -- read by
        :meth:`~rehuco_agent.documents.rehu_document_image_scanner.RehuDocumentImageScanner.after_conversion`,
        which answers ``None`` off a ``.rehu`` before this third lister is even called.

        The one place all three listers are chosen -- and the one place the configured screenshot
        patterns are bound to the two that take them (#281), which otherwise fall back to their
        shipped default set -- so construction, a conversion, a rename, and a saved patterns change all
        install a scanner picked the same way.

        :returns: the scanner to assign to :attr:`image_scanner`.
        """
        patterns = shared_screenshot_patterns_settings().screenshot_name_patterns
        unconverted_lister = partial(scan_unconverted_screenshots, patterns=patterns)
        after_conversion = partial(scan_after_conversion, patterns=patterns)
        return RehuDocumentImageScanner(self, scan_rehu_screenshot_files, unconverted_lister, after_conversion)

    def __on_screenshot_patterns_changed(self) -> None:
        """Reinstall :attr:`image_scanner` when the shared screenshot patterns are saved.

        Unconditional, unlike the ``.tc``-only rebuild this started as (#281): every document's
        un-converted lister reads the patterns now, so a `.rehu` whose dock lists a ``cover.jpg``
        stops listing it the moment the pattern that recognized it is deleted.
        """
        self.image_scanner = self.__make_image_scanner()

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
        if key in PRIMARY_SOURCE_FIELD_NAMES:
            with self.__seeding_guard():
                self.sources = self.__document.source_records
        self.dirty = True

    def __on_sources_changed(self, value: list[Any]) -> None:
        """Write an edited ``sources`` list through to the document and mark dirty (#386).

        The document takes the list whole (:meth:`~rehuco_core.RehuDocument.set_source_records`), so the
        top entry becomes the primary; :attr:`title`/:attr:`publisher`/:attr:`url` are then re-read from it,
        under the seeding guard so that re-read is not written back, since a reorder or a deleted top row
        changes all three at once. No-op while the model is seeding (construction, :meth:`revert`, or
        :meth:`convert`) -- see the comment there.

        :param value: the new entries, top first.
        """
        if self.__seeding:
            return
        self.__document.set_source_records(value)
        with self.__seeding_guard():
            self.title = self.__document.title
            self.publisher = self.__document.publisher
            self.url = self.__document.url
        self.dirty = True

    def __on_type_field_changed(self, key: str, value: Any) -> None:
        """Write an edited type-field scalar through to the document's plugin block and mark dirty.

        A per-user key (:data:`USER_FIELD_NAMES`) lands in the block's ``users`` map under this
        document's own username, the rest inline in the block ([[field-schema#per-user-shared]],
        #99) -- the write half of :meth:`__read_field`'s split. ``None`` (only ever reachable for the
        optional-scalar members of :data:`TYPE_FIELD_INT_NAMES` and :data:`TYPE_FIELD_STR_NAMES` -- the
        bool/str-list fields never hold it) **removes** the key rather than writing a JSON ``null``: for a
        per-user key that rule is core's (``set_active_user_field``, #410), for a shared one it is kept
        here, ``set_active_field`` being a generic value writer with no such rule of its own
        ([[field-schema#deferred-items]]). No-op while the
        model is seeding (construction, :meth:`revert`, or :meth:`convert`) -- see the comment there.

        :param key: the type-field key that changed.
        :param value: the new value, or ``None`` to remove the key.
        """
        if self.__seeding:
            return
        if key in USER_FIELD_NAMES:
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
