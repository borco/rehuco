"""Field toolkit: reactive viewer/editor widgets composed from a declarative field list ([[plugins#field-toolkit]])."""

from typing import Final

from rehuco_agent.fields.boolean_field import BooleanField
from rehuco_agent.fields.field import Field
from rehuco_agent.fields.field_registry import FieldRegistry
from rehuco_agent.fields.fields_form import FieldsForm
from rehuco_agent.fields.int_field import IntField
from rehuco_agent.fields.rating_field import RatingField
from rehuco_agent.fields.text_field import TextField

DOCUMENT_FIELD_SPECS: Final = (
    ("text", "title"),
    ("text", "publisher"),
    ("text", "url"),
    ("bool", "complete"),
    ("bool", "online"),
    ("bool", "viewed"),
    ("bool", "todo"),
    ("bool", "keep"),
    ("bool", "favorite"),
    ("rating", "rating"),
)
"""The document's field list: the common-core title/publisher/url plus the shared resource-type scalar
flags and rating ([[field-schema#resource-types]]). A hardcoded constant for now; per-type field lists and
where this is authored long-term are open questions ([[field-schema#deferred-items]],
[[appendices.open-questions#still-open]])."""

__all__ = [
    "Field",
    "FieldRegistry",
    "FieldsForm",
    "TextField",
    "BooleanField",
    "RatingField",
    "IntField",
    "DOCUMENT_FIELD_SPECS",
    "build_document_form",
]


def build_document_form(registry: FieldRegistry | None = None) -> FieldsForm:
    """Build the document's :class:`FieldsForm` from its field list.

    :param registry: the field registry to resolve types with; a default one when omitted.
    :returns: a form composing the document's title/publisher/url text fields.
    """
    registry = registry or FieldRegistry()
    return FieldsForm([registry.create(type_, name) for type_, name in DOCUMENT_FIELD_SPECS])
