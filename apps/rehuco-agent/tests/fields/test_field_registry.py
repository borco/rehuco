"""Tests for FieldRegistry: type -> class resolution."""

from pytest import raises
from rehuco_agent.fields.field_registry import FieldRegistry
from rehuco_agent.fields.text_field import TextField


def test_registry_resolves_a_type_to_its_class() -> None:
    """The registry maps the ``text`` type to ``TextField`` and instantiates it.

    **Test steps:**

    * build a default registry
    * verify the ``text`` type resolves to ``TextField``
    * create a field and verify its name and derived label
    """
    registry = FieldRegistry()

    assert registry.types["text"] is TextField

    field = registry.create("text", "publisher")
    assert isinstance(field, TextField)
    assert field.name == "publisher"
    assert field.label == "Publisher"


def test_registry_raises_on_an_unknown_type() -> None:
    """An unregistered type raises (the unknown-field fallback is deferred to A2.8/#28).

    **Test steps:**

    * build a default registry
    * verify ``create`` on an unregistered type raises ``KeyError``
    """
    with raises(KeyError):
        FieldRegistry().create("switch", "complete")
