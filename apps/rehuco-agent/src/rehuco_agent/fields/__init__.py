"""Field toolkit: reactive viewer/editor widgets composed from a declarative field list ([[plugins#field-toolkit]])."""

from typing import Final

from rehuco_agent.fields.boolean_field import BooleanField
from rehuco_agent.fields.date_field import DateField
from rehuco_agent.fields.duration_field import DurationField
from rehuco_agent.fields.field import Field
from rehuco_agent.fields.field_registry import FieldRegistry
from rehuco_agent.fields.fields_form import FieldsForm
from rehuco_agent.fields.file_size_field import FileSizeField
from rehuco_agent.fields.int_field import IntField
from rehuco_agent.fields.rating_field import RatingField
from rehuco_agent.fields.text_field import TextField
from rehuco_agent.fields.text_list_field import TextListField
from rehuco_agent.fields.url_field import UrlField

DOCUMENT_FIELD_SPECS: Final = (
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
    ("text_list", "advertised_tags"),
    ("text_list", "extra_tags"),
)
"""The document's field list: the common-core title/authors/released/publisher/url, the Tutorial
plugin-block duration fields, the common-core original/current size pair, the shared resource-type
scalar flags, rating, and the tag lists ([[field-schema#resource-types]], [[field-schema#duration-size]]).
A hardcoded constant for now; per-type field lists and where this is authored long-term are open
questions ([[field-schema#deferred-items]], [[appendices.open-questions#still-open]])."""

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
