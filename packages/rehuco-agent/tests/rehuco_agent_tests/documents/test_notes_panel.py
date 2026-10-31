"""Tests for the notes panel (#573, [[plugins#video-notes-dock]]).

A real tutorial under ``tmp_path``: what is tested is what the panel shows for a video, what each way out of editing
writes, the text a note starts with, and where a link goes.
"""

# the panel's own widgets are reached through its name-mangled members, as the other dock tests do
# astroid reads the title-bar actions' list as signals
# pylint: disable=protected-access,no-member

import logging
from typing import Final

from PySide6.QtCore import QEvent, QUrl
from PySide6.QtGui import QFocusEvent
from PySide6.QtWidgets import QApplication
from pytest import LogCaptureFixture, approx, fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.notes_panel import NotesPanel
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.settings.markdown_rendering_settings import shared_markdown_rendering_settings

from rehuco_agent_tests.progress_writes import HeldWrites

from .video_tree_support import fixture_model  # noqa: F401  # pylint: disable=unused-import

pytestmark = mark.usefixtures("real_path_stat")

KEY: Final = "01 Basics/c.mp4"
OTHER: Final = "a.mp4"
BOOKMARK_LINE: Final = "- [1:05](rehuco-video:01%20Basics/c.mp4#t=65) "
EARLY: Final = "- [0:10](rehuco-video:01%20Basics/c.mp4#t=10) early"
LATE: Final = "- [1:40](rehuco-video:01%20Basics/c.mp4#t=100) late"


@fixture(name="panel")
def fixture_panel(qtbot: QtBot, model: RehuDocumentModel) -> NotesPanel:
    """A shown panel over the tutorial, with no video loaded.

    :param qtbot: pytest-qt fixture.
    :param model: the document.
    :returns: the panel.
    """
    panel = NotesPanel(model)
    qtbot.addWidget(panel)
    panel.resize(300, 400)
    panel.show()
    return panel


def text_of(editor: object) -> str:
    """What an editor holds.

    :param editor: the panel's video or tutorial editor.
    :returns: its text.
    """
    return NotesPanel._NotesPanel__text(editor)  # type: ignore[attr-defined,arg-type]


def video_editor(panel: NotesPanel):  # type: ignore[no-untyped-def]
    """The panel's editor of the video's notes.

    :param panel: the panel.
    :returns: the editor.
    """
    return panel._NotesPanel__video_edit  # type: ignore[attr-defined]


def tutorial_editor(panel: NotesPanel):  # type: ignore[no-untyped-def]
    """The panel's editor of the tutorial's notes.

    :param panel: the panel.
    :returns: the editor.
    """
    return panel._NotesPanel__tutorial_edit  # type: ignore[attr-defined]


def begin_editing(panel: NotesPanel, key: str | None = KEY) -> None:
    """Show a video's notes in the editors.

    :param panel: the panel.
    :param key: the video, or ``None`` for none.
    """
    panel.set_video(key)
    panel.title_bar_actions[0].setChecked(True)


def test_the_video_part_follows_the_video_and_hides_with_none(panel: NotesPanel) -> None:
    """**Test steps:**

    * verify nothing loaded shows the tutorial's part alone
    * set a video and verify the video part shows, headed by the video's key
    * set none and verify it hides again
    """
    ui = panel._NotesPanel__ui  # type: ignore[attr-defined]
    assert ui.video_part.isHidden()
    assert not ui.tutorial_part.isHidden()

    panel.set_video(KEY)

    assert not ui.video_part.isHidden()
    assert panel.video_key == KEY

    panel.set_video(None)

    assert ui.video_part.isHidden()
    assert panel.video_key is None


def test_a_videos_notes_are_shown_rendered(panel: NotesPanel, model: RehuDocumentModel) -> None:
    """**Test steps:**

    * record a note on a video and a note on the tutorial
    * show the video
    * verify each viewer renders its own text
    """
    model.record_notes(notes="about the tutorial", video_notes={KEY: "about this video"})

    panel.set_video(KEY)

    ui = panel._NotesPanel__ui  # type: ignore[attr-defined]
    assert "about this video" in ui.video_view.toPlainText()
    assert "about the tutorial" in ui.tutorial_view.toPlainText()


