"""Tests for LineEdit: the value-widget contract and the echo/cursor guard (#35)."""

from PySide6.QtWidgets import QLineEdit
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets.line_edit import LineEdit


def test_line_edit_is_a_line_edit(qtbot: QtBot) -> None:
    """A `LineEdit` is a ``QLineEdit`` so it drops into any place one is expected.

    **Test steps:**

    * build a `LineEdit`
    * verify it is a ``QLineEdit`` and starts empty
    """
    edit = LineEdit()
    qtbot.addWidget(edit)

    assert isinstance(edit, QLineEdit)
    assert edit.value == ""


def test_line_edit_emits_value_changed_on_user_edit(qtbot: QtBot) -> None:
    """Typing emits ``value_changed`` with the new text and updates ``value``.

    **Test steps:**

    * build a `LineEdit` and record ``value_changed`` emissions
    * set its text
    * verify ``value`` follows and the signal fired once with that text
    """
    edit = LineEdit()
    qtbot.addWidget(edit)
    seen: list[str] = []
    edit.value_changed.connect(seen.append)

    edit.setText("typed")

    assert edit.value == "typed"
    assert seen == ["typed"]


def test_line_edit_set_value_does_not_re_emit(qtbot: QtBot) -> None:
    """``set_value`` writes the value in without re-emitting ``value_changed`` (the echo guard).

    **Test steps:**

    * build a `LineEdit` and record ``value_changed`` emissions
    * call ``set_value``
    * verify the text updated but no ``value_changed`` fired
    """
    edit = LineEdit()
    qtbot.addWidget(edit)
    seen: list[str] = []
    edit.value_changed.connect(seen.append)

    edit.set_value("echoed")

    assert edit.value == "echoed"
    assert not seen


def test_line_edit_value_setter_writes_through_set_value(qtbot: QtBot) -> None:
    """Assigning ``value`` routes through ``set_value`` -- the same guarded write, no re-emit.

    **Test steps:**

    * build a `LineEdit` and record ``value_changed`` emissions
    * assign ``value``
    * verify the text updated and no signal fired
    """
    edit = LineEdit()
    qtbot.addWidget(edit)
    seen: list[str] = []
    edit.value_changed.connect(seen.append)

    edit.value = "assigned"

    assert edit.value == "assigned"
    assert not seen


def test_line_edit_set_value_preserves_cursor_on_identical_text(qtbot: QtBot) -> None:
    """Echoing identical text back through ``set_value`` doesn't teleport the cursor (#35).

    **Test steps:**

    * seed a `LineEdit` and place the cursor mid-string
    * call ``set_value`` with the value it already holds
    * verify the cursor stayed put (the text-equality guard skipped ``setText``)
    """
    edit = LineEdit()
    qtbot.addWidget(edit)
    edit.setText("hello world")
    edit.setCursorPosition(5)

    edit.set_value("hello world")

    assert edit.cursorPosition() == 5
