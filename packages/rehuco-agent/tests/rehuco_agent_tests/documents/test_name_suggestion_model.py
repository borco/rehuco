"""Tests for NameSuggestionModel: the rename-suggestion compute role extracted out of
RehuDocumentModel (#46).
"""

from pytest import fixture, mark, param
from rehuco_agent.documents.name_suggestion_model import NAME_SUGGESTION_PATTERNS, NameSuggestionModel
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
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


def test_suggestions_uses_an_empty_year_when_released_is_none(model: RehuDocumentModel) -> None:
    """A ``None`` ``released`` (absent, [[field-schema#deferred-items]]) yields an empty year in the
    ``[{year}]`` pattern rather than crashing on ``None[:4]``.

    **Test steps:**

    * build suggestions over the shared fixture, which sets no ``released``
    * verify the year-bracket pattern interpolates an empty year
    """
    assert model.released is None

    suggestions = NameSuggestionModel(model).suggestions()

    assert suggestions[NAME_SUGGESTION_PATTERNS.index("{title} [{year}]")] == "Foo []"


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


# endregion