def test_a_video_with_nothing_recorded_is_searched_for_among_the_renamed_before_it_is_shown(
    panel: NotesPanel, model: RehuDocumentModel, mocker: MockerFixture
) -> None:
    """**Test steps:**

    * make the document report the video as having no data, and watch the order of its calls
    * show the video
    * verify the rename search ran before the video's note was read, and the panel waits for it
    * have the search answer and verify the panel no longer waits
    """
    order = mocker.Mock()
    mocker.patch.object(model, "video_data_keys", return_value=set())
    order.attach_mock(mocker.patch.object(model, "reattach_renamed_progress", return_value=True), "search")
    order.attach_mock(mocker.patch.object(model, "video_notes_of", return_value=""), "read")

    panel.set_video(KEY)

    assert [call[0] for call in order.mock_calls] == ["search", "read"]
    assert panel.searching

    model.rename_search_finished.emit()

    assert not panel.searching


def test_a_video_that_has_data_is_not_searched_for(
    panel: NotesPanel, model: RehuDocumentModel, mocker: MockerFixture
) -> None:
    """**Test steps:**

    * make the document report the video as having data
    * show the video
    * verify no rename search ran
    """
    mocker.patch.object(model, "video_data_keys", return_value={KEY})
    search = mocker.patch.object(model, "reattach_renamed_progress", return_value=True)

    panel.set_video(KEY)

    search.assert_not_called()
    assert not panel.searching


def test_a_search_the_record_refuses_leaves_the_editor_usable(
    panel: NotesPanel, model: RehuDocumentModel, mocker: MockerFixture
) -> None:
    """**Test steps:**

    * make the document refuse the search, as it does where progress cannot be written
    * show a video with no data
    * verify the panel does not wait for an answer that will not come
    """
    mocker.patch.object(model, "video_data_keys", return_value=set())
    mocker.patch.object(model, "reattach_renamed_progress", return_value=False)

    panel.set_video(KEY)

    assert not panel.searching
    assert video_editor(panel).isEnabled()


def test_leaving_edit_writes_what_was_typed_once(
    panel: NotesPanel, model: RehuDocumentModel, mocker: MockerFixture
) -> None:
    """**Test steps:**

    * edit a video's notes and type into both editors
    * leave edit
    * verify one write carries both texts, under the video's key
    * verify the viewers show them
    """
    record = mocker.patch.object(model, "record_notes")
    begin_editing(panel)
    video_editor(panel).setText("the smudge trick")
    tutorial_editor(panel).setText("a good course")

    panel.title_bar_actions[0].setChecked(False)

    record.assert_called_once_with(notes="a good course", video_notes={KEY: "the smudge trick"})
    assert not panel.editing


def test_only_the_part_that_changed_is_written(
    panel: NotesPanel, model: RehuDocumentModel, mocker: MockerFixture
) -> None:
    """**Test steps:**

    * edit, and type only into the tutorial's editor
    * flush
    * verify the write names the tutorial's notes alone
    """
    record = mocker.patch.object(model, "record_notes")
    begin_editing(panel)
    tutorial_editor(panel).setText("only this")

    panel.flush()

    record.assert_called_once_with(notes="only this", video_notes=None)


def test_nothing_changed_writes_nothing_and_a_flush_twice_writes_once(
    panel: NotesPanel, model: RehuDocumentModel, mocker: MockerFixture
) -> None:
    """**Test steps:**

    * edit and flush with nothing typed: verify no write
    * type, flush twice: verify one write
    """
    record = mocker.patch.object(model, "record_notes")
    begin_editing(panel)

    panel.flush()
    record.assert_not_called()

    video_editor(panel).setText("typed")
    panel.flush()
    panel.flush()

    record.assert_called_once_with(notes=None, video_notes={KEY: "typed"})


def test_a_flush_outside_edit_writes_nothing(
    panel: NotesPanel, model: RehuDocumentModel, mocker: MockerFixture
) -> None:
    """**Test steps:**

    * show a video without editing and flush
    * verify no write
    """
    record = mocker.patch.object(model, "record_notes")
    panel.set_video(KEY)

    panel.flush()

    record.assert_not_called()


def test_the_editor_losing_focus_writes(panel: NotesPanel, model: RehuDocumentModel, mocker: MockerFixture) -> None:
    """**Test steps:**

    * edit and type into the video's editor
    * send the editor a focus-out
    * verify the text is written
    """
    record = mocker.patch.object(model, "record_notes")
    begin_editing(panel)
    editor = video_editor(panel)
    editor.setText("typed")

    QApplication.sendEvent(editor, QFocusEvent(QEvent.Type.FocusOut))

    record.assert_called_once_with(notes=None, video_notes={KEY: "typed"})


