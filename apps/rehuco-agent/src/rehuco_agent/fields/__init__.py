"""Field toolkit: reactive viewer/editor widgets composed from a declarative field list ([[plugins#field-toolkit]])."""

from collections.abc import Sequence
from typing import Any, Final

from rehuco_agent.fields.boolean_field import BooleanField
from rehuco_agent.fields.date_field import DateField
from rehuco_agent.fields.duration_field import DurationField
from rehuco_agent.fields.field import Field
from rehuco_agent.fields.field_registry import FieldRegistry
from rehuco_agent.fields.fields_form import FieldsForm
from rehuco_agent.fields.file_size_field import FileSizeField
from rehuco_agent.fields.int_field import IntField
from rehuco_agent.fields.multiple_choice_field import MultipleChoiceField
from rehuco_agent.fields.path_field import PathField
from rehuco_agent.fields.rating_field import RatingField
from rehuco_agent.fields.text_field import TextField
from rehuco_agent.fields.text_list_field import TextListField
from rehuco_agent.fields.url_field import UrlField

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

__all__ = [
    "Field",
    "FieldRegistry",
    "FieldsForm",
    "TextField",
    "BooleanField",
    "RatingField",
    "IntField",
    "TextListField",
    "UrlField",
    "DateField",
    "DurationField",
    "FileSizeField",
    "MultipleChoiceField",
    "PathField",
    "LEVEL_CHOICES",
    "DOCUMENT_FIELD_SPECS",
    "build_document_form",
]


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
        fields.append(registry.create(type_, name, **kwargs))
    return FieldsForm(fields)
