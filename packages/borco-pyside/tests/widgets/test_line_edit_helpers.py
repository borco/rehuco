"""Tests for line_edit_helpers: a QLineEdit kept in sync with a typed value via parse/format hooks."""

from borco_pyside.widgets.line_edit_helpers import parsed_value_or_reset, resync_line_edit
from PySide6.QtWidgets import QLineEdit
from pytestqt.qtbot import QtBot


def int_parse(text: str) -> int | None:
    """A trivial ``parse`` hook for these tests: a bare non-negative integer, or ``None``.

    :param text: the text to parse.
    :returns: the parsed integer, or ``None`` if not a bare non-negative integer.
    """
    return int(text) if text.isdigit() else None


# region resync_line_edit tests
def test_resync_line_edit_is_a_no_op_when_text_already_parses_to_value(qtbot: QtBot) -> None:
    """No resync happens when the line edit's current text already parses to ``value``.

    **Test steps:**

    * set text that parses to ``value``
    * call ``resync_line_edit`` with that same ``value``
    * verify the text is unchanged (still exactly as typed, not reformatted)
    """
    line_edit = QLineEdit()
    qtbot.addWidget(line_edit)
    line_edit.setText("007")

    resync_line_edit(line_edit, 7, int_parse, str)

    assert line_edit.text() == "007"


def test_resync_line_edit_overwrites_text_when_it_does_not_match_value(qtbot: QtBot) -> None:
    """The line edit's text is overwritten with the formatted value when it doesn't already match.

    **Test steps:**

    * call ``resync_line_edit`` on an empty line edit
    * verify the text is set to the formatted value
    """
    line_edit = QLineEdit()
    qtbot.addWidget(line_edit)

    resync_line_edit(line_edit, 7, int_parse, str)

    assert line_edit.text() == "7"


def test_resync_line_edit_does_not_re_emit_text_changed(qtbot: QtBot) -> None:
    """Overwriting the text is done under a signal blocker -- ``textChanged`` does not fire.

    **Test steps:**

    * connect to ``textChanged``
    * call ``resync_line_edit`` on a line edit whose text doesn't match
    * verify no signal was received
    """
    line_edit = QLineEdit()
    qtbot.addWidget(line_edit)
    received: list[str] = []
    line_edit.textChanged.connect(received.append)

    resync_line_edit(line_edit, 7, int_parse, str)

    assert not received


# endregion


# region parsed_value_or_reset tests
def test_parsed_value_or_reset_returns_reset_for_blank_text() -> None:
    """Blank text resolves to ``reset``, not ``None`` -- an explicit reset, not "incomplete typing".

    **Test steps:**

    * call ``parsed_value_or_reset`` with whitespace-only text
    * verify it returns ``reset``
    """
    assert parsed_value_or_reset("   ", 0, int_parse) == 0


def test_parsed_value_or_reset_returns_the_parsed_value_for_valid_text() -> None:
    """Non-blank, parseable text resolves to its parsed value.

    **Test steps:**

    * call ``parsed_value_or_reset`` with text that parses
    * verify it returns the parsed value
    """
    assert parsed_value_or_reset("42", 0, int_parse) == 42


def test_parsed_value_or_reset_returns_none_for_unparseable_text() -> None:
    """Non-blank, unparseable text resolves to ``None`` -- leave the current value untouched.

    **Test steps:**

    * call ``parsed_value_or_reset`` with garbage text
    * verify it returns ``None``
    """
    assert parsed_value_or_reset("not a number", 0, int_parse) is None


# endregion
