"""Tests for the notes two panels share (#575, [[plugins#video-notes-dock]]).

Two real panels over one `VideoNotesEdit` and a real tutorial under ``tmp_path``: what is tested is that they show the
same video, that the text of an edit is one text, that each has its own mode, and that nothing typed is lost or written
twice.
"""

# the panels' own editors are reached through their name-mangled members, as the other notes tests do
# pylint: disable=protected-access

from typing import Final

from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.notes_panel import NotesPanel
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.documents.video_notes_edit import VideoNotesEdit

from .video_tree_support import fixture_model  # noqa: F401  # pylint: disable=unused-import

pytestmark = mark.usefixtures("real_path_stat")

KEY: Final = "01 Basics/c.mp4"
OTHER: Final = "a.mp4"


@fixture(name="panels")
def fixture_panels(qtbot: QtBot, model: RehuDocumentModel) -> tuple[NotesPanel, NotesPanel]:
    """Two shown panels over one notes model: the dock's and the player's.

    :param qtbot: pytest-qt fixture.
    :param model: the document.
    :returns: the panels, the first of which made the notes.
    """
    first = NotesPanel(model)
    second = NotesPanel(model, notes=first.notes)
    for panel in (first, second):
        qtbot.addWidget(panel)
        panel.resize(300, 400)
        panel.show()
    return first, second


def editor_of(panel: NotesPanel) -> object:
    """A panel's editor of the video's notes.

    :param panel: the panel.
    :returns: the editor.
    """
    return panel._NotesPanel__video_edit  # type: ignore[attr-defined]


def test_panels_over_one_model_show_the_same_video(panels: tuple[NotesPanel, NotesPanel]) -> None:
    """**Test steps:**

    * show a video in the first panel
    * verify the second shows it too, and it is the same notes model
    """
    first, second = panels

    first.set_video(KEY)

    assert second.video_key == KEY
    assert first.notes is second.notes


def test_what_is_typed_in_one_panel_is_in_the_other_as_it_is_typed(panels: tuple[NotesPanel, NotesPanel]) -> None:
    """**Test steps:**

    * edit the same video in both panels and type in the first
    * verify the second's editor holds the same text, with nothing written yet
    """
    first, second = panels
    first.set_video(KEY)
    first.title_bar_actions[0].setChecked(True)
    second.title_bar_actions[0].setChecked(True)

    editor_of(first).setText("typed")  # type: ignore[attr-defined]

    assert VideoNotesEdit.text_of(editor_of(second)) == "typed"  # type: ignore[arg-type]
    assert second.notes.video_text() == ""


def test_each_panel_has_its_own_mode_and_the_text_is_written_when_the_last_leaves(
    panels: tuple[NotesPanel, NotesPanel], model: RehuDocumentModel
) -> None:
    """**Test steps:**

    * edit in both panels and type, then leave edit in the first
    * verify the first shows rendered notes, the second still edits, and what was typed is written once
    * leave edit in the second and verify the notes are unchanged and still recorded
    """
    first, second = panels
    first.set_video(KEY)
    first.title_bar_actions[0].setChecked(True)
    second.title_bar_actions[0].setChecked(True)
    editor_of(second).setText("typed")  # type: ignore[attr-defined]

    first.title_bar_actions[0].setChecked(False)

    assert not first.editing and second.editing
    assert model.video_notes_of(KEY) == "typed"
    second.title_bar_actions[0].setChecked(False)
    assert model.video_notes_of(KEY) == "typed"


def test_a_bookmark_added_while_another_panel_has_unwritten_text_loses_nothing(
    panels: tuple[NotesPanel, NotesPanel], model: RehuDocumentModel
) -> None:
    """**Test steps:**

    * edit in the second panel and type; the first is not editing
    * add a bookmark through the first
    * verify the text typed and the line are both in the notes and the editor
    """
    first, second = panels
    second.set_video(KEY)
    second.title_bar_actions[0].setChecked(True)
    editor_of(second).setText("typed")  # type: ignore[attr-defined]

    first.add_note(KEY, 65.0)

    recorded = model.video_notes_of(KEY)
    assert "typed" in recorded and "[1:05]" in recorded
    assert VideoNotesEdit.text_of(editor_of(second)) == recorded  # type: ignore[arg-type]


def test_switching_video_writes_what_was_typed_once(
    panels: tuple[NotesPanel, NotesPanel], model: RehuDocumentModel, mocker: MockerFixture
) -> None:
    """**Test steps:**

    * edit in both panels and type, with the document's `record_notes` watched
    * switch video through the second panel
    * verify one write carried the text, and both panels show the other video
    """
    first, second = panels
    first.set_video(KEY)
    first.title_bar_actions[0].setChecked(True)
    second.title_bar_actions[0].setChecked(True)
    editor_of(first).setText("typed")  # type: ignore[attr-defined]
    record = mocker.spy(model, "record_notes")

    second.set_video(OTHER)

    assert record.call_count == 1
    assert model.video_notes_of(KEY) == "typed"
    assert first.video_key == OTHER


def test_an_owned_notes_model_is_let_go_with_its_panel_and_a_shared_one_is_not(
    qtbot: QtBot, model: RehuDocumentModel, mocker: MockerFixture
) -> None:
    """**Test steps:**

    * make a panel with a model of its own and one over another's, with the model's detach watched
    * detach the second and verify the model stays; detach the first and verify it is let go of
    """
    first = NotesPanel(model)
    second = NotesPanel(model, notes=first.notes)
    qtbot.addWidget(first)
    qtbot.addWidget(second)
    detach = mocker.spy(first.notes, "detach")

    second.detach()
    assert detach.call_count == 0
    first.detach()

    assert detach.call_count == 1


def test_a_flush_after_detach_writes_nothing_and_reaches_no_deleted_editor(
    qtbot: QtBot, model: RehuDocumentModel, mocker: MockerFixture
) -> None:
    """**Test steps:**

    * edit in a panel and type, then detach its notes model and let the deferred deletes run
    * ask the panel to flush again, as its editor losing the focus would
    * verify nothing more is written and nothing raises
    """
    panel = NotesPanel(model)
    qtbot.addWidget(panel)
    panel.set_video(KEY)
    panel.title_bar_actions[0].setChecked(True)
    editor_of(panel).setText("typed")  # type: ignore[attr-defined]
    panel.detach()
    qtbot.wait(10)
    record = mocker.spy(model, "record_notes")

    panel.flush()

    assert record.call_count == 0
    assert model.video_notes_of(KEY) == "typed"


def test_the_hidden_editors_are_children_of_the_panel_that_made_the_notes(
    qtbot: QtBot, model: RehuDocumentModel
) -> None:
    """**Test steps:**

    * make a panel with notes of its own
    * verify the notes' hidden editors are hidden children of the panel, not windows of their own
    """
    panel = NotesPanel(model)
    qtbot.addWidget(panel)
    panel.show()
    notes = panel.notes

    editors = (notes._VideoNotesEdit__video_edit, notes._VideoNotesEdit__tutorial_edit)  # type: ignore[attr-defined]

    assert all(editor.parent() is panel and editor.isHidden() and not editor.isWindow() for editor in editors)
