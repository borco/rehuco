"""Tests for NameSuggestionModel: the rename-suggestion compute role extracted out of
RehuDocumentModel (#46).
"""

from pathlib import Path, PurePosixPath
from typing import Final
from unittest.mock import Mock
from uuid import uuid4

from PySide6.QtCore import QObject, Signal
from pytest import fixture, mark, param
from rehuco_agent.documents.name_suggestion_model import NameSuggestionModel, RootDestination
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.rehuco import RootCatalog
from rehuco_agent.settings.location_replacements_settings import shared_location_replacements_settings
from rehuco_agent.settings.location_templates_settings import (
    NAME_SUGGESTION_PATTERNS,
    shared_location_templates_settings,
)
from rehuco_core import MappedRoot, RehuDocument, ReplacementRule
from rehuco_core.access import ResourceKey

BY_AUTHOR: Final = {"*": "{authors}/{title}"}
"""A layout filing every type under its authors."""


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


def test_count_renders_on_a_type_declaring_advertised_count(model: RehuDocumentModel) -> None:
    """``{count}`` interpolates ``advertised_count`` on ReferenceImages, whose plugin declares it (#349).

    **Test steps:**

    * customize the reference-images list to a pattern naming ``{count}``
    * switch the model to that type and set ``advertised_count``
    * verify the suggestion carries the count claim
    """
    settings = shared_location_templates_settings()
    settings.patterns = {**settings.patterns, "reference_images": ("{title} ({count})",)}
    model.resource_type = "reference_images"
    model.advertised_count = "900+"

    assert NameSuggestionModel(model).suggestions() == ["Foo (900+)"]


def test_an_absent_count_drops_its_optional_group(model: RehuDocumentModel) -> None:
    """A ``None`` ``advertised_count`` reads as empty, so a ``{{ ({count})}}`` group drops out the way a
    missing year does -- no ``Foo ()`` (#349).

    **Test steps:**

    * customize the reference-images list to a pattern wrapping ``{count}`` in a group
    * switch the model to that type, leaving ``advertised_count`` unset
    * verify the bare title is offered, with no empty parentheses
    """
    settings = shared_location_templates_settings()
    settings.patterns = {**settings.patterns, "reference_images": ("{title}{{ ({count})}}",)}
    model.resource_type = "reference_images"
    assert model.advertised_count is None

    assert NameSuggestionModel(model).suggestions() == ["Foo"]


def test_a_count_pattern_is_not_offered_on_a_type_without_advertised_count(model: RehuDocumentModel) -> None:
    """A tutorial's plugin does not declare ``advertised_count``, so a stored ``{count}`` row is invalid
    for it and contributes nothing (#349) -- the same "kept but not effective" rule any unknown
    placeholder gets.

    **Test steps:**

    * customize the tutorial list to a pattern naming ``{count}`` alongside a good one
    * verify only the good pattern's name is offered
    """
    settings = shared_location_templates_settings()
    settings.patterns = {**settings.patterns, "tutorial": ("{title} ({count})", "{title}")}

    assert NameSuggestionModel(model).suggestions() == ["Foo"]


def test_changed_fires_when_advertised_count_changes(
    model: RehuDocumentModel, name_suggestions: NameSuggestionModel
) -> None:
    """A change to ``advertised_count`` re-emits ``changed`` without a reopen (#349).

    **Test steps:**

    * connect to ``changed``
    * change the wrapped model's ``advertised_count``
    * verify the signal fired
    """
    fired: list[bool] = []
    name_suggestions.changed.connect(lambda: fired.append(True))

    model.advertised_count = "500"

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


def test_suggestions_run_through_the_saved_replacement_rules(model: RehuDocumentModel) -> None:
    """A rendered name goes through `LocationReplacementsSettings.rules` before it reaches a `PathField`
    (#350).

    **Test steps:**

    * customize the tutorial pattern list to interpolate a colon-space
    * set the shared replacement rules to the shipped seed
    * verify the suggestion carries the replaced separator, not the original
    """
    settings = shared_location_templates_settings()
    settings.patterns = {**settings.patterns, "tutorial": ("{publisher}: {title}",)}
    shared_location_replacements_settings().rules = (ReplacementRule(": ", " - "),)

    assert NameSuggestionModel(model).suggestions() == ["Bar - Foo"]


def test_changed_fires_when_the_location_replacements_settings_apply(name_suggestions: NameSuggestionModel) -> None:
    """Applying a Location Replacements settings page re-emits ``changed`` without a reopen (#350).

    **Test steps:**

    * connect to ``changed``
    * reassign the shared `LocationReplacementsSettings.rules`, as a save would
    * verify the signal fired
    """
    fired: list[bool] = []
    name_suggestions.changed.connect(lambda: fired.append(True))

    shared_location_replacements_settings().rules = (ReplacementRule(":", "-"),)

    assert fired == [True]


# endregion


