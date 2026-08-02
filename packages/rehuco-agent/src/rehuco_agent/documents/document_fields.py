"""The rehu document's field composition: its record field list, its viewer/editor surfaces, and the
builder that assembles them over the shared field toolkit ([[plugins#field-toolkit]]).

Document-specific, deliberately kept out of the reusable ``fields`` toolkit -- the toolkit knows
nothing of *this* document's fields, tabs, or ``level`` choices; only this module (in the
``documents`` layer that owns the view-model and surfaces) does.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Final, NamedTuple

from rehuco_core import (
    CORE_FIELD_NAMES,
    DurationProbeError,
    PluginRegistry,
    content_duration,
    content_size_on_disk,
    enumerate_content_images,
)

from ..fields import (
    PROVENANCE_ABANDONED_TYPE,
    PROVENANCE_NEWER_VERSION,
    PROVENANCE_NOT_CURRENT_TYPE,
    PROVENANCE_PLUGIN_ABSENT,
    DescriptionField,
    Field,
    FieldRegistry,
    FieldsForm,
    FieldsTab,
    ImagesField,
    PathField,
    TypeField,
    UnknownField,
)
from ..settings.excluded_files_settings import shared_excluded_files_settings
from ..settings.identity_settings import shared_identity_settings
from ..settings.image_viewer_settings import shared_image_viewer_settings
from ..settings.markdown_rendering_settings import shared_markdown_rendering_settings
from ..settings.reference_images_settings import shared_reference_images_settings
from ..settings.videos_settings import shared_videos_settings
from .name_suggestion_model import NameSuggestionModel
from .rehu_document_model import RehuDocumentModel

TYPE_FIELD_NAME: Final = "resource_type"
"""The special, editor-only `type` field's model name -- the document's resource type, i.e. the key of
its active plugin block ([[plugins#plugin-blocks]], #83)."""

LOCATION_FIELD_NAME: Final = "location"
"""The special `path` field's model name -- the resource's file location ([[field-schema#field-mapping]])."""

CURRENT_COUNT_FIELD_NAME: Final = "current_count"
"""The measured content-image count's model name ([[field-schema#field-mapping]]) -- the one record field
whose editor takes a runtime callback ([[plugins#field-toolkit]], #198), named here so
:func:`build_document_form` can hand it one."""

SIZE_FIELD_NAMES: Final = ("original_size", "current_size")
"""The measured size fields' model names ([[field-schema#field-mapping]]) -- both take the same runtime
measure callback (#223), because both measure the same content and differ only in *when* they are
pressed ([[field-schema#duration-size]])."""

DURATION_FIELD_NAMES: Final = ("original_duration", "current_duration")
"""The measured duration fields' model names ([[field-schema#field-mapping]]) -- both take the same
runtime measure callback (#224), for the same reason the sizes do. ``advertised_duration`` is
deliberately absent: it is the claim the measurement is checked *against*
([[field-schema#duration-size]]), so it stays a plain duration with no measure row."""

LEARNING_PATHS_FIELD_NAME: Final = "learning_paths"
"""The learning-paths field's model name ([[field-schema#learning-path-ownership]]) -- the one record field
whose editor needs to know **who is editing**, plus where the next file-scoped ``ref`` comes from (#235),
named here so :func:`build_document_form` can hand it both."""

IMAGES_FIELD_NAME: Final = "hidden_images"
"""The images field's model name -- the lightbox's curated-out screenshots ([[data-model#image-meanings]])."""

VIEWER_TAB: Final = FieldsTab("Viewer", ":/icons/document_viewer.svg")
"""The document viewer surface ([[plugins#field-toolkit]]) -- the default all record fields' viewers
are assigned to by :func:`build_document_form`."""

EDITOR_MAIN_TAB: Final = FieldsTab("Main Editor", ":/icons/document_editor_main.svg")
"""The document's main editor surface ([[plugins#field-toolkit]]); record fields' editors default here."""

EDITOR_DESCRIPTION_TAB: Final = FieldsTab("Description", ":/icons/document_description.svg")
"""The Markdown ``description``'s own editor dock ([[plugins#viewer-editor-both]]), so its editor can be
torn out and maximized while writing prose."""

EDITOR_IMAGES_TAB: Final = FieldsTab("Images", ":/icons/document_images.svg")
"""The lightbox-curation editor's own dock ([[data-model#image-meanings]], #27): the checkable
screenshot list beside its sized preview lives here, on its own tab."""

LEVEL_CHOICES: Final = ("beginner", "intermediate", "advanced", "any")
"""The ``level`` multi-choice field's fixed value set ([[field-schema#field-types]])."""


class FieldSpec(NamedTuple):
    """One :data:`MODEL_AGNOSTIC_FIELD_SPECS` entry: which toolkit type renders a model field, plus any
    extra constructor arguments and its viewer/editor tabs.

    :param type: the field-type selector the registry resolves.
    :param name: the model field name to bind.
    :param kwargs: extra constructor arguments the type needs (e.g. ``multi_choice``'s ``choices``).
    :param viewer_tab: the viewer surface this field's viewer lands on; defaults to :data:`VIEWER_TAB`.
    :param editor_tab: the editor surface this field's editor lands on; defaults to
        :data:`EDITOR_MAIN_TAB` (``description`` overrides it to its own dock).
    """

    type: str
    name: str
    # MappingProxyType({}) is a read-only empty mapping. A NamedTuple field default is evaluated once,
    # so a plain ``{}`` would be a single dict shared by every FieldSpec (the mutable-default footgun);
    # the proxy makes that shared default immutable -- a mutation attempt raises rather than leaking
    # across specs. kwargs is only ever read (unpacked as ``**spec.kwargs``), so read-only suffices.
    kwargs: Mapping[str, Any] = MappingProxyType({})
    viewer_tab: FieldsTab = VIEWER_TAB
    editor_tab: FieldsTab = EDITOR_MAIN_TAB


MODEL_AGNOSTIC_FIELD_SPECS: Final[tuple[FieldSpec, ...]] = (
    FieldSpec("text", "title"),
    FieldSpec("authors", "authors"),
    FieldSpec("date", "released"),
    FieldSpec("text", "publisher"),
    FieldSpec("collections", "collections"),
    FieldSpec("url", "url"),
    FieldSpec("duration", "advertised_duration"),
    FieldSpec("measured_duration", "original_duration"),
    FieldSpec("measured_duration", "current_duration"),
    FieldSpec("count_claim", "advertised_count"),
    FieldSpec("content_count", "current_count"),
    FieldSpec("size", "original_size"),
    FieldSpec("size", "current_size"),
    FieldSpec("bool", "complete"),
    FieldSpec("bool", "online"),
    FieldSpec("bool", "viewed"),
    FieldSpec("bool", "todo"),
    FieldSpec("bool", "keep"),
    FieldSpec("bool", "favorite"),
    FieldSpec("rating", "rating"),
    FieldSpec("multi_choice", "level", {"choices": LEVEL_CHOICES}),
    FieldSpec("text_list", "advertised_tags"),
    FieldSpec("text_list", "extra_tags"),
    FieldSpec("learning_paths", "learning_paths"),
)
"""The **model-agnostic** fields the document declares -- the ones the `FieldRegistry` resolves from a
``(type, name)`` pair alone, bar the one runtime callback :func:`build_document_form` hands
``current_count``'s editor (#198). This is the **name-to-toolkit-type map**, not
a per-type field list and not a layout: *which* of these a given resource shows is
:func:`composed_field_specs`' answer, read off the plugin declarations in core (#195), and
:func:`build_document_form` happens to emit the survivors after the model-aware ``location``/images
fields and before the `UnknownField` fallbacks, which is only how the form is assembled.

A name here that no declaration claims renders on **no** type -- which is exactly how ``images_count``
went missing while being declared, coerced, and round-tripped (#195); ``test_plugins`` pins the two
sides together so the next hole fails a test instead of shipping. #196 mapped that count to ``int``, and
#198 split it into the ``advertised_count``/``current_count`` pair ReferenceImages declares today, which
is why two rows render there and none elsewhere; the names left unmapped here are the ones a surface builds
directly (``description``, ``hidden_images``) or never shows at all (``created``, ``updated``).

**Registration order is not display order.** How fields are ordered and placed on screen is a
presentation concern the viewer/editor own; that they currently render fields in this registration
order is incidental (the tracer's simplification) and expected to diverge. **Where** each type's field
list is authored is now settled -- the plugin declares it ([[plugins#core-vs-plugin]]'s schema-extension
row) -- but where the *ordered* list is authored is still open
([[field-schema#deferred-items]], [[appendices.open-questions#still-open]]), which is why the order stays
here, in one list spanning every type, rather than being split across the declarations.

Its members: the common-core title/authors/released/publisher/url, the Tutorial plugin-block duration
fields, the ReferenceImages-only count pair, the common-core original/current size pair, the
shared resource-type scalar flags, rating, the Tutorial-only ``level`` tags, the tag lists, and the two
membership record lists
([[field-schema#resource-types]], [[field-schema#duration-size]], [[field-schema#sources]]) -- the
record lists sit where tc4's viewer put them (``collections`` up in the header group beside the
publisher, ``learning_paths`` last, after the tag lists, [[field-schema#tc4-viewer-layout]]), which
costs nothing while registration order still happens to be display order. The count pair sits with the
durations rather than trailing them: it is what a reference pack has instead of one, answering the same
*how much of it is there* (#196), the claim before the measurement (#198). The Markdown ``description``
is model-aware too (it needs an
`ImageScanner` to resolve embedded images, [[data-model#image-meanings]]) and so is constructed
directly in :func:`build_document_form` alongside ``location``/images, not listed here. A hardcoded
constant for now."""


def composed_field_specs(model: RehuDocumentModel) -> tuple[FieldSpec, ...]:
    """The :data:`MODEL_AGNOSTIC_FIELD_SPECS` entries this document's **type** declares
    ([[field-schema#resource-types]], #195).

    The common core plus the active type's own fields, both read off the declarations in core
    (:data:`~rehuco_core.CORE_FIELD_NAMES` and the plugin's `~rehuco_core.PluginSpec.field_names`), so a
    ReferenceImages resource stops showing the three Tutorial durations and ``level``, and a Collection
    shows the common core alone. The composition is a **filter over one ordered list**, not a per-type
    list assembled from the declarations: the declarations are sets, and where the ordered list is
    authored is still open (:data:`MODEL_AGNOSTIC_FIELD_SPECS`).

    A type whose plugin isn't installed here declares nothing, so it composes the common core alone --
    and every key in its block reaches the generic fallback instead
    (`RehuDocumentModel.unknown_field_names`, [[plugins#fallback-editor]]), which is what keeps a
    narrowed field list from *swallowing* a value rather than merely not rendering it.

    :param model: the document whose active type selects the fields.
    :returns: the declared specs, in :data:`MODEL_AGNOSTIC_FIELD_SPECS` order.
    """
    declared = frozenset(CORE_FIELD_NAMES) | frozenset(model.document.plugins.field_names(model.resource_type))
    return tuple(spec for spec in MODEL_AGNOSTIC_FIELD_SPECS if spec.name in declared)


# the local count is what "the whole field composition lives here, in one place" costs: each model-aware
# field is one construction plus its runtime callbacks, and splitting them out to satisfy a threshold
# would scatter the composition this function exists to keep together
# pylint: disable-next=too-many-locals
def build_document_form(
    model: RehuDocumentModel,
    name_suggestions: NameSuggestionModel,
    registry: FieldRegistry | None = None,
) -> FieldsForm:
    """Build the document's complete :class:`FieldsForm` for ``model``.

    The whole field composition lives here, in one place: the model-aware **leading** fields (the
    ``location`` `PathField`, the images strip/selector, and the Markdown ``description``, whose
    runtime callbacks the registry can't build generically), then the declarative record fields the
    document's **type** declares (:func:`composed_field_specs`, in
    :data:`MODEL_AGNOSTIC_FIELD_SPECS` order, one of which -- the content count -- is handed a runtime
    measure callback the same way), then one generic `UnknownField` fallback per
    unrecognized key in the active block, and finally one per **inactive block**
    ([[plugins#fallback-editor]], #28, #80). All of it is driven from ``model`` alone, so
    `DocumentWidget` only hosts the resulting docks.

    The leading fields and ``description`` are **not** filtered by type: they are common core
    ([[field-schema#resource-types]]) except ``location``, which is a location control rather than a
    payload value and so is authored out-of-band regardless ([[plugins#field-toolkit]]).

    :param model: the reactive view-model the fields bind to and read their runtime state from.
    :param name_suggestions: the rename-suggestion `NameSuggestionModel` the ``location`` field pulls
        candidate names from -- the caller's, not built here. It carries permanent notify-signal
        subscriptions on ``model``, so it must outlive individual form builds: a caller that rebuilds
        the form (a type switch/revert, `DocumentWidget`) owns **one** and passes it to every build, so
        it is reused rather than a fresh one leaking per rebuild (#149). Required, not optional-with-a-
        default: minting one here would put that ownership back inside a per-build call, the exact seam
        #149 closed. The owner parents it to ``model`` so it is freed with the whole document (#148).
    :param registry: the field registry to resolve the record types with; a default one when omitted.
    :returns: a form composing location + images + description, then the record fields, then the
        unknown fallbacks, then the inactive blocks.
    """
    registry = registry or FieldRegistry()

    # the current type is ensured present in the offered list even when it names no installed plugin and
    # carries no block (a bare, unresolved type), so the combo always shows the document's actual type
    # rather than silently snapping to another; ``available_types`` already covers every resurrectable
    # block key ([[plugins#plugin-blocks]], #83)
    type_choices = model.available_types()
    if model.resource_type not in type_choices:
        type_choices = [model.resource_type, *type_choices]
    # the viewer badge is painted with the colors the resource's plugin declares for itself, resolved
    # through the registry -- so a plugin from any source owns how its badge looks; an undeclared color
    # (or a not-installed type) falls back to the theme's selection color ([[plugins#plugin-blocks]], #83)
    plugins = model.document.plugins
    type_field = TypeField(
        TYPE_FIELD_NAME,
        "Type",
        type_choices,
        lambda type_key: (plugins.color(type_key), plugins.text_color(type_key)),
        viewer_tab=VIEWER_TAB,
        editor_tab=EDITOR_MAIN_TAB,
    )

    def rename_to(name: str) -> None:
        # a wrapper, not the bound method directly: it discards ``rename_location``'s bool result (the
        # callback is a command, ``(str) -> None``) and defers the ``model.rename_location`` lookup to
        # click time, so a test that swaps it after construction is still seen
        model.rename_location(name)

    location_field = PathField(
        LOCATION_FIELD_NAME,
        suggestions=name_suggestions.suggestions,
        on_suggestion_selected=rename_to,
        current_name=lambda: model.current_name,
        suggestions_changed=name_suggestions.changed,
        # a lambda for the same reason ``rename_to`` is one: the lookup is deferred to render time, so
        # a test that swaps the model's answer after construction is still seen
        conflicts=lambda name: model.rename_conflicts(name),  # pylint: disable=unnecessary-lambda
        viewer_tab=VIEWER_TAB,
        editor_tab=EDITOR_MAIN_TAB,
    )
    # model.image_scanner is a RehuDocumentImageScanner over the legacy-.tc or the .rehu screenshot lister
    # ([[acquisition-tooling#tc-to-rehu]]); a successful conversion reassigns it, and both fields'
    # widgets forward image_scanner_changed into their own scanner to pick that up live
    images_field = ImagesField(
        IMAGES_FIELD_NAME,
        image_scanner=model.image_scanner,
        image_scanner_changed=model.image_scanner_changed,  # type: ignore[attr-defined]
        viewer_tab=VIEWER_TAB,
        editor_tab=EDITOR_IMAGES_TAB,
        # the height plus its change signal, the same shape the scanner above uses: the strip is built
        # at the configured height and resizes itself when the user applies a new one (#161)
        strip_height=shared_image_viewer_settings().preview_image_height,
        strip_height_changed=shared_image_viewer_settings().preview_image_height_changed,  # type: ignore[attr-defined]
        # and the same again for the strip's layout: built wrapped or not as configured, and re-laid
        # out when the user applies the other choice (#70)
        strip_wrap=shared_image_viewer_settings().preview_wrap,
        strip_wrap_changed=shared_image_viewer_settings().preview_wrap_changed,  # type: ignore[attr-defined]
    )

    def measure_content_images() -> int | None:
        """Count the images inside this resource's archive(s) afresh ([[data-model#resource-scoping]]).

        The enumeration takes its recognized extension set as an argument rather than reading a setting
        (#197), so this is where the user's choice is read (#222) -- at every measurement, so a list edited
        in Settings takes effect on the next Compute without rebuilding the form.

        :returns: the count, or ``None`` when the document has no path yet -- there is nothing on disk to
            count, which is not the same as counting zero.
        """
        path = model.path
        if path is None:
            return None
        extensions = shared_reference_images_settings().content_image_extensions
        return len(enumerate_content_images(path, extensions))

    def measure_size_on_disk() -> int | None:
        """Sum what this resource's content occupies on disk ([[data-model#resource-scoping]], #223).

        The walk takes its excluded-name globs as an argument rather than reading a setting (#226), so
        this is where the user's list is read -- at every measurement, so a list edited in Settings takes
        effect on the next Compute without rebuilding the form. It is the *same* list the checksums will
        take (#203): a file summed here and skipped there is the bug the one shared set exists to prevent.

        Runs on a worker thread (`~rehuco_agent.fields.background_measurement.BackgroundMeasurement`), so
        it touches nothing but plain Python state and the filesystem.

        :returns: the total size in bytes, or ``None`` when the document has no path yet -- there is
            nothing on disk to measure, which is not the same as measuring zero.
        """
        path = model.path
        if path is None:
            return None
        return content_size_on_disk(path, shared_excluded_files_settings().excluded_file_patterns)

    def measure_duration() -> int | None:
        """Sum how long this resource's videos run ([[field-schema#duration-size]], #224).

        Reads the same excluded-name list the size scan does, so the two measure one content set (#226).
        The probe backend and the video-extension list are the Videos settings page's (#225), read here
        at every measurement, so either edited in Settings takes effect on the next Compute without
        rebuilding the form.

        Runs on a worker thread (`~rehuco_agent.fields.background_measurement.BackgroundMeasurement`), so
        it touches nothing but plain Python state, the filesystem, and the probe.

        :returns: the total in whole seconds, or ``None`` when there is nothing to measure -- a document
            with no path yet, or a probe backend that cannot run here at all. The second case is
            deliberately not a ``0``: core raises rather than totalling one, because a misconfigured
            backend and a tutorial holding no video would otherwise be the same answer.
        """
        path = model.path
        if path is None:
            return None
        try:
            videos = shared_videos_settings()
            return content_duration(
                path,
                videos.create_probe(),
                video_extensions=videos.video_extensions,
                excluded_patterns=shared_excluded_files_settings().excluded_file_patterns,
            )
        except DurationProbeError:
            return None

    description_field = DescriptionField(
        "description",
        image_scanner=model.image_scanner,
        image_scanner_changed=model.image_scanner_changed,  # type: ignore[attr-defined]
        # the shared settings satisfy the DescriptionRenderingSettings protocol at runtime; only the
        # SimpleProperty/Signal descriptor duality trips static protocol matching (see bind_value_widget)
        rendering_settings=shared_markdown_rendering_settings(),  # type: ignore[arg-type]
        viewer_tab=VIEWER_TAB,
        editor_tab=EDITOR_DESCRIPTION_TAB,
    )
    # the type selector leads the Main Editor -- it is the most fundamental choice, and re-selecting it
    # re-resolves the whole form (#83). It is editor-only, so it adds no viewer row and location's
    # viewer still leads the viewer surface. Location follows so its editor sits right under the type;
    # the images strip still sits high in the viewer, above the description, and its editor gets its own tab
    fields: list[Field[Any]] = [type_field, location_field, images_field]
    # a record field resolves from its (type, name) pair alone, except where its editor needs a runtime
    # callback the registry cannot build generically: every measure action reaches both the filesystem and
    # a user setting -- the recognized extensions for the count (#198), the excluded names for the sizes
    # and the durations (#224), and a probe backend for the durations besides
    # (#223/#226) -- none of which the toolkit knows about, so they are supplied here the same way the
    # images strip's scanner is. Both sizes get the *same* callback, and so do both durations: each pair
    # measures the same content and differs only in when the user presses it ([[field-schema#duration-size]])
    runtime_kwargs: dict[str, dict[str, Any]] = {CURRENT_COUNT_FIELD_NAME: {"measure": measure_content_images}}
    runtime_kwargs.update({name: {"measure": measure_size_on_disk} for name in SIZE_FIELD_NAMES})
    runtime_kwargs.update({name: {"measure": measure_duration} for name in DURATION_FIELD_NAMES})
    # not a measurement, the same seam for the same reason: the learning-paths table has to know whose
    # rows are editable, where a new path's file-scoped slot comes from, and who inherits a deleted path
    # that still has subscribers -- none of which the toolkit could work out from a ``(type, name)`` pair.
    # The editing identity is the document's own (fixed at open, [[field-schema#per-user-shared]]); the
    # reparent target is the **configured** unknown identity, not core's constant, since ``unknown`` is a
    # setting rather than a reserved name ([[field-schema#learning-path-ownership]], #235). ``next_ref``
    # is a lambda for the reason every other deferred lookup here is one: it is read at mint time, so a
    # test that swaps the document's answer after the form was built is still seen.
    runtime_kwargs[LEARNING_PATHS_FIELD_NAME] = {
        "username": model.document.username,
        "next_ref": lambda: model.document.next_learning_path_ref(),  # pylint: disable=unnecessary-lambda
        "unknown_username": shared_identity_settings().unknown_username,
    }
    for spec in composed_field_specs(model):
        fields.append(
            registry.create(
                spec.type,
                spec.name,
                viewer_tab=spec.viewer_tab,
                editor_tab=spec.editor_tab,
                **spec.kwargs,
                **runtime_kwargs.get(spec.name, {}),
            )
        )
    # description trails the record fields, preserving today's viewer stacking order, even though
    # it's now constructed directly above rather than resolved out of MODEL_AGNOSTIC_FIELD_SPECS
    fields.append(description_field)
    # the unknown-field fallbacks trail after the record fields, each shown labeled by provenance and
    # carried verbatim, with a remove action that drops it from the document
    for name in model.unknown_field_names():
        fields.append(
            UnknownField(
                name,
                provenance=PROVENANCE_NEWER_VERSION,
                on_remove=lambda name=name: model.remove_unknown_field(name),
                is_present=lambda name=name: name in model.document.active_block,
                current_value=lambda name=name: model.document.active_field(name),
                viewer_tab=VIEWER_TAB,
                editor_tab=EDITOR_MAIN_TAB,
            )
        )
    # each inactive block trails as a single flagged row naming the whole block, carried verbatim by
    # default with an explicit drop (#84, [[plugins#fallback-editor]]). Its provenance is why it's
    # inactive -- three cases the user resolves differently:
    #   - **claimed then abandoned** this session: already dropped on save (armed deletion, #83). Its
    #     message says how to keep it (switch back), and it gets *no* drop button -- it is on its way out
    #     already, with the #86 discard-log audit trail, so a manual remove would only bypass that record.
    #   - **foreign, plugin installed here**: not the current type; the fix is switch-the-type or drop.
    #   - **foreign, plugin absent**: this build can't read it; the fix is install-the-plugin or drop.
    # A foreign block's drop removes the whole block through the model, mirroring an unknown field's remove.
    for key, dropped in model.inactive_block_fates():
        fields.append(
            UnknownField(
                key,
                provenance=inactive_block_provenance(key, dropped, plugins),
                on_remove=None if dropped else (lambda key=key: model.drop_inactive_block(key)),
                is_present=lambda key=key: key in model.document.data,
                current_value=lambda key=key: model.document.data.get(key),
                viewer_tab=VIEWER_TAB,
                editor_tab=EDITOR_MAIN_TAB,
            )
        )
    return FieldsForm(fields)


def inactive_block_provenance(key: str, dropped: bool, plugins: PluginRegistry) -> str:
    """The provenance message flagging an inactive block, chosen by *why* it's inactive
    ([[plugins#fallback-editor]], #84).

    Three cases the user resolves differently: a **claimed-then-abandoned** block is already slated to
    drop on save (#83); a never-claimed **foreign** block splits on whether this build has a plugin
    for it -- installed means "switch the type or drop", absent means "install the plugin or drop".

    :param key: the inactive block's key.
    :param dropped: whether the block persistence invariant will drop it on save (claimed then abandoned).
    :param plugins: the plugins installed here, to tell a not-current-type block from a plugin-absent one.
    :returns: the matching ``PROVENANCE_*`` message.
    """
    if dropped:
        return PROVENANCE_ABANDONED_TYPE
    return PROVENANCE_NOT_CURRENT_TYPE if key in plugins else PROVENANCE_PLUGIN_ABSENT
