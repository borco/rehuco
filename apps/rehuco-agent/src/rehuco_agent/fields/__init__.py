"""Field toolkit: reactive viewer/editor widgets composed from a declarative field list ([[plugins#field-toolkit]])."""

from typing import Final

from rehuco_agent.fields.field import Field
from rehuco_agent.fields.field_registry import FieldRegistry
from rehuco_agent.fields.fields_form import FieldsForm
from rehuco_agent.fields.text_field import TextField

DOCUMENT_FIELD_SPECS: Final = (
    ("text", "title"),
    ("text", "publisher"),
    ("text", "url"),
)
"""The document's field list: title/publisher/url, all `text`. A hardcoded constant for A2.0; where
this is authored long-term is an open question ([[appendices.open-questions#still-open]])."""

__all__ = ["Field", "FieldRegistry", "FieldsForm", "TextField", "DOCUMENT_FIELD_SPECS", "build_document_form"]


def build_document_form(registry: FieldRegistry | None = None) -> FieldsForm:
    """Build the document's :class:`FieldsForm` from its field list.

    :param registry: the field registry to resolve types with; a default one when omitted.
    :returns: a form composing the document's title/publisher/url text fields.
    """
    registry = registry or FieldRegistry()
    return FieldsForm([registry.create(type_, name) for type_, name in DOCUMENT_FIELD_SPECS])