def test_switching_video_writes_the_old_videos_notes_under_its_own_key(
    panel: NotesPanel, model: RehuDocumentModel, mocker: MockerFixture
) -> None:
    """**Test steps:**

    * edit one video and type
    * show another video
    * verify the text was written under the first video's key, and the editor now holds the other's notes
    """
    record = mocker.patch.object(model, "record_notes")
    begin_editing(panel, KEY)
    video_editor(panel).setText("for c")

    panel.set_video(OTHER)

    record.assert_called_once_with(notes=None, video_notes={KEY: "for c"})
    assert text_of(video_editor(panel)) == ""


def test_detaching_writes_what_is_waiting(panel: NotesPanel, model: RehuDocumentModel, mocker: MockerFixture) -> None:
    """**Test steps:**

    * edit and type
    * detach the panel, as closing the document does
    * verify the text was written
    """
    record = mocker.patch.object(model, "record_notes")
    begin_editing(panel)
    video_editor(panel).setText("typed")

    panel.detach()

    record.assert_called_once_with(notes=None, video_notes={KEY: "typed"})


def test_what_is_typed_reaches_the_document_without_a_save(panel: NotesPanel, model: RehuDocumentModel) -> None:
    """**Test steps:**

    * edit through the real document and type
    * leave edit
    * verify the document answers with the text and is not dirty
    """
    begin_editing(panel)
    video_editor(panel).setText("kept")

    panel.title_bar_actions[0].setChecked(False)

    assert model.video_notes_of(KEY) == "kept"
    assert not model.dirty


def test_an_editor_the_user_changed_keeps_its_text_when_the_notes_change_under_it(
    panel: NotesPanel, model: RehuDocumentModel
) -> None:
    """**Test steps:**

    * edit the video's notes and type into the video's editor
    * let a note arrive for the tutorial
    * verify the video's editor keeps what was typed and the tutorial's editor takes the arrival
    """
    begin_editing(panel)
    video_editor(panel).setText("half a thought")

    model.record_notes(notes="arrived")

    assert text_of(video_editor(panel)) == "half a thought"
    assert text_of(tutorial_editor(panel)) == "arrived"


def test_a_note_found_by_the_rename_search_replaces_nothing_the_user_typed(
    panel: NotesPanel, model: RehuDocumentModel, mocker: MockerFixture
) -> None:
    """**Test steps:**

    * edit a video that shows no note and flush with nothing typed
    * verify nothing was written over a note a search may yet find
    * let the note arrive and verify the unchanged editor takes it
    """
    record = mocker.patch.object(model, "record_notes")
    begin_editing(panel)

    panel.flush()
    record.assert_not_called()

    mocker.patch.object(model, "video_notes_of", return_value="found")
    model.notes_changed.emit()

    assert text_of(video_editor(panel)) == "found"


@mark.parametrize(
    ("existing", "expected"),
    [
        ("", BOOKMARK_LINE),
        ("first", f"first\n{BOOKMARK_LINE}"),
        (f"{LATE}\n{EARLY}\nsaid early", f"{LATE}\n{EARLY}\nsaid early\n{BOOKMARK_LINE}"),
        (f"{LATE}\nsaid late", f"{BOOKMARK_LINE}\n{LATE}\nsaid late"),
    ],
)
def test_add_note_puts_the_bookmark_beside_its_neighbours_in_time_with_the_caret_at_its_end(
    panel: NotesPanel, existing: str, expected: str
) -> None:
    """The bookmarks already there are anchors, whatever order the user left them in (#573).

    **Test steps:**

    * show a video holding a text, in edit
    * add a bookmark at 1:05
    * verify it went after the latest earlier bookmark and its text, else before the earliest later one, else at the
      end; the caret is at the end of the new line, and editing is on
    """
    begin_editing(panel)
    video_editor(panel).setText(existing)

    panel.add_note(KEY, 65.4)

    editor = video_editor(panel)
    assert text_of(editor) == expected
    assert editor.currentPos() == len(expected[: expected.index(BOOKMARK_LINE) + len(BOOKMARK_LINE)].encode("utf-8"))
    assert panel.editing


def test_add_note_on_another_video_shows_that_video_first(panel: NotesPanel) -> None:
    """**Test steps:**

    * show one video and add a note on another
    * verify the panel shows the other, in edit, with the note
    """
    panel.set_video(OTHER)

    panel.add_note(KEY, 5.0)

    assert panel.video_key == KEY
    assert text_of(video_editor(panel)).startswith("- [0:05](rehuco-video:01%20Basics/c.mp4#t=5) ")


