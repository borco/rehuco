"""Tests for line_edit_helpers: a QLineEdit kept in sync with a typed value via parse/format hooks."""

from borco_pyside.widgets.line_edit_helpers import resync_line_edit
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