# region the roots' places (#579, #339)
class RootsSignals(QObject):
    """The two signals a `RootCatalog` announces its roots changing by, for a mocked catalog to carry."""

    roots_changed = Signal()
    root_reachable = Signal(object, bool)


def catalog_of(signals: RootsSignals, *roots: MappedRoot, unreachable: frozenset[object] = frozenset()) -> Mock:
    """A mocked `RootCatalog` mapping ``roots``, its signals real.

    :param signals: the signals it carries.
    :param roots: the roots this machine reaches.
    :param unreachable: the ids of those it cannot reach now.
    :returns: the catalog.
    """
    catalog = Mock(spec=RootCatalog)
    catalog.mapped_roots.return_value = roots
    catalog.unreachable_roots.return_value = unreachable
    catalog.roots_changed = signals.roots_changed
    catalog.root_reachable = signals.root_reachable
    return catalog


def root_at(path: Path, layouts: dict[str, str] | None = None, fallbacks: dict[str, str] | None = None) -> MappedRoot:
    """A root mapped at ``path``.

    :param path: its folder.
    :param layouts: its layouts; :data:`BY_AUTHOR` when omitted.
    :param fallbacks: its fallbacks.
    :returns: the root.
    """
    return MappedRoot(
        uuid4(), "Tutorials", "//nas/tutorials", path, layouts=layouts or BY_AUTHOR, fallbacks=fallbacks or {}
    )


def place(model: RehuDocumentModel, record: Path) -> None:
    """Put ``model`` at ``record``, as an open does.

    :param model: the document.
    :param record: its ``.rehu``.
    """
    model.key = ResourceKey(record)
    model.path = record


@fixture(name="signals")
def fixture_signals() -> RootsSignals:
    """The mocked catalog's signals.

    :returns: them.
    """
    return RootsSignals()


@fixture(name="authored")
def fixture_authored(model: RehuDocumentModel) -> RehuDocumentModel:
    """The sample document with an author.

    :param model: the sample document.
    :returns: it.
    """
    model.authors = ["Jane"]
    return model


def test_the_root_holding_the_record_gives_its_place_first_and_every_other_root_its_own(
    tmp_path: Path, authored: RehuDocumentModel, signals: RootsSignals
) -> None:
    """Each root's layout renders where it puts the record, named by the root: the root holding the record first,
    then the others in the catalog's order (#339).

    **Test steps:**

    * open a record at ``Old/Foo/info.rehu`` under a root laid out by author, listed after another root
    * check the first place is ``Jane/Foo`` in the record's root, the second ``Jane/Foo`` in the other, each naming
      where the record is now
    """
    root = root_at(tmp_path / "tutorials")
    other = root_at(tmp_path / "other")
    place(authored, root.path / "Old" / "Foo" / "info.rehu")
    catalog = catalog_of(signals, other, root)

    own, elsewhere = NameSuggestionModel(authored, catalog).root_destinations()

    jane = PurePosixPath("Jane/Foo")
    assert own == RootDestination("Tutorials", jane, root.path, root.root_id, False, root.path, root.root_id)
    assert own.same_root and own.into == root.path / "Jane" and own.name == "Foo"
    assert elsewhere == RootDestination("Tutorials", jane, other.path, other.root_id, False, root.path, root.root_id)
    assert not elsewhere.same_root


def test_a_record_already_there_is_marked_so(
    tmp_path: Path, authored: RehuDocumentModel, signals: RootsSignals
) -> None:
    """A file-scoped record already at its place, spelled in another case, is there.

    **Test steps:**

    * open ``jane/foo.rehu`` under a root laid out by author
    * check the place says the record is there
    """
    root = root_at(tmp_path)
    place(authored, tmp_path / "jane" / "foo.rehu")

    (destination,) = NameSuggestionModel(authored, catalog_of(signals, root)).root_destinations()

    assert destination.here


def test_a_record_under_no_root_is_offered_every_root(
    tmp_path: Path, authored: RehuDocumentModel, signals: RootsSignals
) -> None:
    """A stray record -- opened from outside every root -- is offered each root's place, with no root of its own.

    **Test steps:**

    * open a record outside two roots
    * check both roots offer their place, neither the record's own
    """
    first, second = root_at(tmp_path / "a"), root_at(tmp_path / "b")
    place(authored, tmp_path / "elsewhere" / "Foo" / "info.rehu")

    places = NameSuggestionModel(authored, catalog_of(signals, first, second)).root_destinations()

    assert [(place.root_id, place.source_root, place.same_root) for place in places] == [
        (first.root_id, None, False),
        (second.root_id, None, False),
    ]


