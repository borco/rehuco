"""The rehu document's field composition: its record field list, its viewer/editor surfaces, and the
builder that assembles them over the shared field toolkit ([[plugins#field-toolkit]]).

Document-specific, deliberately kept out of the reusable ``fields`` toolkit -- the toolkit knows
nothing of *this* document's fields, tabs, or ``level`` choices; only this module (in the
``documents`` layer that owns the view-model and surfaces) does.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Final, NamedTuple

from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields import (
    PROVENANCE_NEWER_VERSION,
    Field,
    FieldRegistry,
    FieldsForm,
    FieldsTab,
    ImagesField,
    PathField,
    UnknownField,
)

LOCATION_FIELD_NAME: Final = "location"
"""The special `path` field's model name -- the resource's file location ([[field-schema#field-mapping]])."""

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
    FieldSpec("text_list", "authors"),
    FieldSpec("date", "released"),
    FieldSpec("text", "publisher"),
    FieldSpec("url", "url"),
    FieldSpec("duration", "advertised_duration"),
    FieldSpec("duration", "original_duration"),
    FieldSpec("duration", "current_duration"),
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
    FieldSpec("description", "description", editor_tab=EDITOR_DESCRIPTION_TAB),
)
"""The **model-agnostic** fields the document declares -- the ones the `FieldRegistry` resolves from a
``(type, name)`` pair alone, with no runtime model wiring. This is a **model-layer** statement of
*which* fields the document has and their toolkit type, not a layout: :func:`build_document_form`
happens to emit them after the model-aware ``location``/images fields and before the `UnknownField`
fallbacks, but that ordering is only how the form is assembled, not a meaningful grouping.

**Registration order is not display order.** How fields are ordered and placed on screen is a
presentation concern the viewer/editor own; that they currently render fields in this registration
order is incidental (the tracer's simplification) and expected to diverge -- per-type field lists and
where the display order is authored are open questions
([[field-schema#deferred-items]], [[appendices.open-questions#still-open]]).

Its members: the common-core title/authors/released/publisher/url, the Tutorial plugin-block duration
fields, the common-core original/current size pair, the shared resource-type scalar flags, rating, the
Tutorial-only ``level`` tags, the tag lists, and the common-core Markdown ``description`` (which lands
on its own editor dock, :data:`EDITOR_DESCRIPTION_TAB`) ([[field-schema#resource-types]],
[[field-schema#duration-size]]). A hardcoded constant for now."""


def build_document_form(model: RehuDocumentModel, registry: FieldRegistry | None = None) -> FieldsForm:
    """Build the document's complete :class:`FieldsForm` for ``model``.

    The whole field composition lives here, in one place: the model-aware **leading** fields (the
    ``location`` `PathField` and the images strip/selector, whose runtime callbacks the registry can't
    build generically), then the declarative record fields in :data:`MODEL_AGNOSTIC_FIELD_SPECS` order, then
    one generic `UnknownField` fallback per unrecognized live-block key
    ([[plugins#fallback-editor]], A2.8/#28). All of it is driven from ``model`` alone, so
    `DocumentWidget` only hosts the resulting docks.

    :param model: the reactive view-model the fields bind to and read their runtime state from.
    :param registry: the field registry to resolve the record types with; a default one when omitted.
    :returns: a form composing location + images, then the record fields, then the unknown fallbacks.
    """
    registry = registry or FieldRegistry()

    def rename_to(name: str) -> None:
        # a wrapper, not the bound method directly: it discards ``rename_location``'s bool result (the
        # callback is a command, ``(str) -> None``) and defers the ``model.rename_location`` lookup to
        # click time, so a test that swaps it after construction is still seen
        model.rename_location(name)

    location_field = PathField(
        LOCATION_FIELD_NAME,
        suggestions=model.name_suggestions,
        on_suggestion_selected=rename_to,
        current_name=lambda: model.current_name,
        suggestions_changed=model.name_suggestions_changed,
        viewer_tab=VIEWER_TAB,
        editor_tab=EDITOR_MAIN_TAB,
    )
    images_field = ImagesField(
        IMAGES_FIELD_NAME,
        image_files=model.image_files,
        viewer_tab=VIEWER_TAB,
        editor_tab=EDITOR_IMAGES_TAB,
    )
    # location leads so its editor keeps the Main Editor tab first/current; the images strip still
    # sits high in the viewer, above the description, and its editor gets its own tab
    fields: list[Field[Any]] = [location_field, images_field]
    for spec in MODEL_AGNOSTIC_FIELD_SPECS:
        fields.append(
            registry.create(spec.type, spec.name, viewer_tab=spec.viewer_tab, editor_tab=spec.editor_tab, **spec.kwargs)
        )
    # the unknown-field fallbacks trail after the record fields, each shown labeled by provenance and
    # carried verbatim, with a remove action that drops it from the document
    for name in model.unknown_field_names():
        fields.append(
            UnknownField(
                name,
                provenance=PROVENANCE_NEWER_VERSION,
                on_remove=lambda name=name: model.remove_unknown_field(name),
                is_present=lambda name=name: name in model.document.type_fields,
                current_value=lambda name=name: model.document.type_field(name),
                viewer_tab=VIEWER_TAB,
                editor_tab=EDITOR_MAIN_TAB,
            )
        )
    return FieldsForm(fields)