def test_a_link_to_a_video_is_reported_with_its_time(panel: NotesPanel, qtbot: QtBot) -> None:
    """**Test steps:**

    * click a link to a video, with a time
    * verify the video's key is decoded and the time is reported
    """
    view = panel._NotesPanel__ui.video_view  # type: ignore[attr-defined]

    with qtbot.waitSignal(panel.video_link_activated) as blocker:
        view.anchorClicked.emit(QUrl("rehuco-video:01%20Basics/c.mp4#t=65"))

    assert blocker.args == [KEY, 65.0]


def test_a_link_to_a_video_without_a_time_reports_none(panel: NotesPanel, qtbot: QtBot) -> None:
    """**Test steps:**

    * click a link to a video from the tutorial's viewer, with no time
    * verify the key and no time are reported
    """
    view = panel._NotesPanel__ui.tutorial_view  # type: ignore[attr-defined]

    with qtbot.waitSignal(panel.video_link_activated) as blocker:
        view.anchorClicked.emit(QUrl("rehuco-video:a.mp4"))

    assert blocker.args == [OTHER, None]


def test_any_other_link_opens_in_the_browser(panel: NotesPanel, mocker: MockerFixture, qtbot: QtBot) -> None:
    """**Test steps:**

    * click an https link
    * verify it opens externally and no video is reported
    """
    open_url = mocker.patch("rehuco_agent.documents.notes_panel.QDesktopServices.openUrl")
    reported = mocker.Mock()
    panel.video_link_activated.connect(reported)
    view = panel._NotesPanel__ui.video_view  # type: ignore[attr-defined]

    view.anchorClicked.emit(QUrl("https://example.com/page"))

    open_url.assert_called_once_with(QUrl("https://example.com/page"))
    reported.assert_not_called()
    del qtbot


def test_a_link_to_no_video_is_logged_and_goes_nowhere(
    panel: NotesPanel, mocker: MockerFixture, caplog: LogCaptureFixture
) -> None:
    """**Test steps:**

    * click a ``rehuco-video:`` link that names no key
    * verify a warning is logged and neither the player nor the browser is asked
    """
    open_url = mocker.patch("rehuco_agent.documents.notes_panel.QDesktopServices.openUrl")
    reported = mocker.Mock()
    panel.video_link_activated.connect(reported)
    view = panel._NotesPanel__ui.video_view  # type: ignore[attr-defined]

    with caplog.at_level(logging.WARNING):
        view.anchorClicked.emit(QUrl("rehuco-video:#t=5"))

    assert "no video" in caplog.text
    open_url.assert_not_called()
    reported.assert_not_called()


def test_the_split_round_trips_through_the_state(qtbot: QtBot, model: RehuDocumentModel, panel: NotesPanel) -> None:
    """**Test steps:**

    * show a video, so both parts show, and move the split
    * restore its state into a second panel of the same size
    * verify the second panel splits the same
    """
    panel.set_video(KEY)
    splitter = panel._NotesPanel__ui.splitter  # type: ignore[attr-defined]
    splitter.setSizes([100, 250])
    other = NotesPanel(model)
    qtbot.addWidget(other)
    other.resize(300, 400)
    other.set_video(KEY)
    other.show()

    other.restore_state(panel.save_state())

    # the panels differ by a few pixels of height, so it is the proportion that is kept
    restored = other._NotesPanel__ui.splitter.sizes()  # type: ignore[attr-defined]
    assert restored[0] / sum(restored) == approx(splitter.sizes()[0] / sum(splitter.sizes()), abs=0.02)


def test_a_changed_tutorial_editor_keeps_its_text_when_the_notes_change_under_it(
    panel: NotesPanel, model: RehuDocumentModel
) -> None:
    """**Test steps:**

    * edit and type into the tutorial's editor
    * let the notes change
    * verify the tutorial's editor keeps what was typed
    """
    begin_editing(panel, None)
    tutorial_editor(panel).setText("half a thought")

    model.notes_changed.emit()

    assert text_of(tutorial_editor(panel)) == "half a thought"


def test_the_viewers_render_again_when_the_markdown_settings_change(panel: NotesPanel, mocker: MockerFixture) -> None:
    """**Test steps:**

    * watch both viewers' rendering
    * announce a change of the Markdown rendering settings
    * verify each viewer rendered with the settings
    """
    ui = panel._NotesPanel__ui  # type: ignore[attr-defined]
    applied = [mocker.patch.object(view, "apply_rendering_settings") for view in (ui.video_view, ui.tutorial_view)]

    shared_markdown_rendering_settings().description_rendering_changed.emit()

    for apply in applied:
        apply.assert_called_once()


