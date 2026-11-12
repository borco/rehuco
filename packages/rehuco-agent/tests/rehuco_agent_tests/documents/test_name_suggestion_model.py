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
from rehuco_agent.settings.move_settings import shared_move_settings
from rehuco_core import Layouts, MappedRoot, RehuDocument, ReplacementRule
from rehuco_core.access import ResourceKey

BY_AUTHOR: Final = {"*": ("{authors}/{title}",)}
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


def test_changed_fires_when_the_move_settings_are_saved(name_suggestions: NameSuggestionModel) -> None:
    """Applying the Files page re-emits ``changed``, since a place's verified marker reads the move settings (#649).

    **Test steps:**

    * connect to ``changed``
    * announce a save of the shared `MoveSettings`
    * verify the signal fired
    """
    fired: list[bool] = []
    name_suggestions.changed.connect(lambda: fired.append(True))

    shared_move_settings().changed.emit()

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


def root_at(path: Path, layouts: Layouts | None = None, fallbacks: dict[str, str] | None = None) -> MappedRoot:
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
    * check the first place is where the record is, the second ``Jane/Foo`` in the record's root, the third
      ``Jane/Foo`` in the other, each naming where the record is now
    """
    root = root_at(tmp_path / "tutorials")
    other = root_at(tmp_path / "other")
    place(authored, root.path / "Old" / "Foo" / "info.rehu")
    catalog = catalog_of(signals, other, root)

    current, own, elsewhere = NameSuggestionModel(authored, catalog).root_destinations()

    assert (current.relative, current.here, current.same_root) == (PurePosixPath("Old/Foo"), True, True)
    jane = PurePosixPath("Jane/Foo")
    assert own == RootDestination(
        "Tutorials", jane, root.path, root.root_id, False, root.path, root.root_id, BY_AUTHOR["*"][0]
    )
    assert own.same_root and own.into == root.path / "Jane" and own.name == "Foo"
    assert elsewhere == RootDestination(
        "Tutorials", jane, other.path, other.root_id, False, root.path, root.root_id, BY_AUTHOR["*"][0]
    )
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


def test_a_keep_name_layout_puts_a_nested_record_at_the_top_and_shows_where_it_is_first(
    tmp_path: Path, authored: RehuDocumentModel, signals: RootsSignals
) -> None:
    """``*`` is the folder name at the root's top under every root, its own included; where the record sits is a row of
    its own, first and already there (#643).

    **Test steps:**

    * open a record at ``ArtStation/Bros/Foo/info.rehu`` under a ``*`` root, beside another ``*`` root
    * check the first place is ``ArtStation/Bros/Foo`` in the own root, the record is there, no layout rendered it
    * check the second is ``Foo`` in the own root, not there, rendered by ``*``
    * check the third is ``Foo`` in the other root, not there
    """
    root = root_at(tmp_path / "tutorials", {"*": ("*",)})
    other = root_at(tmp_path / "other", {"*": ("*",)})
    place(authored, root.path / "ArtStation" / "Bros" / "Foo" / "info.rehu")

    current, top, elsewhere = NameSuggestionModel(authored, catalog_of(signals, root, other)).root_destinations()

    assert (current.relative, current.here, current.root_id, current.template) == (
        PurePosixPath("ArtStation/Bros/Foo"),
        True,
        root.root_id,
        "",
    )
    assert (top.relative, top.here, top.root_id, top.template) == (PurePosixPath("Foo"), False, root.root_id, "*")
    assert (elsewhere.relative, elsewhere.here, elsewhere.root_id) == (PurePosixPath("Foo"), False, other.root_id)


def test_a_record_at_the_place_its_layout_gives_has_one_row(
    tmp_path: Path, authored: RehuDocumentModel, signals: RootsSignals
) -> None:
    """When the layout's place is where the record sits, the own root offers that one row, already there (#643).

    **Test steps:**

    * open a record at ``Foo/info.rehu`` directly under a ``*`` root
    * check there is one place, ``Foo``, and the record is there
    """
    root = root_at(tmp_path, {"*": ("*",)})
    place(authored, root.path / "Foo" / "info.rehu")

    (only,) = NameSuggestionModel(authored, catalog_of(signals, root)).root_destinations()

    assert (only.relative, only.here) == (PurePosixPath("Foo"), True)


def test_a_record_under_a_root_that_does_not_take_its_type_still_shows_where_it_is(
    tmp_path: Path, authored: RehuDocumentModel, signals: RootsSignals
) -> None:
    """A type the own root's layouts refuse leaves the current place alone to show (#643).

    **Test steps:**

    * open a tutorial at ``Old/Foo/info.rehu`` under a root laid out for another type only
    * check the one place is ``Old/Foo``, already there
    """
    root = root_at(tmp_path, {"reference_images": ("*",)})
    place(authored, root.path / "Old" / "Foo" / "info.rehu")

    (only,) = NameSuggestionModel(authored, catalog_of(signals, root)).root_destinations()

    assert (only.relative, only.here) == (PurePosixPath("Old/Foo"), True)


def test_a_record_that_is_its_roots_folder_has_that_root_alone_already_there(
    tmp_path: Path, authored: RehuDocumentModel, signals: RootsSignals
) -> None:
    """A record at its root's top is not placed by any layout: its root is the one place, already there, and no other
    root offers one (#641).

    **Test steps:**

    * open ``info.rehu`` directly in a root laid out by author, beside another root
    * check the only place is the own root's, with no path, already there
    * check no other root offers a place, and that the root's folder is the record's
    """
    root = root_at(tmp_path / "tutorials")
    other = root_at(tmp_path / "other")
    place(authored, root.path / "info.rehu")
    suggestions = NameSuggestionModel(authored, catalog_of(signals, other, root))

    (only,) = suggestions.root_destinations()

    assert only == RootDestination("Tutorials", PurePosixPath(), root.path, root.root_id, True, root.path, root.root_id)
    assert suggestions.is_root_folder()


def test_a_record_that_is_its_roots_folder_is_offered_no_rename(
    tmp_path: Path, authored: RehuDocumentModel, signals: RootsSignals
) -> None:
    """No name is suggested for a record at its root's top, so nothing renames the root's folder (#641).

    **Test steps:**

    * open ``info.rehu`` directly in a root
    * check there is no suggestion
    """
    root = root_at(tmp_path / "tutorials")
    place(authored, root.path / "info.rehu")

    assert not NameSuggestionModel(authored, catalog_of(signals, root)).suggestions()


@mark.parametrize("record", ["Foo/info.rehu", "foo.rehu"])
def test_a_record_below_its_roots_top_is_not_its_roots_folder(
    tmp_path: Path, authored: RehuDocumentModel, signals: RootsSignals, record: str
) -> None:
    """A directory-scoped record one level down, and a file-scoped record at the top, are placed as any other (#641).

    **Test steps:**

    * open each record under a root
    * check it is not taken for the root's folder, and its own root's place has a path
    """
    root = root_at(tmp_path / "tutorials")
    place(authored, root.path / record)
    suggestions = NameSuggestionModel(authored, catalog_of(signals, root))

    assert not suggestions.is_root_folder()
    assert suggestions.root_destinations()[0].relative.parts


def test_a_record_under_no_root_is_not_a_roots_folder(
    tmp_path: Path, authored: RehuDocumentModel, signals: RootsSignals
) -> None:
    """A record with no root, or no catalog, or no path, is not a root's folder (#641).

    **Test steps:**

    * ask a record outside every root, one with no catalog, and one with no path
    * check none is
    """
    place(authored, tmp_path / "elsewhere" / "info.rehu")

    assert not NameSuggestionModel(authored, catalog_of(signals, root_at(tmp_path / "tutorials"))).is_root_folder()
    assert not NameSuggestionModel(authored).is_root_folder()
    authored.path = None
    assert not NameSuggestionModel(authored, catalog_of(signals)).is_root_folder()


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
    * check only the record's own root offers places
    """
    root = root_at(tmp_path / "tutorials")
    away = root_at(tmp_path / "away")
    pictures = root_at(tmp_path / "pictures", {"reference_images": ("*",)})
    place(authored, root.path / "Foo" / "info.rehu")
    catalog = catalog_of(signals, away, root, pictures, unreachable=frozenset({away.root_id}))

    places = NameSuggestionModel(authored, catalog).root_destinations()

    assert {place.root_id for place in places} == {root.root_id}


@mark.parametrize(
    ("layouts", "unreachable"),
    [
        param({"reference_images": ("*",)}, False, id="a layout not taking the type"),
        param(BY_AUTHOR, False, id="a field left empty with no fallback"),
        param({"*": ("*",)}, True, id="a root that cannot be reached"),
    ],
)
def test_no_place_is_offered(
    tmp_path: Path, model: RehuDocumentModel, signals: RootsSignals, layouts: Layouts, unreachable: bool
) -> None:
    """Only a place that can be built is offered: for a root that does not take the record, or one needing a field the
    record leaves empty, only where the record is now (#643) -- and nothing at all for a record whose own root is not
    reached now.

    **Test steps:**

    * open a record with no authors under a root with the given layout
    * check the places are only the one the record sits at, or none when its root cannot be reached
    """
    root = root_at(tmp_path / "tutorials", layouts)
    place(model, root.path / "Foo" / "info.rehu")
    catalog = catalog_of(signals, root, unreachable=frozenset({root.root_id} if unreachable else ()))

    places = NameSuggestionModel(model, catalog).root_destinations()

    assert [(place.relative, place.here) for place in places] == ([] if unreachable else [(PurePosixPath("Foo"), True)])


def test_a_fallback_fills_an_empty_field(tmp_path: Path, model: RehuDocumentModel, signals: RootsSignals) -> None:
    """A field the record leaves empty renders as the root's fallback for it.

    **Test steps:**

    * open a record with no authors under a root laid out by author, with a fallback for authors
    * check the places are where the record is, then under the fallback
    """
    root = root_at(tmp_path, fallbacks={"authors": "Unknown"})
    place(model, tmp_path / "Foo" / "info.rehu")

    places = NameSuggestionModel(model, catalog_of(signals, root)).root_destinations()

    assert [place.relative for place in places] == [PurePosixPath("Foo"), PurePosixPath("Unknown/Foo")]


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


def test_each_template_of_a_root_is_a_place_in_row_order_and_two_alike_are_one(
    tmp_path: Path, authored: RehuDocumentModel, signals: RootsSignals
) -> None:
    """A root with several templates for the type offers a place for each, in row order, each carrying its template;
    two templates rendering the same place offer it once (#638).

    **Test steps:**

    * open a record at ``Old/Foo/info.rehu`` under a root whose templates are by author, by title and by title again
    * check the places after the one the record sits at are ``Jane/Foo`` then ``Foo``, each with its template
    """
    root = root_at(tmp_path, {"*": ("{authors}/{title}", "{title}", "{title}/")})
    place(authored, root.path / "Old" / "Foo" / "info.rehu")

    _, by_author, by_title = NameSuggestionModel(authored, catalog_of(signals, root)).root_destinations()

    assert (by_author.relative, by_author.template) == (PurePosixPath("Jane/Foo"), "{authors}/{title}")
    assert (by_title.relative, by_title.template) == (PurePosixPath("Foo"), "{title}")


def test_the_current_place_is_not_added_when_one_of_the_templates_puts_the_record_there(
    tmp_path: Path, authored: RehuDocumentModel, signals: RootsSignals
) -> None:
    """When any of the own root's templates renders where the record sits, that is its ``here`` row and no extra
    current-place row is made (#638).

    **Test steps:**

    * open a record at ``Foo/info.rehu`` under a root whose templates are by author, then by title
    * check two places, the second the one the record is at
    """
    root = root_at(tmp_path, {"*": ("{authors}/{title}", "{title}")})
    place(authored, root.path / "Foo" / "info.rehu")

    places = NameSuggestionModel(authored, catalog_of(signals, root)).root_destinations()

    assert [(each.relative, each.here) for each in places] == [
        (PurePosixPath("Jane/Foo"), False),
        (PurePosixPath("Foo"), True),
    ]
