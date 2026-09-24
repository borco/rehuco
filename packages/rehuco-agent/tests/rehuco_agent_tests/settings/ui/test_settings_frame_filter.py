"""Tests for SettingsFrameFilter: showing/hiding a page's labeled frames by filter text.

The filter discovers a page's top-level QFrames and gathers their caption text by introspection, so
these tests build a real little page (a QFrame per group, each holding QLabels) and assert against
it. Visibility is checked with ``isVisibleTo(page)`` -- which reflects each frame's own show/hide
state without the page having to be realized on screen.
"""

from borco_pyside.widgets import StringListEditor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from pytestqt.qtbot import QtBot
from rehuco_agent.settings.ui.settings_frame_filter import SCRATCH_PROPERTY, SettingsFrameFilter


def make_page(qtbot: QtBot, groups: list[list[str]]) -> tuple[QWidget, list[QFrame]]:
    """Build a page with one top-level QFrame per group, each holding a QLabel for every term.

    :param qtbot: the Qt test bot, to own the page.
    :param groups: one list of label texts per frame, in frame order.
    :returns: the page and its frames, in order.
    """
    page = QWidget()
    qtbot.addWidget(page)
    layout = QVBoxLayout(page)
    frames: list[QFrame] = []
    for terms in groups:
        frame = QFrame(page)
        frame_layout = QVBoxLayout(frame)
        for term in terms:
            frame_layout.addWidget(QLabel(term, frame))
        layout.addWidget(frame)
        frames.append(frame)
    return page, frames


def make_value_page(qtbot: QtBot, frame_count: int) -> tuple[QWidget, list[QFrame], list[QLineEdit]]:
    """Build a page with ``frame_count`` top-level frames, each holding one editable `QLineEdit`.

    :param qtbot: the Qt test bot, to own the page.
    :param frame_count: how many frames to build.
    :returns: the page, its frames, and each frame's line edit, all in frame order.
    """
    page = QWidget()
    qtbot.addWidget(page)
    layout = QVBoxLayout(page)
    frames: list[QFrame] = []
    edits: list[QLineEdit] = []
    for _ in range(frame_count):
        frame = QFrame(page)
        frame_layout = QVBoxLayout(frame)
        edit = QLineEdit(frame)
        frame_layout.addWidget(edit)
        layout.addWidget(frame)
        frames.append(frame)
        edits.append(edit)
    return page, frames, edits


def test_empty_text_shows_every_frame(qtbot: QtBot) -> None:
    """With no filter text, every frame is shown.

    **Test steps:**

    * hide one frame, then apply an empty filter
    * verify both frames are visible
    """
    page, (engine, images) = make_page(qtbot, [["Engine"], ["Images"]])
    frame_filter = SettingsFrameFilter(page, "Markdown Rendering")
    images.setVisible(False)

    frame_filter.apply("", show_full_on_title_match=False)

    assert engine.isVisibleTo(page) is True
    assert images.isVisibleTo(page) is True


def test_shows_only_the_frames_whose_text_matches(qtbot: QtBot) -> None:
    """A frame is shown only if its gathered caption text contains the filter text (others hidden).

    **Test steps:**

    * apply a filter matching only the engine frame's labels
    * verify the engine frame is shown and the images frame hidden
    """
    page, (engine, images) = make_page(qtbot, [["Engine", "CSS"], ["Maximum image width"]])
    frame_filter = SettingsFrameFilter(page, "Markdown Rendering")

    frame_filter.apply("css", show_full_on_title_match=False)

    assert engine.isVisibleTo(page) is True
    assert images.isVisibleTo(page) is False


def test_matching_is_case_insensitive(qtbot: QtBot) -> None:
    """Matching ignores case in both the filter text and the gathered caption text.

    **Test steps:**

    * apply an upper-case filter against a mixed-case label
    * verify the matching frame is shown
    """
    page, (images,) = make_page(qtbot, [["Maximum image width"]])
    frame_filter = SettingsFrameFilter(page, "Markdown Rendering")

    frame_filter.apply("WIDTH", show_full_on_title_match=False)

    assert images.isVisibleTo(page) is True


