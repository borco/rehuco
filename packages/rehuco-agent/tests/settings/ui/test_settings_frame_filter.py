"""Tests for SettingsFrameFilter: showing/hiding a page's labeled frames by filter text.

The filter discovers a page's top-level QFrames and gathers their caption text by introspection, so
these tests build a real little page (a QFrame per group, each holding QLabels) and assert against
it. Visibility is checked with ``isVisibleTo(page)`` -- which reflects each frame's own show/hide
state without the page having to be realized on screen.
"""

from borco_pyside.widgets import StringListEditor
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from pytestqt.qtbot import QtBot
from rehuco_agent.settings.ui.settings_frame_filter import SettingsFrameFilter


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