def test_another_root_that_cannot_take_the_record_is_left_out(
    tmp_path: Path, authored: RehuDocumentModel, signals: RootsSignals
) -> None:
    """Another root offers no place when it cannot be reached now, or its layout does not take the record.

    **Test steps:**

    * open a record under a root, beside one that cannot be reached and one taking only another type
    * check only the record's own root offers a place
    """
    root = root_at(tmp_path / "tutorials")
    away = root_at(tmp_path / "away")
    pictures = root_at(tmp_path / "pictures", {"reference_images": "*"})
    place(authored, root.path / "Foo" / "info.rehu")
    catalog = catalog_of(signals, away, root, pictures, unreachable=frozenset({away.root_id}))

    places = NameSuggestionModel(authored, catalog).root_destinations()

    assert [place.root_id for place in places] == [root.root_id]


@mark.parametrize(
    ("layouts", "unreachable"),
    [
        param({"reference_images": "*"}, False, id="a layout not taking the type"),
        param(BY_AUTHOR, False, id="a field left empty with no fallback"),
        param({"*": "*"}, True, id="a root that cannot be reached"),
    ],
)
def test_no_place_is_offered(
    tmp_path: Path, model: RehuDocumentModel, signals: RootsSignals, layouts: dict[str, str], unreachable: bool
) -> None:
    """Only a place that can be built is offered: none for a root that does not take the record, or one needing a
    field the record leaves empty -- and nothing at all for a record whose own root is not reached now.

    **Test steps:**

    * open a record with no authors under a root with the given layout
    * check there is no place
    """
    root = root_at(tmp_path / "tutorials", layouts)
    place(model, root.path / "Foo" / "info.rehu")
    catalog = catalog_of(signals, root, unreachable=frozenset({root.root_id} if unreachable else ()))

    assert not NameSuggestionModel(model, catalog).root_destinations()


def test_a_fallback_fills_an_empty_field(tmp_path: Path, model: RehuDocumentModel, signals: RootsSignals) -> None:
    """A field the record leaves empty renders as the root's fallback for it.

    **Test steps:**

    * open a record with no authors under a root laid out by author, with a fallback for authors
    * check the place is under the fallback
    """
    root = root_at(tmp_path, fallbacks={"authors": "Unknown"})
    place(model, tmp_path / "Foo" / "info.rehu")

    (destination,) = NameSuggestionModel(model, catalog_of(signals, root)).root_destinations()

    assert destination.relative == PurePosixPath("Unknown/Foo")


def test_no_catalog_or_no_path_offers_no_place(
    tmp_path: Path, authored: RehuDocumentModel, signals: RootsSignals
) -> None:
    """Without a catalog, or before the record has a path, there is no place to offer.

    **Test steps:**

    * ask a model with no catalog, then one with a catalog over a record with no path
    * check neither offers a place
    """
    assert not NameSuggestionModel(authored).root_destinations()
    assert not NameSuggestionModel(authored, catalog_of(signals, root_at(tmp_path))).root_destinations()


@mark.parametrize("signal", ["roots_changed", "root_reachable", "path"])
def test_changed_fires_when_the_place_may_have_moved(
    tmp_path: Path, model: RehuDocumentModel, signals: RootsSignals, signal: str
) -> None:
    """The catalog's roots changing, a root's reach changing, or the record moving re-emits ``changed``.

    **Test steps:**

    * connect to ``changed`` of a model with a catalog
    * emit the catalog's signal, or move the record
    * check it fired
    """
    suggestions = NameSuggestionModel(model, catalog_of(signals, root_at(tmp_path)))
    fired: list[bool] = []
    suggestions.changed.connect(lambda: fired.append(True))

    if signal == "roots_changed":
        signals.roots_changed.emit()
    elif signal == "root_reachable":
        signals.root_reachable.emit(uuid4(), False)
    else:
        model.path = tmp_path / "info.rehu"

    assert fired == [True]


@mark.parametrize("signal", ["roots_changed", "root_reachable"])
def test_which_roots_are_reachable_is_asked_once_until_the_catalog_says_it_changed(
    tmp_path: Path, authored: RehuDocumentModel, signals: RootsSignals, signal: str
) -> None:
    """Asking the catalog which roots cannot be reached reads its cache, so the answer is kept across renders -- an
    edit of a field asks nothing -- and asked again once the catalog says its roots or their reach changed.

    **Test steps:**

    * ask for the place three times, editing the title between: the catalog was asked once
    * make the root unreachable and emit the catalog's signal: the place is gone, the catalog asked once more
    """
    root = root_at(tmp_path)
    place(authored, tmp_path / "Old" / "Foo" / "info.rehu")
    catalog = catalog_of(signals, root)
    suggestions = NameSuggestionModel(authored, catalog)

    assert suggestions.root_destinations()
    authored.title = "Bar"
    assert suggestions.root_destinations()
    assert suggestions.root_destinations()
    assert catalog.unreachable_roots.call_count == 1

    catalog.unreachable_roots.return_value = frozenset({root.root_id})
    if signal == "roots_changed":
        signals.roots_changed.emit()
    else:
        signals.root_reachable.emit(root.root_id, False)

    assert not suggestions.root_destinations()
    assert not suggestions.root_destinations()
    assert catalog.unreachable_roots.call_count == 2


# endregion