def test_title_only_match_shows_the_full_page_when_the_flag_is_set(qtbot: QtBot) -> None:
    """When nothing but the title matches and the flag is set, every frame is shown.

    **Test steps:**

    * apply a filter matching the page title but no frame, with the flag set
    * verify every frame is shown
    """
    page, (engine, images) = make_page(qtbot, [["Engine"], ["Images"]])
    frame_filter = SettingsFrameFilter(page, "Registry")

    frame_filter.apply("registry", show_full_on_title_match=True)

    assert engine.isVisibleTo(page) is True
    assert images.isVisibleTo(page) is True


def test_title_match_with_flag_shows_full_page_even_when_only_some_frames_match(qtbot: QtBot) -> None:
    """A title match with the flag set shows the whole page, even if only some frames also match.

    **Test steps:**

    * apply a filter matching both the title and one frame's label, with the flag set
    * verify every frame is shown, not just the matching one
    """
    page, (engine, images) = make_page(qtbot, [["Engine", "markdown"], ["Images"]])
    frame_filter = SettingsFrameFilter(page, "Markdown Rendering")

    frame_filter.apply("mark", show_full_on_title_match=True)

    assert engine.isVisibleTo(page) is True
    assert images.isVisibleTo(page) is True


def test_frame_match_with_flag_clear_shows_only_matching_frames_despite_title_match(qtbot: QtBot) -> None:
    """With the flag clear, a title match is ignored: only the frames matching the text are shown.

    **Test steps:**

    * apply a filter matching the title and one frame, flag clear
    * verify only the matching frame is shown
    """
    page, (engine, images) = make_page(qtbot, [["Engine", "markdown"], ["Images"]])
    frame_filter = SettingsFrameFilter(page, "Markdown Rendering")

    frame_filter.apply("mark", show_full_on_title_match=False)

    assert engine.isVisibleTo(page) is True
    assert images.isVisibleTo(page) is False


def test_title_only_match_hides_everything_when_the_flag_is_clear(qtbot: QtBot) -> None:
    """When only the title matches but the flag is clear, every frame is hidden.

    **Test steps:**

    * apply a filter matching the title but no frame, with the flag clear
    * verify every frame is hidden
    """
    page, (engine, images) = make_page(qtbot, [["Engine"], ["Images"]])
    frame_filter = SettingsFrameFilter(page, "Registry")

    frame_filter.apply("registry", show_full_on_title_match=False)

    assert engine.isVisibleTo(page) is False
    assert images.isVisibleTo(page) is False


def test_no_match_anywhere_hides_everything_even_with_the_flag_set(qtbot: QtBot) -> None:
    """Text matching neither a frame nor the title hides every frame, flag notwithstanding.

    **Test steps:**

    * apply a filter matching nothing, with the flag set
    * verify every frame is hidden
    """
    page, (engine, images) = make_page(qtbot, [["Engine"], ["Images"]])
    frame_filter = SettingsFrameFilter(page, "Registry")

    frame_filter.apply("zzz", show_full_on_title_match=True)

    assert engine.isVisibleTo(page) is False
    assert images.isVisibleTo(page) is False


def test_nested_frame_is_not_a_group_of_its_own(qtbot: QtBot) -> None:
    """Only top-level frames are groups; a frame nested inside one is part of its parent's text.

    **Test steps:**

    * build a page whose single top-level frame contains a nested QFrame with a label
    * filter by the nested label's text
    * verify the one top-level frame matches (its text includes the nested label)
    """
    page, (outer,) = make_page(qtbot, [["Engine"]])
    inner = QFrame(outer)
    inner_layout = QVBoxLayout(inner)
    inner_layout.addWidget(QLabel("nested-term", inner))
    outer_layout = outer.layout()
    assert outer_layout is not None
    outer_layout.addWidget(inner)
    frame_filter = SettingsFrameFilter(page, "Markdown Rendering")

    frame_filter.apply("nested-term", show_full_on_title_match=False)

    assert outer.isVisibleTo(page) is True


def test_group_box_title_is_part_of_a_frames_text(qtbot: QtBot) -> None:
    """A frame's gathered text includes any nested `QGroupBox` title, not just labels and buttons.

    **Test steps:**

    * build a page whose one frame contains a QGroupBox titled "Advanced"
    * filter by the group-box title
    * verify the frame matches
    """
    page, (frame,) = make_page(qtbot, [["Engine"]])
    group_box = QGroupBox("Advanced", frame)
    frame_layout = frame.layout()
    assert frame_layout is not None
    frame_layout.addWidget(group_box)
    frame_filter = SettingsFrameFilter(page, "Markdown Rendering")

    frame_filter.apply("advanced", show_full_on_title_match=False)

    assert frame.isVisibleTo(page) is True


