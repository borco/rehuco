"""Tests for the widgets an asset's fields are edited in (#678): an editable combo of known texts, a size in bytes, a
map of text to text, and a date edit that keeps a UTC time."""

from datetime import UTC, timedelta, timezone

from PySide6.QtWidgets import QLineEdit
from pytest import mark, param
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.local_time import local_time_text
from rehuco_agent.fields.widgets import DateEdit, EditableChoiceComboBox, SizeEdit, StringMapValueEditor

# region EditableChoiceComboBox


def test_an_editable_combo_offers_its_choices_blank_and_reports_a_pick_or_typed_text(qtbot: QtBot) -> None:
    """The combo starts with no text, whatever it offers; a pick and typed text are both its value, reported.

    **Test steps:**

    * build a combo of two choices and verify it is blank
    * pick the second, then type another text
    * verify each is the value and was reported
    """
    combo = EditableChoiceComboBox(["fab-standard", "cc-by-4.0"])
    qtbot.addWidget(combo)
    assert combo.value == ""
    reported: list[str] = []
    combo.value_changed.connect(reported.append)

    combo.setCurrentIndex(1)
    combo.setEditText("daz")

    assert combo.value == "daz"
    assert reported[0] == "cc-by-4.0"
    assert reported[-1] == "daz"


def test_an_editable_combo_takes_a_value_set_without_reporting_it(qtbot: QtBot) -> None:
    """:meth:`set_value` shows a text, offered or not, and says nothing, so an echo never loops; the value setter is
    the same call.

    **Test steps:**

    * build a combo and set an offered text, then one it does not offer, then the same one again
    * verify the line shows each and nothing was reported
    * set the value through the property and verify it shows
    """
    combo = EditableChoiceComboBox(["a", "b"])
    qtbot.addWidget(combo)
    reported: list[str] = []
    combo.value_changed.connect(reported.append)

    combo.set_value("b")
    assert combo.currentText() == "b"
    combo.set_value("elsewhere")
    combo.set_value("elsewhere")
    assert combo.currentText() == "elsewhere"
    combo.value = "a"

    assert combo.currentText() == "a"
    assert not reported


# endregion

# region SizeEdit


def test_a_size_edit_reads_the_bytes_both_ways_and_says_unknown_for_none(qtbot: QtBot) -> None:
    """The readout words the bytes beside the spin box; a size set from outside shows in both, and none is blank.

    **Test steps:**

    * build a size edit and verify it holds none
    * set 2048 and verify the readout
    * clear it and verify the readout is blank again
    """
    edit = SizeEdit()
    qtbot.addWidget(edit)
    readout = edit.layout().itemAt(0).widget()  # type: ignore[union-attr]  # the readout is its first cell
    assert edit.value is None

    edit.set_value(2048)  # type: ignore[attr-defined]  # the property's synthesized slot
    assert readout.text() == "2.0K"  # type: ignore[attr-defined]
    edit.set_value(None)  # type: ignore[attr-defined]  # the property's synthesized slot

    assert readout.text() == ""  # type: ignore[attr-defined]


def test_a_size_edit_reports_what_is_typed(qtbot: QtBot) -> None:
    """Typing bytes into the spin box is the edit's value and is reported.

    **Test steps:**

    * build a size edit and type digits into its spin box
    * verify the value and the report
    """
    edit = SizeEdit()
    qtbot.addWidget(edit)
    reported: list[object] = []
    edit.value_changed.connect(reported.append)  # type: ignore[attr-defined]
    spin_box = edit.layout().itemAt(1).widget()  # type: ignore[union-attr]  # the spin box is its second cell

    spin_box.lineEdit().setText("4096")  # type: ignore[attr-defined]

    assert edit.value == 4096
    assert reported[-1] == 4096


# endregion

# region StringMapValueEditor


def test_a_map_editor_reports_an_edit_once_and_not_a_seed(qtbot: QtBot) -> None:
    """Seeding the rows reports nothing; a cell edit reports the map the rows make; a map already shown is left alone.

    **Test steps:**

    * build a map editor, seed a map and verify nothing was reported
    * edit a value and verify the report carries the new map
    * set the map the rows already make and verify the rows were not replaced
    """
    editor = StringMapValueEditor()
    qtbot.addWidget(editor)
    reported: list[object] = []
    editor.value_changed.connect(reported.append)

    editor.set_value({"unreal": "5.1"})
    assert not reported
    assert editor.value == {"unreal": "5.1"}

    editor.model.setData(editor.model.index(0, 1), "5.2")
    assert reported[-1] == {"unreal": "5.2"}

    editor.model.insert(-1)  # type: ignore[attr-defined]  # the string map model
    editor.set_value({"unreal": "5.2"})
    assert editor.model.rowCount() == 2
    assert editor.header_height > 0