def test_a_note_added_without_editing_is_recorded_at_once_and_changes_no_mode(
    panel: NotesPanel, model: RehuDocumentModel, mocker: MockerFixture
) -> None:
    """**Test steps:**

    * record a note on a video and add a bookmark at 1:05 to it without editing, then one at 0:10
    * verify each was recorded at once, the earlier one before the later, nothing is being edited, and the panel shows
      the video
    """
    model.record_notes(video_notes={KEY: "first"})
    record = mocker.spy(model, "record_notes")

    panel.add_note(KEY, 65.0, edit=False)
    panel.add_note(KEY, 10.0, edit=False)

    assert model.video_notes_of(KEY) == f"first\n- [0:10](rehuco-video:01%20Basics/c.mp4#t=10) \n{BOOKMARK_LINE}"
    assert record.call_count == 2
    assert not panel.editing
    assert panel.video_key == KEY


def test_a_note_added_without_editing_while_editing_joins_the_editor_and_is_written_at_once(
    panel: NotesPanel, model: RehuDocumentModel
) -> None:
    """**Test steps:**

    * edit a video and type into its editor
    * add a note at a time without editing
    * verify the editor holds the typed text and the line, and the document holds both
    """
    begin_editing(panel)
    video_editor(panel).setText("typed")

    panel.add_note(KEY, 65.0, edit=False)

    assert text_of(video_editor(panel)) == f"typed\n{BOOKMARK_LINE}"
    assert model.video_notes_of(KEY) == f"typed\n{BOOKMARK_LINE}"
    assert panel.editing


def test_the_editor_is_disabled_while_the_search_is_out_and_usable_once_it_answers(
    panel: NotesPanel, held_writes: HeldWrites
) -> None:
    """Typing over an empty note while the search is out would replace the note the search then finds (#573).

    **Test steps:**

    * edit a video with no data while the writer holds its writes
    * verify the video's editor is disabled and the tutorial's is not
    * let the search answer and verify the video's editor is usable
    """
    begin_editing(panel)

    assert panel.searching
    assert not video_editor(panel).isEnabled()
    assert tutorial_editor(panel).isEnabled()
    assert held_writes.keys == [("reattach",)]

    held_writes.release_all()

    assert not panel.searching
    assert video_editor(panel).isEnabled()


def test_a_bookmark_asked_for_during_the_search_is_added_once_it_answers(
    panel: NotesPanel, held_writes: HeldWrites
) -> None:
    """**Test steps:**

    * ask for a bookmark on a video with no data while the writer holds the search
    * verify the notes opened for editing, disabled, with nothing added yet
    * let the search answer and verify the line is in the editor, with the caret at its end, and the editor usable
    """
    panel.add_note(KEY, 65.4)

    editor = video_editor(panel)
    assert panel.editing
    assert not editor.isEnabled()
    assert text_of(editor) == ""

    held_writes.release_all()

    assert editor.isEnabled()
    assert text_of(editor) == BOOKMARK_LINE
    assert editor.currentPos() == editor.length()


def test_a_bookmark_asked_for_without_editing_during_the_search_is_recorded_once_it_answers(
    panel: NotesPanel, model: RehuDocumentModel, held_writes: HeldWrites
) -> None:
    """**Test steps:**

    * ask for a bookmark without editing while the writer holds the search
    * verify nothing was recorded and nothing is being edited
    * let the search answer and verify the bookmark was recorded
    """
    panel.add_note(KEY, 65.4, edit=False)

    assert not panel.editing
    assert model.video_notes_of(KEY) == ""

    held_writes.release(("reattach",))

    assert model.video_notes_of(KEY) == BOOKMARK_LINE
    assert not panel.editing


def test_switching_video_during_the_search_drops_the_bookmark_asked_for(
    panel: NotesPanel, held_writes: HeldWrites
) -> None:
    """A bookmark belongs to the video it was asked on; shown another before the search answers, it is not added
    to that one.

    **Test steps:**

    * ask for a bookmark while the search is out, then show another video with data
    * let the search answer and verify neither video got the line
    """
    panel.add_note(KEY, 65.4)
    panel.set_video(OTHER)

    held_writes.release_all()

    assert text_of(video_editor(panel)) == ""
    assert panel.video_key == OTHER