def test_a_list_editors_button_captions_do_not_match_the_frame(qtbot: QtBot) -> None:
    """A frame whose only match would be a list editor's own button captions is not shown for it (#302)
    -- ``StringListEditor``'s Insert/Edit/Delete/Reset and Top/Up/Down/Bottom buttons are not this
    frame's captions, they are the same on every list editor.

    **Test steps:**

    * build a page whose one frame holds nothing but a `StringListEditor`
    * filter by one of the editor's button captions ("delete")
    * verify the frame is hidden
    """
    page = QWidget()
    qtbot.addWidget(page)
    layout = QVBoxLayout(page)
    frame = QFrame(page)
    frame_layout = QVBoxLayout(frame)
    frame_layout.addWidget(StringListEditor(frame))
    layout.addWidget(frame)
    frame_filter = SettingsFrameFilter(page, "Markdown Rendering")

    frame_filter.apply("delete", show_full_on_title_match=False)

    assert frame.isVisibleTo(page) is False


def test_a_list_editors_frame_still_matches_its_own_real_caption(qtbot: QtBot) -> None:
    """Excluding a list editor's button captions leaves the frame's own labels and group-box title
    still searchable (#302).

    **Test steps:**

    * build a page with a labeled frame that also holds a `StringListEditor`
    * filter by the frame's own label text
    * verify the frame is shown
    """
    page, (frame,) = make_page(qtbot, [["Excluded Patterns"]])
    frame_layout = frame.layout()
    assert frame_layout is not None
    frame_layout.addWidget(StringListEditor(frame))
    frame_filter = SettingsFrameFilter(page, "Markdown Rendering")

    frame_filter.apply("excluded", show_full_on_title_match=False)

    assert frame.isVisibleTo(page) is True


def test_field_labels_gathers_each_frames_caption_text(qtbot: QtBot) -> None:
    """``field_labels`` returns one gathered (lowercased) caption string per frame, for the tree filter.

    **Test steps:**

    * build a page with two frames of distinct labels
    * verify ``field_labels`` lists each frame's joined caption text, in frame order
    """
    page, _ = make_page(qtbot, [["Engine", "CSS"], ["Maximum image width"]])
    frame_filter = SettingsFrameFilter(page, "Markdown Rendering")

    assert frame_filter.field_labels() == ["engine css", "maximum image width"]


# region frame-level dirty tracking (#77)


def test_no_frame_is_dirty_right_after_construction(qtbot: QtBot) -> None:
    """A freshly-built filter's baseline is the widgets' own starting values, so nothing is dirty yet.

    **Test steps:**

    * build a two-frame page and its filter
    * verify neither frame is reported dirty
    """
    page, _frames, _edits = make_value_page(qtbot, 2)
    frame_filter = SettingsFrameFilter(page, "Markdown Rendering")

    assert frame_filter.dirty_frames() == []


def test_editing_a_line_edit_marks_its_own_frame_dirty(qtbot: QtBot) -> None:
    """Typing into a frame's `QLineEdit` makes that frame -- and only that frame -- dirty.

    **Test steps:**

    * build a two-frame page and its filter
    * edit the first frame's line edit
    * verify only the first frame is reported dirty
    """
    page, frames, edits = make_value_page(qtbot, 2)
    frame_filter = SettingsFrameFilter(page, "Markdown Rendering")

    edits[0].setText("changed")

    assert frame_filter.dirty_frames() == [frames[0]]


def test_reverting_a_value_to_its_baseline_clears_the_dirty_frame(qtbot: QtBot) -> None:
    """Dirty is judged against the live value, not "was this ever touched" -- typing back the
    original text clears it again.

    **Test steps:**

    * build a page, edit its line edit, then type the original text back
    * verify the frame is no longer reported dirty
    """
    page, _frames, edits = make_value_page(qtbot, 1)
    frame_filter = SettingsFrameFilter(page, "Markdown Rendering")
    edits[0].setText("changed")

    edits[0].setText("")

    assert frame_filter.dirty_frames() == []


