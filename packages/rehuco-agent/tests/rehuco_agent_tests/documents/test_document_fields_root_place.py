"""Tests for the path row's roots' places as the document form wires them (#579, #339): what the rows show, and what
a click on one moves."""

from pathlib import Path, PurePosixPath
from typing import Final
from unittest.mock import Mock
from uuid import UUID

from borco_pyside.widgets import ElidedLabel
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.document_fields import EDITOR_MAIN_TAB, build_document_form
from rehuco_agent.documents.name_suggestion_model import NameSuggestionModel, RootDestination
from rehuco_agent.documents.record_moves import RecordMoves
from rehuco_agent.documents.rehu_document_image_organizer import RehuDocumentImageOrganizer
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.widgets import PathEditor
from rehuco_agent.fields.widgets.path_editor import UNAVAILABLE_SUFFIX
from rehuco_core import RehuDocument

ROOT: Final = Path(Path.cwd().anchor) / "tutorials"
ARCHIVE: Final = Path(Path.cwd().anchor) / "archive"
ROOT_ID: Final = UUID("00000000-0000-0000-0000-000000000001")
ARCHIVE_ID: Final = UUID("00000000-0000-0000-0000-000000000002")
PLACE: Final = RootDestination("Tutorials", PurePosixPath("Jane/Foo"), ROOT, ROOT_ID, False, ROOT, ROOT_ID)
ELSEWHERE: Final = RootDestination("Archive", PurePosixPath("Foo"), ARCHIVE, ARCHIVE_ID, False, ROOT, ROOT_ID)
ROW_TEXT: Final = f"Tutorials: {Path('Jane', 'Foo')}"
"""The row's text: the root's name and the place, in the platform's separators as every path the app shows."""


@fixture(name="model")
def fixture_model() -> RehuDocumentModel:
    """A tutorial record at ``Old/Foo`` under the root.

    :returns: its model.
    """
    return RehuDocumentModel(RehuDocument({"type": "Tutorial"}, ROOT / "Old" / "Foo" / "info.rehu"))


def path_editor(
    qtbot: QtBot, model: RehuDocumentModel, suggestions: NameSuggestionModel, record_moves: RecordMoves | None = None
) -> tuple[PathEditor, tuple[object, ...]]:
    """Build the main editor and return its path row.

    :param qtbot: pytest-qt fixture.
    :param model: the record.
    :param suggestions: what the path row reads.
    :param record_moves: what a click moves through, if anything.
    :returns: the path row, and what the caller keeps referenced while it inspects it -- the form, whose fields
        outlive their widgets, and the editor, which qtbot tracks only weakly.
    """
    form = build_document_form(model, suggestions, RehuDocumentImageOrganizer(model), record_moves=record_moves)
    editor = form.make_editor(model)[EDITOR_MAIN_TAB]
    qtbot.addWidget(editor)
    found = editor.findChild(PathEditor)
    assert isinstance(found, PathEditor)
    return found, (form, editor)


def labels_of(editor: PathEditor) -> list[ElidedLabel]:
    """Return a path row's root-place labels.

    :param editor: the path row.
    :returns: the labels, in order.
    """
    return editor._PathEditor__destination_labels  # type: ignore[attr-defined]  # pylint: disable=protected-access


def full_text(label: ElidedLabel) -> str:
    """Return a label's un-elided text.

    :param label: the label to inspect.
    :returns: the full text it was given.
    """
    return label._ElidedLabel__full  # type: ignore[attr-defined]  # pylint: disable=protected-access


def test_with_no_queue_only_the_own_root_is_offered_and_moved_to_by_a_rename(
    qtbot: QtBot, model: RehuDocumentModel, mocker: MockerFixture
) -> None:
    """A host with nothing to queue a move on offers only the record's own root's place, moved by a rename.

    **Test steps:**

    * give the suggestions a place in the record's root and one in another, nothing occupying either
    * build the editor with no moves and check only the first row shows, live
    * click it and check the model was asked to move into ``Jane`` as ``Foo``, its root being the record's
    """
    suggestions = NameSuggestionModel(model)
    mocker.patch.object(suggestions, "root_destinations", return_value=(PLACE, ELSEWHERE))
    mocker.patch.object(model, "move_conflicts", return_value=False)
    move = mocker.patch.object(model, "move_in_root", return_value=True)
    editor, _kept = path_editor(qtbot, model, suggestions)

    (label,) = labels_of(editor)
    assert full_text(label) == ROW_TEXT
    assert label.isEnabled()

    label.linkActivated.emit("#")

    move.assert_called_once_with(ROOT / "Jane", "Foo", ROOT)


def test_every_root_is_offered_and_a_click_moves_through_the_queue(
    qtbot: QtBot, model: RehuDocumentModel, mocker: MockerFixture
) -> None:
    """With moves to hand, every root's place is a row, and a click hands that place to them.

    **Test steps:**

    * give the suggestions a place in the record's root and one in another
    * build the editor with moves, check both rows, click the second
    * check the moves were handed the other root's place, and the model moved nothing itself
    """
    suggestions = NameSuggestionModel(model)
    mocker.patch.object(suggestions, "root_destinations", return_value=(PLACE, ELSEWHERE))
    mocker.patch.object(model, "move_conflicts", return_value=False)
    move = mocker.patch.object(model, "move_in_root")
    record_moves = Mock(spec=RecordMoves)
    editor, _kept = path_editor(qtbot, model, suggestions, record_moves)

    assert [full_text(label) for label in labels_of(editor)] == [ROW_TEXT, "Archive: Foo"]

    labels_of(editor)[1].linkActivated.emit("#")

    record_moves.move.assert_called_once_with(ELSEWHERE)
    move.assert_not_called()


