"""Tests for the Field base: label derivation and the abstract viewer/editor factories."""

from pytest import mark, raises
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.field import Field


@mark.parametrize(
    ("name", "expected"),
    [("title", "Title"), ("foo_bar", "Foo Bar"), ("FooBar", "Foo Bar"), ("", "")],
)
def test_make_label_derives_a_human_label_from_a_name(name: str, expected: str) -> None:
    """make_label title-cases and word-splits camelCase/snake_case names.

    **Test steps:**

    * call ``Field.make_label`` on representative names
    * verify each yields the expected human label
    """
    assert Field.make_label(name) == expected


def test_field_label_defaults_to_name_but_respects_an_override() -> None:
    """A field derives its label from name unless one is given.

    **Test steps:**

    * build a field without a label and verify it derives ``"Title"``
    * build one with an explicit label and verify it is kept verbatim
    """
    assert Field[str]("title").label == "Title"
    assert Field[str]("title", "Custom Label").label == "Custom Label"


def test_field_base_factories_require_a_subclass(model: RehuDocumentModel) -> None:
    """The Field base leaves ``make_viewer`` / ``make_editors`` abstract for subclasses.

    **Test steps:**

    * build a bare ``Field`` and resolve its binding on the model
    * verify ``make_viewer`` and ``make_editors`` both raise ``NotImplementedError``
    """
    field = Field[str]("title")
    binding = model.bind(field)
    with raises(NotImplementedError):
        field.make_viewer(binding)
    with raises(NotImplementedError):
        field.make_editors(binding)