def test_resync_baseline_clears_every_dirty_frame(qtbot: QtBot) -> None:
    """:meth:`SettingsFrameFilter.resync_baseline` adopts the current values as the new clean state.

    **Test steps:**

    * build a page, edit its line edit, then resync the baseline
    * verify the frame is no longer reported dirty
    """
    page, _frames, edits = make_value_page(qtbot, 1)
    frame_filter = SettingsFrameFilter(page, "Markdown Rendering")
    edits[0].setText("changed")
    assert frame_filter.dirty_frames() != []

    frame_filter.resync_baseline()

    assert frame_filter.dirty_frames() == []


def test_editing_after_resync_is_measured_against_the_new_baseline(qtbot: QtBot) -> None:
    """A resync's baseline is what the *next* edit is measured against, not the original values.

    **Test steps:**

    * edit a line edit, resync, then type the very first (pre-edit) text back
    * verify the frame is dirty again -- it now differs from the resynced baseline
    """
    page, frames, edits = make_value_page(qtbot, 1)
    frame_filter = SettingsFrameFilter(page, "Markdown Rendering")
    edits[0].setText("changed")
    frame_filter.resync_baseline()

    edits[0].setText("")

    assert frame_filter.dirty_frames() == [frames[0]]


def test_checking_a_checkbox_marks_its_frame_dirty(qtbot: QtBot) -> None:
    """A `QCheckBox` counts as a value widget, the same as a line edit.

    **Test steps:**

    * build a page whose one frame holds a checkbox
    * check it
    * verify the frame is reported dirty
    """
    page = QWidget()
    qtbot.addWidget(page)
    layout = QVBoxLayout(page)
    frame = QFrame(page)
    frame_layout = QVBoxLayout(frame)
    check_box = QCheckBox(frame)
    frame_layout.addWidget(check_box)
    layout.addWidget(frame)
    frame_filter = SettingsFrameFilter(page, "Markdown Rendering")

    check_box.setChecked(True)

    assert frame_filter.dirty_frames() == [frame]


def test_changing_a_combo_box_marks_its_frame_dirty(qtbot: QtBot) -> None:
    """A `QComboBox` counts as a value widget, the same as a line edit.

    **Test steps:**

    * build a page whose one frame holds a combo box
    * change its current index
    * verify the frame is reported dirty
    """
    page = QWidget()
    qtbot.addWidget(page)
    layout = QVBoxLayout(page)
    frame = QFrame(page)
    frame_layout = QVBoxLayout(frame)
    combo = QComboBox(frame)
    combo.addItems(["Firefox", "Chrome", "Edge"])
    frame_layout.addWidget(combo)
    layout.addWidget(frame)
    frame_filter = SettingsFrameFilter(page, "Markdown Rendering")

    combo.setCurrentIndex(1)

    assert frame_filter.dirty_frames() == [frame]


def test_restore_saved_puts_a_combo_boxs_baseline_index_back(qtbot: QtBot) -> None:
    """`restore_saved` writes a combo box's captured baseline index back, clearing the frame's dirty
    state (#342).

    **Test steps:**

    * build a page whose one frame holds a combo box, at its baseline index
    * change the index, then restore the saved baseline
    * verify the index is back and the frame is no longer dirty
    """
    page = QWidget()
    qtbot.addWidget(page)
    layout = QVBoxLayout(page)
    frame = QFrame(page)
    frame_layout = QVBoxLayout(frame)
    combo = QComboBox(frame)
    combo.addItems(["Firefox", "Chrome", "Edge"])
    frame_layout.addWidget(combo)
    layout.addWidget(frame)
    frame_filter = SettingsFrameFilter(page, "Markdown Rendering")
    combo.setCurrentIndex(2)

    frame_filter.restore_saved(frame)

    assert combo.currentIndex() == 0
    assert frame_filter.dirty_frames() == []


def test_changing_a_spin_box_marks_its_frame_dirty(qtbot: QtBot) -> None:
    """A `QSpinBox` counts as a value widget, the same as a line edit.

    **Test steps:**

    * build a page whose one frame holds a spin box
    * change its value
    * verify the frame is reported dirty
    """
    page = QWidget()
    qtbot.addWidget(page)
    layout = QVBoxLayout(page)
    frame = QFrame(page)
    frame_layout = QVBoxLayout(frame)
    spin_box = QSpinBox(frame)
    frame_layout.addWidget(spin_box)
    layout.addWidget(frame)
    frame_filter = SettingsFrameFilter(page, "Markdown Rendering")

    spin_box.setValue(spin_box.value() + 1)

    assert frame_filter.dirty_frames() == [frame]


