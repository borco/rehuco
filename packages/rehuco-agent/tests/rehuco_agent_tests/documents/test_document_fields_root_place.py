"""Tests for the path row's root place as the document form wires it (#579): what the row shows, and what a click
on it moves."""

from pathlib import Path, PurePosixPath
from typing import Final

from borco_pyside.widgets import ElidedLabel
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.document_fields import EDITOR_MAIN_TAB, build_document_form
from rehuco_agent.documents.name_suggestion_model import NameSuggestionModel, RootDestination
from rehuco_agent.documents.rehu_document_image_organizer import RehuDocumentImageOrganizer
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.widgets import PathEditor
from rehuco_agent.fields.widgets.path_editor import UNAVAILABLE_SUFFIX
from rehuco_core import RehuDocument

ROOT: Final = Path(Path.cwd().anchor) / "tutorials"
PLACE: Final = RootDestination("Tutorials", PurePosixPath("Jane/Foo"), ROOT, here=False)
ROW_TEXT: Final = f"Tutorials: {Path('Jane', 'Foo')}"
"""The row's text: the root's name and the place, in the platform's separators as every path the app shows."""


@fixture(name="model")
def fixture_model() -> RehuDocumentModel:
    """A tutorial record at ``Old/Foo`` under the root.

    :returns: its model.
    """
    return RehuDocumentModel(RehuDocument({"type": "Tutorial"}, ROOT / "Old" / "Foo" / "info.rehu"))


def destination_label(
    qtbot: QtBot, model: RehuDocumentModel, suggestions: NameSuggestionModel
) -> tuple[ElidedLabel, tuple[object, ...]]:
    """Build the main editor and return its path row's root-place label.

    :param qtbot: pytest-qt fixture.
    :param model: the record.
    :param suggestions: what the path row reads.
    :returns: the label, and what the caller keeps referenced while it inspects it -- the form, whose fields outlive
        their widgets, and the editor, which qtbot tracks only weakly.
    """
    form = build_document_form(model, suggestions, RehuDocumentImageOrganizer(model))
    editor = form.make_editor(model)[EDITOR_MAIN_TAB]
    qtbot.addWidget(editor)
    path_editor = editor.findChild(PathEditor)
    assert isinstance(path_editor, PathEditor)
    label = path_editor._PathEditor__destination_label  # type: ignore[attr-defined]  # pylint: disable=protected-access
    return label, (form, editor)


def full_text(label: ElidedLabel) -> str:
    """Return a label's un-elided text.

    :param label: the label to inspect.
    :returns: the full text it was given.
    """
    return label._ElidedLabel__full  # type: ignore[attr-defined]  # pylint: disable=protected-access


def test_a_click_on_the_place_moves_the_record_there(
    qtbot: QtBot, model: RehuDocumentModel, mocker: MockerFixture
) -> None:
    """The row names the root and the place; a click moves the record into the place's folder, within the root.

    **Test steps:**

    * give the suggestions a place, nothing occupying it
    * build the editor and check the row's text, live
    * click it and check the model was asked to move into ``Jane`` as ``Foo``, within the root
    """
    suggestions = NameSuggestionModel(model)
    mocker.patch.object(suggestions, "root_destination", return_value=PLACE)
    mocker.patch.object(model, "move_conflicts", return_value=False)
    move = mocker.patch.object(model, "move_in_root", return_value=True)
    label, _kept = destination_label(qtbot, model, suggestions)

    assert full_text(label) == ROW_TEXT
    assert label.isEnabled()

    label.linkActivated.emit("#")

    move.assert_called_once_with(ROOT / "Jane", "Foo", ROOT)


def test_an_occupied_place_is_marked(qtbot: QtBot, model: RehuDocumentModel, mocker: MockerFixture) -> None:
    """A place something else sits at is asked of the model, and shown disabled and marked.

    **Test steps:**

    * give the suggestions a place the model reports occupied
    * check the model was asked about the place's folder and name, and the row is disabled and marked
    """
    suggestions = NameSuggestionModel(model)
    mocker.patch.object(suggestions, "root_destination", return_value=PLACE)
    conflicts = mocker.patch.object(model, "move_conflicts", return_value=True)

    label, _kept = destination_label(qtbot, model, suggestions)

    conflicts.assert_called_with(ROOT / "Jane", "Foo")
    assert not label.isEnabled()
    assert full_text(label) == f"{ROW_TEXT}{UNAVAILABLE_SUFFIX}"


def test_the_place_the_record_is_at_moves_nothing(
    qtbot: QtBot, model: RehuDocumentModel, mocker: MockerFixture
) -> None:
    """Where the record already is is neither asked about nor moved to.

    **Test steps:**

    * give the suggestions the place the record is at
    * check the row is disabled, the conflict check never asked, and a click moves nothing
    """
    suggestions = NameSuggestionModel(model)
    mocker.patch.object(
        suggestions, "root_destination", return_value=RootDestination("Tutorials", PLACE.relative, ROOT, here=True)
    )
    conflicts = mocker.patch.object(model, "move_conflicts")
    move = mocker.patch.object(model, "move_in_root")
    label, _kept = destination_label(qtbot, model, suggestions)

    label.linkActivated.emit("#")

    assert not label.isEnabled()
    conflicts.assert_not_called()
    move.assert_not_called()


def test_no_place_hides_the_row_and_a_click_moves_nothing(
    qtbot: QtBot, model: RehuDocumentModel, mocker: MockerFixture
) -> None:
    """A record whose root offers no place shows no row, and a click that arrives anyway moves nothing.

    **Test steps:**

    * build the editor over suggestions offering no place
    * check the row is hidden, and a click on it moves nothing
    """
    suggestions = NameSuggestionModel(model)
    move = mocker.patch.object(model, "move_in_root")
    label, _kept = destination_label(qtbot, model, suggestions)

    label.linkActivated.emit("#")

    assert label.isHidden()
    move.assert_not_called()