# endregion

# region DateEdit with a time


@mark.parametrize(
    ("text", "expected"),
    [
        param("2024-05-03T12:34:56.789123Z", "2024-05-03T12:34:56.789123Z", id="a whole time"),
        param(" 2024-05-03T12:34:56Z ", "2024-05-03T12:34:56.000000Z", id="no fraction, spaces around"),
        param("2024-05-03T12:34:56.5Z", "2024-05-03T12:34:56.500000Z", id="a short fraction is padded"),
        param("2024-05-03T25:00:00Z", None, id="an hour that does not exist"),
        param("2024-02-30T12:00:00Z", None, id="a day that does not exist"),
        param("2024-05-03T12:34:56", None, id="no Z"),
        param("2024-05-03T12:34:56+02:00", None, id="a local offset"),
        param("2024-05-03", None, id="a date"),
        param("", None, id="nothing"),
    ],
)
def test_a_utc_time_is_read_to_six_fractional_digits(text: str, expected: str | None) -> None:
    """Only a whole real UTC time reads as one, its fraction written out to the microsecond.

    **Test steps:**

    * read the text as a UTC time
    * verify the canonical time, or ``None``

    :param text: the text.
    :param expected: what it reads as.
    """
    assert DateEdit.parse_time(text) == expected


def line_edit(edit: DateEdit) -> QLineEdit:
    """The edit's internal line.

    :param edit: the widget.
    :returns: its ``QLineEdit``.
    """
    return edit._DateEdit__line_edit  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def test_a_date_edit_that_keeps_a_time_is_not_cut_to_its_date(qtbot: QtBot) -> None:
    """A time already stored stays through typing inside it; text with a ``T`` or a ``:`` that is not yet a time writes
    nothing, and text with neither is a date as it ever was.

    **Test steps:**

    * build an edit keeping a time and seed a UTC time
    * type text that is part of a time and verify the value did not change
    * type a whole time and verify it is the value, to the microsecond
    * type a date and verify it is the value
    """
    edit = DateEdit(with_time=True)
    qtbot.addWidget(edit)
    edit.set_value("2024-05-03T12:34:56.789123Z")  # type: ignore[attr-defined]  # the property's synthesized slot
    assert line_edit(edit).text() == "2024-05-03T12:34:56.789123Z"

    line_edit(edit).setText("2024-05-03T12:34")
    assert edit.value == "2024-05-03T12:34:56.789123Z"

    line_edit(edit).setText("2024-05-03T12:34:56.5Z")
    assert edit.value == "2024-05-03T12:34:56.500000Z"

    line_edit(edit).setText("2024-05-03")
    assert edit.value == "2024-05-03"


def test_a_date_edit_that_keeps_no_time_reads_a_time_as_a_date_as_ever(qtbot: QtBot) -> None:
    """Without the option nothing changes: text with a time in it is read as a date.

    **Test steps:**

    * build a plain edit and type a whole UTC time
    * verify its date is the value
    """
    edit = DateEdit()
    qtbot.addWidget(edit)

    line_edit(edit).setText("2024-05-03T12:34:56.789123Z")

    assert edit.value == "2024-05-03"


# endregion

# region local_time_text


def test_a_utc_timestamp_is_worded_in_the_zone_asked_for() -> None:
    """A timestamp with a zone is shown in the given zone; a date, text that is no timestamp and an empty one are not
    timestamps.

    **Test steps:**

    * word a UTC timestamp in a zone two hours ahead
    * verify the local text, and ``None`` for a date, for words and for nothing
    """
    plus_two = timezone(timedelta(hours=2))

    assert local_time_text("2026-11-08T15:32:54Z", plus_two) == "2026-11-08 17:32:54"
    assert local_time_text("2026-11-08T15:32:54.123456Z", UTC) == "2026-11-08 15:32:54"
    assert local_time_text("2026-11-08") is None
    assert local_time_text("now") is None
    assert local_time_text("") is None


# endregion