def test_editing_a_plain_text_edit_marks_its_frame_dirty(qtbot: QtBot) -> None:
    """A `QPlainTextEdit` counts as a value widget, the same as a line edit.

    **Test steps:**

    * build a page whose one frame holds a plain text edit
    * type into it
    * verify the frame is reported dirty
    """
    page = QWidget()
    qtbot.addWidget(page)
    layout = QVBoxLayout(page)
    frame = QFrame(page)
    frame_layout = QVBoxLayout(frame)
    text_edit = QPlainTextEdit(frame)
    frame_layout.addWidget(text_edit)
    layout.addWidget(frame)
    frame_filter = SettingsFrameFilter(page, "Markdown Rendering")

    text_edit.setPlainText("changed")

    assert frame_filter.dirty_frames() == [frame]


def test_a_push_button_is_not_a_value_widget(qtbot: QtBot) -> None:
    """A non-checkable button holds nothing, so a frame with only one has no values to snapshot (#342).

    **Test steps:**

    * build a page whose one frame holds a plain push button beside a checkbox
    * verify the frame's snapshot counts the checkbox alone: it has values, and pressing the button
      (which flips nothing) leaves it clean, while a frame with only the button has no values
    """
    page = QWidget()
    qtbot.addWidget(page)
    layout = QVBoxLayout(page)
    mixed = QFrame(page)
    mixed_layout = QVBoxLayout(mixed)
    mixed_layout.addWidget(QPushButton("Browse...", mixed))
    mixed_layout.addWidget(QCheckBox(mixed))
    layout.addWidget(mixed)
    buttons_only = QFrame(page)
    QVBoxLayout(buttons_only).addWidget(QPushButton("Register", buttons_only))
    layout.addWidget(buttons_only)
    frame_filter = SettingsFrameFilter(page, "Markdown Rendering")

    assert frame_filter.has_values(mixed) is True
    assert frame_filter.has_values(buttons_only) is False
    assert frame_filter.dirty_frames() == []


def test_changing_a_string_list_editors_values_marks_its_frame_dirty(qtbot: QtBot) -> None:
    """A `StringListEditor` counts as one value widget, read through its own ``values`` property.

    **Test steps:**

    * build a page whose one frame holds a string list editor
    * change its values
    * verify the frame is reported dirty
    """
    page = QWidget()
    qtbot.addWidget(page)
    layout = QVBoxLayout(page)
    frame = QFrame(page)
    frame_layout = QVBoxLayout(frame)
    editor = StringListEditor(frame)
    frame_layout.addWidget(editor)
    layout.addWidget(frame)
    frame_filter = SettingsFrameFilter(page, "Markdown Rendering")

    editor.values = ["one", "two"]

    assert frame_filter.dirty_frames() == [frame]


def test_a_clean_frame_alongside_a_dirty_one_is_not_reported(qtbot: QtBot) -> None:
    """Only the frame that actually changed is dirty -- a sibling frame is left out (#77).

    **Test steps:**

    * build a two-frame page and edit only the second frame's line edit
    * verify ``dirty_frames`` names only the second frame
    """
    page, frames, edits = make_value_page(qtbot, 2)
    frame_filter = SettingsFrameFilter(page, "Markdown Rendering")

    edits[1].setText("changed")

    assert frame_filter.dirty_frames() == [frames[1]]


# endregion


# region defaults snapshot and restoring either snapshot (#342)


def make_single_frame_page(qtbot: QtBot, widget: QWidget) -> tuple[QWidget, QFrame]:
    """Build a page with one top-level frame holding ``widget`` alone.

    :param qtbot: the Qt test bot, to own the page.
    :param widget: the value widget to put in the frame; reparented to it.
    :returns: the page and its one frame.
    """
    page = QWidget()
    qtbot.addWidget(page)
    layout = QVBoxLayout(page)
    frame = QFrame(page)
    frame_layout = QVBoxLayout(frame)
    widget.setParent(frame)
    frame_layout.addWidget(widget)
    layout.addWidget(frame)
    return page, frame


