"""Tests for WrappingCheckBox: a checkbox with a word-wrapping caption label that toggles it.

The composite exposes the checkbox's state through snake_case accessors and re-emits ``toggled``;
what it adds over a bare ``QCheckBox`` is the wrapping caption and clicking that caption toggling
the box, so those are what these tests exercise.
"""

from borco_pyside.widgets import WrappingCheckBox
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QLabel
from pytestqt.qtbot import QtBot


def find_label(widget: WrappingCheckBox) -> QLabel:
    """The composite's caption label (its only child ``QLabel``)."""
    label = widget.findChild(QLabel)
    assert label is not None
    return label


def find_check_box(widget: WrappingCheckBox) -> QCheckBox:
    """The composite's inner checkbox (its only child ``QCheckBox``)."""
    check_box = widget.findChild(QCheckBox)
    assert check_box is not None
    return check_box


# region state accessors
def test_starts_unchecked(qtbot: QtBot) -> None:
    """A freshly built checkbox is unchecked.

    **Test steps:**

    * build a WrappingCheckBox
    * verify ``is_checked()`` is ``False``
    """
    widget = WrappingCheckBox()
    qtbot.addWidget(widget)

    assert widget.is_checked() is False


def test_set_checked_updates_state_and_emits_toggled(qtbot: QtBot) -> None:
    """Setting the checked state updates ``is_checked()`` and fires ``toggled`` with the new value.

    **Test steps:**

    * record ``toggled`` emissions, then check the box
    * verify the state flipped and ``toggled`` reported ``True`` once
    """
    widget = WrappingCheckBox()
    qtbot.addWidget(widget)
    emitted: list[bool] = []
    widget.toggled.connect(emitted.append)

    widget.set_checked(True)

    assert widget.is_checked() is True
    assert emitted == [True]


# endregion


# region caption label
def test_caption_label_wraps(qtbot: QtBot) -> None:
    """The caption label word-wraps, so a long caption grows taller rather than forcing width.

    **Test steps:**

    * build a WrappingCheckBox
    * verify its caption label has word wrap enabled
    """
    widget = WrappingCheckBox()
    qtbot.addWidget(widget)

    assert find_label(widget).wordWrap() is True


def test_set_text_updates_the_caption(qtbot: QtBot) -> None:
    """``set_text`` changes the caption shown on the label.

    **Test steps:**

    * set new caption text
    * verify ``text()`` and the label both report it
    """
    widget = WrappingCheckBox()
    qtbot.addWidget(widget)

    widget.set_text("updated")

    assert widget.text() == "updated"
    assert find_label(widget).text() == "updated"


# endregion


# region clicking the caption toggles the box
def test_clicking_the_caption_toggles_the_checkbox(qtbot: QtBot) -> None:
    """Clicking the caption label toggles the checkbox, as if the box itself were clicked.

    **Test steps:**

    * click the caption label of an unchecked box
    * verify it becomes checked
    """
    widget = WrappingCheckBox()
    widget.set_text("Click my caption")
    qtbot.addWidget(widget)

    qtbot.mouseClick(find_label(widget), Qt.MouseButton.LeftButton)

    assert widget.is_checked() is True


def test_clicking_the_caption_of_a_disabled_checkbox_does_nothing(qtbot: QtBot) -> None:
    """When disabled, clicking the caption leaves the checkbox untouched.

    **Test steps:**

    * disable the widget, then click its caption label
    * verify it stays unchecked
    """
    widget = WrappingCheckBox()
    widget.set_text("Click my caption")
    qtbot.addWidget(widget)
    widget.setEnabled(False)

    qtbot.mouseClick(find_label(widget), Qt.MouseButton.LeftButton)

    assert widget.is_checked() is False


# endregion
