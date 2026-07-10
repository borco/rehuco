"""The rehu document's field composition: its record field list, its viewer/editor surfaces, and the
builder that assembles them over the shared field toolkit ([[plugins#field-toolkit]]).

Document-specific, deliberately kept out of the reusable ``fields`` toolkit -- the toolkit knows
nothing of *this* document's fields, tabs, or ``level`` choices; only this module (in the
``documents`` layer that owns the view-model and surfaces) does.
"""

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any, Final, NamedTuple

from rehuco_agent.fields import Field, FieldRegistry, FieldsForm, FieldsTab

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
    """One :data:`DOCUMENT_FIELD_SPECS` entry: which toolkit type renders a model field, plus any
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


DOCUMENT_FIELD_SPECS: Final[tuple[FieldSpec, ...]] = (
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
"""The document's record field list: the common-core title/authors/released/publisher/url, the
Tutorial plugin-block duration fields, the common-core original/current size pair, the shared
resource-type scalar flags, rating, the Tutorial-only ``level`` tags, the tag lists, and the
common-core Markdown ``description`` (which lands on its own editor dock, :data:`EDITOR_DESCRIPTION_TAB`)
([[field-schema#resource-types]], [[field-schema#duration-size]]). The special ``location`` `PathField`
is **not** here -- it is model-aware (its rename suggestions read other fields), so its owner
(`DocumentWidget`) constructs it and passes it as a leading field to :func:`build_document_form`. A
hardcoded constant for now; per-type field lists and where this is authored long-term are open questions
([[field-schema#deferred-items]], [[appendices.open-questions#still-open]])."""


def build_document_form(registry: FieldRegistry | None = None, leading_fields: Sequence[Field[Any]] = ()) -> FieldsForm:
    """Build the document's :class:`FieldsForm` from its field list.

    :param registry: the field registry to resolve types with; a default one when omitted.
    :param leading_fields: pre-built fields to place first, before the record fields -- how the
        model-aware ``location`` `PathField` (which the registry can't build generically) is
        threaded in by its owner.
    :returns: a form composing ``leading_fields`` then the record fields, in
        :data:`DOCUMENT_FIELD_SPECS` order.
    """
    registry = registry or FieldRegistry()
    fields: list[Field[Any]] = list(leading_fields)
    for spec in DOCUMENT_FIELD_SPECS:
        fields.append(
            registry.create(spec.type, spec.name, viewer_tab=spec.viewer_tab, editor_tab=spec.editor_tab, **spec.kwargs)
        )
    return FieldsForm(fields)