def test_no_frame_is_at_its_defaults_before_they_are_captured(qtbot: QtBot) -> None:
    """Without a defaults snapshot there is nothing to be at, so no frame is reported.

    **Test steps:**

    * build a filter and never call ``capture_defaults``
    * verify ``frames_at_defaults`` is empty
    """
    page, _, _ = make_value_page(qtbot, 2)
    frame_filter = SettingsFrameFilter(page, "Markdown Rendering")

    assert frame_filter.frames_at_defaults() == []


def test_frames_at_defaults_follows_the_captured_defaults_snapshot(qtbot: QtBot) -> None:
    """A frame is at its defaults exactly while its widgets match what ``capture_defaults`` saw.

    **Test steps:**

    * type the factory text, capture defaults, type the saved text back, resync the baseline
    * verify the frame is clean but not at its defaults
    * type the factory text again: verify it is at its defaults, and dirty
    """
    page, frames, edits = make_value_page(qtbot, 1)
    frame_filter = SettingsFrameFilter(page, "Markdown Rendering")
    edits[0].setText("factory")
    frame_filter.capture_defaults()
    edits[0].setText("saved")
    frame_filter.resync_baseline()
    assert frame_filter.dirty_frames() == []
    assert frame_filter.frames_at_defaults() == []

    edits[0].setText("factory")

    assert frame_filter.dirty_frames() == [frames[0]]
    assert frame_filter.frames_at_defaults() == [frames[0]]


def test_has_values_is_false_for_a_frame_with_no_value_widget(qtbot: QtBot) -> None:
    """A frame with nothing snapshotted has nothing a Reset/Defaults pair could act on -- a scratch
    frame with an edit *does* have values (its own buttons need them), a label-only frame does not.

    **Test steps:**

    * build a page with a label-only frame, a scratch-flagged frame with an edit, and a plain one
    * verify the two frames with an edit have values and the label-only one does not
    """
    page, frames, _ = make_value_page(qtbot, 2)
    frames[0].setProperty(SCRATCH_PROPERTY, True)
    label_only = QFrame(page)
    QVBoxLayout(label_only).addWidget(QLabel("Note", label_only))
    page_layout = page.layout()
    assert page_layout is not None
    page_layout.addWidget(label_only)
    frame_filter = SettingsFrameFilter(page, "Markdown Rendering")

    assert frame_filter.has_values(frames[0]) is True
    assert frame_filter.is_scratch(frames[0]) is True
    assert frame_filter.has_values(frames[1]) is True
    assert frame_filter.is_scratch(frames[1]) is False
    assert frame_filter.has_values(label_only) is False


def test_a_scratch_frame_answers_its_own_state_but_never_the_pages(qtbot: QtBot) -> None:
    """A scratch frame's edit moves ``differs_from_saved``/``differs_from_defaults`` -- what its
    Reset/Defaults follow -- while ``dirty_frames``/``frames_at_defaults`` keep leaving it out.

    **Test steps:**

    * flag a frame scratch, capture defaults, type into its edit
    * verify the per-frame queries see the edit and the page-level lists do not
    """
    page, frames, edits = make_value_page(qtbot, 1)
    frames[0].setProperty(SCRATCH_PROPERTY, True)
    frame_filter = SettingsFrameFilter(page, "Markdown Rendering")
    frame_filter.capture_defaults()
    assert frame_filter.differs_from_defaults(frames[0]) is False

    edits[0].setText("typed")

    assert frame_filter.differs_from_saved(frames[0]) is True
    assert frame_filter.differs_from_defaults(frames[0]) is True
    assert frame_filter.dirty_frames() == []
    assert frame_filter.frames_at_defaults() == []


def test_list_editors_names_a_frames_list_editors_and_nothing_else(qtbot: QtBot) -> None:
    """The list editors among a frame's value widgets, for the dialog to hide their restore buttons.

    **Test steps:**

    * build a page with a list-editor frame and a line-edit frame
    * verify the former answers its editor and the latter nothing
    """
    editor = StringListEditor()
    page, list_frame = make_single_frame_page(qtbot, editor)
    edit_frame = QFrame(page)
    QVBoxLayout(edit_frame).addWidget(QLineEdit(edit_frame))
    page_layout = page.layout()
    assert page_layout is not None
    page_layout.addWidget(edit_frame)
    frame_filter = SettingsFrameFilter(page, "Markdown Rendering")

    assert frame_filter.list_editors(list_frame) == [editor]
    assert frame_filter.list_editors(edit_frame) == []


