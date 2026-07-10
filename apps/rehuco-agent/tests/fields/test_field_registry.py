"""Tests for FieldRegistry: type -> class resolution."""

from pytest import raises
from rehuco_agent.fields.boolean_field import BooleanField
from rehuco_agent.fields.date_field import DateField
from rehuco_agent.fields.duration_field import DurationField
from rehuco_agent.fields.field_registry import FieldRegistry
from rehuco_agent.fields.int_field import IntField
from rehuco_agent.fields.multiple_choice_field import MultipleChoiceField
from rehuco_agent.fields.path_field import PathField
from rehuco_agent.fields.rating_field import RatingField
from rehuco_agent.fields.text_field import TextField
from rehuco_agent.fields.text_list_field import TextListField
from rehuco_agent.fields.url_field import UrlField

from fields.field_testers import TEST_EDITOR_TAB, TEST_VIEWER_TAB


def test_registry_resolves_a_type_to_its_class() -> None:
    """The registry maps the ``text`` type to ``TextField`` and instantiates it.

    **Test steps:**

    * build a default registry
    * verify the ``text`` type resolves to ``TextField``
    * create a field and verify its name and derived label
    """
    registry = FieldRegistry()

    assert registry.types["text"] is TextField

    field = registry.create("text", "publisher", viewer_tab=TEST_VIEWER_TAB, editor_tab=TEST_EDITOR_TAB)
    assert isinstance(field, TextField)
    assert field.name == "publisher"
    assert field.label == "Publisher"


def test_registry_resolves_the_scalar_field_types() -> None:
    """The registry maps the ``bool`` / ``rating`` / ``int`` types to their classes.

    **Test steps:**

    * build a default registry
    * verify each scalar type resolves to its ``Field`` subclass
    """
    registry = FieldRegistry()

    assert registry.types["bool"] is BooleanField
    assert registry.types["rating"] is RatingField
    assert registry.types["int"] is IntField


def test_registry_resolves_the_list_and_url_field_types() -> None:
    """The registry maps the ``text_list`` / ``url`` types to their classes.

    **Test steps:**

    * build a default registry
    * verify each type resolves to its ``Field`` subclass
    """
    registry = FieldRegistry()

    assert registry.types["text_list"] is TextListField
    assert registry.types["url"] is UrlField


def test_registry_resolves_the_date_and_duration_field_types() -> None:
    """The registry maps the ``date`` / ``duration`` types to their classes.

    **Test steps:**

    * build a default registry
    * verify each type resolves to its ``Field`` subclass
    """
    registry = FieldRegistry()

    assert registry.types["date"] is DateField
    assert registry.types["duration"] is DurationField


def test_registry_resolves_the_multi_choice_and_path_field_types() -> None:
    """The registry maps the ``multi_choice`` / ``path`` types to their classes.

    **Test steps:**

    * build a default registry
    * verify each type resolves to its ``Field`` subclass
    """
    registry = FieldRegistry()

    assert registry.types["multi_choice"] is MultipleChoiceField
    assert registry.types["path"] is PathField


def test_registry_raises_on_an_unknown_type() -> None:
    """An unregistered type raises (the unknown-field fallback is deferred to A2.8/#28).

    **Test steps:**

    * build a default registry
    * verify ``create`` on an unregistered type raises ``KeyError``
    """
    with raises(KeyError):
        FieldRegistry().create("multi-choice", "level", viewer_tab=TEST_VIEWER_TAB, editor_tab=TEST_EDITOR_TAB)