def test_an_occupied_place_is_marked(qtbot: QtBot, model: RehuDocumentModel, mocker: MockerFixture) -> None:
    """A place something else sits at is asked of the model, and shown disabled and marked.

    **Test steps:**

    * give the suggestions a place the model reports occupied
    * check the model was asked about the place's folder and name, and the row is disabled and marked
    """
    suggestions = NameSuggestionModel(model)
    mocker.patch.object(suggestions, "root_destinations", return_value=(PLACE,))
    conflicts = mocker.patch.object(model, "move_conflicts", return_value=True)

    editor, _kept = path_editor(qtbot, model, suggestions)

    (label,) = labels_of(editor)
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
    here = RootDestination("Tutorials", PLACE.relative, ROOT, ROOT_ID, True, ROOT, ROOT_ID)
    mocker.patch.object(suggestions, "root_destinations", return_value=(here,))
    conflicts = mocker.patch.object(model, "move_conflicts")
    move = mocker.patch.object(model, "move_in_root")
    editor, _kept = path_editor(qtbot, model, suggestions)

    (label,) = labels_of(editor)
    label.linkActivated.emit("#")

    assert not label.isEnabled()
    conflicts.assert_not_called()
    move.assert_not_called()


def test_a_click_a_render_behind_moves_nothing(qtbot: QtBot, model: RehuDocumentModel, mocker: MockerFixture) -> None:
    """A click on a row whose root no longer offers a place, or on a row there is no longer, moves nothing.

    **Test steps:**

    * show one place, then have the suggestions offer none, and click the row
    * click an index past every row
    * check nothing moved
    """
    suggestions = NameSuggestionModel(model)
    offered = mocker.patch.object(suggestions, "root_destinations", return_value=(PLACE,))
    mocker.patch.object(model, "move_conflicts", return_value=False)
    move = mocker.patch.object(model, "move_in_root")
    editor, _kept = path_editor(qtbot, model, suggestions)
    offered.return_value = ()

    labels_of(editor)[0].linkActivated.emit("#")
    editor.destination_selected.emit(3)

    move.assert_not_called()


def test_no_place_shows_no_row(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A record no root offers a place shows no row.

    **Test steps:**

    * build the editor over suggestions offering no place
    * check there is no row
    """
    editor, _kept = path_editor(qtbot, model, NameSuggestionModel(model))

    assert not labels_of(editor)


def test_a_place_with_no_path_shows_the_label_alone(
    qtbot: QtBot, model: RehuDocumentModel, mocker: MockerFixture
) -> None:
    """The root itself, a record at its top, is its label with nothing after it, disabled and plain (#641).

    **Test steps:**

    * give the suggestions a place with no path, the record already there
    * check the row reads the root's label alone, disabled, and a click moves nothing
    """
    suggestions = NameSuggestionModel(model)
    top = RootDestination("Tutorials", PurePosixPath(), ROOT, ROOT_ID, True, ROOT, ROOT_ID)
    mocker.patch.object(suggestions, "root_destinations", return_value=(top,))
    move = mocker.patch.object(model, "move_in_root")
    editor, _kept = path_editor(qtbot, model, suggestions)

    (label,) = labels_of(editor)
    label.linkActivated.emit("#")

    assert full_text(label) == "Tutorials"
    assert not label.isEnabled()
    move.assert_not_called()


def test_a_name_is_not_applied_to_a_record_that_is_its_roots_folder(
    qtbot: QtBot, model: RehuDocumentModel, mocker: MockerFixture
) -> None:
    """A rename asked for a record at its root's top is dropped, and one asked for any other is applied (#641).

    **Test steps:**

    * build the editor over suggestions saying the record is its root's folder, and emit a name
    * check the model renamed nothing
    * say it is not, emit the name, and check the model renamed to it
    """
    suggestions = NameSuggestionModel(model)
    is_root = mocker.patch.object(suggestions, "is_root_folder", return_value=True)
    rename = mocker.patch.object(model, "rename_location")
    editor, _kept = path_editor(qtbot, model, suggestions)

    editor.suggestion_selected.emit("Bar")
    rename.assert_not_called()

    is_root.return_value = False
    editor.suggestion_selected.emit("Bar")
    rename.assert_called_once_with("Bar")


def test_a_record_that_is_its_roots_folder_shows_no_name_to_click(
    qtbot: QtBot, model: RehuDocumentModel, mocker: MockerFixture
) -> None:
    """The path row of a record at its root's top shows no suggestion, even for names it is handed, and does not draw
    the current name as the wrong one; any other record's shows them (#641).

    **Test steps:**

    * build the editor over suggestions saying the record is its root's folder yet offering a name
    * check the name's label is hidden and the current name is not warned about
    * say it is not the root's folder, announce the change, and check the label shows and the name is warned about
    """
    suggestions = NameSuggestionModel(model)
    is_root = mocker.patch.object(suggestions, "is_root_folder", return_value=True)
    mocker.patch.object(suggestions, "suggestions", return_value=["Bar"])
    editor, _kept = path_editor(qtbot, model, suggestions)
    names = editor._PathEditor__suggestion_labels  # type: ignore[attr-defined]  # pylint: disable=protected-access
    name_line = editor._PathEditor__name_line  # type: ignore[attr-defined]  # pylint: disable=protected-access
    warned = mocker.spy(name_line, "set_warning")

    suggestions.changed.emit()
    assert names["Bar"].isHidden()
    warned.assert_called_with(False)

    is_root.return_value = False
    suggestions.changed.emit()
    assert not names["Bar"].isHidden()
    warned.assert_called_with(True)