def test_apply_frame_saves_only_that_frames_edits_and_keeps_the_others_staged(qtbot: QtBot) -> None:
    """A one-frame commit parks the other frames at their saved values around the page's save, then
    hands their edits back -- so what was saved is one frame's change, and what is on screen is
    everything typed.

    **Test steps:**

    * edit both frames of a two-frame page
    * ``apply_frame`` the first, with a save that records what each edit showed at that moment
    * verify the save saw the first edit changed and the second at its baseline, both edits still show
      what was typed, and only the second frame is dirty
    """
    page, frames, edits = make_value_page(qtbot, 2)
    frame_filter = SettingsFrameFilter(page, "Markdown Rendering")
    edits[0].setText("first")
    edits[1].setText("second")
    seen: list[tuple[str, str]] = []

    frame_filter.apply_frame(frames[0], lambda: seen.append((edits[0].text(), edits[1].text())))

    assert seen == [("first", "")]
    assert (edits[0].text(), edits[1].text()) == ("first", "second")
    assert frame_filter.dirty_frames() == [frames[1]]


def test_apply_frame_leaves_a_scratch_frames_typed_values_alone(qtbot: QtBot) -> None:
    """A scratch frame is neither parked nor applied: its samples stay as typed through a sibling's
    commit, and are never handed to the save.

    **Test steps:**

    * type into a scratch frame and a plain frame, apply the plain one
    * verify the scratch edit showed its typed text during the save and still does
    """
    page, frames, edits = make_value_page(qtbot, 2)
    frames[0].setProperty(SCRATCH_PROPERTY, True)
    frame_filter = SettingsFrameFilter(page, "Markdown Rendering")
    edits[0].setText("sample")
    edits[1].setText("setting")
    seen: list[str] = []

    frame_filter.apply_frame(frames[1], lambda: seen.append(edits[0].text()))

    assert seen == ["sample"]
    assert edits[0].text() == "sample"
    assert frame_filter.dirty_frames() == []


def test_restore_saved_writes_the_baseline_back_into_a_line_edit(qtbot: QtBot) -> None:
    """Restoring the saved snapshot undoes a typed edit, and the frame reads clean again.

    **Test steps:**

    * type into a line edit, then ``restore_saved`` its frame
    * verify the edit shows the baseline text and the frame is not dirty
    """
    page, frames, edits = make_value_page(qtbot, 1)
    edits[0].setText("saved")
    frame_filter = SettingsFrameFilter(page, "Markdown Rendering")
    edits[0].setText("changed")

    frame_filter.restore_saved(frames[0])

    assert edits[0].text() == "saved"
    assert frame_filter.dirty_frames() == []


def test_restore_defaults_writes_the_defaults_snapshot_back(qtbot: QtBot) -> None:
    """Restoring the defaults snapshot puts the factory text on screen, which is a dirty edit.

    **Test steps:**

    * capture defaults with the factory text, resync the baseline with the saved text
    * ``restore_defaults`` the frame
    * verify the edit shows the factory text, the frame is dirty and at its defaults
    """
    page, frames, edits = make_value_page(qtbot, 1)
    frame_filter = SettingsFrameFilter(page, "Markdown Rendering")
    edits[0].setText("factory")
    frame_filter.capture_defaults()
    edits[0].setText("saved")
    frame_filter.resync_baseline()

    frame_filter.restore_defaults(frames[0])

    assert edits[0].text() == "factory"
    assert frame_filter.dirty_frames() == [frames[0]]
    assert frame_filter.frames_at_defaults() == [frames[0]]


def test_restore_writes_a_plain_text_edit_back(qtbot: QtBot) -> None:
    """A `QPlainTextEdit` is restored through ``setPlainText``.

    **Test steps:**

    * snapshot a plain text edit holding the saved text, retype it, restore
    * verify it shows the saved text
    """
    text_edit = QPlainTextEdit()
    text_edit.setPlainText("saved")
    page, frame = make_single_frame_page(qtbot, text_edit)
    frame_filter = SettingsFrameFilter(page, "Markdown Rendering")
    text_edit.setPlainText("changed")

    frame_filter.restore_saved(frame)

    assert text_edit.toPlainText() == "saved"


