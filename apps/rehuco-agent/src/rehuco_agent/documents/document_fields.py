"""The rehu document's field composition: its record field list, its viewer/editor surfaces, and the
builder that assembles them over the shared field toolkit ([[plugins#field-toolkit]]).

Document-specific, deliberately kept out of the reusable ``fields`` toolkit -- the toolkit knows
nothing of *this* document's fields, tabs, or ``level`` choices; only this module (in the
``documents`` layer that owns the view-model and surfaces) does.
"""

from collections.abc import Sequence
from typing import Any, Final

from rehuco_agent.fields import Field, FieldRegistry, FieldsForm, FieldsTab

VIEWER_TAB: Final = FieldsTab("Viewer", ":/icons/document_viewer.svg")
"""The document viewer surface ([[plugins#field-toolkit]]) -- the default all record fields' viewers
are assigned to by :func:`build_document_form`."""

EDITOR_MAIN_TAB: Final = FieldsTab("Main Editor", ":/icons/document_editor_main.svg")
"""The document's main editor surface ([[plugins#field-toolkit]]); record fields' editors default here."""

LEVEL_CHOICES: Final = ("beginner", "intermediate", "advanced", "any")
"""The ``level`` multi-choice field's fixed value set ([[field-schema#field-types]])."""

FieldSpec = tuple[str, str] | tuple[str, str, dict[str, Any]]
"""One :data:`DOCUMENT_FIELD_SPECS` entry: ``(type, name)``, or ``(type, name, kwargs)`` for a type
that needs extra constructor arguments."""

DOCUMENT_FIELD_SPECS: Final[tuple[FieldSpec, ...]] = (
    ("text", "title"),
    ("text_list", "authors"),
    ("date", "released"),
    ("text", "publisher"),
    ("url", "url"),
    ("duration", "advertised_duration"),
    ("duration", "original_duration"),
    ("duration", "current_duration"),
    ("size", "original_size"),
    ("size", "current_size"),
    ("bool", "complete"),
    ("bool", "online"),
    ("bool", "viewed"),
    ("bool", "todo"),
    ("bool", "keep"),
    ("bool", "favorite"),
    ("rating", "rating"),
    ("multi_choice", "level", {"choices": LEVEL_CHOICES}),
    ("text_list", "advertised_tags"),
    ("text_list", "extra_tags"),
)
"""The document's record field list: the common-core title/authors/released/publisher/url, the
Tutorial plugin-block duration fields, the common-core original/current size pair, the shared
resource-type scalar flags, rating, the Tutorial-only ``level`` tags, and the tag lists
([[field-schema#resource-types]], [[field-schema#duration-size]]). The special ``location``
`PathField` is **not** here -- it is model-aware (its rename suggestions read other fields), so its
owner (`DocumentWidget`) constructs it and passes it as a leading field to
:func:`build_document_form`. A hardcoded constant for now; per-type field lists and where this is
authored long-term are open questions ([[field-schema#deferred-items]],
[[appendices.open-questions#still-open]]). Most entries are a ``(type, name)`` pair; a field whose
type needs extra constructor arguments (``level``'s ``choices``) appends a third ``dict`` element,
passed through to :meth:`~rehuco_agent.fields.field_registry.FieldRegistry.create` as keyword arguments."""


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
        type_, name, *rest = spec
        kwargs = rest[0] if rest else {}
        fields.append(registry.create(type_, name, viewer_tab=VIEWER_TAB, editor_tab=EDITOR_MAIN_TAB, **kwargs))
    return FieldsForm(fields)
