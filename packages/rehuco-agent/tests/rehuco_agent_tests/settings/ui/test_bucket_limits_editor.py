"""Tests for BucketLimitsEditor: the two bucket limits, as the Files page and the balance dialog edit them (#681)."""

from PySide6.QtWidgets import QLabel, QSpinBox
from pytest import fixture, mark, param
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.colors import WARNING_COLOR
from rehuco_agent.settings.ui.bucket_limits_editor import BucketLimitsEditor
from rehuco_core import MAX_SPLIT_LIMIT, MIN_SPLIT_LIMIT, max_join_limit


@fixture(name="editor")
def fixture_editor(qtbot: QtBot) -> BucketLimitsEditor:
    """An editor showing 200 and 100.

    :param qtbot: pytest-qt fixture.
    :returns: the editor, shown.
    """
    editor = BucketLimitsEditor()
    qtbot.addWidget(editor)
    editor.limits = (200, 100)
    editor.show()
    return editor


def box(editor: BucketLimitsEditor, name: str) -> QSpinBox:
    """One of the editor's boxes.

    :param editor: the editor.
    :param name: the box's object name.
    :returns: the box.
    """
    found = editor.findChild(QSpinBox, name)
    assert isinstance(found, QSpinBox)
    return found


def warning(editor: BucketLimitsEditor) -> QLabel:
    """The editor's warning.

    :param editor: the editor.
    :returns: its label.
    """
    found = editor.findChild(QLabel, "warning_label")
    assert isinstance(found, QLabel)
    return found


def test_the_boxes_take_what_core_says(editor: BucketLimitsEditor) -> None:
    """The bounds are core's, so neither surface repeats a number.

    **Test steps:**

    * read both boxes' ranges
    * verify them, and the limits shown
    """
    split, join = box(editor, "split_limit_spin_box"), box(editor, "join_limit_spin_box")

    assert (split.minimum(), split.maximum()) == (MIN_SPLIT_LIMIT, MAX_SPLIT_LIMIT)
    assert (join.minimum(), join.maximum()) == (0, max_join_limit(MAX_SPLIT_LIMIT))
    assert editor.limits == (200, 100)


@mark.parametrize(
    "limits, text",
    [
        param((200, 100), None, id="at-half"),
        param((200, 101), "101 is more than half the split limit, so 100 is used.", id="over-half"),
        param((201, 101), "101 is more than half the split limit, so 100 is used.", id="over-an-odd-half"),
        param((50, 0), None, id="never-joined"),
    ],
)
def test_a_join_limit_over_half_the_split_is_told_to_be_ignored(
    editor: BucketLimitsEditor, limits: tuple[int, int], text: str | None
) -> None:
    """The value stays as entered, with the one used instead under it.

    **Test steps:**

    * show limits
    * verify the warning and its color, or none, and the limits as entered
    """
    editor.limits = limits

    assert editor.limits == limits
    assert warning(editor).isVisible() is (text is not None)
    if text is not None:
        assert warning(editor).text() == text
        assert WARNING_COLOR in warning(editor).styleSheet()


def test_typing_a_number_through_a_smaller_one_loses_nothing(editor: BucketLimitsEditor, qtbot: QtBot) -> None:
    """Typing 500 passes through 50, whose half is under the join limit: the warning shows for that moment and the join
    limit is as it was.

    **Test steps:**

    * type 500 over the split limit, digit by digit
    * verify the warning at 50, none at 500, and the join limit throughout
    """
    split = box(editor, "split_limit_spin_box")
    split.selectAll()
    shown: list[tuple[tuple[int, int], bool]] = []

    for digit in "500":
        qtbot.keyClicks(split, digit)
        shown.append((editor.limits, warning(editor).isVisible()))

    assert shown == [((200, 100), False), ((50, 100), True), ((500, 100), False)]


def test_lowering_the_join_limit_takes_the_warning_away(editor: BucketLimitsEditor) -> None:
    """Either box clears it.

    **Test steps:**

    * raise the join limit over half, then lower it
    * verify the warning came and went
    """
    join = box(editor, "join_limit_spin_box")

    join.setValue(150)
    assert warning(editor).isVisible()
    join.setValue(90)
    assert not warning(editor).isVisible()