def test_restore_writes_a_spin_box_back(qtbot: QtBot) -> None:
    """A `QSpinBox` is restored through ``setValue``.

    **Test steps:**

    * snapshot a spin box at 3, change it, restore
    * verify it reads 3
    """
    spin_box = QSpinBox()
    spin_box.setValue(3)
    page, frame = make_single_frame_page(qtbot, spin_box)
    frame_filter = SettingsFrameFilter(page, "Markdown Rendering")
    spin_box.setValue(7)

    frame_filter.restore_saved(frame)

    assert spin_box.value() == 3


def test_restore_writes_a_checkbox_back(qtbot: QtBot) -> None:
    """A `QCheckBox` is restored through ``setChecked``.

    **Test steps:**

    * snapshot a checked box, uncheck it, restore
    * verify it is checked
    """
    check_box = QCheckBox()
    check_box.setChecked(True)
    page, frame = make_single_frame_page(qtbot, check_box)
    frame_filter = SettingsFrameFilter(page, "Markdown Rendering")
    check_box.setChecked(False)

    frame_filter.restore_saved(frame)

    assert check_box.isChecked() is True


def test_restore_writes_a_string_list_editors_rows_back_through_its_model(qtbot: QtBot) -> None:
    """A `StringListEditor` is restored row by row through its model, so an added, removed and
    retyped entry all come back as they were snapshotted.

    **Test steps:**

    * snapshot an editor holding two entries, replace them with three others, restore
    * verify the two original entries are back, in order, and the frame is clean
    """
    editor = StringListEditor()
    editor.values = ["one", "two"]
    page, frame = make_single_frame_page(qtbot, editor)
    frame_filter = SettingsFrameFilter(page, "Markdown Rendering")
    editor.values = ["three", "four", "five"]

    frame_filter.restore_saved(frame)

    assert editor.values == ("one", "two")
    assert frame_filter.dirty_frames() == []


def test_restore_refills_a_string_list_editor_that_was_emptied(qtbot: QtBot) -> None:
    """An editor with every row deleted gets its snapshot's rows back -- no rows to remove first.

    **Test steps:**

    * snapshot an editor holding one entry, delete it, restore
    * verify the entry is back
    """
    editor = StringListEditor()
    editor.values = ["one"]
    page, frame = make_single_frame_page(qtbot, editor)
    frame_filter = SettingsFrameFilter(page, "Markdown Rendering")
    editor.values = []

    frame_filter.restore_saved(frame)

    assert editor.values == ("one",)


def test_restore_empties_a_string_list_editor_whose_snapshot_was_empty(qtbot: QtBot) -> None:
    """A snapshot of no rows restores to no rows.

    **Test steps:**

    * snapshot an empty editor, add an entry, restore
    * verify the editor is empty again
    """
    editor = StringListEditor()
    page, frame = make_single_frame_page(qtbot, editor)
    frame_filter = SettingsFrameFilter(page, "Markdown Rendering")
    editor.values = ["one"]

    frame_filter.restore_saved(frame)

    assert not editor.values


def test_restore_puts_a_scratch_frames_samples_back(qtbot: QtBot) -> None:
    """A scratch frame is snapshotted like any other, so its Reset and Defaults have something to
    return to -- the try-it sample record as it was, or as shipped.

    **Test steps:**

    * capture defaults with the shipped sample, resync with a retyped one, type a third
    * restore saved, then defaults
    * verify each restore lands on its own reference value
    """
    page, frames, edits = make_value_page(qtbot, 1)
    frames[0].setProperty(SCRATCH_PROPERTY, True)
    frame_filter = SettingsFrameFilter(page, "Markdown Rendering")
    edits[0].setText("shipped")
    frame_filter.capture_defaults()
    edits[0].setText("retyped")
    frame_filter.resync_baseline()
    edits[0].setText("typed")

    frame_filter.restore_saved(frames[0])
    assert edits[0].text() == "retyped"
    frame_filter.restore_defaults(frames[0])
    assert edits[0].text() == "shipped"


# endregion
