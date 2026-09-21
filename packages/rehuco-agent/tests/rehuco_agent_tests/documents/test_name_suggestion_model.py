"""Tests for NameSuggestionModel: the rename-suggestion compute role extracted out of
RehuDocumentModel (#46).
"""

from pytest import fixture, mark, param
from rehuco_agent.documents.name_suggestion_model import NameSuggestionModel
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.settings.location_templates_settings import (
    NAME_SUGGESTION_PATTERNS,
    shared_location_templates_settings,
)
from rehuco_core import RehuDocument


# region fixtures
@fixture
def document() -> RehuDocument:
    """An in-memory document with a primary source carrying title/publisher."""
    return RehuDocument(
        {
            "type": "Tutorial",
            "sources": [{"title": "Foo", "publisher": "Bar", "primary": True}],
        }
    )


@fixture
def model(document: RehuDocument) -> RehuDocumentModel:
    """A view-model wrapping the sample document."""
    return RehuDocumentModel(document)


@fixture
def name_suggestions(model: RehuDocumentModel) -> NameSuggestionModel:
    """A suggestion model built over the sample view-model."""
    return NameSuggestionModel(model)


# endregion


# region NameSuggestionModel tests
def test_suggestions_interpolate_the_record_fields() -> None:
    """``suggestions`` formats the patterns from title / publisher / joined authors / released year.

    **Test steps:**

    * build a model with a title, publisher, two authors, and a released date
    * verify each pattern is interpolated from those fields
    """
    document = RehuDocument(
        {
            "type": "Tutorial",
            "sources": [{"title": "Intro", "publisher": "Acme", "primary": True}],
            "authors": ["Jane", "John"],
            "released": "2025-03",
        }
    )
    model = RehuDocumentModel(document)

    assert NameSuggestionModel(model).suggestions() == [
        "Intro",
        "Acme - Intro",
        "Intro [2025]",
        "Jane, John - Intro",
    ]


def test_a_missing_year_drops_its_optional_group_rather_than_crashing(model: RehuDocumentModel) -> None:
    """A ``None`` ``released`` (absent, [[field-schema#deferred-items]]) reads as an empty year, so the
    shipped ``{{ [{year}]}}`` group drops out -- no ``Foo []``, and no crash on ``None[:4]``.

    **Test steps:**

    * build suggestions over the shared fixture, which sets no ``released``
    * verify no suggestion carries empty brackets
    """
    assert model.released is None
    assert "{title}{{ [{year}]}}" in NAME_SUGGESTION_PATTERNS

    suggestions = NameSuggestionModel(model).suggestions()

    assert "Foo" in suggestions
    assert not any("[]" in suggestion for suggestion in suggestions)


def test_patterns_rendering_the_same_name_are_merged(model: RehuDocumentModel) -> None:
    """A record carrying only a title renders every shipped default to the title -- offered once.

    **Test steps:**

    * build suggestions over the shared fixture, then over one with the publisher cleared too
    * verify the publisher-less record yields the title once and nothing else
    """
    model.publisher = ""

    assert NameSuggestionModel(model).suggestions() == ["Foo"]


def test_an_invalid_stored_pattern_is_not_offered(model: RehuDocumentModel) -> None:
    """A row the settings page keeps flagged never reaches a document (#322).

    **Test steps:**

    * store a list holding a good pattern and one naming an unknown placeholder
    * verify only the good one renders into a suggestion
    """
    settings = shared_location_templates_settings()
    settings.patterns = {**settings.patterns, "tutorial": ("{title} ({series})", "{publisher} - {title}")}

    assert NameSuggestionModel(model).suggestions() == ["Bar - Foo"]


@mark.parametrize(
    "attr", [param("title", id="title"), param("authors", id="authors"), param("released", id="released")]
)
def test_changed_fires_when_a_source_field_changes(
    attr: str, model: RehuDocumentModel, name_suggestions: NameSuggestionModel
) -> None:
    """``changed`` fires when a field the suggestions are built from changes.

    **Test steps:**

    * connect to ``changed``
    * change one of the source fields (title / authors / released) on the wrapped model
    * verify the signal fired
    """
    fired: list[bool] = []
    name_suggestions.changed.connect(lambda: fired.append(True))

    setattr(model, attr, ["Someone"] if attr == "authors" else "changed")

    assert fired == [True]


def test_changed_does_not_fire_for_unrelated_fields(
    model: RehuDocumentModel, name_suggestions: NameSuggestionModel
) -> None:
    """A change to a field the suggestions don't use doesn't fire ``changed``.

    **Test steps:**

    * connect to ``changed``
    * change an unrelated field (``rating``) on the wrapped model
    * verify the signal did not fire
    """
    fired: list[bool] = []
    name_suggestions.changed.connect(lambda: fired.append(True))

    model.rating = 4

    assert not fired


def test_suggestions_follow_the_document_type_pattern_list(model: RehuDocumentModel) -> None:
    """A recognised type reads its own list from `LocationTemplatesSettings`, not another type's (#322).

    **Test steps:**

    * customize the reference-images list in the shared settings
    * switch the model to that type
    * verify suggestions follow the customized list rather than the tutorial default
    """
    settings = shared_location_templates_settings()
    settings.patterns = {**settings.patterns, "reference_images": ("{publisher} - {title}", "{title}")}
    model.resource_type = "reference_images"

    assert NameSuggestionModel(model).suggestions() == ["Bar - Foo", "Foo"]


def test_suggestions_fall_back_to_the_tutorial_list_for_an_unrecognised_type(model: RehuDocumentModel) -> None:
    """A foreign/uninstalled type falls back to the tutorial list (#322).

    **Test steps:**

    * customize the tutorial list in the shared settings
    * switch the model to a type no installed plugin claims
    * verify suggestions follow the customized tutorial list
    """
    settings = shared_location_templates_settings()
    settings.patterns = {**settings.patterns, "tutorial": ("{publisher} - {title}",)}
    model.resource_type = "some_future_plugin"

    assert NameSuggestionModel(model).suggestions() == ["Bar - Foo"]


def test_changed_fires_when_the_resource_type_changes(
    model: RehuDocumentModel, name_suggestions: NameSuggestionModel
) -> None:
    """Switching the document's type re-emits ``changed`` without a reopen (#322).

    **Test steps:**

    * connect to ``changed``
    * switch the model's ``resource_type``
    * verify the signal fired
    """
    fired: list[bool] = []
    name_suggestions.changed.connect(lambda: fired.append(True))

    model.resource_type = "reference_images"

    assert fired == [True]


def test_changed_fires_when_the_location_templates_settings_apply(name_suggestions: NameSuggestionModel) -> None:
    """Applying a Locations settings page re-emits ``changed`` without a reopen (#322).

    **Test steps:**

    * connect to ``changed``
    * reassign the shared `LocationTemplatesSettings.patterns`, as a save would
    * verify the signal fired
    """
    fired: list[bool] = []
    name_suggestions.changed.connect(lambda: fired.append(True))

    settings = shared_location_templates_settings()
    settings.patterns = {**settings.patterns, "tutorial": ("{title}",)}

    assert fired == [True]


# endregion
